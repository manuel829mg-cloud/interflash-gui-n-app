import ssl
from flask import request, redirect, url_for, flash
import routeros_api
import app as base

app = base.app


def _ensure_router_columns():
    c = base.con()
    for name, ddl in [
        ('serial_number','TEXT'),('uptime','TEXT'),('cpu_load','INTEGER DEFAULT 0'),
        ('free_memory','TEXT'),('total_memory','TEXT'),('pppoe_total','INTEGER DEFAULT 0'),
        ('last_sync','TEXT'),('notes','TEXT')
    ]:
        base.addcol(c, 'routers', name, ddl)
    c.commit(); c.close()


def _router_connect(r):
    kwargs = dict(
        host=r['host'],
        username=r['username'] or '',
        password=base.dec(r['password_enc']) if r['password_enc'] else '',
        port=int(r['port'] or (8729 if r['use_ssl'] else 8728)),
        use_ssl=bool(r['use_ssl']),
        ssl_verify=bool(r['verify_ssl']),
        plaintext_login=True,
    )
    if r['use_ssl'] and not r['verify_ssl']:
        kwargs['ssl_verify'] = False
    pool = routeros_api.RouterOsApiPool(**kwargs)
    return pool, pool.get_api()


def _sync_router(router_id):
    c = base.con(); r = c.execute('SELECT * FROM routers WHERE id=?',(router_id,)).fetchone(); c.close()
    if not r:
        return False, 'Router no encontrado.'
    pool = None
    try:
        pool, api = _router_connect(r)
        identity_rows = api.get_resource('/system/identity').get()
        resource_rows = api.get_resource('/system/resource').get()
        active_rows = api.get_resource('/ppp/active').get()
        secret_rows = api.get_resource('/ppp/secret').get()
        ident = identity_rows[0] if identity_rows else {}
        res = resource_rows[0] if resource_rows else {}
        c = base.con()
        c.execute('''UPDATE routers SET status=?,identity=?,model=?,ros_version=?,serial_number=?,uptime=?,cpu_load=?,free_memory=?,total_memory=?,pppoe_active=?,pppoe_total=?,last_seen=?,last_sync=?,last_error=? WHERE id=?''',(
            'CONECTADO', ident.get('name',''), res.get('board-name',''), res.get('version',''), res.get('serial-number',''),
            res.get('uptime',''), int(res.get('cpu-load',0) or 0), res.get('free-memory',''), res.get('total-memory',''),
            len(active_rows), len(secret_rows), base.now(), base.now(), '', router_id
        ))
        c.commit(); c.close()
        base.audit('SINCRONIZAR','router',router_id,f"Identity {ident.get('name','')} · PPPoE activos {len(active_rows)}")
        return True, f"Conexión correcta. {len(active_rows)} PPPoE activos de {len(secret_rows)} configurados."
    except Exception as ex:
        msg = str(ex)[:400]
        c = base.con(); c.execute('UPDATE routers SET status=?,last_error=? WHERE id=?',('ERROR',msg,router_id)); c.commit(); c.close()
        return False, msg
    finally:
        try:
            if pool: pool.disconnect()
        except Exception:
            pass


