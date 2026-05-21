#!/bin/bash
# ============================================================
# Synchronise le code local vers le serveur OVH
# Usage : ./deploy/sync_code.sh <IP_VPS>
# ============================================================

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: ./deploy/sync_code.sh <IP_VPS>"
    echo "Exemple: ./deploy/sync_code.sh 51.210.xx.xx"
    exit 1
fi

VPS_IP="$1"
REMOTE_USER="ubuntu"
REMOTE_DIR="/home/ubuntu/jurichat"

echo "Synchronisation vers $REMOTE_USER@$VPS_IP:$REMOTE_DIR"

rsync -avz --progress \
    --exclude '.DS_Store' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'venv/' \
    --exclude 'node_modules/' \
    --exclude 'deploy/' \
    --exclude '.git/' \
    --exclude 'webapp/' \
    --exclude 'old_functions/' \
    --exclude '.env' \
    ./ "$REMOTE_USER@$VPS_IP:$REMOTE_DIR/"

echo ""
echo "Code synchronise."
echo ""
echo "IMPORTANT : N'oublie pas de configurer le .env sur le serveur :"
echo "  ssh $REMOTE_USER@$VPS_IP"
echo "  nano $REMOTE_DIR/.env"
