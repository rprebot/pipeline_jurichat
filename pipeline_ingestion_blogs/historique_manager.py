"""
Module pour gérer l'historique des URLs traitées et sauvegardées dans Qdrant.
Utilise SQLite pour des lookups rapides et un accès concurrent sûr.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Import pour normalisation des URLs
try:
    from .url_utils import normalize_url
except ImportError:
    # Fallback si import relatif échoue
    def normalize_url(url: str) -> str:
        return url


@dataclass
class URLHistoryEntry:
    """Entrée d'historique pour une URL traitée."""
    url: str
    date_sauvegarde: str
    status: str  # "success" ou "error"
    error_message: Optional[str] = None
    qdrant_id: Optional[str] = None
    title: Optional[str] = None
    date_article: Optional[str] = None
    legal_references_count: int = 0


class HistoriqueManager:
    """Gestionnaire d'historique des URLs traitées (SQLite)."""

    def __init__(self, historique_dir: str = "historique_savings"):
        """
        Initialise le gestionnaire d'historique.

        Args:
            historique_dir: Répertoire pour stocker la base de données
        """
        self.historique_dir = Path(historique_dir)
        self.historique_dir.mkdir(exist_ok=True)

        self.db_path = self.historique_dir / "historique_urls.db"
        self.json_path = self.historique_dir / "historique_urls.json"

        # Buffer en mémoire pour optimiser les écritures
        self.buffer: List[URLHistoryEntry] = []
        self.buffer_size = 10  # Écrire toutes les 10 entrées

        # Initialiser la base de données
        self._init_db()

        # Migrer les données JSON existantes si nécessaire
        self._migrate_from_json()

        logger.info(f"Gestionnaire d'historique initialisé (SQLite): {self.db_path}")

    def _init_db(self):
        """Crée les tables si elles n'existent pas."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    url_normalized TEXT NOT NULL,
                    date_sauvegarde TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    qdrant_id TEXT,
                    title TEXT,
                    date_article TEXT,
                    legal_references_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_url_normalized ON urls(url_normalized)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON urls(status)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            # Initialiser created_at si absent
            cursor = conn.execute(
                "SELECT value FROM metadata WHERE key = 'created_at'"
            )
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO metadata (key, value) VALUES ('created_at', ?)",
                    (datetime.now().isoformat(),)
                )
            conn.commit()

    def _migrate_from_json(self):
        """Migre les données depuis le fichier JSON existant vers SQLite."""
        if not self.json_path.exists():
            return

        # Vérifier si la migration a déjà été faite
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM metadata WHERE key = 'json_migrated'"
            )
            if cursor.fetchone() is not None:
                return

        logger.info("Migration des données JSON vers SQLite...")

        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            entries = data.get("urls", [])
            if not entries:
                logger.info("Aucune entrée à migrer.")
                return

            with sqlite3.connect(self.db_path) as conn:
                # Préserver la date de création originale
                created_at = data.get("created_at", datetime.now().isoformat())
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('created_at', ?)",
                    (created_at,)
                )

                # Insérer toutes les entrées
                conn.executemany(
                    """INSERT INTO urls
                       (url, url_normalized, date_sauvegarde, status,
                        error_message, qdrant_id, title, date_article,
                        legal_references_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            entry.get("url", ""),
                            normalize_url(entry.get("url", "")),
                            entry.get("date_sauvegarde", ""),
                            entry.get("status", ""),
                            entry.get("error_message"),
                            entry.get("qdrant_id"),
                            entry.get("title"),
                            entry.get("date_article"),
                            entry.get("legal_references_count", 0),
                        )
                        for entry in entries
                    ]
                )

                # Marquer la migration comme faite
                conn.execute(
                    "INSERT INTO metadata (key, value) VALUES ('json_migrated', ?)",
                    (datetime.now().isoformat(),)
                )
                conn.commit()

            # Renommer le fichier JSON en backup
            backup_path = self.json_path.with_suffix('.json.bak')
            self.json_path.rename(backup_path)

            logger.info(
                f"Migration terminée: {len(entries)} entrées migrées. "
                f"JSON sauvegardé en {backup_path}"
            )

        except Exception as e:
            logger.error(f"Erreur lors de la migration JSON → SQLite: {str(e)}")

    def add_success(
        self,
        url: str,
        qdrant_id: str,
        title: str = "",
        date_article: str = "",
        legal_references_count: int = 0
    ):
        """
        Ajoute une URL sauvegardée avec succès.

        Args:
            url: URL de l'article
            qdrant_id: ID du point dans Qdrant
            title: Titre de l'article
            date_article: Date de l'article
            legal_references_count: Nombre de références juridiques
        """
        entry = URLHistoryEntry(
            url=url,
            date_sauvegarde=datetime.now().isoformat(),
            status="success",
            error_message=None,
            qdrant_id=qdrant_id,
            title=title,
            date_article=date_article,
            legal_references_count=legal_references_count
        )

        self.buffer.append(entry)
        logger.debug(f"Ajouté au buffer (succès): {url}")

        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def add_error(
        self,
        url: str,
        error_message: str,
        stage: str = "unknown"
    ):
        """
        Ajoute une URL en erreur.

        Args:
            url: URL de l'article
            error_message: Message d'erreur
            stage: Étape où l'erreur s'est produite
        """
        entry = URLHistoryEntry(
            url=url,
            date_sauvegarde=datetime.now().isoformat(),
            status="error",
            error_message=f"[{stage}] {error_message}",
            qdrant_id=None
        )

        self.buffer.append(entry)
        logger.debug(f"Ajouté au buffer (erreur): {url}")

        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        """Écrit le buffer dans la base SQLite."""
        if not self.buffer:
            return

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    """INSERT INTO urls
                       (url, url_normalized, date_sauvegarde, status,
                        error_message, qdrant_id, title, date_article,
                        legal_references_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            entry.url,
                            normalize_url(entry.url),
                            entry.date_sauvegarde,
                            entry.status,
                            entry.error_message,
                            entry.qdrant_id,
                            entry.title,
                            entry.date_article,
                            entry.legal_references_count,
                        )
                        for entry in self.buffer
                    ]
                )
                # Mettre à jour last_updated
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_updated', ?)",
                    (datetime.now().isoformat(),)
                )
                conn.commit()

            logger.info(f"Historique sauvegardé: {len(self.buffer)} nouvelles entrées")
            self.buffer = []

        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de l'historique: {str(e)}")

    def get_processed_urls(self) -> set:
        """
        Récupère l'ensemble des URLs déjà traitées (normalisées), quel que soit le statut.

        Returns:
            Set d'URLs normalisées déjà traitées (succès ou erreur)
        """
        # Inclure les URLs dans le buffer non encore flush
        buffered = {normalize_url(entry.url) for entry in self.buffer}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT url_normalized FROM urls")
            db_urls = {row[0] for row in cursor.fetchall()}

        return db_urls | buffered

    def get_success_urls(self) -> set:
        """
        Récupère l'ensemble des URLs traitées avec succès (normalisées).

        Returns:
            Set d'URLs normalisées traitées avec succès
        """
        buffered = {
            normalize_url(entry.url) for entry in self.buffer
            if entry.status == "success"
        }

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT url_normalized FROM urls WHERE status = 'success'"
            )
            db_urls = {row[0] for row in cursor.fetchall()}

        return db_urls | buffered

    def get_error_urls(self) -> set:
        """
        Récupère l'ensemble des URLs en erreur (normalisées).

        Returns:
            Set d'URLs normalisées en erreur
        """
        buffered = {
            normalize_url(entry.url) for entry in self.buffer
            if entry.status == "error"
        }

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT url_normalized FROM urls WHERE status = 'error'"
            )
            db_urls = {row[0] for row in cursor.fetchall()}

        return db_urls | buffered

    def get_stats(self) -> Dict:
        """
        Récupère les statistiques de l'historique.

        Returns:
            Dictionnaire avec les stats
        """
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM urls WHERE status = 'success'"
            ).fetchone()[0]
            errors = conn.execute(
                "SELECT COUNT(*) FROM urls WHERE status = 'error'"
            ).fetchone()[0]

            # Ajouter le buffer non flush
            total += len(self.buffer)
            success += sum(1 for e in self.buffer if e.status == "success")
            errors += sum(1 for e in self.buffer if e.status == "error")

            success_rate = f"{(success / total * 100):.1f}%" if total > 0 else "0%"

            # Métadonnées
            meta = {}
            for row in conn.execute("SELECT key, value FROM metadata"):
                meta[row[0]] = row[1]

        return {
            "total_urls": total,
            "stats": {
                "total_success": success,
                "total_errors": errors,
                "success_rate": success_rate
            },
            "created_at": meta.get("created_at"),
            "last_updated": meta.get("last_updated")
        }

    def create_session_backup(self):
        """
        Méthode obsolète - conservée pour compatibilité.
        """
        logger.debug("create_session_backup() appelée mais désactivée (obsolète)")
        return None

    def close(self):
        """Ferme le gestionnaire et écrit les données restantes."""
        self.flush()
        logger.info("Gestionnaire d'historique fermé")
