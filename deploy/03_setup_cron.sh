#!/bin/bash
# ============================================================
# Script 3/3 : Configuration des crons + lancement immediat
# Usage : ssh ovh-jurichat 'bash -s' < deploy/03_setup_cron.sh
# ============================================================

set -euo pipefail

echo "============================================"
echo "  CONFIGURATION DES CRONS + LANCEMENT"
echo "============================================"

# --- Crons recurrents ---
cat << 'CRON' | crontab -
# JuriChat - Pipelines d'ingestion (cycle quotidien a 2h)
# Lundi, Mercredi, Vendredi : URLs + blogs
0 2 * * 1,3,5 /home/ubuntu/jurichat/run_update_urls.sh && /home/ubuntu/jurichat/run_blogs.sh >> /home/ubuntu/jurichat/logs/cron_blogs.log 2>&1

# Mardi, Jeudi, Samedi : Cour de cassation 2025
0 2 * * 2,4,6 /home/ubuntu/jurichat/run_cc.sh 2025 >> /home/ubuntu/jurichat/logs/cron_cc.log 2>&1

# Dimanche 4h00 : Nettoyage des vieux logs (> 30 jours)
0 4 * * 0 find /home/ubuntu/jurichat/logs/ -name "*.log" -mtime +30 -delete
CRON

echo "Crons configures :"
crontab -l

# --- Lancement immediat dans tmux ---
echo ""
echo "Lancement immediat des pipelines dans tmux..."

tmux new-session -d -s ingestion \
  "cd /home/ubuntu/jurichat && source venv/bin/activate && \
   echo '=== URLS + BLOGS ===' && ./run_update_urls.sh && ./run_blogs.sh && \
   echo '=== COUR DE CASSATION 2025 ===' && ./run_cc.sh 2025"

echo "Pipelines lancees en arriere-plan (tmux session: ingestion)"
echo "Suivre la progression : tmux attach -t ingestion"
echo "Detacher sans arreter : Ctrl+B puis D"
