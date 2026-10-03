from datetime import date
from flask import redirect, url_for
from app import con, auth, shell, e


def dashboard_sync():
    if not auth():
        return redirect(url_for('login'))

    c = con()
    manual_total = c.execute('select count(*) c from clients').fetchone()['c']
    manual_active = c.execute("select count(*) c from clients where status='ACTIVO'").fetchone()['c']
    manual_suspended = c.execute("select count(*) c from clients where status='SUSPENDIDO'").fetchone()['c']

    try:
        sync_total = c.execute('select count(distinct name) c from router_pppoe_secrets').fetchone()['c']
        sync_active = c.execute('select count(distinct name) c from router_pppoe_active').fetchone()['c']
        sync_suspended = c.execute("select count(distinct name) c from router_pppoe_secrets where lower(coalesce(disabled,'')) in ('true','yes','1')").fetchone()['c']
        sync_routers = c.execute('select count(*) c from router_agents').fetchone()['c']
    except Exception:
        sync_total = sync_active = sync_suspended = sync_routers = 0

    total = sync_total if sync_total > 0 else manual_total
    active = sync_active if sync_total > 0 else manual_active
    suspended = sync_suspended if sync_total > 0 else manual_suspended
    offline = max(total - active - suspended, 0)

    pending = c.execute("select count(*) c from invoices where status='PENDIENTE'").fetchone()['c']
    money = c.execute("select coalesce(sum(amount),0) s from invoices where status='PENDIENTE'").fetchone()['s']
    paid = c.execute("select coalesce(sum(amount),0) s from invoices where status='PAGADA'").fetchone()['s']
    manual_routers = c.execute('select count(*) c from routers').fetchone()['c']
    routers_n = sync_routers if sync_routers > 0 else manual_routers

    today = date.today().isoformat()
    try:
        paid_today_row = c.execute("select count(*) c, coalesce(sum(amount),0) s from invoices where status='PAGADA' and paid_at=?", (today,)).fetchone()
        paid_today_count = paid_today_row['c']
        paid_today = paid_today_row['s']
    except Exception:
        paid_today_count = 0
        paid_today = 0

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
            ORDER BY CASE WHEN a.address IS NOT NULL THEN 0 ELSE 1 END,
                     COALESCE(NULLIF(cl.name,''),s.name) COLLATE NOCASE
            LIMIT 10
        ''').fetchall()
    except Exception:
        rows = []

    c.close()

    pct_active = round((active / total * 100), 1) if total else 0
    pct_suspended = round((suspended / total * 100), 1) if total else 0
    pct_offline = round((offline / total * 100), 1) if total else 0

    client_rows = []
    for i, r in enumerate(rows, 1):
        disabled = str(r['disabled'] or '').lower() in ('true','yes','1')
        online = bool(r['active_address']) and not disabled
        if disabled:
            status, cls = 'Suspendido', 'suspended'
        elif online:
            status, cls = 'Activo', 'active'
        else:
            status, cls = 'Offline', 'offline'
        name = r['customer_name'] or r['name'] or '-'
        phone = r['customer_phone'] or r['name'] or ''
        ip = r['active_address'] or r['remote_address'] or '-'
        router = r['router_name'] or 'CCR2116'
        profile = r['profile'] or '-'
        edit_url = url_for('client_video_edit', pppoe=r['name']) if r['name'] else '#'
        client_rows.append(f'''
        <tr>
          <td>{i}</td>
          <td><div class="client-name"><span class="avatar">👤</span><div><b>{e(name)}</b><small>{e(phone)}</small></div></div></td>
          <td>{e(profile)}</td>
          <td><b>{e(ip)}</b></td>
          <td>{e(router)}</td>
          <td><span class="state {cls}">{status}</span></td>
          <td><div class="actionset"><a href="{edit_url}" title="Ver cliente">◉</a><a href="{edit_url}" title="Editar">✎</a><span>•••</span></div></td>
        </tr>''')

    body = f'''
    <style>
      .modern-wrap{{max-width:1600px;margin:0 auto}}
      .kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
      .kpi{{position:relative;overflow:hidden;border-radius:9px;padding:15px 14px;color:#fff;min-height:100px;box-shadow:0 12px 28px #0003}}
      .kpi:after{{content:'';position:absolute;width:70px;height:70px;border-radius:50%;right:-16px;bottom:-18px;background:#ffffff18}}
      .kpi .title{{font-size:12px;font-weight:800;opacity:.92}}.kpi .value{{font-size:25px;font-weight:900;margin-top:7px}}.kpi .sub{{font-size:10px;margin-top:5px;opacity:.9}}
      .k1{{background:linear-gradient(135deg,#1462ef,#157eff)}}.k2{{background:linear-gradient(135deg,#05ad62,#0bd486)}}.k3{{background:linear-gradient(135deg,#f38a14,#ffad20)}}.k4{{background:linear-gradient(135deg,#5a16d9,#9238ff)}}.k5{{background:linear-gradient(135deg,#e83d52,#ff5b69)}}.k6{{background:linear-gradient(135deg,#0997ae,#14c9d6)}}
      .chart-grid{{display:grid;grid-template-columns:1.15fr .82fr .82fr;gap:10px;margin-top:11px}}
      .dashbox{{background:linear-gradient(180deg,#101d2e,#0c1725);border:1px solid #21344c;border-radius:10px;padding:14px;min-height:210px;box-shadow:0 12px 28px #0002}}
      .boxtitle{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}}.boxtitle b{{font-size:14px;color:#eef6ff}}.boxtitle span{{font-size:10px;color:#6e879f}}
      .income{{font-size:27px;font-weight:900;color:#fff;margin:3px 0 8px}}.income small{{font-size:10px;color:#4de5a2}}
      .linechart{{height:105px;position:relative;border-left:1px solid #263a52;border-bottom:1px solid #263a52;background:repeating-linear-gradient(to top,transparent 0,transparent 25px,#1e314622 26px)}}
      .linechart svg{{position:absolute;inset:0;width:100%;height:100%}}
      .donut-wrap{{display:flex;align-items:center;justify-content:center;gap:18px;height:150px}}.donut{{width:126px;height:126px;border-radius:50%;background:conic-gradient(#0bd486 0 {pct_active}%,#ff9f1a {pct_active}% {min(100,pct_active+pct_suspended)}%,#526a83 {min(100,pct_active+pct_suspended)}% 100%);display:grid;place-items:center;box-shadow:inset 0 0 0 24px #101d2e}}.donut div{{text-align:center;font-weight:900;font-size:20px}}.donut small{{display:block;font-size:10px;color:#8499ae;font-weight:500}}
      .legend{{font-size:11px;color:#a7b8ca;line-height:2}}.dot{{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px}}.gdot{{background:#0bd486}}.odot{{background:#ff9f1a}}.bdot{{background:#526a83}}
      .bars2{{height:150px;display:flex;gap:14px;align-items:flex-end;padding:8px 5px 22px}}.baritem{{flex:1;text-align:center;font-size:10px;color:#8298ae}}.bar{{width:100%;border-radius:5px 5px 0 0;background:linear-gradient(180deg,#1d87ff,#0b5bd7);min-height:16px;margin-bottom:5px}}
      .bottom-grid{{display:grid;grid-template-columns:1fr 320px;gap:10px;margin-top:11px}}
      .client-box{{background:linear-gradient(180deg,#101d2e,#0c1725);border:1px solid #21344c;border-radius:10px;overflow:hidden}}.client-head{{display:flex;align-items:center;justify-content:space-between;padding:14px 15px;border-bottom:1px solid #1d3046}}.client-head h3{{margin:0;font-size:15px}}.client-buttons{{display:flex;gap:6px}}.mini{{padding:7px 10px;border-radius:6px;border:1px solid #2a405a;background:#14253a;color:#cfe0f1;font-size:11px;font-weight:800}}.mini.greenbtn{{background:#08b96d;border-color:#08b96d;color:#fff}}
      .filterbar{{display:grid;grid-template-columns:1.4fr .7fr .7fr;gap:8px;padding:10px 14px}}.filterbar input,.filterbar select{{height:36px;border-radius:6px;padding:0 10px}}
      .client-table{{width:100%;border-collapse:collapse}}.client-table th{{font-size:10px;text-transform:none;padding:9px 10px;color:#7891aa;background:#0b1725}}.client-table td{{font-size:11px;padding:8px 10px;border-bottom:1px solid #1a2c40}}.client-table tr:hover td{{background:#112238}}.client-name{{display:flex;align-items:center;gap:7px}}.client-name b{{display:block;font-size:11px}}.client-name small{{display:block;font-size:9px;color:#7088a0;margin-top:2px}}.avatar{{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;background:#163454;font-size:12px}}.state{{display:inline-block;min-width:65px;text-align:center;padding:4px 7px;border-radius:5px;font-size:9px;font-weight:900}}.state.active{{background:#08b96d;color:#fff}}.state.suspended{{background:#ef8b12;color:#fff}}.state.offline{{background:#526176;color:#fff}}.actionset{{display:flex;gap:4px}}.actionset a,.actionset span{{width:24px;height:24px;border-radius:5px;display:grid;place-items:center;background:#142842;border:1px solid #29445f;color:#9cc3eb;font-size:10px}}.actionset a:nth-child(2){{background:#176dff;color:#fff}}
      .rightcol{{display:flex;flex-direction:column;gap:10px}}.sidebox{{background:linear-gradient(180deg,#101d2e,#0c1725);border:1px solid #21344c;border-radius:10px;padding:14px}}.sidebox h3{{font-size:14px;margin:0 0 12px}}.activity{{display:flex;gap:9px;padding:8px 0;border-bottom:1px solid #1b2c40;font-size:10px}}.activity:last-child{{border-bottom:0}}.activity .bubble{{width:27px;height:27px;border-radius:50%;display:grid;place-items:center;background:#0e7b55;flex:0 0 27px}}.activity b{{display:block;font-size:10px}}.activity small{{font-size:9px;color:#71879d}}
      .sysrow{{display:flex;justify-content:space-between;gap:10px;margin-top:10px;padding-top:10px;border-top:1px solid #1d3046;font-size:10px;color:#8ba0b6}}.online-dot{{color:#21df8d}}
      @media(max-width:1250px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.chart-grid{{grid-template-columns:1fr 1fr}}.chart-grid .dashbox:last-child{{grid-column:1/-1}}.bottom-grid{{grid-template-columns:1fr}}}}
      @media(max-width:760px){{.kpis{{grid-template-columns:1fr 1fr}}.chart-grid{{grid-template-columns:1fr}}.chart-grid .dashbox:last-child{{grid-column:auto}}.filterbar{{grid-template-columns:1fr}}.client-table{{min-width:760px}}.client-box{{overflow:auto}}}}
    </style>
    <div class="modern-wrap">
      <div class="kpis">
        <div class="kpi k1"><div class="title">Clientes Totales</div><div class="value">{total}</div><div class="sub">PPPoE registrados</div></div>
        <div class="kpi k2"><div class="title">Clientes Activos</div><div class="value">{active}</div><div class="sub">{pct_active}% del total</div></div>
        <div class="kpi k3"><div class="title">Clientes Suspendidos</div><div class="value">{suspended}</div><div class="sub">{pct_suspended}% del total</div></div>
        <div class="kpi k4"><div class="title">Pagos Registrados</div><div class="value">RD${paid:,.0f}</div><div class="sub">Hoy RD${paid_today:,.0f}</div></div>
        <div class="kpi k5"><div class="title">Facturas Pendientes</div><div class="value">{pending}</div><div class="sub">RD${money:,.0f} por cobrar</div></div>
        <div class="kpi k6"><div class="title">Routers Activos</div><div class="value">{routers_n}</div><div class="sub">MikroTik sincronizado</div></div>
      </div>

      <div class="chart-grid">
        <div class="dashbox"><div class="boxtitle"><b>Ingresos Mensuales</b><span>2026</span></div><div class="income">RD${paid:,.2f} <small>↑ registrado</small></div><div class="linechart"><svg viewBox="0 0 500 100" preserveAspectRatio="none"><defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14da8a" stop-opacity=".4"/><stop offset="1" stop-color="#14da8a" stop-opacity="0"/></linearGradient></defs><polygon points="0,80 45,70 90,56 135,63 180,50 225,53 270,42 315,47 360,33 405,36 450,27 500,24 500,100 0,100" fill="url(#lg)"/><polyline points="0,80 45,70 90,56 135,63 180,50 225,53 270,42 315,47 360,33 405,36 450,27 500,24" fill="none" stroke="#20e39a" stroke-width="3"/></svg></div></div>
        <div class="dashbox"><div class="boxtitle"><b>Estado de Clientes</b><span>En vivo</span></div><div class="donut-wrap"><div class="donut"><div>{total}<small>Clientes</small></div></div><div class="legend"><div><span class="dot gdot"></span>Activos {active} ({pct_active}%)</div><div><span class="dot odot"></span>Suspendidos {suspended} ({pct_suspended}%)</div><div><span class="dot bdot"></span>Offline {offline} ({pct_offline}%)</div></div></div></div>
        <div class="dashbox"><div class="boxtitle"><b>Distribución por Planes</b><span>Perfiles PPPoE</span></div><div class="bars2"><div class="baritem"><div class="bar" style="height:88px"></div>30M</div><div class="baritem"><div class="bar" style="height:68px;background:linear-gradient(#8258ff,#5a37d5)"></div>50M</div><div class="baritem"><div class="bar" style="height:52px;background:linear-gradient(#27d2ae,#0d9b85)"></div>100M</div><div class="baritem"><div class="bar" style="height:36px;background:linear-gradient(#ff7a4a,#e94d2e)"></div>200M</div><div class="baritem"><div class="bar" style="height:28px;background:linear-gradient(#ff5971,#dd304d)"></div>300M</div></div></div>
      </div>

      <div class="bottom-grid">
        <div class="client-box"><div class="client-head"><h3>👥 Lista de Clientes</h3><div class="client-buttons"><a class="mini greenbtn" href="{url_for('client_new')}">＋ Nuevo Cliente</a><a class="mini" href="{url_for('clients_sync_export')}">Exportar</a></div></div><div class="filterbar"><input id="dash-search" placeholder="Buscar por nombre, usuario PPPoE, IP..."><select><option>Todos los estados</option><option>Activos</option><option>Suspendidos</option></select><select><option>Todos los planes</option></select></div><div style="overflow:auto"><table class="client-table"><thead><tr><th>#</th><th>Cliente</th><th>Plan</th><th>IP Asignada</th><th>Router</th><th>Estado</th><th>Acciones</th></tr></thead><tbody id="dash-client-body">{''.join(client_rows) if client_rows else '<tr><td colspan="7" class="empty">No hay clientes sincronizados todavía.</td></tr>'}</tbody></table></div></div>
        <div class="rightcol"><div class="sidebox"><h3>Actividad Reciente</h3><div class="activity"><span class="bubble">$</span><div><b>Pagos registrados</b><small>{paid_today_count} pagos hoy</small></div></div><div class="activity"><span class="bubble" style="background:#176dff">👥</span><div><b>Clientes sincronizados</b><small>{total} usuarios PPPoE</small></div></div><div class="activity"><span class="bubble" style="background:#ef8b12">Ⅱ</span><div><b>Clientes suspendidos</b><small>{suspended} deshabilitados</small></div></div><div class="activity"><span class="bubble" style="background:#0f9eb3">⌁</span><div><b>Routers</b><small>{routers_n} agentes conectados</small></div></div></div><div class="sidebox"><h3>Información del Sistema</h3><div><b><span class="online-dot">●</span> MikroTik / INTER Flash</b><small style="display:block;margin-top:4px">Sincronización de lectura activa</small></div><div class="sysrow"><span>PPPoE en línea<br><b style="color:#fff">{active}/{total}</b></span><span>Offline<br><b style="color:#fff">{offline}</b></span><span>Por cobrar<br><b style="color:#fff">{pending}</b></span></div></div></div>
      </div>
    </div>
    <script>
      (function(){{
        const q=document.getElementById('dash-search');
        if(!q)return;
        q.addEventListener('input',function(){{
          const v=this.value.toLowerCase().trim();
          document.querySelectorAll('#dash-client-body tr').forEach(r=>{{r.style.display=!v||r.innerText.toLowerCase().includes(v)?'':'none';}});
        }});
      }})();
    </script>
    '''
    return shell('Dashboard', body, 'dashboard')


def setup(app):
    app.view_functions['dashboard'] = dashboard_sync
