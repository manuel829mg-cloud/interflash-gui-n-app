import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/secondary.db'
os.environ['INTERFLASH_TESTING'] = '1'
# All checks are local: prevent background workers and provider connections.
with patch('threading.Thread.start'), patch('socket.socket.connect', side_effect=AssertionError('Network disabled in tests')):
    import wsgi
import app as base
import pbr_client
import whatsapp_events as events
import whatsapp_suite as wa
import payment_flow
import zone_whatsapp_reminders as reminders
from customer_phones import recipients

class SecondaryPhoneTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('socket.socket.connect', side_effect=AssertionError('Network disabled in tests'))
        self.network.start(); self.addCleanup(self.network.stop)
        c=base.db()
        for table in ('whatsapp_event_keys','whatsapp_outbox_links','whatsapp_outbox','whatsapp_queue','payments','payment_promises','invoices','customers','zones','router_commands'):
            c.execute('DELETE FROM '+table)
        c.execute("INSERT INTO customers(id,name,phone,phone_secondary,status) VALUES(1,'Prueba','8090000000','8290000000','ACTIVO')")
        c.execute("UPDATE app_settings SET value='1' WHERE key='whatsapp_enabled'")
        c.commit(); c.close()
    def test_distinct_normalized_recipients(self):
        self.assertEqual(recipients({'phone':'8090000000','phone_secondary':'+1 (809) 000-0000'}),['18090000000'])
        self.assertEqual(recipients({'phone':'8090000000'}),['18090000000'])
        self.assertEqual(recipients({'phone':'','phone_secondary':'8290000000'}),['18290000000'])
    def test_events_once_per_number_and_secondary_inbound(self):
        c=base.db()
        self.assertTrue(events.enqueue(c,'TEST',1,'PAYMENT','Prueba'))
        self.assertFalse(events.enqueue(c,'TEST',1,'PAYMENT','Prueba'))
        self.assertEqual([r[0] for r in c.execute('SELECT phone FROM whatsapp_outbox ORDER BY id')],['18090000000','18290000000'])
        self.assertEqual(wa._customer_by_phone(c,'18290000000')['id'],1)
        c.close()
    def test_second_reminder_rechecks_debt(self):
        c=base.db()
        c.execute("INSERT INTO zones(id,name,whatsapp_reminder_enabled,cut_days_after,cut_time) VALUES(1,'Prueba',1,6,'14:00')")
        c.execute('UPDATE customers SET zone_id=1')
        c.execute("INSERT INTO invoices(id,customer_id,amount,concept,status,due_date,issue_date) VALUES(1,1,1000,'Internet','PENDIENTE','2026-10-15','2026-10-01')")
        c.commit();c.close()
        self.assertEqual(reminders.process(datetime(2026,10,15,10)),1)
        c=base.db();ids=[r[0] for r in c.execute('SELECT id FROM whatsapp_outbox ORDER BY id')]
        self.assertEqual(len(ids),2)
        for oid in ids:self.assertTrue(reminders.valid(c,oid,datetime(2026,10,15,11)))
        c.execute("UPDATE invoices SET status='PAGADA'")
        for oid in ids:self.assertFalse(reminders.valid(c,oid,datetime(2026,10,15,11)))
        c.close()
    def test_partial_payment_goes_to_both(self):
        payment_flow.record_payment(customer_id=1,amount='100')
        c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_outbox').fetchone()[0],2);c.close()
    def test_form_create_edit_clear_and_no_router_changes(self):
        c=base.db()
        c.execute('DELETE FROM plans');c.execute('DELETE FROM push_ppp_profiles')
        c.execute("INSERT INTO plans(id,name,download_mbps,upload_mbps,price) VALUES(1,'Prueba',20,20,1000)")
        c.execute("INSERT INTO push_ppp_profiles(router_name,name,rate_limit) VALUES('CCR2116','Prueba','20M/20M')")
        c.commit();c.close()
        client=wsgi.app.test_client()
        with client.session_transaction() as s:s['auth']=True;s['role']='ADMIN'
        data={'name':'Nuevo','phone':'8091111111','phone_secondary':'8291111111','status':'ACTIVO','router_name':'CCR2116','plan_id':'1','mikrotik_profile':'Prueba'}
        response=client.post('/customers/new',data=data)
        self.assertEqual(response.status_code,302)
        c=base.db();cu=c.execute("SELECT * FROM customers WHERE name='Nuevo'").fetchone();self.assertIsNotNone(cu);cid=cu['id'];self.assertEqual(cu['phone_secondary'],'8291111111');c.close()
        response=client.get(f'/customers/{cid}/edit')
        self.assertIn(b'name="phone_secondary"',response.data);self.assertIn(b'8291111111',response.data)
        data['phone_secondary']='8491111111'
        self.assertEqual(client.post(f'/customers/{cid}/edit',data=data).status_code,302)
        c=base.db();self.assertEqual(c.execute('SELECT phone_secondary FROM customers WHERE id=?',(cid,)).fetchone()[0],'8491111111');c.close()
        data['phone_secondary']=''
        client.post(f'/customers/{cid}/edit',data=data)
        c=base.db();self.assertEqual(c.execute('SELECT phone_secondary FROM customers WHERE id=?',(cid,)).fetchone()[0],'');self.assertEqual(c.execute('SELECT COUNT(*) FROM router_commands').fetchone()[0],0);c.close()

if __name__=='__main__':unittest.main()
