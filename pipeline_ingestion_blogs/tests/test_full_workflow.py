"""
Test complet du workflow sur un petit échantillon d'articles.
Teste : Scraping → LLM Processing → Embedding → Qdrant Storage
"""

import asyncio
import sys
import gc
from datetime import datetime
import aiohttp
from openai import OpenAI
from qdrant_client import QdrantClient
from crawl4ai import AsyncWebCrawler
from playwright.async_api import async_playwright

from pipeline_ingestion_blogs.config import BlogPipelineConfig
from pipeline_ingestion_blogs.logger import setup_logger
from pipeline_ingestion_blogs.sitemap_parser import extract_all_article_urls
from pipeline_ingestion_blogs.article_scraper import scrape_articles_batch, clean_content
from pipeline_ingestion_blogs.content_processor import process_articles_batch
from pipeline_ingestion_blogs.vector_store import (
    create_qdrant_collection,
    get_existing_urls,
    store_articles_batch
)
from pipeline_ingestion_blogs.url_utils import normalize_url, is_valid_url


async def test_full_workflow():
    """Test complet sur 5-10 articles."""

    print("\n" + "="*70)
    print("TEST COMPLET DU WORKFLOW (5-10 articles)")
    print("="*70 + "\n")

    start_time = datetime.now()

    # Configuration
    config = BlogPipelineConfig.from_env()
    if not config.validate():
        print("❌ Configuration invalide")
        return False

    logger = setup_logger("test_workflow", "test_workflow.log")
    logger.info("Démarrage du test complet")

    # Stats
    stats = {
        "urls_extracted": 0,
        "urls_to_test": 0,
        "articles_scraped": 0,
        "articles_processed": 0,
        "articles_stored": 0
    }

    # Initialisation clients
    print("Initialisation des clients...")
    try:
        openai_client = OpenAI(
            api_key=config.together_api_key,
            base_url=config.together_base_url
        )
        qdrant_client = QdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            timeout=config.qdrant_timeout
        )
        print("✓ Clients OpenAI et Qdrant initialisés\n")
    except Exception as e:
        print(f"❌ Erreur initialisation clients: {str(e)}")
        return False

    # Créer collection
    print(f"Création de la collection '{config.collection_name}'...")
    try:
        create_qdrant_collection(
            qdrant_client,
            config.collection_name,
            config.embedding_dimension
        )
        print(f"✓ Collection '{config.collection_name}' prête\n")
    except Exception as e:
        print(f"❌ Erreur création collection: {str(e)}")
        return False

    # Parse 2 sitemaps
    print("Étape 1/5: Parsing de 2 sitemaps de test")
    print("-" * 70)
    test_sitemaps = [
        "https://www.cabinetaci.com/post-sitemap.xml",
        "https://www.lekbinet.com/sitemap.xml"
    ]

    try:
        article_urls = await extract_all_article_urls(test_sitemaps, max_concurrent=2)
        stats["urls_extracted"] = len(article_urls)
        print(f"✓ {stats['urls_extracted']} URLs extraites\n")
    except Exception as e:
        print(f"❌ Erreur parsing: {str(e)}")
        return False

    # Prendre les 10 premières URLs valides
    test_urls = [url for url in list(article_urls)[:15] if is_valid_url(url)][:10]
    stats["urls_to_test"] = len(test_urls)

    print(f"URLs de test sélectionnées ({stats['urls_to_test']}):")
    for i, url in enumerate(test_urls, 1):
        print(f"  {i}. {url}")
    print()

    # Vérifier URLs existantes
    print("Étape 2/5: Vérification déduplication")
    print("-" * 70)
    try:
        existing_urls = await get_existing_urls(qdrant_client, config.collection_name)
        print(f"✓ {len(existing_urls)} URLs déjà présentes dans Qdrant")

        # Filtrer
        test_urls = [url for url in test_urls if normalize_url(url) not in existing_urls]
        print(f"✓ {len(test_urls)} nouvelles URLs à traiter\n")

        if len(test_urls) == 0:
            print("Aucune nouvelle URL à traiter (toutes déjà présentes)")
            return True

    except Exception as e:
        print(f"⚠ Erreur déduplication: {str(e)}, on continue sans filtrage\n")

    # Initialisation ressources scraping
    playwright = None
    browser = None
    crawler = None
    session = None

    try:
        # Initialiser Playwright
        print("Initialisation du navigateur...")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context()

        crawler = AsyncWebCrawler()
        crawler.browser = browser
        crawler.context = context

        session = aiohttp.ClientSession()
        print("✓ Navigateur prêt\n")

        # Scraping
        print("Étape 3/5: Scraping des articles")
        print("-" * 70)

        scraped_articles = await scrape_articles_batch(
            test_urls,
            crawler,
            session,
            max_concurrent=3,
            max_retries=2
        )

        # Nettoyer
        for article in scraped_articles:
            article["content"] = clean_content(article["content"])

        stats["articles_scraped"] = len(scraped_articles)
        print(f"✓ {stats['articles_scraped']}/{len(test_urls)} articles scrapés avec succès\n")

        if stats["articles_scraped"] == 0:
            print("❌ Aucun article scrapé")
            return False

        # Afficher un échantillon
        print("Échantillon du premier article scrapé:")
        if scraped_articles:
            first = scraped_articles[0]
            print(f"  Titre: {first.get('title', 'N/A')[:80]}")
            print(f"  URL: {first.get('url', 'N/A')}")
            print(f"  Date: {first.get('date', 'N/A')}")
            print(f"  Sections: {len(first.get('content', []))}")
            if first.get('content'):
                print(f"  Premier paragraphe: {first['content'][0].get('contenu_paragraphe', '')[:100]}...")
        print()

        # LLM Processing
        print("Étape 4/5: Traitement LLM (extraction refs + questions)")
        print("-" * 70)
        print("⚠ Cette étape peut prendre 1-2 minutes (appels GPT-4o)...\n")

        processed_articles = await process_articles_batch(
            scraped_articles,
            openai_client,
            config.openai_model,
            config.max_content_length
        )

        stats["articles_processed"] = len(processed_articles)
        print(f"✓ {stats['articles_processed']}/{stats['articles_scraped']} articles traités\n")

        if stats["articles_processed"] == 0:
            print("❌ Aucun article traité")
            return False

        # Afficher résultats LLM
        print("Résultats du traitement LLM:")
        for i, article in enumerate(processed_articles[:3], 1):
            print(f"\n  Article {i}: {article.get('title', 'N/A')[:60]}")
            print(f"    Question: {article.get('potential_question', 'N/A')}")
            refs = article.get('legal_references', [])
            print(f"    Références juridiques: {', '.join(refs) if refs else 'Aucune'}")
        print()

        # Embedding + Stockage
        print("Étape 5/5: Embedding et stockage dans Qdrant")
        print("-" * 70)
        print("⚠ Génération des embeddings en cours...\n")

        stored_count = await store_articles_batch(
            processed_articles,
            qdrant_client,
            openai_client,
            config.collection_name,
            config.openai_embedding_model,
            config.embedding_dimension
        )

        stats["articles_stored"] = stored_count
        print(f"✓ {stats['articles_stored']}/{stats['articles_processed']} articles stockés\n")

        # Vérification finale
        print("Vérification dans Qdrant:")
        try:
            count = qdrant_client.count(config.collection_name).count
            print(f"  Total d'articles dans '{config.collection_name}': {count}")

            # Récupérer un point pour vérifier
            points, _ = qdrant_client.scroll(config.collection_name, limit=1, with_payload=True)
            if points:
                print(f"\n  Exemple de point stocké:")
                payload = points[0].payload
                print(f"    URL: {payload.get('url', 'N/A')}")
                print(f"    Question: {payload.get('potential_question', 'N/A')[:80]}...")
                print(f"    Refs juridiques: {len(payload.get('legal_references', []))} codes")
                print(f"    Date: {payload.get('date', 'N/A')}")
        except Exception as e:
            print(f"  ⚠ Erreur vérification: {str(e)}")

    except Exception as e:
        print(f"\n❌ Erreur pendant le test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Nettoyage
        print("\nNettoyage des ressources...")
        if session:
            await session.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()
        gc.collect()
        print("✓ Nettoyage terminé")

    # Résumé
    duration = datetime.now() - start_time

    print("\n" + "="*70)
    print("TEST TERMINÉ AVEC SUCCÈS!")
    print("="*70)
    print(f"\nDurée: {duration}")
    print(f"\nStatistiques:")
    print(f"  URLs extraites: {stats['urls_extracted']}")
    print(f"  URLs testées: {stats['urls_to_test']}")
    print(f"  Articles scrapés: {stats['articles_scraped']}")
    print(f"  Articles traités (LLM): {stats['articles_processed']}")
    print(f"  Articles stockés (Qdrant): {stats['articles_stored']}")

    success_rate = (stats['articles_stored'] / stats['urls_to_test'] * 100) if stats['urls_to_test'] > 0 else 0
    print(f"\nTaux de succès: {success_rate:.1f}%")

    print("\n✅ La pipeline fonctionne correctement!")
    print("\nPour lancer la pipeline complète:")
    print("  python -m pipeline_ingestion_blogs.main")
    print("="*70 + "\n")

    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(test_full_workflow())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrompu par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERREUR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
