import json
import math
from customers_responsive import device_ip_links, search_text
import re
import calendar
from datetime import date, datetime, timedelta
from html import escape
from flask import request, redirect, url_for, flash, session
import app as base
import pbr_client


def esc(v):
    return escape('' if v is None else str(v))


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _actor():
    return session.get('user') or base.ADMIN_USER


def ensure_schema():
    c = base.db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS customer_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      customer_id INTEGER NOT NULL,
      action TEXT NOT NULL,
      detail TEXT,
      actor TEXT,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_customer_events_customer ON customer_events(customer_id,id DESC);
    ''')
    c.commit(); c.close()


def _event(customer_id, action, detail=''):
    c = base.db()
    c.execute('INSERT INTO customer_events(customer_id,action,detail,actor,created_at) VALUES(?,?,?,?,?)',
              (customer_id, action, detail, _actor(), datetime.now().isoformat(timespec='seconds')))
    c.commit(); c.close()


def _phone_wa(phone):
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if len(digits) == 10:
        digits = '1' + digits
    return digits


def _due_date_for(day_value):
    today = date.today()
    day = max(1, int(day_value or 30))
    day = min(day, calendar.monthrange(today.year, today.month)[1])
    return date(today.year, today.month, day)


def _float_power(v):
    if v is None:
        return None
    m = re.search(r'-?\d+(?:\.\d+)?', str(v))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _real_state(cu, active_names, secret_disabled):
    local = (cu['status'] or 'ACTIVO').upper()
    if local == 'SUSPENDIDO':
        return 'SUSPENDIDO', 'bad'
    user = (cu['pppoe'] or '').strip()
    if not user:
        return 'SIN PPPOE', 'warn'
    if secret_disabled.get(user, False):
        return 'DESHABILITADO', 'bad'
    if user in active_names:
        return 'CONECTADO', 'ok'
    return 'DESCONECTADO', 'warn'


def _queue(c, cu, action, payload=None):
    pbr_client._queue(c, cu['id'], cu['pppoe'] or '', cu['router_name'] or 'CCR2116', action, payload or {})


def customer_service_action_plus(id, action):
    if not base.logged_in():
        return redirect(url_for('login'))
    action = (action or '').upper()
    if action not in ('SUSPEND', 'REACTIVATE', 'DELETE'):
        flash('Acción no permitida.')
        return redirect(url_for('customers'))
    c = base.db()
    cu = c.execute('SELECT * FROM customers WHERE id=?', (id,)).fetchone()
    if not cu:
        c.close(); flash('Cliente no encontrado.'); return redirect(url_for('customers'))
    if action == 'SUSPEND':
        c.execute("UPDATE customers SET status='SUSPENDIDO',service_status='SUSPENDIDO' WHERE id=?", (id,))
        if cu['pppoe']:
            _queue(c, cu, 'SUSPEND')
        msg = 'Cliente suspendido. La orden fue enviada al MikroTik.' if cu['pppoe'] else 'Cliente marcado como suspendido.'
        ev = ('SUSPENDER', f'PPPoE {cu["pppoe"] or "-"}')
    elif action == 'REACTIVATE':
        c.execute("UPDATE customers SET status='ACTIVO',service_status='ACTIVO' WHERE id=?", (id,))
        if cu['pppoe']:
            _queue(c, cu, 'REACTIVATE')
        msg = 'Cliente reactivado. La orden fue enviada al MikroTik.' if cu['pppoe'] else 'Cliente marcado como activo.'
        ev = ('REACTIVAR', f'PPPoE {cu["pppoe"] or "-"}')
    else:
        c.execute("UPDATE customers SET status='ELIMINADO',service_status='ELIMINADO' WHERE id=?", (id,))
        if cu['pppoe']:
            _queue(c, cu, 'DELETE_PPPOE')
        msg = 'Cliente enviado a la papelera. Se conserva su historial.'
        ev = ('ELIMINAR', f'PPPoE {cu["pppoe"] or "-"}')
    c.commit(); c.close()
    _event(id, ev[0], ev[1])
    try: base.audit('CUSTOMER_' + action, f'#{id} {cu["name"]} · {_actor()}')
    except Exception: pass
    flash(msg)
    return redirect(url_for('customers'))



def _map_coordinates(latitude, longitude):
    try:
        lat, lng = float(latitude), float(longitude)
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return f'{lat:.7f}', f'{lng:.7f}'
    except (TypeError, ValueError):
        return None


def _customer_map_url(customer):
    coordinates = _map_coordinates(customer['latitude'], customer['longitude'])
    return 'https://www.google.com/maps/search/?api=1&query=' + ','.join(coordinates) if coordinates else ''


def customer_location(id):
    if not base.logged_in():
        return redirect(url_for('login'))
    c = base.db()
    cu = c.execute('SELECT * FROM customers WHERE id=?', (id,)).fetchone()
    if not cu:
        c.close()
        flash('Cliente no encontrado.')
        return redirect(url_for('customers'))
    lat, lng = cu['latitude'] or '', cu['longitude'] or ''
    error = ''
    if request.method == 'POST':
        lat = (request.form.get('latitude') or '').strip()
        lng = (request.form.get('longitude') or '').strip()
        coordinates = _map_coordinates(lat, lng)
        if (lat or lng) and not coordinates:
            error = '<div class="notice" role="alert">Introduce una latitud entre -90 y 90 y una longitud entre -180 y 180.</div>'
        else:
            values = coordinates or (None, None)
            c.execute('UPDATE customers SET latitude=?,longitude=? WHERE id=?', (*values, id))
            c.commit()
            c.close()
            _event(id, 'UBICACION', 'Ubicación actualizada' if coordinates else 'Ubicación retirada')
            flash('Ubicación guardada.' if coordinates else 'Ubicación retirada.')
            return redirect(url_for('customer_location', id=id))
    c.close()
    map_url = _customer_map_url(cu)
    map_button = f'<a class="btn blue" href="{esc(map_url)}" target="_blank" rel="noopener noreferrer">Ver en el mapa</a>' if map_url else '<span class="muted">Ubicación pendiente</span>'
    body = f'''<div class="head"><div><h1>Ubicación del cliente</h1><p>{esc(cu['name'])}</p></div><a class="btn" href="{url_for('customer_profile',id=id)}">Volver a la ficha</a></div>
    {error}<form class="panel formgrid" method="post">
      <p class="full muted">Guarda el punto donde está instalado el servicio. Puedes copiar las coordenadas del mapa o usar tu ubicación cuando estés en casa del cliente.</p>
      <label>Latitud<input id="customer-latitude" class="field" name="latitude" type="number" step="any" min="-90" max="90" value="{esc(lat)}" placeholder="18.4861"></label>
      <label>Longitud<input id="customer-longitude" class="field" name="longitude" type="number" step="any" min="-180" max="180" value="{esc(lng)}" placeholder="-69.9312"></label>
      <div class="full quick-links"><button class="btn green" type="submit">Guardar ubicación</button><button id="customer-gps" class="btn" type="button">Usar mi ubicación actual</button>{map_button}</div>
      <p id="customer-gps-status" class="full muted" role="status"></p>
    </form>'''
    body += r'''<script>
    (() => {
      const button = document.getElementById('customer-gps');
      const status = document.getElementById('customer-gps-status');
      button.addEventListener('click', () => {
        if (!navigator.geolocation) { status.textContent = 'Este navegador no permite obtener la ubicación. Introduce las coordenadas.'; return; }
        button.disabled = true;
        status.textContent = 'Buscando tu ubicación…';
        navigator.geolocation.getCurrentPosition(position => {
          document.getElementById('customer-latitude').value = position.coords.latitude.toFixed(7);
          document.getElementById('customer-longitude').value = position.coords.longitude.toFixed(7);
          status.textContent = 'Ubicación obtenida. Pulsa Guardar ubicación para asignarla al cliente.';
          button.disabled = false;
        }, error => {
          status.textContent = error.code === 1 ? 'Permiso de ubicación denegado. Puedes introducir las coordenadas manualmente.' : 'No se pudo obtener tu ubicación. Inténtalo de nuevo o introduce las coordenadas.';
          button.disabled = false;
        }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
      });
    })();
    </script>'''
    return base.shell('Ubicación del cliente', body, 'customers')


def customers_plus():
    if not base.logged_in():
        return redirect(url_for('login'))
    q = (request.args.get('q') or '').strip()
    status_filter = 'SUSPENDIDO' if request.args.get('status') == 'SUSPENDIDO' else ''
    overdue_filter = request.args.get('overdue') == '1'
    c = base.db()
    sql = '''SELECT cu.*,p.name plan_name,p.price plan_price,z.name zone_name,
             COALESCE((SELECT SUM(MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))) FROM invoices i WHERE i.customer_id=cu.id AND UPPER(COALESCE(i.status,'PENDIENTE')) NOT IN ('PAGADA','ANULADA','CANCELADA')),0) debt,
             (SELECT MIN(i.due_date) FROM invoices i WHERE i.customer_id=cu.id AND UPPER(COALESCE(i.status,'PENDIENTE')) NOT IN ('PAGADA','ANULADA','CANCELADA') AND MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))>0) oldest_due,
             (SELECT MAX(py.paid_at) FROM payments py WHERE py.customer_id=cu.id) last_payment,
             (SELECT od.status FROM onu_devices od WHERE od.customer_id=cu.id ORDER BY od.id DESC LIMIT 1) onu_status,
             (SELECT od.rx_power FROM onu_devices od WHERE od.customer_id=cu.id ORDER BY od.id DESC LIMIT 1) onu_rx
             FROM customers cu
             LEFT JOIN plans p ON p.id=cu.plan_id
             LEFT JOIN zones z ON z.id=cu.zone_id
             WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' '''
    args = []
    if status_filter:
        sql += 'AND cu.status = ? '
        args.append(status_filter)
    if overdue_filter:
        sql += "AND EXISTS (SELECT 1 FROM invoices i WHERE i.customer_id=cu.id AND UPPER(COALESCE(i.status,'PENDIENTE')) NOT IN ('PAGADA','ANULADA','CANCELADA') AND MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))>0) "
    sql += 'ORDER BY cu.id DESC'
    rows = c.execute(sql, args).fetchall()
    active_names = {r['name'] for r in c.execute('SELECT name FROM push_pppoe_active').fetchall()} if _table_exists(c, 'push_pppoe_active') else set()
    active_ips = {(str(a['router_name'] or 'CCR2116').strip(), str(a['name'] or '').strip()): a['address'] for a in c.execute('SELECT router_name,name,address FROM push_pppoe_active')} if _table_exists(c, 'push_pppoe_active') else {}
    secret_disabled = {}
    if _table_exists(c, 'push_pppoe_secrets'):
        for s in c.execute('SELECT name,disabled FROM push_pppoe_secrets').fetchall():
            secret_disabled[s['name']] = str(s['disabled'] or '').lower() in ('yes','true','1')
    c.close()

    icon_doc = '<svg class="reference-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M8 11h8M8 15h8M8 19h5"/></svg>'
    icon_edit = '<svg class="reference-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16-1 5 5-1L21 7a2 2 0 0 0-4-4zM15 5l4 4"/></svg>'
    icon_pause = '<svg class="reference-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v9M5.6 5.6a9 9 0 1 0 12.8 0"/></svg>'
    icon_play = '<svg class="reference-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v9M5.6 5.6a9 9 0 1 0 12.8 0"/></svg>'
    icon_trash = '<svg class="reference-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/></svg>'
    icon_wa = '<svg class="reference-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a9 9 0 0 1-13 8L3 21l1.5-5A9 9 0 1 1 21 11.5z"/></svg>'

    trs = []
    query_text = search_text(q)
    visible_count = 0
    today = date.today()
    for r in rows:
        state, cls = _real_state(r, active_names, secret_disabled)
        device_ip = active_ips.get((str(r['router_name'] or 'CCR2116').strip(), str(r['pppoe'] or '').strip())) or r['ip_address']
        ip_html = device_ip_links(device_ip)
        debt = float(r['debt'] or 0)
        oldest_due = r['oldest_due'] or ''
        overdue = bool(oldest_due and oldest_due < today.isoformat() and debt > 0)
        due = oldest_due or _due_date_for(r['due_day']).isoformat()
        wa = _phone_wa(r['phone'])
        onu_status = (r['onu_status'] or '').upper()
        onu_bad = onu_status in ('OFFLINE','DOWN','LOS','CAIDA','CAÍDA')
        client_extra = []
        if r['phone']: client_extra.append(esc(r['phone']))
        if onu_status: client_extra.append(f'ONU: {"⚠ " if onu_bad else ""}{esc(onu_status)} {esc(r["onu_rx"] or "")}')
        service_action = 'REACTIVATE' if (r['status'] or '').upper() == 'SUSPENDIDO' else 'SUSPEND'
        service_icon = icon_play if service_action == 'REACTIVATE' else icon_pause
        service_title = 'Reactivar' if service_action == 'REACTIVATE' else 'Suspender'
        service_cls = 'good' if service_action == 'REACTIVATE' else 'warnx'
        wa_btn = f'<a class="ico wa" title="WhatsApp" target="_blank" href="https://wa.me/{wa}">{icon_wa}</a>' if wa else ''
        searchable = search_text(' '.join(str(value or '') for value in (
            r['name'], r['phone'], r['document'], r['pppoe'], r['onu_serial'],
            r['code'] or '#' + str(r['id']), r['ip_address'], device_ip
        )))
        visible = query_text in searchable
        visible_count += visible
        map_url = _customer_map_url(r)
        map_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="3"/></svg>'
        map_btn = f'<a class="ico" title="Ver ubicación en el mapa" aria-label="Ver ubicación de {esc(r["name"])}" href="{esc(map_url)}" target="_blank" rel="noopener noreferrer">{map_icon}</a>' if map_url else f'<a class="ico" title="Agregar ubicación" aria-label="Agregar ubicación de {esc(r["name"])}" href="{url_for("customer_location",id=r["id"])}">{map_icon}</a>'
        row_class = 'overdue-row' if overdue else ''
        if overdue_filter:
            # Acciones compactas de cobranza, según la referencia visual.
            actions_html = f'''<a class="ico debt-promise" title="Promesa de pago" aria-label="Promesa de pago para {esc(r['name'])}" href="{url_for('promise_new',customer_id=r['id'])}"><span aria-hidden="true" style="font-size:29px;line-height:1;display:block;filter:drop-shadow(0 1px 1px #0006)">🤝</span></a>
            <a class="ico debt-edit" title="Editar cliente" aria-label="Editar {esc(r['name'])}" href="{url_for('customer_edit',id=r['id'])}">{icon_edit}</a>
            <a class="ico debt-pay" title="Registrar pago" aria-label="Registrar pago para {esc(r['name'])}" href="{url_for('invoices',customer_id=r['id'])}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v20M17 6c-2-2-9-2-9 2 0 5 9 2 9 7 0 4-7 5-10 2"/></svg></a>'''
        else:
            actions_html = f'''<a class="ico invoice-create" title="Generar factura" aria-label="Generar factura para {esc(r['name'])}" href="{url_for('invoices',customer_id=r['id'])}#nueva-factura"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 15h8M12 11v8"/></svg></a>
            <a class="ico" title="Ficha" href="{url_for('customer_profile',id=r['id'])}">{icon_doc}</a>
            {wa_btn}
            {map_btn}
            <a class="ico" title="Editar" href="{url_for('customer_edit',id=r['id'])}">{icon_edit}</a>
            <form method="post" action="{url_for('customer_service_action',id=r['id'],action=service_action)}"><button class="ico {service_cls}" title="{service_title}" onclick="return confirm('¿{service_title} este cliente?')">{service_icon}</button></form>
            <form method="post" action="{url_for('customer_service_action',id=r['id'],action='DELETE')}"><button class="ico danger" title="Eliminar" onclick="return confirm('¿Enviar este cliente a la papelera y eliminar su PPPoE del MikroTik?')">{icon_trash}</button></form>'''
        trs.append(f'''<tr class="{row_class}" data-client-search="{esc(searchable)}"{'' if visible else ' hidden'}>
          <td class="c-code"><span>{esc(r['code'] or '#'+str(r['id']))}</span></td>
          <td class="c-client"><b>{esc(r['name'])}</b><br><span class="muted">{' · '.join(client_extra)}</span></td>
          <td class="c-plan">{esc(r['plan_name'] or 'Sin plan')}<br><small class="muted">{('RD$' + format(float(r['plan_price']), ',.0f') + ' / mes') if r['plan_price'] is not None else 'Precio sin asignar'}</small></td>
          <td class="c-zone">{esc(r['zone_name'] or r['zone'] or '-')}</td>
          <td class="c-pppoe"><span>{esc(r['pppoe'] or '-')}</span><br><span class="tag {cls}">{esc(state)}</span>{ip_html}</td>
          <td class="c-due"><span class="{'danger-text' if overdue else ''}">{esc(due)}</span>{'<br><small class="danger-text">VENCIDO</small>' if overdue else ''}</td>
          <td class="c-debt"><b class="{'danger-text' if debt>0 else 'good-text'}">RD${debt:,.0f}</b></td>
          <td class="c-pay">{esc((r['last_payment'] or '-')[:10])}</td>
          <td class="c-actions"><div class="icon-actions">{actions_html}          </div></td>
        </tr>''')

    css='''<style>
    .clients-table .clients-search-row{background:transparent;border:0;box-shadow:none;margin:0;padding:0}
    .clients-table .clients-search-row>td{padding:6px 0 8px;border:0}
    .clients-search-row .toolbar2{margin:0;gap:8px}
    .clients-table tr[hidden]{display:none!important}
    .device-ip{display:flex;flex-direction:column;gap:3px;margin-top:7px}.device-ip-main{color:#53c8ff;font-weight:700;font-size:13px;overflow-wrap:anywhere}.device-ip-https{font-size:10px;color:#8bdac9}.device-ip a:hover{text-decoration:underline}.device-ip-empty{display:block;margin-top:5px;font-size:10px}

    .clients-panel{overflow:hidden}.clients-table{width:100%;border-collapse:collapse;table-layout:fixed}.clients-table th,.clients-table td{padding:10px 7px;border-bottom:1px solid #1b3045;text-align:left;vertical-align:middle;font-size:12px;overflow-wrap:anywhere}.clients-table th{font-size:10px;color:#92a5b8;text-transform:uppercase}.c-code{width:8%}.c-client{width:20%}.c-plan{width:11%}.c-zone{width:10%}.c-pppoe{width:14%}.c-due{width:10%}.clients-table .c-debt{width:9%;white-space:nowrap;overflow-wrap:normal;word-break:normal}.c-debt b{display:inline-block;white-space:nowrap}.c-pay{width:9%}.c-actions{width:17%}.c-code span,.c-pppoe>span:first-child{white-space:nowrap}.icon-actions{display:flex;gap:5px;align-items:center;flex-wrap:wrap}.icon-actions form{margin:0}.ico{width:34px;height:34px;border:1px solid #2a4058;background:#132336;color:#b9c7d6;border-radius:7px;display:inline-grid;place-items:center;cursor:pointer;padding:0}.ico:hover{background:#1b3149;color:#fff}.ico svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.ico.invoice-create{color:#62d7ff;border-color:#2a7796}.ico.debt-promise{background:#ff831c;color:#fff;border:2px solid #ffb86d;box-shadow:0 0 0 2px #ff831c33,0 2px 9px #0005}.ico.debt-edit{background:#6232db;color:white;border-color:#6232db}.ico.debt-pay{background:#199b39;color:white;border-color:#199b39}.ico.debt-promise,.ico.debt-edit,.ico.debt-pay{width:40px;height:40px}
    .clients-table .icon-actions a.ico.debt-promise,.clients-table .icon-actions a.ico.debt-promise:hover{background-color:#f97316!important;color:#fff!important;border:2px solid #fdba74!important}
    .clients-table .icon-actions a.ico.debt-edit,.clients-table .icon-actions a.ico.debt-edit:hover{background-color:#7c3aed!important;color:#fff!important;border:2px solid #a78bfa!important}
    .clients-table .icon-actions a.ico.debt-pay,.clients-table .icon-actions a.ico.debt-pay:hover{background-color:#16a34a!important;color:#fff!important;border:2px solid #86efac!important}
    .clients-table .icon-actions a.ico svg{stroke:#fff!important;opacity:1!important}.ico.debt-promise svg{width:28px;height:28px;stroke:#fff;fill:none}.ico.debt-edit svg,.ico.debt-pay svg{width:22px;height:22px}.ico.wa{color:#3ee38f}.ico.warnx{color:#ffcb69}.ico.good{color:#6af0ac}.ico.danger{color:#ff8791}.danger-text{color:#ff7b86}.good-text{color:#5ce3a0}.overdue-row{background:#3b15192e;box-shadow:inset 3px 0 #e34855}.toolbar2{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}.toolbar2 .field{flex:1;min-width:250px}.quick-links{display:flex;gap:8px;flex-wrap:wrap}
    @media(max-width:1300px){.c-zone,.c-pay{display:none}.c-client{width:24%}.c-actions{width:20%}}
    @media(max-width:1050px){.c-plan{display:none}.c-client{width:27%}.c-pppoe{width:18%}.c-actions{width:25%}}
    @media(max-width:780px){.clients-table thead{display:none}.clients-table,.clients-table tbody,.clients-table tr,.clients-table td{display:block;width:100%!important}.clients-table tr{background:#0b1725;border:1px solid #22374e;border-radius:12px;margin-bottom:10px;padding:10px}.clients-table td{border:0;padding:5px 0}.c-zone,.c-plan,.c-pay{display:block}.icon-actions{margin-top:6px}}
    </style>'''
    body=f'''{css}<div class="head"><div><h1>{'Clientes con factura pendiente' if overdue_filter else ('Clientes suspendidos' if status_filter else 'Clientes')}</h1><p>Estado PPPoE real, facturación, ONU y acciones rápidas</p></div><div class="quick-links"><a class="btn" href="{url_for('onu_overview')}">ONU / ONT</a><a class="btn" href="{url_for('customer_trash')}">Papelera</a><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div></div>
    <div class="panel clients-panel">
    <table class="clients-table"><thead><tr><th>Código</th><th>Cliente</th><th>Plan</th><th>Zona</th><th>PPPoE / estado / IP</th><th>Vence</th><th>Deuda</th><th>Último pago</th><th>Acciones</th></tr></thead><tbody><tr class="clients-search-row"><td colspan="9"><form id="clients-search-form" class="toolbar2" method="get">{'<input type="hidden" name="status" value="SUSPENDIDO">' if status_filter else ''}{'<input type="hidden" name="overdue" value="1">' if overdue_filter else ''}<input id="clients-search" class="field" name="q" aria-label="Buscar clientes" autocomplete="off" value="{esc(q)}" placeholder="Buscar cliente, teléfono, cédula, PPPoE, IP, ONU"><button class="btn blue">Buscar</button><a id="clients-search-clear" class="btn" href="{url_for('customers', **dict(([('status',status_filter)] if status_filter else []) + ([('overdue','1')] if overdue_filter else [])))}">Limpiar</a></form></td></tr>{''.join(trs)}<tr id="clients-search-empty"{' hidden' if visible_count else ''}><td colspan="9" class="muted" role="status">No hay clientes que coincidan con la búsqueda.</td></tr></tbody></table></div>'''
    body += r'''    <script>
    (() => {
      const form = document.getElementById('clients-search-form');
      const input = document.getElementById('clients-search');
      const clear = document.getElementById('clients-search-clear');
      const rows = [...document.querySelectorAll('[data-client-search]')];
      const empty = document.getElementById('clients-search-empty');
      const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
      function filterClients() {
        const query = normalize(input.value);
        let visible = 0;
        rows.forEach(row => {
          row.hidden = !row.dataset.clientSearch.includes(query);
          if (!row.hidden) {
            visible++;
          }
        });
        empty.hidden = visible > 0;
        const url = new URL(location.href);
        if (input.value.trim()) url.searchParams.set('q', input.value.trim());
        else url.searchParams.delete('q');
        history.replaceState(null, '', url);
      }
      input.addEventListener('input', filterClients);
      form.addEventListener('submit', event => { event.preventDefault(); filterClients(); });
      clear.addEventListener('click', event => {
        event.preventDefault(); input.value = ''; filterClients(); input.focus();
      });
      filterClients();
    })();
    </script>'''
    return base.shell('Clientes', body, 'customers')


