import re
import json
import unicodedata
from listes_utiles import CODES_LOI


def extract_context(text, start_idx, length=150):
    """Extrait un contexte avant un index donné dans le texte."""
    context_start = max(0, start_idx - length)
    return text[context_start:start_idx]





def extract_date_from_context(context):
    """Extrait une date au format 'XX mois XXXX' ou 'XX/XX/XXXX' d'un contexte donné."""
    # Pattern pour le format "XX mois XXXX"
    date_pattern_1 = r'(?:Le\s+)?(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})'
    # Pattern pour le format "XX/XX/XXXX"
    date_pattern_2 = r'(\d{1,2})/(\d{1,2})/(\d{4})'
    
    # Essayer d'abord le format avec le nom du mois
    match = re.search(date_pattern_1, context, re.IGNORECASE)
    if match:
        jour, mois, annee = match.groups()
        return f"{annee}-{mois_to_number(mois)}-{jour.zfill(2)}"
    
    # Si pas trouvé, essayer le format avec les slashes
    match = re.search(date_pattern_2, context)
    if match:
        jour, mois, annee = match.groups()
        return f"{annee}-{mois.zfill(2)}-{jour.zfill(2)}"
    
    return None

def normalize_text(text):
    """Normalise un texte en supprimant les accents et en le mettant en minuscule."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', text.lower())
        if unicodedata.category(c) != 'Mn'
    )

def mois_to_number(mois):
    """Convertit le nom d'un mois ou son abréviation en numéro."""
    mois_dict = {
        'janvier': '01', 'janv': '01',
        'février': '02', 'fevrier': '02', 'févr': '02', 'fevr': '02',
        'mars': '03',
        'avril': '04',
        'mai': '05',
        'juin': '06',
        'juillet': '07', 'juil': '07',
        'août': '08', 'aout': '08',
        'septembre': '09', 'sept': '09',
        'octobre': '10', 'oct': '10',
        'novembre': '11', 'nov': '11',
        'décembre': '12', 'decembre': '12', 'déc': '12', 'dec': '12'
    }
    normalized_mois = normalize_text(mois)
    return mois_dict.get(normalized_mois, None)


def format_cour_appel_decisions(text):
    """Formate les décisions de la Cour d'appel en extrayant numéro de renvoi et date."""
    renvoi_pattern = r'\b\d{2}/\d{5}\b'
    cour_appel_decisions = []

    for match in re.finditer(renvoi_pattern, text):
        renvoi = match.group()
        context = extract_context(text, match.start())
        print(f"Contexte extrait pour le renvoi '{renvoi}': {context}")

        date_str = extract_date_from_context(context)

        cour_appel_decisions.append({
            "renvoi": renvoi,
            "date": date_str
        })

    return cour_appel_decisions

def format_cour_cassation_decisions(text):
    """Formate les décisions de la Cour d'appel en extrayant numéro de renvoi et date."""
    pourvoi_pattern = r'\b\d{2,5}-\d{2,5}\.\d{2,5}\b'
    cour_cassation_decisions = []

    for match in re.finditer(pourvoi_pattern, text):
        renvoi = match.group()
        context = extract_context(text, match.start())
        print(f"Contexte extrait pour le renvoi '{renvoi}': {context}")

        date_str = extract_date_from_context(context)

        cour_cassation_decisions.append({
            "renvoi": renvoi,
            "date": date_str
        })

    return cour_cassation_decisions


def normalize_code_name(code):
    """Normalise le nom du code en gérant les variations 'de'/'du'."""
    # Remplacer "du" par "de" pour la normalisation
    normalized = code.replace(" du ", " de ")
    return normalized

def find_code_in_context(context):
    """Trouve le code dans le contexte donné en gérant les variations 'de'/'du'."""
    codes = CODES_LOI
    context_lower = context.lower()
    
    for code in codes:
        # Normaliser le code et le contexte pour la comparaison
        normalized_code = normalize_code_name(code.lower())
        normalized_context = normalize_code_name(context_lower)
        
        # Vérifier si le code normalisé est présent dans le contexte normalisé
        if normalized_code in normalized_context:
            return code
    
    return None

