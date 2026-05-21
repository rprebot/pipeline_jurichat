"""
Module de base pour l'importation et l'indexation des décisions juridiques.

Ce module contient toutes les fonctionnalités communes pour importer et indexer
les décisions de la Cour d'appel (CA) et de la Cour de cassation (CC) dans Qdrant.

Fonctionnalités principales :
- Récupération des décisions via l'API Judilibre
- Génération de résumés et de questions potentielles via LLM
- Vectorisation des questions via OpenAI Embedding
- Insertion des points enrichis dans Qdrant
- Suivi de l'utilisation des ressources et logs détaillés
"""
import os
import time
import logging
import requests
import csv
from typing import List, Dict, Set, Tuple, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI
from dotenv import load_dotenv
import uuid
from multiprocessing import Pool, Manager, cpu_count
import re
import psutil
import gc
from tqdm import tqdm
import requests.exceptions
from datetime import datetime, timedelta
import calendar

# Instructions LLM
from instruction_llm import instruction_llm_import_2, instruction_potential_questions

# Chargement des variables d'environnement
load_dotenv()

# Configuration du logging
def setup_logging(log_filename: str = 'import_decisions.log') -> logging.Logger:
    """Configure le système de logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# Configuration des ressources
NUM_CPUS = cpu_count()
NUM_WORKERS = max(1, NUM_CPUS - 1)  # Garder un CPU pour le système
BATCH_SIZE = 50
VECTOR_SIZE = 256

# Variables d'environnement
BASE_URL = os.getenv('JUDILIBRE_BASE_URL', "https://api.piste.gouv.fr/cassation/judilibre/v1.0")
KEY_ID = os.getenv('JUDILIBRE_KEY_ID', "36565fd1-dd53-4f5e-b912-e6b5203fe259")
QDRANT_URL = os.getenv('QDRANT_URL', "https://c7e975da-a3a8-4ef8-b3ae-52cf73583223.europe-west3-0.gcp.cloud.qdrant.io")
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', "COLLEZ_VOTRE_NOUVELLE_CLE_ICI")

# Paramètres de l'API
MAX_TOKENS = int(os.getenv('MAX_TOKENS', 8000))
TEMPERATURE = float(os.getenv('TEMPERATURE', 0.7))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))

HEADERS_JUDILIBRE = {"accept": "application/json", "KeyId": KEY_ID}

class ResourceMonitor:
    """Classe pour surveiller l'utilisation des ressources."""
    def __init__(self):
        self.start_time = time.time()
        self.process = psutil.Process()
        self.initial_memory = self.process.memory_info().rss

    def get_stats(self) -> Dict:
        """Retourne les statistiques d'utilisation des ressources."""
        current_memory = self.process.memory_info().rss
        elapsed_time = time.time() - self.start_time
        return {
            'memory_used_mb': (current_memory - self.initial_memory) / 1024 / 1024,
            'cpu_percent': self.process.cpu_percent(),
            'elapsed_time_seconds': elapsed_time
        }

class OpenAIEmbeddingClient:
    """Client pour la vectorisation via OpenAI Embedding."""
    def __init__(self, model="text-embedding-3-large", dimensions=256):
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts):
        import openai
        response = openai.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions
        )
        return [d.embedding for d in response.data]

