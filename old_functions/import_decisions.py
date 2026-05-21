#!/usr/bin/env python3
"""
Script principal pour l'importation des décisions juridiques.

Usage:
    # Import d'un mois spécifique
    python import_decisions.py import_ca --start-month 12 --start-year 2024
    
    # Import d'une plage de dates
    python import_decisions.py import_ca --start-month 10 --start-year 2024 --end-month 12 --end-year 2024
    python import_decisions.py import_cc --start-month 1 --start-year 2023 --end-month 12 --end-year 2024

Commandes disponibles:
- import_ca: Importe les décisions de Cour d'appel
- import_cc: Importe les décisions de Cour de cassation

Options:
- --start-month, -sm: Mois de début (1-12)
- --start-year, -sy: Année de début
- --end-month, -em: Mois de fin (1-12, optionnel, défaut: même que start-month)
- --end-year, -ey: Année de fin (optionnel, défaut: même que start-year)
- --verbose, -v: Mode verbeux
- --help, -h: Afficher l'aide
"""
import sys
import argparse
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple

from decision_importer import validate_month_year, setup_logging
from ca_importer import create_ca_importer
from cc_importer import create_cc_importer

def generate_month_year_range(start_month: int, start_year: int, end_month: int, end_year: int) -> List[Tuple[int, int]]:
    """
    Génère une liste de tuples (mois, année) pour la plage spécifiée.
    
    Args:
        start_month: Mois de début (1-12)
        start_year: Année de début
        end_month: Mois de fin (1-12)
        end_year: Année de fin
        
    Returns:
        Liste de tuples (mois, année)
    """
    dates = []
    current_month = start_month
    current_year = start_year
    
    while (current_year < end_year) or (current_year == end_year and current_month <= end_month):
        dates.append((current_month, current_year))
        
        # Passer au mois suivant
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1
    
    return dates

def setup_cli_logging(verbose: bool = False) -> None:
    """Configure le logging pour l'interface en ligne de commande."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('import_decisions.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def print_stats(stats: Dict[str, Any], jurisdiction: str, period: str) -> None:
    """Affiche les statistiques d'importation."""
    print(f"\n=== Statistiques d'importation {jurisdiction.upper()} {period} ===")
    print(f"📊 Total de décisions trouvées: {stats['total']}")
    print(f"✅ Décisions traitées: {stats['processed']}")
    print(f"⏭️  Décisions ignorées (déjà présentes): {stats['skipped']}")
    
    if stats['total'] > 0:
        success_rate = (stats['processed'] / stats['total']) * 100
        print(f"📈 Taux de traitement: {success_rate:.1f}%")
    
    print(f"⏱️  Temps d'exécution: {stats['elapsed_time_seconds']:.2f}s")
    print(f"💾 Mémoire utilisée: {stats['memory_used_mb']:.2f}MB")
    print("=" * 50)

def import_ca_command(start_month: int, start_year: int, end_month: int, end_year: int, verbose: bool = False) -> None:
    """Exécute l'importation des décisions CA pour une plage de dates."""
    try:
        # Génération de la plage de dates
        date_range = generate_month_year_range(start_month, start_year, end_month, end_year)
        
        if len(date_range) == 1:
            period = f"{start_month:02d}/{start_year}"
        else:
            period = f"{start_month:02d}/{start_year} à {end_month:02d}/{end_year}"
        
        print(f"🏛️  Début de l'importation des décisions CA pour {period}")
        print(f"📅 Nombre de mois à traiter: {len(date_range)}")
        
        # Création de l'importateur CA
        importer = create_ca_importer()
        
        # Statistiques globales
        total_stats = {'total': 0, 'processed': 0, 'skipped': 0, 'elapsed_time_seconds': 0.0, 'memory_used_mb': 0.0}
        
        # Traitement de chaque mois
        for i, (month, year) in enumerate(date_range, 1):
            print(f"\n📆 Traitement du mois {i}/{len(date_range)}: {month:02d}/{year}")
            
            # Validation des paramètres
            month, year = validate_month_year(month, year)
            
            # Importation pour ce mois
            stats = importer.import_decisions_for_month(year, month)
            
            # Accumulation des statistiques
            total_stats['total'] += stats['total']
            total_stats['processed'] += stats['processed']
            total_stats['skipped'] += stats['skipped']
            total_stats['elapsed_time_seconds'] += stats['elapsed_time_seconds']
            total_stats['memory_used_mb'] = max(total_stats['memory_used_mb'], stats['memory_used_mb'])
            
            print(f"   ✅ {stats['processed']} décisions traitées, {stats['skipped']} ignorées")
        
        # Affichage des résultats globaux
        print_stats(total_stats, "ca", period)
        
        if total_stats['processed'] > 0:
            print("✅ Importation CA terminée avec succès!")
        else:
            print("ℹ️  Aucune nouvelle décision CA à traiter.")
            
    except Exception as e:
        print(f"❌ Erreur lors de l'importation CA: {e}")
        sys.exit(1)

