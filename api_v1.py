"""
api_v1.py — REST API v1 Blueprint
Mounted at /api/v1 — all routes require Bearer token authentication.

Client routes: accessible with any valid API key for the resource owner.
Admin  routes: require a key whose role == 'admin'.
"""

from flask import Blueprint, request, jsonify, g
from werkzeug.security import generate_password_hash
from api_auth import require_api_key, generate_api_key
from database import get_db_connection
from lxc_manager import LXCManager, IS_MOCK_LXC
import threading
import random
import discord_notify

bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_node(node_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _make_node_request(node, endpoint, method='POST', data=None):
    import urllib.request, json
    scheme = "https" if node['port'] in (443, 8443) else "http"
    url = f"{scheme}://{node['fqdn']}:{node['port']}{endpoint}"
    headers = {
        "Authorization": f"Bearer {node['api_key']}",
        "Content-Type": "application/json"
    }
    req_data = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), resp.status
    except Exception as e:
        return {"message": str(e)}, 500


def _own_vps(vps_id, user_id, role):
    """Return vps dict if user owns it (or is admin), else None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if role == 'admin':
        cursor.execute("SELECT * FROM vps WHERE id = ?", (vps_id,))
    else:
        cursor.execute("SELECT * FROM vps WHERE id = ? AND user_id = ?", (vps_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _log(user_id, action):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO logs (user_id, action) VALUES (?, ?)", (user_id, action))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENDPOINT — no auth needed (used by Discord bot for branding)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/settings/public', methods=['GET'])
def public_settings():
    """Returns safe public branding settings — no auth required."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    safe_keys = {'site_name', 'color_primary', 'color_secondary', 'color_accent', 'color_cool', 'logo_url', 'favicon_url'}
    settings = {r['key']: r['value'] for r in rows if r['key'] in safe_keys}
    return jsonify(settings)


# ─────────────────────────────────────────────────────────────────────────────
# API KEY MANAGEMENT (client manages own keys)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/keys', methods=['GET'])
@require_api_key()
def list_keys():
    """List all API keys for the authenticated user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, key, role, created_at, last_used FROM api_keys WHERE user_id = ? ORDER BY id DESC",
        (g.api_user_id,)
    )
    keys = [dict(r) for r in cursor.fetchall()]
    conn.close()
    # Mask key — show only first 8 + last 4 chars
    for k in keys:
        raw = k['key']
        k['key_masked'] = raw[:8] + '•' * (len(raw) - 12) + raw[-4:]
    return jsonify(keys)


@bp.route('/keys', methods=['POST'])
@require_api_key()
def create_key():
    """Create a new API key."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"error": "validation", "message": "Key name is required."}), 400
    if len(name) > 64:
        return jsonify({"error": "validation", "message": "Key name must be ≤ 64 characters."}), 400

    new_key = generate_api_key()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO api_keys (user_id, name, key, role) VALUES (?, ?, ?, ?)",
        (g.api_user_id, name, new_key, g.api_user_role)
    )
    key_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"Created API key '{name}' via API")
    return jsonify({
        "status": "success",
        "message": "API key created. Store it securely — it will not be shown again.",
        "key": {
            "id": key_id,
            "name": name,
            "key": new_key,   # Only time the full key is returned
            "role": g.api_user_role
        }
    }), 201


