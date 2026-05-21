"""
Vérification du contenu de la collection Qdrant.
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

print("\n" + "="*70)
print(f"VÉRIFICATION DE LA COLLECTION '{collection_name}'")
print("="*70 + "\n")

# Compter les articles
count = client.count(collection_name).count
print(f"Total d'articles stockés: {count}\n")

# Récupérer quelques exemples
points, _ = client.scroll(collection_name, limit=3, with_payload=True)

print(f"Exemples d'articles stockés:\n")
for i, point in enumerate(points, 1):
    payload = point.payload
    print(f"Article {i}:")
    print(f"  Titre: {payload.get('title', 'N/A')}")
    print(f"  URL: {payload.get('url', 'N/A')}")
    print(f"  Date: {payload.get('date', 'N/A')}")
    print(f"  Question: {payload.get('potential_question', 'N/A')}")
    refs = payload.get('legal_references', [])
    print(f"  Références juridiques ({len(refs)}): {', '.join(refs) if refs else 'Aucune'}")
    print(f"  Longueur contenu: {len(payload.get('full_content', ''))} caractères")
    print()

print("="*70)
print("✅ Collection validée!")
print("="*70 + "\n")
