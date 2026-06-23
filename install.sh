#!/bin/bash
# PilotPanel - Ubuntu Installation Script
# Made By VoidFlamer
set -e

# ─── Colors ───────────────────────────────────────────────────────────────────
CYAN='\033[36m'
B_CYAN='\033[1;36m'
SKY_BLUE='\033[38;5;39m'
B_SKY_BLUE='\033[1;38;5;39m'
WHITE='\033[97m'
B_WHITE='\033[1;97m'
SILVER='\033[37m'
NAV_GREEN='\033[32m'
B_NAV_GREEN='\033[1;32m'
RED='\033[31m'
B_RED='\033[1;31m'
YELLOW='\033[33m'
B_YELLOW='\033[1;33m'
NC='\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────
info_msg()    { echo -e "${B_SKY_BLUE}[ATC]${NC} ${SKY_BLUE}$1${NC}"; }
success_msg() { echo -e "${B_NAV_GREEN}[TOWER]${NC} ${NAV_GREEN}$1${NC}"; }
warn_msg()    { echo -e "${B_YELLOW}[⚠ ALERT]${NC} ${YELLOW}$1${NC}"; }
error_msg()   { echo -e "${B_RED}[✗ FATAL]${NC} ${B_RED}$1${NC}"; }

show_progress() {
    local label="$1"
    echo -ne "${B_SKY_BLUE}✈${NC} ${SILVER}${label}...${NC}\n"
    for ((i=1;i<=5;i++)); do
        local bar=""
        for ((j=1;j<=5;j++)); do
            [ $j -le $i ] && bar="${bar}■" || bar="${bar}□"
        done
        echo -ne "\r${B_SKY_BLUE}[${bar}]${NC} ${WHITE}$((i*20))%${NC}"
        sleep 0.2
    done
    echo -e "\r${B_NAV_GREEN}[■■■■■]${NC} ${NAV_GREEN}100% - Ready.${NC}\n"
}

# ─── Root Path (REQUIREMENT #1 & #5) ─────────────────────────────────────────
# APP_ROOT is the single source of truth for ALL paths in this installer.
APP_ROOT="/var/www/pilotpanel"
PANEL_DIR="$APP_ROOT/airlink/panel/panel-main"
DAEMON_DIR="$APP_ROOT/airlink/daemon/daemon-main"
BOT_DIR="$APP_ROOT/bot"
ENV_FILE="$APP_ROOT/.env"             # Single .env at repo root
REPO_URL="https://github.com/xAyan55/pilot.git"

# ─── Banner ───────────────────────────────────────────────────────────────────
clear
echo -e "${B_SKY_BLUE}               ______${NC}"
echo -e "${B_SKY_BLUE}             //  ||  \\ ${NC}"
echo -e "${B_SKY_BLUE}       ____ //___||___\\ ____${NC}"
echo -e "${B_SKY_BLUE}      (____(______/ \\____)____)${NC}"
echo -e "${B_SKY_BLUE}            |    ||    |${NC}"
echo -e "${B_SKY_BLUE}            |____||____|${NC}"
echo ""
echo -e "          ${B_WHITE}P I L O T P A N E L${NC}"
echo -e "      ${SILVER}Flight Operations Platform${NC}"
echo -e "${B_SKY_BLUE}────────────────────────────────────────────────────────────${NC}"
echo ""

# ═════════════════════════════════════════════════════════════════════════════
echo -e "${B_WHITE}✈ PHASE 1 — PRE-FLIGHT CHECKS${NC}"
# ═════════════════════════════════════════════════════════════════════════════
show_progress "Establishing communication with package repository control"
sudo apt update -y

# ═════════════════════════════════════════════════════════════════════════════
echo -e "\n${B_WHITE}✈ PHASE 2 — AIRCRAFT PREPARATION${NC}"
# ═════════════════════════════════════════════════════════════════════════════
info_msg "Fetching Node.js v20 package repository blueprints..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

info_msg "Loading required system utilities..."
sudo apt install -y nodejs python3 python3-pip python3-venv git snapd \
    bridge-utils uidmap openssh-client curl unzip

info_msg "Provisioning Bun runtime compiler engine..."
curl -fsSL https://bun.sh/install | bash
sudo cp /root/.bun/bin/bun /usr/local/bin/bun \
    || sudo cp "$HOME/.bun/bin/bun" /usr/local/bin/bun \
    || true

