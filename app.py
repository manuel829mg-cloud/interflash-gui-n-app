import os, sqlite3, base64, hashlib, html, csv, io, calendar
from datetime import date, datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, render_template_string, session, flash, Response
from cryptography.fernet import Fernet
import routeros_api

APP_NAME = 'INTER Flash'
SECRET = os.getenv('SECRET_KEY', '')
if not SECRET:
    raise RuntimeError('SECRET_KEY no configurada')
USER = os.getenv('ADMIN_USER', 'manuel')
PASSWORD = os.getenv('ADMIN_PASSWORD', '')
DB = os.getenv('DB_PATH', '/app/storage/interflash.db')
PORT = int(os.getenv('PORT', '8080'))
os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)

app = Flask(__name__)
app.secret_key = SECRET
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Lax')
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))


def con():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def addcol(c, table, name, ddl):
    cols = {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
    if name not in cols:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


def init_db():
    c = con()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS plans(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, speed TEXT, price REAL DEFAULT 0,
      description TEXT, active INTEGER DEFAULT 1, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS zones(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, due_day INTEGER DEFAULT 30,
      cut_day INTEGER DEFAULT 6, cut_time TEXT DEFAULT '14:00', active INTEGER DEFAULT 1, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS clients(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, email TEXT, document TEXT,
      address TEXT, pppoe TEXT, status TEXT DEFAULT 'ACTIVO', plan_id INTEGER, zone_id INTEGER,
      ip_address TEXT, mac_address TEXT, service_type TEXT DEFAULT 'PPPoE', notes TEXT,
      installed_at TEXT, created_at TEXT, updated_at TEXT,
      FOREIGN KEY(plan_id) REFERENCES plans(id), FOREIGN KEY(zone_id) REFERENCES zones(id)
    );
    CREATE TABLE IF NOT EXISTS invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT, client_id INTEGER NOT NULL, concept TEXT,
      amount REAL DEFAULT 0, issue_date TEXT, due_date TEXT, status TEXT DEFAULT 'PENDIENTE',
      paid_at TEXT, notes TEXT, created_at TEXT,
      FOREIGN KEY(client_id) REFERENCES clients(id)
    );
    CREATE TABLE IF NOT EXISTS payments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER, client_id INTEGER NOT NULL,
      amount REAL DEFAULT 0, method TEXT, reference TEXT, paid_at TEXT, notes TEXT, created_at TEXT,
      FOREIGN KEY(invoice_id) REFERENCES invoices(id), FOREIGN KEY(client_id) REFERENCES clients(id)
    );
    CREATE TABLE IF NOT EXISTS payment_promises(
      id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL, amount REAL DEFAULT 0,
      promise_date TEXT, status TEXT DEFAULT 'PENDIENTE', notes TEXT, created_at TEXT,
      FOREIGN KEY(client_id) REFERENCES clients(id)
    );
    CREATE TABLE IF NOT EXISTS routers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, host TEXT NOT NULL, port INTEGER DEFAULT 8728,
      username TEXT, password_enc TEXT, use_ssl INTEGER DEFAULT 0, verify_ssl INTEGER DEFAULT 0,
      status TEXT DEFAULT 'PENDIENTE', identity TEXT, model TEXT, ros_version TEXT, pppoe_active INTEGER DEFAULT 0,
      last_seen TEXT, last_error TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS tickets(
      id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, client_id INTEGER, client TEXT,
      phone TEXT, priority TEXT DEFAULT 'MEDIA', status TEXT DEFAULT 'NUEVO', description TEXT,
      assigned_to TEXT, created_at TEXT, updated_at TEXT,
      FOREIGN KEY(client_id) REFERENCES clients(id)
    );
    CREATE TABLE IF NOT EXISTS installations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT NOT NULL, phone TEXT, address TEXT,
      zone_id INTEGER, scheduled_date TEXT, status TEXT DEFAULT 'PENDIENTE', technician TEXT, notes TEXT, created_at TEXT,
      FOREIGN KEY(zone_id) REFERENCES zones(id)
    );
    CREATE TABLE IF NOT EXISTS expenses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, concept TEXT NOT NULL, amount REAL DEFAULT 0, category TEXT,
      expense_date TEXT, notes TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, entity TEXT, entity_id TEXT, detail TEXT, created_at TEXT
    );
    ''')
    migrations = {
      'clients': [('email','TEXT'),('document','TEXT'),('address','TEXT'),('ip_address','TEXT'),('mac_address','TEXT'),('service_type',"TEXT DEFAULT 'PPPoE'"),('notes','TEXT'),('installed_at','TEXT'),('created_at','TEXT'),('updated_at','TEXT')],
      'plans': [('description','TEXT'),('active','INTEGER DEFAULT 1'),('created_at','TEXT')],
      'zones': [('active','INTEGER DEFAULT 1'),('created_at','TEXT')],
      'invoices': [('invoice_no','TEXT'),('notes','TEXT'),('created_at','TEXT')],
      'routers': [('username','TEXT'),('password_enc','TEXT'),('use_ssl','INTEGER DEFAULT 0'),('verify_ssl','INTEGER DEFAULT 0'),('identity','TEXT'),('model','TEXT'),('ros_version','TEXT'),('pppoe_active','INTEGER DEFAULT 0'),('last_seen','TEXT'),('last_error','TEXT'),('created_at','TEXT')],
      'tickets': [('client_id','INTEGER'),('phone','TEXT'),('priority',"TEXT DEFAULT 'MEDIA'"),('description','TEXT'),('assigned_to','TEXT'),('created_at','TEXT'),('updated_at','TEXT')],
    }
    for table, cols in migrations.items():
        for name, ddl in cols:
            addcol(c, table, name, ddl)
    defaults = {
      'company_name':'INTER Flash', 'currency':'RD$', 'whatsapp_number':'',
      'invoice_prefix':'IF', 'invoice_days_before_due':'5', 'cut_delay_days':'6', 'cut_time':'14:00',
      'welcome_message':'¡Hola {nombre}! Bienvenido a INTER Flash.',
      'due_message':'Hola {nombre}. Te recordamos que tienes un balance pendiente de {monto}.',
      'suspended_message':'Hola {nombre}. Tu servicio se encuentra suspendido por balance pendiente.'
    }
    for k,v in defaults.items():
        c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
    c.commit(); c.close()

init_db()

def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def today(): return date.today().isoformat()
def e(v): return html.escape(str(v if v is not None else ''))
def money(v): return f"RD${float(v or 0):,.2f}"
def enc(v): return FERNET.encrypt((v or '').encode()).decode() if v else ''
def dec(v):
    if not v: return ''
    try: return FERNET.decrypt(v.encode()).decode()
    except Exception: return ''

def setting(key, default=''):
    c=con(); r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); c.close(); return r['value'] if r else default

def audit(action, entity='', entity_id='', detail=''):
    c=con(); c.execute('INSERT INTO audit_logs(action,entity,entity_id,detail,created_at) VALUES(?,?,?,?,?)',(action,entity,str(entity_id or ''),detail,now())); c.commit(); c.close()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('auth'):
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def next_invoice_no(c):
    prefix=setting('invoice_prefix','IF'); y=datetime.now().strftime('%Y'); n=c.execute('SELECT COALESCE(MAX(id),0)+1 n FROM invoices').fetchone()['n']; return f'{prefix}-{y}-{int(n):06d}'

def safe_due_date(year, month, day):
    last=calendar.monthrange(year,month)[1]; return date(year,month,min(max(int(day or 30),1),last)).isoformat()

CSS='''
:root{--bg:#f4f6f8;--side:#101821;--green:#0aa566;--blue:#2f7de1;--orange:#ea7a14;--red:#dc4b43;--text:#1f2937;--muted:#687586;--line:#e4e8ee}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--text)}a{text-decoration:none;color:inherit}.side{position:fixed;left:0;top:0;bottom:0;width:260px;background:var(--side);color:#cbd5e1;padding:14px 10px;overflow:auto;z-index:20}.brand{display:flex;gap:11px;align-items:center;padding:8px 10px 16px;border-bottom:1px solid #29333e}.logo{width:46px;height:46px;border-radius:11px;background:linear-gradient(135deg,#0ba96a,#73dfaa);display:grid;place-items:center;color:#fff;font-weight:900}.brand b{display:block;color:#fff;font-size:18px}.brand small{color:#8da0b2}.user{margin:12px 7px;padding:11px;border:1px solid #29333e;border-radius:9px}.user b{color:#fff}.user small{display:block;color:#8da0b2;margin-top:3px}.navsec{font-size:10px;color:#6f8191;letter-spacing:1.2px;padding:14px 11px 5px}.nav a{display:flex;gap:10px;align-items:center;padding:10px 11px;border-radius:7px;margin:2px 0;font-size:13px}.nav a:hover,.nav a.on{background:#0a8354;color:#fff}.main{margin-left:260px;min-height:100vh}.top{height:68px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 26px;position:sticky;top:0;z-index:10}.top small{display:block;color:#8793a1;font-size:10px;letter-spacing:1.4px}.content{padding:24px 27px}.head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:17px}.head h1{margin:0;font-size:27px}.head p{margin:5px 0;color:var(--muted)}.btn{display:inline-block;border:0;border-radius:8px;padding:9px 13px;background:#eef2f6;font-weight:700;cursor:pointer;font-size:13px}.green{background:var(--green);color:#fff}.blue{background:var(--blue);color:#fff}.orange{background:var(--orange);color:#fff}.red{background:var(--red);color:#fff}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}.card,.panel{background:#fff;border:1px solid var(--line);border-radius:11px;padding:16px}.label{font-size:11px;font-weight:800;color:#5b6775;text-transform:uppercase}.num{font-size:27px;font-weight:850;margin-top:7px}.muted{color:var(--muted);font-size:12px}.moneygrid{display:grid;grid-template-columns:repeat(3,1fr);gap:13px;margin-top:13px}.moneygrid .card{color:#fff;border:0}.g{background:linear-gradient(135deg,#0aa566,#08784e)}.o{background:linear-gradient(135deg,#f08a19,#d75b0a)}.b{background:linear-gradient(135deg,#2b8fd4,#1c65af)}.panel{margin-top:14px;overflow:auto}.panel h3{margin:0 0 12px}.twocol{display:grid;grid-template-columns:1fr 1fr;gap:14px}.threecol{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.field label{display:block;font-size:11px;font-weight:800;margin-bottom:5px;color:#52606d}.field input,.field select,.field textarea{width:100%;padding:10px 11px;border:1px solid #d6dde5;border-radius:8px;font:inherit;background:#fff}.field textarea{min-height:88px;resize:vertical}.full{grid-column:1/-1}.actions{display:flex;gap:7px;flex-wrap:wrap}.small{padding:6px 9px;font-size:11px}.tag{padding:4px 8px;border-radius:999px;font-size:10px;font-weight:850;display:inline-block}.ok{background:#e6f8ef;color:#087646}.bad{background:#fff0ec;color:#b6371e}.pending{background:#fff6df;color:#8c6200}.info{background:#eaf3ff;color:#2862a5}.notice{padding:11px 13px;border-radius:8px;margin:0 0 13px;background:#eaf3ff;color:#245b91}.notice.err{background:#fff0ec;color:#9d2d1b}.notice.success{background:#e7f8ef;color:#087646}.empty{text-align:center;padding:34px;color:#7a8592}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #edf0f3;font-size:13px;vertical-align:middle}th{font-size:10px;color:#667481;text-transform:uppercase;letter-spacing:.3px}.searchbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.searchbar input,.searchbar select{padding:9px 10px;border:1px solid #d6dde5;border-radius:8px;min-width:160px}.mono{font-family:Consolas,monospace}
@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}.threecol{grid-template-columns:1fr 1fr}}@media(max-width:860px){.side{width:78px}.brand .text,.user,.nav span.labeltxt,.navsec{display:none}.main{margin-left:78px}.content{padding:16px}.moneygrid,.twocol,.threecol{grid-template-columns:1fr}}@media(max-width:560px){.cards,.grid{grid-template-columns:1fr}.full{grid-column:auto}.top{padding:0 14px}.head{flex-direction:column}}
'''
NAV=[('dashboard','▦','Dashboard','GENERAL'),('clients','👥','Clientes','GENERAL'),('installations','🛠','Instalaciones','GENERAL'),('plans','◉','Planes','SERVICIO'),('zones','⌖','Zonas','SERVICIO'),('routers','⌁','Routers','SERVICIO'),('invoices','▤','Facturas','FINANZAS'),('payments','💳','Pagos','FINANZAS'),('promises','🤝','Promesas','FINANZAS'),('expenses','◫','Gastos','FINANZAS'),('reports','▥','Reportes','FINANZAS'),('support','◉','Soporte técnico','OPERACIÓN'),('whatsapp','◯','WhatsApp','OPERACIÓN'),('settings_page','⚙','Configuración','SISTEMA'),('audit_page','☷','Auditoría','SISTEMA')]

def shell(title, body, active='dashboard'):
    out=[]; sec=None
    for endpoint,icon,label,section in NAV:
        if section!=sec: out.append(f'<div class="navsec">{section}</div>'); sec=section
        cls='on' if endpoint==active else ''; out.append(f'<a class="{cls}" href="{url_for(endpoint)}"><b>{icon}</b><span class="labeltxt">{label}</span></a>')
    msgs=''.join(f'<div class="notice {"err" if cat=="error" else "success" if cat=="success" else ""}">{e(msg)}</div>' for cat,msg in session.pop('_flashes',[]))
    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>ISP Manager</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav></aside><main class="main"><header class="top"><div><small>PANEL DE ADMINISTRACIÓN</small><b>INTER Flash</b></div><div class="actions"><a class="btn small" href="{{url_for('client_new')}}">+ Cliente</a><a class="btn small" href="{{url_for('logout')}}">Salir</a></div></header><section class="content">{{msgs|safe}}{{body|safe}}</section></main></body></html>''',title=title,css=CSS,nav=''.join(out),msgs=msgs,body=body)

