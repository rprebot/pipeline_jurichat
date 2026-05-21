"""
Pipeline d'ingestion des decisions de la Cour de cassation depuis Judilibre.

Filtre les decisions publiees au bulletin et les stocke dans Qdrant
avec resume DeepSeek, references juridiques et embedding du commentaire bulletin.
"""

__version__ = "1.0.0"
