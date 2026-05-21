"""
Configuration du logging structuré pour la pipeline d'ingestion.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logger(
    name: str = "blog_ingestion",
    log_file: str = "blog_ingestion.log",
    level: int = logging.INFO
) -> logging.Logger:
    """
    Configure et retourne un logger avec handlers pour fichier et console.

    Args:
        name: Nom du logger
        log_file: Nom du fichier de log
        level: Niveau de logging (default: INFO)

    Returns:
        Logger configuré
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Éviter les handlers dupliqués
    if logger.handlers:
        return logger

    # Format des logs
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Créer le dossier logs s'il n'existe pas
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Handler pour fichier
    log_path = logs_dir / log_file
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler pour console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def log_error_with_context(
    logger: logging.Logger,
    message: str,
    stage: str,
    url: str = None,
    error: Exception = None,
    retry_count: int = 0
):
    """
    Log une erreur avec contexte structuré.

    Args:
        logger: Instance du logger
        message: Message d'erreur principal
        stage: Étape de la pipeline (sitemap_parsing, scraping, llm_processing, etc.)
        url: URL concernée (optionnel)
        error: Exception capturée (optionnel)
        retry_count: Nombre de tentatives (optionnel)
    """
    context_parts = [f"Stage: {stage}"]

    if url:
        context_parts.append(f"URL: {url}")

    if error:
        context_parts.append(f"Error: {type(error).__name__}: {str(error)}")

    if retry_count > 0:
        context_parts.append(f"Retry: {retry_count}")

    context = " | ".join(context_parts)
    logger.error(f"{message} - {context}")


def log_inaccessible_url(url: str, reason: str, log_file: str = "inaccessible_urls.log"):
    """
    Enregistre une URL inaccessible dans un fichier dédié.

    Args:
        url: URL inaccessible
        reason: Raison de l'inaccessibilité
        log_file: Fichier de log (default: inaccessible_urls.log)
    """
    try:
        # Créer le dossier logs s'il n'existe pas
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)

        log_path = logs_dir / log_file
        timestamp = datetime.now().isoformat()
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} - {url} - {reason}\n")
    except Exception as e:
        # Fallback sur logging standard si écriture fichier échoue
        logging.error(f"Erreur lors de l'écriture dans {log_file}: {str(e)}")
