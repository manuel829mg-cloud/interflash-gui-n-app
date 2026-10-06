from datetime import datetime
from flask import request, redirect, url_for, flash
import os
import app as base
import business_suite as bs


def esc(v): return bs.esc(v)


def zones_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO zones(name,billing_day,invoice_days_before,cut_days_after,cut_time) VALUES(?,?,?,?,?)',(request.form['name'],int(request.form.get('billing_day') or 30),int(request.form.get('invoice_days_before') or 5),int(request.form.get('cut_days_after') or 6),request.form.get('cut_time') or '14:00')); c.commit(); flash('Zona creada.')
    rows=c.execute('SELECT * FROM zones ORDER BY name').fetchall(); c.close(); trs=''.join(f'<tr><td>{esc(r["name"])}</td><td>{r["billing_day"]}</td><td>{r["invoice_days_before"]} días antes</td><td>{r["cut_days_after"]} días después</td><td>{esc(r["cut_time"])}</td></tr>' for r in rows)
    return base.shell('Zonas',f'''<div class="head"><div><h1>Zonas</h1><p>Facturación y corte por zona</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="name" placeholder="Nombre" required><input class="field" type="number" name="billing_day" value="30"><input class="field" type="number" name="invoice_days_before" value="5"><input class="field" type="number" name="cut_days_after" value="6"><input class="field" type="time" name="cut_time" value="14:00"><button class="btn green">Crear zona</button></form><table class="table"><tr><th>Zona</th><th>Vence</th><th>Factura</th><th>Corte</th><th>Hora</th></tr>{trs or '<tr><td colspan=5 class=muted>Sin zonas.</td></tr>'}</table></div>''','zones_page')


def onu_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO onu_devices(customer_id,vendor,model,serial,mac,olt,pon_port,rx_power,tx_power,status,last_seen,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(request.form.get('customer_id') or None,request.form.get('vendor'),request.form.get('model'),request.form.get('serial'),request.form.get('mac'),request.form.get('olt'),request.form.get('pon_port'),request.form.get('rx_power'),request.form.get('tx_power'),request.form.get('status','ACTIVO'),datetime.now().isoformat(timespec='seconds'),request.form.get('notes'))); c.commit(); flash('ONU guardada.')
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); rows=c.execute('''SELECT o.*,cu.name customer FROM onu_devices o LEFT JOIN customers cu ON cu.id=o.customer_id ORDER BY o.id DESC''').fetchall(); c.close(); opts=''.join(f'<option value="{x["id"]}">{esc(x["name"])}</option>' for x in customers); trs=''.join(f'<tr><td>{esc(r["customer"] or "-")}</td><td>{esc(r["vendor"])} {esc(r["model"])}</td><td>{esc(r["serial"])}</td><td>{esc(r["olt"])} / {esc(r["pon_port"])}</td><td>{esc(r["rx_power"] or "-")}</td><td>{esc(r["status"])}</td></tr>' for r in rows)
    return base.shell('OLT / ONU',f'''<div class="head"><div><h1>OLT / ONU</h1><p>Inventario, PON y potencia óptica</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id"><option value="">Cliente</option>{opts}</select><input class="field" name="vendor" placeholder="Marca"><input class="field" name="model" placeholder="Modelo"><input class="field" name="serial" placeholder="Serial"><input class="field" name="mac" placeholder="MAC"><input class="field" name="olt" placeholder="OLT"><input class="field" name="pon_port" placeholder="PON"><input class="field" name="rx_power" placeholder="RX dBm"><button class="btn green">Guardar ONU</button></form><table class="table"><tr><th>Cliente</th><th>Equipo</th><th>Serial</th><th>OLT/PON</th><th>RX</th><th>Estado</th></tr>{trs or '<tr><td colspan=6 class=muted>Sin ONUs.</td></tr>'}</table></div>''','onu_page')


