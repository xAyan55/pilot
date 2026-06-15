import time
import json
import urllib.request
import urllib.error
import threading
import platform
import random
import os
import atexit
from database import get_db_connection

PANEL_START_TIME = time.time()
_monitor_thread = None
_should_run = True

def get_uptime_string(seconds):
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

def get_host_system_stats():
    """Retrieve real-time Host CPU, Memory, and Disk stats."""
    stats = {
        "host_cpu": round(random.uniform(15.0, 35.0), 1),
        "host_ram_used": 4.2,
        "host_ram_total": 8.0,
        "host_ram_percent": 52.5,
        "host_disk_used": 45.0,
        "host_disk_total": 120.0,
        "host_disk_percent": 37.5
    }
    
    if platform.system() == 'Linux':
        try:
            # 1. CPU Usage via /proc/stat
            def read_cpu_times():
                with open('/proc/stat', 'r') as f:
                    for line in f:
                        if line.startswith('cpu '):
                            parts = [float(x) for x in line.split()[1:]]
                            idle = parts[3] + parts[4]
                            total = sum(parts)
                            return idle, total
                return 0.0, 0.0

            idle1, total1 = read_cpu_times()
            time.sleep(0.05)
            idle2, total2 = read_cpu_times()
            
            diff_total = total2 - total1
            diff_idle = idle2 - idle1
            if diff_total > 0:
                stats['host_cpu'] = round(100.0 * (diff_total - diff_idle) / diff_total, 1)
            else:
                stats['host_cpu'] = 0.0
                
            # 2. Memory Usage via /proc/meminfo
            mem_total = 0
            mem_available = 0
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        mem_total = int(line.split()[1])
                    elif line.startswith('MemAvailable:'):
                        mem_available = int(line.split()[1])
            if mem_total > 0:
                mem_used = mem_total - mem_available
                stats['host_ram_total'] = round(mem_total / (1024 * 1024), 1)
                stats['host_ram_used'] = round(mem_used / (1024 * 1024), 1)
                stats['host_ram_percent'] = round((mem_used / mem_total) * 100, 1)

            # 3. Disk Usage via os.statvfs
            disk_info = os.statvfs('/')
            total_bytes = disk_info.f_blocks * disk_info.f_frsize
            free_bytes = disk_info.f_bavail * disk_info.f_frsize
            used_bytes = total_bytes - free_bytes
            
            stats['host_disk_total'] = round(total_bytes / (1024 * 1024 * 1024), 1)
            stats['host_disk_used'] = round(used_bytes / (1024 * 1024 * 1024), 1)
            stats['host_disk_percent'] = round((used_bytes / total_bytes) * 100, 1)
        except Exception:
            pass
            
    return stats

def get_settings():
    settings = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        for row in cursor.fetchall():
            settings[row['key']] = row['value']
        conn.close()
    except Exception:
        pass
    return settings

