import test_greenapi as fixture
from unittest.mock import patch
import whatsapp_menu as menu
import unittest
base=fixture.base;g=fixture.g
class MenuTests(unittest.TestCase):
 login=fixture.GreenTests.login
 event=fixture.GreenTests.event
 def setUp(self):
  fixture.GreenTests.setUp(self);c=base.db()
  for table in ('whatsapp_menu_jobs','whatsapp_menu_state','whatsapp_queue'):c.execute('DELETE FROM '+table)
  c.execute('UPDATE whatsapp_menu_config SET enabled=1');c.execute('UPDATE greenapi_config SET active=1');c.commit();c.close()
 def test_reply_dedup_and_single_attempt(self):
  self.event();self.event()
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_menu_jobs').fetchone()[0],1);c.close()
  with base.app.app_context(),patch.object(g,'send_text',return_value=(True,'greenapi:710722758220:auto','')) as send:
   menu.process_one();menu.process_one();self.assertEqual(send.call_count,1)
 def test_pause_and_disabled(self):
  self.event(idMessage='support',messageData={'textMessageData':{'textMessage':'4'}})
  self.event(idMessage='hello')
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_menu_jobs').fetchone()[0],1);c.execute('UPDATE whatsapp_menu_config SET enabled=0');c.commit();c.close()
  with base.app.app_context(),patch.object(g,'send_text') as send:menu.process_one();send.assert_not_called()
 def test_toggle_csrf(self):
  self.login();self.assertEqual(self.client.post('/whatsapp/menu',data={'enabled':'0'}).status_code,403)
  with self.client.session_transaction() as s:s['wa_menu_csrf']='test'
  self.client.post('/whatsapp/menu',data={'enabled':'0','csrf':'test'})
  self.event();c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_menu_jobs').fetchone()[0],0);c.close()
 def test_invoice_only_for_registered_phone(self):
  c=base.db();cid=c.execute("INSERT INTO customers(name,phone) VALUES('Prueba','18095550123')").lastrowid
  iid=c.execute("INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date) VALUES(?,'Internet',1000,'2026-10-01','2026-10-30')",(cid,)).lastrowid
  c.execute("INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(?,?,250,'2026-10-02')",(cid,iid));c.commit();c.close()
  self.event(idMessage='invoice',messageData={'textMessageData':{'textMessage':'1'}})
  c=base.db();self.assertIn('750.00',c.execute('SELECT body FROM whatsapp_queue').fetchone()[0]);c.close()
  self.event(idMessage='unknown',senderData={'chatId':'18095550999@c.us'},messageData={'textMessageData':{'textMessage':'1'}})
  c=base.db();body=c.execute("SELECT body FROM whatsapp_queue WHERE phone='18095550999'").fetchone()[0];c.close();self.assertNotIn('750',body);self.assertIn('verificar',body)
