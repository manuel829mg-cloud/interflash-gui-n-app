import app as base
import menu_icons

def setup():
    base.NAV[:] = [item for item in base.NAV if item[0] != 'client_extract']

    def grouped_shell(title, body, active='dashboard'):
        nav={ep:(ic,label) for ep,ic,label in base.NAV}
        used=set()

        def item(ep, icon=None, label=None, sub=False):
            if ep not in nav: return ''
            used.add(ep); ic,lab=nav[ep]
            ic=icon or ic; lab=label or lab
            on=' on' if active==ep else ''
            cls='nav-subitem' if sub else 'nav-single'
            return f'<a class="{cls}{on}" href="{base.url_for(ep)}">{menu_icons.icon(ep, lab)}<span class="txt">{lab}</span></a>'

        def group(key, icon, label, endpoints):
            children=''.join(item(ep,sub=True) for ep in endpoints if ep in nav)
            if not children: return ''
            is_open=active in endpoints
            display='block' if is_open else 'none'
            arrow='⌄' if is_open else '›'
            parent_on=' on' if is_open else ''
            return f'''<div class="nav-group">
              <a class="nav-parent{parent_on}" href="#" onclick="event.preventDefault();toggleSideGroup('{key}',this)">
                {menu_icons.icon(key, label)}<span class="txt">{label}</span><span class="nav-arrow txt">{arrow}</span>
              </a>
              <div id="group-{key}" class="nav-sub" style="display:{display}">{children}</div>
            </div>'''

        parts=[]
        parts.append(item('dashboard','▦','Dashboard'))
        if 'whatsapp_inbox' in nav:
            parts.append(f'<a class="nav-single" href="{base.url_for("whatsapp_chatbot")}" title="IA / Automatización" aria-label="IA / Automatización">{menu_icons.icon("automation")}<span class="txt">IA / Automatización</span></a>')
        parts.append(group('clientes','♙','Clientes',['customers','client_extract','customer_trash']))
        parts.append(group('finanzas','▤','Finanzas',['invoices','payments','expenses_page','banks_page']))
        # Almacén se mostrará automáticamente cuando se agregue un módulo de inventario.
        warehouse=[ep for ep in ('inventory_page','warehouse_page','stock_page','equipment_page') if ep in nav]
        if warehouse: parts.append(group('almacen','▣','Almacén',warehouse))
        parts.append(group('admin','♢','Administración',['users_page','settings_page','audit_page','reports_admin','reports_page','backup_center','automation_page']))
        parts.append(group('soporte','◉','Soporte Técnico',['tickets_page','installations_page','monitoring_page','mikrotik_commands']))
        parts.append(item('routers','⌁','Routers'))
        parts.append(item('router_push_view','⌁','Routers'))
        parts.append(item('wan_lines','◫','Líneas'))
        parts.append(item('plans','◉','Planes'))
        parts.append(item('zones_page','⌖','Zonas'))
        parts.append(item('whatsapp_chat','◯','WhatsApp'))
        parts.append(item('whatsapp_inbox','◯','WhatsApp'))
        parts.append(group('olt','◉','OLT',['onu_page','onu_overview']))

        # Preserve any installed module not yet assigned to a section.
        extras=[]
        hidden={'whatsapp_page'}
        for ep,(ic,label) in nav.items():
            if ep not in used and ep not in hidden:
                extras.append(item(ep,ic,label))
        if extras:
            parts.append('<div class="nav-divider"></div>'+''.join(extras))

        links_html=''.join(parts)
        msgs=''.join(f'<div class="flash">{m}</div>' for m in base.get_flashed_messages())
        user=base.session.get('user') or base.ADMIN_USER or 'Manuel'
        role=(base.session.get('role') or 'ADMIN').upper()
        role_label='Administrador' if role=='ADMIN' else role.title()

        extra_css='''
        .app{grid-template-columns:270px 1fr}
        .side{background:#0c1a2c;border-right:1px solid #1c3149;padding:16px 14px;box-shadow:5px 0 24px #0002}
        .side .brand{justify-content:center;padding:0 8px 12px}
        .side .brand .txt{display:none}
        .side .brandmark.brandmark-logo{width:76px!important;height:76px!important;flex-basis:76px!important}
        .side .brandmark.brandmark-logo img{width:76px!important;height:76px!important}
        .side-user{display:flex;align-items:center;gap:12px;padding:13px;margin:0 0 18px;background:#142740;border:1px solid #203b5a;border-radius:4px;box-shadow:0 3px 12px #0002}
        .side-avatar{width:48px;height:48px;border-radius:5px;background:#16d66f;display:grid;place-items:center;color:#07351f;font-weight:900;font-size:18px;flex:0 0 48px}
        .side-user b{display:block;font-size:16px;color:#fff}.side-user small{display:block;color:#9db1ca;margin-top:4px;font-size:13px}
        .nav{display:flex;flex-direction:column;gap:3px}.nav a{margin:0;border-radius:5px;padding:11px 12px;color:#d8e2ef;font-weight:700}
        .nav a:hover{background:#152a45;color:#fff}.nav a.on{background:#1b3555;color:#fff}
        .nav-parent{display:flex!important;align-items:center}.nav-parent .nav-arrow{margin-left:auto;font-size:21px;color:#83a7d3;line-height:1}
        .menu-icon{width:27px;min-width:27px;text-align:center;font-size:20px;color:#86b7e8}
        .nav-sub{margin:2px 0 5px 39px;padding-left:8px;border-left:1px solid #294969}
        .nav .nav-subitem{padding:8px 10px;font-size:13px;color:#9fb3ca;font-weight:600}
        .nav .nav-subitem .menu-icon{width:15px;min-width:15px;font-size:12px}
        .nav .nav-subitem:hover,.nav .nav-subitem.on{background:#173858;color:#fff}
        .nav-divider{height:1px;background:#20364e;margin:8px 6px}
        .side-footer{font-size:11px;color:#637d9a;text-align:center;padding:18px 4px 8px}
        .side .system{display:none}
        @media(max-width:850px){
          .app{grid-template-columns:82px 1fr}.side{padding:12px 8px}.side-user{padding:8px;justify-content:center}.side-user .txt{display:none}.side-avatar{width:44px;height:44px;flex-basis:44px}
          .side .brandmark.brandmark-logo{width:58px!important;height:58px!important;flex-basis:58px!important}.side .brandmark.brandmark-logo img{width:58px!important;height:58px!important}
          .nav-sub{margin-left:8px;padding-left:0;border:0}.nav .nav-subitem{padding:9px}.menu-icon{width:28px;min-width:28px}.side-footer{display:none}
        }
        '''
        extra_css += menu_icons.CSS
        script='''
        <script>
        function toggleMobileMenu(force){
          const open=typeof force==='boolean'?force:!document.body.classList.contains('menu-open');
          document.body.classList.toggle('menu-open',open);
          const button=document.querySelector('.menu-toggle');
          button.setAttribute('aria-expanded',String(open));
          button.setAttribute('aria-label',open?'Cerrar menú':'Abrir menú');
          if(!open) button.focus();
        }
        document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('menu-open'))toggleMobileMenu(false)});
        function toggleSideGroup(key,el){
          const menu=document.getElementById('group-'+key);
          const arrow=el.querySelector('.nav-arrow');
          const open=menu.style.display!=='none';
          menu.style.display=open?'none':'block';
          if(arrow) arrow.textContent=open?'›':'⌄';
        }
        </script>'''
        return base.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}{{extra_css}}</style></head><body><div class="app">
        <button class="menu-shade" aria-label="Cerrar menú" onclick="toggleMobileMenu(false)"></button><aside class="side" id="main-menu"><div class="brand"><div class="brandmark">IF</div><div class="txt"><b>INTER Flash</b><small>ISP Manager</small></div></div>
        <div class="side-user"><div class="side-avatar">{{initial}}</div><div class="txt"><b>{{user}}</b><small>{{role}}</small></div></div>
        <nav class="nav">{{links|safe}}<div class="nav-divider"></div><a class="nav-single" href="{{url_for('logout')}}">{{logout_icon|safe}}<span class="txt">Salir</span></a></nav>
        <div class="side-footer">© 2026 INTER Flash Management</div></aside>
        <main class="main"><header class="top"><button type="button" class="btn menu-toggle" aria-label="Abrir menú" aria-controls="main-menu" aria-expanded="false" onclick="toggleMobileMenu()">☰</button><input class="search" placeholder="Buscar clientes, facturas, ONU, IP..." onkeydown="if(event.key==='Enter'){location.href='{{url_for('customers')}}?q='+encodeURIComponent(this.value)}"><div class="user">{{role}} · {{user}}</div></header><section class="content">{{msgs|safe}}{{body|safe}}</section></main>
        </div>{{script|safe}}</body></html>''',logout_icon=menu_icons.icon("logout"),title=title,css=base.BASE_CSS,extra_css=extra_css,links=links_html,body=body,user=user,role=role_label,initial=(user[:1] or 'M').upper(),msgs=msgs,script=script)

    base.shell=grouped_shell