info_msg "Deploying virtualization engine (LXD)..."
sudo snap install lxd

# ═════════════════════════════════════════════════════════════════════════════
echo -e "\n${B_WHITE}✈ PHASE 3 — NETWORK CONFIGURATION${NC}"
# ═════════════════════════════════════════════════════════════════════════════
info_msg "Configuring container network bridge lxdbr0..."
if ! sudo lxd init --auto; then
    warn_msg "Auto-init failed. Creating custom bridge manually..."
    sudo /snap/bin/lxc network create lxdbr0 ipv4.address=10.99.0.1/24 ipv4.nat=true || true
    sudo lxd init --auto
fi

sudo /snap/bin/lxc profile device add default eth0 nic network=lxdbr0 name=eth0 || true

info_msg "Applying container traffic forwarding rules..."
sudo iptables -I FORWARD -i lxdbr0 -j ACCEPT || true
sudo iptables -I FORWARD -o lxdbr0 -j ACCEPT || true
if command -v ufw >/dev/null; then
    sudo ufw route allow in on lxdbr0 || true
    sudo ufw route allow out on lxdbr0 || true
fi

info_msg "Configuring LXD image registry..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

if [ "$USER" != "root" ]; then
    info_msg "Adding $USER to lxd group..."
    sudo usermod -aG lxd "$USER"
fi

# ═════════════════════════════════════════════════════════════════════════════
echo -e "\n${B_WHITE}✈ PHASE 4 — CODEBASE DEPLOYMENT${NC}"
# ═════════════════════════════════════════════════════════════════════════════
info_msg "Deploying PilotPanel to $APP_ROOT ..."
sudo mkdir -p /var/www
if [ -d "$APP_ROOT" ]; then
    warn_msg "Target directory exists — pulling latest updates..."
    sudo chown -R "${USER}":"${USER}" "$APP_ROOT" 2>/dev/null \
        || sudo chown -R root:root "$APP_ROOT"
    cd "$APP_ROOT"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$APP_ROOT"
    cd "$APP_ROOT"
fi

# ─── Generate root .env (REQUIREMENT #2) ──────────────────────────────────────
# All secrets live in ONE file: $APP_ROOT/.env
# The panel and daemon .env files are symlinks to this single file.
info_msg "Generating master configuration file at $ENV_FILE ..."

# Detect server IP
SERVER_IP=$(hostname -I | awk '{print $1}')
SESSION_SECRET=$(openssl rand -hex 32)

if [ ! -f "$ENV_FILE" ]; then
cat > "$ENV_FILE" << ENVEOF
# ══════════════════════════════════════════════════════
#  PilotPanel — Master Configuration
#  Location: $ENV_FILE
#  Edit this file, then run: systemctl restart pilotpanel
# ══════════════════════════════════════════════════════

# ── Discord OAuth2 (REQUIRED) ──────────────────────────
# Create an app at https://discord.com/developers/applications
# Under OAuth2 → Redirects, add your callback URL below.
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=http://${SERVER_IP}:5000/auth/discord/callback
DISCORD_ADMIN_USER_ID=

# ── Panel ──────────────────────────────────────────────
PORT=5000
URL=http://${SERVER_IP}:5000
NAME=PilotPanel
NODE_ENV=production
SESSION_SECRET=${SESSION_SECRET}

# ── Database ───────────────────────────────────────────
DATABASE_URL=file:${PANEL_DIR}/storage/dev.db

# ── Daemon ─────────────────────────────────────────────
# These are read by the node daemon (airlink/daemon/daemon-main)
remote=0.0.0.0
key=change-this-daemon-key-now
port=5001
DEBUG=false
version=3.0.0
STATS_INTERVAL=10000
CONTAINER_RUNTIME=docker
REQUIRE_HMAC=true
ALLOWED_IPS=
BEHIND_PROXY=false
ENVEOF
    success_msg "Master .env created at $ENV_FILE"
else
    warn_msg "$ENV_FILE already exists — skipping creation. Existing values preserved."
    # Always ensure port and name are correct
    sed -i 's/^PORT=.*/PORT=5000/' "$ENV_FILE"
    sed -i 's/^NAME=Airlink/NAME=PilotPanel/' "$ENV_FILE"
