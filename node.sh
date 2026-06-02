#!/bin/bash
# MintyHost LXC Node Daemon - Cloudflare Native Installation Script
# Node connects to the panel via WebSocket through Cloudflare Tunnel.
set -e

INSTALL_DIR="/var/www/lxc"
REPO_URL="https://github.com/xAyan55/lxc.git"

echo "=========================================================="
echo " Starting MintyHost LXC Node Daemon Installation"
echo " (Cloudflare Native Mode)"
echo "=========================================================="

echo "[*] Updating apt package lists..."
sudo apt update -y

echo "[*] Installing system dependencies..."
sudo apt install -y python3 python3-pip python3-venv git snapd bridge-utils uidmap openssh-client curl iptables

echo "[*] Installing LXD snap..."
sudo snap install lxd

echo "[*] Initializing LXD bridge configuration..."
if ! sudo lxd init --auto; then
    echo "[!] Auto-initialization failed (subnet conflict). Creating a custom lxdbr0 bridge manually..."
    sudo /snap/bin/lxc network create lxdbr0 ipv4.address=10.99.0.1/24 ipv4.nat=true || true
    sudo lxd init --auto
fi

sudo /snap/bin/lxc profile device add default eth0 nic network=lxdbr0 name=eth0 || true

echo "[*] Configuring firewall forwarding rules..."
sudo iptables -I FORWARD -i lxdbr0 -j ACCEPT || true
sudo iptables -I FORWARD -o lxdbr0 -j ACCEPT || true
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -j MASQUERADE || true
if command -v ufw >/dev/null; then
    sudo ufw route allow in on lxdbr0 || true
    sudo ufw route allow out on lxdbr0 || true
fi

echo "[*] Setting active community images remote URL..."
sudo /snap/bin/lxc remote set-url images https://images.lxd.canonical.com/ || true

if [ "$USER" != "root" ]; then
    echo "[*] Adding user $USER to the 'lxd' group..."
    sudo usermod -aG lxd $USER
fi

echo "[*] Cloning repository to $INSTALL_DIR..."
sudo mkdir -p /var/www
if [ -d "$INSTALL_DIR" ]; then
    echo "[!] Directory $INSTALL_DIR already exists. Pulling latest..."
    sudo chown -R "$USER":"$USER" "$INSTALL_DIR" 2>/dev/null || true
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
deactivate

# Read config from environment variables passed during curl execution
if [ -z "$NODE_ID" ] || [ "$NODE_ID" = "0" ]; then
    read -p "Enter Node ID (e.g. 2): " NODE_ID < /dev/tty
fi

if [ -z "$NODE_API_KEY" ] || [ "$NODE_API_KEY" = "default-node-key" ]; then
    read -p "Enter Node API Key: " NODE_API_KEY < /dev/tty
fi

if [ -z "$PANEL_URL" ]; then
    read -p "Enter Panel URL (e.g., https://panel.yourdomain.com): " PANEL_URL < /dev/tty
fi

NODE_PORT=${NODE_PORT:-5001}
NODE_NAME=${NODE_NAME:-"Remote Node"}

PANEL_URL=$(echo "$PANEL_URL" | sed 's/\/$//')

echo "[*] Writing configuration file config.yml..."
cat <<EOF > config.yml
port: $NODE_PORT
api_key: "$NODE_API_KEY"
node_id: $NODE_ID
name: "$NODE_NAME"
panel_url: "$PANEL_URL"
EOF

echo "[*] Creating systemd service file..."
sudo bash -c "cat > /etc/systemd/system/mintyhost-node.service" <<SERVICEEOF
[Unit]
Description=MintyHost LXC Node Daemon (Cloudflare Native)
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python daemon.py
Restart=always
RestartSec=5
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=LC_ALL=C

[Install]
WantedBy=multi-user.target
SERVICEEOF

echo "[*] Starting systemd service..."
sudo systemctl daemon-reload
sudo systemctl enable mintyhost-node.service
sudo systemctl restart mintyhost-node.service

echo "=========================================================="
echo " Node Installation Complete!"
echo ""
echo " The daemon will now connect to: $PANEL_URL"
echo " via WebSocket through Cloudflare Tunnel."
echo ""
echo " Container SSH Access:"
echo "   Each container gets a forwarded port on this node's IP"
echo "   (range 22000-22999). Connect via:"
echo "   ssh root@<NODE_PUBLIC_IP> -p <FORWARDED_PORT>"
echo ""
echo " Check status: systemctl status mintyhost-node.service"
echo " View logs:    journalctl -u mintyhost-node.service -f"
echo "=========================================================="
sudo systemctl status mintyhost-node.service
