"""
Module d'extraction des references juridiques par regex.

Utilise par les pipelines d'ingestion blogs et Cour de cassation.
"""

from .extractor import extract_legal_references_regex

__all__ = ["extract_legal_references_regex"]
