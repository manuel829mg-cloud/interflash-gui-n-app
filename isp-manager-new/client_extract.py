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


def extract_page():
    if not base.logged_in():
        return redirect(url_for('login'))
    ensure_schema()
    c = base.db()
    agents = c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall() if _table_exists(c, 'push_router_agents') else []
    total_sync = c.execute('SELECT COUNT(*) c FROM push_pppoe_secrets').fetchone()['c'] if _table_exists(c, 'push_pppoe_secrets') else 0
    local_total = c.execute('SELECT COUNT(*) c FROM customers').fetchone()['c']
    opts = ''.join(f'<option value="{esc(a["name"])}">{esc(a["identity"] or a["name"])} · {int(a["pppoe_total"] or 0)} PPPoE</option>' for a in agents)
    c.close()

    body = f'''
    <div class="head"><div><h1>Extraer Clientes</h1><p>Importa clientes desde la sincronización segura del MikroTik o desde un archivo CSV.</p></div><a class="btn" href="{url_for('customers')}">← Clientes</a></div>
    <div class="grid6" style="grid-template-columns:repeat(3,minmax(180px,1fr));margin-bottom:14px">
      <div class="kpi blue1"><div class="label">PPPoE sincronizados</div><div class="value">{total_sync}</div><div class="sub">Disponibles para importar</div></div>
      <div class="kpi green1"><div class="label">Clientes en plataforma</div><div class="value">{local_total}</div><div class="sub">Registros actuales</div></div>
      <div class="kpi purple1"><div class="label">Routers detectados</div><div class="value">{len(agents)}</div><div class="sub">Sincronización segura</div></div>
    </div>
    <div class="panel">
      <div style="padding:12px;border-radius:9px;background:#063f2a;color:#b9f7d6;margin-bottom:18px"><b>Seguro:</b> esta función solamente copia datos del MikroTik hacia la plataforma. No cambia, suspende ni elimina nada en el router.</div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(260px,1fr));gap:18px">
        <div style="border:1px solid #29425b;border-radius:14px;padding:22px;background:#101f30">
          <div style="font-size:34px;margin-bottom:8px">⇩</div><h2 style="margin:0 0 8px">Extraer Clientes PPPoE</h2>
          <p class="muted">Toma los usuarios PPPoE ya sincronizados desde tu CCR2116 y los crea o actualiza en Clientes.</p>
          <form method="post" action="{url_for('client_extract_pppoe')}">
            <select class="field" name="router" style="width:100%;margin:10px 0" {'disabled' if not agents else ''}>{opts or '<option>Sin router sincronizado</option>'}</select>
            <button class="btn green" style="width:100%;padding:13px" {'disabled' if not agents else ''}>⇩ Extraer Clientes PPPoE</button>
          </form>
        </div>
        <div style="border:1px solid #29425b;border-radius:14px;padding:22px;background:#101f30">
          <div style="font-size:34px;margin-bottom:8px">⇩</div><h2 style="margin:0 0 8px">Extraer Clientes por CSV</h2>
          <p class="muted">Sube un CSV con clientes. Reconoce columnas como nombre, teléfono, cédula, PPPoE, IP, ONU, plan, zona y estado.</p>
          <form method="post" action="{url_for('client_extract_csv') }" enctype="multipart/form-data">
            <input class="field" type="file" name="file" accept=".csv,text/csv" required style="width:100%;margin:10px 0">
            <button class="btn blue" style="width:100%;padding:13px">⇩ Extraer Clientes por CSV</button>
          </form>
          <div style="margin-top:10px"><a class="btn" href="{url_for('client_extract_csv_template')}">Descargar plantilla CSV</a></div>
        </div>
      </div>
    </div>
    '''
    return base.shell('Extraer Clientes', body, 'client_extract')


