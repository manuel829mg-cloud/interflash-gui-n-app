from flask import redirect, url_for
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
import admin_suite
import traffic_monitor_fix
import traffic_monitor_v2
import free_ip_picker
import pool_compat_fix
import whatsapp_suite
import branding

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
admin_suite.setup(app)
traffic_monitor_fix.setup(app)
traffic_monitor_v2.setup(app)
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

def routers_secure():
    return redirect(url_for('router_push_view'))

app.view_functions['routers'] = routers_secure
print('INTERFLASH_FULL_ISP_SUITE_ENABLED', flush=True)
