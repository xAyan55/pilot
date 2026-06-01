import os
import sys
from flask import Flask, request, jsonify

# Helper function to read config.yml without external dependencies (no PyYAML requirement)
def load_config():
    config = {
        'port': 5001,
        'api_key': 'default-node-key',
        'node_id': 0,
        'name': 'Remote Node',
        'panel_url': ''
    }
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yml')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        k, v = line.split(':', 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if v.isdigit():
                            config[k] = int(v)
                        else:
                            config[k] = v
        except Exception as e:
            print(f"[!] Error reading config.yml: {e}")
    return config

config = load_config()

# Import LXCManager from lxc_manager.py
try:
    from lxc_manager import LXCManager, IS_MOCK_LXC
except ImportError:
    print("[!] Could not import LXCManager. Make sure daemon.py is in the lxc project directory.")
    sys.exit(1)

app = Flask(__name__)

# Authentication decorator
def require_api_key(f):
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"message": "Missing authorization header"}), 401
        
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({"message": "Invalid authorization header format"}), 401
        
        token = parts[1]
        if token != config['api_key']:
            return jsonify({"message": "Invalid API key"}), 403
            
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/api/node/status', methods=['GET'])
@require_api_key
def status():
    return jsonify({
        "status": "online",
        "name": config.get('name'),
        "node_id": config.get('node_id'),
        "is_mock": IS_MOCK_LXC
    })

@app.route('/api/vps/deploy', methods=['POST'])
@require_api_key
def deploy():
    data = request.get_json() or {}
    name = data.get('name')
    os_image = data.get('os')
    cpu = int(data.get('cpu', 1))
    ram = int(data.get('ram', 512))
    disk = int(data.get('disk', 10))
    password = data.get('password')

    if not all([name, os_image, password]):
        return jsonify({"message": "Missing deployment parameters"}), 400

    try:
        LXCManager.deploy_container(
            name=name,
            os_image=os_image,
            cpu_cores=cpu,
            ram_mb=ram,
            disk_gb=disk,
            root_password=password
        )
        return jsonify({"status": "success", "message": "Container deployed on node."})
    except Exception as e:
        return jsonify({"message": f"Deployment failed on node: {str(e)}"}), 500

@app.route('/api/vps/post-deploy', methods=['POST'])
@require_api_key
def post_deploy():
    data = request.get_json() or {}
    name = data.get('name')
    vps_id = data.get('vps_id')
    password = data.get('password')
    site_name = data.get('site_name')

    if not all([name, vps_id, password]):
        return jsonify({"message": "Missing post-deployment parameters"}), 400

    try:
        import threading
        def run_setup():
            try:
                LXCManager.post_deploy_setup(
                    name=name,
                    vps_id=vps_id,
                    root_password=password,
                    site_name=site_name
                )
            except Exception as ex:
                print(f"[ERROR] Remote post_deploy_setup failed: {ex}")

        threading.Thread(target=run_setup).start()
        return jsonify({"status": "success", "message": "Post-deployment setup queued on node."})
    except Exception as e:
        return jsonify({"message": f"Post-deploy setup trigger failed: {str(e)}"}), 500

@app.route('/api/vps/action', methods=['POST'])
@require_api_key
def action():
    data = request.get_json() or {}
    name = data.get('name')
    action = data.get('action')
    vps_id = data.get('vps_id')

    if not name or not action:
        return jsonify({"message": "Missing name or action parameters"}), 400

    try:
        LXCManager.execute_action(name, action)
        if action in ['start', 'restart']:
            import threading
            threading.Thread(target=LXCManager.ensure_pinggy_tunnel_setup, args=(name,)).start()
        return jsonify({"status": "success", "message": f"Action '{action}' executed successfully."})
    except Exception as e:
        return jsonify({"message": f"Action failed: {str(e)}"}), 500

@app.route('/api/vps/rename', methods=['POST'])
@require_api_key
def rename():
    data = request.get_json() or {}
    old_name = data.get('old_name')
    new_name = data.get('new_name')

    if not old_name or not new_name:
        return jsonify({"message": "Missing old_name or new_name"}), 400

    try:
        LXCManager._run(["lxc", "move", old_name, new_name])
        return jsonify({"status": "success", "message": "Container renamed successfully."})
    except Exception as e:
        return jsonify({"message": f"Rename failed: {str(e)}"}), 500

@app.route('/api/vps/backup', methods=['POST'])
@require_api_key
def backup():
    data = request.get_json() or {}
    name = data.get('name')
    filename = data.get('filename')

    if not name or not filename:
        return jsonify({"message": "Missing name or filename"}), 400

    if IS_MOCK_LXC:
        import random
        size_str = f"{random.uniform(80.0, 160.0):.1f} MB"
        return jsonify({"status": "success", "message": "Backup created successfully.", "size": size_str})

    export_path = f"/tmp/{filename}"
    try:
        # Find lxc binary
        lxc_bin = 'lxc'
        if os.path.exists('/snap/bin/lxc'):
            lxc_bin = '/snap/bin/lxc'
        
        import subprocess
        subprocess.run(
            [lxc_bin, 'export', name, export_path],
            capture_output=True, text=True, check=True, timeout=300
        )
        file_size = os.path.getsize(export_path)
        if file_size > 1024 * 1024 * 1024:
            size_str = f"{file_size / (1024*1024*1024):.1f} GB"
        else:
            size_str = f"{file_size / (1024*1024):.1f} MB"
            
        return jsonify({"status": "success", "message": "Backup created successfully.", "size": size_str})
    except Exception as e:
        return jsonify({"message": f"Backup failed on node: {str(e)}"}), 500