class DecisionImporter:
    """Classe principale pour l'importation des décisions."""
    
    def __init__(self, config: Dict):
        """
        Initialise l'importateur avec la configuration spécifiée.
        
        Args:
            config: Configuration contenant:
                - jurisdiction: 'ca' ou 'cc'
                - collection_name: nom de la collection Qdrant
                - llm_config: configuration du client LLM
                - fields: champs spécifiques à extraire
        """
        self.config = config
        self.jurisdiction = config['jurisdiction']
        self.collection_name = config['collection_name']
        self.fields = config.get('fields', [])
        
        # Initialisation des clients
        self.qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        self.embedding_client = OpenAIEmbeddingClient()
        self.llm_client = self._init_llm_client(config['llm_config'])
        
        # Configuration du fichier CSV de tracking
        self.csv_filename = f"decisions_{self.jurisdiction}.csv"
        
        # Vérification des variables d'environnement requises
        self._check_required_env_vars()

    def _load_existing_ids_from_csv(self) -> Set[str]:
        """
        Charge la liste des IDs déjà traités depuis le fichier CSV.
        
        Returns:
            Set des IDs uniques déjà présents dans Qdrant
        """
        existing_ids = set()
        
        if os.path.exists(self.csv_filename):
            try:
                with open(self.csv_filename, 'r', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    
                    # Lire l'en-tête s'il existe
                    first_row = next(reader, None)
                    if first_row and first_row[0] != 'unique_id':
                        # Si la première ligne n'est pas l'en-tête, c'est un ID
                        existing_ids.add(first_row[0])
                    
                    # Lire le reste des lignes
                    for row in reader:
                        if row and row[0].strip():  # Ignorer les lignes vides
                            existing_ids.add(row[0].strip())
                            
                logger.info(f"📊 {len(existing_ids)} IDs déjà traités chargés depuis {self.csv_filename}")
                
            except Exception as e:
                logger.warning(f"⚠️ Erreur lors de la lecture du fichier CSV {self.csv_filename}: {e}")
                logger.info("📝 Un nouveau fichier CSV sera créé")
        else:
            logger.info(f"📝 Fichier CSV {self.csv_filename} non trouvé, création d'un nouveau fichier")
            
        return existing_ids

    def _add_id_to_csv(self, unique_id: str) -> None:
        """
        Ajoute un ID unique au fichier CSV de tracking.
        
        Args:
            unique_id: L'ID unique de la décision à ajouter
        """
        try:
            # Vérifier si le fichier existe et s'il est vide
            file_exists = os.path.exists(self.csv_filename)
            is_empty = not file_exists or os.path.getsize(self.csv_filename) == 0
            
            with open(self.csv_filename, 'a', encoding='utf-8', newline='') as csvfile:
                writer = csv.writer(csvfile)
                
                # Ajouter l'en-tête si le fichier est nouveau ou vide
                if is_empty:
                    writer.writerow(['unique_id', 'date_added'])
                
                # Ajouter l'ID avec la date actuelle
                current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([unique_id, current_date])
                
            logger.info(f"✅ ID {unique_id} ajouté au fichier CSV {self.csv_filename}")
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'ajout de l'ID {unique_id} au CSV: {e}")

    def _init_llm_client(self, llm_config: Dict) -> OpenAI:
        """Initialise le client LLM selon la configuration."""
        return OpenAI(
            api_key=llm_config['api_key'],
            base_url=llm_config['base_url']
        )

    def _check_required_env_vars(self):
        """Vérifie que toutes les variables d'environnement requises sont présentes."""
        required_vars = {
            'BASE_URL': BASE_URL,
            'KEY_ID': KEY_ID,
            'QDRANT_URL': QDRANT_URL,
            'QDRANT_API_KEY': QDRANT_API_KEY
        }
        
        missing_vars = [var for var, value in required_vars.items() if not value]
        if missing_vars:
            raise ValueError(f"Variables d'environnement manquantes : {', '.join(missing_vars)}")

    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=4, max=10))
    def get_decisions_for_month(self, year: int, month: int) -> List[Dict]:
        """Récupère toutes les décisions pour un mois et une année donnés."""
        try:
            # Calcul des dates de début et fin du mois
            first_day = datetime(year, month, 1)
            last_day_num = calendar.monthrange(year, month)[1]
            last_day = datetime(year, month, last_day_num)
            
            date_start = first_day.strftime("%Y-%m-%d")
            date_end = last_day.strftime("%Y-%m-%d")
            
            logger.info(f"Récupération des décisions {self.jurisdiction.upper()} pour {month:02d}/{year} ({date_start} à {date_end})")
            
            all_decisions = []
            page = 1
            page_size = BATCH_SIZE

            params = {
                "query": "*",
                "jurisdiction": self.jurisdiction,
                "date_start": date_start,
                "date_end": date_end,
                "page_size": page_size,
            }

            with tqdm(desc=f"Récupération {self.jurisdiction.upper()} {month:02d}/{year}") as pbar:
                while True:
                    params["page"] = page
                    response = requests.get(
                        f"{BASE_URL}/search",
                        headers=HEADERS_JUDILIBRE,
                        params=params,
                        timeout=30
                    )

                    if response.status_code == 416:
                        break
                    
                    response.raise_for_status()
                    data = response.json()

                    decisions = data.get("results", [])
                    if not decisions:
                        break

                    # Extraction des champs selon la configuration
                    filtered_decisions = []
                    for d in decisions:
                        decision_data = {
                            "id": d.get("id"),
                            "number": d.get("number"),
                            "decision_date": d.get("decision_date"),
                            "jurisdiction": d.get("jurisdiction"),
                            "chamber": d.get("chamber"),
                            "formation": d.get("formation"),
                            "type": d.get("type"),
                            "localisation": d.get("location"),
                            "solution": d.get("solution"),
                            "text": d.get("text"),
                            "theme": d.get("theme")
                        }
                        
                        # Ajout des champs spécifiques selon la configuration
                        for field in self.fields:
                            decision_data[field] = d.get(field)
                        
                        filtered_decisions.append(decision_data)

                    all_decisions.extend(filtered_decisions)
                    pbar.update(len(filtered_decisions))

                    if len(decisions) < page_size:
                        break

                    page += 1
                    time.sleep(1.0)

            logger.info(f"Total décisions récupérées pour {month:02d}/{year} : {len(all_decisions)}")
            return all_decisions

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des décisions pour {month:02d}/{year} : {e}")
            raise

    def get_existing_unique_ids(self) -> Set[str]:
        """Récupère la liste des IDs uniques déjà présents dans la collection."""
        try:
            logger.info(f"Récupération des IDs uniques dans la collection {self.collection_name}")
            unique_ids = set()
            offset = None
            
            # Vérification si la collection existe
            try:
                self.qdrant_client.get_collection(self.collection_name)
            except Exception:
                logger.info(f"Collection {self.collection_name} n'existe pas encore")
                return unique_ids
            
            while True:
                points, next_offset = self.qdrant_client.scroll(
                    collection_name=self.collection_name,
                    limit=100,
                    with_payload=True,
                    offset=offset
                )
                for point in points:
                    if 'unique_ID' in point.payload:
                        unique_ids.add(point.payload['unique_ID'])
                if not next_offset:
                    break
                offset = next_offset
            
            logger.info(f"Nombre d'IDs uniques existants : {len(unique_ids)}")
            return unique_ids
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des IDs uniques : {e}")
            return set()

    def create_collection_if_not_exists(self) -> None:
        """Crée la collection Qdrant si elle n'existe pas."""
        try:
            collections = self.qdrant_client.get_collections()
            if self.collection_name not in [col.name for col in collections.collections]:
                self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE)
                )
                logger.info(f"Collection '{self.collection_name}' créée")
            else:
                logger.info(f"Collection '{self.collection_name}' déjà existante")
        except Exception as e:
            logger.error(f"Erreur lors de la création de la collection : {e}")
            raise

    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=4, max=10))
    def get_decision_text(self, decision_id: str) -> str:
        """Récupère le texte complet d'une décision."""
        try:
            response = requests.get(
                f"{BASE_URL}/decision", 
                headers=HEADERS_JUDILIBRE, 
                params={"id": decision_id}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("text", "Contenu non disponible")
        except requests.RequestException as e:
            logger.error(f"Erreur lors de la récupération du texte de la décision {decision_id} : {e}")
            raise

    def summarize_decision(self, text: str) -> str:
        """Génère un résumé de la décision en utilisant le LLM configuré."""
        prompt = instruction_llm_import_2 + f"\n\n{text}"
        try:
            response = self.llm_client.chat.completions.create(
                model=self.config['llm_config']['model'],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Erreur lors de la génération du résumé : {e}")
            return "Erreur lors de la génération du résumé"

    def generate_potential_questions(self, summary: str) -> List[str]:
        """Génère des questions potentielles à partir du résumé."""
        prompt = instruction_potential_questions + f"\n\n{summary}"
        try:
            response = self.llm_client.chat.completions.create(
                model=self.config['llm_config']['model'],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE
            )
            questions = response.choices[0].message.content.strip().splitlines()
            return questions
        except Exception as e:
            logger.error(f"Erreur lors de la génération des questions potentielles : {e}")
            return ["Erreur lors de la génération des questions"]

    def extract_unique_questions(self, question_string: List[str]) -> List[str]:
        """Extrait les questions uniques d'une liste de questions."""
        try:
            if not question_string:
                return []
            
            # Nettoyage initial des questions
            questions = [q.strip() for q in question_string if q.strip()]
            
            # Suppression des numéros au début (1., 2., etc.)
            questions = [re.sub(r'^\d+\.\s*', '', q) for q in questions]
            
            # Suppression des astérisques
            questions = [q.replace('*', '') for q in questions]
            
            # Filtrage des questions valides (contenant '?')
            valid_questions = [q for q in questions if '?' in q]
            
            # Suppression des doublons
            unique_questions = list(dict.fromkeys(valid_questions))
            
            return unique_questions
        except Exception as e:
            logger.error(f"Erreur dans extract_unique_questions: {str(e)}")
            return []

    def add_point_to_qdrant(self, payload: Dict, vector: List[float]) -> None:
        """Ajoute un point à la collection Qdrant."""
        try:
            self.qdrant_client.upsert(
                collection_name=self.collection_name, 
                points=[models.PointStruct(id=payload["id"], payload=payload, vector=vector)]
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'ajout du point à Qdrant : {e}")
            raise

    def process_decision(self, decision: Dict, existing_ids: Set[str] = None) -> bool:
        """
        Traite une décision individuellement.
        
        Args:
            decision: Les données de la décision
            existing_ids: Set des IDs déjà traités (pour éviter les doublons)
        
        Returns:
            bool: True si la décision a été traitée, False si ignorée ou en cas d'erreur
        """
        decision_id = decision["id"]
        
        # Vérifier si la décision est déjà traitée
        if existing_ids and decision_id in existing_ids:
            logger.debug(f"🔄 Décision {decision_id} déjà présente dans {self.csv_filename}, passage à la suivante")
            return False
        
        try:
            logger.info(f"🔧 Traitement de la décision {decision_id} en cours...")
            
            # Récupérer le texte complet
            text = self.get_decision_text(decision_id)
            
            # Générer le résumé (avec logique spécifique selon la juridiction)
            summary = self.get_summary(decision, text)
            
            # Générer les questions potentielles
            potential_questions = self.generate_potential_questions(summary)
            unique_questions = self.extract_unique_questions(potential_questions)
            
            if not unique_questions:
                logger.warning(f"⚠️ Aucune question générée pour la décision {decision_id}")
                return False
            
            # Traiter chaque question unique
            for question in unique_questions:
                vector = self.embedding_client.embed([question])[0]
                payload = self.create_payload(decision, summary, question)
                self.add_point_to_qdrant(payload, vector)
            
            # ✅ Traitement réussi → Ajouter l'ID au fichier CSV
            self._add_id_to_csv(decision_id)
            
            logger.info(f"✅ Décision {decision['number']} traitée avec succès - {len(unique_questions)} questions générées")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors du traitement de la décision {decision_id} : {e}")
            return False

    def get_summary(self, decision: Dict, text: str) -> str:
        """Méthode à surcharger selon la juridiction pour la génération du résumé."""
        return self.summarize_decision(text)

    def create_payload(self, decision: Dict, summary: str, question: str) -> Dict:
        """Crée le payload pour Qdrant."""
        payload = {
            "id": str(uuid.uuid4()),
            "number": decision["number"],
            "decision_date": decision["decision_date"],
            "jurisdiction": decision["jurisdiction"],
            "chamber": decision["chamber"],
            "formation": decision["formation"],
            "type": decision["type"],
            "localisation": decision["localisation"],
            "solution": decision["solution"],
            "theme": decision["theme"],
            "summary": summary,
            "question": question,
            "unique_ID": decision["id"]
        }
        
        # Ajout des champs spécifiques selon la configuration
        for field in self.fields:
            if field in decision:
                payload[field] = decision[field]
        
        return payload

    def import_decisions_for_month(self, year: int, month: int) -> Dict:
        """
        Importe toutes les décisions pour un mois donné.
        
        Returns:
            Dict: Statistiques d'importation
        """
        monitor = ResourceMonitor()
        
        try:
            logger.info(f"🚀 Début de l'importation {self.jurisdiction.upper()} pour {month:02d}/{year}")
            
            # Créer la collection si nécessaire
            self.create_collection_if_not_exists()
            
            # 📊 Charger les IDs déjà traités depuis le fichier CSV
            existing_ids = self._load_existing_ids_from_csv()
            
            # Récupérer les décisions du mois
            decisions = self.get_decisions_for_month(year, month)
            
            if not decisions:
                logger.info(f"ℹ️ Aucune décision à traiter pour {month:02d}/{year}")
                return {"processed": 0, "skipped": 0, "total": 0}
            
            logger.info(f"📋 {len(decisions)} décisions trouvées pour {month:02d}/{year}")
            
            # Traitement des décisions
            processed = 0
            skipped = 0
            
            with tqdm(total=len(decisions), desc=f"Traitement {self.jurisdiction.upper()} {month:02d}/{year}") as pbar:
                for decision in decisions:
                    if self.process_decision(decision, existing_ids):
                        processed += 1
                    else:
                        skipped += 1
                    pbar.update(1)
                    
                    # Nettoyage mémoire
                    if (processed + skipped) % 10 == 0:
                        gc.collect()
            
            # Statistiques finales
            stats = monitor.get_stats()
            result = {
                "processed": processed,
                "skipped": skipped,
                "total": len(decisions),
                "memory_used_mb": stats['memory_used_mb'],
                "elapsed_time_seconds": stats['elapsed_time_seconds']
            }
            
            logger.info(f"Importation terminée pour {month:02d}/{year}: "
                       f"{processed} traitées, {skipped} ignorées, "
                       f"Temps: {stats['elapsed_time_seconds']:.2f}s")
            
            return result
            
        except Exception as e:
            logger.error(f"Erreur lors de l'importation pour {month:02d}/{year} : {e}")
            raise

def validate_month_year(month: int, year: int) -> Tuple[int, int]:
    """Valide et retourne le mois et l'année."""
    if not (1 <= month <= 12):
        raise ValueError(f"Le mois doit être entre 1 et 12, reçu: {month}")
    
    current_year = datetime.now().year
    if not (2000 <= year <= current_year + 1):
        raise ValueError(f"L'année doit être entre 2000 et {current_year + 1}, reçu: {year}")
    
    return month, year 