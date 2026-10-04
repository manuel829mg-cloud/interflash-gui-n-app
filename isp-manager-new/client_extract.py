import csv
import io
import unicodedata
from datetime import date, datetime
from html import escape
from flask import request, redirect, url_for, flash, Response
import app as base


def esc(v):
    return escape('' if v is None else str(v))


def _cols(c, table):
    return {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_col(c, table, name, ddl):
    if name not in _cols(c, table):
        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


def ensure_schema():
    c = base.db()
    for name, ddl in [
        ('mikrotik_profile', 'TEXT'),
        ('source', 'TEXT'),
        ('last_imported_at', 'TEXT'),
        ('notes', 'TEXT'),
        ('router_name', 'TEXT DEFAULT "CCR2116"'),
        ('service_status', 'TEXT DEFAULT "ACTIVO"'),
    ]:
        _add_col(c, 'customers', name, ddl)
    c.commit()
    c.close()


def _norm(s):
    s = '' if s is None else str(s).strip().lower()
    s = ''.join(ch for ch in unicodedata.normalize('NFD', s) if unicodedata.category(ch) != 'Mn')
    return s.replace(' ', '_').replace('-', '_')


def _pick(row, *names):
    normalized = {_norm(k): (v or '').strip() for k, v in row.items() if k is not None}
    for name in names:
        v = normalized.get(_norm(name), '')
        if v:
            return v
    return ''


def _status(v, default='ACTIVO'):
    x = _norm(v)
    if x in ('suspendido', 'suspended', 'disabled', 'deshabilitado', 'inactivo', 'cortado'):
        return 'SUSPENDIDO'
    if x in ('activo', 'active', 'enabled', 'habilitado', 'online'):
        return 'ACTIVO'
    return default


def _truthy_disabled(v):
    return _norm(v) in ('true', 'yes', 'si', '1', 'disabled', 'deshabilitado')


def _code_after_insert(c, customer_id):
    c.execute('UPDATE customers SET code=? WHERE id=? AND (code IS NULL OR code="")', (f'IF-{customer_id:05d}', customer_id))


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _router_options(agents, selected=''):
    return ''.join(
        f'<option value="{esc(a["name"])}" {"selected" if a["name"] == selected else ""}>{esc(a["identity"] or a["name"])} · {int(a["pppoe_total"] or 0)} PPPoE</option>'
        for a in agents
    )


def extract_page():
    if not base.logged_in():
        return redirect(url_for('login'))
    ensure_schema()
    c = base.db()
    agents = c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall() if _table_exists(c, 'push_router_agents') else []
    total_sync = c.execute('SELECT COUNT(*) c FROM push_pppoe_secrets').fetchone()['c'] if _table_exists(c, 'push_pppoe_secrets') else 0
    local_total = c.execute('SELECT COUNT(*) c FROM customers').fetchone()['c']
    c.close()

    body = f'''
    <div class="head"><div><h1>Extraer Clientes</h1><p>Trae clientes desde MikroTik o desde un archivo CSV.</p></div><a class="btn" href="{url_for('customers')}">← Clientes</a></div>
    <div class="grid6" style="grid-template-columns:repeat(3,minmax(180px,1fr));margin-bottom:14px">
      <div class="kpi blue1"><div class="label">PPPoE sincronizados</div><div class="value">{total_sync}</div><div class="sub">Disponibles desde MikroTik</div></div>
      <div class="kpi green1"><div class="label">Clientes en plataforma</div><div class="value">{local_total}</div><div class="sub">Registros actuales</div></div>
      <div class="kpi purple1"><div class="label">Routers detectados</div><div class="value">{len(agents)}</div><div class="sub">Sincronización segura</div></div>
    </div>
    <div class="panel" style="padding:24px">
      <div style="display:flex;gap:18px;flex-wrap:wrap">
        <a class="btn" style="font-size:18px;padding:18px 28px;background:#f6f7f9;color:#172033;border-color:#d9dde4" href="{url_for('client_extract_pppoe')}">⇩&nbsp;&nbsp; Extraer Clientes PPPoE</a>
        <a class="btn" style="font-size:18px;padding:18px 28px;background:#f6f7f9;color:#172033;border-color:#d9dde4" href="#csv-box">⇩&nbsp;&nbsp; Extraer Clientes por CSV</a>
      </div>
      <div id="csv-box" style="margin-top:26px;border-top:1px solid #25394e;padding-top:20px">
        <h3>Extraer por CSV</h3>
        <form method="post" action="{url_for('client_extract_csv')}" enctype="multipart/form-data" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
          <input class="field" type="file" name="file" accept=".csv,text/csv" required>
          <button class="btn blue">Procesar CSV</button>
          <a class="btn" href="{url_for('client_extract_csv_template')}">Descargar plantilla</a>
        </form>
      </div>
    </div>
    '''
    return base.shell('Extraer Clientes', body, 'client_extract')


def _pppoe_picker(router='', load=False):
    c = base.db()
    agents = c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall() if _table_exists(c, 'push_router_agents') else []
    if not router and agents:
        router = agents[0]['name']

    secrets = []
    active_map = {}
    existing = set()
    if load and router and _table_exists(c, 'push_pppoe_secrets'):
        secrets = c.execute('SELECT * FROM push_pppoe_secrets WHERE router_name=? ORDER BY name', (router,)).fetchall()
        if _table_exists(c, 'push_pppoe_active'):
            active_map = {r['name']: r for r in c.execute('SELECT * FROM push_pppoe_active WHERE router_name=?', (router,)).fetchall()}
        existing = {str(r['pppoe']).lower() for r in c.execute("SELECT pppoe FROM customers WHERE COALESCE(pppoe,'')<>''").fetchall()}
    c.close()

    opts = _router_options(agents, router)
    rows = []
    available = 0
    for r in secrets:
        name = (r['name'] or '').strip()
        if not name:
            continue
        active = active_map.get(name)
        ip = (active['address'] if active else r['remote_address']) or '-'
        profile = r['profile'] or '-'
        disabled = _truthy_disabled(r['disabled'])
        is_existing = name.lower() in existing
        if not is_existing:
            available += 1
        state = 'YA IMPORTADO' if is_existing else ('SUSPENDIDO' if disabled else ('ONLINE' if active else 'OFFLINE'))
        cls = 'ok' if state == 'ONLINE' else ('bad' if state == 'SUSPENDIDO' else 'warn')
        checkbox = '<span class="muted">—</span>' if is_existing else f'<input class="pppcheck" type="checkbox" name="pppoe" value="{esc(name)}" onchange="updateCount()">'
        search_blob = esc(f'{name} {profile} {ip} {r["comment"] or ""}').lower()
        rows.append(f'''<tr class="ppprow" data-search="{search_blob}">
          <td style="width:42px;text-align:center">{checkbox}</td>
          <td><b>{esc(name)}</b><br><span class="muted">{esc(r['comment'] or '')}</span></td>
          <td>{esc(profile)}</td><td>{esc(ip)}</td>
          <td><span class="tag {cls}">{state}</span></td>
        </tr>''')

    list_html = ''.join(rows) if rows else '<tr><td colspan="5" class="muted" style="padding:26px;text-align:center">Selecciona el router y pulsa <b>Buscar cuentas</b>.</td></tr>'
    disabled = 'disabled' if not agents else ''
    modal = f'''
    <style>
      .extract-overlay{{min-height:calc(100vh - 130px);display:grid;place-items:start center;padding:28px 10px}}
      .extract-modal{{width:min(940px,96vw);background:#eef1f5;color:#172033;border:1px solid #cbd2db;border-radius:24px;padding:28px;box-shadow:0 30px 90px #0008}}
      .extract-modal .field{{background:white;color:#172033;border-color:#b9c1cc}}
      .extract-modal .muted{{color:#667085}}
      .extract-modal table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}}
      .extract-modal th,.extract-modal td{{padding:11px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:13px}}
      .extract-modal th{{font-size:11px;color:#667085;text-transform:uppercase;background:#f8fafc}}
      .extract-actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}}
      .extract-search{{display:grid;grid-template-columns:180px 1fr;gap:10px;margin:14px 0}}
      @media(max-width:700px){{.extract-search{{grid-template-columns:1fr}}.extract-modal{{padding:18px}}}}
    </style>
    <div class="extract-overlay"><div class="extract-modal">
      <div style="display:flex;justify-content:space-between;gap:16px;align-items:start">
        <div><h2 style="margin:0 0 7px;font-size:28px">Extraer Clientes PPPoE del router</h2><p class="muted" style="margin:0">Lee las cuentas PPP reales del router que todavía no están vinculadas a ningún cliente del catálogo.</p></div>
        <a href="{url_for('client_extract')}" style="font-size:28px;color:#667085">×</a>
      </div>
      <form method="get" action="{url_for('client_extract_pppoe')}" class="extract-search">
        <select class="field" name="router" {disabled}>{opts or '<option>Sin router sincronizado</option>'}</select>
        <div style="display:flex;gap:10px;min-width:0">
          <button class="btn" name="load" value="1" style="background:white;color:#172033;border-color:#c5ccd5;min-width:150px" {disabled}>Buscar cuentas</button>
          <input id="pppSearch" class="field" placeholder="Buscar cliente, teléfono o IP..." oninput="filterRows()" style="min-width:0;flex:1">
        </div>
      </form>
      <form method="post" action="{url_for('client_extract_pppoe')}" onsubmit="return confirmImport()">
        <input type="hidden" name="router" value="{esc(router)}">
        <div style="max-height:430px;overflow:auto;border:1px solid #d7dce3;border-radius:12px">
          <table><thead><tr><th><input id="selectAll" type="checkbox" onchange="toggleAll(this)"></th><th>Usuario PPPoE</th><th>Perfil</th><th>IP</th><th>Estado</th></tr></thead><tbody>{list_html}</tbody></table>
        </div>
        <div class="extract-actions">
          <button type="button" class="btn" onclick="toggleAll({{checked:true}});document.getElementById('selectAll').checked=true">Todos disponibles</button>
          <span class="muted">{len(secrets)} cuentas encontradas · {available} disponibles para importar</span>
          <span style="flex:1"></span>
          <a class="btn" href="{url_for('client_extract')}">Cancelar</a>
          <button id="importBtn" class="btn green" type="submit">Importar seleccionados (0)</button>
        </div>
      </form>
    </div></div>
    <script>
      function visibleChecks(){{return [...document.querySelectorAll('.ppprow')].filter(r=>r.style.display!=='none').map(r=>r.querySelector('.pppcheck')).filter(Boolean)}}
      function updateCount(){{const n=document.querySelectorAll('.pppcheck:checked').length;document.getElementById('importBtn').textContent='Importar seleccionados ('+n+')'}}
      function toggleAll(src){{visibleChecks().forEach(c=>c.checked=!!src.checked);updateCount()}}
      function filterRows(){{const q=(document.getElementById('pppSearch').value||'').toLowerCase().trim();document.querySelectorAll('.ppprow').forEach(r=>{{r.style.display=!q||r.dataset.search.includes(q)?'':'none'}});}}
      function confirmImport(){{const n=document.querySelectorAll('.pppcheck:checked').length;if(!n){{alert('Selecciona por lo menos una cuenta PPPoE.');return false}}return confirm('¿Importar '+n+' cliente(s) seleccionado(s) a la plataforma?')}}
      updateCount();
    </script>
    '''
    return base.shell('Extraer PPPoE', modal, 'client_extract')


def extract_pppoe():
    if not base.logged_in():
        return redirect(url_for('login'))
    ensure_schema()

    if request.method == 'GET':
        router = (request.args.get('router') or '').strip()
        load = request.args.get('load') == '1'
        return _pppoe_picker(router, load)

    router = (request.form.get('router') or '').strip()
    selected = [x.strip() for x in request.form.getlist('pppoe') if x.strip()]
    if not selected:
        flash('Selecciona por lo menos una cuenta PPPoE para importar.')
        return redirect(url_for('client_extract_pppoe', router=router, load=1))

    c = base.db()
    if not _table_exists(c, 'push_pppoe_secrets'):
        c.close(); flash('Todavía no hay datos PPPoE sincronizados.'); return redirect(url_for('client_extract'))
    if not router:
        a = c.execute('SELECT name FROM push_router_agents ORDER BY id DESC LIMIT 1').fetchone() if _table_exists(c, 'push_router_agents') else None
        router = a['name'] if a else 'CCR2116'

    active_map = {r['name']: r for r in c.execute('SELECT * FROM push_pppoe_active WHERE router_name=?', (router,)).fetchall()} if _table_exists(c, 'push_pppoe_active') else {}
    created = skipped = 0
    now = datetime.now().isoformat(timespec='seconds')

    for pppoe in selected:
        existing = c.execute('SELECT id FROM customers WHERE lower(pppoe)=lower(?) LIMIT 1', (pppoe,)).fetchone()
        if existing:
            skipped += 1
            continue
        r = c.execute('SELECT * FROM push_pppoe_secrets WHERE router_name=? AND name=? LIMIT 1', (router, pppoe)).fetchone()
        if not r:
            skipped += 1
            continue
        active = active_map.get(pppoe)
        ip = (active['address'] if active else r['remote_address']) or ''
        status = 'SUSPENDIDO' if _truthy_disabled(r['disabled']) else 'ACTIVO'
        profile = (r['profile'] or '').strip()
        comment = (r['comment'] or '').strip()
        name = comment if comment else pppoe
        cur = c.execute('''INSERT INTO customers(code,name,pppoe,ip_address,status,due_day,created_at,notes,router_name,service_status,mikrotik_profile,source,last_imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (None, name, pppoe, ip, status, 30, date.today().isoformat(), comment, router, status, profile, 'MIKROTIK', now))
        _code_after_insert(c, cur.lastrowid)
        created += 1

    c.commit(); c.close()
    try:
        base.audit('CUSTOMERS_EXTRACT_PPPoE', f'{router}: creados {created}, omitidos {skipped}')
    except Exception:
        pass
    flash(f'Importación PPPoE completada: {created} clientes creados y {skipped} omitidos.')
    return redirect(url_for('customers'))


def _plan_id(c, name):
    if not name:
        return None
    r = c.execute('SELECT id FROM plans WHERE lower(name)=lower(?) LIMIT 1', (name,)).fetchone()
    return r['id'] if r else None


def _zone_id(c, name):
    if not name or not _table_exists(c, 'zones'):
        return None
    r = c.execute('SELECT id FROM zones WHERE lower(name)=lower(?) LIMIT 1', (name,)).fetchone()
    return r['id'] if r else None


def extract_csv():
    if not base.logged_in():
        return redirect(url_for('login'))
    ensure_schema()
    f = request.files.get('file')
    if not f or not f.filename:
        flash('Selecciona un archivo CSV.'); return redirect(url_for('client_extract'))
    raw = f.read()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        flash('El CSV no tiene encabezados.'); return redirect(url_for('client_extract'))
    c = base.db(); created = updated = skipped = 0; now = datetime.now().isoformat(timespec='seconds')
    cols = _cols(c, 'customers')
    has_zone_id = 'zone_id' in cols
    for row in reader:
        pppoe = _pick(row, 'pppoe', 'usuario', 'username', 'user', 'usuario_pppoe')
        name = _pick(row, 'nombre', 'name', 'cliente', 'customer')
        if not pppoe and not name:
            skipped += 1; continue
        phone = _pick(row, 'telefono', 'teléfono', 'phone', 'whatsapp')
        document = _pick(row, 'cedula', 'cédula', 'documento', 'document')
        email = _pick(row, 'email', 'correo')
        address = _pick(row, 'direccion', 'dirección', 'address')
        zone = _pick(row, 'zona', 'zone')
        ip = _pick(row, 'ip', 'ip_address', 'direccion_ip')
        onu = _pick(row, 'onu', 'onu_serial', 'serial_onu')
        profile = _pick(row, 'perfil', 'profile', 'mikrotik_profile')
        plan = _pick(row, 'plan', 'paquete')
        status = _status(_pick(row, 'estado', 'status'), 'ACTIVO')
        due_raw = _pick(row, 'dia_vencimiento', 'día_vencimiento', 'due_day', 'vencimiento')
        try:
            due_day = max(1, min(int(due_raw or 30), 31))
        except Exception:
            due_day = 30
        existing = c.execute('SELECT * FROM customers WHERE lower(pppoe)=lower(?) LIMIT 1', (pppoe,)).fetchone() if pppoe else None
        if not existing and document:
            existing = c.execute('SELECT * FROM customers WHERE document=? LIMIT 1', (document,)).fetchone()
        plan_id = _plan_id(c, plan)
        zone_id = _zone_id(c, zone) if has_zone_id else None
        if existing:
            if has_zone_id:
                c.execute('''UPDATE customers SET name=COALESCE(NULLIF(?,''),name),phone=COALESCE(NULLIF(?,''),phone),document=COALESCE(NULLIF(?,''),document),email=COALESCE(NULLIF(?,''),email),address=COALESCE(NULLIF(?,''),address),zone=COALESCE(NULLIF(?,''),zone),zone_id=COALESCE(?,zone_id),pppoe=COALESCE(NULLIF(?,''),pppoe),ip_address=COALESCE(NULLIF(?,''),ip_address),onu_serial=COALESCE(NULLIF(?,''),onu_serial),plan_id=COALESCE(?,plan_id),status=?,service_status=?,due_day=?,mikrotik_profile=COALESCE(NULLIF(?,''),mikrotik_profile),source='CSV',last_imported_at=? WHERE id=?''',
                          (name, phone, document, email, address, zone, zone_id, pppoe, ip, onu, plan_id, status, status, due_day, profile, now, existing['id']))
            else:
                c.execute('''UPDATE customers SET name=COALESCE(NULLIF(?,''),name),phone=COALESCE(NULLIF(?,''),phone),document=COALESCE(NULLIF(?,''),document),email=COALESCE(NULLIF(?,''),email),address=COALESCE(NULLIF(?,''),address),zone=COALESCE(NULLIF(?,''),zone),pppoe=COALESCE(NULLIF(?,''),pppoe),ip_address=COALESCE(NULLIF(?,''),ip_address),onu_serial=COALESCE(NULLIF(?,''),onu_serial),plan_id=COALESCE(?,plan_id),status=?,service_status=?,due_day=?,mikrotik_profile=COALESCE(NULLIF(?,''),mikrotik_profile),source='CSV',last_imported_at=? WHERE id=?''',
                          (name, phone, document, email, address, zone, pppoe, ip, onu, plan_id, status, status, due_day, profile, now, existing['id']))
            updated += 1
        else:
            if has_zone_id:
                cur = c.execute('''INSERT INTO customers(code,name,phone,document,email,address,zone,zone_id,pppoe,ip_address,onu_serial,plan_id,status,due_day,created_at,service_status,mikrotik_profile,source,last_imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (None, name or pppoe, phone, document, email, address, zone, zone_id, pppoe, ip, onu, plan_id, status, due_day, date.today().isoformat(), status, profile, 'CSV', now))
            else:
                cur = c.execute('''INSERT INTO customers(code,name,phone,document,email,address,zone,pppoe,ip_address,onu_serial,plan_id,status,due_day,created_at,service_status,mikrotik_profile,source,last_imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (None, name or pppoe, phone, document, email, address, zone, pppoe, ip, onu, plan_id, status, due_day, date.today().isoformat(), status, profile, 'CSV', now))
            _code_after_insert(c, cur.lastrowid); created += 1
    c.commit(); c.close()
    try:
        base.audit('CUSTOMERS_EXTRACT_CSV', f'creados {created}, actualizados {updated}, omitidos {skipped}')
    except Exception:
        pass
    flash(f'CSV procesado: {created} creados, {updated} actualizados y {skipped} omitidos.')
    return redirect(url_for('customers'))


def csv_template():
    header = 'nombre,telefono,cedula,email,direccion,zona,pppoe,ip,onu_serial,plan,perfil,estado,dia_vencimiento\n'
    example = 'Ejemplo Cliente,8095550000,00100000000,cliente@correo.com,Calle Principal,El Manguito,cliente001,10.0.0.10,HWTC12345678,Básico 40,1-30M-hioso,ACTIVO,30\n'
    return Response(header + example, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=plantilla_clientes_interflash.csv'})


def setup(app):
    ensure_schema()
    app.add_url_rule('/clients/extract', endpoint='client_extract', view_func=extract_page, methods=['GET'])
    app.add_url_rule('/clients/extract/pppoe', endpoint='client_extract_pppoe', view_func=extract_pppoe, methods=['GET', 'POST'])
    app.add_url_rule('/clients/extract/csv', endpoint='client_extract_csv', view_func=extract_csv, methods=['POST'])
    app.add_url_rule('/clients/extract/csv-template', endpoint='client_extract_csv_template', view_func=csv_template, methods=['GET'])
    if not any(ep == 'client_extract' for ep, _, _ in base.NAV):
        pos = next((i + 1 for i, item in enumerate(base.NAV) if item[0] == 'customers'), 2)
        base.NAV.insert(pos, ('client_extract', '⇩', 'Extraer clientes'))