LOGIN='''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash</title><style>body{margin:0;font-family:Arial;background:linear-gradient(135deg,#101722,#17394b);display:grid;place-items:center;min-height:100vh}.box{width:min(410px,92vw);background:white;padding:32px;border-radius:18px;box-shadow:0 25px 70px #0006}input,button{width:100%;box-sizing:border-box;padding:13px;margin:7px 0;border:1px solid #d6dbe2;border-radius:9px;font-size:16px}button{background:#0a9b5b;color:#fff;border:0;font-weight:800}.err{background:#fff0f0;color:#a11;padding:10px;border-radius:8px}</style></head><body><form class="box" method="post"><h1>INTER Flash</h1><p>ISP Manager</p>{{error|safe}}<input name="username" placeholder="Usuario" required><input type="password" name="password" placeholder="Contraseña" required><button>Entrar</button></form></body></html>'''

@app.get('/health')
def health(): return 'ok',200
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        if PASSWORD and request.form.get('username')==USER and request.form.get('password')==PASSWORD:
            session.clear(); session['auth']=True; session['user']=USER; audit('LOGIN','system','',f'Inicio de sesión: {USER}'); return redirect(url_for('dashboard'))
        return render_template_string(LOGIN,error='<div class="err">Usuario o contraseña incorrectos.</div>'),401
    return render_template_string(LOGIN,error='')
@app.get('/logout')
def logout():
    if session.get('auth'): audit('LOGOUT','system','',str(session.get('user','')))
    session.clear(); return redirect(url_for('login'))
@app.get('/')
def home(): return redirect(url_for('dashboard') if session.get('auth') else url_for('login'))

@app.get('/dashboard')
@login_required
def dashboard():
    c=con(); total=c.execute('SELECT count(*) c FROM clients').fetchone()['c']; active=c.execute("SELECT count(*) c FROM clients WHERE status='ACTIVO'").fetchone()['c']; suspended=c.execute("SELECT count(*) c FROM clients WHERE status='SUSPENDIDO'").fetchone()['c']; pending=c.execute("SELECT count(*) c FROM invoices WHERE status='PENDIENTE'").fetchone()['c']; pending_money=c.execute("SELECT coalesce(sum(amount),0) s FROM invoices WHERE status='PENDIENTE'").fetchone()['s']; paid_money=c.execute("SELECT coalesce(sum(amount),0) s FROM payments").fetchone()['s']; tickets=c.execute("SELECT count(*) c FROM tickets WHERE status NOT IN ('RESUELTO','CERRADO')").fetchone()['c']; installs=c.execute("SELECT count(*) c FROM installations WHERE status NOT IN ('COMPLETADA','CANCELADA')").fetchone()['c']; routers_n=c.execute('SELECT count(*) c FROM routers').fetchone()['c']; due_today=c.execute("SELECT count(*) c FROM invoices WHERE status='PENDIENTE' AND due_date=?",(today(),)).fetchone()['c']; recent=c.execute("SELECT i.*,c.name client FROM invoices i JOIN clients c ON c.id=i.client_id ORDER BY i.id DESC LIMIT 8").fetchall(); c.close()
    items=[('Clientes',total,'Registrados'),('Activos',active,'En servicio'),('Suspendidos',suspended,'Estado local'),('Instalaciones',installs,'Pendientes'),('Facturas pendientes',pending,money(pending_money)),('Vence hoy',due_today,'Facturas'),('Tickets',tickets,'Abiertos'),('Routers',routers_n,'Registrados')]; cards=''.join(f'<div class="card"><div class="label">{a}</div><div class="num">{b}</div><div class="muted">{d}</div></div>' for a,b,d in items); rows=''.join(f"<tr><td>{e(r['invoice_no'] or r['id'])}</td><td>{e(r['client'])}</td><td>{e(r['due_date'])}</td><td>{money(r['amount'])}</td><td><span class='tag {'ok' if r['status']=='PAGADA' else 'pending'}'>{e(r['status'])}</span></td></tr>" for r in recent)
    body=f'<div class="head"><div><h1>Dashboard</h1><p>Resumen de clientes, cobros y operación</p></div><div class="actions"><a class="btn green" href="{url_for("client_new")}">+ Nuevo cliente</a><a class="btn blue" href="{url_for("invoice_new")}">+ Factura</a></div></div><div class="cards">{cards}</div><div class="moneygrid"><div class="card g"><div>Pagos registrados</div><div class="num">{money(paid_money)}</div></div><div class="card o"><div>Por cobrar</div><div class="num">{money(pending_money)}</div></div><div class="card b"><div>Estado de red</div><div class="num">{routers_n}</div><div>routers configurados</div></div></div><div class="panel"><h3>Facturas recientes</h3><table><tr><th>Factura</th><th>Cliente</th><th>Vence</th><th>Monto</th><th>Estado</th></tr>{rows or "<tr><td colspan=5 class=empty>No hay facturas todavía.</td></tr>"}</table></div>'; return shell('Dashboard',body,'dashboard')

