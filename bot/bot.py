import os
import sqlite3
import urllib.request
import urllib.parse
import json
import string
import random
import datetime
import discord
from discord import app_commands
from discord.ext import commands

# SQLite Database for storing Discord User ID -> Panel account link details
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_users.db")
BOT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

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

    # Invite tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invites (
            inviter_id INTEGER PRIMARY KEY,
            real INTEGER NOT NULL DEFAULT 0,
            fake INTEGER NOT NULL DEFAULT 0,
            rejoiners INTEGER NOT NULL DEFAULT 0,
            bonus INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Track who invited whom (for leave/rejoin detection)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_joins (
            joined_user_id INTEGER PRIMARY KEY,
            inviter_id INTEGER NOT NULL,
            was_fake INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Boost tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS boost_tracking (
            user_id INTEGER PRIMARY KEY,
            boost_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT
        )
    """)

    # Claims tracking (prevent duplicate claims)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL,
            plan_type TEXT NOT NULL,
            plan_name TEXT NOT NULL,
            vps_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
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


# ─────────────────────────────────────────────────────────────────────────────
# INVITE DATABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_invite_stats(user_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT real, fake, rejoiners, bonus FROM invites WHERE inviter_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"real": row[0], "fake": row[1], "rejoiners": row[2], "bonus": row[3]}
    return {"real": 0, "fake": 0, "rejoiners": 0, "bonus": 0}

def add_invite(inviter_id: int, is_fake: bool):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO invites (inviter_id) VALUES (?)", (inviter_id,))
    if is_fake:
        cursor.execute("UPDATE invites SET fake = fake + 1 WHERE inviter_id = ?", (inviter_id,))
    else:
        cursor.execute("UPDATE invites SET real = real + 1 WHERE inviter_id = ?", (inviter_id,))
    conn.commit()
    conn.close()

def add_rejoiner(inviter_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO invites (inviter_id) VALUES (?)", (inviter_id,))
    cursor.execute("UPDATE invites SET rejoiners = rejoiners + 1 WHERE inviter_id = ?", (inviter_id,))
    conn.commit()
    conn.close()

def decrement_invite(inviter_id: int, was_fake: bool):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if was_fake:
        cursor.execute("UPDATE invites SET fake = MAX(fake - 1, 0) WHERE inviter_id = ?", (inviter_id,))
    else:
        cursor.execute("UPDATE invites SET real = MAX(real - 1, 0) WHERE inviter_id = ?", (inviter_id,))
    conn.commit()
    conn.close()

def add_bonus_invites(user_id: int, amount: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO invites (inviter_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE invites SET bonus = bonus + ? WHERE inviter_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def reset_invites(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM invites WHERE inviter_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_invite_join(joined_user_id: int, inviter_id: int, was_fake: bool):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO invite_joins (joined_user_id, inviter_id, was_fake)
        VALUES (?, ?, ?)
    """, (joined_user_id, inviter_id, 1 if was_fake else 0))
    conn.commit()
    conn.close()

