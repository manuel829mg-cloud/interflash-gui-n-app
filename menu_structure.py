from flask import redirect, url_for
import app as appmodule

# INTER Flash navigation based on the workflow the user showed.
# Existing working modules keep their current endpoints.
# Other menu destinations receive safe INTER Flash placeholder pages.

def item(key, label, icon='•', endpoint=None, path=None, description=None):
    return {
        'key': key, 'label': label, 'icon': icon, 'endpoint': endpoint,
        'path': path, 'description': description or f'Módulo de {label}'
    }

CLIENT_ITEMS = [
    item('clients', 'Lista de clientes', '👥', endpoint='clients'),
    item('notifications_push', 'Notificaciones push', '🔔', path='/clientes/notificaciones-push'),
    item('traffic', 'Tráfico', '〽', path='/clientes/trafico'),
    item('installations', 'Instalaciones', '▣', path='/clientes/instalaciones'),
    item('map_clients', 'Mapa', '⌖', path='/clientes/mapa'),
    item('wifi_router', 'Wifi Router', '⌁', path='/clientes/wifi'),
    item('regulatory_reports', 'Reportes regulatorios', '▤', path='/clientes/reportes-regulatorios'),
]

FINANCE_ITEMS = [
    item('finances', 'Resumen financiero', '▦', endpoint='finances'),
    item('payments', 'Pagos pendientes', '💳', endpoint='payments'),
    item('invoices', 'Facturas', '▤', endpoint='invoices'),
    item('proformas', 'Proformas', '▤', path='/finanzas/proformas'),
    item('payment_reports', 'Reporte de pagos', '☷', path='/finanzas/reporte-pagos'),
    item('payment_receipts', 'Comprobantes de pago', '▧', path='/finanzas/comprobantes'),
    item('payment_promises', 'Promesas de pago', '🤝', path='/finanzas/promesas'),
    item('payment_methods', 'Formas de pago', '💳', path='/finanzas/formas-pago'),
    item('automatic_cuts', 'Cortes automáticos', '✂', path='/finanzas/cortes-automaticos'),
    item('expenses', 'Gastos', '◫', path='/finanzas/gastos'),
    item('other_income', 'Otros ingresos', '+', path='/finanzas/otros-ingresos'),
    item('transfers', 'Transferencias', '⇄', path='/finanzas/transferencias'),
    item('collections_dashboard', 'Dashboard de cobros', '▦', path='/dashboard/cobros'),
    item('electronic_invoicing', 'Facturación electrónica', '▤', path='/finanzas/facturacion-electronica'),
    item('accounting', 'Contabilidad', '▥', path='/finanzas/contabilidad'),
    item('accounting_workers', 'Contabilidad · Trabajadores', '👥', path='/finanzas/contabilidad/trabajadores'),
    item('accounting_attendance', 'Contabilidad · Asistencia', '◷', path='/finanzas/contabilidad/asistencia'),
    item('accounting_payroll', 'Contabilidad · Nómina', '▤', path='/finanzas/contabilidad/nomina'),
    item('accounting_balance', 'Contabilidad · Balance general', '⚖', path='/finanzas/contabilidad/balance-general'),
    item('accounting_results', 'Contabilidad · Estado de resultados', '↗', path='/finanzas/contabilidad/estado-resultados'),
    item('accounting_depreciation', 'Contabilidad · Depreciaciones', '▥', path='/finanzas/contabilidad/depreciaciones'),
    item('accounting_periods', 'Contabilidad · Ejercicios', '▣', path='/finanzas/contabilidad/ejercicios'),
    item('accounting_categories', 'Contabilidad · Categorías de gastos', '🏷', path='/finanzas/contabilidad/categorias'),
    item('accounting_groups', 'Contabilidad · Grupos categorías', '▤', path='/finanzas/contabilidad/grupos'),
    item('accounting_taxes', 'Contabilidad · Reporte de impuestos', '%', path='/finanzas/contabilidad/impuestos'),
    item('accounting_projection', 'Contabilidad · Proyección financiera', '〽', path='/finanzas/contabilidad/proyeccion'),
]

