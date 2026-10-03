import os
import sqlite3
from datetime import date, datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, get_flashed_messages

APP_NAME = "INTER Flash ISP Manager"
DB_PATH = os.getenv("DB_PATH", "/data/interflash_isp_manager.db")
ADMIN_USER = os.getenv("ADMIN_USER", "manuel")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")

app = Flask(__name__)
app.secret_key = SECRET_KEY


def db():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS plans(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      download_mbps INTEGER DEFAULT 0,
      upload_mbps INTEGER DEFAULT 0,
      price REAL DEFAULT 0,
      active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS customers(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT UNIQUE,
      name TEXT NOT NULL,
      phone TEXT,
      document TEXT,
      email TEXT,
      address TEXT,
      zone TEXT,
      pppoe TEXT,
      ip_address TEXT,
      onu_serial TEXT,
      plan_id INTEGER,
      status TEXT DEFAULT 'ACTIVO',
      due_day INTEGER DEFAULT 30,
      created_at TEXT,
      FOREIGN KEY(plan_id) REFERENCES plans(id)
    );
    CREATE TABLE IF NOT EXISTS invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      customer_id INTEGER NOT NULL,
      concept TEXT NOT NULL,
      amount REAL NOT NULL,
      issue_date TEXT NOT NULL,
      due_date TEXT NOT NULL,
      status TEXT DEFAULT 'PENDIENTE',
      paid_at TEXT,
      FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS payments(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      customer_id INTEGER NOT NULL,
      invoice_id INTEGER,
      amount REAL NOT NULL,
      method TEXT DEFAULT 'EFECTIVO',
      reference TEXT,
      paid_at TEXT NOT NULL,
      FOREIGN KEY(customer_id) REFERENCES customers(id),
      FOREIGN KEY(invoice_id) REFERENCES invoices(id)
    );
    CREATE TABLE IF NOT EXISTS routers(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      identity TEXT,
      host TEXT,
      status TEXT DEFAULT 'PENDIENTE',
      pppoe_total INTEGER DEFAULT 0,
      pppoe_active INTEGER DEFAULT 0,
      last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS audit_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action TEXT NOT NULL,
      detail TEXT,
      created_at TEXT NOT NULL
    );
    ''')
    if c.execute('SELECT COUNT(*) c FROM plans').fetchone()['c'] == 0:
        c.executemany(
            'INSERT INTO plans(name,download_mbps,upload_mbps,price) VALUES(?,?,?,?)',
            [
                ('Básico 20', 20, 20, 800),
                ('Básico 40', 40, 40, 1000),
                ('Avanzado 60', 60, 60, 1300),
                ('Premium 100', 100, 100, 1500),
                ('Ultra 200', 200, 200, 2000),
                ('Ultra 300', 300, 300, 3000),
            ]
        )
    c.commit()
    c.close()


init_db()


def logged_in():
    return session.get('auth') is True


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper


def audit(action, detail=''):
    c = db()
    c.execute('INSERT INTO audit_log(action,detail,created_at) VALUES(?,?,?)',
              (action, detail, datetime.now().isoformat(timespec='seconds')))
    c.commit()
    c.close()


BASE_CSS = '''
*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:Inter,Segoe UI,Arial,sans-serif;background:#08111e;color:#e8eef8}a{text-decoration:none;color:inherit}button,input,select,textarea{font:inherit}.app{display:grid;grid-template-columns:248px 1fr;min-height:100vh}.side{background:#081522;border-right:1px solid #193047;padding:18px 14px;position:sticky;top:0;height:100vh;overflow:auto}.brand{display:flex;align-items:center;gap:10px;padding:4px 8px 20px}.brandmark{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#0ea5e9,#2563eb);display:grid;place-items:center;font-weight:900}.brand b{font-size:18px}.brand small{display:block;color:#7f94aa;margin-top:2px}.nav a{display:flex;gap:10px;align-items:center;padding:11px 12px;margin:3px 0;border-radius:9px;color:#b9c7d6}.nav a:hover,.nav a.on{background:#0d63f6;color:#fff}.nav .sep{height:1px;background:#183047;margin:12px 6px}.system{margin-top:18px;padding:12px;border:1px solid #183047;border-radius:12px;color:#8ca0b6;font-size:12px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#17d67d;margin-right:7px}.main{min-width:0}.top{height:70px;border-bottom:1px solid #193047;background:#0a1624cc;backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:space-between;padding:0 24px;position:sticky;top:0;z-index:5}.top .search{width:min(560px,52vw);background:#111f2f;border:1px solid #263a50;border-radius:9px;padding:11px 14px;color:white}.top .user{color:#b6c6d8;font-size:13px}.content{padding:22px}.head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.head h1{margin:0;font-size:25px}.head p{margin:4px 0 0;color:#7f94aa}.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:9px 13px;border-radius:8px;border:1px solid #2a4058;background:#132336;color:#e8eef8;font-weight:700;cursor:pointer}.btn:hover{filter:brightness(1.12)}.green{background:#08b96d;border-color:#08b96d;color:#fff}.blue{background:#0d63f6;border-color:#0d63f6;color:white}.grid6{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:12px}.kpi{border:1px solid #22374e;border-radius:12px;padding:16px;background:#0d1a29;min-height:106px}.kpi .label{font-size:11px;color:#eef6ff;text-transform:uppercase;font-weight:800}.kpi .value{font-size:26px;font-weight:900;margin-top:7px}.kpi .sub{font-size:11px;color:#eef6ff;margin-top:6px}.blue1{background:linear-gradient(135deg,#0c4edb,#0a77ff)}.green1{background:linear-gradient(135deg,#0d9c5f,#05c678)}.orange1{background:linear-gradient(135deg,#e8790b,#ff9e24)}.purple1{background:linear-gradient(135deg,#7426d9,#9b3cf7)}.red1{background:linear-gradient(135deg,#d93648,#ef5362)}.cyan1{background:linear-gradient(135deg,#078faa,#10bfd1)}.panel{background:#0d1a29;border:1px solid #22374e;border-radius:12px;padding:16px;margin-top:14px;overflow:auto}.toolbar{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:13px}.field{background:#101f30;border:1px solid #263b51;color:#e7eef8;border-radius:8px;padding:10px 12px}.toolbar .field{min-width:190px}.table{width:100%;border-collapse:collapse}.table th,.table td{padding:11px 10px;border-bottom:1px solid #1b3045;text-align:left;font-size:13px}.table th{color:#92a5b8;font-size:11px;text-transform:uppercase}.tag{display:inline-flex;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800}.ok{background:#063f2a;color:#39e998}.bad{background:#4a161b;color:#ff7b86}.warn{background:#4e3707;color:#ffc94e}.muted{color:#8397aa}.cards2{display:grid;grid-template-columns:2fr 1fr;gap:14px}.formgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.formgrid label{font-size:12px;color:#9aadc1;font-weight:700}.formgrid input,.formgrid select,.formgrid textarea{width:100%;margin-top:6px;background:#101f30;border:1px solid #263b51;color:#fff;border-radius:8px;padding:10px}.full{grid-column:1/-1}.flash{padding:10px 12px;border-radius:8px;background:#0f5132;color:#d1fae5;margin-bottom:12px}.loginwrap{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 30% 10%,#173b63,#08111e 50%)}.loginbox{width:min(420px,92vw);background:#0d1a29;border:1px solid #24415f;border-radius:18px;padding:30px;box-shadow:0 25px 80px #0008}.loginbox input{width:100%;margin:7px 0;padding:12px;background:#101f30;border:1px solid #29425b;border-radius:8px;color:white}.loginbox button{width:100%;margin-top:8px}.notice{padding:10px;border-radius:8px;background:#4a161b;color:#fecaca;margin-bottom:10px}@media(max-width:1200px){.grid6{grid-template-columns:repeat(3,1fr)}}@media(max-width:850px){.app{grid-template-columns:80px 1fr}.side{padding:14px 8px}.brand .txt,.nav .txt,.system{display:none}.grid6{grid-template-columns:repeat(2,1fr)}.cards2{grid-template-columns:1fr}.formgrid{grid-template-columns:1fr}.full{grid-column:auto}}@media(max-width:520px){.grid6{grid-template-columns:1fr}.content{padding:14px}.top{padding:0 14px}.top .search{width:62vw}}
'''

NAV = [
    ('dashboard','⌂','Dashboard'),('customers','👥','Clientes'),('invoices','▤','Facturas'),
    ('payments','💳','Pagos'),('plans','◉','Planes'),('routers','⌁','Routers'),
    ('audit_page','☷','Auditoría')
]


def shell(title, body, active='dashboard'):
    links=''.join(f'<a class="{"on" if active==ep else ""}" href="{url_for(ep)}"><span>{ic}</span><span class="txt">{label}</span></a>' for ep,ic,label in NAV)
    msgs=''.join(f'<div class="flash">{m}</div>' for m in get_flashed_messages())
    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><div class="app"><aside class="side"><div class="brand"><div class="brandmark">IF</div><div class="txt"><b>INTER Flash</b><small>ISP Manager</small></div></div><nav class="nav">{{links|safe}}<div class="sep"></div><a href="{{url_for('logout')}}"><span>↪</span><span class="txt">Salir</span></a></nav><div class="system"><span class="dot"></span>Sistema en línea<br><br>MikroTik: pendiente de conectar</div></aside><main class="main"><header class="top"><input class="search" placeholder="Buscar clientes, facturas, ONU, IP..." onkeydown="if(event.key==='Enter'){location.href='{{url_for('customers')}}?q='+encodeURIComponent(this.value)}"><div class="user">Administrador · {{admin}}</div></header><section class="content">{{msgs|safe}}{{body|safe}}</section></main></div></body></html>''', title=title, css=BASE_CSS, links=links, body=body, admin=ADMIN_USER, msgs=msgs)


