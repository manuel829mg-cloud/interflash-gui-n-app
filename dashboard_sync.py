from datetime import date
from flask import redirect, url_for
from app import con, auth, shell


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

    pending = c.execute("select count(*) c from invoices where status='PENDIENTE'").fetchone()['c']
    money = c.execute("select coalesce(sum(amount),0) s from invoices where status='PENDIENTE'").fetchone()['s']
    paid = c.execute("select coalesce(sum(amount),0) s from invoices where status='PAGADA'").fetchone()['s']
    manual_routers = c.execute('select count(*) c from routers').fetchone()['c']
    routers_n = sync_routers if sync_routers > 0 else manual_routers
    tickets = c.execute("select count(*) c from tickets where status!='CERRADO'").fetchone()['c']

    today = date.today().isoformat()
    try:
        paid_today_row = c.execute("select count(*) c, coalesce(sum(amount),0) s from invoices where status='PAGADA' and paid_at=?", (today,)).fetchone()
        paid_today_count = paid_today_row['c']
        paid_today = paid_today_row['s']
    except Exception:
        paid_today_count = 0
        paid_today = 0

    try:
        due_today = c.execute("select count(*) c from invoices where status='PENDIENTE' and due_date=?", (today,)).fetchone()['c']
    except Exception:
        due_today = 0

    try:
        payment_reports = c.execute("select count(*) c from invoices where status='PAGADA' and paid_at is null").fetchone()['c']
    except Exception:
        payment_reports = 0

    c.close()

    cards = [
        ('CLIENTES TOTALES', total, 'Sincronizados' if sync_total > 0 else 'Registrados', '👥', 'bluebox', ''),
        ('CLIENTES ACTIVOS', active, 'En servicio', '↯', 'greenbox', ''),
        ('CLIENTES SUSPENDIDOS', suspended, 'Clientes cortados', '✖', 'redbox', ''),
        ('INSTALACIONES EN EL MES', 0, 'Sin canceladas', '▣', 'indigobox', ''),
        ('NUEVO CLIENTE', 'Crear', '', '+', 'tealbox', url_for('client_new')),
        ('ROUTERS', routers_n, 'Conectados' if routers_n else 'Sin conexión', '⌁', 'purplebox', url_for('routers')),
        ('REPORTE DE PAGOS', payment_reports, 'Sin reportes por revisar' if payment_reports == 0 else 'Por revisar', '▤', 'orangebox', url_for('payment_reports')),
        ('PROMESAS DE PAGO', 0, 'Sin solicitudes por revisar', '♢', 'royalbox', url_for('payment_promises')),
        ('TICKETS', tickets, f'{tickets} nuevos sin atender' if tickets else 'Ninguno', '◉', 'pinkbox', url_for('support_new')),
        ('VENCE HOY', due_today, 'Ninguna factura vence hoy' if due_today == 0 else 'Facturas por vencer', '▣', 'graybox', url_for('invoices')),
    ]

    card_html = []
    for label, value, sub, icon, icon_class, href in cards:
        inner = f'''<div class="video-kpi"><div><div class="vk-label">{label}</div><div class="vk-value">{value}</div><div class="vk-sub">{sub}</div></div><div class="vk-icon {icon_class}">{icon}</div></div>'''
        card_html.append(f'<a class="vk-link" href="{href}">{inner}</a>' if href else inner)

    body = f'''
    <style>
      .video-dash-grid{{display:grid;grid-template-columns:repeat(6,minmax(125px,1fr));gap:10px;margin-top:8px}}
      .video-kpi{{min-height:116px;background:#fff;border:1px solid #e6e9ee;border-radius:3px;padding:14px 13px;display:flex;justify-content:space-between;gap:8px;align-items:flex-start;box-shadow:0 1px 2px #00000008}}
      .vk-link{{display:block;color:inherit;text-decoration:none}}.vk-link .video-kpi:hover{{border-color:#cfd7df;box-shadow:0 2px 7px #00000010}}
      .vk-label{{font-size:10px;line-height:1.25;color:#6d747c;font-weight:800;letter-spacing:.03em;min-height:25px}}
      .vk-value{{font-size:21px;font-weight:900;color:#161a1f;margin-top:6px;line-height:1.05}}
      .vk-sub{{font-size:11px;color:#848c95;margin-top:6px;line-height:1.25}}
      .vk-icon{{width:30px;height:30px;border-radius:3px;display:grid;place-items:center;color:#fff;font-weight:900;flex:0 0 30px}}
      .bluebox{{background:#2f8fe8}}.greenbox{{background:#24bc76}}.redbox{{background:#ef5548}}.indigobox{{background:#516ddf}}.tealbox{{background:#32b69f}}.purplebox{{background:#8657c9}}.orangebox{{background:#ff8b25}}.royalbox{{background:#526de0}}.pinkbox{{background:#e73b66}}.graybox{{background:#5d6875}}
      .video-money{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}}
      .vm-card{{min-height:100px;color:white;border-radius:3px;padding:18px 19px;box-shadow:0 2px 5px #0002}}
      .vm-green{{background:linear-gradient(110deg,#18b95f,#0ba453)}}.vm-orange{{background:linear-gradient(110deg,#f28a16,#e54d27)}}.vm-blue{{background:linear-gradient(110deg,#1697d0,#1174b4)}}
      .vm-title{{font-size:12px;font-weight:700;opacity:.95}}.vm-value{{font-size:24px;font-weight:900;margin-top:7px}}.vm-sub{{font-size:11px;margin-top:4px;opacity:.9}}
      .dash-lower{{background:#fff;border:1px solid #e7eaee;border-radius:4px;padding:18px;margin-top:14px;min-height:115px}}
      .dash-lower h3{{margin:0 0 12px;font-size:15px}}.bars{{height:56px;display:flex;gap:8px;align-items:flex-end}}.bars span{{flex:1;background:#d9e8f5;border-radius:3px 3px 0 0;min-height:8px}}
      @media(max-width:1250px){{.video-dash-grid{{grid-template-columns:repeat(4,1fr)}}}}
      @media(max-width:850px){{.video-dash-grid{{grid-template-columns:repeat(2,1fr)}}.video-money{{grid-template-columns:1fr}}}}
      @media(max-width:520px){{.video-dash-grid{{grid-template-columns:1fr}}}}
    </style>
    <div class="head"><div><h1>Dashboard</h1><p>Estado actual de tu red</p></div></div>
    <div class="video-dash-grid">{''.join(card_html)}</div>
    <div class="video-money">
      <div class="vm-card vm-green"><div class="vm-title">Pagos hoy</div><div class="vm-value">RD${paid_today:,.2f}</div><div class="vm-sub">{paid_today_count} facturas cobradas</div></div>
      <div class="vm-card vm-orange"><div class="vm-title">Por cobrar</div><div class="vm-value">RD${money:,.2f}</div><div class="vm-sub">{pending} facturas pendientes</div></div>
      <div class="vm-card vm-blue"><div class="vm-title">Ingresos registrados</div><div class="vm-value">RD${paid:,.2f}</div><div class="vm-sub">Total cobrado registrado</div></div>
    </div>
    <div class="dash-lower"><h3>Cobros últimos 12 meses</h3><div class="bars"><span style="height:24%"></span><span style="height:35%"></span><span style="height:28%"></span><span style="height:48%"></span><span style="height:40%"></span><span style="height:57%"></span><span style="height:50%"></span><span style="height:66%"></span><span style="height:61%"></span><span style="height:73%"></span><span style="height:69%"></span><span style="height:82%"></span></div></div>
    '''
    return shell('Dashboard', body, 'dashboard')


def setup(app):
    app.view_functions['dashboard'] = dashboard_sync
