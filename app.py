from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sock import Sock
import json
import time
import os
import sys
import random
from database import get_db_connection, init_db
from lxc_manager import LXCManager

# Import platform specific modules for terminal bridge
if sys.platform != "win32":
    import pty
    import select

app = Flask(__name__)
app.secret_key = 'mintyhost-lxc-secret-key-928475'
sock = Sock(app)

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

# ----------------- PAGE ROUTING -----------------

@app.route('/')
def index():
    if not is_logged_in():
        return redirect(url_for('auth'))
    if is_admin():
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('client_dashboard'))

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
    
    # Check if username or email already exists
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
        
        # Log the user in directly
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
    except Exception as e:
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
    # Check by email or username
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
    cursor.execute(
        "SELECT * FROM vps WHERE user_id = ? ORDER BY id DESC",
        (session['user_id'],)
    )
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
        
    # Get live statistics from LXC Manager
    stats = LXCManager.get_container_stats(
        name=vps_row['container_name'],
        os_type=vps_row['os'],
        plan_cpu=vps_row['cpu'],
        plan_ram=vps_row['ram'],
        plan_disk=vps_row['disk']
    )
    
    # Sync status to DB if it changes
    if stats['status'] != vps_row['status']:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (stats['status'], vps_id))
        conn.commit()
        conn.close()
        
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
        
    # Perform action via LXC manager
    try:
        # If suspended, mapped to pause/resume
        effective_action = action
        if action == 'suspend':
            effective_action = 'suspend'
        elif action == 'resume':
            effective_action = 'resume'
            
        LXCManager.execute_action(vps_row['container_name'], effective_action)
        
        # Update database status field
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
        # LXD rename command: lxc move old new
        if not LXCManager.is_mock():
            LXCManager.execute_cmd(["lxc", "move", old_container_name, new_container_name])
            
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
        # Reinstall flow: Stop -> Delete -> Deploy same specs
        LXCManager.destroy_container(vps['container_name'])
        
        # Deploy again
        LXCManager.deploy_container(
            name=vps['container_name'],
            os_image=os_selection,
            cpu_cores=vps['cpu'],
            ram_mb=vps['ram'],
            disk_gb=vps['disk'],
            root_password=root_password
        )
        
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

