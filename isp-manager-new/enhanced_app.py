import base64
import hashlib
from flask import request, redirect, url_for, flash
from cryptography.fernet import Fernet
import routeros_api
import app as base

app = base.app
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(base.SECRET_KEY.encode()).digest()))


def enc(value):
    return FERNET.encrypt((value or '').encode()).decode() if value else ''


def dec(value):
    if not value:
        return ''
    try:
        return FERNET.decrypt(value.encode()).decode()
    except Exception:
        return ''


def esc(value):
    import html
    return html.escape(str(value if value is not None else ''))


def ensure_schema():
    c = base.db()
    existing = {r['name'] for r in c.execute('PRAGMA table_info(routers)').fetchall()}
    additions = [
        ('port','INTEGER DEFAULT 8728'),('username','TEXT'),('password_enc','TEXT'),
        ('use_ssl','INTEGER DEFAULT 0'),('verify_ssl','INTEGER DEFAULT 0'),
        ('model','TEXT'),('ros_version','TEXT'),('serial_number','TEXT'),('uptime','TEXT'),
        ('cpu_load','INTEGER DEFAULT 0'),('free_memory','TEXT'),('total_memory','TEXT'),
        ('last_error','TEXT'),('last_sync','TEXT'),('notes','TEXT')
    ]
    for name, ddl in additions:
        if name not in existing:
            c.execute(f'ALTER TABLE routers ADD COLUMN {name} {ddl}')
    c.commit(); c.close()


def row_for(router_id):
    c = base.db(); r = c.execute('SELECT * FROM routers WHERE id=?',(router_id,)).fetchone(); c.close(); return r


def connect_router(r):
    return routeros_api.RouterOsApiPool(
        host=r['host'],
        username=r['username'] or '',
        password=dec(r['password_enc']),
        port=int(r['port'] or (8729 if r['use_ssl'] else 8728)),
        use_ssl=bool(r['use_ssl']),
        ssl_verify=bool(r['verify_ssl']),
        plaintext_login=True,
    )


def read_router(router_id):
    r = row_for(router_id)
    if not r:
        return False, 'Router no encontrado.'
    pool = None
    try:
        pool = connect_router(r)
        api = pool.get_api()
        identities = api.get_resource('/system/identity').get()
        resources = api.get_resource('/system/resource').get()
        active = api.get_resource('/ppp/active').get()
        secrets = api.get_resource('/ppp/secret').get()
        ident = identities[0] if identities else {}
        res = resources[0] if resources else {}
        c = base.db()
        c.execute('''UPDATE routers SET
            status='ONLINE', identity=?, model=?, ros_version=?, serial_number=?, uptime=?,
            cpu_load=?, free_memory=?, total_memory=?, pppoe_active=?, pppoe_total=?,
            last_seen=?, last_sync=?, last_error=''
            WHERE id=?''',(
            ident.get('name',''), res.get('board-name',''), res.get('version',''),
            res.get('serial-number',''), res.get('uptime',''), int(res.get('cpu-load',0) or 0),
            res.get('free-memory',''), res.get('total-memory',''), len(active), len(secrets),
            base.datetime.now().isoformat(timespec='seconds'), base.datetime.now().isoformat(timespec='seconds'), router_id
        ))
        c.commit(); c.close()
        base.audit('ROUTER_SYNC', f"#{router_id} {ident.get('name','')} · PPPoE {len(active)}/{len(secrets)}")
        return True, f'{len(active)} PPPoE activos de {len(secrets)} configurados.'
    except Exception as ex:
        msg = str(ex)[:450]
        c = base.db(); c.execute("UPDATE routers SET status='ERROR',last_error=? WHERE id=?",(msg,router_id)); c.commit(); c.close()
        return False, msg
    finally:
        try:
            if pool:
                pool.disconnect()
        except Exception:
            pass