def tickets_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST':
        c.execute('INSERT INTO support_tickets(customer_id,subject,priority,status,assigned_to,opened_at,notes) VALUES(?,?,?,?,?,?,?)',(request.form.get('customer_id') or None,request.form.get('subject'),request.form.get('priority','MEDIA'),'ABIERTO',request.form.get('assigned_to'),datetime.now().isoformat(timespec='seconds'),request.form.get('notes'))); c.commit(); flash('Ticket creado.')
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); rows=c.execute('''SELECT t.*,cu.name customer FROM support_tickets t LEFT JOIN customers cu ON cu.id=t.customer_id ORDER BY t.id DESC''').fetchall(); c.close(); opts=''.join(f'<option value="{x["id"]}">{esc(x["name"])}</option>' for x in customers); trs=''.join(f'<tr><td>#{r["id"]}</td><td>{esc(r["customer"] or "-")}</td><td>{esc(r["subject"])}</td><td>{esc(r["priority"])}</td><td>{esc(r["status"])}</td><td>{esc(r["assigned_to"] or "-")}</td></tr>' for r in rows)
    return base.shell('Soporte',f'''<div class="head"><div><h1>Soporte</h1><p>Tickets, averías y técnicos</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id"><option value="">Cliente</option>{opts}</select><input class="field" name="subject" placeholder="Asunto" required><select class="field" name="priority"><option>BAJA</option><option selected>MEDIA</option><option>ALTA</option><option>URGENTE</option></select><input class="field" name="assigned_to" placeholder="Técnico"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Crear ticket</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Asunto</th><th>Prioridad</th><th>Estado</th><th>Asignado</th></tr>{trs or '<tr><td colspan=6 class=muted>Sin tickets.</td></tr>'}</table></div>''','tickets_page')


def installations_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST': c.execute('INSERT INTO installations(customer_id,scheduled_at,status,technician,notes) VALUES(?,?,?,?,?)',(request.form.get('customer_id') or None,request.form.get('scheduled_at'),request.form.get('status','PENDIENTE'),request.form.get('technician'),request.form.get('notes'))); c.commit(); flash('Instalación guardada.')
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall(); rows=c.execute('''SELECT i.*,cu.name customer FROM installations i LEFT JOIN customers cu ON cu.id=i.customer_id ORDER BY i.id DESC''').fetchall(); c.close(); opts=''.join(f'<option value="{x["id"]}">{esc(x["name"])}</option>' for x in customers); trs=''.join(f'<tr><td>{esc(r["scheduled_at"] or "-")}</td><td>{esc(r["customer"] or "-")}</td><td>{esc(r["technician"] or "-")}</td><td>{esc(r["status"])}</td><td>{esc(r["notes"] or "")}</td></tr>' for r in rows)
    return base.shell('Instalaciones',f'''<div class="head"><div><h1>Instalaciones</h1><p>Agenda y trabajo de campo</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id"><option value="">Cliente</option>{opts}</select><input class="field" type="datetime-local" name="scheduled_at"><input class="field" name="technician" placeholder="Técnico"><input class="field" name="notes" placeholder="Notas"><button class="btn green">Programar</button></form><table class="table"><tr><th>Fecha</th><th>Cliente</th><th>Técnico</th><th>Estado</th><th>Notas</th></tr>{trs or '<tr><td colspan=5 class=muted>Sin instalaciones.</td></tr>'}</table></div>''','installations_page')


