import os
import sqlite3
import urllib.request
import urllib.parse
import json
import discord
from discord import app_commands
from discord.ext import commands

# SQLite Database for storing Discord User ID -> Panel account link details
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_users.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Check if table has old schema and recreate if needed
    try:
        cursor.execute("SELECT panel_user_id FROM discord_users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("DROP TABLE IF EXISTS discord_users")
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discord_users (
            discord_id INTEGER PRIMARY KEY,
            panel_user_id INTEGER NOT NULL,
            panel_username TEXT NOT NULL,
            panel_role TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_user_link(discord_id: int, user_id: int, username: str, role: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO discord_users (discord_id, panel_user_id, panel_username, panel_role)
        VALUES (?, ?, ?, ?)
    """, (discord_id, user_id, username, role))
    conn.commit()
    conn.close()

def get_linked_user(discord_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT panel_user_id, panel_username, panel_role FROM discord_users WHERE discord_id = ?", (discord_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "role": row[2]}
    return None

def remove_user_link(discord_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM discord_users WHERE discord_id = ?", (discord_id,))
    conn.commit()
    conn.close()

# Load Environment Variables / Defaults
from dotenv import load_dotenv
load_dotenv()

PANEL_URL = os.getenv("PANEL_URL", "http://127.0.0.1:5000").rstrip("/")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
PANEL_API_KEY = os.getenv("PANEL_API_KEY")

try:
    ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
except (ValueError, TypeError):
    ADMIN_ROLE_ID = 0

# Helper to check if a Discord user is an administrator
def is_discord_admin(interaction: discord.Interaction) -> bool:
    if not ADMIN_ROLE_ID:
        return False
    member = interaction.user
    if isinstance(member, discord.Member):
        return any(role.id == ADMIN_ROLE_ID for role in member.roles)
    return False

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
            
            logo_url = data.get("logo_url")
            if logo_url and not logo_url.startswith(("http://", "https://")):
                logo_url = f"{PANEL_URL}/{logo_url.lstrip('/')}"
            
            return {
                "site_name": data.get("site_name", "MintyHost LXC"),
                "color": discord.Color(color_int),
                "logo_url": logo_url if logo_url else None
            }
    except Exception:
        return {
            "site_name": "MintyHost LXC",
            "color": discord.Color.blue(),
            "logo_url": None
        }

# API Call Helper using Global Admin Key
def make_api_request(endpoint: str, method: str = "GET", data: dict = None):
    url = f"{PANEL_URL}/api/v1{endpoint}"
    headers = {
        "Authorization": f"Bearer {PANEL_API_KEY}",
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


# Helper function to check if user is linked
async def ensure_linked(interaction: discord.Interaction) -> dict:
    linked = get_linked_user(interaction.user.id)
    if not linked:
        if is_discord_admin(interaction):
            return {"user_id": 0, "username": "admin", "role": "admin"}
        branding = get_branding()
        embed = discord.Embed(
            title="🔒 Account Connection Required",
            description=f"You need to link your control panel account before you can manage your servers.\n\n"
                        f"1. Run `/link <username> <password>` to connect your profile.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"{branding['site_name']} Control Panel API")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return None
    return linked

# Helper to verify VPS ownership
async def check_vps_ownership(interaction: discord.Interaction, vps_id: int, linked: dict) -> bool:
    if is_discord_admin(interaction):
        return True
    if not linked:
        return False
    v_details, status = make_api_request(f"/vps/{vps_id}")
    if status == 200:
        return v_details.get("user_id") == linked["user_id"]
    return False


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="link", description="Link your Discord account to your control panel username.")
@app_commands.describe(username="Your control panel username.", password="Your control panel password.")
async def link_account(interaction: discord.Interaction, username: str, password: str):
    await interaction.response.defer(ephemeral=True)
    
    # Call verify credentials endpoint using global admin key
    res, status = make_api_request("/admin/users/verify", method="POST", data={
        "username": username.strip(),
        "password": password
    })
    
    if status == 200 and res.get("valid"):
        user_info = res.get("user")
        save_user_link(interaction.user.id, user_info["id"], username.strip(), user_info["role"])
        branding = get_branding()
        
        embed = discord.Embed(
            title="✅ Account Linked Successfully!",
            description=f"Hey **{username}**, your Discord account is now linked to **{branding['site_name']}**.",
            color=discord.Color.green()
        )
        embed.add_field(name="Username", value=username, inline=True)
        embed.add_field(name="Role", value=user_info["role"].upper(), inline=True)
        embed.set_footer(text=f"{branding['site_name']} REST Bot Integration")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("❌ Link failed. Invalid username or password.", ephemeral=True)


@bot.tree.command(name="unlink", description="Disconnect your control panel account from Discord.")
async def unlink_account(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    remove_user_link(interaction.user.id)
    await interaction.followup.send("✅ Successfully unlinked your control panel account.", ephemeral=True)


@bot.tree.command(name="profile", description="View your linked control panel user profile details.")
async def profile(interaction: discord.Interaction):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    res, status = make_api_request("/admin/users")
    if status == 200:
        user = next((u for u in res if u["id"] == linked["user_id"]), None)
        if user:
            branding = get_branding()
            embed = discord.Embed(
                title=f"👤 User Profile — {user.get('username')}",
                color=branding["color"]
            )
            embed.add_field(name="Account Username", value=user.get("username"), inline=True)
            embed.add_field(name="Email Address", value=user.get("email"), inline=True)
            embed.add_field(name="Account Role", value=user.get("role").upper(), inline=True)
            embed.set_footer(text=f"Request sent by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
            await interaction.followup.send(embed=embed)
            return
            
    await interaction.followup.send("❌ Failed to load profile details.")


# Group command for VPS
vps_group = app_commands.Group(name="vps", description="Manage your LXC Virtual Private Servers")

@vps_group.command(name="list", description="List all LXC container instances assigned to your account.")
async def list_vps(interaction: discord.Interaction):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    res, status = make_api_request("/admin/vps")

    if status == 200:
        branding = get_branding()
        user_vps = [v for v in res if v.get("user_id") == linked["user_id"]]
        
        embed = discord.Embed(
            title=f"🖥️ My Virtual Private Servers ({len(user_vps)})",
            description="Manage your LXC containers using `/vps action` or `/vps info`.",
            color=branding["color"]
        )

        for v in user_vps:
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

        logo = branding.get("logo_url")
        if logo and logo.startswith(("http://", "https://")):
            embed.set_footer(text=f"{branding['site_name']} Infrastructure Services", icon_url=logo)
        else:
            embed.set_footer(text=f"{branding['site_name']} Infrastructure Services")
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("❌ Failed to fetch instances.")


@vps_group.command(name="info", description="Get comprehensive specifications and status for a single VPS.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.")
async def vps_info(interaction: discord.Interaction, vps_id: int):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    v_details, status = make_api_request(f"/vps/{vps_id}")
    if status != 200:
        await interaction.followup.send("❌ VPS details could not be retrieved.")
        return

    stats, _ = make_api_request(f"/vps/{vps_id}/stats")
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
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    action_val = action.value
    res, status = make_api_request(f"/vps/{vps_id}/action", method="POST", data={"action": action_val})

    if status == 200:
        await interaction.followup.send(f"✅ Power Action Initiated: `{action.name}` on VPS ID `{vps_id}`. Status is changing to `{res.get('new_status')}`.")
    else:
        await interaction.followup.send(f"❌ Action failed: {res.get('message', 'Access Denied')}")


@vps_group.command(name="password", description="Change root login credentials for the container.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.", password="New root password (minimum 6 characters).")
async def vps_password(interaction: discord.Interaction, vps_id: int, password: str):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer(ephemeral=True)
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.", ephemeral=True)
        return

    if len(password.strip()) < 6:
        await interaction.followup.send("❌ Password must be at least 6 characters long.", ephemeral=True)
        return

    res, status = make_api_request(f"/vps/{vps_id}/password", method="POST", data={"password": password.strip()})

    if status == 200:
        await interaction.followup.send(f"✅ Root credentials updated successfully inside VPS ID `{vps_id}`.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Password update failed: {res.get('message')}", ephemeral=True)


@vps_group.command(name="reinstall", description="Format and rebuild your VPS with a fresh Linux distribution.")
@app_commands.describe(vps_id="The unique numerical ID of your VPS.", os="The Linux OS template to install.", root_password="New root credential.")
@app_commands.choices(os=[
    app_commands.Choice(name="Ubuntu 22.04 LTS", value="ubuntu/22.04"),
    app_commands.Choice(name="Ubuntu 24.04 LTS", value="ubuntu/24.04"),
    app_commands.Choice(name="Debian 11", value="debian/11"),
    app_commands.Choice(name="Debian 12", value="debian/12"),
    app_commands.Choice(name="CentOS 9 Stream", value="centos/9-stream"),
    app_commands.Choice(name="Alpine Linux 3.18", value="alpine/3.18")
])
async def vps_reinstall(interaction: discord.Interaction, vps_id: int, os: app_commands.Choice[str], root_password: str):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer(ephemeral=True)
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.", ephemeral=True)
        return

    if len(root_password.strip()) < 6:
        await interaction.followup.send("❌ Root password must be at least 6 characters.", ephemeral=True)
        return

    res, status = make_api_request(f"/vps/{vps_id}/reinstall", method="POST", data={
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
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/snapshots")

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
        await interaction.followup.send(f"❌ Failed to fetch snapshots.")


@snap_group.command(name="create", description="Take an instant hot-snapshot backup of your container.")
@app_commands.describe(vps_id="Server ID", name="Custom name for the snapshot.")
async def create_snap(interaction: discord.Interaction, vps_id: int, name: str):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/snapshots", method="POST", data={"name": name.strip()})

    if status == 201:
        await interaction.followup.send(f"📸 Success! Created container snapshot `{res.get('name')}` for VPS ID `{vps_id}`.")
    else:
        await interaction.followup.send(f"❌ Failed to create snapshot: {res.get('message')}")


@snap_group.command(name="restore", description="Rollback your server's disk state to an existing snapshot.")
@app_commands.describe(vps_id="Server ID", name="Name of the snapshot to restore.")
async def restore_snap(interaction: discord.Interaction, vps_id: int, name: str):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/snapshots/restore", method="POST", data={"name": name.strip()})

    if status == 200:
        await interaction.followup.send(f"✅ Rolled back: VPS ID `{vps_id}` disk state successfully restored to snapshot `{name}`.")
    else:
        await interaction.followup.send(f"❌ Failed to restore snapshot: {res.get('message')}")


@snap_group.command(name="delete", description="Permanently delete a snapshot to free hypervisor space.")
@app_commands.describe(vps_id="Server ID", name="Name of the snapshot to destroy.")
async def delete_snap(interaction: discord.Interaction, vps_id: int, name: str):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/snapshots/{name}", method="DELETE")

    if status == 200:
        await interaction.followup.send(f"🗑️ Snapshot `{name}` successfully deleted from VPS ID `{vps_id}`.")
    else:
        await interaction.followup.send(f"❌ Failed to delete snapshot: {res.get('message')}")


# Group command for Backups
backup_group = app_commands.Group(name="backup", description="Manage and create container backup archives")

@backup_group.command(name="list", description="List compressed tarball backups ready for export/download.")
@app_commands.describe(vps_id="Server ID")
async def list_backups(interaction: discord.Interaction, vps_id: int):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/backups")

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
        await interaction.followup.send(f"❌ Failed to load backups.")


@backup_group.command(name="create", description="Compile and compress a full tarball backup export of your VPS.")
@app_commands.describe(vps_id="Server ID")
async def create_backup(interaction: discord.Interaction, vps_id: int):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/backups", method="POST")

    if status == 201:
        await interaction.followup.send(f"✅ Success! Backed up container. Created archive `{res.get('filename')}`.")
    else:
        await interaction.followup.send(f"❌ Backup generation failed: {res.get('message')}")


# Group command for Firewall Rules
fw_group = app_commands.Group(name="firewall", description="Manage VPS port-level access firewall rules")

@fw_group.command(name="list", description="List all traffic access rules configured for a VPS.")
@app_commands.describe(vps_id="Server ID")
async def list_fw(interaction: discord.Interaction, vps_id: int):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/firewall")

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
        await interaction.followup.send("❌ Failed to fetch firewall rules.")


@fw_group.command(name="add", description="Add a new network access control rule.")
@app_commands.describe(vps_id="Server ID", protocol="Choose TCP, UDP, or ICMP.", port="Port number (ignored for ICMP).", action="ALLOW or DENY")
@app_commands.choices(protocol=[
    app_commands.Choice(name="TCP", value="TCP"),
    app_commands.Choice(name="UDP", value="UDP"),
    app_commands.Choice(name="ICMP (Ping)", value="ICMP")
], action=[
    app_commands.Choice(name="ALLOW", value="ALLOW"),
    app_commands.Choice(name="DENY", value="DENY")
])
async def add_fw(interaction: discord.Interaction, vps_id: int, protocol: app_commands.Choice[str], port: int, action: app_commands.Choice[str]):
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return
    
    port_val = port
    if protocol.value == "ICMP":
        port_val = 0

    if port_val < 0 or port_val > 65535:
        await interaction.followup.send("❌ Port must be between 0 and 65535.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/firewall", method="POST", data={
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
    linked = await ensure_linked(interaction)
    if not linked:
        return

    await interaction.response.defer()
    if not await check_vps_ownership(interaction, vps_id, linked):
        await interaction.followup.send("❌ VPS not found or access denied.")
        return

    res, status = make_api_request(f"/vps/{vps_id}/firewall/{rule_id}", method="DELETE")

    if status == 200:
        await interaction.followup.send(f"🛡️ Firewall Rule `{rule_id}` successfully deleted from VPS ID `{vps_id}`.")
    else:
        await interaction.followup.send(f"❌ Failed to delete rule: {res.get('message')}")


# ─────────────────────────────────────────────────────────────────────────────
# ADMINISTRATOR COMMAND TREE (Restricted by Discord ADMIN_ROLE_ID)
# ─────────────────────────────────────────────────────────────────────────────

admin_group = app_commands.Group(name="admin", description="Administrative control panel commands")
admin_vps_group = app_commands.Group(name="vps", parent=admin_group, description="Administrative VPS control")
admin_user_group = app_commands.Group(name="user", parent=admin_group, description="Administrative user account control")

@admin_group.command(name="stats", description="View global hypervisor cluster statistics.")
async def admin_stats_cmd(interaction: discord.Interaction):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request("/admin/stats")
    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"📊 Cluster Overview — {branding['site_name']}",
            color=branding["color"]
        )
        embed.add_field(name="Total Clients", value=f"`{res.get('clients')}`", inline=True)
        embed.add_field(name="Total VPS Instances", value=f"`{res.get('vps_count')}`", inline=True)
        embed.add_field(name="Total Active API Keys", value=f"`{res.get('total_api_keys')}`", inline=True)
        embed.add_field(name="Allocated CPU Cores", value=f"`{res.get('allocated_cpu')} Cores`", inline=True)
        embed.add_field(name="Allocated Memory", value=f"`{res.get('allocated_ram')} MB`", inline=True)
        embed.add_field(name="Hypervisor Mode", value=f"`{'MOCK' if res.get('is_mock') else 'PRODUCTION'}`", inline=True)
        embed.set_footer(text="MintyHost Cluster Management")
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("❌ Failed to fetch cluster stats.")


@admin_vps_group.command(name="list", description="List all VPS instances deployed on the panel.")
async def admin_list_vps(interaction: discord.Interaction):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request("/admin/vps")
    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title="🖥️ System VPS Instances (All Users)",
            color=branding["color"]
        )
        for v in res[:20]: # Limit to 20 to avoid embed overflow
            status_emoji = "🟢" if v.get("status") == "running" else "🔴" if v.get("status") == "stopped" else "🟡"
            embed.add_field(
                name=f"{status_emoji} {v.get('name')} (ID: {v.get('id')})",
                value=f"👤 Owner ID: `{v.get('user_id')}`\n"
                      f"⚡ Spec: `{v.get('cpu')} Cores / {v.get('ram')}MB / {v.get('disk')}GB`\n"
                      f"🌐 IP: `{v.get('ip_address') or 'N/A'}`",
                inline=False
            )
        if len(res) > 20:
            embed.description = f"*Showing top 20 of {len(res)} total servers.*"
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("❌ Failed to fetch system VPS list.")


@admin_vps_group.command(name="deploy", description="Provision and launch a new LXC container for a client.")
@app_commands.describe(
    name="Name of the server (letters/numbers/dashes).",
    user_id="The numerical ID of the owner user.",
    os="Choose OS template.",
    cpu="CPU cores to allocate.",
    ram="RAM size in MB.",
    disk="Disk space in GB.",
    root_password="Root SSH password."
)
@app_commands.choices(os=[
    app_commands.Choice(name="Ubuntu 22.04 LTS", value="ubuntu/22.04"),
    app_commands.Choice(name="Ubuntu 24.04 LTS", value="ubuntu/24.04"),
    app_commands.Choice(name="Debian 11", value="debian/11"),
    app_commands.Choice(name="Debian 12", value="debian/12"),
    app_commands.Choice(name="CentOS 9 Stream", value="centos/9-stream"),
    app_commands.Choice(name="Alpine Linux 3.18", value="alpine/3.18")
])
async def admin_deploy_vps(interaction: discord.Interaction, name: str, user_id: int, os: app_commands.Choice[str], cpu: int, ram: int, disk: int, root_password: str):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    res, status = make_api_request("/admin/vps", method="POST", data={
        "name": name.strip(),
        "user_id": user_id,
        "os": os.value,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "root_password": root_password.strip()
    })

    if status == 201:
        await interaction.followup.send(f"🚀 Deploy started successfully! Created container `{res['vps']['container_name']}` (ID `{res['vps']['id']}`) for User `{user_id}`.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Deploy failed: {res.get('message', 'Unknown error.')}", ephemeral=True)


@admin_vps_group.command(name="delete", description="Completely destroy and wipe a VPS container.")
@app_commands.describe(vps_id="Numerical ID of the VPS to destroy.")
async def admin_delete_vps(interaction: discord.Interaction, vps_id: int):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request(f"/admin/vps/{vps_id}", method="DELETE")
    if status == 200:
        await interaction.followup.send(f"🗑️ VPS ID `{vps_id}` successfully destroyed.")
    else:
        await interaction.followup.send(f"❌ Destroy failed: {res.get('message')}")


@admin_vps_group.command(name="suspend", description="Suspend or unsuspend a client VPS instance.")
@app_commands.describe(vps_id="VPS ID", suspend="Choose True to freeze container, False to resume container.")
async def admin_suspend_vps(interaction: discord.Interaction, vps_id: int, suspend: bool):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request(f"/admin/vps/{vps_id}/suspend", method="POST", data={"suspend": suspend})
    if status == 200:
        word = "suspended" if suspend else "unsuspended"
        await interaction.followup.send(f"✅ VPS ID `{vps_id}` is now {word}.")
    else:
        await interaction.followup.send(f"❌ Action failed: {res.get('message')}")


@admin_user_group.command(name="list", description="List all registered client user accounts.")
async def admin_list_users_cmd(interaction: discord.Interaction):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request("/admin/users")
    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title="👤 Registered Control Panel Accounts",
            color=branding["color"]
        )
        for u in res[:20]:
            role_badge = "🛡️ Admin" if u.get("role") == "admin" else "👤 Client"
            embed.add_field(
                name=f"{u.get('username')} (ID: {u.get('id')})",
                value=f"📧 Email: `{u.get('email')}`\n"
                      f"🔑 Role: **{role_badge}**\n"
                      f"🖥️ Total Servers: `{u.get('vps_count', 0)}`",
                inline=True
            )
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("❌ Failed to list users.")


@admin_user_group.command(name="create", description="Register a new client or administrator panel account.")
@app_commands.describe(username="Username", email="Email address", password="Initial password", role="Account privileges")
@app_commands.choices(role=[
    app_commands.Choice(name="Client (Default)", value="client"),
    app_commands.Choice(name="Administrator", value="admin")
])
async def admin_create_user_cmd(interaction: discord.Interaction, username: str, email: str, password: str, role: app_commands.Choice[str]):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    res, status = make_api_request("/admin/users", method="POST", data={
        "username": username.strip().lower(),
        "email": email.strip().lower(),
        "password": password,
        "role": role.value
    })
    if status == 201:
        await interaction.followup.send(f"✅ User `{username}` successfully created (ID `{res.get('id')}`).", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ User creation failed: {res.get('message')}", ephemeral=True)


@admin_user_group.command(name="delete", description="Permanently delete a user account from the system.")
@app_commands.describe(user_id="ID of the user to remove.")
async def admin_delete_user_cmd(interaction: discord.Interaction, user_id: int):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request(f"/admin/users/{user_id}", method="DELETE")
    if status == 200:
        await interaction.followup.send(f"🗑️ User ID `{user_id}` has been deleted.")
    else:
        await interaction.followup.send(f"❌ Deletion failed: {res.get('message')}")


@admin_user_group.command(name="suspend", description="Suspend or unsuspend a panel user account.")
@app_commands.describe(user_id="User ID", suspend="Choose True to suspend user, False to unsuspend user.")
async def admin_suspend_user_cmd(interaction: discord.Interaction, user_id: int, suspend: bool):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    res, status = make_api_request(f"/admin/users/{user_id}/suspend", method="POST", data={"suspend": suspend})
    if status == 200:
        word = "suspended" if suspend else "unsuspended"
        await interaction.followup.send(f"✅ User ID `{user_id}` is now {word}.")
    else:
        await interaction.followup.send(f"❌ Suspend action failed: {res.get('message')}")


@admin_group.command(name="logs", description="Inspect recent system and deploy audit logs.")
@app_commands.describe(limit="Number of logs to retrieve (max 50).")
async def admin_logs_cmd(interaction: discord.Interaction, limit: int = 15):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer()
    lim = min(max(limit, 1), 50)
    res, status = make_api_request(f"/admin/logs?limit={lim}")
    if status == 200:
        branding = get_branding()
        embed = discord.Embed(
            title=f"📋 System Audit Logs (Last {len(res)})",
            color=branding["color"]
        )
        logs_text = ""
        for l in res:
            logs_text += f"`[{l.get('timestamp')}]` **{l.get('username')}**: {l.get('action')}\n"
        
        embed.description = logs_text if logs_text else "No recent logs found."
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("❌ Failed to retrieve system logs.")


# Register Groups to Bot Tree
bot.tree.add_command(vps_group)
bot.tree.add_command(snap_group)
bot.tree.add_command(backup_group)
bot.tree.add_command(fw_group)
bot.tree.add_command(admin_group)


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
        name="🔗 Initial Connection Link",
        value="`/link <username> <password>` — Safely link your Discord account to your control panel username. (Response is completely private/hidden)\n"
              "`/unlink` — Disconnect your panel account from Discord.",
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

    if is_discord_admin(interaction):
        embed.add_field(
            name="🛡️ Administrator Commands",
            value="`/admin stats` — Global hypervisor statistics.\n"
                  "`/admin logs` — Inspect audit logs.\n"
                  "`/admin vps list` — List all deployed containers in the entire hosting panel.\n"
                  "`/admin vps deploy <name> <user_id> <os> <cpu> <ram> <disk> <password>` — Deploy new VPS.\n"
                  "`/admin vps delete <vps_id>` — Destroy a container.\n"
                  "`/admin vps suspend <vps_id> <suspend>` — Suspend/unsuspend a container.\n"
                  "`/admin user list` — List accounts.\n"
                  "`/admin user create <username> <email> <password> <role>` — Create accounts.\n"
                  "`/admin user delete <user_id>` — Delete user accounts.\n"
                  "`/admin user suspend <user_id> <suspend>` — Suspend user accounts.",
            inline=False
        )

    logo = branding.get("logo_url")
    if logo and logo.startswith(("http://", "https://")):
        embed.set_footer(text=f"{branding['site_name']} REST API Bot Integrations", icon_url=logo)
    else:
        embed.set_footer(text=f"{branding['site_name']} REST API Bot Integrations")
    await interaction.response.send_message(embed=embed)


# Start Bot
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN environment variable not set in .env")
    elif not PANEL_API_KEY:
        print("❌ Error: PANEL_API_KEY environment variable not set in .env")
    else:
        bot.run(BOT_TOKEN)