def restart_pppoe(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
    if not cu or not cu['pppoe']:
        c.close(); flash('El cliente no tiene PPPoE.'); return redirect(url_for('customer_profile',id=id))
    _queue(c,cu,'RESTART_PPPOE'); c.commit(); c.close()
    _event(id,'REINICIAR_PPPOE',f'PPPoE {cu["pppoe"]}')
    flash('Reinicio PPPoE enviado a la cola. La sesión se desconectará y volverá a conectar automáticamente.')
    return redirect(url_for('customer_profile',id=id))


def change_plan(id):
    if not base.logged_in(): return redirect(url_for('login'))
    plan_id=request.form.get('plan_id') or None
    profile=(request.form.get('mikrotik_profile') or '').strip()
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
    if not cu:
        c.close(); return redirect(url_for('customers'))
    old_plan=cu['plan_id']; old_profile=cu['mikrotik_profile'] if 'mikrotik_profile' in cu.keys() else ''
    if not profile:
        profile = old_profile or ''
    c.execute('UPDATE customers SET plan_id=?,mikrotik_profile=? WHERE id=?',(plan_id,profile,id))
    if profile and profile != (old_profile or '') and cu['pppoe']:
        _queue(c,cu,'CHANGE_PROFILE',{'profile':profile})
    c.commit(); c.close()
    _event(id,'CAMBIAR_PLAN',f'Plan {old_plan or "-"} → {plan_id or "-"}; perfil {old_profile or "-"} → {profile or "-"}')
    flash('Plan actualizado.' + (' Cambio de perfil enviado al MikroTik.' if profile and profile != (old_profile or '') and cu['pppoe'] else ''))
    return redirect(url_for('customer_profile',id=id))


def _client_traffic_refresh_script(endpoint):
    return """<script>
(() => {
  const endpoint = __ENDPOINT__;
  const rate = value => {
    const mbps = Math.max(0, Number(value || 0)) / 1000000;
    return mbps >= 100 ? mbps.toFixed(0) + ' Mbps' : mbps.toFixed(2) + ' Mbps';
  };
  const bytes = value => {
    let n = Math.max(0, Number(value || 0));
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n.toFixed(0) : n.toFixed(2)) + ' ' + units[i];
  };
  let timer;
  let busy = false;
  async function updateTraffic() {
    if (document.hidden || busy) return;
    busy = true;
    try {
      const response = await fetch(endpoint, {credentials:'same-origin', cache:'no-store'});
      if (!response.ok) throw new Error('No se pudo leer el tráfico');
      const data = await response.json();
      document.getElementById('client-traffic-download').textContent = rate(data.download_bps);
      document.getElementById('client-traffic-upload').textContent = rate(data.upload_bps);
      document.getElementById('client-traffic-down-total').textContent = bytes(data.download_bytes);
      document.getElementById('client-traffic-up-total').textContent = bytes(data.upload_bytes);
      const state = document.getElementById('client-traffic-state');
      state.textContent = data.online ? 'CONECTADO' : (data.has_pppoe ? 'ESPERANDO LECTURA' : 'SIN PPPoE');
      state.className = 'tag ' + (data.online ? 'ok' : 'warn');
      document.getElementById('client-traffic-updated').textContent = data.updated_at
        ? 'Última lectura: ' + data.updated_at + ' · pantalla consultada dos veces por segundo'
        : (data.has_pppoe ? 'Esperando los contadores del monitor MikroTik…' : 'Este cliente no tiene un usuario PPPoE asociado.');
    } catch (error) {
      document.getElementById('client-traffic-state').textContent = 'SIN DATOS';
      document.getElementById('client-traffic-state').className = 'tag warn';
    } finally {
      busy = false;
    }
  }
  updateTraffic();
  timer = window.setInterval(updateTraffic, 500);
  document.addEventListener('visibilitychange', updateTraffic);
  window.addEventListener('pagehide', () => window.clearInterval(timer), {once:true});
})();
</script>""".replace('__ENDPOINT__', json.dumps(endpoint))


def customer_profile_plus(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    cu=c.execute('''SELECT cu.*,p.name plan_name,p.price plan_price,z.name zone_name FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id LEFT JOIN zones z ON z.id=cu.zone_id WHERE cu.id=?''',(id,)).fetchone()
    if not cu:
        c.close(); return redirect(url_for('customers'))
    inv=c.execute('SELECT * FROM invoices WHERE customer_id=? ORDER BY id DESC LIMIT 12',(id,)).fetchall()
    pay=c.execute('SELECT * FROM payments WHERE customer_id=? ORDER BY id DESC LIMIT 12',(id,)).fetchall()
    onus=c.execute('SELECT * FROM onu_devices WHERE customer_id=? ORDER BY id DESC LIMIT 8',(id,)).fetchall()
    cmds=c.execute('SELECT * FROM router_commands WHERE customer_id=? ORDER BY id DESC LIMIT 12',(id,)).fetchall()
    events=c.execute('SELECT * FROM customer_events WHERE customer_id=? ORDER BY id DESC LIMIT 20',(id,)).fetchall()
    plans=c.execute('SELECT * FROM plans WHERE active=1 OR id=? ORDER BY price', (cu['plan_id'],)).fetchall()
    profiles=c.execute('SELECT DISTINCT name FROM push_ppp_profiles WHERE COALESCE(name,"")<>"" ORDER BY name').fetchall() if _table_exists(c,'push_ppp_profiles') else []
    active=c.execute('SELECT * FROM push_pppoe_active WHERE name=? ORDER BY id DESC LIMIT 1',(cu['pppoe'],)).fetchone() if _table_exists(c,'push_pppoe_active') and cu['pppoe'] else None
    secret=c.execute('SELECT * FROM push_pppoe_secrets WHERE name=? ORDER BY id DESC LIMIT 1',(cu['pppoe'],)).fetchone() if _table_exists(c,'push_pppoe_secrets') and cu['pppoe'] else None
    debt=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM invoices WHERE customer_id=? AND status='PENDIENTE'",(id,)).fetchone()['s'] or 0)
    oldest=c.execute("SELECT MIN(due_date) d FROM invoices WHERE customer_id=? AND status='PENDIENTE'",(id,)).fetchone()['d']
    last_payment=c.execute('SELECT MAX(paid_at) p FROM payments WHERE customer_id=?',(id,)).fetchone()['p']
    conn_events=[]
    microcuts24=0
    last_connected=None
    last_disconnected=None
    if cu['pppoe'] and _table_exists(c,'pppoe_connection_events'):
        conn_events=c.execute(
            'SELECT * FROM pppoe_connection_events WHERE pppoe=? ORDER BY id DESC LIMIT 30',
            (cu['pppoe'],)
        ).fetchall()
        last_connected=c.execute(
            "SELECT * FROM pppoe_connection_events WHERE pppoe=? AND event='CONECTADO' ORDER BY id DESC LIMIT 1",
            (cu['pppoe'],)
        ).fetchone()
        last_disconnected=c.execute(
            "SELECT * FROM pppoe_connection_events WHERE pppoe=? AND event='DESCONECTADO' ORDER BY id DESC LIMIT 1",
            (cu['pppoe'],)
        ).fetchone()
        cutoff=(datetime.now()-timedelta(hours=24)).isoformat(timespec='seconds')
        microcuts24=c.execute(
            'SELECT COUNT(*) n FROM pppoe_connection_events WHERE pppoe=? AND is_microcut=1 AND created_at>=?',
            (cu['pppoe'],cutoff)
        ).fetchone()['n']
    c.close()

    active_names={cu['pppoe']} if active else set(); disabled={cu['pppoe']: str(secret['disabled'] or '').lower() in ('yes','true','1')} if secret and cu['pppoe'] else {}
    state, state_cls=_real_state(cu,active_names,disabled)
    due=oldest or _due_date_for(cu['due_day']).isoformat(); overdue=bool(oldest and oldest < date.today().isoformat() and debt>0)
    wa=_phone_wa(cu['phone'])
    plan_opts=''.join(f'<option value="{p["id"]}" {"selected" if str(cu["plan_id"] or "")==str(p["id"]) else ""}>{esc(p["name"])} · {p["download_mbps"]}/{p["upload_mbps"]} Mbps · RD${p["price"]:,.0f}</option>' for p in plans)
    profile_names=[x['name'] for x in profiles]
    current_profile=(cu['mikrotik_profile'] if 'mikrotik_profile' in cu.keys() else '') or (secret['profile'] if secret else '') or ''
    if current_profile and current_profile not in profile_names: profile_names.insert(0,current_profile)
    prof_opts=''.join(f'<option value="{esc(x)}" {"selected" if x==current_profile else ""}>{esc(x)}</option>' for x in profile_names)
    onu_latest=onus[0] if onus else None
    onu_state=(onu_latest['status'] if onu_latest else '') or 'ONU NO REGISTRADA'
    onu_cls='bad' if str(onu_state).upper() in ('OFFLINE','DOWN','LOS','CAIDA','CAÍDA') else 'ok' if str(onu_state).upper() in ('ONLINE','ACTIVO','UP') else 'warn'

    invr=''.join(f'<tr><td>#{x["id"]}</td><td>{esc(x["concept"])}</td><td>RD${float(x["amount"]):,.2f}</td><td>{esc(x["due_date"])}</td><td><span class="tag {"ok" if x["status"]=="PAGADA" else "warn"}">{esc(x["status"])}</span></td></tr>' for x in inv) or '<tr><td colspan="5" class="muted">Sin facturas.</td></tr>'
    payr=''.join(f'<tr><td>{esc(x["paid_at"])}</td><td>RD${float(x["amount"]):,.2f}</td><td>{esc(x["method"])}</td><td>{esc(x["reference"] or "-")}</td></tr>' for x in pay) or '<tr><td colspan="4" class="muted">Sin pagos.</td></tr>'
    onur=''.join(f'<tr><td>{esc(x["vendor"])} {esc(x["model"])}</td><td>{esc(x["serial"] or cu["onu_serial"] or "-")}</td><td>{esc(x["olt"] or "-")} / {esc(x["pon_port"] or "-")}</td><td>{esc(x["rx_power"] or "-")}</td><td>{esc(x["tx_power"] or "-")}</td><td><span class="tag {"bad" if str(x["status"] or "").upper() in ("OFFLINE","DOWN","LOS","CAIDA","CAÍDA") else "ok"}">{esc(x["status"] or "-")}</span></td><td>{esc(x["last_seen"] or "-")}</td></tr>' for x in onus) or '<tr><td colspan="7" class="muted">Sin ONU/ONT registrada.</td></tr>'
    cmdr=''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x["action"])}</td><td><span class="tag {"ok" if x["status"]=="COMPLETADO" else "bad" if x["status"]=="ERROR" else "warn"}">{esc(x["status"])}</span></td><td>{esc(x["result"] or "-")}</td></tr>' for x in cmds) or '<tr><td colspan="4" class="muted">Sin comandos.</td></tr>'
    evr=''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x["action"])}</td><td>{esc(x["actor"] or "-")}</td><td>{esc(x["detail"] or "-")}</td></tr>' for x in events) or '<tr><td colspan="4" class="muted">Sin acciones registradas todavía.</td></tr>'

    def _dur(seconds):
        if seconds is None:
            return '-'
        try: seconds=max(0,int(seconds))
        except (TypeError,ValueError): return '-'
        if seconds < 60: return f'{seconds}s'
        if seconds < 3600: return f'{seconds//60}m {seconds%60}s'
        if seconds < 86400: return f'{seconds//3600}h {(seconds%3600)//60}m'
        return f'{seconds//86400}d {(seconds%86400)//3600}h'

    current_session='-'
    if active and last_connected and last_connected['created_at']:
        try:
            current_session=_dur((datetime.now()-datetime.fromisoformat(last_connected['created_at'])).total_seconds())
        except (TypeError,ValueError):
            pass
    conn_rows=[]
    for x in conn_events:
        is_on=x['event']=='CONECTADO'
        badge='ok' if is_on else ('bad' if not x['is_microcut'] else 'warn')
        label='CONECTADO' if is_on else ('MICROCORTE' if x['is_microcut'] else 'DESCONECTADO')
        detail='Sesión actual' if is_on and x['id']==(last_connected['id'] if last_connected else -1) and active else (
            'Duración '+_dur(x['duration_seconds']) if not is_on else (
                'Volvió en '+_dur(x['gap_seconds']) if x['gap_seconds'] is not None else '-'
            )
        )
        if x['is_microcut'] and x['gap_seconds'] is not None:
            detail='Volvió en '+_dur(x['gap_seconds'])
        conn_rows.append(f'<tr><td>{esc(x["created_at"])}</td><td><span class="tag {badge}">{label}</span></td><td>{esc(detail)}</td></tr>')
    connr=''.join(conn_rows) or '<tr><td colspan="3" class="muted">El historial comenzará a llenarse automáticamente con el monitor PPPoE.</td></tr>'
    last_on_text=last_connected['created_at'] if last_connected else '-'
    last_off_text=last_disconnected['created_at'] if last_disconnected else '-'
    service_action='REACTIVATE' if (cu['status'] or '').upper()=='SUSPENDIDO' else 'SUSPEND'
    service_label='Reactivar' if service_action=='REACTIVATE' else 'Suspender'
    wa_btn=f'<a class="btn" style="border-color:#168a57;color:#70ebb0" target="_blank" href="https://wa.me/{wa}">WhatsApp</a>' if wa else ''

    body=f'''<style>.profile-kpis{{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}}.mini{{background:#0d1a29;border:1px solid #22374e;border-radius:11px;padding:13px}}.mini small{{display:block;color:#89a0b7;text-transform:uppercase;font-weight:800;font-size:10px}}.mini b{{display:block;font-size:19px;margin-top:5px}}.actionline{{display:flex;gap:7px;flex-wrap:wrap;align-items:center}}.split2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}@media(max-width:1000px){{.profile-kpis{{grid-template-columns:repeat(2,1fr)}}.split2{{grid-template-columns:1fr}}}}</style>
    <div class="head"><div><h1>{esc(cu['name'])}</h1><p>{esc(cu['code'])} · {esc(cu['pppoe'] or 'Sin PPPoE')} · {esc(cu['zone_name'] or cu['zone'] or 'Sin zona')}</p></div><div class="actionline"><a class="btn" href="{url_for('customers')}">← Clientes</a><a class="btn" href="#client-traffic">Tráfico</a>{wa_btn}<a class="btn blue" href="{url_for('customer_edit',id=id)}">Editar</a></div></div>
    <div class="profile-kpis"><div class="mini"><small>PPPoE real</small><b><span class="tag {state_cls}">{esc(state)}</span></b><span class="muted">{esc(active['address'] if active else cu['ip_address'] or '-')}</span></div><div class="mini"><small>Deuda</small><b style="color:{'#ff7b86' if debt else '#57e6a0'}">RD${debt:,.0f}</b><span class="muted">{'Vencida' if overdue else 'Pendiente' if debt else 'Al día'}</span></div><div class="mini"><small>Vencimiento</small><b>{esc(due)}</b><span class="muted">Día {esc(cu['due_day'])}</span></div><div class="mini"><small>Último pago</small><b>{esc((last_payment or '-')[:10])}</b><span class="muted">{esc(cu['plan_name'] or '-')}</span></div><div class="mini"><small>ONU / ONT</small><b><span class="tag {onu_cls}">{esc(onu_state)}</span></b><span class="muted">RX {esc(onu_latest['rx_power'] if onu_latest else '-')}</span></div></div>
    <div class="panel"><div class="actionline"><form method="post" action="{url_for('customer_service_action',id=id,action=service_action)}"><button class="btn {'green' if service_action=='REACTIVATE' else ''}" onclick="return confirm('¿{service_label} este cliente?')">{service_label}</button></form><form method="post" action="{url_for('restart_pppoe',id=id)}"><button class="btn" onclick="return confirm('¿Reiniciar la sesión PPPoE de este cliente?')">Reiniciar PPPoE</button></form><a class="btn" href="{url_for('promise_new',customer_id=id)}">Promesa de pago</a><a class="btn" href="{url_for('customer_service_info',id=id)}">Servicio / mapa</a></div></div>
    <div class="split2"><div class="panel"><h3>Cambiar plan / perfil</h3><form method="post" action="{url_for('change_customer_plan',id=id)}" class="formgrid"><label>Plan comercial<select name="plan_id"><option value="">Sin plan</option>{plan_opts}</select></label><label>Perfil MikroTik<select name="mikrotik_profile"><option value="">Sin cambiar perfil</option>{prof_opts}</select></label><div class="full"><button class="btn blue">Guardar cambio</button></div></form></div>
    <style>.client-traffic-grid{{grid-template-columns:repeat(4,minmax(120px,1fr))}}@media(max-width:700px){{.client-traffic-grid{{grid-template-columns:repeat(2,minmax(120px,1fr))}}}}</style><div class="panel client-traffic-panel" id="client-traffic"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap"><div><h3 style="margin:0">Tráfico del cliente</h3><p class="muted" style="margin:5px 0 0">Lectura de la sesión PPPoE · solo se consulta mientras esta ficha esté abierta</p></div><span id="client-traffic-state" class="tag warn">Cargando…</span></div><div class="profile-kpis client-traffic-grid" style="margin-top:12px"><div class="mini"><small>Descarga actual</small><b id="client-traffic-download">—</b><span class="muted">Velocidad recibida por el cliente</span></div><div class="mini"><small>Subida actual</small><b id="client-traffic-upload">—</b><span class="muted">Velocidad enviada por el cliente</span></div><div class="mini"><small>Descargado en esta sesión</small><b id="client-traffic-down-total">—</b></div><div class="mini"><small>Subido en esta sesión</small><b id="client-traffic-up-total">—</b></div></div><p id="client-traffic-updated" class="muted" style="margin:12px 0 0">Esperando la primera lectura del MikroTik…</p></div>
    <div class="panel"><h3>Historial de conexión PPPoE</h3><div class="profile-kpis" style="grid-template-columns:repeat(4,minmax(140px,1fr));margin-bottom:14px"><div class="mini"><small>Sesión actual</small><b>{esc(current_session)}</b><span class="muted">{esc(state)}</span></div><div class="mini"><small>Última conexión</small><b style="font-size:14px">{esc(last_on_text)}</b></div><div class="mini"><small>Última desconexión</small><b style="font-size:14px">{esc(last_off_text)}</b></div><div class="mini"><small>Microcortes 24h</small><b>{int(microcuts24 or 0)}</b><span class="muted">Reconexión ≤ 2 min</span></div></div><table class="table"><tr><th>Fecha</th><th>Evento</th><th>Detalle</th></tr>{connr}</table></div>
    <div class="panel"><h3>ONU / ONT</h3><table class="table"><tr><th>Equipo</th><th>Serial</th><th>OLT / PON</th><th>RX</th><th>TX</th><th>Estado</th><th>Última lectura</th></tr>{onur}</table></div>
    <div class="split2"><div class="panel"><h3>Facturas</h3><table class="table"><tr><th>#</th><th>Concepto</th><th>Monto</th><th>Vence</th><th>Estado</th></tr>{invr}</table></div><div class="panel"><h3>Pagos</h3><table class="table"><tr><th>Fecha</th><th>Monto</th><th>Método</th><th>Ref.</th></tr>{payr}</table></div></div>
    <div class="split2"><div class="panel"><h3>Historial de acciones</h3><table class="table"><tr><th>Fecha</th><th>Acción</th><th>Quién</th><th>Detalle</th></tr>{evr}</table></div><div class="panel"><h3>Comandos MikroTik</h3><table class="table"><tr><th>Fecha</th><th>Acción</th><th>Estado</th><th>Resultado</th></tr>{cmdr}</table></div></div>'''
    map_url = _customer_map_url(cu)
    map_button = f'<a class="btn blue" href="{esc(map_url)}" target="_blank" rel="noopener noreferrer">Ver en el mapa</a>' if map_url else '<span class="muted">Ubicación pendiente</span>'
    body += f'<div class="panel"><h3>Ubicación del cliente</h3><div class="quick-links">{map_button}<a class="btn" href="{url_for("customer_location",id=id)}">Editar ubicación</a></div></div>'
    body += _client_traffic_refresh_script(url_for('customer_traffic_api', customer_id=id))
    return base.shell('Ficha cliente',body,'customers')