WAREHOUSE_ITEMS = [
    item('warehouse', 'Dashboard almacén', '▦', path='/almacen'),
    item('warehouse_stock', 'Stock dispositivos de red', '▣', path='/almacen/stock-dispositivos'),
    item('warehouse_devices', 'Lista dispositivos de red', '□', path='/almacen/lista-dispositivos'),
    item('warehouse_articles', 'Otros artículos', '✳', path='/almacen/otros-articulos'),
    item('warehouse_services', 'Otros servicios', '🔧', path='/almacen/otros-servicios'),
    item('warehouse_suppliers', 'Proveedores', '🚚', path='/almacen/proveedores'),
    item('warehouse_branches', 'Sucursales', '▥', path='/almacen/sucursales'),
    item('warehouse_staff', 'Asignar artículos staff', '👤', path='/almacen/asignar-staff'),
    item('warehouse_inventory', 'Mi inventario', '▣', path='/almacen/mi-inventario'),
    item('warehouse_log', 'Log almacén', '↻', path='/almacen/log'),
]

ADMIN_ITEMS = [
    item('team', 'Mi equipo', '👥', path='/administracion/equipo'),
    item('roles', 'Roles y permisos', '🛡', path='/administracion/roles'),
    item('admin', 'Configuración administrativa', '⚙', endpoint='admin'),
]

SUPPORT_ITEMS = [
    item('technician_panel', 'Panel técnico', '🛠', path='/soporte/tecnico'),
    item('technician_attendance', 'Asistencia', '◷', path='/dashboard/tecnico'),
    item('support', 'Tickets', '◉', endpoint='support'),
    item('tickets_unassigned', 'Sin asignar', '○', path='/soporte/tickets/sin-asignar'),
    item('tickets_assigned', 'Asignados', '●', path='/soporte/tickets/asignados'),
    item('tickets_progress', 'En progreso', '◐', path='/soporte/tickets/en-progreso'),
    item('tickets_resolved', 'Resueltos', '✓', path='/soporte/tickets/resueltos'),
    item('tickets_closed', 'Cerrados', '×', path='/soporte/tickets/cerrados'),
    item('tickets_search', 'Buscar tickets', '⌕', path='/soporte/tickets/buscar'),
]

NETWORK_TOP = [
    item('routers', 'Routers', '⌁', endpoint='routers'),
    item('plans', 'Planes', '◉', endpoint='plans'),
    item('zones', 'Zonas', '⌖', endpoint='zones'),
    item('companies', 'Empresas', '▥', path='/empresas'),
    item('whatsapp', 'WhatsApp', '◯', endpoint='whatsapp'),
]

OLT_ITEMS = [
    item('olt_dashboard', 'Dashboard OLT', '▦', path='/olt/dashboard'),
    item('olt_list', 'OLT', '◉', path='/olt'),
    item('onus_authorized', 'ONUs autorizadas', '✓', path='/olt/onu/autorizadas'),
    item('olt_unauthorized', 'ONUs sin autorizar', '◌', path='/olt/onu/sin-autorizar'),
    item('onu_pre_auth', 'Pre-autorizar ONU', '+', path='/olt/onu/pre-autorizar'),
    item('onus_pending', 'ONUs pendientes', '◷', path='/olt/onu/pendientes'),
    item('onu_models', 'Modelos de ONU', '▣', path='/olt/modelos-onu'),
    item('olt_speed_plans', 'Planes de velocidad', '〽', path='/olt/planes-velocidad'),
    item('ftth_map', 'Mapa FTTH', '⌖', path='/olt/mapa-ftth'),
    item('network_health', 'Salud de red', '♥', path='/salud-red'),
    item('olt_alerts', 'Alertas OLT', '⚠', path='/olt/alertas'),
    item('tr069', 'TR069', '⌁', path='/tr069'),
]

ANTENNA_ITEMS = [
    item('antennas_dashboard', 'Dashboard', '▦', path='/antenas/dashboard'),
    item('antennas_all', 'Todas las antenas', '⌁', path='/antenas/todas'),
    item('antennas_ap', 'Access Point', '⌁', path='/antenas/access-point'),
    item('antennas_clients', 'Clientes', '👥', path='/antenas/clientes'),
    item('antennas_ptp', 'PTP', '↔', path='/antenas/ptp'),
    item('antennas_config', 'Configuración', '⚙', path='/antenas/configuracion'),
]

