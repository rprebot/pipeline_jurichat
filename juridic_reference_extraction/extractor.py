"""
Extraction des references juridiques par regex.

Extrait trois types de references :
- Articles de codes (ex: "L. 1311-2 du Code du travail")
- Decisions Cour de cassation (ex: "02-12345.67890")
- Decisions Cour d'appel (ex: "02/12345")
"""

import logging
import re
import unicodedata
from typing import Dict, List, Optional

from .codes_loi import CODES_LOI

logger = logging.getLogger(__name__)


def _normalize_whitespace(text: str) -> str:
    """Remplace toute séquence de whitespace (retours à la ligne inclus) par un espace simple."""
    return re.sub(r'\s+', ' ', text)


def normalize_code_name(code: str) -> str:
    """
    Normalise le nom du code en gérant les variations 'de'/'du',
    les variantes d'apostrophes et les espaces insécables.
    """
    text = code.replace(" du ", " de ")
    # Normaliser les variantes d'apostrophes (' ' ʼ)
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u02BC", "'")
    # Normaliser les espaces insécables
    text = text.replace("\u00A0", " ").replace("\u202F", " ")
    return text


def _find_code_in_context(context: str, article_position: int) -> Optional[str]:
    """Trouve le code juridique le plus proche de l'article dans le contexte."""
    context_lower = _normalize_whitespace(context.lower())
    normalized_context = normalize_code_name(context_lower)

    best_code = None
    best_distance = float('inf')

    for code in CODES_LOI:
        normalized_code = normalize_code_name(code.lower())
        pos = normalized_context.find(normalized_code)
        if pos != -1:
            distance = abs(pos - article_position)
            if distance < best_distance:
                best_distance = distance
                best_code = code

    return best_code


def _extract_date_from_context(context: str) -> Optional[str]:
    """Extrait une date au format 'XX mois XXXX' ou 'XX/XX/XXXX' d'un contexte."""

    def _normalize_text(text):
        return ''.join(
            c for c in unicodedata.normalize('NFD', text.lower())
            if unicodedata.category(c) != 'Mn'
        )

    mois_dict = {
        'janvier': '01', 'janv': '01',
        'fevrier': '02', 'fevr': '02',
        'mars': '03',
        'avril': '04',
        'mai': '05',
        'juin': '06',
        'juillet': '07', 'juil': '07',
        'aout': '08',
        'septembre': '09', 'sept': '09',
        'octobre': '10', 'oct': '10',
        'novembre': '11', 'nov': '11',
        'decembre': '12', 'dec': '12'
    }

    # Format "XX mois XXXX" — formes longues et abrégées, avec ou sans accents
    mois_pattern = (
        r'janvier|janv\.?|f[eé]vrier|f[eé]vr\.?|mars|avril|mai|juin|'
        r'juillet|juil\.?|ao[uû]t|septembre|sept\.?|octobre|oct\.?|'
        r'novembre|nov\.?|d[eé]cembre|d[eé]c\.?'
    )
    date_pattern_1 = rf'(?:Le\s+)?(\d{{1,2}})\s+({mois_pattern})\s+(\d{{4}})'

    all_dates = []

    for m in re.finditer(date_pattern_1, context, re.IGNORECASE):
        jour, mois, annee = m.groups()
        mois_clean = mois.rstrip('.')
        mois_num = mois_dict.get(_normalize_text(mois_clean))
        if mois_num:
            all_dates.append((m.start(), f"{annee}-{mois_num}-{jour.zfill(2)}"))

    # Format "XX/XX/XXXX"
    date_pattern_2 = r'(\d{1,2})/(\d{1,2})/(\d{4})'
    for m in re.finditer(date_pattern_2, context):
        jour, mois, annee = m.groups()
        all_dates.append((m.start(), f"{annee}-{mois.zfill(2)}-{jour.zfill(2)}"))

    if all_dates:
        # Retourner la date la plus proche de la fin du contexte
        all_dates.sort(key=lambda x: x[0], reverse=True)
        return all_dates[0][1]

    return None