@app.get('/clients')
@login_required
def clients():
    q=request.args.get('q','').strip(); status=request.args.get('status','').strip(); params=[]; where=[]
    if q: where.append('(c.name LIKE ? OR c.phone LIKE ? OR c.pppoe LIKE ? OR c.document LIKE ?)'); params += [f'%{q}%']*4
    if status: where.append('c.status=?'); params.append(status)
    sql='SELECT c.*,p.name plan,p.price plan_price,z.name zone FROM clients c LEFT JOIN plans p ON p.id=c.plan_id LEFT JOIN zones z ON z.id=c.zone_id'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY c.id DESC'; c=con(); rows=c.execute(sql,params).fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td><a href='{url_for('client_view',id=r['id'])}'><b>{e(r['name'])}</b></a><br><small>{e(r['phone'])}</small></td><td class='mono'>{e(r['pppoe']) or '-'}</td><td>{e(r['plan']) or '-'}</td><td>{e(r['zone']) or '-'}</td><td><span class='tag {'ok' if r['status']=='ACTIVO' else 'bad'}'>{e(r['status'])}</span></td><td><div class='actions'><a class='btn small' href='{url_for('client_view',id=r['id'])}'>Ver</a><a class='btn small blue' href='{url_for('client_edit',id=r['id'])}'>Editar</a></div></td></tr>" for r in rows)
    body=f'<div class="head"><div><h1>Clientes</h1><p>Administración completa de abonados</p></div><a class="btn green" href="{url_for("client_new")}">+ Nuevo cliente</a></div><form class="searchbar"><input name="q" value="{e(q)}" placeholder="Buscar nombre, teléfono, PPPoE o cédula"><select name="status"><option value="">Todos los estados</option><option {"selected" if status=="ACTIVO" else ""}>ACTIVO</option><option {"selected" if status=="SUSPENDIDO" else ""}>SUSPENDIDO</option></select><button class="btn">Buscar</button><a class="btn" href="{url_for("clients_export")}">Exportar CSV</a></form><div class="panel"><table><tr><th>ID</th><th>Cliente</th><th>PPPoE</th><th>Plan</th><th>Zona</th><th>Estado</th><th>Acciones</th></tr>{trs or "<tr><td colspan=7 class=empty>No hay clientes.</td></tr>"}</table></div>'; return shell('Clientes',body,'clients')

def client_form(row=None):
    c=con(); plans=c.execute('SELECT * FROM plans WHERE active=1 ORDER BY name').fetchall(); zones=c.execute('SELECT * FROM zones WHERE active=1 ORDER BY name').fetchall(); c.close(); val=lambda k:e(row[k]) if row and k in row.keys() and row[k] is not None else ''; po='<option value="">Sin plan</option>'+''.join(f"<option value='{p['id']}' {'selected' if row and row['plan_id']==p['id'] else ''}>{e(p['name'])} · {e(p['speed'])} · {money(p['price'])}</option>" for p in plans); zo='<option value="">Sin zona</option>'+''.join(f"<option value='{z['id']}' {'selected' if row and row['zone_id']==z['id'] else ''}>{e(z['name'])}</option>" for z in zones); status=(row['status'] if row else 'ACTIVO'); st=''.join(f"<option {'selected' if status==s else ''}>{s}</option>" for s in ['ACTIVO','SUSPENDIDO'])
    return f'<form class="grid" method="post"><div class="field"><label>Nombre completo</label><input name="name" value="{val("name")}" required></div><div class="field"><label>Teléfono / WhatsApp</label><input name="phone" value="{val("phone")}"></div><div class="field"><label>Cédula / documento</label><input name="document" value="{val("document")}"></div><div class="field"><label>Correo</label><input type="email" name="email" value="{val("email")}"></div><div class="field full"><label>Dirección</label><input name="address" value="{val("address")}"></div><div class="field"><label>Plan</label><select name="plan_id">{po}</select></div><div class="field"><label>Zona</label><select name="zone_id">{zo}</select></div><div class="field"><label>Usuario PPPoE</label><input name="pppoe" value="{val("pppoe")}"></div><div class="field"><label>Tipo de servicio</label><select name="service_type"><option>PPPoE</option><option>Hotspot</option><option>IP Estática</option></select></div><div class="field"><label>Dirección IP</label><input name="ip_address" value="{val("ip_address")}"></div><div class="field"><label>MAC</label><input name="mac_address" value="{val("mac_address")}"></div><div class="field"><label>Estado local</label><select name="status">{st}</select></div><div class="field"><label>Fecha de instalación</label><input type="date" name="installed_at" value="{val("installed_at")}"></div><div class="field full"><label>Notas</label><textarea name="notes">{val("notes")}</textarea></div><div class="full actions"><button class="btn green">Guardar</button><a class="btn" href="{url_for("clients")}">Cancelar</a></div></form>'

