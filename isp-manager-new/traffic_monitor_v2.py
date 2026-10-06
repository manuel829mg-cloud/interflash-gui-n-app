from flask import request, jsonify, redirect, url_for
import app as base
import push_sync


def traffic_sample():
    if not push_sync._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    name = (request.form.get('router') or 'CCR2116')[:80].strip()
    iface = (request.form.get('interface') or '')[:120].strip()
    if not iface:
        return jsonify(ok=False, error='missing-interface'), 400
    rx = request.form.get('rx') or '0'
    tx = request.form.get('tx') or '0'
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
        push_sync._save_traffic(c, name, items)
        c.execute('DELETE FROM push_pppoe_active WHERE router_name=?', (name,))
        for active_name in active_raw.split('|'):
            active_name = active_name.strip()
            if active_name:
                c.execute('INSERT INTO push_pppoe_active(router_name,name,address,caller_id,service,uptime) VALUES(?,?,?,?,?,?)', (name, active_name[:255], '', '', 'pppoe', ''))
        push_sync._touch(c, name, status='ONLINE')
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True, received=len(items))


def traffic_script_v2(name):
    if not base.logged_in():
        return redirect(url_for('login'))
    if not push_sync.TOKEN:
        return base.shell('Activar monitor','<div class="panel"><div class="notice">Falta MIKROTIK_RELAY_TOKEN en Railway.</div></div>','routers')

    root = request.url_root.rstrip('/')
    if root.startswith('http://'):
        root = 'https://' + root[len('http://'):]

    script = f'''/system script remove [find where name="interflash-traffic"]
/system scheduler remove [find where name="interflash-traffic-scheduler"]
/system script add name="interflash-traffic" policy=read,test source={{
  :local url "{root}/api/mikrotik/traffic-batch";
  :local headers "Content-Type:application/x-www-form-urlencoded,X-InterFlash-Relay: {push_sync.TOKEN}";
  :local samples "";\n  :local active "";\n  :foreach session in=[/ppp active print as-value proplist=name] do={{\n    :local u ($session->"name");\n    :if ([:len $active] > 0) do={{ :set active ($active . "|"); }}\n    :set active ($active . $u);\n  }}\n  :foreach item in=[/interface print stats as-value where name~"WAN"] do={{
    :local n ($item->"name");
    :local rx ($item->"rx-byte");
    :local tx ($item->"tx-byte");
    :if ([:len $samples] > 0) do={{ :set samples ($samples . "|"); }}
    :set samples ($samples . $n . "," . $rx . "," . $tx);
  }}
  :if ([:len $samples] > 0) do={{
    :local data ("router={name}&samples=" . $samples . "&active=" . $active);
    /tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=none check-certificate=yes;
  }}
}}
/system script remove [find where name="interflash-wan-health"]
/system scheduler remove [find where name="interflash-wan-health-scheduler"]
/system script add name="interflash-wan-health" policy=read,test source={{
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
/system scheduler add name="interflash-traffic-scheduler" interval=2s on-event="/system script run interflash-traffic" policy=read,test start-time=startup
/system scheduler add name="interflash-wan-health-scheduler" interval=10s on-event="/system script run interflash-wan-health" policy=read,test start-time=startup
/system script run interflash-traffic
/system script run interflash-wan-health
'''

    body = f'''<div class="head"><div><h1>Activar consumo MikroTik</h1><p>Monitor en tiempo casi real: WAN y estado PPPoE cada 2 segundos; ping real de las 4 líneas cada 10 segundos.</p></div><a class="btn" href="{url_for('router_push_traffic',name=name)}">← Volver</a></div>
    <div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Monitor v6.1 · PPPoE + 4 líneas con ping real.</b> Pega este bloque completo una sola vez. Reemplaza automáticamente el monitor anterior y envía las 4 WAN juntas en una sola petición para no cargar el CCR2116.</div><textarea class="field" style="width:100%;height:440px;font-family:Consolas,monospace">{push_sync.escape(script)}</textarea></div>'''
    return base.shell('Activar consumo MikroTik', body, 'routers')


def traffic_realtime(name):
    page = push_sync.traffic(name)
    if isinstance(page, str):
        page = page.replace('setTimeout(function(){location.reload()},10000)', 'setTimeout(function(){location.reload()},2000)')
    return page


def setup(app):
    app.add_url_rule('/api/mikrotik/traffic-sample', endpoint='mikrotik_traffic_sample_v2', view_func=traffic_sample, methods=['POST'])
    app.add_url_rule('/api/mikrotik/traffic-batch', endpoint='mikrotik_traffic_batch_v3', view_func=traffic_batch, methods=['POST'])
    app.view_functions['router_push_traffic_script'] = traffic_script_v2
    app.view_functions['router_push_traffic'] = traffic_realtime
