"""
Test end-to-end : Génération de 3 questions → Création de 3 points Qdrant.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline_ingestion_blogs.content_processor import process_article_content
from pipeline_ingestion_blogs.vector_store import store_article_in_qdrant
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
import os

load_dotenv()


async def test_3_points_qdrant():
    """Test complet : article → 3 questions → 3 points Qdrant."""

    print("\n" + "="*70)
    print("TEST END-TO-END : 3 POINTS QDRANT PAR ARTICLE")
    print("="*70 + "\n")

    # Mock article
    article_data = {
        "url": "https://test-example.com/article-test-3q",
        "title": "Test: Formation professionnelle",
        "content": """
        Le Code du travail impose à l'employeur d'assurer la formation.
        Les salariés bénéficient du CPF. L'employeur peut mettre en place
        un plan de développement des compétences.
        """,
        "date": "2024-01-15"
    }

    # Clients
    deepseek_client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )

    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    qdrant_client = QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY")
    )

    try:
        # Étape 1 : Traitement de contenu (REGEX + 3 questions)
        print("Étape 1: Traitement de contenu (REGEX + DeepSeek)...")
        enriched_article = await process_article_content(
            article_data,
            deepseek_client,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        )

        print(f"  ✅ Legal references: {enriched_article['legal_references']}")
        print(f"  ✅ Questions générées: {len(enriched_article['potential_questions'])}")
        for i, q in enumerate(enriched_article['potential_questions'], 1):
            print(f"     {i}. {q}")

        assert len(enriched_article['potential_questions']) == 3
        print()

        # Étape 2 : Stockage Qdrant (3 embeddings + 3 points)
        print("Étape 2: Stockage dans Qdrant (3 embeddings + 3 points)...")
        success, qdrant_ids = await store_article_in_qdrant(
            enriched_article,
            qdrant_client,
            openai_client,
            collection_name="articles_blog",
            embedding_model="text-embedding-3-large",
            embedding_dimension=256
        )

        assert success, "Échec du stockage dans Qdrant"
        assert len(qdrant_ids) == 3, f"Expected 3 IDs, got {len(qdrant_ids)}"

        print(f"  ✅ 3 points créés dans Qdrant:")
        for i, qid in enumerate(qdrant_ids, 1):
            print(f"     {i}. ID: {qid}")
        print()

        # Étape 3 : Vérification dans Qdrant
        print("Étape 3: Vérification des points dans Qdrant...")
        for i, point_id in enumerate(qdrant_ids, 1):
            # Récupérer le point avec vecteur
            point = qdrant_client.retrieve(
                collection_name="articles_blog",
                ids=[point_id],
                with_vectors=True
            )[0]

            print(f"\n  Point {i}:")
            print(f"    ID: {point.id}")
            print(f"    URL: {point.payload['url']}")
            print(f"    Question: {point.payload['potential_question']}")
            print(f"    Question index: {point.payload['question_index']}")
            print(f"    Vector dimension: {len(point.vector) if point.vector else 'N/A'}")

            # Validations
            assert "test-example.com" in point.payload['url']
            assert point.payload['question_index'] == i
            if point.vector:
                assert len(point.vector) == 256

        print("\n" + "="*70)
        print("✅ TEST RÉUSSI - 3 POINTS CRÉÉS ET VÉRIFIÉS")
        print("="*70)
        print("\nRésumé:")
        print(f"  - 1 article traité")
        print(f"  - 3 questions générées (DeepSeek)")
        print(f"  - 3 embeddings créés (OpenAI)")
        print(f"  - 3 points stockés dans Qdrant")
        print(f"  - Tous les points vérifiés ✓")

        # Nettoyage
        print("\nNettoyage: Suppression des points de test...")
        qdrant_client.delete(
            collection_name="articles_blog",
            points_selector=qdrant_ids
        )
        print("  ✅ Points de test supprimés")

    except Exception as e:
        print(f"\n❌ ERREUR: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(test_3_points_qdrant())
