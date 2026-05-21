"""
Prompts pour les pipelines d'ingestion.
"""

from .question_generation import QUESTION_GENERATION_PROMPT
from .decision_summary import DECISION_SUMMARY_PROMPT
from .decision_questions import DECISION_QUESTIONS_PROMPT

__all__ = [
    'QUESTION_GENERATION_PROMPT',
    'DECISION_SUMMARY_PROMPT',
    'DECISION_QUESTIONS_PROMPT',
]
