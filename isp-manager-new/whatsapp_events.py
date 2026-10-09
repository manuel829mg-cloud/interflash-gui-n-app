"""Transactional business notices delivered through the configured WhatsApp adapter."""
import os
import secrets
import hmac
import threading
import time
from datetime import date, datetime
from flask import request, session, abort, redirect, url_for, flash
import app as base
import business_suite as bs
import whatsapp_suite as wa
import greenapi_suite as green


def schema():
    c = base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS whatsapp_event_keys(event_key TEXT PRIMARY KEY, outbox_id INTEGER);
        CREATE TABLE IF NOT EXISTS whatsapp_outbox_links(outbox_id INTEGER PRIMARY KEY, queue_id INTEGER UNIQUE);
    ''')
    # Existing historical notices require review, never bulk-send them on upgrade.
    c.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('whatsapp_event_floor',?)",
              (str(c.execute('SELECT COALESCE(MAX(id),0) FROM whatsapp_outbox').fetchone()[0]),))
    c.commit(); c.close()


def enqueue(c, key, customer_id, code, message):
    if dict(c.execute('SELECT key,value FROM app_settings')).get('whatsapp_enabled') != '1':
        return False
    cu = c.execute("SELECT * FROM customers WHERE id=? AND status<>'ELIMINADO'", (customer_id,)).fetchone()
    if not cu or not cu['phone']:
        return False
    if not c.execute('INSERT OR IGNORE INTO whatsapp_event_keys(event_key) VALUES(?)', (key,)).rowcount:
        return False
    oid = c.execute("INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(?,?,?,?,'PENDIENTE',?)",
                    (customer_id, cu['phone'], code, message, wa._now())).lastrowid
    c.execute('UPDATE whatsapp_event_keys SET outbox_id=? WHERE event_key=?', (oid, key))
    return True


def command_notice(c, cmd):
    if cmd['action'] not in ('SUSPEND', 'REACTIVATE'):
        return
    cu = c.execute('SELECT name FROM customers WHERE id=?', (cmd['customer_id'],)).fetchone()
    if not cu:
        return
    text = 'tu servicio de INTER Flash ha sido suspendido. Comunícate con nosotros para regularizarlo.' if cmd['action'] == 'SUSPEND' else 'tu servicio de INTER Flash ha sido reactivado.'
    enqueue(c, f"COMMAND:{cmd['id']}", cmd['customer_id'], cmd['action'], f"Hola {cu['name']}, {text}")


def create_promise(customer_id, invoice_id, promise_date, amount, notes):
    from payment_flow import money
    when = date.fromisoformat(promise_date)
    if when < date.today():
        raise ValueError('La promesa debe tener una fecha de hoy o posterior.')
    value = money(amount)
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        cu = c.execute("SELECT * FROM customers WHERE id=? AND status<>'ELIMINADO'", (customer_id,)).fetchone()
        if not cu:
            raise ValueError('Cliente no disponible.')
        if invoice_id:
            inv = c.execute("SELECT * FROM invoices WHERE id=? AND customer_id=? AND status='PENDIENTE'", (invoice_id, customer_id)).fetchone()
            if not inv:
                raise ValueError('Selecciona una factura pendiente de este cliente.')
        pid = c.execute("INSERT INTO payment_promises(customer_id,invoice_id,promise_date,amount,status,notes,created_at) VALUES(?,?,?,?,'PENDIENTE',?,?)",
                        (customer_id, invoice_id or None, when.isoformat(), float(value), notes, wa._now())).lastrowid
        enqueue(c, f'PROMISE:{pid}', customer_id, 'PROMISE',
                f"Hola {cu['name']}, registramos tu promesa de pago a INTER Flash por RD${value:,.2f} para el {when.strftime('%d/%m/%Y')}.")
        c.commit()
        return pid
    except Exception:
        c.rollback(); raise
    finally:
        c.close()


def promise_reminders():
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        # An invoice settled in full no longer needs promise reminders.
        c.execute("UPDATE payment_promises SET status='CUMPLIDA' WHERE status='PENDIENTE' AND invoice_id IN (SELECT id FROM invoices WHERE status='PAGADA')")
        rows = c.execute("SELECT p.*,cu.name FROM payment_promises p JOIN customers cu ON cu.id=p.customer_id WHERE p.status='PENDIENTE' AND p.promise_date=? AND cu.status<>'ELIMINADO'", (date.today().isoformat(),)).fetchall()
        for p in rows:
            balance = c.execute("SELECT COALESCE(SUM(i.amount-COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id=i.id),0)),0) FROM invoices i WHERE i.customer_id=? AND i.status='PENDIENTE' AND (? IS NULL OR i.id=?)", (p['customer_id'], p['invoice_id'], p['invoice_id'])).fetchone()[0]
            if balance <= 0:
                continue
            # Creation already confirms today's promise; avoid two immediate messages.
            if str(p['created_at'] or '')[:10] == date.today().isoformat():
                continue
            amount = min(float(p['amount']), float(balance))
            enqueue(c, f"PROMISE_DUE:{p['id']}:{p['promise_date']}", p['customer_id'], 'PROMISE_DUE',
                    f"Hola {p['name']}, te recordamos que hoy vence tu promesa de pago a INTER Flash por RD${amount:,.2f}. Si ya pagaste, envíanos tu comprobante.")
        c.commit()
    finally:
        c.close()


def send_outbox(limit=25):
    if bs.setting('whatsapp_enabled', '0') != '1' or not wa._meta_ready():
        return 0, 'Avisos desactivados o proveedor pendiente.'
    sent = 0
    for _ in range(limit):
        c = base.db()
        try:
            c.execute('BEGIN IMMEDIATE')
            floor = int(dict(c.execute('SELECT key,value FROM app_settings')).get('whatsapp_event_floor', '0'))
            row = c.execute("SELECT o.* FROM whatsapp_outbox o LEFT JOIN whatsapp_outbox_links l ON l.outbox_id=o.id WHERE o.id>? AND o.status='PENDIENTE' AND l.outbox_id IS NULL ORDER BY o.id LIMIT 1", (floor,)).fetchone()
            if not row:
                c.rollback(); break
            if row['template_code'] == 'ZONE_REMINDER':
                from zone_whatsapp_reminders import valid
                if not valid(c, row['id']):
                    c.execute("UPDATE whatsapp_outbox SET status='CANCELADO',error='Recordatorio resuelto, desactivado o fuera de fecha' WHERE id=?", (row['id'],))
                    c.commit()
                    continue
            if row['template_code'] == 'PROMISE_DUE':
                event = c.execute('SELECT event_key FROM whatsapp_event_keys WHERE outbox_id=?', (row['id'],)).fetchone()
                pid = int(event[0].split(':')[1]) if event else 0
                promise = c.execute("SELECT * FROM payment_promises WHERE id=? AND status='PENDIENTE' AND promise_date=?", (pid, date.today().isoformat())).fetchone()
                debt = c.execute("SELECT 1 FROM invoices i WHERE i.customer_id=? AND i.status='PENDIENTE' AND i.amount>COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id=i.id),0) AND (? IS NULL OR i.id=?)", (row['customer_id'], promise['invoice_id'] if promise else None, promise['invoice_id'] if promise else None)).fetchone()
                if not promise or not debt:
                    c.execute("UPDATE whatsapp_outbox SET status='CANCELADO',error='Promesa resuelta o recordatorio vencido' WHERE id=?", (row['id'],))
                    c.commit()
                    continue
            if row['template_code'] == 'ZONE_REMINDER':
                row = c.execute('SELECT * FROM whatsapp_outbox WHERE id=?', (row['id'],)).fetchone()
            phone = wa._wa_phone(row['phone'])
            thread = wa._thread_for_phone(c, phone, customer_id=row['customer_id'])
            qid = c.execute("INSERT INTO whatsapp_queue(thread_id,customer_id,phone,kind,body,status,created_at) VALUES(?,?,?,'text',?,'EN_PROCESO',?)", (thread['id'], row['customer_id'], phone, row['message'], wa._now())).lastrowid
            c.execute('INSERT INTO whatsapp_outbox_links VALUES(?,?)', (row['id'], qid))
            c.execute("UPDATE whatsapp_outbox SET status='EN_PROCESO' WHERE id=?", (row['id'],))
            c.commit()
            job = c.execute('SELECT * FROM whatsapp_queue WHERE id=?', (qid,)).fetchone()
            # No automatic retry on ambiguous provider responses: prevents duplicate notices.
            ok, error = wa._process_queue_item(c, job)
            result = c.execute('SELECT status,sent_at,last_error FROM whatsapp_queue WHERE id=?', (qid,)).fetchone()
            c.execute('UPDATE whatsapp_outbox SET status=?,sent_at=?,error=? WHERE id=?', (result['status'], result['sent_at'], result['last_error'], row['id']))
            c.commit()
            sent += int(ok)
        finally:
            c.close()
    # Reflect delivery receipts and administrator retries in the legacy history.
    c = base.db()
    c.execute("UPDATE whatsapp_queue SET status='ERROR',last_error='Envío interrumpido: revisa el proveedor antes de reintentar para evitar duplicados.' WHERE status='EN_PROCESO' AND datetime(created_at)<datetime('now','localtime','-5 minutes') AND id IN (SELECT queue_id FROM whatsapp_outbox_links)")
    c.execute('''UPDATE whatsapp_outbox SET (status,sent_at,error)=(SELECT q.status,q.sent_at,q.last_error FROM whatsapp_queue q JOIN whatsapp_outbox_links l ON l.queue_id=q.id WHERE l.outbox_id=whatsapp_outbox.id) WHERE id IN (SELECT outbox_id FROM whatsapp_outbox_links)''')
    c.commit(); c.close()
    return sent, 'Procesado; consulta los estados de entrega en la cola.'


def page():
    if not base.logged_in(): return redirect(url_for('login'))
    if session.get('role', 'ADMIN') != 'ADMIN': abort(403)
    state = 'Sin comprobar'
    if green.enabled():
        try:
            state = 'CONECTADO' if green.api('getStateInstance').get('stateInstance') == 'authorized' else 'DESCONECTADO: revisa el QR de GREEN-API'
        except green.APIError as exc:
            state = str(exc)
    if request.method == 'POST':
        if not hmac.compare_digest(session.get('wa_events_csrf', ''), request.form.get('csrf', 'missing')): abort(403)
        if request.form.get('action') == 'enable':
            if state != 'CONECTADO':
                flash('No se activaron los avisos: primero conecta GREEN-API.')
            else:
                c = base.db()
                c.execute('BEGIN IMMEDIATE')
                if dict(c.execute('SELECT key,value FROM app_settings')).get('whatsapp_enabled') != '1':
                    floor = c.execute('SELECT COALESCE(MAX(id),0) FROM whatsapp_outbox').fetchone()[0]
                    c.execute("UPDATE app_settings SET value=? WHERE key='whatsapp_event_floor'", (str(floor),))
                c.execute("UPDATE app_settings SET value='1' WHERE key='whatsapp_enabled'")
                c.commit(); c.close()
                flash('Avisos automáticos activados para nuevos eventos.')
        else:
            bs.set_setting('whatsapp_enabled', '0')
        return redirect(url_for('whatsapp_automatics'))
    token = session.setdefault('wa_events_csrf', secrets.token_urlsafe(32))
    enabled = bs.setting('whatsapp_enabled', '0') == '1'
    body = wa._tabs('auto') + f'''<div class="panel"><h1>Avisos automáticos de WhatsApp</h1><p>GREEN-API: <b>{wa.esc(state)}</b></p><p>Avisos: <b>{'ACTIVOS' if enabled else 'DESACTIVADOS'}</b></p><ul><li>Pago: confirmación del monto registrado.</li><li>Corte y reconexión: aviso cuando MikroTik confirma la operación.</li><li>Promesa: confirmación al guardarla y recordatorio el día acordado si queda deuda.</li><li>Facturas: emisión y vencimiento.</li><li>Recordatorio antes del corte: configurable al crear o editar cada zona, solo con deuda pendiente, desde las 8:00.</li></ul><p>Revisión automática cada 10 segundos. El recordatorio de promesa se revisa durante el día, desde las 8:00, hora dominicana.</p><p>Los avisos anteriores a la activación no se envían en lote. Un error o envío sin confirmación requiere revisión antes de reintentarlo.</p><form method="post"><input type="hidden" name="csrf" value="{wa.esc(token)}"><button class="btn green" name="action" value="{'disable' if enabled else 'enable'}">{'Desactivar avisos' if enabled else 'Activar avisos automáticos'}</button></form><p><a class="btn" href="/whatsapp/queue">Ver estados de entrega</a></p></div>'''
    return base.shell('Avisos automáticos', body, 'whatsapp_inbox')


def setup(app):
    schema()
    bs.try_send_outbox = send_outbox
    app.view_functions['whatsapp_automatics'] = page
    app.add_url_rule('/whatsapp/automatics', endpoint='whatsapp_events_save', view_func=page, methods=['POST'])
    if os.getenv('INTERFLASH_TESTING') == '1': return
    def worker():
        while True:
            try:
                with app.app_context():
                    if 8 <= datetime.now().hour < 20:
                        promise_reminders()
                        from zone_whatsapp_reminders import process
                        process()
                    send_outbox()
            except Exception:
                app.logger.error('Revisión de avisos WhatsApp pendiente; se volverá a comprobar.')
            time.sleep(10)
    threading.Thread(target=worker, daemon=True, name='whatsapp-business-events').start()
