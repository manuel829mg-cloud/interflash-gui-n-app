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

    if sync_total > 0:
        total = sync_total
        active = sync_active
        suspended = sync_suspended
    else:
        total = manual_total
        active = manual_active
        suspended = manual_suspended

    pending = c.execute("select count(*) c from invoices where status='PENDIENTE'").fetchone()['c']
    money = c.execute("select coalesce(sum(amount),0) s from invoices where status='PENDIENTE'").fetchone()['s']
    paid = c.execute("select coalesce(sum(amount),0) s from invoices where status='PAGADA'").fetchone()['s']
    manual_routers = c.execute('select count(*) c from routers').fetchone()['c']
    routers_n = sync_routers if sync_routers > 0 else manual_routers
    tickets = c.execute("select count(*) c from tickets where status!='CERRADO'").fetchone()['c']
    c.close()

    items = [
        ('Clientes totales', total, 'Sincronizados desde MikroTik' if sync_total > 0 else 'Registrados'),
        ('Clientes activos', active, 'PPPoE conectados' if sync_total > 0 else 'En servicio'),
        ('Clientes suspendidos', suspended, 'PPPoE deshabilitados' if sync_total > 0 else 'Cortados'),
        ('Instalaciones en el mes', 0, 'Sin canceladas'),
        ('Reporte de pagos', 0, 'Sin reportes'),
        ('Promesas de pago', 0, 'Sin solicitudes'),
        ('Tickets', tickets, 'Abiertos'),
        ('Vence hoy', 0, 'Ninguna factura'),
    ]
    cards = ''.join(
        f'<div class="card"><div class="label">{a}</div><div class="num">{b}</div><div class="muted">{d}</div></div>'
        for a, b, d in items
    )

    body = (
        f'<div class="head"><div><h1>Dashboard</h1><p>Estado actual de tu red</p></div>'
        f'<a class="btn green" href="{url_for("client_new")}">+ Nuevo cliente</a></div>'
        f'<div class="cards">{cards}</div>'
        f'<div class="money">'
        f'<div class="card g"><div>Pagos registrados</div><div class="num">RD${paid:,.2f}</div></div>'
        f'<div class="card o"><div>Por cobrar</div><div class="num">RD${money:,.2f}</div><div>{pending} facturas pendientes</div></div>'
        f'<div class="card b"><div>Routers</div><div class="num">{routers_n}</div></div>'
        f'</div>'
    )
    return shell('Dashboard', body, 'dashboard')


def setup(app):
    app.view_functions['dashboard'] = dashboard_sync
