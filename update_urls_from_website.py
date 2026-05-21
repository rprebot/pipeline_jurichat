"""
Script unifié pour extraire les URLs d'articles depuis les sites juridiques
et créer un fichier avec les URLs non encore traitées.

Usage:
    python update_urls_from_website.py                      # Lance les 2 sources
    python update_urls_from_website.py consultation_avocats  # Une seule source
    python update_urls_from_website.py open_lefebvre         # Une seule source

Sources supportées:
- consultation_avocats : consultation.avocat.fr (extraction par regex HTML)
- open_lefebvre : open.lefebvre-dalloz.fr (extraction via __NEXT_DATA__ JSON)
"""

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import aiohttp

from pipeline_ingestion_blogs.logger import setup_logger
from pipeline_ingestion_blogs.historique_manager import HistoriqueManager
from pipeline_ingestion_blogs.url_utils import normalize_url, is_valid_url


# ======================================================================
# Configuration des sources
# ======================================================================

SOURCES = {
    "consultation_avocats": {
        "label": "CONSULTATION.AVOCAT.FR",
        "module": "blog_base.urls_consultations_avocats",
        "source_name": "consultation_avocat",
    },
    "open_lefebvre": {
        "label": "OPEN LEFEBVRE DALLOZ",
        "module": "blog_base.urls_open_lefebvre_dalloz",
        "source_name": "open_lefebvre_dalloz",
    },
}

# ======================================================================
# Extraction : consultation.avocat.fr
# ======================================================================

ARTICLE_URL_PATTERN = re.compile(
    r'href=["\']'
    r'(https://consultation\.avocat\.fr/blog/[^/]+/article-\d+[^"\']*\.html)'
    r'["\']'
)


async def fetch_page_consultation_avocats(
    session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore, logger
) -> list[str]:
    async with semaphore:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    logger.warning(f"HTTP {response.status} pour {url}")
                    return []
                html = await response.text()
                article_urls = list(dict.fromkeys(ARTICLE_URL_PATTERN.findall(html)))
                logger.info(f"{url} -> {len(article_urls)} articles")
                return article_urls
        except asyncio.TimeoutError:
            logger.warning(f"Timeout pour {url}")
            return []
        except Exception as e:
            logger.warning(f"Erreur pour {url}: {e}")
            return []


# ======================================================================
# Extraction : open.lefebvre-dalloz.fr
# ======================================================================

BASE_URL_LEFEBVRE = "https://open.lefebvre-dalloz.fr"
NEXT_DATA_PATTERN = re.compile(
    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*({.*?})\s*</script>',
    re.DOTALL,
)


async def fetch_page_open_lefebvre(
    session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore, logger
) -> list[str]:
    async with semaphore:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    logger.warning(f"HTTP {response.status} pour {url}")
                    return []
                html = await response.text()
                match = NEXT_DATA_PATTERN.search(html)
                if not match:
                    logger.warning(f"Pas de __NEXT_DATA__ trouve dans {url}")
                    return []
                data = json.loads(match.group(1))
                actualites = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("page", {})
                    .get("actualites", [])
                )
                article_urls = [
                    BASE_URL_LEFEBVRE + a["href"]
                    for a in actualites
                    if a.get("href")
                ]
                logger.info(f"{url} -> {len(article_urls)} articles")
                return article_urls
        except asyncio.TimeoutError:
            logger.warning(f"Timeout pour {url}")
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"Erreur JSON pour {url}: {e}")
            return []
        except Exception as e:
            logger.warning(f"Erreur pour {url}: {e}")
            return []


# ======================================================================
# Fonctions communes
# ======================================================================

FETCH_FUNCTIONS = {
    "consultation_avocats": fetch_page_consultation_avocats,
    "open_lefebvre": fetch_page_open_lefebvre,
}


async def extract_all_article_urls(
    page_urls: list[str], fetch_fn, max_concurrent: int = 5, logger=None
) -> list[str]:
    semaphore = asyncio.Semaphore(max_concurrent)
    all_urls = []

    async with aiohttp.ClientSession(
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    ) as session:
        tasks = [fetch_fn(session, url, semaphore, logger) for url in page_urls]
        results = await asyncio.gather(*tasks)
        for urls in results:
            all_urls.extend(urls)

    seen = set()
    unique = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def load_page_urls(source_key: str) -> list[str]:
    cfg = SOURCES[source_key]
    try:
        import importlib
        mod = importlib.import_module(cfg["module"])
        return mod.unique_urls
    except ImportError:
        print(f"ERREUR: Impossible d'importer unique_urls depuis {cfg['module']}")
        sys.exit(1)


