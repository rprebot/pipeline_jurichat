"""
Module pour scraper le contenu des articles de blogs.
Réutilise les fonctions de old_functions/url_ingestion_pipeline.py
"""

import asyncio
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
import logging
import re
from datetime import datetime
from dateutil.parser import parse as parse_date

from .logger import log_inaccessible_url

logger = logging.getLogger(__name__)

# Script JS par défaut pour nettoyer les pages
DEFAULT_JS_SCRIPT = """
function disableScripts() {
    document.querySelectorAll("script").forEach(function(script) {
        script.remove();
    });
}

function clearNoise() {
    // Supprime les éléments hors-corps de page (header, footer, sidebar, nav, etc.)
    var noiseSelectors = [
        "header", "footer", "nav", "aside",
        ".sidebar", ".side-menu", ".side-nav",
        ".navbar", ".navigation", ".nav",
        ".breadcrumb", ".breadcrumbs",
        ".footnote", ".footnotes", ".references", ".endnotes",
        ".share", ".social-share", ".social-links",
        ".related-posts", ".related-articles",
        ".comments", "#comments", ".comment-section",
        ".cookie-banner", ".cookie-consent",
        ".pagination", ".pager",
        "[role='navigation']", "[role='banner']", "[role='contentinfo']",
        "[role='complementary']"
    ];
    noiseSelectors.forEach(function(selector) {
        document.querySelectorAll(selector).forEach(function(el) {
            el.innerHTML = "";
            el.style.cssText = "display: none; visibility: hidden;";
        });
    });
}

function expandAllMenus() {
    // Sélecteurs larges pour couvrir les différents patterns d'accordéons/menus déroulants
    var selectors = [
        // France Design System (sites .gouv.fr)
        ".fr-collapse__btn", ".fr-accordion__btn",
        // Patterns génériques
        ".accordion-toggle", ".accordion-button",
        ".collapse-toggle", ".collapsible-toggle",
        ".panel-heading", ".panel-title a",
        // Boutons avec aria-expanded
        "button[aria-expanded='false']", "a[aria-expanded='false']",
        "[data-toggle='collapse']", "[data-bs-toggle='collapse']",
        // Éléments <details> fermés : on les ouvre via attribut
        "details:not([open])",
        // Menus déroulants dans le corps
        ".menu-toggle", ".dropdown-toggle",
        ".expandable-trigger", ".expand-btn",
        // Tabs (parfois du contenu est masqué dans des onglets)
        ".tab-link", ".nav-tab", "[role='tab']"
    ];

    selectors.forEach(function(selector) {
        document.querySelectorAll(selector).forEach(function(el) {
            if (el.tagName === "DETAILS") {
                el.setAttribute("open", "");
            } else if (el.click) {
                el.click();
            }
        });
    });

    return new Promise(function(resolve) {
        setTimeout(resolve, 300);
    });
}

function forceRenderHiddenContent() {
    // Rendre visible les contenus masqués par aria-hidden dans le corps de page
    var mainContent = document.querySelector("main, article, [role='main'], .content, #content") || document.body;
    mainContent.querySelectorAll("[aria-hidden='true']").forEach(function(el) {
        el.setAttribute("aria-hidden", "false");
        el.style.cssText = "display: block; visibility: visible; opacity: 1;";
    });
    // Ouvrir les .fr-collapse (Design System FR)
    mainContent.querySelectorAll(".fr-collapse:not(.fr-collapse--expanded)").forEach(function(el) {
        el.classList.add("fr-collapse--expanded");
        el.style.cssText = "display: block; visibility: visible; opacity: 1; max-height: none;";
    });
    // Forcer l'affichage des panels collapsés Bootstrap
    mainContent.querySelectorAll(".collapse:not(.show)").forEach(function(el) {
        el.classList.add("show");
        el.style.cssText = "display: block; visibility: visible; opacity: 1; height: auto;";
    });
}

function scrollToBottom() {
    var scrollHeight = document.body.scrollHeight;
    window.scrollTo(0, scrollHeight);
    return new Promise(function(resolve) {
        setTimeout(resolve, 500);
    });
}

try {
    disableScripts();
    clearNoise();
    expandAllMenus().then(function() {
        forceRenderHiddenContent();
        return scrollToBottom();
    }).then(function() {
        // Deuxième passe : certains accordéons ne se déplient qu'après le premier clic
        return expandAllMenus();
    }).then(function() {
        forceRenderHiddenContent();
    }).catch(function(error) {
        console.error("Erreur JS:", error);
    });
} catch (error) {
    console.error("Erreur JS:", error);
}
"""




