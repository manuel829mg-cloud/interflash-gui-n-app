"""TV pairing backend prototype. NOT enabled in app.py or production."""
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone
from flask import jsonify, request

def setup(flask_app, database_path, admin_auth):
    def db():
        c = sqlite3.connect(database_path, timeout=20)
        c.row_factory = sqlite3.Row
        return c

    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tv_devices (
            id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
            pairing_code TEXT UNIQUE, name TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0,
            subscription_status TEXT NOT NULL DEFAULT 'PENDING',
            paid_through TEXT, created_at TEXT NOT NULL
        )""")

    @flask_app.post('/api/tv-native/register')
    def tv_native_register():
        data = request.get_json(silent=True) or {}
        token = data.get('token')
        if not isinstance(token, str) or len(token) != 64:
            return jsonify(error='Invalid device token'), 400
        try:
            bytes.fromhex(token)
        except ValueError:
            return jsonify(error='Invalid device token'), 400
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with db() as c:
            row = c.execute('SELECT * FROM tv_devices WHERE token_hash=?', (token_hash,)).fetchone()
            if row is None:
                for _ in range(10):
                    code = str(secrets.randbelow(9000000) + 1000000)
                    try:
                        c.execute('INSERT INTO tv_devices(token_hash,pairing_code,name,created_at) VALUES(?,?,?,?)',
                                  (token_hash, code, 'Inter Flash TV', datetime.now(timezone.utc).isoformat()))
                        break
                    except sqlite3.IntegrityError:
                        continue
                else:
                    return jsonify(error='Unable to generate pairing code'), 503
                row = c.execute('SELECT * FROM tv_devices WHERE token_hash=?', (token_hash,)).fetchone()
        return jsonify(code=row['pairing_code'], approved=bool(row['approved']))

    @flask_app.get('/api/tv-native/config')
    def tv_native_config():
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify(error='Missing device token'), 401
        token = auth[7:]
        if len(token) != 64:
            return jsonify(error='Invalid device token'), 401
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with db() as c:
            row = c.execute('SELECT * FROM tv_devices WHERE token_hash=?', (token_hash,)).fetchone()
        if row is None or not row['approved']:
            return jsonify(error='Device not linked'), 403
        if row['subscription_status'] != 'ACTIVE':
            return jsonify(error='TV subscription suspended', code='TV_SUSPENDED'), 403
        # Do not expose a permanent M3U URL. Stream authorization must be
        # implemented before enabling subscription playback in production.
        return jsonify(error='Streaming authorization not configured'), 503
