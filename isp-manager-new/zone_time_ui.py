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


def _zone_customer_counts(c, rows):
    """Return a count for every zone, supporting old and new customer schemas."""
    counts = {int(r['id']): 0 for r in rows}
    used_zone_id = False

    try:
        for row in c.execute(
            'SELECT zone_id, COUNT(*) AS qty FROM customers WHERE zone_id IS NOT NULL GROUP BY zone_id'
        ).fetchall():
            zid = _int_value(row['zone_id'], 0)
            if zid in counts:
                counts[zid] += int(row['qty'] or 0)
        used_zone_id = True
    except Exception:
        pass

    # Count legacy customers that only have the text zone field. If zone_id exists,
    # only count rows without zone_id so the same customer is never counted twice.
    try:
        sql = (
            "SELECT zone, COUNT(*) AS qty FROM customers "
            "WHERE zone_id IS NULL AND COALESCE(zone,'')<>'' GROUP BY zone"
            if used_zone_id else
            "SELECT zone, COUNT(*) AS qty FROM customers WHERE COALESCE(zone,'')<>'' GROUP BY zone"
        )
        name_counts = {str(x['zone']).strip().lower(): int(x['qty'] or 0) for x in c.execute(sql).fetchall()}
        for zone in rows:
            counts[int(zone['id'])] += name_counts.get(str(zone['name']).strip().lower(), 0)
    except Exception:
        pass

    return counts


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
                try:
                    assigned += c.execute(
                        "SELECT COUNT(*) FROM customers WHERE zone_id IS NULL AND zone=?", (current['name'],)
                    ).fetchone()[0]
                except Exception:
                    pass
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

        try:
            suspend_count = int(request.form.get('suspend_invoice_count', '1'))
            if not 1 <= suspend_count <= 12:
                raise ValueError()
        except (TypeError, ValueError):
            c.close()
            flash('Selecciona entre 1 y 12 facturas vencidas para suspender el servicio.')
            return redirect(url_for('zones_page', edit=zone_id) if zone_id else url_for('zones_page'))

        reminder_enabled = int(request.form.get('whatsapp_reminder_enabled') == '1')
        reminder_days = 0

        if zone_id:
            current = c.execute('SELECT * FROM zones WHERE id=?', (zone_id,)).fetchone()
            if not current:
                c.close()
                flash('La zona no existe.')
                return redirect(url_for('zones_page'))

            c.execute(
                'UPDATE zones SET name=?, billing_day=?, invoice_days_before=?, cut_days_after=?, cut_time=?, whatsapp_reminder_enabled=?, whatsapp_reminder_days=?, suspend_invoice_count=? WHERE id=?',
                (name, billing_day, invoice_days_before, cut_days_after, cut_time, reminder_enabled, reminder_days, suspend_count, zone_id),
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
            'INSERT INTO zones(name,billing_day,invoice_days_before,cut_days_after,cut_time,whatsapp_reminder_enabled,whatsapp_reminder_days,suspend_invoice_count) VALUES(?,?,?,?,?,?,?,?)',
            (name, billing_day, invoice_days_before, cut_days_after, cut_time, reminder_enabled, reminder_days, suspend_count),
        )
        c.commit()
        c.close()
        flash('Zona creada.')
        return redirect(url_for('zones_page'))

    edit_id = _int_value(request.args.get('edit'), 0)
    edit_zone = c.execute('SELECT * FROM zones WHERE id=?', (edit_id,)).fetchone() if edit_id else None
    rows = c.execute('SELECT * FROM zones ORDER BY name').fetchall()
    from zone_summary import totals
    summaries = totals(c)
    zone_counts = _zone_customer_counts(c, rows)
    client_count = sum(zone_counts.values())
    c.close()

    from datetime import datetime
    from zoneinfo import ZoneInfo
    preview_today = datetime.now(ZoneInfo('America/Santo_Domingo')).date().isoformat()

    form_name = edit_zone['name'] if edit_zone else ''
    form_billing = edit_zone['billing_day'] if edit_zone else 30
    form_invoice = edit_zone['invoice_days_before'] if edit_zone else 5
    form_cut_days = edit_zone['cut_days_after'] if edit_zone else 6
    form_cut_time = edit_zone['cut_time'] if edit_zone else '14:00'
    time_options = _time_options(form_cut_time)
    reminder_checked = 'checked' if edit_zone and edit_zone['whatsapp_reminder_enabled'] else ''

    suspend_count = edit_zone['suspend_invoice_count'] if edit_zone else 1
    suspend_options = ''.join(f'<option value="{n}"{" selected" if n == suspend_count else ""}>{n} factura{"s" if n > 1 else ""} vencida{"s" if n > 1 else ""}</option>' for n in range(1, 13))

    total_zones = len(rows)
    zones_billing = sum(1 for r in rows if r['invoice_days_before'] is not None)
    zones_cut = sum(1 for r in rows if r['cut_days_after'] is not None)

    trs = ''.join(
        f'<tr class="zone-row" data-zone="{esc(str(r["name"]).lower())}">'
        f'<td><div class="zone-name"><span class="zone-pin">◆</span><b>{esc(r["name"])}</b></div></td>'
        f'<td><a class="client-pill" href="/zones/{r["id"]}/summary">👥 {summaries.get(r["id"], {}).get("clients", 0)}</a>'
        f'<div class="muted">Deuda: RD${summaries.get(r["id"], {}).get("balance", 0):,.2f}</div>'
        f'<a href="/zones/{r["id"]}/summary?filter=suspended">Suspendidos: {summaries.get(r["id"], {}).get("suspended", 0)}</a></td>'
        f'<td>{r["billing_day"]}</td>'
        f'<td>{r["invoice_days_before"]} días antes</td>'
        f'<td>{r["cut_days_after"]} días después</td>'
        f'<td><span class="time-pill">{esc(_time12(r["cut_time"]))}</span></td>'
        f'<td>{"El día de vencimiento" if r["whatsapp_reminder_enabled"] else "Desactivado"}</td>'
        f'<td><div class="zone-actions">'
        f'<a class="edit-btn" href="/zones/{r["id"]}/summary">Resumen e historial</a>'
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
      .zones-table{{width:100%;border-collapse:collapse;min-width:1400px;table-layout:auto}}
      .zones-table th{{padding:10px 8px;text-align:left;font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:#a9bdd8;background:rgba(18,39,69,.72);border-bottom:1px solid rgba(121,151,194,.20)}}
      .zones-table td{{padding:10px 8px;font-size:13px;line-height:1.35;border-bottom:1px solid rgba(115,145,184,.12);color:#e7eef8}}
      .zones-table tr:last-child td{{border-bottom:0}}
      .zones-table tbody tr:hover{{background:rgba(19,91,168,.08)}}
      .zone-name{{display:flex;align-items:center;gap:12px;min-width:240px}}
      .zone-name b{{overflow-wrap:normal!important;word-break:normal!important;white-space:nowrap!important}}
      .zones-table th:first-child,.zones-table td:first-child{{min-width:260px;width:auto}}
      .zones-table td{{vertical-align:middle;overflow-wrap:normal;word-break:normal}}
      .zones-table th:not(:first-child),.zones-table td:not(:first-child){{width:auto}}
      .zones-table td:nth-child(4),.zones-table td:nth-child(5){{white-space:nowrap}}
      .zones-table .client-pill,.zones-table .time-pill{{white-space:nowrap;padding:8px 12px}}
      .zones-table .zone-actions{{gap:5px}}
      .zones-table .zone-actions form{{margin:0}}
      .zones-table .edit-btn,.zones-table .delete-btn{{height:32px;padding:0 8px;font-size:12px}}
      .zone-pin{{width:32px;height:32px;flex-shrink:0;border-radius:10px;display:grid;place-items:center;background:linear-gradient(145deg,#0b7dff,#734cff);color:#fff;font-size:11px;transform:rotate(45deg)}}
      .zone-pin::first-letter{{transform:rotate(-45deg)}}
      .client-pill{{display:inline-flex;align-items:center;gap:5px;padding:6px 10px;border-radius:999px;background:rgba(147,79,255,.11);border:1px solid rgba(147,79,255,.28);color:#d9c7ff;font-weight:900}}
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
          <div class="field-group" style="grid-column:1/-1"><label for="suspend-invoice-count">Suspender servicio</label><select id="suspend-invoice-count" class="field" name="suspend_invoice_count">{suspend_options}</select><p class="muted">Aplica a todos los clientes de esta zona. Cuenta facturas vencidas con saldo pendiente y respeta los días y la hora de corte desde la factura que completa esa cantidad. Las promesas vigentes aplazan el corte.</p></div>
          <div class="field-group" style="grid-column:1/-1"><label><input type="checkbox" name="whatsapp_reminder_enabled" value="1" {reminder_checked}> Recordatorio por WhatsApp</label><p class="muted">Avisa únicamente a clientes con pagos pendientes. Requiere avisos automáticos de WhatsApp activos. Se envía siempre el día de vencimiento de la factura, desde las 10:00, hora dominicana.</p></div>
          <section id="zone-calendar" style="grid-column:1/-1;padding:16px;border:1px solid #30445e;border-radius:12px;background:#101e31" aria-live="polite">
            <h4 style="margin:0 0 12px">Calendario del próximo vencimiento</h4>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px">
              <div><span class="muted">Generación de factura</span><div id="preview-invoice"></div></div>
              <div><span class="muted">Vencimiento</span><div id="preview-due"></div></div>
              <div><span class="muted">Aviso de WhatsApp</span><div id="preview-whatsapp"></div></div>
              <div><span class="muted">Corte previsto</span><div id="preview-cut"></div></div>
            </div>
            <p class="muted" id="preview-note" style="margin-bottom:0"></p>
          </section>
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
            <thead><tr><th>Zona</th><th>Clientes</th><th>Vence</th><th>Factura</th><th>Corte</th><th>Hora</th><th>WhatsApp</th><th>Acciones</th></tr></thead>
            <tbody id="zoneRows">{trs or '<tr><td colspan="8" class="empty-zone">Sin zonas registradas.</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>

    <style>

      /* Fit all columns to the available screen; wrap at word boundaries. */
      .zones-wrap{{max-width:none;width:100%;min-width:0;box-sizing:border-box}}
      .zone-card,.zone-table-wrap{{min-width:0;max-width:100%;box-sizing:border-box}}
      .zone-table-wrap{{overflow:visible}}
      .zones-table{{width:100%;min-width:0!important;table-layout:fixed}}
      .zones-table th,.zones-table td{{width:auto!important;min-width:0!important;padding:12px 6px;white-space:normal!important;overflow-wrap:normal;word-break:normal;vertical-align:middle}}
      .zones-table th:nth-child(1){{width:17%!important}}
      .zones-table th:nth-child(2){{width:17%!important}}
      .zones-table th:nth-child(3){{width:6%!important}}
      .zones-table th:nth-child(4){{width:10%!important}}
      .zones-table th:nth-child(5){{width:10%!important}}
      .zones-table th:nth-child(6){{width:9%!important}}
      .zones-table th:nth-child(7){{width:12%!important}}
      .zones-table th:nth-child(8){{width:19%!important}}
      .zone-name{{min-width:0;gap:10px;flex-wrap:wrap}}
      .zone-name b{{min-width:0;max-width:100%;white-space:normal!important;word-break:normal!important;overflow-wrap:normal!important}}
      .zones-table .zone-actions{{min-width:0;display:flex;flex-wrap:wrap;white-space:normal;gap:6px}}
      .zones-table .edit-btn,.zones-table .delete-btn{{max-width:100%;height:auto;min-height:34px;white-space:normal;box-sizing:border-box;text-align:center}}
      .zones-table .client-pill,.zones-table .time-pill{{max-width:100%;box-sizing:border-box;white-space:normal}}
      @media(max-width:750px){{.zones-table th,.zones-table td{{font-size:11px;padding:8px 3px}}.zone-pin{{width:26px;height:26px}}.zones-table .edit-btn,.zones-table .delete-btn{{font-size:10px;padding:5px 3px}}}}
    </style>
    <script>
      (function(){{

        const todayParts='{preview_today}'.split('-').map(Number);
        const today=new Date(Date.UTC(todayParts[0],todayParts[1]-1,todayParts[2]));
        const ids=['billing-day','invoice-days','cut-days','cut-time','suspend-invoice-count'];
        const reminder=document.querySelector('[name="whatsapp_reminder_enabled"]');
        const fmt=new Intl.DateTimeFormat('es-DO',{{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}});
        function updateCalendar(){{
          const day=Number(document.getElementById('billing-day').value);
          const before=Number(document.getElementById('invoice-days').value);
          const after=Number(document.getElementById('cut-days').value);
          if(!Number.isInteger(day)||day<1||day>31||!Number.isInteger(before)||before<0||!Number.isInteger(after)||after<0){{
            ['invoice','due','whatsapp','cut'].forEach(k=>document.getElementById('preview-'+k).textContent='Revisa los valores');return;
          }}
          function dueInMonth(year,month){{return new Date(Date.UTC(year,month,Math.min(day,new Date(Date.UTC(year,month+1,0)).getUTCDate())));}}
          let due=dueInMonth(today.getUTCFullYear(),today.getUTCMonth());
          if(due<today)due=dueInMonth(today.getUTCFullYear(),today.getUTCMonth()+1);
          const invoice=new Date(due);invoice.setUTCDate(invoice.getUTCDate()-before);
          const cut=new Date(due);cut.setUTCDate(cut.getUTCDate()+after);
          document.getElementById('preview-invoice').textContent=fmt.format(invoice)+(invoice<today?' (fecha programada ya pasada)':'');
          document.getElementById('preview-due').textContent=fmt.format(due);
          document.getElementById('preview-whatsapp').textContent=reminder.checked?fmt.format(due)+' · desde las 10:00 a. m.':'Desactivado';
          const count=Number(document.getElementById('suspend-invoice-count').value);
          const time=document.getElementById('cut-time').selectedOptions[0].textContent;
          document.getElementById('preview-cut').textContent=count===1?fmt.format(cut)+' · '+time:'Al acumular '+count+' facturas vencidas con saldo';
          document.getElementById('preview-note').textContent='Vista previa de la programación, hora dominicana. No confirma facturas generadas ni mensajes enviados. '+(count===1?'El corte aplica si queda saldo pendiente y no hay promesa vigente.':'La fecha de corte depende de la factura que complete esa cantidad; se respetan el plazo y las promesas vigentes.');
        }}
        ids.forEach(id=>document.getElementById(id).addEventListener('input',updateCalendar));
        reminder.addEventListener('change',updateCalendar);updateCalendar();
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
    from zone_summary import setup as summary_setup
    summary_setup(app)
    app.view_functions['zones_page'] = zones_page
