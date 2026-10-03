from app import app
from menu_structure import setup as setup_menu_structure

# Apply the shared navigation/shell before importing modules that capture shell.
setup_menu_structure(app)

from push_agent import setup as setup_push_agent
from sync_fix import setup as setup_sync_fix
from dashboard_sync import setup as setup_dashboard_sync
from router_menu_sync import setup as setup_router_menu_sync
from clients_sync import setup as setup_clients_sync

setup_push_agent(app)
setup_sync_fix(app)
setup_dashboard_sync(app)
setup_router_menu_sync(app)
setup_clients_sync(app)