def import_cc_command(start_month: int, start_year: int, end_month: int, end_year: int, verbose: bool = False) -> None:
    """Exécute l'importation des décisions CC pour une plage de dates."""
    try:
        # Génération de la plage de dates
        date_range = generate_month_year_range(start_month, start_year, end_month, end_year)
        
        if len(date_range) == 1:
            period = f"{start_month:02d}/{start_year}"
        else:
            period = f"{start_month:02d}/{start_year} à {end_month:02d}/{end_year}"
        
        print(f"⚖️  Début de l'importation des décisions CC pour {period}")
        print(f"📅 Nombre de mois à traiter: {len(date_range)}")
        
        # Création de l'importateur CC
        importer = create_cc_importer()
        
        # Statistiques globales
        total_stats = {'total': 0, 'processed': 0, 'skipped': 0, 'elapsed_time_seconds': 0.0, 'memory_used_mb': 0.0}
        
        # Traitement de chaque mois
        for i, (month, year) in enumerate(date_range, 1):
            print(f"\n📆 Traitement du mois {i}/{len(date_range)}: {month:02d}/{year}")
            
            # Validation des paramètres
            month, year = validate_month_year(month, year)
            
            # Importation pour ce mois
            stats = importer.import_decisions_for_month(year, month)
            
            # Accumulation des statistiques
            total_stats['total'] += stats['total']
            total_stats['processed'] += stats['processed']
            total_stats['skipped'] += stats['skipped']
            total_stats['elapsed_time_seconds'] += stats['elapsed_time_seconds']
            total_stats['memory_used_mb'] = max(total_stats['memory_used_mb'], stats['memory_used_mb'])
            
            print(f"   ✅ {stats['processed']} décisions traitées, {stats['skipped']} ignorées")
        
        # Affichage des résultats globaux
        print_stats(total_stats, "cc", period)
        
        if total_stats['processed'] > 0:
            print("✅ Importation CC terminée avec succès!")
        else:
            print("ℹ️  Aucune nouvelle décision CC à traiter.")
            
    except Exception as e:
        print(f"❌ Erreur lors de l'importation CC: {e}")
        sys.exit(1)

def create_parser() -> argparse.ArgumentParser:
    """Crée le parser d'arguments."""
    parser = argparse.ArgumentParser(
        description="Importation des décisions juridiques dans Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  
  # Importer les décisions CA de décembre 2024
  python import_decisions.py import_ca --start-month 12 --start-year 2024
  
  # Importer les décisions CA d'octobre à décembre 2024
  python import_decisions.py import_ca --start-month 10 --start-year 2024 --end-month 12 --end-year 2024
  
  # Importer les décisions CC de 2023 à 2024 (janvier 2023 à décembre 2024)
  python import_decisions.py import_cc --start-month 1 --start-year 2023 --end-month 12 --end-year 2024 --verbose
  
  # Importer toutes les décisions CA de novembre 2024 (syntaxe courte)
  python import_decisions.py import_ca -sm 11 -sy 2024
        """
    )
    
    # Sous-commandes
    subparsers = parser.add_subparsers(dest='command', help='Commandes disponibles')
    
    # Fonction helper pour ajouter les arguments communs
    def add_date_arguments(subparser):
        subparser.add_argument(
            '--start-month', '-sm', 
            type=int, 
            required=True,
            help='Mois de début (1-12)'
        )
        subparser.add_argument(
            '--start-year', '-sy', 
            type=int, 
            required=True,
            help='Année de début'
        )
        subparser.add_argument(
            '--end-month', '-em', 
            type=int,
            help='Mois de fin (1-12, optionnel, défaut: même que start-month)'
        )
        subparser.add_argument(
            '--end-year', '-ey', 
            type=int,
            help='Année de fin (optionnel, défaut: même que start-year)'
        )
        subparser.add_argument(
            '--verbose', '-v', 
            action='store_true',
            help='Mode verbeux'
        )
    
    # Commande import_ca
    ca_parser = subparsers.add_parser(
        'import_ca', 
        help='Importer les décisions de Cour d\'appel'
    )
    add_date_arguments(ca_parser)
    
    # Commande import_cc
    cc_parser = subparsers.add_parser(
        'import_cc', 
        help='Importer les décisions de Cour de cassation'
    )
    add_date_arguments(cc_parser)
    
    return parser

def main():
    """Fonction principale."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Si aucune commande n'est fournie, afficher l'aide
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Configuration du logging
    setup_cli_logging(getattr(args, 'verbose', False))
    
    # Gestion des valeurs par défaut pour end_month et end_year
    start_month = args.start_month
    start_year = args.start_year
    end_month = getattr(args, 'end_month', None) or start_month
    end_year = getattr(args, 'end_year', None) or start_year
    
    # Validation des plages de dates
    if end_year < start_year or (end_year == start_year and end_month < start_month):
        print("❌ Erreur: La date de fin doit être postérieure ou égale à la date de début")
        sys.exit(1)
    
    # Affichage des informations de démarrage
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🚀 Démarrage de l'importation des décisions - {current_time}")
    
    if start_month == end_month and start_year == end_year:
        print(f"📅 Période: {start_month:02d}/{start_year}")
    else:
        print(f"📅 Période: {start_month:02d}/{start_year} à {end_month:02d}/{end_year}")
    
    print("-" * 50)
    
    try:
        # Exécution de la commande appropriée
        if args.command == 'import_ca':
            import_ca_command(start_month, start_year, end_month, end_year, getattr(args, 'verbose', False))
        elif args.command == 'import_cc':
            import_cc_command(start_month, start_year, end_month, end_year, getattr(args, 'verbose', False))
        else:
            print(f"❌ Commande inconnue: {args.command}")
            parser.print_help()
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  Interruption par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 