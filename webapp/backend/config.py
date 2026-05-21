"""
Configuration de l'application web RAG.
"""

import os
import json
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


@dataclass
class WebAppConfig:
    """Configuration pour le backend RAG."""

    # Qdrant
    qdrant_url: str = ""
    qdrant_api_key: str = ""

    # Collections à interroger
    collections: List[str] = field(default_factory=list)

    # DeepInfra (embeddings BGE-M3)
    deepinfra_api_key: str = ""
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 256

    # DeepSeek (reasoning)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-reasoner"

    # RAG
    top_k: int = 10  # nombre de résultats par collection
    max_context_length: int = 30000

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "WebAppConfig":
        # Construire la liste des collections depuis l'env
        collections = []

        # Collection blogs
        collections.append(os.getenv("COLLECTION_NAME", "articles_blog"))

        # Collection Cour de cassation
        collections.append(os.getenv("CC_COLLECTION_NAME", "decisions_cour_cassation"))

        # Collections depuis les variables JSON
        for env_var in ["COLLECTION_QUESTIONS", "COLLECTION_JURISPRUDENCES"]:
            raw = os.getenv(env_var, "[]")
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    collections.extend(parsed)
            except json.JSONDecodeError:
                pass

        # Dédupliquer en gardant l'ordre
        seen = set()
        unique_collections = []
        for c in collections:
            if c not in seen:
                seen.add(c)
                unique_collections.append(c)

        return cls(
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            collections=unique_collections,
            deepinfra_api_key=os.getenv("DEEPINFRA_API_KEY", ""),
            deepinfra_base_url=os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"),
            embedding_model=os.getenv("DEEPINFRA_EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "256")),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL_REASONING", "deepseek-reasoner"),
            host=os.getenv("WEBAPP_HOST", "0.0.0.0"),
            port=int(os.getenv("WEBAPP_PORT", "8000")),
        )
