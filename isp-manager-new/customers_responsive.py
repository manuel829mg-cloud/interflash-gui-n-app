import json
from datetime import datetime
from html import escape
from flask import request, redirect, url_for, flash, session
import app as base


def esc(value):
    return escape('' if value is None else str(value))


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _queue(c, customer, action, payload=None):
    c.execute(
        '''INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by)
           VALUES(?,?,?,?,?,?,?,?)''',
        (
            customer['router_name'] or 'CCR2116',
            customer['id'],
            customer['pppoe'] or '',
            action,
            json.dumps(payload or {}, ensure_ascii=False),
            'PENDIENTE',
            datetime.now().isoformat(timespec='seconds'),
            session.get('user') or base.ADMIN_USER,
        ),
    )


def _icon(name):
    icons = {
        'file': '''<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h8M8 9h2"/></svg>''',
        'edit': '''<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>''',
        'suspend': '''<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9 8v8M15 8v8"/></svg>''',
        'reactivate': '''<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>''',
        'trash': '''<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 15H6L5 6"/><path d="M10 10v7M14 10v7"/></svg>''',
    }
    return icons.get(name, '')


def customer_service_action(id, action):
    if not base.logged_in():
        return redirect(url_for('login'))

    action = (action or '').upper()
    if action not in ('SUSPEND', 'REACTIVATE', 'DELETE'):
        flash('Acción no permitida.')
        return redirect(url_for('customers'))

    c = base.db()
    customer = c.execute('SELECT * FROM customers WHERE id=?', (id,)).fetchone()
    if not customer:
        c.close()
        flash('Cliente no encontrado.')
        return redirect(url_for('customers'))

    if action == 'SUSPEND':
        c.execute("UPDATE customers SET status='SUSPENDIDO', service_status='SUSPENDIDO' WHERE id=?", (id,))
        if customer['pppoe']:
            _queue(c, customer, 'SUSPEND')
        message = 'Cliente marcado como suspendido.' + (' Orden enviada a la cola del MikroTik.' if customer['pppoe'] else '')
        audit_action = 'CUSTOMER_SUSPEND'
    elif action == 'REACTIVATE':
        c.execute("UPDATE customers SET status='ACTIVO', service_status='ACTIVO' WHERE id=?", (id,))
        if customer['pppoe']:
            _queue(c, customer, 'REACTIVATE')
        message = 'Cliente marcado como activo.' + (' Orden enviada a la cola del MikroTik.' if customer['pppoe'] else '')
        audit_action = 'CUSTOMER_REACTIVATE'
    else:
        c.execute("UPDATE customers SET status='ELIMINADO', service_status='ELIMINADO' WHERE id=?", (id,))
        if customer['pppoe']:
            _queue(c, customer, 'DELETE_PPPOE')
        message = 'Cliente eliminado de la lista.' + (' Se envió la eliminación del PPPoE al MikroTik.' if customer['pppoe'] else '') + ' El historial financiero se conserva.'
        audit_action = 'CUSTOMER_DELETE'

    c.commit()
    c.close()
    try:
        base.audit(audit_action, f"#{id} {customer['name']}")
    except Exception:
        pass
    flash(message)
    return redirect(url_for('customers'))


