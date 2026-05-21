"""
Module spécifique pour l'importation des décisions de Cour de cassation (CC).

Ce module hérite du DecisionImporter de base et personnalise le comportement
pour les décisions CC avec l'API Nebius et la logique spécifique pour les résumés.
"""
import os
from typing import Dict
from decision_importer import DecisionImporter, logger
from dotenv import load_dotenv

load_dotenv()

class CCImporter(DecisionImporter):
    """Importateur spécialisé pour les décisions de Cour de cassation."""
    
    def __init__(self):
        # Configuration spécifique pour CC
        config = {
            'jurisdiction': 'cc',
            'collection_name': 'new_decisions_cc',
            'llm_config': {
                'api_key': os.getenv('NEBIUS_API_KEY', "eyJhbGciOiJIUzI1NiIsImtpZCI6IlV6SXJWd1h0dnprLVRvdzlLZWstc0M1akptWXBvX1VaVkxUZlpnMDRlOFUiLCJ0eXAiOiJKV1QifQ.eyJzdWIiOiJnb29nbGUtb2F1dGgyfDEwMjQyMDQwMTEyNjM0NTk4MTA1NiIsInNjb3BlIjoib3BlbmlkIG9mZmxpbmVfYWNjZXNzIiwiaXNzIjoiYXBpX2tleV9pc3N1ZXIiLCJhdWQiOlsiaHR0cHM6Ly9uZWJpdXMtaW5mZXJlbmNlLmV1LmF1dGgwLmNvbS9hcGkvdjIvIl0sImV4cCI6MTkwMDk0NjQzNywidXVpZCI6IjVmNjFkZjg5LWM4ZjUtNDAxZC1iNDYwLTI2MDljNDkzZGMxOCIsIm5hbWUiOiJqdXJpY2hhdCIsImV4cGlyZXNfYXQiOiIyMDMwLTAzLTI4VDE2OjQwOjM3KzAwMDAifQ.S9ni3mMsgtAVhZhNngtlF7Ow75pVxi7iFrPKpvHAz5Y"),
                'base_url': "https://api.studio.nebius.com/v1/",
                'model': "meta-llama/Llama-3.3-70B-Instruct-fast"
            },
            'fields': ['publication', 'titlesAndSummaries']  # Champs supplémentaires pour CC
        }
        
        super().__init__(config)
    
    def get_summary(self, decision: Dict, text: str) -> str:
        """
        Génère le résumé pour une décision CC.
        
        Pour CC, on essaie d'abord d'utiliser le résumé existant dans titlesAndSummaries,
        sinon on génère un nouveau résumé avec le LLM.
        
        Returns:
            tuple: (summary, ia_indicator)
        """
        try:
            # Vérifier si un résumé existe déjà dans titlesAndSummaries
            titles_summaries = decision.get("titlesAndSummaries")
            if titles_summaries and len(titles_summaries) > 0:
                existing_summary = titles_summaries[0].get("summary", "")
                if existing_summary and len(existing_summary) > 100:
                    logger.info(f"Utilisation du résumé existant pour la décision {decision['id']}")
                    return existing_summary
            
            # Si pas de résumé existant ou trop court, générer avec le LLM
            logger.info(f"Génération d'un nouveau résumé pour la décision {decision['id']}")
            return self.summarize_decision(text)
            
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération du résumé existant pour {decision['id']}: {e}")
            # Fallback: générer avec le LLM
            return self.summarize_decision(text)
    
    def create_payload(self, decision: Dict, summary: str, question: str) -> Dict:
        """Crée le payload spécifique pour CC avec les champs supplémentaires."""
        payload = super().create_payload(decision, summary, question)
        
        # Ajout des champs spécifiques à CC
        payload['publication'] = decision.get('publication')
        payload['titlesAndSummaries'] = decision.get('titlesAndSummaries')
        
        # Indicateur de génération IA pour le résumé
        titles_summaries = decision.get("titlesAndSummaries")
        if titles_summaries and len(titles_summaries) > 0:
            existing_summary = titles_summaries[0].get("summary", "")
            if existing_summary and len(existing_summary) > 100:
                payload['ia'] = "résumé généré sans IA"
            else:
                payload['ia'] = "résumé généré par l'IA"
        else:
            payload['ia'] = "résumé généré par l'IA"
        
        return payload

def create_cc_importer() -> CCImporter:
    """Factory function pour créer un importateur CC."""
    return CCImporter() 