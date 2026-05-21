"""
Test de la génération de 3 questions et création de 3 points Qdrant.
"""

import sys
import asyncio
from pathlib import Path

# Ajouter le parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline_ingestion_blogs.content_processor import generate_potential_questions
from dotenv import load_dotenv
from openai import OpenAI
import os

load_dotenv()


async def test_3_questions():
    """Test de la génération de 3 questions potentielles."""

    print("\n" + "="*70)
    print("TEST GÉNÉRATION DE 3 QUESTIONS")
    print("="*70 + "\n")

    # Article de test
    title = "Les obligations de l'employeur en matière de formation professionnelle"
    content = """
    Le Code du travail impose à l'employeur d'assurer l'adaptation des salariés
    à leur poste de travail et de veiller au maintien de leur capacité à occuper
    un emploi. L'employeur doit proposer des formations adaptées.

    Les salariés bénéficient d'un compte personnel de formation (CPF) qui leur
    permet de suivre des formations qualifiantes. Le CPF est alimenté chaque année
    en fonction du temps de travail.

    L'employeur peut également mettre en place un plan de développement des
    compétences pour ses salariés. Ce plan peut inclure des actions de formation,
    des bilans de compétences, ou des validations des acquis de l'expérience (VAE).
    """

    # Configuration DeepSeek
    deepseek_client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )

    try:
        print("Génération de 3 questions avec DeepSeek...\n")
        questions = await generate_potential_questions(
            title=title,
            content=content,
            client=deepseek_client,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        )

        print(f"✅ {len(questions)} questions générées:\n")
        for i, q in enumerate(questions, 1):
            print(f"  Question {i}: {q}")

            # Validations
            assert q.endswith("?"), f"Question {i} ne se termine pas par '?'"
            word_count = len(q.split())
            assert 5 <= word_count <= 30, f"Question {i} hors limites: {word_count} mots"

        print()

        # Vérifier que les questions sont différentes
        assert questions[0] != questions[1], "Question 1 et 2 sont identiques!"
        assert questions[1] != questions[2], "Question 2 et 3 sont identiques!"
        assert questions[0] != questions[2], "Question 1 et 3 sont identiques!"
        print("✅ Les 3 questions sont bien différentes")

        print("\n" + "="*70)
        print("✅ TEST RÉUSSI")
        print("="*70)

    except Exception as e:
        print(f"❌ ERREUR: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(test_3_questions())
