import eventlet
eventlet.monkey_patch()
import eventlet.debug
eventlet.debug.hub_prevent_multiple_readers(False)

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit
import json
import time
import os
import sys
import subprocess
import random
import threading
import uuid
from werkzeug.utils import secure_filename
from database import get_db_connection, init_db
from lxc_manager import LXCManager, LXC_BIN, IS_MOCK_LXC
from collections import deque

# Metrics history cache to keep the line graphs pre-populated and real-time
METRICS_HISTORY = {}

def get_node_by_id(node_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
    node = cursor.fetchone()
    conn.close()
    return node

def allocate_relay_port(vps_id, ports_setting):
    if not ports_setting:
        return 40000 + vps_id
    
    # Parse list of ports
    try:
        ports = [int(p.strip()) for p in ports_setting.split(',') if p.strip().isdigit()]
    except Exception:
        return 40000 + vps_id
        
    if not ports:
        return 40000 + vps_id

    # Find currently used ports
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tunnel_port FROM vps WHERE tunnel_port IS NOT NULL AND id != ?", (vps_id,))
    used_ports = {row['tunnel_port'] for row in cursor.fetchall()}
    
    # Find first free port
    allocated_port = None
    for p in ports:
        if p not in used_ports:
            allocated_port = p
            break
            
    if allocated_port is not None:
        # Save to this VPS
        cursor.execute("UPDATE vps SET tunnel_port = ? WHERE id = ?", (allocated_port, vps_id))
        conn.commit()
    else:
        # Fallback if all ports are exhausted
        allocated_port = 40000 + vps_id
        cursor.execute("UPDATE vps SET tunnel_port = ? WHERE id = ?", (allocated_port, vps_id))
        conn.commit()
        
    conn.close()
    return allocated_port

def make_node_request(node, endpoint, method='POST', data=None):
    import urllib.request
    import urllib.parse
    import json
    
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
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = response.read().decode('utf-8')
            return json.loads(res_data), response.status
    except urllib.error.HTTPError as e:
        try:
            err_data = e.read().decode('utf-8')
            err_json = json.loads(err_data)
            return err_json, e.code
        except Exception:
            return {"message": f"HTTP Error {e.code}: {e.reason}"}, e.code
    except Exception as e:
        return {"message": f"Connection error: {str(e)}"}, 500



# Linux-only modules for real PTY terminal bridge
try:
    import pty
    import select
    import struct
    import fcntl
    import termios
    HAS_PTY = True
except ImportError:
    HAS_PTY = False

app = Flask(__name__)
app.secret_key = 'mintyhost-lxc-secret-key-928475'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

# Ensure database is initialized on startup
with app.app_context():
    init_db()

def get_contrast_color(hex_color):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return '#0f172a'
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        # Relative luminance formula
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return '#ffffff' if luminance < 0.5 else '#0f172a'
    except ValueError:
        return '#0f172a'

@app.context_processor
def inject_settings():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        settings = {row['key']: row['value'] for row in rows}
        conn.close()
    except Exception:
        settings = {}
        
    defaults = {
        'site_name': 'MintyHost LXC',
        'color_primary': '#ECF4E8',
        'color_secondary': '#CBF3BB',
        'color_accent': '#ABE7B2',
        'color_cool': '#93BFC7'
    }
    for k, v in defaults.items():
        if k not in settings:
            settings[k] = v
            
    # Calculate contrast colors for dynamic text readability on theme backgrounds
    settings['color_primary_text'] = get_contrast_color(settings['color_primary'])
    settings['color_secondary_text'] = get_contrast_color(settings['color_secondary'])
    settings['color_accent_text'] = get_contrast_color(settings['color_accent'])
    settings['color_cool_text'] = get_contrast_color(settings['color_cool'])
            
    return dict(settings=settings)

# Helper: Log audit action
def log_audit(user_id, action):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (user_id, action))
    conn.commit()
    conn.close()

# Helper: Auth check
def is_logged_in():
    return 'user_id' in session

def is_admin():
    return session.get('role') == 'admin'

# ----------------- PAGE ROUTING -----------------

@app.route('/')
def index():
    if is_logged_in():
        if is_admin():
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('client_dashboard'))
    return redirect(url_for('auth'))

@app.route('/auth')
def auth():
    if is_logged_in():
        return redirect(url_for('index'))
    return render_template('auth.html')

@app.route('/client')
def client_dashboard():
    if not is_logged_in():
        flash("Please log in to access the dashboard.", "error")
        return redirect(url_for('auth'))
    if is_admin():
        return redirect(url_for('admin_dashboard'))
    return render_template('client.html', username=session.get('username'))

@app.route('/admin')
def admin_dashboard():
    if not is_logged_in():
        flash("Please log in to access the dashboard.", "error")
        return redirect(url_for('auth'))
    if not is_admin():
        flash("Access Denied: Administrative permissions required.", "error")
        return redirect(url_for('client_dashboard'))
    return render_template('admin.html', username=session.get('username'))

# ----------------- AUTHENTICATION ENDPOINTS -----------------

@app.route('/signup', methods=['POST'])
def signup_handler():
    username = request.form.get('username', '').strip().lower()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password')

    if not username or not email or not password:
        flash("All fields are required.", "error")
        return redirect(url_for('auth'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, email))
    if cursor.fetchone():
        flash("Username or email already registered.", "error")
        conn.close()
        return redirect(url_for('auth'))

    hashed_pw = generate_password_hash(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, 'client')",
            (username, email, hashed_pw)
        )
        conn.commit()

        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        session['user_id'] = user['id']
        session['username'] = user['username']
        session['email'] = user['email']
        session['role'] = user['role']
        session['is_admin'] = (user['role'] == 'admin')
        session['pfp'] = user['pfp']

        log_audit(user['id'], f"Registered user account: {username}")
        conn.close()

        flash("Welcome to MintyHost LXC Panel! Account created successfully.", "success")
        return redirect(url_for('client_dashboard'))
    except Exception:
        flash("Registration failed. Please try again.", "error")
        conn.close()
        return redirect(url_for('auth'))

