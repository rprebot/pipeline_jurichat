"""
Prompt pour la génération de questions potentielles à partir d'articles de blogs.
"""

QUESTION_GENERATION_PROMPT = """Tu es un assistant qui aide à formuler des questions juridiques pertinentes.

CONTEXTE:
Titre de l'article: {title}

Contenu de l'article:
{content}

TÂCHE:
Génère EXACTEMENT 3 questions différentes et complémentaires en français qu'un utilisateur pourrait poser et pour lesquelles cet article constituerait une réponse pertinente.

Les 3 questions doivent couvrir différents aspects de l'article (par exemple: définition, procédure, conséquences).

CRITÈRES POUR CHAQUE QUESTION:
1. La question doit être spécifique au contenu de l'article
2. La question doit être formulée du point de vue d'un utilisateur cherchant de l'information juridique
3. La question doit être complète et grammaticalement correcte
4. La question doit se terminer par un point d'interrogation
5. Privilégier les questions commençant par: "Comment...", "Quels sont...", "Quelles sont...", "Peut-on...", "Faut-il...", "Qu'est-ce que..."
6. Chaque question doit être entre 8 et 25 mots
7. Les 3 questions doivent être DIFFÉRENTES et complémentaires (ne pas répéter la même idée)

EXEMPLES DE BONNES QUESTIONS:
- "Comment calculer les indemnités de licenciement en cas de rupture conventionnelle?"
- "Quels sont les délais de prescription pour une action en responsabilité civile?"
- "Peut-on résilier un bail commercial avant son terme sans pénalité?"

FORMAT DE SORTIE:
Retourne UNIQUEMENT un array JSON avec exactement 3 questions, sans texte supplémentaire.
Exemple: ["Question 1 ?", "Question 2 ?", "Question 3 ?"]

QUESTIONS (JSON):"""
