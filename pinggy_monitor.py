"""
Pinggy Tunnel Background Monitor
Runs every 10 seconds, reads /var/run/pinggy_host and /var/run/pinggy_port
from each running container and syncs them to the database.
When Pinggy's 1-hour free session expires and the tunnel script restarts
with a new URL, this monitor picks up the change and updates the DB,
so the dashboard always shows the current SSH connection command.
"""
import time
import urllib.request
import json
import threading
import re
from database import get_db_connection

try:
    from lxc_manager import LXCManager
except ImportError:
    LXCManager = None


def make_node_request(node, endpoint, method='POST', data=None, timeout=30):
    scheme = "https" if node['port'] in (443, 8443) else "http"
    url = f"{scheme}://{node['fqdn']}:{node['port']}{endpoint}"
    headers = {
        "Authorization": f"Bearer {node['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    req_data = None
    if data:
        req_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_data = response.read().decode('utf-8')
            return json.loads(res_data), response.status
    except Exception as e:
        return {"message": str(e)}, 500


def monitor_loop():
    print("[PINGGY MONITOR] Starting background monitor loop...")
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vps WHERE status = 'running'")
            running_vps = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM nodes")
            nodes_map = {row['id']: dict(row) for row in cursor.fetchall()}
            conn.close()

            for vps in running_vps:
                vps_id = vps['id']
                container_name = vps['container_name']
                node_id = vps['node_id']

                stats = None
                if node_id == 1:
                    # Local node — read tunnel files directly from container
                    if LXCManager:
                        try:
                            stats = LXCManager.get_container_stats(
                                name=container_name,
                                plan_cpu=vps['cpu'],
                                plan_ram=vps['ram'],
                                plan_disk=vps['disk'],
                                db_status=vps['status'],
                                vps_id=vps_id
                            )
                        except Exception:
                            pass
                else:
                    # Remote node — fetch stats via daemon API if online and fqdn is resolved
                    node = nodes_map.get(node_id)
                    if node and node['status'] == 'online' and node['fqdn'] and node['fqdn'] != 'dynamic':
                        res, code = make_node_request(node, "/api/vps/stats", data={
                            "name": container_name,
                            "cpu": vps['cpu'],
                            "ram": vps['ram'],
                            "disk": vps['disk'],
                            "status": vps['status'],
                            "vps_id": vps_id
                        })
                        if code == 200:
                            stats = res

                if not stats:
                    continue

                tunnel_host = stats.get('tunnel_host')
                tunnel_port = stats.get('tunnel_port')

                # Only sync when we have REAL Pinggy-assigned values
                if not tunnel_host or not tunnel_port:
                    continue

                # Check if DB is out of date
                db_host = vps.get('tunnel_host')
                db_port = vps.get('tunnel_port')
                if str(tunnel_host) != str(db_host) or str(tunnel_port) != str(db_port):
                    print(f"[PINGGY MONITOR] Tunnel updated for {container_name}: {tunnel_host}:{tunnel_port}")
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE vps SET tunnel_host = ?, tunnel_port = ? WHERE id = ?",
                        (tunnel_host, int(tunnel_port), vps_id)
                    )
                    conn.commit()
                    conn.close()

        except Exception as e:
            print(f"[PINGGY MONITOR] Error in loop iteration: {e}")

        time.sleep(10)


def start_monitor():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