def does_make_sense(text: str, strict: bool = True) -> bool:
    """
    Vérifie si le texte a du sens (longueur, diversité des mots).

    Args:
        text: Texte à vérifier
        strict: Si True, applique les seuils standards (paragraphes).
                Si False, applique des seuils assouplis (éléments de liste, cellules, etc.)

    Returns:
        True si le texte a du sens, False sinon
    """
    if not text or len(text.strip()) < 5:
        return False
    try:
        words = text.lower().split()
        if strict:
            if len(words) < 10:
                return False
            unique_words = set(words)
            return len(unique_words) / len(words) > 0.3
        else:
            # Mode assoupli : au moins 2 mots suffisent (listes, cellules de tableau, etc.)
            return len(words) >= 2
    except Exception as e:
        logger.error(f"Erreur dans does_make_sense: {str(e)}")
        return False


# Tags considérés comme du bruit / hors corps de page
NOISE_SELECTORS = [
    "header", "footer", "nav",
    "aside", ".sidebar", ".side-menu", ".side-nav",
    ".nav", ".navbar", ".navigation", ".menu:not(main .menu)",
    ".breadcrumb", ".breadcrumbs",
    ".footnote", ".footnotes", ".references", ".endnotes",
    ".share", ".social-share", ".social-links",
    ".related-posts", ".related-articles", ".see-also",
    ".comments", "#comments", ".comment-section",
    ".cookie-banner", ".cookie-consent",
    ".pagination", ".pager",
    ".toc", ".table-of-contents",
    "[role='navigation']", "[role='banner']", "[role='contentinfo']",
    "[role='complementary']",
]


def _is_inside_noise(element) -> bool:
    """Vérifie si un élément HTML est à l'intérieur d'une zone de bruit (header, footer, sidebar, etc.)."""
    for parent in element.parents:
        if parent.name in ("header", "footer", "nav", "aside"):
            return True
        parent_classes = " ".join(parent.get("class", []))
        parent_id = parent.get("id", "")
        for noise in ("sidebar", "side-menu", "side-nav", "footnote", "footnotes",
                       "endnotes", "references", "breadcrumb", "social", "share",
                       "related-post", "related-article", "comment", "cookie",
                       "pagination", "pager", "toc", "table-of-contents",
                       "navbar", "navigation", "nav-"):
            if noise in parent_classes.lower() or noise in parent_id.lower():
                return True
        role = parent.get("role", "")
        if role in ("navigation", "banner", "contentinfo", "complementary"):
            return True
    return False


def _extract_list_text(list_element) -> str:
    """Extrait le texte d'une liste <ul>/<ol> en conservant la structure avec des préfixes."""
    lines = []
    items = list_element.find_all("li", recursive=False)
    is_ordered = list_element.name == "ol"
    start = int(list_element.get("start", 1)) if is_ordered else 0

    for i, li in enumerate(items):
        # Extraire le texte direct du <li> (sans les sous-listes)
        direct_text_parts = []
        for child in li.children:
            if hasattr(child, 'name') and child.name in ("ul", "ol"):
                continue  # Skip nested lists, handled below
            text = child.get_text(strip=True) if hasattr(child, 'get_text') else str(child).strip()
            if text:
                direct_text_parts.append(text)

        direct_text = " ".join(direct_text_parts)
        if direct_text:
            prefix = f"{start + i}. " if is_ordered else "- "
            lines.append(f"{prefix}{direct_text}")

        # Sous-listes imbriquées (récursion avec indentation)
        for sub_list in li.find_all(["ul", "ol"], recursive=False):
            sub_text = _extract_list_text(sub_list)
            if sub_text:
                indented = "\n".join(f"  {line}" for line in sub_text.split("\n"))
                lines.append(indented)

    return "\n".join(lines)


