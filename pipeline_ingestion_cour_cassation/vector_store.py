"""
Stockage vectoriel dans Qdrant pour les decisions de la Cour de cassation.
Embedding avec DeepInfra (BGE-M3) - meme embedder que le pipeline blogs.
Chaque decision est stockee 3 fois, une par question potentielle.
"""

import logging
import time
import uuid
from typing import Dict, List, Set

from openai import OpenAI
from qdrant_client import QdrantClient, models
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
)
def embed_texts_batch(
    texts: List[str],
    client: OpenAI,
    model: str = "BAAI/bge-m3",
    dimensions: int = 256,
) -> List[List[float]]:
    """
    Genere des embeddings pour plusieurs textes en un seul appel API.

    Args:
        texts: Liste de textes a vectoriser
        client: Client DeepInfra (compatible OpenAI)
        model: Modele d'embedding
        dimensions: Dimension cible du vecteur

    Returns:
        Liste de vecteurs d'embedding
    """
    response = client.embeddings.create(
        input=texts,
        model=model,
        dimensions=dimensions,
    )
    sorted_data = sorted(response.data, key=lambda x: x.index)
    embeddings = [item.embedding for item in sorted_data]
    logger.debug(f"Batch embedding genere: {len(embeddings)} textes, {dimensions} dimensions")
    return embeddings


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
)
def create_collection_if_not_exists(
    qdrant_client: QdrantClient,
    collection_name: str,
    vector_dimension: int = 256,
) -> None:
    """Cree la collection Qdrant si elle n'existe pas."""
    collections = qdrant_client.get_collections().collections
    existing_names = [c.name for c in collections]

    if collection_name in existing_names:
        info = qdrant_client.get_collection(collection_name)
        vectors_config = info.config.params.vectors
        # vectors peut etre un VectorParams ou un dict de VectorParams
        if isinstance(vectors_config, dict):
            vectors_config = next(iter(vectors_config.values()))
        existing_dim = vectors_config.size
        if existing_dim == vector_dimension:
            logger.info(f"Collection {collection_name} existe deja ({vector_dimension}d)")
            return
        else:
            logger.warning(
                f"Collection {collection_name} dimension {existing_dim} != {vector_dimension}, recreation..."
            )
            qdrant_client.delete_collection(collection_name)

    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=vector_dimension,
            distance=models.Distance.COSINE,
        ),
    )
    logger.info(f"Collection creee: {collection_name}")


def get_existing_decision_ids(
    qdrant_client: QdrantClient,
    collection_name: str,
) -> Set[str]:
    """
    Recupere les IDs de decisions deja presentes dans Qdrant.

    Returns:
        Set des decision_id deja indexes
    """
    existing_ids = set()

    try:
        collections = qdrant_client.get_collections().collections
        if collection_name not in [c.name for c in collections]:
            return existing_ids

        offset = None
        while True:
            points, next_offset = qdrant_client.scroll(
                collection_name=collection_name,
                limit=100,
                with_payload=True,
                offset=offset,
            )
            for point in points:
                decision_id = point.payload.get("decision_id", "")
                if decision_id:
                    existing_ids.add(decision_id)

            if next_offset is None:
                break
            offset = next_offset

        logger.info(f"Decisions existantes dans {collection_name}: {len(existing_ids)}")
    except Exception as e:
        logger.error(f"Erreur recuperation IDs existants: {e}")

    return existing_ids


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def upsert_decision_points(
    qdrant_client: QdrantClient,
    collection_name: str,
    points: List[models.PointStruct],
) -> None:
    """Insere des points decision dans Qdrant avec retries."""
    start = time.time()
    qdrant_client.upsert(
        collection_name=collection_name,
        points=points,
    )
    elapsed = time.time() - start
    logger.debug(f"{len(points)} points upsertes dans {collection_name} en {elapsed:.2f}s")


def store_decision_in_qdrant(
    decision_data: Dict,
    vectors: List[List[float]],
    questions: List[str],
    qdrant_client: QdrantClient,
    collection_name: str,
) -> List[str]:
    """
    Stocke une decision dans Qdrant avec 3 points (un par question potentielle).

    Args:
        decision_data: Payload de la decision
        vectors: Liste de 3 embeddings (un par question)
        questions: Liste de 3 questions potentielles
        qdrant_client: Client Qdrant
        collection_name: Nom de la collection

    Returns:
        Liste des IDs des 3 points crees
    """
    base_payload = {
        "url": decision_data["url"],
        "decision_id": decision_data["decision_id"],
        "full_text": decision_data["full_text"],
        "summary": decision_data["summary"],
        "bulletin_comment": decision_data["bulletin_comment"],
        "chamber": decision_data["chamber"],
        "legal_references": decision_data["legal_references"],
        "decision_date": decision_data["decision_date"],
        "number": decision_data["number"],
        "formation": decision_data.get("formation"),
        "solution": decision_data.get("solution"),
        "publication": decision_data.get("publication"),
    }

    points = []
    point_ids = []

    for i, (question, vector) in enumerate(zip(questions, vectors)):
        point_id = str(uuid.uuid4())
        point_ids.append(point_id)

        payload = {
            **base_payload,
            "potential_question": question,
            "question_index": i + 1,
        }

        points.append(models.PointStruct(
            id=point_id,
            vector=vector,
            payload=payload,
        ))

    upsert_decision_points(qdrant_client, collection_name, points)
    logger.info(
        f"Decision {decision_data['decision_id']} stockee avec 3 questions "
        f"(points {point_ids})"
    )
    return point_ids
