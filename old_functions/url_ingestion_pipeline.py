import json
import asyncio
import aiohttp
from aiohttp import ClientSession
import xml.etree.ElementTree as ET
import os
import re
import gzip
from typing import List, Dict, Optional
from datetime import datetime
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models
from openai import OpenAI
import glob
import logging
import uuid
import gc
import boto3
from botocore.exceptions import ClientError
from dataclasses import dataclass
from dateutil.parser import parse as parse_date
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv
import sys
from tenacity import retry, stop_after_attempt, wait_exponential
from prometheus_client import Counter, Histogram, start_http_server
from external_urls import sitemap_urls
from playwright.async_api import async_playwright
from URLS import URLs_conseil_etat

# Fonction pour extraire les URLs des fichiers Sitemap
def get_existing_urls_from_qdrant() -> set:
    """Récupère toutes les URLs uniques depuis la collection Qdrant potential_questions."""
    collection_name = "potential_questions"
    existing_urls = set()
    
    try:
        offset = None
        while True:
            # Récupère les points par lots avec scroll
            points, next_offset = qdrant_client.scroll(
                collection_name=collection_name,
                limit=100,  # Taille du lot
                with_payload=True,
                offset=offset
            )
            
            # Extrait les URLs du payload
            for point in points:
                url = point.payload.get('url', '')
                if url and is_valid_url(url):
                    existing_urls.add(normalize_url(url))
            
            # Si pas de prochain offset, fin de la collection
            if next_offset is None:
                break
            offset = next_offset
        
        logger.info(f"Total URLs uniques extraites de Qdrant: {len(existing_urls)}")
        return existing_urls
    
    except Exception as e:
        logger.error(f"Erreur générale récupération URLs Qdrant: {str(e)}")
        return set()


# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('crawler.log')  # Journalisation structurée
    ]
)
logger = logging.getLogger(__name__)

# Fichier pour enregistrer les URLs inaccessibles
INACCESSIBLE_LOG = 'inaccessible_urls.log'

# Métriques Prometheus
scrape_duration = Histogram("scrape_duration_seconds", "Temps de scraping par URL")
urls_processed = Counter("urls_processed_total", "Nombre total d'URLs traitées")

# Chargement des variables d'environnement
load_dotenv()

# Script JS par défaut
DEFAULT_JS_SCRIPT = """
function clearHeaderFooterAndSidebars() {
    ["header", "footer", "aside", ".sidebar", ".nav", ".menu"].forEach(function(selector) {
        document.querySelectorAll(selector).forEach(function(el) {
            el.innerHTML = "";
            el.style.cssText = "display: none; visibility: hidden;";
        });
    });
}

function disableScripts() {
    document.querySelectorAll("script").forEach(function(script) {
        script.remove();
    });
}

function expandAllMenus() {
    var selectors = [
        ".fr-collapse__btn", ".accordion-toggle", ".menu-toggle",
        "button[aria-expanded='false']", "a[aria-expanded='false']",
        "div[aria-hidden='true']"
    ];

    selectors.forEach(function(selector) {
        document.querySelectorAll(selector).forEach(function(el) {
            if (el.click) el.click();
        });
    });
    return new Promise(function(resolve) {
        requestAnimationFrame(resolve);
    });
}

function forceRenderHiddenContent() {
    document.querySelectorAll("[aria-hidden='true']").forEach(function(el) {
        el.setAttribute("aria-hidden", "false");
        el.style.cssText = "display: block; visibility: visible; opacity: 1;";
    });
}

function scrollToBottom() {
    var scrollHeight = document.body.scrollHeight;
    window.scrollTo(0, scrollHeight);
    return new Promise(function(resolve) {
        setTimeout(resolve, 500);
    });
}

try {
    disableScripts();
    clearHeaderFooterAndSidebars();
    expandAllMenus().then(function() {
        forceRenderHiddenContent();
        return scrollToBottom();
    }).catch(function(error) {
        console.error("Erreur JS:", error);
    });
} catch (error) {
    console.error("Erreur JS:", error);
}
"""