def extract_legal_references_regex(content: str) -> Dict:
    """
    Extrait les références juridiques mentionnées dans le texte :
    articles de codes, décisions Cour de cassation, décisions Cour d'appel.

    Args:
        content: Contenu textuel a analyser

    Returns:
        Dict avec 3 clés :
        - "codes": {nom_du_code: [liste d'articles]}
        - "cour_cassation": [{"pourvoi": "XX-XXXXX.XXX", "date": "YYYY-MM-DD"|null}]
        - "cour_appel": [{"renvoi": "XX/XXXXX", "date": "YYYY-MM-DD"|null}]

    Examples:
        >>> extract_legal_references_regex("Article L. 1311-2 du Code du travail")
        {"codes": {"Code du travail": ["L. 1311-2"]}, "cour_cassation": [], "cour_appel": []}
    """
    try:
        codes_result: Dict[str, List[str]] = {}
        cour_cassation: List[Dict] = []
        cour_appel: List[Dict] = []

        # --- 1. Articles de codes ---
        article_patterns = [
            r'(?:Article|Articles|article|articles|art\.|Art\.)\s+(?:\d{1,7})(?:\s+et\s+suivant(?:s)?)?',
            r'(?:Article|Articles|article|articles|art\.|Art\.)\s+n°\s+(?:\d{1,7})(?:\s+et\s+suivant(?:s)?)?',
            r'[LlRrDd](?:\.\s?|\s)?\d{2,4}(?:-\d{1,4})?(?:-\d{1,2})?',
        ]

        seen_articles = set()

        for pattern in article_patterns:
            for match in re.finditer(pattern, content):
                article_ref = re.sub(r'\s+', ' ', match.group()).strip()

                start_idx = match.start()
                context_start = max(0, start_idx - 150)
                context_end = min(len(content), start_idx + 150)
                context = content[context_start:context_end]

                article_position = start_idx - context_start
                code = _find_code_in_context(context, article_position)
                if code is None:
                    continue

                article_key = f"{article_ref}_{code}"
                if article_key in seen_articles:
                    continue
                seen_articles.add(article_key)

                if code not in codes_result:
                    codes_result[code] = []
                codes_result[code].append(article_ref)

        # Codes mentionnés sans article précis
        content_flat = _normalize_whitespace(content.lower())
        normalized_content = normalize_code_name(content_flat)

        for code in CODES_LOI:
            normalized_code = normalize_code_name(code.lower())
            if normalized_code in normalized_content and code not in codes_result:
                codes_result[code] = []

        # Filtrer les codes qui sont des sous-chaînes d'un code plus long déjà trouvé
        codes_to_remove = set()
        found_codes = list(codes_result.keys())
        for short_code in found_codes:
            for long_code in found_codes:
                if short_code != long_code and short_code in long_code:
                    short_norm = normalize_code_name(short_code.lower())
                    long_norm = normalize_code_name(long_code.lower())
                    content_without_long = normalized_content.replace(long_norm, "")
                    if short_norm not in content_without_long:
                        codes_to_remove.add(short_code)
        for code in codes_to_remove:
            del codes_result[code]

        # --- 2. Décisions Cour de cassation (pourvoi: XX-XXXXX.XXXXX) ---
        pourvoi_pattern = r'\b\d{2,5}-\d{2,5}\.\d{2,5}\b'
        cassation_context_pattern = re.compile(
            r'cass(?:ation)?|pourvoi|cour\s+de\s+cassation',
            re.IGNORECASE
        )
        seen_pourvois = set()

        for match in re.finditer(pourvoi_pattern, content):
            pourvoi = match.group()
            if pourvoi in seen_pourvois:
                continue

            ctx_start = max(0, match.start() - 300)
            ctx_end = min(len(content), match.end() + 100)
            surrounding = content[ctx_start:ctx_end]
            if not cassation_context_pattern.search(surrounding):
                continue
            seen_pourvois.add(pourvoi)

            before = content[max(0, match.start() - 300):match.start()]
            date_str = _extract_date_from_context(before)
            if not date_str:
                after = content[match.end():min(len(content), match.end() + 150)]
                date_str = _extract_date_from_context(after)

            cour_cassation.append({"pourvoi": pourvoi, "date": date_str})

        # --- 3. Décisions Cour d'appel (renvoi: XX/XXXXX) ---
        renvoi_pattern = r'\b\d{2}/\d{5}\b'
        appel_context_pattern = re.compile(
            r"cour\s+d['\u2019]appel|(?<!\w)CA(?!\w)|(?<!\w)RG(?!\w)",
            re.IGNORECASE
        )
        seen_renvois = set()

        for match in re.finditer(renvoi_pattern, content):
            renvoi = match.group()
            if renvoi in seen_renvois:
                continue

            ctx_start = max(0, match.start() - 300)
            ctx_end = min(len(content), match.end() + 100)
            surrounding = content[ctx_start:ctx_end]
            if not appel_context_pattern.search(surrounding):
                continue
            seen_renvois.add(renvoi)

            before = content[max(0, match.start() - 300):match.start()]
            date_str = _extract_date_from_context(before)
            if not date_str:
                after = content[match.end():min(len(content), match.end() + 150)]
                date_str = _extract_date_from_context(after)

            cour_appel.append({"renvoi": renvoi, "date": date_str})

        result = {
            "codes": codes_result,
            "cour_cassation": cour_cassation,
            "cour_appel": cour_appel,
        }

        logger.info(
            f"Références juridiques extraites (REGEX): "
            f"{len(codes_result)} codes, {sum(len(v) for v in codes_result.values())} articles, "
            f"{len(cour_cassation)} décisions Cass., {len(cour_appel)} décisions CA"
        )

        return result

    except Exception as e:
        logger.error(f"Erreur lors de l'extraction REGEX des références: {str(e)}")
        return {"codes": {}, "cour_cassation": [], "cour_appel": []}
