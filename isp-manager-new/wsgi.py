import os
import time

# INTER Flash operates in the Dominican Republic. Force the process local
# timezone before loading the application so datetime.now()/date.today() and
# scheduled billing/cut logic use America/Santo_Domingo (UTC-4) instead of the
# Railway host timezone.
os.environ['TZ'] = 'America/Santo_Domingo'
try:
    time.tzset()
except AttributeError:
    pass

from flask import redirect, url_for, request, flash
from enhanced_app import app
import schema_compat
import push_sync
from push_sync import setup as setup_push_sync
import business_suite
import ops_suite
import finance_plus
import command_queue_ui
import client_extract
import client_nav_group
import pbr_client
import plan_import
import customers_responsive
import suspension_agent
import isp_operations_plus
import customer_provisioning
import plan_form_cleanup
import admin_suite
import traffic_monitor_fix
import traffic_monitor_v2
import wan_monitor
import free_ip_picker
import pool_compat_fix
import whatsapp_suite
import branding
import zone_time_ui
import zone_cut_scheduler

_original_audit = push_sync.base.audit

def _audit_without_relay_lock(action, detail=''):
    if action == 'MIKROTIK_RELAY_SYNC':
        return
    return _original_audit(action, detail)

push_sync.base.audit = _audit_without_relay_lock
setup_push_sync(app)
business_suite.setup(app)
ops_suite.setup(app)
finance_plus.setup(app)
command_queue_ui.setup(app)
client_extract.setup(app)
client_nav_group.setup()
pbr_client.setup(app)
free_ip_picker.setup(app)
pool_compat_fix.setup(app)
plan_import.setup(app)
customers_responsive.setup(app)
suspension_agent.setup(app)
isp_operations_plus.setup(app)
customer_provisioning.setup(app)
plan_form_cleanup.setup(app)
admin_suite.setup(app)
traffic_monitor_fix.setup(app)
traffic_monitor_v2.setup(app)
wan_monitor.setup(app)
whatsapp_suite.setup(app)
branding.setup(app)

# Use a dedicated path for the new WhatsApp inbox. An older module already
# owns /whatsapp, so this avoids the route collision and makes the menu open
# the new chat inbox instead of the legacy outbox page.
app.add_url_rule('/whatsapp/inbox', endpoint='whatsapp_chat', view_func=whatsapp_suite.inbox, methods=['GET'])
try:
    whatsapp_suite.base.NAV[:] = [x for x in whatsapp_suite.base.NAV if x[2] != 'WhatsApp']
    idx = next((i for i, x in enumerate(whatsapp_suite.base.NAV) if x[0] == 'audit_page'), len(whatsapp_suite.base.NAV))
    whatsapp_suite.base.NAV.insert(idx, ('whatsapp_chat', '◉', 'WhatsApp'))
except Exception:
    pass

# pbr_client replaces the queue page during setup. Restore the safer queue view
# so the administrator can cancel stale PENDIENTE/EN_PROCESO commands before
# enabling the MikroTik agent. The clear endpoint itself is registered by
# command_queue_ui.setup() above.
app.view_functions['mikrotik_commands'] = command_queue_ui.commands_page

# Legacy 12-hour zone form kept for compatibility. The final override below
# replaces its three separate hour/minute/AM-PM controls with one single field.
def _cut_time_24h(hour12, minute, period):
    try:
        h = max(1, min(int(hour12), 12))
        m = max(0, min(int(minute), 59))
    except Exception:
        h, m = 2, 0
    period = (period or 'PM').upper()
    if period == 'AM':
        h24 = 0 if h == 12 else h
    else:
        h24 = 12 if h == 12 else h + 12
    return f'{h24:02d}:{m:02d}'


def _cut_time_12h(value):
    try:
        h, m = [int(x) for x in str(value or '14:00').split(':')[:2]]
    except Exception:
        h, m = 14, 0
    period = 'AM' if h < 12 else 'PM'
    h12 = h % 12 or 12
    return f'{h12}:{m:02d} {period}'


def zones_page_12h():
    if not ops_suite.base.logged_in():
        return redirect(url_for('login'))
    c = ops_suite.base.db()
    if request.method == 'POST':
        cut_time = _cut_time_24h(
            request.form.get('cut_hour'),
            request.form.get('cut_minute'),
            request.form.get('cut_period'),
        )
        c.execute(
            'INSERT INTO zones(name,billing_day,invoice_days_before,cut_days_after,cut_time) VALUES(?,?,?,?,?)',
            (
                request.form['name'],
                int(request.form.get('billing_day') or 30),
                int(request.form.get('invoice_days_before') or 5),
                int(request.form.get('cut_days_after') or 6),
                cut_time,
            ),
        )
        c.commit()
        flash('Zona creada.')
    rows = c.execute('SELECT * FROM zones ORDER BY name').fetchall()
    c.close()
    trs = ''.join(
        f'<tr><td>{ops_suite.esc(r["name"])}</td><td>{r["billing_day"]}</td>'
        f'<td>{r["invoice_days_before"]} días antes</td>'
        f'<td>{r["cut_days_after"]} días después</td>'
        f'<td>{_cut_time_12h(r["cut_time"])} <span class="muted">RD</span></td></tr>'
        for r in rows
    )
    hour_opts = ''.join(f'<option value="{h}" {"selected" if h == 2 else ""}>{h}</option>' for h in range(1, 13))
    minute_opts = ''.join(f'<option value="{m:02d}" {"selected" if m == 0 else ""}>{m:02d}</option>' for m in range(60))
    body = f'''<div class="head"><div><h1>Zonas</h1><p>Facturación y corte por zona · Hora de República Dominicana</p></div></div>
    <div class="panel">
      <form class="toolbar" method="post">
        <input class="field" name="name" placeholder="Nombre" required>
        <input class="field" type="number" name="billing_day" value="30" title="Día de vencimiento">
        <input class="field" type="number" name="invoice_days_before" value="5" title="Factura días antes">
        <input class="field" type="number" name="cut_days_after" value="6" title="Corte días después">
        <span class="muted" style="font-weight:700">Hora de corte (RD)</span>
        <select class="field" name="cut_hour" aria-label="Hora">{hour_opts}</select>
        <span style="font-weight:800">:</span>
        <select class="field" name="cut_minute" aria-label="Minutos">{minute_opts}</select>
        <select class="field" name="cut_period" aria-label="AM o PM"><option>AM</option><option selected>PM</option></select>
        <button class="btn green">Crear zona</button>
      </form>
      <table class="table"><tr><th>Zona</th><th>Vence</th><th>Factura</th><th>Corte</th><th>Hora RD</th></tr>{trs or '<tr><td colspan=5 class=muted>Sin zonas.</td></tr>'}</table>
    </div>'''
    return ops_suite.base.shell('Zonas', body, 'zones_page')

app.view_functions['zones_page'] = zones_page_12h

# Final zone time UI: one selector shows the whole time, including AM/PM,
# for example "2:00 PM", while the saved value remains 14:00 internally.
zone_time_ui.setup(app)

# Automatic cut engine: evaluates each customer's zone every 30 seconds using
# Dominican Republic local time and queues SUSPEND only after the configured
# cut date and cut time have both arrived.
zone_cut_scheduler.setup(app)


def routers_secure():
    return redirect(url_for('router_push_view'))

app.view_functions['routers'] = routers_secure
print('INTERFLASH_FULL_ISP_SUITE_ENABLED', flush=True)
