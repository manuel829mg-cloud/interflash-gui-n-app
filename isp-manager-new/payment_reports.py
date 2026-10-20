"""Incoming attachments are reports for human review, never proof of settlement."""
import os
import secrets
from html import escape as esc
from flask import request, session, redirect, url_for, abort, flash, g
import app as base


def schema():
    c = base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS whatsapp_payment_reports(
        id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE, thread_id INTEGER NOT NULL,
        customer_id INTEGER, phone TEXT NOT NULL, attachment_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDIENTE', created_at TEXT NOT NULL,
        reviewed_at TEXT, outbox_id INTEGER);
    CREATE INDEX IF NOT EXISTS idx_payment_reports_status ON whatsapp_payment_reports(status,id);
    ''')
    c.commit(); c.close()


def attachment_type(data):
    media = data.get('media') if isinstance(data.get('media'), dict) else {}
    mime = str(media.get('mimetype') or media.get('mimeType') or '').lower().split(';')[0]
    kind = str(data.get('type') or '').lower()
    if mime.startswith('image/') or kind == 'image':
        return 'image'
    if mime == 'application/pdf' or (kind == 'document' and str(media.get('filename') or '').lower().endswith('.pdf')):
        return 'document'
    return None


def capture(c, mid, thread_id, phone, kind, stamp):
    if not kind:
        return
    from customer_phones import recipients
    import whatsapp_suite as wa
    # A shared telephone is ambiguous, even if an old chat has a customer_id.
    matches = [r for r in c.execute("SELECT * FROM customers WHERE COALESCE(status,'')<>'ELIMINADO'") if phone in recipients(r)]
    cu = matches[0] if len(matches) == 1 else None
    cur = c.execute('''INSERT OR IGNORE INTO whatsapp_payment_reports
        (message_id,thread_id,customer_id,phone,attachment_type,created_at) VALUES(?,?,?,?,?,?)''',
        (mid,thread_id,cu['id'] if cu else None,phone,kind,stamp))
    if not cur.rowcount:
        return
    report_id = cur.lastrowid
    settings = dict(c.execute('SELECT key,value FROM app_settings'))
    # Reuse the administrator's existing alert destination; never the sender.
    target = wa._wa_phone(settings.get('payment_report_phone') or settings.get('wan_alert_phone') or '')
    root = os.environ.get('APP_URL', '').rstrip('/')
    if target and target != phone and settings.get('whatsapp_enabled') == '1' and root.startswith('https://'):
        label = cu['name'] if cu else phone + ' (cliente por identificar)'
        body = ('INTER Flash · Posible comprobante recibido de ' + label +
                '.\nPago pendiente de verificar. Revisa el comprobante en el WhatsApp del negocio y confirma el ingreso en tu banco.\n' +
                root + '/pagos/reportados/' + str(report_id))
        oid = c.execute("""INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at)
            VALUES(NULL,?,'PAYMENT_REPORT',?,'PENDIENTE',?)""", (target,body,stamp)).lastrowid
        c.execute('UPDATE whatsapp_payment_reports SET outbox_id=? WHERE id=?',(oid,report_id))


def access():
    if not base.logged_in():
        # Store only our internally constructed path; the login clears session.
        return redirect(url_for('login', payment_report=request.path))
    if (session.get('role') or 'ADMIN').upper() not in ('ADMIN','CAJA','COBRADOR'):
        abort(403)


def csrf():
    return session.setdefault('payment_report_csrf',secrets.token_urlsafe(32))


def check_csrf():
    if not secrets.compare_digest(csrf(), request.form.get('csrf','')):
        abort(403)


def reports():
    gate = access()
    if gate is not None: return gate
    c=base.db()
    try:
        if request.method == 'POST':
            if (session.get('role') or 'ADMIN').upper() != 'ADMIN': abort(403)
            check_csrf()
            import whatsapp_suite as wa
            phone=wa._wa_phone(request.form.get('phone'))
            if phone and (not phone.isascii() or not phone.isdigit() or not 8 <= len(phone) <= 15): abort(400)
            c.execute("INSERT INTO app_settings(key,value) VALUES('payment_report_phone',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(phone,))
            c.commit(); flash('Destino de avisos guardado. Solo se avisarán comprobantes nuevos.')
        settings=dict(c.execute('SELECT key,value FROM app_settings'))
        rows=c.execute('''SELECT r.*,cu.name FROM whatsapp_payment_reports r LEFT JOIN customers cu ON cu.id=r.customer_id
                          ORDER BY r.id DESC LIMIT 100''').fetchall()
    finally: c.close()
    body='<div class="head"><h1>Comprobantes por revisar</h1></div><div class="panel"><p>Las imágenes y PDF recibidos se señalan como posibles comprobantes. Revisa el archivo en el WhatsApp del negocio y verifica el ingreso antes de registrar un pago.</p>'
    if (session.get('role') or 'ADMIN').upper() == 'ADMIN':
        phone=settings.get('payment_report_phone') or settings.get('wan_alert_phone') or ''
        body+=f'<form method="post" class="toolbar"><input type="hidden" name="csrf" value="{csrf()}"><label>Tu WhatsApp para avisos <input class="field" name="phone" value="{esc(phone)}" placeholder="1809..."></label><button class="btn">Guardar destino</button></form>'
        if not phone: body+='<p class="notice">Configura tu número para recibir los enlaces por WhatsApp. Los reportes ya quedan registrados aquí.</p>'
    body+='<table class="table"><tr><th>Cliente</th><th>Fecha</th><th>Revisión</th><th></th></tr>'
    for r in rows:
        body+=f'<tr><td>{esc(r["name"] or "Cliente por identificar")}<br>{esc(r["phone"])}</td><td>{esc(r["created_at"])}</td><td>{esc(r["status"])}</td><td><a class="btn blue" href="{url_for("payment_report_detail",id=r["id"])}">Revisar</a></td></tr>'
    return base.shell('Comprobantes por revisar',body+'</table></div>','whatsapp_chat')


def detail(id):
    gate=access()
    if gate is not None: return gate
    c=base.db()
    try:
        r=c.execute('''SELECT r.*,cu.name,m.body FROM whatsapp_payment_reports r
            LEFT JOIN customers cu ON cu.id=r.customer_id JOIN whatsapp_messages m ON m.id=r.message_id WHERE r.id=?''',(id,)).fetchone()
        if not r: abort(404)
        if request.method=='POST':
            check_csrf()
            if request.form.get('action') == 'pay':
                if request.form.get('verified') != '1': abort(400)
                from payment_flow import record_payment
                try:
                    pid=record_payment(customer_id=int(request.form.get('customer_id','0')),
                        invoice_id=int(request.form.get('invoice_id','0')),
                        amount=request.form.get('amount'),method=request.form.get('method','TRANSFERENCIA'),
                        reference=request.form.get('reference',''),actor=session.get('user') or base.ADMIN_USER,
                        proof='Comprobante WhatsApp #'+str(id),report_id=id)
                except (ValueError,TypeError) as exc:
                    flash(str(exc)); return redirect(url_for('payment_report_detail',id=id))
                flash('Pago registrado y aviso cerrado.')
                return redirect(url_for('payment_receipt',id=pid))
            from datetime import datetime
            c.execute("UPDATE whatsapp_payment_reports SET status='REVISADO',reviewed_at=? WHERE id=? AND status='PENDIENTE'",(datetime.now().isoformat(timespec='seconds'),id))
            c.commit(); flash('Reporte revisado. Esta acción no registra ningún pago.')
            return redirect(url_for('payment_report_detail',id=id))
        customers=c.execute("SELECT id,name FROM customers WHERE COALESCE(status,'')<>'ELIMINADO' ORDER BY name").fetchall()
        selected=r['customer_id'] or request.args.get('customer_id',type=int)
        invoices=c.execute('''SELECT i.*,i.amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0) balance
            FROM invoices i WHERE i.customer_id=? AND i.status='PENDIENTE' ORDER BY i.due_date,i.id''',(selected,)).fetchall() if selected else []
    finally: c.close()
    body=f'<div class="head"><h1>{esc(r["name"] or "Cliente por identificar")}</h1></div><div class="panel"><span class="tag warn">{esc(r["status"])}</span><p>Posible comprobante recibido · {esc(r["phone"])} · {esc(r["created_at"])}</p><p>{esc(r["body"] or "Archivo recibido")}</p><p>Abre el WhatsApp del negocio para ver el archivo original. Comprueba el ingreso en tu banco antes de registrar el pago.</p><a class="btn" href="{url_for("whatsapp_chat",thread=r["thread_id"])}">Abrir conversación</a> '
    if r['customer_id']: body+=f'<a class="btn" href="{url_for("customer_profile",id=r["customer_id"])}">Ficha del cliente</a>'
    else: body+='<p class="notice">El número no identifica a un solo cliente. Confirma el titular antes de registrar el pago.</p>'
    if r['status']=='PENDIENTE':
        if not r['customer_id']:
            body+='<form method="get"><label>Selecciona el cliente <select name="customer_id" required><option value="">Elegir cliente</option>'
            for cu in customers:
                chosen=' selected' if cu['id']==selected else ''
                body+=f'<option value="{cu["id"]}"{chosen}>{esc(cu["name"])}</option>'
            body+='</select></label><button class="btn">Ver facturas pendientes</button></form>'
        payable=[inv for inv in invoices if inv['balance']>0]
        if payable:
            body+=f'<h3>Registrar pago</h3><form method="post"><input type="hidden" name="csrf" value="{csrf()}"><input type="hidden" name="action" value="pay"><input type="hidden" name="customer_id" value="{selected}"><label>Factura <select name="invoice_id" required>'
            for inv in payable:
                body+=f'<option value="{inv["id"]}">Factura #{inv["id"]} · Balance RD${inv["balance"]:,.2f}</option>'
            body+='</select></label><label>Monto RD$ <input name="amount" type="number" min="0.01" step="0.01" required></label><label>Método <select name="method"><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>EFECTIVO</option></select></label><label>Referencia <input name="reference" maxlength="500"></label><label><input type="checkbox" name="verified" value="1" required> Verifiqué el ingreso y los datos del cliente y la factura</label><button class="btn green">Registrar pago y cerrar aviso</button></form>'
        elif selected:
            body+='<p>No hay facturas pendientes para este cliente.</p>'
    body+=f'<form method="post"><input type="hidden" name="csrf" value="{csrf()}"><button class="btn">Marcar reporte revisado</button></form><p class="muted">Marcar revisado solo cierra el aviso; el pago se registra en la factura.</p><a href="{url_for("payment_reports")}">Todos los reportes</a></div>'
    return base.shell('Revisar comprobante',body,'whatsapp_chat')


def setup(app):
    schema()
    app.add_url_rule('/pagos/reportados',endpoint='payment_reports',view_func=reports,methods=['GET','POST'])
    app.add_url_rule('/pagos/reportados/<int:id>',endpoint='payment_report_detail',view_func=detail,methods=['GET','POST'])
    @app.before_request
    def remember_report_login():
        if request.endpoint=='login':
            path=request.args.get('payment_report','')
            import re
            if re.fullmatch(r'/pagos/reportados(?:/[0-9]+)?',path): g.payment_report_return=path
    @app.after_request
    def report_notice(response):
        if request.endpoint=='login' and request.method=='POST' and response.status_code in (302,303) and base.logged_in() and getattr(g,'payment_report_return',None):
            response.headers['Location']=g.payment_report_return
        if response.status_code==200 and response.mimetype=='text/html' and base.logged_in() and (session.get('role') or 'ADMIN').upper() in ('ADMIN','CAJA','COBRADOR'):
            c=base.db()
            try: count=c.execute("SELECT COUNT(*) FROM whatsapp_payment_reports WHERE status='PENDIENTE'").fetchone()[0]
            finally: c.close()
            if count or request.endpoint in ('whatsapp_chat','whatsapp_inbox'):
                notice=f'<a href="{url_for("payment_reports")}" style="position:fixed;bottom:16px;right:16px;z-index:40;background:#634600;color:#fff;padding:12px;border-radius:10px">Comprobantes por revisar: {count}</a>'
                response.set_data(response.get_data(as_text=True).replace('</body>',notice+'</body>'))
                response.headers['Cache-Control']='no-store'
        return response
