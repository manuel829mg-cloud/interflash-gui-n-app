import os,tempfile,unittest
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=_tmp.name+'/test.db';os.environ['INTERFLASH_TESTING']='1'
with patch('threading.Thread.start'):
 import wsgi
import app as base
import invoice_void
import payment_flow

class VoidTests(unittest.TestCase):
 def setUp(self):
  c=base.db()
  for t in ('invoice_cancellations','payments','invoices','customers','router_commands','payment_promises'):c.execute('DELETE FROM '+t)
  c.execute("INSERT INTO customers(id,name,status) VALUES(1,'Cliente de prueba','ACTIVO')")
  c.execute("INSERT INTO invoices(id,customer_id,concept,amount,issue_date,due_date,status) VALUES(1,1,'Internet',800,'2026-01-01','2026-01-30','PENDIENTE')")
  c.execute("INSERT INTO router_commands(customer_id,action,status,requested_by) VALUES(1,'SUSPEND','PENDIENTE','ZONA:Prueba')")
  c.commit();c.close()
  self.client=wsgi.app.test_client()
  with self.client.session_transaction() as s:s['auth']=True;s['role']='ADMIN';s['user']='test';s['invoice_void_csrf']='token'
 def test_cancel_history_balance_and_no_payment(self):
  r=self.client.post('/invoices/1/cancel',data={'csrf':'token','reason':'Factura duplicada'},follow_redirects=True)
  self.assertEqual(r.status_code,200);html=r.get_data(as_text=True)
  self.assertIn('FACTURA ANULADA',html);self.assertIn('Factura duplicada',html)
  self.assertNotIn('id="registrar-pago"',html)
  with self.assertRaises(ValueError):payment_flow.record_payment(invoice_id=1)
  c=base.db();self.assertEqual(c.execute('SELECT status FROM router_commands').fetchone()[0],'CANCELADO');self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1);c.close()
  self.assertFalse(invoice_void.cancel_invoice(1,'Segundo intento','test'))
  listing=self.client.get('/invoices').get_data(as_text=True)
  self.assertIn('ANULADA',listing);self.assertNotIn('>VENCIDA<',listing)
 def test_paid_or_partial_cannot_be_cancelled(self):
  payment_flow.record_payment(1,1,'100')
  with self.assertRaises(ValueError):invoice_void.cancel_invoice(1,'Creada por error','test')
 def test_keep_cut_for_other_overdue_invoice(self):
  c=base.db();c.execute("INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date,status) VALUES(1,'Otro mes',800,'2026-01-01','2026-01-30','PENDIENTE')");c.commit();c.close()
  invoice_void.cancel_invoice(1,'Duplicada por error','test')
  c=base.db();self.assertEqual(c.execute('SELECT status FROM router_commands').fetchone()[0],'PENDIENTE');c.close()
 def test_authorization_csrf_and_reason(self):
  self.assertEqual(self.client.post('/invoices/1/cancel',data={'reason':'Error duplicada'}).status_code,403)
  with self.assertRaises(ValueError):invoice_void.cancel_invoice(1,'','test')
  with self.client.session_transaction() as s:s['role']='CAJA'
  self.assertEqual(self.client.post('/invoices/1/cancel',data={'csrf':'token','reason':'Duplicada'}).status_code,403)
if __name__=='__main__':unittest.main()