def _extract_table_text(table_element) -> str:
    """
    Extrait le contenu d'un tableau HTML en format Markdown avec :
    - Alignement des colonnes (padding)
    - Séparateur d'en-tête (--- | ---)
    - Gestion des colspan (cellules fusionnées horizontalement)
    - Gestion des rowspan (cellules fusionnées verticalement)
    - Contenu riche dans les cellules (listes inline, etc.)
    - Caption du tableau si présente
    """
    output_lines = []

    # Caption
    caption = table_element.find("caption")
    if caption:
        caption_text = caption.get_text(strip=True)
        if caption_text:
            output_lines.append(f"[Tableau : {caption_text}]")

    # --- Étape 1 : construire la grille normalisée (résolution colspan/rowspan) ---
    raw_rows = table_element.find_all("tr")
    if not raw_rows:
        return ""

    # Déterminer le nombre de colonnes réel
    max_cols = 0
    for row in raw_rows:
        col_count = sum(int(cell.get("colspan", 1)) for cell in row.find_all(["th", "td"]))
        max_cols = max(max_cols, col_count)

    if max_cols == 0:
        return ""

    # Grille : list[list[tuple(text, is_header)]]
    # None = slot réservé par un rowspan d'une ligne précédente
    grid = []
    rowspan_tracker = {}  # col_index -> (remaining_rows, text, is_header)

    for row in raw_rows:
        grid_row = [None] * max_cols
        cells = row.find_all(["th", "td"])
        cell_iter = iter(cells)
        target_col = 0

        while target_col < max_cols:
            # Si un rowspan précédent occupe cette colonne
            if target_col in rowspan_tracker:
                remaining, text, is_header = rowspan_tracker[target_col]
                grid_row[target_col] = (text, is_header)
                if remaining <= 1:
                    del rowspan_tracker[target_col]
                else:
                    rowspan_tracker[target_col] = (remaining - 1, text, is_header)
                target_col += 1
                continue

            # Prendre la cellule suivante
            cell = next(cell_iter, None)
            if cell is None:
                grid_row[target_col] = ("", False)
                target_col += 1
                continue

            # Extraire le texte de la cellule (contenu riche)
            cell_text = _extract_cell_content(cell)
            is_header = cell.name == "th"
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))

            # Remplir les colonnes couvertes par ce colspan
            for c in range(colspan):
                fill_col = target_col + c
                if fill_col < max_cols:
                    grid_row[fill_col] = (cell_text if c == 0 else "", is_header)
                    # Enregistrer le rowspan pour les lignes suivantes
                    if rowspan > 1:
                        rowspan_tracker[fill_col] = (rowspan - 1, cell_text if c == 0 else "", is_header)

            target_col += colspan

        grid.append(grid_row)

    # --- Étape 2 : identifier la ligne d'en-tête ---
    header_row_idx = None
    for i, row in enumerate(grid):
        if all(cell is not None and cell[1] for cell in row if cell is not None):
            header_row_idx = i
            break

    # Si pas de <th>, traiter la 1ère ligne du <thead> comme en-tête
    if header_row_idx is None:
        thead = table_element.find("thead")
        if thead:
            header_row_idx = 0

    # --- Étape 3 : calculer la largeur de chaque colonne pour l'alignement ---
    col_widths = [3] * max_cols  # minimum 3 chars (pour ---)
    for row in grid:
        for col_idx, cell in enumerate(row):
            if cell is not None:
                text = cell[0]
                # Pour les cellules multi-lignes, prendre la ligne la plus longue
                max_line_len = max((len(line) for line in text.split("\n")), default=0)
                col_widths[col_idx] = max(col_widths[col_idx], max_line_len)

    # --- Étape 4 : formater en Markdown ---
    def _format_row(row_data):
        """Formate une ligne de la grille en Markdown."""
        cells_text = []
        for col_idx, cell in enumerate(row_data):
            text = cell[0] if cell else ""
            # Remplacer les sauts de ligne par " ; " pour rester sur une ligne
            text = text.replace("\n", " ; ") if "\n" in text else text
            # Padding pour alignement
            cells_text.append(text.ljust(col_widths[col_idx]))
        return "| " + " | ".join(cells_text) + " |"

    for i, row in enumerate(grid):
        # Sauter les lignes complètement vides
        if all(cell is None or not cell[0].strip() for cell in row):
            continue

        output_lines.append(_format_row(row))

        # Ajouter le séparateur après la ligne d'en-tête
        if i == header_row_idx:
            separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
            output_lines.append(separator)

    # Si aucun en-tête n'a été détecté, ajouter un séparateur après la 1ère ligne
    if header_row_idx is None and len(output_lines) > (1 if caption else 0):
        insert_pos = 1 if caption else 0
        if insert_pos < len(output_lines):
            first_row_line = output_lines[insert_pos]
            separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
            output_lines.insert(insert_pos + 1, separator)

    return "\n".join(output_lines)


