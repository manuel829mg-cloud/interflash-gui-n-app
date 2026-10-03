import unicodedata
from datetime import date
from flask import request, redirect, url_for
from app import con, auth, shell, e


def _norm(value):
    text = str(value or '').strip().lower()
    return ''.join(
        ch for ch in unicodedata.normalize('NFD', text)
        if unicodedata.category(ch) != 'Mn'
    )


def _ensure_columns():
    c = con()
    try:
        cols = {r['name'] for r in c.execute('PRAGMA table_info(clients)').fetchall()}
        wanted = {
            'surname': 'TEXT',
            'document': 'TEXT',
            'email': 'TEXT',
            'address': 'TEXT',
            'install_date': 'TEXT',
            'access_type': "TEXT DEFAULT 'FIBRA'",
            'onu': 'TEXT',
            'latitude': 'TEXT',
            'longitude': 'TEXT',
            'ipv6': 'TEXT',
            'wan': "TEXT DEFAULT 'AUTO'",
            'router_model': 'TEXT',
        }
        for name, ddl in wanted.items():
            if name not in cols:
                c.execute(f'ALTER TABLE clients ADD COLUMN {name} {ddl}')
        c.commit()
    finally:
        c.close()


def _get_sync_client(pppoe):
    c = con()
    try:
        local = c.execute('''
            SELECT c.*,p.name AS plan_name,p.speed AS plan_speed,p.price AS plan_price,
                   z.name AS zone_name
            FROM clients c
            LEFT JOIN plans p ON p.id=c.plan_id
            LEFT JOIN zones z ON z.id=c.zone_id
            WHERE LOWER(TRIM(c.pppoe))=LOWER(TRIM(?))
            LIMIT 1
        ''', (pppoe,)).fetchone()
        try:
            sync = c.execute('''
                SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                       a.address AS active_address,a.caller_id AS active_caller,a.uptime
                FROM router_pppoe_secrets s
                LEFT JOIN router_pppoe_active a
                  ON a.router_name=s.router_name AND a.name=s.name
                WHERE LOWER(TRIM(s.name))=LOWER(TRIM(?))
                LIMIT 1
            ''', (pppoe,)).fetchone()
        except Exception:
            sync = None
        plans = c.execute('SELECT * FROM plans ORDER BY price,name').fetchall()
        zones = c.execute('SELECT * FROM zones ORDER BY name').fetchall()
        return local, sync, plans, zones
    finally:
        c.close()


def _status_from(sync, local=None):
    if sync:
        disabled = str(sync['disabled'] or '').lower() in ('true', 'yes', '1')
        if disabled:
            return 'SUSPENDIDO', 'bad'
        if sync['active_address']:
            return 'ACTIVO', 'ok'
        return 'OFFLINE', 'pending'
    status = (local['status'] if local else 'ACTIVO') or 'ACTIVO'
    return status, 'ok' if status == 'ACTIVO' else 'bad'


