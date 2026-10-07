"""Deterministic opt-in menu; durable, single-attempt reply queue."""
import secrets
import threading
import time
import unicodedata
from flask import session, request, abort, redirect, url_for, flash
import app as base

MENU = ('¡Hola! Bienvenido a INTER Flash.\nElige una opción:\n'
        '1. Consultar factura\n2. Cuentas bancarias\n3. Reportar un pago\n4. Soporte técnico\n'
        'Escribe MENÚ para volver o ASESOR para atención personal.')


def schema():
    c=base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS whatsapp_menu_config(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 1);
    INSERT OR IGNORE INTO whatsapp_menu_config(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS whatsapp_menu_state(phone TEXT PRIMARY KEY,last_reply REAL DEFAULT 0,pause_until REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS whatsapp_menu_jobs(event_id TEXT PRIMARY KEY,queue_id INTEGER UNIQUE,instance TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'PENDIENTE',created REAL NOT NULL);
    ''');c.commit();c.close()


def enqueue(c, thread, text, event_id, instance):
    import whatsapp_suite as wa
    import greenapi_suite as green
    if not green.enabled() or not c.execute('SELECT enabled FROM whatsapp_menu_config WHERE id=1').fetchone()[0]: return
    command=''.join(ch for ch in unicodedata.normalize('NFD',text.lower().strip()) if unicodedata.category(ch)!='Mn')
    if command not in ('hola','menu','buenas','buenos dias','buenas tardes','buenas noches','1','2','3','4','asesor'): return
    now=time.time();phone=thread['phone']
    state=c.execute('SELECT * FROM whatsapp_menu_state WHERE phone=?',(phone,)).fetchone()
    if state and (now-state['last_reply']<10 or (state['pause_until']>now and command!='menu')): return
    if c.execute('SELECT 1 FROM whatsapp_menu_jobs WHERE event_id=?',(event_id,)).fetchone(): return
    pause=0; reply=MENU
    if command=='1':
        matches=[r for r in c.execute("SELECT id,phone FROM customers WHERE COALESCE(status,'')<>'ELIMINADO'").fetchall() if wa._wa_phone(r['phone'])==phone]
        if len(matches)!=1:
            reply='Para consultar tu factura, un asesor debe verificar tu cuenta. Escribe ASESOR para solicitar atención.'
        else:
            invoices=c.execute("SELECT i.*,COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0) paid FROM invoices i WHERE customer_id=? AND status IN ('PENDIENTE','VENCIDA') ORDER BY due_date,id",(matches[0]['id'],)).fetchall()
            pending=[(i,max(0,float(i['amount'] or 0)-float(i['paid'] or 0))) for i in invoices]
            pending=[(i,b) for i,b in pending if b>0.005]
            if not pending: reply='No tienes facturas pendientes registradas en INTER Flash. Escribe MENÚ para volver.'
            else:
                invoice,balance=pending[0]
                reply=f"INTER Flash\nSaldo pendiente de facturas: RD${sum(b for _,b in pending):,.2f}.\nFactura #{invoice['id']}: RD${balance:,.2f}.\nVencimiento: {invoice['due_date']}.\nEscribe 2 para ver las cuentas bancarias o MENÚ para volver."
    elif command=='2':
        banks=[]
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='bank_accounts' AND type='table'").fetchone():
            banks=c.execute("SELECT * FROM bank_accounts WHERE active=1 AND COALESCE(account_number,'')<>'' ORDER BY id").fetchall()
        reply=('Cuentas de INTER Flash:\n'+'\n\n'.join(f"{b['bank']} · {b['account_type'] or ''}\n{b['account_number']}\n{b['label'] or ''}" for b in banks)+'\n\nEscribe 3 para reportar el pago.') if banks else 'Todavía no hay cuentas bancarias configuradas. Escribe ASESOR para solicitar los datos de pago.'
    elif command in ('3','4','asesor'):
        pause=now+86400
        reply={'3':'Para reportar tu pago, escribe el banco, monto, fecha y referencia. Un asesor lo revisará; este mensaje no registra ni confirma el pago. Puedes adjuntar el comprobante, pero su imagen todavía debe revisarse en el WhatsApp del negocio.',
               '4':'Cuéntanos qué problema tienes con tu internet. Tu consulta quedará en esta conversación para que un asesor la atienda.',
               'asesor':'Tu solicitud de atención quedará en esta conversación. Cuéntanos cómo podemos ayudarte.'}[command]
        reply+='\nEl menú queda pausado durante 24 horas. Escribe MENÚ para volver antes.'
    cur=c.execute("INSERT INTO whatsapp_queue(thread_id,customer_id,phone,kind,body,status,created_at) VALUES(?,?,?,'text',?,'PENDIENTE',?)",(thread['id'],thread['customer_id'],phone,reply[:4096],wa._now()))
    c.execute('INSERT INTO whatsapp_menu_jobs(event_id,queue_id,instance,created) VALUES(?,?,?,?)',(event_id,cur.lastrowid,instance,now))
    c.execute('INSERT INTO whatsapp_menu_state(phone,last_reply,pause_until) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET last_reply=excluded.last_reply,pause_until=excluded.pause_until',(phone,now,pause))


def process_one():
    import whatsapp_suite as wa
    import greenapi_suite as green
    c=base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        job=c.execute("SELECT * FROM whatsapp_menu_jobs WHERE state='PENDIENTE' ORDER BY created LIMIT 1").fetchone()
        if not job: c.commit();return
        cfg=green.config()
        enabled=c.execute('SELECT enabled FROM whatsapp_menu_config WHERE id=1').fetchone()[0]
        row=c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(job['queue_id'],)).fetchone()
        if not row or row['status']!='PENDIENTE':
            c.execute("UPDATE whatsapp_menu_jobs SET state='OMITIDO' WHERE event_id=?",(job['event_id'],));c.commit();return
        if not enabled or not cfg['active'] or cfg['channel']!=job['instance'] or time.time()-job['created']>300:
            c.execute("UPDATE whatsapp_queue SET status='CANCELADO',last_error='Respuesta automática cancelada por pausa, cambio de conexión o antigüedad' WHERE id=?",(row['id'],))
            c.execute("UPDATE whatsapp_menu_jobs SET state='CANCELADO' WHERE event_id=?",(job['event_id'],));c.commit();return
        c.execute("UPDATE whatsapp_menu_jobs SET state='EN_PROCESO' WHERE event_id=?",(job['event_id'],))
        c.execute("UPDATE whatsapp_queue SET status='EN_PROCESO',attempts=attempts+1 WHERE id=?",(row['id'],));c.commit()
        ok,pid,error=green.send_text(row['phone'],row['body'])
        status=green.confirmed_status(c,pid,'ACEPTADO') if ok else 'ERROR'
        c.execute('UPDATE whatsapp_queue SET status=?,provider_id=?,last_error=?,sent_at=? WHERE id=?',(status,pid or None,error or None,wa._now() if ok else None,row['id']))
        wa._record_outgoing(c,row['thread_id'],row['body'],pid,status,error)
        c.execute("UPDATE whatsapp_menu_jobs SET state='FINALIZADO' WHERE event_id=?",(job['event_id'],));c.commit()
    finally:c.close()


def toggle():
    if not base.logged_in():abort(401)
    if session.get('role')!='ADMIN':abort(403)
    if not session.get('wa_menu_csrf') or not secrets.compare_digest(session['wa_menu_csrf'],request.form.get('csrf','')):abort(403)
    c=base.db();c.execute('UPDATE whatsapp_menu_config SET enabled=? WHERE id=1',(1 if request.form.get('enabled')=='1' else 0,));c.commit();c.close()
    flash('Configuración del menú automático guardada.');return redirect(url_for('whatsapp_settings'))


def panel():
    import whatsapp_suite as wa
    c=base.db();enabled=c.execute('SELECT enabled FROM whatsapp_menu_config WHERE id=1').fetchone()[0];c.close()
    token=session.setdefault('wa_menu_csrf',secrets.token_urlsafe(32))
    control=f'<form method="post" action="{url_for("whatsapp_menu_toggle")}"><input type="hidden" name="csrf" value="{wa.esc(token)}"><button class="btn" name="enabled" value="{0 if enabled else 1}">{"Desactivar" if enabled else "Activar"} menú automático</button></form>' if session.get('role')=='ADMIN' else ''
    return f'<div class="panel"><h3>Menú automático sin IA · {"ACTIVO" if enabled else "DESACTIVADO"}</h3><pre style="white-space:pre-wrap">{wa.esc(MENU)}</pre><p>Responde a HOLA, MENÚ y las opciones 1–4. Consulta factura por el número registrado; no registra pagos ni cambia el servicio. Soporte y pagos pausan el menú 24 horas.</p>{control}</div>'


def setup(app):
    schema();app.add_url_rule('/whatsapp/menu',endpoint='whatsapp_menu_toggle',view_func=toggle,methods=['POST'])


def start_worker(app):
    def worker():
        while True:
            try:
                with app.app_context(): process_one()
            except Exception as exc: app.logger.error('WhatsApp menu worker failed type=%s',type(exc).__name__)
            time.sleep(2)
    threading.Thread(target=worker,name='whatsapp-menu',daemon=True).start()
