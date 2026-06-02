#!/bin/bash
# MintyHost LXC Control Panel - Ubuntu Installation Script
set -e

# Define variables
INSTALL_DIR="/var/www/lxc"
REPO_URL="https://github.com/xAyan55/lxc.git"

echo "=========================================================="
echo " Starting MintyHost LXC Control Panel Installation"
echo "=========================================================="

echo "[*] Updating apt package lists..."
sudo apt update -y

echo "[*] Installing system dependencies (Python, Git, LXC bridging, SSH, Curl)..."
sudo apt install -y python3 python3-pip python3-venv git snapd bridge-utils uidmap openssh-client curl

echo "[*] Installing LXD snap..."
sudo snap install lxd

echo "[*] Initializing LXD bridge configuration..."
if ! sudo lxd init --auto; then
    echo "[!] Auto-initialization failed (subnet conflict). Creating a custom lxdbr0 bridge manually..."
    sudo /snap/bin/lxc network create lxdbr0 ipv4.address=10.99.0.1/24 ipv4.nat=true || true
    sudo lxd init --auto
fi

# Ensure default profile has the network device eth0 attached to lxdbr0
sudo /snap/bin/lxc profile device add default eth0 nic network=lxdbr0 name=eth0 || true

echo "[*] Configuring firewall rules to allow LXD bridge routing (resolves Docker/UFW conflicts)..."
sudo iptables -I FORWARD -i lxdbr0 -j ACCEPT || true
sudo iptables -I FORWARD -o lxdbr0 -j ACCEPT || true
if command -v ufw >/dev/null; then
    sudo ufw route allow in on lxdbr0 || true
    sudo ufw route allow out on lxdbr0 || true
fi

echo "[*] Setting active community images remote URL..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

# If running as non-root user, ensure they belong to the lxd group
if [ "$USER" != "root" ]; then
    echo "[*] Adding user $USER to the 'lxd' group..."
    sudo usermod -aG lxd $USER
fi

echo "[*] Cloning repository to $INSTALL_DIR..."
sudo mkdir -p /var/www
if [ -d "$INSTALL_DIR" ]; then
    echo "[!] Directory $INSTALL_DIR already exists. Pulling latest..."
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR" 2>/dev/null || sudo chown -R root:root "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "[*] Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[*] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[*] Seeding database schema..."
python seed.py
deactivate

echo "[*] Registering and starting web panel systemd service..."
sudo cp "$INSTALL_DIR/mintyhost.service" /etc/systemd/system/mintyhost.service
sudo systemctl daemon-reload
sudo systemctl enable mintyhost.service
sudo systemctl restart mintyhost.service

echo "[*] Setting up Discord Bot virtual environment..."
if [ ! -f "$INSTALL_DIR/bot/.env" ]; then
    cp "$INSTALL_DIR/bot/.env.example" "$INSTALL_DIR/bot/.env"
    echo "[!] Created default bot/.env. Please configure your Discord Token, Guild ID, and API keys."
fi

python3 -m venv "$INSTALL_DIR/bot/venv"
source "$INSTALL_DIR/bot/venv/bin/activate"
pip install --upgrade pip
pip install -r "$INSTALL_DIR/bot/requirements.txt"
deactivate

echo "[*] Registering and starting Discord bot systemd service..."
sudo cp "$INSTALL_DIR/bot/mintyhost-bot.service" /etc/systemd/system/mintyhost-bot.service
sudo systemctl daemon-reload
sudo systemctl enable mintyhost-bot.service
sudo systemctl restart mintyhost-bot.service || echo "[WARNING] Discord bot service failed to start. Make sure to configure bot/.env first."

echo "=========================================================="
echo " Installation Complete!"
echo " Web Panel running on: http://YOUR_SERVER_IP:5000"
echo "   - View status: systemctl status mintyhost.service"
echo " Discord Bot running under systemd."
echo "   - View status: systemctl status mintyhost-bot.service"
echo ""
echo " [OPTIONAL] Windows 10 VPS Support:"
echo "   To enable Windows VM deployment, import a Windows ISO:"
echo "   bash $INSTALL_DIR/setup_windows_image.sh /path/to/Win10.iso"
echo "=========================================================="
sudo systemctl status mintyhost.service
