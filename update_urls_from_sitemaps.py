"""
Script pour extraire toutes les URLs des sitemaps et créer un fichier avec les URLs non encore traitées.

Usage:
    python update_urls_from_sitemaps.py

Ce script va :
1. Parser tous les sitemaps définis dans blog_base/sitemap_urls.py
2. Vérifier quelles URLs sont déjà dans l'historique (historique_savings/historique_urls.db)
3. Créer un fichier daté dans URL_to_ingest/ avec les URLs non encore traitées
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Set

# Import des modules de la pipeline
from pipeline_ingestion_blogs.logger import setup_logger
from pipeline_ingestion_blogs.sitemap_parser import extract_all_article_urls
from pipeline_ingestion_blogs.historique_manager import HistoriqueManager
from pipeline_ingestion_blogs.url_utils import normalize_url, is_valid_url

# Import de la liste des sitemaps
try:
    from blog_base.sitemap_urls import sitemap_urls
except ImportError:
    print("ERREUR: Impossible d'importer sitemap_urls depuis blog_base/sitemap_urls.py")
    sys.exit(1)


async def main():
    """
    Fonction principale pour extraire et filtrer les URLs.
    """
    print("\n" + "="*70)
    print("EXTRACTION DES URLs DEPUIS LES SITEMAPS")
    print("="*70 + "\n")

    start_time = datetime.now()

    # Setup logger
    logger = setup_logger()
    logger.info("Démarrage de l'extraction des URLs depuis les sitemaps")

    # Initialiser le gestionnaire d'historique
    historique = HistoriqueManager()
    logger.info("Gestionnaire d'historique initialisé")

    # ====== 1. PARSING DES SITEMAPS ======
    logger.info(f"Parsing de {len(sitemap_urls)} sitemaps")
    print(f"Étape 1/3: Parsing des sitemaps ({len(sitemap_urls)} sitemaps)")

    try:
        article_urls = await extract_all_article_urls(sitemap_urls, max_concurrent=10)
        logger.info(f"URLs extraites: {len(article_urls)}")
        print(f"  → {len(article_urls)} URLs d'articles extraites\n")
    except Exception as e:
        logger.critical(f"Erreur parsing sitemaps: {str(e)}")
        print(f"ERREUR: {str(e)}")
        sys.exit(1)

    # ====== 2. VÉRIFICATION DANS L'HISTORIQUE ======
    logger.info("Vérification des URLs déjà traitées dans l'historique")
    print(f"Étape 2/3: Vérification de l'historique")

    # Charger l'historique (URLs avec succès uniquement)
    processed_urls = historique.get_processed_urls()
    logger.info(f"URLs déjà traitées (historique): {len(processed_urls)}")
    print(f"  → {len(processed_urls)} URLs déjà traitées dans l'historique\n")

    # ====== 3. FILTRAGE DES NOUVELLES URLs ======
    logger.info("Filtrage des nouvelles URLs")
    print(f"Étape 3/3: Filtrage des nouvelles URLs")

    # Normaliser et filtrer
    new_urls = [
        url for url in article_urls
        if is_valid_url(url) and normalize_url(url) not in processed_urls
    ]

    logger.info(f"Nouvelles URLs à traiter: {len(new_urls)}")
    print(f"  → {len(new_urls)} nouvelles URLs à traiter")

    # ====== 4. SAUVEGARDE DANS UN FICHIER DATÉ ======
    if len(new_urls) == 0:
        print("\n✓ Aucune nouvelle URL à traiter.")
        print("  Tous les articles des sitemaps ont déjà été traités.\n")
        logger.info("Aucune nouvelle URL à traiter")
        return

    # Créer le dossier s'il n'existe pas
    output_dir = Path("URL_to_ingest")
    output_dir.mkdir(exist_ok=True)

    # Nom du fichier avec la date du jour
    date_str = datetime.now().strftime("%Y%m%d")
    output_file = output_dir / f"urls_{date_str}.json"

    # Si le fichier existe déjà, ajouter un suffixe avec l'heure
    if output_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"urls_{timestamp}.json"

    # Préparer les données
    data = {
        "created_at": datetime.now().isoformat(),
        "total_urls": len(new_urls),
        "source": "sitemaps",
        "urls": sorted(new_urls)  # Trier pour faciliter la lecture
    }

    # Sauvegarder
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Fichier créé: {output_file}")
        print(f"\n✓ Fichier créé avec succès: {output_file}")
        print(f"  Contient {len(new_urls)} URLs à traiter\n")

    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde du fichier: {str(e)}")
        print(f"\nERREUR lors de la sauvegarde: {str(e)}")
        sys.exit(1)

    # ====== 5. STATISTIQUES FINALES ======
    end_time = datetime.now()
    duration = end_time - start_time

    print("="*70)
    print("EXTRACTION TERMINÉE")
    print("="*70)
    print(f"\nDurée totale: {duration}")
    print(f"\nStatistiques:")
    print(f"  Sitemaps parsés: {len(sitemap_urls)}")
    print(f"  URLs extraites: {len(article_urls)}")
    print(f"  URLs déjà traitées: {len(processed_urls)}")
    print(f"  Nouvelles URLs: {len(new_urls)}")
    print(f"\n📄 Fichier généré: {output_file}")
    print(f"\nProchaine étape:")
    print(f"  python scrape_and_update_qdrant_collection.py")
    print("\n" + "="*70 + "\n")

    logger.info(f"Extraction terminée. Durée: {duration}")
    logger.info(f"Fichier généré: {output_file} avec {len(new_urls)} URLs")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nExtraction interrompue par l'utilisateur (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\nERREUR CRITIQUE: {str(e)}")
        sys.exit(1)
