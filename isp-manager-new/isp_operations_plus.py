import re
import calendar
from datetime import date, datetime
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


def customers_plus():
    if not base.logged_in():
        return redirect(url_for('login'))
    q = (request.args.get('q') or '').strip()
    c = base.db()
    sql = '''SELECT cu.*,p.name plan_name,z.name zone_name,
             COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.customer_id=cu.id AND i.status='PENDIENTE'),0) debt,
             (SELECT MIN(i.due_date) FROM invoices i WHERE i.customer_id=cu.id AND i.status='PENDIENTE') oldest_due,
             (SELECT MAX(py.paid_at) FROM payments py WHERE py.customer_id=cu.id) last_payment,
             (SELECT od.status FROM onu_devices od WHERE od.customer_id=cu.id ORDER BY od.id DESC LIMIT 1) onu_status,
             (SELECT od.rx_power FROM onu_devices od WHERE od.customer_id=cu.id ORDER BY od.id DESC LIMIT 1) onu_rx
             FROM customers cu
             LEFT JOIN plans p ON p.id=cu.plan_id
             LEFT JOIN zones z ON z.id=cu.zone_id
             WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' '''
    args = []
    if q:
        like = '%' + q + '%'
        sql += '''AND (cu.name LIKE ? OR cu.phone LIKE ? OR cu.document LIKE ? OR cu.pppoe LIKE ?
                  OR cu.onu_serial LIKE ? OR cu.code LIKE ? OR cu.ip_address LIKE ?) '''
        args = [like] * 7
    sql += 'ORDER BY cu.id DESC'
    rows = c.execute(sql, args).fetchall()
    active_names = {r['name'] for r in c.execute('SELECT name FROM push_pppoe_active').fetchall()} if _table_exists(c, 'push_pppoe_active') else set()
    secret_disabled = {}
    if _table_exists(c, 'push_pppoe_secrets'):
        for s in c.execute('SELECT name,disabled FROM push_pppoe_secrets').fetchall():
            secret_disabled[s['name']] = str(s['disabled'] or '').lower() in ('yes','true','1')
    c.close()

    icon_doc = '<svg viewBox="0 0 24 24"><path d="M6 2h9l3 3v17H6z"/><path d="M15 2v5h5M9 12h6M9 16h6"/></svg>'
    icon_edit = '<svg viewBox="0 0 24 24"><path d="M4 20l4-1 11-11-3-3L5 16zM14 6l3 3"/></svg>'
    icon_pause = '<svg viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></svg>'
    icon_play = '<svg viewBox="0 0 24 24"><path d="M8 5l11 7-11 7z"/></svg>'
    icon_trash = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/></svg>'
    icon_wa = '<svg viewBox="0 0 24 24"><path d="M20 11.5a8 8 0 0 1-11.8 7L4 20l1.5-4A8 8 0 1 1 20 11.5z"/><path d="M9 8c.5 3 2 4.5 5 5"/></svg>'

    trs = []
    today = date.today()
    for r in rows:
        state, cls = _real_state(r, active_names, secret_disabled)
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
        row_class = 'overdue-row' if overdue else ''
        trs.append(f'''<tr class="{row_class}">
          <td class="c-code"><span>{esc(r['code'] or '#'+str(r['id']))}</span></td>
          <td class="c-client"><b>{esc(r['name'])}</b><br><span class="muted">{' · '.join(client_extra)}</span></td>
          <td class="c-plan">{esc(r['plan_name'] or '-')}</td>
          <td class="c-zone">{esc(r['zone_name'] or r['zone'] or '-')}</td>
          <td class="c-pppoe"><span>{esc(r['pppoe'] or '-')}</span><br><span class="tag {cls}">{esc(state)}</span></td>
          <td class="c-due"><span class="{'danger-text' if overdue else ''}">{esc(due)}</span>{'<br><small class="danger-text">VENCIDO</small>' if overdue else ''}</td>
          <td class="c-debt"><b class="{'danger-text' if debt>0 else 'good-text'}">RD${debt:,.0f}</b></td>
          <td class="c-pay">{esc((r['last_payment'] or '-')[:10])}</td>
          <td class="c-actions"><div class="icon-actions">
            <a class="ico" title="Ficha" href="{url_for('customer_profile',id=r['id'])}">{icon_doc}</a>
            {wa_btn}
            <a class="ico" title="Editar" href="{url_for('customer_edit',id=r['id'])}">{icon_edit}</a>
            <form method="post" action="{url_for('customer_service_action',id=r['id'],action=service_action)}"><button class="ico {service_cls}" title="{service_title}" onclick="return confirm('¿{service_title} este cliente?')">{service_icon}</button></form>
            <form method="post" action="{url_for('customer_service_action',id=r['id'],action='DELETE')}"><button class="ico danger" title="Eliminar" onclick="return confirm('¿Enviar este cliente a la papelera y eliminar su PPPoE del MikroTik?')">{icon_trash}</button></form>
          </div></td>
        </tr>''')

    css='''<style>
    .clients-panel{overflow:hidden}.clients-table{width:100%;border-collapse:collapse;table-layout:fixed}.clients-table th,.clients-table td{padding:10px 7px;border-bottom:1px solid #1b3045;text-align:left;vertical-align:middle;font-size:12px;overflow-wrap:anywhere}.clients-table th{font-size:10px;color:#92a5b8;text-transform:uppercase}.c-code{width:8%}.c-client{width:20%}.c-plan{width:11%}.c-zone{width:10%}.c-pppoe{width:14%}.c-due{width:10%}.c-debt{width:9%}.c-pay{width:9%}.c-actions{width:17%}.c-code span,.c-pppoe>span:first-child{white-space:nowrap}.icon-actions{display:flex;gap:5px;align-items:center;flex-wrap:wrap}.icon-actions form{margin:0}.ico{width:34px;height:34px;border:1px solid #2a4058;background:#132336;color:#b9c7d6;border-radius:7px;display:inline-grid;place-items:center;cursor:pointer;padding:0}.ico:hover{background:#1b3149;color:#fff}.ico svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.ico.wa{color:#3ee38f}.ico.warnx{color:#ffcb69}.ico.good{color:#6af0ac}.ico.danger{color:#ff8791}.danger-text{color:#ff7b86}.good-text{color:#5ce3a0}.overdue-row{background:#3b15192e;box-shadow:inset 3px 0 #e34855}.toolbar2{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}.toolbar2 .field{flex:1;min-width:250px}.quick-links{display:flex;gap:8px;flex-wrap:wrap}
    @media(max-width:1300px){.c-zone,.c-pay{display:none}.c-client{width:24%}.c-actions{width:20%}}
    @media(max-width:1050px){.c-plan{display:none}.c-client{width:27%}.c-pppoe{width:18%}.c-actions{width:25%}}
    @media(max-width:780px){.clients-table thead{display:none}.clients-table,.clients-table tbody,.clients-table tr,.clients-table td{display:block;width:100%!important}.clients-table tr{background:#0b1725;border:1px solid #22374e;border-radius:12px;margin-bottom:10px;padding:10px}.clients-table td{border:0;padding:5px 0}.c-zone,.c-plan,.c-pay{display:block}.icon-actions{margin-top:6px}}
    </style>'''
    body=f'''{css}<div class="head"><div><h1>Clientes</h1><p>Estado PPPoE real, facturación, ONU y acciones rápidas</p></div><div class="quick-links"><a class="btn" href="{url_for('onu_overview')}">ONU / ONT</a><a class="btn" href="{url_for('customer_trash')}">Papelera</a><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div></div>
    <div class="panel clients-panel"><form class="toolbar2" method="get"><input class="field" name="q" value="{esc(q)}" placeholder="Buscar cliente, teléfono, cédula, PPPoE, IP, ONU"><button class="btn blue">Buscar</button><a class="btn" href="{url_for('customers')}">Limpiar</a></form>
    <table class="clients-table"><thead><tr><th>Código</th><th>Cliente</th><th>Plan</th><th>Zona</th><th>PPPoE / estado</th><th>Vence</th><th>Deuda</th><th>Último pago</th><th>Acciones</th></tr></thead><tbody>{''.join(trs) or '<tr><td colspan="9" class="muted">No hay clientes.</td></tr>'}</tbody></table></div>'''
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
    c.execute('UPDATE customers SET plan_id=?,mikrotik_profile=? WHERE id=?',(plan_id,profile,id))
    if profile and profile != (old_profile or '') and cu['pppoe']:
        _queue(c,cu,'CHANGE_PROFILE',{'profile':profile})
    c.commit(); c.close()
    _event(id,'CAMBIAR_PLAN',f'Plan {old_plan or "-"} → {plan_id or "-"}; perfil {old_profile or "-"} → {profile or "-"}')
    flash('Plan actualizado.' + (' Cambio de perfil enviado al MikroTik.' if profile and profile != (old_profile or '') and cu['pppoe'] else ''))
    return redirect(url_for('customer_profile',id=id))


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
    plans=c.execute('SELECT * FROM plans WHERE active=1 ORDER BY price').fetchall()
    profiles=c.execute('SELECT DISTINCT name FROM push_ppp_profiles WHERE COALESCE(name,"")<>"" ORDER BY name').fetchall() if _table_exists(c,'push_ppp_profiles') else []
    active=c.execute('SELECT * FROM push_pppoe_active WHERE name=? ORDER BY id DESC LIMIT 1',(cu['pppoe'],)).fetchone() if _table_exists(c,'push_pppoe_active') and cu['pppoe'] else None
    secret=c.execute('SELECT * FROM push_pppoe_secrets WHERE name=? ORDER BY id DESC LIMIT 1',(cu['pppoe'],)).fetchone() if _table_exists(c,'push_pppoe_secrets') and cu['pppoe'] else None
    traffic=None
    if _table_exists(c,'push_router_traffic') and cu['pppoe']:
        traffic=c.execute('''SELECT * FROM push_router_traffic WHERE router_name=? AND LOWER(interface_name) LIKE ? ORDER BY updated_at DESC LIMIT 1''',
                          (cu['router_name'] or 'CCR2116','%'+str(cu['pppoe']).lower()+'%')).fetchone()
    debt=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM invoices WHERE customer_id=? AND status='PENDIENTE'",(id,)).fetchone()['s'] or 0)
    oldest=c.execute("SELECT MIN(due_date) d FROM invoices WHERE customer_id=? AND status='PENDIENTE'",(id,)).fetchone()['d']
    last_payment=c.execute('SELECT MAX(paid_at) p FROM payments WHERE customer_id=?',(id,)).fetchone()['p']
    c.close()

    active_names={cu['pppoe']} if active else set(); disabled={cu['pppoe']: str(secret['disabled'] or '').lower() in ('yes','true','1')} if secret and cu['pppoe'] else {}
    state, state_cls=_real_state(cu,active_names,disabled)
    due=oldest or _due_date_for(cu['due_day']).isoformat(); overdue=bool(oldest and oldest < date.today().isoformat() and debt>0)
    rx_mbps=(float(traffic['rx_bps'] or 0)/1_000_000) if traffic else 0.0
    tx_mbps=(float(traffic['tx_bps'] or 0)/1_000_000) if traffic else 0.0
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
    service_action='REACTIVATE' if (cu['status'] or '').upper()=='SUSPENDIDO' else 'SUSPEND'
    service_label='Reactivar' if service_action=='REACTIVATE' else 'Suspender'
    wa_btn=f'<a class="btn" style="border-color:#168a57;color:#70ebb0" target="_blank" href="https://wa.me/{wa}">WhatsApp</a>' if wa else ''

    body=f'''<style>.profile-kpis{{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}}.mini{{background:#0d1a29;border:1px solid #22374e;border-radius:11px;padding:13px}}.mini small{{display:block;color:#89a0b7;text-transform:uppercase;font-weight:800;font-size:10px}}.mini b{{display:block;font-size:19px;margin-top:5px}}.actionline{{display:flex;gap:7px;flex-wrap:wrap;align-items:center}}.split2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}@media(max-width:1000px){{.profile-kpis{{grid-template-columns:repeat(2,1fr)}}.split2{{grid-template-columns:1fr}}}}</style>
    <div class="head"><div><h1>{esc(cu['name'])}</h1><p>{esc(cu['code'])} · {esc(cu['pppoe'] or 'Sin PPPoE')} · {esc(cu['zone_name'] or cu['zone'] or 'Sin zona')}</p></div><div class="actionline"><a class="btn" href="{url_for('customers')}">← Clientes</a>{wa_btn}<a class="btn blue" href="{url_for('customer_edit',id=id)}">Editar</a></div></div>
    <div class="profile-kpis"><div class="mini"><small>PPPoE real</small><b><span class="tag {state_cls}">{esc(state)}</span></b><span class="muted">{esc(active['address'] if active else cu['ip_address'] or '-')}</span></div><div class="mini"><small>Deuda</small><b style="color:{'#ff7b86' if debt else '#57e6a0'}">RD${debt:,.0f}</b><span class="muted">{'Vencida' if overdue else 'Pendiente' if debt else 'Al día'}</span></div><div class="mini"><small>Vencimiento</small><b>{esc(due)}</b><span class="muted">Día {esc(cu['due_day'])}</span></div><div class="mini"><small>Último pago</small><b>{esc((last_payment or '-')[:10])}</b><span class="muted">{esc(cu['plan_name'] or '-')}</span></div><div class="mini"><small>ONU / ONT</small><b><span class="tag {onu_cls}">{esc(onu_state)}</span></b><span class="muted">RX {esc(onu_latest['rx_power'] if onu_latest else '-')}</span></div></div>
    <div class="panel"><div class="actionline"><form method="post" action="{url_for('customer_service_action',id=id,action=service_action)}"><button class="btn {'green' if service_action=='REACTIVATE' else ''}" onclick="return confirm('¿{service_label} este cliente?')">{service_label}</button></form><form method="post" action="{url_for('restart_pppoe',id=id)}"><button class="btn" onclick="return confirm('¿Reiniciar la sesión PPPoE de este cliente?')">Reiniciar PPPoE</button></form><a class="btn" href="{url_for('promise_new',customer_id=id)}">Promesa de pago</a><a class="btn" href="{url_for('customer_service_info',id=id)}">Servicio / mapa</a></div></div>
    <div class="split2"><div class="panel"><h3>Cambiar plan / perfil</h3><form method="post" action="{url_for('change_customer_plan',id=id)}" class="formgrid"><label>Plan comercial<select name="plan_id"><option value="">Sin plan</option>{plan_opts}</select></label><label>Perfil MikroTik<select name="mikrotik_profile"><option value="">Sin cambiar perfil</option>{prof_opts}</select></label><div class="full"><button class="btn blue">Guardar cambio</button></div></form></div>
    <div class="panel"><h3>Consumo / sesión PPPoE</h3><div class="profile-kpis" style="grid-template-columns:repeat(2,1fr)"><div class="mini"><small>Descarga actual</small><b>{rx_mbps:.2f} Mbps</b><span class="muted">{esc(traffic['interface_name'] if traffic else 'Sin contador sincronizado')}</span></div><div class="mini"><small>Subida actual</small><b>{tx_mbps:.2f} Mbps</b><span class="muted">Uptime {esc(active['uptime'] if active else '-')}</span></div></div></div></div>
    <div class="panel"><h3>ONU / ONT</h3><table class="table"><tr><th>Equipo</th><th>Serial</th><th>OLT / PON</th><th>RX</th><th>TX</th><th>Estado</th><th>Última lectura</th></tr>{onur}</table></div>
    <div class="split2"><div class="panel"><h3>Facturas</h3><table class="table"><tr><th>#</th><th>Concepto</th><th>Monto</th><th>Vence</th><th>Estado</th></tr>{invr}</table></div><div class="panel"><h3>Pagos</h3><table class="table"><tr><th>Fecha</th><th>Monto</th><th>Método</th><th>Ref.</th></tr>{payr}</table></div></div>
    <div class="split2"><div class="panel"><h3>Historial de acciones</h3><table class="table"><tr><th>Fecha</th><th>Acción</th><th>Quién</th><th>Detalle</th></tr>{evr}</table></div><div class="panel"><h3>Comandos MikroTik</h3><table class="table"><tr><th>Fecha</th><th>Acción</th><th>Estado</th><th>Resultado</th></tr>{cmdr}</table></div></div>'''
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
    overdue=c.execute("SELECT COUNT(DISTINCT customer_id) c FROM invoices WHERE status='PENDIENTE' AND due_date<?",(today,)).fetchone()['c']
    overdue_money=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM invoices WHERE status='PENDIENTE' AND due_date<?",(today,)).fetchone()['s'] or 0)
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
    recent=c.execute('''SELECT cu.name,i.amount,i.status,i.due_date FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' ORDER BY i.id DESC LIMIT 8''').fetchall()
    c.close()
    kpis=[('Clientes',total,f'{online_ppp} PPPoE online','blue1'),('Suspendidos',suspended,'Fuera de servicio','orange1'),('Morosos',overdue,f'RD${overdue_money:,.0f} vencido','red1'),('ONU caídas',onu_down,'OFFLINE / LOS','purple1'),('Órdenes MikroTik',pending_cmd,'Pendientes / proceso','cyan1'),('Papelera',trash,'Clientes eliminados','green1')]
    cards=''.join(f'<div class="kpi {cls}"><div class="label">{a}</div><div class="value">{b}</div><div class="sub">{d}</div></div>' for a,b,d,cls in kpis)
    alerts=[]
    if overdue: alerts.append(('bad',f'{overdue} clientes con facturas vencidas',url_for('invoices')))
    if suspended: alerts.append(('warn',f'{suspended} clientes suspendidos',url_for('customers')))
    if onu_down: alerts.append(('bad',f'{onu_down} ONU/ONT caídas o en LOS',url_for('onu_overview')))
    if pending_cmd: alerts.append(('warn',f'{pending_cmd} órdenes pendientes para MikroTik',url_for('mikrotik_commands')))
    if wan_issues: alerts.append(('bad',f'WAN sin lectura reciente: {", ".join(wan_issues[:4])}',url_for('routers')))
    if router_bad: alerts.append(('bad',f'{router_bad} router/agente no está ONLINE',url_for('routers')))
    if not wan_rows: alerts.append(('warn','Todavía no hay lecturas WAN en el monitor',url_for('routers')))
    alert_html=''.join(f'<a href="{u}" style="display:block;padding:11px 12px;margin:7px 0;border-radius:9px;background:{"#4a161b" if cls=="bad" else "#4e3707"};color:{"#fecaca" if cls=="bad" else "#ffe6a3"}">{esc(txt)}</a>' for cls,txt,u in alerts) or '<div style="padding:12px;border-radius:9px;background:#063f2a;color:#b8f6d6">Sin alertas operativas importantes.</div>'
    rows=''.join(f'<tr><td>{esc(r["name"])}</td><td>RD${float(r["amount"]):,.2f}</td><td>{esc(r["due_date"])}</td><td><span class="tag {"ok" if r["status"]=="PAGADA" else "warn"}">{esc(r["status"])}</span></td></tr>' for r in recent)
    body=f'''<div class="head"><div><h1>Dashboard</h1><p>Operación diaria de INTER Flash</p></div><div style="display:flex;gap:8px"><a class="btn" href="{url_for('onu_overview')}">ONU / ONT</a><a class="btn green" href="{url_for('customer_new')}">+ Nuevo cliente</a></div></div><div class="grid6">{cards}</div><div class="cards2"><div class="panel"><h3>Alertas operativas</h3>{alert_html}</div><div class="panel"><h3>Accesos rápidos</h3><p><a class="btn" href="{url_for('customers')}">Clientes</a></p><p><a class="btn" href="{url_for('mikrotik_commands')}">Cola MikroTik</a></p><p><a class="btn" href="{url_for('customer_trash')}">Papelera</a></p></div></div><div class="panel"><h3>Facturas recientes</h3><table class="table"><tr><th>Cliente</th><th>Monto</th><th>Vence</th><th>Estado</th></tr>{rows or '<tr><td colspan="4" class="muted">Sin facturas.</td></tr>'}</table></div>'''
    return base.shell('Dashboard',body,'dashboard')


def setup(app):
    ensure_schema()
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
