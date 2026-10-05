from flask import request, redirect, url_for, flash
import app as base
import business_suite as bs


def esc(v):
    return bs.esc(v)


def _time12(value):
    try:
        hh, mm = (value or '14:00').split(':', 1)
        h = int(hh)
        m = int(mm)
        suffix = 'AM' if h < 12 else 'PM'
        h12 = h % 12 or 12
        return f'{h12}:{m:02d} {suffix}'
    except Exception:
        return str(value or '-')


def _time_options(selected='14:00'):
    selected = selected or '14:00'
    values = [f'{hour:02d}:{minute:02d}' for hour in range(24) for minute in range(0, 60, 5)]
    if selected not in values:
        values.append(selected)
        values.sort()
    return ''.join(
        f'<option value="{v}" {"selected" if v == selected else ""}>{_time12(v)}</option>'
        for v in values
    )


def _int_value(value, default):
    try:
        return int(value)
    except Exception:
        return default


def zones_page():
    if not base.logged_in():
        return redirect(url_for('login'))

    c = base.db()

    if request.method == 'POST':
        action = (request.form.get('action') or 'save').strip().lower()
        zone_id = _int_value(request.form.get('zone_id'), 0)

        if action == 'delete':
            current = c.execute('SELECT * FROM zones WHERE id=?', (zone_id,)).fetchone() if zone_id else None
            if not current:
                c.close()
                flash('La zona no existe.')
                return redirect(url_for('zones_page'))

            assigned = 0
            try:
                assigned = c.execute('SELECT COUNT(*) FROM customers WHERE zone_id=?', (zone_id,)).fetchone()[0]
            except Exception:
                try:
                    assigned = c.execute('SELECT COUNT(*) FROM customers WHERE zone=?', (current['name'],)).fetchone()[0]
                except Exception:
                    assigned = 0

            if assigned:
                c.close()
                flash(f'No se puede eliminar {current["name"]}: tiene {assigned} cliente(s) asignado(s). Cambia esos clientes de zona primero.')
                return redirect(url_for('zones_page'))

            c.execute('DELETE FROM zones WHERE id=?', (zone_id,))
            c.commit()
            c.close()
            flash(f'Zona {current["name"]} eliminada.')
            return redirect(url_for('zones_page'))

        name = (request.form.get('name') or '').strip()
        billing_day = _int_value(request.form.get('billing_day'), 30)
        invoice_days_before = _int_value(request.form.get('invoice_days_before'), 5)
        cut_days_after = _int_value(request.form.get('cut_days_after'), 6)
        cut_time = request.form.get('cut_time') or '14:00'

        if zone_id:
            current = c.execute('SELECT * FROM zones WHERE id=?', (zone_id,)).fetchone()
            if not current:
                c.close()
                flash('La zona no existe.')
                return redirect(url_for('zones_page'))

            c.execute(
                'UPDATE zones SET name=?, billing_day=?, invoice_days_before=?, cut_days_after=?, cut_time=? WHERE id=?',
                (name, billing_day, invoice_days_before, cut_days_after, cut_time, zone_id),
            )
            try:
                c.execute('UPDATE customers SET zone=? WHERE zone_id=?', (name, zone_id))
            except Exception:
                pass
            c.commit()
            c.close()
            flash('Zona actualizada.')
            return redirect(url_for('zones_page'))

        c.execute(
            'INSERT INTO zones(name,billing_day,invoice_days_before,cut_days_after,cut_time) VALUES(?,?,?,?,?)',
            (name, billing_day, invoice_days_before, cut_days_after, cut_time),
        )
        c.commit()
        c.close()
        flash('Zona creada.')
        return redirect(url_for('zones_page'))

    edit_id = _int_value(request.args.get('edit'), 0)
    edit_zone = c.execute('SELECT * FROM zones WHERE id=?', (edit_id,)).fetchone() if edit_id else None
    rows = c.execute('SELECT * FROM zones ORDER BY name').fetchall()

    client_count = 0
    try:
        client_count = c.execute('SELECT COUNT(*) FROM customers WHERE zone_id IS NOT NULL').fetchone()[0]
    except Exception:
        try:
            client_count = c.execute("SELECT COUNT(*) FROM customers WHERE COALESCE(zone,'')<>''").fetchone()[0]
        except Exception:
            client_count = 0
    c.close()

    form_name = edit_zone['name'] if edit_zone else ''
    form_billing = edit_zone['billing_day'] if edit_zone else 30
    form_invoice = edit_zone['invoice_days_before'] if edit_zone else 5
    form_cut_days = edit_zone['cut_days_after'] if edit_zone else 6
    form_cut_time = edit_zone['cut_time'] if edit_zone else '14:00'
    time_options = _time_options(form_cut_time)

    total_zones = len(rows)
    zones_billing = sum(1 for r in rows if r['invoice_days_before'] is not None)
    zones_cut = sum(1 for r in rows if r['cut_days_after'] is not None)

    trs = ''.join(
        f'<tr class="zone-row" data-zone="{esc(str(r["name"]).lower())}">'
        f'<td><div class="zone-name"><span class="zone-pin">◆</span><b>{esc(r["name"])}</b></div></td>'
        f'<td>{r["billing_day"]}</td>'
        f'<td>{r["invoice_days_before"]} días antes</td>'
        f'<td>{r["cut_days_after"]} días después</td>'
        f'<td><span class="time-pill">{esc(_time12(r["cut_time"]))}</span></td>'
        f'<td><div class="zone-actions">'
        f'<a class="edit-btn" href="{url_for("zones_page", edit=r["id"])}#zone-form">✎&nbsp; Editar</a>'
        f'<form method="post" style="display:inline" onsubmit="return confirm(\'¿Seguro que deseas eliminar esta zona?\')">'
        f'<input type="hidden" name="action" value="delete">'
        f'<input type="hidden" name="zone_id" value="{r["id"]}">'
        f'<button class="delete-btn" type="submit">🗑&nbsp; Eliminar</button>'
        f'</form></div></td>'
        f'</tr>'
        for r in rows
    )

    heading = 'Editar zona' if edit_zone else 'Crear zona'
    subheading = (
        f'Editando <b>{esc(form_name)}</b>. Modifica los parámetros y guarda los cambios.'
        if edit_zone else
        'Configura los parámetros de facturación y corte para una nueva zona.'
    )
    button_text = 'Guardar cambios' if edit_zone else 'Crear zona'
    cancel_button = (
        f'<a class="cancel-btn" href="{url_for("zones_page")}#zone-form">Cancelar</a>'
        if edit_zone else ''
    )
    hidden_id = f'<input type="hidden" name="zone_id" value="{edit_zone["id"]}">' if edit_zone else ''

    body = f'''
    <style>
      .zones-wrap{{max-width:1400px;margin:0 auto}}
      .zones-hero{{position:relative;overflow:hidden;padding:8px 4px 18px}}
      .zones-title-row{{display:flex;align-items:center;gap:16px}}
      .zones-title-icon{{width:54px;height:54px;border-radius:16px;display:grid;place-items:center;font-size:27px;background:linear-gradient(145deg,#0b75ff,#00b7ff);box-shadow:0 10px 30px rgba(0,123,255,.28)}}
      .zones-title-row h1{{margin:0;font-size:34px;line-height:1.05}}
      .zones-title-row p{{margin:6px 0 0;color:#9fb3cf}}
      .zones-stats{{display:grid;grid-template-columns:repeat(4,minmax(170px,1fr));gap:14px;margin:16px 0 20px}}
      .zstat{{position:relative;padding:18px 20px;border-radius:18px;border:1px solid rgba(102,153,255,.24);background:linear-gradient(145deg,rgba(18,37,67,.96),rgba(9,21,39,.96));box-shadow:0 12px 30px rgba(0,0,0,.18)}}
      .zstat:before{{content:'';position:absolute;inset:0;border-radius:18px;background:radial-gradient(circle at 90% 10%,rgba(26,125,255,.13),transparent 42%);pointer-events:none}}
      .zstat .ico{{font-size:24px;margin-bottom:8px}}
      .zstat .label{{color:#9fb3cf;font-size:13px;font-weight:700}}
      .zstat .num{{font-size:31px;font-weight:900;margin-top:4px;letter-spacing:-.5px}}
      .zstat.blue{{border-color:rgba(0,132,255,.45)}}
      .zstat.purple{{border-color:rgba(159,79,255,.38)}}
      .zstat.green{{border-color:rgba(32,217,133,.38)}}
      .zstat.orange{{border-color:rgba(255,170,43,.38)}}
      .zone-card{{border:1px solid rgba(72,137,235,.30);background:linear-gradient(150deg,rgba(14,30,54,.98),rgba(8,19,35,.98));border-radius:20px;padding:22px;box-shadow:0 14px 40px rgba(0,0,0,.22);margin-bottom:20px}}
      .zone-card.form-card{{box-shadow:inset 0 0 0 1px rgba(0,125,255,.08),0 14px 40px rgba(0,0,0,.22)}}
      .card-head{{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:18px}}
      .card-title{{display:flex;align-items:center;gap:12px}}
      .card-icon{{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,#0c68dd,#128cff);font-size:22px;box-shadow:0 8px 20px rgba(0,119,255,.22)}}
      .card-title h3{{margin:0;font-size:22px}}
      .card-title p{{margin:4px 0 0;color:#93a9c6;font-size:13px}}
      .zone-form-grid{{display:grid;grid-template-columns:1.35fr .9fr .9fr .9fr .9fr auto;gap:13px;align-items:end}}
      .field-group label{{display:block;font-size:12px;font-weight:800;margin:0 0 7px 3px;color:#dce8f7}}
      .zone-card .field{{width:100%;height:48px;border-radius:13px;border:1px solid rgba(130,166,219,.30)!important;background:rgba(7,19,36,.72)!important;color:#fff!important;padding:0 13px!important;box-sizing:border-box}}
      .zone-card .field:focus{{outline:none!important;border-color:#1787ff!important;box-shadow:0 0 0 3px rgba(23,135,255,.13)}}
      .primary-zone-btn{{height:48px;border:0;border-radius:13px;padding:0 20px;font-weight:900;color:#04140c;background:linear-gradient(135deg,#24e37e,#17c968);box-shadow:0 10px 24px rgba(28,211,116,.22);cursor:pointer;white-space:nowrap}}
      .cancel-btn{{height:48px;display:inline-flex;align-items:center;padding:0 17px;border-radius:13px;text-decoration:none!important;color:#dce8f7;border:1px solid rgba(150,176,214,.30);background:rgba(255,255,255,.04)}}
      .list-tools{{display:flex;align-items:center;gap:10px}}
      .zone-search{{width:230px;height:44px;border-radius:12px;border:1px solid rgba(130,166,219,.26);background:rgba(6,17,32,.75);color:#fff;padding:0 13px}}
      .zone-search::placeholder{{color:#7890ad}}
      .zone-table-wrap{{overflow:auto;border-radius:15px;border:1px solid rgba(113,147,196,.18)}}
      .zones-table{{width:100%;border-collapse:collapse;min-width:840px}}
      .zones-table th{{padding:14px 16px;text-align:left;font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:#a9bdd8;background:rgba(18,39,69,.72);border-bottom:1px solid rgba(121,151,194,.20)}}
      .zones-table td{{padding:15px 16px;border-bottom:1px solid rgba(115,145,184,.12);color:#e7eef8}}
      .zones-table tr:last-child td{{border-bottom:0}}
      .zones-table tbody tr:hover{{background:rgba(19,91,168,.08)}}
      .zone-name{{display:flex;align-items:center;gap:10px}}
      .zone-pin{{width:28px;height:28px;border-radius:9px;display:grid;place-items:center;background:linear-gradient(145deg,#0b7dff,#734cff);color:#fff;font-size:11px;transform:rotate(45deg)}}
      .zone-pin::first-letter{{transform:rotate(-45deg)}}
      .time-pill{{display:inline-flex;padding:6px 10px;border-radius:999px;background:rgba(29,128,255,.10);border:1px solid rgba(29,128,255,.22);color:#cfe5ff;font-weight:800}}
      .zone-actions{{display:flex;align-items:center;gap:8px;white-space:nowrap}}
      .edit-btn{{display:inline-flex;align-items:center;height:36px;padding:0 13px;border-radius:10px;text-decoration:none!important;color:#65b5ff!important;border:1px solid #137bdf;background:rgba(11,93,178,.10);font-weight:800}}
      .delete-btn{{display:inline-flex;align-items:center;height:36px;padding:0 13px;border-radius:10px;border:1px solid rgba(239,68,68,.65);background:rgba(239,68,68,.10);color:#ff8d8d;font-weight:800;cursor:pointer}}
      .delete-btn:hover{{background:rgba(239,68,68,.18);border-color:#ef4444;color:#ffd1d1}}
      .empty-zone{{padding:28px;text-align:center;color:#8ea5c0}}
      @media(max-width:1050px){{.zones-stats{{grid-template-columns:repeat(2,1fr)}}.zone-form-grid{{grid-template-columns:repeat(2,1fr)}}.primary-zone-btn,.cancel-btn{{width:100%;justify-content:center}}}}
      @media(max-width:650px){{.zones-stats{{grid-template-columns:1fr}}.zone-form-grid{{grid-template-columns:1fr}}.card-head{{align-items:flex-start;flex-direction:column}}.list-tools{{width:100%}}.zone-search{{width:100%}}}}
    </style>

    <div class="zones-wrap">
      <div class="zones-hero">
        <div class="zones-title-row">
          <div class="zones-title-icon">⌖</div>
          <div><h1>Zonas</h1><p>Facturación y corte por zona · Hora de República Dominicana</p></div>
        </div>
      </div>

      <div class="zones-stats">
        <div class="zstat blue"><div class="ico">◉</div><div class="label">Total de zonas</div><div class="num">{total_zones}</div></div>
        <div class="zstat purple"><div class="ico">👥</div><div class="label">Clientes asignados</div><div class="num">{client_count}</div></div>
        <div class="zstat green"><div class="ico">▤</div><div class="label">Zonas con facturación</div><div class="num">{zones_billing}</div></div>
        <div class="zstat orange"><div class="ico">✂</div><div class="label">Zonas con corte</div><div class="num">{zones_cut}</div></div>
      </div>

      <div class="zone-card form-card" id="zone-form" style="scroll-margin-top:18px">
        <div class="card-head">
          <div class="card-title"><div class="card-icon">+</div><div><h3>{heading}</h3><p>{subheading}</p></div></div>
        </div>
        <form method="post" class="zone-form-grid">
          {hidden_id}
          <input type="hidden" name="action" value="save">
          <div class="field-group"><label for="zone-name">Nombre de zona *</label><input id="zone-name" class="field" name="name" value="{esc(form_name)}" placeholder="Ej. El Manguito" required></div>
          <div class="field-group"><label for="billing-day">Día de vencimiento *</label><input id="billing-day" class="field" type="number" name="billing_day" value="{form_billing}" min="1" max="31"></div>
          <div class="field-group"><label for="invoice-days">Factura días antes *</label><input id="invoice-days" class="field" type="number" name="invoice_days_before" value="{form_invoice}" min="0"></div>
          <div class="field-group"><label for="cut-days">Corte días después *</label><input id="cut-days" class="field" type="number" name="cut_days_after" value="{form_cut_days}" min="0"></div>
          <div class="field-group"><label for="cut-time">Hora de corte *</label><select id="cut-time" class="field" name="cut_time">{time_options}</select></div>
          <div style="display:flex;gap:9px"><button class="primary-zone-btn" type="submit">+ {button_text}</button>{cancel_button}</div>
        </form>
      </div>

      <div class="zone-card">
        <div class="card-head">
          <div class="card-title"><div class="card-icon">▱</div><div><h3>Zonas registradas</h3><p>Listado de zonas con sus parámetros de facturación y corte.</p></div></div>
          <div class="list-tools"><input id="zoneSearch" class="zone-search" type="search" placeholder="🔎  Buscar zona..."></div>
        </div>
        <div class="zone-table-wrap">
          <table class="zones-table">
            <thead><tr><th>Zona</th><th>Vence</th><th>Factura</th><th>Corte</th><th>Hora</th><th>Acciones</th></tr></thead>
            <tbody id="zoneRows">{trs or '<tr><td colspan="6" class="empty-zone">Sin zonas registradas.</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      (function(){{
        const q=document.getElementById('zoneSearch');
        if(q) q.addEventListener('input',function(){{
          const term=(this.value||'').trim().toLowerCase();
          document.querySelectorAll('.zone-row').forEach(function(row){{
            const name=row.getAttribute('data-zone')||'';
            row.style.display=name.includes(term)?'':'none';
          }});
        }});
        if(window.location.hash==='#zone-form'){{
          setTimeout(function(){{document.getElementById('zone-form')?.scrollIntoView({{behavior:'smooth',block:'start'}})}},120);
        }}
      }})();
    </script>
    '''
    return base.shell('Zonas', body, 'zones_page')


def setup(app):
    app.view_functions['zones_page'] = zones_page
