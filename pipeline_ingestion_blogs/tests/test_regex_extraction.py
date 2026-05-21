"""
Test de l'extraction REGEX des codes juridiques.
"""

import sys
from pathlib import Path

# Ajouter le parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from juridic_reference_extraction import extract_legal_references_regex


def test_regex_extraction():
    """Teste l'extraction REGEX des codes juridiques."""

    print("\n" + "="*70)
    print("TEST D'EXTRACTION REGEX DES CODES JURIDIQUES")
    print("="*70 + "\n")

    # Test 1: Texte avec plusieurs codes
    test_text_1 = """
    Selon l'article L. 1234-1 du Code du travail, l'employeur doit respecter
    certaines obligations. Le Code civil prévoit également des dispositions
    relatives aux contrats. Le Code de la sécurité sociale s'applique aux
    cotisations.
    """

    print("Test 1: Texte avec Code du travail, Code civil, Code de la sécurité sociale")
    result_1 = extract_legal_references_regex(test_text_1)
    codes_1 = result_1["codes"]
    print(f"  Codes trouvés: {codes_1}")
    assert "Code du travail" in codes_1
    assert "Code civil" in codes_1
    assert "Code de la sécurité sociale" in codes_1
    print("  ✓ Test 1 réussi\n")

    # Test 2: Texte avec variations de/du
    test_text_2 = """
    L'article 123 du code de la route impose le respect des limitations.
    """

    print("Test 2: Texte avec 'du code de' (normalisation de/du)")
    result_2 = extract_legal_references_regex(test_text_2)
    codes_2 = result_2["codes"]
    print(f"  Codes trouvés: {codes_2}")
    assert "Code de la route" in codes_2
    print("  ✓ Test 2 réussi\n")

    # Test 3: Texte sans code
    test_text_3 = """
    Ce texte ne mentionne aucun code juridique spécifique.
    Il parle juste de loi en général.
    """

    print("Test 3: Texte sans code")
    result_3 = extract_legal_references_regex(test_text_3)
    codes_3 = result_3["codes"]
    print(f"  Codes trouvés: {codes_3}")
    assert len(codes_3) == 0
    print("  ✓ Test 3 réussi\n")

    # Test 4: Texte avec de nombreux codes
    test_text_4 = """
    Cette décision s'appuie sur le Code du travail, le Code civil,
    le Code pénal, le Code de commerce, et le Code général des impôts.
    Également le Code de procédure civile et le Code de la consommation.
    """

    print("Test 4: Texte avec 7 codes différents")
    result_4 = extract_legal_references_regex(test_text_4)
    codes_4 = result_4["codes"]
    print(f"  Codes trouvés ({len(codes_4)}): {codes_4}")
    assert len(codes_4) >= 7
    print("  ✓ Test 4 réussi\n")

    # Test 5: Texte réel d'un article de blog juridique
    test_text_5 = """
    La loi du 5 mars 2014 relative à la formation professionnelle a modifié
    plusieurs articles du Code du travail. L'article L. 6323-1 du Code du
    travail définit le compte personnel de formation (CPF). Les dispositions
    du Code de l'éducation s'appliquent également pour certaines formations.
    """

    print("Test 5: Texte réaliste d'article juridique")
    result_5 = extract_legal_references_regex(test_text_5)
    codes_5 = result_5["codes"]
    print(f"  Codes trouvés: {codes_5}")
    assert "Code du travail" in codes_5
    assert "Code de l'éducation" in codes_5
    print("  ✓ Test 5 réussi\n")

    # Test 6: Texte de decision Cour de cassation - article L. 3323-4 du Code de la sante publique
    test_text_6 = """Il résulte de l'article L. 3323-4, alinéa 3, du code de la santé publique que le conditionnement d'une boisson alcoolique ne peut être reproduit dans une publicité que s'il est conforme aux dispositions du premier alinéa de ce texte, qui énumère limitativement les indications permises dans le cadre de la publicité autorisée pour de telles boissons. Il s'en déduit que ce conditionnement n'est pas en lui-même soumis aux dispositions de ce premier alinéa. Encourt la cassation l'arrêt qui, pour déclarer la prévenue coupable de publicité illicite pour une boisson alcoolique en raison de mentions présentes sur les étiquettes des bouteilles contenant la boisson concernée, indépendamment de leur reproduction dans une publicité, retient que dès lors que le conditionnement est utilisé à des fins publicitaires, il n'échappe pas aux restrictions relatives à la publicité Selon l'article L. 3323-4 du code de la santé publique, la publicité autorisée pour les boissons alcooliques est  volumique d'alcool, de l'origine, de la dénomination, de la composition du produit, du nom et de l'adresse du fabricant, des agents et des dépositaires ainsi que du mode d'élaboration, des modalités de vente et du mode de consommation du produit. Encourt la cassation l'arrêt qui déclare la prévenue coupable de publicité illicite pour une boisson alcoolique en raison de l'usage du nom « Levrette » sur son site internet, alors que ce terme, nom commercial sous lequel les boissons concernées étaient vendues, constitue leur dénomination"""

    print("Test 6: Decision CC - article L. 3323-4 du Code de la sante publique")
    result_6 = extract_legal_references_regex(test_text_6)
    codes_6 = result_6["codes"]
    print(f"  Codes trouvés: {codes_6}")
    assert "Code de la santé publique" in codes_6, f"Code de la santé publique non trouvé dans {codes_6}"
    assert "L. 3323-4" in codes_6["Code de la santé publique"], f"L. 3323-4 non trouvé dans {codes_6['Code de la santé publique']}"
    print("  ✓ Test 6 réussi\n")

    print("="*70)
    print("✅ TOUS LES TESTS REGEX SONT PASSÉS!")
    print("="*70 + "\n")

    print("Comparaison LLM vs REGEX:")
    print("  - LLM: ~2-5 secondes par article + coût API")
    print("  - REGEX: ~0.001 secondes par article + gratuit")
    print("  - Précision: REGEX détecte les mentions explicites (meilleure précision)")
    print()


if __name__ == "__main__":
    test_regex_extraction()
