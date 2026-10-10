import os, secrets, sqlite3, tempfile, urllib.request, json
from datetime import date, datetime, timedelta
from html import escape
from flask import request, redirect, url_for, flash, session, send_file, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
import app as base


def esc(v): return escape('' if v is None else str(v))

def _col(c,table,name,ddl):
    if name not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')

def ensure_schema():
    c=base.db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS zones(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,billing_day INTEGER DEFAULT 30,invoice_days_before INTEGER DEFAULT 5,cut_days_after INTEGER DEFAULT 6,cut_time TEXT DEFAULT '14:00',active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS onu_devices(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER,vendor TEXT,model TEXT,serial TEXT,mac TEXT,olt TEXT,pon_port TEXT,rx_power TEXT,tx_power TEXT,status TEXT DEFAULT 'PENDIENTE',last_seen TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS support_tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER,subject TEXT,priority TEXT DEFAULT 'MEDIA',status TEXT DEFAULT 'ABIERTO',assigned_to TEXT,opened_at TEXT,closed_at TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS installations(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER,scheduled_at TEXT,status TEXT DEFAULT 'PENDIENTE',technician TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS payment_promises(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER,invoice_id INTEGER,promise_date TEXT,amount REAL DEFAULT 0,status TEXT DEFAULT 'PENDIENTE',notes TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY AUTOINCREMENT,concept TEXT,category TEXT,amount REAL,paid_at TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS bank_accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,bank TEXT,account_type TEXT,account_number TEXT,label TEXT,active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS whatsapp_templates(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,name TEXT,body TEXT,active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS whatsapp_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER,phone TEXT,template_code TEXT,message TEXT,status TEXT DEFAULT 'PENDIENTE',created_at TEXT,sent_at TEXT,error TEXT);
    CREATE TABLE IF NOT EXISTS staff_users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password_hash TEXT,name TEXT,role TEXT DEFAULT 'SOPORTE',active INTEGER DEFAULT 1,last_login TEXT);
    CREATE TABLE IF NOT EXISTS portal_tokens(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER UNIQUE,token TEXT UNIQUE,enabled INTEGER DEFAULT 1,created_at TEXT);
    CREATE TABLE IF NOT EXISTS billing_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,run_date TEXT,status TEXT,detail TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS router_commands(id INTEGER PRIMARY KEY AUTOINCREMENT,router_name TEXT DEFAULT 'CCR2116',customer_id INTEGER,pppoe TEXT,action TEXT,payload TEXT,status TEXT DEFAULT 'PENDIENTE',created_at TEXT,executed_at TEXT,result TEXT,requested_by TEXT);
    ''')
    for n,ddl in [('latitude','TEXT'),('longitude','TEXT'),('notes','TEXT'),('zone_id','INTEGER'),('router_name','TEXT DEFAULT "CCR2116"'),('install_date','TEXT'),('service_status','TEXT DEFAULT "ACTIVO"')]: _col(c,'customers',n,ddl)
    for n,ddl in [('period','TEXT'),('late_fee','REAL DEFAULT 0'),('generated_by','TEXT'),('plan_name','TEXT'),('plan_speed','TEXT')]: _col(c,'invoices',n,ddl)
    for n,ddl in [('received_by','TEXT'),('proof','TEXT')]: _col(c,'payments',n,ddl)
    for k,v in {'business_name':'INTER Flash','business_rnc':'','business_phone':'','business_email':'','business_address':'','billing_footer':'Gracias por preferir INTER Flash.','billing_enabled':'1','auto_suspend':'0','auto_reactivate':'0','whatsapp_enabled':'0','monitor_stale_minutes':'10'}.items(): c.execute('INSERT OR IGNORE INTO app_settings(key,value) VALUES(?,?)',(k,v))
    for code,name,body in [('INVOICE','Factura generada','Hola {name}, tu factura de {amount} vence el {due_date}.'),('OVERDUE','Factura vencida','Hola {name}, tienes una factura vencida por {amount}.'),('PAYMENT','Pago recibido','Hola {name}, recibimos tu pago de {amount}. Gracias.'),('SUSPEND','Suspensión','Hola {name}, tu servicio está programado para suspensión.'),('RECONNECT','Reconexión','Hola {name}, tu servicio fue programado para reconexión.')]:
        c.execute('INSERT OR IGNORE INTO whatsapp_templates(code,name,body) VALUES(?,?,?)',(code,name,body))
    c.commit(); c.close()

def setting(key,default=''):
    c=base.db(); r=c.execute('SELECT value FROM app_settings WHERE key=?',(key,)).fetchone(); c.close(); return r['value'] if r else default

def set_setting(key,value):
    c=base.db(); c.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); c.commit(); c.close()

def queue_whatsapp(customer_id,code,extra=None):
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(customer_id,)).fetchone(); t=c.execute('SELECT * FROM whatsapp_templates WHERE code=? AND active=1',(code,)).fetchone()
    if not cu or not t or not cu['phone']: c.close(); return False
    data={'name':cu['name'],'amount':'','due_date':''}; data.update(extra or {})
    try: msg=t['body'].format(**data)
    except: msg=t['body']
    c.execute('INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(?,?,?,?,?,?)',(customer_id,cu['phone'],code,msg,'PENDIENTE',datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close(); return True

def try_send_outbox(limit=25):
    api=os.getenv('WHATSAPP_API_URL','').strip(); token=os.getenv('WHATSAPP_API_TOKEN','').strip()
    if not api or not token: return 0,'API de WhatsApp no configurada.'
    c=base.db(); rows=c.execute("SELECT * FROM whatsapp_outbox WHERE status='PENDIENTE' ORDER BY id LIMIT ?",(limit,)).fetchall(); sent=0
    for r in rows:
        try:
            data=json.dumps({'to':r['phone'],'message':r['message']}).encode(); req=urllib.request.Request(api,data=data,method='POST',headers={'Content-Type':'application/json','Authorization':'Bearer '+token}); urllib.request.urlopen(req,timeout=8).read(128)
            c.execute("UPDATE whatsapp_outbox SET status='ENVIADO',sent_at=?,error='' WHERE id=?",(datetime.now().isoformat(timespec='seconds'),r['id'])); sent+=1
        except Exception as ex: c.execute("UPDATE whatsapp_outbox SET status='ERROR',error=? WHERE id=?",(str(ex)[:300],r['id']))
    c.commit(); c.close(); return sent,'ok'

def run_billing():
    today=date.today(); period=today.strftime('%Y-%m'); c=base.db(); rows=c.execute('''SELECT cu.*,p.price plan_price,p.name plan_name,p.download_mbps,p.upload_mbps,z.invoice_days_before,z.cut_days_after FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id LEFT JOIN zones z ON z.id=cu.zone_id WHERE cu.plan_id IS NOT NULL''').fetchall(); created=overdue=commands=0
    for cu in rows:
        due_day=max(1,min(int(cu['due_day'] or 30),28 if today.month==2 else 30)); due=date(today.year,today.month,due_day); issue=due-timedelta(days=int(cu['invoice_days_before'] if cu['invoice_days_before'] is not None else 5))
        if today>=issue and not c.execute('SELECT id FROM invoices WHERE customer_id=? AND period=?',(cu['id'],period)).fetchone():
            c.execute('INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date,status,period,generated_by,plan_name,plan_speed) VALUES(?,?,?,?,?,?,?,?,?,?)',(cu['id'],'Servicio de Internet '+period,float(cu['plan_price'] or 0),today.isoformat(),due.isoformat(),'PENDIENTE',period,'AUTOMATICO',cu['plan_name'] or '',(str(cu['download_mbps'] or 0)+'/'+str(cu['upload_mbps'] or 0)+' Mbps'))); created+=1
            if setting('whatsapp_enabled','0')=='1' and cu['phone']:
                t=c.execute("SELECT body FROM whatsapp_templates WHERE code='INVOICE'").fetchone(); msg=t['body'].format(name=cu['name'],amount='RD${:,.2f}'.format(float(cu['plan_price'] or 0)),due_date=due.isoformat()) if t else ''
                if msg: c.execute('INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(?,?,?,?,?,?)',(cu['id'],cu['phone'],'INVOICE',msg,'PENDIENTE',datetime.now().isoformat(timespec='seconds')))
        invs=c.execute("SELECT * FROM invoices WHERE customer_id=? AND status='PENDIENTE' AND due_date<?",(cu['id'],today.isoformat())).fetchall()
        if invs:
            overdue+=1; oldest=min(date.fromisoformat(i['due_date']) for i in invs); cut=int(cu['cut_days_after'] if cu['cut_days_after'] is not None else 6)
            if setting('auto_suspend','0')=='1' and today>=oldest+timedelta(days=cut) and cu['pppoe'] and not c.execute("SELECT id FROM router_commands WHERE pppoe=? AND action='SUSPEND' AND status IN ('PENDIENTE','EN_PROCESO')",(cu['pppoe'],)).fetchone():
                c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],'SUSPEND','{}','PENDIENTE',datetime.now().isoformat(timespec='seconds'),'AUTOMATICO')); commands+=1
    c.execute('INSERT INTO billing_runs(run_date,status,detail,created_at) VALUES(?,?,?,?)',(today.isoformat(),'OK',f'Facturas {created}; morosos {overdue}; comandos {commands}',datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close(); return created,overdue,commands

def customers_full():
    if not base.logged_in(): return redirect(url_for('login'))
    q=(request.args.get('q') or '').strip(); c=base.db(); sql='''SELECT cu.*,p.name plan_name,z.name zone_name FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id LEFT JOIN zones z ON z.id=cu.zone_id'''; args=[]
    if q: like='%'+q+'%'; sql+=' WHERE cu.name LIKE ? OR cu.phone LIKE ? OR cu.document LIKE ? OR cu.pppoe LIKE ? OR cu.onu_serial LIKE ?'; args=[like]*5
    sql+=' ORDER BY cu.id DESC'; rows=c.execute(sql,args).fetchall(); active={r['name'] for r in c.execute('SELECT * FROM push_pppoe_active').fetchall()} if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_pppoe_active'").fetchone() else set(); c.close(); trs=[]
    for r in rows:
        state='ONLINE' if r['pppoe'] in active else (r['status'] or 'ACTIVO'); cls='ok' if state in ('ONLINE','ACTIVO') else 'bad' if state=='SUSPENDIDO' else 'warn'; trs.append(f'''<tr><td>{esc(r['code'] or '#'+str(r['id']))}</td><td><b>{esc(r['name'])}</b><br><span class="muted">{esc(r['phone'])}</span></td><td>{esc(r['plan_name'] or '-')}</td><td>{esc(r['zone_name'] or r['zone'] or '-')}</td><td>{esc(r['pppoe'] or '-')}</td><td><span class="tag {cls}">{state}</span></td><td><a class="btn blue" href="{url_for('customer_profile',id=r['id'])}">Ficha</a> <a class="btn" href="{url_for('customer_edit',id=r['id'])}">Editar</a></td></tr>''')
    return base.shell('Clientes',f'''<div class="head"><div><h1>Clientes</h1><p>Clientes, servicio, facturas, ONU y soporte</p></div><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div><div class="panel"><form class="toolbar"><input class="field" name="q" value="{esc(q)}" placeholder="Buscar cliente, teléfono, cédula, PPPoE, ONU"><button class="btn blue">Buscar</button></form><table class="table"><tr><th>Código</th><th>Cliente</th><th>Plan</th><th>Zona</th><th>PPPoE</th><th>Estado</th><th></th></tr>{''.join(trs) or '<tr><td colspan=7 class=muted>No hay clientes.</td></tr>'}</table></div>''','customers')

def customer_profile(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); cu=c.execute('''SELECT cu.*,p.name plan_name,p.price plan_price,z.name zone_name FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id LEFT JOIN zones z ON z.id=cu.zone_id WHERE cu.id=?''',(id,)).fetchone()
    if not cu: c.close(); return redirect(url_for('customers'))
    inv=c.execute('SELECT * FROM invoices WHERE customer_id=? ORDER BY id DESC LIMIT 10',(id,)).fetchall(); pay=c.execute('SELECT * FROM payments WHERE customer_id=? ORDER BY id DESC LIMIT 10',(id,)).fetchall(); onu=c.execute('SELECT * FROM onu_devices WHERE customer_id=? ORDER BY id DESC LIMIT 5',(id,)).fetchall(); portal=c.execute('SELECT * FROM portal_tokens WHERE customer_id=?',(id,)).fetchone(); cmds=c.execute('SELECT * FROM router_commands WHERE customer_id=? ORDER BY id DESC LIMIT 8',(id,)).fetchall(); c.close()
    invr=''.join(f'<tr><td>#{x["id"]}</td><td>{esc(x["concept"])}</td><td>RD${x["amount"]:,.2f}</td><td>{esc(x["due_date"])}</td><td>{esc(x["status"])}</td></tr>' for x in inv) or '<tr><td colspan=5 class=muted>Sin facturas.</td></tr>'; payr=''.join(f'<tr><td>{esc(x["paid_at"])}</td><td>RD${x["amount"]:,.2f}</td><td>{esc(x["method"])}</td></tr>' for x in pay) or '<tr><td colspan=3 class=muted>Sin pagos.</td></tr>'; onur=''.join(f'<tr><td>{esc(x["vendor"])} {esc(x["model"])}</td><td>{esc(x["serial"])}</td><td>{esc(x["olt"])} / {esc(x["pon_port"])}</td><td>{esc(x["rx_power"] or "-")}</td></tr>' for x in onu) or '<tr><td colspan=4 class=muted>Sin ONU.</td></tr>'; cmdr=''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x["action"])}</td><td>{esc(x["status"])}</td></tr>' for x in cmds) or '<tr><td colspan=3 class=muted>Sin comandos.</td></tr>'; plink=(request.url_root.rstrip('/')+url_for('customer_portal',token=portal['token'])) if portal and portal['enabled'] else ''
    body=f'''<div class="head"><div><h1>{esc(cu['name'])}</h1><p>{esc(cu['code'])} · {esc(cu['pppoe'] or 'Sin PPPoE')}</p></div><div><a class="btn" href="{url_for('customers')}">← Clientes</a> <a class="btn blue" href="{url_for('customer_edit',id=id)}">Editar</a> <a class="btn" href="{url_for('customer_service_info',id=id)}">Servicio / mapa</a></div></div><div class="panel"><div class="toolbar"><form method="post" action="{url_for('queue_customer_command',id=id,action='SUSPEND')}"><button class="btn" style="background:#6b1b23">Suspender</button></form><form method="post" action="{url_for('queue_customer_command',id=id,action='REACTIVATE')}"><button class="btn green">Reactivar</button></form><a class="btn blue" href="{url_for('promise_new',customer_id=id)}">Promesa</a><form method="post" action="{url_for('portal_toggle',id=id)}"><button class="btn">Portal cliente</button></form></div>{f'<p class="muted">Portal: <a href="{plink}" target="_blank">{esc(plink)}</a></p>' if plink else ''}</div><div class="cards2"><div class="panel"><h3>Facturas</h3><table class="table">{invr}</table></div><div class="panel"><h3>Pagos</h3><table class="table">{payr}</table></div></div><div class="panel"><h3>ONU</h3><table class="table">{onur}</table></div><div class="panel"><h3>Comandos MikroTik</h3><table class="table">{cmdr}</table></div>'''; return base.shell('Ficha cliente',body,'customers')

def promise_new(customer_id):
    if not base.logged_in(): return redirect(url_for('login'))
    if request.method=='POST':
        if (session.get('role') or 'ADMIN').upper() not in ('ADMIN','CAJA','COBRADOR'): return 'Sin permiso.',403
        from whatsapp_events import create_promise
        try:
            create_promise(customer_id,request.form.get('invoice_id') or None,request.form.get('promise_date') or '',request.form.get('amount') or '0',request.form.get('notes') or '')
            flash('Promesa registrada.')
            return redirect(url_for('customer_profile',id=customer_id))
        except (ValueError,TypeError) as exc:
            flash(str(exc))
            return redirect(url_for('promise_new',customer_id=customer_id))
    c=base.db()
    customer=c.execute("SELECT name FROM customers WHERE id=?",(customer_id,)).fetchone()
    inv=c.execute("SELECT * FROM invoices WHERE customer_id=? AND status='PENDIENTE'",(customer_id,)).fetchall()
    c.close()
    if not customer: return 'Cliente no encontrado',404
    opts=''.join(f'<option value="{x["id"]}">#{x["id"]} · RD${x["amount"]:,.2f}</option>' for x in inv)
    today=date.today().isoformat()
    body=f'''<style>
    .promise-overlay{{position:fixed;inset:0;background:#0009;display:flex;align-items:center;justify-content:center;z-index:500;padding:16px}}
    .promise-modal{{width:min(100%,610px);max-height:92vh;overflow:auto;background:#fff;color:#253248;border-radius:12px;box-shadow:0 20px 60px #0006}}
    .promise-head{{background:linear-gradient(100deg,#e9690b,#c6290c);color:#fff;padding:23px 26px;display:flex;justify-content:space-between;align-items:center}}
    .promise-head h2{{margin:0;color:#fff}}.promise-head small{{color:#fff}}
    .promise-body{{padding:25px}}.promise-help{{background:#fff8e9;border:1px solid #f3dba7;border-radius:8px;padding:15px;margin-bottom:20px}}
    .promise-body label{{display:block;font-weight:700;margin:14px 0}}.promise-body input,.promise-body select,.promise-body textarea{{display:block;width:100%;padding:12px;border:1px solid #d7dce3;border-radius:6px;background:white;color:#263242;margin-top:7px}}
    .promise-foot{{display:flex;gap:12px;padding:16px 25px;border-top:1px solid #ddd}}.promise-foot>*{{flex:1;text-align:center;padding:12px;border-radius:6px}}.promise-save{{background:#d53d0c;color:white;border:0;font-weight:bold;cursor:pointer}}
    </style><div class="promise-overlay"><section class="promise-modal" role="dialog" aria-modal="true" aria-label="Crear promesa de pago">
    <header class="promise-head"><div><h2>🤝 Crear Promesa de Pago</h2><small>{esc(customer["name"])}</small></div><a href="{url_for('customers_plus',overdue=1)}" style="color:white;font-size:26px" aria-label="Cerrar">×</a></header>
    <form method="post"><div class="promise-body">
    <div class="promise-help"><b>¿Qué es una promesa de pago?</b><p>Acuerdo temporal que extiende la fecha de pago. El corte automático al incumplir requiere que esté habilitado y verificado en el sistema.</p></div>
    <label>Nueva Fecha de Pago *<input type="date" name="promise_date" min="{today}" required></label>
    <label>Hora de Corte si no cumple *<input type="time" name="promise_time" value="23:59" required></label>
    <label>Factura<select name="invoice_id"><option value="">General</option>{opts}</select></label>
    <label>Monto acordado (RD$)<input type="number" step="0.01" min="0" name="amount" value="0"></label>
    <label>Motivo / Notas (Opcional)<textarea name="notes" rows="3" placeholder="Ej: Cliente solicita extensión por problemas económicos"></textarea></label>
    </div><footer class="promise-foot"><a href="{url_for('customers_plus',overdue=1)}">Cancelar</a><button class="promise-save" type="submit">Crear Promesa</button></footer></form></section></div>'''
    return base.shell('Promesa de pago',body,'customers')

def portal_toggle(id):
    if not base.logged_in(): return redirect(url_for('login'))
    token=secrets.token_urlsafe(32); c=base.db(); c.execute('INSERT INTO portal_tokens(customer_id,token,enabled,created_at) VALUES(?,?,1,?) ON CONFLICT(customer_id) DO UPDATE SET token=excluded.token,enabled=1,created_at=excluded.created_at',(id,token,datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close(); flash('Portal generado.'); return redirect(url_for('customer_profile',id=id))

def customer_portal(token):
    c=base.db(); p=c.execute('SELECT * FROM portal_tokens WHERE token=? AND enabled=1',(token,)).fetchone()
    if not p: c.close(); return 'Portal no disponible',404
    cu=c.execute('''SELECT cu.*,p.name plan_name FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id WHERE cu.id=?''',(p['customer_id'],)).fetchone(); inv=c.execute('SELECT * FROM invoices WHERE customer_id=? ORDER BY id DESC',(p['customer_id'],)).fetchall(); pay=c.execute('SELECT * FROM payments WHERE customer_id=? ORDER BY id DESC LIMIT 20',(p['customer_id'],)).fetchall(); c.close(); invr=''.join(f'<tr><td>{esc(x["concept"])}</td><td>RD${x["amount"]:,.2f}</td><td>{esc(x["due_date"])}</td><td>{esc(x["status"])}</td></tr>' for x in inv); payr=''.join(f'<tr><td>{esc(x["paid_at"])}</td><td>RD${x["amount"]:,.2f}</td><td>{esc(x["method"])}</td></tr>' for x in pay)
    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Portal INTER Flash</title><style>{{css}}</style></head><body><div style="max-width:900px;margin:30px auto;padding:16px"><div class="panel"><h2>{{name}}</h2><p>Plan: <b>{{plan}}</b> · Estado: <b>{{status}}</b></p></div><div class="panel"><h3>Facturas</h3><table class="table">{{invr|safe}}</table></div><div class="panel"><h3>Pagos</h3><table class="table">{{payr|safe}}</table></div></div></body></html>''',css=base.BASE_CSS,name=cu['name'],plan=cu['plan_name'] or '-',status=cu['status'],invr=invr,payr=payr)

def backup_download():
    if not base.logged_in(): return redirect(url_for('login'))
    fd,path=tempfile.mkstemp(prefix='interflash-',suffix='.db'); os.close(fd); src=base.db(); dst=sqlite3.connect(path); src.backup(dst); dst.close(); src.close(); return send_file(path,as_attachment=True,download_name='interflash-backup-'+datetime.now().strftime('%Y%m%d-%H%M')+'.db')

def users_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    if request.method=='POST': c.execute('INSERT INTO staff_users(username,password_hash,name,role,active) VALUES(?,?,?,?,1)',(request.form['username'].strip(),generate_password_hash(request.form['password']),request.form.get('name'),request.form.get('role','SOPORTE'))); c.commit(); flash('Usuario creado.')
    rows=c.execute('SELECT * FROM staff_users ORDER BY id DESC').fetchall(); c.close(); trs=''.join(f'<tr><td>{esc(r["username"])}</td><td>{esc(r["name"] or "-")}</td><td>{esc(r["role"])}</td><td>{"ACTIVO" if r["active"] else "INACTIVO"}</td></tr>' for r in rows); return base.shell('Usuarios',f'''<div class="head"><div><h1>Usuarios</h1><p>Permisos por rol</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="username" placeholder="Usuario" required><input class="field" name="name" placeholder="Nombre"><input class="field" type="password" name="password" placeholder="Contraseña" required><select class="field" name="role"><option>ADMIN</option><option>COBRADOR</option><option>TECNICO</option><option>SOPORTE</option></select><button class="btn green">Crear</button></form><table class="table">{trs}</table></div>''','users_page')

def settings_page():
    if not base.logged_in(): return redirect(url_for('login'))
    keys=['business_name','business_rnc','business_phone','business_email','business_address','billing_footer','billing_enabled','auto_suspend','auto_reactivate','whatsapp_enabled','monitor_stale_minutes']
    if request.method=='POST':
        for k in keys: set_setting(k,request.form.get(k,'0') if k in ('billing_enabled','auto_suspend','auto_reactivate','whatsapp_enabled') else request.form.get(k,''))
        flash('Configuración guardada.')
    def sel(k,v): return 'selected' if setting(k)==v else ''
    return base.shell('Configuración',f'''<div class="head"><div><h1>Configuración</h1><p>Datos generales y de facturación de INTER Flash</p></div><a class="btn" href="{url_for('backup_download')}">Descargar backup</a></div>
    <div class="panel"><h3>Datos que aparecerán en la factura</h3><form class="formgrid" method="post">
    <label>Empresa<input name="business_name" value="{esc(setting('business_name'))}"></label>
    <label>RNC / Identificación fiscal<input name="business_rnc" value="{esc(setting('business_rnc'))}" placeholder="Opcional"></label>
    <label>Teléfono<input name="business_phone" value="{esc(setting('business_phone'))}"></label>
    <label>Correo<input type="email" name="business_email" value="{esc(setting('business_email'))}"></label>
    <label class="full">Dirección<input name="business_address" value="{esc(setting('business_address'))}"></label>
    <label class="full">Pie de factura<input name="billing_footer" value="{esc(setting('billing_footer'))}"></label>
    <label>Monitoreo (minutos)<input type="number" name="monitor_stale_minutes" value="{esc(setting('monitor_stale_minutes'))}"></label>
    <label>Facturación<select name="billing_enabled"><option value="1" {sel('billing_enabled','1')}>ACTIVA</option><option value="0" {sel('billing_enabled','0')}>INACTIVA</option></select></label>
    <label>Corte automático<select name="auto_suspend"><option value="0" {sel('auto_suspend','0')}>DESACTIVADO</option><option value="1" {sel('auto_suspend','1')}>ACTIVO</option></select></label>
    <label>Reconexión<select name="auto_reactivate"><option value="0" {sel('auto_reactivate','0')}>DESACTIVADA</option><option value="1" {sel('auto_reactivate','1')}>ACTIVA</option></select></label>
    <label>WhatsApp<select name="whatsapp_enabled"><option value="0" {sel('whatsapp_enabled','0')}>DESACTIVADO</option><option value="1" {sel('whatsapp_enabled','1')}>ACTIVO</option></select></label>
    <div class="full"><button class="btn green">Guardar</button></div></form></div>''','settings_page')

def login_full():
    error=''
    if request.method=='POST':
        u=request.form.get('username',''); p=request.form.get('password','')
        if u==base.ADMIN_USER and base.ADMIN_PASSWORD and p==base.ADMIN_PASSWORD: session.clear(); session['auth']=True; session['role']='ADMIN'; session['user']=u; return redirect(url_for('dashboard'))
        c=base.db(); row=c.execute('SELECT * FROM staff_users WHERE username=? AND active=1',(u,)).fetchone()
        if row and check_password_hash(row['password_hash'],p): session.clear(); session['auth']=True; session['role']=row['role']; session['user']=row['username']; c.execute('UPDATE staff_users SET last_login=? WHERE id=?',(datetime.now().isoformat(timespec='seconds'),row['id'])); c.commit(); c.close(); return redirect(url_for('dashboard'))
        c.close(); error='Usuario o contraseña incorrectos.'
    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash</title><style>{{css}}</style></head><body><div class="loginwrap"><form class="loginbox" method="post"><h2>INTER Flash ISP Manager</h2>{% if error %}<div class="notice">{{error}}</div>{% endif %}<input name="username" placeholder="Usuario" required><input type="password" name="password" placeholder="Contraseña" required><button class="btn blue">Entrar</button></form></div></body></html>''',css=base.BASE_CSS,error=error)

def setup(app):
    ensure_schema(); app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True)
    for item in [('users_page','👤','Usuarios'),('settings_page','⚙','Configuración')]:
        if item[0] not in {x[0] for x in base.NAV}: base.NAV.append(item)
    app.view_functions['customers']=customers_full; app.view_functions['login']=login_full
    for rule,ep,fn,methods in [('/customers/<int:id>/profile','customer_profile',customer_profile,['GET']),('/customers/<int:customer_id>/promise','promise_new',promise_new,['GET','POST']),('/customers/<int:id>/portal','portal_toggle',portal_toggle,['POST']),('/portal/<token>','customer_portal',customer_portal,['GET']),('/backup/download','backup_download',backup_download,['GET']),('/users','users_page',users_page,['GET','POST']),('/settings','settings_page',settings_page,['GET','POST'])]: app.add_url_rule(rule,endpoint=ep,view_func=fn,methods=methods)
