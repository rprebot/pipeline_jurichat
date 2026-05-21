"""
Test du système d'historique (SQLite).
"""

import sys
import sqlite3
import tempfile
import shutil
from pathlib import Path

# Ajouter le parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline_ingestion_blogs.historique_manager import HistoriqueManager


def test_historique():
    """Teste le gestionnaire d'historique."""

    print("\n" + "="*70)
    print("TEST DU SYSTÈME D'HISTORIQUE (SQLite)")
    print("="*70 + "\n")

    # Utiliser un répertoire temporaire pour ne pas polluer les données réelles
    test_dir = tempfile.mkdtemp(prefix="historique_test_")

    try:
        # Initialiser le gestionnaire
        historique = HistoriqueManager(historique_dir=test_dir)
        print("+ Gestionnaire d'historique initialisé\n")

        # Vérifier que la DB existe
        db_path = Path(test_dir) / "historique_urls.db"
        assert db_path.exists(), "La base de données n'a pas été créée"
        print("+ Base SQLite créée\n")

        # Test 1: Ajouter des succès
        print("Test 1: Ajout de succès")
        historique.add_success(
            url="https://example.com/article1",
            qdrant_id="uuid-123",
            title="Article de test 1",
            date_article="2024-01-01",
            legal_references_count=2
        )
        historique.add_success(
            url="https://example.com/article2",
            qdrant_id="uuid-456",
            title="Article de test 2",
            date_article="2024-01-02",
            legal_references_count=1
        )
        print("+ 2 succès ajoutés au buffer\n")

        # Test 2: Ajouter des erreurs
        print("Test 2: Ajout d'erreurs")
        historique.add_error(
            url="https://example.com/article3",
            error_message="Timeout lors du scraping",
            stage="scraping"
        )
        historique.add_error(
            url="https://example.com/article4",
            error_message="Échec génération question",
            stage="llm_processing"
        )
        print("+ 2 erreurs ajoutées au buffer\n")

        # Test 3: Vérifier que get_processed_urls inclut le buffer
        print("Test 3: URLs accessibles avant flush")
        processed = historique.get_processed_urls()
        assert len(processed) == 4, f"Attendu 4, obtenu {len(processed)}"
        print(f"+ {len(processed)} URLs accessibles (buffer inclus)\n")

        # Test 4: Flush manuel
        print("Test 4: Flush des données")
        historique.flush()
        print("+ Buffer écrit dans SQLite\n")

        # Test 5: Vérifier en DB
        print("Test 5: Vérification en base")
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
            assert count == 4, f"Attendu 4 lignes, obtenu {count}"
        print(f"+ {count} lignes en base\n")

        # Test 6: Récupérer les stats
        print("Test 6: Récupération des stats")
        stats = historique.get_stats()
        assert stats["total_urls"] == 4
        assert stats["stats"]["total_success"] == 2
        assert stats["stats"]["total_errors"] == 2
        print(f"  Total URLs: {stats['total_urls']}")
        print(f"  Succès: {stats['stats']['total_success']}")
        print(f"  Erreurs: {stats['stats']['total_errors']}")
        print(f"  Taux de succès: {stats['stats']['success_rate']}")
        print()

        # Test 7: Récupérer les URLs par statut
        print("Test 7: Récupération des URLs par statut")
        processed_urls = historique.get_processed_urls()
        success_urls = historique.get_success_urls()
        error_urls = historique.get_error_urls()
        assert len(processed_urls) == 4
        assert len(success_urls) == 2
        assert len(error_urls) == 2
        print(f"  Toutes: {len(processed_urls)}")
        print(f"  Succès: {len(success_urls)}")
        print(f"  Erreurs: {len(error_urls)}")
        print()

        # Test 8: Backup (obsolète mais doit pas planter)
        print("Test 8: create_session_backup (obsolète)")
        result = historique.create_session_backup()
        assert result is None
        print("+ Méthode obsolète retourne None\n")

        # Test 9: Fermer le gestionnaire
        print("Test 9: Fermeture")
        historique.close()
        print("+ Gestionnaire fermé\n")

        # Test 10: Réouverture et persistance
        print("Test 10: Réouverture et persistance")
        historique2 = HistoriqueManager(historique_dir=test_dir)
        stats2 = historique2.get_stats()
        assert stats2["total_urls"] == 4, "Les données ne sont pas persistées"
        historique2.close()
        print("+ Données persistées après réouverture\n")

        print("="*70)
        print("TOUS LES TESTS SONT PASSES!")
        print("="*70 + "\n")

    finally:
        # Nettoyer le répertoire temporaire
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    test_historique()