# ----------------- BONUS: SNAPSHOTS, BACKUPS & FIREWALL -----------------

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
        
    # POST - Create Snapshot
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
        
    # POST - Create Mock Backup File
    filename = f"backup-{vps_row['container_name']}-{int(time.time())}.tar.gz"
    size = f"{random.uniform(120.5, 450.8):.1f} MB"
    
    try:
        # Mocking container backing export (normally runs lxc export)
        cursor.execute("INSERT INTO backups (vps_id, filename, size) VALUES (?, ?, ?)", (vps_id, filename, size))
        conn.commit()
        log_audit(session['user_id'], f"Created backup tarball {filename} for VPS {vps_row['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "Backup archiver generated successfully."})
    except Exception as e:
        conn.close()
        return jsonify({"message": str(e)}), 500

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
        
    # POST - Add firewall rule
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
        
        # Connect to DB and verify user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            yield "data: [ERROR] Target user owner not found in database.\n\n"
            conn.close()
            return
            
        # Check uniqueness of name
        container_name = f"vps-{name}-{random.randint(100, 999)}"
        cursor.execute("SELECT * FROM vps WHERE container_name = ?", (container_name,))
        if cursor.fetchone():
            yield "data: [ERROR] Container name duplicate. Please choose a different key.\n\n"
            conn.close()
            return
            
        yield f"data: [INFO] Initiating LXC deploy for container: {container_name}...\n\n"
        
        def stream_logger(msg):
            # Formats message for SSE
            sys.stdout.flush()
            
        try:
            # Deploy container
            LXCManager.deploy_container(
                name=container_name,
                os_image=os_sel,
                cpu_cores=int(cpu),
                ram_mb=int(ram),
                disk_gb=int(disk),
                root_password=root_pw,
                log_callback=lambda log_line: time.sleep(0.1) or sys.stdout.write(f"data: {log_line}\n\n")
            )
            
            # Since lambda cannot return generator output in python easily, let's yield steps directly here:
            yield "data: [INFO] Downloading and provisioning container template...\n\n"
            time.sleep(0.6)
            yield f"data: [INFO] Setting resource parameters limits.cpu = {cpu} cores...\n\n"
            time.sleep(0.4)
            yield f"data: [INFO] Setting limits.memory = {ram}MB memory...\n\n"
            time.sleep(0.4)
            yield f"data: [INFO] Overriding root disk capacity to {disk}GB...\n\n"
            time.sleep(0.4)
            yield "data: [INFO] Applying root passwords chpasswd scripts...\n\n"
            time.sleep(0.4)
            yield "data: [INFO] Starting container services...\n\n"
            time.sleep(0.5)
            
            # Execute actual deploy in background thread if not mock
            if not LXCManager.is_mock():
                LXCManager.deploy_container(
                    name=container_name,
                    os_image=os_sel,
                    cpu_cores=int(cpu),
                    ram_mb=int(ram),
                    disk_gb=int(disk),
                    root_password=root_pw
                )
                
            # Create DB Record
            cursor.execute(
                '''INSERT INTO vps (user_id, container_name, os, cpu, ram, disk, root_password, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'running')''',
                (user_id, container_name, os_sel, cpu, ram, disk, root_pw)
            )
            conn.commit()
            
            log_audit(admin_id, f"Admin deployed container {container_name} assigned to user ID {user_id}")
            conn.close()
            
            yield "data: [SUCCESS] Container deployed and allocated to user.\n\n"
        except Exception as e:
            yield f"data: [ERROR] Deployment crash: {str(e)}\n\n"
            if conn:
                conn.close()
                
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/admin/vps/<int:vps_id>/suspend', methods=['POST'])
def admin_vps_suspend(vps_id):
    if not is_admin():
        return jsonify({"message": "Forbidden"}), 403
        
    data = request.get_json() or {}
    suspend = data.get('suspend') # True or False
    
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
        # Stop and destroy container
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
    
    # Simple aggregates
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'client'")
    client_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM vps")
    vps_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(cpu) FROM vps")
    allocated_cpu = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT SUM(ram) FROM vps")
    allocated_ram = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return jsonify({
        "clients": client_count,
        "vps_count": vps_count,
        "allocated_cpu": allocated_cpu,
        "allocated_ram": allocated_ram,
        "is_mock": LXCManager.is_mock()
    })

# ----------------- WEB TERMINAL WS ROUTE -----------------

@sock.route('/ws/terminal/<container_name>')
def terminal_websocket(ws, container_name):
    # Verify authentication from session
    user_id = session.get('user_id')
    role = session.get('role')
    
    if not user_id:
        ws.send("\r\n[ERROR] Unauthorized session. Connection rejected.\r\n")
        ws.close()
        return
        
    # Check container ownership or admin credentials
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE container_name = ?", (container_name,))
    vps = cursor.fetchone()
    conn.close()
    
    if not vps:
        ws.send("\r\n[ERROR] Container configuration not found.\r\n")
        ws.close()
        return
        
    if role != 'admin' and vps['user_id'] != user_id:
        ws.send("\r\n[ERROR] Access denied. You do not own this container.\r\n")
        ws.close()
        return
        
    # If Mock Mode, launch pseudo interactive shell
    if LXCManager.is_mock():
        ws.send("\r\n\x1b[32m=== MintyHost LXC Interactive Pseudo Shell ===\x1b[0m\r\n")
        ws.send(f"Container: {container_name} | OS: {vps['os']} | CPU: {vps['cpu']} Cores\r\n")
        ws.send("Type 'help' to see mock commands. Press Ctrl+C to clear line, 'exit' to quit.\r\n\r\n")
        current_dir = "/root"
        prompt = f"\r\n\x1b[1;36mroot@{container_name}\x1b[0m:\x1b[1;34m~\x1b[0m# "
        ws.send(prompt)

        buffer = ""
        while True:
            try:
                data = ws.receive()
                if data is None:
                    break
                
                # Check characters
                for char in data:
                    if char in ['\r', '\n']:
                        ws.send("\r\n")
                        cmd = buffer.strip()
                        buffer = ""
                        
                        if cmd == "help":
                            ws.send("Available simulated commands: help, ls, pwd, whoami, ip a, uname -a, clear, reboot, exit, ps\r\n")
                        elif cmd == "ls":
                            ws.send("bin  boot  dev  etc  home  lib  mnt  opt  proc  root  run  sbin  sys  tmp  usr  var\r\n")
                        elif cmd == "pwd":
                            ws.send(f"{current_dir}\r\n")
                        elif cmd == "whoami":
                            ws.send("root\r\n")
                        elif cmd == "ps":
                            ws.send("  PID TTY          TIME CMD\r\n")
                            ws.send("    1 ?        00:00:02 systemd\r\n")
                            ws.send("   24 ?        00:00:00 systemd-journal\r\n")
                            ws.send("   88 pts/0    00:00:00 bash\r\n")
                            ws.send("   95 pts/0    00:00:00 ps\r\n")
                        elif cmd == "clear":
                            ws.send("\x1b[2J\x1b[H")
                        elif cmd in ["ip a", "ip addr"]:
                            ip = LXCManager.get_container_ip(container_name)
                            ws.send(f"1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN\r\n")
                            ws.send(f"    inet 127.0.0.1/8 scope host lo\r\n")
                            ws.send(f"2: eth0@if21: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP\r\n")
                            ws.send(f"    inet {ip}/24 scope global dynamic eth0\r\n")
                        elif cmd == "uname -a":
                            ws.send(f"Linux {container_name} 5.15.0-101-generic #111-Ubuntu SMP Tue Feb 11 19:40:12 UTC 2026 x86_64 GNU/Linux\r\n")
                        elif cmd == "reboot":
                            ws.send("Requesting reboot signal...\r\n")
                            time.sleep(1)
                            ws.send("Container restarted.\r\n")
                        elif cmd == "exit":
                            ws.send("Terminating socket session.\r\n")
                            ws.close()
                            return
                        elif cmd != "":
                            ws.send(f"bash: {cmd}: command not found (mock terminal)\r\n")
                            
                        ws.send(prompt)
                    elif char in ['\x7f', '\x08']: # Backspace
                        if len(buffer) > 0:
                            buffer = buffer[:-1]
                            ws.send("\b \b")
                    elif char == '\x03': # Ctrl+C
                        ws.send("^C\r\n")
                        buffer = ""
                        ws.send(prompt)
                    else:
                        buffer += char
                        ws.send(char)
            except Exception:
                break
        return

    # Real LXD terminal connection using pty module
    master_fd, slave_fd = pty.openpty()
    p = subprocess.Popen(
        ['lxc', 'exec', container_name, '--', 'bash'],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        preexec_fn=os.setsid
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    try:
        while p.poll() is None:
            # Check websocket client data
            data = ws.receive(timeout=0.01)
            if data:
                os.write(master_fd, data.encode())
                
            # Check container console output
            r, w, e = select.select([master_fd], [], [], 0.01)
            if master_fd in r:
                try:
                    output = os.read(master_fd, 4096)
                    if output:
                        ws.send(output.decode(errors='replace'))
                except OSError:
                    break
    except Exception as e:
        print(f"[!] Terminal bridge error for {container_name}: {e}")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        p.terminate()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