@dataclass
class Config:
    """Configuration centrale pour le crawler."""
    output_dir: str = os.getenv('OUTPUT_DIR', 'scraped_articles')
    qdrant_url: str = os.getenv('QDRANT_URL', '')
    qdrant_api_key: str = os.getenv('QDRANT_API_KEY', '')
    qdrant_cluster: str = os.getenv('QDRANT_CLUSTER', 'default')
    nebius_api_url: str = os.getenv('NEBIUS_API_URL', '')
    nebius_api_key: str = os.getenv('NEBIUS_API_KEY', '')
    s3_bucket_name: str = os.getenv('S3_BUCKET_NAME', '')
    aws_region: str = os.getenv('AWS_REGION', 'us-east-1')
    aws_access_key_id: str = os.getenv('AWS_ACCESS_KEY_ID', '')
    aws_secret_access_key: str = os.getenv('AWS_SECRET_ACCESS_KEY', '')
    vector_dimension: int = 384
    timeout: int = 30
    max_retries: int = 3

    def validate(self) -> bool:
        """Valide les variables d'environnement requises."""
        required = [
            self.qdrant_url, self.qdrant_api_key, self.nebius_api_url,
            self.nebius_api_key, self.s3_bucket_name, self.aws_access_key_id,
            self.aws_secret_access_key
        ]
        if not all(required):
            logger.error("Variables d'environnement manquantes. Vérifiez votre fichier .env")
            return False
        return True

# Initialisation de la configuration
CONFIG = Config()
if not CONFIG.validate():
    sys.exit(1)

# Initialisation des clients
s3_client = boto3.client(
    's3',
    region_name=CONFIG.aws_region,
    aws_access_key_id=CONFIG.aws_access_key_id,
    aws_secret_access_key=CONFIG.aws_secret_access_key
)
qdrant_client = QdrantClient(url=CONFIG.qdrant_url, api_key=CONFIG.qdrant_api_key, timeout=10)
sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
client_nebius = OpenAI(base_url=CONFIG.nebius_api_url, api_key=CONFIG.nebius_api_key)

def log_inaccessible_url(url: str, reason: str):
    """Enregistre une URL inaccessible dans un fichier de log."""
    try:
        with open(INACCESSIBLE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()} - {url} - {reason}\n")
    except Exception as e:
        logger.error(f"Erreur écriture dans {INACCESSIBLE_LOG}: {str(e)}")

def extract_json_from_response(response_text: str) -> Dict:
    """Extrait le premier bloc JSON valide d'une réponse texte."""
    try:
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
            logger.warning("Aucun JSON valide trouvé dans la réponse")
            return {
                "cour de cassation": [],
                "code civil": [],
                "code du travail": []
            }
        json_str = response_text[start_idx:end_idx+1]
        parsed_json = json.loads(json_str)
        if not isinstance(parsed_json, dict) or not all(
            key in parsed_json for key in ["cour de cassation", "code civil", "code du travail"]
        ):
            logger.warning("JSON mal formé ou clés manquantes")
            return {
                "cour de cassation": [],
                "code civil": [],
                "code du travail": []
            }
        return parsed_json
    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON: {str(e)}")
        return {
            "cour de cassation": [],
            "code civil": [],
            "code du travail": []
        }

def normalize_url(url: str) -> str:
    """Normalise une URL pour ignorer les variations mineures."""
    try:
        parsed = urlparse(url)
        return urlunparse((
            'https' if parsed.scheme == 'http' else parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/'),
            parsed.params,
            parsed.query,
            ''
        ))
    except Exception as e:
        logger.error(f"Erreur normalisation URL {url}: {str(e)}")
        return url