@app.route('/api/vps/password', methods=['POST'])
@require_api_key
def change_password():
    data = request.get_json() or {}
    name = data.get('name')
    password = data.get('password')

    if not name or not password:
        return jsonify({"message": "Missing name or password"}), 400

    try:
        LXCManager.change_password(name, password)
        return jsonify({"status": "success", "message": "Password successfully updated."})
    except Exception as e:
        return jsonify({"message": f"Failed to change password: {str(e)}"}), 500

@app.route('/api/vps/stats', methods=['POST'])
@require_api_key
def stats():
    data = request.get_json() or {}
    name = data.get('name')
    cpu = int(data.get('cpu', 1))
    ram = int(data.get('ram', 512))
    disk = int(data.get('disk', 10))
    status = data.get('status', 'running')
    vps_id = data.get('vps_id')

    if not name:
        return jsonify({"message": "Missing container name"}), 400

    try:
        stats = LXCManager.get_container_stats(
            name=name,
            plan_cpu=cpu,
            plan_ram=ram,
            plan_disk=disk,
            db_status=status,
            vps_id=vps_id
        )
        return jsonify(stats)
    except Exception as e:
        return jsonify({"message": f"Failed to get stats: {str(e)}"}), 500

@app.route('/api/vps/snapshot', methods=['POST'])
@require_api_key
def snapshot_create():
    data = request.get_json() or {}
    name = data.get('name')
    snap_name = data.get('snap_name')

    if not name or not snap_name:
        return jsonify({"message": "Missing name or snap_name"}), 400

    try:
        LXCManager.create_snapshot(name, snap_name)
        return jsonify({"status": "success", "message": "Snapshot created."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/snapshot/restore', methods=['POST'])
@require_api_key
def snapshot_restore():
    data = request.get_json() or {}
    name = data.get('name')
    snap_name = data.get('snap_name')

    if not name or not snap_name:
        return jsonify({"message": "Missing name or snap_name"}), 400

    try:
        LXCManager.restore_snapshot(name, snap_name)
        return jsonify({"status": "success", "message": "Snapshot restored."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/snapshot/delete', methods=['POST'])
@require_api_key
def snapshot_delete():
    data = request.get_json() or {}
    name = data.get('name')
    snap_name = data.get('snap_name')

    if not name or not snap_name:
        return jsonify({"message": "Missing name or snap_name"}), 400

    try:
        LXCManager.delete_snapshot(name, snap_name)
        return jsonify({"status": "success", "message": "Snapshot deleted."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/destroy', methods=['POST'])
@require_api_key
def destroy():
    data = request.get_json() or {}
    name = data.get('name')

    if not name:
        return jsonify({"message": "Missing container name"}), 400

    try:
        LXCManager.destroy_container(name)
        return jsonify({"status": "success", "message": "Container destroyed."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

# Helper to start Pinggy tunnel and register with the master panel dynamically
def start_pinggy_tunnel(local_port, panel_url, node_id, api_key):
    import subprocess
    import re
    import time
    import urllib.request
    import json
    import threading

    def tunnel_thread():
        print(f"[*] Starting Pinggy tunnel background thread for local port {local_port}...")
        while True:
            try:
                # Start SSH tunnel to Pinggy forwarding daemon port
                cmd = [
                    "ssh", "-T", "-p", "443",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null",
                    "-o", "ServerAliveInterval=30",
                    f"-R0:127.0.0.1:{local_port}",
                    "tcp@free.pinggy.io"
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                for line in iter(proc.stdout.readline, ''):
                    print(f"[Pinggy Tunnel Log] {line.strip()}")
                    # Look for tcp://rporty-XXXXX.free.pinggy.link:XXXXX
                    match = re.search(r"tcp://([a-zA-Z0-9.-]+):(\d+)", line)
                    if match:
                        host = match.group(1)
                        port = int(match.group(2))
                        print(f"[+] Pinggy tunnel established: {host}:{port}")
                        register_tunnel_with_panel(panel_url, node_id, api_key, host, port)
                        
                proc.wait()
                print("[-] Pinggy tunnel process exited. Restarting in 5 seconds...")
            except Exception as e:
                print(f"[!] Error in Pinggy tunnel: {e}")
            time.sleep(5)

    def register_tunnel_with_panel(panel_url, node_id, api_key, host, port):
        if not panel_url:
            return
        url = f"{panel_url.rstrip('/')}/api/nodes/register_tunnel"
        payload = {
            "node_id": node_id,
            "api_key": api_key,
            "fqdn": host,
            "port": port
        }
        req_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                print(f"[+] Registered tunnel with panel: {res}")
        except Exception as e:
            print(f"[!] Failed to register tunnel with panel at {url}: {e}")

    t = threading.Thread(target=tunnel_thread, daemon=True)
    t.start()


if __name__ == '__main__':
    port = config.get('port', 5001)
    
    # Start the tunnel if panel_url is configured and this is not the local node
    panel_url = config.get('panel_url')
    node_id = config.get('node_id')
    api_key = config.get('api_key')
    if panel_url and node_id and api_key and node_id != 1:
        start_pinggy_tunnel(port, panel_url, node_id, api_key)

    print(f"[*] Starting MintyHost Node Daemon on port {port}...")
    app.run(host='0.0.0.0', port=port)