def whatsapp_page():
    if not base.logged_in(): return redirect(url_for('login'))
    if request.method=='POST': n,msg=bs.try_send_outbox(100); flash(f'Enviados: {n}. {msg}')
    c=base.db(); rows=c.execute('SELECT * FROM whatsapp_outbox ORDER BY id DESC LIMIT 100').fetchall(); templates=c.execute('SELECT * FROM whatsapp_templates ORDER BY id').fetchall(); c.close(); trs=''.join(f'<tr><td>{esc(r["created_at"])}</td><td>{esc(r["phone"])}</td><td>{esc(r["template_code"])}</td><td>{esc(r["message"])}</td><td>{esc(r["status"])}</td></tr>' for r in rows); trows=''.join(f'<tr><td>{esc(t["code"])}</td><td>{esc(t["name"])}</td><td>{esc(t["body"])}</td></tr>' for t in templates); configured=bool(os.getenv('WHATSAPP_API_URL') and os.getenv('WHATSAPP_API_TOKEN'))
    return base.shell('WhatsApp',f'''<div class="head"><div><h1>WhatsApp</h1><p>Cola, plantillas y avisos</p></div><form method="post"><button class="btn green">Enviar cola ahora</button></form></div><div class="panel"><div class="notice" style="background:{'#063f2a' if configured else '#4e3707'};color:#fff">{'API configurada.' if configured else 'La cola está lista. Falta conectar el proveedor de WhatsApp mediante WHATSAPP_API_URL y WHATSAPP_API_TOKEN.'}</div><table class="table"><tr><th>Fecha</th><th>Teléfono</th><th>Tipo</th><th>Mensaje</th><th>Estado</th></tr>{trs or '<tr><td colspan=5 class=muted>Sin mensajes.</td></tr>'}</table></div><div class="panel"><h3>Plantillas</h3><table class="table">{trows}</table></div>''','whatsapp_page')


def monitoring_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); routers=c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall() if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_router_agents'").fetchone() else []; active=c.execute('SELECT COUNT(*) c FROM push_pppoe_active').fetchone()['c'] if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_pppoe_active'").fetchone() else 0; total=c.execute('SELECT COUNT(*) c FROM push_pppoe_secrets').fetchone()['c'] if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_pppoe_secrets'").fetchone() else 0; tickets=c.execute("SELECT COUNT(*) c FROM support_tickets WHERE status='ABIERTO'").fetchone()['c']; c.close(); stale=int(bs.setting('monitor_stale_minutes','10')); now=datetime.now(); trs=[]
    for r in routers:
        try: age=(now-datetime.fromisoformat(r['last_seen'])).total_seconds()/60 if r['last_seen'] else 99999
        except: age=99999
        state='ONLINE' if age<=stale else 'SIN DATOS'; cls='ok' if state=='ONLINE' else 'bad'; trs.append(f'<tr><td>{esc(r["identity"] or r["name"])}</td><td><span class="tag {cls}">{state}</span></td><td>{esc(r["ros_version"] or "-")}</td><td>{r["pppoe_active"]}/{r["pppoe_total"]}</td><td>{esc(r["last_seen"] or "-")}</td></tr>')
    return base.shell('Monitoreo',f'''<div class="head"><div><h1>Monitoreo</h1><p>Red, clientes y soporte</p></div></div><div class="grid6" style="grid-template-columns:repeat(3,1fr)"><div class="kpi green1"><div class="label">PPPoE conectados</div><div class="value">{active}</div><div class="sub">de {total}</div></div><div class="kpi orange1"><div class="label">No activos</div><div class="value">{max(total-active,0)}</div></div><div class="kpi purple1"><div class="label">Tickets abiertos</div><div class="value">{tickets}</div></div></div><div class="panel"><table class="table"><tr><th>Router</th><th>Estado</th><th>RouterOS</th><th>PPPoE</th><th>Última sync</th></tr>{''.join(trs) or '<tr><td colspan=5 class=muted>Sin routers.</td></tr>'}</table></div>''','monitoring_page')


