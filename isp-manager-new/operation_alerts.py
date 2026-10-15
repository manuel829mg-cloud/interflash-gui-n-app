"""Visible operational failures without retrying or changing customer services."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import redirect, url_for
import app as base
from business_suite import esc


def ensure_schema():
    c=base.db()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS operation_alerts(
            alert_key TEXT PRIMARY KEY, kind TEXT NOT NULL, message TEXT NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, occurrences INTEGER NOT NULL DEFAULT 1,
            resolved_at TEXT)''')
        c.commit()
    finally:
        c.close()


def billing_failed():
    now=datetime.now(ZoneInfo('America/Santo_Domingo')).isoformat(timespec='seconds')
    c=base.db()
    try:
        c.execute('''INSERT INTO operation_alerts(alert_key,kind,message,first_seen,last_seen)
            VALUES('BILLING','Facturación','La facturación automática no terminó. Revisa las facturas y el registro del servicio.',?,?)
            ON CONFLICT(alert_key) DO UPDATE SET last_seen=excluded.last_seen,
            occurrences=operation_alerts.occurrences+1,resolved_at=NULL''',(now,now))
        c.commit()
    finally:
        c.close()


def billing_succeeded():
    c=base.db()
    try:
        c.execute("UPDATE operation_alerts SET resolved_at=? WHERE alert_key='BILLING' AND resolved_at IS NULL",(datetime.now(ZoneInfo('America/Santo_Domingo')).isoformat(timespec='seconds'),))
        c.commit()
    finally:
        c.close()


def read_alerts():
    c=base.db()
    try:
        billing=c.execute('SELECT * FROM operation_alerts WHERE resolved_at IS NULL ORDER BY last_seen DESC').fetchall()
        cutoff=(datetime.now(ZoneInfo('America/Santo_Domingo'))-timedelta(minutes=30)).replace(tzinfo=None).isoformat(timespec='seconds')
        whatsapp=c.execute("SELECT o.id,o.status,o.created_at,cu.name FROM whatsapp_outbox o LEFT JOIN customers cu ON cu.id=o.customer_id WHERE o.status IN ('ERROR','FALLIDO') AND datetime(o.created_at)>=datetime(?) ORDER BY o.id DESC LIMIT 50",(cutoff,)).fetchall()
        count=c.execute("SELECT COUNT(*) FROM whatsapp_outbox WHERE status IN ('ERROR','FALLIDO') AND datetime(created_at)>=datetime(?)",(cutoff,)).fetchone()[0]
        return billing,whatsapp,count
    finally:
        c.close()


def page():
    if not base.logged_in():
        return redirect(url_for('login'))
    billing,whatsapp,count=read_alerts()
    rows=''.join(f'<tr><td>{esc(a["kind"])}</td><td>{esc(a["message"])}</td><td>{esc(a["last_seen"])}</td><td>{a["occurrences"]}</td></tr>' for a in billing)
    messages=''.join(f'<tr><td>#{a["id"]}</td><td>{esc(a["name"] or "Cliente no disponible")}</td><td>{esc(a["status"])}</td><td>{esc(a["created_at"])}</td></tr>' for a in whatsapp)
    return base.shell('Alertas operativas',f'''<div class="panel"><h1>Alertas operativas</h1><p>Fallos registrados de facturación y WhatsApp. No se reenvían mensajes desde esta pantalla.</p><h2>Facturación</h2><div style="overflow:auto"><table class="table"><tr><th>Tipo</th><th>Detalle</th><th>Último fallo</th><th>Intentos fallidos</th></tr>{rows or '<tr><td colspan="4">Sin fallos de facturación registrados pendientes.</td></tr>'}</table></div><h2>WhatsApp: {count} avisos con error</h2><p>Se muestran hasta 50 errores de los últimos 30 minutos. Los anteriores se conservan en el historial. <a href="/whatsapp/queue">Abrir cola para revisar el detalle</a>.</p><div style="overflow:auto"><table class="table"><tr><th>Aviso</th><th>Cliente</th><th>Estado</th><th>Creado</th></tr>{messages or '<tr><td colspan="4">Sin avisos con error.</td></tr>'}</table></div></div>''','dashboard')


def setup(app):
    ensure_schema()
    original=base.shell
    def shell(title,body,active='dashboard'):
        if base.logged_in():
            try:
                billing,_,count=read_alerts()
                total=len(billing)+count
                if total:
                    body=body+f'<div role="alert" style="padding:14px;margin-bottom:16px;border:1px solid #e8ac45;border-radius:10px;background:#382b18;color:#ffe2a6"><b>Atención: {total} alerta(s) operativa(s).</b> <a href="/operations/alerts" style="color:#fff">Revisar fallos de facturación y WhatsApp</a></div>'
            except Exception:
                app.logger.warning('No se pudo consultar el panel de alertas operativas.')
        return original(title,body,active)
    base.shell=shell
    app.add_url_rule('/operations/alerts',endpoint='operation_alerts',view_func=page)