def customers_responsive():
    if not base.logged_in():
        return redirect(url_for('login'))

    q = (request.args.get('q') or '').strip()
    c = base.db()
    sql = '''SELECT cu.*,p.name plan_name,z.name zone_name
             FROM customers cu
             LEFT JOIN plans p ON p.id=cu.plan_id
             LEFT JOIN zones z ON z.id=cu.zone_id
             WHERE COALESCE(cu.status,'ACTIVO') <> 'ELIMINADO' '''
    args = []
    if q:
        like = '%' + q + '%'
        sql += ''' AND (cu.name LIKE ? OR cu.phone LIKE ? OR cu.document LIKE ?
                   OR cu.pppoe LIKE ? OR cu.onu_serial LIKE ? OR cu.code LIKE ?)'''
        args = [like] * 6
    sql += ' ORDER BY cu.id DESC'
    rows = c.execute(sql, args).fetchall()

    active_names = set()
    active_pairs = set()
    if _table_exists(c, 'push_pppoe_active'):
        for a in c.execute('SELECT router_name,name FROM push_pppoe_active').fetchall():
            pppoe_name = (a['name'] or '').strip()
            router_name = (a['router_name'] or 'CCR2116').strip()
            if pppoe_name:
                active_names.add(pppoe_name)
                active_pairs.add((router_name, pppoe_name))
    c.close()

    trs = []
    connected_count = 0
    disconnected_count = 0
    suspended_count = 0
    no_pppoe_count = 0

    for r in rows:
        local_status = (r['status'] or 'ACTIVO').upper()
        pppoe = (r['pppoe'] or '').strip()
        router_name = (r['router_name'] or 'CCR2116').strip()

        if local_status == 'SUSPENDIDO':
            state = 'SUSPENDIDO'
            suspended_count += 1
        elif not pppoe:
            state = 'SIN PPPoE'
            no_pppoe_count += 1
        elif (router_name, pppoe) in active_pairs or pppoe in active_names:
            state = 'CONECTADO'
            connected_count += 1
        else:
            state = 'DESCONECTADO'
            disconnected_count += 1

        if state == 'CONECTADO':
            cls = 'ok connection-online'
        elif state == 'SUSPENDIDO':
            cls = 'bad connection-suspended'
        elif state == 'SIN PPPoE':
            cls = 'connection-none'
        else:
            cls = 'warn connection-offline'

        code = r['code'] or ('#' + str(r['id']))

        if state == 'SUSPENDIDO':
            service_button = f'''<form method="post" action="{url_for('customer_service_action',id=r['id'],action='REACTIVATE')}"><button class="icon-btn reactivate-icon" type="submit" title="Reactivar cliente" aria-label="Reactivar cliente" onclick="return confirm('¿Reactivar este cliente?')">{_icon('reactivate')}</button></form>'''
        else:
            service_button = f'''<form method="post" action="{url_for('customer_service_action',id=r['id'],action='SUSPEND')}"><button class="icon-btn suspend-icon" type="submit" title="Suspender cliente" aria-label="Suspender cliente" onclick="return confirm('¿Suspender este cliente?')">{_icon('suspend')}</button></form>'''

        delete_button = f'''<form method="post" action="{url_for('customer_service_action',id=r['id'],action='DELETE')}"><button class="icon-btn delete-icon" type="submit" title="Eliminar cliente" aria-label="Eliminar cliente" onclick="return confirm('¿ELIMINAR este cliente? Se quitará de la lista y se eliminará su PPPoE del MikroTik. El historial de facturas y pagos se conservará.')">{_icon('trash')}</button></form>'''

        actions = f'''<div class="client-actions">
          <a class="icon-btn" href="{url_for('customer_profile',id=r['id'])}" title="Ficha del cliente" aria-label="Ficha del cliente">{_icon('file')}</a>
          <a class="icon-btn" href="{url_for('customer_edit',id=r['id'])}" title="Editar cliente" aria-label="Editar cliente">{_icon('edit')}</a>
          {service_button}
          {delete_button}
        </div>'''

        dot_class = 'dot-online' if state == 'CONECTADO' else ('dot-offline' if state == 'DESCONECTADO' else ('dot-suspended' if state == 'SUSPENDIDO' else 'dot-none'))
        state_html = f'<span class="tag {cls}"><span class="status-dot {dot_class}"></span>{esc(state)}</span>'

        trs.append(f'''<tr>
          <td class="c-code" data-label="Código"><span>{esc(code)}</span></td>
          <td class="c-client" data-label="Cliente"><b>{esc(r['name'])}</b><br><span class="muted">{esc(r['phone'])}</span></td>
          <td class="c-plan" data-label="Plan">{esc(r['plan_name'] or '-')}</td>
          <td class="c-zone" data-label="Zona">{esc(r['zone_name'] or r['zone'] or '-')}</td>
          <td class="c-pppoe" data-label="PPPoE">{esc(pppoe or '-')}</td>
          <td class="c-state" data-label="Conexión">{state_html}</td>
          <td class="c-actions" data-label="Acciones">{actions}</td>
        </tr>''')

    body = f'''
    <style>
      .clients-fit-panel{{overflow-x:hidden;max-width:100%;}}
      .clients-fit{{width:100%;max-width:100%;table-layout:fixed;border-collapse:collapse;}}
      .clients-fit th,.clients-fit td{{padding:11px 8px;border-bottom:1px solid #1b3045;text-align:left;vertical-align:middle;font-size:13px;min-width:0;overflow-wrap:anywhere;word-break:break-word;}}
      .clients-fit th{{color:#92a5b8;font-size:11px;text-transform:uppercase;}}
      .clients-fit .c-code{{width:9%;}}
      .clients-fit .c-code span{{white-space:nowrap;word-break:normal;overflow-wrap:normal;}}
      .clients-fit .c-client{{width:22%;}}
      .clients-fit .c-plan{{width:13%;}}
      .clients-fit .c-zone{{width:11%;}}
      .clients-fit .c-pppoe{{width:15%;font-family:Consolas,monospace;font-size:12px;}}
      .clients-fit .c-state{{width:12%;}}
      .clients-fit .c-actions{{width:18%;}}
      .client-actions{{display:flex;gap:0;align-items:center;flex-wrap:nowrap;}}
      .client-actions form{{margin:0;display:flex;}}
      .icon-btn{{width:42px;height:38px;display:inline-flex;align-items:center;justify-content:center;border:1px solid #33485d;background:#132231;color:#aebdcb;cursor:pointer;padding:0;margin:0 -1px 0 0;border-radius:0;transition:.15s ease;}}
      .client-actions > :first-child{{border-radius:7px 0 0 7px;}}
      .client-actions > :last-child .icon-btn,.client-actions > .icon-btn:last-child{{border-radius:0 7px 7px 0;}}
      .icon-btn:hover{{background:#1b3043;color:#fff;border-color:#50667c;position:relative;z-index:1;}}
      .icon-btn svg{{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;pointer-events:none;}}
      .suspend-icon:hover{{color:#ffc94e;border-color:#8a5c0a;background:#3b2b0d;}}
      .reactivate-icon:hover{{color:#66e7ad;border-color:#0a925d;background:#0b3e2b;}}
      .delete-icon:hover{{color:#ff919b;border-color:#a52a34;background:#45171b;}}
      .clients-toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:13px;}}
      .clients-toolbar .field{{flex:1;min-width:220px;max-width:560px;}}
      .connection-summary{{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 14px;}}
      .connection-card{{display:inline-flex;align-items:center;gap:8px;padding:9px 12px;border-radius:12px;border:1px solid #243b52;background:#0d1c2c;font-size:12px;font-weight:800;}}
      .connection-card b{{font-size:17px;color:#fff;}}
      .status-dot{{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:7px;vertical-align:1px;box-shadow:0 0 0 3px rgba(255,255,255,.04);}}
      .dot-online{{background:#22d37f;box-shadow:0 0 0 3px rgba(34,211,127,.12),0 0 10px rgba(34,211,127,.45);}}
      .dot-offline{{background:#ffad2f;box-shadow:0 0 0 3px rgba(255,173,47,.12);}}
      .dot-suspended{{background:#ff5e6c;box-shadow:0 0 0 3px rgba(255,94,108,.12);}}
      .dot-none{{background:#8798aa;box-shadow:0 0 0 3px rgba(135,152,170,.12);}}
      .connection-none{{display:inline-flex;align-items:center;padding:6px 9px;border-radius:999px;border:1px solid #3a4b5d;color:#aab7c4;background:#172534;font-size:11px;font-weight:800;}}
      .connection-online,.connection-offline,.connection-suspended{{display:inline-flex;align-items:center;white-space:nowrap;}}
      @media(max-width:1180px){{
        .clients-fit .c-zone{{display:none;}}
        .clients-fit .c-client{{width:25%;}}
        .clients-fit .c-plan{{width:14%;}}
        .clients-fit .c-pppoe{{width:17%;}}
        .clients-fit .c-code{{width:10%;}}
        .clients-fit .c-state{{width:13%;}}
        .clients-fit .c-actions{{width:21%;}}
      }}
      @media(max-width:900px){{
        .clients-fit .c-plan{{display:none;}}
        .clients-fit .c-client{{width:29%;}}
        .clients-fit .c-pppoe{{width:21%;}}
        .clients-fit .c-code{{width:12%;}}
        .clients-fit .c-state{{width:15%;}}
        .clients-fit .c-actions{{width:23%;}}
        .icon-btn{{width:38px;height:36px;}}
      }}
      @media(max-width:760px){{
        .clients-fit{{table-layout:auto;}}
        .clients-fit thead{{display:none;}}
        .clients-fit,.clients-fit tbody,.clients-fit tr,.clients-fit td{{display:block;width:100%!important;}}
        .clients-fit tr{{background:#0b1725;border:1px solid #22374e;border-radius:12px;margin:0 0 10px;padding:10px 12px;}}
        .clients-fit td{{border:0;padding:6px 0 6px 94px;position:relative;min-height:30px;}}
        .clients-fit td::before{{content:attr(data-label);position:absolute;left:0;top:6px;width:86px;color:#7f94aa;font-size:10px;text-transform:uppercase;font-weight:800;}}
        .clients-fit .c-zone,.clients-fit .c-plan{{display:block;}}
        .client-actions{{justify-content:flex-start;}}
        .clients-toolbar .field{{min-width:100%;max-width:100%;}}
      }}
    </style>
    <div class="head"><div><h1>Clientes</h1><p>Clientes, servicio, facturas, ONU y soporte</p></div><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div>
    <div class="panel clients-fit-panel">
      <div class="connection-summary">
        <div class="connection-card"><span class="status-dot dot-online"></span>Conectados <b>{connected_count}</b></div>
        <div class="connection-card"><span class="status-dot dot-offline"></span>Desconectados <b>{disconnected_count}</b></div>
        <div class="connection-card"><span class="status-dot dot-suspended"></span>Suspendidos <b>{suspended_count}</b></div>
        <div class="connection-card"><span class="status-dot dot-none"></span>Sin PPPoE <b>{no_pppoe_count}</b></div>
      </div>
      <form class="clients-toolbar" method="get">
        <input class="field" name="q" value="{esc(q)}" placeholder="Buscar cliente, teléfono, cédula, PPPoE, ONU">
        <button class="btn blue">Buscar</button>
        <a class="btn" href="{url_for('customers')}">Limpiar</a>
      </form>
      <table class="clients-fit">
        <thead><tr><th>Código</th><th>Cliente</th><th>Plan</th><th class="c-zone">Zona</th><th>PPPoE</th><th>Conexión</th><th>Acciones</th></tr></thead>
        <tbody>{''.join(trs) or '<tr><td colspan="7" class="muted">No hay clientes.</td></tr>'}</tbody>
      </table>
    </div>
    '''
    return base.shell('Clientes', body, 'customers')


def setup(app):
    app.view_functions['customers'] = customers_responsive
    app.add_url_rule('/customers/<int:id>/service/<action>', endpoint='customer_service_action', view_func=customer_service_action, methods=['POST'])
