from flask import redirect, url_for
from enhanced_app import app
import push_sync
from push_sync import setup as setup_push_sync
import business_suite
import ops_suite
import finance_plus

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

def routers_secure():
    return redirect(url_for('router_push_view'))

app.view_functions['routers'] = routers_secure
print('INTERFLASH_ISP_MODULES_ENABLED', flush=True)
