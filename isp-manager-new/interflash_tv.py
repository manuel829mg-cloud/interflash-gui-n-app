"""Inter Flash TV: isolated blueprint prototype (not registered in production)."""
from flask import Blueprint, jsonify, request

tv = Blueprint("interflash_tv", __name__, url_prefix="/interflash-tv")

# Demo metadata only. Add licensed streams through an admin workflow later.
CHANNELS = []

@tv.get("/api/channels")
def channels():
    return jsonify({"channels": CHANNELS, "count": len(CHANNELS)})

@tv.get("/api/status")
def status():
    return jsonify({"module": "Inter Flash TV", "phase": "prototype", "ready_for_production": False})

def setup(app):
    """Register only in a dedicated test app after authentication is integrated."""
    app.register_blueprint(tv)
