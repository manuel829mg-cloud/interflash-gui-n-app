import app as base
from flask import request, redirect, url_for, flash

app = base.app
con = base.con
e = base.e
enc = base.enc
dec = base.dec
now = base.now
audit = base.audit
login_required = base.login_required
shell = base.shell
routeros_api = base.routeros_api


def _ensure_router_columns():
    c = con()
    cols = {r['name'] for r in c.execute('PRAGMA table_info(routers)').fetchall()}
    wanted = {
        'architecture_name': 'TEXT',
        'uptime': 'TEXT',
        'cpu_load': 'INTEGER DEFAULT 0',
        'cpu_count': 'INTEGER DEFAULT 0',
        'free_memory': 'TEXT',
        'total_memory': 'TEXT',
        'pppoe_total': 'INTEGER DEFAULT 0',
        'pppoe_disabled': 'INTEGER DEFAULT 0',
        'profiles_count': 'INTEGER DEFAULT 0',
        'interfaces_count': 'INTEGER DEFAULT 0',
        'last_sync': 'TEXT',
        'notes': 'TEXT'
    }
    for name, ddl in wanted.items():
        if name not in cols:
            c.execute(f'ALTER TABLE routers ADD COLUMN {name} {ddl}')
    c.commit()
    c.close()


_ensure_router_columns()


def _truthy(v):
    return str(v).lower() in ('true', 'yes', '1', 'on')


def _router_pool(r):
    return routeros_api.RouterOsApiPool(
        r['host'],
        username=r['username'] or '',
        password=dec(r['password_enc']),
        port=int(r['port'] or 8728),
        use_ssl=bool(r['use_ssl']),
        ssl_verify=bool(r['verify_ssl']),
        ssl_verify_hostname=bool(r['verify_ssl']),
        plaintext_login=True,
    )


def _read_router(r, full=True):
    pool = _router_pool(r)
    try:
        api = pool.get_api()
        ident_rows = api.get_resource('/system/identity').get()
        res_rows = api.get_resource('/system/resource').get()
        ident = ident_rows[0] if ident_rows else {}
        res = res_rows[0] if res_rows else {}
        active = api.get_resource('/ppp/active').get()
        data = {
            'identity': ident.get('name', ''),
            'model': res.get('board-name', ''),
            'ros_version': res.get('version', ''),
            'architecture_name': res.get('architecture-name', ''),
            'uptime': res.get('uptime', ''),
            'cpu_load': int(res.get('cpu-load') or 0),
            'cpu_count': int(res.get('cpu-count') or 0),
            'free_memory': str(res.get('free-memory', '')),
            'total_memory': str(res.get('total-memory', '')),
            'pppoe_active': len(active),
            'pppoe_total': 0,
            'pppoe_disabled': 0,
            'profiles_count': 0,
            'interfaces_count': 0,
        }
        if full:
            secrets = api.get_resource('/ppp/secret').get()
            profiles = api.get_resource('/ppp/profile').get()
            interfaces = api.get_resource('/interface').get()
            data['pppoe_total'] = len(secrets)
            data['pppoe_disabled'] = sum(1 for x in secrets if _truthy(x.get('disabled', False)))
            data['profiles_count'] = len(profiles)
            data['interfaces_count'] = len(interfaces)
        return data
    finally:
        try:
            pool.disconnect()
        except Exception:
            pass


def _save_router_status(router_id, data):
    c = con()
    c.execute('''UPDATE routers SET
        status='ONLINE', identity=?, model=?, ros_version=?, architecture_name=?, uptime=?,
        cpu_load=?, cpu_count=?, free_memory=?, total_memory=?, pppoe_active=?, pppoe_total=?,
        pppoe_disabled=?, profiles_count=?, interfaces_count=?, last_seen=?, last_sync=?, last_error=''
        WHERE id=?''', (
        data.get('identity',''), data.get('model',''), data.get('ros_version',''),
        data.get('architecture_name',''), data.get('uptime',''), data.get('cpu_load',0),
        data.get('cpu_count',0), data.get('free_memory',''), data.get('total_memory',''),
        data.get('pppoe_active',0), data.get('pppoe_total',0), data.get('pppoe_disabled',0),
        data.get('profiles_count',0), data.get('interfaces_count',0), now(), now(), router_id
    ))
    c.commit()
    c.close()


