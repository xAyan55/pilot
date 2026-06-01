#!/bin/bash
# MintyHost LXC Node Daemon - Ubuntu 1-Click Installation Script
set -e

INSTALL_DIR="/root/lxc-node"
REPO_URL="https://github.com/xAyan55/lxc.git"

echo "=========================================================="
echo " Starting MintyHost LXC Node Daemon Installation"
echo "=========================================================="

echo "[*] Updating apt package lists..."
sudo apt update -y

echo "[*] Installing system dependencies (Python, Git, LXC bridging)..."
sudo apt install -y python3 python3-pip python3-venv git snapd bridge-utils uidmap

echo "[*] Installing LXD snap..."
sudo snap install lxd

echo "[*] Initializing LXD bridge configuration..."
if ! sudo lxd init --auto; then
    echo "[!] Auto-initialization failed (subnet conflict). Creating a custom lxdbr0 bridge manually..."
    sudo /snap/bin/lxc network create lxdbr0 ipv4.address=10.99.0.1/24 ipv4.nat=true || true
    sudo lxd init --auto
fi

echo "[*] Setting active community images remote URL..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

# If running as non-root user, ensure they belong to the lxd group
if [ "$USER" != "root" ]; then
    echo "[*] Adding user $USER to the 'lxd' group..."
    sudo usermod -aG lxd $USER
fi

echo "[*] Cloning repository to $INSTALL_DIR..."
if [ -d "$INSTALL_DIR" ]; then
    echo "[!] Directory $INSTALL_DIR already exists. Pulling latest..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "[*] Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[*] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# Read config from environment variables passed during curl execution
NODE_PORT=${NODE_PORT:-5001}
NODE_API_KEY=${NODE_API_KEY:-"default-node-key"}
NODE_ID=${NODE_ID:-0}
NODE_NAME=${NODE_NAME:-"Remote Node"}

echo "[*] Writing configuration file config.yml..."
cat <<EOF > config.yml
port: $NODE_PORT
api_key: "$NODE_API_KEY"
node_id: $NODE_ID
name: "$NODE_NAME"
EOF

echo "[*] Creating systemd service file..."
sudo cat <<EOF > /etc/systemd/system/mintyhost-node.service
[Unit]
Description=MintyHost LXC Node Daemon
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python daemon.py
Restart=always
RestartSec=5
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "[*] Starting systemd service..."
sudo systemctl daemon-reload
sudo systemctl enable mintyhost-node.service
sudo systemctl restart mintyhost-node.service

echo "=========================================================="
echo " Node Installation Complete!"
echo " The daemon is now running under systemd (port $NODE_PORT)."
echo " Check status with: systemctl status mintyhost-node.service"
echo "=========================================================="
sudo systemctl status mintyhost-node.service