def get_invite_join(joined_user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT inviter_id, was_fake FROM invite_joins WHERE joined_user_id = ?", (joined_user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"inviter_id": row[0], "was_fake": bool(row[1])}
    return None

def remove_invite_join(joined_user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM invite_joins WHERE joined_user_id = ?", (joined_user_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# BOOST DATABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def update_boost(user_id: int, boost_count: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    if boost_count > 0:
        cursor.execute("""
            INSERT INTO boost_tracking (user_id, boost_count, started_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET boost_count = ?
        """, (user_id, boost_count, now, boost_count))
    else:
        cursor.execute("DELETE FROM boost_tracking WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_boost_count(user_id: int) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT boost_count FROM boost_tracking WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0


# ─────────────────────────────────────────────────────────────────────────────
# CLAIMS DATABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_claim(discord_id: int, plan_type: str, plan_name: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO claims (discord_id, plan_type, plan_name, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
    """, (discord_id, plan_type, plan_name, now))
    claim_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return claim_id

def update_claim_status(claim_id: int, status: str, vps_id: int = None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if vps_id:
        cursor.execute("UPDATE claims SET status = ?, vps_id = ? WHERE id = ?", (status, vps_id, claim_id))
    else:
        cursor.execute("UPDATE claims SET status = ? WHERE id = ?", (status, claim_id))
    conn.commit()
    conn.close()

def get_active_claims(discord_id: int) -> list:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM claims WHERE discord_id = ? AND status IN ('pending', 'approved')", (discord_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# PLAN LOADING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_invite_plans() -> list:
    try:
        with open(os.path.join(BOT_DIR, "invite-plans.json"), "r") as f:
            return json.load(f)
    except Exception:
        return []

def load_boost_plans() -> list:
    try:
        with open(os.path.join(BOT_DIR, "boost-plans.json"), "r") as f:
            return json.load(f)
    except Exception:
        return []

def load_free_plans() -> list:
    try:
        with open(os.path.join(BOT_DIR, "free-plans.json"), "r") as f:
            return json.load(f)
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────────────────────

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

try:
    GUILD_ID = int(os.getenv("GUILD_ID", "0"))
except (ValueError, TypeError):
    GUILD_ID = 0

try:
    APPROVAL_CHANNEL_ID = int(os.getenv("APPROVAL_CHANNEL_ID", "0"))
except (ValueError, TypeError):
    APPROVAL_CHANNEL_ID = 0

# Fake invite threshold: accounts younger than 45 days
FAKE_ACCOUNT_DAYS = 45


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

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
                "site_name": data.get("site_name", "PilotPanel"),
                "color": discord.Color(color_int),
                "logo_url": logo_url if logo_url else None
            }
    except Exception:
        return {
            "site_name": "PilotPanel",
            "color": discord.Color.blue(),
            "logo_url": None
        }

# API Call Helper using Global Admin Key
def make_api_request(endpoint: str, method: str = "GET", data: dict = None):
    url = f"{PANEL_URL}/api/v1{endpoint}"
    headers = {
        "Authorization": f"Bearer {PANEL_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
            try:
                print(f"[ERROR] API HTTP Error {e.code} response body: {err_data}")
            except Exception:
                pass
            return {"message": f"HTTP Error {e.code}: {e.reason}"}, e.code
    except Exception as e:
        return {"message": f"Connection error: {str(e)}"}, 500

def generate_random_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(random.choice(chars) for _ in range(length))

def generate_random_name():
    adjectives = ["swift", "brave", "calm", "dark", "fast", "keen", "wild", "bold", "pure", "warm"]
    nouns = ["wolf", "hawk", "lion", "bear", "fox", "deer", "owl", "lynx", "crow", "pike"]
    return f"{random.choice(adjectives)}-{random.choice(nouns)}-{random.randint(100, 999)}"


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD BOT SETUP
# ─────────────────────────────────────────────────────────────────────────────

class VPSBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # Required for invite tracking + boost detection
        super().__init__(command_prefix="!", intents=intents)
        self.invite_cache = {}  # guild_id -> {code: uses}

    async def setup_hook(self):
        # Sync slash commands with Discord
        await self.tree.sync()

bot = VPSBot()


# ─────────────────────────────────────────────────────────────────────────────
# INVITE CACHE SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

async def cache_guild_invites(guild: discord.Guild):
    """Fetch all invites for a guild and cache them."""
    try:
        invites = await guild.invites()
        bot.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
    except discord.Forbidden:
        print(f"[WARN] Missing 'Manage Server' permission to track invites in {guild.name}")
        bot.invite_cache[guild.id] = {}
    except Exception as e:
        print(f"[ERROR] Failed to cache invites for {guild.name}: {e}")
        bot.invite_cache[guild.id] = {}


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("Discord Bot is ready for slash commands!")
    init_db()
    
    # Cache invites for all guilds
    for guild in bot.guilds:
        await cache_guild_invites(guild)
        print(f"[INVITES] Cached {len(bot.invite_cache.get(guild.id, {}))} invites for {guild.name}")
    
    # Sync boost states on startup
    for guild in bot.guilds:
        for member in guild.members:
            if member.premium_since is not None:
                # Count this member's boosts (discord.py doesn't expose exact count per user easily,
                # so we track presence: 1 = boosting, 0 = not boosting)
                current = get_boost_count(member.id)
                if current == 0:
                    update_boost(member.id, 1)


# ─────────────────────────────────────────────────────────────────────────────
# INVITE TRACKING EVENTS
# ─────────────────────────────────────────────────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    """Track which invite was used when a member joins."""
    guild = member.guild
    
    # Check if this user has joined before (rejoiner)
    previous_join = get_invite_join(member.id)
    
    try:
        # Fetch fresh invites and compare with cache
        new_invites = await guild.invites()
        old_cache = bot.invite_cache.get(guild.id, {})
        
        inviter_id = None
        used_code = None
        
        for inv in new_invites:
            old_uses = old_cache.get(inv.code, 0)
            if inv.uses > old_uses and inv.inviter:
                inviter_id = inv.inviter.id
                used_code = inv.code
                break
        
        # Update cache
        bot.invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
        
        if inviter_id:
            # Check if account is fake (created less than 45 days ago)
            account_age = (discord.utils.utcnow() - member.created_at).days
            is_fake = account_age < FAKE_ACCOUNT_DAYS
            
            if previous_join:
                # This is a rejoiner
                add_rejoiner(inviter_id)
                save_invite_join(member.id, inviter_id, is_fake)
                print(f"[INVITES] Rejoiner: {member} (invited by {inviter_id}, code: {used_code})")
            else:
                # New join
                add_invite(inviter_id, is_fake)
                save_invite_join(member.id, inviter_id, is_fake)
                tag = "FAKE" if is_fake else "REAL"
                print(f"[INVITES] {tag} invite: {member} (invited by {inviter_id}, code: {used_code}, age: {account_age}d)")
    
    except discord.Forbidden:
        print(f"[WARN] Cannot track invites — missing permissions in {guild.name}")
    except Exception as e:
        print(f"[ERROR] Invite tracking error on join: {e}")


@bot.event
async def on_member_remove(member: discord.Member):
    """When a member leaves, update the inviter's stats."""
    join_info = get_invite_join(member.id)
    if join_info:
        inviter_id = join_info["inviter_id"]
        was_fake = join_info["was_fake"]
        decrement_invite(inviter_id, was_fake)
        # Don't remove the join record — we need it to detect rejoiners
        print(f"[INVITES] Member left: {member} (was invited by {inviter_id})")
    
    # Re-cache invites
    await cache_guild_invites(member.guild)


@bot.event
async def on_invite_create(invite: discord.Invite):
    """Update cache when a new invite is created."""
    if invite.guild:
        cache = bot.invite_cache.get(invite.guild.id, {})
        cache[invite.code] = invite.uses
        bot.invite_cache[invite.guild.id] = cache


@bot.event
async def on_invite_delete(invite: discord.Invite):
    """Update cache when an invite is deleted."""
    if invite.guild:
        cache = bot.invite_cache.get(invite.guild.id, {})
        cache.pop(invite.code, None)
        bot.invite_cache[invite.guild.id] = cache


# ─────────────────────────────────────────────────────────────────────────────
# BOOST TRACKING EVENT
# ─────────────────────────────────────────────────────────────────────────────

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Detect boost start/stop."""
    # Check if boost state changed
    if before.premium_since != after.premium_since:
        if after.premium_since is not None and before.premium_since is None:
            # Started boosting
            update_boost(after.id, 1)
            print(f"[BOOST] {after} started boosting!")
        elif after.premium_since is None and before.premium_since is not None:
            # Stopped boosting
            update_boost(after.id, 0)
            print(f"[BOOST] {after} stopped boosting.")


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: CHECK IF USER IS LINKED
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_linked(interaction: discord.Interaction) -> dict:
    linked = get_linked_user(interaction.user.id)
    if not linked:
        if is_discord_admin(interaction):
            return {"user_id": 0, "username": "admin", "role": "admin"}
        branding = get_branding()
        embed = discord.Embed(
            title="🔒 Account Connection Required",
            description=f"You need to link your control panel account before you can manage your servers.\n\n"
                        f"1. Run `/link <username> <password>` to connect your profile.\n"
                        f"2. Or run `/account-create <username> <email> <password>` to register a new account.",
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
# SLASH COMMANDS — ACCOUNT & LINK
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


@bot.tree.command(name="account-create", description="Register a new panel account linked to your Discord.")
@app_commands.describe(username="Choose a username.", email="Your email address.", password="Choose a password (min 6 chars).")
async def account_create(interaction: discord.Interaction, username: str, email: str, password: str):
    await interaction.response.defer(ephemeral=True)
    
    # Check if already linked
    existing = get_linked_user(interaction.user.id)
    if existing:
        await interaction.followup.send("❌ You already have a linked panel account. Use `/unlink` first if you want to create a new one.", ephemeral=True)
        return
    
    if len(password.strip()) < 6:
        await interaction.followup.send("❌ Password must be at least 6 characters long.", ephemeral=True)
        return
    
    # Create user via admin API
    res, status = make_api_request("/admin/users", method="POST", data={
        "username": username.strip().lower(),
        "email": email.strip().lower(),
        "password": password.strip(),
        "role": "client"
    })
    
    if status == 201:
        user_id = res.get("id")
        # Auto-link the account
        save_user_link(interaction.user.id, user_id, username.strip().lower(), "client")
        
        branding = get_branding()
        
        # Send credentials via DM
        try:
            dm_embed = discord.Embed(
                title=f"🎉 Welcome to {branding['site_name']}!",
                description="Your control panel account has been created successfully. Here are your credentials:",
                color=discord.Color.green()
            )
            dm_embed.add_field(name="🌐 Panel URL", value=f"`{PANEL_URL}`", inline=False)
            dm_embed.add_field(name="👤 Username", value=f"`{username.strip().lower()}`", inline=True)
            dm_embed.add_field(name="📧 Email", value=f"`{email.strip().lower()}`", inline=True)
            dm_embed.add_field(name="🔑 Password", value=f"||`{password.strip()}`||", inline=False)
            dm_embed.set_footer(text=f"{branding['site_name']} • Keep your credentials safe!")
            
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # User has DMs disabled
        
        # Respond in channel
        embed = discord.Embed(
            title="✅ Account Created & Linked!",
            description=f"Your panel account **{username}** has been created and linked to your Discord.\n\n"
                        f"📬 Your credentials have been sent to your DMs.\n"
                        f"🌐 Login at: `{PANEL_URL}`",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"{branding['site_name']}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        error_msg = res.get("message", "Unknown error")
        await interaction.followup.send(f"❌ Account creation failed: {error_msg}", ephemeral=True)


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


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — INVITES
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(name="invites", description="View invite statistics for yourself or another user.")
@app_commands.describe(user="The user to check invites for (leave empty for yourself).")
async def invites_cmd(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    stats = get_invite_stats(target.id)
    branding = get_branding()
    
    total_effective = stats["real"] + stats["bonus"]
    
    embed = discord.Embed(
        title=f"📨 Invite Statistics — {target.display_name}",
        color=branding["color"]
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="✅ Real Invites", value=f"`{stats['real']}`", inline=True)
    embed.add_field(name="⚠️ Fake Invites", value=f"`{stats['fake']}`", inline=True)
    embed.add_field(name="🔄 Rejoiners", value=f"`{stats['rejoiners']}`", inline=True)
    embed.add_field(name="🎁 Bonus Invites", value=f"`{stats['bonus']}`", inline=True)
    embed.add_field(name="📊 Total Effective", value=f"**`{total_effective}`**", inline=True)
    embed.set_footer(text=f"{branding['site_name']} Invite Tracker • Fake threshold: accounts < {FAKE_ACCOUNT_DAYS} days old")
    
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — PLANS
# ─────────────────────────────────────────────────────────────────────────────

class PlanTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Free Plans", value="free", emoji="🆓", description="No requirements needed"),
            discord.SelectOption(label="Invite Plans", value="invite", emoji="📨", description="Earned by inviting members"),
            discord.SelectOption(label="Boost Plans", value="boost", emoji="💎", description="Earned by boosting the server"),
        ]
        super().__init__(placeholder="Select a plan category...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        branding = get_branding()
        plan_type = self.values[0]
        
        if plan_type == "free":
            plans = load_free_plans()
            title = "🆓 Free Plans"
            desc = "These plans are available to everyone — no invites or boosts required. Limited to one per user."
        elif plan_type == "invite":
            plans = load_invite_plans()
            title = "📨 Invite Plans"
            desc = "Earn these plans by inviting real members to the server."
        else:
            plans = load_boost_plans()
            title = "💎 Boost Plans"
            desc = "Earn these plans by boosting the server."
        
        embed = discord.Embed(title=title, description=desc, color=branding["color"])
        
        if not plans:
            embed.add_field(name="No Plans Available", value="No plans have been configured for this category yet.", inline=False)
        else:
            for p in plans:
                if plan_type == "invite":
                    req_text = f"📨 **Required Invites:** `{p.get('required_invites', 0)}`"
                elif plan_type == "boost":
                    req_text = f"💎 **Required Boosts:** `{p.get('required_boosts', 0)}`"
                else:
                    req_text = "✅ **No requirements**"
                
                embed.add_field(
                    name=f"🖥️ {p['name']}",
                    value=f"{req_text}\n"
                          f"⚡ CPU: `{p.get('cpu', 1)} Cores` • 🧠 RAM: `{p.get('ram', 512)} MB` • 💾 Disk: `{p.get('disk', 5)} GB`",
                    inline=False
                )
        
        embed.set_footer(text=f"{branding['site_name']} • Use /claim to claim a plan")
        await interaction.response.edit_message(embed=embed, view=None)


class PlanTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(PlanTypeSelect())


@bot.tree.command(name="plans", description="View all available VPS plans (free, invite-based, boost-based).")
async def plans_cmd(interaction: discord.Interaction):
    branding = get_branding()
    
    embed = discord.Embed(
        title=f"📋 {branding['site_name']} — Available Plans",
        description="Select a plan category below to view available VPS plans and their requirements.",
        color=branding["color"]
    )
    
    free_count = len(load_free_plans())
    invite_count = len(load_invite_plans())
    boost_count = len(load_boost_plans())
    
    embed.add_field(name="🆓 Free Plans", value=f"`{free_count}` plan(s) available", inline=True)
    embed.add_field(name="📨 Invite Plans", value=f"`{invite_count}` plan(s) available", inline=True)
    embed.add_field(name="💎 Boost Plans", value=f"`{boost_count}` plan(s) available", inline=True)
    embed.set_footer(text="Select a category from the dropdown below")
    
    await interaction.response.send_message(embed=embed, view=PlanTypeView(), ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — CLAIM
# ─────────────────────────────────────────────────────────────────────────────

class ClaimTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Free Plan", value="free", emoji="🆓"),
            discord.SelectOption(label="Invite Plan", value="invite", emoji="📨"),
            discord.SelectOption(label="Boost Plan", value="boost", emoji="💎"),
        ]
        super().__init__(placeholder="What type of plan do you want to claim?", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        plan_type = self.values[0]
        
        if plan_type == "free":
            plans = load_free_plans()
        elif plan_type == "invite":
            plans = load_invite_plans()
        else:
            plans = load_boost_plans()
        
        if not plans:
            await interaction.response.edit_message(
                content="❌ No plans are configured for this category.", embed=None, view=None
            )
            return
        
        # Show plan selection
        view = ClaimPlanView(plan_type, plans, interaction.user)
        branding = get_branding()
        
        embed = discord.Embed(
            title=f"Select a {plan_type.title()} Plan to Claim",
            description="Choose the specific plan you want to deploy:",
            color=branding["color"]
        )
        
        for p in plans:
            if plan_type == "invite":
                req_text = f"📨 Requires `{p.get('required_invites', 0)}` real invites"
            elif plan_type == "boost":
                req_text = f"💎 Requires `{p.get('required_boosts', 0)}` active boost(s)"
            else:
                req_text = "✅ No requirements"
            
            embed.add_field(
                name=f"🖥️ {p['name']}",
                value=f"{req_text}\n⚡ `{p.get('cpu', 1)} Cores` • 🧠 `{p.get('ram', 512)} MB` • 💾 `{p.get('disk', 5)} GB`",
                inline=False
            )
        
        await interaction.response.edit_message(embed=embed, view=view)


class ClaimPlanSelect(discord.ui.Select):
    def __init__(self, plan_type: str, plans: list, claimer: discord.User):
        self.plan_type = plan_type
        self.plans = plans
        self.claimer = claimer
        
        options = [
            discord.SelectOption(
                label=p["name"],
                value=str(i),
                description=f"{p.get('cpu', 1)} Cores / {p.get('ram', 512)} MB / {p.get('disk', 5)} GB"
            )
            for i, p in enumerate(plans)
        ]
        super().__init__(placeholder="Select the plan...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.claimer.id:
            await interaction.response.send_message("❌ This menu is not for you.", ephemeral=True)
            return
        
        plan_index = int(self.values[0])
        plan = self.plans[plan_index]
        branding = get_branding()
        
        # Check if user has a linked account
        linked = get_linked_user(interaction.user.id)
        if not linked:
            await interaction.response.edit_message(
                content="❌ You need a linked panel account first. Use `/account-create` or `/link`.",
                embed=None, view=None
            )
            return
        
        # Check requirements
        if self.plan_type == "invite":
            stats = get_invite_stats(interaction.user.id)
            effective = stats["real"] + stats["bonus"]
            required = plan.get("required_invites", 0)
            if effective < required:
                await interaction.response.edit_message(
                    content=f"❌ You need **{required}** effective invites but only have **{effective}**. Keep inviting!",
                    embed=None, view=None
                )
                return
        
        elif self.plan_type == "boost":
            boost_count = get_boost_count(interaction.user.id)
            required = plan.get("required_boosts", 0)
            # Also check premium_since on the member object
            member = interaction.user
            if isinstance(member, discord.Member) and member.premium_since is None:
                boost_count = 0
            if boost_count < required:
                await interaction.response.edit_message(
                    content=f"❌ You need **{required}** active boost(s) but have **{boost_count}**. Boost the server to claim!",
                    embed=None, view=None
                )
                return
        
        # Check for existing pending/approved claims
        active = get_active_claims(interaction.user.id)
        if active:
            await interaction.response.edit_message(
                content="❌ You already have an active or pending claim. Please wait for it to be processed.",
                embed=None, view=None
            )
            return
        
        # Save the claim
        claim_id = save_claim(interaction.user.id, self.plan_type, plan["name"])
        
        # Send to approval channel
        if APPROVAL_CHANNEL_ID:
            approval_channel = bot.get_channel(APPROVAL_CHANNEL_ID)
            if approval_channel:
                approval_embed = discord.Embed(
                    title="📋 New VPS Claim Request",
                    description=f"A user has requested a VPS through the **{self.plan_type.title()} Plan** system.",
                    color=discord.Color.yellow()
                )
                approval_embed.add_field(name="👤 User", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=True)
                approval_embed.add_field(name="🏷️ Plan", value=f"`{plan['name']}`", inline=True)
                approval_embed.add_field(name="📂 Type", value=f"`{self.plan_type.upper()}`", inline=True)
                approval_embed.add_field(
                    name="⚡ Specs",
                    value=f"CPU: `{plan.get('cpu', 1)} Cores` • RAM: `{plan.get('ram', 512)} MB` • Disk: `{plan.get('disk', 5)} GB`",
                    inline=False
                )
                
                if self.plan_type == "invite":
                    stats = get_invite_stats(interaction.user.id)
                    approval_embed.add_field(
                        name="📨 Invite Stats",
                        value=f"Real: `{stats['real']}` | Fake: `{stats['fake']}` | Rejoiners: `{stats['rejoiners']}` | Bonus: `{stats['bonus']}`",
                        inline=False
                    )
                elif self.plan_type == "boost":
                    approval_embed.add_field(name="💎 Boost Status", value="Active Booster ✅", inline=False)
                
                approval_embed.add_field(name="🔗 Panel Account", value=f"`{linked['username']}` (ID: `{linked['user_id']}`)", inline=False)
                approval_embed.set_footer(text=f"Claim ID: {claim_id} • {branding['site_name']}")
                approval_embed.timestamp = discord.utils.utcnow()
                
                view = ApprovalView(claim_id, interaction.user.id, linked["user_id"], plan)
                await approval_channel.send(embed=approval_embed, view=view)
        
        # Confirm to user
        embed = discord.Embed(
            title="✅ Claim Submitted!",
            description=f"Your claim for **{plan['name']}** has been submitted and is pending admin approval.\n\n"
                        f"You will receive a DM when your VPS is ready!",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Claim ID: {claim_id}")
        await interaction.response.edit_message(embed=embed, view=None)


class ClaimPlanView(discord.ui.View):
    def __init__(self, plan_type: str, plans: list, claimer: discord.User):
        super().__init__(timeout=120)
        self.add_item(ClaimPlanSelect(plan_type, plans, claimer))


class ClaimTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ClaimTypeSelect())


# ─────────────────────────────────────────────────────────────────────────────
# APPROVAL SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalView(discord.ui.View):
    def __init__(self, claim_id: int, discord_user_id: int, panel_user_id: int, plan: dict):
        super().__init__(timeout=None)  # Persistent view
        self.claim_id = claim_id
        self.discord_user_id = discord_user_id
        self.panel_user_id = panel_user_id
        self.plan = plan
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="✅", custom_id="claim_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is admin
        if not is_discord_admin(interaction):
            await interaction.response.send_message("❌ Only administrators can approve claims.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Deploy VPS
        random_name = generate_random_name()
        random_password = generate_random_password()
        
        deploy_data = {
            "name": random_name,
            "user_id": self.panel_user_id,
            "os": "debian/11",
            "cpu": self.plan.get("cpu", 1),
            "ram": self.plan.get("ram", 512),
            "disk": self.plan.get("disk", 5),
            "root_password": random_password
        }
        
        res, status = make_api_request("/admin/vps", method="POST", data=deploy_data)
        
        if status == 201:
            vps_info = res.get("vps", {})
            vps_id = vps_info.get("id", 0)
            container_name = vps_info.get("container_name", random_name)
            
            update_claim_status(self.claim_id, "approved", vps_id)
            
            # DM the user with credentials
            try:
                user = await bot.fetch_user(self.discord_user_id)
                branding = get_branding()
                
                dm_embed = discord.Embed(
                    title="🎉 Your VPS Has Been Approved & Deployed!",
                    description=f"Your **{self.plan['name']}** VPS claim has been approved by an administrator.",
                    color=discord.Color.green()
                )
                dm_embed.add_field(name="🖥️ Server Name", value=f"`{container_name}`", inline=True)
                dm_embed.add_field(name="🆔 VPS ID", value=f"`{vps_id}`", inline=True)
                dm_embed.add_field(name="🐧 Operating System", value="`Debian 11`", inline=True)
                dm_embed.add_field(
                    name="⚡ Specifications",
                    value=f"CPU: `{self.plan.get('cpu', 1)} Cores` • RAM: `{self.plan.get('ram', 512)} MB` • Disk: `{self.plan.get('disk', 5)} GB`",
                    inline=False
                )
                dm_embed.add_field(name="🔑 Root Password", value=f"||`{random_password}`||", inline=False)
                dm_embed.add_field(name="🌐 Panel URL", value=f"`{PANEL_URL}`", inline=False)
                dm_embed.set_footer(text=f"{branding['site_name']} • Your server will be ready in ~30 seconds")
                
                await user.send(embed=dm_embed)
            except Exception as e:
                print(f"[ERROR] Failed to DM user {self.discord_user_id}: {e}")
            
            # Update the approval embed
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = discord.Color.green()
            embed.add_field(
                name="✅ APPROVED",
                value=f"Approved by {interaction.user.mention}\nVPS ID: `{vps_id}` | Container: `{container_name}`",
                inline=False
            )
            
            # Disable buttons
            for child in self.children:
                child.disabled = True
            
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(f"✅ Claim #{self.claim_id} approved! VPS `{container_name}` deployed for user <@{self.discord_user_id}>.", ephemeral=True)
        else:
            error_msg = res.get("message", "Unknown error")
            await interaction.followup.send(f"❌ VPS deployment failed: {error_msg}", ephemeral=True)
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, emoji="❌", custom_id="claim_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_discord_admin(interaction):
            await interaction.response.send_message("❌ Only administrators can deny claims.", ephemeral=True)
            return
        
        update_claim_status(self.claim_id, "denied")
        
        # DM the user
        try:
            user = await bot.fetch_user(self.discord_user_id)
            branding = get_branding()
            
            dm_embed = discord.Embed(
                title="❌ VPS Claim Denied",
                description=f"Your claim for **{self.plan['name']}** has been denied by an administrator.\n\n"
                            f"If you believe this is a mistake, please contact the server staff.",
                color=discord.Color.red()
            )
            dm_embed.set_footer(text=branding["site_name"])
            await user.send(embed=dm_embed)
        except Exception:
            pass
        
        # Update the approval embed
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.red()
        embed.add_field(
            name="❌ DENIED",
            value=f"Denied by {interaction.user.mention}",
            inline=False
        )
        
        # Disable buttons
        for child in self.children:
            child.disabled = True
        
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"❌ Claim #{self.claim_id} denied.", ephemeral=True)


@bot.tree.command(name="claim", description="Claim a free VPS based on your invites, boosts, or a free plan.")
async def claim_cmd(interaction: discord.Interaction):
    branding = get_branding()
    
    embed = discord.Embed(
        title=f"🎁 Claim a VPS — {branding['site_name']}",
        description="Choose how you'd like to claim your VPS:",
        color=branding["color"]
    )
    embed.add_field(name="🆓 Free Plan", value="Available to everyone (one per user)", inline=False)
    embed.add_field(name="📨 Invite Plan", value="Earned by inviting real members", inline=False)
    embed.add_field(name="💎 Boost Plan", value="Earned by boosting the server", inline=False)
    embed.set_footer(text="Select an option from the dropdown below")
    
    await interaction.response.send_message(embed=embed, view=ClaimTypeView(), ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — VPS MANAGEMENT (existing)
# ─────────────────────────────────────────────────────────────────────────────

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
    app_commands.Choice(name="Alpine Linux 3.18", value="alpine/3.18"),
    app_commands.Choice(name="Windows 10 Pro", value="windows/10"),
    app_commands.Choice(name="Windows 11 Pro", value="windows/11"),
    app_commands.Choice(name="Windows Server 2022", value="windows/server/2022"),
    app_commands.Choice(name="Windows Server 2019", value="windows/server/2019"),
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


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — SNAPSHOTS (existing)
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — BACKUPS (existing)
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# SLASH COMMANDS — FIREWALL (existing)
# ─────────────────────────────────────────────────────────────────────────────

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
admin_invites_group = app_commands.Group(name="invites", parent=admin_group, description="Manage user invite counts")

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
        embed.set_footer(text="PilotPanel Cluster Management")
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
    root_password="Root SSH password.",
    discord_user="Discord user to notify via DM with credentials"
)
@app_commands.choices(os=[
    app_commands.Choice(name="Ubuntu 22.04 LTS", value="ubuntu/22.04"),
    app_commands.Choice(name="Ubuntu 24.04 LTS", value="ubuntu/24.04"),
    app_commands.Choice(name="Debian 11", value="debian/11"),
    app_commands.Choice(name="Debian 12", value="debian/12"),
    app_commands.Choice(name="CentOS 9 Stream", value="centos/9-stream"),
    app_commands.Choice(name="Alpine Linux 3.18", value="alpine/3.18"),
    app_commands.Choice(name="Windows 10 Pro", value="windows/10"),
    app_commands.Choice(name="Windows 11 Pro", value="windows/11"),
    app_commands.Choice(name="Windows Server 2022", value="windows/server/2022"),
    app_commands.Choice(name="Windows Server 2019", value="windows/server/2019"),
])
async def admin_deploy_vps(interaction: discord.Interaction, name: str, user_id: int, os: app_commands.Choice[str], cpu: int, ram: int, disk: int, root_password: str, discord_user: discord.User = None):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    data = {
        "name": name.strip(),
        "user_id": user_id,
        "os": os.value,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "root_password": root_password.strip()
    }
    if discord_user:
        data["discord_user_id"] = str(discord_user.id)

    res, status = make_api_request("/admin/vps", method="POST", data=data)

    if status == 201:
        msg = f"🚀 Deploy started successfully! Created container `{res['vps']['container_name']}` (ID `{res['vps']['id']}`) for User `{user_id}`."
        if discord_user:
            msg += f" Will send credentials DM to {discord_user.mention}."
        await interaction.followup.send(msg, ephemeral=True)
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
@app_commands.describe(username="Username", email="Email address", password="Initial password", role="Account privileges", discord_user="Discord user to notify via DM with credentials")
@app_commands.choices(role=[
    app_commands.Choice(name="Client (Default)", value="client"),
    app_commands.Choice(name="Administrator", value="admin")
])
async def admin_create_user_cmd(interaction: discord.Interaction, username: str, email: str, password: str, role: app_commands.Choice[str], discord_user: discord.User = None):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    data = {
        "username": username.strip().lower(),
        "email": email.strip().lower(),
        "password": password,
        "role": role.value
    }
    if discord_user:
        data["discord_user_id"] = str(discord_user.id)

    res, status = make_api_request("/admin/users", method="POST", data=data)
    if status == 201:
        msg = f"✅ User `{username}` successfully created (ID `{res.get('id')}`)."
        if discord_user:
            msg += f" Sent credentials DM to {discord_user.mention}."
        await interaction.followup.send(msg, ephemeral=True)
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


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN INVITE MANAGEMENT COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

@admin_invites_group.command(name="add", description="Add bonus invites to a user's count.")
@app_commands.describe(user="The Discord user to award invites to.", amount="Number of invites to add.")
async def admin_add_invites(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)
        return
    
    add_bonus_invites(user.id, amount)
    stats = get_invite_stats(user.id)
    
    await interaction.response.send_message(
        f"✅ Added **{amount}** bonus invites to {user.mention}.\n"
        f"📊 New totals — Real: `{stats['real']}` | Fake: `{stats['fake']}` | Bonus: `{stats['bonus']}` | Effective: `{stats['real'] + stats['bonus']}`"
    )


@admin_invites_group.command(name="reset", description="Reset all invite counts for a user.")
@app_commands.describe(user="The Discord user to reset invites for.")
async def admin_reset_invites(interaction: discord.Interaction, user: discord.User):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return
    
    reset_invites(user.id)
    await interaction.response.send_message(f"✅ Reset all invite statistics for {user.mention}.")


@admin_invites_group.command(name="check", description="View detailed invite stats for any user.")
@app_commands.describe(user="The Discord user to check.")
async def admin_check_invites(interaction: discord.Interaction, user: discord.User):
    if not is_discord_admin(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator role required.", ephemeral=True)
        return
    
    stats = get_invite_stats(user.id)
    branding = get_branding()
    
    embed = discord.Embed(
        title=f"🔍 Admin Invite Check — {user.display_name}",
        color=branding["color"]
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="✅ Real", value=f"`{stats['real']}`", inline=True)
    embed.add_field(name="⚠️ Fake", value=f"`{stats['fake']}`", inline=True)
    embed.add_field(name="🔄 Rejoiners", value=f"`{stats['rejoiners']}`", inline=True)
    embed.add_field(name="🎁 Bonus", value=f"`{stats['bonus']}`", inline=True)
    embed.add_field(name="📊 Effective Total", value=f"**`{stats['real'] + stats['bonus']}`**", inline=True)
    
    boost_count = get_boost_count(user.id)
    embed.add_field(name="💎 Active Boosts", value=f"`{boost_count}`", inline=True)
    
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER GROUPS & HELP COMMAND
# ─────────────────────────────────────────────────────────────────────────────

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
        name="🔗 Account & Connection",
        value="`/account-create <username> <email> <password>` — Register a new panel account (credentials sent via DM)\n"
              "`/link <username> <password>` — Link existing panel account to Discord\n"
              "`/unlink` — Disconnect panel account\n"
              "`/profile` — View your panel profile",
        inline=False
    )
    embed.add_field(
        name="📨 Invites & Plans",
        value="`/invites [user]` — View invite statistics (real, fake, rejoiners, bonus)\n"
              "`/plans` — Browse all available VPS plans (free, invite, boost)\n"
              "`/claim` — Claim a VPS based on your invites or boosts",
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
                  "`/admin vps list/deploy/delete/suspend` — VPS management.\n"
                  "`/admin user list/create/delete/suspend` — User management.\n"
                  "`/admin invites add <user> <amount>` — Award bonus invites.\n"
                  "`/admin invites reset <user>` — Reset user invite stats.\n"
                  "`/admin invites check <user>` — View detailed invite & boost stats.",
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
