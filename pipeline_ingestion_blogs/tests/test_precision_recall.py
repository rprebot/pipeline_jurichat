"""
Test de précision et recall de l'extraction de références juridiques.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline_ingestion_blogs.content_processor import extract_legal_references_regex


# --- Ground truth : textes annotés avec les références attendues ---

TEST_CASES = [
    {
        "name": "Article de blog classique - droit du travail",
        "text": """
        Selon l'article L. 1234-1 du Code du travail, l'employeur doit respecter
        un préavis en cas de licenciement. L'article L. 1234-9 du Code du travail
        prévoit une indemnité de licenciement. Le Code civil, notamment son
        article 1240, s'applique en matière de responsabilité.
        La Cour de cassation, dans un arrêt du 15 janvier 2023 (pourvoi n° 21-12345.678),
        a confirmé cette position. Une décision antérieure du 3 mars 2022
        (pourvoi n° 20-98765.432) allait dans le même sens.
        """,
        "expected_codes": ["Code du travail", "Code civil"],
        "expected_cassation_pourvois": ["21-12345.678", "20-98765.432"],
        "expected_cassation_dates": ["2023-01-15", "2022-03-03"],
        "expected_appel_renvois": [],
    },
    {
        "name": "Droit de la consommation avec Cour d'appel",
        "text": """
        Le Code de la consommation impose des obligations d'information au
        professionnel (article L. 111-1 du Code de la consommation). Le Code
        de commerce s'applique également aux relations entre professionnels.
        La Cour d'appel de Paris, dans sa décision du 12 juin 2023
        (RG n° 22/01234), a jugé que le consommateur avait droit à réparation.
        La Cour d'appel de Lyon, le 8 novembre 2022 (RG n° 21/56789),
        a statué dans le même sens.
        """,
        "expected_codes": ["Code de la consommation", "Code de commerce"],
        "expected_cassation_pourvois": [],
        "expected_appel_renvois": ["22/01234", "21/56789"],
        "expected_appel_dates": ["2023-06-12", "2022-11-08"],
    },
    {
        "name": "Texte sans aucune référence juridique",
        "text": """
        Les nouvelles technologies transforment profondément le monde du travail.
        L'intelligence artificielle permet d'automatiser de nombreuses tâches.
        Les entreprises doivent s'adapter à ces changements rapides.
        """,
        "expected_codes": [],
        "expected_cassation_pourvois": [],
        "expected_appel_renvois": [],
    },
    {
        "name": "Multiples codes sans articles précis",
        "text": """
        Cette réforme touche plusieurs domaines : le Code pénal a été modifié
        pour renforcer les sanctions, le Code de procédure pénale prévoit de
        nouvelles garanties, et le Code de la sécurité intérieure encadre
        les pouvoirs de police. Le Code de l'environnement et le Code de
        l'urbanisme sont également concernés par ces dispositions.
        """,
        "expected_codes": [
            "Code pénal", "Code de procédure pénale",
            "Code de la sécurité intérieure", "Code de l'environnement",
            "Code de l'urbanisme"
        ],
        "expected_cassation_pourvois": [],
        "expected_appel_renvois": [],
    },
    {
        "name": "Variations d'apostrophes et espaces insécables",
        "text": "Le Code de l\u2019action sociale et des familles pr\u00e9voit des aides. "
                "Le Code\u00A0civil s\u2019applique \u00e9galement.",
        "expected_codes": ["Code de l'action sociale et des familles", "Code civil"],
        "expected_cassation_pourvois": [],
        "expected_appel_renvois": [],
    },
    {
        "name": "Normalisation de/du",
        "text": """
        L'article 123 du code de la route impose le respect des limitations.
        Les dispositions du code du travail maritime sont applicables aux marins.
        """,
        "expected_codes": ["Code de la route", "Code du travail maritime"],
        "expected_cassation_pourvois": [],
        "expected_appel_renvois": [],
    },
    {
        "name": "Dates abrégées pour pourvois",
        "text": """
        La Cour de cassation, le 5 janv. 2024 (pourvoi n° 23-11111.222),
        puis le 18 sept. 2023 (pourvoi n° 22-33333.444), et enfin
        le 2 déc. 2022 (pourvoi n° 21-55555.666), ont confirmé
        l'application du Code du travail.
        """,
        "expected_codes": ["Code du travail"],
        "expected_cassation_pourvois": ["23-11111.222", "22-33333.444", "21-55555.666"],
        "expected_cassation_dates": ["2024-01-05", "2023-09-18", "2022-12-02"],
        "expected_appel_renvois": [],
    },
    {
        "name": "Mélange codes + Cass. + CA",
        "text": """
        Au visa de l'article L. 3141-1 du Code du travail et de l'article 9
        du Code civil, la Cour de cassation (Cass. soc., 20 février 2023,
        pourvoi n° 22-10000.100) a cassé l'arrêt de la Cour d'appel de
        Versailles du 14 octobre 2022 (RG n° 21/98765). Le Code de la
        sécurité sociale est aussi visé.
        """,
        "expected_codes": ["Code du travail", "Code civil", "Code de la sécurité sociale"],
        "expected_cassation_pourvois": ["22-10000.100"],
        "expected_cassation_dates": ["2023-02-20"],
        "expected_appel_renvois": ["21/98765"],
        "expected_appel_dates": ["2022-10-14"],
    },
    {
        "name": "Faux positifs potentiels - numéros qui ressemblent à des références",
        "text": """
        Le chiffre d'affaires a augmenté de 12/34567 euros cette année.
        Le numéro de dossier interne est 99-12345.678 mais ce n'est pas un pourvoi.
        Contactez-nous au 01 23 45 67 89.
        """,
        "expected_codes": [],
        # Note: le pattern va quand même matcher 99-12345.678 et 12/34567
        # car il n'y a pas de validation contextuelle — on documente ces faux positifs
        "expected_cassation_pourvois": [],
        "expected_appel_renvois": [],
    },
    {
        "name": "Article réaliste - droit immobilier",
        "text": """
        En matière de copropriété, l'article 14 de la loi du 10 juillet 1965
        fixe les règles de gestion. Le Code de la construction et de l'habitation
        (articles L. 271-1 et suivants) impose un diagnostic technique.
        Le Code civil, dans ses articles 544 et 545, définit le droit de propriété.
        Le Code de l'urbanisme encadre les permis de construire.
        La Cour de cassation, 3e chambre civile, 15 mars 2023
        (pourvoi n° 22-15432.789), a rappelé ces principes.
        """,
        "expected_codes": [
            "Code de la construction et de l'habitation",
            "Code civil",
            "Code de l'urbanisme"
        ],
        "expected_cassation_pourvois": ["22-15432.789"],
        "expected_cassation_dates": ["2023-03-15"],
        "expected_appel_renvois": [],
    },
]


def compute_precision_recall(predicted: set, expected: set):
    """Calcule précision et recall."""
    if not predicted and not expected:
        return 1.0, 1.0  # Aucun attendu, aucun prédit = parfait
    tp = len(predicted & expected)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 0.0
    return precision, recall


def f1_score(precision, recall):
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def run_tests():
    print("\n" + "=" * 80)
    print("TEST DE PRÉCISION ET RECALL — EXTRACTION DE RÉFÉRENCES JURIDIQUES")
    print("=" * 80)

    # Accumulateurs globaux
    totals = {
        "codes": {"tp": 0, "fp": 0, "fn": 0},
        "cassation_pourvois": {"tp": 0, "fp": 0, "fn": 0},
        "cassation_dates": {"tp": 0, "fp": 0, "fn": 0},
        "appel_renvois": {"tp": 0, "fp": 0, "fn": 0},
        "appel_dates": {"tp": 0, "fp": 0, "fn": 0},
    }

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n{'─' * 80}")
        print(f"  Cas {i}: {case['name']}")
        print(f"{'─' * 80}")

        result = extract_legal_references_regex(case["text"])

        # --- Codes ---
        pred_codes = set(result["codes"].keys())
        exp_codes = set(case["expected_codes"])
        p, r = compute_precision_recall(pred_codes, exp_codes)
        tp = len(pred_codes & exp_codes)
        fp = len(pred_codes - exp_codes)
        fn = len(exp_codes - pred_codes)
        totals["codes"]["tp"] += tp
        totals["codes"]["fp"] += fp
        totals["codes"]["fn"] += fn

        print(f"  Codes    | attendus: {sorted(exp_codes) or '∅'}")
        print(f"           | trouvés:  {sorted(pred_codes) or '∅'}")
        if fp > 0:
            print(f"           | FP: {sorted(pred_codes - exp_codes)}")
        if fn > 0:
            print(f"           | FN: {sorted(exp_codes - pred_codes)}")
        print(f"           | P={p:.0%}  R={r:.0%}  F1={f1_score(p, r):.0%}")

        # --- Pourvois Cass. ---
        pred_pourvois = set(d["pourvoi"] for d in result["cour_cassation"])
        exp_pourvois = set(case["expected_cassation_pourvois"])
        p, r = compute_precision_recall(pred_pourvois, exp_pourvois)
        tp = len(pred_pourvois & exp_pourvois)
        fp = len(pred_pourvois - exp_pourvois)
        fn = len(exp_pourvois - pred_pourvois)
        totals["cassation_pourvois"]["tp"] += tp
        totals["cassation_pourvois"]["fp"] += fp
        totals["cassation_pourvois"]["fn"] += fn

        if exp_pourvois or pred_pourvois:
            print(f"  Cass.    | attendus: {sorted(exp_pourvois) or '∅'}")
            print(f"           | trouvés:  {sorted(pred_pourvois) or '∅'}")
            if fp > 0:
                print(f"           | FP: {sorted(pred_pourvois - exp_pourvois)}")
            if fn > 0:
                print(f"           | FN: {sorted(exp_pourvois - pred_pourvois)}")
            print(f"           | P={p:.0%}  R={r:.0%}  F1={f1_score(p, r):.0%}")

        # --- Dates Cass. ---
        if "expected_cassation_dates" in case:
            pred_dates = set(
                d["date"] for d in result["cour_cassation"] if d["date"]
            )
            exp_dates = set(case["expected_cassation_dates"])
            p, r = compute_precision_recall(pred_dates, exp_dates)
            tp = len(pred_dates & exp_dates)
            fp = len(pred_dates - exp_dates)
            fn = len(exp_dates - pred_dates)
            totals["cassation_dates"]["tp"] += tp
            totals["cassation_dates"]["fp"] += fp
            totals["cassation_dates"]["fn"] += fn

            if exp_dates or pred_dates:
                print(f"  Dates C. | attendues: {sorted(exp_dates) or '∅'}")
                print(f"           | trouvées:  {sorted(pred_dates) or '∅'}")
                if fn > 0:
                    print(f"           | FN: {sorted(exp_dates - pred_dates)}")
                print(f"           | P={p:.0%}  R={r:.0%}  F1={f1_score(p, r):.0%}")

        # --- Renvois CA ---
        pred_renvois = set(d["renvoi"] for d in result["cour_appel"])
        exp_renvois = set(case["expected_appel_renvois"])
        p, r = compute_precision_recall(pred_renvois, exp_renvois)
        tp = len(pred_renvois & exp_renvois)
        fp = len(pred_renvois - exp_renvois)
        fn = len(exp_renvois - pred_renvois)
        totals["appel_renvois"]["tp"] += tp
        totals["appel_renvois"]["fp"] += fp
        totals["appel_renvois"]["fn"] += fn

        if exp_renvois or pred_renvois:
            print(f"  CA       | attendus: {sorted(exp_renvois) or '∅'}")
            print(f"           | trouvés:  {sorted(pred_renvois) or '∅'}")
            if fp > 0:
                print(f"           | FP: {sorted(pred_renvois - exp_renvois)}")
            if fn > 0:
                print(f"           | FN: {sorted(exp_renvois - pred_renvois)}")
            print(f"           | P={p:.0%}  R={r:.0%}  F1={f1_score(p, r):.0%}")

        # --- Dates CA ---
        if "expected_appel_dates" in case:
            pred_dates = set(
                d["date"] for d in result["cour_appel"] if d["date"]
            )
            exp_dates = set(case["expected_appel_dates"])
            p, r = compute_precision_recall(pred_dates, exp_dates)
            tp = len(pred_dates & exp_dates)
            fp = len(pred_dates - exp_dates)
            fn = len(exp_dates - pred_dates)
            totals["appel_dates"]["tp"] += tp
            totals["appel_dates"]["fp"] += fp
            totals["appel_dates"]["fn"] += fn

            if exp_dates or pred_dates:
                print(f"  Dates CA | attendues: {sorted(exp_dates) or '∅'}")
                print(f"           | trouvées:  {sorted(pred_dates) or '∅'}")
                if fn > 0:
                    print(f"           | FN: {sorted(exp_dates - pred_dates)}")
                print(f"           | P={p:.0%}  R={r:.0%}  F1={f1_score(p, r):.0%}")

    # --- Scores globaux ---
    print("\n" + "=" * 80)
    print("  SCORES GLOBAUX (micro-average sur tous les cas de test)")
    print("=" * 80)

    header = f"  {'Catégorie':<22} {'TP':>4} {'FP':>4} {'FN':>4} {'Précision':>10} {'Recall':>10} {'F1':>10}"
    print(header)
    print("  " + "─" * 76)

    all_tp = all_fp = all_fn = 0

    for cat, label in [
        ("codes", "Codes juridiques"),
        ("cassation_pourvois", "Pourvois Cass."),
        ("cassation_dates", "Dates Cass."),
        ("appel_renvois", "Renvois CA"),
        ("appel_dates", "Dates CA"),
    ]:
        t = totals[cat]
        tp, fp, fn = t["tp"], t["fp"], t["fn"]
        all_tp += tp
        all_fp += fp
        all_fn += fn

        prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = f1_score(prec, rec)

        print(f"  {label:<22} {tp:>4} {fp:>4} {fn:>4} {prec:>9.1%} {rec:>9.1%} {f1:>9.1%}")

    # Total
    prec_all = all_tp / (all_tp + all_fp) if (all_tp + all_fp) > 0 else 1.0
    rec_all = all_tp / (all_tp + all_fn) if (all_tp + all_fn) > 0 else 1.0
    f1_all = f1_score(prec_all, rec_all)

    print("  " + "─" * 76)
    print(f"  {'TOTAL':<22} {all_tp:>4} {all_fp:>4} {all_fn:>4} {prec_all:>9.1%} {rec_all:>9.1%} {f1_all:>9.1%}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_tests()
