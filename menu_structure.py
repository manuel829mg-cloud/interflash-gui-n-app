from flask import redirect, url_for
import app as appmodule

# INTER Flash: navegación reconstruida de forma independiente a partir del flujo
# y etiquetas que el usuario compartió. Se conservan los endpoints que ya funcionan.

CLIENT_ITEMS = {
    'clients': ('👥', 'Lista de clientes'),
    'notifications_push': ('🔔', 'Notificaciones push'),
    'traffic': ('〽', 'Tráfico'),
    'installations': ('▣', 'Instalaciones'),
    'map_clients': ('⌖', 'Mapa'),
    'wifi_router': ('⌁', 'Wifi Router'),
    'regulatory_reports': ('▥', 'Reportes regulatorios'),
}
FINANCE_ITEMS = {
    'finances': ('▦', 'Resumen'), 'collections_dashboard': ('▦', 'Dashboard de cobros'),
    'payments': ('💳', 'Pagos pendientes'), 'invoices': ('▤', 'Facturas'),
    'proformas': ('▤', 'Proformas'), 'payment_reports': ('☷', 'Reporte de pagos'),
    'payment_receipts': ('▧', 'Comprobantes de pago'), 'payment_promises': ('🤝', 'Promesas de pago'),
    'payment_methods': ('💳', 'Formas de pago'), 'automatic_cuts': ('✂', 'Cortes automáticos'),
    'expenses': ('◫', 'Gastos'),
}
ACCOUNTING_ITEMS = {
    'accounting_workers': ('👥', 'Trabajadores'), 'accounting_attendance': ('◷', 'Asistencia'),
    'accounting_payroll': ('☷', 'Nómina'), 'accounting_balance': ('⚖', 'Balance general'),
    'accounting_results': ('↗', 'Estado de resultados'), 'accounting_depreciation': ('▥', 'Depreciaciones'),
    'accounting_periods': ('▣', 'Ejercicios'), 'accounting_categories': ('⌑', 'Categorías de gastos'),
    'accounting_groups': ('▤', 'Grupos categorías'), 'accounting_taxes': ('%', 'Reporte de impuestos'),
    'accounting_projection': ('〽', 'Proyección financiera'),
}
WAREHOUSE_ITEMS = {
    'warehouse': ('▦', 'Dashboard'), 'warehouse_stock': ('▣', 'Stock dispositivos de red'),
    'warehouse_devices': ('□', 'Lista dispositivos de red'), 'warehouse_articles': ('✳', 'Otros artículos'),
    'warehouse_services': ('🔧', 'Otros servicios'), 'warehouse_suppliers': ('🚚', 'Proveedores'),
    'warehouse_branches': ('▥', 'Sucursales'), 'warehouse_staff': ('👤', 'Asignar artículos staff'),
    'warehouse_inventory': ('▣', 'Mi inventario'), 'warehouse_log': ('↻', 'Log'),
}
ADMIN_ITEMS = {'team': ('👥', 'Mi equipo'), 'roles': ('🛡', 'Roles y permisos'), 'admin': ('⚙', 'Configuración')}
SUPPORT_ITEMS = {
    'technician_panel': ('🛠', 'Panel técnico'), 'technician_attendance': ('◷', 'Asistencia'),
    'support_new': ('◉', 'Tickets nuevos'), 'support_unassigned': ('○', 'Sin asignar'),
    'support_assigned': ('◉', 'Asignados'), 'support_progress': ('◌', 'En progreso'),
    'support_resolved': ('✓', 'Resueltos'), 'support_closed': ('■', 'Cerrados'),
    'support_search': ('⌕', 'Buscar tickets'),
}
NETWORK_ITEMS = {'routers': ('⌁', 'Routers'), 'plans': ('◉', 'Planes'), 'zones': ('⌖', 'Zonas'), 'companies': ('▥', 'Empresas'), 'whatsapp': ('◯', 'WhatsApp')}
OLT_ITEMS = {
    'olt_dashboard_page': ('▦', 'Dashboard'), 'olt_dashboard': ('◉', 'OLT'),
    'olt_authorized': ('✓', 'ONUs autorizadas'), 'olt_unauthorized': ('◌', 'ONUs sin autorizar'),
    'olt_pre_authorize': ('＋', 'Pre-autorizar ONU'), 'olt_pending': ('◷', 'ONUs pendientes'),
    'olt_models': ('□', 'Modelo de ONU'), 'olt_speed_plans': ('〽', 'Planes de velocidad'),
    'ftth_map': ('⌖', 'Mapa FTTH'), 'network_health': ('❤', 'Salud de red'),
    'olt_alerts': ('⚠', 'Alertas'), 'tr069': ('⌁', 'TR069'),
}
ANTENNA_ITEMS = {
    'antennas_dashboard': ('▦', 'Dashboard'), 'antennas_all': ('⌁', 'Todas'),
    'antennas_ap': ('◉', 'Access Point'), 'antennas_clients': ('⌁', 'Clientes / CPE'),
    'antennas_ptp': ('↔', 'PTP'), 'antennas_config': ('⚙', 'Configuración'),
}
SYSTEM_ITEMS = {
    'system_ai': ('✦', 'Asistente IA'), 'manual': ('?', 'Manual'), 'templates': ('▤', 'Plantillas'),
    'zone_discounts': ('%', 'Descuento por zona'), 'system_logs': ('☷', 'Logs'),
    'client_portal': ('▣', 'Portal del cliente'), 'portal_domain': ('⌁', 'Dominio portal'),
    'bank_accounts': ('▥', 'Cuentas bancarias'), 'payment_gateways': ('💳', 'Pasarelas de pago'),
    'integration_api': ('<>', 'API de integración'), 'periodic_tasks': ('↻', 'Tareas periódicas'),
}
CONFIG_ITEMS = {
    'settings_company': ('▥', 'Empresa y perfil'), 'settings_themes': ('◐', 'Temas'),
    'settings_apks': ('▣', 'APK'), 'settings_referrals': ('↗', 'Referidos'),
    'settings_widgets': ('▦', 'Widgets dashboard'), 'settings_general': ('⚙', 'Preferencias'),
    'email_server': ('✉', 'Servidor de correo'),
}
XUI_ITEMS = {'xui_dashboard': ('▦', 'Dashboard'), 'xui_lines': ('☷', 'Lines'), 'xui_streams': ('▶', 'Streams'), 'xui_down': ('↓', 'Down'), 'xui_config': ('⚙', 'Configuración')}
HOTSPOT_ITEMS = {
    'hotspot_dashboard': ('▦', 'Dashboard'), 'hotspot_routers': ('⌁', 'Router Hotspot'),
    'hotspot_profiles': ('👤', 'User Profile'), 'hotspot_plans': ('◉', 'Planes'),
    'hotspot_create_vouchers': ('＋', 'Crear fichas'), 'hotspot_vouchers': ('☷', 'Listado de fichas'),
    'hotspot_print': ('▤', 'Impresión de fichas'), 'hotspot_sales_points': ('▥', 'Puntos de venta'),
    'hotspot_pos': ('▣', 'Punto de venta'), 'hotspot_cash_close': ('💰', 'Corte de caja'),
}
E_INVOICE_ITEMS = {
    'einvoice_sat': ('▤', 'SAT México'), 'einvoice_dian': ('▤', 'DIAN Colombia'),
    'einvoice_sunat': ('▤', 'SUNAT Perú'), 'einvoice_sii': ('▤', 'SII Chile'),
    'einvoice_sri': ('▤', 'SRI Ecuador'), 'einvoice_afip': ('▤', 'AFIP Argentina'),
    'einvoice_sat_gt': ('▤', 'SAT Guatemala'), 'einvoice_ve': ('▤', 'Emisiones Venezuela'),
}