def trash_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); rows=c.execute("SELECT * FROM customers WHERE status='ELIMINADO' ORDER BY id DESC").fetchall(); c.close()
    trs=''.join(f'''<tr><td>{esc(r['code'] or '#'+str(r['id']))}</td><td><b>{esc(r['name'])}</b><br><span class="muted">{esc(r['phone'] or '')}</span></td><td>{esc(r['pppoe'] or '-')}</td><td>{esc(r['zone'] or '-')}</td><td><form method="post" action="{url_for('restore_customer',id=r['id'])}"><button class="btn green" onclick="return confirm('¿Restaurar este cliente a la lista?')">Restaurar</button></form></td></tr>''' for r in rows)
    body=f'''<div class="head"><div><h1>Papelera de clientes</h1><p>Clientes eliminados. Facturas, pagos e historial se conservan.</p></div><a class="btn" href="{url_for('customers')}">← Clientes</a></div><div class="panel"><div class="notice" style="background:#17304b;color:#bfdbfe">Restaurar devuelve el registro a la lista. Si su PPPoE fue eliminado del MikroTik, tendrás que recrearlo desde Editar cliente.</div><table class="table"><tr><th>Código</th><th>Cliente</th><th>PPPoE</th><th>Zona</th><th></th></tr>{trs or '<tr><td colspan="5" class="muted">La papelera está vacía.</td></tr>'}</table></div>'''
    return base.shell('Papelera',body,'customers')


