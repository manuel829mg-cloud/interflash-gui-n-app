import csv
import io
import unicodedata
from flask import request, redirect, url_for, Response
from app import con, auth, shell, e


def _norm(value):
    text = str(value or '').strip().lower()
    return ''.join(
        ch for ch in unicodedata.normalize('NFD', text)
        if unicodedata.category(ch) != 'Mn'
    )


def clients_sync_view():
    if not auth():
        return redirect(url_for('login'))

    raw_q = (request.args.get('q') or '').strip()
    state = (request.args.get('state') or 'TODOS').upper()

    c = con()
    try:
        rows = c.execute('''
            SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                   a.address AS active_address,a.caller_id AS active_caller,a.uptime,
                   cl.name AS customer_name,cl.phone AS customer_phone
            FROM router_pppoe_secrets s
            LEFT JOIN router_pppoe_active a
              ON a.router_name=s.router_name AND a.name=s.name
            LEFT JOIN clients cl
              ON LOWER(TRIM(cl.pppoe))=LOWER(TRIM(s.name))
            ORDER BY COALESCE(NULLIF(cl.name,''),s.name) COLLATE NOCASE
        ''').fetchall()
    except Exception:
        try:
            rows = c.execute('''
                SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                       a.address AS active_address,a.caller_id AS active_caller,a.uptime,
                       NULL AS customer_name,NULL AS customer_phone
                FROM router_pppoe_secrets s
                LEFT JOIN router_pppoe_active a
                  ON a.router_name=s.router_name AND a.name=s.name
                ORDER BY s.name COLLATE NOCASE
            ''').fetchall()
        except Exception:
            rows = []
    c.close()

    rendered = []
    total = online = suspended = visible_by_state = 0

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

        if state != 'TODOS' and status != state:
            continue

        ip = r['active_address'] or r['remote_address'] or '-'
        caller = r['active_caller'] or r['caller_id'] or '-'
        profile = r['profile'] or '-'
        service = r['service'] or '-'
        router = r['router_name'] or 'CCR2116'
        pppoe = r['name'] or ''
        customer_name = r['customer_name'] or ''
        customer_phone = r['customer_phone'] or ''
        visible_by_state += 1

        display_name = customer_name or pppoe
        secondary = []
        if customer_name and _norm(customer_name) != _norm(pppoe):
            secondary.append(f'PPPoE: {e(pppoe)}')
        if customer_phone:
            secondary.append(e(customer_phone))
        if not secondary:
            secondary.append(e(profile))
        subline = ' · '.join(secondary)

        search_text = _norm(' '.join(str(x or '') for x in (
            customer_name, customer_phone, pppoe, ip, profile,
            caller, router, service, status
        )))

        rendered.append(f'''
        <tr class="client-row" data-search="{e(search_text)}">
          <td><input type="checkbox"></td>
          <td><b style="font-size:16px">{e(display_name)}</b><br><small>{subline}</small></td>
          <td>—</td>
          <td><a href="{url_for('agent_pppoe_view', name=router)}" style="color:#246bb3;font-weight:700">{e(ip)}</a><br><small>{e(router)}</small></td>
          <td><span class="tag {cls}">{status}</span></td>
          <td>{e(caller)}<br><small>{e(profile)} · {e(service)}</small></td>
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
      <form method="get" id="client-search-form" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
        <input id="client-search" name="q" value="{e(raw_q)}" autocomplete="off"
          placeholder="Empieza a escribir el nombre del cliente..."
          style="min-width:320px;flex:1;padding:11px;border:1px solid #d7dde5;border-radius:8px">
        <select id="client-state" name="state" style="padding:11px;border:1px solid #d7dde5;border-radius:8px">{options}</select>
        <a class="btn" href="{url_for('clients')}">Limpiar</a>
      </form>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">
        <span class="tag">Total: {total}</span>
        <span class="tag ok">Online: {online}</span>
        <span class="tag bad">Suspendidos: {suspended}</span>
        <span class="tag" id="client-results">Resultados: {visible_by_state}</span>
      </div>
      <table>
        <tr><th></th><th>Cliente / PPPoE</th><th>F. Inst.</th><th>IP / Router</th><th>Estado</th><th>MAC / Perfil</th><th>Acción</th></tr>
        {''.join(rendered) if rendered else '<tr><td colspan="7" class="empty">No hay clientes.</td></tr>'}
        <tr id="client-no-results" style="display:none"><td colspan="7" class="empty">No hay clientes que coincidan con la búsqueda.</td></tr>
      </table>
    </div>
    <script>
      (function(){{
        const q=document.getElementById('client-search');
        const rows=[...document.querySelectorAll('.client-row')];
        const result=document.getElementById('client-results');
        const empty=document.getElementById('client-no-results');
        const state=document.getElementById('client-state');

        function normalizeText(v){{
          return (v||'').toString().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase().trim();
        }}

        function filterClients(){{
          const words=normalizeText(q.value).split(/\\s+/).filter(Boolean);
          let shown=0;
          rows.forEach(row=>{{
            const hay=normalizeText(row.dataset.search||'');
            const ok=words.every(w=>hay.includes(w));
            row.style.display=ok?'':'none';
            if(ok) shown++;
          }});
          if(result) result.textContent='Resultados: '+shown;
          if(empty) empty.style.display=shown===0?'':'none';
        }}

        if(q){{
          q.focus();
          q.addEventListener('input',filterClients);
          q.addEventListener('keydown',function(ev){{
            if(ev.key==='Escape'){{ q.value=''; filterClients(); }}
          }});
          filterClients();
        }}

        if(state){{
          state.addEventListener('change',function(){{
            const u=new URL(window.location.href);
            u.searchParams.set('state',state.value);
            u.searchParams.delete('q');
            window.location=u.toString();
          }});
        }}
      }})();
    </script>
    '''
    return shell('Clientes', body, 'clients')


def clients_sync_export():
    if not auth():
        return redirect(url_for('login'))
    c = con()
    try:
        rows = c.execute('''
            SELECT s.router_name,s.name,s.profile,s.service,s.remote_address,s.caller_id,s.disabled,
                   a.address AS active_address,a.caller_id AS active_caller,
                   cl.name AS customer_name,cl.phone AS customer_phone
            FROM router_pppoe_secrets s
            LEFT JOIN router_pppoe_active a
              ON a.router_name=s.router_name AND a.name=s.name
            LEFT JOIN clients cl
              ON LOWER(TRIM(cl.pppoe))=LOWER(TRIM(s.name))
            ORDER BY COALESCE(NULLIF(cl.name,''),s.name) COLLATE NOCASE
        ''').fetchall()
    except Exception:
        rows = []
    c.close()

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Cliente','Teléfono','Usuario PPPoE','Perfil','IP','Router','Estado','Caller ID','Servicio'])
    for r in rows:
        disabled = str(r['disabled'] or '').lower() in ('true','yes','1')
        if disabled:
            status = 'SUSPENDIDO'
        elif r['active_address']:
            status = 'ONLINE'
        else:
            status = 'OFFLINE'
        w.writerow([
            r['customer_name'] or '', r['customer_phone'] or '', r['name'] or '', r['profile'] or '',
            r['active_address'] or r['remote_address'] or '', r['router_name'] or '', status,
            r['active_caller'] or r['caller_id'] or '', r['service'] or ''
        ])
    data = '\ufeff' + out.getvalue()
    return Response(data, mimetype='text/csv; charset=utf-8', headers={
        'Content-Disposition':'attachment; filename=clientes-mikrotik.csv'
    })


def setup(app):
    app.view_functions['clients'] = clients_sync_view
    if 'clients_sync_export' not in app.view_functions:
        app.add_url_rule('/clients/export', endpoint='clients_sync_export', view_func=clients_sync_export, methods=['GET'])
