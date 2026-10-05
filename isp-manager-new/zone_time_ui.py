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
        zone_id = _int_value(request.form.get('zone_id'), 0)
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
            # Keep the customer text field synchronized with the selected zone.
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
    c.close()

    form_name = edit_zone['name'] if edit_zone else ''
    form_billing = edit_zone['billing_day'] if edit_zone else 30
    form_invoice = edit_zone['invoice_days_before'] if edit_zone else 5
    form_cut_days = edit_zone['cut_days_after'] if edit_zone else 6
    form_cut_time = edit_zone['cut_time'] if edit_zone else '14:00'
    time_options = _time_options(form_cut_time)

    trs = ''.join(
        f'<tr>'
        f'<td>{esc(r["name"])}</td>'
        f'<td>{r["billing_day"]}</td>'
        f'<td>{r["invoice_days_before"]} días antes</td>'
        f'<td>{r["cut_days_after"]} días después</td>'
        f'<td>{esc(_time12(r["cut_time"]))}</td>'
        f'<td><a class="btn" style="padding:7px 12px;text-decoration:none" href="{url_for("zones_page", edit=r["id"])}">Editar</a></td>'
        f'</tr>'
        for r in rows
    )

    label_style = 'display:block;font-size:13px;font-weight:700;margin:0 0 7px 3px;color:#cbd5e1'
    group_style = 'min-width:170px;flex:1'
    heading = 'Editar zona' if edit_zone else 'Crear zona'
    button_text = 'Guardar cambios' if edit_zone else 'Crear zona'
    cancel_button = (
        f'<a class="btn" style="text-decoration:none" href="{url_for("zones_page")}">Cancelar</a>'
        if edit_zone else ''
    )
    hidden_id = f'<input type="hidden" name="zone_id" value="{edit_zone["id"]}">' if edit_zone else ''

    body = f'''<div class="head"><div><h1>Zonas</h1><p>Facturación y corte por zona · Hora de República Dominicana</p></div></div>
    <div class="panel">
      <h3 style="margin-top:0">{heading}</h3>
      <form class="toolbar" method="post" style="align-items:flex-end">
        {hidden_id}
        <div style="{group_style}">
          <label for="zone-name" style="{label_style}">Nombre de zona</label>
          <input id="zone-name" class="field" name="name" value="{esc(form_name)}" placeholder="Ej. El Manguito" required>
        </div>
        <div style="{group_style}">
          <label for="billing-day" style="{label_style}">Día de vencimiento</label>
          <input id="billing-day" class="field" type="number" name="billing_day" value="{form_billing}" min="1" max="31">
        </div>
        <div style="{group_style}">
          <label for="invoice-days" style="{label_style}">Factura días antes</label>
          <input id="invoice-days" class="field" type="number" name="invoice_days_before" value="{form_invoice}" min="0">
        </div>
        <div style="{group_style}">
          <label for="cut-days" style="{label_style}">Corte días después</label>
          <input id="cut-days" class="field" type="number" name="cut_days_after" value="{form_cut_days}" min="0">
        </div>
        <div style="{group_style}">
          <label for="cut-time" style="{label_style}">Hora de corte</label>
          <select id="cut-time" class="field" name="cut_time" aria-label="Hora de corte">{time_options}</select>
        </div>
        <button class="btn green">{button_text}</button>
        {cancel_button}
      </form>
      <table class="table">
        <tr><th>Zona</th><th>Vence</th><th>Factura</th><th>Corte</th><th>Hora</th><th>Acciones</th></tr>
        {trs or '<tr><td colspan=6 class=muted>Sin zonas.</td></tr>'}
      </table>
    </div>'''
    return base.shell('Zonas', body, 'zones_page')


def setup(app):
    app.view_functions['zones_page'] = zones_page