def is_valid_url(url: str) -> bool:
    """Vérifie si une URL est valide."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False

async def check_url_status(session: aiohttp.ClientSession, url: str) -> bool:
    """Vérifie si une URL est accessible (code 200)."""
    try:
        async with session.head(url, timeout=5) as response:
            if response.status == 200:
                return True
            else:
                log_inaccessible_url(url, f"Code HTTP {response.status}")
                logger.warning(f"URL non accessible: {url} (Code HTTP {response.status})")
                return False
    except asyncio.TimeoutError:
        log_inaccessible_url(url, "Timeout")
        logger.warning(f"URL non accessible: {url} (Timeout)")
        return False
    except Exception as e:
        log_inaccessible_url(url, f"Erreur: {str(e)}")
        logger.warning(f"URL non accessible: {url} (Erreur: {str(e)})")
        return False

def does_make_sense(text: str) -> bool:
    """Vérifie si le texte a du sens."""
    if not text or len(text.strip()) < 20:
        return False
    try:
        words = text.lower().split()
        if len(words) < 10:
            return False
        unique_words = set(words)
        return len(unique_words) / len(words) > 0.3
    except Exception as e:
        logger.error(f"Erreur dans does_make_sense: {str(e)}")
        return False

async def scrape_article(url: str, crawler: AsyncWebCrawler, session: aiohttp.ClientSession, js_script: str = DEFAULT_JS_SCRIPT) -> Optional[Dict]:
    """Scrape un article avec retries et gestion améliorée des ressources."""
    if not await check_url_status(session, url):
        log_inaccessible_url(url, "URL inaccessible")
        return None

    for attempt in range(CONFIG.max_retries):
        try:
            logger.info(f"Tentative {attempt + 1}/{CONFIG.max_retries} de scraping: {url}")
            
            # Configuration minimale du crawler sans arguments de navigateur
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                js_code=[js_script],
                wait_until='networkidle'
            )

            try:
                result = await crawler.arun(url=url, config=run_config)
                
                if not result or not result.html:
                    raise ValueError("Résultat vide")
                
                soup = BeautifulSoup(result.html, "lxml")
                structured_content = parse_html_content(soup)
                text_content = soup.get_text(separator=" ", strip=True)
                date = extract_date(text_content)
                
                urls_processed.inc()
                return {
                    "url": url,
                    "title": result.metadata.get("title", "page_sans_titre"),
                    "content": structured_content,
                    "date": date,
                    "attempt": attempt + 1
                }
                
            except Exception as e:
                logger.error(f"Erreur lors du scraping de {url} (tentative {attempt + 1}): {str(e)}")
                if attempt < CONFIG.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                
        except Exception as e:
            logger.error(f"Erreur générale pour {url}: {str(e)}")
            if attempt < CONFIG.max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            log_inaccessible_url(url, f"Erreur scraping: {str(e)}")

    return None

def parse_html_content(soup: BeautifulSoup, title_tags: List[str] = ["h1", "h2", "h3", "h4", "h5"], content_tags: List[str] = ["p"]) -> List[Dict[str, str]]:
    """Parse le HTML pour extraire titres et paragraphes avec balises configurables."""
    try:
        structured_content = []
        current_title = None
        current_paragraphs = []
        for element in soup.find_all(title_tags + content_tags):
            if element.name in title_tags and element.get_text(strip=True):
                if current_title and current_paragraphs:
                    structured_content.append({
                        "titre_paragraphe": current_title,
                        "contenu_paragraphe": "\n".join(current_paragraphs)
                    })
                    current_paragraphs = []
                current_title = element.get_text(strip=True)
            elif element.name in content_tags and current_title:
                text = element.get_text(strip=True)
                if text and does_make_sense(text):
                    current_paragraphs.append(text)
        if current_title and current_paragraphs:
            structured_content.append({
                "titre_paragraphe": current_title,
                "contenu_paragraphe": "\n".join(current_paragraphs)
            })
        return structured_content
    except Exception as e:
        logger.error(f"Erreur parsing HTML: {str(e)}")
        return []

def extract_date(text: str) -> str:
    """Extrait la première date trouvée dans le texte."""
    try:
        # Patterns de dates courantes en français
        date_patterns = [
            r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b',  # 01/01/2024, 1-1-2024
            r'\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b',  # 2024/01/01, 2024-1-1
            r'\b(\d{1,2})\s*(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s*(\d{4})\b',  # 1 janvier 2024
            r'\b(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s*(\d{1,2})\s*,?\s*(\d{4})\b',  # janvier 1, 2024
            r'\b(\d{4})\b'  # Juste l'année
        ]

        # Mapping des mois en français
        mois_mapping = {
            'janvier': '01', 'février': '02', 'mars': '03', 'avril': '04',
            'mai': '05', 'juin': '06', 'juillet': '07', 'août': '08',
            'septembre': '09', 'octobre': '10', 'novembre': '11', 'décembre': '12'
        }

        # Recherche des patterns dans le texte
        for pattern in date_patterns:
            matches = re.finditer(pattern, text.lower())
            for match in matches:
                groups = match.groups()
                
                # Pattern avec juste l'année
                if len(groups) == 1:
                    year = int(groups[0])
                    if 1900 <= year <= 2100:
                        return f"{year}-01-01"  # Retourne immédiatement la première année valide
                
                # Patterns avec jour/mois/année
                elif len(groups) == 3:
                    try:
                        if groups[1] in mois_mapping:  # Format texte pour le mois
                            jour = groups[0].zfill(2)
                            mois = mois_mapping[groups[1]]
                            annee = groups[2]
                        elif groups[0] in mois_mapping:  # Format "mois jour année"
                            jour = groups[1].zfill(2)
                            mois = mois_mapping[groups[0]]
                            annee = groups[2]
                        else:  # Format numérique
                            if len(groups[0]) == 4:  # Premier groupe est l'année
                                annee = groups[0]
                                mois = str(int(groups[1])).zfill(2)
                                jour = str(int(groups[2])).zfill(2)
                            else:  # Premier groupe est le jour
                                jour = str(int(groups[0])).zfill(2)
                                mois = str(int(groups[1])).zfill(2)
                                annee = groups[2]
                        
                        # Validation de la date
                        date = datetime(int(annee), int(mois), int(jour))
                        if 1900 <= date.year <= 2100:
                            return date.strftime("%Y-%m-%d")  # Retourne immédiatement la première date valide
                    except ValueError:
                        continue

        # Si aucune date valide n'est trouvée via les patterns, essayer parse_date
        try:
            parsed_date = parse_date(text, fuzzy=True)
            if 1900 <= parsed_date.year <= 2100:
                return parsed_date.strftime("%Y-%m-%d")
        except Exception:
            pass

        logger.warning(f"Aucune date valide trouvée dans le texte")
        return ""

    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de la date: {str(e)}")
        return ""

def clean_content(content: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Nettoie le contenu en supprimant les sections non pertinentes."""
    return [section for section in content if does_make_sense(section["contenu_paragraphe"])]