def clients_video_list():
    if not auth():
        return redirect(url_for('login'))

    state = (request.args.get('state') or 'TODOS').upper()
    c = con()
    try:
        try:
            rows = c.execute('''
                SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                       a.address AS active_address,a.caller_id AS active_caller,a.uptime,
                       cl.id AS client_id,cl.name AS customer_name,cl.surname AS customer_surname,
                       cl.phone AS customer_phone,cl.install_date,cl.status AS local_status
                FROM router_pppoe_secrets s
                LEFT JOIN router_pppoe_active a
                  ON a.router_name=s.router_name AND a.name=s.name
                LEFT JOIN clients cl
                  ON LOWER(TRIM(cl.pppoe))=LOWER(TRIM(s.name))
                ORDER BY COALESCE(NULLIF(cl.name,''),s.name) COLLATE NOCASE
            ''').fetchall()
        except Exception:
            rows = []
    finally:
        c.close()

    total = online = suspended = 0
    rendered = []
    for r in rows:
        total += 1
        status, cls = _status_from(r)
        if status == 'ACTIVO':
            online += 1
        if status == 'SUSPENDIDO':
            suspended += 1
        if state != 'TODOS' and status != state:
            continue

        pppoe = r['name'] or ''
        full_name = ' '.join(x for x in [r['customer_name'] or '', r['customer_surname'] or ''] if x).strip() or pppoe
        ip = r['active_address'] or r['remote_address'] or '-'
        router = r['router_name'] or 'CCR2116'
        install_date = r['install_date'] or '—'
        phone = r['customer_phone'] or ''
        profile = r['profile'] or '-'
        caller = r['active_caller'] or r['caller_id'] or '-'
        search = _norm(' '.join([full_name, pppoe, phone, ip, router, status, profile, caller]))

        edit_url = url_for('client_video_edit', pppoe=pppoe)
        history_url = url_for('client_video_history', pppoe=pppoe)
        rendered.append(f'''
        <tr class="v-client-row" data-search="{e(search)}">
          <td><input type="checkbox" aria-label="Seleccionar"></td>
          <td><div class="v-name">● &nbsp;{e(full_name)}</div><div class="v-sub">{e(phone or pppoe)}</div></td>
          <td>{e(install_date)}</td>
          <td><a class="v-ip" href="{edit_url}">{e(ip)}</a><div class="v-sub">{e(router)}</div></td>
          <td><span class="tag {cls}">{e(status)}</span></td>
          <td><div class="v-actions">
            <a title="Editar cliente" href="{edit_url}">✎</a>
            <a title="Historial de pagos" href="{history_url}">▤</a>
            <a title="Ver PPPoE" href="{url_for('agent_pppoe_view', name=router)}">⌁</a>
            <span title="MAC / Caller ID">◉</span>
            <span title="Ubicación">⌖</span>
          </div><div class="v-sub">{e(profile)} · {e(caller)}</div></td>
        </tr>''')

    options = ''.join(
        f'<option value="{x}" {"selected" if state == x else ""}>{x.title()}</option>'
        for x in ('TODOS', 'ACTIVO', 'OFFLINE', 'SUSPENDIDO')
    )
    body = f'''
    <style>
      .video-toolbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:15px}}
      .video-toolbar input,.video-toolbar select{{height:40px;border:1px solid #dce3ea;border-radius:7px;padding:0 12px;background:#fff}}
      .video-toolbar input{{min-width:310px;flex:1}}
      .video-table th{{font-size:11px;letter-spacing:.03em;color:#6f7e8c}}
      .video-table td{{padding:12px 10px}}
      .v-name{{font-weight:800;color:#202b36}}.v-name:first-letter{{color:#20a464}}
      .v-sub{{font-size:11px;color:#8a98a6;margin-top:3px}}
      .v-ip{{color:#4779d8;font-weight:800}}
      .v-actions{{display:flex;gap:5px;align-items:center;flex-wrap:wrap}}
      .v-actions a,.v-actions span{{width:24px;height:24px;border:1px solid #d8dfe7;border-radius:5px;display:grid;place-items:center;background:#f7f9fb;color:#5b6875;font-size:12px}}
      .v-actions a:first-child{{background:#fff2f1;color:#c74b42;border-color:#f0d1cf}}
      .video-summary{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}
      .license-strip{{background:#fff4dc;border:1px solid #f2d18b;color:#9a6714;padding:9px 12px;border-radius:8px;font-size:12px;margin-bottom:12px}}
    </style>
    <div class="license-strip">INTER Flash · Lista de clientes sincronizada con MikroTik</div>
    <div class="head"><div><h1>Lista de clientes</h1><p>Vista de clientes como la mostrada en el video</p></div><a class="btn green" href="{url_for('client_new')}">+ Nuevo cliente</a></div>
    <div class="panel">
      <div class="video-toolbar">
        <input id="v-search" placeholder="Buscar nombre, IP, modelo..." autocomplete="off">
        <button class="btn" type="button">Columnas ▾</button>
        <select id="v-state">{options}</select>
        <button class="btn" type="button">Acción ▾</button>
      </div>
      <div class="video-summary"><span class="tag">Total: {total}</span><span class="tag ok">Activos: {online}</span><span class="tag bad">Suspendidos: {suspended}</span><span class="tag" id="v-results">Resultados: {len(rendered)}</span></div>
      <table class="video-table"><tr><th></th><th>Nombre</th><th>F. Inst.</th><th>IP / Antena</th><th>Estado</th><th>Acciones</th></tr>{''.join(rendered) if rendered else '<tr><td colspan="6" class="empty">No hay clientes sincronizados.</td></tr>'}<tr id="v-none" style="display:none"><td colspan="6" class="empty">No hay coincidencias.</td></tr></table>
    </div>
    <script>
      (function(){{
        const q=document.getElementById('v-search'), rows=[...document.querySelectorAll('.v-client-row')], results=document.getElementById('v-results'), none=document.getElementById('v-none'), state=document.getElementById('v-state');
        function n(v){{return (v||'').toString().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase().trim()}}
        function run(){{const w=n(q.value).split(/\\s+/).filter(Boolean);let shown=0;rows.forEach(r=>{{const ok=w.every(x=>n(r.dataset.search).includes(x));r.style.display=ok?'':'none';if(ok)shown++}});results.textContent='Resultados: '+shown;none.style.display=shown?'none':''}}
        q.addEventListener('input',run);q.addEventListener('keydown',ev=>{{if(ev.key==='Escape'){{q.value='';run()}}}});q.focus();
        state.addEventListener('change',()=>{{const u=new URL(location.href);u.searchParams.set('state',state.value);location.href=u.toString()}});
      }})();
    </script>
    '''
    return shell('Lista de clientes', body, 'clients')


