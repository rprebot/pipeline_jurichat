"""
Point d'entree de la pipeline d'ingestion des decisions de la Cour de cassation.

Usage:
    python -m pipeline_ingestion_cour_cassation.main --year 2024
"""

import argparse
import gc
import logging
import sys
import time
from datetime import datetime

from openai import OpenAI
from qdrant_client import QdrantClient
from tqdm import tqdm

from .config import CCPipelineConfig
from .historique_manager import HistoriqueDecisionsManager
from .judilibre_client import JudilibreClient
from .content_processor import generate_summary, generate_questions_from_summary, extract_references
from .vector_store import (
    create_collection_if_not_exists,
    embed_texts_batch,
    store_decision_in_qdrant,
)

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"logs/pipeline_cc_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def process_decision(
    decision: dict,
    judilibre: JudilibreClient,
    deepseek_client: OpenAI,
    embedding_client: OpenAI,
    qdrant_client: QdrantClient,
    config: CCPipelineConfig,
    historique: HistoriqueDecisionsManager,
) -> bool:
    """
    Traite une decision individuelle : texte complet, resume, questions, references, embedding, stockage.
    Stocke 3 points par decision (un par question potentielle).
    Enregistre le resultat dans l'historique (success ou error).

    Returns:
        True si la decision a ete traitee avec succes
    """
    decision_id = decision["id"]
    number = decision.get("number", "")
    decision_date = decision.get("decision_date", "")
    url = judilibre.get_decision_url(decision_id)

    try:
        # 1. Recuperer le texte complet
        full_text = judilibre.get_decision_full_text(decision_id)
        if not full_text:
            logger.warning(f"Texte vide pour decision {decision_id}, skip")
            historique.add_error(decision_id, "Texte vide", number, url, decision_date)
            return False

        # 2. Extraire le commentaire du bulletin
        bulletin_comment = judilibre.extract_bulletin_comment(decision)
        if not bulletin_comment:
            logger.warning(f"Pas de commentaire bulletin pour {decision_id}, skip")
            historique.add_error(decision_id, "Pas de commentaire bulletin", number, url, decision_date)
            return False

        # 3. Generer le resume via DeepSeek
        summary = generate_summary(
            full_text,
            deepseek_client,
            config.deepseek_model,
            config.max_content_length,
        )

        # 4. Generer 3 questions a partir du resume
        questions = generate_questions_from_summary(
            summary,
            deepseek_client,
            config.deepseek_model,
        )

        # 5. Extraire les references juridiques (regex, meme que blogs)
        legal_references = extract_references(full_text)

        # 6. Embedding des 3 questions (un seul appel API batch)
        vectors = embed_texts_batch(
            questions,
            embedding_client,
            config.deepinfra_embedding_model,
            config.embedding_dimension,
        )

        # 7. Stocker 3 points dans Qdrant (un par question)
        decision_data = {
            "url": url,
            "decision_id": decision_id,
            "full_text": full_text,
            "summary": summary,
            "bulletin_comment": bulletin_comment,
            "chamber": decision.get("chamber"),
            "legal_references": legal_references,
            "decision_date": decision_date,
            "number": number,
            "formation": decision.get("formation"),
            "solution": decision.get("solution"),
            "publication": decision.get("publication"),
        }

        store_decision_in_qdrant(decision_data, vectors, questions, qdrant_client, config.collection_name)

        # Enregistrer le succes dans l'historique
        historique.add_success(decision_id, number, url, decision_date)
        logger.info(f"Decision {number or decision_id} traitee avec succes (3 points)")
        return True

    except Exception as e:
        logger.error(f"Erreur traitement decision {decision_id}: {e}")
        historique.add_error(decision_id, str(e), number, url, decision_date)
        return False


def run_pipeline(year: int) -> dict:
    """
    Execute la pipeline d'ingestion pour une annee donnee.

    Args:
        year: Annee des decisions a importer

    Returns:
        Statistiques d'importation
    """
    start_time = time.time()

    # Configuration
    config = CCPipelineConfig.from_env()
    if not config.validate():
        logger.error("Configuration invalide, arret")
        sys.exit(1)

    # Initialisation des clients
    judilibre = JudilibreClient(config)

    deepseek_client = OpenAI(
        api_key=config.deepseek_api_key,
        base_url=config.deepseek_base_url,
    )

    embedding_client = OpenAI(
        api_key=config.deepinfra_api_key,
        base_url=config.deepinfra_base_url,
    )

    qdrant_client = QdrantClient(
        url=config.qdrant_url,
        api_key=config.qdrant_api_key,
        timeout=config.qdrant_timeout,
    )

    # Initialiser le gestionnaire d'historique
    historique = HistoriqueDecisionsManager()
    historique_stats = historique.get_stats()
    logger.info(f"Historique: {historique_stats['total_success']} decisions en succes, {historique_stats['total_errors']} en erreur")

    # Creer la collection si necessaire
    create_collection_if_not_exists(
        qdrant_client, config.collection_name, config.embedding_dimension
    )

    # Recuperer les decisions de l'annee (filtre bulletin)
    decisions = judilibre.get_decisions_for_year(year)
    logger.info(f"{len(decisions)} decisions bulletin trouvees pour {year}")

    # Filtrer les decisions deja traitees avec succes (via historique local)
    success_ids = historique.get_success_ids()
    new_decisions = [d for d in decisions if d["id"] not in success_ids]
    logger.info(f"{len(new_decisions)} nouvelles decisions a traiter ({len(decisions) - len(new_decisions)} deja dans l'historique)")

    # Traitement
    processed = 0
    errors = 0

    with tqdm(total=len(new_decisions), desc=f"Ingestion CC bulletin {year}") as pbar:
        for decision in new_decisions:
            if process_decision(
                decision, judilibre, deepseek_client, embedding_client, qdrant_client, config, historique
            ):
                processed += 1
            else:
                errors += 1

            pbar.update(1)

            # Nettoyage memoire periodique
            if (processed + errors) % 10 == 0:
                gc.collect()

    # Fermer l'historique (flush final)
    historique.close()

    elapsed = time.time() - start_time
    stats = {
        "year": year,
        "total_found": len(decisions),
        "already_indexed": len(decisions) - len(new_decisions),
        "processed": processed,
        "errors": errors,
        "qdrant_points_created": processed * 3,
        "elapsed_seconds": round(elapsed, 2),
    }

    logger.info(
        f"Pipeline terminee pour {year}: "
        f"{processed} traitees ({processed * 3} points Qdrant), {errors} erreurs, "
        f"{stats['already_indexed']} deja indexees, "
        f"temps: {elapsed:.0f}s"
    )

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingestion des decisions de la Cour de cassation (bulletin) depuis Judilibre"
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Annee des decisions a importer (ex: 2024)",
    )
    args = parser.parse_args()

    # Validation de l'annee
    current_year = datetime.now().year
    if not (2000 <= args.year <= current_year):
        print(f"Erreur: l'annee doit etre entre 2000 et {current_year}")
        sys.exit(1)

    stats = run_pipeline(args.year)
    print(f"\nResultats: {stats}")


if __name__ == "__main__":
    main()
