import ast
import sqlite3
import types
import unittest
from datetime import datetime,timedelta
from pathlib import Path

source = ast.parse((Path(__file__).parents[1]/'wan_alerts.py').read_text())
mod = types.ModuleType('wan_under_test')
mod.datetime = datetime
nodes = [n for n in source.body if isinstance(n,(ast.Assign,ast.FunctionDef)) and (isinstance(n,ast.Assign) or n.name in ('schema','_event','observe'))]
exec(compile(ast.Module(body=nodes,type_ignores=[]),'wan_alerts.py','exec'),mod.__dict__)

class AlertTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.executescript('''CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE wan_alert_state(router_name,interface_name,state,candidate,streak,sample_at,PRIMARY KEY(router_name,interface_name));
        CREATE TABLE wan_alert_events(id INTEGER PRIMARY KEY,router_name,interface_name,state,message,created_at,outbox_id);
        CREATE TABLE whatsapp_outbox(id INTEGER PRIMARY KEY,customer_id,phone,template_code,message,status,created_at);''')
        self.now = datetime(2026,10,11,22)
    def tearDown(self): self.c.close()
    def sample(self,n,loss=0,iface='WAN1-CLARO'):
        stamp=self.now+timedelta(seconds=10*n)
        mod.observe(self.c,'CCR2116',iface,loss,stamp.isoformat(),now=stamp)
    def events(self): return self.c.execute('SELECT * FROM wan_alert_events').fetchall()
    def test_debounce_deduplicate_recover(self):
        for n in range(3): self.sample(n)
        self.assertEqual(len(self.events()),0)
        self.sample(3,100); self.sample(4,100)
        self.assertEqual(len(self.events()),0)
        self.sample(5,100); self.sample(5,100); self.sample(6,100)
        self.assertEqual([r['state'] for r in self.events()],['NO_REPLY'])
        for n in (7,8,9): self.sample(n)
        self.assertEqual([r['state'] for r in self.events()],['NO_REPLY','ONLINE'])
    def test_stale_once_and_no_unknown_interfaces(self):
        self.sample(0)
        for sec in (46,60,90):
            mod.observe(self.c,'CCR2116','WAN1-CLARO',0,self.now.isoformat(),now=self.now+timedelta(seconds=sec))
        self.assertEqual([r['state'] for r in self.events()],['STALE'])
        self.sample(10,100,iface='OTHER')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM wan_alert_state').fetchone()[0],1)
    def test_whatsapp_only_explicit_admin_recipient(self):
        for n in range(3): self.sample(n,100)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0],0)
        self.c.executemany('INSERT INTO app_settings VALUES(?,?)',[('wan_alert_whatsapp','1'),('whatsapp_enabled','1'),('wan_alert_phone','18095550123')])
        for n in (3,4,5): self.sample(n)
        rows=self.c.execute('SELECT * FROM whatsapp_outbox').fetchall()
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['customer_id'])
        self.assertEqual(rows[0]['phone'],'18095550123')

if __name__=='__main__': unittest.main()
