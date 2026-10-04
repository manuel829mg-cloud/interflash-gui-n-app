import re
from html import escape
from flask import request, redirect, url_for, flash
import app as base


def esc(v):
    return escape('' if v is None else str(v))


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _speed_to_mbps(value):
    text = str(value or '').strip().lower()
    if not text:
        return 0
    m = re.match(r'^([0-9]+(?:\.[0-9]+)?)([kmg]?)', text)
    if not m:
        return 0
    number = float(m.group(1))
    unit = m.group(2)
    if unit == 'g':
        number *= 1000
    elif unit == 'k':
        number /= 1000
    return int(round(number))


def _parse_rate_limit(rate_limit):
    raw = str(rate_limit or '').strip()
    if not raw:
        return 0, 0
    first = raw.split()[0]
    parts = first.split('/')
    if len(parts) >= 2:
        upload = _speed_to_mbps(parts[0])
        download = _speed_to_mbps(parts[1])
        return download, upload
    speed = _speed_to_mbps(first)
    return speed, speed


def _parse_profile_name(name):
    text = str(name or '')
    m = re.search(r'(?i)(\d+(?:\.\d+)?\s*[kmg]?)[^0-9/]{0,3}/\s*(\d+(?:\.\d+)?\s*[kmg]?)', text)
    if not m:
        return 0, 0
    upload = _speed_to_mbps(m.group(1).replace(' ', ''))
    download = _speed_to_mbps(m.group(2).replace(' ', ''))
    return download, upload


def _insert_plan(c, name, download, upload, price):
    exists = c.execute('SELECT id FROM plans WHERE lower(trim(name))=lower(trim(?)) LIMIT 1', (name,)).fetchone()
    if exists:
        return False
    c.execute('INSERT INTO plans(name,download_mbps,upload_mbps,price) VALUES(?,?,?,?)',
              (name, int(download or 0), int(upload or 0), float(price or 0)))
    return True


def _router_names(c):
    names = []
    if _table_exists(c, 'push_router_agents'):
        names += [str(r['name'] or '').strip() for r in c.execute('SELECT name FROM push_router_agents ORDER BY id DESC').fetchall()]
    if _table_exists(c, 'push_pppoe_secrets'):
        names += [str(r['router_name'] or '').strip() for r in c.execute("SELECT DISTINCT router_name FROM push_pppoe_secrets WHERE COALESCE(router_name,'')<>''").fetchall()]
    if _table_exists(c, 'push_ppp_profiles'):
        names += [str(r['router_name'] or '').strip() for r in c.execute("SELECT DISTINCT router_name FROM push_ppp_profiles WHERE COALESCE(router_name,'')<>''").fetchall()]
    out = []
    seen = set()
    for n in names:
        if n and n.lower() not in seen:
            seen.add(n.lower()); out.append(n)
    return out


def _profiles_for_router(c, router):
    by_name = {}
    if _table_exists(c, 'push_ppp_profiles'):
        for r in c.execute('SELECT * FROM push_ppp_profiles WHERE router_name=? ORDER BY name', (router,)).fetchall():
            name = str(r['name'] or '').strip()
            if not name:
                continue
            by_name[name.lower()] = {'name': name, 'rate_limit': str(r['rate_limit'] or '').strip(), 'source': 'PPP Profile'}

    # Important fallback: even if the profile table has not arrived yet, every PPPoE
    # secret already tells us which MikroTik profile/plan it uses. This makes the
    # picker work immediately from the same synchronized data as Extraer Clientes.
    if _table_exists(c, 'push_pppoe_secrets'):
        rows = c.execute("SELECT DISTINCT profile FROM push_pppoe_secrets WHERE router_name=? AND COALESCE(profile,'')<>'' ORDER BY profile", (router,)).fetchall()
        for r in rows:
            name = str(r['profile'] or '').strip()
            if name and name.lower() not in by_name:
                by_name[name.lower()] = {'name': name, 'rate_limit': '', 'source': 'Clientes PPPoE'}

    out = sorted(by_name.values(), key=lambda x: x['name'].lower())
    for p in out:
        down, up = _parse_rate_limit(p['rate_limit'])
        if not down and not up:
            down, up = _parse_profile_name(p['name'])
        p['download'] = down
        p['upload'] = up
    return out


def _router_options(c, routers, selected):
    options = []
    for name in routers:
        count = len(_profiles_for_router(c, name))
        options.append(f'<option value="{esc(name)}" {"selected" if name == selected else ""}>{esc(name)} · {count} planes</option>')
    return ''.join(options)


