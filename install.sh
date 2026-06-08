#!/bin/bash
# MintyHost LXC Control Panel - Ubuntu Installation Script
# Made By VoidFlamer
set -e

# ANSI Color Codes
NC='\033[0m'
BOLD='\033[1m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
MAGENTA='\033[35m'
BLUE='\033[34m'

B_CYAN='\033[1;36m'
B_GREEN='\033[1;32m'
B_YELLOW='\033[1;33m'
B_RED='\033[1;31m'
B_MAGENTA='\033[1;35m'
B_BLUE='\033[1;34m'

# Helper functions for formatted output
info_msg() {
    echo -e "${B_CYAN}[*]${NC} ${CYAN}$1${NC}"
}
success_msg() {
    echo -e "${B_GREEN}[✓]${NC} ${GREEN}$1${NC}"
}
warn_msg() {
    echo -e "${B_YELLOW}[!]${NC} ${YELLOW}$1${NC}"
}
error_msg() {
    echo -e "${B_RED}[✗]${NC} ${B_RED}ERROR: $1${NC}"
}

# Define variables
INSTALL_DIR="/var/www/lxc"
REPO_URL="https://github.com/xAyan55/lxc.git"

clear
echo -e "${B_MAGENTA}┌────────────────────────────────────────────────────────┐${NC}"
echo -e "${B_MAGENTA}│${NC}        ${B_CYAN}MINTYHOST LXC CONTROL PANEL INSTALLER${NC}           ${B_MAGENTA}│${NC}"
echo -e "${B_MAGENTA}│${NC}                 ${B_GREEN}Made By VoidFlamer${NC}                    ${B_MAGENTA}│${NC}"
echo -e "${B_MAGENTA}└────────────────────────────────────────────────────────┘${NC}"
echo ""

info_msg "Updating apt package lists..."
sudo apt update -y

info_msg "Installing system dependencies (Python, Git, LXC bridging, SSH, Curl)..."
sudo apt install -y python3 python3-pip python3-venv git snapd bridge-utils uidmap openssh-client curl

info_msg "Installing LXD snap..."
sudo snap install lxd

info_msg "Initializing LXD bridge configuration..."
if ! sudo lxd init --auto; then
    warn_msg "Auto-initialization failed (subnet conflict). Creating a custom lxdbr0 bridge manually..."
    sudo /snap/bin/lxc network create lxdbr0 ipv4.address=10.99.0.1/24 ipv4.nat=true || true
    sudo lxd init --auto
fi

# Ensure default profile has the network device eth0 attached to lxdbr0
sudo /snap/bin/lxc profile device add default eth0 nic network=lxdbr0 name=eth0 || true

info_msg "Configuring firewall rules to allow LXD bridge routing (resolves Docker/UFW conflicts)..."
sudo iptables -I FORWARD -i lxdbr0 -j ACCEPT || true
sudo iptables -I FORWARD -o lxdbr0 -j ACCEPT || true
if command -v ufw >/dev/null; then
    sudo ufw route allow in on lxdbr0 || true
    sudo ufw route allow out on lxdbr0 || true
fi

info_msg "Setting active community images remote URL..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

# If running as non-root user, ensure they belong to the lxd group
if [ "$USER" != "root" ]; then
    info_msg "Adding user $USER to the 'lxd' group..."
    sudo usermod -aG lxd $USER
fi

info_msg "Cloning repository to $INSTALL_DIR..."
sudo mkdir -p /var/www
if [ -d "$INSTALL_DIR" ]; then
    warn_msg "Directory $INSTALL_DIR already exists. Pulling latest..."
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR" 2>/dev/null || sudo chown -R root:root "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

info_msg "Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate

info_msg "Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

info_msg "Seeding database schema..."
python seed.py
deactivate

info_msg "Registering and starting web panel systemd service..."
sudo cp "$INSTALL_DIR/mintyhost.service" /etc/systemd/system/mintyhost.service
sudo systemctl daemon-reload
sudo systemctl enable mintyhost.service
sudo systemctl restart mintyhost.service

info_msg "Setting up Discord Bot virtual environment..."
if [ ! -f "$INSTALL_DIR/bot/.env" ]; then
    cp "$INSTALL_DIR/bot/.env.example" "$INSTALL_DIR/bot/.env"
    warn_msg "Created default bot/.env. Please configure your Discord Token, Guild ID, and API keys."
fi

python3 -m venv "$INSTALL_DIR/bot/venv"
source "$INSTALL_DIR/bot/venv/bin/activate"
pip install --upgrade pip
pip install -r "$INSTALL_DIR/bot/requirements.txt"
deactivate

info_msg "Registering and starting Discord bot systemd service..."
sudo cp "$INSTALL_DIR/bot/mintyhost-bot.service" /etc/systemd/system/mintyhost-bot.service
sudo systemctl daemon-reload
sudo systemctl enable mintyhost-bot.service
sudo systemctl restart mintyhost-bot.service || warn_msg "Discord bot service failed to start. Make sure to configure bot/.env first."

echo ""
echo -e "${B_GREEN}┌────────────────────────────────────────────────────────┐${NC}"
echo -e "${B_GREEN}│${NC}               ${B_GREEN}INSTALLATION COMPLETE!${NC}                   ${B_GREEN}│${NC}"
echo -e "${B_GREEN}└────────────────────────────────────────────────────────┘${NC}"
echo -e "${BOLD} Web Panel running on:${NC} ${B_CYAN}http://YOUR_SERVER_IP:5000${NC}"
echo -e "   - View status: ${CYAN}systemctl status mintyhost.service${NC}"
echo -e "${BOLD} Discord Bot running under systemd.${NC}"
echo -e "   - View status: ${CYAN}systemctl status mintyhost-bot.service${NC}"
echo ""
echo -e "${B_YELLOW}[OPTIONAL] Windows 10 VPS Support:${NC}"
echo -e "   To enable Windows VM deployment, import a Windows ISO:"
echo -e "   ${CYAN}bash $INSTALL_DIR/setup_windows_image.sh /path/to/Win10.iso${NC}"
echo -e "${B_GREEN}==========================================================${NC}"
sudo systemctl status mintyhost.service
