from flask import redirect, url_for
import app as appmodule

# INTER Flash navigation inspired by the user's preferred workflow.
# Existing working modules keep their original endpoints; the rest are placeholders
# ready to be connected gradually without copying third-party source code.

CLIENT_ITEMS = {
    'clients': ('👥', 'Lista de clientes'),
    'notifications_push': ('🔔', 'Notificaciones push'),
    'traffic': ('〽', 'Tráfico'),
    'installations': ('▣', 'Instalaciones'),
    'map_clients': ('⌖', 'Mapa'),
    'wifi_router': ('⌁', 'Wifi Router'),
}

FINANCE_ITEMS = {
    'finances': ('▣', 'Resumen'),
    'payments': ('💳', 'Pagos pendientes'),
    'invoices': ('▤', 'Facturas'),
    'proformas': ('▤', 'Proformas'),
    'payment_reports': ('☷', 'Reporte de pagos'),
    'payment_receipts': ('▧', 'Comprobantes de pago'),
    'payment_promises': ('🤝', 'Promesas de pago'),
    'payment_methods': ('💳', 'Formas de pago'),
    'automatic_cuts': ('✂', 'Cortes automáticos'),
    'expenses': ('◫', 'Gastos'),
    'accounting': ('▥', 'Contabilidad'),
}

WAREHOUSE_ITEMS = {
    'warehouse': ('▦', 'Dashboard almacén'),
    'warehouse_stock': ('▣', 'Stock dispositivos'),
    'warehouse_devices': ('□', 'Lista dispositivos'),
    'warehouse_articles': ('✳', 'Otros artículos'),
    'warehouse_services': ('🔧', 'Otros servicios'),
    'warehouse_suppliers': ('🚚', 'Proveedores'),
    'warehouse_branches': ('▥', 'Sucursales'),
    'warehouse_staff': ('👤', 'Asignar artículos staff'),
    'warehouse_inventory': ('▣', 'Mi inventario'),
    'warehouse_log': ('↻', 'Log almacén'),
}

ADMIN_ITEMS = {
    'team': ('👥', 'Mi equipo'),
    'roles': ('🛡', 'Roles y permisos'),
    'admin': ('⚙', 'Configuración'),
}

SUPPORT_ITEMS = {
    'support': ('◉', 'Tickets de soporte'),
    'technician_panel': ('🛠', 'Panel técnico'),
}

NETWORK_ITEMS = {
    'routers': ('⌁', 'Routers'),
    'plans': ('◉', 'Planes'),
    'zones': ('⌖', 'Zonas'),
    'whatsapp': ('◯', 'WhatsApp'),
}

OLT_ITEMS = {
    'olt_dashboard': ('◉', 'OLT / ONUs'),
    'olt_unauthorized': ('◌', 'ONUs sin autorizar'),
    'ftth_map': ('⌖', 'Mapa FTTH'),
}

ANTENNA_ITEMS = {
    'antennas': ('⌁', 'Antenas'),
}

SYSTEM_ITEMS = {
    'system_main': ('⚙', 'Sistema'),
    'system_logs': ('☷', 'Logs'),
    'client_portal': ('▣', 'Portal del cliente'),
    'bank_accounts': ('▥', 'Cuentas bancarias'),
    'payment_gateways': ('💳', 'Pasarelas de pago'),
    'integration_api': ('<>', 'API de integración'),
    'periodic_tasks': ('↻', 'Tareas periódicas'),
    'manual': ('?', 'Manual'),
}

CONFIG_ITEMS = {
    'settings_company': ('▥', 'Datos de la empresa'),
    'settings_general': ('⚙', 'Ajustes generales'),
    'email_server': ('✉', 'Servidor de correo'),
    'templates': ('▤', 'Plantillas'),
}

HOTSPOT_ITEMS = {
    'hotspot': ('◉', 'Hotspot'),
    'hotspot_pos': ('▣', 'Punto de venta'),
}


def _href(endpoint):
    try:
        return url_for(endpoint)
    except Exception:
        return '#'


def _link(endpoint, icon, label, active):
    cls = 'sub on' if active == endpoint else 'sub'
    return f'<a class="{cls}" href="{_href(endpoint)}"><span class="ico">{icon}</span><span>{label}</span></a>'


def _group(title, icon, items, active):
    opened = ' open' if active in items else ''
    links = ''.join(_link(k, *v, active) for k, v in items.items())
    return f'''<details class="navgroup"{opened}>
      <summary><span class="ico">{icon}</span><span>{title}</span><span class="chev">⌄</span></summary>
      <div class="submenu">{links}</div>
    </details>'''