def plans_page():
    if not base.logged_in():
        return redirect(url_for('login'))

    c = base.db()
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        try:
            download = int(request.form.get('download') or 0)
            upload = int(request.form.get('upload') or 0)
            price = float(request.form.get('price') or 0)
        except (TypeError, ValueError):
            c.close(); flash('Revisa la velocidad y el precio del plan.'); return redirect(url_for('plans'))
        if not name:
            c.close(); flash('Escribe el nombre del plan.'); return redirect(url_for('plans'))
        if not _insert_plan(c, name, download, upload, price):
            c.close(); flash('Ese plan ya existe.'); return redirect(url_for('plans'))
        c.commit(); c.close(); base.audit('PLAN_CREATE', name); flash('Plan creado correctamente.'); return redirect(url_for('plans'))

    rows = c.execute('SELECT * FROM plans ORDER BY price,name').fetchall()
    routers = _router_names(c)
    mikrotik_total = sum(len(_profiles_for_router(c, r)) for r in routers)
    c.close()

    trs = ''.join(
        f'<tr><td><b>{esc(r["name"])}</b></td>'
        f'<td>{int(r["download_mbps"] or 0)}/{int(r["upload_mbps"] or 0)} Mbps</td>'
        f'<td>RD${float(r["price"] or 0):,.2f}</td>'
        f'<td><span class="tag ok">{"ACTIVO" if r["active"] else "INACTIVO"}</span></td></tr>'
        for r in rows
    )

    body = f'''<div class="head"><div><h1>Planes</h1><p>Planes comerciales de Internet</p></div>
    <a class="btn blue" href="{url_for('plans_import_mikrotik')}">⇩ Extraer planes del MikroTik</a></div>
    <div class="panel">
      <div style="padding:11px;border-radius:8px;background:#0b2740;color:#b9dcff;margin-bottom:13px"><b>{mikrotik_total} perfiles/planes detectados en MikroTik.</b> Puedes buscarlos y escoger manualmente cuáles importar.</div>
      <form class="toolbar" method="post">
        <input class="field" name="name" placeholder="Nombre" required>
        <input class="field" type="number" name="download" placeholder="Bajada Mbps" required>
        <input class="field" type="number" name="upload" placeholder="Subida Mbps" required>
        <input class="field" type="number" step="0.01" name="price" placeholder="Precio RD$" required>
        <button class="btn green">Crear plan</button>
      </form>
      <table class="table"><tr><th>Plan</th><th>Velocidad</th><th>Precio</th><th>Estado</th></tr>{trs}</table>
    </div>'''
    return base.shell('Planes', body, 'plans')


