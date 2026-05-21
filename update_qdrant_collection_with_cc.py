"""
Script pour importer les decisions de la Cour de cassation (bulletin) dans Qdrant.

Usage:
    python update_qdrant_collection_with_cc.py --year 2024

Arguments:
    --year    Annee des decisions a importer (ex: 2024)
"""

import argparse
import sys
from datetime import datetime

from pipeline_ingestion_cour_cassation.main import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Importer les decisions de la Cour de cassation (bulletin) dans Qdrant"
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Annee des decisions a importer (ex: 2024)",
    )
    args = parser.parse_args()

    current_year = datetime.now().year
    if not (2000 <= args.year <= current_year):
        print(f"Erreur: l'annee doit etre entre 2000 et {current_year}")
        sys.exit(1)

    stats = run_pipeline(args.year)

    print(f"\n{'='*50}")
    print(f"Importation terminee pour {args.year}")
    print(f"  Decisions trouvees (bulletin) : {stats['total_found']}")
    print(f"  Deja indexees                 : {stats['already_indexed']}")
    print(f"  Nouvelles traitees            : {stats['processed']}")
    print(f"  Erreurs                       : {stats['errors']}")
    print(f"  Temps total                   : {stats['elapsed_seconds']}s")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
