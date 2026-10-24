"""Inter Flash TV prototype: channel catalog with separate SQLite storage.

NOT wired into the live application. Call setup(app, db_path=..., admin_check=...)
in a test environment only. Admin routes fail closed until an authentication
callback is provided. Use only streams with redistribution permission.
"""
import os
import sqlite3
from flask import Blueprint, abort, jsonify, request

def setup(app, *, db_path, admin_check=None):
    bp = Blueprint("interflash_tv_admin", __name__, url_prefix="/interflash-tv")
    def connection():
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS tv_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            stream_url TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            rights_confirmed INTEGER NOT NULL DEFAULT 0
        )""")
        return db

    def require_admin():
        if admin_check is None or not admin_check():
            abort(403)

    @bp.get("/api/channels")
    def list_channels():
        require_admin()
        with connection() as db:
            rows = db.execute("SELECT id,name,category,enabled,rights_confirmed FROM tv_channels ORDER BY category,name").fetchall()
        return jsonify(channels=[dict(row) for row in rows])

    @bp.post("/api/channels")
    def create_channel():
        require_admin()
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        url = str(data.get("stream_url", "")).strip()
        category = str(data.get("category", "General")).strip() or "General"
        rights = data.get("rights_confirmed") is True
        if not name or len(name) > 120 or len(category) > 80 or not url.startswith("https://") or not rights:
            return jsonify(error="Nombre, categoria, HTTPS y derechos de distribucion confirmados son obligatorios"), 400
        with connection() as db:
            cursor = db.execute("INSERT INTO tv_channels(name,category,stream_url,rights_confirmed) VALUES(?,?,?,1)", (name,category,url))
            db.commit()
            channel_id = cursor.lastrowid
        return jsonify(id=channel_id, name=name), 201

    @bp.get("/api/status")
    def status():
        require_admin()
        return jsonify(module="Inter Flash TV", phase="prototype", deployed=False)

    app.register_blueprint(bp)
