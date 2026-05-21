"""
Module pour parser les sitemaps XML et extraire les URLs d'articles.
"""

import asyncio
import gzip
import xml.etree.ElementTree as ET
from typing import List, Set
import aiohttp
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# Namespaces XML pour sitemaps
SITEMAP_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
)
async def fetch_sitemap(session: aiohttp.ClientSession, url: str) -> str:
    """
    Récupère le contenu d'un sitemap (gère la compression gzip).

    Args:
        session: Session aiohttp
        url: URL du sitemap

    Returns:
        Contenu XML du sitemap en str

    Raises:
        aiohttp.ClientError: En cas d'erreur HTTP
        asyncio.TimeoutError: En cas de timeout
    """
    try:
        async with session.get(url, timeout=30) as response:
            response.raise_for_status()

            content = await response.read()

            # Décompresser si gzip
            if url.endswith('.gz') or response.headers.get('Content-Encoding') == 'gzip':
                try:
                    content = gzip.decompress(content)
                except Exception as e:
                    logger.warning(f"Échec décompression gzip pour {url}: {str(e)}")

            return content.decode('utf-8', errors='ignore')

    except asyncio.TimeoutError:
        logger.warning(f"Timeout lors de la récupération du sitemap: {url}")
        raise
    except aiohttp.ClientError as e:
        logger.warning(f"Erreur HTTP lors de la récupération du sitemap {url}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la récupération du sitemap {url}: {str(e)}")
        raise


async def parse_sitemap_xml(xml_content: str) -> List[str]:
    """
    Parse un sitemap XML et extrait les URLs.

    Args:
        xml_content: Contenu XML du sitemap

    Returns:
        Liste des URLs trouvées dans les tags <loc>
    """
    urls = []

    try:
        root = ET.fromstring(xml_content)

        # Chercher les tags <url><loc> (sitemaps réguliers)
        for url_elem in root.findall('.//sm:url/sm:loc', SITEMAP_NS):
            if url_elem.text:
                urls.append(url_elem.text.strip())

        # Si pas de namespace, essayer sans
        if not urls:
            for url_elem in root.findall('.//url/loc'):
                if url_elem.text:
                    urls.append(url_elem.text.strip())

    except ET.ParseError as e:
        logger.error(f"Erreur parsing XML: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue lors du parsing XML: {str(e)}")

    return urls


async def is_sitemap_index(xml_content: str) -> bool:
    """
    Vérifie si le XML est un sitemap index (contient des tags <sitemap>).

    Args:
        xml_content: Contenu XML

    Returns:
        True si c'est un sitemap index, False sinon
    """
    try:
        root = ET.fromstring(xml_content)

        # Chercher les tags <sitemap>
        sitemap_elems = root.findall('.//sm:sitemap', SITEMAP_NS)
        if not sitemap_elems:
            sitemap_elems = root.findall('.//sitemap')

        return len(sitemap_elems) > 0

    except Exception:
        return False


async def handle_sitemap_index(session: aiohttp.ClientSession, index_url: str) -> List[str]:
    """
    Gère un sitemap index en récupérant récursivement tous les sub-sitemaps.

    Args:
        session: Session aiohttp
        index_url: URL du sitemap index

    Returns:
        Liste de toutes les URLs d'articles trouvées
    """
    all_urls = []

    try:
        xml_content = await fetch_sitemap(session, index_url)
        root = ET.fromstring(xml_content)

        # Extraire les URLs des sub-sitemaps
        sub_sitemap_urls = []
        for sitemap_elem in root.findall('.//sm:sitemap/sm:loc', SITEMAP_NS):
            if sitemap_elem.text:
                sub_sitemap_urls.append(sitemap_elem.text.strip())

        # Si pas de namespace, essayer sans
        if not sub_sitemap_urls:
            for sitemap_elem in root.findall('.//sitemap/loc'):
                if sitemap_elem.text:
                    sub_sitemap_urls.append(sitemap_elem.text.strip())

        logger.info(f"Sitemap index {index_url} contient {len(sub_sitemap_urls)} sub-sitemaps")

        # Récupérer toutes les URLs de chaque sub-sitemap
        for sub_url in sub_sitemap_urls:
            try:
                sub_xml = await fetch_sitemap(session, sub_url)

                # Vérifier si c'est encore un index (récursion)
                if await is_sitemap_index(sub_xml):
                    sub_urls = await handle_sitemap_index(session, sub_url)
                    all_urls.extend(sub_urls)
                else:
                    sub_urls = await parse_sitemap_xml(sub_xml)
                    all_urls.extend(sub_urls)

                logger.info(f"Extrait {len(sub_urls)} URLs de {sub_url}")

            except Exception as e:
                logger.error(f"Erreur lors du traitement du sub-sitemap {sub_url}: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"Erreur lors du traitement du sitemap index {index_url}: {str(e)}")

    return all_urls


async def extract_all_article_urls(sitemap_urls: List[str], max_concurrent: int = 10) -> Set[str]:
    """
    Extrait toutes les URLs d'articles à partir d'une liste de sitemaps.

    Args:
        sitemap_urls: Liste des URLs de sitemaps à parser
        max_concurrent: Nombre max de sitemaps à traiter en parallèle

    Returns:
        Set d'URLs uniques d'articles
    """
    all_urls = set()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_sitemap(session: aiohttp.ClientSession, sitemap_url: str):
        async with semaphore:
            try:
                logger.info(f"Traitement du sitemap: {sitemap_url}")

                xml_content = await fetch_sitemap(session, sitemap_url)

                # Vérifier si c'est un sitemap index
                if await is_sitemap_index(xml_content):
                    urls = await handle_sitemap_index(session, sitemap_url)
                else:
                    urls = await parse_sitemap_xml(xml_content)

                logger.info(f"Extrait {len(urls)} URLs de {sitemap_url}")
                return urls

            except Exception as e:
                logger.error(f"Échec traitement sitemap {sitemap_url}: {str(e)}")
                return []

    async with aiohttp.ClientSession() as session:
        tasks = [process_sitemap(session, url) for url in sitemap_urls]
        results = await asyncio.gather(*tasks)

        # Combiner tous les résultats
        for urls in results:
            all_urls.update(urls)

    logger.info(f"Total URLs uniques extraites: {len(all_urls)}")
    return all_urls
