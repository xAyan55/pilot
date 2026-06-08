import os
import urllib.request
import urllib.parse
import urllib.error
import json
import time
from database import get_db_connection
from lxc_manager import LXCManager
from dotenv import load_dotenv

# Load bot environment variables
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), 'bot', '.env'))

def get_config_setting(key, env_name=None):
    """Retrieve config value from sqlite database settings first, then from environment variable."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        if row and row['value'] and row['value'].strip() and not row['value'].strip().startswith("your_"):
            return row['value'].strip()
    except Exception:
        pass

    if env_name:
        val = os.getenv(env_name)
        if val and val.strip() and not val.strip().startswith("your_"):
            return val.strip()
    return None

def get_discord_bot_token():
    return get_config_setting('discord_bot_token', 'DISCORD_BOT_TOKEN')

def get_discord_guild_id():
    return get_config_setting('discord_guild_id', 'DISCORD_GUILD_ID')

def fetch_discord_guild_members():
    """Retrieve members list of the configured Guild via Discord v10 API."""
    token = get_discord_bot_token()
    guild_id = get_discord_guild_id()
    if not token or not guild_id:
        return []
    
    url = f"https://discord.com/api/v10/guilds/{guild_id}/members?limit=1000"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/xAyan55/lxc, 1.0.0) Python-urllib/3.12"
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            members = []
            for m in data:
                user = m.get("user", {})
                if user.get("bot"):
                    continue
                username = user.get("username")
                global_name = user.get("global_name")
                display_name = global_name if global_name else username
                members.append({
                    "id": user.get("id"),
                    "username": username,
                    "display_name": display_name
                })
            # Case-insensitive sorting by display_name
            members.sort(key=lambda x: x["display_name"].lower())
            return members
    except Exception as e:
        print(f"[ERROR] Failed to fetch discord members from Discord API: {e}")
        return []

def send_discord_dm_embed(discord_user_id, embed_dict):
    """Create a DM channel with recipient user and send a message with the specified Embed dictionary."""
    token = get_discord_bot_token()
    if not token or not discord_user_id:
        return False
    
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/xAyan55/lxc, 1.0.0) Python-urllib/3.12"
    }
    
    # 1. Create DM channel
    dm_url = "https://discord.com/api/v10/users/@me/channels"
    dm_data = json.dumps({"recipient_id": str(discord_user_id)}).encode("utf-8")
    req = urllib.request.Request(dm_url, data=dm_data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            channel = json.loads(resp.read().decode())
            channel_id = channel.get("id")
            if not channel_id:
                return False
            
            # 2. Send message
            msg_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            msg_data = json.dumps({"embeds": [embed_dict]}).encode("utf-8")
            msg_req = urllib.request.Request(msg_url, data=msg_data, headers=headers, method="POST")
            with urllib.request.urlopen(msg_req, timeout=5) as msg_resp:
                return msg_resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            print(f"Error sending Discord DM Embed to {discord_user_id}: HTTP {e.code} - {err_body}")
        except Exception:
            print(f"Error sending Discord DM Embed to {discord_user_id}: {e}")
        return False
    except Exception as e:
        print(f"Error sending Discord DM Embed to {discord_user_id}: {e}")
        return False

def send_user_creation_dm(discord_user_id, username, email, password, panel_url):
    """Send user credential details via DM embed on account registration."""
    embed = {
        "title": "🔐 MintyHost Control Panel Account Created",
        "description": "An administrator has created an account for you on the MintyHost LXC Control Panel.",
        "color": 6512639, # HSL Primary theme blueish tone
        "fields": [
            {"name": "Panel Link", "value": f"🔗 [Go to Control Panel]({panel_url})", "inline": False},
            {"name": "Username", "value": f"`{username}`", "inline": True},
            {"name": "Email", "value": f"`{email}`", "inline": True},
            {"name": "Default Password", "value": f"`{password}`", "inline": False}
        ],
        "footer": {
            "text": "MintyHost Infrastructure Services"
        }
    }
    return send_discord_dm_embed(discord_user_id, embed)

def send_vps_creation_dm(discord_user_id, vps_id, root_password, ip_address, tunnel_url, panel_url, site_name):
    """Send server specifications and login details (including SSH commands) via DM embed on VPS deploy."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ?", (vps_id,))
    vps = cursor.fetchone()
    conn.close()
    if not vps:
        return False

    is_windows = 'windows' in (vps['os'] or '').lower()
    login_user = 'Administrator' if is_windows else 'root'

    ssh_info = f"Host: `{ip_address}`\nPort: `22`"
    if tunnel_url:
        ssh_info = f"Relay command: `{tunnel_url}`"

    fields = [
        {"name": "Panel Link", "value": f"🔗 [Go to Control Panel]({panel_url})", "inline": False},
        {"name": "Server ID", "value": f"`{vps['id']}`", "inline": True},
        {"name": "Container Name", "value": f"`{vps['container_name']}`", "inline": True},
        {"name": "OS Distribution", "value": f"`{vps['os']}`", "inline": True},
        {"name": "Hardware Profile", "value": f"⚡ `{vps['cpu']} Cores / {vps['ram']}MB RAM / {vps['disk']}GB SSD`", "inline": False},
        {"name": "Login User", "value": f"`{login_user}`", "inline": True},
        {"name": "Root Password", "value": f"`{root_password}`", "inline": True},
    ]

    if is_windows:
        rdp_port = 3389
        fields.append({
            "name": "🖥️ RDP Connection (Windows)",
            "value": f"Host: `{ip_address}`\nPort: `{rdp_port}`\nUser: `{login_user}`\nPassword: `{root_password}`",
            "inline": False,
        })
        fields.append({
            "name": "🔐 SSH Connection (OpenSSH)",
            "value": f"Host: `{ip_address}`\nPort: `22`\nUser: `{login_user}`\nPassword: `{root_password}`",
            "inline": False,
        })
    else:
        fields.append({"name": "SSH Connection", "value": ssh_info, "inline": False})

    embed = {
        "title": "🖥️ New VPS Instance Deployed",
        "description": "Your new virtual private server container is now online and ready to use.",
        "color": 6512639,
        "fields": fields,
        "footer": {
            "text": f"{site_name} Automated Provisioning"
        }
    }
    return send_discord_dm_embed(discord_user_id, embed)

