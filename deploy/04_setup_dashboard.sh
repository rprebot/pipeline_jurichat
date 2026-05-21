#!/bin/bash
# ============================================================
# Setup du dashboard sur le VPS OVH
# Usage : ssh ovh-jurichat 'bash -s' < deploy/04_setup_dashboard.sh
# ============================================================

set -euo pipefail

echo "============================================"
echo "  SETUP DASHBOARD JURICHAT"
echo "============================================"

cd /home/ubuntu/jurichat

# --- 1. Installer les dependances dashboard ---
echo "[1/4] Installation des dependances..."
source venv/bin/activate
pip install fastapi uvicorn asyncssh qdrant-client python-dotenv --quiet

# --- 2. Creer le service systemd ---
echo "[2/4] Creation du service systemd..."
sudo tee /etc/systemd/system/jurichat-dashboard.service > /dev/null << 'SERVICE'
[Unit]
Description=JuriChat Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/jurichat
Environment=DASHBOARD_LOCAL=1
ExecStart=/home/ubuntu/jurichat/venv/bin/uvicorn dashboard.backend:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

# --- 3. Ouvrir le port 8080 dans le firewall ---
echo "[3/4] Ouverture du port 8080..."
sudo ufw allow 8080/tcp

# --- 4. Demarrer le service ---
echo "[4/4] Demarrage du service..."
sudo systemctl daemon-reload
sudo systemctl enable jurichat-dashboard
sudo systemctl restart jurichat-dashboard

sleep 2
sudo systemctl status jurichat-dashboard --no-pager

echo ""
echo "============================================"
echo "  DASHBOARD DEPLOYE"
echo "  URL: http://141.227.133.247:8080"
echo "  Logs: sudo journalctl -u jurichat-dashboard -f"
echo "============================================"
