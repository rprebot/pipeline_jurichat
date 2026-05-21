"""
Module pour gerer l'historique des decisions de la Cour de cassation traitees.
Utilise SQLite pour des lookups rapides sur decision_id.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DecisionHistoryEntry:
    """Entree d'historique pour une decision traitee."""
    decision_id: str
    number: str
    url: str
    decision_date: str
    date_sauvegarde: str
    status: str  # "success" ou "error"
    error_message: Optional[str] = None


class HistoriqueDecisionsManager:
    """Gestionnaire d'historique des decisions CC traitees (SQLite)."""

    def __init__(self, historique_dir: str = "historique_savings"):
        """
        Initialise le gestionnaire d'historique.

        Args:
            historique_dir: Repertoire pour stocker la base de donnees
        """
        self.historique_dir = Path(historique_dir)
        self.historique_dir.mkdir(exist_ok=True)

        self.db_path = self.historique_dir / "historique_decisions_cc.db"

        # Buffer en memoire pour optimiser les ecritures
        self.buffer: List[DecisionHistoryEntry] = []
        self.buffer_size = 10

        self._init_db()
        logger.info(f"Historique decisions CC initialise: {self.db_path}")

    def _init_db(self):
        """Cree les tables si elles n'existent pas."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT NOT NULL,
                    number TEXT,
                    url TEXT,
                    decision_date TEXT,
                    date_sauvegarde TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_id ON decisions(decision_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON decisions(status)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cursor = conn.execute(
                "SELECT value FROM metadata WHERE key = 'created_at'"
            )
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO metadata (key, value) VALUES ('created_at', ?)",
                    (datetime.now().isoformat(),)
                )
            conn.commit()

    def add_success(
        self,
        decision_id: str,
        number: str = "",
        url: str = "",
        decision_date: str = "",
    ):
        """Ajoute une decision traitee avec succes."""
        entry = DecisionHistoryEntry(
            decision_id=decision_id,
            number=number,
            url=url,
            decision_date=decision_date,
            date_sauvegarde=datetime.now().isoformat(),
            status="success",
        )
        self.buffer.append(entry)
        logger.debug(f"Buffer (succes): decision {decision_id}")

        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def add_error(
        self,
        decision_id: str,
        error_message: str,
        number: str = "",
        url: str = "",
        decision_date: str = "",
    ):
        """Ajoute une decision en erreur."""
        entry = DecisionHistoryEntry(
            decision_id=decision_id,
            number=number,
            url=url,
            decision_date=decision_date,
            date_sauvegarde=datetime.now().isoformat(),
            status="error",
            error_message=error_message,
        )
        self.buffer.append(entry)
        logger.debug(f"Buffer (erreur): decision {decision_id}")

        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        """Ecrit le buffer dans la base SQLite."""
        if not self.buffer:
            return

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    """INSERT INTO decisions
                       (decision_id, number, url, decision_date,
                        date_sauvegarde, status, error_message)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            e.decision_id,
                            e.number,
                            e.url,
                            e.decision_date,
                            e.date_sauvegarde,
                            e.status,
                            e.error_message,
                        )
                        for e in self.buffer
                    ]
                )
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_updated', ?)",
                    (datetime.now().isoformat(),)
                )
                conn.commit()

            logger.info(f"Historique decisions flush: {len(self.buffer)} entrees")
            self.buffer = []

        except Exception as e:
            logger.error(f"Erreur flush historique decisions: {e}")

    def get_success_ids(self) -> Set[str]:
        """
        Recupere les decision_id deja traitees avec succes.

        Returns:
            Set des decision_id avec statut success
        """
        buffered = {
            e.decision_id for e in self.buffer
            if e.status == "success"
        }

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT decision_id FROM decisions WHERE status = 'success'"
            )
            db_ids = {row[0] for row in cursor.fetchall()}

        return db_ids | buffered

    def get_stats(self) -> Dict:
        """Recupere les statistiques de l'historique."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE status = 'success'"
            ).fetchone()[0]
            errors = conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE status = 'error'"
            ).fetchone()[0]

            total += len(self.buffer)
            success += sum(1 for e in self.buffer if e.status == "success")
            errors += sum(1 for e in self.buffer if e.status == "error")

            success_rate = f"{(success / total * 100):.1f}%" if total > 0 else "0%"

            meta = {}
            for row in conn.execute("SELECT key, value FROM metadata"):
                meta[row[0]] = row[1]

        return {
            "total_decisions": total,
            "total_success": success,
            "total_errors": errors,
            "success_rate": success_rate,
            "created_at": meta.get("created_at"),
            "last_updated": meta.get("last_updated"),
        }

    def close(self):
        """Ferme le gestionnaire et ecrit les donnees restantes."""
        self.flush()
        logger.info("Historique decisions CC ferme")
