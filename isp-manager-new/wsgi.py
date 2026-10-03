from enhanced_app import app
from push_sync import setup as setup_push_sync

setup_push_sync(app)
print('INTERFLASH_PUSH_SYNC_ENABLED', flush=True)