def routers_view():
    if not base.session.get('auth'):
        return redirect(url_for('login'))
    c = base.con(); rows = c.execute('SELECT * FROM routers ORDER BY id DESC').fetchall(); c.close()
    online = sum(1 for r in rows if r['status']=='CONECTADO')
    active = sum(int(r['pppoe_active'] or 0) for r in rows)
    total = sum(int(r['pppoe_total'] or 0) for r in rows)
    cards = f'''<div class="cards">
      <div class="card"><div class="label">Routers</div><div class="num">{len(rows)}</div><div class="muted">Configurados</div></div>
      <div class="card"><div class="label">Conectados</div><div class="num">{online}</div><div class="muted">En línea</div></div>
      <div class="card"><div class="label">PPPoE activos</div><div class="num">{active}</div><div class="muted">Sesiones</div></div>
      <div class="card"><div class="label">PPPoE configurados</div><div class="num">{total}</div><div class="muted">Secrets</div></div>
    </div>'''
    trs=[]
    for r in rows:
        cls='ok' if r['status']=='CONECTADO' else 'bad' if r['status']=='ERROR' else 'pending'
        err = f"<div class='muted' style='max-width:250px'>{base.e(r['last_error'])}</div>" if r['last_error'] else ''
        trs.append(f'''<tr>
          <td><b>{base.e(r['name'])}</b><br><span class="muted">{base.e(r['identity']) or 'Identity pendiente'}</span></td>
          <td class="mono">{base.e(r['host'])}:{r['port']}</td>
          <td>{base.e(r['username']) or '-'}</td>
          <td><span class="tag {cls}">{base.e(r['status'])}</span>{err}</td>
          <td>{base.e(r['model']) or '-'}</td><td>{base.e(r['ros_version']) or '-'}</td>
          <td>{int(r['pppoe_active'] or 0)} / {int(r['pppoe_total'] or 0)}</td>
          <td>{base.e(r['cpu_load'])}%<br><span class="muted">{base.e(r['uptime']) or '-'}</span></td>
          <td>{base.e(r['last_seen']) or '-'}</td>
          <td><div class="actions">
            <a class="btn blue small" href="{url_for('router_full_test',id=r['id'])}">Probar</a>
            <a class="btn green small" href="{url_for('router_full_sync',id=r['id'])}">Sincronizar</a>
            <a class="btn small" href="{url_for('router_full_edit',id=r['id'])}">Editar</a>
            <a class="btn red small" href="{url_for('router_full_delete',id=r['id'])}" onclick="return confirm('¿Eliminar este router de la página?')">Eliminar</a>
          </div></td></tr>''')
    table=''.join(trs) or '<tr><td colspan="10" class="empty">No hay routers configurados.</td></tr>'
    body=f'''<div class="head"><div><h1>Routers MikroTik</h1><p>Administración, prueba y sincronización de tus routers.</p></div><a class="btn green" href="{url_for('router_full_new')}">+ Agregar router</a></div>
    {cards}
    <div class="notice">Las pruebas y la sincronización de esta pantalla son de solo lectura: consultan Identity, RouterOS, recursos y PPPoE. No suspenden ni modifican clientes.</div>
    <div class="panel"><table><tr><th>Router</th><th>Host / API</th><th>Usuario</th><th>Estado</th><th>Modelo</th><th>RouterOS</th><th>PPPoE</th><th>CPU / Uptime</th><th>Última conexión</th><th>Acciones</th></tr>{table}</table></div>'''
    return base.shell('Routers', body, 'routers')


def _router_form(row=None):
    editing = row is not None
    title = 'Editar router' if editing else 'Agregar router'
    rid = row['id'] if editing else ''
    def v(k, default=''):
        return base.e(row[k]) if editing and k in row.keys() and row[k] is not None else default
    checked_ssl = 'checked' if editing and row['use_ssl'] else ''
    checked_verify = 'checked' if editing and row['verify_ssl'] else ''
    action = url_for('router_full_edit',id=rid) if editing else url_for('router_full_new')
    body=f'''<div class="head"><div><h1>{title}</h1><p>Configura el acceso API del MikroTik.</p></div><a class="btn" href="{url_for('routers')}">← Volver</a></div>
    <div class="panel"><form class="grid" method="post" action="{action}">
      <div class="field"><label>Nombre del router</label><input name="name" value="{v('name')}" placeholder="Ej. CCR2116" required></div>
      <div class="field"><label>Host / IP / DDNS</label><input name="host" value="{v('host')}" placeholder="Ej. 192.168.88.1 o mi-router.sn.mynetname.net" required></div>
      <div class="field"><label>Usuario API</label><input name="username" value="{v('username')}" autocomplete="off" required></div>
      <div class="field"><label>Contraseña API</label><input type="password" name="password" autocomplete="new-password" placeholder="{'Déjala vacía para conservarla' if editing else 'Contraseña del usuario API'}" {'required' if not editing else ''}></div>
      <div class="field"><label>Puerto API</label><input type="number" min="1" max="65535" name="port" value="{v('port','8728')}" required></div>
      <div class="field"><label>Notas</label><input name="notes" value="{v('notes')}" placeholder="Ej. Router principal"></div>
      <div class="field"><label><input type="checkbox" name="use_ssl" value="1" {checked_ssl}> Usar API-SSL (normalmente puerto 8729)</label></div>
      <div class="field"><label><input type="checkbox" name="verify_ssl" value="1" {checked_verify}> Verificar certificado SSL</label></div>
      <div class="full"><button class="btn green" type="submit">Guardar router</button></div>
    </form></div>
    <div class="notice">Identity, modelo, versión, serial, uptime y cantidad PPPoE se llenan automáticamente al pulsar Probar o Sincronizar.</div>'''
    return base.shell(title, body, 'routers')