def _extract_cell_content(cell) -> str:
    """
    Extrait le contenu riche d'une cellule de tableau.
    Gère les listes, paragraphes multiples, liens, etc. dans une cellule.
    """
    # Vérifier s'il y a des sous-éléments structurés
    has_lists = cell.find(["ul", "ol"])
    has_paragraphs = cell.find_all("p")

    if has_lists:
        parts = []
        for child in cell.children:
            if hasattr(child, 'name') and child.name in ("ul", "ol"):
                parts.append(_extract_list_text(child))
            elif hasattr(child, 'get_text'):
                text = child.get_text(strip=True)
                if text:
                    parts.append(text)
            else:
                text = str(child).strip()
                if text:
                    parts.append(text)
        return " ; ".join(parts) if parts else ""

    if len(has_paragraphs) > 1:
        texts = [p.get_text(strip=True) for p in has_paragraphs if p.get_text(strip=True)]
        return " ; ".join(texts)

    # Contenu simple
    return cell.get_text(separator=" ", strip=True)


def _extract_definition_list_text(dl_element) -> str:
    """Extrait le contenu d'une liste de définitions <dl>."""
    lines = []
    children = dl_element.find_all(["dt", "dd"], recursive=False)
    for child in children:
        text = child.get_text(strip=True)
        if not text:
            continue
        if child.name == "dt":
            lines.append(f"**{text}**")
        else:
            lines.append(f"  {text}")
    return "\n".join(lines)


def _extract_details_content(details_element) -> tuple:
    """
    Extrait le titre (summary) et le contenu d'un élément <details> (menu déroulant).
    Returns: (summary_text, content_text)
    """
    summary = details_element.find("summary")
    summary_text = summary.get_text(strip=True) if summary else ""

    content_parts = []
    for child in details_element.children:
        if hasattr(child, 'name') and child.name == "summary":
            continue
        if hasattr(child, 'name'):
            if child.name in ("ul", "ol"):
                content_parts.append(_extract_list_text(child))
            elif child.name == "table":
                content_parts.append(_extract_table_text(child))
            elif child.name == "dl":
                content_parts.append(_extract_definition_list_text(child))
            elif child.name == "details":
                sub_title, sub_content = _extract_details_content(child)
                if sub_title:
                    content_parts.append(f"[{sub_title}]")
                if sub_content:
                    content_parts.append(sub_content)
            else:
                text = child.get_text(strip=True)
                if text:
                    content_parts.append(text)
        else:
            text = str(child).strip()
            if text:
                content_parts.append(text)

    return summary_text, "\n".join(content_parts)


