import os, sqlite3, base64, hashlib, html
from datetime import date, datetime
from flask import Flask, request, redirect, url_for, make_response, render_template_string
from cryptography.fernet import Fernet
import routeros_api

SECRET=os.getenv('SECRET_KEY','interflash-secret')
app=Flask(__name__)
app.secret_key=SECRET
USER=os.getenv('ADMIN_USER','manuel')
PASSWORD=os.getenv('ADMIN_PASSWORD','InterFlash2026!')
DB=os.getenv('DB_PATH','/tmp/interflash.db')
parent=os.path.dirname(DB)
if parent:
    os.makedirs(parent,exist_ok=True)
FERNET=Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))

def con():
    c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; return c

def addcol(c,table,name,ddl):
    cols={r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
    if name not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')

def init():
    c=con(); c.executescript('''
    CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,speed TEXT,price REAL);
    CREATE TABLE IF NOT EXISTS zones(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,due_day INTEGER DEFAULT 30,cut_day INTEGER DEFAULT 6,cut_time TEXT DEFAULT '14:00');
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,phone TEXT,pppoe TEXT,status TEXT DEFAULT 'ACTIVO',plan_id INTEGER,zone_id INTEGER);
    CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER,concept TEXT,amount REAL,issue_date TEXT,due_date TEXT,status TEXT DEFAULT 'PENDIENTE',paid_at TEXT);
    CREATE TABLE IF NOT EXISTS routers(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,host TEXT,port INTEGER DEFAULT 8728,status TEXT DEFAULT 'PENDIENTE');
    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,subject TEXT,client TEXT,status TEXT DEFAULT 'NUEVO');
    ''')
    addcol(c,'routers','username','TEXT')
    addcol(c,'routers','password_enc','TEXT')
    addcol(c,'routers','use_ssl','INTEGER DEFAULT 1')
    addcol(c,'routers','verify_ssl','INTEGER DEFAULT 0')
    addcol(c,'routers','identity','TEXT')
    addcol(c,'routers','model','TEXT')
    addcol(c,'routers','ros_version','TEXT')
    addcol(c,'routers','pppoe_active','INTEGER DEFAULT 0')
    addcol(c,'routers','last_seen','TEXT')
    addcol(c,'routers','last_error','TEXT')
    c.commit(); c.close()
init()

def auth(): return request.cookies.get('if_session')=='ok'
def e(v): return html.escape(str(v if v is not None else ''))
def enc(v): return FERNET.encrypt((v or '').encode()).decode() if v else ''
def dec(v):
    if not v: return ''
    try: return FERNET.decrypt(v.encode()).decode()
    except Exception: return ''

CSS='''
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial;background:#f5f7fa;color:#1f2937}a{text-decoration:none;color:inherit}.side{position:fixed;left:0;top:0;bottom:0;width:250px;background:#111820;color:#cbd5e1;padding:18px 12px;overflow:auto}.brand{display:flex;gap:11px;align-items:center;padding:7px 10px 18px;border-bottom:1px solid #29333e}.logo{width:44px;height:44px;border-radius:11px;background:linear-gradient(135deg,#079b5d,#6bd99b);display:grid;place-items:center;color:#fff;font-weight:900}.brand b{display:block;color:#fff;font-size:18px}.brand small{color:#94a3b8}.user{margin:14px 7px;padding:12px;border:1px solid #29333e;border-radius:9px}.user b{color:#fff}.user small{display:block;color:#8da0b2;margin-top:3px}.nav a{display:block;padding:11px 12px;border-radius:8px;margin:2px 0}.nav a:hover,.nav a.on{background:#087e50;color:#fff}.main{margin-left:250px;min-height:100vh}.top{height:70px;background:#fff;border-bottom:1px solid #e6e9ee;display:flex;align-items:center;justify-content:space-between;padding:0 27px;position:sticky;top:0;z-index:4}.top small{display:block;color:#8793a1;font-size:11px;letter-spacing:1.4px}.content{padding:27px}.head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:17px}.head h1{margin:0;font-size:29px}.head p{margin:6px 0;color:#6b7280}.btn{display:inline-block;border:0;border-radius:8px;padding:10px 14px;background:#eef2f7;font-weight:700;cursor:pointer}.green{background:#0a9b5b;color:#fff}.blue{background:#2f7de1;color:#fff}.red{background:#d94841;color:#fff}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,.panel{background:#fff;border:1px solid #e7eaf0;border-radius:12px;padding:17px}.label{font-size:12px;font-weight:800;color:#5b6775;text-transform:uppercase}.num{font-size:27px;font-weight:800;margin-top:8px}.muted{color:#6b7280;font-size:13px}.money{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:15px}.money .card{color:#fff;border:0}.money .g{background:linear-gradient(135deg,#079b5d,#087445)}.money .o{background:linear-gradient(135deg,#ef7b00,#d54c00)}.money .b{background:linear-gradient(135deg,#198ed1,#1267b0)}.panel{margin-top:15px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px;border-bottom:1px solid #edf0f3;font-size:14px;vertical-align:middle}th{font-size:12px;color:#667481;text-transform:uppercase}.tag{padding:5px 8px;border-radius:999px;font-size:11px;font-weight:800;display:inline-block}.ok{background:#e7f8ef;color:#087646}.bad{background:#fff0ec;color:#b6371e}.pending{background:#fff6df;color:#8c6200}.empty{text-align:center;padding:38px;color:#7a8592}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:13px}.field label{display:block;font-size:12px;font-weight:800;margin-bottom:6px;color:#52606d}.field input,.field select{width:100%;padding:11px;border:1px solid #d7dde5;border-radius:8px;font:inherit}.check{display:flex;align-items:center;gap:8px;padding-top:25px}.check input{width:auto}.full{grid-column:1/-1}.notice{padding:12px 14px;border-radius:9px;margin-bottom:14px;background:#eef6ff;color:#245b91}.notice.err{background:#fff0ec;color:#9d2d1b}.actions{display:flex;gap:7px;flex-wrap:wrap}.small{padding:7px 9px;font-size:12px}
@media(max-width:900px){.side{width:78px}.brand .text,.user,.nav .txt{display:none}.main{margin-left:78px}.cards{grid-template-columns:repeat(2,1fr)}.money{grid-template-columns:1fr}.content{padding:16px}}@media(max-width:550px){.cards{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.full{grid-column:auto}}
'''
NAV=[('dashboard','▦ Dashboard'),('clients','👥 Clientes'),('finances','▣ Finanzas'),('invoices','▤ Facturas'),('payments','💳 Pagos pendientes'),('routers','⌁ Routers'),('plans','◉ Planes'),('zones','⌖ Zonas'),('whatsapp','◯ WhatsApp'),('support','◉ Soporte Técnico'),('admin','⚙ Administración')]

def shell(title,body,active='dashboard'):
    nav=''.join(f'<a class="{"on" if k==active else ""}" href="{url_for(k)}"><span class="txt">{n}</span></a>' for k,n in NAV)
    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav></aside><main class="main"><header class="top"><div><small>BIENVENIDO</small><b>INTER Flash</b></div><a href="{{url_for('logout')}}">Salir</a></header><section class="content">{{body|safe}}</section></main></body></html>''',title=title,css=CSS,nav=nav,body=body)

LOGIN='''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash</title><style>body{margin:0;font-family:Arial;background:linear-gradient(135deg,#101722,#17394b);display:grid;place-items:center;min-height:100vh}.box{width:min(410px,92vw);background:white;padding:32px;border-radius:18px;box-shadow:0 25px 70px #0006}input,button{width:100%;box-sizing:border-box;padding:13px;margin:7px 0;border:1px solid #d6dbe2;border-radius:9px;font-size:16px}button{background:#0a9b5b;color:#fff;border:0;font-weight:800}.err{background:#fff0f0;color:#a11;padding:10px;border-radius:8px}</style></head><body><form class="box" method="post"><h1>INTER Flash</h1><p>Acceso al panel de administración</p>{{error|safe}}<input name="username" placeholder="Usuario" required><input type="password" name="password" placeholder="Contraseña" required><button>Entrar</button></form></body></html>'''

@app.get('/health')
def health(): return 'ok',200
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        if request.form.get('username')==USER and request.form.get('password')==PASSWORD:
            r=make_response(redirect(url_for('dashboard'))); r.set_cookie('if_session','ok',httponly=True,secure=True,samesite='Lax'); return r
        return render_template_string(LOGIN,error='<div class="err">Usuario o contraseña incorrectos.</div>'),401
    return render_template_string(LOGIN,error='')
@app.get('/logout')
def logout():
    r=make_response(redirect(url_for('login'))); r.delete_cookie('if_session'); return r
@app.get('/')
def home(): return redirect(url_for('dashboard') if auth() else url_for('login'))

@app.get('/dashboard')
def dashboard():
    if not auth(): return redirect(url_for('login'))
    c=con(); total=c.execute('select count(*) c from clients').fetchone()['c']; active=c.execute("select count(*) c from clients where status='ACTIVO'").fetchone()['c']; suspended=c.execute("select count(*) c from clients where status='SUSPENDIDO'").fetchone()['c']; pending=c.execute("select count(*) c from invoices where status='PENDIENTE'").fetchone()['c']; money=c.execute("select coalesce(sum(amount),0) s from invoices where status='PENDIENTE'").fetchone()['s']; paid=c.execute("select coalesce(sum(amount),0) s from invoices where status='PAGADA'").fetchone()['s']; routers_n=c.execute('select count(*) c from routers').fetchone()['c']; tickets=c.execute("select count(*) c from tickets where status!='CERRADO'").fetchone()['c']; c.close()
    items=[('Clientes totales',total,'Registrados'),('Clientes activos',active,'En servicio'),('Clientes suspendidos',suspended,'Cortados'),('Instalaciones en el mes',0,'Sin canceladas'),('Reporte de pagos',0,'Sin reportes'),('Promesas de pago',0,'Sin solicitudes'),('Tickets',tickets,'Abiertos'),('Vence hoy',0,'Ninguna factura')]
    cards=''.join(f'<div class="card"><div class="label">{a}</div><div class="num">{b}</div><div class="muted">{d}</div></div>' for a,b,d in items)
    body=f'<div class="head"><div><h1>Dashboard</h1><p>Estado actual de tu red</p></div><a class="btn green" href="{url_for("client_new")}">+ Nuevo cliente</a></div><div class="cards">{cards}</div><div class="money"><div class="card g"><div>Pagos registrados</div><div class="num">RD${paid:,.2f}</div></div><div class="card o"><div>Por cobrar</div><div class="num">RD${money:,.2f}</div><div>{pending} facturas pendientes</div></div><div class="card b"><div>Routers</div><div class="num">{routers_n}</div></div></div>'
    return shell('Dashboard',body,'dashboard')

@app.get('/clients')
def clients():
    if not auth(): return redirect(url_for('login'))
    c=con(); rows=c.execute('select c.*,p.name plan,z.name zone from clients c left join plans p on p.id=c.plan_id left join zones z on z.id=c.zone_id order by c.id desc').fetchall(); c.close()
    trs=''.join(f"<tr><td>#{r['id']}</td><td><b>{e(r['name'])}</b><br><small>{e(r['phone'])}</small></td><td>{e(r['pppoe']) or '-'}</td><td>{e(r['plan']) or '-'}</td><td>{e(r['zone']) or '-'}</td><td><span class='tag {'ok' if r['status']=='ACTIVO' else 'bad'}'>{e(r['status'])}</span></td><td><a class='btn small' href='{url_for('client_toggle',id=r['id'])}'>Cambiar</a></td></tr>" for r in rows)
    return shell('Clientes',f'<div class="head"><div><h1>Clientes</h1><p>Gestión de abonados</p></div><a class="btn green" href="{url_for("client_new")}">+ Nuevo cliente</a></div><div class="panel"><table><tr><th>ID</th><th>Cliente</th><th>PPPoE</th><th>Plan</th><th>Zona</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=7 class=empty>No hay clientes todavía.</td></tr>"}</table></div>','clients')

@app.route('/clients/new',methods=['GET','POST'])
def client_new():
    if not auth(): return redirect(url_for('login'))
    c=con()
    if request.method=='POST':
        c.execute('insert into clients(name,phone,pppoe,plan_id,zone_id) values(?,?,?,?,?)',(request.form['name'],request.form.get('phone'),request.form.get('pppoe'),request.form.get('plan_id') or None,request.form.get('zone_id') or None)); c.commit(); c.close(); return redirect(url_for('clients'))
    ps=c.execute('select * from plans order by name').fetchall(); zs=c.execute('select * from zones order by name').fetchall(); c.close(); po=''.join(f"<option value='{x['id']}'>{e(x['name'])} · {e(x['speed'])}</option>" for x in ps); zo=''.join(f"<option value='{x['id']}'>{e(x['name'])}</option>" for x in zs)
    body=f'<div class="head"><div><h1>Nuevo cliente</h1><p>Registrar abonado</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Nombre completo</label><input name="name" required></div><div class="field"><label>Teléfono</label><input name="phone"></div><div class="field"><label>Usuario PPPoE</label><input name="pppoe"></div><div class="field"><label>Plan</label><select name="plan_id"><option value="">Sin plan</option>{po}</select></div><div class="field"><label>Zona</label><select name="zone_id"><option value="">Sin zona</option>{zo}</select></div><div class="full"><button class="btn green">Guardar cliente</button></div></form></div>'
    return shell('Nuevo cliente',body,'clients')
@app.get('/clients/<int:id>/toggle')
def client_toggle(id):
    if not auth(): return redirect(url_for('login'))
    c=con(); r=c.execute('select status from clients where id=?',(id,)).fetchone()
    if r: c.execute('update clients set status=? where id=?',('SUSPENDIDO' if r['status']=='ACTIVO' else 'ACTIVO',id)); c.commit()
    c.close(); return redirect(url_for('clients'))

@app.route('/plans',methods=['GET','POST'])
def plans():
    if not auth(): return redirect(url_for('login'))
    c=con()
    if request.method=='POST': c.execute('insert into plans(name,speed,price) values(?,?,?)',(request.form['name'],request.form['speed'],request.form['price'])); c.commit(); c.close(); return redirect(url_for('plans'))
    rows=c.execute('select * from plans order by price').fetchall(); c.close(); trs=''.join(f"<tr><td>{e(r['name'])}</td><td>{e(r['speed'])}</td><td>RD${r['price']:,.2f}</td></tr>" for r in rows)
    body=f'<div class="head"><div><h1>Planes</h1><p>Simple Queue · PPPoE</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Nombre</label><input name="name" required></div><div class="field"><label>Velocidad</label><input name="speed" placeholder="40/40 Mbps" required></div><div class="field"><label>Precio RD$</label><input name="price" type="number" step="0.01" required></div><div class="full"><button class="btn blue">+ Nuevo plan</button></div></form></div><div class="panel"><table><tr><th>Plan</th><th>Velocidad</th><th>Precio</th></tr>{trs or "<tr><td colspan=3 class=empty>No hay planes todavía.</td></tr>"}</table></div>'
    return shell('Planes',body,'plans')

@app.route('/zones',methods=['GET','POST'])
def zones():
    if not auth(): return redirect(url_for('login'))
    c=con()
    if request.method=='POST': c.execute('insert into zones(name,due_day,cut_day,cut_time) values(?,?,?,?)',(request.form['name'],request.form['due_day'],request.form['cut_day'],request.form['cut_time'])); c.commit(); c.close(); return redirect(url_for('zones'))
    rows=c.execute('select * from zones order by name').fetchall(); c.close(); trs=''.join(f"<tr><td>{e(r['name'])}</td><td>Día {r['due_day']}</td><td>Día {r['cut_day']}</td><td>{e(r['cut_time'])}</td></tr>" for r in rows)
    body=f'<div class="head"><div><h1>Zonas</h1><p>Vencimiento y corte</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Zona</label><input name="name" required></div><div class="field"><label>Día vencimiento</label><input name="due_day" type="number" value="30" required></div><div class="field"><label>Día corte</label><input name="cut_day" type="number" value="6" required></div><div class="field"><label>Hora corte</label><input name="cut_time" type="time" value="14:00" required></div><div class="full"><button class="btn green">Guardar zona</button></div></form></div><div class="panel"><table><tr><th>Zona</th><th>Vence</th><th>Corte</th><th>Hora</th></tr>{trs or "<tr><td colspan=4 class=empty>No hay zonas todavía.</td></tr>"}</table></div>'
    return shell('Zonas',body,'zones')

@app.route('/invoices',methods=['GET','POST'])
def invoices():
    if not auth(): return redirect(url_for('login'))
    c=con()
    if request.method=='POST': c.execute('insert into invoices(client_id,concept,amount,issue_date,due_date) values(?,?,?,?,?)',(request.form['client_id'],request.form['concept'],request.form['amount'],request.form['issue_date'],request.form['due_date'])); c.commit(); c.close(); return redirect(url_for('invoices'))
    rows=c.execute('select i.*,c.name client from invoices i join clients c on c.id=i.client_id order by i.id desc').fetchall(); cl=c.execute('select * from clients order by name').fetchall(); c.close(); opts=''.join(f"<option value='{x['id']}'>{e(x['name'])}</option>" for x in cl); t=date.today().isoformat(); trs=''.join(f"<tr><td>{e(r['client'])}</td><td>{e(r['concept'])}</td><td>RD${r['amount']:,.2f}</td><td>{e(r['due_date'])}</td><td><span class='tag {'ok' if r['status']=='PAGADA' else 'pending'}'>{e(r['status'])}</span></td><td>{'' if r['status']=='PAGADA' else '<a class=btn href=/invoices/'+str(r['id'])+'/pay>Cobrar</a>'}</td></tr>" for r in rows)
    body=f'<div class="head"><div><h1>Gestión de Facturas</h1><p>Facturación y cobros</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Cliente</label><select name="client_id" required><option value="">Selecciona</option>{opts}</select></div><div class="field"><label>Concepto</label><input name="concept" value="Servicio de Internet" required></div><div class="field"><label>Monto</label><input name="amount" type="number" step="0.01" required></div><div class="field"><label>Emisión</label><input name="issue_date" type="date" value="{t}" required></div><div class="field"><label>Vencimiento</label><input name="due_date" type="date" value="{t}" required></div><div class="full"><button class="btn green">Crear factura</button></div></form></div><div class="panel"><table><tr><th>Cliente</th><th>Concepto</th><th>Monto</th><th>Vence</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=6 class=empty>No hay facturas todavía.</td></tr>"}</table></div>'
    return shell('Facturas',body,'invoices')
@app.get('/invoices/<int:id>/pay')
def invoice_pay(id):
    if not auth(): return redirect(url_for('login'))
    c=con(); c.execute("update invoices set status='PAGADA',paid_at=? where id=?",(date.today().isoformat(),id)); c.commit(); c.close(); return redirect(url_for('invoices'))
@app.get('/payments')
def payments():
    if not auth(): return redirect(url_for('login'))
    c=con(); rows=c.execute("select i.*,c.name client from invoices i join clients c on c.id=i.client_id where i.status='PENDIENTE' order by i.due_date").fetchall(); c.close(); trs=''.join(f"<tr><td>{e(r['client'])}</td><td>{e(r['concept'])}</td><td>RD${r['amount']:,.2f}</td><td>{e(r['due_date'])}</td><td><a class='btn green small' href='/invoices/{r['id']}/pay'>Registrar pago</a></td></tr>" for r in rows)
    return shell('Pagos pendientes',f'<div class="head"><div><h1>Pagos Pendientes</h1><p>Facturas por cobrar</p></div></div><div class="panel"><table><tr><th>Cliente</th><th>Concepto</th><th>Monto</th><th>Vence</th><th></th></tr>{trs or "<tr><td colspan=5 class=empty>No hay pagos pendientes.</td></tr>"}</table></div>','payments')

def router_pool(r):
    password=dec(r['password_enc'])
    if not r['username'] or not password: raise ValueError('Falta usuario o contraseña del MikroTik.')
    pool=routeros_api.RouterOsApiPool(r['host'],username=r['username'],password=password,port=int(r['port'] or 8728),plaintext_login=True,use_ssl=bool(r['use_ssl']),ssl_verify=bool(r['verify_ssl']),ssl_verify_hostname=bool(r['verify_ssl']))
    pool.socket_timeout=8
    return pool,pool.get_api()

def router_form(r=None):
    rid=r['id'] if r else None; name=e(r['name']) if r else 'CCR2116'; host=e(r['host']) if r else ''; port=r['port'] if r else 8729; username=e(r['username']) if r else ''; ssl_checked='checked' if (not r or r['use_ssl']) else ''; verify_checked='checked' if (r and r['verify_ssl']) else ''; action=url_for('router_edit',id=rid) if r else url_for('routers')
    return f'''<div class="panel"><form class="grid" method="post" action="{action}"><div class="field"><label>Nombre</label><input name="name" value="{name}" required></div><div class="field"><label>Host / IP accesible desde Internet</label><input name="host" value="{host}" placeholder="ej. vpn.midominio.com" required></div><div class="field"><label>Puerto API</label><input name="port" type="number" value="{port}" required></div><div class="field"><label>Usuario API dedicado</label><input name="username" value="{username}" autocomplete="off" required></div><div class="field"><label>Contraseña {('(dejar vacío para conservarla)' if r else '')}</label><input type="password" name="password" autocomplete="new-password" {'required' if not r else ''}></div><div class="check"><input type="checkbox" name="use_ssl" value="1" {ssl_checked}> <span>Usar API SSL (recomendado)</span></div><div class="check"><input type="checkbox" name="verify_ssl" value="1" {verify_checked}> <span>Verificar certificado SSL</span></div><div class="full"><div class="notice">Para seguridad, usa un usuario exclusivo para esta plataforma. La contraseña se guarda cifrada y nunca se muestra.</div><button class="btn green">Guardar MikroTik</button></div></form></div>'''

@app.route('/routers',methods=['GET','POST'])
def routers():
    if not auth(): return redirect(url_for('login'))
    c=con()
    if request.method=='POST':
        c.execute('insert into routers(name,host,port,status,username,password_enc,use_ssl,verify_ssl) values(?,?,?,?,?,?,?,?)',(request.form['name'],request.form['host'].strip(),int(request.form['port']), 'PENDIENTE',request.form['username'].strip(),enc(request.form['password']),1 if request.form.get('use_ssl') else 0,1 if request.form.get('verify_ssl') else 0)); c.commit(); c.close(); return redirect(url_for('routers'))
    rows=c.execute('select * from routers order by id desc').fetchall(); c.close(); msg=request.args.get('msg',''); err=request.args.get('err',''); note=(f'<div class="notice">{e(msg)}</div>' if msg else '')+(f'<div class="notice err">{e(err)}</div>' if err else '')
    trs=''
    for r in rows:
        cls='ok' if r['status']=='ONLINE' else ('bad' if r['status']=='ERROR' else 'pending')
        details=' · '.join(x for x in [e(r['identity']),e(r['model']),e(r['ros_version'])] if x)
        actions=f"<div class='actions'><a class='btn blue small' href='{url_for('router_test',id=r['id'])}'>Probar conexión</a><a class='btn small' href='{url_for('router_pppoe',id=r['id'])}'>Ver PPPoE</a><a class='btn small' href='{url_for('router_edit',id=r['id'])}'>Editar</a></div>"
        trs+=f"<tr><td><b>{e(r['name'])}</b><br><small>{details}</small></td><td>{e(r['host'])}:{r['port']}<br><small>{'SSL' if r['use_ssl'] else 'Sin SSL'}</small></td><td><span class='tag {cls}'>{e(r['status'])}</span><br><small>{e(r['last_seen'])}</small></td><td>{r['pppoe_active'] or 0}</td><td>{actions}</td></tr>"
    body=f'<div class="head"><div><h1>Routers</h1><p>Conexión real con MikroTik RouterOS</p></div></div>{note}{router_form()}<div class="panel"><table><tr><th>Router</th><th>Host</th><th>Estado</th><th>PPPoE activos</th><th>Acciones</th></tr>{trs or "<tr><td colspan=5 class=empty>No hay MikroTik configurados todavía.</td></tr>"}</table></div>'
    return shell('Routers',body,'routers')

@app.route('/routers/<int:id>/edit',methods=['GET','POST'])
def router_edit(id):
    if not auth(): return redirect(url_for('login'))
    c=con(); r=c.execute('select * from routers where id=?',(id,)).fetchone()
    if not r: c.close(); return redirect(url_for('routers',err='Router no encontrado'))
    if request.method=='POST':
        pw=request.form.get('password') or ''
        pw_enc=enc(pw) if pw else r['password_enc']
        c.execute('update routers set name=?,host=?,port=?,username=?,password_enc=?,use_ssl=?,verify_ssl=?,status=? where id=?',(request.form['name'],request.form['host'].strip(),int(request.form['port']),request.form['username'].strip(),pw_enc,1 if request.form.get('use_ssl') else 0,1 if request.form.get('verify_ssl') else 0,'PENDIENTE',id)); c.commit(); c.close(); return redirect(url_for('routers',msg='MikroTik actualizado. Pulsa Probar conexión.'))
    c.close(); return shell('Editar MikroTik',f'<div class="head"><div><h1>Editar MikroTik</h1><p>{e(r["name"])}</p></div><a class="btn" href="{url_for("routers")}">Volver</a></div>{router_form(r)}','routers')

@app.get('/routers/<int:id>/test')
def router_test(id):
    if not auth(): return redirect(url_for('login'))
    c=con(); r=c.execute('select * from routers where id=?',(id,)).fetchone(); c.close()
    if not r: return redirect(url_for('routers',err='Router no encontrado'))
    pool=None
    try:
        pool,api=router_pool(r)
        ident=(api.get_resource('/system/identity').get() or [{}])[0]
        res=(api.get_resource('/system/resource').get() or [{}])[0]
        active=api.get_resource('/ppp/active').get()
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c=con(); c.execute('update routers set status=?,identity=?,model=?,ros_version=?,pppoe_active=?,last_seen=?,last_error=? where id=?',('ONLINE',ident.get('name',''),res.get('board-name') or res.get('platform',''),res.get('version',''),len(active),now,'',id)); c.commit(); c.close()
        return redirect(url_for('routers',msg=f"Conexión correcta: {ident.get('name',r['name'])}. PPPoE activos: {len(active)}"))
    except Exception as ex:
        msg=str(ex)[:300]; c=con(); c.execute('update routers set status=?,last_error=? where id=?',('ERROR',msg,id)); c.commit(); c.close(); return redirect(url_for('routers',err='No se pudo conectar al MikroTik: '+msg))
    finally:
        if pool:
            try: pool.disconnect()
            except Exception: pass

@app.get('/routers/<int:id>/pppoe')
def router_pppoe(id):
    if not auth(): return redirect(url_for('login'))
    c=con(); r=c.execute('select * from routers where id=?',(id,)).fetchone(); c.close()
    if not r: return redirect(url_for('routers',err='Router no encontrado'))
    pool=None
    try:
        pool,api=router_pool(r); secrets=api.get_resource('/ppp/secret').get(); active=api.get_resource('/ppp/active').get(); active_names={x.get('name') for x in active}; trs=''
        for s in secrets:
            name=s.get('name',''); online=name in active_names; cls='ok' if online else 'pending'; state='ONLINE' if online else 'OFFLINE'
            trs+=f"<tr><td><b>{e(name)}</b></td><td>{e(s.get('service',''))}</td><td>{e(s.get('profile',''))}</td><td>{e(s.get('remote-address','')) or '-'}</td><td>{e(s.get('caller-id','')) or '-'}</td><td><span class='tag {cls}'>{state}</span></td></tr>"
        body=f'<div class="head"><div><h1>PPPoE · {e(r["name"])}</h1><p>{len(active)} conectados · {len(secrets)} secretos PPPoE</p></div><a class="btn" href="{url_for("routers")}">Volver a Routers</a></div><div class="panel"><table><tr><th>Usuario</th><th>Servicio</th><th>Perfil</th><th>IP remota</th><th>Caller ID</th><th>Estado</th></tr>{trs or "<tr><td colspan=6 class=empty>No hay secretos PPPoE.</td></tr>"}</table></div>'
        return shell('PPPoE',body,'routers')
    except Exception as ex:
        return shell('Error MikroTik',f'<div class="head"><div><h1>No se pudo leer PPPoE</h1><p>{e(str(ex))}</p></div><a class="btn" href="{url_for("routers")}">Volver</a></div>','routers')
    finally:
        if pool:
            try: pool.disconnect()
            except Exception: pass

@app.get('/finances')
def finances():
    if not auth(): return redirect(url_for('login'))
    c=con(); a=c.execute("select coalesce(sum(amount),0) s from invoices where status='PAGADA'").fetchone()['s']; p=c.execute("select coalesce(sum(amount),0) s from invoices where status='PENDIENTE'").fetchone()['s']; c.close(); return shell('Finanzas',f'<div class="head"><div><h1>Finanzas</h1><p>Resumen financiero</p></div></div><div class="money"><div class="card g"><div>Cobrado</div><div class="num">RD${a:,.2f}</div></div><div class="card o"><div>Por cobrar</div><div class="num">RD${p:,.2f}</div></div><div class="card b"><div>Balance</div><div class="num">RD${a-p:,.2f}</div></div></div>','finances')
@app.route('/support',methods=['GET','POST'])
def support():
    if not auth(): return redirect(url_for('login'))
    c=con()
    if request.method=='POST': c.execute('insert into tickets(subject,client) values(?,?)',(request.form['subject'],request.form.get('client'))); c.commit(); c.close(); return redirect(url_for('support'))
    rows=c.execute('select * from tickets order by id desc').fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td>{e(r['subject'])}</td><td>{e(r['client']) or '-'}</td><td><span class='tag pending'>{e(r['status'])}</span></td></tr>" for r in rows); body=f'<div class="head"><div><h1>Soporte Técnico</h1><p>Tickets e incidencias</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Asunto</label><input name="subject" required></div><div class="field"><label>Cliente</label><input name="client"></div><div class="full"><button class="btn blue">Crear ticket</button></div></form></div><div class="panel"><table><tr><th>ID</th><th>Asunto</th><th>Cliente</th><th>Estado</th></tr>{trs or "<tr><td colspan=4 class=empty>No hay tickets.</td></tr>"}</table></div>'; return shell('Soporte',body,'support')
@app.get('/whatsapp')
def whatsapp():
    if not auth(): return redirect(url_for('login'))
    return shell('WhatsApp','<div class="head"><div><h1>WhatsApp</h1><p>Mensajería y automatizaciones</p></div></div><div class="panel"><div class="empty">Interfaz lista para conectar WhatsApp.</div></div>','whatsapp')
@app.get('/admin')
def admin():
    if not auth(): return redirect(url_for('login'))
    return shell('Administración','<div class="head"><div><h1>Administración</h1><p>Configuración general</p></div></div><div class="panel"><table><tr><td>Empresa</td><td><b>INTER Flash</b></td></tr><tr><td>Base de datos</td><td><span class="tag ok">PERSISTENTE</span></td></tr><tr><td>Integración MikroTik</td><td><span class="tag ok">LISTA</span></td></tr></table></div>','admin')

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','8080')))
