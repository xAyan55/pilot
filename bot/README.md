# Discord Bot Integration Setup Guide

This directory contains a pre-built, premium, **multi-user Discord bot** that allows you and your users to manage LXC Virtual Private Servers directly from Discord using safe slash commands.

---

## Features

- **Multi-User Architecture**: Each user runs `/setup <api_key>` to link their Discord account. Keys are securely cached in a local sqlite database (`bot_users.db`).
- **Dynamic branding theme sync**: Automatically syncs embed color palettes and names with the branding configuration on your control panel.
- **Power Operations**: `/vps action <vps_id> <start|stop|restart>` to control power states.
- **Live Stats Monitoring**: `/vps info <vps_id>` to view live CPU, memory, and disk usage as premium visual summaries.
- **Backups & Snapshots**: Create, restore, list, or delete snapshots and export archives via `/snapshot` and `/backup`.
- **Firewall Control**: Easily list, add, or delete port access rules with `/firewall`.

---

## 🛠️ Step-by-Step Installation

### 1. Register a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and enter a name (e.g. `PilotPanel Bot`).
3. Under the **Bot** tab on the left sidebar:
   - Click **Add Bot** or generate a token.
   - Click **Reset Token** and copy the resulting string. Keep it safe (this is your `DISCORD_BOT_TOKEN`).
   - Enable **Message Content Intent** under the **Privileged Gateway Intents** section.
4. Under the **OAuth2** -> **URL Generator** tab:
   - Select `bot` and `applications.commands` scopes.
   - Under Bot Permissions, select:
     - `Send Messages`
     - `Embed Links`
     - `Use Slash Commands`
   - Copy the generated URL and open it in your browser to invite the bot to your Discord Server.

### 2. Configure Environment

1. Copy `.env.example` to a new file named `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your details:
   ```env
   DISCORD_BOT_TOKEN=your_copied_bot_token_string
   PANEL_URL=http://your-panel-domain-or-ip:5000
   ```

### 3. Install Dependencies & Run

1. It is recommended to run inside a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install the lightweight requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Boot up the bot:
   ```bash
   python bot.py
   ```
4. Once you see `Logged in as ...` in your console, go to Discord and type `/help` to see all available actions.

---

## 🔒 Security Practices

- **Ephemeral Setup**: The `/setup <api_key>` slash command is configured with the `ephemeral=True` property. This means the command call and input are only visible to the user who ran the command. No one else in your server will ever see the API Key input.
- **Restricted Access**: The bot ensures that standard users can only view and manage containers **assigned to their own account** in the backend. 
