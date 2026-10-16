import unittest,sqlite3,json
from datetime import datetime,timedelta
from automatic_ip import suggest
class AutomaticIPTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
  self.c.executescript('''CREATE TABLE customers(id,name,ip_address,router_name,plan_id,mikrotik_profile);
CREATE TABLE plans(id,active,upload_mbps,download_mbps);
CREATE TABLE push_ppp_profiles(router_name,name,rate_limit,remote_address,local_address);
CREATE TABLE mikrotik_ip_pools(router_name,name,ranges,updated_at);
CREATE TABLE mikrotik_ip_used(router_name,address,updated_at);
CREATE TABLE app_settings(key,value);
INSERT INTO plans VALUES(1,1,20,20);
INSERT INTO push_ppp_profiles VALUES('R','Plan20','20M/20M','dynamic','10.0.0.1');''')
  now=datetime.now().isoformat()
  self.c.execute('INSERT INTO mikrotik_ip_pools VALUES(?,?,?,?)',('R','dynamic','10.0.0.100-10.0.0.200',now))
  self.c.execute('INSERT INTO mikrotik_ip_used VALUES(?,?,?)',('R','10.0.0.2',now))
 def configure(self,ranges='10.0.0.2-10.0.0.5'):
  self.c.execute('INSERT INTO app_settings VALUES(?,?)',('automatic_ip_static_ranges',json.dumps([{'router':'R','plan_id':1,'profile':'Plan20','ranges':ranges}])))
 def test_missing_range(self):
  with self.assertRaisesRegex(ValueError,'rango reservado'):suggest(self.c,'R',1)
 def test_occupied_addresses(self):
  self.configure();self.c.execute("INSERT INTO customers VALUES(1,'Test','10.0.0.3','R',1,'Plan20')")
  result=suggest(self.c,'R',1);self.assertEqual(result['ip'],'10.0.0.4');self.assertTrue(result['confirmation_required'])
 def test_preserve_existing(self):
  self.c.execute("INSERT INTO customers VALUES(1,'Test','10.0.0.150','R',1,'Plan20')")
  self.assertEqual(suggest(self.c,'R',1,1),{'ip':'10.0.0.150','preserved':True,'confirmation_required':False})
 def test_overlap(self):
  self.configure('10.0.0.2-10.0.0.110')
  with self.assertRaisesRegex(ValueError,'solapa'):suggest(self.c,'R',1)
 def test_stale(self):
  self.configure();self.c.execute('UPDATE mikrotik_ip_used SET updated_at=?',((datetime.now()-timedelta(hours=1)).isoformat(),))
  with self.assertRaisesRegex(ValueError,'Sincroniza'):suggest(self.c,'R',1)
 def test_exhaustion(self):
  self.configure('10.0.0.2')
  with self.assertRaisesRegex(ValueError,'No quedan'):suggest(self.c,'R',1)
 def test_read_only(self):
  self.configure();before=self.c.total_changes;suggest(self.c,'R',1);self.assertEqual(self.c.total_changes,before)
if __name__=='__main__':unittest.main()
