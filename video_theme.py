from flask import url_for
import app as appmodule
import menu_structure as m


def shell(title, body, active='dashboard'):
    finance_open = active in m.FINANCE_ITEMS or active in m.ACCOUNTING_ITEMS or active in m.E_INVOICE_ITEMS
    finance_bits = ''.join(m._link(k, *v, active) for k, v in m.FINANCE_ITEMS.items()) + m._group('Facturación electrónica', '▤', m.E_INVOICE_ITEMS, active, True) + m._group('Contabilidad', '▥', m.ACCOUNTING_ITEMS, active, True)
    finance = f'''<details class="navgroup"{' open' if finance_open else ''}><summary><span class="ico">▣</span><span>Finanzas</span><span class="chev">⌄</span></summary><div class="submenu">{finance_bits}</div></details>'''

    config_open = active in m.CONFIG_ITEMS or active in m.XUI_ITEMS
    config_bits = ''.join(m._link(k, *v, active) for k, v in m.CONFIG_ITEMS.items()) + m._group('Xui One', '▶', m.XUI_ITEMS, active, True)
    config = f'''<details class="navgroup"{' open' if config_open else ''}><summary><span class="ico">⚙</span><span>Configuración</span><span class="chev">⌄</span></summary><div class="submenu">{config_bits}</div></details>'''

    nav = ''.join([
        m._top('dashboard', '▦', 'Dashboard', active),
        m._group('Clientes', '👥', m.CLIENT_ITEMS, active),
        finance,
        m._group('Almacén', '▤', m.WAREHOUSE_ITEMS, active),
        m._group('Administración', '♢', m.ADMIN_ITEMS, active),
        m._group('Soporte Técnico', '◉', m.SUPPORT_ITEMS, active),
        '<div class="sep"></div>',
        *[m._top(k, *v, active) for k, v in m.NETWORK_ITEMS.items()],
        m._group('OLT / Fibra', '◉', m.OLT_ITEMS, active),
        m._group('Antenas', '⌁', m.ANTENNA_ITEMS, active),
        m._group('Sistema', '⚙', m.SYSTEM_ITEMS, active),
        m._top('license_page', '🔑', 'Licencia', active),
        config,
        m._group('Hotspot', '◉', m.HOTSPOT_ITEMS, active),
    ])

    css = appmodule.CSS + '''
    body{background:#f6f7f9;color:#20252b}
    .side{width:268px;padding:10px 10px 14px;background:#111822;overflow-y:auto;border-right:1px solid #202a36}
    .main{margin-left:268px}
    .brand{padding:10px 9px 13px;margin-bottom:7px;border-bottom:1px solid #27313d}
    .logo{width:48px;height:48px;border-radius:8px;background:linear-gradient(135deg,#f1f5f9,#cbd5e1);color:#1f2937;box-shadow:0 2px 8px #0004}
    .brand b{font-size:16px}.brand small{font-size:11px}
    .user{margin:7px 7px 12px;padding:10px 10px;border:0;border-bottom:1px solid #27313d;border-radius:0}
    .user b{font-size:13px}.user small{font-size:11px}
    .nav{margin-top:2px}.toplink,.navgroup summary,.sub{display:flex;align-items:center;gap:11px;border-radius:4px;color:#d3d9e1;cursor:pointer;text-decoration:none}
    .toplink{padding:10px 11px;margin:2px 0;font-size:13px;font-weight:700}
    .toplink:hover,.toplink.on{background:#14a95d;color:white}
    .navgroup{margin:2px 0}.navgroup summary{list-style:none;padding:10px 11px;font-size:13px;font-weight:700}.navgroup summary::-webkit-details-marker{display:none}.navgroup summary:hover{background:#172330}.navgroup[open]>summary{color:#fff}.chev{margin-left:auto;font-size:15px}.navgroup[open]>summary .chev{transform:rotate(180deg)}
    .submenu{padding:1px 0 5px 18px}.nested .submenu{padding-left:9px}.navgroup.nested{margin-left:7px;border-left:1px solid #ffffff18}.navgroup.nested>summary{font-size:12px;padding:8px 10px}
    .sub{padding:8px 10px;margin:1px 0;font-size:12px}.sub:hover{background:#172a38;color:#fff}.sub.on{background:#173624;color:#79e7a9;font-weight:800}.ico{width:20px;text-align:center;flex:0 0 20px;color:#a8b3c2}.toplink.on .ico{color:#fff}
    .footer-menu{color:#788492;font-size:11px;padding:15px 13px}.sep{height:1px;background:#ffffff14;margin:8px}
    .top{height:66px;padding:0 25px}.content{padding:24px 28px}.head h1{font-size:26px}.head p{margin-top:5px}
    .panel,.card{border-color:#e7eaee;box-shadow:0 1px 2px #00000008}
    @media(max-width:900px){.side{width:82px}.main{margin-left:82px}.navgroup summary span:not(.ico),.toplink span:not(.ico),.sub span:not(.ico),.footer-menu,.brand .text,.user{display:none}.submenu{padding-left:0}.navgroup.nested{margin-left:0;border-left:0}}
    '''

    return appmodule.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER Flash</b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav><div class="footer-menu">© 2026 INTER Flash Management</div></aside><main class="main"><header class="top"><div><small>BIENVENIDO</small><b>INTER Flash</b></div><a href="{{url_for('logout')}}">Salir</a></header><section class="content">{{body|safe}}</section></main></body></html>''', title=title, css=css, nav=nav, body=body)


def setup(flask_app):
    appmodule.shell = shell
