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
        # Eliminación segura: desaparece de la lista de clientes y se elimina el PPPoE,
        # pero se conserva el registro para no perder facturas, pagos ni auditoría.
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
    active = {r['name'] for r in c.execute('SELECT name FROM push_pppoe_active').fetchall()} if _table_exists(c, 'push_pppoe_active') else set()
    c.close()

    trs = []
    for r in rows:
        local_status = (r['status'] or 'ACTIVO').upper()
        if local_status == 'SUSPENDIDO':
            state = local_status
        else:
            state = 'ONLINE' if (r['pppoe'] or '') in active else local_status
        cls = 'ok' if state in ('ONLINE', 'ACTIVO') else ('bad' if state == 'SUSPENDIDO' else 'warn')
        code = r['code'] or ('#' + str(r['id']))

        if state == 'SUSPENDIDO':
            service_buttons = f'''<form method="post" action="{url_for('customer_service_action',id=r['id'],action='REACTIVATE')}" style="display:inline"><button class="btn action-reactivate" type="submit" onclick="return confirm('¿Reactivar este cliente?')">Reactivar</button></form>'''
        else:
            service_buttons = f'''<form method="post" action="{url_for('customer_service_action',id=r['id'],action='SUSPEND')}" style="display:inline"><button class="btn action-suspend" type="submit" onclick="return confirm('¿Suspender este cliente?')">Suspender</button></form>'''

        delete_button = f'''<form method="post" action="{url_for('customer_service_action',id=r['id'],action='DELETE')}" style="display:inline"><button class="btn action-delete" type="submit" onclick="return confirm('¿ELIMINAR este cliente? Se quitará de la lista y se eliminará su PPPoE del MikroTik. El historial de facturas y pagos se conservará.')">Eliminar</button></form>'''

        trs.append(f'''<tr>
          <td class="c-code" data-label="Código"><span>{esc(code)}</span></td>
          <td class="c-client" data-label="Cliente"><b>{esc(r['name'])}</b><br><span class="muted">{esc(r['phone'])}</span></td>
          <td class="c-plan" data-label="Plan">{esc(r['plan_name'] or '-')}</td>
          <td class="c-zone" data-label="Zona">{esc(r['zone_name'] or r['zone'] or '-')}</td>
          <td class="c-pppoe" data-label="PPPoE">{esc(r['pppoe'] or '-')}</td>
          <td class="c-state" data-label="Estado"><span class="tag {cls}">{esc(state)}</span></td>
          <td class="c-actions" data-label="Acciones"><div class="client-actions"><a class="btn blue" href="{url_for('customer_profile',id=r['id'])}">Ficha</a><a class="btn" href="{url_for('customer_edit',id=r['id'])}">Editar</a>{service_buttons}{delete_button}</div></td>
        </tr>''')

    body = f'''
    <style>
      .clients-fit-panel{{overflow-x:hidden;max-width:100%;}}
      .clients-fit{{width:100%;max-width:100%;table-layout:fixed;border-collapse:collapse;}}
      .clients-fit th,.clients-fit td{{padding:11px 8px;border-bottom:1px solid #1b3045;text-align:left;vertical-align:middle;font-size:13px;min-width:0;overflow-wrap:anywhere;word-break:break-word;}}
      .clients-fit th{{color:#92a5b8;font-size:11px;text-transform:uppercase;}}
      .clients-fit .c-code{{width:9%;}}
      .clients-fit .c-code span{{white-space:nowrap;word-break:normal;overflow-wrap:normal;}}
      .clients-fit .c-client{{width:21%;}}
      .clients-fit .c-plan{{width:13%;}}
      .clients-fit .c-zone{{width:11%;}}
      .clients-fit .c-pppoe{{width:14%;font-family:Consolas,monospace;font-size:12px;}}
      .clients-fit .c-state{{width:10%;}}
      .clients-fit .c-actions{{width:22%;}}
      .client-actions{{display:flex;gap:5px;flex-wrap:wrap;align-items:center;}}
      .client-actions .btn{{padding:6px 8px;font-size:11px;white-space:nowrap;}}
      .client-actions form{{margin:0;}}
      .action-suspend{{background:#5a3b08;border-color:#8a5c0a;color:#ffd782;}}
      .action-reactivate{{background:#076d45;border-color:#0a925d;color:#b8f6d6;}}
      .action-delete{{background:#5a161b;border-color:#a52a34;color:#ff9aa3;}}
      .clients-toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:13px;}}
      .clients-toolbar .field{{flex:1;min-width:220px;max-width:560px;}}
      @media(max-width:1180px){{
        .clients-fit .c-zone{{display:none;}}
        .clients-fit .c-client{{width:24%;}}
        .clients-fit .c-plan{{width:14%;}}
        .clients-fit .c-pppoe{{width:16%;}}
        .clients-fit .c-code{{width:10%;}}
        .clients-fit .c-state{{width:11%;}}
        .clients-fit .c-actions{{width:25%;}}
      }}
      @media(max-width:900px){{
        .clients-fit .c-plan{{display:none;}}
        .clients-fit .c-client{{width:27%;}}
        .clients-fit .c-pppoe{{width:20%;}}
        .clients-fit .c-code{{width:12%;}}
        .clients-fit .c-state{{width:13%;}}
        .clients-fit .c-actions{{width:28%;}}
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
      <form class="clients-toolbar" method="get">
        <input class="field" name="q" value="{esc(q)}" placeholder="Buscar cliente, teléfono, cédula, PPPoE, ONU">
        <button class="btn blue">Buscar</button>
        <a class="btn" href="{url_for('customers')}">Limpiar</a>
      </form>
      <table class="clients-fit">
        <thead><tr><th>Código</th><th>Cliente</th><th>Plan</th><th class="c-zone">Zona</th><th>PPPoE</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>{''.join(trs) or '<tr><td colspan="7" class="muted">No hay clientes.</td></tr>'}</tbody>
      </table>
    </div>
    '''
    return base.shell('Clientes', body, 'customers')


def setup(app):
    app.view_functions['customers'] = customers_responsive
    app.add_url_rule('/customers/<int:id>/service/<action>', endpoint='customer_service_action', view_func=customer_service_action, methods=['POST'])