def _is_nested_in_handled_parent(element, tags_to_check: set) -> bool:
    """Vérifie si l'élément est déjà imbriqué dans un parent qu'on traite explicitement."""
    for parent in element.parents:
        if parent.name in tags_to_check:
            return True
    return False


def parse_html_content(
    soup: BeautifulSoup,
    title_tags: List[str] = ["h1", "h2", "h3", "h4", "h5", "h6"],
) -> List[Dict[str, str]]:
    """
    Parse le HTML pour extraire le contenu structuré du corps de page.
    Capture : titres, paragraphes, listes, tableaux, citations, menus déroulants,
    listes de définitions, et tout contenu inline pertinent.
    Exclut : headers, footers, sidebars, navigation, footnotes, etc.

    Args:
        soup: BeautifulSoup object
        title_tags: Tags HTML considérés comme titres de section

    Returns:
        Liste de sections avec titre (incluant le niveau) et contenu
    """
    try:
        structured_content = []
        current_title = None
        current_level = 0
        current_paragraphs = []

        # Tags de contenu qu'on sait extraire
        content_tags = {"p", "ul", "ol", "table", "blockquote", "pre", "dl", "details", "figure"}
        # Tags parents qui gèrent eux-mêmes leurs enfants (éviter le double-comptage)
        compound_parents = {"ul", "ol", "table", "dl", "details", "blockquote"}
        # Tous les tags qu'on cherche dans le DOM
        all_tags = set(title_tags) | content_tags

        def _flush_section():
            """Sauvegarde la section courante si elle a du contenu."""
            nonlocal current_title, current_paragraphs
            if current_paragraphs:
                title_prefix = f"[h{current_level}] " if current_level else ""
                structured_content.append({
                    "titre_paragraphe": f"{title_prefix}{current_title}" if current_title else "[Introduction]",
                    "contenu_paragraphe": "\n".join(current_paragraphs)
                })
                current_paragraphs = []

        for element in soup.find_all(all_tags):
            # --- Filtrage du bruit ---
            if _is_inside_noise(element):
                continue

            # --- Éviter le double-comptage d'éléments imbriqués ---
            if element.name in content_tags and _is_nested_in_handled_parent(element, compound_parents):
                continue

            # --- Titres ---
            if element.name in title_tags:
                title_text = element.get_text(strip=True)
                if not title_text:
                    continue
                _flush_section()
                current_title = title_text
                current_level = int(element.name[1])  # h1->1, h2->2, etc.
                continue

            # --- Menus déroulants / accordéons (<details><summary>) ---
            if element.name == "details":
                summary_text, details_content = _extract_details_content(element)
                if summary_text or details_content:
                    # Flush section courante, créer une sous-section dédiée
                    _flush_section()
                    dropdown_title = summary_text or "[Contenu déroulant]"
                    level = current_level + 1 if current_level else 3
                    structured_content.append({
                        "titre_paragraphe": f"[h{level}] [Menu déroulant] {dropdown_title}",
                        "contenu_paragraphe": details_content
                    })
                continue

            # --- Paragraphes ---
            if element.name == "p":
                text = element.get_text(strip=True)
                if text and does_make_sense(text, strict=True):
                    current_paragraphs.append(text)
                elif text and does_make_sense(text, strict=False):
                    # Paragraphes courts mais valides (ex: "Le délai est de 5 ans.")
                    current_paragraphs.append(text)
                continue

            # --- Listes <ul> / <ol> ---
            if element.name in ("ul", "ol"):
                list_text = _extract_list_text(element)
                if list_text and does_make_sense(list_text, strict=False):
                    current_paragraphs.append(list_text)
                continue

            # --- Tableaux ---
            if element.name == "table":
                table_text = _extract_table_text(element)
                if table_text:
                    current_paragraphs.append(table_text)
                continue

            # --- Citations ---
            if element.name == "blockquote":
                quote_text = element.get_text(strip=True)
                if quote_text and does_make_sense(quote_text, strict=False):
                    current_paragraphs.append(f"> {quote_text}")
                continue

            # --- Blocs de code pré-formatés ---
            if element.name == "pre":
                code_text = element.get_text(strip=False).strip()
                if code_text:
                    current_paragraphs.append(f"```\n{code_text}\n```")
                continue

            # --- Listes de définitions ---
            if element.name == "dl":
                dl_text = _extract_definition_list_text(element)
                if dl_text:
                    current_paragraphs.append(dl_text)
                continue

            # --- Figures avec légende ---
            if element.name == "figure":
                figcaption = element.find("figcaption")
                if figcaption:
                    caption_text = figcaption.get_text(strip=True)
                    if caption_text:
                        current_paragraphs.append(f"[Figure : {caption_text}]")
                continue

        # Flush de la dernière section
        _flush_section()

        return structured_content

    except Exception as e:
        logger.error(f"Erreur parsing HTML: {str(e)}")
        return []


