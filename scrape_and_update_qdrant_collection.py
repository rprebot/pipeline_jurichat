"""
Script pour scraper les URLs d'un fichier et les intégrer dans Qdrant.

Usage:
    python scrape_and_update_qdrant_collection.py [fichier1.json fichier2.json ...] [--update-failed]

Arguments:
    fichiers          Noms des fichiers JSON dans URL_to_ingest/ à traiter.
                      Si aucun fichier n'est spécifié, le fichier le plus récent est utilisé.
    --update-failed   Retraiter les URLs qui ont échoué précédemment.
                      Par défaut (False), les URLs déjà traitées (succès ou échec) sont ignorées.

Ce script va :
1. Lire le(s) fichier(s) spécifiés (ou le plus récent) dans URL_to_ingest/
2. Filtrer les URLs déjà traitées dans l'historique
3. Scraper le contenu de chaque URL
4. Générer les questions potentielles avec le LLM
5. Créer les embeddings et stocker dans Qdrant (2 batches en parallèle)
6. Mettre à jour l'historique
"""

import argparse
import asyncio
import json
import sys
import gc
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from openai import OpenAI
from qdrant_client import QdrantClient
from crawl4ai import AsyncWebCrawler
from playwright.async_api import async_playwright

# Import des modules de la pipeline
from pipeline_ingestion_blogs.config import BlogPipelineConfig
from pipeline_ingestion_blogs.logger import setup_logger
from pipeline_ingestion_blogs.article_scraper import scrape_articles_batch, clean_content
from pipeline_ingestion_blogs.content_processor import process_articles_batch
from pipeline_ingestion_blogs.vector_store import (
    check_qdrant_health,
    create_qdrant_collection,
    store_article_in_qdrant
)
from pipeline_ingestion_blogs.historique_manager import HistoriqueManager
from pipeline_ingestion_blogs.url_utils import normalize_url

# Nombre de batches traités en parallèle
MAX_PARALLEL_BATCHES = 1


def parse_args():
    """Parse les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description="Scrape des URLs et les intègre dans Qdrant"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Noms des fichiers JSON dans URL_to_ingest/ à traiter. "
             "Si aucun fichier n'est spécifié, le fichier le plus récent est utilisé."
    )
    parser.add_argument(
        "--update-failed",
        action="store_true",
        default=False,
        help="Retraiter les URLs qui ont échoué précédemment."
    )
    return parser.parse_args()


def get_urls_files(file_names: List[str] = None) -> List[Path]:
    """
    Récupère les fichiers d'URLs à traiter dans URL_to_ingest/.

    Args:
        file_names: Liste de noms de fichiers à traiter.
                    Si None ou vide, retourne le fichier le plus récent.

    Returns:
        Liste de Paths des fichiers à traiter

    Raises:
        FileNotFoundError: Si aucun fichier n'est trouvé
    """
    urls_dir = Path("URL_to_ingest")

    if not urls_dir.exists():
        raise FileNotFoundError("Le dossier URL_to_ingest/ n'existe pas")

    if file_names:
        files = []
        for name in file_names:
            file_path = urls_dir / name
            if not file_path.exists():
                raise FileNotFoundError(f"Fichier non trouvé: {file_path}")
            files.append(file_path)
        return files

    json_files = list(urls_dir.glob("urls_*.json"))

    if not json_files:
        raise FileNotFoundError("Aucun fichier urls_*.json trouvé dans URL_to_ingest/")

    latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
    return [latest_file]


def load_urls_from_file(file_path: Path) -> List[str]:
    """
    Charge les URLs depuis un fichier JSON.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        urls = data.get("urls", [])

        if not urls:
            raise ValueError("Le fichier ne contient aucune URL")

        return urls

    except json.JSONDecodeError as e:
        raise ValueError(f"Fichier JSON invalide: {str(e)}")
    except Exception as e:
        raise ValueError(f"Erreur lors de la lecture du fichier: {str(e)}")


