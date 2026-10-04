from flask import request, redirect, url_for
import app as base
import push_sync


def traffic_script_fixed(name):
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
  :local url "{root}/api/mikrotik/relay-sync";
  :local headers "Content-Type:application/json,X-InterFlash-Relay: {push_sync.TOKEN}";
  :local traffic [:serialize to=json value=[/interface print stats as-value proplist=name,rx-byte,tx-byte] options=json.no-string-conversion];
  :local data ("{{\\\"router\\\":\\\"{name}\\\",\\\"kind\\\":\\\"traffic\\\",\\\"items\\\":" . $traffic . "}}");
  /tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-traffic-scheduler" interval=15s on-event="/system script run interflash-traffic" policy=read,test start-time=startup
/system script run interflash-traffic
'''

    body = f'''<div class="head"><div><h1>Activar consumo MikroTik</h1><p>Pega este bloque una sola vez en la terminal del MikroTik. Solo lee contadores de interfaces.</p></div><a class="btn" href="{url_for('router_push_traffic',name=name)}">← Volver</a></div>
    <div class="panel"><div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Monitor corregido.</b> Usa HTTPS y envía RX/TX cada 15 segundos para calcular Mbps.</div><textarea class="field" style="width:100%;height:360px;font-family:Consolas,monospace">{push_sync.escape(script)}</textarea></div>'''
    return base.shell('Activar consumo MikroTik', body, 'routers')


def setup(app):
    app.view_functions['router_push_traffic_script'] = traffic_script_fixed