def restore_customer(id):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
    if not cu:
        c.close(); return redirect(url_for('customer_trash'))
    c.execute("UPDATE customers SET status='ACTIVO',service_status='ACTIVO' WHERE id=?",(id,)); c.commit(); c.close()
    _event(id,'RESTAURAR','Restaurado desde papelera')
    try: base.audit('CUSTOMER_RESTORE',f'#{id} {cu["name"]} · {_actor()}')
    except Exception: pass
    flash('Cliente restaurado. Revisa su PPPoE antes de darle servicio.')
    return redirect(url_for('customer_profile',id=id))


def onu_overview():
    if not base.logged_in(): return redirect(url_for('login'))
    q=(request.args.get('q') or '').strip(); c=base.db()
    sql='''SELECT o.*,cu.name customer,cu.code customer_code FROM onu_devices o LEFT JOIN customers cu ON cu.id=o.customer_id WHERE 1=1 '''; args=[]
    if q:
        like='%'+q+'%'; sql+='AND (cu.name LIKE ? OR o.serial LIKE ? OR o.olt LIKE ? OR o.pon_port LIKE ? OR o.model LIKE ?) '; args=[like]*5
    sql+='ORDER BY o.id DESC'; rows=c.execute(sql,args).fetchall(); c.close()
    total=len(rows); online=0; offline=0; optical=0; trs=[]
    for r in rows:
        st=str(r['status'] or 'PENDIENTE').upper(); is_on=st in ('ONLINE','UP','ACTIVO'); is_off=st in ('OFFLINE','DOWN','LOS','CAIDA','CAÍDA'); online+=1 if is_on else 0; offline+=1 if is_off else 0
        p=_float_power(r['rx_power']); bad_power=p is not None and (p < -27 or p > -8); optical+=1 if bad_power else 0
        cls='ok' if is_on else 'bad' if is_off else 'warn'
        trs.append(f'''<tr><td><b>{esc(r['customer'] or '-')}</b><br><span class="muted">{esc(r['customer_code'] or '')}</span></td><td>{esc(r['vendor'] or '')} {esc(r['model'] or '')}</td><td>{esc(r['serial'] or '-')}</td><td>{esc(r['olt'] or '-')} / {esc(r['pon_port'] or '-')}</td><td class="{'danger-text' if bad_power else ''}">{esc(r['rx_power'] or '-')}</td><td>{esc(r['tx_power'] or '-')}</td><td><span class="tag {cls}">{esc(st)}</span></td><td>{esc(r['last_seen'] or '-')}</td></tr>''')
    body=f'''<style>.onu-kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.danger-text{{color:#ff7b86}}@media(max-width:800px){{.onu-kpis{{grid-template-columns:repeat(2,1fr)}}}}</style><div class="head"><div><h1>ONU / ONT</h1><p>Potencia óptica, estado, serial y puerto PON</p></div><a class="btn" href="{url_for('customers')}">← Clientes</a></div><div class="onu-kpis"><div class="kpi blue1"><div class="label">ONU registradas</div><div class="value">{total}</div></div><div class="kpi green1"><div class="label">Online</div><div class="value">{online}</div></div><div class="kpi red1"><div class="label">Caídas / LOS</div><div class="value">{offline}</div></div><div class="kpi orange1"><div class="label">Potencia fuera rango</div><div class="value">{optical}</div><div class="sub">Referencia visual: -8 a -27 dBm</div></div></div><div class="panel"><form class="toolbar" method="get"><input class="field" name="q" value="{esc(q)}" placeholder="Buscar cliente, serial, OLT, PON, modelo"><button class="btn blue">Buscar</button></form><table class="table"><tr><th>Cliente</th><th>Equipo</th><th>Serial</th><th>OLT / PON</th><th>RX</th><th>TX</th><th>Estado</th><th>Última lectura</th></tr>{''.join(trs) or '<tr><td colspan="8" class="muted">No hay ONU/ONT registradas.</td></tr>'}</table></div>'''
    return base.shell('ONU / ONT',body,'customers')


