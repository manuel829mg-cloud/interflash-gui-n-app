"""TV device access. Administrator provisions tokens; active subscriptions are checked on every catalog request."""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, abort, jsonify, request
from interflash_tv_subscribers import is_entitled

def setup(app, db_path, admin_check):
    bp = Blueprint("tv_device_access", __name__, url_prefix="/interflash-tv/api")
    def connect():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS tv_device_tokens (
            token_hash TEXT PRIMARY KEY, isp_client_id TEXT NOT NULL,
            created_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
        )""")
        db.commit()
        return db

    @bp.post("/devices")
    def provision():
        if not admin_check():
            abort(403)
        data = request.get_json(silent=True) or {}
        client_id = str(data.get("isp_client_id", "")).strip()
        if not client_id.isdecimal() or len(client_id) > 12:
            return jsonify(error="Invalid client ID"), 400
        if not is_entitled(db_path, client_id):
            return jsonify(error="TV subscription is not active"), 409
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect() as db:
            db.execute("INSERT INTO tv_device_tokens VALUES (?,?,?,0)",
                       (digest, client_id, datetime.now(timezone.utc).isoformat()))
            db.commit()
        return jsonify(device_token=token, isp_client_id=client_id), 201

    @bp.get("/device/channels")
    def device_channels():
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            abort(401)
        token = auth[7:].strip()
        if len(token) < 32 or len(token) > 256:
            abort(401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect() as db:
            row = db.execute("SELECT isp_client_id FROM tv_device_tokens WHERE token_hash=? AND revoked=0", (digest,)).fetchone()
            if not row or not is_entitled(db_path, row["isp_client_id"]):
                abort(403)
            channels = db.execute("SELECT id,name,category,stream_url FROM tv_channels WHERE enabled=1 AND rights_confirmed=1 ORDER BY category,name").fetchall()
        return jsonify(channels=[dict(channel) for channel in channels])

    @bp.post("/devices/revoke")
    def revoke():
        if not admin_check():
            abort(403)
        client_id = str((request.get_json(silent=True) or {}).get("isp_client_id", "")).strip()
        if not client_id.isdecimal():
            return jsonify(error="Invalid client ID"), 400
        with connect() as db:
            cursor = db.execute("UPDATE tv_device_tokens SET revoked=1 WHERE isp_client_id=?", (client_id,))
            db.commit()
        return jsonify(revoked=cursor.rowcount)

    app.register_blueprint(bp)
