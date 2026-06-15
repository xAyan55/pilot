"""
Tunnel Port Forwarding Background Monitor
Runs every 15 seconds, reads local iptables port forwards and syncs
tunnel_host/tunnel_port to the database for containers on the local node (ID 1).

On remote nodes, port forwarding is managed by the daemon via iptables
and reported through the WebSocket connection.
"""
import time
import subprocess
import re
import threading
import socket
from database import get_db_connection
from lxc_manager import LXCManager, IS_MOCK_LXC


def _get_advertised_host():
    """Return a usable hostname: ssh_relay_host setting > FQDN > 0.0.0.0."""
    host = '0.0.0.0'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'ssh_relay_host'")
        row = cur.fetchone()
        conn.close()
        if row and row['value']:
            host = row['value']
    except Exception:
        pass
    if host == '0.0.0.0':
        try:
            host = socket.getfqdn() or '0.0.0.0'
        except Exception:
            pass
    return host


def get_local_port_forwards():
    """Read iptables DNAT rules to find container port forwards."""
    if IS_MOCK_LXC:
        return {}
    try:
        out = subprocess.run(
            ['iptables', '-t', 'nat', '-L', 'PREROUTING', '-n'],
            capture_output=True, text=True, timeout=5
        )
        forwards = {}
        for line in out.stdout.splitlines():
            if 'DNAT' in line and 'tcp' in line and 'dpt:' in line and 'to:' in line:
                m = re.search(r'dpt:(\d+).*to:([\d.]+):22', line)
                if m:
                    port = int(m.group(1))
                    ip = m.group(2)
                    forwards[ip] = port
        return forwards
    except Exception:
        return {}


def monitor_loop():
    print("[TUNNEL MONITOR] Starting port forward monitor (local node)...")
    while True:
        try:
            forwards = get_local_port_forwards()
            if not forwards:
                time.sleep(15)
                continue

            advertised_host = _get_advertised_host()

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vps WHERE node_id = 1 AND status = 'running'")
            running_vps = [dict(row) for row in cursor.fetchall()]
            conn.close()

            for vps in running_vps:
                vps_id = vps['id']
                name = vps['container_name']
                try:
                    ip = LXCManager.get_container_ip(name)
                except Exception:
                    continue
                if ip and ip in forwards:
                    port = forwards[ip]
                    if vps.get('tunnel_port') != port or vps.get('tunnel_host') != advertised_host:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE vps SET tunnel_host = ?, tunnel_port = ? WHERE id = ?",
                            (advertised_host, port, vps_id)
                        )
                        conn.commit()
                        conn.close()
                        print(f"[TUNNEL MONITOR] Port forward synced for {name}: :{port} -> {ip}:22")
        except Exception as e:
            print(f"[TUNNEL MONITOR] Error: {e}")

        time.sleep(15)


def start_monitor():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