def extract_date_from_metadata(soup: BeautifulSoup) -> str:
    """
    Extrait la date de publication depuis les métadonnées HTML.

    Args:
        soup: BeautifulSoup object de la page

    Returns:
        Date au format YYYY-MM-DD, ou chaîne vide si non trouvée
    """
    try:
        # Chercher dans les meta tags
        meta_selectors = [
            ('meta', {'property': 'article:published_time'}),
            ('meta', {'property': 'article:published'}),
            ('meta', {'name': 'article:published_time'}),
            ('meta', {'name': 'publication_date'}),
            ('meta', {'name': 'publishdate'}),
            ('meta', {'name': 'date'}),
            ('meta', {'itemprop': 'datePublished'}),
            ('meta', {'itemprop': 'dateCreated'}),
            ('time', {'itemprop': 'datePublished'}),
            ('time', {'datetime': True}),
        ]

        for tag, attrs in meta_selectors:
            elem = soup.find(tag, attrs)
            if elem:
                # Récupérer le contenu
                date_str = elem.get('content') or elem.get('datetime') or elem.get_text()
                if date_str:
                    try:
                        parsed = parse_date(date_str)
                        if 2000 <= parsed.year <= 2100:  # Articles récents seulement
                            return parsed.strftime("%Y-%m-%d")
                    except Exception:
                        continue

        return ""

    except Exception as e:
        logger.debug(f"Erreur extraction date metadata: {str(e)}")
        return ""


def extract_date(text: str, soup: BeautifulSoup = None) -> str:
    """
    Extrait la date de publication d'un article.
    Priorité: 1) Métadonnées HTML, 2) Patterns contextuels dans le texte.

    Args:
        text: Texte de l'article
        soup: BeautifulSoup object (optionnel, pour métadonnées)

    Returns:
        Date au format YYYY-MM-DD, ou chaîne vide si non trouvée
    """
    try:
        # 1. Prioriser les métadonnées HTML (source la plus fiable)
        if soup:
            date_meta = extract_date_from_metadata(soup)
            if date_meta:
                logger.debug(f"Date extraite depuis métadonnées: {date_meta}")
                return date_meta

        # 2. Mapping des mois français
        mois_mapping = {
            'janvier': '01', 'février': '02', 'mars': '03', 'avril': '04',
            'mai': '05', 'juin': '06', 'juillet': '07', 'août': '08',
            'septembre': '09', 'octobre': '10', 'novembre': '11', 'décembre': '12'
        }

        # 3. Chercher des patterns contextuels dans les premiers 2000 caractères
        # (la date de publication apparaît généralement en début d'article)
        text_start = text.lower()[:2000]

        # Pattern avec mots-clés de publication + date en français
        pattern = r'(?:publié|publiée?|publication|date|posté|mis en ligne|écrit|rédigé)\s*(?:le)?\s*:?\s*(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})'

        match = re.search(pattern, text_start, re.IGNORECASE)
        if match:
            jour, mois_nom, annee = match.groups()
            try:
                mois = mois_mapping[mois_nom.lower()]
                jour = jour.zfill(2)
                date = datetime(int(annee), int(mois), int(jour))
                if 2000 <= date.year <= 2100:
                    logger.debug(f"Date extraite depuis pattern contextuel: {date.strftime('%Y-%m-%d')}")
                    return date.strftime("%Y-%m-%d")
            except (ValueError, KeyError):
                pass

        # Pattern avec mots-clés de publication + date numérique
        pattern_num = r'(?:publié|publiée?|publication|date|posté|mis en ligne|écrit|rédigé)\s*(?:le)?\s*:?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})'

        match = re.search(pattern_num, text_start, re.IGNORECASE)
        if match:
            jour, mois, annee = match.groups()
            try:
                jour = str(int(jour)).zfill(2)
                mois = str(int(mois)).zfill(2)
                date = datetime(int(annee), int(mois), int(jour))
                if 2000 <= date.year <= 2100:
                    logger.debug(f"Date extraite depuis pattern contextuel numérique: {date.strftime('%Y-%m-%d')}")
                    return date.strftime("%Y-%m-%d")
            except ValueError:
                pass

        logger.warning("Aucune date valide trouvée")
        return ""

    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de la date: {str(e)}")
        return ""


