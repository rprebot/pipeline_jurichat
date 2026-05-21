"""
Script de test pour la pipeline d'ingestion.
Teste sur un petit échantillon de 2 sitemaps et maximum 5 articles.
"""

import asyncio
import sys
from pipeline_ingestion_blogs.config import BlogPipelineConfig
from pipeline_ingestion_blogs.logger import setup_logger
from pipeline_ingestion_blogs.sitemap_parser import extract_all_article_urls
from pipeline_ingestion_blogs.url_utils import is_valid_url

async def test_pipeline():
    """Test de la pipeline sur un petit échantillon."""

    print("\n" + "="*60)
    print("TEST DE LA PIPELINE D'INGESTION")
    print("="*60 + "\n")

    # Configuration
    config = BlogPipelineConfig.from_env()
    if not config.validate():
        print("❌ Configuration invalide. Vérifiez votre fichier .env")
        return False

    print("✓ Configuration valide")
    print(f"  - DeepSeek Model: {config.deepseek_model}")
    print(f"  - Embedding Model: {config.openai_embedding_model}")
    print(f"  - Embedding Dimension: {config.embedding_dimension}")
    print(f"  - Qdrant Collection: {config.collection_name}\n")

    # Logger
    logger = setup_logger("test_pipeline", "test_pipeline.log")
    logger.info("Démarrage du test de la pipeline")

    # Test 1: Parse quelques sitemaps
    print("Test 1: Parsing de sitemaps")
    print("-" * 60)

    test_sitemaps = [
        "https://www.cabinetaci.com/post-sitemap.xml",
        "https://www.lekbinet.com/sitemap.xml"
    ]

    try:
        print(f"Parsing de {len(test_sitemaps)} sitemaps...")
        article_urls = await extract_all_article_urls(test_sitemaps, max_concurrent=2)
        print(f"✓ {len(article_urls)} URLs extraites")

        # Afficher les 5 premières URLs
        valid_urls = [url for url in list(article_urls)[:10] if is_valid_url(url)]
        print(f"\nPremières URLs extraites:")
        for i, url in enumerate(valid_urls[:5], 1):
            print(f"  {i}. {url}")

    except Exception as e:
        print(f"❌ Erreur parsing sitemaps: {str(e)}")
        logger.error(f"Erreur test parsing: {str(e)}")
        return False

    # Test 2: Test OpenAI client
    print("\n\nTest 2: Connexion OpenAI")
    print("-" * 60)

    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=config.together_api_key,
            base_url=config.together_base_url
        )

        # Test simple
        print("Test simple de l'API OpenAI...")
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",  # Utiliser le modèle mini pour le test
            messages=[{"role": "user", "content": "Dis juste 'OK' si tu me reçois."}],
            max_tokens=10
        )
        result = response.choices[0].message.content.strip()
        print(f"✓ OpenAI répond: {result}")

    except Exception as e:
        print(f"❌ Erreur OpenAI: {str(e)}")
        logger.error(f"Erreur test OpenAI: {str(e)}")
        return False

    # Test 3: Test Qdrant
    print("\n\nTest 3: Connexion Qdrant")
    print("-" * 60)

    try:
        from qdrant_client import QdrantClient
        qdrant_client = QdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            timeout=config.qdrant_timeout
        )

        # Lister les collections
        collections = qdrant_client.get_collections()
        print(f"✓ Qdrant connecté")
        print(f"  Collections existantes: {len(collections.collections)}")
        for c in collections.collections[:5]:
            count = qdrant_client.count(c.name).count
            print(f"    - {c.name}: {count} points")

    except Exception as e:
        print(f"❌ Erreur Qdrant: {str(e)}")
        logger.error(f"Erreur test Qdrant: {str(e)}")
        return False

    # Test 4: Test embedding
    print("\n\nTest 4: Génération d'embedding")
    print("-" * 60)

    try:
        print("Génération d'un embedding de test...")
        test_text = "Quelles sont les obligations de l'employeur en matière de sécurité?"

        response = await asyncio.to_thread(
            client.embeddings.create,
            input=test_text,
            model=config.openai_embedding_model,
            dimensions=config.embedding_dimension
        )

        embedding = response.data[0].embedding
        print(f"✓ Embedding généré: {len(embedding)} dimensions")

    except Exception as e:
        print(f"❌ Erreur embedding: {str(e)}")
        logger.error(f"Erreur test embedding: {str(e)}")
        return False

    # Résumé
    print("\n" + "="*60)
    print("RÉSUMÉ DU TEST")
    print("="*60)
    print("✓ Tous les tests sont passés avec succès!")
    print("\nLa pipeline est prête à être lancée:")
    print("  python -m pipeline_ingestion_blogs.main")
    print("="*60 + "\n")

    return True

if __name__ == "__main__":
    try:
        success = asyncio.run(test_pipeline())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrompu par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERREUR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