def _href(endpoint):
    try: return url_for(endpoint)
    except Exception: return '#'

def _link(endpoint, icon, label, active):
    cls = 'sub on' if active == endpoint else 'sub'
    return f'<a class="{cls}" href="{_href(endpoint)}"><span class="ico">{icon}</span><span>{label}</span></a>'

def _group(title, icon, items, active, nested=False):
    opened = ' open' if active in items else ''
    links = ''.join(_link(k, *v, active) for k, v in items.items())
    extra = ' nested' if nested else ''
    return f'''<details class="navgroup{extra}"{opened}><summary><span class="ico">{icon}</span><span>{title}</span><span class="chev">⌄</span></summary><div class="submenu">{links}</div></details>'''

def _top(endpoint, icon, label, active):
    cls = 'toplink on' if active == endpoint else 'toplink'
    return f'<a class="{cls}" href="{_href(endpoint)}"><span class="ico">{icon}</span><span>{label}</span></a>'

def shell(title, body, active='dashboard'):
    finance_open = active in FINANCE_ITEMS or active in ACCOUNTING_ITEMS or active in E_INVOICE_ITEMS
    finance_bits = ''.join(_link(k,*v,active) for k,v in FINANCE_ITEMS.items()) + _group('Facturación electrónica','▤',E_INVOICE_ITEMS,active,True) + _group('Contabilidad','▥',ACCOUNTING_ITEMS,active,True)
    finance = f'''<details class="navgroup"{' open' if finance_open else ''}><summary><span class="ico">▣</span><span>Finanzas</span><span class="chev">⌄</span></summary><div class="submenu">{finance_bits}</div></details>'''
    config_open = active in CONFIG_ITEMS or active in XUI_ITEMS
    config_bits = ''.join(_link(k,*v,active) for k,v in CONFIG_ITEMS.items()) + _group('Xui One','▶',XUI_ITEMS,active,True)
    config = f'''<details class="navgroup"{' open' if config_open else ''}><summary><span class="ico">⚙</span><span>Configuración</span><span class="chev">⌄</span></summary><div class="submenu">{config_bits}</div></details>'''
    nav = ''.join([
        _top('dashboard','▦','Dashboard',active), _group('Clientes','👥',CLIENT_ITEMS,active), finance,
        _group('Almacén','▤',WAREHOUSE_ITEMS,active), _group('Administración','♢',ADMIN_ITEMS,active),
        _group('Soporte Técnico','◉',SUPPORT_ITEMS,active), '<div class="sep"></div>',
        *[_top(k,*v,active) for k,v in NETWORK_ITEMS.items()], _group('OLT / Fibra','◉',OLT_ITEMS,active),
        _group('Antenas','⌁',ANTENNA_ITEMS,active), _group('Sistema','⚙',SYSTEM_ITEMS,active),
        _top('license_page','🔑','Licencia',active), config, _group('Hotspot','◉',HOTSPOT_ITEMS,active)
    ])
    css = appmodule.CSS + '''
    .side{width:286px;padding:16px 12px;overflow-y:auto}.main{margin-left:286px}.nav{margin-top:10px}.toplink,.navgroup summary,.sub{display:flex;align-items:center;gap:12px;border-radius:9px;color:#d5dde6;cursor:pointer;text-decoration:none}.toplink{padding:11px 12px;margin:2px 0}.toplink:hover,.toplink.on{background:#173f82;color:white}.navgroup{margin:2px 0}.navgroup summary{list-style:none;padding:11px 12px;font-size:15px;font-weight:700}.navgroup summary::-webkit-details-marker{display:none}.navgroup summary:hover{background:#18222d}.navgroup[open]>summary{color:#fff}.navgroup.nested{margin-left:8px;border-left:1px solid #ffffff18}.navgroup.nested>summary{font-size:13px;padding:9px 10px}.chev{margin-left:auto;font-size:17px}.navgroup[open]>summary .chev{transform:rotate(180deg)}.submenu{padding:2px 0 6px 13px}.nested .submenu{padding-left:10px}.sub{padding:9px 11px;margin:1px 0;font-size:13px}.sub:hover{background:#172a40;color:#fff}.sub.on{background:linear-gradient(135deg,#2866d8,#1748a5);color:#fff;font-weight:800}.ico{width:22px;text-align:center;flex:0 0 22px}.brand{margin-bottom:7px}.footer-menu{color:#8090a0;font-size:12px;padding:14px 13px}.sep{height:1px;background:#ffffff14;margin:9px 8px}@media(max-width:900px){.side{width:82px}.main{margin-left:82px}.navgroup summary span:not(.ico),.toplink span:not(.ico),.sub span:not(.ico),.footer-menu{display:none}.submenu{padding-left:0}.navgroup.nested{margin-left:0;border-left:0}}
    '''
    return appmodule.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav><div class="footer-menu">© 2026 INTER Flash Management</div></aside><main class="main"><header class="top"><div><small>BIENVENIDO</small><b>INTER Flash</b></div><a href="{{url_for('logout')}}">Salir</a></header><section class="content">{{body|safe}}</section></main></body></html>''', title=title, css=css, nav=nav, body=body)

def _placeholder(title, text, active):
    if not appmodule.auth(): return redirect(url_for('login'))
    body=f'''<div class="head"><div><h1>{title}</h1><p>{text}</p></div></div><div class="panel"><div class="empty"><b>{title}</b><br><br>Este módulo ya está creado en INTER Flash y está listo para que conectemos su función real.</div></div>'''
    return shell(title,body,active)

def _add(flask_app,path,endpoint,title,description):
    if endpoint not in flask_app.view_functions:
        flask_app.add_url_rule(path,endpoint,lambda t=title,d=description,a=endpoint:_placeholder(t,d,a))

def setup(flask_app):
    appmodule.shell=shell
    placeholders=[
        ('/clientes/notificaciones-push','notifications_push','Notificaciones push','Avisos y notificaciones para clientes'),('/clientes/trafico','traffic','Tráfico','Consumo y actividad de clientes'),('/clientes/instalaciones','installations','Instalaciones','Control de instalaciones'),('/clientes/mapa','map_clients','Mapa de clientes','Ubicación de clientes'),('/clientes/wifi','wifi_router','Wifi Router','Gestión WiFi'),('/clientes/reportes-regulatorios','regulatory_reports','Reportes regulatorios','Reportes regulatorios'),
        ('/dashboard/cobros','collections_dashboard','Dashboard de cobros','Vista de cobranza'),('/finanzas/proformas','proformas','Proformas','Cotizaciones'),('/finanzas/reporte-pagos','payment_reports','Reporte de pagos','Reportes de pagos'),('/finanzas/comprobantes','payment_receipts','Comprobantes de pago','Comprobantes'),('/finanzas/promesas','payment_promises','Promesas de pago','Promesas'),('/finanzas/formas-pago','payment_methods','Formas de pago','Métodos de pago'),('/finanzas/cortes-automaticos','automatic_cuts','Cortes automáticos','Suspensión y reconexión'),('/finanzas/gastos','expenses','Gastos','Control de gastos'),
        ('/finanzas/contabilidad/trabajadores','accounting_workers','Trabajadores','Trabajadores'),('/finanzas/contabilidad/asistencia','accounting_attendance','Asistencia','Asistencia'),('/finanzas/contabilidad/nomina','accounting_payroll','Nómina','Nómina'),('/finanzas/contabilidad/balance-general','accounting_balance','Balance General','Balance'),('/finanzas/contabilidad/estado-resultados','accounting_results','Estado de Resultados','Resultados'),('/finanzas/contabilidad/depreciaciones','accounting_depreciation','Depreciaciones','Depreciaciones'),('/finanzas/contabilidad/ejercicios','accounting_periods','Ejercicios','Períodos'),('/finanzas/contabilidad/categorias','accounting_categories','Categorías de Gastos','Categorías'),('/finanzas/contabilidad/grupos','accounting_groups','Grupos Categorías','Grupos'),('/finanzas/contabilidad/impuestos','accounting_taxes','Reporte de Impuestos','Impuestos'),('/finanzas/contabilidad/proyeccion','accounting_projection','Proyección Financiera','Proyección'),
        ('/finanzas/facturacion-electronica/sat','einvoice_sat','SAT México','Facturación electrónica'),('/finanzas/facturacion-electronica/colombia','einvoice_dian','DIAN Colombia','Facturación electrónica'),('/finanzas/facturacion-electronica/sunat','einvoice_sunat','SUNAT Perú','Facturación electrónica'),('/finanzas/facturacion-electronica/sii','einvoice_sii','SII Chile','Facturación electrónica'),('/finanzas/facturacion-electronica/sri','einvoice_sri','SRI Ecuador','Facturación electrónica'),('/finanzas/facturacion-electronica/afip','einvoice_afip','AFIP Argentina','Facturación electrónica'),('/finanzas/facturacion-electronica/sat-guatemala','einvoice_sat_gt','SAT Guatemala','Facturación electrónica'),('/finanzas/facturacion-electronica/emisiones-venezuela','einvoice_ve','Emisiones Venezuela','Facturación electrónica'),
        ('/almacen','warehouse','Almacén','Inventario'),('/almacen/stock-dispositivos','warehouse_stock','Stock dispositivos de red','Stock'),('/almacen/lista-dispositivos','warehouse_devices','Lista dispositivos de red','Dispositivos'),('/almacen/otros-articulos','warehouse_articles','Otros artículos','Artículos'),('/almacen/otros-servicios','warehouse_services','Otros servicios','Servicios'),('/almacen/proveedores','warehouse_suppliers','Proveedores','Proveedores'),('/almacen/sucursales','warehouse_branches','Sucursales','Sucursales'),('/almacen/asignar-staff','warehouse_staff','Asignar artículos staff','Asignaciones'),('/almacen/mi-inventario','warehouse_inventory','Mi inventario','Inventario'),('/almacen/log','warehouse_log','Log almacén','Movimientos'),
        ('/administracion/equipo','team','Mi equipo','Usuarios internos'),('/administracion/roles','roles','Roles y permisos','Permisos'),('/soporte/tecnico','technician_panel','Panel técnico','Agenda técnica'),('/dashboard/tecnico/asistencia','technician_attendance','Asistencia','Asistencia'),('/soporte/tickets/nuevos','support_new','Tickets nuevos','Tickets'),('/soporte/tickets/sin-asignar','support_unassigned','Sin asignar','Tickets'),('/soporte/tickets/asignados','support_assigned','Asignados','Tickets'),('/soporte/tickets/en-progreso','support_progress','En progreso','Tickets'),('/soporte/tickets/resueltos','support_resolved','Resueltos','Tickets'),('/soporte/tickets/cerrados','support_closed','Cerrados','Tickets'),('/soporte/tickets/buscar','support_search','Buscar tickets','Búsqueda'),('/empresas','companies','Empresas','Multiempresa'),
        ('/olt/dashboard','olt_dashboard_page','Dashboard OLT','Estado OLT'),('/olt','olt_dashboard','OLT','Gestión OLT'),('/olt/onu/autorizadas','olt_authorized','ONUs autorizadas','ONUs'),('/olt/onu/sin-autorizar','olt_unauthorized','ONUs sin autorizar','ONUs'),('/olt/onu/pre-autorizar','olt_pre_authorize','Pre-autorizar ONU','ONU'),('/olt/onu/pendientes','olt_pending','ONUs pendientes','ONU'),('/olt/modelos-onu','olt_models','Modelo de ONU','Modelos'),('/olt/planes-velocidad','olt_speed_plans','Planes de velocidad','Perfiles'),('/olt/mapa-ftth','ftth_map','Mapa FTTH','Red fibra'),('/salud-red','network_health','Salud de red','OLT y MikroTik'),('/olt/alertas','olt_alerts','Alertas OLT','Alertas'),('/tr069','tr069','TR069','Gestión remota'),
        ('/antenas/dashboard','antennas_dashboard','Dashboard Antenas','Resumen'),('/antenas/todas','antennas_all','Todas las antenas','Radios'),('/antenas/access-point','antennas_ap','Access Point','AP'),('/antenas/clientes','antennas_clients','Clientes / CPE','CPE'),('/antenas/ptp','antennas_ptp','PTP','PTP'),('/antenas/configuracion','antennas_config','Configuración de Antenas','Configuración'),
        ('/sistema/ia','system_ai','Asistente IA','Asistente'),('/sistema/manual','manual','Manual','Manual'),('/sistema/plantillas','templates','Plantillas','Plantillas'),('/sistema/descuentos-zona','zone_discounts','Descuento por zona','Descuentos'),('/sistema/logs','system_logs','Logs','Actividad'),('/sistema/portal-cliente','client_portal','Portal del cliente','Portal'),('/sistema/dominio-portal','portal_domain','Dominio personalizado','Dominio'),('/sistema/cuentas-bancarias','bank_accounts','Cuentas bancarias','Cuentas'),('/sistema/pasarelas-pago','payment_gateways','Pasarelas de pago','Pagos'),('/sistema/api-integracion','integration_api','API de integración','API'),('/sistema/tareas','periodic_tasks','Tareas periódicas','Automatización'),('/licencia','license_page','Licencia','Plan'),
        ('/settings','settings_company','Empresa y perfil','Empresa'),('/settings/temas','settings_themes','Temas','Apariencia'),('/settings/apks','settings_apks','APK','Aplicaciones'),('/settings/referidos','settings_referrals','Referidos','Referidos'),('/settings/dashboard-widgets','settings_widgets','Widgets dashboard','Widgets'),('/settings/preferencias','settings_general','Preferencias','Ajustes'),('/settings/servidor-correo','email_server','Servidor de correo','SMTP'),('/settings/xui-one','xui_dashboard','Xui One · Dashboard','Xui One'),('/settings/xui-one/lines','xui_lines','Xui One · Lines','Xui One'),('/settings/xui-one/streams','xui_streams','Xui One · Streams','Xui One'),('/settings/xui-one/down','xui_down','Xui One · Down','Xui One'),('/settings/xui-one/configuracion','xui_config','Xui One · Configuración','Xui One'),
        ('/hotspot/dashboard','hotspot_dashboard','Dashboard Hotspot','Hotspot'),('/hotspot/routers','hotspot_routers','Router Hotspot','Hotspot'),('/hotspot/perfiles','hotspot_profiles','User Profile','Hotspot'),('/hotspot/planes','hotspot_plans','Planes Hotspot','Hotspot'),('/hotspot/fichas/crear','hotspot_create_vouchers','Crear fichas','Hotspot'),('/hotspot/fichas','hotspot_vouchers','Listado de fichas','Hotspot'),('/hotspot/impresion','hotspot_print','Impresión de fichas','Hotspot'),('/hotspot/puntos-venta','hotspot_sales_points','Puntos de venta','Hotspot'),('/hotspot/punto-venta','hotspot_pos','Punto de venta','Hotspot'),('/hotspot/corte-caja','hotspot_cash_close','Corte de caja','Hotspot')
    ]
    for args in placeholders: _add(flask_app,*args)