@app.route('/login', methods=['GET','POST'])
def login():
    error=''
    if request.method=='POST':
        if not ADMIN_PASSWORD:
            error='Falta configurar ADMIN_PASSWORD en Railway.'
        elif request.form.get('username')==ADMIN_USER and request.form.get('password')==ADMIN_PASSWORD:
            session.clear(); session['auth']=True; audit('LOGIN', ADMIN_USER)
            return redirect(url_for('dashboard'))
        else:
            error='Usuario o contraseña incorrectos.'
    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash ISP Manager</title><style>{{css}}</style></head><body><div class="loginwrap"><form class="loginbox" method="post"><div class="brand" style="padding-left:0"><div class="brandmark">IF</div><div class="txt"><b>INTER Flash</b><small>ISP Manager · Nuevo sistema</small></div></div><h2>Administración ISP</h2><p class="muted">Proyecto nuevo e independiente</p>{% if error %}<div class="notice">{{error}}</div>{% endif %}<input name="username" placeholder="Usuario" required><input type="password" name="password" placeholder="Contraseña" required><button class="btn blue">Entrar</button></form></div></body></html>''', css=BASE_CSS, error=error)


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.get('/health')
def health():
    return {'ok': True, 'app': APP_NAME}, 200


@app.get('/')
def home():
    return redirect(url_for('dashboard') if logged_in() else url_for('login'))


@app.get('/dashboard')
@login_required
def dashboard():
    c=db()
    total=c.execute('SELECT COUNT(*) c FROM customers').fetchone()['c']
    active=c.execute("SELECT COUNT(*) c FROM customers WHERE status='ACTIVO'").fetchone()['c']
    suspended=c.execute("SELECT COUNT(*) c FROM customers WHERE status='SUSPENDIDO'").fetchone()['c']
    pending=c.execute("SELECT COUNT(*) c FROM invoices WHERE status='PENDIENTE'").fetchone()['c']
    pending_money=c.execute("SELECT COALESCE(SUM(amount),0) s FROM invoices WHERE status='PENDIENTE'").fetchone()['s']
    paid_money=c.execute("SELECT COALESCE(SUM(amount),0) s FROM payments").fetchone()['s']
    routers_n=c.execute('SELECT COUNT(*) c FROM routers').fetchone()['c']
    recent=c.execute('''SELECT cu.name,i.amount,i.status,i.due_date FROM invoices i JOIN customers cu ON cu.id=i.customer_id ORDER BY i.id DESC LIMIT 6''').fetchall()
    c.close()
    kpis=[('Clientes totales',total,'Registrados','blue1'),('Clientes activos',active,'En servicio','green1'),('Suspendidos',suspended,'Fuera de servicio','orange1'),('Pagos recibidos',f'RD${paid_money:,.0f}','Acumulado','purple1'),('Facturas pendientes',pending,f'RD${pending_money:,.0f} por cobrar','red1'),('Routers',routers_n,'Configurados','cyan1')]
    cards=''.join(f'<div class="kpi {cls}"><div class="label">{a}</div><div class="value">{b}</div><div class="sub">{d}</div></div>' for a,b,d,cls in kpis)
    rows=''.join(f'<tr><td>{r["name"]}</td><td>RD${r["amount"]:,.2f}</td><td>{r["due_date"]}</td><td><span class="tag {"ok" if r["status"]=="PAGADA" else "warn"}">{r["status"]}</span></td></tr>' for r in recent)
    body=f'''<div class="head"><div><h1>Dashboard</h1><p>Nuevo sistema de administración de clientes ISP</p></div><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div><div class="grid6">{cards}</div><div class="cards2"><div class="panel"><h3>Facturas recientes</h3><table class="table"><tr><th>Cliente</th><th>Monto</th><th>Vence</th><th>Estado</th></tr>{rows or '<tr><td colspan=4 class="muted">Todavía no hay facturas.</td></tr>'}</table></div><div class="panel"><h3>Estado del sistema</h3><p><span class="dot"></span> Aplicación operativa</p><p class="muted">Base separada del sistema anterior.</p><p class="muted">La conexión con MikroTik se agregará después de validar esta base.</p></div></div>'''
    return shell('Dashboard',body,'dashboard')


@app.get('/customers')
@login_required
def customers():
    q=(request.args.get('q') or '').strip()
    c=db()
    sql='''SELECT cu.*,p.name plan_name,p.price plan_price FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id'''
    args=[]
    if q:
        sql += " WHERE cu.name LIKE ? OR cu.phone LIKE ? OR cu.document LIKE ? OR cu.pppoe LIKE ? OR cu.ip_address LIKE ? OR cu.onu_serial LIKE ?"
        like=f'%{q}%'; args=[like]*6
    sql += ' ORDER BY cu.id DESC'
    rows=c.execute(sql,args).fetchall(); c.close()
    trs=''
    for r in rows:
        cls='ok' if r['status']=='ACTIVO' else 'bad'
        trs+=f'''<tr><td>#{r['id']}</td><td><b>{r['name']}</b><br><span class="muted">{r['phone'] or ''}</span></td><td>{r['plan_name'] or '-'}</td><td>{r['zone'] or '-'}</td><td>{r['pppoe'] or '-'}</td><td>{r['ip_address'] or '-'}</td><td><span class="tag {cls}">{r['status']}</span></td><td><a class="btn" href="{url_for('customer_edit',id=r['id'])}">Editar</a></td></tr>'''
    body=f'''<div class="head"><div><h1>Clientes</h1><p>Administración completa de abonados</p></div><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div><div class="panel"><form class="toolbar" method="get"><input class="field" name="q" value="{q}" placeholder="Buscar nombre, teléfono, cédula, PPPoE, IP, ONU"><button class="btn blue">Buscar</button><a class="btn" href="{url_for('customers')}">Limpiar</a></form><table class="table"><tr><th>ID</th><th>Cliente</th><th>Plan</th><th>Zona</th><th>PPPoE</th><th>IP</th><th>Estado</th><th></th></tr>{trs or '<tr><td colspan=8 class="muted">No hay clientes todavía.</td></tr>'}</table></div>'''
    return shell('Clientes',body,'customers')


