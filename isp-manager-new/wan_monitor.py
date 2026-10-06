from datetime import datetime
from html import escape
from flask import request, jsonify, redirect, url_for
import app as base
import push_sync

LINES = [
    ('WAN1-CLARO', 'Claro 1', 'Ruta-Linea1', '4.2.2.1'),
    ('WAN2-CLARO', 'Claro 2', 'Ruta-Linea2', '4.2.2.2'),
    ('WAN3-ALTICE', 'Altice 3', 'Ruta-Linea3', '208.67.222.222'),
    ('WAN4-ALTICE', 'Altice 4', 'Ruta-Linea4', '208.67.220.220'),
]

def ensure_schema():
    c=base.db()
    c.execute('''CREATE TABLE IF NOT EXISTS wan_line_health(
      router_name TEXT NOT NULL,
      interface_name TEXT NOT NULL,
      received INTEGER DEFAULT 0,
      sent INTEGER DEFAULT 3,
      packet_loss REAL DEFAULT 100,
      updated_at TEXT,
      PRIMARY KEY(router_name,interface_name)
    )''')
    c.commit(); c.close()

def health_api():
    if not push_sync._auth():
        return jsonify(ok=False,error='unauthorized'),401
    router=(request.form.get('router') or 'CCR2116')[:80].strip()
    raw=request.form.get('health') or ''
    ensure_schema()
    c=base.db(); now=datetime.now().isoformat(timespec='seconds'); received_count=0
    try:
        for part in raw.split('|'):
            cols=part.split(',')
            if len(cols)!=3:
                continue
            iface=cols[0][:120].strip()
            try:
                received=max(0,int(cols[1])); sent=max(1,int(cols[2]))
            except (TypeError,ValueError):
                continue
            loss=max(0.0,min(100.0,((sent-received)*100.0)/sent))
            c.execute('''INSERT INTO wan_line_health(router_name,interface_name,received,sent,packet_loss,updated_at)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(router_name,interface_name) DO UPDATE SET
                           received=excluded.received,sent=excluded.sent,
                           packet_loss=excluded.packet_loss,updated_at=excluded.updated_at''',
                      (router,iface,received,sent,loss,now))
            received_count+=1
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True,received=received_count)

def page():
    if not base.logged_in():
        return redirect(url_for('login'))
    ensure_schema(); push_sync.ensure_schema()
    c=base.db()
    health={r['interface_name']:r for r in c.execute('SELECT * FROM wan_line_health WHERE router_name=?',('CCR2116',)).fetchall()}
    traffic={r['interface_name']:r for r in c.execute('SELECT * FROM push_router_traffic WHERE router_name=?',('CCR2116',)).fetchall()}
    c.close()
    now=datetime.now(); cards=[]
    for iface,provider,table,probe in LINES:
        h=health.get(iface); t=traffic.get(iface)
        fresh=False
        if h and h['updated_at']:
            try:
                fresh=(now-datetime.fromisoformat(h['updated_at'])).total_seconds() <= 45
            except (TypeError,ValueError):
                pass
        loss=float(h['packet_loss'] or 0) if h and fresh else None
        if loss is None:
            status,cls='SIN DATOS','warn'
        elif loss >= 100:
            status,cls='OFFLINE','bad'
        elif loss >= 34:
            status,cls='INESTABLE','warn'
        else:
            status,cls='ONLINE','ok'
        rx=push_sync._fmt_mbps(t['rx_bps']) if t else '0.00 Mbps'
        tx=push_sync._fmt_mbps(t['tx_bps']) if t else '0.00 Mbps'
        loss_txt='—' if loss is None else f'{loss:.0f}%'
        updated=escape(h['updated_at']) if h and h['updated_at'] else 'Esperando monitor'
        cards.append(f'''<div class="panel" style="margin:0">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
            <div><div class="muted">INTER Flash · {escape(iface)}</div><h2 style="margin:4px 0">{escape(provider)}</h2></div>
            <span class="tag {cls}" style="font-size:14px">{status}</span>
          </div>
          <div class="grid6" style="grid-template-columns:repeat(3,minmax(90px,1fr));margin-top:12px">
            <div><div class="muted">Descarga</div><b>{rx}</b></div>
            <div><div class="muted">Subida</div><b>{tx}</b></div>
            <div><div class="muted">Pérdida</div><b>{loss_txt}</b></div>
          </div>
          <div class="muted" style="margin-top:12px">Prueba {escape(probe)} · {escape(table)}<br>Última prueba: {updated}</div>
        </div>''')
    body=f'''<div class="head"><div><h1>Estado de líneas</h1><p>Claro y Altice en vivo · estado, consumo y pérdida de paquetes.</p></div>
      <a class="btn blue" href="{url_for('router_push_traffic_script',name='CCR2116')}">Activar / actualizar monitor</a></div>
    <div style="padding:11px;border-radius:8px;background:#17304b;color:#bfdbfe;margin-bottom:14px">
      Las pruebas son de solo lectura. No cambian rutas, mangle ni gateways del CCR2116.
    </div>
    <div class="cards2">{''.join(cards)}</div>
    <script>setTimeout(function(){{location.reload()}},5000)</script>'''
    return base.shell('Estado de líneas',body,'wan_lines')

def setup(app):
    ensure_schema()
    app.add_url_rule('/api/mikrotik/wan-health',endpoint='mikrotik_wan_health',view_func=health_api,methods=['POST'])
    app.add_url_rule('/wan-lines',endpoint='wan_lines',view_func=page,methods=['GET'])
    if not any(x[0]=='wan_lines' for x in base.NAV):
        idx=next((i for i,x in enumerate(base.NAV) if x[0]=='routers'),len(base.NAV))
        base.NAV.insert(idx+1,('wan_lines','◫','Líneas'))
