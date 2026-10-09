import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/reminders.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
import zone_whatsapp_reminders as reminders
import whatsapp_events as events

class ReminderTests(unittest.TestCase):
    def setUp(self):
        c = base.db()
        for table in ('whatsapp_event_keys','whatsapp_outbox_links','whatsapp_outbox','whatsapp_queue','payments','payment_promises','invoices','customers','zones'):
            c.execute('DELETE FROM '+table)
        c.execute("INSERT INTO zones(id,name,cut_days_after,cut_time,whatsapp_reminder_enabled,whatsapp_reminder_days) VALUES(1,'Zona',6,'14:00',1,2)")
        c.execute("INSERT INTO customers(id,name,phone,status,zone_id) VALUES(1,'Prueba','8090000000','ACTIVO',1)")
        c.execute("INSERT INTO invoices(id,customer_id,concept,amount,issue_date,due_date,status) VALUES(1,1,'Internet',1000,'2026-09-25','2026-09-30','PENDIENTE')")
        c.execute("UPDATE app_settings SET value='1' WHERE key='whatsapp_enabled'")
        c.execute("UPDATE app_settings SET value='0' WHERE key='whatsapp_event_floor'")
        c.commit(); c.close()
    def execute(self,sql):
        c=base.db(); c.executescript(sql);c.commit();c.close()
    def test_once_and_partial_balance(self):
        self.execute("INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(1,1,250,'2026-10-04')")
        self.assertEqual(reminders.process(datetime(2026,10,4,8)),1)
        self.assertEqual(reminders.process(datetime(2026,10,4,9)),0)
        c=base.db();self.assertIn('750.00',c.execute('SELECT message FROM whatsapp_outbox').fetchone()[0]);c.close()
    def test_only_scheduled_date_and_hours(self):
        for now in (datetime(2026,10,3,9),datetime(2026,10,4,7,59),datetime(2026,10,4,20),datetime(2026,10,5,9)):
            self.assertEqual(reminders.process(now),0)
    def test_disabled_zone_or_global(self):
        self.execute('UPDATE zones SET whatsapp_reminder_enabled=0')
        self.assertEqual(reminders.process(datetime(2026,10,4,8)),0)
        self.execute("UPDATE zones SET whatsapp_reminder_enabled=1;UPDATE app_settings SET value='0' WHERE key='whatsapp_enabled'")
        self.assertEqual(reminders.process(datetime(2026,10,4,8)),0)
    def test_paid_invoice_and_other_customers_excluded(self):
        self.execute("UPDATE invoices SET status='PAGADA';INSERT INTO customers(name,phone,status,zone_id) VALUES('Otro','8091111111','ACTIVO',2)")
        self.assertEqual(reminders.process(datetime(2026,10,4,8)),0)
    def test_full_payment_pending_status_excluded(self):
        self.execute("INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(1,1,1000,'2026-10-04')")
        self.assertEqual(reminders.process(datetime(2026,10,4,8)),0)
    def test_promise_and_legacy_zone(self):
        self.execute("UPDATE customers SET zone_id=NULL,zone='Zona'")
        self.assertEqual(reminders.process(datetime(2026,10,4,8)),1)
        self.execute("INSERT INTO payment_promises(customer_id,promise_date,status) VALUES(1,'2026-10-06','PENDIENTE')")
        c=base.db();self.assertFalse(reminders.valid(c,1,datetime(2026,10,4,8)));c.close()
    def test_cancel_after_payment_and_refresh_partial(self):
        reminders.process(datetime(2026,10,4,8))
        c=base.db();oid=c.execute('SELECT id FROM whatsapp_outbox').fetchone()[0];c.close()
        self.execute("INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(1,1,250,'2026-10-04')")
        c=base.db();self.assertTrue(reminders.valid(c,oid,datetime(2026,10,4,8)));self.assertIn('750.00',c.execute('SELECT message FROM whatsapp_outbox').fetchone()[0]);c.commit();c.close()
        self.execute("UPDATE invoices SET status='PAGADA'")
        with patch.object(events.wa,'_meta_ready',return_value=True),patch.object(events.wa,'_send_text') as send:
            self.assertEqual(events.send_outbox()[0],0);send.assert_not_called()
        c=base.db();self.assertEqual(c.execute('SELECT status FROM whatsapp_outbox').fetchone()[0],'CANCELADO');c.close()
    def test_zero_days_before_cut_and_month_boundary(self):
        self.execute("UPDATE zones SET whatsapp_reminder_days=0")
        self.assertEqual(reminders.process(datetime(2026,10,6,8)),1)
        c=base.db();self.assertEqual(list(reminders.candidates(c,datetime(2026,10,6,14))),[]);c.close()
    def test_form_create_edit_and_validation(self):
        client=wsgi.app.test_client()
        with client.session_transaction() as session:session['auth']=True;session['role']='ADMIN'
        data={'name':'Nueva','billing_day':'30','invoice_days_before':'5','cut_days_after':'6','cut_time':'14:00','whatsapp_reminder_enabled':'1','whatsapp_reminder_days':'3'}
        self.assertEqual(client.post('/zones',data=data).status_code,302)
        c=base.db();z=c.execute("SELECT * FROM zones WHERE name='Nueva'").fetchone();c.close()
        self.assertEqual(z['whatsapp_reminder_days'],3);self.assertEqual(z['whatsapp_reminder_enabled'],1)
        self.assertIn('Recordatorio por WhatsApp',client.get('/zones?edit='+str(z['id'])).get_data(as_text=True))
        data['zone_id']=str(z['id']);data.pop('whatsapp_reminder_enabled');client.post('/zones',data=data)
        c=base.db();self.assertEqual(c.execute('SELECT whatsapp_reminder_enabled FROM zones WHERE id=?',(z['id'],)).fetchone()[0],0);c.close()
        data['whatsapp_reminder_days']='-1';client.post('/zones',data=data)
        c=base.db();self.assertEqual(c.execute('SELECT whatsapp_reminder_days FROM zones WHERE id=?',(z['id'],)).fetchone()[0],3);c.close()

if __name__=='__main__':unittest.main()