def customer_form(row=None):
    c=db(); plans=c.execute('SELECT * FROM plans WHERE active=1 ORDER BY price').fetchall(); c.close()
    def v(k,default=''):
        if row is None: return default
        return row[k] if k in row.keys() and row[k] is not None else default
    opts=''.join(f'<option value="{p["id"]}" {"selected" if str(v("plan_id"))==str(p["id"]) else ""}>{p["name"]} · {p["download_mbps"]}/{p["upload_mbps"]} Mbps · RD${p["price"]:,.0f}</option>' for p in plans)
    return f'''<form method="post" class="panel formgrid"><div><label>Nombre completo<input name="name" value="{v('name')}" required></label></div><div><label>Teléfono<input name="phone" value="{v('phone')}"></label></div><div><label>Cédula / documento<input name="document" value="{v('document')}"></label></div><div><label>Email<input name="email" value="{v('email')}"></label></div><div class="full"><label>Dirección<textarea name="address" rows="2">{v('address')}</textarea></label></div><div><label>Zona<input name="zone" value="{v('zone')}"></label></div><div><label>Plan<select name="plan_id"><option value="">Sin plan</option>{opts}</select></label></div><div><label>Usuario PPPoE<input name="pppoe" value="{v('pppoe')}"></label></div><div><label>IP asignada<input name="ip_address" value="{v('ip_address')}"></label></div><div><label>Serial ONU<input name="onu_serial" value="{v('onu_serial')}"></label></div><div><label>Día de vencimiento<input type="number" min="1" max="31" name="due_day" value="{v('due_day',30)}"></label></div><div><label>Estado<select name="status"><option {"selected" if v('status','ACTIVO')=='ACTIVO' else ''}>ACTIVO</option><option {"selected" if v('status')=='SUSPENDIDO' else ''}>SUSPENDIDO</option></select></label></div><div class="full"><button class="btn green">Guardar cliente</button></div></form>'''


