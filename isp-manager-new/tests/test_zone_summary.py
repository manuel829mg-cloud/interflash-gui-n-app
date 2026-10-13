import os
import tempfile
import unittest
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/summary.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
from zone_summary import totals

class ZoneSummaryTests(unittest.TestCase):
    def setUp(self):
        c=base.db()
        for t in ('payments','whatsapp_outbox','invoices','customers','zones'):
            c.execute('DELETE FROM '+t)
        c.executescript("""
        INSERT INTO zones(id,name) VALUES(1,'Resumen'),(2,'Otra');
        INSERT INTO customers(id,name,status,zone_id,zone) VALUES(1,'Con deuda','ACTIVO',1,'Resumen'),(2,'Suspendido legado','SUSPENDIDO',NULL,'Resumen'),(3,'Eliminado','ELIMINADO',1,'Resumen'),(4,'Otro','ACTIVO',2,'Otra');
        INSERT INTO invoices(id,customer_id,concept,amount,issue_date,due_date,status) VALUES(1,1,'Internet',1000,'2026-10-10','2026-10-15','PENDIENTE'),(2,1,'Internet',500,'2026-09-10','2026-09-15','PENDIENTE'),(3,2,'Internet',1000,'2026-10-10','2026-10-15','PENDIENTE'),(4,2,'Internet',900,'2026-09-10','2026-09-15','PAGADA');
        INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(1,1,250,'2026-10-13'),(2,3,1200,'2026-10-13');
        INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at,error) VALUES(1,'8090000000','ZONE_REMINDER','Aviso','ERROR','2026-10-15 10:00','Proveedor sin respuesta');
        """)
        c.commit();c.close()
        self.client=wsgi.app.test_client()
    def test_totals_without_duplicates_and_negative_debt(self):
        c=base.db();result=totals(c);c.close()
        self.assertEqual(result[1],{'clients':2,'balance':1250,'suspended':1,'debtors':1})
        self.assertEqual(result[2]['balance'],0)
    def test_auth_filters_history_and_missing_zone(self):
        self.assertEqual(self.client.get('/zones/1/summary').status_code,302)
        with self.client.session_transaction() as s:s['auth']=True;s['role']='ADMIN'
        h=self.client.get('/zones/1/summary').get_data(as_text=True)
        self.assertIn('RD$1,250.00',h);self.assertIn('Proveedor sin respuesta',h)
        filtered=self.client.get('/zones/1/summary?filter=suspended').get_data(as_text=True).split('<h2>Historial de facturas')[0]
        self.assertIn('Suspendido legado',filtered);self.assertNotIn('>Con deuda</a>',filtered)
        self.assertEqual(self.client.get('/zones/999/summary').status_code,404)
        self.assertIn('Resumen e historial',self.client.get('/zones').get_data(as_text=True))
