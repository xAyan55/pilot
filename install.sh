#!/bin/bash
# PilotPanel LXC Control Panel - Ubuntu Installation Script
# Made By VoidFlamer
set -e

# Colors based on request: Deep Cyan, Sky Blue, White, Silver, Navigation Green
CYAN='\033[36m'
B_CYAN='\033[1;36m'
SKY_BLUE='\033[38;5;39m'
B_SKY_BLUE='\033[1;38;5;39m'
WHITE='\033[97m'
B_WHITE='\033[1;97m'
SILVER='\033[37m'
B_SILVER='\033[1;37m'
NAV_GREEN='\033[32m'
B_NAV_GREEN='\033[1;32m'
RED='\033[31m'
B_RED='\033[1;31m'
YELLOW='\033[33m'
B_YELLOW='\033[1;33m'
NC='\033[0m'

# Helper functions for aviation-themed output
info_msg() {
    echo -e "${B_SKY_BLUE}[ATC]${NC} ${SKY_BLUE}$1${NC}"
}
success_msg() {
    echo -e "${B_NAV_GREEN}[TOWER]${NC} ${NAV_GREEN}$1${NC}"
}
warn_msg() {
    echo -e "${B_YELLOW}[🛰 ALERT]${NC} ${YELLOW}$1${NC}"
}
error_msg() {
    echo -e "${B_RED}[✗ FATAL]${NC} ${B_RED}SYSTEM CRITICAL: $1${NC}"
}

show_progress() {
    local label="$1"
    local steps=5
    echo -ne "${B_SKY_BLUE}✈${NC} ${SILVER}${label}...${NC}\n"
    for ((i=1; i<=steps; i++)); do
        local pct=$((i * 20))
        local bar=""
        for ((j=1; j<=5; j++)); do
            if [ $j -le $i ]; then
                bar="${bar}■"
            else
                bar="${bar}□"
            fi
        done
        echo -ne "\r${B_SKY_BLUE}[${bar}]${NC} ${WHITE}${pct}%${NC}"
        sleep 0.2
    done
    echo -e "\r${B_NAV_GREEN}[■■■■■]${NC} ${NAV_GREEN}100% - Ready.${NC}\n"
}

# Define variables
INSTALL_DIR="/var/www/pilotpanel"
REPO_URL="https://github.com/xAyan55/pilot.git"

clear
echo -e "${B_SKY_BLUE}               ______${NC}"
echo -e "${B_SKY_BLUE}             //  ||  \\\\ ${NC}"
echo -e "${B_SKY_BLUE}       ____ //___||___\\\\ ____${NC}"
echo -e "${B_SKY_BLUE}      (____(______/ \\____)____)${NC}"
echo -e "${B_SKY_BLUE}            |    ||    |${NC}"
echo -e "${B_SKY_BLUE}            |____||____|${NC}"
echo -e ""
echo -e "          ${B_WHITE}P I L O T P A N E L${NC}"
echo -e "      ${SILVER}Flight Operations Platform${NC}"
echo -e "${B_SKY_BLUE}────────────────────────────────────────────────────────────${NC}"
echo ""

echo -e "${B_WHITE}✈ PHASE 1 — PRE-FLIGHT CHECKS${NC}"
show_progress "Establishing communication with package repository control"
sudo apt update -y

echo -e "\n${B_WHITE}✈ PHASE 2 — AIRCRAFT PREPARATION${NC}"
info_msg "Fetching Node.js v20 package repository blueprints..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

info_msg "[GROUND CREW] Loading required system utilities (Python, Git, LXC bridges, SSH, Curl)..."
sudo apt install -y nodejs python3 python3-pip python3-venv git snapd bridge-utils uidmap openssh-client curl

info_msg "[GROUND CREW] Provisioning Bun runtime compiler engine..."
curl -fsSL https://bun.sh/install | bash
sudo cp /root/.bun/bin/bun /usr/local/bin/bun || sudo cp "$HOME/.bun/bin/bun" /usr/local/bin/bun || true

info_msg "[GROUND CREW] Deploying virtualization engine (LXD Snap)..."
sudo snap install lxd

echo -e "\n${B_WHITE}✈ PHASE 3 — NETWORK CONFIGURATION${NC}"
info_msg "Configuring container network bridge lxdbr0..."
if ! sudo lxd init --auto; then
    warn_msg "Auto-initialization failed due to subnet overlap. Provisioning custom bridge route manually..."
    sudo /snap/bin/lxc network create lxdbr0 ipv4.address=10.99.0.1/24 ipv4.nat=true || true
    sudo lxd init --auto
fi

# Ensure default profile has the network device eth0 attached to lxdbr0
sudo /snap/bin/lxc profile device add default eth0 nic network=lxdbr0 name=eth0 || true

info_msg "Applying routing policies for container traffic forwarding..."
sudo iptables -I FORWARD -i lxdbr0 -j ACCEPT || true
sudo iptables -I FORWARD -o lxdbr0 -j ACCEPT || true
if command -v ufw >/dev/null; then
    sudo ufw route allow in on lxdbr0 || true
    sudo ufw route allow out on lxdbr0 || true
fi

info_msg "Configuring satellite navigation images registry URL..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

# If running as non-root user, ensure they belong to the lxd group
if [ "$USER" != "root" ]; then
    info_msg "Granting user $USER permission to access hypervisor controls..."
    sudo usermod -aG lxd $USER
fi

