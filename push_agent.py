import os, hmac
from datetime import datetime
from flask import request, jsonify, redirect, url_for
from app import con, auth, shell

TOKEN = os.getenv('MIKROTIK_AGENT_TOKEN','')


def _migrate():
    c = con()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS router_agents(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        identity TEXT,
        source_ip TEXT,
        ros_version TEXT,
        last_seen TEXT,
        last_sync TEXT,
        status TEXT DEFAULT 'OFFLINE',
        pppoe_secrets INTEGER DEFAULT 0,
        pppoe_active INTEGER DEFAULT 0,
        ppp_profiles INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS router_pppoe_secrets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        router_name TEXT,
        name TEXT,
        profile TEXT,
        service TEXT,
        remote_address TEXT,
        caller_id TEXT,
        disabled TEXT,
        comment TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_router_pppoe_secrets_router ON router_pppoe_secrets(router_name);
    CREATE TABLE IF NOT EXISTS router_pppoe_active(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        router_name TEXT,
        name TEXT,
        address TEXT,
        caller_id TEXT,
        service TEXT,
        uptime TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_router_pppoe_active_router ON router_pppoe_active(router_name);
    CREATE TABLE IF NOT EXISTS router_ppp_profiles(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        router_name TEXT,
        name TEXT,
        remote_address TEXT,
        local_address TEXT,
        rate_limit TEXT,
        comment TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_router_ppp_profiles_router ON router_ppp_profiles(router_name);
    ''')
    cols = {r['name'] for r in c.execute('PRAGMA table_info(router_agents)').fetchall()}
    additions = {
        'ros_version': 'ros_version TEXT',
        'last_sync': 'last_sync TEXT',
        'pppoe_secrets': 'pppoe_secrets INTEGER DEFAULT 0',
        'pppoe_active': 'pppoe_active INTEGER DEFAULT 0',
        'ppp_profiles': 'ppp_profiles INTEGER DEFAULT 0',
    }
    for name, ddl in additions.items():
        if name not in cols:
            c.execute(f'ALTER TABLE router_agents ADD COLUMN {ddl}')
    c.commit(); c.close()


def _authorized():
    supplied = request.headers.get('X-InterFlash-Token','')
    return bool(TOKEN) and hmac.compare_digest(supplied, TOKEN)


def _safe(value, limit=255):
    if value is None:
        return ''
    return str(value)[:limit]


def _touch_agent(c, name, identity=None, ros_version=None, status='ONLINE'):
    now = datetime.now().isoformat(timespec='seconds')
    c.execute('''INSERT INTO router_agents(name,identity,source_ip,ros_version,last_seen,status)
                 VALUES(?,?,?,?,?,?)
                 ON CONFLICT(name) DO UPDATE SET
                   identity=COALESCE(NULLIF(excluded.identity,''),router_agents.identity),
                   source_ip=excluded.source_ip,
                   ros_version=COALESCE(NULLIF(excluded.ros_version,''),router_agents.ros_version),
                   last_seen=excluded.last_seen,status=excluded.status''',
              (name, identity or name, request.remote_addr or '', ros_version or '', now, status))


def heartbeat():
    if not _authorized():
        return 'unauthorized', 401
    name = _safe(request.form.get('name') or 'CCR2116', 80).strip()
    identity = _safe(request.form.get('identity') or name, 80).strip()
    ros_version = _safe(request.form.get('version') or '', 80).strip()
    c = con(); _touch_agent(c, name, identity, ros_version, 'ONLINE'); c.commit(); c.close()
    return 'ok', 200


def sync():
    if not _authorized():
        return jsonify(ok=False, error='unauthorized'), 401
    payload = request.get_json(silent=True) or {}
    name = _safe(payload.get('router') or 'CCR2116', 80).strip()
    kind = _safe(payload.get('kind') or '', 20).lower()
    items = payload.get('items') or []
    if not isinstance(items, list):
        return jsonify(ok=False, error='items must be a list'), 400

    c = con()
    try:
        if kind == 'start':
            c.execute('DELETE FROM router_pppoe_secrets WHERE router_name=?', (name,))
            c.execute('DELETE FROM router_pppoe_active WHERE router_name=?', (name,))
            c.execute('DELETE FROM router_ppp_profiles WHERE router_name=?', (name,))
            _touch_agent(c, name, _safe(payload.get('identity') or name, 80), _safe(payload.get('version') or '', 80), 'SYNCING')

        elif kind == 'secrets':
            for x in items:
                if not isinstance(x, dict):
                    continue
                c.execute('''INSERT INTO router_pppoe_secrets
                    (router_name,name,profile,service,remote_address,caller_id,disabled,comment)
                    VALUES(?,?,?,?,?,?,?,?)''', (
                    name, _safe(x.get('name')), _safe(x.get('profile')), _safe(x.get('service')),
                    _safe(x.get('remote-address')), _safe(x.get('caller-id')), _safe(x.get('disabled'), 20),
                    _safe(x.get('comment'), 500)
                ))
            _touch_agent(c, name, status='SYNCING')

        elif kind == 'active':
            for x in items:
                if not isinstance(x, dict):
                    continue
                c.execute('''INSERT INTO router_pppoe_active
                    (router_name,name,address,caller_id,service,uptime)
                    VALUES(?,?,?,?,?,?)''', (
                    name, _safe(x.get('name')), _safe(x.get('address')), _safe(x.get('caller-id')),
                    _safe(x.get('service')), _safe(x.get('uptime'))
                ))
            _touch_agent(c, name, status='SYNCING')

        elif kind == 'profiles':
            for x in items:
                if not isinstance(x, dict):
                    continue
                c.execute('''INSERT INTO router_ppp_profiles
                    (router_name,name,remote_address,local_address,rate_limit,comment)
                    VALUES(?,?,?,?,?,?)''', (
                    name, _safe(x.get('name')), _safe(x.get('remote-address')), _safe(x.get('local-address')),
                    _safe(x.get('rate-limit')), _safe(x.get('comment'), 500)
                ))
            _touch_agent(c, name, status='SYNCING')

        elif kind == 'finish':
            secrets = c.execute('SELECT count(*) c FROM router_pppoe_secrets WHERE router_name=?', (name,)).fetchone()['c']
            active = c.execute('SELECT count(*) c FROM router_pppoe_active WHERE router_name=?', (name,)).fetchone()['c']
            profiles = c.execute('SELECT count(*) c FROM router_ppp_profiles WHERE router_name=?', (name,)).fetchone()['c']
            now = datetime.now().isoformat(timespec='seconds')
            _touch_agent(c, name, _safe(payload.get('identity') or name, 80), _safe(payload.get('version') or '', 80), 'ONLINE')
            c.execute('''UPDATE router_agents SET last_sync=?,pppoe_secrets=?,pppoe_active=?,ppp_profiles=? WHERE name=?''',
                      (now, secrets, active, profiles, name))
        else:
            return jsonify(ok=False, error='unknown kind'), 400
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True, kind=kind, received=len(items))


def agent_view():
    if not auth():
        return redirect(url_for('login'))
    c = con()
    agents = c.execute('SELECT * FROM router_agents ORDER BY id DESC').fetchall()
    trs = ''
    for a in agents:
        cls = 'ok' if a['status'] == 'ONLINE' else ('pending' if a['status'] == 'SYNCING' else 'bad')
        trs += (f"<tr><td><b>{a['name']}</b><br><small>{a['identity'] or ''} {a['ros_version'] or ''}</small></td>"
                f"<td><span class='tag {cls}'>{a['status']}</span><br><small>{a['last_seen'] or '-'}</small></td>"
                f"<td>{a['pppoe_secrets'] or 0}</td><td>{a['pppoe_active'] or 0}</td><td>{a['ppp_profiles'] or 0}</td>"
                f"<td><a class='btn blue' href='{url_for('agent_pppoe_view', name=a['name'])}'>Ver PPPoE</a></td></tr>")
    c.close()
    body = f'''<div class="head"><div><h1>Sincronización MikroTik</h1><p>Lectura segura enviada por el CCR hacia INTER Flash</p></div></div>
    <div class="panel"><table><tr><th>Router</th><th>Estado</th><th>PPPoE</th><th>Activos</th><th>Perfiles</th><th></th></tr>
    {trs or '<tr><td colspan="6" class="empty">Todavía no hay sincronización.</td></tr>'}</table></div>'''
    return shell('MikroTik Sync', body, 'routers')


def agent_pppoe_view(name):
    if not auth():
        return redirect(url_for('login'))
    c = con()
    rows = c.execute('SELECT * FROM router_pppoe_secrets WHERE router_name=? ORDER BY name', (name,)).fetchall()
    active = {r['name']: r for r in c.execute('SELECT * FROM router_pppoe_active WHERE router_name=?', (name,)).fetchall()}
    agent = c.execute('SELECT * FROM router_agents WHERE name=?', (name,)).fetchone()
    c.close()
    trs = ''
    for r in rows:
        a = active.get(r['name'])
        if str(r['disabled']).lower() in ('true','yes'):
            state, cls = 'DESHABILITADO', 'bad'
        elif a:
            state, cls = 'ONLINE', 'ok'
        else:
            state, cls = 'OFFLINE', 'pending'
        addr = a['address'] if a else r['remote_address']
        caller = a['caller_id'] if a else r['caller_id']
        trs += (f"<tr><td><b>{r['name']}</b></td><td>{r['profile'] or '-'}</td><td>{r['service'] or '-'}</td>"
                f"<td>{addr or '-'}</td><td>{caller or '-'}</td><td><span class='tag {cls}'>{state}</span></td></tr>")
    title = agent['identity'] if agent and agent['identity'] else name
    body = f'''<div class="head"><div><h1>PPPoE · {title}</h1><p>{len(active)} conectados · {len(rows)} usuarios sincronizados</p></div>
    <a class="btn" href="{url_for('agent_view')}">Volver</a></div>
    <div class="panel"><table><tr><th>Usuario</th><th>Perfil</th><th>Servicio</th><th>IP</th><th>Caller ID</th><th>Estado</th></tr>
    {trs or '<tr><td colspan="6" class="empty">No hay usuarios sincronizados todavía.</td></tr>'}</table></div>'''
    return shell('PPPoE sincronizado', body, 'routers')


def setup(app):
    _migrate()
    app.add_url_rule('/api/mikrotik/heartbeat', endpoint='mikrotik_heartbeat', view_func=heartbeat, methods=['POST'])
    app.add_url_rule('/api/mikrotik/sync', endpoint='mikrotik_sync', view_func=sync, methods=['POST'])
    app.add_url_rule('/routers/sync', endpoint='agent_view', view_func=agent_view, methods=['GET'])
    app.add_url_rule('/routers/sync/<name>', endpoint='agent_pppoe_view', view_func=agent_pppoe_view, methods=['GET'])