SYSTEM_ITEMS = [
    item('system_manual', 'Manual del sistema', '?', path='/sistema/manual'),
    item('system_templates', 'Plantillas', '▤', path='/sistema/plantillas'),
    item('zone_discounts', 'Descuento por zona', '%', path='/sistema/descuentos-zona'),
    item('system_logs', 'Logs', '☷', path='/sistema/logs'),
    item('client_portal', 'Portal del cliente', '▣', path='/sistema/portal-cliente'),
    item('custom_domain', 'Dominio personalizado', '◎', path='/sistema/dominio-portal'),
    item('bank_accounts', 'Cuentas bancarias', '▥', path='/sistema/cuentas-bancarias'),
    item('payment_gateways', 'Pasarelas de pago', '💳', path='/sistema/pasarelas-pago'),
    item('integration_api', 'API de integración', '<>', path='/sistema/api-integracion'),
    item('periodic_tasks', 'Tareas periódicas', '↻', path='/sistema/tareas'),
    item('ai_assistant', 'Asistente IA', '✦', path='/sistema/ia'),
]

CONFIG_ITEMS = [
    item('settings_company', 'Empresa y perfil', '▥', path='/settings'),
    item('themes', 'Temas', '◐', path='/settings/temas'),
    item('apps_apk', 'APK', '▣', path='/settings/apks'),
    item('referrals', 'Referidos', '↗', path='/settings/referidos'),
    item('dashboard_widgets', 'Widgets del dashboard', '▦', path='/settings/dashboard-widgets'),
    item('preferences', 'Preferencias', '⚙', path='/settings/preferencias'),
    item('email_server', 'Servidor de correo', '✉', path='/settings/servidor-correo'),
    item('xui_dashboard', 'XUI One · Dashboard', '▦', path='/settings/xui-one'),
    item('xui_lines', 'XUI One · Líneas', '☷', path='/settings/xui-one/lines'),
    item('xui_streams', 'XUI One · Streams', '▶', path='/settings/xui-one/streams'),
    item('xui_down', 'XUI One · Caídos', '⚠', path='/settings/xui-one/down'),
    item('xui_config', 'XUI One · Configuración', '⚙', path='/settings/xui-one/configuracion'),
]

HOTSPOT_ITEMS = [
    item('hotspot_dashboard', 'Dashboard', '▦', path='/hotspot/dashboard'),
    item('hotspot_routers', 'Router Hotspot', '⌁', path='/hotspot/routers'),
    item('hotspot_profiles', 'User Profile', '👤', path='/hotspot/perfiles'),
    item('hotspot_plans', 'Planes', '◉', path='/hotspot/planes'),
    item('hotspot_create', 'Crear fichas', '+', path='/hotspot/fichas/crear'),
    item('hotspot_vouchers', 'Listado de fichas', '☷', path='/hotspot/fichas'),
    item('hotspot_print', 'Impresión de fichas', '▤', path='/hotspot/impresion'),
    item('hotspot_pos_list', 'Puntos de venta', '▣', path='/hotspot/puntos-venta'),
    item('hotspot_pos', 'Punto de venta', '💳', path='/hotspot/punto-venta'),
    item('hotspot_cash_close', 'Corte de caja', '▥', path='/hotspot/corte-caja'),
]

GROUPS = [
    ('Clientes', '👥', CLIENT_ITEMS),
    ('Finanzas', '▣', FINANCE_ITEMS),
    ('Almacén', '▤', WAREHOUSE_ITEMS),
    ('Administración', '♢', ADMIN_ITEMS),
    ('Soporte Técnico', '◉', SUPPORT_ITEMS),
]

SECONDARY_GROUPS = [
    ('OLT', '◉', OLT_ITEMS),
    ('Antenas', '⌁', ANTENNA_ITEMS),
    ('Sistema', '⚙', SYSTEM_ITEMS),
    ('Configuración', '⚙', CONFIG_ITEMS),
    ('Hotspot', '◉', HOTSPOT_ITEMS),
]

def _href(it):
    if it.get('endpoint'):
        try:
            return url_for(it['endpoint'])
        except Exception:
            return '#'
    return it.get('path') or '#'

def _is_active(it, active):
    return active == it['key'] or (it.get('endpoint') and active == it['endpoint'])

def _link(it, active):
    cls = 'sub on' if _is_active(it, active) else 'sub'
    return f'<a class="{cls}" href="{_href(it)}"><span class="ico">{it["icon"]}</span><span>{it["label"]}</span></a>'

