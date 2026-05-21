#!/bin/bash
# MintyHost LXC Control Panel - Ubuntu Installation Script
set -e

# Define variables
INSTALL_DIR="/root/lxc"
REPO_URL="https://github.com/xAyan55/lxc.git"

echo "=========================================================="
echo " Starting MintyHost LXC Control Panel Installation"
echo "=========================================================="

echo "[*] Updating apt package lists..."
sudo apt update -y

echo "[*] Installing system dependencies (Python, Git, LXC bridging)..."
sudo apt install -y python3 python3-pip python3-venv git snapd bridge-utils uidmap

echo "[*] Installing LXD snap..."
sudo snap install lxd

echo "[*] Initializing LXD bridge configuration..."
sudo lxd init --auto

# If running as non-root user, ensure they belong to the lxd group
if [ "$USER" != "root" ]; then
    echo "[*] Adding user $USER to the 'lxd' group..."
    sudo usermod -aG lxd $USER
fi

echo "[*] Cloning repository to $INSTALL_DIR..."
if [ -d "$INSTALL_DIR" ]; then
    echo "[!] Directory $INSTALL_DIR already exists. Backing up..."
    sudo mv "$INSTALL_DIR" "${INSTALL_DIR}_backup_$(date +%s)"
fi
sudo git clone "$REPO_URL" "$INSTALL_DIR"

cd "$INSTALL_DIR"

echo "[*] Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[*] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt gunicorn

echo "[*] Seeding database schema..."
python seed.py

echo "[*] Registering and starting systemd service..."
sudo cp "$INSTALL_DIR/mintyhost.service" /etc/systemd/system/mintyhost.service
sudo systemctl daemon-reload
sudo systemctl enable mintyhost.service
sudo systemctl start mintyhost.service

echo "=========================================================="
echo " Installation Complete!"
echo " The panel is now running under systemd (port 5000)."
echo " Check status with: systemctl status mintyhost.service"
echo "=========================================================="
sudo systemctl status mintyhost.service