async def scrape_article(
    url: str,
    crawler: AsyncWebCrawler,
    max_retries: int = 3,
    js_script: str = DEFAULT_JS_SCRIPT
) -> Optional[Dict]:
    """
    Scrape un article avec retries et gestion des erreurs.

    Args:
        url: URL de l'article
        crawler: Instance AsyncWebCrawler
        max_retries: Nombre max de tentatives
        js_script: Script JavaScript à injecter

    Returns:
        Dict avec url, title, content, date ou None si échec
    """
    for attempt in range(max_retries):
        try:
            logger.info(f"Tentative {attempt + 1}/{max_retries} de scraping: {url}")

            # Configuration du crawler
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                js_code=[js_script],
                wait_until='networkidle'
            )

            result = await crawler.arun(url=url, config=run_config)

            if not result or not result.html:
                raise ValueError("Résultat vide")

            soup = BeautifulSoup(result.html, "lxml")
            structured_content = parse_html_content(soup)
            text_content = soup.get_text(separator=" ", strip=True)
            date = extract_date(text_content, soup)

            return {
                "url": url,
                "title": result.metadata.get("title", "page_sans_titre"),
                "content": structured_content,
                "date": date,
                "attempt": attempt + 1
            }

        except Exception as e:
            logger.error(f"Erreur lors du scraping de {url} (tentative {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            else:
                log_inaccessible_url(url, f"Erreur scraping: {str(e)}")

    return None


async def scrape_articles_batch(
    urls: List[str],
    crawler: AsyncWebCrawler,
    max_concurrent: int = 5,
    max_retries: int = 3
) -> List[Dict]:
    """
    Scrape un batch d'articles en parallèle avec limite de concurrence.

    Args:
        urls: Liste d'URLs à scraper
        crawler: Instance AsyncWebCrawler
        max_concurrent: Nombre max de scrapes en parallèle
        max_retries: Nombre max de retries par URL

    Returns:
        Liste de dicts avec les articles scrapés (excluant les échecs)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_with_semaphore(url: str):
        async with semaphore:
            return await scrape_article(url, crawler, max_retries)

    tasks = [scrape_with_semaphore(url) for url in urls]
    results = await asyncio.gather(*tasks)

    # Filtrer les None (échecs)
    return [r for r in results if r is not None]


def clean_content(content: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Nettoie le contenu en supprimant les sections non pertinentes.

    Args:
        content: Liste de sections structurées

    Returns:
        Liste nettoyée
    """
    return [
        section for section in content
        if does_make_sense(section.get("contenu_paragraphe", ""), strict=False)
    ]