fi

# ─── Symlink .env to panel and daemon (REQUIREMENT #1 & #5) ───────────────────
# Panel and daemon read .env from their own working directory.
# We symlink the single master .env to both locations so only ONE file to edit.
info_msg "Symlinking master .env to panel and daemon directories..."
ln -sf "$ENV_FILE" "$PANEL_DIR/.env"
ln -sf "$ENV_FILE" "$DAEMON_DIR/.env"
success_msg "Symlinks created: panel and daemon both read from $ENV_FILE"

# ═════════════════════════════════════════════════════════════════════════════
echo -e "\n${B_WHITE}✈ PHASE 5 — PANEL BUILD & DATABASE${NC}"
# ═════════════════════════════════════════════════════════════════════════════
info_msg "Installing panel Node.js packages..."
cd "$PANEL_DIR"
npm install

info_msg "Generating Prisma database client..."
npx prisma generate

info_msg "Pushing database schema..."
npx prisma db push

info_msg "Building panel CSS and TypeScript assets..."
npm run build

# ─── Daemon dependencies ───────────────────────────────────────────────────
info_msg "Installing daemon Bun packages..."
cd "$DAEMON_DIR"
/usr/local/bin/bun install || bun install || true

# ═════════════════════════════════════════════════════════════════════════════
echo -e "\n${B_WHITE}✈ PHASE 6 — CONFIGURATION VALIDATION${NC}"
# ═════════════════════════════════════════════════════════════════════════════
info_msg "Validating required configuration variables..."

MISSING_VARS=0

