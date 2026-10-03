from app import app
from push_agent import setup as setup_push_agent
from sync_fix import setup as setup_sync_fix

setup_push_agent(app)
setup_sync_fix(app)
