"""
Configuration de la pipeline d'ingestion des decisions de la Cour de cassation.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class CCPipelineConfig:
    """Configuration centrale pour la pipeline d'ingestion CC."""

    # API Judilibre
    judilibre_base_url: str
    judilibre_key_id: str

    # DeepSeek (generation de resumes)
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # DeepInfra (embeddings BGE-M3 - meme que pipeline blogs)
    deepinfra_api_key: str = ""
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    deepinfra_embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 256

    # Qdrant (meme cluster que articles_blog)
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    collection_name: str = "decisions_cour_cassation"
    qdrant_timeout: int = 60

    # Processing
    batch_size: int = 50
    max_retries: int = 3
    max_content_length: int = 50000

    def validate(self) -> bool:
        """Valide que toutes les variables d'environnement requises sont presentes."""
        missing = []
        if not self.judilibre_key_id:
            missing.append("JUDILIBRE_KEY_ID")
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
    def from_env(cls) -> "CCPipelineConfig":
        """Cree une configuration a partir des variables d'environnement."""
        return cls(
            judilibre_base_url=os.getenv(
                "JUDILIBRE_BASE_URL",
                "https://api.piste.gouv.fr/cassation/judilibre/v1.0",
            ),
            judilibre_key_id=os.getenv("JUDILIBRE_KEY_ID", ""),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            deepinfra_api_key=os.getenv("DEEPINFRA_API_KEY", ""),
            deepinfra_base_url=os.getenv(
                "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
            ),
            deepinfra_embedding_model=os.getenv("DEEPINFRA_EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "256")),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            collection_name=os.getenv("CC_COLLECTION_NAME", "decisions_cour_cassation"),
            qdrant_timeout=int(os.getenv("QDRANT_TIMEOUT", "60")),
            batch_size=int(os.getenv("CC_BATCH_SIZE", "50")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            max_content_length=int(os.getenv("MAX_CONTENT_LENGTH", "50000")),
        )