def _internal_make_node_request(node, endpoint, method='POST', data=None):
    """Helper to perform requests to remote hypervisor node API."""
    url = f"http://{node['fqdn']}:{node['port']}{endpoint}"
    headers = {
        "Authorization": f"Bearer {node['api_key']}",
        "Content-Type": "application/json"
    }
    req_data = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), resp.status
    except Exception as e:
        return {"message": str(e)}, 500

def run_post_deploy_and_notify(container_name, vps_id, root_pw, site_name_val, node_id, node, discord_user_id, panel_url):
    """Background worker function executing post-deploy packages setup, port forward allocation, and credentials DM delivery."""
    try:
        # 1. Run post-deployment configuration on target hypervisor node
        if node_id != 1:
            _internal_make_node_request(node, "/api/vps/post-deploy", data={
                "name": container_name,
                "vps_id": vps_id,
                "password": root_pw,
                "site_name": site_name_val
            })
        else:
            LXCManager.post_deploy_setup(
                name=container_name,
                vps_id=vps_id,
                root_password=root_pw,
                site_name=site_name_val
            )
            
        # 2. If Discord DM is requested, poll host for IP and tunnel URL
        if discord_user_id:
            ip_address = 'Pending'
            tunnel_url = None
            
            # Poll for up to 30 seconds (15 cycles * 2s) to wait for tunnel/post-deploy to finish
            for _ in range(15):
                time.sleep(2)
                if node_id != 1:
                    res, code = _internal_make_node_request(node, "/api/vps/stats", method='GET', data={
                        "name": container_name, "vps_id": vps_id
                    })
                    if code == 200:
                        ip = res.get("ip")
                        if ip and ip not in ('Pending', 'N/A'):
                            ip_address = ip
                        t_host = res.get("tunnel_host")
                        t_port = res.get("tunnel_port")
                        if t_host and t_port:
                            tunnel_url = f"ssh -p {t_port} root@{t_host}"
                            break
                else:
                    ip = LXCManager.get_container_ip(container_name)
                    if ip and ip not in ('Pending', 'N/A'):
                        ip_address = ip
                    
                    stats = LXCManager.get_container_stats(container_name, plan_cpu=1, plan_ram=512, plan_disk=10, db_status='running', vps_id=vps_id)
                    t_host = stats.get('tunnel_host')
                    t_port = stats.get('tunnel_port')
                    if t_host and t_port:
                        tunnel_url = f"ssh -p {t_port} root@{t_host}"
                        break
            
            # 3. Deliver rich DM notifications to recipient Discord ID
            send_vps_creation_dm(discord_user_id, vps_id, root_pw, ip_address, tunnel_url, panel_url, site_name_val)
    except Exception as e:
        print(f"[ERROR] Unified post-deploy setup and notification failed for VPS ID {vps_id}: {e}")

