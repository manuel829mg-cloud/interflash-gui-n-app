from datetime import datetime
from flask import request, jsonify, redirect, url_for, Response
import app as base
import push_sync


def traffic_sample():
    if not push_sync._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    name = (request.form.get('router') or 'CCR2116')[:80].strip()
    iface = (request.form.get('interface') or '')[:120].strip()
    if not iface:
        return jsonify(ok=False, error='missing-interface'), 400
    rx = request.form.get('rx')
    tx = request.form.get('tx')
    push_sync.ensure_schema()
    c = base.db()
    try:
        push_sync._save_traffic(c, name, [{'name': iface, 'rx_bytes': rx, 'tx_bytes': tx}])
        push_sync._touch(c, name, status='ONLINE')
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True, interface=iface)


def traffic_batch():
    if not push_sync._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    name = (request.form.get('router') or 'CCR2116')[:80].strip()
    raw = request.form.get('samples') or ''
    active_raw = request.form.get('active') or ''
    items = []
    for part in raw.split('|'):
        if not part:
            continue
        cols = part.split(',')
        if len(cols) != 3:
            continue
        iface, rx, tx = cols
        iface = iface[:120].strip()
        if iface:
            items.append({'name': iface, 'rx_bytes': rx, 'tx_bytes': tx})
    if not items:
        return jsonify(ok=False, error='missing-samples'), 400
    push_sync.ensure_schema()
    c = base.db()
    try:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS pppoe_connection_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          router_name TEXT NOT NULL,
          pppoe TEXT NOT NULL,
          event TEXT NOT NULL,
          created_at TEXT NOT NULL,
          duration_seconds INTEGER,
          gap_seconds INTEGER,
          is_microcut INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_pppoe_connection_events_user
          ON pppoe_connection_events(pppoe,id DESC);
        ''')
        previous = {str(x['name']).strip() for x in c.execute(
            'SELECT name FROM push_pppoe_active WHERE router_name=?', (name,)
        ).fetchall() if x['name']}
        current = {x.strip()[:255] for x in active_raw.split('|') if x.strip()}
        now = datetime.now()
        now_s = now.isoformat(timespec='seconds')

        # Seed users that were already online when connection history was enabled.
        for user in current & previous:
            exists = c.execute(
                'SELECT 1 FROM pppoe_connection_events WHERE router_name=? AND pppoe=? LIMIT 1',
                (name, user)
            ).fetchone()
            if not exists:
                c.execute(
                    'INSERT INTO pppoe_connection_events(router_name,pppoe,event,created_at) VALUES(?,?,?,?)',
                    (name, user, 'CONECTADO', now_s)
                )

        for user in previous - current:
            last_on = c.execute(
                "SELECT created_at FROM pppoe_connection_events WHERE router_name=? AND pppoe=? AND event='CONECTADO' ORDER BY id DESC LIMIT 1",
                (name, user)
            ).fetchone()
            duration = None
            if last_on and last_on['created_at']:
                try:
                    duration = max(0, int((now - datetime.fromisoformat(last_on['created_at'])).total_seconds()))
                except (TypeError, ValueError):
                    pass
            c.execute(
                'INSERT INTO pppoe_connection_events(router_name,pppoe,event,created_at,duration_seconds) VALUES(?,?,?,?,?)',
                (name, user, 'DESCONECTADO', now_s, duration)
            )

        for user in current - previous:
            last_off = c.execute(
                "SELECT id,created_at FROM pppoe_connection_events WHERE router_name=? AND pppoe=? AND event='DESCONECTADO' ORDER BY id DESC LIMIT 1",
                (name, user)
            ).fetchone()
            gap = None
            if last_off and last_off['created_at']:
                try:
                    gap = max(0, int((now - datetime.fromisoformat(last_off['created_at'])).total_seconds()))
                except (TypeError, ValueError):
                    pass
            if last_off and gap is not None and gap <= 120:
                c.execute(
                    'UPDATE pppoe_connection_events SET is_microcut=1,gap_seconds=? WHERE id=?',
                    (gap, last_off['id'])
                )
            c.execute(
                'INSERT INTO pppoe_connection_events(router_name,pppoe,event,created_at,gap_seconds) VALUES(?,?,?,?,?)',
                (name, user, 'CONECTADO', now_s, gap)
            )

        push_sync._save_traffic(c, name, items)
        pppoe_watch = []
        try:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='client_traffic_watch'").fetchone():
                pppoe_watch = [r['pppoe'] for r in c.execute(
                    'SELECT pppoe FROM client_traffic_watch WHERE router_name=? AND expires_at>=? ORDER BY pppoe',
                    (name, now_s)
                ).fetchall() if r['pppoe']]
        except Exception:
            pppoe_watch = []
        c.execute('DELETE FROM push_pppoe_active WHERE router_name=?', (name,))
        for active_name in sorted(current):
            c.execute(
                'INSERT INTO push_pppoe_active(router_name,name,address,caller_id,service,uptime) VALUES(?,?,?,?,?,?)',
                (name, active_name, '', '', 'pppoe', '')
            )
        push_sync._touch(c, name, status='ONLINE')
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True, received=len(items), active=len(current), pppoe_watch=pppoe_watch)


def build_traffic_script(name):
    root = request.url_root.rstrip('/')
    if root.startswith('http://'):
        root = 'https://' + root[len('http://'):]

    script = f'''/system script remove [find where name="interflash-traffic"]
