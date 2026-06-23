#!/bin/bash
# PilotPanel LXC Control Panel - Ubuntu Installation Script
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
INSTALL_DIR="/var/www/pilotpanel"
REPO_URL="https://github.com/xAyan55/pilot.git"

clear
echo -e "${B_CYAN}    ____  _ __      __     ____                  __${NC}"
echo -e "${B_CYAN}   / __ \\(_) /___  / /_   / __ \\____ _____  ___ / /${NC}"
echo -e "${B_CYAN}  / /_/ / / / __ \\/ __/  / /_/ / __ \`/ __ \\/ _ \\/ / ${NC}"
echo -e "${B_CYAN} / ____/ / / /_/ / /_   / ____/ /_/ / / / /  __/ /  ${NC}"
echo -e "${B_CYAN}/_/   /_/_/\\____/\\__/  /_/    \\__,_/_/ /_/\\___/_/   ${NC}"
echo -e "         ${B_MAGENTA}⚡ Premium LXC Orchestration Panel ⚡${NC}"
echo -e "              ${B_GREEN}Created by VoidFlamer${NC}"
echo -e "${B_BLUE}────────────────────────────────────────────────────────────${NC}"
echo ""

info_msg "Updating apt package lists..."
sudo apt update -y

info_msg "Installing system dependencies (Node.js, Python, Git, LXC bridging, SSH, Curl)..."
# Setup Node.js v20 repository
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

# Install dependencies (including python/venv for bot and tools)
sudo apt install -y nodejs python3 python3-pip python3-venv git snapd bridge-utils uidmap openssh-client curl

info_msg "Installing Bun runtime..."
curl -fsSL https://bun.sh/install | bash
sudo cp /root/.bun/bin/bun /usr/local/bin/bun || sudo cp "$HOME/.bun/bin/bun" /usr/local/bin/bun || true

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

# Check and copy legacy database if present
if [ -f "/var/www/lxc/pilotpanel.db" ] && [ ! -f "$INSTALL_DIR/pilotpanel.db" ]; then
    info_msg "Found existing pilotpanel.db database in legacy directory. Copying to $INSTALL_DIR..."
    sudo cp "/var/www/lxc/pilotpanel.db" "$INSTALL_DIR/pilotpanel.db"
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR/pilotpanel.db" 2>/dev/null || true
fi

info_msg "Setting up PilotPanel TypeScript web panel..."
cd "$INSTALL_DIR/airlink/panel/panel-main"
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Configure production port to 5000 to match old configuration
    sed -i 's/PORT=3000/PORT=5000/g' .env
    sed -i 's/URL="http:\/\/localhost:3000"/URL="http:\/\/localhost:5000"/g' .env
    sed -i 's/NAME="Airlink"/NAME="PilotPanel"/g' .env
fi

npm install
npx prisma generate
npx prisma db push

if [ -f "$INSTALL_DIR/pilotpanel.db" ]; then
    info_msg "Existing pilotpanel.db database found! Migrating data into PilotPanel..."
    npm run migrate:pilot || warn_msg "Database migration failed. You may need to run it manually."
fi

# Build typescript assets
npm run build

info_msg "Setting up PilotPanel Daemon node..."
cd "$INSTALL_DIR/airlink/daemon/daemon-main"
if [ ! -f ".env" ]; then
    cp example.env .env
fi
/usr/local/bin/bun install || bun install || true

info_msg "Registering and starting web panel systemd service..."
sudo cp "$INSTALL_DIR/pilotpanel.service" /etc/systemd/system/pilotpanel.service
sudo systemctl daemon-reload
sudo systemctl enable pilotpanel.service
sudo systemctl restart pilotpanel.service

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
sudo cp "$INSTALL_DIR/bot/pilotpanel-bot.service" /etc/systemd/system/pilotpanel-bot.service
sudo systemctl daemon-reload
sudo systemctl enable pilotpanel-bot.service
sudo systemctl restart pilotpanel-bot.service || warn_msg "Discord bot service failed to start. Make sure to configure bot/.env first."

echo ""
echo -e "${B_GREEN}┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${B_GREEN}│${NC}             ${B_GREEN}${BOLD}PILOTPANEL INSTALLATION COMPLETE!${NC}            ${B_GREEN}│${NC}"
echo -e "${B_GREEN}└──────────────────────────────────────────────────────────┘${NC}"
echo -e " 🚀 ${B_CYAN}PilotPanel Service Status:${NC}"
echo -e "    • Web Interface:    ${B_GREEN}http://YOUR_SERVER_IP:5000${NC}"
echo -e "    • Systemd Service:  ${CYAN}systemctl status pilotpanel.service${NC}"
echo -e ""
echo -e " 🤖 ${B_CYAN}Discord Bot Status:${NC}"
echo -e "    • Systemd Service:  ${CYAN}systemctl status pilotpanel-bot.service${NC}"
echo -e "    • Configuration:    ${YELLOW}/var/www/pilotpanel/bot/.env${NC}"
echo -e ""
echo -e " 💡 ${B_YELLOW}Post-Installation Guide:${NC}"
echo -e "    1. Configure your environment variables in ${BOLD}/var/www/pilotpanel/airlink/panel/panel-main/.env${NC}"
echo -e "    2. Make sure Discord OAuth2 variables are populated for logins to work:"
echo -e "       - DISCORD_CLIENT_ID"
# Enforce line breaks / limits
echo -e "       - DISCORD_CLIENT_SECRET"
echo -e "       - DISCORD_REDIRECT_URI"
echo -e "       - DISCORD_ADMIN_USER_ID"
echo -e "    3. Restart services: ${CYAN}sudo systemctl restart pilotpanel.service${NC}"
echo -e ""
# Keep OPTIONAL Windows line but rename script is still setup_windows_image.sh
echo -e "${B_YELLOW}[OPTIONAL] Windows 10 VPS Support:${NC}"
echo -e "   To enable Windows VM deployment, import a Windows ISO:"
echo -e "   ${CYAN}bash $INSTALL_DIR/setup_windows_image.sh /path/to/Win10.iso${NC}"
echo -e "${B_GREEN}==========================================================${NC}"
sudo systemctl status pilotpanel.service