def format_article_loi(text):
    """Extrait les références d'articles de loi d'un texte avec leur code associé."""
    # Liste des patterns pour les différents formats d'articles
    article_patterns = [
        # Format "Article XXX" ou similaire
        r'(?:Article|Articles|article|articles|art\.|Art\.)\s+(?:\d{1,7})(?:\s+et\s+suivant(?:s)?)?',
        
        # Format "Article n° XXX" ou similaire
        r'(?:Article|Articles|article|articles|art\.|Art\.)\s+n°\s+(?:\d{1,7})(?:\s+et\s+suivant(?:s)?)?',
        
        # Format "LXXX-Y-ZZ" avec toutes les variations possibles
        r'[lL](?:\.\s?|\s)?\d{2,4}(?:-\d{1,4})?(?:-\d)?',

        # Format "RXXX-Y-ZZ" avec toutes les variations possibles
        r'[rR](?:\.\s?|\s)?\d{2,4}(?:-\d{1,4})?(?:-\d)?',

        # Format "DXXX-Y-ZZ" avec toutes les variations possibles
        r'[dD](?:\.\s?|\s)?\d{2,4}(?:-\d{1,4})?(?:-\d)?',
    ]
    
    articles = []
    seen_articles = set()  # Pour éviter les doublons
    
    # Recherche de tous les patterns dans le texte
    for pattern in article_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            article = match.group()
            article = re.sub(r'\s+', ' ', article).strip()
            
            # Extraire le contexte autour de l'article
            start_idx = match.start()
            context_start = max(0, start_idx - 150)
            context_end = min(len(text), start_idx + 150)
            context = text[context_start:context_end]
            
            # Calculer la position relative de l'article dans le contexte
            article_position_in_context = start_idx - context_start
            
            # Trouver le code associé en passant la position de l'article
            code = find_code_in_context(context)
            
            # Créer l'entrée pour l'article
            article_entry = {
                "article": article,
                "code": code if code else "Code non identifié"
            }
            
            # Éviter les doublons en utilisant un set
            article_key = f"{article}_{code}"
            if article_key not in seen_articles:
                seen_articles.add(article_key)
                articles.append(article_entry)
    
    return articles


if __name__ == "__main__":
    # Test unitaire
    test_text = """32-6 publient, chaque année, le nombre de femmes et d’hommes nommés dans les emplois soumis à l’obligation prévue à l’article L. 132-5. Ces chiffres sont rendus publics sur le site internet du ministère chargé de la fonction publique. « Art. L. 132-6-2. – En cas de non-respect de l’obligation de publication mentionnée à l’article L. 132-6-1, une contribution est due, selon le cas, par le département ministériel intéressé, par la collectivité territoriale ou l’établissement public de coopération intercommunale concerné ou par l’établissement public mentionné à l’article L. 5 concerné.« Le montant de cette contribution est forfaitaire. » Article 4 I. – L’article L. 132-5 du code général de la fonction publique est ainsi modifié :1° Au 1°, après le mot : « emplois », sont insérés les mots : « ou fonctions » ;2° Au 3°, les mots : « de direction des » sont remplacés par les mots : « comportant un mandat exécutif de dirigeant d’ » ;3° Au 5°, après le mot : « Emplois », il est inséré le mot : « supérieurs » ;4° Après le même 5°, il est inséré un 6° ainsi rédigé :« 6° Fonctions mentionnées au quatrième alinéa de l’article L. 6146-1 du code de la santé publique et au deuxième alinéa de l’article L. 6146-1-1 du même code, lorsque l’établissement dispose d’un nombre de ces fonctions au moins égal à un nombre défini par décret. » ;5° Le dernier alinéa est complété par les mots : « ou un même type de fonction ».II. – Le premier alinéa de l’article L. 132-8 du code général de la fonction publique est ainsi modifié :1° Après le mot : « emplois », il est inséré le mot : « supérieurs » ;2° Est ajoutée une phrase ainsi rédigée : « Pour les fonctions mentionnées au quatrième alinéa de l’article L. 6146-1 du code de la santé publique et au deuxième alinéa de l’article L. 6146-1-1 du même code, cette contribution est due par l’établissement employeur. » Article 5 Le code des juridictions financières est ainsi modifié :1° L’article L. 121-1 est complété par un alinéa ainsi rédigé :« Ces nominations favorisent l’égal accès des femmes et des hommes aux fonctions de premier président et de président de chambre. » ;2° L’article L. 212-2 est complété par un alinéa ainsi rédigé :« Les nominations des présidents de chambre régionale des comptes tiennent compte de l’objectif d’égal accès des femmes et des hommes à cette fonction. » Article 6 Le code de justice administrative est ainsi modifié :1° L’article L. 133-2 est complété par un alinéa ainsi rédigé :« Ces nominations favorisent l’égal accès des femmes et des hommes à la fonction de président de section. » ;2° L’article L. 234-5 est complété par un alinéa ainsi rédigé :« Ces nominations favorisent l’égal accès des femmes et des hommes à ces fonctions. » Article 7 I. – La section 2 du chapitre II du titre III du livre Ier du code général de la fonction publique est complétée par un article L. 132-9-1 ainsi rédigé : « Art. L. 132-9-1. – La proportion de personnes de même sexe parmi les personnes occupant les emplois mentionnés aux 1° à 6° de l’article L. 132-5 ne peut être inférieure à 40 %. Le respect de cette obligation est apprécié, au terme de chaque année civile, par département ministériel pour l’Etat et ses établissements publics, par autorité territoriale, par établissement public de coopération intercommunale et globalement pour les établissements publics mentionnés à l’article L. 5.« Lorsque l’employeur ne se conforme pas à l’obligation prévue au premier alinéa du présent article, il dispose d’un délai de trois ans pour se mettre en conformité. Il publie"""
    
    result = format_article_loi(test_text)
    print("Articles trouvés:", json.dumps(result1, indent=2, ensure_ascii=False))