def routers_complete():
    if not base.logged_in():
        return redirect(url_for('login'))
    c = base.db(); rows = c.execute('SELECT * FROM routers ORDER BY id DESC').fetchall(); c.close()
    online = sum(1 for r in rows if r['status']=='ONLINE')
    active = sum(int(r['pppoe_active'] or 0) for r in rows)
    total = sum(int(r['pppoe_total'] or 0) for r in rows)
    errors = sum(1 for r in rows if r['status']=='ERROR')
    stats=f'''<div class="grid6" style="grid-template-columns:repeat(4,minmax(150px,1fr))">
      <div class="kpi blue1"><div class="label">Routers</div><div class="value">{len(rows)}</div><div class="sub">Configurados</div></div>
      <div class="kpi green1"><div class="label">Conectados</div><div class="value">{online}</div><div class="sub">En línea</div></div>
      <div class="kpi purple1"><div class="label">PPPoE activos</div><div class="value">{active}</div><div class="sub">de {total} configurados</div></div>
      <div class="kpi {'red1' if errors else 'cyan1'}"><div class="label">Errores</div><div class="value">{errors}</div><div class="sub">Conexiones con problema</div></div>
    </div>'''
    trs=[]
    for r in rows:
        cls='ok' if r['status']=='ONLINE' else 'bad' if r['status']=='ERROR' else 'warn'
        err=f'<div class="muted" style="max-width:260px;margin-top:4px">{esc(r["last_error"])}</div>' if r['last_error'] else ''
        trs.append(f'''<tr>
          <td><b>{esc(r['name'])}</b><br><span class="muted">{esc(r['identity']) or 'Identity automático'}</span></td>
          <td><span style="font-family:Consolas,monospace">{esc(r['host'])}:{int(r['port'] or 8728)}</span><br><span class="muted">{'API-SSL' if r['use_ssl'] else 'API'}</span></td>
          <td>{esc(r['username']) or '-'}</td>
          <td><span class="tag {cls}">{esc(r['status'])}</span>{err}</td>
          <td>{esc(r['model']) or '-'}<br><span class="muted">ROS {esc(r['ros_version']) or '-'}</span></td>
          <td><b>{int(r['pppoe_active'] or 0)}</b> / {int(r['pppoe_total'] or 0)}</td>
          <td>{int(r['cpu_load'] or 0)}%<br><span class="muted">{esc(r['uptime']) or '-'}</span></td>
          <td>{esc(r['last_seen']) or '-'}</td>
          <td><div style="display:flex;gap:6px;flex-wrap:wrap">
            <a class="btn blue" style="padding:6px 9px" href="{url_for('router_test_full',id=r['id'])}">Probar</a>
            <a class="btn green" style="padding:6px 9px" href="{url_for('router_sync_full',id=r['id'])}">Sincronizar</a>
            <a class="btn" style="padding:6px 9px" href="{url_for('router_edit_full',id=r['id'])}">Editar</a>
            <form method="post" action="{url_for('router_delete_full',id=r['id'])}" onsubmit="return confirm('¿Eliminar este router de la página?')" style="display:inline"><button class="btn" style="padding:6px 9px;background:#4a161b;border-color:#7c2d35;color:#ff9aa2">Eliminar</button></form>
          </div></td>
        </tr>''')
    table=''.join(trs) or '<tr><td colspan="9" class="muted">No hay routers configurados.</td></tr>'
    body=f'''<div class="head"><div><h1>Routers MikroTik</h1><p>Configuración, prueba y sincronización de tus routers.</p></div><a class="btn green" href="{url_for('router_new_full')}">+ Agregar router</a></div>
    {stats}
    <div class="panel"><div style="padding:10px;border-radius:8px;background:#17304b;color:#bfdbfe;margin-bottom:14px">La conexión de esta sección es <b>solo lectura</b>. Lee Identity, modelo, RouterOS, CPU, uptime y PPPoE. No suspende ni modifica clientes.</div>
    <table class="table"><tr><th>Router</th><th>Host / API</th><th>Usuario</th><th>Estado</th><th>Equipo</th><th>PPPoE</th><th>CPU / Uptime</th><th>Última conexión</th><th>Acciones</th></tr>{table}</table></div>'''
    return base.shell('Routers',body,'routers')