def _save_router_error(router_id, ex):
    c = con()
    c.execute("UPDATE routers SET status='ERROR',last_seen=?,last_error=? WHERE id=?",
              (now(), str(ex)[:500], router_id))
    c.commit()
    c.close()


def _selected(value, current):
    return 'selected' if str(value) == str(current) else ''


def router_form(r=None):
    def v(k, d=''):
        return e(r[k] if r is not None and k in r.keys() and r[k] is not None else d)
    ssl = int(r['use_ssl'] or 0) if r is not None and 'use_ssl' in r.keys() else 0
    verify = int(r['verify_ssl'] or 0) if r is not None and 'verify_ssl' in r.keys() else 0
    password_help = 'Déjala vacía para conservar la actual.' if r is not None else 'La contraseña se guarda cifrada.'
    return f'''
    <form class="grid" method="post">
      <div class="field"><label>Nombre del router</label><input name="name" value="{v('name')}" placeholder="Ej. CCR2116 Principal" required></div>
      <div class="field"><label>Host / IP / DDNS</label><input name="host" value="{v('host')}" placeholder="IP pública o DDNS" required></div>
      <div class="field"><label>Usuario RouterOS</label><input name="username" value="{v('username')}" autocomplete="username" required></div>
      <div class="field"><label>Contraseña RouterOS</label><input type="password" name="password" autocomplete="new-password" placeholder="{password_help}"></div>
      <div class="field"><label>Puerto API</label><input type="number" min="1" max="65535" name="port" value="{v('port',8728)}" required></div>
      <div class="field"><label>Usar SSL</label><select name="use_ssl"><option value="0" {_selected(0,ssl)}>No</option><option value="1" {_selected(1,ssl)}>Sí</option></select></div>
      <div class="field"><label>Verificar certificado SSL</label><select name="verify_ssl"><option value="0" {_selected(0,verify)}>No</option><option value="1" {_selected(1,verify)}>Sí</option></select></div>
      <div class="field"><label>Identity</label><input value="{v('identity')}" placeholder="Se detecta automáticamente" disabled></div>
      <div class="field full"><label>Notas</label><textarea name="notes" placeholder="Ubicación, proveedor, función del router...">{v('notes')}</textarea></div>
      <div class="full actions"><button class="btn green" name="action" value="save">Guardar</button><button class="btn blue" name="action" value="save_test">Guardar y probar conexión</button><a class="btn" href="{url_for('routers')}">Cancelar</a></div>
    </form>'''


base.router_form = router_form