async def _process_batch_async(
    batch_idx: int,
    num_batches: int,
    batch_urls: List[str],
    deepseek_client: OpenAI,
    deepinfra_client: OpenAI,
    qdrant_client: QdrantClient,
    config: BlogPipelineConfig,
    historique: HistoriqueManager,
    stats: Dict,
    lock: threading.Lock,
    logger
) -> None:
    """
    Traite un batch d'URLs de manière asynchrone :
    scraping → LLM → embedding → Qdrant.

    Chaque appel crée sa propre instance playwright/browser/crawler.
    Les écritures partagées (stats, historique) sont protégées par un lock.
    """
    batch_label = f"Batch {batch_idx + 1}/{num_batches}"
    logger.info(f"{batch_label}: {len(batch_urls)} URLs")
    print(f"{batch_label} ({len(batch_urls)} articles) - démarrage")

    # Créer des ressources de scraping propres à ce batch
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        args=['--no-sandbox', '--disable-dev-shm-usage']
    )
    context = await browser.new_context()
    crawler = AsyncWebCrawler()
    crawler.browser = browser
    crawler.context = context

    try:
        # --- SCRAPING ---
        try:
            scraped_articles = await scrape_articles_batch(
                batch_urls,
                crawler,
                config.max_concurrent_scrapes,
                config.max_retries
            )

            for article in scraped_articles:
                article["content"] = clean_content(article["content"])

            scraped_urls = {article["url"] for article in scraped_articles}
            with lock:
                stats["articles_scraped"] += len(scraped_articles)
                stats["articles_scrape_failed"] += len(batch_urls) - len(scraped_articles)
                for url in batch_urls:
                    if url not in scraped_urls:
                        historique.add_error(url, "Échec du scraping après retries", "scraping")

            logger.info(f"  {batch_label} Scraped: {len(scraped_articles)}/{len(batch_urls)}")
            print(f"  {batch_label} → Scraped: {len(scraped_articles)}/{len(batch_urls)}")

        except Exception as e:
            logger.error(f"Erreur scraping {batch_label}: {str(e)}")
            with lock:
                stats["articles_scrape_failed"] += len(batch_urls)
                for url in batch_urls:
                    historique.add_error(url, str(e), "scraping_batch")
            return

        if not scraped_articles:
            logger.warning(f"Aucun article scrapé dans {batch_label}")
            return

        # --- LLM PROCESSING ---
        try:
            processed_articles = await process_articles_batch(
                scraped_articles,
                deepseek_client,
                config.deepseek_model,
                config.max_content_length
            )

            processed_urls = {article["url"] for article in processed_articles}
            with lock:
                stats["articles_processed"] += len(processed_articles)
                stats["articles_process_failed"] += len(scraped_articles) - len(processed_articles)
                for article in scraped_articles:
                    if article["url"] not in processed_urls:
                        historique.add_error(
                            article["url"],
                            "Échec du traitement LLM (génération question ou extraction refs)",
                            "llm_processing"
                        )

            logger.info(f"  {batch_label} Processed: {len(processed_articles)}/{len(scraped_articles)}")
            print(f"  {batch_label} → Processed (LLM): {len(processed_articles)}/{len(scraped_articles)}")

        except Exception as e:
            logger.error(f"Erreur traitement LLM {batch_label}: {str(e)}")
            with lock:
                stats["articles_process_failed"] += len(scraped_articles)
                for article in scraped_articles:
                    historique.add_error(article["url"], str(e), "llm_batch")
            return

        if not processed_articles:
            logger.warning(f"Aucun article traité dans {batch_label}")
            return

        # --- EMBEDDING + STOCKAGE QDRANT ---
        try:
            stored_articles = []
            for article in processed_articles:
                try:
                    success, qdrant_ids = await store_article_in_qdrant(
                        article,
                        qdrant_client,
                        deepinfra_client,
                        config.collection_name,
                        config.deepinfra_embedding_model,
                        config.embedding_dimension
                    )

                    if success and qdrant_ids:
                        stored_articles.append(article)
                        with lock:
                            historique.add_success(
                                url=article["url"],
                                qdrant_id=",".join(qdrant_ids),
                                title=article.get("title", ""),
                                date_article=article.get("date", ""),
                                legal_references_count=len(article.get("legal_references", {}).get("codes", {}))
                            )
                        logger.info(f"  ✓ Ingéré dans Qdrant: {article['url']}")
                        print(f"  ✓ Ingéré dans Qdrant: {article['url']}")
                    else:
                        logger.warning(f"  ✗ Échec ingestion Qdrant: {article.get('url')}")
                        print(f"  ✗ Échec ingestion Qdrant: {article.get('url')}")
                        with lock:
                            historique.add_error(
                                article["url"],
                                "Échec du stockage dans Qdrant",
                                "qdrant_storage"
                            )
                except Exception as e:
                    logger.error(f"Erreur stockage article {article.get('url')}: {str(e)}")
                    print(f"  ✗ Erreur ingestion Qdrant: {article.get('url')} ({str(e)[:80]})")
                    with lock:
                        historique.add_error(
                            article.get("url", "unknown"),
                            str(e),
                            "embedding_or_storage"
                        )

            stored_count = len(stored_articles)
            with lock:
                stats["articles_stored"] += stored_count
                stats["articles_store_failed"] += len(processed_articles) - stored_count

            logger.info(f"  {batch_label} Stored: {stored_count}/{len(processed_articles)} (3 points each)")
            print(f"  {batch_label} → Stored (Qdrant): {stored_count}/{len(processed_articles)} articles (3 questions/article)")

        except Exception as e:
            logger.error(f"Erreur stockage {batch_label}: {str(e)}")
            with lock:
                stats["articles_store_failed"] += len(processed_articles)
                for article in processed_articles:
                    historique.add_error(article["url"], str(e), "storage_batch")

    finally:
        # Nettoyage des ressources propres à ce batch
        await context.close()
        await browser.close()
        await pw.stop()
        gc.collect()

    print(f"  {batch_label} ✓ terminé\n")