def send_vps_deploy_status_alert(discord_user_id, container_name, status_text, is_success, details_or_error):
    """Sends a deployment status alert (success/failure) directly to the configured Discord user ID."""
    token = get_discord_bot_token()
    if not token or not discord_user_id:
        return False

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/xAyan55/lxc, 1.0.0) Python-urllib/3.12"
    }

    # 1. Create DM channel
    dm_url = "https://discord.com/api/v10/users/@me/channels"
    dm_data = json.dumps({"recipient_id": str(discord_user_id)}).encode("utf-8")
    req = urllib.request.Request(dm_url, data=dm_data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            channel = json.loads(resp.read().decode())
            channel_id = channel.get("id")
            if not channel_id:
                return False

            # 2. Build embed
            title = "🟢 VPS Deployment Successful" if is_success else "🔴 VPS Deployment Failed"
            color = 3066993 if is_success else 15158332 # Green or Red
            
            embed = {
                "title": title,
                "description": f"Status update for container: `{container_name}`",
                "color": color,
                "fields": [
                    {"name": "Container Name", "value": f"`{container_name}`", "inline": True},
                    {"name": "Status", "value": f"`{status_text}`", "inline": True},
                    {"name": "Details / Error", "value": str(details_or_error), "inline": False}
                ],
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                "footer": {
                    "text": "MintyHost Automated Deployments"
                }
            }

            # 3. Send message with embed and a ping in the content
            msg_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            msg_data = json.dumps({
                "content": f"⚡ <@ {discord_user_id}> - VPS deployment status update:",
                "embeds": [embed]
            }).replace("<@ ", "<@").encode("utf-8")

            msg_req = urllib.request.Request(msg_url, data=msg_data, headers=headers, method="POST")
            with urllib.request.urlopen(msg_req, timeout=5) as msg_resp:
                return msg_resp.status in (200, 201)
    except Exception as e:
        print(f"[ERROR] Failed to send VPS deployment status alert to user {discord_user_id}: {e}")
        return False

def trigger_vps_deploy_status_alert(container_name, status_text, is_success, details_or_error):
    """Fetches the configured discord_notify_user_id from settings and sends a deployment alert in a background thread."""
    import threading
    discord_user_id = get_config_setting('discord_notify_user_id')
    if discord_user_id:
        threading.Thread(
            target=send_vps_deploy_status_alert,
            args=(discord_user_id, container_name, status_text, is_success, details_or_error)
        ).start()

