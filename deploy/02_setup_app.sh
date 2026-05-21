#!/bin/bash
# ============================================================
# Script 2/3 : Setup de l'application (a lancer en tant que jurichat)
# Usage : ssh jurichat@<IP_VPS> 'bash -s' < deploy/02_setup_app.sh
# ============================================================

set -euo pipefail

echo "============================================"
echo "  SETUP APPLICATION JURICHAT"
echo "============================================"

cd /home/ubuntu

# --- 1. Creer la structure ---
echo "[1/5] Creation de la structure..."
mkdir -p jurichat/{logs,URL_to_ingest,historique_savings}

# --- 2. Environnement virtuel Python ---
echo "[2/5] Creation de l'environnement virtuel Python..."
python3 -m venv jurichat/venv
source jurichat/venv/bin/activate

# --- 3. Installation des dependances Python ---
echo "[3/5] Installation des dependances Python..."
pip install --upgrade pip

pip install \
    crawl4ai==0.6.2 \
    aiohttp \
    asyncio-throttle \
    beautifulsoup4 \
    openai \
    qdrant-client \
    python-dotenv \
    tenacity \
    python-dateutil \
    tqdm

# --- 4. Installation de Playwright Chromium ---
echo "[4/5] Installation de Playwright Chromium..."
playwright install chromium

# --- 5. Script de lancement ---
echo "[5/5] Creation des scripts de lancement..."

# Script pour la pipeline blogs
cat > jurichat/run_blogs.sh << 'SCRIPT'
#!/bin/bash
# Lance la pipeline d'ingestion des blogs
set -euo pipefail

cd /home/ubuntu/jurichat
source venv/bin/activate

echo "$(date '+%Y-%m-%d %H:%M:%S') - Demarrage pipeline blogs"

python scrape_and_update_qdrant_collection.py 2>&1 | tee -a logs/pipeline_blogs_$(date +%Y%m%d).log

echo "$(date '+%Y-%m-%d %H:%M:%S') - Pipeline blogs terminee"
SCRIPT
chmod +x jurichat/run_blogs.sh

# Script pour la pipeline Cour de cassation
cat > jurichat/run_cc.sh << 'SCRIPT'
#!/bin/bash
# Lance la pipeline d'ingestion Cour de cassation
set -euo pipefail

cd /home/ubuntu/jurichat
source venv/bin/activate

YEAR=${1:-$(date +%Y)}

echo "$(date '+%Y-%m-%d %H:%M:%S') - Demarrage pipeline CC pour annee $YEAR"

python -m pipeline_ingestion_cour_cassation.main --year "$YEAR" 2>&1 | tee -a logs/pipeline_cc_$(date +%Y%m%d).log

echo "$(date '+%Y-%m-%d %H:%M:%S') - Pipeline CC terminee"
SCRIPT
chmod +x jurichat/run_cc.sh

# Script pour mettre a jour les URLs depuis les sitemaps
cat > jurichat/run_update_urls.sh << 'SCRIPT'
#!/bin/bash
# Met a jour la liste des URLs a ingerer depuis les sitemaps
set -euo pipefail

cd /home/ubuntu/jurichat
source venv/bin/activate

echo "$(date '+%Y-%m-%d %H:%M:%S') - Mise a jour des URLs depuis les sitemaps"

python update_urls_from_sitemaps.py 2>&1 | tee -a logs/update_urls_$(date +%Y%m%d).log

echo "$(date '+%Y-%m-%d %H:%M:%S') - Mise a jour terminee"
SCRIPT
chmod +x jurichat/run_update_urls.sh

echo ""
echo "============================================"
echo "  SETUP APPLICATION TERMINE"
echo ""
echo "  Prochaine etape :"
echo "  1. Transferer le code vers le serveur"
echo "  2. Configurer le .env"
echo "  3. Mettre en place les crons"
echo "============================================"