def save_to_s3(data: Dict, site_name: str) -> tuple[str, int]:
    """Sauvegarde les données scrapées dans S3 avec compression gzip."""
    try:
        safe_title = re.sub(r"[^\w\-_]", "_", data["title"])[:50]
        s3_key = f"articles/{site_name}/{safe_title}.json.gz"
        content_text = "\n".join(
            f"{section['titre_paragraphe']}\n{section['contenu_paragraphe']}"
            for section in data["content"]
        )[:50000]
        token_count = len(content_text.split())
        json_data = {
            "url": data["url"],
            "date": data["date"],
            "title": data["title"],
            "content_par_paragraphe": data["content"],
            "content": content_text,
            "token_count": token_count
        }
        json_bytes = json.dumps(json_data, ensure_ascii=False).encode('utf-8')
        compressed_data = gzip.compress(json_bytes)
        s3_client.put_object(
            Bucket=CONFIG.s3_bucket_name,
            Key=s3_key,
            Body=compressed_data,
            ContentType='application/json',
            ContentEncoding='gzip'
        )
        logger.info(f"Sauvegardé sur S3: s3://{CONFIG.s3_bucket_name}/{s3_key}")
        return content_text, token_count
    except ClientError as e:
        logger.error(f"Erreur sauvegarde S3 pour {site_name}: {str(e)}")
        return "", 0

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def create_qdrant_collection(collection_name: str) -> bool:
    """Crée une collection Qdrant si elle n'existe pas avec retries."""
    try:
        collections = qdrant_client.get_collections().collections
        if collection_name in [c.name for c in collections]:
            collection_info = qdrant_client.get_collection(collection_name)
            if (
                collection_info.config.params.vectors.size == CONFIG.vector_dimension
                and collection_info.config.params.vectors.distance == models.Distance.COSINE
            ):
                logger.info(f"Collection {collection_name} existe déjà avec la bonne configuration")
                return True
            else:
                logger.error(f"Configuration incorrecte pour la collection {collection_name}")
                return False
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=CONFIG.vector_dimension,
                distance=models.Distance.COSINE
            )
        )
        logger.info(f"Collection créée: {collection_name}")
        return True
    except Exception as e:
        logger.error(f"Erreur création collection {collection_name}: {str(e)}")
        raise

