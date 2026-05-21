"""
Utilitaires pour la manipulation et validation des URLs.
Réutilise les fonctions de old_functions/url_ingestion_pipeline.py
"""

from urllib.parse import urlparse, urlunparse
import logging

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    Normalise une URL pour ignorer les variations mineures.

    Args:
        url: URL à normaliser

    Returns:
        URL normalisée (HTTPS, sans trailing slash, sans fragment)
    """
    try:
        parsed = urlparse(url)
        return urlunparse((
            'https' if parsed.scheme == 'http' else parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/'),
            parsed.params,
            parsed.query,
            ''  # Retire le fragment
        ))
    except Exception as e:
        logger.error(f"Erreur normalisation URL {url}: {str(e)}")
        return url


def is_valid_url(url: str) -> bool:
    """
    Vérifie si une URL est valide (présence de scheme et netloc).

    Args:
        url: URL à valider

    Returns:
        True si l'URL est valide, False sinon
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False