def _top(endpoint, icon, label, active):
    cls = 'toplink on' if active == endpoint else 'toplink'
    return f'<a class="{cls}" href="{_href(endpoint)}"><span class="ico">{icon}</span><span>{label}</span></a>'


def shell(title, body, active='dashboard'):
    nav = ''.join([
        _top('dashboard', '▦', 'Dashboard', active),
        _group('Clientes', '👥', CLIENT_ITEMS, active),
        _group('Finanzas', '▣', FINANCE_ITEMS, active),
        _group('Almacén', '▤', WAREHOUSE_ITEMS, active),
        _group('Administración', '♢', ADMIN_ITEMS, active),
        _group('Soporte Técnico', '◉', SUPPORT_ITEMS, active),
        '<div class="sep"></div>',
        *[_top(k, *v, active) for k, v in NETWORK_ITEMS.items()],
        _group('OLT', '◉', OLT_ITEMS, active),
        _group('Antenas', '⌁', ANTENNA_ITEMS, active),
        _group('Sistema', '⚙', SYSTEM_ITEMS, active),
        _top('license_page', '🔑', 'Licencia', active),
        _group('Configuración', '⚙', CONFIG_ITEMS, active),
        _group('Hotspot', '◉', HOTSPOT_ITEMS, active),
    ])

    css = appmodule.CSS + '''
    .side{width:280px;padding:18px 13px;overflow-y:auto}.main{margin-left:280px}.nav{margin-top:12px}.toplink,.navgroup summary,.sub{display:flex;align-items:center;gap:12px;border-radius:9px;color:#d5dde6;cursor:pointer;text-decoration:none}.toplink{padding:12px 13px;margin:3px 0}.toplink:hover,.toplink.on{background:#173f82;color:white}.navgroup{margin:3px 0}.navgroup summary{list-style:none;padding:12px 13px;font-size:16px;font-weight:700}.navgroup summary::-webkit-details-marker{display:none}.navgroup summary:hover{background:#18222d}.navgroup[open] summary{color:#fff}.chev{margin-left:auto;font-size:18px}.navgroup[open] .chev{transform:rotate(180deg)}.submenu{padding:2px 0 6px 14px}.sub{padding:10px 12px;margin:2px 0;font-size:14px}.sub:hover{background:#172a40;color:#fff}.sub.on{background:linear-gradient(135deg,#2866d8,#1748a5);color:#fff;font-weight:800}.ico{width:22px;text-align:center;flex:0 0 22px}.brand{margin-bottom:8px}.footer-menu{color:#8090a0;font-size:12px;padding:14px 13px}.sep{height:1px;background:#ffffff14;margin:10px 8px}@media(max-width:900px){.side{width:82px}.main{margin-left:82px}.navgroup summary span:not(.ico),.toplink span:not(.ico),.sub span:not(.ico),.footer-menu{display:none}.submenu{padding-left:0}}
    '''
    return appmodule.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav><div class="footer-menu">© 2026 INTER Flash Management</div></aside><main class="main"><header class="top"><div><small>BIENVENIDO</small><b>INTER Flash</b></div><a href="{{url_for('logout')}}">Salir</a></header><section class="content">{{body|safe}}</section></main></body></html>''', title=title, css=css, nav=nav, body=body)


def _placeholder(title, text, active):
    if not appmodule.auth():
        return redirect(url_for('login'))
    body = f'''<div class="head"><div><h1>{title}</h1><p>{text}</p></div></div>
    <div class="panel"><div class="empty"><b>{title}</b><br><br>Este módulo ya está incluido en INTER Flash. La estructura está lista para conectar sus funciones reales.</div></div>'''
    return shell(title, body, active)


def _add(flask_app, path, endpoint, title, description):
    if endpoint not in flask_app.view_functions:
        flask_app.add_url_rule(path, endpoint, lambda t=title, d=description, a=endpoint: _placeholder(t, d, a))


def setup(flask_app):
    appmodule.shell = shell

    placeholders = [
        ('/clientes/notificaciones-push','notifications_push','Notificaciones push','Avisos y notificaciones para clientes'),
        ('/clientes/trafico','traffic','Tráfico','Consumo y actividad de los clientes'),
        ('/clientes/instalaciones','installations','Instalaciones','Control de instalaciones nuevas'),
        ('/clientes/mapa','map_clients','Mapa','Ubicación y cobertura de clientes'),
        ('/clientes/wifi','wifi_router','Wifi Router','Gestión de routers WiFi de clientes'),

        ('/finanzas/proformas','proformas','Proformas','Cotizaciones y proformas'),
        ('/finanzas/reporte-pagos','payment_reports','Reporte de pagos','Reportes recibidos desde clientes'),
        ('/finanzas/comprobantes','payment_receipts','Comprobantes de pago','Fotos y comprobantes de pagos'),
        ('/finanzas/promesas','payment_promises','Promesas de pago','Promesas y compromisos de pago'),
        ('/finanzas/formas-pago','payment_methods','Formas de pago','Métodos disponibles para registrar pagos'),
        ('/finanzas/cortes-automaticos','automatic_cuts','Cortes automáticos','Reglas automáticas de suspensión y reconexión'),
        ('/finanzas/gastos','expenses','Gastos','Registro y control de gastos'),
        ('/finanzas/contabilidad','accounting','Contabilidad','Balance, nómina, categorías e informes'),

        ('/almacen','warehouse','Almacén','Inventario de equipos y materiales'),
        ('/almacen/stock-dispositivos','warehouse_stock','Stock dispositivos','Stock de equipos de red'),
        ('/almacen/lista-dispositivos','warehouse_devices','Lista dispositivos','Listado de dispositivos de red'),
        ('/almacen/otros-articulos','warehouse_articles','Otros artículos','Inventario de artículos generales'),
        ('/almacen/otros-servicios','warehouse_services','Otros servicios','Servicios adicionales'),
        ('/almacen/proveedores','warehouse_suppliers','Proveedores','Proveedores y compras'),
        ('/almacen/sucursales','warehouse_branches','Sucursales','Inventario por sucursal'),
        ('/almacen/asignar-staff','warehouse_staff','Asignar artículos staff','Asignación de equipos al personal'),
        ('/almacen/mi-inventario','warehouse_inventory','Mi inventario','Inventario asignado al técnico'),
        ('/almacen/log','warehouse_log','Log almacén','Historial de movimientos de inventario'),

        ('/administracion/equipo','team','Mi equipo','Usuarios internos de INTER Flash'),
        ('/administracion/roles','roles','Roles y permisos','Permisos por usuario y rol'),
        ('/soporte/tecnico','technician_panel','Panel técnico','Soportes asignados y agenda técnica'),

        ('/olt','olt_dashboard','OLT / ONUs','Gestión de OLT y ONUs'),
        ('/olt/onu/sin-autorizar','olt_unauthorized','ONUs sin autorizar','ONUs pendientes de autorización'),
        ('/olt/mapa-ftth','ftth_map','Mapa FTTH','Planta externa y red de fibra'),
        ('/antenas','antennas','Antenas','Gestión de AP y CPE'),

        ('/sistema','system_main','Sistema','Herramientas generales del sistema'),
        ('/sistema/logs','system_logs','Logs','Registro de actividad de INTER Flash'),
        ('/sistema/portal-cliente','client_portal','Portal del cliente','Configuración del portal del abonado'),
        ('/sistema/cuentas-bancarias','bank_accounts','Cuentas bancarias','Cuentas mostradas a clientes'),
        ('/sistema/pasarelas-pago','payment_gateways','Pasarelas de pago','Integraciones para pagos en línea'),
        ('/sistema/api-integracion','integration_api','API de integración','Conexión con sistemas externos'),
        ('/sistema/tareas','periodic_tasks','Tareas periódicas','Procesos automáticos programados'),
        ('/sistema/manual','manual','Manual','Manual de uso de INTER Flash'),
        ('/licencia','license_page','Licencia','Información de licencia y plan'),

        ('/settings','settings_company','Datos de la empresa','Nombre, logo y datos comerciales'),
        ('/settings/general','settings_general','Ajustes generales','Preferencias principales del sistema'),
        ('/settings/servidor-correo','email_server','Servidor de correo','Configuración SMTP y avisos por correo'),
        ('/sistema/plantillas','templates','Plantillas','Mensajes, contratos y documentos'),

        ('/hotspot','hotspot','Hotspot','Gestión de fichas y usuarios Hotspot'),
        ('/hotspot/punto-venta','hotspot_pos','Punto de venta Hotspot','Venta e impresión de fichas'),
    ]

    for args in placeholders:
        _add(flask_app, *args)
