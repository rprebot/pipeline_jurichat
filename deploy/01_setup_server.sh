#!/bin/bash
# ============================================================
# Script 1/3 : Setup initial du serveur OVH
# Usage : ssh root@<IP_VPS> 'bash -s' < deploy/01_setup_server.sh
# ============================================================

set -euo pipefail

echo "============================================"
echo "  SETUP SERVEUR OVH POUR JURICHAT"
echo "============================================"

# --- 1. Mise a jour systeme ---
echo "[1/6] Mise a jour du systeme..."
apt update && apt upgrade -y

# --- 2. Installation des dependances systeme ---
echo "[2/6] Installation des dependances systeme..."
apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    git \
    curl \
    wget \
    unzip \
    htop \
    tmux \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2t64 \
    libxshmfence1 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    libatspi2.0-0 \
    fonts-liberation

# --- 3. Creer un utilisateur dedie ---
echo "[3/6] Creation de l'utilisateur 'jurichat'..."
if ! id "jurichat" &>/dev/null; then
    useradd -m -s /bin/bash jurichat
    echo "Utilisateur 'jurichat' cree"
else
    echo "Utilisateur 'jurichat' existe deja"
fi

# Copier les cles SSH de root vers jurichat
mkdir -p /home/jurichat/.ssh
cp /root/.ssh/authorized_keys /home/jurichat/.ssh/
chown -R jurichat:jurichat /home/jurichat/.ssh
chmod 700 /home/jurichat/.ssh
chmod 600 /home/jurichat/.ssh/authorized_keys

# --- 4. Configurer le firewall ---
echo "[4/6] Configuration du firewall..."
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

# --- 5. Configurer les limites systeme (pour Playwright) ---
echo "[5/6] Configuration des limites systeme..."
cat >> /etc/security/limits.conf << 'LIMITS'
jurichat soft nofile 65536
jurichat hard nofile 65536
LIMITS

# --- 6. Swap (utile si 4GB RAM serres avec Playwright) ---
echo "[6/6] Configuration du swap (2GB)..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "Swap 2GB active"
else
    echo "Swap deja configure"
fi

echo ""
echo "============================================"
echo "  SETUP SERVEUR TERMINE"
echo "  Prochaine etape : se connecter en tant que jurichat"
echo "  ssh jurichat@<IP_VPS>"
echo "============================================"
