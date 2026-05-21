"""
Test du traitement de contenu avec extraction REGEX.
"""

import sys
import asyncio
from pathlib import Path

# Ajouter le parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline_ingestion_blogs.content_processor import (
    extract_legal_references_regex,
    process_article_content
)
from dotenv import load_dotenv
from openai import OpenAI
import os

load_dotenv()


async def test_content_processing():
    """Test du traitement complet d'un article avec REGEX."""

    print("\n" + "="*70)
    print("TEST DU TRAITEMENT DE CONTENU AVEC REGEX")
    print("="*70 + "\n")

    # Mock article data
    article_data = {
        "url": "https://example.com/test-article",
        "title": "Les obligations de l'employeur en matière de formation",
        "content": """
        Selon les dispositions du Code du travail, l'employeur doit assurer
        l'adaptation des salariés à leur poste de travail (article L. 6321-1
        du Code du travail).

        Le Code de l'éducation et le Code civil contiennent également des
        dispositions applicables en matière de formation professionnelle.
        """,
        "date": "2024-01-15"
    }

    # Test 1: Extraction REGEX seule
    print("Test 1: Extraction REGEX des codes juridiques")
    content_text = "\n".join([article_data["content"]])
    result = extract_legal_references_regex(content_text)
    codes = result["codes"]
    print(f"  Codes trouvés: {codes}")
    expected_codes = ["Code du travail", "Code de l'éducation", "Code civil"]
    for code in expected_codes:
        assert code in codes, f"Code manquant: {code}"
    print("  ✓ Tous les codes attendus sont présents\n")

    # Test 2: Traitement complet avec GPT-4o (question generation)
    print("Test 2: Traitement complet (REGEX + GPT-4o)")
    print("  Extraction: REGEX (gratuit, rapide)")
    print("  Question: GPT-4o (1 appel API)\n")

    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
        enriched_article = await process_article_content(
            article_data,
            openai_client,
            model="gpt-4o"
        )

        print(f"  Legal references (REGEX): {enriched_article['legal_references']}")
        print(f"  Potential questions (LLM): {enriched_article['potential_questions']}")

        # Vérifications
        assert "legal_references" in enriched_article
        assert "potential_questions" in enriched_article
        assert "full_content" in enriched_article

        legal_refs = enriched_article["legal_references"]
        assert isinstance(legal_refs, dict), "legal_references doit être un Dict"
        assert "codes" in legal_refs, "legal_references doit contenir la clé 'codes'"
        assert len(legal_refs["codes"]) >= 3

        questions = enriched_article["potential_questions"]
        assert isinstance(questions, list), "potential_questions doit être une liste"
        assert len(questions) == 3

        print("\n  ✓ Article enrichi avec succès")
        print(f"    - {len(legal_refs['codes'])} codes juridiques")
        print(f"    - {len(questions)} questions générées")

    except Exception as e:
        print(f"  ❌ Erreur: {str(e)}")
        raise

    print("\n" + "="*70)
    print("✅ TEST RÉUSSI - REGEX FONCTIONNE CORRECTEMENT")
    print("="*70)

    print("\nAvantages du REGEX vs LLM pour l'extraction:")
    print("  1. Vitesse: ~1000x plus rapide (0.001s vs 2-5s)")
    print("  2. Coût: Gratuit (vs ~$0.002 par article)")
    print("  3. Précision: Détecte uniquement les mentions explicites")
    print("  4. Fiabilité: Pas de dépendance à l'API OpenAI")
    print("  5. Passage à l'échelle: Traiter 10,000 articles = même vitesse")
    print()


if __name__ == "__main__":
    asyncio.run(test_content_processing())
