"""
Script pour migrer le champ legal_references des points Qdrant existants.
Retraite tous les points qui n'ont pas le format complet :
  {"codes": {...}, "cour_cassation": [...], "cour_appel": [...]}

Parcourt tous les points de la collection, réapplique extract_legal_references_regex()
sur le full_content, et met à jour le payload.
"""

import os
import sys
import time
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

sys.path.insert(0, os.path.dirname(__file__))
from juridic_reference_extraction import extract_legal_references_regex

load_dotenv()


def migrate_collection(client: QdrantClient, collection_name: str, content_field: str = "full_content"):
    """
    Migre les legal_references d'une collection Qdrant.

    Args:
        client: Client Qdrant
        collection_name: Nom de la collection
        content_field: Nom du champ contenant le texte a analyser
    """
    # Vérifier la collection
    collections = [c.name for c in client.get_collections().collections]
    if collection_name not in collections:
        print(f"  SKIP: Collection '{collection_name}' introuvable")
        return {"updated": 0, "skipped": 0, "errors": 0}

    total = client.count(collection_name).count
    print(f"  Collection '{collection_name}': {total} points a verifier")
    print(f"  Champ source: '{content_field}' -> stockage dans 'legal_references'")

    updated = 0
    skipped_no_content = 0
    errors = 0
    offset = None

    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            limit=50,
            with_payload=True,
            offset=offset
        )

        if not points:
            break

        for point in points:
            point_id = point.id
            payload = point.payload or {}

            content = payload.get(content_field, "")
            if not content:
                label = payload.get("url", payload.get("decision_id", point_id))
                print(f"    SKIP (champ '{content_field}' vide): {label}")
                skipped_no_content += 1
                continue

            try:
                new_refs = extract_legal_references_regex(content)

                client.set_payload(
                    collection_name=collection_name,
                    payload={"legal_references": new_refs},
                    points=[point_id]
                )
                updated += 1

                # Identifiant lisible selon la collection
                label = payload.get("url", payload.get("decision_id", "?"))
                if isinstance(label, str) and len(label) > 80:
                    label = label[:80]
                codes_count = len(new_refs.get("codes", {}))
                articles_count = sum(len(v) for v in new_refs.get("codes", {}).values())
                cass_count = len(new_refs.get("cour_cassation", []))
                ca_count = len(new_refs.get("cour_appel", []))
                print(f"    [{updated}] {label} -> {codes_count} codes, {articles_count} articles, {cass_count} Cass., {ca_count} CA")

            except Exception as e:
                errors += 1
                print(f"    ERREUR point {point_id}: {e}")

        if next_offset is None:
            break
        offset = next_offset

    skipped = skipped_no_content
    print(f"\n  Bilan '{collection_name}':")
    print(f"    - Mis a jour       : {updated}")
    print(f"    - Sans contenu     : {skipped_no_content}")
    print(f"    - Erreurs          : {errors}")
    return {"updated": updated, "skipped": skipped, "errors": errors}


# Mapping collection -> champ contenant le texte a analyser
COLLECTIONS_CONFIG = {
    os.getenv("COLLECTION_NAME", "articles_blog"): "full_content",
    "decisions_cour_cassation": "full_text",
}


def migrate(collection_filter: str = None):
    """
    Lance la migration des legal_references.

    Args:
        collection_filter: Nom de la collection a traiter.
                          Si None, toutes les collections sont traitees.
    """
    qdrant_url = os.getenv("QDRANT_URL", "")
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "")

    if not qdrant_url or not qdrant_api_key:
        print("ERREUR: QDRANT_URL et QDRANT_API_KEY doivent être définis dans .env")
        sys.exit(1)

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, timeout=60)

    # Determiner les collections a traiter
    if collection_filter:
        if collection_filter not in COLLECTIONS_CONFIG:
            print(f"ERREUR: Collection '{collection_filter}' inconnue.")
            print(f"Collections disponibles: {', '.join(COLLECTIONS_CONFIG.keys())}")
            sys.exit(1)
        targets = {collection_filter: COLLECTIONS_CONFIG[collection_filter]}
    else:
        targets = COLLECTIONS_CONFIG

    total_stats = {"updated": 0, "skipped": 0, "errors": 0}

    for collection_name, content_field in targets.items():
        print(f"\n--- {collection_name} (champ: {content_field}) ---")
        stats = migrate_collection(client, collection_name, content_field)
        for key in total_stats:
            total_stats[key] += stats[key]

    total = sum(total_stats.values())
    print(f"\n{'='*60}")
    label = collection_filter if collection_filter else "toutes collections"
    print(f"Migration terminée ({label}):")
    print(f"  - Mis à jour : {total_stats['updated']}")
    print(f"  - Ignorés    : {total_stats['skipped']}")
    print(f"  - Erreurs    : {total_stats['errors']}")
    print(f"  - Total      : {total}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration legal_references : retraitement format incomplet"
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help=f"Nom de la collection a traiter. Sans argument, toutes les collections sont traitees. "
             f"Choix: {', '.join(COLLECTIONS_CONFIG.keys())}",
    )
    args = parser.parse_args()

    print("="*60)
    print("MIGRATION legal_references : retraitement format incomplet")
    if args.collection:
        print(f"Collection: {args.collection}")
    else:
        print("Collections: toutes")
    print("="*60 + "\n")

    response = input("Lancer la migration ? (oui/non) : ").strip().lower()
    if response != "oui":
        print("Migration annulée.")
        sys.exit(0)

    start = time.time()
    migrate(args.collection)
    print(f"\nDurée: {time.time() - start:.1f}s")