def get_collection_by_date(data: Dict) -> str:
    """Retourne toujours la collection potential_questions."""
    return "potential_questions"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def upsert_points(collection_name: str, points: List[models.PointStruct]):
    """Insère des points dans Qdrant avec retries et affiche un message pour chaque URL insérée."""
    url = points[0].payload.get("url")

    try : 
        qdrant_client.upsert(collection_name=collection_name, points=points)
        logger.info(f"Upserted {len(points)} points dans {collection_name} pour l'URL {url}")
    except Exception as e:
        logger.error(f"Erreur upsert points {collection_name} pour l'URL {url}: {str(e)}")
        raise

def is_valid_question(question: str) -> bool:
    """Vérifie si une question est pertinente."""
    if len(question) < 10 or len(question.split()) < 3:
        return False
    return True

async def generate_questions(data: Dict, content_text: str, token_count: int, site_name: str) -> bool:
    """Génère des questions potentielles et extrait les décisions de justice pour un article."""
    try:
        if not content_text.strip():
            return False
        question_count = min(4, max(1, token_count // 200))

        # Extraire les décisions de justice
        justice_prompt = """
        Texte de l'article :
        {content_text}

        Analysez le texte ci-dessus pour extraire les décisions de justice et les références légales. Retournez une liste des informations pertinentes.

        Exemple de sortie : ['Cass. 1re civ., 18 sept. 2019, no19-40022', 'article 371-2 du code civil', ...]

        Critères :
        - Retournez chaque référence légale ou décision de justice précisément.
        - Ne retournez aucun texte supplémentaire, seulement la liste.
        - Si aucune décision ou référence légale n'est trouvée, retournez "aucune décision ou référence légale trouvée".
        """
        try:
            justice_response = await asyncio.wait_for(
                asyncio.to_thread(client_nebius.chat.completions.create,
                    model="meta-llama/Meta-Llama-3.1-8B-Instruct-fast",
                    messages=[{
                        "role": "user",
                        "content": justice_prompt.format(content_text=content_text[:50000])
                    }],
                    max_tokens=1000
                ),
                timeout=60
            )
            decisions_justice = str(justice_response.choices[0].message.content).strip()
        except Exception as e:
            logger.error(f"Erreur extraction décisions de justice pour {data['url']}: {repr(e)}")
            decisions_justice = f"Erreur lors de l'extraction : {repr(e)}"

        # Générer les questions
        question_prompt = f"""
        Article:
        {content_text[:50000]}
        Formulez {question_count} questions pertinentes pour lesquelles cet article pourrait être une réponse, une par ligne, toujours terminées par '?'.
        """
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(client_nebius.chat.completions.create,
                    model="meta-llama/Meta-Llama-3.1-8B-Instruct-fast",
                    messages=[{"role": "user", "content": question_prompt}],
                    max_tokens=200
                ),
                timeout=60
            )
            questions = [q.strip() for q in response.choices[0].message.content.strip().split("\n") if q.strip() and "?" in q and is_valid_question(q)]
            
            collection_name = get_collection_by_date(data)
            create_qdrant_collection(collection_name)

            vectors = sentence_model.encode(questions, batch_size=32, show_progress_bar=False).tolist()
            points = []
            for question, vector in zip(questions[:question_count], vectors):
                points.append(models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "question": question,
                        "url": data["url"],
                        "date": data["date"],
                        "title": data["title"],
                        "content": content_text,
                        "token_count": token_count,
                        "decisions_justice": decisions_justice
                    }
                ))
            if points:
                upsert_points(collection_name, points)

            return True
        except Exception as e:
            logger.error(f"Erreur génération questions pour {data['url']}: {str(e)}")
            return False
    except Exception as e:
        logger.error(f"Erreur génération questions: {str(e)}")
        return False

