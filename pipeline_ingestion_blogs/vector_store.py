"""
Module pour gérer le stockage vectoriel dans Qdrant.
Embedding avec DeepInfra (BGE-M3) et upsert dans Qdrant.
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple
from openai import OpenAI
from qdrant_client import QdrantClient, models
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .url_utils import normalize_url

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30)
)
async def embed_text_openai(
    text: str,
    client: OpenAI,
    model: str = "BAAI/bge-m3",
    dimensions: int = 256
) -> List[float]:
    """
    Génère un embedding pour un texte en utilisant l'API DeepInfra (compatible OpenAI).

    Args:
        text: Texte à vectoriser
        client: Client DeepInfra (compatible OpenAI)
        model: Modèle d'embedding
        dimensions: Dimension cible du vecteur

    Returns:
        Vecteur d'embedding (List[float])

    Raises:
        Exception: Si l'embedding échoue
    """
    try:
        response = await asyncio.to_thread(
            client.embeddings.create,
            input=text,
            model=model,
            dimensions=dimensions
        )

        embedding = response.data[0].embedding
        logger.debug(f"Embedding généré: {len(embedding)} dimensions")
        return embedding

    except Exception as e:
        logger.error(f"Erreur lors de la génération d'embedding: {str(e)}")
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30)
)
async def embed_texts_batch(
    texts: List[str],
    client: OpenAI,
    model: str = "BAAI/bge-m3",
    dimensions: int = 256
) -> List[List[float]]:
    """
    Génère des embeddings pour plusieurs textes en un seul appel API.

    Args:
        texts: Liste de textes à vectoriser
        client: Client DeepInfra (compatible OpenAI)
        model: Modèle d'embedding
        dimensions: Dimension cible du vecteur

    Returns:
        Liste de vecteurs d'embedding

    Raises:
        Exception: Si l'embedding échoue
    """
    if not texts:
        return []

    try:
        response = await asyncio.to_thread(
            client.embeddings.create,
            input=texts,
            model=model,
            dimensions=dimensions
        )

        # Trier par index pour garantir l'ordre
        sorted_data = sorted(response.data, key=lambda x: x.index)
        embeddings = [item.embedding for item in sorted_data]
        logger.debug(f"Batch embedding généré: {len(embeddings)} textes, {len(embeddings[0])} dimensions")
        return embeddings

    except Exception as e:
        logger.error(f"Erreur lors du batch embedding ({len(texts)} textes): {str(e)}")
        raise


def check_qdrant_health(qdrant_client: QdrantClient, collection_name: str) -> Dict:
    """
    Vérifie la santé de Qdrant et log les infos diagnostiques.

    Returns:
        Dict avec les infos de santé
    """
    health = {}
    try:
        # Test de latence basique
        start = time.time()
        collections = qdrant_client.get_collections().collections
        latency = time.time() - start
        health["latency_ms"] = round(latency * 1000)
        health["collections"] = [c.name for c in collections]
        logger.info(f"Qdrant health check - latence: {health['latency_ms']}ms, collections: {health['collections']}")

        # Infos sur la collection cible
        if collection_name in health["collections"]:
            info = qdrant_client.get_collection(collection_name)
            health["points_count"] = info.points_count
            health["status"] = str(info.status)
            health["optimizer_status"] = str(getattr(info, 'optimizer_status', 'unknown'))
            logger.info(
                f"Collection '{collection_name}': "
                f"{health['points_count']} points, "
                f"status={health['status']}, "
                f"optimizer={health['optimizer_status']}"
            )
            # Si l'optimizer tourne, ça peut causer des timeouts
            if "indexing" in str(info.optimizer_status).lower():
                logger.warning(
                    "⚠ L'optimizer Qdrant est en cours d'indexation. "
                    "Cela peut ralentir les upserts et causer des timeouts."
                )
        else:
            logger.info(f"Collection '{collection_name}' n'existe pas encore")

    except Exception as e:
        health["error"] = str(e)
        logger.error(f"Qdrant health check FAILED: {type(e).__name__}: {str(e)}")

    return health


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def create_qdrant_collection(
    qdrant_client: QdrantClient,
    collection_name: str,
    vector_dimension: int = 256
) -> bool:
    """
    Crée une collection Qdrant si elle n'existe pas.

    Args:
        qdrant_client: Client Qdrant
        collection_name: Nom de la collection
        vector_dimension: Dimension des vecteurs

    Returns:
        True si succès, False sinon

    Raises:
        Exception: Si la création échoue après retries
    """
    try:
        collections = qdrant_client.get_collections().collections
        existing_names = [c.name for c in collections]

        if collection_name in existing_names:
            # Vérifier que la dimension est correcte
            info = qdrant_client.get_collection(collection_name)
            existing_dim = info.config.params.vectors.size
            if existing_dim == vector_dimension:
                logger.info(f"Collection {collection_name} existe déjà avec la bonne dimension ({vector_dimension}), réutilisation")
                return True
            else:
                logger.warning(f"Collection {collection_name} existe avec dimension {existing_dim} != {vector_dimension}, recréation...")
                qdrant_client.delete_collection(collection_name)
                logger.info(f"Collection {collection_name} supprimée")

        # Créer la collection
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_dimension,
                distance=models.Distance.COSINE
            )
        )
        logger.info(f"Collection créée: {collection_name}")
        return True

    except Exception as e:
        logger.error(f"Erreur création collection {collection_name}: {str(e)}")
        raise


async def get_existing_urls(
    qdrant_client: QdrantClient,
    collection_name: str
) -> Set[str]:
    """
    Récupère toutes les URLs existantes dans une collection Qdrant.

    Args:
        qdrant_client: Client Qdrant
        collection_name: Nom de la collection

    Returns:
        Set d'URLs normalisées
    """
    existing_urls = set()

    try:
        # Vérifier si la collection existe
        collections = qdrant_client.get_collections().collections
        if collection_name not in [c.name for c in collections]:
            logger.info(f"Collection {collection_name} n'existe pas encore")
            return existing_urls

        offset = None
        while True:
            # Scroll pour récupérer les points
            points, next_offset = qdrant_client.scroll(
                collection_name=collection_name,
                limit=100,
                with_payload=True,
                offset=offset
            )

            # Extraire les URLs
            for point in points:
                url = point.payload.get('url', '')
                if url:
                    existing_urls.add(normalize_url(url))

            # Continuer si il y a plus de points
            if next_offset is None:
                break
            offset = next_offset

        logger.info(f"Total URLs existantes dans {collection_name}: {len(existing_urls)}")
        return existing_urls

    except Exception as e:
        logger.error(f"Erreur récupération URLs de {collection_name}: {str(e)}")
        return set()


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def upsert_points(
    qdrant_client: QdrantClient,
    collection_name: str,
    points: List[models.PointStruct]
):
    """
    Insère des points dans Qdrant avec retries.

    Args:
        qdrant_client: Client Qdrant
        collection_name: Nom de la collection
        points: Liste de points à insérer

    Raises:
        Exception: Si l'upsert échoue après retries
    """
    try:
        if not points:
            logger.warning("Liste de points vide, skip upsert")
            return

        # Log la taille du payload pour diagnostiquer les timeouts
        total_payload_size = sum(
            len(str(p.payload.get("full_content", ""))) for p in points
        )
        logger.info(f"Upsert {len(points)} points dans {collection_name} (payload total: {total_payload_size:,} chars)")

        start = time.time()
        qdrant_client.upsert(collection_name=collection_name, points=points)
        elapsed = time.time() - start

        logger.info(f"Upserted {len(points)} points dans {collection_name} en {elapsed:.2f}s")

    except Exception as e:
        logger.error(
            f"Erreur upsert points dans {collection_name}: "
            f"type={type(e).__name__}, message={str(e)}, "
            f"nb_points={len(points)}, payload_size={total_payload_size:,} chars"
        )
        raise


async def store_article_in_qdrant(
    article_data: Dict,
    qdrant_client: QdrantClient,
    openai_client: OpenAI,
    collection_name: str,
    embedding_model: str = "text-embedding-3-large",
    embedding_dimension: int = 256
) -> Tuple[bool, List[str]]:
    """
    Stocke un article dans Qdrant avec 3 questions potentielles.
    Crée 3 points Qdrant distincts, un par question, avec le même contenu mais embeddings différents.

    Args:
        article_data: Dict avec tous les champs de l'article (incluant "potential_questions")
        qdrant_client: Client Qdrant
        openai_client: Client OpenAI
        collection_name: Nom de la collection
        embedding_model: Modèle d'embedding
        embedding_dimension: Dimension du vecteur

    Returns:
        Tuple (success: bool, point_ids: List[str]) - Liste des 3 IDs Qdrant créés
    """
    try:
        # Vérifier que les questions sont présentes
        questions = article_data.get("potential_questions")
        if not questions or not isinstance(questions, list) or len(questions) != 3:
            logger.error(f"Pas de 3 questions pour l'article {article_data.get('url')}")
            return False, []

        # Préparer le payload de base (commun aux 3 points)
        base_payload = {
            "url": normalize_url(article_data["url"]),
            "unique_url": article_data["url"],
            "full_content": article_data.get("full_content", ""),
            "date": article_data.get("date", ""),
            "legal_references": article_data.get("legal_references", {}),
            "title": article_data.get("title", "")
        }

        # Générer les 3 embeddings en un seul appel API
        vectors = await embed_texts_batch(
            questions,
            openai_client,
            embedding_model,
            embedding_dimension
        )

        # Créer 3 points, un par question
        points = []
        point_ids = []

        for i, (question, vector) in enumerate(zip(questions, vectors)):
            payload = {
                **base_payload,
                "potential_question": question,
                "question_index": i + 1  # 1, 2, ou 3
            }

            point_id = str(uuid.uuid4())
            point_ids.append(point_id)

            point = models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            )
            points.append(point)

        # Upsert les 3 points en une seule fois
        upsert_points(qdrant_client, collection_name, points)

        logger.info(f"Article stocké dans Qdrant avec 3 questions: {article_data['url']}")
        return True, point_ids

    except Exception as e:
        logger.error(f"Erreur stockage article {article_data.get('url')}: {str(e)}")
        return False, []


async def store_articles_batch(
    articles: List[Dict],
    qdrant_client: QdrantClient,
    openai_client: OpenAI,
    collection_name: str,
    embedding_model: str = "text-embedding-3-large",
    embedding_dimension: int = 256
) -> int:
    """
    Stocke un batch d'articles dans Qdrant.

    Args:
        articles: Liste d'articles enrichis
        qdrant_client: Client Qdrant
        openai_client: Client OpenAI
        collection_name: Nom de la collection
        embedding_model: Modèle d'embedding
        embedding_dimension: Dimension du vecteur

    Returns:
        Nombre d'articles stockés avec succès
    """
    success_count = 0

    for article in articles:
        try:
            success, _ = await store_article_in_qdrant(
                article,
                qdrant_client,
                openai_client,
                collection_name,
                embedding_model,
                embedding_dimension
            )
            if success:
                success_count += 1

        except Exception as e:
            logger.error(f"Échec stockage article {article.get('url')}: {str(e)}")
            continue

    logger.info(f"Batch stockage: {success_count}/{len(articles)} articles stockés")
    return success_count
