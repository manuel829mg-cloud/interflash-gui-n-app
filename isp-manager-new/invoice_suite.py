import secrets
from datetime import date, datetime
from html import escape
from flask import request, redirect, url_for, flash, render_template_string, session
import app as base
import business_suite as bs

def esc(v): return escape('' if v is None else str(v))

def invoices_plus():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        cid=int(request.form['customer_id'])
        cu=c.execute("""SELECT cu.*,p.name plan_name,p.price plan_price,p.download_mbps,p.upload_mbps
                        FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id WHERE cu.id=?""",(cid,)).fetchone()
        if not cu:
            c.close(); flash('Cliente no encontrado.'); return redirect(url_for('invoices'))
        amount=float(request.form.get('amount') or cu['plan_price'] or 0)
        period=(request.form.get('period') or date.today().strftime('%Y-%m')).strip()
        concept=(request.form.get('concept') or ('Servicio de Internet '+period)).strip()
        speed=(str(cu['download_mbps'] or 0)+'/'+str(cu['upload_mbps'] or 0)+' Mbps') if cu['plan_name'] else ''
        c.execute("""INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date,status,period,generated_by,plan_name,plan_speed)
                     VALUES(?,?,?,?,?,'PENDIENTE',?,?,?,?)""",
                  (cid,concept,amount,request.form['issue_date'],request.form['due_date'],period,
                   session.get('user') or base.ADMIN_USER,cu['plan_name'] or '',speed))
        iid=c.execute('SELECT last_insert_rowid() id').fetchone()['id']
        c.commit(); c.close()
        try: base.audit('INVOICE_CREATE',f'#{iid} cliente {cid}')
        except Exception: pass
        flash('Factura creada.'); return redirect(url_for('invoice_detail',id=iid))
    customers=c.execute("""SELECT cu.id,cu.name,cu.code,cu.phone,cu.pppoe,p.name plan_name,p.price FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id
                           WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' ORDER BY cu.name""").fetchall()
    rows=c.execute("""SELECT i.*,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id ORDER BY i.id DESC LIMIT 500""").fetchall()
    c.close()
    today=date.today().isoformat(); period=date.today().strftime('%Y-%m')
    selected_id=request.args.get('customer_id',type=int)
    selected_customer=next((x for x in customers if x['id']==selected_id),None)
    selected_amount=f"{float(selected_customer['price'] or 0):.2f}" if selected_customer else ''
    selected_notice=('Cliente seleccionado: '+selected_customer['name']) if selected_customer else ''
    opts=''.join(f'<option value="{x["id"]}" {'selected' if selected_customer and x["id"]==selected_customer["id"] else ''} data-search="{esc(str(x["name"] or "")+" "+str(x["code"] or "")+" "+str(x["phone"] or "")+" "+str(x["pppoe"] or ""))}" data-price="{float(x["price"] or 0):.2f}">{esc(x["name"])} · {esc(x["code"] or x["id"])} · {esc(x["plan_name"] or "Sin plan")} · RD&#36;{float(x["price"] or 0):,.0f}</option>' for x in customers)
    trs=[]
    for r in rows:
        paid=(r['status'] or '').upper()=='PAGADA'; cancelled=r['status']=='ANULADA'; overdue=(not paid and not cancelled and (r['due_date'] or '') < today)
        status='VENCIDA' if overdue else (r['status'] or 'PENDIENTE'); cls='bad' if overdue else 'ok' if paid else 'warn'
        collect='' if paid or cancelled else f'<a class="btn green" href="{url_for("invoice_detail",id=r["id"])}#registrar-pago">Cobrar</a>'
        trs.append(f'<tr><td><b>IF-{r["id"]:06d}</b></td><td>{esc(r["customer"])}</td><td>{esc(r["period"] or "-")}</td><td>{esc(r["concept"])}</td><td>RD&#36;{float(r["amount"]):,.2f}</td><td>{esc(r["issue_date"])}</td><td>{esc(r["due_date"])}</td><td><span class="tag {cls}">{esc(status)}</span></td><td style="white-space:nowrap"><a class="btn blue" href="{url_for("invoice_detail",id=r["id"])}">Ver</a> {collect}</td></tr>')
    body=f'''<div class="head"><div><h1>Facturas</h1><p>Facturación, impresión, cobros y comprobantes</p></div></div>
    <div class="panel" id="nueva-factura"><h3>Nueva factura</h3><form class="toolbar" method="post">
    <div class="invoice-client-picker" style="flex:1 1 100%;min-width:0">
    <label for="invoice-client-search">Buscar cliente</label>
    <input class="field" id="invoice-client-search" type="search" placeholder="Nombre, código, teléfono o PPPoE…" autocomplete="off" aria-controls="invoice-customer" style="width:100%;margin:6px 0">
    <select class="field" id="invoice-customer" name="customer_id" required aria-label="Seleccionar cliente" style="width:100%" onchange="var o=this.options[this.selectedIndex];document.getElementById('invoice-amount').value=o.dataset.price||''"><option value="">Selecciona un cliente</option>{opts}</select>
    <small id="invoice-client-results" role="status" aria-live="polite">{esc(selected_notice)}</small>
    </div>
    <input class="field" name="concept" value="Servicio de Internet" required><input class="field" id="invoice-amount" value="{esc(selected_amount)}" type="number" step="0.01" name="amount" placeholder="Monto" required>
    <input class="field" type="month" name="period" value="{period}" required><input class="field" type="date" name="issue_date" value="{today}" required><input class="field" type="date" name="due_date" value="{today}" required>
    <button class="btn green">Crear factura</button></form></div>
    <div class="panel"><table class="table"><tr><th>Factura</th><th>Cliente</th><th>Período</th><th>Concepto</th><th>Monto</th><th>Emisión</th><th>Vence</th><th>Estado</th><th>Acciones</th></tr>{''.join(trs) or '<tr><td colspan="9" class="muted">No hay facturas.</td></tr>'}</table></div>'''
    body += "\n    <script>\n    (() => {\n      const search = document.getElementById('invoice-client-search');\n      const select = document.getElementById('invoice-customer');\n      const status = document.getElementById('invoice-client-results');\n      const amount = document.getElementById('invoice-amount');\n      const options = Array.from(select.options).slice(1);\n      const normalize = value => value.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().trim();\n      search.addEventListener('input', () => {\n        const query = normalize(search.value);\n        const terms = query.split(/\\s+/).filter(Boolean);\n        const selected = select.value;\n        const matches = options.filter(option => terms.every(term => normalize(option.dataset.search).includes(term)));\n        select.replaceChildren(new Option(matches.length ? 'Selecciona un cliente' : 'No se encontraron clientes', ''), ...matches);\n        if (selected && matches.some(option => option.value === selected)) select.value = selected;\n        else { select.value = ''; if (selected) amount.value = ''; }\n        select.size = query ? Math.min(6, matches.length + 1) : 1;\n        status.textContent = query ? matches.length + ' cliente(s) encontrado(s). Selecciona uno de la lista.' : '';\n      });\n      select.addEventListener('change', () => {\n        if (select.value) {\n          select.size = 1;\n          status.textContent = 'Cliente seleccionado: ' + select.selectedOptions[0].textContent;\n        }\n      });\n    })();\n    </script>\n"
    return base.shell('Facturas',body,'invoices')

