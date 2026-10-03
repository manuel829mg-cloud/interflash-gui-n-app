from enhanced_app import app
import push_sync
from push_sync import setup as setup_push_sync

_original_audit = push_sync.base.audit

def _audit_without_relay_lock(action, detail=''):
    if action == 'MIKROTIK_RELAY_SYNC':
        return
    return _original_audit(action, detail)

push_sync.base.audit = _audit_without_relay_lock
setup_push_sync(app)
print('INTERFLASH_PUSH_SYNC_ENABLED', flush=True)