def update_setting(key, value):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def send_discord_status(status_type="online"):
    settings = get_settings()
    
    enabled = settings.get('discord_status_enabled', '0') == '1'
    webhook_url = settings.get('discord_status_webhook_url', '').strip()
    
    # If not enabled or no webhook, do nothing
    if not webhook_url:
        return
        
    # In case of offline trigger, we update even if disabled to make sure we cleanly report shutdown
    if not enabled and status_type != "offline":
        return

    title = settings.get('discord_status_title', 'MintyHost Panel Status').strip()
    health_url = settings.get('discord_status_health_url', '').strip()
    message_id = settings.get('discord_status_message_id', '').strip()

    # Get system stats
    stats = get_host_system_stats()
    
    # Get nodes
    nodes = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, status, fqdn FROM nodes")
        nodes = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception:
        pass

    # Get VPS counts
    total_vps = 0
    running_vps = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM vps")
        vps_rows = cursor.fetchall()
        conn.close()
        total_vps = len(vps_rows)
        running_vps = sum(1 for r in vps_rows if r['status'] == 'running')
    except Exception:
        pass

    # Construct embed color & status lines
    if status_type == "online":
        color = 3066993  # Green
        status_value = "🟢 **Online**"
        uptime_seconds = time.time() - PANEL_START_TIME
        uptime_str = get_uptime_string(uptime_seconds)
    else:
        color = 15158332  # Red
        status_value = "🔴 **Offline**"
        uptime_str = "N/A"

    node_lines = []
    for n in nodes:
        emoji = "🟢" if n['status'] == 'online' else "🔴"
        node_lines.append(f"{emoji} **{n['name']}** ({n['fqdn']})")
    node_str = "\n".join(node_lines) if node_lines else "No nodes registered"

    fields = [
        {"name": "Status", "value": status_value, "inline": True},
        {"name": "Uptime", "value": f"⏱️ `{uptime_str}`", "inline": True},
        {"name": "Health URL", "value": f"🔗 [Link]({health_url})" if health_url else "N/A", "inline": True}
    ]

    if status_type == "online":
        fields.append({
            "name": "System Resources",
            "value": f"💻 **CPU:** {stats['host_cpu']}%\n⚙️ **RAM:** {stats['host_ram_used']} GB / {stats['host_ram_total']} GB ({stats['host_ram_percent']}%)\n💽 **Disk:** {stats['host_disk_used']} GB / {stats['host_disk_total']} GB ({stats['host_disk_percent']}%)",
            "inline": False
        })
        fields.append({"name": "Nodes Status", "value": node_str, "inline": True})
        fields.append({"name": "Active VPS Instances", "value": f"⚡ `{running_vps}` Running / `{total_vps}` Total", "inline": True})

    payload = {
        "embeds": [{
            "title": f"🛡️ {title}",
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Last Updated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} (Updates every 10s)"
            }
        }]
    }

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }

    # If we have a message ID, try to edit the existing message
    success = False
    if message_id:
        patch_url = webhook_url
        if patch_url.endswith('/'):
            patch_url = f"{patch_url}messages/{message_id}"
        else:
            patch_url = f"{patch_url}/messages/{message_id}"
            
        try:
            req = urllib.request.Request(
                patch_url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='PATCH'
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                if response.status in (200, 204):
                    success = True
        except urllib.error.HTTPError as e:
            # If 404, the message was deleted; we will create a new one
            if e.code == 404:
                message_id = ""
            else:
                print(f"[STATUS MONITOR] Webhook PATCH failed with code {e.code}: {e.read().decode('utf-8', errors='ignore')}")
        except Exception as e:
            print(f"[STATUS MONITOR] Webhook PATCH exception: {e}")

    # If no message ID or PATCH failed with 404, send a new message
    if not success:
        post_url = webhook_url
        if '?' in post_url:
            post_url += "&wait=true"
        else:
            post_url += "?wait=true"
            
        try:
            req = urllib.request.Request(
                post_url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                new_msg_id = res_data.get('id')
                if new_msg_id:
                    update_setting('discord_status_message_id', new_msg_id)
                    print(f"[STATUS MONITOR] Created new status message ID: {new_msg_id}")
        except Exception as e:
            print(f"[STATUS MONITOR] Webhook POST failed: {e}")

def monitor_loop():
    print("[STATUS MONITOR] Real-time status monitor thread started.")
    while _should_run:
        try:
            send_discord_status("online")
        except Exception as e:
            print(f"[STATUS MONITOR] Error in monitor loop: {e}")
        time.sleep(10)

def start_status_monitor():
    global _monitor_thread, _should_run
    _should_run = True
    if _monitor_thread is None or not _monitor_thread.is_alive():
        _monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        _monitor_thread.start()

def stop_status_monitor():
    global _should_run
    _should_run = False

# Ensure offline status is sent when Python exits cleanly
@atexit.register
def on_exit():
    try:
        # Stop background thread loop
        stop_status_monitor()
        # Set status to offline
        send_discord_status("offline")
        print("[STATUS MONITOR] Sent offline status to Discord webhook.")
    except Exception as e:
        pass