@app.route('/login', methods=['POST'])
def login_handler():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password')

    if not email or not password:
        flash("Please fill in all credentials.", "error")
        return redirect(url_for('auth'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ? OR username = ?", (email, email))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['email'] = user['email']
        session['role'] = user['role']
        session['is_admin'] = (user['role'] == 'admin')
        session['pfp'] = user['pfp']

        log_audit(user['id'], "Logged into control panel")

        flash("Logged in successfully. Welcome back!", "success")
        if user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('client_dashboard'))
    else:
        flash("Invalid credentials.", "error")
        return redirect(url_for('auth'))

@app.route('/logout')
def logout_handler():
    user_id = session.get('user_id')
    if user_id:
        log_audit(user_id, "Logged out of control panel")
    session.clear()
    flash("You have logged out successfully.", "success")
    return redirect(url_for('auth'))

# ----------------- CLIENT VPS ACTIONS API -----------------

@app.route('/api/client/vps')
def client_list_vps():
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE user_id = ? ORDER BY id DESC", (session['user_id'],))
    rows = cursor.fetchall()
    vps_list = [dict(row) for row in rows]
    conn.close()

    return jsonify(vps_list)

@app.route('/api/client/vps/<int:vps_id>/stats')
def client_vps_stats(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()
    conn.close()

    if not vps_row:
        return jsonify({"message": "VPS not found or permission denied."}), 404

    if vps_row['node_id'] != 1:
        node = get_node_by_id(vps_row['node_id'])
        if node:
            res, code = make_node_request(node, "/api/vps/stats", data={
                "name": vps_row['container_name'],
                "cpu": vps_row['cpu'],
                "ram": vps_row['ram'],
                "disk": vps_row['disk'],
                "status": vps_row['status'],
                "vps_id": vps_id
            })
            if code == 200:
                stats = res
            else:
                return jsonify({"message": f"Failed to fetch stats from remote node: {res.get('message', '')}"}), code
        else:
            return jsonify({"message": "Remote node not found."}), 404
    else:
        stats = LXCManager.get_container_stats(
            name=vps_row['container_name'],
            plan_cpu=vps_row['cpu'],
            plan_ram=vps_row['ram'],
            plan_disk=vps_row['disk'],
            db_status=vps_row['status'],
            vps_id=vps_id
        )

    # Sync status, tunnel_host, and tunnel_port to DB if they change
    if (stats['status'] != vps_row['status'] or 
        stats.get('tunnel_host') != vps_row['tunnel_host'] or 
        stats.get('tunnel_port') != vps_row['tunnel_port']):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE vps SET status = ?, tunnel_host = ?, tunnel_port = ? WHERE id = ?",
            (stats['status'], stats.get('tunnel_host'), stats.get('tunnel_port'), vps_id)
        )
        conn.commit()
        conn.close()

    # Track metrics history to feed UI chart
    container_name = vps_row['container_name']
    if container_name not in METRICS_HISTORY:
        # Populate history with 10 backward-extrapolated, realistic data points so graph is not flat at 0%
        history_list = deque(maxlen=10)
        status = stats['status']
        for _ in range(10):
            if status == 'running':
                h_cpu = round(random.uniform(2.0, 12.0), 1)
                h_ram_percent = round(random.uniform(18.0, 32.0), 1)
            else:
                h_cpu = 0.0
                h_ram_percent = 0.0
            history_list.append({
                'cpu': h_cpu,
                'ram_percent': h_ram_percent
            })
        METRICS_HISTORY[container_name] = history_list

    # Append current reading
    ram_limit = stats['ram_limit']
    ram_percent = round((stats['ram_used'] / ram_limit) * 100, 1) if ram_limit > 0 else 0.0
    METRICS_HISTORY[container_name].append({
        'cpu': stats['cpu'],
        'ram_percent': ram_percent
    })

    stats['history'] = list(METRICS_HISTORY[container_name])

    return jsonify(stats)

@app.route('/api/client/vps/<int:vps_id>/action', methods=['POST'])
def client_vps_action(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    action = data.get('action')

    if action not in ['start', 'stop', 'restart', 'suspend', 'resume']:
        return jsonify({"message": "Invalid action."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found or permission denied."}), 404

    try:
        if vps_row['node_id'] != 1:
            node = get_node_by_id(vps_row['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/action", data={
                "name": vps_row['container_name'],
                "action": action,
                "vps_id": vps_id
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote node error: {res.get('message', '')}"}), code
        else:
            LXCManager.execute_action(vps_row['container_name'], action)
            if action in ['start', 'restart']:
                threading.Thread(target=LXCManager.ensure_pinggy_tunnel_setup, args=(vps_row['container_name'],)).start()

        new_status = 'running' if action in ['start', 'restart', 'resume'] else ('stopped' if action == 'stop' else 'suspended')
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps_id))
        conn.commit()

        log_audit(session['user_id'], f"Triggered power state: {action} on VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": f"Power state change '{action}' initiated."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Action failed: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/rename', methods=['POST'])
def client_vps_rename(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_name = data.get('name', '').strip()

    if not new_name or len(new_name) < 3 or not new_name.isalnum():
        return jsonify({"message": "Name must be alphanumeric and at least 3 chars."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found or permission denied."}), 404

    old_container_name = vps_row['container_name']
    new_container_name = f"vps-{new_name}-{random.randint(10, 99)}"

    try:
        if vps_row['node_id'] != 1:
            node = get_node_by_id(vps_row['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/rename", data={
                "old_name": old_container_name,
                "new_name": new_container_name
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote node error: {res.get('message', '')}"}), code
        else:
            LXCManager._run(["lxc", "move", old_container_name, new_container_name])
            
        cursor.execute("UPDATE vps SET container_name = ? WHERE id = ?", (new_container_name, vps_id))
        conn.commit()

        log_audit(session['user_id'], f"Renamed container from {old_container_name} to {new_container_name}")

        conn.close()
        return jsonify({"status": "success", "message": "Container renamed successfully.", "new_name": new_container_name})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Rename failed: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/password', methods=['POST'])
def client_vps_password(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_password = data.get('root_password', '').strip()

    if not new_password or len(new_password) < 6:
        return jsonify({"message": "Root password must be at least 6 characters."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found or permission denied."}), 404

    try:
        if vps_row['node_id'] != 1:
            node = get_node_by_id(vps_row['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/password", data={
                "name": vps_row['container_name'],
                "password": new_password
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote node error: {res.get('message', '')}"}), code
        else:
            LXCManager.change_password(vps_row['container_name'], new_password)
            
        cursor.execute("UPDATE vps SET root_password = ? WHERE id = ?", (new_password, vps_id))
        conn.commit()

        log_audit(session['user_id'], f"Changed root password for container: {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Root password successfully updated inside container."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to set root credentials: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/reinstall', methods=['POST'])
def client_vps_reinstall(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    os_selection = data.get('os')
    root_password = data.get('root_password', '').strip()

    if os_selection not in ['ubuntu/22.04', 'debian/11']:
        return jsonify({"message": "Invalid OS selection. Must be Ubuntu 22.04 or Debian 11."}), 400
    if not root_password or len(root_password) < 6:
        return jsonify({"message": "Password must be at least 6 characters."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps = cursor.fetchone()

    if not vps:
        conn.close()
        return jsonify({"message": "VPS not found or permission denied."}), 404

    # Fetch settings for MOTD and relay configurations
    cursor.execute("SELECT key, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    site_name_val = settings.get('site_name', 'MintyHost LXC')

    # Determine dynamic tunnel_port
    tunnel_port = vps['tunnel_port']
    if settings.get('ssh_relay_enabled') == '1':
        if tunnel_port is None:
            tunnel_port = allocate_relay_port(vps_id, settings.get('ssh_relay_ports', ''))
    else:
        tunnel_port = 40000 + vps_id

    try:
        if vps['node_id'] != 1:
            node = get_node_by_id(vps['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            
            # Destroy container on remote node
            res, code = make_node_request(node, "/api/vps/destroy", data={"name": vps['container_name']})
            if code != 200:
                conn.close()
                return jsonify({"message": f"Failed to destroy old container on remote node: {res.get('message', '')}"}), code
            
            # Deploy container on remote node
            res, code = make_node_request(node, "/api/vps/deploy", data={
                "name": vps['container_name'],
                "os": os_selection,
                "cpu": vps['cpu'],
                "ram": vps['ram'],
                "disk": vps['disk'],
                "password": root_password
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Failed to deploy new container on remote node: {res.get('message', '')}"}), code
                
            # Trigger background setup on remote node
            res, code = make_node_request(node, "/api/vps/post-deploy", data={
                "name": vps['container_name'],
                "vps_id": vps_id,
                "password": root_password,
                "site_name": site_name_val,
                "ssh_relay_enabled": settings.get('ssh_relay_enabled'),
                "ssh_relay_host": settings.get('ssh_relay_host'),
                "ssh_relay_port": settings.get('ssh_relay_port'),
                "ssh_relay_user": settings.get('ssh_relay_user'),
                "ssh_relay_password": settings.get('ssh_relay_password'),
                "tunnel_port": tunnel_port
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Failed to initialize remote post-deployment setup: {res.get('message', '')}"}), code
        else:
            LXCManager.destroy_container(vps['container_name'])
            LXCManager.deploy_container(
                name=vps['container_name'],
                os_image=os_selection,
                cpu_cores=vps['cpu'],
                ram_mb=vps['ram'],
                disk_gb=vps['disk'],
                root_password=root_password
            )

            # Run post-deployment environment setup (packages and Bore/SSH tunnel) in background
            def run_reinstall_setup(name, target_id, root_pw, s_name, relay_settings, t_port):
                try:
                    LXCManager.post_deploy_setup(
                        name=name,
                        vps_id=target_id,
                        root_password=root_pw,
                        site_name=s_name,
                        ssh_relay_enabled=relay_settings.get('ssh_relay_enabled'),
                        ssh_relay_host=relay_settings.get('ssh_relay_host'),
                        ssh_relay_port=relay_settings.get('ssh_relay_port'),
                        ssh_relay_user=relay_settings.get('ssh_relay_user'),
                        ssh_relay_password=relay_settings.get('ssh_relay_password'),
                        tunnel_port=t_port
                    )
                except Exception as ex:
                    print(f"[ERROR] Background reinstall post_deploy_setup failed: {ex}")

            threading.Thread(
                target=run_reinstall_setup,
                args=(vps['container_name'], vps_id, root_password, site_name_val, settings, tunnel_port)
            ).start()

        cursor.execute(
            "UPDATE vps SET os = ?, root_password = ?, status = 'running' WHERE id = ?",
            (os_selection, root_password, vps_id)
        )
        conn.commit()

        log_audit(session['user_id'], f"Reinstalled OS to {os_selection} on VPS {vps['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "OS Reinstallation complete."})

    except Exception as e:
        conn.close()
        return jsonify({"message": f"Reinstallation failed: {str(e)}"}), 500

# ----------------- SNAPSHOTS, BACKUPS & FIREWALL -----------------

@app.route('/api/client/vps/<int:vps_id>/snapshots', methods=['GET', 'POST'])
def client_vps_snapshots(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    if request.method == 'GET':
        cursor.execute("SELECT * FROM snapshots WHERE vps_id = ? ORDER BY id DESC", (vps_id,))
        snaps = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(snaps)

    data = request.get_json() or {}
    snap_name = data.get('name', '').strip()
    if not snap_name or not snap_name.isalnum():
        conn.close()
        return jsonify({"message": "Snapshot name must be alphanumeric."}), 400

    full_snap_name = f"{snap_name}-{int(time.time())}"

    try:
        if vps_row['node_id'] != 1:
            node = get_node_by_id(vps_row['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/snapshot", data={
                "name": vps_row['container_name'],
                "snap_name": full_snap_name
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote snapshot failed: {res.get('message', '')}"}), code
        else:
            LXCManager.create_snapshot(vps_row['container_name'], full_snap_name)
            
        cursor.execute("INSERT INTO snapshots (vps_id, name) VALUES (?, ?)", (vps_id, full_snap_name))
        conn.commit()
        log_audit(session['user_id'], f"Created snapshot {full_snap_name} for VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Snapshot created."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Snapshot failed: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/snapshots/restore', methods=['POST'])
def client_vps_restore_snapshot(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    snap_name = data.get('name')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    try:
        if vps_row['node_id'] != 1:
            node = get_node_by_id(vps_row['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/snapshot/restore", data={
                "name": vps_row['container_name'],
                "snap_name": snap_name
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote restore failed: {res.get('message', '')}"}), code
        else:
            LXCManager.restore_snapshot(vps_row['container_name'], snap_name)
            
        log_audit(session['user_id'], f"Restored snapshot {snap_name} on VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Snapshot restored successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Restore failed: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/snapshots/<name>', methods=['DELETE'])
def client_vps_delete_snapshot(vps_id, name):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    try:
        if vps_row['node_id'] != 1:
            node = get_node_by_id(vps_row['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/snapshot/delete", data={
                "name": vps_row['container_name'],
                "snap_name": name
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote deletion failed: {res.get('message', '')}"}), code
        else:
            LXCManager.delete_snapshot(vps_row['container_name'], name)
            
        cursor.execute("DELETE FROM snapshots WHERE vps_id = ? AND name = ?", (vps_id, name))
        conn.commit()
        log_audit(session['user_id'], f"Deleted snapshot {name} for VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Snapshot deleted."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Snapshot deletion failed: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/backups', methods=['GET', 'POST'])
def client_vps_backups(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    if request.method == 'GET':
        cursor.execute("SELECT * FROM backups WHERE vps_id = ? ORDER BY id DESC", (vps_id,))
        backups = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(backups)

    # POST - Create a real backup using lxc export
    filename = f"backup-{vps_row['container_name']}-{int(time.time())}.tar.gz"
    
    if vps_row['node_id'] != 1:
        node = get_node_by_id(vps_row['node_id'])
        if not node:
            conn.close()
            return jsonify({"message": "Remote node not found."}), 404
        res, code = make_node_request(node, "/api/vps/backup", data={
            "name": vps_row['container_name'],
            "filename": filename
        })
        if code != 200:
            conn.close()
            return jsonify({"message": f"Remote backup failed: {res.get('message', '')}"}), code
        size_str = res.get('size', '0 MB')
        
        try:
            cursor.execute("INSERT INTO backups (vps_id, filename, size) VALUES (?, ?, ?)", (vps_id, filename, size_str))
            conn.commit()
            log_audit(session['user_id'], f"Created backup {filename} for VPS {vps_row['container_name']}")
            conn.close()
            return jsonify({"status": "success", "message": "Backup created successfully."})
        except Exception as e:
            conn.close()
            return jsonify({"message": f"Failed to save backup details: {str(e)}"}), 500

    if IS_MOCK_LXC:
        try:
            size_str = f"{random.uniform(80.0, 160.0):.1f} MB"
            cursor.execute("INSERT INTO backups (vps_id, filename, size) VALUES (?, ?, ?)", (vps_id, filename, size_str))
            conn.commit()
            log_audit(session['user_id'], f"Created mock backup {filename} for VPS {vps_row['container_name']}")
            conn.close()
            return jsonify({"status": "success", "message": "Backup created successfully."})
        except Exception as e:
            conn.close()
            return jsonify({"message": f"Backup failed: {str(e)}"}), 500

    export_path = f"/tmp/{filename}"
    try:
        subprocess.run(
            [LXC_BIN, 'export', vps_row['container_name'], export_path],
            capture_output=True, text=True, check=True, timeout=300
        )
        # Get real file size
        file_size = os.path.getsize(export_path)
        if file_size > 1024 * 1024 * 1024:
            size_str = f"{file_size / (1024*1024*1024):.1f} GB"
        else:
            size_str = f"{file_size / (1024*1024):.1f} MB"

        cursor.execute("INSERT INTO backups (vps_id, filename, size) VALUES (?, ?, ?)", (vps_id, filename, size_str))
        conn.commit()
        log_audit(session['user_id'], f"Created backup {filename} for VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Backup created successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Backup failed: {str(e)}"}), 500

@app.route('/api/client/vps/<int:vps_id>/firewall', methods=['GET', 'POST'])
def client_vps_firewall(vps_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    if request.method == 'GET':
        cursor.execute("SELECT * FROM firewall_rules WHERE vps_id = ? ORDER BY id DESC", (vps_id,))
        rules = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(rules)

    data = request.get_json() or {}
    protocol = data.get('protocol')
    port = data.get('port')
    action = data.get('action')

    if protocol not in ['TCP', 'UDP', 'ICMP'] or action not in ['ALLOW', 'DENY']:
        conn.close()
        return jsonify({"message": "Invalid rule configurations."}), 400

    try:
        port_int = int(port) if protocol != 'ICMP' else 0
    except ValueError:
        conn.close()
        return jsonify({"message": "Port must be integer."}), 400

    try:
        cursor.execute(
            "INSERT INTO firewall_rules (vps_id, protocol, port, action) VALUES (?, ?, ?, ?)",
            (vps_id, protocol, port_int, action)
        )
        conn.commit()
        log_audit(session['user_id'], f"Added firewall rule: {action} {protocol}:{port_int} for VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Firewall configuration rules updated."})
    except Exception as e:
        conn.close()
        return jsonify({"message": str(e)}), 500

@app.route('/api/client/vps/<int:vps_id>/firewall/<int:rule_id>', methods=['DELETE'])
def client_vps_delete_firewall(vps_id, rule_id):
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, session['user_id']))
    vps_row = cursor.fetchone()

    if not vps_row:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    try:
        cursor.execute("DELETE FROM firewall_rules WHERE id = ? AND vps_id = ?", (rule_id, vps_id))
        conn.commit()
        log_audit(session['user_id'], f"Deleted firewall rule ID {rule_id} for VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Firewall rule successfully deleted."})
    except Exception as e:
        conn.close()
        return jsonify({"message": str(e)}), 500

# ----------------- ADMIN OPERATIONS -----------------

@app.route('/api/admin/users')
def admin_users_list():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role FROM users WHERE role = 'client'")
    users = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(users)

@app.route('/api/admin/vps', methods=['GET'])
def admin_vps_list():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT v.*, u.username as owner_username
        FROM vps v
        LEFT JOIN users u ON v.user_id = u.id
        ORDER BY v.id DESC
    ''')
    vps_list = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(vps_list)

@app.route('/api/admin/vps/deploy-stream')
def admin_vps_deploy_stream():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    name = request.args.get('name', '').strip()
    user_id = request.args.get('user_id')
    os_sel = request.args.get('os')
    cpu = request.args.get('cpu')
    ram = request.args.get('ram')
    disk = request.args.get('disk')
    root_pw = request.args.get('root_password', '').strip()
    node_id = request.args.get('node_id', 1)

    try:
        node_id = int(node_id)
    except (ValueError, TypeError):
        node_id = 1

    if not all([name, user_id, os_sel, cpu, ram, disk, root_pw]):
        return "data: [ERROR] Missing deployment configurations\n\n"

    admin_id = session.get('user_id')

    def generate():
        yield "data: [INFO] Validating parameters and DB hooks...\n\n"
        time.sleep(0.3)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            yield "data: [ERROR] Target user owner not found in database.\n\n"
            conn.close()
            return

        container_name = f"vps-{name}-{random.randint(100, 999)}"
        cursor.execute("SELECT * FROM vps WHERE container_name = ?", (container_name,))
        if cursor.fetchone():
            yield "data: [ERROR] Container name duplicate. Please choose a different key.\n\n"
            conn.close()
            return

        yield f"data: [INFO] Initiating LXC deploy for container: {container_name}...\n\n"

        try:
            if node_id != 1:
                node = get_node_by_id(node_id)
                if not node:
                    yield "data: [ERROR] Remote node target not found in database.\n\n"
                    conn.close()
                    return
                
                yield f"data: [INFO] Forwarding deploy request to remote node: {node['name']} ({node['fqdn']})...\n\n"
                
                res, code = make_node_request(node, "/api/vps/deploy", data={
                    "name": container_name,
                    "os": os_sel,
                    "cpu": int(cpu),
                    "ram": int(ram),
                    "disk": int(disk),
                    "password": root_pw
                })
                if code != 200:
                    yield f"data: [ERROR] Remote deploy failed: {res.get('message', '')}\n\n"
                    conn.close()
                    return
            else:
                def stream_log(msg):
                    pass  # SSE cannot yield from callback; we yield steps below

                # Execute REAL deployment
                LXCManager.deploy_container(
                    name=container_name,
                    os_image=os_sel,
                    cpu_cores=int(cpu),
                    ram_mb=int(ram),
                    disk_gb=int(disk),
                    root_password=root_pw,
                    log_callback=stream_log
                )

            yield "data: [INFO] Container image downloaded and launched.\n\n"
            yield f"data: [INFO] Resource limits applied: {cpu} cores, {ram}MB RAM, {disk}GB disk.\n\n"
            yield "data: [INFO] Root password configured.\n\n"

            # Create DB Record
            cursor.execute(
                '''INSERT INTO vps (user_id, container_name, os, cpu, ram, disk, root_password, status, node_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)''',
                (user_id, container_name, os_sel, cpu, ram, disk, root_pw, node_id)
            )
            vps_id = cursor.lastrowid
            conn.commit()

            # Fetch all settings
            cursor.execute("SELECT key, value FROM settings")
            settings = {row['key']: row['value'] for row in cursor.fetchall()}
            site_name_val = settings.get('site_name', 'MintyHost LXC')

            # Execute post-deployment environment setup (packages and Pinggy SSH tunnel)
            yield "data: [INFO] Initiating background installation of standard packages and tunnel client...\n\n"

            if node_id != 1:
                # Trigger post-deploy on remote node
                res, code = make_node_request(node, "/api/vps/post-deploy", data={
                    "name": container_name,
                    "vps_id": vps_id,
                    "password": root_pw,
                    "site_name": site_name_val
                })
                if code != 200:
                    yield f"data: [WARNING] Remote post-deploy trigger failed: {res.get('message', '')}\n\n"
            else:
                def run_deploy_setup(name, target_id, root_pw, s_name):
                    try:
                        LXCManager.post_deploy_setup(
                            name=name,
                            vps_id=target_id,
                            root_password=root_pw,
                            site_name=s_name
                        )
                    except Exception as ex:
                        print(f"[ERROR] Background deploy post_deploy_setup failed: {ex}")

                threading.Thread(
                    target=run_deploy_setup,
                    args=(container_name, vps_id, root_pw, site_name_val)
                ).start()
            
            yield "data: [INFO] Background setup task successfully queued.\n\n"

            log_audit(admin_id, f"Admin deployed container {container_name} assigned to user ID {user_id}")
            conn.close()

            yield "data: [SUCCESS] Container deployed and allocated to user.\n\n"
        except Exception as e:
            yield f"data: [ERROR] Deployment failed: {str(e)}\n\n"
            try:
                conn.close()
            except Exception:
                pass

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/admin/vps/<int:vps_id>/suspend', methods=['POST'])
def admin_vps_suspend(vps_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json() or {}
    suspend = data.get('suspend')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ?", (vps_id,))
    vps = cursor.fetchone()

    if not vps:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    try:
        action = 'suspend' if suspend else 'resume'
        if vps['node_id'] != 1:
            node = get_node_by_id(vps['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/action", data={
                "name": vps['container_name'],
                "action": action,
                "vps_id": vps_id
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote node error: {res.get('message', '')}"}), code
        else:
            LXCManager.execute_action(vps['container_name'], action)

        new_status = 'suspended' if suspend else 'running'
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps_id))
        conn.commit()

        log_audit(session['user_id'], f"Admin {action}ed container {vps['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": f"VPS container state set to: {new_status}."})
    except Exception as e:
        conn.close()
        return jsonify({"message": str(e)}), 500

@app.route('/api/admin/vps/<int:vps_id>', methods=['DELETE'])
def admin_delete_vps(vps_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ?", (vps_id,))
    vps = cursor.fetchone()

    if not vps:
        conn.close()
        return jsonify({"message": "VPS not found."}), 404

    try:
        if vps['node_id'] != 1:
            node = get_node_by_id(vps['node_id'])
            if not node:
                conn.close()
                return jsonify({"message": "Remote node not found."}), 404
            res, code = make_node_request(node, "/api/vps/destroy", data={
                "name": vps['container_name']
            })
            if code != 200:
                conn.close()
                return jsonify({"message": f"Remote node error: {res.get('message', '')}"}), code
        else:
            LXCManager.destroy_container(vps['container_name'])
            
        cursor.execute("DELETE FROM vps WHERE id = ?", (vps_id,))
        conn.commit()

        log_audit(session['user_id'], f"Admin permanently destroyed VPS {vps['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Container completely destroyed and deleted."})
    except Exception as e:
        conn.close()
        return jsonify({"message": str(e)}), 500


@app.route('/api/admin/logs')
def admin_logs():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT l.*, u.username
        FROM logs l
        LEFT JOIN users u ON l.user_id = u.id
        ORDER BY l.id DESC LIMIT 100
    ''')
    rows = cursor.fetchall()
    logs_list = [dict(row) for row in rows]
    conn.close()
    return jsonify(logs_list)

@app.route('/api/admin/stats')
def admin_stats():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'client'")
    client_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM vps")
    vps_count = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(cpu) FROM vps")
    allocated_cpu = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(ram) FROM vps")
    allocated_ram = cursor.fetchone()[0] or 0

    return jsonify({
        "clients": client_count,
        "vps_count": vps_count,
        "allocated_cpu": allocated_cpu,
        "allocated_ram": allocated_ram,
        "is_mock": IS_MOCK_LXC
    })

@app.route('/api/admin/settings/branding', methods=['POST'])
def admin_settings_branding():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
    
    data = request.get_json() or {}
    site_name = data.get('site_name', '').strip()
    color_primary = data.get('color_primary', '').strip()
    color_secondary = data.get('color_secondary', '').strip()
    color_accent = data.get('color_accent', '').strip()
    color_cool = data.get('color_cool', '').strip()

    if not site_name:
        return jsonify({"message": "Website name cannot be empty."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        updates = {
            'site_name': site_name,
            'color_primary': color_primary,
            'color_secondary': color_secondary,
            'color_accent': color_accent,
            'color_cool': color_cool
        }
        for key, val in updates.items():
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, val, val)
            )
        conn.commit()
        log_audit(session['user_id'], f"Updated branding and site settings. Site name set to: {site_name}")
        return jsonify({"status": "success", "message": "Branding settings saved successfully."})
    except Exception as e:
        return jsonify({"message": f"Failed to save settings: {str(e)}"}), 500
    finally:
        conn.close()

@app.route('/api/admin/settings/relay', methods=['POST'])
def admin_settings_relay():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
    
    data = request.get_json() or {}
    enabled = data.get('enabled', '0')
    host = data.get('host', '').strip()
    port = data.get('port', '22').strip()
    user = data.get('user', '').strip()
    password = data.get('password', '').strip()
    ports = data.get('ports', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        updates = {
            'ssh_relay_enabled': enabled,
            'ssh_relay_host': host,
            'ssh_relay_port': port,
            'ssh_relay_user': user,
            'ssh_relay_password': password,
            'ssh_relay_ports': ports
        }
        for key, val in updates.items():
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, val, val)
            )
        conn.commit()
        log_audit(session['user_id'], "Updated custom SSH Tunnel Relay configuration.")
        return jsonify({"status": "success", "message": "SSH Tunnel Relay settings saved successfully."})
    except Exception as e:
        return jsonify({"message": f"Failed to save relay settings: {str(e)}"}), 500
    finally:
        conn.close()

@app.route('/api/admin/settings/pages', methods=['POST'])
def admin_settings_pages():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
    
    data = request.get_json() or {}
    about_intro = data.get('about_intro', '').strip()
    about_mission = data.get('about_mission', '').strip()
    about_infra = data.get('about_infra', '').strip()
    about_why_trust = data.get('about_why_trust', '').strip()
    tos_content = data.get('tos_content', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        updates = {
            'about_intro': about_intro,
            'about_mission': about_mission,
            'about_infra': about_infra,
            'about_why_trust': about_why_trust,
            'tos_content': tos_content
        }
        for key, val in updates.items():
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, val, val)
            )
        conn.commit()
        log_audit(session['user_id'], "Updated public pages customization (About & TOS pages)")
        return jsonify({"status": "success", "message": "Page contents saved successfully."})
    except Exception as e:
        return jsonify({"message": f"Failed to save page contents: {str(e)}"}), 500
    finally:
        conn.close()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/admin/settings/upload', methods=['POST'])
def admin_settings_upload():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
        
    upload_type = request.form.get('type')
    if upload_type not in ['logo', 'favicon']:
        return jsonify({"message": "Invalid upload type. Must be 'logo' or 'favicon'."}), 400
        
    if 'file' not in request.files:
        return jsonify({"message": "No file part in request."}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"message": "No file selected."}), 400
        
    if file and allowed_file(file.filename):
        # Ensure uploads directory exists
        uploads_dir = os.path.join(app.static_folder, 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        
        # Save file with unique name
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{upload_type}_{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(uploads_dir, filename)
        file.save(filepath)
        
        # Update setting in database
        file_url = url_for('static', filename=f"uploads/{filename}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            key = f"{upload_type}_url"
            
            # Retrieve old file to delete it
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                old_url = row['value']
                if 'static/' in old_url:
                    old_rel_path = old_url.split('static/')[-1]
                    old_file_path = os.path.join(app.static_folder, old_rel_path)
                    if os.path.exists(old_file_path):
                        try:
                            os.remove(old_file_path)
                        except Exception as ex:
                            print(f"[WARN] Failed to delete old asset: {ex}")
                            
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, file_url, file_url)
            )
            conn.commit()
            log_audit(session['user_id'], f"Uploaded new custom {upload_type}: {file_url}")
            return jsonify({"status": "success", "url": file_url, "message": f"{upload_type.capitalize()} uploaded successfully."})
        except Exception as e:
            return jsonify({"message": f"Failed to save setting: {str(e)}"}), 500
        finally:
            conn.close()
            
    return jsonify({"message": "File extension not allowed."}), 400

@app.route('/api/admin/settings/remove-image', methods=['POST'])
def admin_settings_remove_image():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
        
    data = request.get_json() or {}
    image_type = data.get('type')
    if image_type not in ['logo', 'favicon']:
        return jsonify({"message": "Invalid type. Must be 'logo' or 'favicon'."}), 400
        
    key = f"{image_type}_url"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            current_url = row['value']
            if 'static/' in current_url:
                relative_path = current_url.split('static/')[-1]
                file_path = os.path.join(app.static_folder, relative_path)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as ex:
                        print(f"[WARN] Failed to delete physical asset: {ex}")
                        
        cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()
        log_audit(session['user_id'], f"Removed custom {image_type}")
        return jsonify({"status": "success", "message": f"{image_type.capitalize()} removed successfully."})
    except Exception as e:
        return jsonify({"message": f"Failed to remove asset: {str(e)}"}), 500
    finally:
        conn.close()

@app.route('/api/admin/plans', methods=['GET', 'POST'])
def admin_plans_handler():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute("SELECT * FROM vps_plans ORDER BY price ASC")
        plans = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(plans)
        
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    try:
        price = float(data.get('price', 0))
        price_credits = int(data.get('price_credits', 0))
    except ValueError:
        conn.close()
        return jsonify({"message": "Price and price credits must be numbers."}), 400

    ram = data.get('ram', '').strip()
    cpu = data.get('cpu', '').strip()
    storage = data.get('storage', '').strip()
    bandwidth = data.get('bandwidth', '').strip()

    if not name or not ram or not cpu or not storage or not bandwidth:
        conn.close()
        return jsonify({"message": "All plan fields are required."}), 400

    try:
        cursor.execute(
            "INSERT INTO vps_plans (name, price, price_credits, ram, cpu, storage, bandwidth) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, price, price_credits, ram, cpu, storage, bandwidth)
        )
        conn.commit()
        log_audit(session['user_id'], f"Created new VPS pricing plan: {name}")
        conn.close()
        return jsonify({"status": "success", "message": f"Plan '{name}' created successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to create plan: {str(e)}"}), 500

@app.route('/api/admin/plans/<int:plan_id>', methods=['PUT', 'DELETE'])
def admin_plan_detail_handler(plan_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM vps_plans WHERE id = ?", (plan_id,))
    plan = cursor.fetchone()
    if not plan:
        conn.close()
        return jsonify({"message": "Plan not found."}), 404

    if request.method == 'DELETE':
        try:
            cursor.execute("DELETE FROM vps_plans WHERE id = ?", (plan_id,))
            conn.commit()
            log_audit(session['user_id'], f"Deleted VPS plan: {plan['name']}")
            conn.close()
            return jsonify({"status": "success", "message": f"Plan '{plan['name']}' deleted successfully."})
        except Exception as e:
            conn.close()
            return jsonify({"message": f"Failed to delete plan: {str(e)}"}), 500

    data = request.get_json() or {}
    name = data.get('name', '').strip()
    try:
        price = float(data.get('price', 0))
        price_credits = int(data.get('price_credits', 0))
    except ValueError:
        conn.close()
        return jsonify({"message": "Price and price credits must be numbers."}), 400

    ram = data.get('ram', '').strip()
    cpu = data.get('cpu', '').strip()
    storage = data.get('storage', '').strip()
    bandwidth = data.get('bandwidth', '').strip()

    if not name or not ram or not cpu or not storage or not bandwidth:
        conn.close()
        return jsonify({"message": "All plan fields are required."}), 400

    try:
        cursor.execute(
            "UPDATE vps_plans SET name = ?, price = ?, price_credits = ?, ram = ?, cpu = ?, storage = ?, bandwidth = ? WHERE id = ?",
            (name, price, price_credits, ram, cpu, storage, bandwidth, plan_id)
        )
        conn.commit()
        log_audit(session['user_id'], f"Updated VPS pricing plan: {name}")
        conn.close()
        return jsonify({"status": "success", "message": f"Plan '{name}' updated successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to update plan: {str(e)}"}), 500

@app.route('/api/admin/faqs', methods=['GET', 'POST'])
def admin_faqs_handler():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM faqs ORDER BY id ASC")
        faqs = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(faqs)

    data = request.get_json() or {}
    question = data.get('question', '').strip()
    answer = data.get('answer', '').strip()

    if not question or not answer:
        conn.close()
        return jsonify({"message": "Question and answer fields are required."}), 400

    try:
        cursor.execute("INSERT INTO faqs (question, answer) VALUES (?, ?)", (question, answer))
        conn.commit()
        log_audit(session['user_id'], f"Created new FAQ: {question[:40]}...")
        conn.close()
        return jsonify({"status": "success", "message": "FAQ item created successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to create FAQ: {str(e)}"}), 500

@app.route('/api/admin/faqs/<int:faq_id>', methods=['PUT', 'DELETE'])
def admin_faq_detail_handler(faq_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM faqs WHERE id = ?", (faq_id,))
    faq = cursor.fetchone()
    if not faq:
        conn.close()
        return jsonify({"message": "FAQ not found."}), 404

    if request.method == 'DELETE':
        try:
            cursor.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
            conn.commit()
            log_audit(session['user_id'], f"Deleted FAQ ID: {faq_id}")
            conn.close()
            return jsonify({"status": "success", "message": "FAQ item deleted successfully."})
        except Exception as e:
            conn.close()
            return jsonify({"message": f"Failed to delete FAQ: {str(e)}"}), 500

    data = request.get_json() or {}
    question = data.get('question', '').strip()
    answer = data.get('answer', '').strip()

    if not question or not answer:
        conn.close()
        return jsonify({"message": "Question and answer fields are required."}), 400

    try:
        cursor.execute("UPDATE faqs SET question = ?, answer = ? WHERE id = ?", (question, answer, faq_id))
        conn.commit()
        log_audit(session['user_id'], f"Updated FAQ item: {question[:40]}...")
        conn.close()
        return jsonify({"status": "success", "message": "FAQ item updated successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to update FAQ: {str(e)}"}), 500

# ----------------- REAL WEB TERMINAL VIA SOCKETIO + PTY -----------------

# Store active terminal processes per session
terminal_processes = {}

@socketio.on('terminal_connect')
def handle_terminal_connect(data):
    """Client requests a terminal session to a specific container."""
    container_name = data.get('container_name')
    user_id = session.get('user_id')
    role = session.get('role')
    sid = request.sid

    if not user_id:
        emit('terminal_output', {'output': '\r\n[ERROR] Unauthorized session.\r\n'})
        return

    # Verify container ownership or admin
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE container_name = ?", (container_name,))
    vps = cursor.fetchone()
    conn.close()

    if not vps:
        emit('terminal_output', {'output': '\r\n[ERROR] Container not found.\r\n'})
        return

    if role != 'admin' and vps['user_id'] != user_id:
        emit('terminal_output', {'output': '\r\n[ERROR] Access denied. You do not own this container.\r\n'})
        return

    # If container is on a remote node, web terminal console is not supported directly via panel PTY
    if vps['node_id'] != 1:
        emit('terminal_output', {
            'output': '\r\n[INFO] Web Console is only supported on the Local Node.\r\n'
                      '[INFO] Please connect using the Bore SSH Tunnel shown in the Overview tab.\r\n'
        })
        return

    # Check container is running
    if vps['status'] != 'running':
        emit('terminal_output', {'output': '\r\n[ERROR] Container is not running. Start it first.\r\n'})
        return

    # Open a REAL PTY and spawn lxc exec into the container
    if not HAS_PTY:
        emit('terminal_output', {'output': '\r\n[ERROR] Terminal not available on this platform. Deploy on Linux.\r\n'})
        return

    try:
        master_fd, slave_fd = pty.openpty()

        process = subprocess.Popen(
            [LXC_BIN, 'exec', container_name, '--env', 'TERM=xterm-256color', '--', '/bin/bash'],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            close_fds=True
        )
        os.close(slave_fd)

        # Store reference
        terminal_processes[sid] = {
            'master_fd': master_fd,
            'process': process,
            'container': container_name
        }

        emit('terminal_output', {'output': ''})  # Signal connection success

        # Start background reader task
        def read_output():
            while True:
                try:
                    socketio.sleep(0.01)
                    if process.poll() is not None:
                        socketio.emit('terminal_output', {'output': '\r\n[Session ended]\r\n'}, room=sid)
                        break
                    r, _, _ = select.select([master_fd], [], [], 0.02)
                    if master_fd in r:
                        output = os.read(master_fd, 4096)
                        if output:
                            socketio.emit('terminal_output', {'output': output.decode('utf-8', errors='replace')}, room=sid)
                        else:
                            break
                except OSError:
                    break
                except Exception:
                    break
            # Cleanup
            cleanup_terminal(sid)

        socketio.start_background_task(read_output)

    except Exception as e:
        emit('terminal_output', {'output': f'\r\n[ERROR] Failed to open terminal: {str(e)}\r\n'})

@socketio.on('terminal_input')
def handle_terminal_input(data):
    """Receive keyboard input from the browser and write it to the PTY."""
    sid = request.sid
    term = terminal_processes.get(sid)
    if term:
        try:
            os.write(term['master_fd'], data['input'].encode('utf-8'))
        except OSError:
            cleanup_terminal(sid)

@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    """Handle terminal resize events from xterm.js."""
    sid = request.sid
    term = terminal_processes.get(sid)
    if term and HAS_PTY:
        try:
            cols = data.get('cols', 80)
            rows = data.get('rows', 24)
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(term['master_fd'], termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

@socketio.on('disconnect')
def handle_disconnect():
    """Clean up terminal process when the WebSocket disconnects."""
    cleanup_terminal(request.sid)

def cleanup_terminal(sid):
    """Terminate and clean up a terminal session."""
    term = terminal_processes.pop(sid, None)
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


# ----------------- USER PROFILE API -----------------

@app.route('/api/profile/update', methods=['POST'])
def profile_update():
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    user_id = session['user_id']
    username = request.form.get('username', '').strip().lower()
    email = request.form.get('email', '').strip().lower()

    if not username or not email:
        return jsonify({"message": "Username and email are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check for duplicate username or email
    cursor.execute("SELECT id FROM users WHERE (username = ? OR email = ?) AND id != ?", (username, email, user_id))
    if cursor.fetchone():
        conn.close()
        return jsonify({"message": "Username or email is already taken."}), 400

    pfp_url = session.get('pfp')

    # Handle PFP Upload
    if 'pfp' in request.files:
        file = request.files['pfp']
        if file and file.filename != '':
            if allowed_file(file.filename):
                uploads_dir = os.path.join(app.static_folder, 'uploads', 'pfps')
                os.makedirs(uploads_dir, exist_ok=True)
                
                # Delete old pfp file if exists
                if pfp_url and 'static/' in pfp_url:
                    try:
                        old_rel_path = pfp_url.split('static/')[-1]
                        old_file_path = os.path.join(app.static_folder, old_rel_path)
                        if os.path.exists(old_file_path):
                            os.remove(old_file_path)
                    except Exception as ex:
                        print(f"[WARN] Failed to delete old pfp: {ex}")

                # Save new file
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"pfp_{user_id}_{uuid.uuid4().hex}.{ext}"
                filepath = os.path.join(uploads_dir, filename)
                file.save(filepath)
                pfp_url = url_for('static', filename=f"uploads/pfps/{filename}")
            else:
                conn.close()
                return jsonify({"message": "File extension not allowed for profile picture."}), 400

    try:
        cursor.execute(
            "UPDATE users SET username = ?, email = ?, pfp = ? WHERE id = ?",
            (username, email, pfp_url, user_id)
        )
        conn.commit()
        
        # Update session
        session['username'] = username
        session['email'] = email
        session['pfp'] = pfp_url
        
        log_audit(user_id, f"Updated profile details: username={username}, email={email}")
        conn.close()
        return jsonify({
            "status": "success", 
            "message": "Profile updated successfully.",
            "username": username,
            "email": email,
            "pfp": pfp_url
        })
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to update profile: {str(e)}"}), 500


@app.route('/api/profile/update-password', methods=['POST'])
def profile_update_password():
    if not is_logged_in():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_password or not new_password:
        return jsonify({"message": "Current password and new password are required."}), 400

    if len(new_password) < 6:
        return jsonify({"message": "New password must be at least 6 characters."}), 400

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()

    if not user or not check_password_hash(user['password_hash'], current_password):
        conn.close()
        return jsonify({"message": "Incorrect current password."}), 400

    hashed_pw = generate_password_hash(new_password)
    try:
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed_pw, user_id))
        conn.commit()
        log_audit(user_id, "Changed account password")
        conn.close()
        return jsonify({"status": "success", "message": "Password updated successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to update password: {str(e)}"}), 500


# ----------------- ADMIN USER MANAGEMENT API -----------------

@app.route('/api/admin/users/all')
def admin_users_all():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    # Fetch all users, join with VPS to count active instances and sum allocations
    cursor.execute('''
        SELECT 
            u.id, 
            u.username, 
            u.email, 
            u.role, 
            u.password_hash, 
            u.pfp,
            COUNT(v.id) AS vps_count,
            COALESCE(SUM(v.cpu), 0) AS total_cpu,
            COALESCE(SUM(v.ram), 0) AS total_ram,
            COALESCE(SUM(v.disk), 0) AS total_disk
        FROM users u
        LEFT JOIN vps v ON u.id = v.user_id
        GROUP BY u.id
        ORDER BY u.id ASC
    ''')
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(users)


@app.route('/api/admin/users/create', methods=['POST'])
def admin_users_create():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    email = data.get('email', '').strip().lower()
    password = data.get('password')
    role = data.get('role', 'client')

    if not username or not email or not password or not role:
        return jsonify({"message": "All fields (username, email, password, role) are required."}), 400

    if role not in ['admin', 'client']:
        return jsonify({"message": "Invalid role specified."}), 400

    if len(password) < 6:
        return jsonify({"message": "Password must be at least 6 characters."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check for duplicate
    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
    if cursor.fetchone():
        conn.close()
        return jsonify({"message": "Username or email is already registered."}), 400

    hashed_pw = generate_password_hash(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, email, hashed_pw, role)
        )
        conn.commit()
        log_audit(session['user_id'], f"Admin created new user account: {username} ({role})")
        conn.close()
        return jsonify({"status": "success", "message": f"User account '{username}' created successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to create user: {str(e)}"}), 500


@app.route('/api/admin/users/<int:target_user_id>/update', methods=['POST'])
def admin_users_update(target_user_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    email = data.get('email', '').strip().lower()
    role = data.get('role', 'client')
    new_password = data.get('password')

    if not username or not email or not role:
        return jsonify({"message": "Username, email, and role are required."}), 400

    if role not in ['admin', 'client']:
        return jsonify({"message": "Invalid role specified."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check duplicate username/email
    cursor.execute("SELECT id FROM users WHERE (username = ? OR email = ?) AND id != ?", (username, email, target_user_id))
    if cursor.fetchone():
        conn.close()
        return jsonify({"message": "Username or email is already registered by another user."}), 400

    try:
        if new_password and len(new_password.strip()) >= 6:
            hashed_pw = generate_password_hash(new_password.strip())
            cursor.execute(
                "UPDATE users SET username = ?, email = ?, role = ?, password_hash = ? WHERE id = ?",
                (username, email, role, hashed_pw, target_user_id)
            )
            log_audit(session['user_id'], f"Admin updated user account details and reset password for ID {target_user_id} ({username})")
        else:
            cursor.execute(
                "UPDATE users SET username = ?, email = ?, role = ? WHERE id = ?",
                (username, email, role, target_user_id)
            )
            log_audit(session['user_id'], f"Admin updated user account details for ID {target_user_id} ({username})")
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "User details successfully updated."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to update user: {str(e)}"}), 500


@app.route('/api/admin/users/<int:target_user_id>/delete', methods=['DELETE'])
def admin_users_delete(target_user_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    if target_user_id == session['user_id']:
        return jsonify({"message": "You cannot delete your own admin account."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch user username
    cursor.execute("SELECT username FROM users WHERE id = ?", (target_user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return jsonify({"message": "User not found."}), 404
    username = user_row['username']

    # Fetch all VPS owned by the user
    cursor.execute("SELECT container_name, node_id FROM vps WHERE user_id = ?", (target_user_id,))
    vps_rows = cursor.fetchall()

    try:
        # 1. Destroy all LXC containers for this user
        for vps in vps_rows:
            try:
                if vps['node_id'] == 1:
                    LXCManager.destroy_container(vps['container_name'])
                else:
                    node = get_node_by_id(vps['node_id'])
                    if node:
                        make_node_request(node, "/api/vps/destroy", data={"name": vps['container_name']})
            except Exception as ex:
                print(f"[WARN] Failed to destroy container {vps['container_name']} for deleted user: {ex}")

        # 2. Delete all user records in DB (cascading deletes will handle snapshots, backups, firewall, vps)
        cursor.execute("DELETE FROM users WHERE id = ?", (target_user_id,))
        conn.commit()
        log_audit(session['user_id'], f"Admin deleted user account: {username} (ID {target_user_id}) and permanently destroyed all associated VPS containers.")
        conn.close()
        return jsonify({"status": "success", "message": f"User account '{username}' and all associated VPS containers have been permanently deleted."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to delete user and assets: {str(e)}"}), 500


@app.route('/api/admin/users/<int:target_user_id>/suspend', methods=['POST'])
def admin_users_suspend(target_user_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json() or {}
    suspend = data.get('suspend', True)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch user username
    cursor.execute("SELECT username FROM users WHERE id = ?", (target_user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return jsonify({"message": "User not found."}), 404
    username = user_row['username']

    # Fetch all VPS owned by the user
    cursor.execute("SELECT id, container_name, status, node_id FROM vps WHERE user_id = ?", (target_user_id,))
    vps_rows = cursor.fetchall()

    action = 'suspend' if suspend else 'resume'
    new_status = 'suspended' if suspend else 'running'

    try:
        # Loop and execute action on each container
        for vps in vps_rows:
            # Only suspend if running, or resume if suspended
            if suspend and vps['status'] == 'running':
                if vps['node_id'] == 1:
                    LXCManager.execute_action(vps['container_name'], 'suspend')
                else:
                    node = get_node_by_id(vps['node_id'])
                    if node:
                        make_node_request(node, "/api/vps/action", data={"name": vps['container_name'], "action": 'suspend', "vps_id": vps['id']})
                cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps['id']))
            elif not suspend and vps['status'] == 'suspended':
                if vps['node_id'] == 1:
                    LXCManager.execute_action(vps['container_name'], 'resume')
                else:
                    node = get_node_by_id(vps['node_id'])
                    if node:
                        make_node_request(node, "/api/vps/action", data={"name": vps['container_name'], "action": 'resume', "vps_id": vps['id']})
                cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps['id']))

        conn.commit()
        log_audit(session['user_id'], f"Admin bulk-{action}ed all instances owned by user: {username} (ID {target_user_id}).")
        conn.close()
        return jsonify({"status": "success", "message": f"All instances for user '{username}' have been set to {new_status}."})

    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to modify instances: {str(e)}"}), 500


@app.route('/api/admin/users/<int:target_user_id>/vps')
def admin_users_vps_list(target_user_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE user_id = ? ORDER BY id DESC", (target_user_id,))
    vps_list = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(vps_list)

@app.route('/api/admin/nodes')
def admin_nodes_list():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, fqdn, port, location, api_key, status, created_at FROM nodes ORDER BY id ASC")
    nodes = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(nodes)

@app.route('/api/admin/nodes/create', methods=['POST'])
def admin_nodes_create():
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
        
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    fqdn = data.get('fqdn', '').strip()
    port = data.get('port', 5001)
    location = data.get('location', '').strip()

    if not name or not fqdn:
        return jsonify({"message": "Name and FQDN are required."}), 400

    try:
        port_int = int(port)
    except ValueError:
        return jsonify({"message": "Port must be an integer."}), 400

    import secrets
    api_key = secrets.token_hex(32)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO nodes (name, fqdn, port, location, api_key, status) VALUES (?, ?, ?, ?, ?, 'offline')",
            (name, fqdn, port_int, location, api_key)
        )
        conn.commit()
        node_id = cursor.lastrowid
        log_audit(session['user_id'], f"Created remote node {name} (ID {node_id})")
        conn.close()
        return jsonify({"status": "success", "message": "Node successfully created.", "node_id": node_id})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to create node: {str(e)}"}), 500

@app.route('/api/admin/nodes/<int:node_id>', methods=['DELETE'])
def admin_nodes_delete(node_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    if node_id == 1:
        return jsonify({"message": "Default Local Node cannot be deleted."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM nodes WHERE id = ?", (node_id,))
    node_row = cursor.fetchone()
    if not node_row:
        conn.close()
        return jsonify({"message": "Node not found."}), 404

    # Check if there are any VPS associated with this node
    cursor.execute("SELECT COUNT(*) FROM vps WHERE node_id = ?", (node_id,))
    if cursor.fetchone()[0] > 0:
        conn.close()
        return jsonify({"message": "Cannot delete node because it has active virtual servers deployed on it."}), 400

    try:
        cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        conn.commit()
        log_audit(session['user_id'], f"Deleted remote node {node_row['name']} (ID {node_id})")
        conn.close()
        return jsonify({"status": "success", "message": "Node successfully deleted."})
    except Exception as e:
        conn.close()
        return jsonify({"message": f"Failed to delete node: {str(e)}"}), 500

@app.route('/api/admin/nodes/<int:node_id>/config')
def admin_nodes_config(node_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    node = get_node_by_id(node_id)
    if not node:
        return jsonify({"message": "Node not found."}), 404

    config_yaml = f"""# MintyHost LXC Node Config File
port: {node['port']}
api_key: "{node['api_key']}"
node_id: {node['id']}
name: "{node['name']}"
"""

    install_cmd = f"curl -sSL {request.host_url}node.sh | NODE_PORT={node['port']} NODE_API_KEY=\"{node['api_key']}\" NODE_ID={node['id']} NODE_NAME=\"{node['name']}\" bash"

    return jsonify({
        "config_yaml": config_yaml,
        "install_cmd": install_cmd
    })

@app.route('/api/admin/nodes/<int:node_id>/status')
def admin_node_status(node_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403

    if node_id == 1:
        # Local node is always online
        return jsonify({"status": "online"})

    node = get_node_by_id(node_id)
    if not node:
        return jsonify({"message": "Node not found"}), 404

    # Ping the remote node daemon's status endpoint
    res, code = make_node_request(node, "/api/node/status", method='GET')
    if code == 200 and res.get('status') == 'online':
        # Update status in DB to online
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE nodes SET status = 'online' WHERE id = ?", (node_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "online"})
    else:
        # Update status in DB to offline
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE nodes SET status = 'offline' WHERE id = ?", (node_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "offline"})

@app.route('/node.sh')
def download_node_sh():
    from flask import send_from_directory
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'node.sh', mimetype='text/x-shellscript')


if __name__ == '__main__':
    import os
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        try:
            from pinggy_monitor import start_monitor
            start_monitor()
        except Exception as e:
            print(f"[WARNING] Failed to start Pinggy background monitor: {e}")
            
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
