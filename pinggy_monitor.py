import time
import urllib.request
import urllib.parse
import json
import threading
from database import get_db_connection

try:
    from lxc_manager import LXCManager
except ImportError:
    LXCManager = None

def get_node_by_id(node_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def make_node_request(node, endpoint, method='POST', data=None):
    url = f"http://{node['fqdn']}:{node['port']}{endpoint}"
    headers = {
        "Authorization": f"Bearer {node['api_key']}",
        "Content-Type": "application/json"
    }
    req_data = None
    if data:
        req_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
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
            conn.close()

            for vps in running_vps:
                vps_id = vps['id']
                container_name = vps['container_name']
                node_id = vps['node_id']
                
                stats = None
                if node_id == 1:
                    # Local node
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
                        except Exception as ex:
                            # Silently fail to not spam logs if container transiently busy
                            pass
                else:
                    # Remote node
                    node = get_node_by_id(node_id)
                    if node:
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

                if stats:
                    tunnel_host = stats.get('tunnel_host')
                    tunnel_port = stats.get('tunnel_port')
                    # Sync if different from DB and valid
                    if tunnel_host and tunnel_port:
                        if tunnel_host != vps['tunnel_host'] or tunnel_port != vps['tunnel_port']:
                            print(f"[PINGGY MONITOR] Tunnel updated for {container_name}: {tunnel_host}:{tunnel_port}")
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute(
                                "UPDATE vps SET tunnel_host = ?, tunnel_port = ? WHERE id = ?",
                                (tunnel_host, tunnel_port, vps_id)
                            )
                            conn.commit()
                            conn.close()

        except Exception as e:
            print(f"[PINGGY MONITOR] Error in loop iteration: {e}")
        
        time.sleep(10)

def start_monitor():
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
