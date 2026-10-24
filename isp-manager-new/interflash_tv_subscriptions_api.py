"""Admin-only subscription routes for the optional TV module."""
from flask import Blueprint, jsonify, request, abort
import sqlite3
from interflash_tv_subscribers import init_subscribers, set_subscription, is_entitled

def setup(app, db_path, admin_check):
    init_subscribers(db_path)
    bp = Blueprint("tv_subs", __name__, url_prefix="/interflash-tv/api")
    @bp.get("/subscribers")
    def subscribers():
        if not admin_check(): abort(403)
        with sqlite3.connect(db_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT isp_client_id,status,expires_at FROM tv_subscribers ORDER BY id DESC LIMIT 500").fetchall()
        return jsonify(subscribers=[dict(row) for row in rows])
    @bp.post("/subscribers")
    def save():
        if not admin_check(): abort(403)
        data = request.get_json(silent=True) or {}
        client_id = str(data.get("isp_client_id", "")).strip()
        status = data.get("status")
        expiry = data.get("expires_at")
        if not client_id.isdecimal() or status not in ("inactive","active","suspended"):
            return jsonify(error="Invalid client or status"), 400
        if status == "active" and not expiry:
            return jsonify(error="Expiry required"), 400
        try:
            set_subscription(db_path, client_id, status, expiry)
            entitled = is_entitled(db_path, client_id)
        except ValueError:
            return jsonify(error="Invalid expiry"), 400
        return jsonify(isp_client_id=client_id, status=status, entitled=entitled)
    app.register_blueprint(bp)