@login_required
def routers_page():
    c = con()
    rows = c.execute('SELECT * FROM routers ORDER BY id DESC').fetchall()
    total = len(rows)
    online = sum(1 for r in rows if r['status'] == 'ONLINE')
    active = sum(int(r['pppoe_active'] or 0) for r in rows)
    secrets = sum(int(r['pppoe_total'] or 0) for r in rows)
    c.close()

    trs = ''
    for r in rows:
        state_class = 'ok' if r['status']=='ONLINE' else 'bad' if r['status']=='ERROR' else 'pending'
        sync_text = e(r['last_sync'] or r['last_seen'] or '-')
        details = f"{e(r['model']) or '-'}<br><small>{e(r['ros_version']) or '-'} · {e(r['architecture_name']) or '-'}</small>"
        ppp = f"<b>{int(r['pppoe_active'] or 0)}</b> activos / {int(r['pppoe_total'] or 0)} total<br><small>{int(r['pppoe_disabled'] or 0)} deshabilitados · {int(r['profiles_count'] or 0)} perfiles</small>"
        resources = f"CPU {int(r['cpu_load'] or 0)}%<br><small>Uptime {e(r['uptime']) or '-'}</small>"
        err = f"<br><small style='color:#b6371e'>{e(r['last_error'])}</small>" if r['last_error'] else ''
        trs += f"""<tr>
          <td>#{r['id']}</td>
          <td><b>{e(r['name'])}</b><br><small>{e(r['identity']) or 'Identity pendiente'}</small></td>
          <td class='mono'>{e(r['host'])}:{int(r['port'] or 8728)}<br><small>{'SSL' if r['use_ssl'] else 'API'} · usuario {e(r['username']) or '-'}</small></td>
          <td>{details}</td><td>{ppp}</td><td>{resources}</td>
          <td><span class='tag {state_class}'>{e(r['status'])}</span><br><small>{sync_text}</small>{err}</td>
          <td><div class='actions'>
            <a class='btn small' href='{url_for('router_view',id=r['id'])}'>Ver</a>
            <a class='btn small blue' href='{url_for('router_edit',id=r['id'])}'>Editar</a>
            <form method='post' action='{url_for('router_test',id=r['id'])}'><button class='btn small green'>Probar</button></form>
            <form method='post' action='{url_for('router_sync',id=r['id'])}'><button class='btn small orange'>Sincronizar</button></form>
          </div></td>
        </tr>"""

    quick = f'''
    <div class="panel"><h3>Agregar router</h3>
      <form class="grid" method="post" action="{url_for('router_new')}">
        <div class="field"><label>Nombre</label><input name="name" placeholder="Ej. CCR2116" required></div>
        <div class="field"><label>Host / IP / DDNS</label><input name="host" placeholder="Host o IP" required></div>
        <div class="field"><label>Usuario RouterOS</label><input name="username" required></div>
        <div class="field"><label>Contraseña</label><input type="password" name="password"></div>
        <div class="field"><label>Puerto API</label><input type="number" min="1" max="65535" name="port" value="8728"></div>
        <div class="field"><label>SSL</label><select name="use_ssl"><option value="0">No</option><option value="1">Sí</option></select></div>
        <input type="hidden" name="verify_ssl" value="0"><input type="hidden" name="notes" value="">
        <div class="full actions"><button class="btn green" name="action" value="save_test">Guardar y probar conexión</button><button class="btn" name="action" value="save">Solo guardar</button></div>
      </form>
    </div>'''

    cards = f'''<div class="cards">
      <div class="card"><div class="label">Routers</div><div class="num">{total}</div><div class="muted">registrados</div></div>
      <div class="card"><div class="label">En línea</div><div class="num">{online}</div><div class="muted">última prueba correcta</div></div>
      <div class="card"><div class="label">PPPoE activos</div><div class="num">{active}</div><div class="muted">sesiones detectadas</div></div>
      <div class="card"><div class="label">PPPoE registrados</div><div class="num">{secrets}</div><div class="muted">secrets detectados</div></div>
    </div>'''

    body = f'''<div class="head"><div><h1>Routers MikroTik</h1><p>Conexión, estado y sincronización de solo lectura.</p></div><a class="btn green" href="{url_for('router_new')}">+ Router</a></div>
    <div class="notice">Identity, modelo, RouterOS, arquitectura, uptime, CPU, PPPoE, perfiles e interfaces se detectan automáticamente. Probar y Sincronizar no modifican la configuración del MikroTik.</div>
    {cards}{quick}
    <div class="panel"><h3>Routers configurados</h3><table><tr><th>ID</th><th>Router / Identity</th><th>Conexión</th><th>Equipo</th><th>PPPoE</th><th>Recursos</th><th>Estado / última sincronización</th><th>Acciones</th></tr>{trs or '<tr><td colspan=8 class=empty>No hay routers configurados.</td></tr>'}</table></div>'''
    return shell('Routers', body, 'routers')


