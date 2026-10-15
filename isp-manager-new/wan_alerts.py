"""Persistent WAN probe alerts. Never executes router commands or calls AI."""
import hmac
import os
import secrets
import threading
import time
from datetime import datetime
from html import escape
from flask import abort, redirect, request, session, url_for
import app as base

LABELS = {'ONLINE':'Prueba recuperada', 'LOSS':'Pérdida de paquetes en prueba',
          'NO_REPLY':'Sin respuesta del destino de prueba', 'STALE':'Sin datos recientes'}
INTERFACES = ('WAN1-CLARO','WAN2-CLARO','WAN3-ALTICE','WAN4-ALTICE')

def schema():
    c = base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS wan_alert_state(
      router_name TEXT, interface_name TEXT, state TEXT, candidate TEXT,
      streak INTEGER DEFAULT 0, sample_at TEXT, PRIMARY KEY(router_name,interface_name));
    CREATE TABLE IF NOT EXISTS wan_alert_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,router_name TEXT,interface_name TEXT,
      state TEXT,message TEXT,created_at TEXT,outbox_id INTEGER);
    ''')
    c.execute('''CREATE TABLE IF NOT EXISTS wan_whatsapp_incidents(
      router_name TEXT, interface_name TEXT, opened_at TEXT,
      PRIMARY KEY(router_name,interface_name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS wan_whatsapp_filter(
      router_name TEXT, interface_name TEXT, candidate TEXT, since_at TEXT, last_at TEXT,
      PRIMARY KEY(router_name,interface_name))''')
    c.commit(); c.close()

def _event(c, router, iface, state, loss, stamp, notify=False):
    detail = f' ({loss:.0f}% de pérdida en la muestra)' if loss is not None else ''
    message = f'INTER Flash · {router} · {iface}: {LABELS[state]}{detail}. Hora: {stamp}. '
    message += 'Una prueba ICMP no confirma por sí sola una caída del proveedor. No se ejecutó ninguna reparación.'
    eid = c.execute('INSERT INTO wan_alert_events(router_name,interface_name,state,message,created_at) VALUES(?,?,?,?,?)',
                    (router,iface,state,message,stamp)).lastrowid
    if not notify:
        return
    settings = dict(c.execute('SELECT key,value FROM app_settings'))
    phone = settings.get('wan_alert_phone','')
    # Filter only administrator WhatsApp notices; retain every panel event.
    incident = c.execute('SELECT 1 FROM wan_whatsapp_incidents WHERE router_name=? AND interface_name=?',(router,iface)).fetchone()
    important = state == 'NO_REPLY' or (state == 'LOSS' and loss is not None and loss >= 50)
    recovery = state == 'ONLINE' and incident is not None
    if not ((important and not incident) or recovery):
        return
    if settings.get('wan_alert_whatsapp') == '1' and settings.get('whatsapp_enabled') == '1' and phone:
        oid = c.execute("INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(NULL,?,'WAN_ALERT',?,'PENDIENTE',?)", (phone,message,stamp)).lastrowid
        c.execute('UPDATE wan_alert_events SET outbox_id=? WHERE id=?',(oid,eid))
        if recovery:
            c.execute('DELETE FROM wan_whatsapp_incidents WHERE router_name=? AND interface_name=?',(router,iface))
        else:
            c.execute('INSERT OR IGNORE INTO wan_whatsapp_incidents VALUES(?,?,?)',(router,iface,stamp))


def _whatsapp_sample(c, router, iface, state, loss, now):
    """Debounce only administrator notices, independently of panel transitions."""
    severe = state == 'NO_REPLY' or (state == 'LOSS' and loss is not None and loss >= 50)
    candidate = 'BAD' if severe else 'GOOD' if state == 'ONLINE' else 'OTHER'
    stamp = now.isoformat(timespec='seconds')
    previous = c.execute('SELECT * FROM wan_whatsapp_filter WHERE router_name=? AND interface_name=?',
                         (router,iface)).fetchone()
    since = stamp
    if previous and previous['candidate'] == candidate:
        try:
            gap = (now-datetime.fromisoformat(previous['last_at'])).total_seconds()
            if 0 <= gap <= 45:
                since = previous['since_at']
        except (ValueError,TypeError):
            pass
    c.execute('''INSERT INTO wan_whatsapp_filter VALUES(?,?,?,?,?)
        ON CONFLICT(router_name,interface_name) DO UPDATE SET
        candidate=excluded.candidate,since_at=excluded.since_at,last_at=excluded.last_at''',
        (router,iface,candidate,since,stamp))
    elapsed = (now-datetime.fromisoformat(since)).total_seconds()
    incident = c.execute('SELECT 1 FROM wan_whatsapp_incidents WHERE router_name=? AND interface_name=?',
                         (router,iface)).fetchone()
    if candidate == 'BAD' and elapsed >= 180 and not incident:
        _event(c,router,iface,state,loss,stamp,notify=True)
    elif candidate == 'GOOD' and elapsed >= 300 and incident:
        _event(c,router,iface,'ONLINE',0,stamp,notify=True)


def observe(c, router, iface, loss, sample_at, now=None):
    if iface not in INTERFACES:
        return
    now = now or datetime.now()
    try:
        age = (now-datetime.fromisoformat(sample_at)).total_seconds()
    except (TypeError,ValueError):
        age = 999
    state = 'STALE' if not 0 <= age <= 45 else 'NO_REPLY' if loss >= 100 else 'LOSS' if loss > 0 else 'ONLINE'
    row = c.execute('SELECT * FROM wan_alert_state WHERE router_name=? AND interface_name=?',(router,iface)).fetchone()
    stamp = now.isoformat(timespec='seconds')
    if state == 'STALE' or not row or row['sample_at'] != sample_at:
        _whatsapp_sample(c,router,iface,state,loss if state != 'STALE' else None,now)
    if not row:
        # Establish a baseline without announcing an ordinary healthy start.
        c.execute('INSERT INTO wan_alert_state VALUES(?,?,?,?,?,?)',(router,iface,'BASELINE',state,1,sample_at))
        return
    if state != 'STALE' and row['sample_at'] == sample_at:
        return
    streak = row['streak']+1 if row['candidate'] == state else 1
    required = 1 if state == 'STALE' else 3
    confirmed = state if streak >= required else row['state']
    if confirmed != row['state']:
        if state != 'ONLINE' or row['state'] != 'BASELINE':
            _event(c,router,iface,state,loss if state != 'STALE' else None,stamp)
    c.execute('UPDATE wan_alert_state SET state=?,candidate=?,streak=?,sample_at=? WHERE router_name=? AND interface_name=?',
              (confirmed,state,min(streak,3),sample_at,router,iface))


def check_stale():
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        for row in c.execute('SELECT * FROM wan_line_health').fetchall():
            try:
                age = (datetime.now()-datetime.fromisoformat(row['updated_at'])).total_seconds()
            except (TypeError,ValueError):
                age = 999
            if not 0 <= age <= 45:
                observe(c,row['router_name'],row['interface_name'],float(row['packet_loss']),row['updated_at'])
        c.commit()
    finally:
        c.close()


def page():
    if not base.logged_in(): return redirect(url_for('login'))
    if (session.get('role') or 'ADMIN').upper() != 'ADMIN': abort(403)
    token = session.setdefault('wan_alert_csrf',secrets.token_urlsafe(32))
    c = base.db(); error = ''
    try:
        if request.method == 'POST':
            if not hmac.compare_digest(token,request.form.get('csrf','')): abort(403)
            import re
            phone = re.sub(r'[^0-9]','',request.form.get('phone',''))
            enabled = request.form.get('enabled') == '1'
            if enabled and not 10 <= len(phone) <= 15:
                error = 'Indica tu número de WhatsApp con código de país para activar los avisos.'
            else:
                if len(phone) == 10 and phone.startswith(('809','829','849')): phone = '1'+phone
                for key,value in [('wan_alert_phone',phone),('wan_alert_whatsapp','1' if enabled else '0')]:
                    c.execute('INSERT INTO app_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
                c.commit()
                return redirect(url_for('wan_alerts'))
        settings = dict(c.execute('SELECT key,value FROM app_settings'))
        events = c.execute('''SELECT e.*,o.status delivery FROM wan_alert_events e LEFT JOIN whatsapp_outbox o ON o.id=e.outbox_id ORDER BY e.id DESC LIMIT 100''').fetchall()
        esc = lambda v: escape(str(v or ''))
        rows = ''.join(f'<tr><td>{esc(r["created_at"])}</td><td>{esc(r["router_name"])} / {esc(r["interface_name"])}</td><td>{esc(LABELS[r["state"]])}</td><td>{esc(r["delivery"] or "Solo panel")}</td></tr>' for r in events)
        body = f'''<div class="head"><h1>Alertas de líneas</h1></div><div class="panel"><p>Monitoreo del panel activo. Se confirma un cambio tras tres muestras consecutivas; no se repite el aviso mientras el estado siga igual. Si pasan 45 segundos sin medición, se registra en el panel. WhatsApp avisa una vez tras 3 minutos continuos con pérdida de al menos 50% o sin respuesta. Solo avisa recuperación después de 5 minutos continuos sin pérdida. Las fluctuaciones breves y la falta de muestras quedan en el panel.</p><p>Las alertas describen pruebas ICMP. No garantizan que el proveedor esté caído ni comprueban el failover. No ejecutan reparaciones ni consultas de IA.</p><p>{esc(error)}</p><form method="post"><input type="hidden" name="csrf" value="{esc(token)}"><label>Tu WhatsApp para alertas<input name="phone" value="{esc(settings.get('wan_alert_phone'))}" placeholder="Código de país y número"></label><label><input type="checkbox" name="enabled" value="1" {'checked' if settings.get('wan_alert_whatsapp')=='1' else ''}> Enviarme alertas por WhatsApp</label><p>Requiere avisos generales de WhatsApp activos y proveedor conectado. Solo se envían eventos nuevos; el historial no se manda en lote.</p><button class="btn green">Guardar</button></form></div><div class="panel"><table class="table"><tr><th>Hora</th><th>Línea</th><th>Evento</th><th>WhatsApp</th></tr>{rows or '<tr><td colspan="4">Sin eventos registrados.</td></tr>'}</table></div>'''
        return base.shell('Alertas WAN',body,'wan_alerts')
    finally:
        c.close()


def setup(app):
    schema()
    app.add_url_rule('/wan-alerts',endpoint='wan_alerts',view_func=page,methods=['GET','POST'])
    base.NAV.append(('wan_alerts','!','Alertas de líneas'))
    if os.getenv('INTERFLASH_TESTING') == '1': return
    def worker():
        while True:
            try:
                with app.app_context(): check_stale()
            except Exception:
                app.logger.error('No se pudo revisar la vigencia de las muestras WAN.')
            time.sleep(10)
    threading.Thread(target=worker,name='wan-alerts',daemon=True).start()
