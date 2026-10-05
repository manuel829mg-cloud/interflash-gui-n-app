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
    return ''.join(f'<option value="{v}" {"selected" if v == selected else ""}>{_time12(v)}</option>' for v in values)


def zones_page():
    if not base.logged_in():
        return redirect(url_for('login'))
    c = base.db()
    if request.method == 'POST':
        cut_time = request.form.get('cut_time') or '14:00'
        c.execute('INSERT INTO zones(name,billing_day,invoice_days_before,cut_days_after,cut_time) VALUES(?,?,?,?,?)',(
            request.form['name'],
            int(request.form.get('billing_day') or 30),
            int(request.form.get('invoice_days_before') or 5),
            int(request.form.get('cut_days_after') or 6),
            cut_time,
        ))
        c.commit()
        flash('Zona creada.')
    rows = c.execute('SELECT * FROM zones ORDER BY name').fetchall()
    c.close()
    trs = ''.join(
        f'<tr><td>{esc(r["name"])}</td><td>{r["billing_day"]}</td><td>{r["invoice_days_before"]} días antes</td><td>{r["cut_days_after"]} días después</td><td>{esc(_time12(r["cut_time"]))}</td></tr>'
        for r in rows
    )
    time_options = _time_options('14:00')
    body = f'''<div class="head"><div><h1>Zonas</h1><p>Facturación y corte por zona · Hora de República Dominicana</p></div></div><div class="panel"><form class="toolbar" method="post"><input class="field" name="name" placeholder="Nombre" required><input class="field" type="number" name="billing_day" value="30"><input class="field" type="number" name="invoice_days_before" value="5"><input class="field" type="number" name="cut_days_after" value="6"><select class="field" name="cut_time" aria-label="Hora de corte">{time_options}</select><button class="btn green">Crear zona</button></form><table class="table"><tr><th>Zona</th><th>Vence</th><th>Factura</th><th>Corte</th><th>Hora</th></tr>{trs or '<tr><td colspan=5 class=muted>Sin zonas.</td></tr>'}</table></div>'''
    return base.shell('Zonas', body, 'zones_page')


def setup(app):
    app.view_functions['zones_page'] = zones_page