@app.route('/clients/new',methods=['GET','POST'])
@login_required
def client_new():
    if request.method=='POST':
        c=con(); cur=c.execute('INSERT INTO clients(name,phone,email,document,address,pppoe,status,plan_id,zone_id,ip_address,mac_address,service_type,notes,installed_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(request.form['name'].strip(),request.form.get('phone','').strip(),request.form.get('email','').strip(),request.form.get('document','').strip(),request.form.get('address','').strip(),request.form.get('pppoe','').strip(),request.form.get('status','ACTIVO'),request.form.get('plan_id') or None,request.form.get('zone_id') or None,request.form.get('ip_address','').strip(),request.form.get('mac_address','').strip(),request.form.get('service_type','PPPoE'),request.form.get('notes','').strip(),request.form.get('installed_at') or None,now(),now())); cid=cur.lastrowid; c.commit(); c.close(); audit('CREAR','client',cid,request.form['name']); flash('Cliente creado correctamente.','success'); return redirect(url_for('client_view',id=cid))
    return shell('Nuevo cliente',f'<div class="head"><div><h1>Nuevo cliente</h1><p>Datos personales, servicio y red</p></div></div><div class="panel">{client_form()}</div>','clients')

@app.get('/clients/<int:id>')
@login_required
def client_view(id):
    c=con(); r=c.execute('SELECT c.*,p.name plan,p.speed,p.price,z.name zone FROM clients c LEFT JOIN plans p ON p.id=c.plan_id LEFT JOIN zones z ON z.id=c.zone_id WHERE c.id=?',(id,)).fetchone()
    if not r: c.close(); return ('Cliente no encontrado',404)
    inv=c.execute('SELECT * FROM invoices WHERE client_id=? ORDER BY id DESC LIMIT 20',(id,)).fetchall(); pay=c.execute('SELECT * FROM payments WHERE client_id=? ORDER BY id DESC LIMIT 20',(id,)).fetchall(); tickets=c.execute('SELECT * FROM tickets WHERE client_id=? ORDER BY id DESC LIMIT 10',(id,)).fetchall(); c.close(); invrows=''.join(f"<tr><td>{e(x['invoice_no'] or x['id'])}</td><td>{e(x['concept'])}</td><td>{e(x['due_date'])}</td><td>{money(x['amount'])}</td><td><span class='tag {'ok' if x['status']=='PAGADA' else 'pending'}'>{e(x['status'])}</span></td><td>{'' if x['status']=='PAGADA' else f'<a class=\"btn small green\" href=\"{url_for('invoice_pay',id=x['id'])}\">Cobrar</a>'}</td></tr>" for x in inv); payrows=''.join(f"<tr><td>{e(x['paid_at'])}</td><td>{money(x['amount'])}</td><td>{e(x['method'])}</td><td>{e(x['reference'])}</td></tr>" for x in pay); trows=''.join(f"<tr><td>#{x['id']}</td><td>{e(x['subject'])}</td><td>{e(x['priority'])}</td><td>{e(x['status'])}</td></tr>" for x in tickets)
    body=f'<div class="head"><div><h1>{e(r["name"])}</h1><p>Cliente #{r["id"]} · {e(r["phone"])}</p></div><div class="actions"><a class="btn blue" href="{url_for("client_edit",id=id)}">Editar</a><form method="post" action="{url_for("client_toggle",id=id)}"><button class="btn {"red" if r["status"]=="ACTIVO" else "green"}">{"Suspender local" if r["status"]=="ACTIVO" else "Reactivar local"}</button></form></div></div><div class="threecol"><div class="card"><div class="label">Estado</div><div class="num"><span class="tag {"ok" if r["status"]=="ACTIVO" else "bad"}">{e(r["status"])}</span></div><div class="muted">Este cambio todavía no modifica el MikroTik.</div></div><div class="card"><div class="label">Plan</div><div class="num" style="font-size:20px">{e(r["plan"]) or "-"}</div><div class="muted">{e(r["speed"])} · {money(r["price"]) if r["price"] is not None else "-"}</div></div><div class="card"><div class="label">Red</div><div><b>PPPoE:</b> {e(r["pppoe"]) or "-"}</div><div><b>IP:</b> {e(r["ip_address"]) or "-"}</div><div><b>MAC:</b> {e(r["mac_address"]) or "-"}</div></div></div><div class="twocol"><div class="panel"><h3>Datos del cliente</h3><table><tr><th>Documento</th><td>{e(r["document"]) or "-"}</td></tr><tr><th>Correo</th><td>{e(r["email"]) or "-"}</td></tr><tr><th>Dirección</th><td>{e(r["address"]) or "-"}</td></tr><tr><th>Zona</th><td>{e(r["zone"]) or "-"}</td></tr><tr><th>Instalado</th><td>{e(r["installed_at"]) or "-"}</td></tr><tr><th>Notas</th><td>{e(r["notes"]) or "-"}</td></tr></table></div><div class="panel"><h3>Acciones rápidas</h3><div class="actions"><a class="btn green" href="{url_for("invoice_new",client_id=id)}">+ Factura</a><a class="btn blue" href="{url_for("promise_new",client_id=id)}">+ Promesa</a><a class="btn" href="{url_for("ticket_new",client_id=id)}">+ Ticket</a><a class="btn" href="{url_for("whatsapp_client",id=id)}">WhatsApp</a></div></div></div><div class="panel"><h3>Facturas</h3><table><tr><th>Factura</th><th>Concepto</th><th>Vence</th><th>Monto</th><th>Estado</th><th></th></tr>{invrows or "<tr><td colspan=6 class=empty>Sin facturas.</td></tr>"}</table></div><div class="twocol"><div class="panel"><h3>Pagos</h3><table><tr><th>Fecha</th><th>Monto</th><th>Método</th><th>Referencia</th></tr>{payrows or "<tr><td colspan=4 class=empty>Sin pagos.</td></tr>"}</table></div><div class="panel"><h3>Tickets</h3><table><tr><th>ID</th><th>Asunto</th><th>Prioridad</th><th>Estado</th></tr>{trows or "<tr><td colspan=4 class=empty>Sin tickets.</td></tr>"}</table></div></div>'; return shell(r['name'],body,'clients')

@app.route('/clients/<int:id>/edit',methods=['GET','POST'])
@login_required
def client_edit(id):
    c=con(); r=c.execute('SELECT * FROM clients WHERE id=?',(id,)).fetchone()
    if not r: c.close(); return ('Cliente no encontrado',404)
    if request.method=='POST':
        c.execute('UPDATE clients SET name=?,phone=?,email=?,document=?,address=?,pppoe=?,status=?,plan_id=?,zone_id=?,ip_address=?,mac_address=?,service_type=?,notes=?,installed_at=?,updated_at=? WHERE id=?',(request.form['name'].strip(),request.form.get('phone','').strip(),request.form.get('email','').strip(),request.form.get('document','').strip(),request.form.get('address','').strip(),request.form.get('pppoe','').strip(),request.form.get('status','ACTIVO'),request.form.get('plan_id') or None,request.form.get('zone_id') or None,request.form.get('ip_address','').strip(),request.form.get('mac_address','').strip(),request.form.get('service_type','PPPoE'),request.form.get('notes','').strip(),request.form.get('installed_at') or None,now(),id)); c.commit(); c.close(); audit('EDITAR','client',id,request.form['name']); flash('Cliente actualizado.','success'); return redirect(url_for('client_view',id=id))
    c.close(); return shell('Editar cliente',f'<div class="head"><div><h1>Editar cliente</h1><p>{e(r["name"])}</p></div></div><div class="panel">{client_form(r)}</div>','clients')

@app.post('/clients/<int:id>/toggle')
@login_required
def client_toggle(id):
    c=con(); r=c.execute('SELECT name,status FROM clients WHERE id=?',(id,)).fetchone()
    if not r: c.close(); return ('No encontrado',404)
    new='SUSPENDIDO' if r['status']=='ACTIVO' else 'ACTIVO'; c.execute('UPDATE clients SET status=?,updated_at=? WHERE id=?',(new,now(),id)); c.commit(); c.close(); audit('CAMBIAR_ESTADO_LOCAL','client',id,f"{r['status']} -> {new}"); flash(f'Estado local cambiado a {new}. No se envió ningún cambio al MikroTik.','success'); return redirect(request.referrer or url_for('clients'))

@app.route('/plans',methods=['GET','POST'])
@login_required
def plans():
    c=con()
    if request.method=='POST': cur=c.execute('INSERT INTO plans(name,speed,price,description,active,created_at) VALUES(?,?,?,?,1,?)',(request.form['name'].strip(),request.form.get('speed','').strip(),float(request.form.get('price') or 0),request.form.get('description','').strip(),now())); c.commit(); audit('CREAR','plan',cur.lastrowid,request.form['name']); flash('Plan creado.','success')
    rows=c.execute('SELECT * FROM plans ORDER BY active DESC,name').fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td><b>{e(r['name'])}</b><br><small>{e(r['description'])}</small></td><td>{e(r['speed'])}</td><td>{money(r['price'])}</td><td><span class='tag {'ok' if r['active'] else 'bad'}'>{'ACTIVO' if r['active'] else 'INACTIVO'}</span></td><td><form method='post' action='{url_for('plan_toggle',id=r['id'])}'><button class='btn small'>Cambiar</button></form></td></tr>" for r in rows); body=f'<div class="head"><div><h1>Planes</h1><p>Planes comerciales de internet</p></div></div><div class="twocol"><div class="panel"><h3>Crear plan</h3><form class="grid" method="post"><div class="field"><label>Nombre</label><input name="name" required></div><div class="field"><label>Velocidad</label><input name="speed" placeholder="40/40 Mbps"></div><div class="field"><label>Precio RD$</label><input type="number" step="0.01" name="price"></div><div class="field"><label>Descripción</label><input name="description"></div><div class="full"><button class="btn green">Guardar plan</button></div></form></div><div class="panel"><h3>Planes registrados</h3><table><tr><th>ID</th><th>Plan</th><th>Velocidad</th><th>Precio</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=6 class=empty>Sin planes.</td></tr>"}</table></div></div>'; return shell('Planes',body,'plans')
@app.post('/plans/<int:id>/toggle')
@login_required
def plan_toggle(id):
    c=con(); r=c.execute('SELECT active FROM plans WHERE id=?',(id,)).fetchone();
    if r: c.execute('UPDATE plans SET active=? WHERE id=?',(0 if r['active'] else 1,id)); c.commit(); audit('CAMBIAR_ESTADO','plan',id,'')
    c.close(); return redirect(url_for('plans'))

@app.route('/zones',methods=['GET','POST'])
@login_required
def zones():
    c=con()
    if request.method=='POST': cur=c.execute('INSERT INTO zones(name,due_day,cut_day,cut_time,active,created_at) VALUES(?,?,?,?,1,?)',(request.form['name'].strip(),int(request.form.get('due_day') or 30),int(request.form.get('cut_day') or 6),request.form.get('cut_time') or '14:00',now())); c.commit(); audit('CREAR','zone',cur.lastrowid,request.form['name']); flash('Zona creada.','success')
    rows=c.execute('SELECT * FROM zones ORDER BY active DESC,name').fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td><b>{e(r['name'])}</b></td><td>Día {r['due_day']}</td><td>+{r['cut_day']} días · {e(r['cut_time'])}</td><td><span class='tag {'ok' if r['active'] else 'bad'}'>{'ACTIVA' if r['active'] else 'INACTIVA'}</span></td></tr>" for r in rows); body=f'<div class="head"><div><h1>Zonas</h1><p>Vencimiento y política de corte por zona</p></div></div><div class="twocol"><div class="panel"><h3>Nueva zona</h3><form class="grid" method="post"><div class="field full"><label>Nombre</label><input name="name" required></div><div class="field"><label>Día de vencimiento</label><input type="number" min="1" max="31" name="due_day" value="30"></div><div class="field"><label>Días después para corte</label><input type="number" min="0" name="cut_day" value="6"></div><div class="field"><label>Hora de corte</label><input type="time" name="cut_time" value="14:00"></div><div class="full"><button class="btn green">Guardar zona</button></div></form></div><div class="panel"><h3>Zonas registradas</h3><table><tr><th>ID</th><th>Zona</th><th>Vence</th><th>Corte</th><th>Estado</th></tr>{trs or "<tr><td colspan=5 class=empty>Sin zonas.</td></tr>"}</table></div></div>'; return shell('Zonas',body,'zones')

