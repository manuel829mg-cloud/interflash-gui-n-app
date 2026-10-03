from flask import redirect, url_for
import app as appmodule

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
    'invoices': ('▤', 'Facturas'),
    'payments': ('💳', 'Pagos pendientes'),
}
ADMIN_ITEMS = {
    'routers': ('⌁', 'Routers'),
    'plans': ('◉', 'Planes'),
    'zones': ('⌖', 'Zonas'),
    'whatsapp': ('◯', 'WhatsApp'),
    'admin': ('⚙', 'Configuración'),
}


def _link(endpoint, icon, label, active):
    cls = 'sub on' if active == endpoint else 'sub'
    try:
        href = url_for(endpoint)
    except Exception:
        href = '#'
    return f'<a class="{cls}" href="{href}"><span class="ico">{icon}</span><span>{label}</span></a>'


def _group(title, icon, items, active):
    opened = ' open' if active in items else ''
    links = ''.join(_link(k, *v, active) for k, v in items.items())
    return f'''<details class="navgroup"{opened}>
      <summary><span class="ico">{icon}</span><span>{title}</span><span class="chev">⌄</span></summary>
      <div class="submenu">{links}</div>
    </details>'''


def shell(title, body, active='dashboard'):
    client_group = _group('Clientes', '👥', CLIENT_ITEMS, active)
    finance_group = _group('Finanzas', '▣', FINANCE_ITEMS, active)
    admin_group = _group('Administración', '♢', ADMIN_ITEMS, active)
    dashboard_cls = 'toplink on' if active == 'dashboard' else 'toplink'
    warehouse_cls = 'toplink on' if active == 'warehouse' else 'toplink'
    support_cls = 'toplink on' if active == 'support' else 'toplink'
    nav = f'''
      <a class="{dashboard_cls}" href="{url_for('dashboard')}"><span class="ico">▦</span><span>Dashboard</span></a>
      {client_group}
      {finance_group}
      <a class="{warehouse_cls}" href="{url_for('warehouse')}"><span class="ico">▤</span><span>Almacén</span></a>
      {admin_group}
      <a class="{support_cls}" href="{url_for('support')}"><span class="ico">◉</span><span>Soporte Técnico</span></a>
    '''
    css = appmodule.CSS + '''
    .side{width:280px;padding:18px 13px}.main{margin-left:280px}.nav{margin-top:12px}.toplink,.navgroup summary,.sub{display:flex;align-items:center;gap:12px;border-radius:9px;color:#d5dde6;cursor:pointer}.toplink{padding:12px 13px;margin:3px 0}.toplink:hover,.toplink.on{background:#183f82;color:white}.navgroup{margin:3px 0}.navgroup summary{list-style:none;padding:12px 13px;font-size:16px;font-weight:700}.navgroup summary::-webkit-details-marker{display:none}.navgroup summary:hover{background:#18222d}.navgroup[open] summary{color:#fff}.chev{margin-left:auto;font-size:18px}.submenu{padding:2px 0 6px 14px}.sub{padding:10px 12px;margin:2px 0;font-size:14px}.sub:hover{background:#172a40;color:#fff}.sub.on{background:linear-gradient(135deg,#2866d8,#1748a5);color:#fff;font-weight:800}.ico{width:22px;text-align:center;flex:0 0 22px}.brand{margin-bottom:8px}.footer-menu{color:#8090a0;font-size:12px;padding:14px 13px}@media(max-width:900px){.side{width:82px}.main{margin-left:82px}.navgroup summary span:not(.ico),.toplink span:not(.ico),.sub span:not(.ico),.footer-menu{display:none}.submenu{padding-left:0}}
    '''
    return appmodule.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav><div class="footer-menu">© 2026 INTER Flash Management</div></aside><main class="main"><header class="top"><div><small>BIENVENIDO</small><b>INTER Flash</b></div><a href="{{url_for('logout')}}">Salir</a></header><section class="content">{{body|safe}}</section></main></body></html>''', title=title, css=css, nav=nav, body=body)


def _placeholder(title, text, active):
    if not appmodule.auth():
        return redirect(url_for('login'))
    body = f'''<div class="head"><div><h1>{title}</h1><p>{text}</p></div></div>
    <div class="panel"><div class="empty"><b>{title}</b><br><br>Este módulo ya está incluido en la estructura de INTER Flash y lo iremos conectando con las funciones reales.</div></div>'''
    return shell(title, body, active)


def setup(flask_app):
    appmodule.shell = shell

    if 'notifications_push' not in flask_app.view_functions:
        flask_app.add_url_rule('/notifications-push', 'notifications_push', lambda: _placeholder('Notificaciones push', 'Avisos y notificaciones para clientes', 'notifications_push'))
    if 'traffic' not in flask_app.view_functions:
        flask_app.add_url_rule('/traffic', 'traffic', lambda: _placeholder('Tráfico', 'Consumo y actividad de los clientes', 'traffic'))
    if 'installations' not in flask_app.view_functions:
        flask_app.add_url_rule('/installations', 'installations', lambda: _placeholder('Instalaciones', 'Control de instalaciones nuevas', 'installations'))
    if 'map_clients' not in flask_app.view_functions:
        flask_app.add_url_rule('/mapa', 'map_clients', lambda: _placeholder('Mapa', 'Ubicación y cobertura de clientes', 'map_clients'))
    if 'wifi_router' not in flask_app.view_functions:
        flask_app.add_url_rule('/wifi-router', 'wifi_router', lambda: _placeholder('Wifi Router', 'Gestión de routers WiFi de clientes', 'wifi_router'))
    if 'warehouse' not in flask_app.view_functions:
        flask_app.add_url_rule('/warehouse', 'warehouse', lambda: _placeholder('Almacén', 'Inventario de equipos y materiales', 'warehouse'))
