from app import app
from mikrotik_ext import setup as setup_mikrotik
from push_agent import setup as setup_push_agent

setup_mikrotik(app)
setup_push_agent(app)