@app.get('/invoices')
@login_required
def invoices():
    status=request.args.get('status',''); q=request.args.get('q','').strip(); where=[]; params=[]
    if status: where.append('i.status=?'); params.append(status)
    if q: where.append('(c.name LIKE ? OR i.invoice_no LIKE ?)'); params += [f'%{q}%',f'%{q}%']
    sql='SELECT i.*,c.name client FROM invoices i JOIN clients c ON c.id=i.client_id'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY i.id DESC'; c=con(); rows=c.execute(sql,params).fetchall(); c.close(); trs=''.join(f"<tr><td>{e(r['invoice_no'] or r['id'])}</td><td><a href='{url_for('client_view',id=r['client_id'])}'>{e(r['client'])}</a></td><td>{e(r['concept'])}</td><td>{e(r['issue_date'])}</td><td>{e(r['due_date'])}</td><td>{money(r['amount'])}</td><td><span class='tag {'ok' if r['status']=='PAGADA' else 'pending'}'>{e(r['status'])}</span></td><td>{'' if r['status']=='PAGADA' else f'<a class=\"btn small green\" href=\"{url_for('invoice_pay',id=r['id'])}\">Cobrar</a>'}</td></tr>" for r in rows); body=f'<div class="head"><div><h1>Facturas</h1><p>Emisión, vencimiento y cobro</p></div><div class="actions"><a class="btn green" href="{url_for("invoice_new")}">+ Nueva factura</a><form method="post" action="{url_for("generate_monthly_invoices")}" style="display:inline"><button class="btn blue">Generar mes actual</button></form></div></div><form class="searchbar"><input name="q" value="{e(q)}" placeholder="Cliente o factura"><select name="status"><option value="">Todas</option><option {"selected" if status=="PENDIENTE" else ""}>PENDIENTE</option><option {"selected" if status=="PAGADA" else ""}>PAGADA</option></select><button class="btn">Filtrar</button><a class="btn" href="{url_for("invoices_export")}">Exportar CSV</a></form><div class="panel"><table><tr><th>Factura</th><th>Cliente</th><th>Concepto</th><th>Emisión</th><th>Vence</th><th>Monto</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=8 class=empty>Sin facturas.</td></tr>"}</table></div>'; return shell('Facturas',body,'invoices')

@app.route('/invoices/new',methods=['GET','POST'])
@login_required
def invoice_new():
    pre=request.args.get('client_id',''); c=con(); clients_=c.execute('SELECT c.*,p.price plan_price,z.due_day FROM clients c LEFT JOIN plans p ON p.id=c.plan_id LEFT JOIN zones z ON z.id=c.zone_id ORDER BY c.name').fetchall()
    if request.method=='POST':
        cid=int(request.form['client_id']); amount=float(request.form.get('amount') or 0); invno=next_invoice_no(c); cur=c.execute('INSERT INTO invoices(invoice_no,client_id,concept,amount,issue_date,due_date,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(invno,cid,request.form.get('concept','Mensualidad').strip(),amount,request.form.get('issue_date') or today(),request.form.get('due_date') or today(),'PENDIENTE',request.form.get('notes','').strip(),now())); c.commit(); iid=cur.lastrowid; c.close(); audit('CREAR','invoice',iid,invno); flash(f'Factura {invno} creada.','success'); return redirect(url_for('invoices'))
    opts=''.join(f"<option value='{x['id']}' {'selected' if str(x['id'])==str(pre) else ''}>{e(x['name'])} · {money(x['plan_price']) if x['plan_price'] is not None else 'sin plan'}</option>" for x in clients_); c.close(); body=f'<div class="head"><div><h1>Nueva factura</h1><p>Crear cargo manual</p></div></div><div class="panel"><form class="grid" method="post"><div class="field full"><label>Cliente</label><select name="client_id" required>{opts}</select></div><div class="field"><label>Concepto</label><input name="concept" value="Mensualidad"></div><div class="field"><label>Monto RD$</label><input type="number" step="0.01" name="amount" required></div><div class="field"><label>Fecha de emisión</label><input type="date" name="issue_date" value="{today()}"></div><div class="field"><label>Vencimiento</label><input type="date" name="due_date" value="{today()}"></div><div class="field full"><label>Notas</label><textarea name="notes"></textarea></div><div class="full actions"><button class="btn green">Crear factura</button><a class="btn" href="{url_for("invoices")}">Cancelar</a></div></form></div>'; return shell('Nueva factura',body,'invoices')

@app.post('/invoices/generate-monthly')
@login_required
def generate_monthly_invoices():
    c=con(); rows=c.execute("SELECT c.id,c.name,p.price,z.due_day FROM clients c JOIN plans p ON p.id=c.plan_id LEFT JOIN zones z ON z.id=c.zone_id WHERE c.status='ACTIVO' AND p.active=1").fetchall(); y=date.today().year; m=date.today().month; key=f'{y}-{m:02d}'; created=0
    for r in rows:
        concept=f'Mensualidad {key}'; exists=c.execute('SELECT 1 FROM invoices WHERE client_id=? AND concept=?',(r['id'],concept)).fetchone()
        if exists: continue
        due=safe_due_date(y,m,r['due_day'] or 30); invno=next_invoice_no(c); c.execute('INSERT INTO invoices(invoice_no,client_id,concept,amount,issue_date,due_date,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(invno,r['id'],concept,float(r['price'] or 0),today(),due,'PENDIENTE',now())); created+=1
    c.commit(); c.close(); audit('GENERAR_MENSUAL','invoice','',f'{created} facturas'); flash(f'Se generaron {created} facturas del mes.','success'); return redirect(url_for('invoices'))

@app.route('/invoices/<int:id>/pay',methods=['GET','POST'])
@login_required
def invoice_pay(id):
    c=con(); r=c.execute('SELECT i.*,c.name client FROM invoices i JOIN clients c ON c.id=i.client_id WHERE i.id=?',(id,)).fetchone()
    if not r: c.close(); return ('Factura no encontrada',404)
    if request.method=='POST':
        amount=float(request.form.get('amount') or r['amount']); paid_at=request.form.get('paid_at') or today(); cur=c.execute('INSERT INTO payments(invoice_id,client_id,amount,method,reference,paid_at,notes,created_at) VALUES(?,?,?,?,?,?,?,?)',(id,r['client_id'],amount,request.form.get('method','Efectivo'),request.form.get('reference','').strip(),paid_at,request.form.get('notes','').strip(),now())); c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?",(paid_at,id)); c.commit(); pid=cur.lastrowid; c.close(); audit('COBRAR','payment',pid,f"Factura {r['invoice_no']}"); flash('Pago registrado y factura marcada como pagada.','success'); return redirect(url_for('client_view',id=r['client_id']))
    c.close(); body=f'<div class="head"><div><h1>Registrar pago</h1><p>{e(r["invoice_no"])} · {e(r["client"])}</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Monto RD$</label><input type="number" step="0.01" name="amount" value="{r["amount"]}" required></div><div class="field"><label>Fecha</label><input type="date" name="paid_at" value="{today()}"></div><div class="field"><label>Método</label><select name="method"><option>Efectivo</option><option>Transferencia</option><option>Depósito</option><option>Tarjeta</option><option>Otro</option></select></div><div class="field"><label>Referencia</label><input name="reference"></div><div class="field full"><label>Notas</label><textarea name="notes"></textarea></div><div class="full"><button class="btn green">Registrar pago</button></div></form></div>'; return shell('Registrar pago',body,'payments')

@app.get('/payments')
@login_required
def payments():
    c=con(); rows=c.execute('SELECT p.*,c.name client,i.invoice_no FROM payments p JOIN clients c ON c.id=p.client_id LEFT JOIN invoices i ON i.id=p.invoice_id ORDER BY p.id DESC').fetchall(); total=c.execute('SELECT coalesce(sum(amount),0) s FROM payments').fetchone()['s']; c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td>{e(r['paid_at'])}</td><td>{e(r['client'])}</td><td>{e(r['invoice_no']) or '-'}</td><td>{money(r['amount'])}</td><td>{e(r['method'])}</td><td>{e(r['reference'])}</td></tr>" for r in rows); return shell('Pagos',f'<div class="head"><div><h1>Pagos</h1><p>Historial de cobros registrados</p></div><div class="card"><div class="label">Total registrado</div><div class="num">{money(total)}</div></div></div><div class="panel"><table><tr><th>ID</th><th>Fecha</th><th>Cliente</th><th>Factura</th><th>Monto</th><th>Método</th><th>Referencia</th></tr>{trs or "<tr><td colspan=7 class=empty>Sin pagos.</td></tr>"}</table></div>','payments')

@app.get('/promises')
@login_required
def promises():
    c=con(); rows=c.execute('SELECT p.*,c.name client FROM payment_promises p JOIN clients c ON c.id=p.client_id ORDER BY p.id DESC').fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td>{e(r['client'])}</td><td>{money(r['amount'])}</td><td>{e(r['promise_date'])}</td><td><span class='tag {'ok' if r['status']=='CUMPLIDA' else 'pending'}'>{e(r['status'])}</span></td><td><form method='post' action='{url_for('promise_done',id=r['id'])}'><button class='btn small'>Cumplida</button></form></td></tr>" for r in rows); return shell('Promesas de pago',f'<div class="head"><div><h1>Promesas de pago</h1><p>Compromisos de clientes</p></div><a class="btn green" href="{url_for("promise_new")}">+ Nueva promesa</a></div><div class="panel"><table><tr><th>ID</th><th>Cliente</th><th>Monto</th><th>Fecha</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=6 class=empty>Sin promesas.</td></tr>"}</table></div>','promises')

@app.route('/promises/new',methods=['GET','POST'])
@login_required
def promise_new():
    pre=request.args.get('client_id',''); c=con(); clients_=c.execute('SELECT id,name FROM clients ORDER BY name').fetchall()
    if request.method=='POST': cur=c.execute('INSERT INTO payment_promises(client_id,amount,promise_date,status,notes,created_at) VALUES(?,?,?,?,?,?)',(request.form['client_id'],float(request.form.get('amount') or 0),request.form.get('promise_date') or today(),'PENDIENTE',request.form.get('notes',''),now())); c.commit(); pid=cur.lastrowid; c.close(); audit('CREAR','promise',pid,''); return redirect(url_for('promises'))
    opts=''.join(f"<option value='{x['id']}' {'selected' if str(x['id'])==str(pre) else ''}>{e(x['name'])}</option>" for x in clients_); c.close(); return shell('Nueva promesa',f'<div class="head"><div><h1>Nueva promesa</h1></div></div><div class="panel"><form class="grid" method="post"><div class="field full"><label>Cliente</label><select name="client_id">{opts}</select></div><div class="field"><label>Monto</label><input type="number" step="0.01" name="amount"></div><div class="field"><label>Fecha prometida</label><input type="date" name="promise_date" value="{today()}"></div><div class="field full"><label>Notas</label><textarea name="notes"></textarea></div><div><button class="btn green">Guardar</button></div></form></div>','promises')
@app.post('/promises/<int:id>/done')
@login_required
def promise_done(id): c=con(); c.execute("UPDATE payment_promises SET status='CUMPLIDA' WHERE id=?",(id,)); c.commit(); c.close(); audit('CUMPLIR','promise',id,''); return redirect(url_for('promises'))

@app.route('/expenses',methods=['GET','POST'])
@login_required
def expenses():
    c=con()
    if request.method=='POST': cur=c.execute('INSERT INTO expenses(concept,amount,category,expense_date,notes,created_at) VALUES(?,?,?,?,?,?)',(request.form['concept'].strip(),float(request.form.get('amount') or 0),request.form.get('category',''),request.form.get('expense_date') or today(),request.form.get('notes',''),now())); c.commit(); audit('CREAR','expense',cur.lastrowid,request.form['concept'])
    rows=c.execute('SELECT * FROM expenses ORDER BY id DESC').fetchall(); total=c.execute('SELECT coalesce(sum(amount),0) s FROM expenses').fetchone()['s']; c.close(); trs=''.join(f"<tr><td>{e(r['expense_date'])}</td><td>{e(r['concept'])}</td><td>{e(r['category'])}</td><td>{money(r['amount'])}</td><td>{e(r['notes'])}</td></tr>" for r in rows); body=f'<div class="head"><div><h1>Gastos</h1><p>Control de egresos</p></div><div class="card"><div class="label">Total</div><div class="num">{money(total)}</div></div></div><div class="twocol"><div class="panel"><h3>Registrar gasto</h3><form class="grid" method="post"><div class="field full"><label>Concepto</label><input name="concept" required></div><div class="field"><label>Monto</label><input type="number" step="0.01" name="amount"></div><div class="field"><label>Categoría</label><input name="category"></div><div class="field"><label>Fecha</label><input type="date" name="expense_date" value="{today()}"></div><div class="field full"><label>Notas</label><textarea name="notes"></textarea></div><div><button class="btn green">Guardar</button></div></form></div><div class="panel"><h3>Historial</h3><table><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Monto</th><th>Notas</th></tr>{trs or "<tr><td colspan=5 class=empty>Sin gastos.</td></tr>"}</table></div></div>'; return shell('Gastos',body,'expenses')

@app.get('/routers')
@login_required
def routers():
    c=con(); rows=c.execute('SELECT * FROM routers ORDER BY id DESC').fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td><b>{e(r['name'])}</b><br><small>{e(r['identity'])}</small></td><td class='mono'>{e(r['host'])}:{r['port']}</td><td>{e(r['model']) or '-'}</td><td>{e(r['ros_version']) or '-'}</td><td>{r['pppoe_active'] or 0}</td><td><span class='tag {'ok' if r['status']=='ONLINE' else 'bad' if r['status']=='ERROR' else 'pending'}'>{e(r['status'])}</span><br><small>{e(r['last_seen'])}</small></td><td><div class='actions'><a class='btn small blue' href='{url_for('router_edit',id=r['id'])}'>Editar</a><form method='post' action='{url_for('router_test',id=r['id'])}'><button class='btn small green'>Probar</button></form></div></td></tr>" for r in rows); body=f'<div class="head"><div><h1>Routers</h1><p>RouterOS API. Las pruebas son de solo lectura.</p></div><a class="btn green" href="{url_for("router_new")}">+ Router</a></div><div class="notice">Por seguridad, esta página no suspende, crea ni modifica usuarios en MikroTik todavía.</div><div class="panel"><table><tr><th>ID</th><th>Router</th><th>Host</th><th>Modelo</th><th>RouterOS</th><th>PPPoE activos</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=8 class=empty>Sin routers.</td></tr>"}</table></div>'; return shell('Routers',body,'routers')