@app.route('/router-manager/new', methods=['GET','POST'], endpoint='router_full_new')
def router_full_new():
    if not base.session.get('auth'): return redirect(url_for('login'))
    if request.method=='POST':
        name=request.form.get('name','').strip(); host=request.form.get('host','').strip(); username=request.form.get('username','').strip(); password=request.form.get('password','')
        port=int(request.form.get('port') or (8729 if request.form.get('use_ssl') else 8728))
        c=base.con(); cur=c.execute('''INSERT INTO routers(name,host,port,username,password_enc,use_ssl,verify_ssl,status,created_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?)''',(
            name,host,port,username,base.enc(password),1 if request.form.get('use_ssl') else 0,1 if request.form.get('verify_ssl') else 0,'PENDIENTE',base.now(),request.form.get('notes','')
        )); rid=cur.lastrowid; c.commit(); c.close(); base.audit('CREAR','router',rid,f'{name} {host}:{port}'); flash('Router guardado. Ahora puedes probar la conexión.','success'); return redirect(url_for('routers'))
    return _router_form()


@app.route('/router-manager/<int:id>/edit', methods=['GET','POST'], endpoint='router_full_edit')
def router_full_edit(id):
    if not base.session.get('auth'): return redirect(url_for('login'))
    c=base.con(); row=c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone()
    if not row: c.close(); flash('Router no encontrado.','error'); return redirect(url_for('routers'))
    if request.method=='POST':
        pwd=request.form.get('password',''); encpwd=base.enc(pwd) if pwd else row['password_enc']
        port=int(request.form.get('port') or (8729 if request.form.get('use_ssl') else 8728))
        c.execute('''UPDATE routers SET name=?,host=?,port=?,username=?,password_enc=?,use_ssl=?,verify_ssl=?,notes=?,status='PENDIENTE' WHERE id=?''',(
            request.form.get('name','').strip(),request.form.get('host','').strip(),port,request.form.get('username','').strip(),encpwd,
            1 if request.form.get('use_ssl') else 0,1 if request.form.get('verify_ssl') else 0,request.form.get('notes',''),id
        )); c.commit(); c.close(); base.audit('EDITAR','router',id,'Configuración API actualizada'); flash('Router actualizado.','success'); return redirect(url_for('routers'))
    c.close(); return _router_form(row)


@app.get('/router-manager/<int:id>/test', endpoint='router_full_test')
def router_full_test(id):
    if not base.session.get('auth'): return redirect(url_for('login'))
    ok,msg=_sync_router(id); flash(('Prueba correcta: ' if ok else 'No se pudo conectar: ')+msg,'success' if ok else 'error'); return redirect(url_for('routers'))


@app.get('/router-manager/<int:id>/sync', endpoint='router_full_sync')
def router_full_sync(id):
    if not base.session.get('auth'): return redirect(url_for('login'))
    ok,msg=_sync_router(id); flash(('Sincronización completada: ' if ok else 'Error de sincronización: ')+msg,'success' if ok else 'error'); return redirect(url_for('routers'))


@app.get('/router-manager/<int:id>/delete', endpoint='router_full_delete')
def router_full_delete(id):
    if not base.session.get('auth'): return redirect(url_for('login'))
    c=base.con(); r=c.execute('SELECT name FROM routers WHERE id=?',(id,)).fetchone(); c.execute('DELETE FROM routers WHERE id=?',(id,)); c.commit(); c.close(); base.audit('ELIMINAR','router',id,r['name'] if r else ''); flash('Router eliminado de la página.','success'); return redirect(url_for('routers'))


_ensure_router_columns()
app.view_functions['routers'] = routers_view