check_var() {
    local key="$1"
    local val
    val=$(grep -E "^${key}=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [ -z "$val" ]; then
        warn_msg "MISSING: ${key} is not set in $ENV_FILE"
        MISSING_VARS=$((MISSING_VARS + 1))
    fi
}

check_var "DISCORD_CLIENT_ID"
check_var "DISCORD_CLIENT_SECRET"
check_var "SESSION_SECRET"

if [ "$MISSING_VARS" -gt 0 ]; then
    echo ""
    echo -e "${B_YELLOW}┌─────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${B_YELLOW}│  ⚠  ${MISSING_VARS} required variable(s) are missing from your .env file.      │${NC}"
    echo -e "${B_YELLOW}│  PilotPanel will start but Discord login WILL NOT work until set.  │${NC}"
    echo -e "${B_YELLOW}│  Edit: nano ${ENV_FILE}                        │${NC}"
    echo -e "${B_YELLOW}└─────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
fi

# ═════════════════════════════════════════════════════════════════════════════
echo -e "\n${B_WHITE}✈ PHASE 7 — SERVICE REGISTRATION${NC}"
# ═════════════════════════════════════════════════════════════════════════════

# ─── Write panel systemd service ──────────────────────────────────────────────
info_msg "Registering PilotPanel panel service..."
sudo bash -c "cat > /etc/systemd/system/pilotpanel.service" << SVCEOF
[Unit]
Description=PilotPanel Control Panel
After=network.target

[Service]
User=root
WorkingDirectory=${PANEL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/node dist/app.js
Restart=always
RestartSec=5
Environment=PATH=/usr/bin:/usr/local/bin:/bin

[Install]
WantedBy=multi-user.target
SVCEOF

# ─── Write daemon systemd service ─────────────────────────────────────────────
info_msg "Registering PilotPanel daemon service..."
sudo bash -c "cat > /etc/systemd/system/pilotpanel-node.service" << SVCEOF
[Unit]
Description=PilotPanel LXC Node Daemon
After=network.target

[Service]
User=root
WorkingDirectory=${DAEMON_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/local/bin/bun src/app.ts
Restart=always
RestartSec=5
Environment=PATH=/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
SVCEOF

# ─── Discord Bot (Python) ──────────────────────────────────────────────────
info_msg "Setting up Discord bot..."
if [ -f "$BOT_DIR/requirements.txt" ]; then
    python3 -m venv "$BOT_DIR/venv"
    source "$BOT_DIR/venv/bin/activate"
    pip install --upgrade pip -q
    pip install -r "$BOT_DIR/requirements.txt" -q
    deactivate

    sudo bash -c "cat > /etc/systemd/system/pilotpanel-bot.service" << SVCEOF
[Unit]
Description=PilotPanel Discord Bot
After=network.target pilotpanel.service

[Service]
User=root
WorkingDirectory=${BOT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${BOT_DIR}/venv/bin/python bot.py
Restart=always
RestartSec=5
Environment=PATH=${BOT_DIR}/venv/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF
fi

# ─── Enable and start services ─────────────────────────────────────────────
info_msg "Loading service definitions..."
sudo systemctl daemon-reload

info_msg "Enabling and starting PilotPanel panel..."
sudo systemctl enable pilotpanel.service
sudo systemctl restart pilotpanel.service

info_msg "Enabling and starting PilotPanel daemon..."
sudo systemctl enable pilotpanel-node.service
sudo systemctl restart pilotpanel-node.service

if [ -f "$BOT_DIR/requirements.txt" ]; then
    info_msg "Enabling and starting Discord bot..."
    sudo systemctl enable pilotpanel-bot.service
    sudo systemctl restart pilotpanel-bot.service \
        || warn_msg "Bot failed to start — fill Discord credentials first."
fi

# ═════════════════════════════════════════════════════════════════════════════
# REQUIREMENT #3 — Post-Install Summary
# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${B_SKY_BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${B_SKY_BLUE}║${NC}             ${B_WHITE}🛫  PILOTPANEL DEPLOYMENT COMPLETE  🛫${NC}            ${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}╠══════════════════════════════════════════════════════════════════════╣${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Panel URL:${NC}       ${CYAN}http://${SERVER_IP}:5000${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}App Root:${NC}        ${SILVER}${APP_ROOT}${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Config File:${NC}     ${SILVER}${ENV_FILE}${NC}"
echo -e "${B_SKY_BLUE}╠══════════════════════════════════════════════════════════════════════╣${NC}"
echo -e "${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_RED}ACTION REQUIRED — Set these variables in your .env:${NC}"
echo -e "${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}    ${B_YELLOW}DISCORD_CLIENT_ID${NC}      = <from Discord Developer Portal>"
echo -e "${B_SKY_BLUE}║${NC}    ${B_YELLOW}DISCORD_CLIENT_SECRET${NC}  = <from Discord Developer Portal>"
echo -e "${B_SKY_BLUE}║${NC}    ${B_YELLOW}DISCORD_REDIRECT_URI${NC}   = http://${SERVER_IP}:5000/auth/discord/callback"
echo -e "${B_SKY_BLUE}║${NC}    ${B_YELLOW}DISCORD_ADMIN_USER_ID${NC}  = <your Discord user ID>"
echo -e "${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Step 1:${NC} Edit config:"
echo -e "${B_SKY_BLUE}║${NC}    ${CYAN}nano ${ENV_FILE}${NC}"
echo -e "${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Step 2:${NC} Restart panel:"
echo -e "${B_SKY_BLUE}║${NC}    ${CYAN}systemctl restart pilotpanel${NC}"
echo -e "${B_SKY_BLUE}║${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Discord App Setup:${NC}"
echo -e "${B_SKY_BLUE}║${NC}    ${SILVER}https://discord.com/developers/applications${NC}"
echo -e "${B_SKY_BLUE}║${NC}    Add redirect: ${CYAN}http://${SERVER_IP}:5000/auth/discord/callback${NC}"
echo -e "${B_SKY_BLUE}║${NC}    Scopes: ${SILVER}identify, email${NC}"
echo -e "${B_SKY_BLUE}╠══════════════════════════════════════════════════════════════════════╣${NC}"
echo -e "${B_SKY_BLUE}║${NC}  ${B_WHITE}Service Commands:${NC}"
echo -e "${B_SKY_BLUE}║${NC}    ${CYAN}systemctl status pilotpanel${NC}          — panel status"
echo -e "${B_SKY_BLUE}║${NC}    ${CYAN}systemctl status pilotpanel-node${NC}      — daemon status"
echo -e "${B_SKY_BLUE}║${NC}    ${CYAN}systemctl status pilotpanel-bot${NC}       — Discord bot status"
echo -e "${B_SKY_BLUE}║${NC}    ${CYAN}journalctl -u pilotpanel -f${NC}           — panel logs"
echo -e "${B_SKY_BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