def dashboard_plus():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); today=date.today().isoformat()
    total=c.execute("SELECT COUNT(*) c FROM customers WHERE COALESCE(status,'ACTIVO')<>'ELIMINADO'").fetchone()['c']
    suspended=c.execute("SELECT COUNT(*) c FROM customers WHERE status='SUSPENDIDO'").fetchone()['c']
    overdue=c.execute("SELECT COUNT(DISTINCT i.customer_id) c FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' AND UPPER(COALESCE(i.status,'PENDIENTE')) NOT IN ('PAGADA','ANULADA','CANCELADA') AND MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))>0 AND COALESCE(i.due_date,'')<>'' AND i.due_date<?",(today,)).fetchone()['c']
    overdue_money=float(c.execute("SELECT COALESCE(SUM(MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))),0) s FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' AND UPPER(COALESCE(i.status,'PENDIENTE')) NOT IN ('PAGADA','ANULADA','CANCELADA') AND MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))>0 AND COALESCE(i.due_date,'')<>'' AND i.due_date<?",(today,)).fetchone()['s'] or 0)
    pending_customers=c.execute("SELECT COUNT(DISTINCT i.customer_id) c FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' AND UPPER(COALESCE(i.status,'PENDIENTE')) NOT IN ('PAGADA','ANULADA','CANCELADA') AND MAX(0, COALESCE(i.amount,0)+COALESCE(i.late_fee,0)-COALESCE((SELECT SUM(py.amount) FROM payments py WHERE py.invoice_id=i.id),0))>0").fetchone()['c']
    pending_cmd=c.execute("SELECT COUNT(*) c FROM router_commands WHERE status IN ('PENDIENTE','EN_PROCESO')").fetchone()['c'] if _table_exists(c,'router_commands') else 0
    onu_down=c.execute("SELECT COUNT(*) c FROM onu_devices WHERE UPPER(COALESCE(status,'')) IN ('OFFLINE','DOWN','LOS','CAIDA','CAÍDA')").fetchone()['c'] if _table_exists(c,'onu_devices') else 0
    trash=c.execute("SELECT COUNT(*) c FROM customers WHERE status='ELIMINADO'").fetchone()['c']
    online_ppp=c.execute('SELECT COUNT(*) c FROM push_pppoe_active').fetchone()['c'] if _table_exists(c,'push_pppoe_active') else 0
    wan_rows=c.execute("SELECT * FROM push_router_traffic WHERE UPPER(interface_name) LIKE '%WAN%' ORDER BY interface_name").fetchall() if _table_exists(c,'push_router_traffic') else []
    wan_issues=[]; now=datetime.now()
    for w in wan_rows:
        stale=True
        if w['updated_at']:
            try: stale=(now-datetime.fromisoformat(w['updated_at'])).total_seconds()>180
            except Exception: stale=True
        if stale: wan_issues.append(w['interface_name'])
    agent_rows=c.execute('SELECT * FROM push_router_agents ORDER BY id DESC').fetchall() if _table_exists(c,'push_router_agents') else []
    router_bad=sum(1 for a in agent_rows if str(a['status'] or '').upper()!='ONLINE')
    optical_critical=0; optical_warn=0; optical_alert_rows=[]
    if _table_exists(c,'onu_optical_readings'):
        optical_critical=c.execute("""SELECT COUNT(*) c FROM onu_optical_readings
                                      WHERE rx_power IS NOT NULL AND (rx_power < -27 OR rx_power > -8)""").fetchone()['c']
        optical_warn=c.execute("""SELECT COUNT(*) c FROM onu_optical_readings
                                  WHERE rx_power >= -27 AND rx_power < -25""").fetchone()['c']
        optical_alert_rows=c.execute("""SELECT o.id,o.customer_id,o.serial,o.index_key,o.rx_power,cu.name customer
                                        FROM onu_optical_readings o
                                        LEFT JOIN customers cu ON cu.id=o.customer_id
                                        WHERE o.rx_power IS NOT NULL
                                          AND (o.rx_power < -25 OR o.rx_power > -8)
                                        ORDER BY CASE WHEN o.rx_power < -27 OR o.rx_power > -8 THEN 0 ELSE 1 END,
                                                 o.rx_power ASC
                                        LIMIT 20""").fetchall()
    recent=c.execute('''SELECT cu.name,i.amount,i.status,i.due_date FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' ORDER BY i.id DESC LIMIT 8''').fetchall()
    c.close()
    kpis=[('Clientes',total,f'<span class="pppoe-online"><span class="online-dot" aria-hidden="true"></span><strong>{online_ppp}</strong><span>clientes conectados</span></span>','blue1'),('Suspendidos',suspended,'Fuera de servicio','orange1'),('Morosos',overdue,f'RD${overdue_money:,.0f} vencido','red1'),('Clientes con factura',pending_customers,'Con saldo pendiente','purple1'),('Órdenes MikroTik',pending_cmd,'Pendientes / proceso','cyan1'),('Papelera',trash,'Clientes eliminados','green1')]
    icons = ["<circle cx=\"9\" cy=\"8\" r=\"3\"/><path d=\"M3 21v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 4v2\"/>","<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M9 8v8m6-8v8\"/>","<path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 12h8m-8 4h4\"/><path d=\"M17 15v2m0 2h.01\"/>","<rect x=\"3\" y=\"12\" width=\"18\" height=\"8\" rx=\"2\"/><path d=\"M7 16h.01M11 16h.01M12 12V8M8 4a7 7 0 0 1 8 0M3 3l18 18\"/>","<rect x=\"3\" y=\"4\" width=\"18\" height=\"6\" rx=\"2\"/><rect x=\"3\" y=\"14\" width=\"18\" height=\"6\" rx=\"2\"/><path d=\"M7 7h.01M7 17h.01M11 7h6m-6 10h6\"/>","<path d=\"M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7\"/>"]
    icons[3] = '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 12h8M8 16h5"/><path d="M17 15v2m0 2h.01"/>'
    # Keep overdue customers beside the trash card in the second row.
    kpis[3], kpis[4] = kpis[4], kpis[3]
    icons[3], icons[4] = icons[4], icons[3]
    cards=[]
    for (a,b,d,cls),icon in zip(kpis,icons):
        card=f'<div class="kpi {cls} dashboard-stat"><div class="stat-heading"><span class="stat-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{icon}</svg></span><div class="label">{a}</div></div><div class="value">{b}</div><div class="sub">{d}</div></div>'
        if a in ('Clientes', 'Suspendidos', 'Clientes con factura'):
            target = url_for('customers',overdue='1') if a == 'Clientes con factura' else (url_for('customers', status='SUSPENDIDO') if a == 'Suspendidos' else url_for('customers'))
            label = 'Ver clientes con factura vencida' if a == 'Clientes con factura vencida' else ('Ver clientes suspendidos' if a == 'Suspendidos' else 'Ver lista de clientes')
            card=card.replace('<div class="kpi ', f'<a href="{target}" aria-label="{label}" class="dashboard-client-link kpi ', 1)
            card=card[:-6] + '</a>'
        cards.append(card)
    cards=''.join(cards)
    alerts=[]
    if overdue: alerts.append(('bad',f'{overdue} clientes con facturas vencidas',url_for('invoices')))
    if suspended: alerts.append(('warn',f'{suspended} clientes suspendidos',url_for('customers')))
    if onu_down: alerts.append(('bad',f'{onu_down} ONU/ONT caídas o en LOS',url_for('onu_overview')))
    if optical_critical: alerts.append(('bad',f'{optical_critical} ONU con potencia óptica CRÍTICA (RX menor de -27 dBm)',url_for('onu_page')))
    if optical_warn: alerts.append(('warn',f'{optical_warn} ONU con potencia óptica en ALERTA (-27 a -25 dBm)',url_for('onu_page')))
    if pending_cmd: alerts.append(('warn',f'{pending_cmd} órdenes pendientes para MikroTik',url_for('mikrotik_commands')))
    if wan_issues: alerts.append(('bad',f'WAN sin lectura reciente: {", ".join(wan_issues[:4])}',url_for('routers')))
    if router_bad: alerts.append(('bad',f'{router_bad} router/agente no está ONLINE',url_for('routers')))
    if not wan_rows: alerts.append(('warn','Todavía no hay lecturas WAN en el monitor',url_for('routers')))
    alert_html=''.join(f'<a href="{u}" style="display:block;padding:11px 12px;margin:7px 0;border-radius:9px;background:{"#4a161b" if cls=="bad" else "#4e3707"};color:{"#fecaca" if cls=="bad" else "#ffe6a3"}">{esc(txt)}</a>' for cls,txt,u in alerts) or '<div style="padding:12px;border-radius:9px;background:#063f2a;color:#b8f6d6">Sin alertas operativas importantes.</div>'
    traffic_rows=[]
    fresh_rx=0.0; fresh_tx=0.0; fresh_count=0
    for w in wan_rows:
        fresh=False
        try:
            age=(now-datetime.fromisoformat(w['updated_at'])).total_seconds()
            fresh=0 <= age <= 180
        except (ValueError,TypeError):
            pass
        rx=max(0,float(w['rx_bps'] or 0)); tx=max(0,float(w['tx_bps'] or 0))
        if fresh:
            fresh_rx+=rx; fresh_tx+=tx; fresh_count+=1
        rx_text=f'{rx/1000000:,.2f} Mbps' if fresh else '—'
        tx_text=f'{tx/1000000:,.2f} Mbps' if fresh else '—'
        state='Actualizado' if fresh else 'Sin lectura reciente'
        traffic_rows.append(f'<tr><td><b>{esc(w["interface_name"])}</b><br><small class="muted">{esc(w["router_name"])}</small></td><td style="color:#75d2ff">{rx_text}</td><td style="color:#70edbd">{tx_text}</td><td><span class="muted">{state}</span><br><small>{esc(w["updated_at"] or "Sin datos")}</small></td></tr>')
    rx_total=f'{fresh_rx/1000000:,.2f}' if fresh_count else '—'
    tx_total=f'{fresh_tx/1000000:,.2f}' if fresh_count else '—'
    traffic_stamp='|'.join(str(w['updated_at'] or '') for w in wan_rows)
    traffic_html=f'''<div style="margin-top:22px;padding:14px;background:#0b192a;border:1px solid #29465b;border-radius:12px"><h3>Tráfico en vivo</h3><p style="font-size:13px"><span style="color:#75d2ff">━ Descarga</span> · <span style="color:#70edbd">━ Subida</span></p><canvas id="wan-traffic-chart" role="img" aria-label="Gráfica de descarga y subida en Mbps" style="display:block;width:100%;height:220px"></canvas><small id="wan-chart-note" class="muted">Esperando lecturas para trazar la gráfica.</small></div><section id="dashboard-traffic" data-rx="{fresh_rx/1000000}" data-tx="{fresh_tx/1000000}" data-fresh="{fresh_count}" data-stamp="{esc(traffic_stamp)}" style="margin-top:22px">
    <h3>Tráfico MikroTik</h3><p class="muted">Descarga y subida por interfaces WAN · Actualización cada segundo</p>
    <div style="display:flex;flex-wrap:wrap;gap:14px;margin:16px 0">
    <div style="flex:1;min-width:150px;padding:16px;background:#122d43;border:1px solid #2b5974;border-radius:12px"><span>↓ Descarga</span><div style="font-size:28px;font-weight:750;color:#75d2ff">{rx_total} <small style="font-size:13px">Mbps</small></div></div>
    <div style="flex:1;min-width:150px;padding:16px;background:#12372f;border:1px solid #2c6554;border-radius:12px"><span>↑ Subida</span><div style="font-size:28px;font-weight:750;color:#70edbd">{tx_total} <small style="font-size:13px">Mbps</small></div></div></div>
    <p class="muted">{fresh_count} de {len(wan_rows)} interfaces con lectura reciente. Totales de lecturas recientes.</p>
    <div style="overflow-x:auto"><table class="table"><tr><th>Interfaz</th><th>Descarga</th><th>Subida</th><th>Última lectura</th></tr>{''.join(traffic_rows) or '<tr><td colspan="4">Todavía no se reciben datos de tráfico del MikroTik.</td></tr>'}</table></div>
    <small class="muted" id="traffic-refresh-status" role="status"></small></section>'''
    alert_html += traffic_html
    rows=''.join(f'<tr><td>{esc(r["name"])}</td><td>RD${float(r["amount"]):,.2f}</td><td>{esc(r["due_date"])}</td><td><span class="tag {"ok" if r["status"]=="PAGADA" else "warn"}">{esc(r["status"])}</span></td></tr>' for r in recent)
    body=f'''<div class="head"><div><h1>Dashboard</h1><p>Operación diaria de INTER Flash</p></div><div style="display:flex;gap:8px"><a class="btn" href="{url_for('onu_overview')}">ONU / ONT</a><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div></div><style>
body .dashboard-stats{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px;margin-bottom:24px}}
body .dashboard-stats .dashboard-stat{{min-width:0;min-height:180px;padding:18px 16px;border:1px solid #30465e;border-top:3px solid var(--tone);border-radius:15px;background:linear-gradient(150deg,#192f47,#101e31);box-shadow:0 8px 22px #0002}}
body .dashboard-stat:after{{display:none}}
body .dashboard-client-link{{display:block;text-decoration:none;color:inherit;cursor:pointer}}
body .dashboard-stats .dashboard-client-link:hover{{border-color:var(--tone)}}
body .dashboard-client-link:focus-visible{{outline:3px solid var(--tone);outline-offset:4px}}
body .dashboard-stat .stat-heading{{display:flex;flex-direction:column;align-items:flex-start;gap:12px}}
body .dashboard-stat .stat-icon{{display:flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:10px;background:#ffffff08;border:1px solid #ffffff14;color:var(--tone)}}
body .dashboard-stat .stat-icon svg{{width:22px;height:22px}}
body .dashboard-stat .label{{font-size:12px;line-height:1.35;font-weight:650;letter-spacing:.1px;color:#e0eafa;text-transform:none;min-height:33px}}
body .dashboard-stat .value{{font-size:38px;line-height:1.1;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-1px;margin:6px 0 10px;color:var(--tone)}}
body .dashboard-stat .sub{{font-size:12px;line-height:1.5;color:#b1c4d9}}
body .dashboard-stat .pppoe-online{{display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;margin-top:4px;padding:9px 10px;border:1px solid #367768;border-radius:9px;background:#123c35;color:#b5f3df;font-size:14px;font-weight:600;line-height:1.3}}
body .dashboard-stat .pppoe-online strong{{font-size:23px;font-weight:750;color:#70edbd;font-variant-numeric:tabular-nums}}
body .dashboard-stat .online-dot{{width:7px;height:7px;border-radius:50%;background:#70edbd;flex-shrink:0}}

@media(max-width:1350px){{body .dashboard-stats{{grid-template-columns:repeat(3,minmax(0,1fr))}}body .dashboard-stat .stat-heading{{flex-direction:row;align-items:center}}body .dashboard-stat .label{{min-height:0}}body .dashboard-stats .dashboard-stat{{min-height:158px}}}}
@media(max-width:560px){{body .dashboard-stats{{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}body .dashboard-stats .dashboard-stat{{padding:14px 12px}}body .dashboard-stat .stat-heading{{flex-direction:column;align-items:flex-start;gap:8px}}body .dashboard-stat .label{{min-height:33px}}body .dashboard-stat .value{{font-size:32px}}}}
</style><div class="grid6 dashboard-stats">{cards}</div><div class="cards2"><div class="panel"><h3>Alertas operativas</h3>{alert_html}</div><div class="panel"><h3>Accesos rápidos</h3><p><a class="btn" href="{url_for('customers')}">Clientes</a></p><p><a class="btn" href="{url_for('mikrotik_commands')}">Cola MikroTik</a></p><p><a class="btn" href="{url_for('customer_trash')}">Papelera</a></p></div></div><div class="panel"><h3>Facturas recientes</h3><table class="table"><tr><th>Cliente</th><th>Monto</th><th>Vence</th><th>Estado</th></tr>{rows or '<tr><td colspan="4" class="muted">Sin facturas.</td></tr>'}</table></div>'''
    body += "<script>\n(() => {\nconst canvas=document.getElementById('wan-traffic-chart');\nif(!canvas) return;\nconst ctx=canvas.getContext('2d'), samples=[];\nlet busy=false, lastStamp='';\nfunction draw() {\n const width=canvas.clientWidth, height=220, ratio=window.devicePixelRatio||1;\n if(!width) return;\n canvas.width=width*ratio;canvas.height=height*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);\n const left=48,right=12,top=16,bottom=30,w=width-left-right,h=height-top-bottom;\n const max=Math.max(1,...samples.flatMap(p=>[p.rx,p.tx]))*1.15;\n ctx.font='11px Segoe UI, sans-serif';ctx.lineWidth=1;\n for(let i=0;i<=4;i++){const y=top+h*i/4;ctx.strokeStyle='#253e53';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();ctx.fillStyle='#a9bfd1';ctx.fillText((max*(1-i/4)).toFixed(0),2,y+4);}\n ctx.fillStyle='#a9bfd1';ctx.fillText('Mbps',2,10);\n for(const [key,color] of [['rx','#75d2ff'],['tx','#70edbd']]){\n  ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();\n  samples.forEach((p,i)=>{const x=left+w*i/Math.max(1,samples.length-1),y=top+h*(1-p[key]/max);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();\n  if(samples.length){const p=samples[samples.length-1];ctx.fillStyle=color;ctx.beginPath();ctx.arc(left+w*(samples.length-1)/Math.max(1,samples.length-1),top+h*(1-p[key]/max),3,0,Math.PI*2);ctx.fill();}\n }\n if(samples.length){ctx.fillStyle='#a9bfd1';ctx.fillText(samples[0].label,left,height-7);const label=samples[samples.length-1].label;ctx.fillText(label,width-right-ctx.measureText(label).width,height-7);}\n}\nfunction collect(section) {\n if(Number(section.dataset.fresh)===0){document.getElementById('wan-chart-note').textContent='Sin lecturas recientes del MikroTik.';return;}\n const stamp=section.dataset.stamp;\n if(stamp && stamp!==lastStamp){\n  const rx=Number(section.dataset.rx),tx=Number(section.dataset.tx);\n  if(!Number.isFinite(rx)||!Number.isFinite(tx))return;\n  lastStamp=stamp;samples.push({rx,tx,label:new Date().toLocaleTimeString('es-DO')});if(samples.length>30)samples.shift();draw();\n }\n document.getElementById('wan-chart-note').textContent='Lecturas recibidas mientras esta página está abierta · '+samples.length+' muestras · Consulta cada segundo · La gráfica avanza al recibir datos nuevos del router.';\n}\ncollect(document.getElementById('dashboard-traffic'));\nnew ResizeObserver(draw).observe(canvas);\nsetInterval(async () => {\n if (busy || document.hidden) return;\n busy=true;\n try {\n  const response=await fetch(window.location.pathname, {credentials:'same-origin',cache:'no-store'});\n  if (!response.ok) throw new Error('refresh');\n  const doc=new DOMParser().parseFromString(await response.text(),'text/html');\n  const next=doc.getElementById('dashboard-traffic');\n  const current=document.getElementById('dashboard-traffic');\n  if (!next || !current) throw new Error('refresh');\n  current.replaceWith(next);collect(next);\n } catch (_) {\n  const status=document.getElementById('traffic-refresh-status');\n  if(status) status.textContent='No se pudo actualizar. Mostrando la última lectura disponible.';\n } finally { busy=false; }\n},1000);\n})();\n</script>"
    return base.shell('Dashboard',body,'dashboard')


