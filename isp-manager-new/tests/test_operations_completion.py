import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import date, datetime
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(_tmp.name) / 'test.db')
os.environ['INTERFLASH_TESTING'] = '1'
import app as base
import business_suite as bs
import admin_suite
import payment_flow as pay
import zone_cut_scheduler as cuts
import operations_health as health
base.init_db()
bs.ensure_schema()
admin_suite.ensure_schema()
health.ensure_schema()

class OperationTests(unittest.TestCase):
    def setUp(self):
        c=base.db()
        for table in ('payments','invoices','customers','zones','router_commands','payment_promises','whatsapp_outbox','billing_runs','backup_runs','maintenance_runs','notice_events'):
            c.execute('DELETE FROM '+table)
        c.execute("INSERT INTO customers(id,name,phone,pppoe,status,router_name,zone_id,plan_id) VALUES(1,'Prueba','8090000000','test','SUSPENDIDO','CCR2116',1,1)")
        c.execute("INSERT INTO zones(id,name,billing_day,invoice_days_before,cut_days_after,cut_time,active) VALUES(1,'Prueba',30,5,6,'14:00',1)")
        c.execute("INSERT INTO invoices(id,customer_id,concept,amount,issue_date,due_date,status,period) VALUES(1,1,'Internet',1000,'2026-09-25','2026-09-30','PENDIENTE','2026-09')")
        for key,value in [('auto_suspend','0'),('auto_reactivate','1'),('billing_enabled','1'),('whatsapp_enabled','1')]:
            c.execute('UPDATE app_settings SET value=? WHERE key=?',(value,key))
        c.commit();c.close()
    def query(self,sql):
        c=base.db();r=c.execute(sql).fetchall();c.close();return r
    def execute(self,sql):
        c=base.db();c.executescript(sql);c.commit();c.close()
    def test_partial_then_quick_payment_charges_only_remaining(self):
        pay.record_payment(1,1,'250')
        self.assertFalse(self.query('SELECT * FROM router_commands'))
        pay.record_payment(invoice_id=1)
        self.assertEqual([r['amount'] for r in self.query('SELECT amount FROM payments')],[250,750])
        self.assertEqual(self.query('SELECT action FROM router_commands')[0][0],'REACTIVATE')
        with self.assertRaises(ValueError): pay.record_payment(invoice_id=1)
        self.assertEqual(len(self.query('SELECT * FROM payments')),2)
        self.assertEqual(len(self.query('SELECT * FROM whatsapp_outbox')),2)
    def test_other_overdue_invoice_blocks_reactivation(self):
        self.execute("INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date,status) VALUES(1,'Otro',500,'2026-08-25','2026-08-30','PENDIENTE')")
        pay.record_payment(invoice_id=1)
        self.assertFalse(self.query('SELECT * FROM router_commands'))
    def test_invalid_and_wrong_customer_payments_are_atomic(self):
        for amount in ('NaN','Infinity','-5','0','1.001','1001'):
            with self.assertRaises(ValueError): pay.record_payment(1,1,amount)
        with self.assertRaises(ValueError): pay.record_payment(2,1,'100')
        self.assertFalse(self.query('SELECT * FROM payments'))
    def test_payment_cancels_pending_automatic_cut(self):
        self.execute("UPDATE customers SET status='ACTIVO'; INSERT INTO router_commands(customer_id,action,status,requested_by) VALUES(1,'SUSPEND','PENDIENTE','ZONA:Prueba')")
        pay.record_payment(invoice_id=1)
        self.assertEqual(self.query('SELECT status FROM router_commands')[0][0],'CANCELADO')
    def test_preview_cut_time_and_promise(self):
        self.execute("UPDATE customers SET status='ACTIVO'")
        self.assertEqual(cuts.process_zone_cuts(datetime(2026,10,6,13,59),dry_run=True),[])
        self.assertEqual(len(cuts.process_zone_cuts(datetime(2026,10,6,14),dry_run=True)),1)
        self.assertFalse(self.query('SELECT * FROM router_commands'))
        self.execute("INSERT INTO payment_promises(customer_id,promise_date,status) VALUES(1,'2026-10-07','PENDIENTE')")
        self.assertEqual(cuts.process_zone_cuts(datetime(2026,10,7,15),dry_run=True),[])
    def test_cut_queues_once(self):
        self.execute("UPDATE customers SET status='ACTIVO'; UPDATE app_settings SET value='1' WHERE key='auto_suspend'")
        self.assertEqual(cuts.process_zone_cuts(datetime(2026,10,6,14)),1)
        self.assertEqual(cuts.process_zone_cuts(datetime(2026,10,6,14)),0)
    def test_billing_crosses_month_and_does_not_duplicate(self):
        self.execute("UPDATE zones SET billing_day=2; DELETE FROM invoices")
        class Clock(date):
            @classmethod
            def today(cls): return cls(2026,10,28)
        with patch.object(cuts,'date',Clock):
            self.assertEqual(cuts.run_billing()[0],2)
            self.assertEqual(cuts.run_billing()[0],0)
        self.assertEqual([r[0] for r in self.query('SELECT due_date FROM invoices ORDER BY due_date')],['2026-10-02','2026-11-02'])
    def test_backup_without_request_is_readable(self):
        name=admin_suite._make_db_backup('test')
        c=sqlite3.connect(Path(admin_suite._backup_dir())/name)
        self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],1)
        c.close()
    def test_worker_runs_daily_tasks_once(self):
        with patch.object(bs,'run_billing',cuts.run_billing):
            health.maintenance_tick()
            health.maintenance_tick()
        self.assertEqual(len(self.query('SELECT * FROM billing_runs')),1)
        self.assertEqual(len(self.query('SELECT * FROM backup_runs')),1)
    def test_due_notice_once_and_only_remaining_balance(self):
        self.execute("UPDATE invoices SET due_date='"+date.today().isoformat()+"'")
        pay.record_payment(1,1,'250')
        self.assertEqual(health.prepare_due_notices(),1)
        self.assertEqual(health.prepare_due_notices(),0)
        notices=self.query("SELECT message FROM whatsapp_outbox WHERE template_code='DUE'")
        self.assertIn('750.00',notices[0][0])
        pay.record_payment(invoice_id=1)
        self.assertEqual(health.prepare_due_notices(),0)
    def test_disabled_suspend_survives_setup(self):
        cuts.setup(base.app)
        self.assertEqual(bs.setting('auto_suspend'),'0')

if __name__ == '__main__': unittest.main()
