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
        m._top('dashboard', '⌂', 'Dashboard', active),
        m._group('Clientes', '👥', m.CLIENT_ITEMS, active),
        finance,
        m._top('routers', '⌁', 'Routers', active),
        m._top('plans', '▣', 'Planes', active),
        m._top('zones', '⌖', 'Zonas', active),
        m._top('whatsapp', '◯', 'WhatsApp', active),
        m._group('OLT / Fibra', '◉', m.OLT_ITEMS, active),
        m._group('Soporte Técnico', '◉', m.SUPPORT_ITEMS, active),
        m._group('Administración', '♢', m.ADMIN_ITEMS, active),
        config,
    ])

    css = appmodule.CSS + '''
    :root{--bg:#08111f;--panel:#0f1b2b;--panel2:#122238;--line:#22344d;--text:#e9f1fb;--muted:#8ea2ba;--blue:#1f73ff;--green:#0acb79;--orange:#ff9d19;--red:#ff4659;--purple:#7f35f5;--cyan:#15bfd2}
    *{box-sizing:border-box}body{background:radial-gradient(circle at 70% -20%,#153252 0,#08111f 45%,#060c15 100%);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}
    a{color:inherit}.side{width:242px;padding:12px 10px 18px;background:linear-gradient(180deg,#071321,#08101b);overflow-y:auto;border-right:1px solid #1b2c42;box-shadow:10px 0 30px #0003}.main{margin-left:242px;min-height:100vh}
    .brand{padding:13px 10px 16px;margin:0 0 9px;border-bottom:1px solid #1d3048}.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#168fff,#19c6dd);color:#fff;box-shadow:0 8px 22px #1489ff33;font-weight:900}.brand b{font-size:18px;letter-spacing:.2px}.brand small{font-size:10px;letter-spacing:2px;color:#88a5c1;text-transform:uppercase}
    .user{margin:8px 7px 12px;padding:11px;border:1px solid #1c3048;background:#0b1726;border-radius:10px}.user b{font-size:13px;color:#fff}.user small{font-size:11px;color:#7f96ad}
    .nav{margin-top:2px}.toplink,.navgroup summary,.sub{display:flex;align-items:center;gap:11px;border-radius:8px;color:#c6d2df;cursor:pointer;text-decoration:none;transition:.18s ease}.toplink{padding:10px 11px;margin:3px 0;font-size:13px;font-weight:700}.toplink:hover,.toplink.on{background:linear-gradient(90deg,#176dff,#1e7fff);color:#fff;box-shadow:0 6px 18px #0c62ff25}
    .navgroup{margin:3px 0}.navgroup summary{list-style:none;padding:10px 11px;font-size:13px;font-weight:700}.navgroup summary::-webkit-details-marker{display:none}.navgroup summary:hover{background:#10243a;color:#fff}.navgroup[open]>summary{color:#fff}.chev{margin-left:auto;font-size:14px}.navgroup[open]>summary .chev{transform:rotate(180deg)}
    .submenu{padding:2px 0 5px 18px}.nested .submenu{padding-left:8px}.navgroup.nested{margin-left:6px;border-left:1px solid #ffffff14}.navgroup.nested>summary{font-size:12px;padding:8px 10px}.sub{padding:8px 10px;margin:1px 0;font-size:12px;color:#96aabd}.sub:hover{background:#10243a;color:#fff}.sub.on{background:#123359;color:#69aaff;font-weight:800}.ico{width:20px;text-align:center;flex:0 0 20px;color:#89a8c7}.toplink.on .ico{color:#fff}
    .footer-menu{color:#5e7388;font-size:10px;padding:15px 13px}.sep{height:1px;background:#ffffff12;margin:8px}
    .top{height:70px;padding:0 24px;background:#0b1625e8;border-bottom:1px solid #1b2d44;backdrop-filter:blur(10px);color:#fff}.top small{color:#6f8aa4}.content{padding:18px 16px 28px}.head h1{font-size:25px;color:#fff}.head p{color:#7f95ab}.btn{background:#17283e;color:#dce8f5;border:1px solid #2b405a}.btn:hover{background:#1d3350}.green{background:#08b96d!important;border-color:#08b96d!important;color:#fff}.blue{background:#176dff!important;border-color:#176dff!important;color:#fff}.red{background:#e63c50!important;border-color:#e63c50!important;color:#fff}
    .panel,.card{background:linear-gradient(180deg,#101d2e,#0d1928);border:1px solid #21344c;color:#dce7f3;box-shadow:0 12px 30px #0002;border-radius:10px}.label,th{color:#7890a7}.muted,small{color:#7f94aa}.num{color:#fff}.field label{color:#a5b5c6}.field input,.field select,input,select{background:#0b1726!important;color:#dce7f3!important;border-color:#2a3f58!important}.notice{background:#102a46;color:#9fd0ff;border:1px solid #1a426b}.empty{color:#71869b}table{color:#dbe6f2}th,td{border-bottom:1px solid #1d2f45}tr:hover td{background:#0f2135}.tag.ok,.ok{background:#0b5b42;color:#55efad}.tag.bad,.bad{background:#5d2330;color:#ff8e9b}.tag.pending,.pending{background:#5f491c;color:#ffd363}
    @media(max-width:900px){.side{width:82px}.main{margin-left:82px}.navgroup summary span:not(.ico),.toplink span:not(.ico),.sub span:not(.ico),.footer-menu,.brand .text,.user{display:none}.submenu{padding-left:0}.navgroup.nested{margin-left:0;border-left:0}.content{padding:14px 10px}}
    '''

    return appmodule.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}</style></head><body><aside class="side"><div class="brand"><div class="logo">IF</div><div class="text"><b>INTER <span style="color:#26a4ff">Flash</span></b><small>Management</small></div></div><div class="user"><b>Manuel</b><small>Administrador</small></div><nav class="nav">{{nav|safe}}</nav><div class="footer-menu">INTER Flash · 2026</div></aside><main class="main"><header class="top"><div><small>PANEL DE CONTROL</small><b>INTER Flash Management</b></div><div style="display:flex;align-items:center;gap:18px"><span style="font-size:12px;color:#42e5a3">● MikroTik sincronizado</span><a href="{{url_for('logout')}}">Salir</a></div></header><section class="content">{{body|safe}}</section></main></body></html>''', title=title, css=css, nav=nav, body=body)


def setup(flask_app):
    appmodule.shell = shell
