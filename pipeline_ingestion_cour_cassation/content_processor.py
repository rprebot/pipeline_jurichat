"""
Traitement du contenu des decisions : resume DeepSeek, generation de questions et extraction des references juridiques.
Reutilise la meme technique d'extraction regex que le pipeline blogs.
"""

import json
import logging
from typing import Dict, List

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from prompts import DECISION_SUMMARY_PROMPT, DECISION_QUESTIONS_PROMPT

from juridic_reference_extraction import extract_legal_references_regex

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception),
)
def generate_summary(
    text: str,
    client: OpenAI,
    model: str = "deepseek-chat",
    max_content_length: int = 50000,
) -> str:
    """
    Genere un resume de la decision via l'API DeepSeek.

    Args:
        text: Texte complet de la decision
        client: Client OpenAI-compatible (DeepSeek)
        model: Modele LLM
        max_content_length: Longueur max du texte envoye

    Returns:
        Resume genere
    """
    truncated_text = text[:max_content_length]
    prompt = DECISION_SUMMARY_PROMPT.format(text=truncated_text)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.3,
    )

    summary = response.choices[0].message.content.strip()
    logger.info(f"Resume genere ({len(summary)} chars)")
    return summary


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception),
)
def generate_questions_from_summary(
    summary: str,
    client: OpenAI,
    model: str = "deepseek-chat",
) -> List[str]:
    """
    Genere 3 questions potentielles a partir du resume d'une decision.

    Args:
        summary: Resume de la decision
        client: Client OpenAI-compatible (DeepSeek)
        model: Modele LLM

    Returns:
        Liste de 3 questions generees
    """
    prompt = DECISION_QUESTIONS_PROMPT.format(summary=summary)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.4,
    )

    response_text = response.choices[0].message.content.strip()

    # Nettoyer les backticks markdown si presents
    if response_text.startswith("```"):
        response_text = response_text.replace("```json", "").replace("```", "").strip()

    # Parser la reponse JSON
    questions = json.loads(response_text)

    if not isinstance(questions, list):
        raise ValueError("La reponse n'est pas une liste JSON")

    if len(questions) == 0:
        raise ValueError("Aucune question generee")

    # Completer ou tronquer a 3 questions
    while len(questions) < 3:
        questions.append(questions[0])
    questions = questions[:3]

    # Validation de chaque question
    validated = []
    for q in questions:
        q = str(q).strip()
        if not q.endswith("?"):
            q += " ?"
        validated.append(q)

    logger.info(f"3 questions generees a partir du resume")
    return validated


def extract_references(text: str) -> Dict:
    """
    Extrait les references juridiques du texte de la decision.
    Utilise la meme fonction regex que le pipeline blogs.

    Args:
        text: Texte complet de la decision

    Returns:
        Dict avec codes, cour_cassation, cour_appel
    """
    try:
        return extract_legal_references_regex(text)
    except Exception as e:
        logger.error(f"Erreur extraction references: {e}")
        return {"codes": {}, "cour_cassation": [], "cour_appel": []}
