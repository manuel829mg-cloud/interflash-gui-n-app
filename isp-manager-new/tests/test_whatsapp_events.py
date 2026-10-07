import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/events.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
import whatsapp_events as events
import payment_flow

class EventTests(unittest.TestCase):
    def setUp(self):
        c=base.db()
        for table in ('whatsapp_event_keys','whatsapp_outbox_links','whatsapp_outbox','whatsapp_queue','whatsapp_messages','whatsapp_threads','payments','payment_promises','invoices','customers','router_commands'):
            c.execute('DELETE FROM '+table)
        c.execute("INSERT INTO customers(id,name,phone,pppoe,status) VALUES(1,'Prueba','8090000000','prueba','ACTIVO')")
        c.execute("INSERT INTO invoices(id,customer_id,concept,amount,issue_date,due_date,status) VALUES(1,1,'Internet',1000,'2026-10-01',?,'PENDIENTE')", (date.today().isoformat(),))
        c.execute("UPDATE app_settings SET value='1' WHERE key='whatsapp_enabled'")
        c.execute("UPDATE app_settings SET value='0' WHERE key='whatsapp_event_floor'")
        c.commit();c.close()
    def rows(self,sql):
        c=base.db(); rows=c.execute(sql).fetchall(); c.close(); return rows
    def test_payment_routes_through_configured_provider_once(self):
        payment_flow.record_payment(1,1,'1000')
        with patch.object(events.wa,'_meta_ready',return_value=True), patch.object(events.wa,'_send_text',return_value=(True,'test-provider-id','')) as send:
            self.assertEqual(events.send_outbox()[0],1)
            self.assertEqual(events.send_outbox()[0],0)
            send.assert_called_once()
        self.assertEqual(self.rows('SELECT status FROM whatsapp_queue')[0][0],'ACEPTADO')
        self.assertEqual(self.rows('SELECT status FROM whatsapp_outbox')[0][0],'ACEPTADO')
    def test_provider_error_is_visible_not_retried(self):
        payment_flow.record_payment(1,1,'100')
        with patch.object(events.wa,'_meta_ready',return_value=True), patch.object(events.wa,'_send_text',return_value=(False,'','Proveedor no confirmado')) as send:
            events.send_outbox();events.send_outbox();send.assert_called_once()
        self.assertEqual(self.rows('SELECT status FROM whatsapp_queue')[0][0],'ERROR')
    def test_historical_notices_excluded(self):
        payment_flow.record_payment(1,1,'100')
        c=base.db();c.execute("UPDATE app_settings SET value=(SELECT MAX(id) FROM whatsapp_outbox) WHERE key='whatsapp_event_floor'");c.commit();c.close()
        with patch.object(events.wa,'_meta_ready',return_value=True), patch.object(events.wa,'_send_text') as send:
            events.send_outbox();send.assert_not_called()
    def test_promise_confirmation_reminder_and_payment(self):
        events.create_promise(1,1,date.today().isoformat(),'500','')
        events.promise_reminders()
        self.assertEqual(len(self.rows('SELECT * FROM whatsapp_outbox')),1)
        c=base.db();c.execute('UPDATE payment_promises SET created_at=?',((date.today()-timedelta(days=1)).isoformat(),));c.commit();c.close()
        events.promise_reminders();events.promise_reminders()
        self.assertEqual(len(self.rows("SELECT * FROM whatsapp_outbox WHERE template_code='PROMISE_DUE'")),1)
        payment_flow.record_payment(1,1,'1000'); events.promise_reminders()
        self.assertEqual(self.rows('SELECT status FROM payment_promises')[0][0],'CUMPLIDA')
    def test_wrong_customer_invoice_rejected(self):
        with self.assertRaises(ValueError):events.create_promise(1,999,date.today().isoformat(),'100','')
        self.assertFalse(self.rows('SELECT * FROM payment_promises'))
    def test_successful_router_callback_once_and_failure_silent(self):
        c=base.db();c.execute("INSERT INTO router_commands(id,customer_id,action,status) VALUES(1,1,'SUSPEND','EN_PROCESO')");c.commit();c.close()
        client=wsgi.app.test_client()
        with patch('pbr_client._auth',return_value=True):
            r=client.post('/api/mikrotik/agent/result',json={'id':1,'ok':False});self.assertEqual(r.status_code,200)
            self.assertFalse(self.rows('SELECT * FROM whatsapp_outbox'))
            client.post('/api/mikrotik/agent/result',json={'id':1,'ok':True})
            client.post('/api/mikrotik/agent/result',json={'id':1,'ok':True})
        self.assertEqual(len(self.rows('SELECT * FROM whatsapp_outbox')),1)
    def test_enable_requires_verified_connection_and_csrf(self):
        client=wsgi.app.test_client()
        with client.session_transaction() as s:s['auth']=True;s['role']='ADMIN';s['wa_events_csrf']='test'
        with patch.object(events.green,'enabled',return_value=True),patch.object(events.green,'api',return_value={'stateInstance':'authorized'}):
            self.assertEqual(client.get('/whatsapp/automatics').status_code,200)
            self.assertEqual(client.post('/whatsapp/automatics',data={'action':'enable','csrf':'wrong'}).status_code,403)
            self.assertEqual(client.post('/whatsapp/automatics',data={'action':'enable','csrf':'test'}).status_code,302)

if __name__=='__main__':unittest.main()
