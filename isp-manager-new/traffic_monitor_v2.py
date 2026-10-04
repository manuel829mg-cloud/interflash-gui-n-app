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
  :local url "{root}/api/mikrotik/traffic-sample";
  :local headers "Content-Type:application/x-www-form-urlencoded,X-InterFlash-Relay: {push_sync.TOKEN}";
  :foreach item in=[/interface print stats as-value where name~"WAN"] do={{
    :local n ($item->"name");
    :local rx ($item->"rx-byte");
    :local tx ($item->"tx-byte");
    :local data ("router={name}&interface=" . $n . "&rx=" . $rx . "&tx=" . $tx);
    /tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=none check-certificate=yes;
  }}
}}
/system scheduler add name="interflash-traffic-scheduler" interval=15s on-event="/system script run interflash-traffic" policy=read,test start-time=startup
/system script run interflash-traffic
'''

    body = f'''<div class="head"><div><h1>Activar consumo MikroTik</h1><p>Versión 2: envía cada interfaz WAN por separado para evitar el error HTTP 400.</p></div><a class="btn" href="{url_for('router_push_traffic',name=name)}">← Volver</a></div>
    <div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Monitor v2.</b> Pega este bloque completo una sola vez. Reemplaza automáticamente el monitor anterior y lee solo interfaces cuyo nombre contiene WAN.</div><textarea class="field" style="width:100%;height:420px;font-family:Consolas,monospace">{push_sync.escape(script)}</textarea></div>'''
    return base.shell('Activar consumo MikroTik', body, 'routers')


def setup(app):
    app.add_url_rule('/api/mikrotik/traffic-sample', endpoint='mikrotik_traffic_sample_v2', view_func=traffic_sample, methods=['POST'])
    app.view_functions['router_push_traffic_script'] = traffic_script_v2
