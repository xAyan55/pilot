import os
import sys
import json
import time
import threading
import subprocess
import socket
import re
import urllib.request

def load_config():
    config = {
        'port': 5001,
        'api_key': 'default-node-key',
        'node_id': 0,
        'name': 'Remote Node',
        'panel_url': '',
        'cloudflare_domain': ''
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

try:
    from lxc_manager import LXCManager, IS_MOCK_LXC
except ImportError:
    print("[!] Could not import LXCManager. Make sure daemon.py is in the lxc project directory.")
    sys.exit(1)

from flask import Flask, request, jsonify
app = Flask(__name__)

PORT_FORWARD_LOCK = threading.Lock()
PORT_FORWARD_RANGE = range(22000, 22999)
_allocated_ports = {}


def _port_forwards_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'port_forwards.json')


def _load_port_forwards_from_disk():
    path = _port_forwards_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    _allocated_ports[k] = int(v)
                except Exception:
                    pass
    except Exception as e:
        print(f"[!] Failed to load port_forwards.json: {e}")


def _reapply_port_forwards_from_disk():
    """After load, re-create iptables DNAT rules from the persisted map."""
    with PORT_FORWARD_LOCK:
        for key, port in list(_allocated_ports.items()):
            try:
                name = key.split('__rdp', 1)[0] if key.endswith('__rdp') else key
                container_ip = get_container_ip(name)
                if not container_ip:
                    continue
                if key.endswith('__rdp'):
                    dest_port = 3389
                else:
                    dest_port = 22
                subprocess.run(
                    ['iptables', '-t', 'nat', '-A', 'PREROUTING', '-p', 'tcp',
                     '--dport', str(port), '-j', 'DNAT', '--to-destination', f'{container_ip}:{dest_port}'],
                    capture_output=True, timeout=5, check=False
                )
                subprocess.run(
                    ['iptables', '-A', 'FORWARD', '-p', 'tcp', '-d', container_ip,
                     '--dport', str(dest_port), '-j', 'ACCEPT'],
                    capture_output=True, timeout=5, check=False
                )
                print(f"[+] Re-applied port forward :{port} -> {container_ip}:{dest_port} ({name})")
            except Exception as e:
                print(f"[!] Failed to re-apply port forward for {key}: {e}")


