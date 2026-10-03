import os, hmac
from datetime import datetime
from html import escape
from flask import request, jsonify, redirect, url_for
import app as base

TOKEN = os.getenv('MIKROTIK_RELAY_TOKEN','')


def _safe(v, n=500):
    return '' if v is None else str(v)[:n]


def _auth():
    supplied = request.headers.get('X-InterFlash-Relay','')
    return bool(TOKEN) and hmac.compare_digest(supplied, TOKEN)


def ensure_schema():
    c=base.db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS push_router_agents(
      id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,identity TEXT,ros_version TEXT,
      status TEXT DEFAULT 'OFFLINE',last_seen TEXT,last_sync TEXT,
      pppoe_total INTEGER DEFAULT 0,pppoe_active INTEGER DEFAULT 0,ppp_profiles INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS push_pppoe_secrets(
      id INTEGER PRIMARY KEY AUTOINCREMENT,router_name TEXT,name TEXT,profile TEXT,service TEXT,
      remote_address TEXT,caller_id TEXT,disabled TEXT,comment TEXT
    );
    CREATE TABLE IF NOT EXISTS push_pppoe_active(
      id INTEGER PRIMARY KEY AUTOINCREMENT,router_name TEXT,name TEXT,address TEXT,caller_id TEXT,service TEXT,uptime TEXT
    );
    CREATE TABLE IF NOT EXISTS push_ppp_profiles(
      id INTEGER PRIMARY KEY AUTOINCREMENT,router_name TEXT,name TEXT,remote_address TEXT,local_address TEXT,rate_limit TEXT,comment TEXT
    );
    ''')
    c.commit(); c.close()


def _touch(c,name,identity='',version='',status='ONLINE'):
    now=datetime.now().isoformat(timespec='seconds')
    c.execute('''INSERT INTO push_router_agents(name,identity,ros_version,status,last_seen)
      VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
      identity=COALESCE(NULLIF(excluded.identity,''),push_router_agents.identity),
      ros_version=COALESCE(NULLIF(excluded.ros_version,''),push_router_agents.ros_version),
      status=excluded.status,last_seen=excluded.last_seen''',(name,identity or name,version or '',status,now))


def sync_api():
    if not _auth(): return jsonify(ok=False,error='unauthorized'),401
    p=request.get_json(silent=True)
    if not isinstance(p,dict): return jsonify(ok=False,error='invalid-json'),400
    name=_safe(p.get('router') or 'CCR2116',80).strip(); kind=_safe(p.get('kind') or '',24).lower()
    items=p.get('items') or []
    if isinstance(items,dict): items=[items]
    if not isinstance(items,list): return jsonify(ok=False,error='invalid-items'),400
    c=base.db()
    try:
        if kind=='start':
            c.execute('DELETE FROM push_pppoe_secrets WHERE router_name=?',(name,)); c.execute('DELETE FROM push_pppoe_active WHERE router_name=?',(name,)); c.execute('DELETE FROM push_ppp_profiles WHERE router_name=?',(name,))
            _touch(c,name,_safe(p.get('identity'),80),_safe(p.get('version'),80),'SYNCING')
        elif kind=='secrets':
            for x in items:
                if isinstance(x,dict): c.execute('INSERT INTO push_pppoe_secrets(router_name,name,profile,service,remote_address,caller_id,disabled,comment) VALUES(?,?,?,?,?,?,?,?)',(name,_safe(x.get('name'),255),_safe(x.get('profile'),255),_safe(x.get('service'),80),_safe(x.get('remote-address'),255),_safe(x.get('caller-id'),255),_safe(x.get('disabled'),20),_safe(x.get('comment'))))
            _touch(c,name,status='SYNCING')
        elif kind=='active':
            for x in items:
                if isinstance(x,dict): c.execute('INSERT INTO push_pppoe_active(router_name,name,address,caller_id,service,uptime) VALUES(?,?,?,?,?,?)',(name,_safe(x.get('name'),255),_safe(x.get('address'),255),_safe(x.get('caller-id'),255),_safe(x.get('service'),80),_safe(x.get('uptime'),80)))
            _touch(c,name,status='SYNCING')
        elif kind=='profiles':
            for x in items:
                if isinstance(x,dict): c.execute('INSERT INTO push_ppp_profiles(router_name,name,remote_address,local_address,rate_limit,comment) VALUES(?,?,?,?,?,?)',(name,_safe(x.get('name'),255),_safe(x.get('remote-address'),255),_safe(x.get('local-address'),255),_safe(x.get('rate-limit'),255),_safe(x.get('comment'))))
            _touch(c,name,status='SYNCING')
        elif kind=='finish':
            total=c.execute('SELECT COUNT(*) c FROM push_pppoe_secrets WHERE router_name=?',(name,)).fetchone()['c']; active=c.execute('SELECT COUNT(*) c FROM push_pppoe_active WHERE router_name=?',(name,)).fetchone()['c']; profiles=c.execute('SELECT COUNT(*) c FROM push_ppp_profiles WHERE router_name=?',(name,)).fetchone()['c']; now=datetime.now().isoformat(timespec='seconds')
            _touch(c,name,_safe(p.get('identity'),80),_safe(p.get('version'),80),'ONLINE'); c.execute('UPDATE push_router_agents SET last_sync=?,pppoe_total=?,pppoe_active=?,ppp_profiles=? WHERE name=?',(now,total,active,profiles,name)); base.audit('MIKROTIK_RELAY_SYNC',f'{name} {active}/{total}')
        else: return jsonify(ok=False,error='unknown-kind'),400
        c.commit()
    finally: c.close()
    return jsonify(ok=True,kind=kind,received=len(items))


def view():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); agents=c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall(); c.close(); rows=[]
    for a in agents:
        cls='ok' if a['status']=='ONLINE' else 'warn'
        rows.append(f'''<tr><td><b>{escape(a['name'] or '')}</b><br><span class="muted">{escape(a['identity'] or '')}</span></td><td><span class="tag {cls}">{escape(a['status'] or '')}</span></td><td>{escape(a['ros_version'] or '-')}</td><td>{int(a['pppoe_active'] or 0)} / {int(a['pppoe_total'] or 0)}</td><td>{int(a['ppp_profiles'] or 0)}</td><td>{escape(a['last_sync'] or '-')}</td><td><a class="btn blue" href="{url_for('router_push_pppoe',name=a['name'])}">Ver PPPoE</a></td></tr>''')
    table=''.join(rows) or '<tr><td colspan="7" class="muted">Esperando la primera sincronización desde la página anterior.</td></tr>'
    body=f'''<div class="head"><div><h1>Sincronización segura</h1><p>La página anterior recibe el CCR2116 y reenvía una copia a este sistema.</p></div><a class="btn" href="{url_for('routers')}">← Volver</a></div><div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Solo lectura.</b> No abre 8728/8729 y no modifica clientes.</div><table class="table"><tr><th>Router</th><th>Estado</th><th>RouterOS</th><th>PPPoE activos/total</th><th>Perfiles</th><th>Última sync</th><th></th></tr>{table}</table></div>'''
    return base.shell('Sincronización segura',body,'routers')


def pppoe(name):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); secrets=c.execute('SELECT * FROM push_pppoe_secrets WHERE router_name=? ORDER BY name',(name,)).fetchall(); act=c.execute('SELECT * FROM push_pppoe_active WHERE router_name=?',(name,)).fetchall(); c.close(); amap={r['name']:r for r in act}; rows=[]
    for r in secrets:
        a=amap.get(r['name']); disabled=str(r['disabled'] or '').lower() in ('true','yes','1'); status,cls=('SUSPENDIDO','bad') if disabled else (('ONLINE','ok') if a else ('OFFLINE','warn')); ip=a['address'] if a else r['remote_address']; caller=a['caller_id'] if a else r['caller_id']
        rows.append(f'''<tr><td><b>{escape(r['name'] or '')}</b></td><td>{escape(r['profile'] or '-')}</td><td>{escape(ip or '-')}</td><td>{escape(caller or '-')}</td><td><span class="tag {cls}">{status}</span></td></tr>''')
    table=''.join(rows) or '<tr><td colspan="5" class="muted">No hay PPPoE sincronizados.</td></tr>'
    return base.shell('PPPoE',f'''<div class="head"><div><h1>PPPoE · {escape(name)}</h1><p>{len(amap)} conectados · {len(secrets)} configurados</p></div><a class="btn" href="{url_for('router_push_view')}">← Volver</a></div><div class="panel"><table class="table"><tr><th>Usuario</th><th>Perfil</th><th>IP</th><th>Caller ID</th><th>Estado</th></tr>{table}</table></div>''','routers')


def setup(app):
    ensure_schema(); app.add_url_rule('/api/mikrotik/relay-sync',endpoint='mikrotik_relay_sync',view_func=sync_api,methods=['POST']); app.add_url_rule('/routers/push-sync',endpoint='router_push_view',view_func=view,methods=['GET']); app.add_url_rule('/routers/push-sync/<name>',endpoint='router_push_pppoe',view_func=pppoe,methods=['GET'])