@bp.route('/keys/<int:key_id>', methods=['DELETE'])
@require_api_key()
def delete_key(key_id):
    """Delete an API key. Users can only delete their own keys."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM api_keys WHERE id = ? AND user_id = ?", (key_id, g.api_user_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not_found", "message": "API key not found."}), 404
    cursor.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"Deleted API key ID {key_id}")
    return jsonify({"status": "success", "message": "API key revoked."})


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/profile', methods=['GET'])
@require_api_key()
def get_profile():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, pfp FROM users WHERE id = ?", (g.api_user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not_found", "message": "User not found."}), 404
    return jsonify(dict(row))


@bp.route('/profile', methods=['PUT'])
@require_api_key()
def update_profile():
    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    email = data.get('email', '').strip().lower()
    if not username or not email:
        return jsonify({"error": "validation", "message": "Username and email are required."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM users WHERE (username = ? OR email = ?) AND id != ?",
        (username, email, g.api_user_id)
    )
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "conflict", "message": "Username or email already taken."}), 409
    cursor.execute(
        "UPDATE users SET username = ?, email = ? WHERE id = ?",
        (username, email, g.api_user_id)
    )
    conn.commit()
    conn.close()
    _log(g.api_user_id, "Updated profile via API")
    return jsonify({"status": "success", "message": "Profile updated."})


@bp.route('/profile/password', methods=['PUT'])
@require_api_key()
def update_profile_password():
    from werkzeug.security import check_password_hash
    data = request.get_json() or {}
    current = data.get('current_password', '')
    new_pw = data.get('new_password', '')
    if not current or not new_pw or len(new_pw) < 6:
        return jsonify({"error": "validation", "message": "current_password and new_password (min 6 chars) required."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id = ?", (g.api_user_id,))
    row = cursor.fetchone()
    if not row or not check_password_hash(row['password_hash'], current):
        conn.close()
        return jsonify({"error": "unauthorized", "message": "Current password is incorrect."}), 401
    cursor.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_pw), g.api_user_id)
    )
    conn.commit()
    conn.close()
    _log(g.api_user_id, "Changed panel password via API")
    return jsonify({"status": "success", "message": "Password changed."})


# ─────────────────────────────────────────────────────────────────────────────
# VPS — CLIENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/vps', methods=['GET'])
@require_api_key()
def list_vps():
    conn = get_db_connection()
    cursor = conn.cursor()
    if g.api_user_role == 'admin':
        cursor.execute("""
            SELECT v.*, u.username as owner_username
            FROM vps v LEFT JOIN users u ON v.user_id = u.id
            ORDER BY v.id DESC
        """)
    else:
        cursor.execute("SELECT * FROM vps WHERE user_id = ? ORDER BY id DESC", (g.api_user_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/vps/<int:vps_id>', methods=['GET'])
@require_api_key()
def get_vps(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    return jsonify(vps)


@bp.route('/vps/<int:vps_id>/stats', methods=['GET'])
@require_api_key()
def vps_stats(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    if vps['node_id'] != 1:
        node = _get_node(vps['node_id'])
        if not node:
            return jsonify({"error": "node_error", "message": "Remote node not found."}), 404
        res, code = _make_node_request(node, "/api/vps/stats", data={
            "name": vps['container_name'], "cpu": vps['cpu'],
            "ram": vps['ram'], "disk": vps['disk'],
            "status": vps['status'], "vps_id": vps_id
        })
        return jsonify(res), code
    stats = LXCManager.get_container_stats(
        name=vps['container_name'], plan_cpu=vps['cpu'],
        plan_ram=vps['ram'], plan_disk=vps['disk'],
        db_status=vps['status'], vps_id=vps_id
    )
    return jsonify(stats)


@bp.route('/vps/<int:vps_id>/action', methods=['POST'])
@require_api_key()
def vps_action(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    data = request.get_json() or {}
    action = data.get('action')
    if action not in ('start', 'stop', 'restart'):
        return jsonify({"error": "validation", "message": "action must be: start, stop, restart"}), 400
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            if not node:
                return jsonify({"error": "node_error", "message": "Remote node not found."}), 404
            res, code = _make_node_request(node, "/api/vps/action", data={
                "name": vps['container_name'], "action": action, "vps_id": vps_id
            })
            if code != 200:
                return jsonify(res), code
        else:
            LXCManager.execute_action(vps['container_name'], action)
            if action in ('start', 'restart'):
                threading.Thread(target=LXCManager.ensure_pinggy_tunnel_setup, args=(vps['container_name'],)).start()
        new_status = 'running' if action in ('start', 'restart') else 'stopped'
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps_id))
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: {action} on VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": f"Action '{action}' initiated.", "new_status": new_status})
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/vps/<int:vps_id>/password', methods=['POST'])
@require_api_key()
def vps_password(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    data = request.get_json() or {}
    new_pw = data.get('password', '').strip()
    if len(new_pw) < 6:
        return jsonify({"error": "validation", "message": "Password must be at least 6 characters."}), 400
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            if not node:
                return jsonify({"error": "node_error", "message": "Remote node not found."}), 404
            res, code = _make_node_request(node, "/api/vps/password", data={
                "name": vps['container_name'], "password": new_pw
            })
            return jsonify(res), code
        LXCManager.change_root_password(vps['container_name'], new_pw)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE vps SET root_password = ? WHERE id = ?", (new_pw, vps_id))
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: Changed root password for VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": "Root password updated."})
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/vps/<int:vps_id>/reinstall', methods=['POST'])
@require_api_key()
def vps_reinstall(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    data = request.get_json() or {}
    new_os = data.get('os', vps['os'])
    password = data.get('password', vps['root_password'])
    SUPPORTED_OS = ['ubuntu/22.04', 'debian/11', 'debian/12', 'ubuntu/24.04', 'centos/9-stream', 'alpine/3.18', 'windows/10']
    if new_os not in SUPPORTED_OS:
        return jsonify({"error": "validation", "message": f"Unsupported OS. Choose from: {', '.join(SUPPORTED_OS)}"}), 400
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            if not node:
                return jsonify({"error": "node_error", "message": "Remote node not found."}), 404
            res, code = _make_node_request(node, "/api/vps/reinstall", data={
                "name": vps['container_name'], "os": new_os, "password": password
            })
            return jsonify(res), code
        LXCManager.reinstall_os(vps['container_name'], new_os, password, vps['cpu'], vps['ram'], vps['disk'])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE vps SET os = ?, root_password = ? WHERE id = ?", (new_os, password, vps_id))
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: Reinstalled OS to {new_os} on VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": f"OS reinstalled to {new_os}."})
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


# ─── SNAPSHOTS ───────────────────────────────────────────────────────────────

@bp.route('/vps/<int:vps_id>/snapshots', methods=['GET'])
@require_api_key()
def list_snapshots(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM snapshots WHERE vps_id = ? ORDER BY id DESC", (vps_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/vps/<int:vps_id>/snapshots', methods=['POST'])
@require_api_key()
def create_snapshot(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    data = request.get_json() or {}
    import time
    snap_name = data.get('name', f"snap-{int(time.time())}")
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            res, code = _make_node_request(node, "/api/vps/snapshots", data={
                "name": vps['container_name'], "snapshot_name": snap_name
            })
            return jsonify(res), code
        LXCManager.create_snapshot(vps['container_name'], snap_name)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO snapshots (vps_id, name) VALUES (?, ?)", (vps_id, snap_name))
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: Created snapshot '{snap_name}' for VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": "Snapshot created.", "name": snap_name}), 201
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/vps/<int:vps_id>/snapshots/restore', methods=['POST'])
@require_api_key()
def restore_snapshot(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    data = request.get_json() or {}
    snap_name = data.get('name', '').strip()
    if not snap_name:
        return jsonify({"error": "validation", "message": "Snapshot name is required."}), 400
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            res, code = _make_node_request(node, "/api/vps/snapshots/restore", data={
                "name": vps['container_name'], "snapshot_name": snap_name
            })
            return jsonify(res), code
        LXCManager.restore_snapshot(vps['container_name'], snap_name)
        _log(g.api_user_id, f"API: Restored snapshot '{snap_name}' on VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": f"Snapshot '{snap_name}' restored."})
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/vps/<int:vps_id>/snapshots/<string:snap_name>', methods=['DELETE'])
@require_api_key()
def delete_snapshot(vps_id, snap_name):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            res, code = _make_node_request(node, f"/api/vps/snapshots/{snap_name}", method='DELETE', data={
                "name": vps['container_name']
            })
            return jsonify(res), code
        LXCManager.delete_snapshot(vps['container_name'], snap_name)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM snapshots WHERE vps_id = ? AND name = ?", (vps_id, snap_name))
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: Deleted snapshot '{snap_name}' from VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": "Snapshot deleted."})
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


# ─── BACKUPS ─────────────────────────────────────────────────────────────────

@bp.route('/vps/<int:vps_id>/backups', methods=['GET'])
@require_api_key()
def list_backups(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM backups WHERE vps_id = ? ORDER BY id DESC", (vps_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/vps/<int:vps_id>/backups', methods=['POST'])
@require_api_key()
def create_backup(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    import time
    backup_filename = f"backup-{vps['container_name']}-{int(time.time())}.tar.gz"
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            res, code = _make_node_request(node, "/api/vps/backups", data={"name": vps['container_name']})
            return jsonify(res), code
        LXCManager.create_backup(vps['container_name'], backup_filename)
        size_mb = round(random.uniform(80, 400), 1)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO backups (vps_id, filename, size) VALUES (?, ?, ?)",
            (vps_id, backup_filename, f"{size_mb} MB")
        )
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: Created backup {backup_filename}")
        return jsonify({"status": "success", "message": "Backup created.", "filename": backup_filename}), 201
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


# ─── FIREWALL ─────────────────────────────────────────────────────────────────

@bp.route('/vps/<int:vps_id>/firewall', methods=['GET'])
@require_api_key()
def list_firewall(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM firewall_rules WHERE vps_id = ? ORDER BY id", (vps_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/vps/<int:vps_id>/firewall', methods=['POST'])
@require_api_key()
def add_firewall_rule(vps_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    data = request.get_json() or {}
    protocol = data.get('protocol', '').upper()
    port = data.get('port')
    action = data.get('action', '').upper()
    if protocol not in ('TCP', 'UDP', 'ICMP'):
        return jsonify({"error": "validation", "message": "protocol must be TCP, UDP, or ICMP"}), 400
    if action not in ('ALLOW', 'DENY'):
        return jsonify({"error": "validation", "message": "action must be ALLOW or DENY"}), 400
    if not isinstance(port, int) or port < 0 or port > 65535:
        return jsonify({"error": "validation", "message": "port must be an integer 0–65535"}), 400
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO firewall_rules (vps_id, protocol, port, action) VALUES (?, ?, ?, ?)",
            (vps_id, protocol, port, action)
        )
        rule_id = cursor.lastrowid
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API: Added firewall rule {protocol}/{port} {action} to VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": "Firewall rule added.", "id": rule_id}), 201
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/vps/<int:vps_id>/firewall/<int:rule_id>', methods=['DELETE'])
@require_api_key()
def delete_firewall_rule(vps_id, rule_id):
    vps = _own_vps(vps_id, g.api_user_id, g.api_user_role)
    if not vps:
        return jsonify({"error": "not_found", "message": "VPS not found or access denied."}), 404
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM firewall_rules WHERE id = ? AND vps_id = ?", (rule_id, vps_id))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "not_found", "message": "Firewall rule not found."}), 404
    cursor.execute("DELETE FROM firewall_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API: Deleted firewall rule {rule_id} from VPS {vps['container_name']}")
    return jsonify({"status": "success", "message": "Firewall rule deleted."})


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/admin/stats', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'client'")
    clients = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM vps")
    vps_count = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(cpu),0) FROM vps")
    allocated_cpu = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(ram),0) FROM vps")
    allocated_ram = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM api_keys")
    total_keys = cursor.fetchone()[0]
    conn.close()
    return jsonify({
        "clients": clients,
        "vps_count": vps_count,
        "allocated_cpu": allocated_cpu,
        "allocated_ram": allocated_ram,
        "total_api_keys": total_keys,
        "is_mock": IS_MOCK_LXC
    })


@bp.route('/admin/users', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_list_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.role,
               COUNT(v.id) AS vps_count
        FROM users u
        LEFT JOIN vps v ON u.id = v.user_id
        GROUP BY u.id ORDER BY u.id
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/admin/users', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_create_user():
    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role', 'client')
    discord_user_id = data.get('discord_user_id', '').strip()

    if not username or not email or not password:
        return jsonify({"error": "validation", "message": "username, email, password required."}), 400
    if role not in ('admin', 'client'):
        return jsonify({"error": "validation", "message": "role must be admin or client."}), 400
    if len(password) < 6:
        return jsonify({"error": "validation", "message": "Password must be at least 6 characters."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "conflict", "message": "Username or email already registered."}), 409
    cursor.execute(
        "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (username, email, generate_password_hash(password), role)
    )
    uid = cursor.lastrowid
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Created user {username} ({role})")

    # Send Discord notification if requested
    if discord_user_id:
        panel_url = request.url_root.rstrip('/')
        discord_notify.send_user_creation_dm(discord_user_id, username, email, password, panel_url)

    return jsonify({"status": "success", "message": "User created.", "id": uid}), 201


@bp.route('/admin/users/<int:target_id>', methods=['PUT'])
@require_api_key(roles=['admin'])
def admin_update_user(target_id):
    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    email = data.get('email', '').strip().lower()
    role = data.get('role', 'client')
    new_pw = data.get('password')
    if not username or not email:
        return jsonify({"error": "validation", "message": "username and email required."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    if new_pw and len(new_pw) >= 6:
        cursor.execute(
            "UPDATE users SET username=?, email=?, role=?, password_hash=? WHERE id=?",
            (username, email, role, generate_password_hash(new_pw), target_id)
        )
    else:
        cursor.execute(
            "UPDATE users SET username=?, email=?, role=? WHERE id=?",
            (username, email, role, target_id)
        )
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Updated user ID {target_id}")
    return jsonify({"status": "success", "message": "User updated."})


@bp.route('/admin/users/<int:target_id>', methods=['DELETE'])
@require_api_key(roles=['admin'])
def admin_delete_user(target_id):
    if target_id == g.api_user_id:
        return jsonify({"error": "forbidden", "message": "Cannot delete your own account."}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (target_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not_found", "message": "User not found."}), 404
    cursor.execute("DELETE FROM users WHERE id = ?", (target_id,))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Deleted user {row['username']} (ID {target_id})")
    return jsonify({"status": "success", "message": "User deleted."})


@bp.route('/admin/users/<int:target_id>/suspend', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_suspend_user(target_id):
    data = request.get_json() or {}
    suspend = data.get('suspend', True)
    new_role = 'suspended' if suspend else 'client'
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, target_id))
    conn.commit()
    conn.close()
    action = "suspended" if suspend else "unsuspended"
    _log(g.api_user_id, f"API Admin: {action} user ID {target_id}")
    return jsonify({"status": "success", "message": f"User {action}."})


@bp.route('/admin/users/verify', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_verify_user_credentials():
    data = request.get_json() or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({"error": "validation", "message": "username and password required."}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash, role FROM users WHERE username = ? OR email = ?", (username, username))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"valid": False, "message": "User not found."}), 404
        
    from werkzeug.security import check_password_hash
    if check_password_hash(row['password_hash'], password):
        return jsonify({"valid": True, "user": {"id": row['id'], "role": row['role']}})
    else:
        return jsonify({"valid": False, "message": "Invalid password."}), 401


@bp.route('/admin/vps', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_deploy_vps():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    user_id = data.get('user_id')
    os_sel = data.get('os')
    cpu = data.get('cpu')
    ram = data.get('ram')
    disk = data.get('disk')
    root_pw = data.get('root_password', '').strip()
    node_id = data.get('node_id', 1)

    discord_user_id = data.get('discord_user_id', '').strip()

    if not all([name, user_id, os_sel, cpu, ram, disk, root_pw]):
        return jsonify({"error": "validation", "message": "name, user_id, os, cpu, ram, disk, root_password required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "not_found", "message": "Target user not found."}), 404

    container_name = f"vps-{name}-{random.randint(100, 999)}"
    cursor.execute("SELECT * FROM vps WHERE container_name = ?", (container_name,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "conflict", "message": "Container name already taken."}), 409

    try:
        node = None
        if node_id != 1:
            node = _get_node(node_id)
            if not node:
                conn.close()
                return jsonify({"error": "not_found", "message": "Remote node not found."}), 404
            
            res, code = _make_node_request(node, "/api/vps/deploy", data={
                "name": container_name,
                "os": os_sel,
                "cpu": int(cpu),
                "ram": int(ram),
                "disk": int(disk),
                "password": root_pw
            })
            if code != 200:
                conn.close()
                return jsonify({"error": "node_error", "message": res.get('message', 'Remote deploy failed.')}), code
        else:
            LXCManager.deploy_container(
                name=container_name,
                os_image=os_sel,
                cpu_cores=int(cpu),
                ram_mb=int(ram),
                disk_gb=int(disk),
                root_password=root_pw
            )

        cursor.execute(
            '''INSERT INTO vps (user_id, container_name, os, cpu, ram, disk, root_password, status, node_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)''',
            (user_id, container_name, os_sel, cpu, ram, disk, root_pw, node_id)
        )
        vps_id = cursor.lastrowid
        conn.commit()

        cursor.execute("SELECT key, value FROM settings")
        settings = {row['key']: row['value'] for row in cursor.fetchall()}
        site_name_val = settings.get('site_name', 'MintyHost LXC')

        # Spawn unified background thread to handle remote/local setup and notify
        panel_url = request.url_root.rstrip('/')
        import threading
        threading.Thread(
            target=discord_notify.run_post_deploy_and_notify,
            args=(container_name, vps_id, root_pw, site_name_val, node_id, node if node_id != 1 else None, discord_user_id, panel_url)
        ).start()

        _log(g.api_user_id, f"API Admin: Deployed container {container_name} assigned to user ID {user_id}")
        conn.close()
        return jsonify({
            "status": "success",
            "message": "VPS successfully deployed and allocated.",
            "vps": {
                "id": vps_id,
                "container_name": container_name,
                "os": os_sel,
                "cpu": cpu,
                "ram": ram,
                "disk": disk,
                "status": "running"
            }
        }), 201
    except Exception as e:
        conn.close()
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/admin/vps', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_list_vps():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.*, u.username as owner_username
        FROM vps v LEFT JOIN users u ON v.user_id = u.id
        ORDER BY v.id DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/admin/vps/<int:vps_id>', methods=['DELETE'])
@require_api_key(roles=['admin'])
def admin_delete_vps(vps_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ?", (vps_id,))
    vps = cursor.fetchone()
    if not vps:
        conn.close()
        return jsonify({"error": "not_found", "message": "VPS not found."}), 404
    vps = dict(vps)
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            if node:
                _make_node_request(node, "/api/vps/delete", data={"name": vps['container_name']})
        else:
            LXCManager.destroy_container(vps['container_name'])
        cursor.execute("DELETE FROM vps WHERE id = ?", (vps_id,))
        conn.commit()
        _log(g.api_user_id, f"API Admin: Destroyed VPS {vps['container_name']}")
        conn.close()
        return jsonify({"status": "success", "message": "VPS destroyed."})
    except Exception as e:
        conn.close()
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/admin/vps/<int:vps_id>/suspend', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_suspend_vps(vps_id):
    data = request.get_json() or {}
    suspend = data.get('suspend', True)
    action = 'suspend' if suspend else 'resume'
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps WHERE id = ?", (vps_id,))
    vps = cursor.fetchone()
    if not vps:
        conn.close()
        return jsonify({"error": "not_found", "message": "VPS not found."}), 404
    vps = dict(vps)
    try:
        if vps['node_id'] != 1:
            node = _get_node(vps['node_id'])
            if node:
                _make_node_request(node, "/api/vps/action", data={"name": vps['container_name'], "action": action})
        else:
            LXCManager.execute_action(vps['container_name'], action)
        new_status = 'suspended' if suspend else 'running'
        cursor.execute("UPDATE vps SET status = ? WHERE id = ?", (new_status, vps_id))
        conn.commit()
        conn.close()
        word = "suspended" if suspend else "unsuspended"
        _log(g.api_user_id, f"API Admin: {word} VPS {vps['container_name']}")
        return jsonify({"status": "success", "message": f"VPS {word}.", "new_status": new_status})
    except Exception as e:
        conn.close()
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/admin/logs', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_logs():
    limit = min(int(request.args.get('limit', 100)), 500)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT l.id, l.action, l.timestamp, u.username
        FROM logs l LEFT JOIN users u ON l.user_id = u.id
        ORDER BY l.id DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/admin/nodes', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_list_nodes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, fqdn, port, location, status, created_at FROM nodes ORDER BY id")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/admin/nodes', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_create_node():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    fqdn = data.get('fqdn', '').strip()
    port = data.get('port', 5001)
    location = data.get('location', '')
    if not name or not fqdn:
        return jsonify({"error": "validation", "message": "name and fqdn required."}), 400
    import secrets as _s
    api_key = _s.token_hex(24)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO nodes (name, fqdn, port, location, api_key, status) VALUES (?, ?, ?, ?, ?, 'offline')",
            (name, fqdn, port, location, api_key)
        )
        node_id = cursor.lastrowid
        conn.commit()
        conn.close()
        _log(g.api_user_id, f"API Admin: Added node {name} ({fqdn})")
        return jsonify({"status": "success", "message": "Node added.", "id": node_id, "api_key": api_key}), 201
    except Exception as e:
        conn.close()
        return jsonify({"error": "server_error", "message": str(e)}), 500


@bp.route('/admin/nodes/<int:node_id>', methods=['DELETE'])
@require_api_key(roles=['admin'])
def admin_delete_node(node_id):
    if node_id == 1:
        return jsonify({"error": "forbidden", "message": "Cannot delete the local node."}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM nodes WHERE id = ?", (node_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not_found", "message": "Node not found."}), 404
    cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Deleted node {row['name']}")
    return jsonify({"status": "success", "message": "Node deleted."})


@bp.route('/admin/settings', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_get_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = {r['key']: r['value'] for r in cursor.fetchall()}
    conn.close()
    return jsonify(rows)


@bp.route('/admin/settings', methods=['PUT'])
@require_api_key(roles=['admin'])
def admin_update_settings():
    data = request.get_json() or {}
    allowed = {
        'site_name', 'color_primary', 'color_secondary', 'color_accent', 'color_cool',
        'about_intro', 'about_mission', 'about_infra', 'about_why_trust', 'tos_content'
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "validation", "message": f"No valid settings fields provided. Valid: {', '.join(sorted(allowed))}"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    for k, v in updates.items():
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Updated settings: {', '.join(updates.keys())}")
    return jsonify({"status": "success", "message": "Settings updated.", "updated": list(updates.keys())})


@bp.route('/admin/plans', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_list_plans():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vps_plans ORDER BY id")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@bp.route('/admin/plans', methods=['POST'])
@require_api_key(roles=['admin'])
def admin_create_plan():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    price = data.get('price', 0)
    price_credits = data.get('price_credits', 0)
    ram = data.get('ram', '')
    cpu = data.get('cpu', '')
    storage = data.get('storage', '')
    bandwidth = data.get('bandwidth', '')
    if not all([name, ram, cpu, storage, bandwidth]):
        return jsonify({"error": "validation", "message": "name, ram, cpu, storage, bandwidth required."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO vps_plans (name, price, price_credits, ram, cpu, storage, bandwidth) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, price, price_credits, ram, cpu, storage, bandwidth)
    )
    plan_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Created plan '{name}'")
    return jsonify({"status": "success", "message": "Plan created.", "id": plan_id}), 201


@bp.route('/admin/plans/<int:plan_id>', methods=['PUT'])
@require_api_key(roles=['admin'])
def admin_update_plan(plan_id):
    data = request.get_json() or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM vps_plans WHERE id = ?", (plan_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "not_found", "message": "Plan not found."}), 404
    allowed = ('name', 'price', 'price_credits', 'ram', 'cpu', 'storage', 'bandwidth')
    updates = {k: v for k, v in data.items() if k in allowed}
    for k, v in updates.items():
        cursor.execute(f"UPDATE vps_plans SET {k} = ? WHERE id = ?", (v, plan_id))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Updated plan ID {plan_id}")
    return jsonify({"status": "success", "message": "Plan updated."})


@bp.route('/admin/plans/<int:plan_id>', methods=['DELETE'])
@require_api_key(roles=['admin'])
def admin_delete_plan(plan_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM vps_plans WHERE id = ?", (plan_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not_found", "message": "Plan not found."}), 404
    cursor.execute("DELETE FROM vps_plans WHERE id = ?", (plan_id,))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Deleted plan '{row['name']}'")
    return jsonify({"status": "success", "message": "Plan deleted."})


@bp.route('/admin/keys', methods=['GET'])
@require_api_key(roles=['admin'])
def admin_list_all_keys():
    """Admin can see all API keys across all users."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ak.id, ak.name, ak.key, ak.role, ak.created_at, ak.last_used,
               u.username, u.email
        FROM api_keys ak
        JOIN users u ON ak.user_id = u.id
        ORDER BY ak.id DESC
    """)
    keys = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for k in keys:
        raw = k['key']
        k['key_masked'] = raw[:8] + '•' * (len(raw) - 12) + raw[-4:]
    return jsonify(keys)


@bp.route('/admin/keys/<int:key_id>', methods=['DELETE'])
@require_api_key(roles=['admin'])
def admin_revoke_key(key_id):
    """Admin can revoke any user's API key."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM api_keys WHERE id = ?", (key_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not_found", "message": "API key not found."}), 404
    cursor.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()
    _log(g.api_user_id, f"API Admin: Revoked API key '{row['name']}' (ID {key_id})")
    return jsonify({"status": "success", "message": "API key revoked."})