def extract_pppoe():
    if not base.logged_in():
        return redirect(url_for('login'))
    ensure_schema()
    router = (request.form.get('router') or '').strip()
    c = base.db()
    if not _table_exists(c, 'push_pppoe_secrets'):
        c.close(); flash('Todavía no hay datos PPPoE sincronizados.'); return redirect(url_for('client_extract'))
    if not router:
        a = c.execute('SELECT name FROM push_router_agents ORDER BY id DESC LIMIT 1').fetchone() if _table_exists(c, 'push_router_agents') else None
        router = a['name'] if a else 'CCR2116'
    secrets = c.execute('SELECT * FROM push_pppoe_secrets WHERE router_name=? ORDER BY id', (router,)).fetchall()
    actives = c.execute('SELECT * FROM push_pppoe_active WHERE router_name=?', (router,)).fetchall() if _table_exists(c, 'push_pppoe_active') else []
    amap = {r['name']: r for r in actives}
    created = updated = skipped = 0
    now = datetime.now().isoformat(timespec='seconds')
    for r in secrets:
        pppoe = (r['name'] or '').strip()
        if not pppoe:
            skipped += 1; continue
        active = amap.get(pppoe)
        ip = (active['address'] if active else r['remote_address']) or ''
        status = 'SUSPENDIDO' if _truthy_disabled(r['disabled']) else 'ACTIVO'
        profile = (r['profile'] or '').strip()
        comment = (r['comment'] or '').strip()
        existing = c.execute('SELECT * FROM customers WHERE lower(pppoe)=lower(?) LIMIT 1', (pppoe,)).fetchone()
        if existing:
            c.execute('''UPDATE customers SET ip_address=?,status=?,service_status=?,router_name=?,mikrotik_profile=?,source=?,last_imported_at=?,notes=CASE WHEN COALESCE(notes,'')='' THEN ? ELSE notes END WHERE id=?''',
                      (ip, status, status, router, profile, 'MIKROTIK', now, comment, existing['id']))
            updated += 1
        else:
            name = comment if comment else pppoe
            cur = c.execute('''INSERT INTO customers(code,name,pppoe,ip_address,status,due_day,created_at,notes,router_name,service_status,mikrotik_profile,source,last_imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (None, name, pppoe, ip, status, 30, date.today().isoformat(), comment, router, status, profile, 'MIKROTIK', now))
            _code_after_insert(c, cur.lastrowid)
            created += 1
    c.commit(); c.close()
    try:
        base.audit('CUSTOMERS_EXTRACT_PPPoE', f'{router}: creados {created}, actualizados {updated}, omitidos {skipped}')
    except Exception:
        pass
    flash(f'Extracción PPPoE completada: {created} creados, {updated} actualizados y {skipped} omitidos.')
    return redirect(url_for('customers'))


def _plan_id(c, name):
    if not name: return None
    r = c.execute('SELECT id FROM plans WHERE lower(name)=lower(?) LIMIT 1', (name,)).fetchone()
    return r['id'] if r else None


def _zone_id(c, name):
    if not name or not _table_exists(c, 'zones'): return None
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
        try: due_day = max(1, min(int(due_raw or 30), 31))
        except Exception: due_day = 30
        existing = c.execute('SELECT * FROM customers WHERE lower(pppoe)=lower(?) LIMIT 1', (pppoe,)).fetchone() if pppoe else None
        if not existing and document:
            existing = c.execute('SELECT * FROM customers WHERE document=? LIMIT 1', (document,)).fetchone()
        plan_id = _plan_id(c, plan); zone_id = _zone_id(c, zone)
        if existing:
            c.execute('''UPDATE customers SET name=COALESCE(NULLIF(?,''),name),phone=COALESCE(NULLIF(?,''),phone),document=COALESCE(NULLIF(?,''),document),email=COALESCE(NULLIF(?,''),email),address=COALESCE(NULLIF(?,''),address),zone=COALESCE(NULLIF(?,''),zone),zone_id=COALESCE(?,zone_id),pppoe=COALESCE(NULLIF(?,''),pppoe),ip_address=COALESCE(NULLIF(?,''),ip_address),onu_serial=COALESCE(NULLIF(?,''),onu_serial),plan_id=COALESCE(?,plan_id),status=?,service_status=?,due_day=?,mikrotik_profile=COALESCE(NULLIF(?,''),mikrotik_profile),source='CSV',last_imported_at=? WHERE id=?''',
                      (name, phone, document, email, address, zone, zone_id, pppoe, ip, onu, plan_id, status, status, due_day, profile, now, existing['id']))
            updated += 1
        else:
            cur = c.execute('''INSERT INTO customers(code,name,phone,document,email,address,zone,zone_id,pppoe,ip_address,onu_serial,plan_id,status,due_day,created_at,service_status,mikrotik_profile,source,last_imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (None, name or pppoe, phone, document, email, address, zone, zone_id, pppoe, ip, onu, plan_id, status, due_day, date.today().isoformat(), status, profile, 'CSV', now))
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
    app.add_url_rule('/clients/extract/pppoe', endpoint='client_extract_pppoe', view_func=extract_pppoe, methods=['POST'])
    app.add_url_rule('/clients/extract/csv', endpoint='client_extract_csv', view_func=extract_csv, methods=['POST'])
    app.add_url_rule('/clients/extract/csv-template', endpoint='client_extract_csv_template', view_func=csv_template, methods=['GET'])
    if not any(ep == 'client_extract' for ep, _, _ in base.NAV):
        pos = next((i + 1 for i, item in enumerate(base.NAV) if item[0] == 'customers'), 2)
        base.NAV.insert(pos, ('client_extract', '⇩', 'Extraer clientes'))
