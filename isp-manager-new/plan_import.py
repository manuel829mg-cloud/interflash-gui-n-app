import re
from html import escape
from flask import request, redirect, url_for, flash
import app as base


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


def _parse_manual_profiles(text):
    """Accept RouterOS `ppp profile print detail` output or simple pipe/semicolon rows.

    Simple row examples:
      Plan 100 | 100 | 100 | 1500
      Plan 100 ; 100 ; 100 ; 1500
    RouterOS detail example:
      0 name="1-30M/130M-hioso" rate-limit="30M/130M"
    """
    text = str(text or '').replace('\r', '')
    found = []

    # RouterOS detail output may wrap across lines. Split records on a line that starts
    # with an index number, while retaining each record body.
    records = re.split(r'(?m)(?=^\s*\d+\s+)', text)
    for rec in records:
        name_m = re.search(r'\bname=(?:"([^"]+)"|([^\s]+))', rec)
        if not name_m:
            continue
        name = (name_m.group(1) or name_m.group(2) or '').strip()
        rate_m = re.search(r'\brate-limit=(?:"([^"]*)"|([^\s]+))', rec)
        rate = (rate_m.group(1) or rate_m.group(2) or '').strip() if rate_m else ''
        down, up = _parse_rate_limit(rate)
        if name:
            found.append({'name': name, 'download': down, 'upload': up, 'price': 0, 'source': 'RouterOS'})

    # If no RouterOS records were detected, accept easy bulk-entry rows.
    if not found:
        for raw_line in text.split('\n'):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            sep = '|' if '|' in line else (';' if ';' in line else None)
            if not sep:
                # Also allow: NAME 30M/130M
                pieces = line.rsplit(None, 1)
                if len(pieces) == 2 and '/' in pieces[1]:
                    down, up = _parse_rate_limit(pieces[1])
                    found.append({'name': pieces[0].strip(), 'download': down, 'upload': up, 'price': 0, 'source': 'Manual'})
                continue
            parts = [x.strip() for x in line.split(sep)]
            if not parts or not parts[0]:
                continue
            name = parts[0]
            try:
                down = int(float(parts[1])) if len(parts) > 1 and parts[1] else 0
            except (TypeError, ValueError):
                down = _speed_to_mbps(parts[1]) if len(parts) > 1 else 0
            try:
                up = int(float(parts[2])) if len(parts) > 2 and parts[2] else down
            except (TypeError, ValueError):
                up = _speed_to_mbps(parts[2]) if len(parts) > 2 else down
            try:
                price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            except (TypeError, ValueError):
                price = 0
            found.append({'name': name, 'download': down, 'upload': up, 'price': price, 'source': 'Manual'})

    # De-duplicate by name while preserving the first occurrence.
    unique = []
    seen = set()
    for item in found:
        key = item['name'].strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _insert_plan(c, name, download, upload, price):
    exists = c.execute('SELECT id FROM plans WHERE lower(trim(name))=lower(trim(?)) LIMIT 1', (name,)).fetchone()
    if exists:
        return False
    c.execute('INSERT INTO plans(name,download_mbps,upload_mbps,price) VALUES(?,?,?,?)',
              (name, int(download or 0), int(upload or 0), float(price or 0)))
    return True


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
            c.close()
            flash('Revisa la velocidad y el precio del plan.')
            return redirect(url_for('plans'))
        if not name:
            c.close()
            flash('Escribe el nombre del plan.')
            return redirect(url_for('plans'))
        if not _insert_plan(c, name, download, upload, price):
            c.close()
            flash('Ese plan ya existe.')
            return redirect(url_for('plans'))
        c.commit(); c.close()
        base.audit('PLAN_CREATE', name)
        flash('Plan creado correctamente.')
        return redirect(url_for('plans'))

    rows = c.execute('SELECT * FROM plans ORDER BY price,name').fetchall()
    try:
        synced = c.execute('SELECT COUNT(DISTINCT name) c FROM push_ppp_profiles').fetchone()['c']
    except Exception:
        synced = 0
    c.close()

    trs = ''.join(
        f'<tr><td><b>{escape(r["name"] or "")}</b></td>'
        f'<td>{int(r["download_mbps"] or 0)}/{int(r["upload_mbps"] or 0)} Mbps</td>'
        f'<td>RD${float(r["price"] or 0):,.2f}</td>'
        f'<td><span class="tag ok">{"ACTIVO" if r["active"] else "INACTIVO"}</span></td></tr>'
        for r in rows
    )

    body = f'''<div class="head"><div><h1>Planes</h1><p>Planes comerciales de Internet</p></div>
    <a class="btn blue" href="{url_for('plans_import_mikrotik')}">⇩ Importar planes</a></div>
    <div class="panel">
      <div style="padding:11px;border-radius:8px;background:#0b2740;color:#b9dcff;margin-bottom:13px"><b>{synced} perfiles MikroTik sincronizados.</b> También puedes entrar a “Importar planes” y pegarlos manualmente desde la terminal.</div>
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


def import_mikrotik():
    if not base.logged_in():
        return redirect(url_for('login'))

    c = base.db()

    if request.method == 'POST':
        action = request.form.get('action') or 'synced'

        if action == 'manual':
            parsed = _parse_manual_profiles(request.form.get('manual_profiles') or '')
            if not parsed:
                c.close()
                flash('No pude reconocer ningún plan. Pega la salida del MikroTik o usa: Nombre | Bajada | Subida | Precio.')
                return redirect(url_for('plans_import_mikrotik'))
            created = skipped = 0
            for item in parsed:
                if _insert_plan(c, item['name'], item['download'], item['upload'], item['price']):
                    created += 1
                else:
                    skipped += 1
            c.commit(); c.close()
            if created:
                base.audit('MANUAL_PLAN_IMPORT', f'{created} planes importados manualmente')
            flash(f'Importación manual terminada: {created} planes agregados' + (f' · {skipped} ya existían' if skipped else '') + '.')
            return redirect(url_for('plans'))

        raw_ids = request.form.getlist('profile_ids')
        ids = []
        for value in raw_ids:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                pass
        if not ids:
            c.close()
            flash('Selecciona por lo menos un perfil del MikroTik.')
            return redirect(url_for('plans_import_mikrotik'))

        marks = ','.join('?' for _ in ids)
        profiles = c.execute(f'SELECT * FROM push_ppp_profiles WHERE id IN ({marks}) ORDER BY id', ids).fetchall()
        created = skipped = 0
        for p in profiles:
            name = (p['name'] or '').strip()
            if not name:
                continue
            parsed_down, parsed_up = _parse_rate_limit(p['rate_limit'])
            try:
                download = int(request.form.get(f'download_{p["id"]}') or parsed_down or 0)
            except (TypeError, ValueError):
                download = parsed_down
            try:
                upload = int(request.form.get(f'upload_{p["id"]}') or parsed_up or 0)
            except (TypeError, ValueError):
                upload = parsed_up
            try:
                price = float(request.form.get(f'price_{p["id"]}') or 0)
            except (TypeError, ValueError):
                price = 0
            if _insert_plan(c, name, download, upload, price):
                created += 1
            else:
                skipped += 1

        c.commit(); c.close()
        if created:
            base.audit('MIKROTIK_PLAN_IMPORT', f'{created} perfiles importados como planes')
        flash(f'Importación terminada: {created} planes agregados' + (f' · {skipped} ya existían' if skipped else '') + '.')
        return redirect(url_for('plans'))

    profiles = c.execute('SELECT * FROM push_ppp_profiles ORDER BY router_name,name').fetchall()
    existing = {str(r['name'] or '').strip().lower() for r in c.execute('SELECT name FROM plans').fetchall()}
    c.close()

    rows = []
    available = 0
    for p in profiles:
        name = (p['name'] or '').strip()
        down, up = _parse_rate_limit(p['rate_limit'])
        already = name.lower() in existing if name else False
        if already:
            choose = '<span class="tag ok">YA IMPORTADO</span>'
        else:
            choose = f'<input class="profile-check" type="checkbox" name="profile_ids" value="{p["id"]}" style="width:20px;height:20px">'
            available += 1
        rows.append(f'''<tr>
          <td>{choose}</td>
          <td><b>{escape(name or '-')}</b><br><span class="muted">{escape(p['router_name'] or 'CCR2116')}</span></td>
          <td class="mono">{escape(p['rate_limit'] or '-')}</td>
          <td><input class="field" style="width:105px" type="number" min="0" name="download_{p['id']}" value="{down}"></td>
          <td><input class="field" style="width:105px" type="number" min="0" name="upload_{p['id']}" value="{up}"></td>
          <td><input class="field" style="width:125px" type="number" min="0" step="0.01" name="price_{p['id']}" value="0"></td>
        </tr>''')

    table = ''.join(rows) or '<tr><td colspan="6" class="muted">No hay perfiles sincronizados. Usa la importación manual de arriba.</td></tr>'
    body = f'''<div class="head"><div><h1>Importar planes</h1><p>Puedes pegarlos manualmente o seleccionar perfiles sincronizados.</p></div><a class="btn" href="{url_for('plans')}">← Volver</a></div>

    <div class="panel" style="border:1px solid #0d63f6">
      <h3 style="margin-top:0">Importación manual desde MikroTik</h3>
      <div style="padding:11px;border-radius:8px;background:#0b2740;color:#b9dcff;margin-bottom:12px">
        En la terminal del MikroTik ejecuta <b>/ppp profile print detail without-paging</b>, copia el resultado completo y pégalo aquí. También acepta una línea por plan con el formato <b>Nombre | Bajada | Subida | Precio</b>.
      </div>
      <form method="post">
        <input type="hidden" name="action" value="manual">
        <textarea class="field" name="manual_profiles" style="width:100%;height:220px;font-family:Consolas,monospace" placeholder='Ejemplo RouterOS:\n0 name="1-30M/130M-hioso" rate-limit="30M/130M"\n\nO manual:\nPlan 100 | 100 | 100 | 1500'></textarea>
        <div style="margin-top:10px"><button class="btn green" type="submit">Importar manualmente</button></div>
      </form>
    </div>

    <div class="panel">
      <div style="padding:11px;border-radius:8px;background:#063f2a;color:#9ff0c8;margin-bottom:12px"><b>Perfiles sincronizados.</b> Encontré {len(profiles)} perfiles · {available} disponibles para importar.</div>
      <form method="post" onsubmit="return document.querySelectorAll('.profile-check:checked').length ? confirm('¿Importar los planes seleccionados?') : (alert('Selecciona por lo menos un perfil.'), false)">
        <input type="hidden" name="action" value="synced">
        <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:7px"><input id="select-all-plans" type="checkbox" style="width:20px;height:20px"> <b>Seleccionar todos</b></label>
          <button class="btn green" type="submit">Importar seleccionados</button>
        </div>
        <table class="table"><tr><th>Elegir</th><th>Perfil / Router</th><th>Rate limit</th><th>Bajada Mbps</th><th>Subida Mbps</th><th>Precio RD$</th></tr>{table}</table>
      </form>
    </div>
    <script>document.getElementById('select-all-plans').addEventListener('change',function(){{document.querySelectorAll('.profile-check').forEach(x=>x.checked=this.checked)}})</script>'''
    return base.shell('Importar planes', body, 'plans')


def setup(app):
    app.view_functions['plans'] = plans_page
    app.add_url_rule('/plans/import-mikrotik', endpoint='plans_import_mikrotik', view_func=import_mikrotik, methods=['GET','POST'])
