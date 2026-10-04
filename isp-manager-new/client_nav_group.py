import app as base


def setup():
    # "Extraer clientes" deja de mostrarse como opción principal.
    base.NAV[:] = [item for item in base.NAV if item[0] != 'client_extract']

    def grouped_shell(title, body, active='dashboard'):
        customer_group_active = active in ('customers', 'client_extract')
        group_style = '' if customer_group_active else 'display:none'
        arrow = '▾' if customer_group_active else '▸'

        links = []
        for ep, ic, label in base.NAV:
            if ep == 'customers':
                parent_on = ' on' if customer_group_active else ''
                sub_customers_on = ' on' if active == 'customers' else ''
                sub_extract_on = ' on' if active == 'client_extract' else ''
                links.append(f'''
                <div class="nav-group">
                  <a class="nav-parent{parent_on}" href="#" onclick="event.preventDefault();toggleClientMenu(this)">
                    <span>{ic}</span><span class="txt">{label}</span><span class="nav-arrow txt">{arrow}</span>
                  </a>
                  <div id="clientSubmenu" class="nav-sub" style="{group_style}">
                    <a class="nav-subitem{sub_customers_on}" href="{base.url_for('customers')}"><span>•</span><span class="txt">Ver clientes</span></a>
                    <a class="nav-subitem{sub_extract_on}" href="{base.url_for('client_extract')}"><span>⇩</span><span class="txt">Extraer clientes</span></a>
                  </div>
                </div>''')
            else:
                on = ' on' if active == ep else ''
                links.append(f'<a class="{on.strip()}" href="{base.url_for(ep)}"><span>{ic}</span><span class="txt">{label}</span></a>')

        links_html = ''.join(links)
        msgs = ''.join(f'<div class="flash">{m}</div>' for m in base.get_flashed_messages())
        extra_css = '''
        .nav-parent{position:relative}.nav-parent .nav-arrow{margin-left:auto;font-size:14px}
        .nav-sub{margin:2px 0 7px 16px;padding-left:9px;border-left:1px solid #27435f}
        .nav .nav-subitem{padding:8px 10px;margin:2px 0;font-size:13px;color:#9eb0c4}
        .nav .nav-subitem:hover,.nav .nav-subitem.on{background:#123457;color:#fff}
        '''
        script = '''
        <script>
        function toggleClientMenu(el){
          const menu=document.getElementById('clientSubmenu');
          const arrow=el.querySelector('.nav-arrow');
          const open=menu.style.display!=='none';
          menu.style.display=open?'none':'block';
          if(arrow) arrow.textContent=open?'▸':'▾';
        }
        </script>
        '''
        return base.render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · INTER Flash</title><style>{{css}}{{extra_css}}</style></head><body><div class="app"><aside class="side"><div class="brand"><div class="brandmark">IF</div><div class="txt"><b>INTER Flash</b><small>ISP Manager</small></div></div><nav class="nav">{{links|safe}}<div class="sep"></div><a href="{{url_for('logout')}}"><span>↪</span><span class="txt">Salir</span></a></nav><div class="system"><span class="dot"></span>Sistema en línea<br><br>MikroTik: sincronización segura</div></aside><main class="main"><header class="top"><input class="search" placeholder="Buscar clientes, facturas, ONU, IP..." onkeydown="if(event.key==='Enter'){location.href='{{url_for('customers')}}?q='+encodeURIComponent(this.value)}"><div class="user">Administrador · {{admin}}</div></header><section class="content">{{msgs|safe}}{{body|safe}}</section></main></div>{{script|safe}}</body></html>''', title=title, css=base.BASE_CSS, extra_css=extra_css, links=links_html, body=body, admin=base.ADMIN_USER, msgs=msgs, script=script)

    base.shell = grouped_shell
