# Mise à jour : 3 Questions par Article

## Résumé des Changements

La pipeline a été modifiée pour générer **3 questions potentielles** par article au lieu d'une seule. Chaque question génère un **point Qdrant distinct**, permettant d'améliorer la couverture de recherche.

## Modifications Apportées

### 1. Génération de Questions (LLM)

**Avant :**
- 1 question par article
- 1 appel LLM par article
- Format de sortie : texte brut

**Après :**
- 3 questions par article
- Toujours 1 seul appel LLM par article (plus efficace)
- Format de sortie : JSON array `["Question 1?", "Question 2?", "Question 3?"]`

**Fichier modifié** : `prompts/question_generation.py`
```python
# Nouveau prompt
TÂCHE:
Génère EXACTEMENT 3 questions différentes et complémentaires...

FORMAT DE SORTIE:
Retourne UNIQUEMENT un array JSON avec exactement 3 questions
Exemple: ["Question 1 ?", "Question 2 ?", "Question 3 ?"]
```

### 2. Traitement de Contenu

**Fichier modifié** : `pipeline_ingestion_blogs/content_processor.py`

**Fonction renommée** : `generate_potential_question()` → `generate_potential_questions()`

**Changements :**
```python
# Avant
async def generate_potential_question(...) -> str:
    # Retournait 1 question

# Après
async def generate_potential_questions(...) -> List[str]:
    # Retourne 3 questions
    questions = json.loads(response_text)  # Parse JSON
    return validated_questions  # Liste de 3 questions
```

**Dans `process_article_content()` :**
```python
# Avant
article_data["potential_question"] = question  # str

# Après
article_data["potential_questions"] = questions  # List[str]
```

### 3. Stockage Qdrant

**Fichier modifié** : `pipeline_ingestion_blogs/vector_store.py`

**Fonction modifiée** : `store_article_in_qdrant()`

**Changements majeurs :**
```python
# Avant
async def store_article_in_qdrant(...) -> tuple[bool, str]:
    # Créait 1 point Qdrant
    # Retournait 1 ID

# Après
async def store_article_in_qdrant(...) -> tuple[bool, List[str]]:
    # Crée 3 points Qdrant (un par question)
    # Retourne 3 IDs
```

**Logique de stockage :**
```python
# Pour chaque question (i = 0, 1, 2):
for i, question in enumerate(questions):
    # 1. Générer l'embedding pour cette question
    vector = await embed_text_openai(question, ...)

    # 2. Créer le payload avec cette question
    payload = {
        **base_payload,  # Contenu commun
        "potential_question": question,  # Différent
        "question_index": i + 1  # 1, 2, ou 3
    }

    # 3. Créer le point avec ID unique
    point_id = str(uuid.uuid4())
    points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

# 4. Upsert les 3 points en une seule fois
upsert_points(qdrant_client, collection_name, points)
```

### 4. Pipeline Principale

**Fichier modifié** : `pipeline_ingestion_blogs/main.py`

**Changements :**
```python
# Avant
success, qdrant_id = await store_article_in_qdrant(...)  # 1 ID
historique.add_success(url=url, qdrant_id=qdrant_id, ...)

# Après
success, qdrant_ids = await store_article_in_qdrant(...)  # 3 IDs
historique.add_success(url=url, qdrant_id=",".join(qdrant_ids), ...)
# Stocke "id1,id2,id3" dans l'historique
```

**Logs améliorés :**
```python
# Avant
print(f"→ Stored (Qdrant): {stored_count}/{len(processed_articles)}")

# Après
print(f"→ Stored (Qdrant): {stored_count}/{len(processed_articles)} articles (3 questions/article)")
```

### 5. Historique

**Fichier** : `pipeline_ingestion_blogs/historique_manager.py`

**Modification** : Le champ `qdrant_id` stocke maintenant 3 IDs séparés par des virgules.

**Exemple :**
```json
{
  "url": "https://example.com/article",
  "qdrant_id": "uuid-123,uuid-456,uuid-789",
  "status": "success"
}
```

## Structure des Données Qdrant

### Un Article → 3 Points

**Article source :**
```
Titre: "Les congés payés en France"
Contenu: "Les salariés ont droit à 2.5 jours..."
```

**3 Points créés :**

**Point 1 :**
```json
{
  "id": "uuid-aaa",
  "vector": [0.123, 0.456, ...],  // Embedding de Q1
  "payload": {
    "url": "https://example.com/article",
    "full_content": "Les salariés ont droit...",
    "potential_question": "Comment calculer les congés payés ?",
    "question_index": 1,
    "legal_references": ["Code du travail"],
    "title": "Les congés payés en France"
  }
}
```