def _backfill_pppoe_phones():
    c = base.db()
    try:
        rows = c.execute("""SELECT id,pppoe FROM customers
                            WHERE TRIM(COALESCE(phone,''))=''
                            AND COALESCE(status,'ACTIVO')<>'ELIMINADO'""").fetchall()
        for row in rows:
            username = (row['pppoe'] or '').strip()
            if not re.fullmatch(r'\+?[0-9 ()-]+', username):
                continue
            digits = re.sub(r'\D', '', username)
            if len(digits) == 11 and digits.startswith('1'):
                digits = digits[1:]
            if len(digits) == 10 and digits[:3] in ('809', '829', '849'):
                c.execute("""UPDATE customers SET phone=?
                             WHERE id=? AND TRIM(COALESCE(phone,''))=''""",
                          (digits, row['id']))
        c.commit()
    finally:
        c.close()


def setup(app):
    _backfill_pppoe_phones()
    ensure_schema()
    app.add_url_rule('/customers/<int:id>/location', endpoint='customer_location', view_func=customer_location, methods=['GET','POST'])
    app.view_functions['customers'] = customers_plus
    if 'customer_profile' in app.view_functions:
        app.view_functions['customer_profile'] = customer_profile_plus
    app.view_functions['dashboard'] = dashboard_plus
    app.view_functions['customer_service_action'] = customer_service_action_plus

    app.add_url_rule('/customers/<int:id>/restart-pppoe',endpoint='restart_pppoe',view_func=restart_pppoe,methods=['POST'])
    app.add_url_rule('/customers/<int:id>/change-plan',endpoint='change_customer_plan',view_func=change_plan,methods=['POST'])
    app.add_url_rule('/customers/trash',endpoint='customer_trash',view_func=trash_page,methods=['GET'])
    app.add_url_rule('/customers/<int:id>/restore',endpoint='restore_customer',view_func=restore_customer,methods=['POST'])
    app.add_url_rule('/onu',endpoint='onu_overview',view_func=onu_overview,methods=['GET'])

    # Add actor-aware edit history without replacing the existing edit logic.
    original_edit = app.view_functions.get('customer_edit')
    if original_edit and not getattr(original_edit,'_interflash_history_wrapped',False):
        def edit_with_history(id, _orig=original_edit):
            is_post = request.method == 'POST'
            response = _orig(id)
            if is_post:
                try: _event(id,'EDITAR','Datos del cliente actualizados')
                except Exception: pass
            return response
        edit_with_history._interflash_history_wrapped = True
        app.view_functions['customer_edit'] = edit_with_history

    if not any(x[0]=='onu_overview' for x in base.NAV):
        base.NAV.append(('onu_overview','◉','ONU / ONT'))
    if not any(x[0]=='customer_trash' for x in base.NAV):
        base.NAV.append(('customer_trash','⌫','Papelera'))
