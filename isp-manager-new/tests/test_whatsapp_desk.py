import os, tempfile, unittest
from pathlib import Path
_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(_tmp.name) / 'desk.db')
os.environ['SECRET_KEY'] = 'desk-test-secret-with-at-least-32-characters'
import app as base
import whatsapp_suite as wa
wa.setup(base.app)
base.app.config['TESTING'] = True

class DeskTests(unittest.TestCase):
 def test_customer_balance_drafts_and_settings(self):
  c = base.db()
  cid = c.execute("INSERT INTO customers(name,phone) VALUES(?,?)", ('Cliente <prueba>', '18095551234')).lastrowid
  iid = c.execute("INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date) VALUES(?, 'Internet',1000,'2026-10-01','2026-10-30')", (cid,)).lastrowid
  c.execute("INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(?,?,250,'2026-10-02')", (cid,iid))
  t = wa._thread_for_phone(c,'18095551234')
  c.commit();c.close()
  client = base.app.test_client()
  with client.session_transaction() as session: session['auth'] = True
  page = client.get('/whatsapp?thread='+str(t['id']))
  self.assertEqual(page.status_code,200)
  text = page.get_data(as_text=True)
  self.assertIn('RD$750.00',text)
  self.assertIn('Cliente &lt;prueba&gt;',text)
  self.assertIn('Resumen de factura',text)
  self.assertIn('data-message=',text)
  self.assertNotIn('Webhook:',text)
  self.assertNotIn('Enviar prueba',text)
  settings = client.get('/whatsapp/settings').get_data(as_text=True)
  self.assertIn('Webhook:',settings)
  self.assertIn('Enviar prueba',settings)
  c = base.db()
  self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_queue').fetchone()[0],0)
  c.close()

if __name__ == '__main__': unittest.main()
