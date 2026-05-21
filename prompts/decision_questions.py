"""
Prompt pour la génération de questions potentielles à partir du résumé d'une décision de justice.
"""

DECISION_QUESTIONS_PROMPT = """Tu es un assistant juridique spécialisé en droit français.

CONTEXTE:
Résumé d'une décision de justice :
{summary}

TÂCHE:
Génère EXACTEMENT 3 questions différentes et complémentaires en français qu'un professionnel du droit ou un justiciable pourrait poser et pour lesquelles cette décision constituerait une réponse pertinente.

Les 3 questions doivent couvrir différents aspects de la décision (par exemple : le principe de droit, les conditions d'application, les conséquences pratiques).

CRITÈRES POUR CHAQUE QUESTION:
1. La question doit être spécifique au contenu de la décision
2. La question doit être formulée du point de vue d'un utilisateur cherchant de l'information juridique
3. La question doit être complète et grammaticalement correcte
4. La question doit se terminer par un point d'interrogation
5. Privilégier les questions commençant par: "Comment...", "Quels sont...", "Quelles sont...", "Peut-on...", "Faut-il...", "Qu'est-ce que...", "Dans quelles conditions..."
6. Chaque question doit être entre 8 et 25 mots
7. Les 3 questions doivent être DIFFÉRENTES et complémentaires (ne pas répéter la même idée)

FORMAT DE SORTIE:
Retourne UNIQUEMENT un array JSON avec exactement 3 questions, sans texte supplémentaire.
Exemple: ["Question 1 ?", "Question 2 ?", "Question 3 ?"]

QUESTIONS (JSON):"""