def reports_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); total=c.execute('SELECT COUNT(*) c FROM customers').fetchone()['c']; pending=c.execute("SELECT COALESCE(SUM(amount+COALESCE(late_fee,0)),0) s FROM invoices WHERE status='PENDIENTE'").fetchone()['s']; paid=c.execute('SELECT COALESCE(SUM(amount),0) s FROM payments').fetchone()['s']; expenses=c.execute('SELECT COALESCE(SUM(amount),0) s FROM expenses').fetchone()['s']; byzone=c.execute('''SELECT COALESCE(z.name,cu.zone,'Sin zona') zone,COUNT(*) n FROM customers cu LEFT JOIN zones z ON z.id=cu.zone_id GROUP BY COALESCE(z.name,cu.zone,'Sin zona') ORDER BY n DESC''').fetchall(); c.close(); zrows=''.join(f'<tr><td>{esc(r["zone"])}</td><td>{r["n"]}</td></tr>' for r in byzone)
    return base.shell('Reportes',f'''<div class="head"><div><h1>Reportes</h1><p>Ingresos, morosidad, gastos y crecimiento</p></div></div><div class="grid6" style="grid-template-columns:repeat(4,1fr)"><div class="kpi blue1"><div class="label">Clientes</div><div class="value">{total}</div></div><div class="kpi green1"><div class="label">Cobrado</div><div class="value" style="font-size:20px">RD${paid:,.0f}</div></div><div class="kpi red1"><div class="label">Por cobrar</div><div class="value" style="font-size:20px">RD${pending:,.0f}</div></div><div class="kpi orange1"><div class="label">Gastos</div><div class="value" style="font-size:20px">RD${expenses:,.0f}</div></div></div><div class="panel"><h3>Clientes por zona</h3><table class="table">{zrows}</table></div>''','reports_page')


def automation_page():
    if not base.logged_in(): return redirect(url_for('login'))
    if request.method=='POST':
        created,overdue,commands=bs.run_billing(); flash(f'Proceso terminado: {created} facturas, {overdue} morosos, {commands} comandos.')
    c=base.db(); rows=c.execute('SELECT * FROM billing_runs ORDER BY id DESC LIMIT 30').fetchall(); c.close(); trs=''.join(f'<tr><td>{esc(r["run_date"])}</td><td>{esc(r["status"])}</td><td>{esc(r["detail"])}</td></tr>' for r in rows)
    return base.shell('Automatización',f'''<div class="head"><div><h1>Automatización</h1><p>Facturas, avisos, corte y reconexión</p></div><form method="post"><button class="btn green">Ejecutar ahora</button></form></div><div class="panel"><p><b>Facturación:</b> {'ACTIVA' if bs.setting('billing_enabled')=='1' else 'INACTIVA'}</p><p><b>Corte automático:</b> {'ACTIVO' if bs.setting('auto_suspend')=='1' else 'DESACTIVADO'}</p><p><b>Reconexión:</b> {'ACTIVA' if bs.setting('auto_reactivate')=='1' else 'DESACTIVADA'}</p><p class="muted">Los cambios del MikroTik se agregan a una cola segura.</p></div><div class="panel"><table class="table"><tr><th>Fecha</th><th>Estado</th><th>Detalle</th></tr>{trs or '<tr><td colspan=3 class=muted>Sin ejecuciones.</td></tr>'}</table></div>''','automation_page')


def setup(app):
    nav=[('zones_page','⌖','Zonas'),('onu_page','◈','OLT / ONU'),('tickets_page','🎧','Soporte'),('installations_page','🛠','Instalaciones'),('monitoring_page','⌁','Monitoreo'),('reports_page','▥','Reportes'),('automation_page','⚙','Automatización')]
    existing={x[0] for x in base.NAV}
    for x in nav:
        if x[0] not in existing: base.NAV.append(x)
    for rule,ep,fn,methods in [('/zones','zones_page',zones_page,['GET','POST']),('/onu','onu_page',onu_page,['GET','POST']),('/tickets','tickets_page',tickets_page,['GET','POST']),('/installations','installations_page',installations_page,['GET','POST']),('/monitoring','monitoring_page',monitoring_page,['GET']),('/reports','reports_page',reports_page,['GET']),('/automation','automation_page',automation_page,['GET','POST'])]: app.add_url_rule(rule,endpoint=ep,view_func=fn,methods=methods)
