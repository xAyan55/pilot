#!/bin/bash
# PilotPanel LXC Node Daemon - Cloudflare Native Installation Script
# Node connects to the panel via WebSocket through Cloudflare Tunnel.
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

INSTALL_DIR="/var/www/pilotpanel"
REPO_URL="https://github.com/xAyan55/pilot.git"

clear
echo -e "${B_CYAN}    ____  _ __      __     ____                  __${NC}"
echo -e "${B_CYAN}   / __ \\(_) /___  / /_   / __ \\____ _____  ___ / /${NC}"
echo -e "${B_CYAN}  / /_/ / / / __ \\/ __/  / /_/ / __ \`/ __ \\/ _ \\/ / ${NC}"
echo -e "${B_CYAN} / ____/ / / /_/ / /_   / ____/ /_/ / / / /  __/ /  ${NC}"
echo -e "${B_CYAN}/_/   /_/_/\\____/\\__/  /_/    \\__,_/_/ /_/\\___/_/   ${NC}"
echo -e "         ${B_MAGENTA}⚡ Premium LXC Orchestration Node ⚡${NC}"
echo -e "              ${B_GREEN}Created by VoidFlamer${NC}"
echo -e "${B_BLUE}────────────────────────────────────────────────────────────${NC}"
echo ""

info_msg "Updating apt package lists..."
sudo apt update -y

info_msg "Installing system dependencies..."
sudo apt install -y python3 python3-pip python3-venv git snapd bridge-utils uidmap openssh-client curl iptables unzip

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

sudo /snap/bin/lxc profile device add default eth0 nic network=lxdbr0 name=eth0 || true

info_msg "Configuring firewall forwarding rules..."
sudo iptables -I FORWARD -i lxdbr0 -j ACCEPT || true
sudo iptables -I FORWARD -o lxdbr0 -j ACCEPT || true
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -j MASQUERADE || true
if command -v ufw >/dev/null; then
    sudo ufw route allow in on lxdbr0 || true
    sudo ufw route allow out on lxdbr0 || true
fi

info_msg "Setting active community images remote URL..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

if [ "$USER" != "root" ]; then
    info_msg "Adding user $USER to the 'lxd' group..."
    sudo usermod -aG lxd $USER
fi

info_msg "Cloning repository to $INSTALL_DIR..."
sudo mkdir -p /var/www
if [ -d "$INSTALL_DIR" ]; then
    warn_msg "Directory $INSTALL_DIR already exists. Pulling latest..."
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR" 2>/dev/null || true
    cd "$INSTALL_DIR"
    git pull origin main
else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Read config from environment variables passed during curl execution
if [ -z "$NODE_ID" ] || [ "$NODE_ID" = "0" ]; then
    echo -ne "${B_YELLOW}[?] Enter Node ID (e.g. 2): ${NC}"
    read -r NODE_ID < /dev/tty
fi

if [ -z "$NODE_API_KEY" ] || [ "$NODE_API_KEY" = "default-node-key" ]; then
    echo -ne "${B_YELLOW}[?] Enter Node API Key: ${NC}"
    read -r NODE_API_KEY < /dev/tty
fi

if [ -z "$PANEL_URL" ]; then
    echo -ne "${B_YELLOW}[?] Enter Panel URL (e.g., https://panel.yourdomain.com): ${NC}"
    read -r PANEL_URL < /dev/tty
fi

NODE_PORT=${NODE_PORT:-5001}
NODE_NAME=${NODE_NAME:-"Remote Node"}

PANEL_URL=$(echo "$PANEL_URL" | sed 's/\/$//')

info_msg "Writing configuration file .env..."
cd "$INSTALL_DIR/airlink/daemon/daemon-main"
cat <<EOF > .env
remote="0.0.0.0"
key="$NODE_API_KEY"
port=$NODE_PORT
DEBUG=false
version=3.0.0
STATS_INTERVAL=10000
CONTAINER_RUNTIME=docker
REQUIRE_HMAC=true
ALLOWED_IPS=
BEHIND_PROXY=false
EOF

info_msg "Installing daemon dependencies..."
/usr/local/bin/bun install || bun install || true

info_msg "Creating systemd service file..."
sudo bash -c "cat > /etc/systemd/system/pilotpanel-node.service" <<SERVICEEOF
[Unit]
Description=PilotPanel LXC Node Daemon (Bun Core)
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR/airlink/daemon/daemon-main
ExecStart=/usr/local/bin/bun src/app.ts
Restart=always
RestartSec=5
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=LC_ALL=C

[Install]
WantedBy=multi-user.target
SERVICEEOF

info_msg "Starting systemd service..."
sudo systemctl daemon-reload
sudo systemctl enable pilotpanel-node.service
sudo systemctl restart pilotpanel-node.service

echo ""
echo -e "${B_GREEN}┌────────────────────────────────────────────────────────┐${NC}"
echo -e "${B_GREEN}│${NC}                 ${B_GREEN}NODE INSTALLATION COMPLETE!${NC}            ${B_GREEN}│${NC}"
echo -e "${B_GREEN}└────────────────────────────────────────────────────────┘${NC}"
echo -e " The daemon will now connect to: ${B_CYAN}$PANEL_URL${NC}"
echo -e " via WebSocket connection."
echo ""
echo -e "${BOLD} Container SSH Access:${NC}"
echo -e "   Each container gets a forwarded port on this node's IP"
echo -e "   (range 22000-22999). Connect via:"
echo -e "   ${CYAN}ssh root@<NODE_PUBLIC_IP> -p <FORWARDED_PORT>${NC}"
echo ""
echo -e " Check status: ${CYAN}systemctl status pilotpanel-node.service${NC}"
echo -e " View logs:    ${CYAN}journalctl -u pilotpanel-node.service -f${NC}"
echo -e "${B_GREEN}==========================================================${NC}"
sudo systemctl status pilotpanel-node.service