def _group(title, icon, items, active):
    opened = ' open' if any(_is_active(x, active) for x in items) else ''
    links = ''.join(_link(x, active) for x in items)
    return f'''<details class="navgroup"{opened}>
      <summary><span class="ico">{icon}</span><span>{title}</span><span class="chev">⌄</span></summary>
      <div class="submenu">{links}</div>
    </details>'''

def _top(it, active):
    cls = 'toplink on' if _is_active(it, active) else 'toplink'
    return f'<a class="{cls}" href="{_href(it)}"><span class="ico">{it["icon"]}</span><span>{it["label"]}</span></a>'

def shell(title, body, active='dashboard'):
    dashboard = item('dashboard', 'Dashboard', '▦', endpoint='dashboard')
    nav_parts = [_top(dashboard, active)]
    nav_parts.extend(_group(*g, active) for g in GROUPS)
    nav_parts.append('<div class="sep"></div>')
    nav_parts.extend(_top(x, active) for x in NETWORK_TOP)
    nav_parts.extend(_group(*g, active) for g in SECONDARY_GROUPS)
    nav_parts.append(_top(item('license_page', 'Licencia', '🔑', path='/licencia'), active))
    nav = ''.join(nav_parts)

    css = appmodule.CSS + '''
    .side{width:292px;padding:18px 13px;overflow-y:auto}.main{margin-left:292px}.nav{margin-top:12px}
    .toplink,.navgroup summary,.sub{display:flex;align-items:center;gap:12px;border-radius:9px;color:#d5dde6;cursor:pointer;text-decoration:none}
    .toplink{padding:12px 13px;margin:3px 0}.toplink:hover,.toplink.on{background:#173f82;color:white}
    .navgroup{margin:3px 0}.navgroup summary{list-style:none;padding:12px 13px;font-size:15px;font-weight:700}
    .navgroup summary::-webkit-details-marker{display:none}.navgroup summary:hover{background:#18222d}.navgroup[open] summary{color:#fff}
    .chev{margin-left:auto;font-size:18px;transition:.18s}.navgroup[open] .chev{transform:rotate(180deg)}
    .submenu{padding:2px 0 7px 14px}.sub{padding:9px 11px;margin:2px 0;font-size:13px;line-height:1.25}
    .sub:hover{background:#172a40;color:#fff}.sub.on{background:linear-gradient(135deg,#2866d8,#1748a5);color:#fff;font-weight:800}
    .ico{width:22px;text-align:center;flex:0 0 22px}.brand{margin-bottom:8px}.footer-menu{color:#8090a0;font-size:12px;padding:14px 13px}
    .sep{height:1px;background:#ffffff14;margin:10px 8px}
    @media(max-width:900px){.side{width:82px}.main{margin-left:82px}.navgroup summary span:not(.ico),.toplink span:not(.ico),.sub span:not(.ico),.footer-menu{display:none}.submenu{padding-left:0}}
    '''
    return appmodule.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav><div class="footer-menu">© 2026 INTER Flash Management</div></aside><main class="main"><header class="top"><div><small>BIENVENIDO</small><b>INTER Flash</b></div><a href="{{url_for('logout')}}">Salir</a></header><section class="content">{{body|safe}}</section></main></body></html>''', title=title, css=css, nav=nav, body=body)

def _placeholder(title, text, active):
    if not appmodule.auth():
        return redirect(url_for('login'))
    body = f'''<div class="head"><div><h1>{title}</h1><p>{text}</p></div></div>
    <div class="panel"><div class="empty"><b>{title}</b><br><br>Este módulo ya está incluido en INTER Flash. La pantalla y navegación están listas; aquí conectaremos los datos y acciones reales de INTER Flash.</div></div>'''
    return shell(title, body, active)

def _add(flask_app, it):
    path = it.get('path')
    if not path:
        return
    known_paths = {rule.rule for rule in flask_app.url_map.iter_rules()}
    if path in known_paths:
        return
    endpoint = 'menu_' + it['key']
    if endpoint in flask_app.view_functions:
        return
    flask_app.add_url_rule(
        path, endpoint,
        lambda t=it['label'], d=it['description'], a=it['key']: _placeholder(t, d, a)
    )

def setup(flask_app):
    appmodule.shell = shell
    all_items = []
    for _, _, xs in GROUPS + SECONDARY_GROUPS:
        all_items.extend(xs)
    all_items.extend(NETWORK_TOP)
    all_items.append(item('license_page', 'Licencia', '🔑', path='/licencia'))
    for it in all_items:
        _add(flask_app, it)
