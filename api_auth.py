"""
api_auth.py — API key authentication utilities.

Usage in routes:
    from api_auth import require_api_key
    from flask import g

    @bp.route('/api/v1/vps')
    @require_api_key()
    def list_vps():
        user_id = g.api_user_id   # authenticated user's id
        role    = g.api_user_role # 'admin' or 'client'
        ...

    # Admin-only:
    @require_api_key(roles=['admin'])
"""

import secrets
import functools
from flask import request, jsonify, g
from database import get_db_connection


def generate_api_key() -> str:
    """Return a cryptographically-secure 64-hex-character API key."""
    return secrets.token_hex(32)


def _lookup_key(raw_key: str):
    """Return the api_keys row dict for raw_key, or None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ak.*, u.username, u.email
        FROM api_keys ak
        JOIN users u ON ak.user_id = u.id
        WHERE ak.key = ?
        """,
        (raw_key,)
    )
    row = cursor.fetchone()
    if row:
        # Stamp last_used
        cursor.execute(
            "UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE id = ?",
            (row['id'],)
        )
        conn.commit()
    conn.close()
    return dict(row) if row else None


def require_api_key(roles=None):
    """
    Decorator factory.
    roles: list of allowed roles, e.g. ['admin'] or ['admin','client'].
           If None or empty, any valid key is accepted.
    """
    if roles is None:
        roles = []

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return jsonify({
                    "error": "unauthorized",
                    "message": "Missing or malformed Authorization header. Use: Authorization: Bearer <api_key>"
                }), 401

            raw_key = auth_header[len('Bearer '):]
            api_record = _lookup_key(raw_key)

            if not api_record:
                return jsonify({
                    "error": "unauthorized",
                    "message": "Invalid API key."
                }), 401

            if roles and api_record['role'] not in roles:
                return jsonify({
                    "error": "forbidden",
                    "message": f"This endpoint requires one of the following roles: {', '.join(roles)}."
                }), 403

            # Inject into request context
            g.api_user_id   = api_record['user_id']
            g.api_user_role = api_record['role']
            g.api_username  = api_record['username']
            g.api_key_id    = api_record['id']

            return fn(*args, **kwargs)
        return wrapper
    return decorator