def _plan_picker(router='', load=False):
    c = base.db()
    routers = _router_names(c)
    if not router and routers:
        router = routers[0]

    profiles = _profiles_for_router(c, router) if load and router else []
    existing = {str(r['name'] or '').strip().lower() for r in c.execute('SELECT name FROM plans').fetchall()}
    opts = _router_options(c, routers, router)
    c.close()

    rows = []
    available = 0
    for idx, p in enumerate(profiles):
        name = p['name']
        already = name.lower() in existing
        if not already:
            available += 1
        choose = '<span class="muted">—</span>' if already else f'<input class="plancheck" type="checkbox" name="plan_key" value="p{idx}" onchange="updateCount()">'
        status = '<span class="tag ok">YA IMPORTADO</span>' if already else '<span class="tag warn">DISPONIBLE</span>'
        search_blob = esc(f'{name} {p["rate_limit"]} {p["download"]} {p["upload"]}').lower()
        rows.append(f'''<tr class="planrow" data-search="{search_blob}">
          <td style="width:42px;text-align:center">{choose}</td>
          <td><b>{esc(name)}</b><br><span class="muted">{esc(p['source'])}</span></td>
          <td>{esc(p['rate_limit'] or '-')}</td>
          <td><input class="field" type="number" min="0" name="download_p{idx}" value="{p['download']}" style="width:90px"></td>
          <td><input class="field" type="number" min="0" name="upload_p{idx}" value="{p['upload']}" style="width:90px"></td>
          <td><input class="field" type="number" min="0" step="0.01" name="price_p{idx}" value="0" style="width:110px"></td>
          <td>{status}</td>
          <input type="hidden" name="name_p{idx}" value="{esc(name)}">
        </tr>''')

    list_html = ''.join(rows) if rows else '<tr><td colspan="7" class="muted" style="padding:26px;text-align:center">Selecciona el router y pulsa <b>Buscar planes</b>.</td></tr>'
    disabled = 'disabled' if not routers else ''

    modal = f'''
    <style>
      .extract-overlay{{min-height:calc(100vh - 130px);display:grid;place-items:start center;padding:28px 10px}}
      .extract-modal{{width:min(1060px,97vw);background:#eef1f5;color:#172033;border:1px solid #cbd2db;border-radius:24px;padding:28px;box-shadow:0 30px 90px #0008}}
      .extract-modal .field{{background:white;color:#172033;border-color:#b9c1cc}}
      .extract-modal .muted{{color:#667085}}
      .extract-modal table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}}
      .extract-modal th,.extract-modal td{{padding:11px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:13px}}
      .extract-modal th{{font-size:11px;color:#667085;text-transform:uppercase;background:#f8fafc}}
      .extract-actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}}
      .extract-search{{display:grid;grid-template-columns:220px 1fr;gap:10px;margin:14px 0}}
      @media(max-width:760px){{.extract-search{{grid-template-columns:1fr}}.extract-modal{{padding:18px}}}}
    </style>
    <div class="extract-overlay"><div class="extract-modal">
      <div style="display:flex;justify-content:space-between;gap:16px;align-items:start">
        <div><h2 style="margin:0 0 7px;font-size:28px">Extraer planes de Internet del router</h2><p class="muted" style="margin:0">Lee los perfiles PPP del MikroTik y te deja escoger manualmente cuáles convertir en planes de INTER Flash.</p></div>
        <a href="{url_for('plans')}" style="font-size:28px;color:#667085">×</a>
      </div>
      <form method="get" action="{url_for('plans_import_mikrotik')}" class="extract-search">
        <select class="field" name="router" {disabled}>{opts or '<option>Sin router sincronizado</option>'}</select>
        <div style="display:flex;gap:10px;min-width:0">
          <button class="btn" name="load" value="1" style="background:white;color:#172033;border-color:#c5ccd5;min-width:150px" {disabled}>Buscar planes</button>
          <input id="planSearch" class="field" placeholder="Buscar plan o velocidad..." oninput="filterRows()" style="min-width:0;flex:1">
        </div>
      </form>
      <form method="post" action="{url_for('plans_import_mikrotik')}" onsubmit="return confirmImport()">
        <input type="hidden" name="router" value="{esc(router)}">
        <div style="max-height:460px;overflow:auto;border:1px solid #d7dce3;border-radius:12px">
          <table><thead><tr><th><input id="selectAll" type="checkbox" onchange="toggleAll(this)"></th><th>Plan / Perfil PPP</th><th>Rate limit</th><th>Bajada</th><th>Subida</th><th>Precio RD$</th><th>Estado</th></tr></thead><tbody>{list_html}</tbody></table>
        </div>
        <div class="extract-actions">
          <button type="button" class="btn" onclick="toggleAll({{checked:true}});document.getElementById('selectAll').checked=true">Todos disponibles</button>
          <span class="muted">{len(profiles)} planes encontrados · {available} disponibles para importar</span>
          <span style="flex:1"></span>
          <a class="btn" href="{url_for('plans')}">Cancelar</a>
          <button id="importBtn" class="btn green" type="submit">Importar seleccionados (0)</button>
        </div>
      </form>
    </div></div>
    <script>
      function visibleChecks(){{return [...document.querySelectorAll('.planrow')].filter(r=>r.style.display!=='none').map(r=>r.querySelector('.plancheck')).filter(Boolean)}}
      function updateCount(){{const n=document.querySelectorAll('.plancheck:checked').length;document.getElementById('importBtn').textContent='Importar seleccionados ('+n+')'}}
      function toggleAll(src){{visibleChecks().forEach(c=>c.checked=!!src.checked);updateCount()}}
      function filterRows(){{const q=(document.getElementById('planSearch').value||'').toLowerCase().trim();document.querySelectorAll('.planrow').forEach(r=>{{r.style.display=!q||r.dataset.search.includes(q)?'':'none'}})}}
      function confirmImport(){{const n=document.querySelectorAll('.plancheck:checked').length;if(!n){{alert('Selecciona por lo menos un plan.');return false}}return confirm('¿Importar '+n+' plan(es) seleccionado(s) a la plataforma?')}}
      updateCount();
    </script>'''
    return base.shell('Extraer planes', modal, 'plans')


def import_mikrotik():
    if not base.logged_in():
        return redirect(url_for('login'))

    if request.method == 'GET':
        router = (request.args.get('router') or '').strip()
        load = request.args.get('load') == '1'
        return _plan_picker(router, load)

    router = (request.form.get('router') or '').strip()
    selected = [x.strip() for x in request.form.getlist('plan_key') if x.strip()]
    if not selected:
        flash('Selecciona por lo menos un plan para importar.')
        return redirect(url_for('plans_import_mikrotik', router=router, load=1))

    c = base.db()
    created = skipped = 0
    for key in selected:
        name = (request.form.get(f'name_{key}') or '').strip()
        if not name:
            skipped += 1; continue
        try:
            download = int(float(request.form.get(f'download_{key}') or 0))
        except (TypeError, ValueError):
            download = 0
        try:
            upload = int(float(request.form.get(f'upload_{key}') or 0))
        except (TypeError, ValueError):
            upload = 0
        try:
            price = float(request.form.get(f'price_{key}') or 0)
        except (TypeError, ValueError):
            price = 0
        if _insert_plan(c, name, download, upload, price):
            created += 1
        else:
            skipped += 1

    c.commit(); c.close()
    if created:
        base.audit('MIKROTIK_PLAN_IMPORT', f'{router}: {created} planes importados')
    flash(f'Importación terminada: {created} planes agregados' + (f' · {skipped} ya existían o fueron omitidos' if skipped else '') + '.')
    return redirect(url_for('plans'))


def setup(app):
    app.view_functions['plans'] = plans_page
    app.add_url_rule('/plans/import-mikrotik', endpoint='plans_import_mikrotik', view_func=import_mikrotik, methods=['GET','POST'])
