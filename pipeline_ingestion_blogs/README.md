# Pipeline d'Ingestion d'Articles de Blogs

Pipeline ETL complète pour ingérer des articles de blogs juridiques depuis des sitemaps XML, les traiter avec DeepSeek et REGEX, et les stocker dans Qdrant avec vectorisation OpenAI.

## Architecture

```
Sitemaps XML (116 URLs)
  → Parse XML & Extract URLs
  → Deduplicate (Historique + Qdrant check)
  → Scrape Content (crawl4ai)
  → Extract Legal Refs (REGEX - 77 codes juridiques)
  → Generate 3 Questions (DeepSeek - 1 appel LLM)
  → Embed 3 Questions (OpenAI text-embedding-3-large, 256 dim)
  → Store 3 Points in Qdrant (1 article → 3 points avec questions différentes)
```

## Caractéristiques

- **Extraction de références juridiques par REGEX** : Rapide, précis, gratuit (77 codes juridiques français)
- **Génération de 3 questions par DeepSeek** : 3 questions complémentaires par article en un seul appel LLM
- **3 points Qdrant par article** : Améliore la couverture de recherche avec des angles différents
- **Déduplication intelligente** : Historique JSON + Qdrant pour éviter les doublons
- **Historique complet** : Tracking de toutes les URLs (succès et erreurs) dans `historique_savings/`
- **Traitement par batches** : Optimisé pour de grandes quantités d'articles
- **Gestion d'erreurs robuste** : Retry logic, graceful degradation

## Installation

### 1. Installer les dépendances

```bash
cd /Users/prebot/new_jurichat
pip install -r requirements.txt
```

### 2. Installer Playwright Chromium

```bash
playwright install chromium
```

### 3. Vérifier le fichier .env

Assurez-vous que votre fichier `.env` contient les variables nécessaires :

```bash
# DeepSeek (pour génération de texte)
DEEPSEEK_API_KEY=sk-...

# OpenAI (pour embeddings uniquement)
OPENAI_API_KEY=sk-...

# Qdrant
QDRANT_URL=https://...
QDRANT_API_KEY=...

# Optionnel (valeurs par défaut)
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=256
COLLECTION_NAME=articles_blog
MAX_CONCURRENT_SCRAPES=5
TIMEOUT=30
MAX_RETRIES=3
BATCH_SIZE=10
```

## Utilisation

### Lancer la pipeline

```bash
cd /Users/prebot/new_jurichat
python -m pipeline_ingestion_blogs.main
```

### Logs

La pipeline génère plusieurs fichiers de logs :

- `blog_ingestion.log` - Log principal de la pipeline
- `inaccessible_urls.log` - URLs qui n'ont pas pu être scrapées

### Arrêter la pipeline

Utilisez `Ctrl+C` pour arrêter proprement la pipeline.

## Structure des Données

### Collection Qdrant "articles_blog"

**Important** : Chaque article génère **3 points Qdrant** (un par question potentielle).

Structure d'un point :

```python
{
    "id": str(uuid.uuid4()),
    "vector": [256 dimensions],  # Embedding de la question
    "payload": {
        "url": str,                    # URL normalisée (même pour les 3 points)
        "unique_url": str,             # URL originale
        "full_content": str,           # Contenu complet (identique pour les 3 points)
        "date": str,                   # Date (YYYY-MM-DD)
        "legal_references": List[str], # Codes juridiques (identique)
        "potential_question": str,     # Question générée (DIFFÉRENTE pour chaque point)
        "question_index": int,         # 1, 2 ou 3
        "title": str                   # Titre
    }
}
```

**Exemple** : Un article "Les congés payés" génère 3 points avec :
- Point 1 : Question "Comment calculer les congés payés ?"
- Point 2 : Question "Quels sont les droits aux congés payés ?"
- Point 3 : Question "Peut-on reporter ses congés payés ?"

Chaque point a le même contenu mais une question différente (donc un embedding différent).

## Modules

