import os
import tempfile
import unittest
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/test.db'
os.environ['SECRET_KEY'] = 'isolated-test'
import app as base
import pbr_client
import commercial_service as service


class CommercialServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pbr_client.ensure_schema()
        c = base.db()
        c.executescript('''
        CREATE TABLE push_ppp_profiles(router_name TEXT,name TEXT,rate_limit TEXT,remote_address TEXT,local_address TEXT);
        CREATE TABLE plan_profile_map(router_name TEXT,plan_id INTEGER,pbr_line TEXT,profile_name TEXT);
        CREATE TABLE mikrotik_ip_pools(router_name TEXT,name TEXT,ranges TEXT);
        CREATE TABLE router_commands(id INTEGER PRIMARY KEY,router_name TEXT,customer_id INTEGER,pppoe TEXT,action TEXT,payload TEXT,status TEXT,created_at TEXT,requested_by TEXT);
        ALTER TABLE customers ADD COLUMN latitude TEXT;
        ALTER TABLE customers ADD COLUMN longitude TEXT;
        ''')
        c.commit();c.close()
        base.app.view_functions['customer_edit'] = pbr_client.customer_edit_pbr
        service.setup(base.app)

    def setUp(self):
        c = base.db()
        for table in ('customers','plans','push_ppp_profiles','plan_profile_map','mikrotik_ip_pools','router_commands'):
            c.execute('DELETE FROM ' + table)
        c.executemany('INSERT INTO plans(id,name,download_mbps,upload_mbps,price,active) VALUES(?,?,?,?,?,1)', [(i,str(speed),speed,speed,price) for i,(speed,price) in enumerate(((20,800),(40,1000),(60,1300),(100,1500),(200,2000),(300,3000)),1)])
        c.execute("INSERT INTO plans VALUES(99,'Viejo',25,10,900,0)")
        c.execute("INSERT INTO customers(id,name,pppoe,plan_id,mikrotik_profile,router_name,pbr_line,ip_address) VALUES(1,'Prueba','prueba',99,'legacy','CCR2116','Linea-4-Altice','10.55.55.59')")
        c.executemany('INSERT INTO push_ppp_profiles VALUES(?,?,?,?,?)', [
            ('CCR2116','legacy','10M/25M','Pool-HSGQ','10.55.55.1'),
            ('CCR2116','20M-Altice1','20M/20M','Pool-HSGQ','10.55.55.1'),
            ('CCR2116','40M-Altice1','40M/40M','Pool-HSGQ','10.55.55.1'),
            ('CCR2116','wrong-pool','60M/60M','Hioso','10.20.0.1'),
            ('OTHER','wrong-router','300M/300M','Pool-HSGQ','10.55.55.1'),
        ])
        c.execute("INSERT INTO mikrotik_ip_pools VALUES('CCR2116','Pool-HSGQ','10.55.55.2-10.55.55.254')")
        c.commit();c.close()

    def customer(self,c):
        return c.execute('SELECT * FROM customers WHERE id=1').fetchone()

    def test_rate_and_connectivity(self):
        c=base.db();row=self.customer(c)
        self.assertEqual(service.resolve(c,99,'CCR2116','Linea-4-Altice','',row),'legacy')
        self.assertEqual(service.resolve(c,1,'CCR2116','Linea-4-Altice','',row),'20M-Altice1')
        self.assertEqual(service.resolve(c,2,'CCR2116','Linea-4-Altice','',row),'40M-Altice1')
        for plan in (3,6):
            with self.assertRaises(ValueError):service.resolve(c,plan,'CCR2116','','',row)
        self.assertEqual(service.resolve(c,1,'CCR2116','','10.55.55.60'),'20M-Altice1')
        with self.assertRaises(ValueError):service.resolve(c,1,'CCR2116','','')
        c.close()

    def test_bad_mapping_cannot_override_rate(self):
        c=base.db();c.execute("INSERT INTO plan_profile_map VALUES('CCR2116',1,'Linea-4-Altice','legacy')")
        self.assertEqual(service.resolve(c,1,'CCR2116','Linea-4-Altice','',self.customer(c)),'20M-Altice1');c.close()

    def test_form_hides_old_dropdown_preserves_current(self):
        from html.parser import HTMLParser
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.options=[];self.select=''
            def handle_starttag(self,tag,attrs):
                a=dict(attrs)
                if tag=='select':self.select=a.get('name')
                if tag=='option' and self.select=='plan_id':self.options.append(a)
            def handle_endtag(self,tag):
                if tag=='select':self.select=''
        c=base.db();row=self.customer(c);c.close()
        html='<form><select name="plan_id"><option value="99" selected>Viejo</option>'+''.join(f'<option value="{i}">{i}</option>' for i in range(1,7))+'</select><label>Perfil MikroTik <div class="if-profile-row"><select name="mikrotik_profile"><option>legacy</option></select><button>Perfiles</button></div><small>Old</small></label></form><script>window.IFPROFILE=old;</script>'
        result=service.clean_form(html,row);parser=Parser();parser.feed(result)
        self.assertNotIn('window.IFPROFILE',result)
        self.assertNotIn('<select name="mikrotik_profile"',result)
        self.assertIn('value="legacy"',result)
        self.assertEqual(len([o for o in parser.options if 'disabled' not in o]),6)

    def edit(self,data):
        with base.app.test_request_context('/customers/1/edit',method='POST',data=data):
            from flask import session
            session['user']='manuel'
            with patch.object(base,'logged_in',return_value=True):
                return base.app.view_functions['customer_edit'](id=1)

    def test_ordinary_edit_preserves_legacy_without_command(self):
        self.edit({'name':'New name','pppoe':'prueba','ip_address':'10.55.55.59','pbr_line':'Linea-4-Altice','router_name':'CCR2116'})
        c=base.db();row=self.customer(c)
        self.assertEqual((row['plan_id'],row['mikrotik_profile']),(99,'legacy'))
        self.assertEqual(c.execute('SELECT COUNT(*) FROM router_commands').fetchone()[0],0);c.close()

    def test_explicit_plan_change_queues_only_customer_profile(self):
        self.edit({'name':'Prueba','pppoe':'prueba','plan_id':'1','mikrotik_profile':'malicious','ip_address':'10.55.55.59','pbr_line':'Linea-4-Altice','router_name':'CCR2116'})
        c=base.db();row=self.customer(c);commands=c.execute('SELECT * FROM router_commands').fetchall()
        self.assertEqual((row['plan_id'],row['mikrotik_profile'],row['pbr_line']),(1,'20M-Altice1','Linea-4-Altice'))
        self.assertEqual(len(commands),1);self.assertEqual(commands[0]['action'],'CHANGE_PROFILE')
        self.assertEqual(pbr_client._dec_payload(commands[0]['payload']),{'profile':'20M-Altice1'});c.close()

    def test_missing_profile_saves_nothing(self):
        self.edit({'name':'Should not save','plan_id':'3','mikrotik_profile':'wrong-pool'})
        c=base.db();self.assertEqual(self.customer(c)['name'],'Prueba')
        self.assertEqual(c.execute('SELECT COUNT(*) FROM router_commands').fetchone()[0],0);c.close()


if __name__=='__main__':unittest.main()
