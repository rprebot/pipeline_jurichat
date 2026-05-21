"""
Pipeline RAG : embedding de la query, recherche Qdrant multi-collections, construction du contexte.
"""

import logging
from typing import AsyncIterator, Dict, List, Optional

from openai import OpenAI
from qdrant_client import QdrantClient, models

from .config import WebAppConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es JuriChat, un assistant juridique expert en droit social français.
Tu réponds aux questions des utilisateurs en te basant EXCLUSIVEMENT sur les documents fournis dans le contexte.

Règles :
- Réponds de manière claire, structurée et précise.
- Cite tes sources (articles de loi, décisions de justice, URL) quand c'est pertinent.
- Si le contexte ne contient pas assez d'informations pour répondre, dis-le clairement.
- Ne fabrique jamais de références juridiques.
- Utilise un langage professionnel mais accessible.
- Structure ta réponse avec des titres et des listes si nécessaire."""


def create_clients(config: WebAppConfig):
    """Crée les clients Qdrant et DeepInfra."""
    qdrant_client = QdrantClient(
        url=config.qdrant_url,
        api_key=config.qdrant_api_key,
        timeout=60,
    )

    embedding_client = OpenAI(
        api_key=config.deepinfra_api_key,
        base_url=config.deepinfra_base_url,
    )

    llm_client = OpenAI(
        api_key=config.deepseek_api_key,
        base_url=config.deepseek_base_url,
    )

    return qdrant_client, embedding_client, llm_client


def embed_query(text: str, client: OpenAI, config: WebAppConfig) -> List[float]:
    """Génère l'embedding de la requête utilisateur."""
    response = client.embeddings.create(
        input=text,
        model=config.embedding_model,
        dimensions=config.embedding_dimension,
    )
    return response.data[0].embedding


def search_collections(
    query_vector: List[float],
    qdrant_client: QdrantClient,
    config: WebAppConfig,
) -> List[Dict]:
    """Recherche dans toutes les collections Qdrant et fusionne les résultats."""
    all_results = []

    for collection_name in config.collections:
        try:
            results = qdrant_client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=config.top_k,
                with_payload=True,
            )

            for hit in results.points:
                payload = hit.payload or {}
                all_results.append({
                    "collection": collection_name,
                    "score": hit.score,
                    "url": payload.get("url", payload.get("unique_url", "")),
                    "title": payload.get("title", ""),
                    "content": payload.get("full_content", payload.get("full_text", "")),
                    "question": payload.get("potential_question", ""),
                    "date": payload.get("date", payload.get("decision_date", "")),
                    "legal_references": payload.get("legal_references", {}),
                    "summary": payload.get("summary", ""),
                    "decision_id": payload.get("decision_id", ""),
                    "number": payload.get("number", ""),
                    "chamber": payload.get("chamber", ""),
                })

        except Exception as e:
            logger.warning(f"Erreur recherche dans {collection_name}: {e}")
            continue

    # Trier par score décroissant
    all_results.sort(key=lambda x: x["score"], reverse=True)

    # Dédupliquer par URL (garder le meilleur score)
    seen_urls = set()
    unique_results = []
    for r in all_results:
        url = r["url"]
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_results.append(r)

    return unique_results


def build_context(results: List[Dict], max_length: int = 30000) -> str:
    """Construit le contexte textuel à partir des résultats de recherche."""
    if not results:
        return "Aucun document pertinent trouvé dans la base de connaissances."

    context_parts = []
    current_length = 0

    for i, r in enumerate(results, 1):
        # Construire le bloc selon le type de document
        if r["decision_id"]:
            # Décision de justice
            header = f"[Document {i} - Décision {r['number'] or r['decision_id']}]"
            if r["chamber"]:
                header += f" ({r['chamber']})"
            if r["date"]:
                header += f" du {r['date']}"

            content = r["summary"] or r["content"]
            block = f"{header}\nURL: {r['url']}\n{content}"
        else:
            # Article de blog
            header = f"[Document {i} - Article]"
            if r["title"]:
                header += f" {r['title']}"
            if r["date"]:
                header += f" ({r['date']})"

            content = r["content"]
            block = f"{header}\nURL: {r['url']}\n{content}"

        # Tronquer le contenu si trop long
        if len(block) > 5000:
            block = block[:5000] + "\n[...tronqué...]"

        if current_length + len(block) > max_length:
            break

        context_parts.append(block)
        current_length += len(block)

    return "\n\n---\n\n".join(context_parts)


async def stream_rag_response(
    query: str,
    chat_history: List[Dict],
    qdrant_client: QdrantClient,
    embedding_client: OpenAI,
    llm_client: OpenAI,
    config: WebAppConfig,
) -> AsyncIterator[str]:
    """
    Pipeline RAG complet avec streaming.
    Yield les tokens au fur et à mesure.
    """
    # 1. Embed la query
    query_vector = embed_query(query, embedding_client, config)

    # 2. Recherche multi-collections
    results = search_collections(query_vector, qdrant_client, config)
    logger.info(f"RAG: {len(results)} résultats trouvés pour: {query[:80]}...")

    # 3. Construire le contexte
    context = build_context(results, config.max_context_length)

    # 4. Construire les messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Ajouter l'historique de conversation (limité aux 10 derniers échanges)
    for msg in chat_history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Ajouter la query avec le contexte
    user_message = f"""Voici les documents pertinents trouvés dans la base de connaissances :

{context}

---

Question de l'utilisateur : {query}"""

    messages.append({"role": "user", "content": user_message})

    # 5. Stream la réponse DeepSeek
    try:
        stream = llm_client.chat.completions.create(
            model=config.deepseek_model,
            messages=messages,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                # DeepSeek reasoner renvoie reasoning_content et content
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content

    except Exception as e:
        logger.error(f"Erreur streaming LLM: {e}")
        yield f"\n\n[Erreur lors de la génération de la réponse: {str(e)}]"


def get_sources_from_results(results: List[Dict], limit: int = 5) -> List[Dict]:
    """Extrait les sources à afficher dans l'UI."""
    sources = []
    for r in results[:limit]:
        source = {
            "url": r["url"],
            "title": r["title"] or r.get("number", "") or "Document",
            "collection": r["collection"],
            "score": round(r["score"], 3),
        }
        if r["date"]:
            source["date"] = r["date"]
        sources.append(source)
    return sources