@app.get('/routers/<int:id>')
@login_required
def router_view(id):
    c = con(); r = c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone(); c.close()
    if not r:
        return ('Router no encontrado',404)
    state_class = 'ok' if r['status']=='ONLINE' else 'bad' if r['status']=='ERROR' else 'pending'
    error = f'<div class="notice err"><b>Último error:</b> {e(r["last_error"])}</div>' if r['last_error'] else ''
    body = f'''<div class="head"><div><h1>{e(r['name'])}</h1><p>{e(r['identity']) or 'Identity pendiente'} · {e(r['host'])}:{int(r['port'] or 8728)}</p></div><div class="actions"><a class="btn blue" href="{url_for('router_edit',id=id)}">Editar</a><form method="post" action="{url_for('router_test',id=id)}"><button class="btn green">Probar conexión</button></form><form method="post" action="{url_for('router_sync',id=id)}"><button class="btn orange">Sincronizar</button></form></div></div>
    {error}
    <div class="cards">
      <div class="card"><div class="label">Estado</div><div class="num"><span class="tag {state_class}">{e(r['status'])}</span></div><div class="muted">{e(r['last_seen']) or 'Sin prueba todavía'}</div></div>
      <div class="card"><div class="label">PPPoE activos</div><div class="num">{int(r['pppoe_active'] or 0)}</div><div class="muted">de {int(r['pppoe_total'] or 0)} registrados</div></div>
      <div class="card"><div class="label">CPU</div><div class="num">{int(r['cpu_load'] or 0)}%</div><div class="muted">{int(r['cpu_count'] or 0)} núcleos</div></div>
      <div class="card"><div class="label">Perfiles PPP</div><div class="num">{int(r['profiles_count'] or 0)}</div><div class="muted">{int(r['pppoe_disabled'] or 0)} secrets deshabilitados</div></div>
    </div>
    <div class="twocol">
      <div class="panel"><h3>Equipo</h3><table><tr><th>Dato</th><th>Valor</th></tr><tr><td>Identity</td><td>{e(r['identity']) or '-'}</td></tr><tr><td>Modelo</td><td>{e(r['model']) or '-'}</td></tr><tr><td>RouterOS</td><td>{e(r['ros_version']) or '-'}</td></tr><tr><td>Arquitectura</td><td>{e(r['architecture_name']) or '-'}</td></tr><tr><td>Uptime</td><td>{e(r['uptime']) or '-'}</td></tr><tr><td>Interfaces</td><td>{int(r['interfaces_count'] or 0)}</td></tr></table></div>
      <div class="panel"><h3>Conexión API</h3><table><tr><th>Dato</th><th>Valor</th></tr><tr><td>Host</td><td class="mono">{e(r['host'])}</td></tr><tr><td>Puerto</td><td>{int(r['port'] or 8728)}</td></tr><tr><td>Usuario</td><td>{e(r['username']) or '-'}</td></tr><tr><td>SSL</td><td>{'Sí' if r['use_ssl'] else 'No'}</td></tr><tr><td>Verificar certificado</td><td>{'Sí' if r['verify_ssl'] else 'No'}</td></tr><tr><td>Última sincronización</td><td>{e(r['last_sync']) or '-'}</td></tr></table></div>
    </div>
    <div class="panel"><h3>Memoria y notas</h3><p><b>Memoria libre:</b> {e(r['free_memory']) or '-'} &nbsp; <b>Total:</b> {e(r['total_memory']) or '-'}</p><p>{e(r['notes']) or 'Sin notas.'}</p><hr><form method="post" action="{url_for('router_delete',id=id)}" onsubmit="return confirm('¿Eliminar este router de INTER Flash? No se hará ningún cambio en el MikroTik.')"><button class="btn red">Eliminar router de la página</button></form></div>'''
    return shell(e(r['name']), body, 'routers')


@app.post('/routers/<int:id>/sync')
@login_required
def router_sync(id):
    c = con(); r = c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone(); c.close()
    if not r:
        return ('Router no encontrado',404)
    try:
        data = _read_router(r, full=True)
        _save_router_status(id, data)
        flash(f"Sincronización correcta: {data['pppoe_active']} PPPoE activos de {data['pppoe_total']} registrados.", 'success')
        audit('SINCRONIZAR_LECTURA','router',id,f"PPPoE {data['pppoe_active']}/{data['pppoe_total']}")
    except Exception as ex:
        _save_router_error(id, ex)
        flash('No se pudo sincronizar. Revisa host, puerto API, usuario, contraseña y acceso desde Internet.', 'error')
        audit('ERROR_SYNC','router',id,str(ex)[:180])
    return redirect(request.referrer or url_for('routers'))


