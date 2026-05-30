import os
import sqlite3
import urllib.request
import urllib.parse
import json
import discord
from discord import app_commands
from discord.ext import commands

# SQLite Database for storing Discord User ID -> Panel API Key
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_users.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discord_users (
            discord_id INTEGER PRIMARY KEY,
            api_key TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_user_key(discord_id: int, api_key: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO discord_users (discord_id, api_key)
        VALUES (?, ?)
    """, (discord_id, api_key))
    conn.commit()
    conn.close()

def get_user_key(discord_id: int) -> str:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT api_key FROM discord_users WHERE discord_id = ?", (discord_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

# Load Environment Variables / Defaults
PANEL_URL = os.getenv("PANEL_URL", "http://127.0.0.1:5000").rstrip("/")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Dynamic Branding Loader
def get_branding():
    """Fetches public branding settings from the panel to theme the bot dynamically."""
    try:
        url = f"{PANEL_URL}/api/v1/settings/public"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            # Convert HEX color to discord.Color
            hex_color = data.get("color_primary", "#6367FF").lstrip("#")
            color_int = int(hex_color, 16) if len(hex_color) == 6 else 0x6367FF
            return {
                "site_name": data.get("site_name", "MintyHost LXC"),
                "color": discord.Color(color_int),
                "logo_url": data.get("logo_url")
            }
    except Exception:
        return {
            "site_name": "MintyHost LXC",
            "color": discord.Color.blue(),
            "logo_url": None
        }

# API Call Helper
def make_api_request(api_key: str, endpoint: str, method: str = "GET", data: dict = None):
    url = f"{PANEL_URL}/api/v1{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        try:
            err_data = e.read().decode("utf-8")
            err_json = json.loads(err_data)
            return err_json, e.code
        except Exception:
            return {"message": f"HTTP Error {e.code}: {e.reason}"}, e.code
    except Exception as e:
        return {"message": f"Connection error: {str(e)}"}, 500


# Discord Bot setup
class VPSBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Sync slash commands with Discord
        await self.tree.sync()

bot = VPSBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("Discord Bot is ready for slash commands!")
    init_db()


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup", description="Connect your control panel account using your API key.")
@app_commands.describe(api_key="Your 64-character API Key generated in the dashboard.")
async def setup(interaction: discord.Interaction, api_key: str):
    # Enforce ephemeral for API keys safety
    await interaction.response.defer(ephemeral=True)
    
    api_key = api_key.strip()
    if len(api_key) != 64:
        await interaction.followup.send("❌ Invalid API Key format. It should be a 64-character hex string.", ephemeral=True)
        return

    # Verify key by calling profile endpoint
    res, status = make_api_request(api_key, "/profile")
    if status == 200:
        save_user_key(interaction.user.id, api_key)
        branding = get_branding()
        embed = discord.Embed(
            title="✅ Account Linked Successfully!",
            description=f"Hey **{res.get('username')}**, your Discord account is now linked to **{branding['site_name']}**.",
            color=discord.Color.green()
        )
        embed.add_field(name="Username", value=res.get("username"), inline=True)
        embed.add_field(name="Email", value=res.get("email"), inline=True)
        embed.add_field(name="Role", value=res.get("role").upper(), inline=True)
        embed.set_footer(text=f"{branding['site_name']} REST Bot Integration")
        if branding["logo_url"]:
            embed.set_thumbnail(url=branding["logo_url"])
            
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("❌ Verification failed. Please make sure the API key is active and correct.", ephemeral=True)


# Helper function to check if user is linked
async def ensure_linked(interaction: discord.Interaction) -> str:
    key = get_user_key(interaction.user.id)
    if not key:
        branding = get_branding()
        embed = discord.Embed(
            title="🔒 API Authentication Required",
            description=f"You need to link your control panel account before you can manage your servers.\n\n"
                        f"1. Log into **{branding['site_name']}**\n"
                        f"2. Navigate to **API Keys** tab\n"
                        f"3. Generate a new API Key\n"
                        f"4. Run `/setup <your_api_key>` in this server.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"{branding['site_name']} Control Panel API")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return None
    return key


@bot.tree.command(name="profile", description="View your linked control panel user profile details.")
async def profile(interaction: discord.Interaction):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, "/profile")
    
    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"👤 User Profile — {res.get('username')}",
            color=branding["color"]
        )
        embed.add_field(name="Account Username", value=res.get("username"), inline=True)
        embed.add_field(name="Email Address", value=res.get("email"), inline=True)
        embed.add_field(name="Account Role", value=res.get("role").upper(), inline=True)
        
        pfp = res.get("pfp")
        if pfp:
            embed.set_thumbnail(url=pfp)
        elif branding["logo_url"]:
            embed.set_thumbnail(url=branding["logo_url"])

        embed.set_footer(text=f"Request sent by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Failed to load profile: {res.get('message', 'Unknown Error')}")


# Group command for VPS
vps_group = app_commands.Group(name="vps", description="Manage your LXC Virtual Private Servers")

@vps_group.command(name="list", description="List all LXC container instances assigned to your account.")
async def list_vps(interaction: discord.Interaction):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, "/vps")

    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"🖥️ My Virtual Private Servers ({len(res)})",
            description="Manage your LXC containers using `/vps action` or `/vps info`.",
            color=branding["color"]
        )

        for v in res:
            status_emoji = "🟢" if v.get("status") == "running" else "🔴" if v.get("status") == "stopped" else "🟡"
            ip_val = v.get("ip_address") if v.get("ip_address") else "Assigning..."
            relay_info = ""
            if v.get("status") == "running" and v.get("tunnel_url"):
                relay_info = f"\n🔗 Relay URL: `{v.get('tunnel_url')}`"

            embed.add_field(
                name=f"{status_emoji} {v.get('name')} (ID: {v.get('id')})",
                value=f"🏷️ Container Name: `{v.get('container_name')}`\n"
                      f"📟 OS: `{v.get('os')}`\n"
                      f"⚡ Spec: `{v.get('cpu')} Cores / {v.get('ram')} / {v.get('disk')}`\n"
                      f"🌐 IPv4: `{ip_val}`{relay_info}",
                inline=False
            )

        embed.set_footer(text=f"{branding['site_name']} Infrastructure Services", icon_url=branding["logo_url"])
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Failed to fetch instances: {res.get('message', 'Unknown Error')}")


@vps_group.command(name="info", description="Get comprehensive specifications and status for a single VPS.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.")
async def vps_info(interaction: discord.Interaction, vps_id: int):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    v_details, status = make_api_request(api_key, f"/vps/{vps_id}")
    if status != 200:
        await interaction.followup.send(f"❌ VPS not found or access denied: {v_details.get('message')}")
        return

    stats, _ = make_api_request(api_key, f"/vps/{vps_id}/stats")
    branding = get_branding()

    status_emoji = "🟢 RUNNING" if v_details.get("status") == "running" else "🔴 STOPPED" if v_details.get("status") == "stopped" else "🟡 SUSPENDED"
    embed = discord.Embed(
        title=f"🖥️ VPS Details — {v_details.get('name')}",
        color=branding["color"]
    )
    embed.add_field(name="Server ID", value=f"`{vps_id}`", inline=True)
    embed.add_field(name="Container Name", value=f"`{v_details.get('container_name')}`", inline=True)
    embed.add_field(name="Current Status", value=f"**{status_emoji}**", inline=True)

    embed.add_field(name="Operating System", value=f"`{v_details.get('os')}`", inline=True)
    embed.add_field(name="Local IPv4 IP", value=f"`{v_details.get('ip_address') or 'N/A'}`", inline=True)
    embed.add_field(name="Relay Port", value=f"`{v_details.get('tunnel_port') or 'N/A'}`", inline=True)

    if v_details.get("status") == "running" and v_details.get("tunnel_url"):
        embed.add_field(name="SSH / Web Relay URL", value=f"[`{v_details.get('tunnel_url')}`]({v_details.get('tunnel_url')})", inline=False)

    # Add Stats if running
    if v_details.get("status") == "running" and stats:
        cpu_usage = stats.get("cpu_percent", 0.0)
        ram_usage = stats.get("ram_percent", 0.0)
        disk_usage = stats.get("disk_percent", 0.0)
        embed.add_field(
            name="📊 Live Resource Utilization",
            value=f"⚡ **CPU Core Load:** `{cpu_usage}%` / `{v_details.get('cpu')} Cores`\n"
                  f"🧠 **Memory Load:** `{ram_usage}%` / `{v_details.get('ram')}`\n"
                  f"💾 **Storage Space:** `{disk_usage}%` / `{v_details.get('disk')}`",
            inline=False
        )
    else:
        embed.add_field(
            name="📊 Resource Specifications",
            value=f"⚡ **CPU Cores:** `{v_details.get('cpu')} Cores`\n"
                  f"🧠 **Allocated RAM:** `{v_details.get('ram')}`\n"
                  f"💾 **Allocated Storage:** `{v_details.get('disk')}`",
            inline=False
        )

    embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=embed)


@vps_group.command(name="action", description="Trigger power cycle actions (start, stop, restart) on your server.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.", action="Choose start, stop, or restart.")
@app_commands.choices(action=[
    app_commands.Choice(name="Start Instance", value="start"),
    app_commands.Choice(name="Stop Instance", value="stop"),
    app_commands.Choice(name="Reboot Instance", value="restart")
])
async def vps_action(interaction: discord.Interaction, vps_id: int, action: app_commands.Choice[str]):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    action_val = action.value
    res, status = make_api_request(api_key, f"/vps/{vps_id}/action", method="POST", data={"action": action_val})

    if status == 200:
        await interaction.followup.send(f"✅ Power Action Initiated: `{action.name}` on VPS ID `{vps_id}`. Status is changing to `{res.get('new_status')}`.")
    else:
        await interaction.followup.send(f"❌ Action failed: {res.get('message', 'Access Denied')}")


@vps_group.command(name="password", description="Change root login credentials for the container.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.", password="New root password (minimum 6 characters).")
async def vps_password(interaction: discord.Interaction, vps_id: int, password: str):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    # Defer ephemerally because passwords must be invisible
    await interaction.response.defer(ephemeral=True)
    
    if len(password.strip()) < 6:
        await interaction.followup.send("❌ Password must be at least 6 characters long.", ephemeral=True)
        return

    res, status = make_api_request(api_key, f"/vps/{vps_id}/password", method="POST", data={"password": password.strip()})

    if status == 200:
        await interaction.followup.send(f"✅ Root credentials updated successfully inside VPS ID `{vps_id}`.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Password update failed: {res.get('message')}", ephemeral=True)


@vps_group.command(name="reinstall", description="Format and rebuild your VPS with a fresh Linux distribution.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.", os="The Linux OS template to install.", root_password="New root credential.")
@app_commands.choices(os=[
    app_commands.Choice(name="Ubuntu 22.04 LTS (Jammy Jellyfish)", value="ubuntu/22.04"),
    app_commands.Choice(name="Ubuntu 24.04 LTS (Noble Numbat)", value="ubuntu/24.04"),
    app_commands.Choice(name="Debian 11 (Bullseye)", value="debian/11"),
    app_commands.Choice(name="Debian 12 (Bookworm)", value="debian/12"),
    app_commands.Choice(name="CentOS 9 Stream", value="centos/9-stream"),
    app_commands.Choice(name="Alpine Linux 3.18 (Ultra-lightweight)", value="alpine/3.18")
])
async def vps_reinstall(interaction: discord.Interaction, vps_id: int, os: app_commands.Choice[str], root_password: str):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    # Defer ephemerally for security
    await interaction.response.defer(ephemeral=True)
    
    if len(root_password.strip()) < 6:
        await interaction.followup.send("❌ Root password must be at least 6 characters.", ephemeral=True)
        return

    res, status = make_api_request(api_key, f"/vps/{vps_id}/reinstall", method="POST", data={
        "os": os.value,
        "password": root_password.strip()
    })

    if status == 200:
        await interaction.followup.send(f"🚀 Reinstall triggered! VPS ID `{vps_id}` is formatting and installing `{os.name}`. Wait about 30 seconds for it to provision.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ OS Reinstall failed: {res.get('message')}", ephemeral=True)


# Group command for Snapshots
snap_group = app_commands.Group(name="snapshot", description="Manage VPS snapshots and restore states")

@snap_group.command(name="list", description="List all on-demand container snapshots for a VPS.")
@app_commands.describe(vps_id="Server ID")
async def list_snaps(interaction: discord.Interaction, vps_id: int):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/snapshots")

    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"📸 On-Demand Snapshots — VPS ID {vps_id} ({len(res)})",
            color=branding["color"]
        )
        if not res:
            embed.description = "No snapshots found for this container. Create one using `/snapshot create`!"
        else:
            for s in res:
                embed.add_field(
                    name=f"💾 Snapshot: {s.get('name')}",
                    value=f"⏰ Created: `{s.get('created_at')}`",
                    inline=False
                )
        embed.set_footer(text=branding["site_name"])
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Failed to fetch snapshots: {res.get('message')}")


@snap_group.command(name="create", description="Take an instant hot-snapshot backup of your container.")
@app_commands.describe(vps_id="Server ID", name="Custom name for the snapshot (letters/numbers/dashes).")
async def create_snap(interaction: discord.Interaction, vps_id: int, name: str):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/snapshots", method="POST", data={"name": name.strip()})

    if status == 201:
        await interaction.followup.send(f"📸 Success! Created container snapshot `{res.get('name')}` for VPS ID `{vps_id}`.")
    else:
        await interaction.followup.send(f"❌ Failed to create snapshot: {res.get('message')}")


@snap_group.command(name="restore", description="Rollback your server's disk state to an existing snapshot.")
@app_commands.describe(vps_id="Server ID", name="Name of the snapshot to restore.")
async def restore_snap(interaction: discord.Interaction, vps_id: int, name: str):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/snapshots/restore", method="POST", data={"name": name.strip()})

    if status == 200:
        await interaction.followup.send(f"✅ Rolled back: VPS ID `{vps_id}` disk state successfully restored to snapshot `{name}`.")
    else:
        await interaction.followup.send(f"❌ Failed to restore snapshot: {res.get('message')}")


@snap_group.command(name="delete", description="Permanently delete a snapshot to free hypervisor space.")
@app_commands.describe(vps_id="Server ID", name="Name of the snapshot to destroy.")
async def delete_snap(interaction: discord.Interaction, vps_id: int, name: str):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/snapshots/{name}", method="DELETE")

    if status == 200:
        await interaction.followup.send(f"🗑️ Snapshot `{name}` successfully deleted from VPS ID `{vps_id}`.")
    else:
        await interaction.followup.send(f"❌ Failed to delete snapshot: {res.get('message')}")


# Group command for Backups
backup_group = app_commands.Group(name="backup", description="Manage and create container backup archives")

@backup_group.command(name="list", description="List compressed tarball backups ready for export/download.")
@app_commands.describe(vps_id="Server ID")
async def list_backups(interaction: discord.Interaction, vps_id: int):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/backups")

    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"🗄️ Full Backups — VPS ID {vps_id} ({len(res)})",
            color=branding["color"]
        )
        if not res:
            embed.description = "No backups found. Trigger a complete container export using `/backup create`!"
        else:
            for b in res:
                embed.add_field(
                    name=f"📦 {b.get('filename')}",
                    value=f"💾 Size: `{b.get('size')}`\n⏰ Created: `{b.get('created_at')}`",
                    inline=False
                )
        embed.set_footer(text=branding["site_name"])
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Failed to load backups: {res.get('message')}")


@backup_group.command(name="create", description="Compile and compress a full tarball backup export of your VPS.")
@app_commands.describe(vps_id="Server ID")
async def create_backup(interaction: discord.Interaction, vps_id: int):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/backups", method="POST")

    if status == 201:
        await interaction.followup.send(f"✅ Success! Backed up container. Created archive `{res.get('filename')}`.")
    else:
        await interaction.followup.send(f"❌ Backup generation failed: {res.get('message')}")


# Group command for Firewall Rules
fw_group = app_commands.Group(name="firewall", description="Manage VPS port-level access firewall rules")

@fw_group.command(name="list", description="List all traffic access rules configured for a VPS.")
@app_commands.describe(vps_id="Server ID")
async def list_fw(interaction: discord.Interaction, vps_id: int):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/firewall")

    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"🛡️ Firewall Rules — VPS ID {vps_id} ({len(res)})",
            color=branding["color"]
        )
        if not res:
            embed.description = "No custom rules. Default state: ALL traffic is allowed."
        else:
            for r in res:
                rule_action = "🟢 ALLOW" if r.get("action") == "ALLOW" else "🔴 DENY"
                port_str = f"Port {r.get('port')}" if r.get("protocol") != "ICMP" else "All Ports"
                embed.add_field(
                    name=f"Rule ID: {r.get('id')}",
                    value=f"🛠️ Protocol: `{r.get('protocol')}` | {port_str}\n"
                          f"📣 Action: **{rule_action}**",
                    inline=True
                )
        embed.set_footer(text=branding["site_name"])
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Failed to fetch firewall rules: {res.get('message')}")


@fw_group.command(name="add", description="Add a new network access control rule.")
@app_commands.describe(vps_id="Server ID", protocol="Choose TCP, UDP, or ICMP.", port="Port number 0-65535 (ignored for ICMP).", action="ALLOW or DENY")
@app_commands.choices(protocol=[
    app_commands.Choice(name="TCP", value="TCP"),
    app_commands.Choice(name="UDP", value="UDP"),
    app_commands.Choice(name="ICMP (Ping)", value="ICMP")
], action=[
    app_commands.Choice(name="ALLOW (Green-light)", value="ALLOW"),
    app_commands.Choice(name="DENY (Block-list)", value="DENY")
])
async def add_fw(interaction: discord.Interaction, vps_id: int, protocol: app_commands.Choice[str], port: int, action: app_commands.Choice[str]):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    
    port_val = port
    if protocol.value == "ICMP":
        port_val = 0

    if port_val < 0 or port_val > 65535:
        await interaction.followup.send("❌ Port must be between 0 and 65535.")
        return

    res, status = make_api_request(api_key, f"/vps/{vps_id}/firewall", method="POST", data={
        "protocol": protocol.value,
        "port": port_val,
        "action": action.value
    })

    if status == 201:
        await interaction.followup.send(f"🛡️ Firewall rule successfully created (Rule ID `{res.get('id')}`). configured `{protocol.value}/{port_val}` as `{action.value}`.")
    else:
        await interaction.followup.send(f"❌ Failed to add rule: {res.get('message')}")


@fw_group.command(name="delete", description="Revoke/delete an existing firewall rule.")
@app_commands.describe(vps_id="Server ID", rule_id="The unique ID of the rule.")
async def delete_fw(interaction: discord.Interaction, vps_id: int, rule_id: int):
    api_key = await ensure_linked(interaction)
    if not api_key:
        return

    await interaction.response.defer()
    res, status = make_api_request(api_key, f"/vps/{vps_id}/firewall/{rule_id}", method="DELETE")

    if status == 200:
        await interaction.followup.send(f"🛡️ Firewall Rule `{rule_id}` successfully deleted from VPS ID `{vps_id}`.")
    else:
        await interaction.followup.send(f"❌ Failed to delete rule: {res.get('message')}")


# Register Groups to Bot Tree
bot.tree.add_command(vps_group)
bot.tree.add_command(snap_group)
bot.tree.add_command(backup_group)
bot.tree.add_command(fw_group)


# Help Command
@bot.tree.command(name="help", description="Get instructions on how to use the VPS Bot.")
async def help_cmd(interaction: discord.Interaction):
    branding = get_branding()
    embed = discord.Embed(
        title=f"📖 {branding['site_name']} Bot Help Guide",
        description="Follow these commands to manage your LXC virtual servers directly from Discord.",
        color=branding["color"]
    )
    
    embed.add_field(
        name="🔑 Initial Connection Setup",
        value="`/setup <your_api_key>` — Securely link your Discord account with your control panel API credentials. (Response is completely private/hidden)",
        inline=False
    )
    embed.add_field(
        name="👤 Profile & Identity",
        value="`/profile` — Display your active panel account profile details.",
        inline=False
    )
    embed.add_field(
        name="🖥️ VPS Power & OS Commands",
        value="`/vps list` — List all containers assigned to you.\n"
              "`/vps info <vps_id>` — Live CPU/RAM/Disk stats, OS, IP address, SSH tunnel, etc.\n"
              "`/vps action <vps_id> <action>` — Trigger **start / stop / restart**.\n"
              "`/vps password <vps_id> <new_password>` — Re-set container root login.\n"
              "`/vps reinstall <vps_id> <os>` — Format container OS distributions.",
        inline=False
    )
    embed.add_field(
        name="📸 Container Hot-Snapshots",
        value="`/snapshot list <vps_id>` — List on-demand container disk snapshots.\n"
              "`/snapshot create <vps_id> <name>` — Take an instant hot-snapshot state.\n"
              "`/snapshot restore <vps_id> <name>` — Rollback container disk contents.\n"
              "`/snapshot delete <vps_id> <name>` — Delete a snapshot.",
        inline=False
    )
    embed.add_field(
        name="🗄️ Compressed Backups",
        value="`/backup list <vps_id>` — View list of backup archives.\n"
              "`/backup create <vps_id>` — Export container as a compressed tarball.",
        inline=False
    )
    embed.add_field(
        name="🛡️ Port Access Firewall",
        value="`/firewall list <vps_id>` — View port blocking rules.\n"
              "`/firewall add <vps_id> <protocol> <port> <action>` — Create a new ALLOW/DENY rule.\n"
              "`/firewall delete <vps_id> <rule_id>` — Remove a rule.",
        inline=False
    )

    embed.set_footer(text=f"{branding['site_name']} REST API Bot Integrations", icon_url=branding["logo_url"])
    await interaction.response.send_message(embed=embed)


# Start Bot
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN environment variable not set in .env")
    else:
        bot.run(BOT_TOKEN)