@app.route('/customers/new', methods=['GET','POST'])
@login_required
def customer_new():
    if request.method=='POST':
        c=db(); cur=c.execute('''INSERT INTO customers(code,name,phone,document,email,address,zone,pppoe,ip_address,onu_serial,plan_id,status,due_day,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (None,request.form['name'].strip(),request.form.get('phone'),request.form.get('document'),request.form.get('email'),request.form.get('address'),request.form.get('zone'),request.form.get('pppoe'),request.form.get('ip_address'),request.form.get('onu_serial'),request.form.get('plan_id') or None,request.form.get('status','ACTIVO'),int(request.form.get('due_day') or 30),date.today().isoformat()))
        cid=cur.lastrowid; c.execute('UPDATE customers SET code=? WHERE id=?',(f'IF-{cid:05d}',cid)); c.commit(); c.close(); audit('CUSTOMER_CREATE',f'#{cid} {request.form["name"]}'); flash('Cliente creado correctamente.'); return redirect(url_for('customers'))
    return shell('Nuevo cliente',f'<div class="head"><div><h1>Nuevo cliente</h1><p>Registro de abonado</p></div></div>{customer_form()}','customers')


@app.route('/customers/<int:id>/edit', methods=['GET','POST'])
@login_required
def customer_edit(id):
    c=db(); row=c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
    if not row: c.close(); return redirect(url_for('customers'))
    if request.method=='POST':
        c.execute('''UPDATE customers SET name=?,phone=?,document=?,email=?,address=?,zone=?,pppoe=?,ip_address=?,onu_serial=?,plan_id=?,status=?,due_day=? WHERE id=?''',
            (request.form['name'].strip(),request.form.get('phone'),request.form.get('document'),request.form.get('email'),request.form.get('address'),request.form.get('zone'),request.form.get('pppoe'),request.form.get('ip_address'),request.form.get('onu_serial'),request.form.get('plan_id') or None,request.form.get('status','ACTIVO'),int(request.form.get('due_day') or 30),id))
        c.commit(); c.close(); audit('CUSTOMER_UPDATE',f'#{id}'); flash('Cliente actualizado.'); return redirect(url_for('customer_edit',id=id))
    c.close()
    body=f'<div class="head"><div><h1>Editar cliente</h1><p>{row["code"] or ""} · {row["name"]}</p></div><a class="btn" href="{url_for("customers")}">Volver</a></div>{customer_form(row)}'
    return shell('Editar cliente',body,'customers')


@app.route('/plans', methods=['GET','POST'])
@login_required
def plans():
    c=db()
    if request.method=='POST':
        c.execute('INSERT INTO plans(name,download_mbps,upload_mbps,price) VALUES(?,?,?,?)',(request.form['name'],int(request.form['download']),int(request.form['upload']),float(request.form['price']))); c.commit(); audit('PLAN_CREATE',request.form['name'])
    rows=c.execute('SELECT * FROM plans ORDER BY price').fetchall(); c.close()
    trs=''.join(f'<tr><td>{r["name"]}</td><td>{r["download_mbps"]}/{r["upload_mbps"]} Mbps</td><td>RD${r["price"]:,.2f}</td><td><span class="tag ok">{"ACTIVO" if r["active"] else "INACTIVO"}</span></td></tr>' for r in rows)
    body=f'''<div class="head"><div><h1>Planes</h1><p>Planes comerciales de Internet</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="name" placeholder="Nombre" required><input class="field" type="number" name="download" placeholder="Bajada Mbps" required><input class="field" type="number" name="upload" placeholder="Subida Mbps" required><input class="field" type="number" step="0.01" name="price" placeholder="Precio RD$" required><button class="btn green">Crear plan</button></form><table class="table"><tr><th>Plan</th><th>Velocidad</th><th>Precio</th><th>Estado</th></tr>{trs}</table></div>'''
    return shell('Planes',body,'plans')


@app.route('/invoices', methods=['GET','POST'])
@login_required
def invoices():
    c=db()
    if request.method=='POST':
        c.execute('INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date) VALUES(?,?,?,?,?)',(int(request.form['customer_id']),request.form['concept'],float(request.form['amount']),request.form['issue_date'],request.form['due_date'])); c.commit(); audit('INVOICE_CREATE',request.form['customer_id'])
    customers=c.execute('SELECT id,name FROM customers ORDER BY name').fetchall()
    rows=c.execute('''SELECT i.*,cu.name customer FROM invoices i JOIN customers cu ON cu.id=i.customer_id ORDER BY i.id DESC''').fetchall(); c.close()
    opts=''.join(f'<option value="{x["id"]}">{x["name"]}</option>' for x in customers); today=date.today().isoformat()
    trs=''
    for r in rows:
        action='' if r['status']=='PAGADA' else f'<form method="post" action="{url_for("invoice_pay",id=r["id"])}"><button class="btn green">Cobrar</button></form>'
        trs+=f'<tr><td>#{r["id"]}</td><td>{r["customer"]}</td><td>{r["concept"]}</td><td>RD${r["amount"]:,.2f}</td><td>{r["due_date"]}</td><td><span class="tag {"ok" if r["status"]=="PAGADA" else "warn"}">{r["status"]}</span></td><td>{action}</td></tr>'
    body=f'''<div class="head"><div><h1>Facturas</h1><p>Facturación y cobros</p></div></div><div class="panel"><form class="toolbar" method="post"><select class="field" name="customer_id" required><option value="">Cliente</option>{opts}</select><input class="field" name="concept" value="Servicio de Internet" required><input class="field" type="number" step="0.01" name="amount" placeholder="Monto" required><input class="field" type="date" name="issue_date" value="{today}" required><input class="field" type="date" name="due_date" value="{today}" required><button class="btn green">Crear factura</button></form><table class="table"><tr><th>#</th><th>Cliente</th><th>Concepto</th><th>Monto</th><th>Vence</th><th>Estado</th><th></th></tr>{trs or '<tr><td colspan=7 class="muted">No hay facturas.</td></tr>'}</table></div>'''
    return shell('Facturas',body,'invoices')


@app.post('/invoices/<int:id>/pay')
@login_required
def invoice_pay(id):
    c=db(); inv=c.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone()
    if inv and inv['status']!='PAGADA':
        now=datetime.now().isoformat(timespec='seconds'); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(now,id)); c.execute('INSERT INTO payments(customer_id,invoice_id,amount,method,paid_at) VALUES(?,?,?,?,?)',(inv['customer_id'],id,inv['amount'],'EFECTIVO',now)); c.commit(); audit('INVOICE_PAID',f'#{id}')
    c.close(); return redirect(url_for('invoices'))