def router_form(r=None):
    editing=r is not None
    def val(k, default=''):
        return esc(r[k]) if editing and k in r.keys() and r[k] is not None else default
    action=url_for('router_edit_full',id=r['id']) if editing else url_for('router_new_full')
    ssl_checked='checked' if editing and r['use_ssl'] else ''
    verify_checked='checked' if editing and r['verify_ssl'] else ''
    body=f'''<div class="head"><div><h1>{'Editar' if editing else 'Agregar'} router</h1><p>Datos para acceder por API de MikroTik.</p></div><a class="btn" href="{url_for('routers')}">← Volver</a></div>
    <div class="panel"><form class="formgrid" method="post" action="{action}">
      <label>Nombre<input name="name" value="{val('name')}" placeholder="Ej. CCR2116" required></label>
      <label>Host / IP / DDNS<input name="host" value="{val('host')}" placeholder="IP pública, privada o DDNS" required></label>
      <label>Usuario API<input name="username" value="{val('username')}" autocomplete="off" required></label>
      <label>Contraseña API<input type="password" name="password" autocomplete="new-password" placeholder="{'Déjala vacía para conservarla' if editing else 'Contraseña del MikroTik'}" {'required' if not editing else ''}></label>
      <label>Puerto API<input type="number" min="1" max="65535" name="port" value="{val('port','8728')}" required></label>
      <label>Notas<input name="notes" value="{val('notes')}" placeholder="Ej. Router principal"></label>
      <label><input style="width:auto;margin-right:8px" type="checkbox" name="use_ssl" value="1" {ssl_checked}>Usar API-SSL (normalmente 8729)</label>
      <label><input style="width:auto;margin-right:8px" type="checkbox" name="verify_ssl" value="1" {verify_checked}>Verificar certificado SSL</label>
      <div class="full"><button class="btn green">Guardar router</button></div>
    </form></div>
    <div class="panel"><b>Automático después de probar:</b><p class="muted">Identity, modelo, versión RouterOS, serial, uptime, CPU, memoria, PPPoE activos/configurados y última conexión.</p></div>'''
    return base.shell('Router',body,'routers')


@app.route('/router-manager/new',methods=['GET','POST'],endpoint='router_new_full')
@base.login_required
def router_new_full():
    if request.method=='POST':
        use_ssl=1 if request.form.get('use_ssl') else 0
        port=int(request.form.get('port') or (8729 if use_ssl else 8728))
        c=base.db(); cur=c.execute('''INSERT INTO routers(name,host,status,port,username,password_enc,use_ssl,verify_ssl,notes) VALUES(?,?,?,?,?,?,?,?,?)''',(
            request.form.get('name','').strip(),request.form.get('host','').strip(),'PENDIENTE',port,
            request.form.get('username','').strip(),enc(request.form.get('password','')),use_ssl,1 if request.form.get('verify_ssl') else 0,request.form.get('notes','')
        )); rid=cur.lastrowid; c.commit(); c.close(); base.audit('ROUTER_CREATE',f'#{rid} {request.form.get("name","")}'); flash('Router guardado. Ahora pulsa Probar.'); return redirect(url_for('routers'))
    return router_form()


@app.route('/router-manager/<int:id>/edit',methods=['GET','POST'],endpoint='router_edit_full')
@base.login_required
def router_edit_full(id):
    r=row_for(id)
    if not r:
        flash('Router no encontrado.'); return redirect(url_for('routers'))
    if request.method=='POST':
        password=request.form.get('password',''); password_enc=enc(password) if password else r['password_enc']
        use_ssl=1 if request.form.get('use_ssl') else 0
        port=int(request.form.get('port') or (8729 if use_ssl else 8728))
        c=base.db(); c.execute('''UPDATE routers SET name=?,host=?,port=?,username=?,password_enc=?,use_ssl=?,verify_ssl=?,notes=?,status='PENDIENTE' WHERE id=?''',(
            request.form.get('name','').strip(),request.form.get('host','').strip(),port,request.form.get('username','').strip(),password_enc,use_ssl,1 if request.form.get('verify_ssl') else 0,request.form.get('notes',''),id
        )); c.commit(); c.close(); base.audit('ROUTER_EDIT',f'#{id}'); flash('Router actualizado.'); return redirect(url_for('routers'))
    return router_form(r)


@app.get('/router-manager/<int:id>/test',endpoint='router_test_full')
@base.login_required
def router_test_full(id):
    ok,msg=read_router(id); flash(('Conexión correcta. ' if ok else 'No se pudo conectar. ')+msg); return redirect(url_for('routers'))


@app.get('/router-manager/<int:id>/sync',endpoint='router_sync_full')
@base.login_required
def router_sync_full(id):
    ok,msg=read_router(id); flash(('Sincronización completada. ' if ok else 'Error de sincronización. ')+msg); return redirect(url_for('routers'))


@app.post('/router-manager/<int:id>/delete',endpoint='router_delete_full')
@base.login_required
def router_delete_full(id):
    r=row_for(id); c=base.db(); c.execute('DELETE FROM routers WHERE id=?',(id,)); c.commit(); c.close(); base.audit('ROUTER_DELETE',f'#{id} {r["name"] if r else ""}'); flash('Router eliminado de la página.'); return redirect(url_for('routers'))


ensure_schema()
app.view_functions['routers']=routers_complete
