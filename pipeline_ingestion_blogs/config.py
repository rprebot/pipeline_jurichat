"""
Configuration de la pipeline d'ingestion de blogs.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()


@dataclass
class BlogPipelineConfig:
    """Configuration centrale pour la pipeline d'ingestion de blogs."""

    # Champs requis (sans valeur par défaut) - DOIVENT être en premier
    deepseek_api_key: str
    deepinfra_api_key: str
    qdrant_url: str
    qdrant_api_key: str

    # DeepSeek Configuration (pour génération de texte)
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # DeepInfra Configuration (pour embeddings)
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    deepinfra_embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 256

    # Qdrant Configuration
    collection_name: str = "articles_blog"
    qdrant_timeout: int = 60

    # Scraping Configuration
    max_concurrent_scrapes: int = 5
    timeout: int = 30
    max_retries: int = 3

    # Processing Configuration
    batch_size: int = 10
    max_content_length: int = 50000  # Limite pour le contenu envoyé au LLM

    def validate(self) -> bool:
        """
        Valide que toutes les variables d'environnement requises sont présentes.

        Returns:
            True si toutes les variables sont présentes, False sinon
        """
        missing = []
        if not self.deepseek_api_key:
            missing.append("DEEPSEEK_API_KEY")
        if not self.deepinfra_api_key:
            missing.append("DEEPINFRA_API_KEY")

        if not self.qdrant_url:
            missing.append("QDRANT_URL")
        if not self.qdrant_api_key:
            missing.append("QDRANT_API_KEY")

        if missing:
            print(f"Variables d'environnement manquantes: {', '.join(missing)}")
            return False

        return True

    @classmethod
    def from_env(cls) -> "BlogPipelineConfig":
        """
        Crée une configuration à partir des variables d'environnement.

        Returns:
            Instance de BlogPipelineConfig
        """
        return cls(
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            deepinfra_api_key=os.getenv("DEEPINFRA_API_KEY", ""),
            deepinfra_base_url=os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"),
            deepinfra_embedding_model=os.getenv("DEEPINFRA_EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "256")),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            collection_name=os.getenv("COLLECTION_NAME", "articles_blog"),
            max_concurrent_scrapes=int(os.getenv("MAX_CONCURRENT_SCRAPES", "5")),
            timeout=int(os.getenv("TIMEOUT", "30")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            batch_size=int(os.getenv("BATCH_SIZE", "10")),
            max_content_length=int(os.getenv("MAX_CONTENT_LENGTH", "50000")),
            qdrant_timeout=int(os.getenv("QDRANT_TIMEOUT", "60"))
        )