/system scheduler remove [find where name="interflash-traffic-scheduler"]
/system script add name="interflash-traffic" policy=ftp,read,write,test source={{
  :local url "{root}/api/mikrotik/traffic-batch";
  :local relayUrl "{root}/api/mikrotik/relay-sync";
  :local headers "Content-Type:application/x-www-form-urlencoded,X-InterFlash-Relay: {push_sync.TOKEN}";
  :local jsonHeaders "Content-Type:application/json,X-InterFlash-Relay: {push_sync.TOKEN}";
  :local samples "";\n  :local active "";\n  :foreach session in=[/ppp active print as-value proplist=name] do={{\n    :local u ($session->"name");\n    :if ([:len $active] > 0) do={{ :set active ($active . "|"); }}\n    :set active ($active . $u);\n  }}\n  :foreach item in=[/interface print stats as-value where name~"WAN"] do={{
    :local n ($item->"name");
    :local rx ($item->"rx-byte");
    :local tx ($item->"tx-byte");
    :if ([:len $samples] > 0) do={{ :set samples ($samples . "|"); }}
    :set samples ($samples . $n . "," . $rx . "," . $tx);
  }}
  :if ([:len $samples] > 0) do={{
    :local data ("router={name}&samples=" . $samples . "&active=" . $active);
    :local sync [/tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=user as-value check-certificate=yes];
    :do {{
      :local syncObj [:deserialize from=json value=($sync->"data")];
      :local watched ($syncObj->"pppoe_watch");
      :if ([:len $watched] > 0) do={{
        /system scheduler set [find where name="interflash-traffic-scheduler"] interval=1s;
      }} else={{
        /system scheduler set [find where name="interflash-traffic-scheduler"] interval=2s;
      }}
      :foreach pppoe in=$watched do={{
        :foreach session in=[/ppp active print as-value proplist=name,bytes where name=$pppoe] do={{
          :local record [:serialize to=json value=$session options=json.no-string-conversion];
          :local pppData ("{{\\\"router\\\":\\\"{name}\\\",\\\"kind\\\":\\\"pppoe-traffic\\\",\\\"items\\\":[" . $record . "]}}");
          /tool fetch url=$relayUrl http-method=post http-header-field=$jsonHeaders http-data=$pppData output=none check-certificate=yes;
        }}
      }}
    }} on-error={{}}
  }}
}}
/system script remove [find where name="interflash-wan-health"]
/system scheduler remove [find where name="interflash-wan-health-scheduler"]
/system script add name="interflash-wan-health" policy=ftp,read,test source={{
  :local url "{root}/api/mikrotik/wan-health";
  :local headers "Content-Type:application/x-www-form-urlencoded,X-InterFlash-Relay: {push_sync.TOKEN}";
  :local r1 [/tool ping address=4.2.2.1 interface=WAN1-CLARO count=3 interval=200ms];
  :local r2 [/tool ping address=4.2.2.2 interface=WAN2-CLARO count=3 interval=200ms];
  :local r3 [/tool ping address=208.67.222.222 interface=WAN3-ALTICE count=3 interval=200ms];
  :local r4 [/tool ping address=208.67.220.220 interface=WAN4-ALTICE count=3 interval=200ms];
  :local health ("WAN1-CLARO," . $r1 . ",3|WAN2-CLARO," . $r2 . ",3|WAN3-ALTICE," . $r3 . ",3|WAN4-ALTICE," . $r4 . ",3");
  :local data ("router={name}&health=" . $health);
  /tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-traffic-scheduler" interval=2s on-event="/system script run interflash-traffic" policy=ftp,read,write,test start-time=startup
/system scheduler add name="interflash-wan-health-scheduler" interval=10s on-event="/system script run interflash-wan-health" policy=ftp,read,test start-time=startup
'''
    return script


def traffic_script_v2(name):
    if not base.logged_in():
        return redirect(url_for('login'))
    if not push_sync.TOKEN:
        return base.shell('Activar monitor','<div class="panel"><div class="notice">Falta MIKROTIK_RELAY_TOKEN en Railway.</div></div>','routers')

    script = build_traffic_script(name)
    download_url = url_for('router_push_traffic_script_download', name=name)

    body = f'''<div class="head"><div><h1>Activar consumo MikroTik</h1><p>Monitor: 4 WAN y PPPoE cada 2 segundos; al abrir una ficha, los contadores consultados pasan a 1 segundo y vuelven a 2 al cerrarla. Ping de las 4 líneas cada 10 segundos.</p></div><a class="btn" href="{url_for('router_push_traffic',name=name)}">← Volver</a></div>
    <div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Monitor v6.3 · Instalación con archivo y validación previa.</b> Descarga el archivo y súbelo en WinBox → Files. En Terminal ejecuta primero <code>/import file-name=interflash-traffic-v2.rsc verbose=yes dry-run</code>. Si termina sin errores, aplica con <code>/import file-name=interflash-traffic-v2.rsc verbose=yes</code>. Luego verifica con <code>/system script print where name="interflash-traffic"</code>. La instalación no reinicia sesiones PPPoE.</div><p><a class="btn primary" href="{download_url}">Descargar instalador .rsc</a></p><details><summary>Ver el contenido del instalador</summary><textarea class="field" readonly style="width:100%;height:440px;font-family:Consolas,monospace">{push_sync.escape(script)}</textarea></details></div>'''
    return base.shell('Activar consumo MikroTik', body, 'routers')


def traffic_script_download(name):
    if not base.logged_in():
        return redirect(url_for('login'))
    if not push_sync.TOKEN:
        return base.shell('Activar monitor','<div class="panel"><div class="notice">Falta MIKROTIK_RELAY_TOKEN en Railway.</div></div>','routers')
    return Response(
        build_traffic_script(name),
        mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="interflash-traffic-v2.rsc"'}
    )


def traffic_realtime(name):
    page = push_sync.traffic(name)
    if isinstance(page, str):
        page = page.replace('setTimeout(function(){location.reload()},10000)', 'setTimeout(function(){location.reload()},2000)')
    return page


def setup(app):
    app.add_url_rule('/api/mikrotik/traffic-sample', endpoint='mikrotik_traffic_sample_v2', view_func=traffic_sample, methods=['POST'])
    app.add_url_rule('/api/mikrotik/traffic-batch', endpoint='mikrotik_traffic_batch_v3', view_func=traffic_batch, methods=['POST'])
    app.view_functions['router_push_traffic_script'] = traffic_script_v2
    app.add_url_rule('/routers/push-sync/<name>/traffic-script/download', endpoint='router_push_traffic_script_download', view_func=traffic_script_download, methods=['GET'])
    app.view_functions['router_push_traffic'] = traffic_realtime
