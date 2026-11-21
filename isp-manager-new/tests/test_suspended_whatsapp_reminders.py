import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/suspended_reminders.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi

import app as base
import suspended_whatsapp_reminders as reminders

RD = ZoneInfo('America/Santo_Domingo')


class SuspendedReminderTests(unittest.TestCase):
    def setUp(self):
        c = base.db()
        for table in (
            'whatsapp_event_keys', 'whatsapp_outbox_links',
            'whatsapp_outbox', 'whatsapp_queue', 'payments',
            'payment_promises', 'invoices', 'customers', 'router_commands'
        ):
            c.execute('DELETE FROM ' + table)
        c.execute("""INSERT INTO customers(
            id,name,phone,pppoe,status,service_status
        ) VALUES(1,'Prueba','8090000000','prueba','SUSPENDIDO','SUSPENDIDO')""")
        c.execute("""INSERT INTO invoices(
            id,customer_id,concept,amount,issue_date,due_date,status
        ) VALUES(1,1,'Internet',1000,'2026-11-01','2026-11-15','PENDIENTE')""")
        c.execute("""INSERT INTO router_commands(
            id,customer_id,action,status,executed_at
        ) VALUES(3,1,'SUSPEND','COMPLETADO','2026-11-16T10:00:00-04:00')""")
        c.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('whatsapp_enabled','1')")
        c.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('whatsapp_event_floor','0')")
        c.commit()
        c.close()

    def execute(self, sql):
        c = base.db()
        c.executescript(sql)
        c.commit()
        c.close()

    def test_two_and_four_days_once_with_footer(self):
        self.assertEqual(reminders.process(datetime(2026,11,18,9,0,tzinfo=RD)),0)
        self.assertEqual(reminders.process(datetime(2026,11,18,11,0,tzinfo=RD)),1)
        self.assertEqual(reminders.process(datetime(2026,11,18,12,0,tzinfo=RD)),0)
        c = base.db()
        first = c.execute("SELECT * FROM whatsapp_outbox").fetchone()
        self.assertEqual(first['template_code'],'SUSPENDED_D2')
        self.assertIn('Inter Flash, siempre conectado contigo.',first['message'])
        self.assertTrue(reminders.valid(c,first['id'],datetime(2026,11,18,11,0,tzinfo=RD)))
        c.execute("UPDATE whatsapp_outbox SET status='ACEPTADO',sent_at='2026-11-18T11:00:00-04:00'")
        c.commit()
        c.close()
        self.assertEqual(reminders.process(datetime(2026,11,19,12,0,tzinfo=RD)),0)
        self.assertEqual(reminders.process(datetime(2026,11,20,12,0,tzinfo=RD)),1)
        self.assertEqual(reminders.process(datetime(2026,11,20,12,0,tzinfo=RD)),0)
        c = base.db()
        rows = c.execute("SELECT template_code,message FROM whatsapp_outbox ORDER BY id").fetchall()
        self.assertEqual([r['template_code'] for r in rows],['SUSPENDED_D2','SUSPENDED_D4'])
        self.assertTrue(all(r['message'].count('siempre conectado contigo.')==1 for r in rows))
        c.close()

    def test_only_suspended_unpaid_and_verified(self):
        for sql in [
            "UPDATE customers SET status='ACTIVO',service_status='ACTIVO'",
            "UPDATE invoices SET status='PAGADA'",
            "UPDATE router_commands SET status='ERROR'",
            "INSERT INTO payment_promises(customer_id,promise_date,status) VALUES(1,'2026-11-30','PENDIENTE')",
        ]:
            with self.subTest(sql=sql):
                self.setUp()
                self.execute(sql)
                self.assertEqual(reminders.process(datetime(2026,11,19,10,0,tzinfo=RD)),0)

    def test_backfill_stagger_and_cancellation(self):
        self.assertEqual(reminders.process(datetime(2026,11,30,11,0,tzinfo=RD)),1)
        c = base.db()
        oid = c.execute("SELECT id FROM whatsapp_outbox").fetchone()['id']
        self.assertTrue(reminders.valid(c,oid,datetime(2026,11,30,11,0,tzinfo=RD)))
        c.execute("UPDATE whatsapp_outbox SET status='ACEPTADO',sent_at='2026-11-30T11:00:00-04:00'")
        c.commit(); c.close()
        self.assertEqual(reminders.process(datetime(2026,12,1,11,0,tzinfo=RD)),0)
        self.assertEqual(reminders.process(datetime(2026,12,2,11,0,tzinfo=RD)),1)
        self.execute("UPDATE invoices SET status='PAGADA'")
        c = base.db()
        second = c.execute("SELECT id FROM whatsapp_outbox WHERE template_code='SUSPENDED_D4'").fetchone()['id']
        self.assertFalse(reminders.valid(c,second,datetime(2026,12,2,11,0,tzinfo=RD)))
        c.close()

    def test_queued_first_still_valid_and_hours(self):
        self.assertEqual(reminders.process(datetime(2026,11,18,20,15,tzinfo=RD)),0)
        self.assertEqual(reminders.process(datetime(2026,11,19,10,0,tzinfo=RD)),1)
        c = base.db()
        oid = c.execute('SELECT id FROM whatsapp_outbox').fetchone()['id']
        self.assertTrue(reminders.valid(c,oid,datetime(2026,11,19,10,0,tzinfo=RD)))
        self.assertIsNone(reminders.valid(c,oid,datetime(2026,11,19,21,0,tzinfo=RD)))
        c.close()


if __name__ == '__main__':
    unittest.main()