async def main():
    """
    Fonction principale pour scraper et intégrer les URLs dans Qdrant.
    """
    args = parse_args()

    print("\n" + "="*70)
    print("SCRAPING ET INTÉGRATION DANS QDRANT")
    print(f"  (parallélisme: {MAX_PARALLEL_BATCHES} batches simultanés)")
    print("="*70 + "\n")

    if args.update_failed:
        print("Mode: --update-failed activé (les URLs en échec seront retraitées)\n")

    start_time = datetime.now()

    # ====== 1. INITIALISATION ======
    config = BlogPipelineConfig.from_env()
    if not config.validate():
        print("ERREUR: Configuration invalide. Vérifiez votre fichier .env")
        sys.exit(1)

    logger = setup_logger()
    logger.info("Démarrage du scraping et intégration dans Qdrant")
    logger.info(f"Configuration: {config}")

    stats = {
        "urls_to_process": 0,
        "articles_scraped": 0,
        "articles_scrape_failed": 0,
        "articles_processed": 0,
        "articles_process_failed": 0,
        "articles_stored": 0,
        "articles_store_failed": 0
    }
    lock = threading.Lock()

    historique = HistoriqueManager()
    logger.info("Gestionnaire d'historique initialisé")

    # Initialisation des clients (thread-safe)
    try:
        deepseek_client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url
        )
        deepinfra_client = OpenAI(
            api_key=config.deepinfra_api_key,
            base_url=config.deepinfra_base_url
        )
        qdrant_client = QdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            timeout=config.qdrant_timeout
        )
        logger.info("Clients initialisés: DeepSeek (LLM), DeepInfra (embeddings), Qdrant")
    except Exception as e:
        logger.critical(f"Erreur initialisation clients: {str(e)}")
        sys.exit(1)

    # ====== 1b. HEALTH CHECK QDRANT ======
    logger.info("Vérification de la santé de Qdrant...")
    print("Vérification de la santé de Qdrant...")
    health = check_qdrant_health(qdrant_client, config.collection_name)
    if "error" in health:
        logger.critical(f"Qdrant inaccessible: {health['error']}")
        print(f"ERREUR: Qdrant inaccessible - {health['error']}")
        sys.exit(1)
    print(f"Qdrant OK - latence: {health.get('latency_ms', '?')}ms, points: {health.get('points_count', 'N/A')}")

    # ====== 2. CRÉATION/VÉRIFICATION DE LA COLLECTION QDRANT ======
    logger.info(f"Création/vérification collection: {config.collection_name}")
    print(f"Vérification de la collection Qdrant: {config.collection_name}")
    try:
        success = create_qdrant_collection(
            qdrant_client,
            config.collection_name,
            config.embedding_dimension
        )
        if not success:
            logger.critical("Échec création collection Qdrant")
            sys.exit(1)
        print(f"  → Collection OK\n")
    except Exception as e:
        logger.critical(f"Erreur création collection: {str(e)}")
        sys.exit(1)

    # ====== 3. CHARGEMENT DES URLs DEPUIS LE(S) FICHIER(S) ======
    logger.info("Chargement des URLs depuis le(s) fichier(s)")
    print(f"Étape 1/3: Chargement des URLs")

    try:
        urls_files = get_urls_files(args.files if args.files else None)
        for uf in urls_files:
            logger.info(f"Fichier trouvé: {uf}")
            print(f"  → Fichier: {uf}")

        urls_to_process = []
        for uf in urls_files:
            urls_to_process.extend(load_urls_from_file(uf))

        stats["urls_to_process"] = len(urls_to_process)
        logger.info(f"URLs chargées: {stats['urls_to_process']}")
        print(f"  → {stats['urls_to_process']} URLs chargées au total\n")

    except FileNotFoundError as e:
        logger.error(f"Erreur: {str(e)}")
        print(f"\nERREUR: {str(e)}")
        print("\nVeuillez d'abord exécuter: python update_urls_from_sitemaps.py\n")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Erreur: {str(e)}")
        print(f"\nERREUR: {str(e)}\n")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Erreur chargement URLs: {str(e)}")
        print(f"\nERREUR CRITIQUE: {str(e)}\n")
        sys.exit(1)

    if stats["urls_to_process"] == 0:
        logger.info("Aucune URL à traiter")
        print("Aucune URL à traiter. Pipeline terminée.\n")
        return

    # ====== 3bis. FILTRAGE DES URLs DÉJÀ TRAITÉES ======
    if args.update_failed:
        urls_to_skip = historique.get_success_urls()
        logger.info("Mode --update-failed: seules les URLs en succès sont ignorées")
    else:
        urls_to_skip = historique.get_processed_urls()

    urls_to_process = [
        url for url in urls_to_process
        if normalize_url(url) not in urls_to_skip
    ]
    skipped = stats["urls_to_process"] - len(urls_to_process)
    if skipped > 0:
        logger.info(f"URLs déjà traitées (ignorées): {skipped}")
        print(f"  → {skipped} URLs déjà traitées (ignorées)")
    stats["urls_to_process"] = len(urls_to_process)
    print(f"  → {len(urls_to_process)} URLs restantes à traiter\n")

    if len(urls_to_process) == 0:
        logger.info("Toutes les URLs ont déjà été traitées")
        print("Toutes les URLs ont déjà été traitées. Pipeline terminée.\n")
        return

    # ====== 4. TRAITEMENT PAR BATCHES EN PARALLÈLE ======
    num_batches = (len(urls_to_process) + config.batch_size - 1) // config.batch_size
    print(f"Étape 2/3: Traitement des articles ({num_batches} batches de {config.batch_size}, "
          f"{MAX_PARALLEL_BATCHES} en parallèle)")
    print(f"  Scraping → LLM Processing → Embedding → Qdrant Storage\n")

    # Préparer les batches
    batches = []
    for batch_idx in range(num_batches):
        batch_start = batch_idx * config.batch_size
        batch_end = min(batch_start + config.batch_size, len(urls_to_process))
        batches.append((batch_idx, urls_to_process[batch_start:batch_end]))

    # Exécuter les batches en parallèle avec asyncio.Semaphore
    semaphore = asyncio.Semaphore(MAX_PARALLEL_BATCHES)

    async def run_batch_with_semaphore(batch_idx, batch_urls):
        async with semaphore:
            await _process_batch_async(
                batch_idx, num_batches, batch_urls,
                deepseek_client, deepinfra_client, qdrant_client,
                config, historique, stats, lock, logger
            )

    try:
        results = await asyncio.gather(
            *(run_batch_with_semaphore(batch_idx, batch_urls) for batch_idx, batch_urls in batches),
            return_exceptions=True
        )

        for (batch_idx, _), result in zip(batches, results):
            if isinstance(result, Exception):
                logger.error(f"Erreur critique batch {batch_idx + 1}: {str(result)}")
                print(f"  Batch {batch_idx + 1}/{num_batches} ✗ erreur: {str(result)}")

    except Exception as e:
        logger.critical(f"Erreur critique pendant le traitement: {str(e)}")
        raise

    finally:
        # ====== 5. NETTOYAGE DES RESSOURCES ======
        logger.info("Nettoyage des ressources")
        historique.close()
        gc.collect()

    # ====== 6. STATISTIQUES FINALES ======
    end_time = datetime.now()
    duration = end_time - start_time

    hist_stats = historique.get_stats()

    print("="*70)
    print("TRAITEMENT TERMINÉ")
    print("="*70)
    print(f"\nDurée totale: {duration}")
    print(f"\nStatistiques:")
    print(f"  URLs à traiter: {stats['urls_to_process']}")
    print(f"\n  Articles scrapés: {stats['articles_scraped']}")
    print(f"  Articles échec scraping: {stats['articles_scrape_failed']}")
    print(f"\n  Articles traités (LLM): {stats['articles_processed']}")
    print(f"  Articles échec LLM: {stats['articles_process_failed']}")
    print(f"\n  Articles stockés (Qdrant): {stats['articles_stored']}")
    print(f"  Articles échec stockage: {stats['articles_store_failed']}")
    print(f"\n📊 Historique:")
    print(f"  Total URLs historique: {hist_stats.get('total_urls', 0)}")
    print(f"  Taux de succès global: {hist_stats.get('stats', {}).get('success_rate', 'N/A')}")
    print(f"  Fichier: historique_savings/historique_urls.db")
    print("\n" + "="*70 + "\n")

    logger.info(f"Pipeline terminée. Durée: {duration}")
    logger.info(f"Stats finales: {stats}")
    logger.info(f"Stats historique: {hist_stats}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nPipeline interrompue par l'utilisateur (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\nERREUR CRITIQUE: {str(e)}")
        sys.exit(1)
