"""
Client pour l'API Judilibre - recuperation des decisions de la Cour de cassation.
Filtre uniquement les decisions publiees au bulletin.
"""

import logging
import time
import calendar
from datetime import datetime
from typing import Dict, List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from .config import CCPipelineConfig

logger = logging.getLogger(__name__)


class JudilibreClient:
    """Client pour interroger l'API Judilibre."""

    def __init__(self, config: CCPipelineConfig):
        self.config = config
        self.base_url = config.judilibre_base_url
        self.headers = {
            "accept": "application/json",
            "KeyId": config.judilibre_key_id,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def get_decisions_for_month(self, year: int, month: int) -> List[Dict]:
        """
        Recupere les decisions CC publiees au bulletin pour un mois donne.

        Returns:
            Liste de decisions avec leurs metadonnees
        """
        first_day = datetime(year, month, 1)
        last_day_num = calendar.monthrange(year, month)[1]
        last_day = datetime(year, month, last_day_num)

        date_start = first_day.strftime("%Y-%m-%d")
        date_end = last_day.strftime("%Y-%m-%d")

        logger.info(f"Recuperation decisions CC bulletin pour {month:02d}/{year} ({date_start} a {date_end})")

        all_decisions = []
        page = 1
        page_size = self.config.batch_size

        params = {
            "query": "*",
            "jurisdiction": "cc",
            "date_start": date_start,
            "date_end": date_end,
            "page_size": page_size,
            "publication": "b",
        }

        with tqdm(desc=f"Recuperation CC bulletin {month:02d}/{year}") as pbar:
            while True:
                params["page"] = page
                response = requests.get(
                    f"{self.base_url}/search",
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )

                if response.status_code == 416:
                    break

                response.raise_for_status()
                data = response.json()

                decisions = data.get("results", [])
                if not decisions:
                    break

                for d in decisions:
                    decision_data = {
                        "id": d.get("id"),
                        "number": d.get("number"),
                        "decision_date": d.get("decision_date"),
                        "chamber": d.get("chamber"),
                        "formation": d.get("formation"),
                        "type": d.get("type"),
                        "solution": d.get("solution"),
                        "publication": d.get("publication"),
                        "titlesAndSummaries": d.get("titlesAndSummaries"),
                    }
                    all_decisions.append(decision_data)

                pbar.update(len(decisions))

                if len(decisions) < page_size:
                    break

                page += 1
                time.sleep(1.0)

        logger.info(f"Total decisions bulletin recuperees pour {month:02d}/{year}: {len(all_decisions)}")
        return all_decisions

    def get_decisions_for_year(self, year: int) -> List[Dict]:
        """
        Recupere toutes les decisions CC publiees au bulletin pour une annee.

        Args:
            year: Annee a importer

        Returns:
            Liste de toutes les decisions de l'annee
        """
        current_date = datetime.now()
        all_decisions = []

        for month in range(1, 13):
            # Ne pas chercher les mois futurs
            if year == current_date.year and month > current_date.month:
                break

            decisions = self.get_decisions_for_month(year, month)
            all_decisions.extend(decisions)

        logger.info(f"Total decisions bulletin pour {year}: {len(all_decisions)}")
        return all_decisions

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def get_decision_full_text(self, decision_id: str) -> str:
        """
        Recupere le texte complet d'une decision via son ID.

        Args:
            decision_id: ID de la decision Judilibre

        Returns:
            Texte complet de la decision
        """
        response = requests.get(
            f"{self.base_url}/decision",
            headers=self.headers,
            params={"id": decision_id},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("text", "")

    @staticmethod
    def get_decision_url(decision_id: str) -> str:
        """Construit l'URL publique d'une decision."""
        return f"https://www.courdecassation.fr/decision/{decision_id}"

    @staticmethod
    def extract_bulletin_comment(decision: Dict) -> Optional[str]:
        """
        Extrait le commentaire du bulletin depuis titlesAndSummaries.

        Returns:
            Le commentaire du bulletin ou None
        """
        titles_summaries = decision.get("titlesAndSummaries")
        if not titles_summaries or not isinstance(titles_summaries, list):
            return None

        # Concatener tous les summaries disponibles
        parts = []
        for entry in titles_summaries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if title:
                parts.append(title)
            if summary:
                parts.append(summary)

        return "\n".join(parts) if parts else None