- **config.py** - Configuration de la pipeline
- **logger.py** - Logging structuré
- **url_utils.py** - Normalisation et validation d'URLs
- **sitemap_parser.py** - Parsing de sitemaps XML
- **article_scraper.py** - Scraping avec crawl4ai
- **content_processor.py** - Traitement LLM (DeepSeek pour questions, REGEX pour refs juridiques)
- **vector_store.py** - Opérations Qdrant
- **historique_manager.py** - Gestion de l'historique des URLs traitées
- **main.py** - Orchestration principale

## Historique des URLs

La pipeline enregistre automatiquement toutes les URLs traitées dans `historique_savings/historique_urls.json` :

### Structure de l'historique

```json
{
  "created_at": "2024-01-01T12:00:00",
  "last_updated": "2024-01-01T14:00:00",
  "total_urls": 150,
  "stats": {
    "total_success": 120,
    "total_errors": 30,
    "success_rate": "80.0%"
  },
  "urls": [
    {
      "url": "https://...",
      "date_sauvegarde": "2024-01-01T12:05:00",
      "status": "success",
      "error_message": null,
      "qdrant_id": "uuid...",
      "title": "Titre de l'article",
      "date_article": "2024-01-01",
      "legal_references_count": 2
    },
    {
      "url": "https://...",
      "date_sauvegarde": "2024-01-01T12:10:00",
      "status": "error",
      "error_message": "[scraping] Timeout lors du scraping",
      "qdrant_id": null
    }
  ]
}
```

### Visualiser l'historique

```bash
python -m pipeline_ingestion_blogs.tests.view_historique
```

Affiche :
- Statistiques globales (total, succès, erreurs, taux de succès)
- Derniers succès (5 derniers)
- Dernières erreurs (5 dernières)
- Répartition des erreurs par catégorie

Chaque URL dans l'historique contient son propre timestamp (`date_sauvegarde`), permettant une traçabilité complète sans fichiers multiples.

## Prompts

Les prompts sont stockés dans le dossier `prompts/` :

- **legal_reference_extraction.py** - Extraction de codes juridiques
- **question_generation.py** - Génération de questions potentielles

## Performance

Estimation pour un traitement complet :

- **Sitemaps parsing** : 1-5 minutes (116 sitemaps)
- **URLs extraites** : ~5,000-10,000 articles estimés
- **Traitement par batch (10 articles)** : ~100 secondes
  - Scraping : ~30s
  - LLM processing : ~60s
  - Embedding + Qdrant : ~10s

**Durée totale estimée :**
- 1,000 nouveaux articles → ~3 heures
- 5,000 nouveaux articles → ~14 heures

## Gestion des Erreurs

La pipeline implémente une gestion robuste des erreurs avec :

- **Retry logic** avec exponential backoff (3 tentatives)
- **Graceful degradation** (skip articles en cas d'échec)
- **Logging détaillé** de tous les échecs
- **Déduplication** pour éviter de re-traiter les articles existants

## Vérification des Résultats

### Vérifier la collection Qdrant

```python
from qdrant_client import QdrantClient
import os
from dotenv import load_dotenv

load_dotenv()

client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY")
)

# Compter les articles
count = client.count("articles_blog")
print(f"Articles stockés: {count.count}")

# Échantillon
points, _ = client.scroll("articles_blog", limit=1, with_payload=True)
print(points[0].payload)
```

### Vérifier les logs

```bash
tail -f blog_ingestion.log
grep "ERROR" blog_ingestion.log
cat inaccessible_urls.log
```

## Troubleshooting

### Erreur "Collection doesn't exist"

La collection est créée automatiquement au démarrage. Si l'erreur persiste, vérifiez les credentials Qdrant.

### Erreur OpenAI API

Vérifiez que `OPENAI_API_KEY` est valide et que vous avez des crédits.

### Erreur Playwright

Assurez-vous que Chromium est installé :

```bash
playwright install chromium
```

### Memory issues

Réduisez `BATCH_SIZE` dans le `.env` (ex: `BATCH_SIZE=5`).

## Maintenance

### Ajouter de nouveaux sitemaps

Modifiez `blog_base/sitemap_urls.py` et ajoutez vos URLs de sitemaps.

### Modifier les prompts

Les prompts sont dans le dossier `prompts/`. Modifiez-les selon vos besoins.

### Changer la collection Qdrant

Modifiez `COLLECTION_NAME` dans le `.env`.
