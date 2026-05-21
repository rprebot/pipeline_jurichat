"""
Module pour traiter le contenu des articles avec GPT-4o.
Extraction de références juridiques (REGEX) et génération de questions potentielles (LLM).
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from prompts import QUESTION_GENERATION_PROMPT

from juridic_reference_extraction import extract_legal_references_regex

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception)
)
async def generate_potential_questions(
    title: str,
    content: str,
    client: OpenAI,
    model: str = "deepseek-chat",
    max_content_length: int = 50000
) -> List[str]:
    """
    Génère 3 questions potentielles à partir d'un article en utilisant un LLM.

    Args:
        title: Titre de l'article
        content: Contenu de l'article
        client: Client OpenAI-compatible (DeepSeek, OpenAI, etc.)
        model: Modèle LLM à utiliser (ex: "deepseek-chat", "gpt-4o")
        max_content_length: Longueur max du contenu à envoyer

    Returns:
        Liste de 3 questions générées (List[str])

    Raises:
        Exception: Si la génération échoue
    """
    try:
        # Limiter la longueur du contenu
        truncated_content = content[:max_content_length]

        # Préparer le prompt
        prompt = QUESTION_GENERATION_PROMPT.format(
            title=title,
            content=truncated_content
        )

        # Appel API OpenAI
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,  # Plus de tokens pour 3 questions
            temperature=0.4  # Un peu plus de créativité pour la diversité
        )

        response_text = response.choices[0].message.content.strip()

        # Nettoyer les backticks markdown si présents
        if response_text.startswith("```"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()

        # Parser la réponse JSON
        try:
            questions = json.loads(response_text)

            # Validation
            if not isinstance(questions, list):
                logger.warning(f"Réponse LLM n'est pas une liste: {response_text}")
                raise ValueError("La réponse n'est pas une liste JSON")

            if len(questions) != 3:
                logger.warning(f"Nombre de questions incorrect: {len(questions)} (attendu: 3)")
                # Si on a au moins 1 question, on complète avec des variations
                if len(questions) == 0:
                    raise ValueError("Aucune question générée")
                # Prendre les 3 premières ou dupliquer si moins de 3
                while len(questions) < 3:
                    questions.append(questions[0])
                questions = questions[:3]

            # Validation de chaque question
            validated_questions = []
            for i, q in enumerate(questions):
                if not isinstance(q, str):
                    q = str(q)
                q = q.strip()

                if not q.endswith('?'):
                    logger.warning(f"Question {i+1} ne se termine pas par '?': {q}")
                    q += " ?"

                validated_questions.append(q)

            logger.info(f"3 questions générées: {validated_questions}")
            return validated_questions

        except json.JSONDecodeError:
            logger.warning(f"Impossible de parser la réponse JSON: {response_text}")
            raise ValueError("Réponse JSON invalide")

    except Exception as e:
        logger.error(f"Erreur lors de la génération des questions: {str(e)}")
        raise


async def process_article_content(
    article_data: Dict,
    client: OpenAI,
    model: str = "deepseek-chat",
    max_content_length: int = 50000
) -> Dict:
    """
    Traite le contenu d'un article : extraction refs (REGEX) + génération question (LLM).

    Args:
        article_data: Dict avec url, title, content, date
        client: Client OpenAI-compatible (DeepSeek, OpenAI, etc.)
        model: Modèle LLM à utiliser (ex: "deepseek-chat", "gpt-4o")
        max_content_length: Longueur max du contenu

    Returns:
        Dict enrichi avec legal_references (REGEX) et potential_question (LLM)

    Raises:
        Exception: Si le traitement échoue
    """
    try:
        # Convertir le contenu structuré en texte
        if isinstance(article_data.get("content"), list):
            content_text = "\n\n".join([
                f"{section.get('titre_paragraphe', '')}\n{section.get('contenu_paragraphe', '')}"
                for section in article_data["content"]
            ])
        else:
            content_text = str(article_data.get("content", ""))

        # Extraction des références juridiques avec REGEX (rapide, pas d'API call)
        legal_refs = []
        try:
            legal_refs = extract_legal_references_regex(content_text)
        except Exception as e:
            logger.error(f"Échec extraction références pour {article_data['url']}: {str(e)}")
            # Continuer avec liste vide

        # Génération des 3 questions (critique, doit réussir)
        questions = await generate_potential_questions(
            article_data.get("title", ""),
            content_text,
            client,
            model,
            max_content_length
        )

        # Enrichir l'article
        article_data["legal_references"] = legal_refs
        article_data["potential_questions"] = questions  # Liste de 3 questions
        article_data["full_content"] = content_text

        return article_data

    except Exception as e:
        logger.error(f"Erreur lors du traitement du contenu pour {article_data.get('url')}: {str(e)}")
        raise


async def process_articles_batch(
    articles: List[Dict],
    client: OpenAI,
    model: str = "deepseek-chat",
    max_content_length: int = 50000
) -> List[Dict]:
    """
    Traite un batch d'articles avec les appels LLM en parallèle.

    Args:
        articles: Liste d'articles à traiter
        client: Client OpenAI-compatible (DeepSeek, OpenAI, etc.)
        model: Modèle LLM (ex: "deepseek-chat", "gpt-4o")
        max_content_length: Longueur max du contenu

    Returns:
        Liste d'articles enrichis (excluant les échecs)
    """
    async def process_with_error_handling(article: Dict) -> Optional[Dict]:
        """Wrapper pour gérer les erreurs individuellement."""
        try:
            return await process_article_content(
                article,
                client,
                model,
                max_content_length
            )
        except Exception as e:
            logger.error(f"Échec traitement article {article.get('url')}: {str(e)}")
            return None

    # Traiter tous les articles en parallèle
    results = await asyncio.gather(*[
        process_with_error_handling(article)
        for article in articles
    ])

    # Filtrer les None (échecs)
    return [result for result in results if result is not None]
