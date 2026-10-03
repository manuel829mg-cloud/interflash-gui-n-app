import csv
import io
from flask import request, redirect, url_for, Response
from app import con, auth, shell, e


def clients_sync_view():
    if not auth():
        return redirect(url_for('login'))

    q = (request.args.get('q') or '').strip().lower()
    state = (request.args.get('state') or 'TODOS').upper()

    c = con()
    try:
        rows = c.execute('''
            SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                   a.address AS active_address,a.caller_id AS active_caller,a.uptime
            FROM router_pppoe_secrets s
            LEFT JOIN router_pppoe_active a
              ON a.router_name=s.router_name AND a.name=s.name
            ORDER BY s.name COLLATE NOCASE
        ''').fetchall()
    except Exception:
        rows = []
    c.close()

    rendered = []
    total = online = suspended = 0
    for r in rows:
        total += 1
        disabled = str(r['disabled'] or '').lower() in ('true','yes','1')
        is_online = bool(r['active_address']) and not disabled
        if disabled:
            status = 'SUSPENDIDO'
            cls = 'bad'
            suspended += 1
        elif is_online:
            status = 'ONLINE'
            cls = 'ok'
            online += 1
        else:
            status = 'OFFLINE'
            cls = 'pending'

        ip = r['active_address'] or r['remote_address'] or '-'
        caller = r['active_caller'] or r['caller_id'] or '-'
        profile = r['profile'] or '-'
        service = r['service'] or '-'
        router = r['router_name'] or 'CCR2116'

        haystack = ' '.join(str(x or '') for x in (r['name'], ip, profile, caller, router)).lower()
        if q and q not in haystack:
            continue
        if state != 'TODOS' and status != state:
            continue

        rendered.append(f'''
        <tr>
          <td><input type="checkbox"></td>
          <td><b style="font-size:16px">{e(r['name'])}</b><br><small>{e(profile)}</small></td>
          <td>—</td>
          <td><a href="{url_for('agent_pppoe_view', name=router)}" style="color:#246bb3;font-weight:700">{e(ip)}</a><br><small>{e(router)}</small></td>
          <td><span class="tag {cls}">{status}</span></td>
          <td>{e(caller)}<br><small>{e(service)}</small></td>
          <td><a class="btn small" href="{url_for('agent_pppoe_view', name=router)}">Ver</a></td>
        </tr>''')

    options = ''.join(
        f'<option value="{x}" {"selected" if state==x else ""}>{x.title()}</option>'
        for x in ('TODOS','ONLINE','OFFLINE','SUSPENDIDO')
    )

    body = f'''
    <div class="head">
      <div><h1>Clientes</h1><p>Clientes PPPoE sincronizados desde MikroTik</p></div>
      <a class="btn" href="{url_for('clients_sync_export')}">Exportar CSV</a>
    </div>
    <div class="panel">
      <form method="get" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
        <input name="q" value="{e(request.args.get('q') or '')}" placeholder="Buscar nombre, IP, perfil o MAC" style="min-width:320px;flex:1;padding:11px;border:1px solid #d7dde5;border-radius:8px">
        <select name="state" style="padding:11px;border:1px solid #d7dde5;border-radius:8px">{options}</select>
        <button class="btn green" type="submit">Buscar</button>
        <a class="btn" href="{url_for('clients')}">Limpiar</a>
      </form>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">
        <span class="tag">Total: {total}</span>
        <span class="tag ok">Online: {online}</span>
        <span class="tag bad">Suspendidos: {suspended}</span>
      </div>
      <table>
        <tr><th></th><th>Nombre / Perfil</th><th>F. Inst.</th><th>IP / Router</th><th>Estado</th><th>Caller ID / Servicio</th><th>Acción</th></tr>
        {''.join(rendered) if rendered else '<tr><td colspan="7" class="empty">No hay clientes que coincidan con el filtro.</td></tr>'}
      </table>
    </div>
    '''
    return shell('Clientes', body, 'clients')


def clients_sync_export():
    if not auth():
        return redirect(url_for('login'))
    c = con()
    try:
        rows = c.execute('''
            SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                   a.address AS active_address,a.caller_id AS active_caller
            FROM router_pppoe_secrets s
            LEFT JOIN router_pppoe_active a
              ON a.router_name=s.router_name AND a.name=s.name
            ORDER BY s.name COLLATE NOCASE
        ''').fetchall()
    except Exception:
        rows = []
    c.close()

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Usuario','Perfil','IP','Router','Estado','Caller ID','Servicio'])
    for r in rows:
        disabled = str(r['disabled'] or '').lower() in ('true','yes','1')
        if disabled:
            status = 'SUSPENDIDO'
        elif r['active_address']:
            status = 'ONLINE'
        else:
            status = 'OFFLINE'
        w.writerow([
            r['name'] or '', r['profile'] or '', r['active_address'] or r['remote_address'] or '',
            r['router_name'] or '', status, r['active_caller'] or r['caller_id'] or '', r['service'] or ''
        ])
    data = '\ufeff' + out.getvalue()
    return Response(data, mimetype='text/csv; charset=utf-8', headers={
        'Content-Disposition':'attachment; filename=clientes-mikrotik.csv'
    })


def setup(app):
    app.view_functions['clients'] = clients_sync_view
    app.add_url_rule('/clients/export', endpoint='clients_sync_export', view_func=clients_sync_export, methods=['GET'])