def client_video_edit(pppoe):
    if not auth():
        return redirect(url_for('login'))
    local, sync, plans, zones = _get_sync_client(pppoe)
    if not sync and not local:
        return redirect(url_for('clients'))

    if request.method == 'POST':
        values = {
            'name': (request.form.get('name') or pppoe).strip(),
            'surname': (request.form.get('surname') or '').strip(),
            'document': (request.form.get('document') or '').strip(),
            'phone': (request.form.get('phone') or '').strip(),
            'email': (request.form.get('email') or '').strip(),
            'address': (request.form.get('address') or '').strip(),
            'status': request.form.get('status') or 'ACTIVO',
            'plan_id': request.form.get('plan_id') or None,
            'zone_id': request.form.get('zone_id') or None,
            'install_date': request.form.get('install_date') or None,
            'access_type': request.form.get('access_type') or 'FIBRA',
            'onu': (request.form.get('onu') or '').strip(),
            'latitude': (request.form.get('latitude') or '').strip(),
            'longitude': (request.form.get('longitude') or '').strip(),
            'ipv6': (request.form.get('ipv6') or '').strip(),
            'wan': (request.form.get('wan') or 'AUTO').strip(),
            'router_model': (request.form.get('router_model') or '').strip(),
        }
        c = con()
        try:
            row = c.execute('SELECT id FROM clients WHERE LOWER(TRIM(pppoe))=LOWER(TRIM(?)) LIMIT 1', (pppoe,)).fetchone()
            if row:
                c.execute('''UPDATE clients SET name=?,surname=?,document=?,phone=?,email=?,address=?,status=?,plan_id=?,zone_id=?,install_date=?,access_type=?,onu=?,latitude=?,longitude=?,ipv6=?,wan=?,router_model=? WHERE id=?''',
                          (values['name'], values['surname'], values['document'], values['phone'], values['email'], values['address'], values['status'], values['plan_id'], values['zone_id'], values['install_date'], values['access_type'], values['onu'], values['latitude'], values['longitude'], values['ipv6'], values['wan'], values['router_model'], row['id']))
            else:
                c.execute('''INSERT INTO clients(name,surname,document,phone,email,address,pppoe,status,plan_id,zone_id,install_date,access_type,onu,latitude,longitude,ipv6,wan,router_model) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (values['name'], values['surname'], values['document'], values['phone'], values['email'], values['address'], pppoe, values['status'], values['plan_id'], values['zone_id'], values['install_date'], values['access_type'], values['onu'], values['latitude'], values['longitude'], values['ipv6'], values['wan'], values['router_model']))
            c.commit()
        finally:
            c.close()
        return redirect(url_for('client_video_edit', pppoe=pppoe, saved='1'))

    status, _ = _status_from(sync, local)
    def lv(key, default=''):
        return (local[key] if local and key in local.keys() else default) or default

    name = lv('name', pppoe)
    surname = lv('surname')
    document = lv('document')
    phone = lv('phone')
    email = lv('email')
    address = lv('address')
    install_date = lv('install_date', date.today().isoformat())
    access_type = lv('access_type', 'FIBRA')
    onu = lv('onu')
    lat = lv('latitude')
    lon = lv('longitude')
    ipv6 = lv('ipv6')
    wan = lv('wan', 'AUTO')
    router_model = lv('router_model')
    current_plan = str(lv('plan_id'))
    current_zone = str(lv('zone_id'))
    plan_opts = ''.join(f'<option value="{p["id"]}" {"selected" if str(p["id"]) == current_plan else ""}>{e(p["name"])} · {e(p["speed"])} · RD${p["price"]:,.0f}</option>' for p in plans)
    zone_opts = ''.join(f'<option value="{z["id"]}" {"selected" if str(z["id"]) == current_zone else ""}>{e(z["name"])}</option>' for z in zones)
    ip = (sync['active_address'] or sync['remote_address']) if sync else '-'
    router = sync['router_name'] if sync else 'CCR2116'
    profile = sync['profile'] if sync else '-'
    caller = (sync['active_caller'] or sync['caller_id']) if sync else '-'
    saved = '<div class="notice">Cambios guardados correctamente.</div>' if request.args.get('saved') else ''
    wa_link = 'https://wa.me/' + ''.join(ch for ch in phone if ch.isdigit()) if phone else '#'

    body = f'''
    <style>
      .v-topbuttons{{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0 16px}}.v-topbuttons a{{padding:8px 11px;border:1px solid #dbe2e9;border-radius:7px;background:#fff;font-size:12px;font-weight:800}}.v-topbuttons .greenish{{background:#eaf8ef;color:#21834e;border-color:#bfe5cc}}
      .v-edit-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.v-card{{background:#fff;border:1px solid #e7ebf0;border-radius:11px;padding:16px}}.v-card h3{{margin:0 0 14px;font-size:17px}}.v-card .grid{{gap:10px}}
      .v-radio{{display:flex;gap:18px;padding:10px 0}}.v-inline-btns{{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}}.v-inline-btns button{{border:1px solid #dce3ea;background:#f8fafb;border-radius:6px;padding:7px 9px;font-size:11px}}.mapbox{{height:230px;border-radius:9px;background:linear-gradient(145deg,#d8e1d3,#b6c8ac);border:1px solid #cbd7c8;display:grid;place-items:center;color:#40584a;text-align:center;margin:10px 0;font-weight:700}}.map-pin{{width:28px;height:28px;border-radius:50% 50% 50% 0;background:#2d8ae8;transform:rotate(-45deg);margin:0 auto 8px}}.map-pin:after{{content:'';width:10px;height:10px;background:white;border-radius:50%;position:absolute;margin:9px 0 0 -5px}}
      .v-readonly{{background:#f7f9fb;border:1px solid #e2e7ec;border-radius:8px;padding:10px 12px;font-size:12px;color:#596675;margin-bottom:10px}}@media(max-width:1000px){{.v-edit-grid{{grid-template-columns:1fr}}}}
    </style>
    <div class="head"><div><a href="{url_for('clients')}" class="muted">← Volver al cliente</a><h1 style="margin-top:6px">Editar Cliente</h1><p>Actualiza la información de {e(name)}</p></div></div>
    <div class="v-topbuttons"><a href="{url_for('invoices')}">▧ Facturación individual</a><a class="greenish" href="{url_for('client_video_history', pppoe=pppoe)}">▤ Ver Historial de Pagos</a><a href="#">✉ SMS</a><a href="{e(wa_link)}" target="_blank">◯ WhatsApp al cliente</a></div>
    {saved}
    <div class="v-readonly"><b>MikroTik:</b> {e(router)} &nbsp; · &nbsp; <b>PPPoE:</b> {e(pppoe)} &nbsp; · &nbsp; <b>IP:</b> {e(ip)} &nbsp; · &nbsp; <b>Perfil:</b> {e(profile)} &nbsp; · &nbsp; <b>MAC/Caller:</b> {e(caller)}</div>
    <form method="post"><div class="v-edit-grid">
      <div class="v-card"><h3>👤 Datos Personales</h3><div class="grid">
        <div class="field"><label>Nombre</label><input name="name" value="{e(name)}" required></div><div class="field"><label>Apellido</label><input name="surname" value="{e(surname)}"></div>
        <div class="field"><label>Cédula / CI / DNI</label><input name="document" value="{e(document)}"></div><div class="field"><label>Teléfono</label><input name="phone" value="{e(phone)}"></div>
        <div class="field"><label>Email (opcional)</label><input type="email" name="email" value="{e(email)}"></div><div class="field"><label>Fecha instalación</label><input type="date" name="install_date" value="{e(install_date)}"></div>
        <div class="field"><label>Estado del servicio</label><select name="status"><option value="ACTIVO" {"selected" if status == "ACTIVO" else ""}>Activo</option><option value="SUSPENDIDO" {"selected" if status == "SUSPENDIDO" else ""}>Suspendido</option></select></div><div class="field"><label>Dirección</label><input name="address" value="{e(address)}"></div>
      </div></div>
      <div class="v-card"><h3>📶 Servicio y Red</h3><label class="label">Tipo de acceso del cliente</label><div class="v-radio"><label><input type="radio" name="access_type" value="FIBRA" {"checked" if access_type != "ANTENA" else ""}> Fibra (OLT / ONU)</label><label><input type="radio" name="access_type" value="ANTENA" {"checked" if access_type == "ANTENA" else ""}> Antena</label></div>
        <div class="field"><label>ONU</label><input name="onu" value="{e(onu)}" placeholder="Sin vincular ONU por ahora"></div><div class="v-inline-btns"><button type="button" title="Visual, aún no escribe en el MikroTik">♙ Autorizar ONU</button><button type="button" title="Visual, aún no escribe en el MikroTik">↻ Sincronizar IP/MAC</button><button type="button" title="Visual, aún no escribe en el MikroTik">⌁ Traer MAC ARP</button></div>
        <div class="field" style="margin-top:12px"><label>Plan de Internet</label><select name="plan_id"><option value="">Sin plan</option>{plan_opts}</select></div><div class="field"><label>Zona / Nodo</label><select name="zone_id"><option value="">Sin zona</option>{zone_opts}</select></div>
      </div>
      <div class="v-card"><h3>⌖ Ubicación</h3><div class="mapbox"><div><div class="map-pin"></div>Mapa del cliente<br><small>{e(lat or 'Latitud pendiente')} · {e(lon or 'Longitud pendiente')}</small></div></div><div class="grid"><div class="field"><label>Latitud</label><input name="latitude" value="{e(lat)}"></div><div class="field"><label>Longitud</label><input name="longitude" value="{e(lon)}"></div></div></div>
      <div class="v-card"><h3>🌐 Información de red</h3><div class="field"><label>IPv6 (opcional)</label><input name="ipv6" value="{e(ipv6)}"></div><div class="field"><label>WAN preferida (opcional)</label><input name="wan" value="{e(wan)}"></div><div class="field"><label>Modelo de Router (opcional)</label><input name="router_model" value="{e(router_model)}"></div><div style="margin-top:22px"><button class="btn green">Guardar cambios</button></div></div>
    </div></form>
    '''
    return shell('Editar cliente', body, 'clients')


def client_video_history(pppoe):
    if not auth():
        return redirect(url_for('login'))
    c = con()
    try:
        client = c.execute('SELECT * FROM clients WHERE LOWER(TRIM(pppoe))=LOWER(TRIM(?)) LIMIT 1', (pppoe,)).fetchone()
        rows = c.execute('SELECT * FROM invoices WHERE client_id=? ORDER BY id DESC', (client['id'],)).fetchall() if client else []
    finally:
        c.close()
    name = (client['name'] if client else pppoe) or pppoe
    filt = (request.args.get('f') or 'TODAS').upper()
    visible = []
    for r in rows:
        st = (r['status'] or 'PENDIENTE').upper()
        if filt == 'PENDIENTES' and st != 'PENDIENTE':
            continue
        if filt == 'PAGADAS' and st != 'PAGADA':
            continue
        if filt == 'ANULADAS' and st != 'ANULADA':
            continue
        visible.append(r)
    pending_total = sum(float(r['amount'] or 0) for r in rows if (r['status'] or '').upper() == 'PENDIENTE')
    trs = ''.join(f'''<tr><td>#{r['id']}</td><td>{e(r['issue_date'])}</td><td>{e(r['due_date'])}</td><td>{e(r['paid_at'] or '—')}</td><td>RD${float(r['amount'] or 0):,.2f}</td><td><span class="tag {'ok' if (r['status'] or '').upper() == 'PAGADA' else 'pending'}">{e(r['status'])}</span></td></tr>''' for r in visible)
    tabs = ''.join(f'<a class="btn small {"blue" if filt == key else ""}" href="?f={key}">{label}</a>' for key, label in [('TODAS','Todas'),('PENDIENTES','Pendientes'),('PAGADAS','Pagadas'),('ANULADAS','Anuladas')])
    body = f'''
      <div class="head"><div><a class="muted" href="{url_for('client_video_edit', pppoe=pppoe)}">← Volver al cliente</a><h1 style="margin-top:6px">Historial de Pagos</h1><p>{e(name)}</p></div><div style="text-align:right"><div class="muted">Total pendiente</div><div style="font-size:24px;font-weight:900;color:#15935b">RD${pending_total:,.2f}</div></div></div>
      <div style="display:flex;gap:7px;margin:12px 0">{tabs}</div>
      <div class="panel"><h3 style="margin-top:0">▤ Facturas</h3><table><tr><th>Factura</th><th>Emisión</th><th>Vencimiento</th><th>Fecha pago</th><th>Monto</th><th>Estado</th></tr>{trs or '<tr><td colspan="6" class="empty">No hay facturas para este filtro.</td></tr>'}</table></div>
    '''
    return shell('Historial de Pagos', body, 'clients')


def setup(app):
    _ensure_columns()
    app.view_functions['clients'] = clients_video_list
    if 'client_video_edit' not in app.view_functions:
        app.add_url_rule('/clients/pppoe/<path:pppoe>/edit', endpoint='client_video_edit', view_func=client_video_edit, methods=['GET', 'POST'])
    if 'client_video_history' not in app.view_functions:
        app.add_url_rule('/clients/pppoe/<path:pppoe>/history', endpoint='client_video_history', view_func=client_video_history, methods=['GET'])