async def run_source(source_key: str, logger, historique: HistoriqueManager):
    cfg = SOURCES[source_key]
    fetch_fn = FETCH_FUNCTIONS[source_key]

    print("\n" + "=" * 70)
    print(f"EXTRACTION DES URLs DEPUIS {cfg['label']}")
    print("=" * 70 + "\n")

    start_time = datetime.now()
    logger.info(f"Demarrage de l'extraction des URLs depuis {cfg['label']}")

    # 1. Parcours des pages
    page_urls = load_page_urls(source_key)
    logger.info(f"Parcours de {len(page_urls)} pages")
    print(f"Etape 1/3: Parcours des pages ({len(page_urls)} pages)")

    try:
        article_urls = await extract_all_article_urls(
            page_urls, fetch_fn, max_concurrent=5, logger=logger
        )
        logger.info(f"URLs extraites: {len(article_urls)}")
        print(f"  -> {len(article_urls)} URLs d'articles extraites\n")
    except Exception as e:
        logger.critical(f"Erreur extraction: {str(e)}")
        print(f"ERREUR: {str(e)}")
        return 0

    # 2. Verification dans l'historique
    logger.info("Verification des URLs deja traitees dans l'historique")
    print("Etape 2/3: Verification de l'historique")

    processed_urls = historique.get_processed_urls()
    logger.info(f"URLs deja traitees (historique): {len(processed_urls)}")
    print(f"  -> {len(processed_urls)} URLs deja traitees dans l'historique\n")

    # 3. Filtrage
    logger.info("Filtrage des nouvelles URLs")
    print("Etape 3/3: Filtrage des nouvelles URLs")

    new_urls = [
        url for url in article_urls
        if is_valid_url(url) and normalize_url(url) not in processed_urls
    ]

    logger.info(f"Nouvelles URLs a traiter: {len(new_urls)}")
    print(f"  -> {len(new_urls)} nouvelles URLs a traiter")

    # 4. Sauvegarde
    if len(new_urls) == 0:
        print(f"\n* Aucune nouvelle URL a traiter pour {cfg['label']}.\n")
        logger.info("Aucune nouvelle URL a traiter")
        return 0

    output_dir = Path("URL_to_ingest")
    output_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    output_file = output_dir / f"urls_{date_str}.json"

    if output_file.exists():
        logger.info(f"Fichier existant detecte: {output_file}, fusion en cours")
        print(f"\n  Fichier existant detecte: {output_file}")
        with open(output_file, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        existing_urls = set(existing_data.get("urls", []))
        print(f"  -> {len(existing_urls)} URLs deja presentes dans le fichier")

        urls_to_add = [url for url in new_urls if url not in existing_urls]
        logger.info(f"URLs a ajouter (non dupliquees): {len(urls_to_add)}")
        print(f"  -> {len(urls_to_add)} nouvelles URLs a ajouter (apres dedup)")

        merged_urls = existing_data["urls"] + urls_to_add
        data = {
            "created_at": existing_data.get("created_at", datetime.now().isoformat()),
            "total_urls": len(merged_urls),
            "source": existing_data.get("source", "mixed"),
            "urls": merged_urls,
        }
    else:
        data = {
            "created_at": datetime.now().isoformat(),
            "total_urls": len(new_urls),
            "source": cfg["source_name"],
            "urls": sorted(new_urls),
        }
        urls_to_add = new_urls

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Fichier sauvegarde: {output_file}")
        print(f"\n* Fichier sauvegarde: {output_file}")
        print(f"  Total: {data['total_urls']} URLs ({len(urls_to_add)} ajoutees)\n")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde du fichier: {str(e)}")
        print(f"\nERREUR lors de la sauvegarde: {str(e)}")
        return 0

    # 5. Statistiques
    end_time = datetime.now()
    duration = end_time - start_time

    print("=" * 70)
    print(f"EXTRACTION TERMINEE - {cfg['label']}")
    print("=" * 70)
    print(f"\nDuree totale: {duration}")
    print(f"\nStatistiques:")
    print(f"  Pages parcourues: {len(page_urls)}")
    print(f"  URLs extraites: {len(article_urls)}")
    print(f"  URLs deja traitees: {len(processed_urls)}")
    print(f"  Nouvelles URLs: {len(new_urls)}")
    print(f"\nFichier genere: {output_file}")
    print("\n" + "=" * 70 + "\n")

    logger.info(f"Extraction terminee. Duree: {duration}")
    logger.info(f"Fichier genere: {output_file} avec {len(urls_to_add)} URLs ajoutees")

    return len(urls_to_add)


async def main():
    # Determiner quelles sources lancer
    valid_sources = list(SOURCES.keys())

    if len(sys.argv) > 1:
        source_arg = sys.argv[1]
        if source_arg not in valid_sources:
            print(f"ERREUR: Source inconnue '{source_arg}'")
            print(f"Sources valides: {', '.join(valid_sources)}")
            sys.exit(1)
        sources_to_run = [source_arg]
    else:
        sources_to_run = valid_sources

    logger = setup_logger()
    historique = HistoriqueManager()
    logger.info("Gestionnaire d'historique initialise")

    print("\n" + "#" * 70)
    print(f"# MISE A JOUR DES URLs - {len(sources_to_run)} source(s)")
    print("#" * 70)

    total_added = 0
    for source_key in sources_to_run:
        added = await run_source(source_key, logger, historique)
        total_added += added

    if len(sources_to_run) > 1:
        print("\n" + "#" * 70)
        print(f"# BILAN GLOBAL: {total_added} URLs ajoutees au total")
        print("#" * 70)

    print(f"\nProchaine etape:")
    print(f"  python scrape_and_update_qdrant_collection.py")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nExtraction interrompue par l'utilisateur (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\nERREUR CRITIQUE: {str(e)}")
        sys.exit(1)