**Point 2 :**
```json
{
  "id": "uuid-bbb",
  "vector": [0.789, 0.012, ...],  // Embedding de Q2 (différent)
  "payload": {
    "url": "https://example.com/article",  // Même URL
    "full_content": "Les salariés ont droit...",  // Même contenu
    "potential_question": "Quels sont les droits aux congés payés ?",  // Question différente
    "question_index": 2,
    "legal_references": ["Code du travail"],
    "title": "Les congés payés en France"
  }
}
```

**Point 3 :**
```json
{
  "id": "uuid-ccc",
  "vector": [0.345, 0.678, ...],  // Embedding de Q3 (différent)
  "payload": {
    "url": "https://example.com/article",
    "full_content": "Les salariés ont droit...",
    "potential_question": "Peut-on reporter ses congés payés ?",  // Question différente
    "question_index": 3,
    "legal_references": ["Code du travail"],
    "title": "Les congés payés en France"
  }
}
```

## Avantages

### 1. Meilleure Couverture de Recherche

Un utilisateur peut formuler sa question de différentes manières :
- "Comment calculer les congés ?" → Match avec Point 1
- "Quels sont mes droits ?" → Match avec Point 2
- "Puis-je reporter ?" → Match avec Point 3

Avec 1 seule question, on risquait de manquer 2/3 des recherches possibles.

### 2. Même Coût LLM

- Avant : 1 appel LLM pour 1 question
- Après : 1 appel LLM pour 3 questions
- **Coût identique**, mais 3x plus de couverture

### 3. Diversité des Angles

Les 3 questions couvrent différents aspects :
- **Définition** : "Qu'est-ce que..."
- **Procédure** : "Comment faire..."
- **Droits/Conséquences** : "Peut-on...", "Quels sont..."

### 4. Meilleure Précision

Au lieu de forcer une seule question "moyenne", on peut capturer plusieurs intentions spécifiques.

## Impact sur les Performances

### Embeddings

- **Avant** : 1 embedding par article
- **Après** : 3 embeddings par article
- **Impact** : +200% d'appels OpenAI embeddings
- **Coût** : ~$0.0003 par article (au lieu de $0.0001)

### Stockage Qdrant

- **Avant** : 1 point par article
- **Après** : 3 points par article
- **Impact** : Database 3x plus grande
- **Pour 80,000 articles** : 240,000 points au lieu de 80,000

### Temps de Traitement

- **LLM** : Identique (1 appel par article)
- **Embeddings** : +2-3 secondes par article (3 appels au lieu d'1)
- **Stockage** : Légèrement plus lent (upsert de 3 points au lieu d'1)
- **Total** : ~+20% de temps par article

## Tests

### Test de Génération

**Fichier** : `pipeline_ingestion_blogs/tests/test_3_questions.py`

```bash
python3 pipeline_ingestion_blogs/tests/test_3_questions.py
```

**Résultat attendu :**
```
✅ 3 questions générées:
  Question 1: Quelles sont les obligations légales de l'employeur en matière de formation professionnelle ?
  Question 2: Comment fonctionne le compte personnel de formation (CPF) pour un salarié ?
  Question 3: Quels éléments peut inclure un plan de développement des compétences en entreprise ?

✅ Les 3 questions sont bien différentes
```

## Migration des Données Existantes

### Articles déjà stockés

Les articles déjà dans Qdrant avec 1 seule question resteront tels quels. Pas de migration automatique.

**Recommandation** : Nettoyer la collection et re-ingérer pour bénéficier des 3 questions.

```bash
# Nettoyer la collection
python3 pipeline_ingestion_blogs/tests/clean_qdrant.py

# Re-lancer la pipeline
python3 -m pipeline_ingestion_blogs.main
```

## Compatibilité

### Recherche

Les requêtes de recherche fonctionneront de la même manière :
```python
# Embedding de la question utilisateur
query_vector = embed_text("Comment calculer les congés ?")

# Recherche (retournera jusqu'à 3 points du même article si pertinents)
results = qdrant_client.search(
    collection_name="articles_blog",
    query_vector=query_vector,
    limit=10
)
```

**Note** : Les résultats peuvent contenir plusieurs points du même article (avec différentes questions). Déduplication par URL recommandée côté application.

## Résumé Exécutif

✅ **1 appel LLM** → 3 questions au lieu d'1
✅ **3 points Qdrant** par article pour meilleure couverture
✅ **Questions complémentaires** couvrant différents aspects
✅ **Tests passés** avec DeepSeek
✅ **Documentation mise à jour**

**Prochaine étape** : Lancer la pipeline complète pour ingérer les 79,871 articles avec 3 questions chacun.