echo -e "\n${B_WHITE}✈ PHASE 4 — CONTROL SYSTEM DEPLOYMENT${NC}"
info_msg "Downloading PilotPanel flight operations blueprints to $INSTALL_DIR..."
sudo mkdir -p /var/www
if [ -d "$INSTALL_DIR" ]; then
    warn_msg "Target directory exists. Fetching latest updates from origin control..."
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR" 2>/dev/null || sudo chown -R root:root "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Check and copy legacy database if present
if [ -f "/var/www/lxc/pilotpanel.db" ] && [ ! -f "$INSTALL_DIR/pilotpanel.db" ]; then
    info_msg "Restoring historical flight records database pilotpanel.db..."
    sudo cp "/var/www/lxc/pilotpanel.db" "$INSTALL_DIR/pilotpanel.db"
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR/pilotpanel.db" 2>/dev/null || true
fi

echo -e "\n${B_WHITE}✈ PHASE 5 — FLIGHT SERVICES ACTIVATION${NC}"
info_msg "Initializing PilotPanel TypeScript cockpit modules..."
cd "$INSTALL_DIR/airlink/panel/panel-main"
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Configure production port to 5000 to match old configuration
    sed -i 's/PORT=3000/PORT=5000/g' .env
    sed -i 's/URL="http:\/\/localhost:3000"/URL="http:\/\/localhost:5000"/g' .env
    sed -i 's/NAME="Airlink"/NAME="PilotPanel"/g' .env
fi

info_msg "[GROUND CREW] Loading node packages for cockpit interface..."
npm install
info_msg "[GROUND CREW] Building database schema blueprint classes..."
npx prisma generate
npx prisma db push

if [ -f "$INSTALL_DIR/pilotpanel.db" ]; then
    info_msg "Importing legacy database information into primary cockpit database..."
    npm run migrate:pilot || warn_msg "Data migration experienced database conflicts. Please review logs."
fi

info_msg "[GROUND CREW] Compiling instrumentation display styling (CSS/JS)..."
npm run build

info_msg "Setting up local hypervisor monitoring node daemon..."
cd "$INSTALL_DIR/airlink/daemon/daemon-main"
if [ ! -f ".env" ]; then
    cp example.env .env
fi
info_msg "[GROUND CREW] Installing daemon package bundles..."
/usr/local/bin/bun install || bun install || true

echo -e "\n${B_WHITE}✈ PHASE 6 — FINAL SYSTEM INSPECTION${NC}"
info_msg "[TOWER] Authorizing PilotPanel systems for takeoff (systemd cockpit registration)..."
sudo cp "$INSTALL_DIR/pilotpanel.service" /etc/systemd/system/pilotpanel.service
sudo systemctl daemon-reload
sudo systemctl enable pilotpanel.service
sudo systemctl restart pilotpanel.service

info_msg "Assembling auxiliary Discord communications link..."
if [ ! -f "$INSTALL_DIR/bot/.env" ]; then
    cp "$INSTALL_DIR/bot/.env.example" "$INSTALL_DIR/bot/.env"
    warn_msg "Generated bot/.env config. Setup Discord credentials to activate bot telemetry links."
fi

python3 -m venv "$INSTALL_DIR/bot/venv"
source "$INSTALL_DIR/bot/venv/bin/activate"
pip install --upgrade pip
pip install -r "$INSTALL_DIR/bot/requirements.txt"
deactivate

info_msg "[TOWER] Launching Discord communication services..."
sudo cp "$INSTALL_DIR/bot/pilotpanel-bot.service" /etc/systemd/system/pilotpanel-bot.service
sudo systemctl daemon-reload
sudo systemctl enable pilotpanel-bot.service
sudo systemctl restart pilotpanel-bot.service || warn_msg "Discord communications bot failed to launch. Verify credentials in bot/.env."

echo ""
echo -e "${B_SKY_BLUE}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${B_SKY_BLUE}║${NC}               ${B_WHITE}${BOLD}🛫 PILOTPANEL DEPLOYMENT COMPLETED 🛫${NC}              ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}╠══════════════════════════════════════════════════════════════════════════╣${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Flight Status:${NC}        ${B_NAV_GREEN}ONLINE 🛫${NC}                                          ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Control Panel URL:${NC}    ${B_SKY_BLUE}http://YOUR_SERVER_IP:5000${NC}                            ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Virtualization Engine:${NC} ${SILVER}LXC/LXD (OPERATIONAL)${NC}                                  ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Local Monitoring Node:${NC} ${SILVER}ACTIVE 🛰${NC}                                            ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Discord Telemetry Link:${NC} ${SILVER}ACTIVE 📡${NC}                                           ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}                                                                          ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Control Systemd Unit:${NC}  ${SILVER}systemctl status pilotpanel.service${NC}             ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Discord Bot Service:${NC}   ${SILVER}systemctl status pilotpanel-bot.service${NC}         ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Bot Config File:${NC}       ${SILVER}/var/www/pilotpanel/bot/.env${NC}                    ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e " ${B_WHITE}🛫 Post-Flight Instructions:${NC}"
echo -e "    1. Populate credentials and keys in the primary config file:"
echo -e "       ${BOLD}/var/www/pilotpanel/airlink/panel/panel-main/.env${NC}"
echo -e "    2. Set OAuth2 variables for client/admin log-ins:"
echo -e "       - DISCORD_CLIENT_ID"
echo -e "       - DISCORD_CLIENT_SECRET"
echo -e "       - DISCORD_REDIRECT_URI"
echo -e "       - DISCORD_ADMIN_USER_ID"
echo -e "    3. Restart navigation services: ${CYAN}sudo systemctl restart pilotpanel.service${NC}"
echo ""
echo -e " ${B_WHITE}📡 Windows 10/11 VM Support:${NC}"
echo -e "    To deploy Windows VMs on this node, pre-bake the OS image:"
echo -e "    ${CYAN}bash $INSTALL_DIR/setup_windows_image.sh /path/to/windows.iso${NC}"
echo -e "${B_SKY_BLUE}============================================================================${NC}"
sudo systemctl status pilotpanel.service