async def process_urls(urls: list, session: aiohttp.ClientSession):
    """Traite une liste d'URLs de manière séquentielle."""
    try:
        if not urls:
            logger.warning("Aucune URL valide à traiter")
            return

        logger.info(f"Traitement de {len(urls)} URLs")
        
        # Initialisation explicite de Playwright
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context()
        
        # Création du crawler avec le contexte initialisé
        crawler = AsyncWebCrawler()
        crawler.browser = browser
        crawler.context = context
        
        try:
            for url in urls:
                logger.info(f"Traitement de l'URL: {url}")
                try:
                    scraped_data = await scrape_article(url, crawler, session, DEFAULT_JS_SCRIPT)
                    if scraped_data:
                        scraped_data["content"] = clean_content(scraped_data["content"])
                        if scraped_data["content"]:
                            content_text, token_count = save_to_s3(scraped_data, "default_site")
                            if content_text:
                                await generate_questions(scraped_data, content_text, token_count, "default_site")
                    else:
                        logger.warning(f"Aucun contenu scrapé pour {url}")
                except Exception as e:
                    logger.error(f"Erreur lors du traitement de l'URL {url}: {str(e)}")
                    continue
                finally:
                    gc.collect()
        finally:
            # Nettoyage des ressources
            await context.close()
            await browser.close()
            await playwright.stop()
                
    except Exception as e:
        logger.error(f"Erreur lors du traitement des URLs: {str(e)}")


async def main():
    # Récupérer les URLs depuis les sitemaps
    urls = URLs_conseil_etat
    logger.info(f"Nombre total d'URLs extraites des sitemaps: {len(urls)}")
    
    # Récupérer les URLs existantes dans Qdrant
    existing_urls = get_existing_urls_from_qdrant()
    
    # Filtrer les URLs
    new_urls = [url for url in urls if is_valid_url(url) and normalize_url(url) not in existing_urls]
    
    logger.info(f"Nombre d'URLs nouvelles à traiter: {len(new_urls)} (après filtrage des {len(existing_urls)} URLs existantes)")
    
    if not new_urls:
        logger.info("Aucune nouvelle URL à traiter")
        return
    
    async with aiohttp.ClientSession() as session:
        await process_urls(new_urls, session)
    
    # Optionnel : Vérifier les collections après traitement
    await verify_qdrant_collections()


async def verify_qdrant_collections():
    """Vérifie et crée la collection Qdrant si nécessaire."""
    collection_name = "potential_questions"
    try:
        collections = qdrant_client.get_collections().collections
        collection_names = [collection.name for collection in collections]
        
        if collection_name not in collection_names:
            logger.info(f"Création de la collection {collection_name}")
            create_qdrant_collection(collection_name)
        else:
            logger.info(f"Collection {collection_name} existe déjà")
            
    except Exception as e:
        logger.error(f"Erreur vérification collections Qdrant: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())