def invoice_detail(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    inv=c.execute("""SELECT i.*,cu.name customer,cu.code customer_code,cu.phone,cu.document,cu.email,cu.address,cu.pppoe,
                     p.name current_plan,p.download_mbps,p.upload_mbps FROM invoices i JOIN customers cu ON cu.id=i.customer_id
                     LEFT JOIN plans p ON p.id=cu.plan_id WHERE i.id=?""",(id,)).fetchone()
    if not inv:
        c.close(); flash('Factura no encontrada.'); return redirect(url_for('invoices'))
    payments=c.execute('SELECT * FROM payments WHERE invoice_id=? ORDER BY id',(id,)).fetchall()
    cancellation=c.execute('SELECT * FROM invoice_cancellations WHERE invoice_id=?',(id,)).fetchone()
    banks=c.execute('SELECT * FROM bank_accounts WHERE active=1 ORDER BY id').fetchall(); c.close()
    company={'name':bs.setting('business_name','INTER Flash'),'rnc':bs.setting('business_rnc',''),'phone':bs.setting('business_phone',''),
             'email':bs.setting('business_email',''),'address':bs.setting('business_address',''),'footer':bs.setting('billing_footer','Gracias por preferir INTER Flash.')}
    paid_total=sum(float(x['amount'] or 0) for x in payments); balance=max(0,float(inv['amount'] or 0)-paid_total)
    is_paid=(inv['status'] or '').upper()=='PAGADA' or balance<=0; overdue=(not is_paid and (inv['due_date'] or '') < date.today().isoformat())
    status='ANULADA' if inv['status']=='ANULADA' else 'PAGADA' if is_paid else 'VENCIDA' if overdue else 'PENDIENTE'
    if status=='ANULADA': balance=0
    can_cancel=inv['status']=='PENDIENTE' and not payments and (session.get('role') or 'ADMIN').upper()=='ADMIN'
    void_csrf=session.setdefault('invoice_void_csrf',secrets.token_urlsafe(32))
    plan=inv['plan_name'] or inv['current_plan'] or '-'
    speed=inv['plan_speed'] or ((str(inv['download_mbps'] or 0)+'/'+str(inv['upload_mbps'] or 0)+' Mbps') if inv['current_plan'] else '-')
    pay_rows=''.join(f'<tr><td>{esc((p["paid_at"] or "")[:19])}</td><td>{esc(p["method"] or "-")}</td><td>{esc(p["reference"] or "-")}</td><td>RD&#36;{float(p["amount"] or 0):,.2f}</td><td class="no-print"><a class="btn" href="{url_for("payment_receipt",id=p["id"])}">Ver recibo</a></td></tr>' for p in payments)
    bank_html=''.join(f'<div><b>{esc(b["bank"])}</b> · {esc(b["account_type"] or "")} · {esc(b["account_number"])} {("· "+esc(b["label"])) if b["label"] else ""}</div>' for b in banks)
    html='''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Factura {{number}} · {{company.name}}</title><style>
    *{box-sizing:border-box}body{margin:0;background:#eef2f7;color:#172033;font-family:Arial,sans-serif}.actions{max-width:900px;margin:18px auto;display:flex;gap:8px}.btn{border:0;border-radius:8px;padding:10px 14px;background:#132336;color:white;text-decoration:none;font-weight:700;cursor:pointer}.blue{background:#0d63f6}.sheet{max-width:900px;margin:0 auto 30px;background:white;padding:42px;box-shadow:0 8px 35px #0002}.top{display:flex;justify-content:space-between;gap:30px;border-bottom:3px solid #0d63f6;padding-bottom:20px}.brand{font-size:28px;font-weight:900;color:#0d63f6}.muted{color:#65758b}.right{text-align:right}.status{display:inline-block;padding:7px 12px;border-radius:999px;font-weight:800;background:{{status_bg}};color:{{status_fg}}}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:24px 0}.box{border:1px solid #dbe3ec;border-radius:10px;padding:15px}.box h3{margin:0 0 10px;font-size:13px;text-transform:uppercase;color:#65758b}.line{margin:5px 0}.table{width:100%;border-collapse:collapse;margin-top:18px}.table th,.table td{padding:11px;border-bottom:1px solid #dbe3ec;text-align:left}.table th{font-size:12px;color:#65758b}.totals{margin:20px 0 0 auto;width:min(360px,100%)}.totals div{display:flex;justify-content:space-between;padding:7px 0}.grand{font-size:20px;font-weight:900;border-top:2px solid #172033}.footer{text-align:center;color:#65758b;margin-top:35px;padding-top:18px;border-top:1px solid #dbe3ec}.banks{font-size:13px;line-height:1.6}.paidstamp{font-size:12px;color:#147a4b;font-weight:800}@media(max-width:650px){.sheet{padding:22px}.grid,.top{grid-template-columns:1fr;display:grid}.right{text-align:left}}@media print{body{background:white}.actions{display:none}.sheet{box-shadow:none;margin:0;max-width:none;padding:18mm}@page{size:A4;margin:0}}</style></head><body>
    <div class="actions"><a class="btn" href="{{back}}">← Facturas</a><button class="btn blue" onclick="window.print()">Imprimir / Guardar PDF</button></div>
    <main class="sheet">{% for message in get_flashed_messages() %}<p role="status">{{message}}</p>{% endfor %}
    {% if cancellation %}<div class="box"><b>FACTURA ANULADA</b><p>Motivo: {{cancellation.reason}}</p><p>Por {{cancellation.actor}} · {{cancellation.created_at}}</p><p>Este documento se conserva como historial y no genera deuda.</p></div>{% endif %}
    <div class="top"><div><div class="brand">{{company.name}}</div><div class="muted">{{company.address}}</div><div class="muted">{{company.phone}}{% if company.email %} · {{company.email}}{% endif %}</div>{% if company.rnc %}<div class="muted">RNC: {{company.rnc}}</div>{% endif %}</div>
    <div class="right"><h1 style="margin:0">FACTURA</h1><div><b>{{number}}</b></div><div style="margin-top:10px"><span class="status">{{status}}</span></div></div></div>
    <div class="grid"><div class="box"><h3>Facturado a</h3><div class="line"><b>{{inv.customer}}</b></div><div class="line">{{inv.customer_code or ''}}</div>{% if inv.document %}<div class="line">Cédula/RNC: {{inv.document}}</div>{% endif %}<div class="line">{{inv.phone or ''}}</div><div class="line">{{inv.email or ''}}</div><div class="line">{{inv.address or ''}}</div></div>
    <div class="box"><h3>Datos de factura</h3><div class="line"><b>Emisión:</b> {{inv.issue_date}}</div><div class="line"><b>Vencimiento:</b> {{inv.due_date}}</div><div class="line"><b>Período:</b> {{inv.period or '-'}}</div><div class="line"><b>Generada por:</b> {{inv.generated_by or '-'}}</div></div></div>
    <table class="table"><tr><th>Descripción</th><th>Plan</th><th>Velocidad</th><th style="text-align:right">Monto</th></tr><tr><td>{{inv.concept}}</td><td>{{plan}}</td><td>{{speed}}</td><td style="text-align:right">RD&#36;{{amount}}</td></tr></table>
    <div class="totals"><div><span>Total</span><b>RD&#36;{{amount}}</b></div><div><span>Pagado</span><span>RD&#36;{{paid_total}}</span></div><div class="grand"><span>Balance</span><span>RD&#36;{{balance}}</span></div></div>
    {% if status in ('PENDIENTE','VENCIDA') %}<div class="box no-print" id="registrar-pago" style="margin-top:24px"><h3>Registrar pago</h3>
    <form method="post" action="{{pay_url}}" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
    <label>Monto<input name="amount" type="number" min="0.01" max="{{balance_raw}}" step="0.01" value="{{balance_raw}}" required style="width:100%;padding:10px;margin-top:5px"></label>
    <label>Método<select name="method" required style="width:100%;padding:10px;margin-top:5px"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPÓSITO</option><option>TARJETA</option><option>CHEQUE</option><option>OTRO</option></select></label>
    <label style="grid-column:1/-1">Referencia / comprobante<input name="reference" placeholder="Opcional en efectivo" style="width:100%;padding:10px;margin-top:5px"></label>
    <div style="grid-column:1/-1"><button class="btn blue">Registrar pago</button></div></form></div>{% endif %}
    {% if can_cancel %}<div class="box no-print" style="margin-top:24px"><h3>Anular factura</h3><p>Úsalo si esta factura se creó por error. Se conservará en el historial y dejará de contar como deuda.</p><form method="post" action="{{cancel_url}}" onsubmit="return confirm('¿Anular esta factura? Dejará de contar como deuda y quedará en el historial como ANULADA.')"><input type="hidden" name="csrf" value="{{void_csrf}}"><label>Motivo de anulación<textarea name="reason" minlength="5" maxlength="500" required placeholder="Ejemplo: factura duplicada" style="display:block;width:100%;padding:10px;margin:8px 0"></textarea></label><button class="btn" style="background:#b4232f">Anular factura</button></form></div>{% endif %}
    {% if pay_rows %}<div class="box" style="margin-top:24px"><h3>Pagos registrados</h3><table class="table"><tr><th>Fecha</th><th>Método</th><th>Referencia</th><th>Monto</th><th class="no-print">Recibo</th></tr>{{pay_rows|safe}}</table>{% if status=='PAGADA' %}<div class="paidstamp">✓ Factura pagada</div>{% endif %}</div>{% endif %}
    {% if bank_html %}<div class="box banks" style="margin-top:20px"><h3>Cuentas para pago</h3>{{bank_html|safe}}</div>{% endif %}<div class="footer">{{company.footer}}</div></main></body></html>'''
    bg='#dff7e9' if status=='PAGADA' else '#ffe5e7' if status=='VENCIDA' else '#fff2cc'; fg='#147a4b' if status=='PAGADA' else '#b4232f' if status=='VENCIDA' else '#8a5a00'
    return render_template_string(html,inv=inv,cancellation=cancellation,can_cancel=can_cancel,void_csrf=void_csrf,cancel_url=url_for('invoice_cancel',id=id),company=company,number=f'IF-{id:06d}',status=status,status_bg=bg,status_fg=fg,
      amount=f'{float(inv["amount"] or 0):,.2f}',paid_total=f'{paid_total:,.2f}',balance=f'{balance:,.2f}',balance_raw=f'{balance:.2f}',plan=plan,speed=speed,pay_rows=pay_rows,bank_html=bank_html,back=url_for('invoices'),pay_url=url_for('invoice_payment',id=id))


def invoice_payment(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone()
    if not inv:
        c.close(); flash('Factura no encontrada.'); return redirect(url_for('invoices'))
    paid=float(c.execute('SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?',(id,)).fetchone()['s'] or 0)
    balance=max(0,float(inv['amount'] or 0)-paid)
    try: amount=float(request.form.get('amount') or 0)
    except ValueError: amount=0
    if amount<=0 or amount>balance+0.001:
        c.close(); flash('El monto del pago no es válido.'); return redirect(url_for('invoice_detail',id=id))
    method=(request.form.get('method') or 'EFECTIVO').strip().upper()
    allowed={'EFECTIVO','TRANSFERENCIA','DEPÓSITO','TARJETA','CHEQUE','OTRO'}
    if method not in allowed: method='OTRO'
    reference=(request.form.get('reference') or '').strip()
    now=datetime.now().isoformat(timespec='seconds')
    c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,reference,paid_at) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,amount,method,reference,now))
    pid=c.execute('SELECT last_insert_rowid() id').fetchone()['id']
    new_paid=paid+amount
    if new_paid+0.001>=float(inv['amount'] or 0):
        c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id))
    else:
        c.execute("UPDATE invoices SET status='PENDIENTE',paid_at=NULL WHERE id=?",(id,))
    c.commit(); c.close()
    try: base.audit('PAYMENT_CREATE',f'Pago #{pid} factura #{id} RD$ {amount:.2f} {method}')
    except Exception: pass
    flash('Pago registrado correctamente.')
    return redirect(url_for('payment_receipt',id=pid))