_load_port_forwards_from_disk()

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
        "is_mock": IS_MOCK_LXC,
        "version": "2.0-cloudflare"
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
        LXCManager.deploy_container(name=name, os_image=os_image, cpu_cores=cpu, ram_mb=ram, disk_gb=disk, root_password=password)
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
        def run_setup():
            try:
                LXCManager.post_deploy_setup(name=name, vps_id=vps_id, root_password=password, site_name=site_name)
                setup_port_forward(name, vps_id)
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
    if not name or not action:
        return jsonify({"message": "Missing name or action parameters"}), 400
    try:
        LXCManager.execute_action(name, action)
        if action in ['start', 'restart']:
            remove_port_forward(name)
            vps_id = data.get('vps_id')
            if vps_id:
                setup_port_forward(name, vps_id)
        if action in ['stop', 'suspend']:
            remove_port_forward(name)
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
        with PORT_FORWARD_LOCK:
            if old_name in _allocated_ports:
                _allocated_ports[new_name] = _allocated_ports.pop(old_name)
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
        lxc_bin = subprocess.check_output(['which', 'lxc']).strip().decode() if not IS_MOCK_LXC else 'lxc'
        if os.path.exists('/snap/bin/lxc'):
            lxc_bin = '/snap/bin/lxc'
        subprocess.run([lxc_bin, 'export', name, export_path], capture_output=True, text=True, check=True, timeout=300)
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
        stats = LXCManager.get_container_stats(name=name, plan_cpu=cpu, plan_ram=ram, plan_disk=disk, db_status=status, vps_id=vps_id)
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
        remove_port_forward(name)
        LXCManager.destroy_container(name)
        return jsonify({"status": "success", "message": "Container destroyed."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/port-forward', methods=['POST'])
@require_api_key
def get_port_forward():
    data = request.get_json() or {}
    name = data.get('name')
    with PORT_FORWARD_LOCK:
        if name in _allocated_ports:
            return jsonify({"name": name, "port": _allocated_ports[name]})
    return jsonify({"name": name, "port": None})

def get_container_ip(name):
    if IS_MOCK_LXC:
        ip_suffix = sum(ord(c) for c in name) % 250 + 4
        return f"10.155.88.{ip_suffix}"
    try:
        out = subprocess.run(
            [LXCManager.LXC_BIN, 'list', name, '--format=json'],
            capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0:
            data = json.loads(out.stdout)
            for container in data:
                if container.get('name') == name:
                    state = container.get('state') or {}
                    network = state.get('network') or {}
                    for iface_name, iface_info in network.items():
                        if iface_name == 'lo':
                            continue
                        for addr in iface_info.get('addresses', []):
                            if addr.get('family') == 'inet':
                                return addr.get('address')
    except Exception as e:
        print(f"[!] Error getting IP for {name}: {e}")
    return None

def remove_port_forward(name):
    with PORT_FORWARD_LOCK:
        port = _allocated_ports.pop(name, None)
    if port and not IS_MOCK_LXC:
        try:
            subprocess.run(
                ['iptables', '-t', 'nat', '-D', 'PREROUTING', '-p', 'tcp', '--dport', str(port), '-j', 'DNAT', '--to-destination', ':22'],
                capture_output=True, timeout=5, check=False
            )
            subprocess.run(
                ['iptables', '-D', 'FORWARD', '-p', 'tcp', '--dport', '22', '-j', 'ACCEPT'],
                capture_output=True, timeout=5, check=False
            )
            rdp_key = f"{name}__rdp"
            rdp_port = _allocated_ports.pop(rdp_key, None)
            if rdp_port:
                subprocess.run(
                    ['iptables', '-t', 'nat', '-D', 'PREROUTING', '-p', 'tcp', '--dport', str(rdp_port), '-j', 'DNAT', '--to-destination', ':3389'],
                    capture_output=True, timeout=5, check=False
                )
            print(f"[+] Removed port forward {port} -> {name}:22 (and RDP {rdp_port})")
        except Exception as e:
            print(f"[!] Failed to remove port forward for {name}: {e}")


def _is_windows_vm(name):
    if IS_MOCK_LXC:
        return False
    try:
        out = subprocess.run(
            [LXCManager.LXC_BIN, 'config', 'get', name, 'image.os'],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and 'windows' in out.stdout.lower():
            return True
    except Exception:
        pass
    return False


def setup_port_forward(name, vps_id):
    if IS_MOCK_LXC:
        return None
    container_ip = get_container_ip(name)
    if not container_ip:
        print(f"[!] Cannot set up port forward: no IP for {name}")
        return None
    is_win = _is_windows_vm(name)
    with PORT_FORWARD_LOCK:
        if name in _allocated_ports:
            port = _allocated_ports[name]
        else:
            used = set(_allocated_ports.values())
            for p in PORT_FORWARD_RANGE:
                if p not in used:
                    port = p
                    _allocated_ports[name] = port
                    break
            else:
                port = 40000 + vps_id
                _allocated_ports[name] = port
    try:
        check = subprocess.run(
            ['iptables', '-t', 'nat', '-C', 'PREROUTING', '-p', 'tcp', '--dport', str(port), '-j', 'DNAT', '--to-destination', f'{container_ip}:22'],
            capture_output=True, timeout=5, check=False
        )
        if check.returncode != 0:
            subprocess.run(
                ['iptables', '-t', 'nat', '-A', 'PREROUTING', '-p', 'tcp', '--dport', str(port), '-j', 'DNAT', '--to-destination', f'{container_ip}:22'],
                capture_output=True, timeout=5, check=False
            )
        subprocess.run(
            ['iptables', '-A', 'FORWARD', '-p', 'tcp', '-d', container_ip, '--dport', '22', '-j', 'ACCEPT'],
            capture_output=True, timeout=5, check=False
        )
        print(f"[+] Port forward set: :{port} -> {container_ip}:22 ({name})")
        if is_win:
            rdp_key = f"{name}__rdp"
            rdp_port = port + 1000
            _allocated_ports[rdp_key] = rdp_port
            rdp_check = subprocess.run(
                ['iptables', '-t', 'nat', '-C', 'PREROUTING', '-p', 'tcp', '--dport', str(rdp_port), '-j', 'DNAT', '--to-destination', f'{container_ip}:3389'],
                capture_output=True, timeout=5, check=False
            )
            if rdp_check.returncode != 0:
                subprocess.run(
                    ['iptables', '-t', 'nat', '-A', 'PREROUTING', '-p', 'tcp', '--dport', str(rdp_port), '-j', 'DNAT', '--to-destination', f'{container_ip}:3389'],
                    capture_output=True, timeout=5, check=False
                )
            subprocess.run(
                ['iptables', '-A', 'FORWARD', '-p', 'tcp', '-d', container_ip, '--dport', '3389', '-j', 'ACCEPT'],
                capture_output=True, timeout=5, check=False
            )
            print(f"[+] RDP port forward set: :{rdp_port} -> {container_ip}:3389 ({name})")
            _write_port_forwards_to_disk()
        return port
    except Exception as e:
        print(f"[!] Failed to set port forward for {name} on {container_ip}:22: {e}")
        return None


def _write_port_forwards_to_disk():
    try:
        with open(_port_forwards_path(), 'w') as f:
            json.dump(_allocated_ports, f)
    except Exception:
        pass

def get_public_ip():
    try:
        req = urllib.request.Request('https://api.ipify.org?format=json')
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())['ip']
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None

def connect_panel_websocket(panel_url, node_id, api_key):
    try:
        import socketio
    except ImportError:
        print("[!] python-socketio not installed. WebSocket connection unavailable.")
        return
    def run_ws():
        sio = socketio.Client()
        known_config = config
        @sio.on('connect')
        def on_connect():
            print(f"[WS] Connected to panel {panel_url}")
            sio.emit('node_auth', {
                'node_id': node_id,
                'api_key': api_key,
                'name': known_config.get('name'),
                'daemon_port': known_config.get('port'),
                'public_ip': get_public_ip(),
                'version': '2.0'
            })
        @sio.on('node_authenticated')
        def on_authenticated(data):
            print(f"[WS] Panel authenticated node: {data}")
            def heartbeat():
                while sio.connected:
                    sio.emit('node_heartbeat', {'node_id': node_id})
                    time.sleep(10)
            threading.Thread(target=heartbeat, daemon=True).start()
            def stats_push():
                while sio.connected:
                    try:
                        if IS_MOCK_LXC:
                            time.sleep(30)
                            continue
                        out = subprocess.run(
                            [LXCManager.LXC_BIN, 'list', '--format=json'],
                            capture_output=True, text=True, timeout=10
                        )
                        if out.returncode == 0:
                            containers = json.loads(out.stdout)
                            for c in containers:
                                cname = c.get('name', '')
                                if cname:
                                    try:
                                        stats = LXCManager.get_container_stats(name=cname, vps_id=0)
                                        if stats:
                                            sio.emit('container_stats', {
                                                'node_id': node_id,
                                                'container_name': cname,
                                                'stats': stats
                                            })
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    time.sleep(15)
            threading.Thread(target=stats_push, daemon=True).start()
        @sio.on('node_task')
        def on_task(task):
            task_id = task.get('id')
            action = task.get('action')
            data = task.get('data', {})
            print(f"[WS] Task received: {action} (id={task_id})")
            result = {'success': False, 'message': 'Unknown action'}
            try:
                if action == 'deploy':
                    LXCManager.deploy_container(**data)
                    result = {'success': True, 'message': 'Container deployed'}
                elif action == 'destroy':
                    remove_port_forward(data.get('name'))
                    LXCManager.destroy_container(data.get('name'))
                    result = {'success': True, 'message': 'Container destroyed'}
                elif action == 'action':
                    LXCManager.execute_action(data.get('name'), data.get('action'))
                    if data.get('action') in ['start', 'restart']:
                        setup_port_forward(data.get('name'), data.get('vps_id'))
                    if data.get('action') in ['stop', 'suspend']:
                        remove_port_forward(data.get('name'))
                    result = {'success': True, 'message': f"Action {data.get('action')} done"}
                elif action == 'post_deploy':
                    LXCManager.post_deploy_setup(**data)
                    setup_port_forward(data.get('name'), data.get('vps_id'))
                    result = {'success': True, 'message': 'Post-deploy done'}
                elif action == 'password':
                    LXCManager.change_password(data.get('name'), data.get('password'))
                    result = {'success': True, 'message': 'Password changed'}
                elif action == 'stats':
                    s = LXCManager.get_container_stats(name=data.get('name'))
                    result = {'success': True, 'stats': s}
                elif action == 'snapshot':
                    LXCManager.create_snapshot(data.get('name'), data.get('snap_name'))
                    result = {'success': True}
                elif action == 'snapshot_restore':
                    LXCManager.restore_snapshot(data.get('name'), data.get('snap_name'))
                    result = {'success': True}
                elif action == 'snapshot_delete':
                    LXCManager.delete_snapshot(data.get('name'), data.get('snap_name'))
                    result = {'success': True}
                elif action == 'backup':
                    name = data.get('name')
                    filename = data.get('filename')
                    lxc_bin = LXCManager.LXC_BIN
                    subprocess.run([lxc_bin, 'export', name, f'/tmp/{filename}'], capture_output=True, text=True, check=True, timeout=300)
                    result = {'success': True, 'message': 'Backup created'}
                elif action == 'port_forward':
                    port = setup_port_forward(data.get('name'), data.get('vps_id'))
                    result = {'success': True, 'port': port}
            except Exception as e:
                result = {'success': False, 'message': str(e)}
            try:
                if sio.connected:
                    sio.emit('node_task_result', {'task_id': task_id, 'node_id': node_id, 'result': result})
            except Exception:
                pass

        # Store active terminal processes per session
        node_terminal_processes = {}

        def cleanup_node_terminal(session_id):
            term = node_terminal_processes.pop(session_id, None)
            if term:
                try:
                    os.close(term['master_fd'])
                except OSError:
                    pass
                try:
                    term['process'].terminate()
                    term['process'].wait(timeout=3)
                except Exception:
                    try:
                        term['process'].kill()
                    except Exception:
                        pass
                print(f"[WS] Cleaned up remote terminal session {session_id}")

        @sio.on('terminal_start')
        def on_terminal_start(data):
            session_id = data.get('session_id')
            container_name = data.get('container_name')
            if not session_id or not container_name:
                return

            try:
                import pty
                import select
                import struct
                import fcntl
                import termios
                HAS_PTY = True
            except ImportError:
                HAS_PTY = False

            if not HAS_PTY:
                sio.emit('node_terminal_output', {
                    'session_id': session_id,
                    'output': '\r\n[ERROR] Terminal PTY not supported on this platform.\r\n'
                })
                return

            try:
                # Stop existing session if any
                if session_id in node_terminal_processes:
                    cleanup_node_terminal(session_id)
                    
                master_fd, slave_fd = pty.openpty()
                
                # Check LXC path
                lxc_bin = LXCManager.LXC_BIN
                
                process = subprocess.Popen(
                    [lxc_bin, 'exec', container_name, '--env', 'TERM=xterm-256color', '--', '/bin/bash'],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    preexec_fn=os.setsid,
                    close_fds=True
                )
                os.close(slave_fd)
                
                node_terminal_processes[session_id] = {
                    'master_fd': master_fd,
                    'process': process,
                    'container': container_name
                }
                
                # Emit empty output to confirm start
                sio.emit('node_terminal_output', {
                    'session_id': session_id,
                    'output': ''
                })

                def read_output():
                    while True:
                        try:
                            # Standard thread sleep
                            time.sleep(0.01)
                            if process.poll() is not None:
                                sio.emit('node_terminal_output', {
                                    'session_id': session_id,
                                    'output': '\r\n[Session ended]\r\n'
                                })
                                break
                            r, _, _ = select.select([master_fd], [], [], 0.02)
                            if master_fd in r:
                                output = os.read(master_fd, 4096)
                                if output:
                                    sio.emit('node_terminal_output', {
                                        'session_id': session_id,
                                        'output': output.decode('utf-8', errors='replace')
                                    })
                                else:
                                    break
                        except OSError:
                            break
                        except Exception:
                            break
                    # Cleanup
                    cleanup_node_terminal(session_id)

                threading.Thread(target=read_output, daemon=True).start()
                print(f"[WS] Started remote terminal session {session_id} for {container_name}")

            except Exception as e:
                sio.emit('node_terminal_output', {
                    'session_id': session_id,
                    'output': f'\r\n[ERROR] Failed to start terminal: {str(e)}\r\n'
                })

        @sio.on('terminal_input')
        def on_terminal_input(data):
            session_id = data.get('session_id')
            term_input = data.get('input')
            term = node_terminal_processes.get(session_id)
            if term:
                try:
                    os.write(term['master_fd'], term_input.encode('utf-8'))
                except OSError:
                    cleanup_node_terminal(session_id)

        @sio.on('terminal_resize')
        def on_terminal_resize(data):
            session_id = data.get('session_id')
            cols = data.get('cols', 80)
            rows = data.get('rows', 24)
            term = node_terminal_processes.get(session_id)
            if term:
                try:
                    import struct
                    import fcntl
                    import termios
                    winsize = struct.pack('HHHH', rows, cols, 0, 0)
                    fcntl.ioctl(term['master_fd'], termios.TIOCSWINSZ, winsize)
                except Exception:
                    pass

        @sio.on('terminal_stop')
        def on_terminal_stop(data):
            session_id = data.get('session_id')
            cleanup_node_terminal(session_id)

        @sio.on('disconnect')
        def on_disconnect():
            print("[-] Panel WebSocket disconnected. Reconnecting in 10s...")
            for session_id in list(node_terminal_processes.keys()):
                cleanup_node_terminal(session_id)

        ws_url = panel_url.rstrip('/').replace('http://', 'ws://').replace('https://', 'wss://')
        while True:
            try:
                print(f"[WS] Connecting to {ws_url}/ws/node...")
                sio.connect(f"{ws_url}/ws/node", wait_timeout=15)
                sio.wait()
            except Exception as e:
                print(f"[!] WebSocket error: {e}")
            time.sleep(10)
    threading.Thread(target=run_ws, daemon=True).start()
@app.route('/api/vps/files', methods=['GET', 'DELETE'])
@require_api_key
def vps_files():
    name = request.args.get('name')
    path = request.args.get('path', '/root')
    if not name:
        return jsonify({"message": "Missing container name"}), 400
    try:
        if request.method == 'GET':
            items = LXCManager.list_files(name, path)
            return jsonify({"status": "success", "path": path, "items": items})
        elif request.method == 'DELETE':
            LXCManager.delete_file(name, path)
            return jsonify({"status": "success", "message": "Deleted successfully."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/files/content', methods=['GET', 'POST'])
@require_api_key
def vps_files_content():
    if request.method == 'GET':
        name = request.args.get('name')
        path = request.args.get('path')
        if not name or not path:
            return jsonify({"message": "name and path are required"}), 400
        try:
            content = LXCManager.read_file(name, path)
            return jsonify({"status": "success", "path": path, "content": content})
        except Exception as e:
            return jsonify({"message": str(e)}), 500
    elif request.method == 'POST':
        data = request.get_json() or {}
        name = data.get('name')
        path = data.get('path')
        content = data.get('content', '')
        if not name or not path:
            return jsonify({"message": "name and path are required"}), 400
        try:
            LXCManager.write_file(name, path, content)
            return jsonify({"status": "success", "message": "File saved successfully."})
        except Exception as e:
            return jsonify({"message": str(e)}), 500

@app.route('/api/vps/files/directory', methods=['POST'])
@require_api_key
def vps_files_directory():
    data = request.get_json() or {}
    name = data.get('name')
    path = data.get('path')
    if not name or not path:
        return jsonify({"message": "name and path are required"}), 400
    try:
        LXCManager.create_directory(name, path)
        return jsonify({"status": "success", "message": "Directory created."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/files/upload', methods=['POST'])
@require_api_key
def vps_files_upload():
    data = request.get_json() or {}
    name = data.get('name')
    path = data.get('path')
    content_b64 = data.get('content_b64')
    if not name or not path or content_b64 is None:
        return jsonify({"message": "name, path, and content_b64 are required"}), 400
    try:
        import base64
        file_bytes = base64.b64decode(content_b64)
        LXCManager.write_file_bin(name, path, file_bytes)
        return jsonify({"status": "success", "message": "File uploaded successfully."})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/vps/files/download', methods=['GET'])
@require_api_key
def vps_files_download():
    name = request.args.get('name')
    path = request.args.get('path')
    if not name or not path:
        return jsonify({"message": "name and path are required"}), 400
    try:
        import base64
        file_bytes = LXCManager.read_file_bin(name, path)
        content_b64 = base64.b64encode(file_bytes).decode('utf-8')
        filename = os.path.basename(path)
        return jsonify({
            "status": "success",
            "filename": filename,
            "content_b64": content_b64
        })
    except Exception as e:
        return jsonify({"message": str(e)}), 500

if __name__ == '__main__':
    port = config.get('port', 5001)
    panel_url = config.get('panel_url')
    node_id = config.get('node_id')
    api_key = config.get('api_key')
    if panel_url and node_id and api_key and node_id != 1:
        connect_panel_websocket(panel_url, node_id, api_key)
    try:
        _reapply_port_forwards_from_disk()
    except Exception as e:
        print(f"[!] Could not re-apply port forwards on startup: {e}")
    print(f"[*] Starting MintyHost Node Daemon v2.0 (Cloudflare Native) on port {port}...")
    app.run(host='0.0.0.0', port=port)
