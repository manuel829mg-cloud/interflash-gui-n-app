import os, hmac, io, csv
from datetime import datetime
from html import escape
from flask import request, jsonify, redirect, url_for, flash, Response
import app as base

TOKEN = os.getenv('MIKROTIK_RELAY_TOKEN','')


def _safe(v, n=500):
    return '' if v is None else str(v)[:n]


def _auth():
    supplied = request.headers.get('X-InterFlash-Relay','')
    return bool(TOKEN) and hmac.compare_digest(supplied, TOKEN)


def _int(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _bps(v):
    try:
        return max(float(v or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _fmt_mbps(v):
    return f'{_bps(v) / 1_000_000:.2f} Mbps'


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
    CREATE TABLE IF NOT EXISTS push_router_traffic(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      router_name TEXT NOT NULL,
      interface_name TEXT NOT NULL,
      rx_bytes INTEGER DEFAULT 0,
      tx_bytes INTEGER DEFAULT 0,
      rx_bps REAL DEFAULT 0,
      tx_bps REAL DEFAULT 0,
      updated_at TEXT,
      UNIQUE(router_name, interface_name)
    );
    CREATE INDEX IF NOT EXISTS idx_push_router_traffic_router ON push_router_traffic(router_name);
    ''')
    c.commit(); c.close()


def _touch(c,name,identity='',version='',status='ONLINE'):
    now=datetime.now().isoformat(timespec='seconds')
    c.execute('''INSERT INTO push_router_agents(name,identity,ros_version,status,last_seen)
      VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
      identity=COALESCE(NULLIF(excluded.identity,''),push_router_agents.identity),
      ros_version=COALESCE(NULLIF(excluded.ros_version,''),push_router_agents.ros_version),
      status=excluded.status,last_seen=excluded.last_seen''',(name,identity or name,version or '',status,now))


def _save_traffic(c, name, items):
    now = datetime.now()
    now_s = now.isoformat(timespec='microseconds')
    for x in items:
        if not isinstance(x, dict):
            continue
        iface = _safe(x.get('name') or x.get('interface'), 120).strip()
        if not iface:
            continue
        # Missing/invalid counters are not a measurement of zero traffic.
        try:
            rx = int(str(x.get('rx-byte') if 'rx-byte' in x else x.get('rx_bytes')))
            tx = int(str(x.get('tx-byte') if 'tx-byte' in x else x.get('tx_bytes')))
            if rx < 0 or tx < 0:
                continue
        except (TypeError, ValueError):
            continue
        prev = c.execute(
            'SELECT rx_bytes,tx_bytes,updated_at FROM push_router_traffic WHERE router_name=? AND interface_name=?',
            (name, iface)
        ).fetchone()
        rx_bps = tx_bps = 0.0
        if prev and prev['updated_at']:
            try:
                before = datetime.fromisoformat(prev['updated_at'])
                seconds = max((now - before).total_seconds(), 0.0)
                # Router counters can repeat between refreshes, and concurrent
                # reporters can arrive only fractions of a second apart.
                # Measure over at least the requested 1.1-second interval;
                # keep BOTH the timestamp and counters until then so bytes
                # are neither lost nor divided by a tiny arrival interval.
                if seconds < 1.1:
                    continue
                if seconds >= 1.1:
                    prev_rx = int(prev['rx_bytes']); prev_tx = int(prev['tx_bytes'])
                    if rx >= prev_rx:
                        rx_bps = ((rx - prev_rx) * 8.0) / seconds
                    if tx >= prev_tx:
                        tx_bps = ((tx - prev_tx) * 8.0) / seconds
            except (TypeError, ValueError):
                pass
        c.execute('''INSERT INTO push_router_traffic(router_name,interface_name,rx_bytes,tx_bytes,rx_bps,tx_bps,updated_at)
                     VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(router_name,interface_name) DO UPDATE SET
                       rx_bytes=excluded.rx_bytes,tx_bytes=excluded.tx_bytes,
                       rx_bps=excluded.rx_bps,tx_bps=excluded.tx_bps,updated_at=excluded.updated_at''',
                  (name, iface, rx, tx, rx_bps, tx_bps, now_s))


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
            c.execute('DELETE FROM push_pppoe_secrets WHERE router_name=?',(name,))
            c.execute('DELETE FROM push_pppoe_active WHERE router_name=?',(name,))
            c.execute('DELETE FROM push_ppp_profiles WHERE router_name=?',(name,))
            _touch(c,name,_safe(p.get('identity'),80),_safe(p.get('version'),80),'SYNCING')
        elif kind=='secrets':
            for x in items:
                if isinstance(x,dict):
                    c.execute('INSERT INTO push_pppoe_secrets(router_name,name,profile,service,remote_address,caller_id,disabled,comment) VALUES(?,?,?,?,?,?,?,?)',
                              (name,_safe(x.get('name'),255),_safe(x.get('profile'),255),_safe(x.get('service'),80),_safe(x.get('remote-address'),255),_safe(x.get('caller-id'),255),_safe(x.get('disabled'),20),_safe(x.get('comment'))))
            _touch(c,name,status='SYNCING')
        elif kind=='active-snapshot':
            c.execute('DELETE FROM push_pppoe_active WHERE router_name=?',(name,))
            for x in items:
                if isinstance(x,dict):
                    c.execute('INSERT INTO push_pppoe_active(router_name,name,address,caller_id,service,uptime) VALUES(?,?,?,?,?,?)',
                              (name,_safe(x.get('name'),255),_safe(x.get('address'),255),_safe(x.get('caller-id'),255),_safe(x.get('service'),80),_safe(x.get('uptime'),80)))
            _touch(c,name,status='ONLINE')
        elif kind=='active':
            for x in items:
                if isinstance(x,dict):
                    c.execute('INSERT INTO push_pppoe_active(router_name,name,address,caller_id,service,uptime) VALUES(?,?,?,?,?,?)',
                              (name,_safe(x.get('name'),255),_safe(x.get('address'),255),_safe(x.get('caller-id'),255),_safe(x.get('service'),80),_safe(x.get('uptime'),80)))
            _touch(c,name,status='SYNCING')
        elif kind=='profiles':
            for x in items:
                if isinstance(x,dict):
                    c.execute('INSERT INTO push_ppp_profiles(router_name,name,remote_address,local_address,rate_limit,comment) VALUES(?,?,?,?,?,?)',
                              (name,_safe(x.get('name'),255),_safe(x.get('remote-address'),255),_safe(x.get('local-address'),255),_safe(x.get('rate-limit'),255),_safe(x.get('comment'))))
            _touch(c,name,status='SYNCING')
        elif kind=='traffic':
            _save_traffic(c, name, items)
            _touch(c,name,status='ONLINE')
        elif kind=='finish':
            total=c.execute('SELECT COUNT(*) c FROM push_pppoe_secrets WHERE router_name=?',(name,)).fetchone()['c']
            active=c.execute('SELECT COUNT(*) c FROM push_pppoe_active WHERE router_name=?',(name,)).fetchone()['c']
            profiles=c.execute('SELECT COUNT(*) c FROM push_ppp_profiles WHERE router_name=?',(name,)).fetchone()['c']
            now=datetime.now().isoformat(timespec='seconds')
            _touch(c,name,_safe(p.get('identity'),80),_safe(p.get('version'),80),'ONLINE')
            c.execute('UPDATE push_router_agents SET last_sync=?,pppoe_total=?,pppoe_active=?,ppp_profiles=? WHERE name=?',
                      (now,total,active,profiles,name))
            base.audit('MIKROTIK_RELAY_SYNC',f'{name} {active}/{total}')
        else:
            return jsonify(ok=False,error='unknown-kind'),400
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True,kind=kind,received=len(items))


def view():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); agents=c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall(); c.close(); rows=[]
    for a in agents:
        cls='ok' if a['status']=='ONLINE' else 'warn'
        rows.append(f'''<tr><td><b>{escape(a['name'] or '')}</b><br><span class="muted">{escape(a['identity'] or '')}</span></td><td><span class="tag {cls}">{escape(a['status'] or '')}</span></td><td>{escape(a['ros_version'] or '-')}</td><td>{int(a['pppoe_active'] or 0)} / {int(a['pppoe_total'] or 0)}</td><td>{int(a['ppp_profiles'] or 0)}</td><td>{escape(a['last_sync'] or '-')}</td><td><a class="btn blue" href="{url_for('router_push_traffic',name=a['name'])}">Consumo MikroTik</a></td></tr>''')
    table=''.join(rows) or '<tr><td colspan="7" class="muted">Esperando la primera sincronización desde el MikroTik.</td></tr>'
    body=f'''<div class="head"><div><h1>Sincronización segura</h1><p>Estado general del CCR y consumo de sus interfaces WAN.</p></div></div><div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Solo lectura del MikroTik.</b> La opción principal muestra el tráfico total de las WAN, no el consumo por cliente.</div><table class="table"><tr><th>Router</th><th>Estado</th><th>RouterOS</th><th>PPPoE activos/total</th><th>Perfiles</th><th>Última sync</th><th>Consumo</th></tr>{table}</table></div>'''
    return base.shell('Sincronización segura',body,'routers')


def traffic(name):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    rows=c.execute('SELECT * FROM push_router_traffic WHERE router_name=? ORDER BY interface_name',(name,)).fetchall()
    c.close()

    wan=[r for r in rows if 'wan' in (r['interface_name'] or '').lower()]
    total_rx=sum(_bps(r['rx_bps']) for r in wan)
    total_tx=sum(_bps(r['tx_bps']) for r in wan)
    last=max((r['updated_at'] or '' for r in rows), default='-')

    ifaces=[]
    for r in rows:
        is_wan='wan' in (r['interface_name'] or '').lower()
        badge='<span class="tag ok">WAN</span>' if is_wan else '<span class="tag warn">OTRA</span>'
        ifaces.append(f'''<tr><td><b>{escape(r['interface_name'] or '')}</b></td><td>{badge}</td><td>{_fmt_mbps(r['rx_bps'])}</td><td>{_fmt_mbps(r['tx_bps'])}</td><td>{escape(r['updated_at'] or '-')}</td></tr>''')
    table=''.join(ifaces) or '<tr><td colspan="5" class="muted">Todavía no han llegado datos de tráfico.</td></tr>'

    if wan:
        note=f'Sumando {len(wan)} interfaz(es) cuyo nombre contiene WAN.'
    else:
        note='Aún no se identifican interfaces con “WAN” en el nombre. Activa el monitor para comenzar a recibir datos.'

    body=f'''<div class="head"><div><h1>Consumo MikroTik · {escape(name)}</h1><p>Tráfico total del router por sus interfaces WAN.</p></div><div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn blue" href="{url_for('router_push_traffic_script',name=name)}">Activar monitor</a><a class="btn" href="{url_for('router_push_view')}">← Volver</a></div></div>
    <div class="grid6" style="grid-template-columns:repeat(3,minmax(180px,1fr))">
      <div class="kpi blue1"><div class="label">Descarga total</div><div class="value">{_fmt_mbps(total_rx)}</div><div class="sub">RX de las WAN</div></div>
      <div class="kpi green1"><div class="label">Subida total</div><div class="value">{_fmt_mbps(total_tx)}</div><div class="sub">TX de las WAN</div></div>
      <div class="kpi cyan1"><div class="label">Última lectura</div><div class="value" style="font-size:16px">{escape(last)}</div><div class="sub">{escape(note)}</div></div>
    </div>
    <div class="panel"><table class="table"><tr><th>Interfaz</th><th>Tipo</th><th>Descarga</th><th>Subida</th><th>Actualizado</th></tr>{table}</table></div>
    <script>setTimeout(function(){{location.reload()}},10000)</script>'''
    return base.shell('Consumo MikroTik',body,'routers')


def traffic_script(name):
    if not base.logged_in(): return redirect(url_for('login'))
    if not TOKEN:
        return base.shell('Activar monitor','<div class="panel"><div class="notice">Falta MIKROTIK_RELAY_TOKEN en Railway.</div></div>','routers')
    root=request.url_root.rstrip('/')
    script=f'''/system script remove [find where name="interflash-traffic"]
/system scheduler remove [find where name="interflash-traffic-scheduler"]
/system script add name="interflash-traffic" policy=read,test source={{
  :local url "{root}/api/mikrotik/relay-sync";
  :local headers "Content-Type:application/json,X-InterFlash-Relay: {TOKEN}";
  :local active [:serialize to=json value=[/ppp active print as-value proplist=name,address,caller-id,service,uptime] options=json.no-string-conversion];
  :local activeData ("{{\"router\":\"{name}\",\"kind\":\"active-snapshot\",\"items\":" . $active . "}}");
  /tool fetch url=$url http-method=post http-header-field=$headers http-data=$activeData output=none check-certificate=yes;
  :local traffic [:serialize to=json value=[/interface print stats as-value proplist=name,rx-byte,tx-byte] options=json.no-string-conversion];
  :local data ("{{\"router\":\"{name}\",\"kind\":\"traffic\",\"items\":" . $traffic . "}}");
  /tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-traffic-scheduler" interval=15s on-event="/system script run interflash-traffic" policy=read,test start-time=startup
/system script run interflash-traffic
'''
    body=f'''<div class="head"><div><h1>Activar consumo MikroTik</h1><p>Pega este bloque una sola vez en la terminal del MikroTik. Solo lee contadores de interfaces.</p></div><a class="btn" href="{url_for('router_push_traffic',name=name)}">← Volver</a></div>
    <div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Solo lectura.</b> Envía RX/TX cada 15 segundos para calcular Mbps.</div><textarea class="field" style="width:100%;height:360px;font-family:Consolas,monospace">{escape(script)}</textarea></div>'''
    return base.shell('Activar consumo MikroTik',body,'routers')


def pppoe(name):
    if not base.logged_in(): return redirect(url_for('login'))
    q=(request.args.get('q') or '').strip()
    c=base.db()
    secrets=c.execute('SELECT * FROM push_pppoe_secrets WHERE router_name=? ORDER BY name',(name,)).fetchall()
    act=c.execute('SELECT * FROM push_pppoe_active WHERE router_name=?',(name,)).fetchall()
    imported={r['pppoe'] for r in c.execute("SELECT pppoe FROM customers WHERE COALESCE(pppoe,'')<>''").fetchall()}
    c.close()
    amap={r['name']:r for r in act}; rows=[]
    shown=0
    for r in secrets:
        display_name=(r['comment'] or '').strip() or (r['name'] or '')
        if q and q.lower() not in ((r['name'] or '')+' '+display_name+' '+(r['profile'] or '')).lower():
            continue
        shown+=1
        a=amap.get(r['name']); disabled=str(r['disabled'] or '').lower() in ('true','yes','1')
        status,cls=('SUSPENDIDO','bad') if disabled else (('ONLINE','ok') if a else ('OFFLINE','warn'))
        ip=a['address'] if a else r['remote_address']; caller=a['caller_id'] if a else r['caller_id']
        already=(r['name'] or '') in imported
        checkbox='<span class="tag ok">YA IMPORTADO</span>' if already else f'<input class="client-check" type="checkbox" name="client_ids" value="{r["id"]}" style="width:20px;height:20px">'
        rows.append(f'''<tr><td>{checkbox}</td><td><b>{escape(display_name)}</b><br><span class="muted">PPPoE: {escape(r['name'] or '')}</span></td><td>{escape(r['profile'] or '-')}</td><td>{escape(ip or '-')}</td><td>{escape(caller or '-')}</td><td><span class="tag {cls}">{status}</span></td></tr>''')
    table=''.join(rows) or '<tr><td colspan="6" class="muted">No se encontraron clientes.</td></tr>'
    body=f'''<div class="head"><div><h1>Extraer clientes · {escape(name)}</h1><p>Marca solamente los clientes que quieres agregar a INTER Flash.</p></div><div style="display:flex;gap:8px"><a class="btn" href="{url_for('router_push_csv',name=name)}">Descargar CSV</a><a class="btn" href="{url_for('router_push_view')}">← Volver</a></div></div>
    <div class="panel"><form class="toolbar" method="get"><input class="field" name="q" value="{escape(q)}" placeholder="Buscar usuario, nombre o perfil"><button class="btn blue">Buscar</button><a class="btn" href="{url_for('router_push_pppoe',name=name)}">Limpiar</a></form>
    <form method="post" action="{url_for('router_push_import',name=name)}" onsubmit="return document.querySelectorAll('.client-check:checked').length ? confirm('¿Importar los clientes seleccionados?') : (alert('Selecciona por lo menos un cliente.'), false)">
      <div style="display:flex;align-items:center;gap:10px;margin:8px 0 14px"><label style="display:flex;align-items:center;gap:7px"><input id="select-all" type="checkbox" style="width:20px;height:20px"> <b>Seleccionar todos los visibles</b></label><span class="muted">{shown} mostrados · {len(secrets)} PPPoE sincronizados</span><button class="btn green" type="submit" style="margin-left:auto">Importar seleccionados</button></div>
      <table class="table"><tr><th>Elegir</th><th>Cliente / PPPoE</th><th>Perfil</th><th>IP</th><th>Caller ID</th><th>Estado</th></tr>{table}</table>
    </form></div>
    <script>document.getElementById('select-all').addEventListener('change',function(){{document.querySelectorAll('.client-check').forEach(x=>x.checked=this.checked)}})</script>'''
    return base.shell('Extraer clientes',body,'routers')


def import_selected(name):
    if not base.logged_in(): return redirect(url_for('login'))
    raw_ids=request.form.getlist('client_ids')
    ids=[]
    for x in raw_ids:
        try: ids.append(int(x))
        except (TypeError,ValueError): pass
    if not ids:
        flash('Selecciona por lo menos un cliente.')
        return redirect(url_for('router_push_pppoe',name=name))
    marks=','.join('?' for _ in ids)
    c=base.db()
    rows=c.execute(f'SELECT * FROM push_pppoe_secrets WHERE router_name=? AND id IN ({marks})',[name,*ids]).fetchall()
    created=0; skipped=0
    for r in rows:
        pppoe=(r['name'] or '').strip()
        if not pppoe: continue
        exists=c.execute('SELECT id FROM customers WHERE pppoe=? LIMIT 1',(pppoe,)).fetchone()
        if exists:
            skipped+=1; continue
        customer_name=(r['comment'] or '').strip() or pppoe
        disabled=str(r['disabled'] or '').lower() in ('true','yes','1')
        status='SUSPENDIDO' if disabled else 'ACTIVO'
        ip=(r['remote_address'] or '').strip()
        cur=c.execute('''INSERT INTO customers(code,name,phone,document,email,address,zone,pppoe,ip_address,onu_serial,plan_id,status,due_day,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (None,customer_name,'','','','','',pppoe,ip,'',None,status,30,datetime.now().date().isoformat()))
        cid=cur.lastrowid
        c.execute('UPDATE customers SET code=? WHERE id=?',(f'IF-{cid:05d}',cid))
        created+=1
    c.commit(); c.close()
    if created:
        base.audit('MIKROTIK_CLIENT_IMPORT',f'{name}: {created} clientes importados')
    flash(f'Importación terminada: {created} clientes agregados' + (f' · {skipped} ya existían' if skipped else '') + '.')
    return redirect(url_for('customers'))


def export_csv(name):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); rows=c.execute('SELECT * FROM push_pppoe_secrets WHERE router_name=? ORDER BY name',(name,)).fetchall(); c.close()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(['pppoe','nombre_o_comentario','perfil','servicio','ip_remota','caller_id','suspendido'])
    for r in rows:
        w.writerow([r['name'] or '',r['comment'] or '',r['profile'] or '',r['service'] or '',r['remote_address'] or '',r['caller_id'] or '',r['disabled'] or ''])
    data='\ufeff'+out.getvalue()
    return Response(data,mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="clientes-{name}.csv"'})


def setup(app):
    ensure_schema()
    app.add_url_rule('/api/mikrotik/relay-sync',endpoint='mikrotik_relay_sync',view_func=sync_api,methods=['POST'])
    app.add_url_rule('/routers/push-sync',endpoint='router_push_view',view_func=view,methods=['GET'])
    app.add_url_rule('/routers/push-sync/<name>',endpoint='router_push_pppoe',view_func=pppoe,methods=['GET'])
    app.add_url_rule('/routers/push-sync/<name>/traffic',endpoint='router_push_traffic',view_func=traffic,methods=['GET'])
    app.add_url_rule('/routers/push-sync/<name>/traffic-script',endpoint='router_push_traffic_script',view_func=traffic_script,methods=['GET'])
    app.add_url_rule('/routers/push-sync/<name>/import',endpoint='router_push_import',view_func=import_selected,methods=['POST'])
    app.add_url_rule('/routers/push-sync/<name>/csv',endpoint='router_push_csv',view_func=export_csv,methods=['GET'])
