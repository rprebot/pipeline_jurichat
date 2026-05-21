"""
Nettoyage de la collection Qdrant articles_blog.
"""

from qdrant_client import QdrantClient
from dotenv import load_dotenv
import os

load_dotenv()

client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY")
)

collection_name = "articles_blog"

print(f"\nSuppression de la collection '{collection_name}'...")

try:
    # Vérifier si la collection existe
    collections = client.get_collections().collections
    if collection_name in [c.name for c in collections]:
        # Compter avant suppression
        count = client.count(collection_name).count
        print(f"  Collection existante avec {count} articles")

        # Supprimer
        client.delete_collection(collection_name)
        print(f"✓ Collection '{collection_name}' supprimée avec succès\n")
    else:
        print(f"  Collection '{collection_name}' n'existe pas\n")

except Exception as e:
    print(f"❌ Erreur: {str(e)}\n")
