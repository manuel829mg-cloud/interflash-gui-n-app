from datetime import datetime
from flask import request, jsonify, redirect, url_for
import re
import app as base
import push_sync
import business_suite as bs


def _norm(v):
    return re.sub(r'[^A-Z0-9]', '', str(v or '').upper())


def _level(rx):
    try:
        v = float(rx)
    except (TypeError, ValueError):
        return 'SIN DATOS', 'warn'
    if v < -27.0 or v > -8.0:
        return 'CRITICA', 'bad'
    if v < -25.0:
        return 'ALERTA', 'warn'
    return 'BUENA', 'ok'


def ensure_schema(c=None):
    own = c is None
    if own:
        c = base.db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS onu_optical_readings(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      olt_ip TEXT NOT NULL,
      index_key TEXT NOT NULL,
      serial TEXT NOT NULL,
      rx_power REAL,
      tx_power REAL,
      status TEXT NOT NULL DEFAULT 'SIN DATOS',
      last_seen TEXT NOT NULL,
      UNIQUE(olt_ip,index_key)
    );
    CREATE INDEX IF NOT EXISTS idx_onu_optical_serial ON onu_optical_readings(serial);
    """)
    if own:
        c.commit()
        c.close()


def optical_batch():
    if not push_sync._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    olt = (request.form.get('olt') or '192.168.3.253')[:80].strip()
    raw = request.form.get('rows') or ''
    now = datetime.now().isoformat(timespec='seconds')
    parsed = []
    for part in raw.split('|'):
        cols = part.split(',')
        if len(cols) != 4:
            continue
        serial, idx, rx, tx = [x.strip() for x in cols]
        if not serial or not idx:
            continue
        try:
            rxv = float(rx)
        except (TypeError, ValueError):
            rxv = None
        try:
            txv = float(tx)
        except (TypeError, ValueError):
            txv = None
        status, _ = _level(rxv)
        parsed.append((serial[:80], idx[:40], rxv, txv, status))

    if not parsed:
        return jsonify(ok=False, error='missing-rows'), 400

    c = base.db()
    try:
        ensure_schema(c)
        for serial, idx, rxv, txv, status in parsed:
            c.execute("""INSERT INTO onu_optical_readings(olt_ip,index_key,serial,rx_power,tx_power,status,last_seen)
                         VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(olt_ip,index_key) DO UPDATE SET
                           serial=excluded.serial,rx_power=excluded.rx_power,tx_power=excluded.tx_power,
                           status=excluded.status,last_seen=excluded.last_seen""",
                      (olt, idx, serial, rxv, txv, status, now))
            # Keep manually linked ONU inventory fresh when the same serial exists there.
            c.execute("""UPDATE onu_devices SET rx_power=?,tx_power=?,status=?,last_seen=?
                         WHERE UPPER(REPLACE(REPLACE(REPLACE(serial,':',''),'-',''),' ',''))=?""",
                      (str(rxv) if rxv is not None else None,
                       str(txv) if txv is not None else None,
                       status, now, _norm(serial)))
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True, received=len(parsed), olt=olt)


def onu_live_page():
    if not base.logged_in():
        return redirect(url_for('login'))
    c = base.db()
    ensure_schema(c)
    rows = c.execute('SELECT * FROM onu_optical_readings ORDER BY CAST(rx_power AS REAL) ASC, index_key').fetchall()
    customers = c.execute('SELECT id,name,onu_serial FROM customers ORDER BY name').fetchall()
    devices = c.execute('SELECT customer_id,serial FROM onu_devices WHERE customer_id IS NOT NULL').fetchall()
    c.close()

    cmap = {}
    names = {x['id']: x['name'] for x in customers}
    for x in customers:
        if x['onu_serial']:
            cmap[_norm(x['onu_serial'])] = x['name']
    for x in devices:
        if x['serial'] and x['customer_id'] in names:
            cmap[_norm(x['serial'])] = names[x['customer_id']]

    good = alert = critical = 0
    last = '-'
    trs = []
    for r in rows:
        status, cls = _level(r['rx_power'])
        if status == 'BUENA':
            good += 1
        elif status == 'ALERTA':
            alert += 1
        elif status == 'CRITICA':
            critical += 1
        if r['last_seen'] and (last == '-' or r['last_seen'] > last):
            last = r['last_seen']
        client = cmap.get(_norm(r['serial']), 'Sin asociar')
        rx = '-' if r['rx_power'] is None else f"{float(r['rx_power']):.2f} dBm"
        tx = '-' if r['tx_power'] is None else f"{float(r['tx_power']):.2f} dBm"
        trs.append(f'<tr><td>{bs.esc(client)}</td><td>{bs.esc(r["serial"])}</td><td>{bs.esc(r["index_key"])}</td>'
                   f'<td><b>{rx}</b></td><td>{tx}</td><td><span class="tag {cls}">{status}</span></td>'
                   f'<td>{bs.esc(r["last_seen"])}</td></tr>')

    body = f"""<div class="head"><div><h1>OLT / ONU</h1><p>Potencia óptica en vivo · Hioso HA7304VX</p></div>
    <a class="btn green" href="{url_for('onu_optical_script')}">Activar monitor OLT</a></div>
    <div class="grid6" style="grid-template-columns:repeat(4,1fr)">
      <div class="kpi green1"><div class="label">Señal buena</div><div class="value">{good}</div><div class="sub">RX ≥ -25 dBm</div></div>
      <div class="kpi orange1"><div class="label">Alerta</div><div class="value">{alert}</div><div class="sub">-27 a -25 dBm</div></div>
      <div class="kpi red1"><div class="label">Crítica</div><div class="value">{critical}</div><div class="sub">RX &lt; -27 dBm</div></div>
      <div class="kpi blue1"><div class="label">ONU leídas</div><div class="value">{len(rows)}</div><div class="sub">Última: {bs.esc(last)}</div></div>
    </div>
    <div class="panel"><div class="notice" style="margin-bottom:12px">Las lecturas se reciben desde el CCR2116 por SNMP de solo lectura. Una ONU con RX menor de -27 dBm queda marcada en rojo.</div>
    <table class="table"><tr><th>Cliente</th><th>Serial</th><th>PON / ONU</th><th>RX</th><th>TX</th><th>Estado</th><th>Actualizado</th></tr>
    {''.join(trs) or '<tr><td colspan=7 class=muted>Aún no hay lecturas. Pulsa “Activar monitor OLT”.</td></tr>'}</table></div>
    <script>setTimeout(function(){{location.reload()}},30000)</script>"""
    return base.shell('OLT / ONU', body, 'onu_page')


def optical_script():
    if not base.logged_in():
        return redirect(url_for('login'))
    if not push_sync.TOKEN:
        return base.shell('Activar monitor OLT','<div class="panel"><div class="notice">Falta MIKROTIK_RELAY_TOKEN en Railway.</div></div>','onu_page')
    root = request.url_root.rstrip('/')
    if root.startswith('http://'):
        root = 'https://' + root[7:]

    script = f'''/system script remove [find where name="interflash-onu-optical"]
/system scheduler remove [find where name="interflash-onu-optical-scheduler"]
/system script add name="interflash-onu-optical" policy=read,test source={{
  :local olt "192.168.3.253";
  :local community "public";
  :local url "{root}/api/olt/optical-batch";
  :local headers "Content-Type:application/x-www-form-urlencoded,X-InterFlash-Relay: {push_sync.TOKEN}";
  :local snBase "1.3.6.1.4.1.25355.3.2.6.3.2.1.11";
  :local txBase "1.3.6.1.4.1.25355.3.2.6.14.2.1.4";
  :local rxBase "1.3.6.1.4.1.25355.3.2.6.14.2.1.8";
  :for pon from=1 to=4 do={{
    :local rows "";
    :for onu from=1 to=64 do={{
      :local idx ("1." . $pon . "." . $onu);
      :local sn "";
      :do {{
        :local s [/tool snmp-get address=$olt community=$community version=2c oid=($snBase . "." . $idx) as-value];
        :set sn ($s->"value");
      }} on-error={{ :set sn ""; }}
      :if ([:len $sn] > 0) do={{
        :local rx "";
        :local tx "";
        :do {{
          :local r [/tool snmp-get address=$olt community=$community version=2c oid=($rxBase . "." . $idx) as-value];
          :set rx ($r->"value");
        }} on-error={{ :set rx ""; }}
        :do {{
          :local t [/tool snmp-get address=$olt community=$community version=2c oid=($txBase . "." . $idx) as-value];
          :set tx ($t->"value");
        }} on-error={{ :set tx ""; }}
        :if ([:len $rows] > 0) do={{ :set rows ($rows . "|"); }}
        :set rows ($rows . $sn . "," . $idx . "," . $rx . "," . $tx);
      }}
    }}
    :if ([:len $rows] > 0) do={{
      :local data ("olt=" . $olt . "&rows=" . $rows);
      /tool fetch url=$url http-method=post http-header-field=$headers http-data=$data output=none check-certificate=yes;
    }}
  }}
}}
/system scheduler add name="interflash-onu-optical-scheduler" interval=10m on-event="/system script run interflash-onu-optical" policy=read,test start-time=startup
/system script run interflash-onu-optical
'''
    body = f"""<div class="head"><div><h1>Activar monitor óptico</h1><p>Hioso HA7304VX · SN + RX + TX por SNMP de solo lectura</p></div>
    <a class="btn" href="{url_for('onu_page')}">← Volver</a></div>
    <div class="panel"><div class="notice" style="background:#063f2a;color:#fff;margin-bottom:12px"><b>Monitor óptico v1.</b> Pega este bloque completo una sola vez en New Terminal del CCR2116. Consulta la OLT cada 10 minutos y no realiza cambios en las ONU.</div>
    <textarea class="field" style="width:100%;height:520px;font-family:Consolas,monospace">{push_sync.escape(script)}</textarea></div>"""
    return base.shell('Activar monitor OLT', body, 'onu_page')


def setup(app):
    ensure_schema()
    app.add_url_rule('/api/olt/optical-batch', endpoint='onu_optical_batch', view_func=optical_batch, methods=['POST'])
    app.add_url_rule('/onu/monitor-script', endpoint='onu_optical_script', view_func=optical_script, methods=['GET'])
    app.view_functions['onu_page'] = onu_live_page