def payment_receipt(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    p=c.execute("""SELECT p.*,i.concept,i.period,i.amount invoice_amount,cu.name customer,cu.code customer_code,cu.document,cu.phone
                   FROM payments p LEFT JOIN invoices i ON i.id=p.invoice_id JOIN customers cu ON cu.id=p.customer_id WHERE p.id=?""",(id,)).fetchone()
    if not p:
        c.close(); flash('Recibo no encontrado.'); return redirect(url_for('payments'))
    total_paid=float(c.execute('SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?',(p['invoice_id'],)).fetchone()['s'] or 0) if p['invoice_id'] else float(p['amount'] or 0)
    c.close()
    company={'name':bs.setting('business_name','INTER Flash'),'rnc':bs.setting('business_rnc',''),'phone':bs.setting('business_phone',''),'address':bs.setting('business_address','')}
    balance=max(0,float(p['invoice_amount'] or p['amount'] or 0)-total_paid)
    html="""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Recibo {{number}}</title>
    <style>body{font-family:Arial;background:#eef2f7;color:#172033;margin:0}.actions,.sheet{max-width:720px;margin:18px auto}.sheet{background:white;padding:38px;box-shadow:0 8px 30px #0002}.actions{display:flex;gap:8px}.btn{background:#132336;color:white;padding:10px 14px;border:0;border-radius:8px;text-decoration:none;font-weight:700;cursor:pointer}.blue{background:#0d63f6}.head{display:flex;justify-content:space-between;border-bottom:3px solid #0d63f6;padding-bottom:18px}.brand{font-size:26px;font-weight:900;color:#0d63f6}.box{border:1px solid #dbe3ec;border-radius:10px;padding:15px;margin-top:20px}.row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #eef2f7}.amount{font-size:28px;font-weight:900;color:#147a4b}.footer{text-align:center;color:#65758b;margin-top:28px}@media print{body{background:white}.actions{display:none}.sheet{box-shadow:none;margin:0;max-width:none}@page{size:A4;margin:15mm}}</style></head><body>
    <div class="actions"><a class="btn" href="{{invoice_url}}">← Factura</a><button class="btn blue" onclick="window.print()">Imprimir / Guardar PDF</button></div>
    <main class="sheet"><div class="head"><div><div class="brand">{{company.name}}</div><div>{{company.address}}</div><div>{{company.phone}}</div>{% if company.rnc %}<div>RNC: {{company.rnc}}</div>{% endif %}</div><div style="text-align:right"><h2 style="margin:0">RECIBO DE PAGO</h2><b>{{number}}</b></div></div>
    <div class="box"><div class="row"><span>Cliente</span><b>{{p.customer}}</b></div><div class="row"><span>Factura</span><b>IF-{{'%06d'|format(p.invoice_id) if p.invoice_id else '-'}}</b></div><div class="row"><span>Fecha</span><b>{{p.paid_at}}</b></div><div class="row"><span>Método</span><b>{{p.method}}</b></div><div class="row"><span>Referencia</span><b>{{p.reference or '-'}}</b></div><div class="row"><span>Período</span><b>{{p.period or '-'}}</b></div><div class="row"><span>Pago recibido</span><span class="amount">RD&#36;{{payment}}</span></div><div class="row"><span>Balance restante</span><b>RD&#36;{{balance}}</b></div></div>
    <div class="footer">Pago recibido. Gracias por preferir {{company.name}}.</div></main></body></html>"""
    return render_template_string(html,p=p,company=company,number=f'RC-{id:06d}',payment=f'{float(p["amount"] or 0):,.2f}',balance=f'{balance:,.2f}',invoice_url=url_for('invoice_detail',id=p['invoice_id']) if p['invoice_id'] else url_for('payments'))

def setup(app):
    app.view_functions['invoices']=invoices_plus
    app.add_url_rule('/invoices/<int:id>',endpoint='invoice_detail',view_func=invoice_detail,methods=['GET'])
    app.add_url_rule('/invoices/<int:id>/payment',endpoint='invoice_payment',view_func=invoice_payment,methods=['POST'])
    app.add_url_rule('/payments/<int:id>/receipt',endpoint='payment_receipt',view_func=payment_receipt,methods=['GET'])
