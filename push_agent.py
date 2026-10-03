import os, hmac, sqlite3
from datetime import datetime
from flask import request
from app import con

TOKEN = os.getenv('MIKROTIK_AGENT_TOKEN','')


def _migrate():
    c = con()
    c.execute('''CREATE TABLE IF NOT EXISTS router_agents(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        identity TEXT,
        source_ip TEXT,
        last_seen TEXT,
        status TEXT DEFAULT 'OFFLINE'
    )''')
    c.commit(); c.close()


def _authorized():
    supplied = request.headers.get('X-InterFlash-Token','')
    return bool(TOKEN) and hmac.compare_digest(supplied, TOKEN)


def heartbeat():
    if not _authorized():
        return 'unauthorized', 401
    name = (request.form.get('name') or 'CCR2116').strip()[:80]
    identity = (request.form.get('identity') or name).strip()[:80]
    now = datetime.now().isoformat(timespec='seconds')
    c = con()
    c.execute('''INSERT INTO router_agents(name,identity,source_ip,last_seen,status)
                 VALUES(?,?,?,?, 'ONLINE')
                 ON CONFLICT(name) DO UPDATE SET identity=excluded.identity,
                 source_ip=excluded.source_ip,last_seen=excluded.last_seen,status='ONLINE' ''',
              (name, identity, request.remote_addr or '', now))
    c.commit(); c.close()
    return 'ok', 200


def setup(app):
    _migrate()
    app.add_url_rule('/api/mikrotik/heartbeat', endpoint='mikrotik_heartbeat', view_func=heartbeat, methods=['POST'])
