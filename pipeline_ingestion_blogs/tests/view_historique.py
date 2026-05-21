"""
Script pour visualiser l'historique des URLs traitées.
"""

import sqlite3
import sys
from pathlib import Path

# Ajouter le parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline_ingestion_blogs.historique_manager import HistoriqueManager


def view_historique():
    """Affiche un résumé de l'historique."""

    print("\n" + "="*70)
    print("HISTORIQUE DES URLs TRAITÉES")
    print("="*70 + "\n")

    historique = HistoriqueManager()

    # Stats globales
    stats = historique.get_stats()

    print("Statistiques Globales:")
    print(f"  Total URLs traitées: {stats.get('total_urls', 0)}")
    print(f"  Succès: {stats.get('stats', {}).get('total_success', 0)}")
    print(f"  Erreurs: {stats.get('stats', {}).get('total_errors', 0)}")
    print(f"  Taux de succès: {stats.get('stats', {}).get('success_rate', 'N/A')}")
    print(f"  Créé le: {stats.get('created_at', 'N/A')}")
    print(f"  Dernière MAJ: {stats.get('last_updated', 'N/A')}")
    print()

    # Requêtes directes sur la DB pour les détails
    db_path = Path("historique_savings/historique_urls.db")
    if not db_path.exists():
        print("Aucun historique trouvé.")
        return

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Derniers succès
        print("Derniers Succès (5 derniers):")
        rows = conn.execute(
            "SELECT * FROM urls WHERE status = 'success' ORDER BY id DESC LIMIT 5"
        ).fetchall()
        for row in rows:
            print(f"  - {(row['title'] or 'N/A')[:60]}")
            print(f"    URL: {row['url']}")
            print(f"    Date sauvegarde: {row['date_sauvegarde']}")
            print(f"    Refs juridiques: {row['legal_references_count']}")
            print()

        # Dernières erreurs
        print("Dernières Erreurs (5 dernières):")
        rows = conn.execute(
            "SELECT * FROM urls WHERE status = 'error' ORDER BY id DESC LIMIT 5"
        ).fetchall()
        for row in rows:
            print(f"  - URL: {row['url']}")
            print(f"    Erreur: {row['error_message']}")
            print(f"    Date: {row['date_sauvegarde']}")
            print()

        # Statistiques par type d'erreur
        error_count = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status = 'error'"
        ).fetchone()[0]

        if error_count > 0:
            print("Erreurs par Catégorie:")
            rows = conn.execute("""
                SELECT
                    CASE
                        WHEN error_message LIKE '[%]%'
                        THEN SUBSTR(error_message, 2, INSTR(error_message, ']') - 2)
                        ELSE 'unknown'
                    END AS category,
                    COUNT(*) AS cnt
                FROM urls
                WHERE status = 'error'
                GROUP BY category
                ORDER BY cnt DESC
            """).fetchall()
            for row in rows:
                pct = (row['cnt'] / error_count * 100)
                print(f"  {row['category']}: {row['cnt']} ({pct:.1f}%)")
            print()

    print("="*70 + "\n")


if __name__ == "__main__":
    view_historique()
