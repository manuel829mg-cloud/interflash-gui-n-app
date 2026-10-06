import os, secrets
from datetime import date, datetime
from flask import request, redirect, url_for, flash, session
import app as base
import business_suite as bs


def esc(v):
    return bs.esc(v)


def customer_service_info(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone(); zones=c.execute('SELECT * FROM zones WHERE active=1 ORDER BY name').fetchall()
    if not cu: c.close(); return redirect(url_for('customers'))
    if request.method=='POST':
        zid=request.form.get('zone_id') or None; zname=''; due=int(request.form.get('due_day') or cu['due_day'] or 30)
        if zid:
            z=c.execute('SELECT name,billing_day FROM zones WHERE id=?',(zid,)).fetchone()
            if z: zname=z['name']; due=int(z['billing_day'] or due)
        c.execute('UPDATE customers SET zone_id=?,zone=?,latitude=?,longitude=?,notes=?,router_name=?,due_day=? WHERE id=?',(
            zid,zname or request.form.get('zone'),request.form.get('latitude'),request.form.get('longitude'),request.form.get('notes'),request.form.get('router_name') or 'CCR2116',due,id))
        c.commit(); c.close(); flash('Datos de servicio actualizados.'); return redirect(url_for('customer_profile',id=id))
    opts=''.join('<option value="{}" {}>{}</option>'.format(z['id'],'selected' if str(cu['zone_id'] or '')==str(z['id']) else '',esc(z['name'])) for z in zones); c.close()
    body='''<div class="head"><div><h1>Servicio y ubicación</h1><p>{name}</p></div><a class="btn" href="{back}">← Volver</a></div>
    <form class="panel formgrid" method="post"><label>Zona<select name="zone_id"><option value="">Sin zona</option>{opts}</select></label><label>Router<input name="router_name" value="{router}"></label><label>Latitud<input name="latitude" value="{lat}" placeholder="18.48..."></label><label>Longitud<input name="longitude" value="{lng}" placeholder="-69.93..."></label><label>Día de vencimiento<input type="number" min="1" max="31" name="due_day" value="{due}"></label><label>Zona libre<input name="zone" value="{zone}"></label><label class="full">Notas<textarea name="notes" rows="4">{notes}</textarea></label><div class="full"><button class="btn green">Guardar</button></div></form>'''.format(name=esc(cu['name']),back=url_for('customer_profile',id=id),opts=opts,router=esc(cu['router_name'] or 'CCR2116'),lat=esc(cu['latitude'] or ''),lng=esc(cu['longitude'] or ''),due=int(cu['due_day'] or 30),zone=esc(cu['zone'] or ''),notes=esc(cu['notes'] or ''))
    return base.shell('Servicio',body,'customers')


def payments_full():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        cid=int(request.form['customer_id']); inv_id=request.form.get('invoice_id') or None; amount=float(request.form.get('amount') or 0); now=datetime.now().isoformat(timespec='seconds')
        c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,reference,paid_at,received_by,proof) VALUES(?,?,?,?,?,?,?,?)',(cid,inv_id,amount,request.form.get('method','EFECTIVO'),request.form.get('reference'),now,session.get('user') or base.ADMIN_USER,request.form.get('proof')))
        if inv_id:
            inv=c.execute('SELECT amount FROM invoices WHERE id=?',(inv_id,)).fetchone(); total=c.execute('SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?',(inv_id,)).fetchone()['s']
            if inv and total>=float(inv['amount']): c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,inv_id))
        cu=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone(); c.commit(); c.close()
        if bs.setting('whatsapp_enabled','0')=='1':
            try:
                import whatsapp_suite as wa
                wa.queue_event(cid,'PAYMENT',{'amount':'RD'+'
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
            try:
                import whatsapp_suite as wa
                wa.queue_event(cid,'RECONNECT',{})
            except Exception: pass
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1':
        try:
            import whatsapp_suite as wa
            wa.queue_event(inv['customer_id'],'PAYMENT',{'amount':'RD'+'
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        try:
            import whatsapp_suite as wa
            wa.queue_event(cu['id'],'RECONNECT',{})
        except Exception: pass
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1':
        try:
            import whatsapp_suite as wa
            sent=wa.process_legacy_outbox(100)
        except Exception:
            sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(amount)})
            except Exception:
                bs.queue_whatsapp(cid,'PAYMENT',{'amount':'RD'+'
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1': bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD${:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(amount)})
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1': bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD${:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(inv['amount'])})
        except Exception:
            bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD'+'
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(amount)})
            except Exception:
                bs.queue_whatsapp(cid,'PAYMENT',{'amount':'RD'+'
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1': bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD${:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(amount)})
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1': bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD${:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(amount)})
            except Exception:
                bs.queue_whatsapp(cid,'PAYMENT',{'amount':'RD'+'
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1': bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD${:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
+'{:,.2f}'.format(amount)})
        if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
            c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cid,cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
        flash('Pago registrado.'); return redirect(url_for('payments'))
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); invoices=c.execute("SELECT i.id,i.customer_id,i.amount,i.due_date,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.status='PENDIENTE' ORDER BY i.id DESC").fetchall(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC LIMIT 200''').fetchall(); c.close()
    copts=''.join('<option value="{}">{}</option>'.format(x['id'],esc(x['name'])) for x in customers); iopts=''.join('<option value="{}">#{} · {} · RD${:,.2f}</option>'.format(x['id'],x['id'],esc(x['customer']),x['amount']) for x in invoices); trs=''.join('<tr><td>#{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['id'],esc(r['customer']),r['amount'],esc(r['method']),esc(r['reference'] or '-'),esc(r['paid_at'])) for r in rows)
    body='''<div class="head"><div><h1>Pagos</h1><p>Recibos, transferencias y conciliación manual</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{copts}</select><select class="field" name="invoice_id"><option value="">Sin factura específica</option>{iopts}</select><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><select class="field" name="method"><option>EFECTIVO</option><option>TRANSFERENCIA</option><option>DEPOSITO</option><option>TARJETA</option><option>OTRO</option></select><input class="field" name="reference" placeholder="Referencia"><input class="field" name="proof" placeholder="Comprobante / nota"><button class="btn green">Registrar pago</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{rows}</table></div>'''.format(copts=copts,iopts=iopts,rows=trs or '<tr><td colspan=6 class=muted>Sin pagos.</td></tr>')
    return base.shell('Pagos',body,'payments')


def expenses_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO expenses(concept,category,amount,paid_at,notes) VALUES(?,?,?,?,?)',(request.form['concept'],request.form.get('category'),float(request.form.get('amount') or 0),request.form.get('paid_at') or date.today().isoformat(),request.form.get('notes'))); c.commit(); flash('Gasto registrado.')
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 200').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>RD${:,.2f}</td><td>{}</td></tr>'.format(esc(r['paid_at']),esc(r['concept']),esc(r['category'] or '-'),r['amount'],esc(r['notes'] or '')) for r in rows)
    body='''<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="concept" placeholder="Concepto" required><input class="field" name="category" placeholder="Categoría"><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="paid_at" value="{today}"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Registrar</button></form><table class="table"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{rows}</table></div>'''.format(today=date.today().isoformat(),rows=trs or '<tr><td colspan=5 class=muted>Sin gastos.</td></tr>')
    return base.shell('Gastos',body,'expenses_page')


def banks_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO bank_accounts(bank,account_type,account_number,label,active) VALUES(?,?,?,?,1)',(request.form['bank'],request.form.get('account_type'),request.form['account_number'],request.form.get('label'))); c.commit(); flash('Cuenta bancaria guardada.')
    rows=c.execute('SELECT * FROM bank_accounts ORDER BY id DESC').fetchall(); c.close(); trs=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(esc(r['bank']),esc(r['account_type'] or '-'),esc(r['account_number']),esc(r['label'] or '-')) for r in rows)
    body='''<div class="head"><div><h1>Cuentas bancarias</h1><p>Cuentas para recibir pagos</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="bank" placeholder="Banco" required><input class="field" name="account_type" placeholder="Tipo de cuenta"><input class="field" name="account_number" placeholder="Número de cuenta" required><input class="field" name="label" placeholder="Titular / etiqueta"><button class="btn green">Guardar</button></form><table class="table"><tr><th>Banco</th><th>Tipo</th><th>Cuenta</th><th>Etiqueta</th></tr>{rows}</table></div>'''.format(rows=trs or '<tr><td colspan=4 class=muted>Sin cuentas.</td></tr>')
    return base.shell('Bancos',body,'banks_page')


def invoice_pay_full(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone(); cu=None
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at,received_by) VALUES(?,?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now,session.get('user') or base.ADMIN_USER)); cu=c.execute('SELECT * FROM customers WHERE id=?',(inv['customer_id'],)).fetchone(); c.commit()
    c.close()
    if inv and inv['status']!='PAGADA' and bs.setting('whatsapp_enabled','0')=='1': bs.queue_whatsapp(inv['customer_id'],'PAYMENT',{'amount':'RD${:,.2f}'.format(inv['amount'])})
    if cu and cu['status']=='SUSPENDIDO' and bs.setting('auto_reactivate','0')=='1' and cu['pppoe']:
        c=base.db(); c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'REACTIVATE','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'PAGO')); c.commit(); c.close()
    return redirect(url_for('invoices'))


def cron_daily():
    supplied=request.headers.get('X-InterFlash-Cron',''); token=os.getenv('BILLING_CRON_TOKEN','')
    if not token or not secrets.compare_digest(supplied,token): return {'ok':False},401
    if bs.setting('billing_enabled','1')!='1': return {'ok':True,'skipped':'billing-disabled'}
    created,overdue,commands=bs.run_billing(); sent=0
    if bs.setting('whatsapp_enabled','0')=='1': sent,_=bs.try_send_outbox(100)
    return {'ok':True,'created':created,'overdue':overdue,'commands':commands,'whatsapp_sent':sent}


def role_guard():
    if not base.logged_in(): return None
    role=session.get('role','ADMIN')
    if role=='ADMIN': return None
    sensitive={'users_page','settings_page','backup_download','automation_page','zones_page','expenses_page','banks_page','mikrotik_commands','mikrotik_control_script','queue_customer_command'}
    if request.endpoint in sensitive:
        flash('Tu usuario no tiene permiso para esa sección.'); return redirect(url_for('dashboard'))
    return None


def setup(app):
    if not any(x[0]=='expenses_page' for x in base.NAV): base.NAV.append(('expenses_page','−','Gastos'))
    if not any(x[0]=='banks_page' for x in base.NAV): base.NAV.append(('banks_page','🏦','Bancos'))
    app.view_functions['payments']=payments_full; app.view_functions['invoice_pay']=invoice_pay_full
    app.before_request(role_guard)
    app.add_url_rule('/customers/<int:id>/service',endpoint='customer_service_info',view_func=customer_service_info,methods=['GET','POST'])
    app.add_url_rule('/expenses',endpoint='expenses_page',view_func=expenses_page,methods=['GET','POST'])
    app.add_url_rule('/banks',endpoint='banks_page',view_func=banks_page,methods=['GET','POST'])
    app.add_url_rule('/api/cron/daily',endpoint='cron_daily',view_func=cron_daily,methods=['POST'])
