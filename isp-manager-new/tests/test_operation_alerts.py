import os,tempfile,unittest
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=_tmp.name+'/alerts.db'
os.environ['INTERFLASH_TESTING']='1'
with patch('threading.Thread.start'):import wsgi
import app as base
import operation_alerts as alerts

class AlertTests(unittest.TestCase):
    def setUp(self):
        c=base.db();c.execute('DELETE FROM operation_alerts');c.execute('DELETE FROM whatsapp_outbox');c.commit();c.close()
    def test_billing_deduplicated_resolved_and_reopened(self):
        alerts.billing_failed();alerts.billing_failed()
        rows,_,_=alerts.read_alerts();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['occurrences'],2)
        alerts.billing_succeeded();self.assertEqual(alerts.read_alerts()[0],[])
        alerts.billing_failed();self.assertEqual(len(alerts.read_alerts()[0]),1)
    def test_page_auth_and_banner_with_whatsapp_failure(self):
        client=wsgi.app.test_client();self.assertEqual(client.get('/operations/alerts').status_code,302)
        c=base.db();c.execute("INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(999,'8090000000','ZONE_REMINDER','Prueba','ERROR','2026-10-15')");c.commit();c.close()
        with client.session_transaction() as s:s['auth']=True;s['role']='ADMIN'
        self.assertEqual(alerts.read_alerts()[2],1)
        self.assertIn('1 avisos con error',client.get('/operations/alerts').get_data(as_text=True))
        self.assertIn('Revisar fallos de facturación',client.get('/zones').get_data(as_text=True))