@app.get('/payments')
@login_required
def payments():
    c=db(); rows=c.execute('''SELECT p.*,cu.name customer FROM payments p JOIN customers cu ON cu.id=p.customer_id ORDER BY p.id DESC''').fetchall(); c.close()
    trs=''.join(f'<tr><td>#{r["id"]}</td><td>{r["customer"]}</td><td>RD${r["amount"]:,.2f}</td><td>{r["method"]}</td><td>{r["reference"] or "-"}</td><td>{r["paid_at"]}</td></tr>' for r in rows)
    return shell('Pagos',f'<div class="head"><div><h1>Pagos</h1><p>Historial de cobros registrados</p></div></div><div class="panel"><table class="table"><tr><th>#</th><th>Cliente</th><th>Monto</th><th>Método</th><th>Referencia</th><th>Fecha</th></tr>{trs or "<tr><td colspan=6 class=muted>No hay pagos.</td></tr>"}</table></div>','payments')


@app.route('/routers', methods=['GET','POST'])
@login_required
def routers():
    c=db()
    if request.method=='POST':
        c.execute('INSERT INTO routers(name,identity,host,status,last_seen) VALUES(?,?,?,?,?)',(request.form['name'],request.form.get('identity'),request.form.get('host'),'PENDIENTE',None)); c.commit(); audit('ROUTER_CREATE',request.form['name'])
    rows=c.execute('SELECT * FROM routers ORDER BY id DESC').fetchall(); c.close()
    trs=''.join(f'<tr><td>{r["name"]}</td><td>{r["identity"] or "-"}</td><td>{r["host"] or "-"}</td><td><span class="tag {"ok" if r["status"]=="ONLINE" else "warn"}">{r["status"]}</span></td><td>{r["pppoe_active"]}/{r["pppoe_total"]}</td><td>{r["last_seen"] or "-"}</td></tr>' for r in rows)
    body=f'''<div class="head"><div><h1>Routers</h1><p>Módulo preparado para conectar MikroTik después</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="name" placeholder="Nombre, ej. CCR2116" required><input class="field" name="identity" placeholder="Identity"><input class="field" name="host" placeholder="Host / IP"><button class="btn green">Agregar router</button></form><div class="notice" style="background:#17304b;color:#bfdbfe">Esta página nueva todavía no ejecuta cambios en tu MikroTik. Primero validamos clientes, facturación y diseño; luego conectamos la sincronización de forma segura.</div><table class="table"><tr><th>Router</th><th>Identity</th><th>Host</th><th>Estado</th><th>PPPoE</th><th>Última vez</th></tr>{trs or '<tr><td colspan=6 class="muted">No hay routers configurados.</td></tr>'}</table></div>'''
    return shell('Routers',body,'routers')


@app.get('/audit')
@login_required
def audit_page():
    c=db(); rows=c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT 100').fetchall(); c.close()
    trs=''.join(f'<tr><td>{r["created_at"]}</td><td>{r["action"]}</td><td>{r["detail"] or ""}</td></tr>' for r in rows)
    return shell('Auditoría',f'<div class="head"><div><h1>Auditoría</h1><p>Últimas acciones del sistema</p></div></div><div class="panel"><table class="table"><tr><th>Fecha</th><th>Acción</th><th>Detalle</th></tr>{trs}</table></div>','audit_page')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','8080')))