def router_form(r=None):
    v=lambda k,d='':e(r[k] if r and k in r.keys() and r[k] is not None else d); return f'<form class="grid" method="post"><div class="field"><label>Nombre</label><input name="name" value="{v("name")}" required></div><div class="field"><label>Host / IP / DDNS</label><input name="host" value="{v("host")}" required></div><div class="field"><label>Puerto API</label><input type="number" name="port" value="{v("port",8728)}"></div><div class="field"><label>Usuario RouterOS</label><input name="username" value="{v("username")}"></div><div class="field full"><label>Contraseña</label><input type="password" name="password"></div><div class="field"><label>SSL</label><select name="use_ssl"><option value="0">No</option><option value="1">Sí</option></select></div><div class="field"><label>Verificar certificado SSL</label><select name="verify_ssl"><option value="0">No</option><option value="1">Sí</option></select></div><div class="full"><button class="btn green">Guardar router</button></div></form>'
@app.route('/routers/new',methods=['GET','POST'])
@login_required
def router_new():
    if request.method=='POST': c=con(); cur=c.execute('INSERT INTO routers(name,host,port,username,password_enc,use_ssl,verify_ssl,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(request.form['name'].strip(),request.form['host'].strip(),int(request.form.get('port') or 8728),request.form.get('username','').strip(),enc(request.form.get('password','')),int(request.form.get('use_ssl') or 0),int(request.form.get('verify_ssl') or 0),'PENDIENTE',now())); c.commit(); rid=cur.lastrowid; c.close(); audit('CREAR','router',rid,request.form['name']); return redirect(url_for('routers'))
    return shell('Nuevo router',f'<div class="head"><div><h1>Nuevo router</h1></div></div><div class="panel">{router_form()}</div>','routers')
@app.route('/routers/<int:id>/edit',methods=['GET','POST'])
@login_required
def router_edit(id):
    c=con(); r=c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone()
    if not r: c.close(); return ('No encontrado',404)
    if request.method=='POST': pw=r['password_enc'] if not request.form.get('password') else enc(request.form.get('password')); c.execute('UPDATE routers SET name=?,host=?,port=?,username=?,password_enc=?,use_ssl=?,verify_ssl=? WHERE id=?',(request.form['name'].strip(),request.form['host'].strip(),int(request.form.get('port') or 8728),request.form.get('username','').strip(),pw,int(request.form.get('use_ssl') or 0),int(request.form.get('verify_ssl') or 0),id)); c.commit(); c.close(); audit('EDITAR','router',id,request.form['name']); return redirect(url_for('routers'))
    c.close(); return shell('Editar router',f'<div class="head"><div><h1>Editar router</h1><p>{e(r["name"])}</p></div></div><div class="panel">{router_form(r)}</div>','routers')
@app.post('/routers/<int:id>/test')
@login_required
def router_test(id):
    c=con(); r=c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone()
    if not r: c.close(); return ('No encontrado',404)
    try:
        pool=routeros_api.RouterOsApiPool(r['host'],username=r['username'] or '',password=dec(r['password_enc']),port=int(r['port'] or 8728),use_ssl=bool(r['use_ssl']),ssl_verify=bool(r['verify_ssl']),ssl_verify_hostname=bool(r['verify_ssl']),plaintext_login=True); api=pool.get_api(); ident=api.get_resource('/system/identity').get()[0].get('name',''); res=api.get_resource('/system/resource').get()[0]; active=len(api.get_resource('/ppp/active').get()); pool.disconnect(); c.execute("UPDATE routers SET status='ONLINE',identity=?,model=?,ros_version=?,pppoe_active=?,last_seen=?,last_error='' WHERE id=?",(ident,res.get('board-name',''),res.get('version',''),active,now(),id)); c.commit(); flash(f'Conexión correcta. PPPoE activos: {active}.','success'); audit('PROBAR_LECTURA','router',id,f'PPPoE activos {active}')
    except Exception as ex: c.execute("UPDATE routers SET status='ERROR',last_seen=?,last_error=? WHERE id=?",(now(),str(ex)[:500],id)); c.commit(); flash('No se pudo conectar al router. Revisa IP/puerto/usuario y acceso desde Railway.','error'); audit('ERROR_CONEXION','router',id,str(ex)[:180])
    c.close(); return redirect(url_for('routers'))

@app.get('/support')
@login_required
def support():
    c=con(); rows=c.execute('SELECT t.*,c.name client_name FROM tickets t LEFT JOIN clients c ON c.id=t.client_id ORDER BY t.id DESC').fetchall(); c.close(); trs=''.join(f"<tr><td>#{r['id']}</td><td><b>{e(r['subject'])}</b><br><small>{e(r['client_name'] or r['client'])}</small></td><td><span class='tag {'bad' if r['priority']=='ALTA' else 'pending' if r['priority']=='MEDIA' else 'info'}'>{e(r['priority'])}</span></td><td>{e(r['assigned_to']) or '-'}</td><td><span class='tag {'ok' if r['status'] in ('RESUELTO','CERRADO') else 'pending'}'>{e(r['status'])}</span></td><td><a class='btn small' href='{url_for('ticket_view',id=r['id'])}'>Abrir</a></td></tr>" for r in rows); return shell('Soporte técnico',f'<div class="head"><div><h1>Soporte técnico</h1><p>Tickets y seguimiento</p></div><a class="btn green" href="{url_for("ticket_new")}">+ Ticket</a></div><div class="panel"><table><tr><th>ID</th><th>Ticket</th><th>Prioridad</th><th>Técnico</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=6 class=empty>Sin tickets.</td></tr>"}</table></div>','support')
@app.route('/support/new',methods=['GET','POST'])
@login_required
def ticket_new():
    pre=request.args.get('client_id',''); c=con(); clients_=c.execute('SELECT id,name,phone FROM clients ORDER BY name').fetchall()
    if request.method=='POST':
        cid=request.form.get('client_id') or None; name=''; phone=request.form.get('phone','')
        if cid: cr=c.execute('SELECT name,phone FROM clients WHERE id=?',(cid,)).fetchone(); name=cr['name'] if cr else ''; phone=phone or (cr['phone'] if cr else '')
        cur=c.execute('INSERT INTO tickets(subject,client_id,client,phone,priority,status,description,assigned_to,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(request.form['subject'].strip(),cid,name,phone,request.form.get('priority','MEDIA'),'NUEVO',request.form.get('description',''),request.form.get('assigned_to',''),now(),now())); c.commit(); tid=cur.lastrowid; c.close(); audit('CREAR','ticket',tid,request.form['subject']); return redirect(url_for('ticket_view',id=tid))
    opts='<option value="">Sin cliente vinculado</option>'+''.join(f"<option value='{x['id']}' {'selected' if str(x['id'])==str(pre) else ''}>{e(x['name'])}</option>" for x in clients_); c.close(); body=f'<div class="head"><div><h1>Nuevo ticket</h1></div></div><div class="panel"><form class="grid" method="post"><div class="field full"><label>Asunto</label><input name="subject" required></div><div class="field"><label>Cliente</label><select name="client_id">{opts}</select></div><div class="field"><label>Teléfono</label><input name="phone"></div><div class="field"><label>Prioridad</label><select name="priority"><option>BAJA</option><option selected>MEDIA</option><option>ALTA</option></select></div><div class="field"><label>Técnico asignado</label><input name="assigned_to"></div><div class="field full"><label>Descripción</label><textarea name="description"></textarea></div><div><button class="btn green">Crear ticket</button></div></form></div>'; return shell('Nuevo ticket',body,'support')
@app.route('/support/<int:id>',methods=['GET','POST'])
@login_required
def ticket_view(id):
    c=con(); r=c.execute('SELECT t.*,c.name client_name FROM tickets t LEFT JOIN clients c ON c.id=t.client_id WHERE t.id=?',(id,)).fetchone()
    if not r: c.close(); return ('No encontrado',404)
    if request.method=='POST': c.execute('UPDATE tickets SET status=?,priority=?,assigned_to=?,description=?,updated_at=? WHERE id=?',(request.form.get('status'),request.form.get('priority'),request.form.get('assigned_to',''),request.form.get('description',''),now(),id)); c.commit(); c.close(); audit('ACTUALIZAR','ticket',id,request.form.get('status')); return redirect(url_for('ticket_view',id=id))
    c.close(); statuses=['NUEVO','ASIGNADO','EN PROGRESO','RESUELTO','CERRADO']; body=f'<div class="head"><div><h1>Ticket #{id}</h1><p>{e(r["subject"])} · {e(r["client_name"] or r["client"])}</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Estado</label><select name="status">{"".join(f"<option {\"selected\" if r[\"status\"]==s else \"\"}>{s}</option>" for s in statuses)}</select></div><div class="field"><label>Prioridad</label><select name="priority">{"".join(f"<option {\"selected\" if r[\"priority\"]==s else \"\"}>{s}</option>" for s in ["BAJA","MEDIA","ALTA"])}</select></div><div class="field full"><label>Técnico</label><input name="assigned_to" value="{e(r["assigned_to"])}"></div><div class="field full"><label>Descripción / seguimiento</label><textarea name="description">{e(r["description"])}</textarea></div><div><button class="btn green">Actualizar ticket</button></div></form></div>'; return shell('Ticket',body,'support')

@app.route('/installations',methods=['GET','POST'])
@login_required
def installations():
    c=con()
    if request.method=='POST': cur=c.execute('INSERT INTO installations(client_name,phone,address,zone_id,scheduled_date,status,technician,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(request.form['client_name'].strip(),request.form.get('phone',''),request.form.get('address',''),request.form.get('zone_id') or None,request.form.get('scheduled_date') or today(),'PENDIENTE',request.form.get('technician',''),request.form.get('notes',''),now())); c.commit(); audit('CREAR','installation',cur.lastrowid,request.form['client_name'])
    rows=c.execute('SELECT i.*,z.name zone FROM installations i LEFT JOIN zones z ON z.id=i.zone_id ORDER BY i.id DESC').fetchall(); zones_=c.execute('SELECT id,name FROM zones WHERE active=1 ORDER BY name').fetchall(); c.close(); zo='<option value="">Sin zona</option>'+''.join(f"<option value='{z['id']}'>{e(z['name'])}</option>" for z in zones_); trs=''.join(f"<tr><td>#{r['id']}</td><td><b>{e(r['client_name'])}</b><br><small>{e(r['phone'])}</small></td><td>{e(r['zone']) or '-'}</td><td>{e(r['scheduled_date'])}</td><td>{e(r['technician']) or '-'}</td><td><span class='tag {'ok' if r['status']=='COMPLETADA' else 'pending'}'>{e(r['status'])}</span></td><td><form method='post' action='{url_for('installation_done',id=r['id'])}'><button class='btn small'>Completar</button></form></td></tr>" for r in rows); body=f'<div class="head"><div><h1>Instalaciones</h1><p>Agenda de clientes nuevos</p></div></div><div class="twocol"><div class="panel"><h3>Nueva instalación</h3><form class="grid" method="post"><div class="field full"><label>Cliente</label><input name="client_name" required></div><div class="field"><label>Teléfono</label><input name="phone"></div><div class="field"><label>Zona</label><select name="zone_id">{zo}</select></div><div class="field full"><label>Dirección</label><input name="address"></div><div class="field"><label>Fecha</label><input type="date" name="scheduled_date" value="{today()}"></div><div class="field"><label>Técnico</label><input name="technician"></div><div class="field full"><label>Notas</label><textarea name="notes"></textarea></div><div><button class="btn green">Guardar</button></div></form></div><div class="panel"><h3>Agenda</h3><table><tr><th>ID</th><th>Cliente</th><th>Zona</th><th>Fecha</th><th>Técnico</th><th>Estado</th><th></th></tr>{trs or "<tr><td colspan=7 class=empty>Sin instalaciones.</td></tr>"}</table></div></div>'; return shell('Instalaciones',body,'installations')
@app.post('/installations/<int:id>/done')
@login_required
def installation_done(id): c=con(); c.execute("UPDATE installations SET status='COMPLETADA' WHERE id=?",(id,)); c.commit(); c.close(); audit('COMPLETAR','installation',id,''); return redirect(url_for('installations'))

@app.get('/whatsapp')
@login_required
def whatsapp(): return shell('WhatsApp',f'<div class="head"><div><h1>WhatsApp</h1><p>Plantillas y accesos rápidos</p></div></div><div class="threecol"><div class="card"><div class="label">Bienvenida</div><p>{e(setting("welcome_message"))}</p></div><div class="card"><div class="label">Vencimiento</div><p>{e(setting("due_message"))}</p></div><div class="card"><div class="label">Suspensión</div><p>{e(setting("suspended_message"))}</p></div></div><div class="panel"><p>Las plantillas se editan en <b>Configuración</b>. Desde la ficha de cada cliente puedes abrir WhatsApp con el mensaje listo para enviar.</p></div>','whatsapp')
@app.get('/whatsapp/client/<int:id>')
@login_required
def whatsapp_client(id):
    c=con(); r=c.execute('SELECT c.*,coalesce(sum(CASE WHEN i.status="PENDIENTE" THEN i.amount ELSE 0 END),0) balance FROM clients c LEFT JOIN invoices i ON i.client_id=c.id WHERE c.id=? GROUP BY c.id',(id,)).fetchone(); c.close()
    if not r: return ('No encontrado',404)
    tpl=setting('due_message'); msg=tpl.replace('{nombre}',r['name'] or '').replace('{monto}',money(r['balance'])); phone=''.join(ch for ch in (r['phone'] or '') if ch.isdigit()); import urllib.parse; link=f'https://wa.me/{phone}?text={urllib.parse.quote(msg)}' if phone else '#'; body=f'<div class="head"><div><h1>WhatsApp</h1><p>{e(r["name"])}</p></div></div><div class="panel"><div class="field"><label>Mensaje</label><textarea readonly>{e(msg)}</textarea></div><p><a class="btn green" target="_blank" href="{link}">Abrir WhatsApp</a></p></div>'; return shell('WhatsApp cliente',body,'whatsapp')

@app.get('/reports')
@login_required
def reports():
    c=con(); month=date.today().strftime('%Y-%m'); income=c.execute("SELECT coalesce(sum(amount),0) s FROM payments WHERE substr(paid_at,1,7)=?",(month,)).fetchone()['s']; expense=c.execute("SELECT coalesce(sum(amount),0) s FROM expenses WHERE substr(expense_date,1,7)=?",(month,)).fetchone()['s']; pending=c.execute("SELECT coalesce(sum(amount),0) s FROM invoices WHERE status='PENDIENTE'").fetchone()['s']; total=c.execute('SELECT count(*) c FROM clients').fetchone()['c']; active=c.execute("SELECT count(*) c FROM clients WHERE status='ACTIVO'").fetchone()['c']; plans_=c.execute('SELECT p.name,count(c.id) n FROM plans p LEFT JOIN clients c ON c.plan_id=p.id GROUP BY p.id ORDER BY n DESC').fetchall(); c.close(); prow=''.join(f"<tr><td>{e(r['name'])}</td><td>{r['n']}</td></tr>" for r in plans_); body=f'<div class="head"><div><h1>Reportes</h1><p>Resumen del mes {month}</p></div><div class="actions"><a class="btn" href="{url_for("clients_export")}">Clientes CSV</a><a class="btn" href="{url_for("invoices_export")}">Facturas CSV</a></div></div><div class="cards"><div class="card"><div class="label">Ingresos del mes</div><div class="num">{money(income)}</div></div><div class="card"><div class="label">Gastos del mes</div><div class="num">{money(expense)}</div></div><div class="card"><div class="label">Balance operativo</div><div class="num">{money(income-expense)}</div></div><div class="card"><div class="label">Por cobrar</div><div class="num">{money(pending)}</div></div></div><div class="twocol"><div class="panel"><h3>Clientes</h3><div class="num">{active}/{total}</div><div class="muted">activos / registrados</div></div><div class="panel"><h3>Clientes por plan</h3><table><tr><th>Plan</th><th>Clientes</th></tr>{prow or "<tr><td colspan=2 class=empty>Sin datos.</td></tr>"}</table></div></div>'; return shell('Reportes',body,'reports')

@app.route('/settings',methods=['GET','POST'])
@login_required
def settings_page():
    keys=['company_name','currency','whatsapp_number','invoice_prefix','invoice_days_before_due','cut_delay_days','cut_time','welcome_message','due_message','suspended_message']
    if request.method=='POST':
        c=con()
        for k in keys: c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,request.form.get(k,'')))
        c.commit(); c.close(); audit('ACTUALIZAR','settings','','Configuración general'); flash('Configuración guardada.','success'); return redirect(url_for('settings_page'))
    vals={k:setting(k) for k in keys}; body=f'<div class="head"><div><h1>Configuración</h1><p>Datos generales, facturación y mensajes</p></div></div><div class="panel"><form class="grid" method="post"><div class="field"><label>Empresa</label><input name="company_name" value="{e(vals["company_name"])}"></div><div class="field"><label>Moneda</label><input name="currency" value="{e(vals["currency"])}"></div><div class="field"><label>Número WhatsApp de la empresa</label><input name="whatsapp_number" value="{e(vals["whatsapp_number"])}"></div><div class="field"><label>Prefijo de factura</label><input name="invoice_prefix" value="{e(vals["invoice_prefix"])}"></div><div class="field"><label>Días antes del vencimiento para factura</label><input type="number" name="invoice_days_before_due" value="{e(vals["invoice_days_before_due"])}"></div><div class="field"><label>Días después del vencimiento para corte</label><input type="number" name="cut_delay_days" value="{e(vals["cut_delay_days"])}"></div><div class="field"><label>Hora de corte</label><input type="time" name="cut_time" value="{e(vals["cut_time"])}"></div><div></div><div class="field full"><label>Mensaje de bienvenida</label><textarea name="welcome_message">{e(vals["welcome_message"])}</textarea></div><div class="field full"><label>Mensaje de vencimiento · variables: {{nombre}} {{monto}}</label><textarea name="due_message">{e(vals["due_message"])}</textarea></div><div class="field full"><label>Mensaje de suspensión</label><textarea name="suspended_message">{e(vals["suspended_message"])}</textarea></div><div><button class="btn green">Guardar configuración</button></div></form></div>'; return shell('Configuración',body,'settings_page')

@app.get('/audit')
@login_required
def audit_page():
    c=con(); rows=c.execute('SELECT * FROM audit_logs ORDER BY id DESC LIMIT 300').fetchall(); c.close(); trs=''.join(f"<tr><td>{e(r['created_at'])}</td><td>{e(r['action'])}</td><td>{e(r['entity'])} {e(r['entity_id'])}</td><td>{e(r['detail'])}</td></tr>" for r in rows); return shell('Auditoría',f'<div class="head"><div><h1>Auditoría</h1><p>Últimas acciones administrativas</p></div></div><div class="panel"><table><tr><th>Fecha</th><th>Acción</th><th>Entidad</th><th>Detalle</th></tr>{trs or "<tr><td colspan=4 class=empty>Sin eventos.</td></tr>"}</table></div>','audit_page')

@app.get('/export/clients.csv')
@login_required
def clients_export():
    c=con(); rows=c.execute('SELECT c.id,c.name,c.phone,c.email,c.document,c.address,c.pppoe,c.status,p.name plan,z.name zone FROM clients c LEFT JOIN plans p ON p.id=c.plan_id LEFT JOIN zones z ON z.id=c.zone_id ORDER BY c.id').fetchall(); c.close(); out=io.StringIO(); w=csv.writer(out); w.writerow(['ID','Nombre','Teléfono','Email','Documento','Dirección','PPPoE','Estado','Plan','Zona']); [w.writerow(list(r)) for r in rows]; return Response('\ufeff'+out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=clientes-interflash.csv'})
@app.get('/export/invoices.csv')
@login_required
def invoices_export():
    c=con(); rows=c.execute('SELECT i.invoice_no,c.name client,i.concept,i.amount,i.issue_date,i.due_date,i.status,i.paid_at FROM invoices i JOIN clients c ON c.id=i.client_id ORDER BY i.id').fetchall(); c.close(); out=io.StringIO(); w=csv.writer(out); w.writerow(['Factura','Cliente','Concepto','Monto','Emisión','Vencimiento','Estado','Pagada']); [w.writerow(list(r)) for r in rows]; return Response('\ufeff'+out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=facturas-interflash.csv'})

if __name__=='__main__': app.run(host='0.0.0.0',port=PORT)
