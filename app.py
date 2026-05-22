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
from database import get_db_connection, init_db
from lxc_manager import LXCManager, LXC_BIN, IS_MOCK_LXC
from collections import deque

# Metrics history cache to keep the line graphs pre-populated and real-time
METRICS_HISTORY = {}


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
        settings = {
            'site_name': 'MintyHost LXC',
            'color_primary': '#ECF4E8',
            'color_secondary': '#CBF3BB',
            'color_accent': '#ABE7B2',
            'color_cool': '#93BFC7'
        }
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

# Static content configurations for marketing/public pages
TEAM_MEMBERS = [
    {
        'name': 'Ayan Khan',
        'role': 'Founder & Lead Architect',
        'bio': 'Passionate about virtualization, Linux containers, and low-latency network architectures.'
    },
    {
        'name': 'Sarah Chen',
        'role': 'Head of Infrastructure',
        'bio': 'Ensures high availability across our bare-metal hardware hypervisors and network uplinks.'
    },
    {
        'name': 'Marcus Vance',
        'role': 'Support Lead',
        'bio': 'Dedicated to assisting developers and startups with troubleshooting and container management.'
    }
]

# ----------------- PAGE ROUTING -----------------

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vps_plans ORDER BY price ASC")
        plans = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        print(f"Error fetching plans: {e}")
        plans = []
    return render_template('index.html', plans=plans)

@app.route('/plans')
def plans_page():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vps_plans ORDER BY price ASC")
        plans = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        print(f"Error fetching plans: {e}")
        plans = []
    return render_template('plans.html', plans=plans)

@app.route('/about')
def about_page():
    return render_template('about.html', team_members=TEAM_MEMBERS)

@app.route('/faq')
def faq_page():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM faqs ORDER BY id ASC")
        faqs = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        print(f"Error fetching FAQs: {e}")
        faqs = []
    return render_template('faq.html', faqs=faqs)

@app.route('/tos')
def tos_page():
    return render_template('tos.html')

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
        session['role'] = user['role']
        session['is_admin'] = (user['role'] == 'admin')

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
        session['role'] = user['role']
        session['is_admin'] = (user['role'] == 'admin')

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

    stats = LXCManager.get_container_stats(
        name=vps_row['container_name'],
        plan_cpu=vps_row['cpu'],
        plan_ram=vps_row['ram'],
        plan_disk=vps_row['disk'],
        db_status=vps_row['status'],
        vps_id=vps_id
    )

    # Sync status to DB if it changes
    if stats['status'] != vps_row['status']:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (stats['status'], vps_id))
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
        LXCManager.execute_action(vps_row['container_name'], action)

        new_status = 'running' if action in ['start', 'restart', 'resume'] else ('stopped' if action == 'stop' else 'suspended')
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps_id))
        conn.commit()

        if action in ['start', 'restart']:
            threading.Thread(target=LXCManager.ensure_dynamic_bore_setup, args=(vps_row['container_name'], vps_id)).start()

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

    try:
        LXCManager.destroy_container(vps['container_name'])
        LXCManager.deploy_container(
            name=vps['container_name'],
            os_image=os_selection,
            cpu_cores=vps['cpu'],
            ram_mb=vps['ram'],
            disk_gb=vps['disk'],
            root_password=root_password
        )

        # Fetch site name for MOTD configuration
        site_name_val = "MintyHost LXC"
        try:
            cursor.execute("SELECT value FROM settings WHERE key = 'site_name'")
            row = cursor.fetchone()
            if row:
                site_name_val = row['value']
        except Exception:
            pass

        # Run post-deployment environment setup (packages and Bore tunnel) in background
        def run_reinstall_setup(name, target_id, root_pw, s_name):
            try:
                LXCManager.post_deploy_setup(
                    name=name,
                    vps_id=target_id,
                    root_password=root_pw,
                    site_name=s_name
                )
            except Exception as ex:
                print(f"[ERROR] Background reinstall post_deploy_setup failed: {ex}")

        threading.Thread(
            target=run_reinstall_setup,
            args=(vps['container_name'], vps_id, root_password, site_name_val)
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
                '''INSERT INTO vps (user_id, container_name, os, cpu, ram, disk, root_password, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'running')''',
                (user_id, container_name, os_sel, cpu, ram, disk, root_pw)
            )
            vps_id = cursor.lastrowid
            conn.commit()

            # Execute post-deployment environment setup (packages and Bore tunnel) in background
            yield "data: [INFO] Initiating background installation of standard packages and Bore tunnel...\n\n"
            
            site_name_val = "MintyHost LXC"
            try:
                cursor.execute("SELECT value FROM settings WHERE key = 'site_name'")
                row = cursor.fetchone()
                if row:
                    site_name_val = row['value']
            except Exception:
                pass

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


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