@login_required
def router_test_new(id):
    c = con(); r = c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone(); c.close()
    if not r:
        return ('Router no encontrado',404)
    try:
        data = _read_router(r, full=False)
        _save_router_status(id, data)
        flash(f"Conexión correcta con {data.get('identity') or r['name']}. PPPoE activos: {data['pppoe_active']}.", 'success')
        audit('PROBAR_LECTURA','router',id,f"PPPoE activos {data['pppoe_active']}")
    except Exception as ex:
        _save_router_error(id, ex)
        flash('No se pudo conectar al router. Revisa IP/DDNS, puerto API, usuario, contraseña y acceso desde Railway.', 'error')
        audit('ERROR_CONEXION','router',id,str(ex)[:180])
    return redirect(request.referrer or url_for('routers'))


@login_required
def router_new_new():
    if request.method == 'POST':
        c = con()
        cur = c.execute('''INSERT INTO routers(name,host,port,username,password_enc,use_ssl,verify_ssl,status,created_at,notes)
                           VALUES(?,?,?,?,?,?,?,?,?,?)''',(
            request.form['name'].strip(), request.form['host'].strip(), int(request.form.get('port') or 8728),
            request.form.get('username','').strip(), enc(request.form.get('password','')),
            int(request.form.get('use_ssl') or 0), int(request.form.get('verify_ssl') or 0),
            'PENDIENTE', now(), request.form.get('notes','').strip()
        ))
        c.commit(); rid = cur.lastrowid; c.close()
        audit('CREAR','router',rid,request.form['name'])
        if request.form.get('action') == 'save_test':
            return router_test_new(rid)
        flash('Router guardado. Ahora puedes probar la conexión o sincronizar.', 'success')
        return redirect(url_for('routers'))
    return shell('Nuevo router',f'<div class="head"><div><h1>Nuevo router</h1><p>Los datos del equipo se detectan automáticamente al probar la conexión.</p></div></div><div class="panel">{router_form()}</div>','routers')


@login_required
def router_edit_new(id):
    c = con(); r = c.execute('SELECT * FROM routers WHERE id=?',(id,)).fetchone()
    if not r:
        c.close(); return ('Router no encontrado',404)
    if request.method == 'POST':
        pw = r['password_enc'] if not request.form.get('password') else enc(request.form.get('password'))
        c.execute('''UPDATE routers SET name=?,host=?,port=?,username=?,password_enc=?,use_ssl=?,verify_ssl=?,notes=? WHERE id=?''',(
            request.form['name'].strip(), request.form['host'].strip(), int(request.form.get('port') or 8728),
            request.form.get('username','').strip(), pw, int(request.form.get('use_ssl') or 0),
            int(request.form.get('verify_ssl') or 0), request.form.get('notes','').strip(), id
        ))
        c.commit(); c.close(); audit('EDITAR','router',id,request.form['name'])
        if request.form.get('action') == 'save_test':
            return router_test_new(id)
        flash('Router actualizado.', 'success')
        return redirect(url_for('router_view',id=id))
    c.close()
    return shell('Editar router',f'<div class="head"><div><h1>Editar router</h1><p>{e(r["name"])}</p></div></div><div class="panel">{router_form(r)}</div>','routers')


@app.post('/routers/<int:id>/delete')
@login_required
def router_delete(id):
    c = con(); r = c.execute('SELECT name FROM routers WHERE id=?',(id,)).fetchone()
    if not r:
        c.close(); return ('Router no encontrado',404)
    c.execute('DELETE FROM routers WHERE id=?',(id,)); c.commit(); c.close()
    audit('ELIMINAR','router',id,r['name'])
    flash('Router eliminado de INTER Flash. No se modificó el MikroTik.', 'success')
    return redirect(url_for('routers'))


# Reemplaza las vistas originales sin cambiar las URLs existentes.
app.view_functions['routers'] = routers_page
app.view_functions['router_test'] = router_test_new
app.view_functions['router_new'] = router_new_new
app.view_functions['router_edit'] = router_edit_new
