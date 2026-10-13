import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/zones.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
import zone_cut_scheduler as cuts


class ZoneSuspendCountTests(unittest.TestCase):
    def setUp(self):
        c = base.db()
        for table in ('payments', 'invoices', 'customers', 'zones', 'router_commands', 'payment_promises'):
            c.execute('DELETE FROM ' + table)
        c.execute("INSERT INTO zones(id,name,cut_days_after,cut_time,suspend_invoice_count) VALUES(1,'Prueba',6,'14:00',2)")
        c.execute("INSERT INTO customers(id,name,pppoe,status,zone_id) VALUES(1,'Prueba','prueba','ACTIVO',1)")
        for invoice, due in enumerate(('2026-09-30', '2026-10-30', '2026-11-30'), 1):
            c.execute("INSERT INTO invoices(id,customer_id,concept,amount,issue_date,due_date,status) VALUES(?,1,'Internet',1000,'2026-09-01',?,'PENDIENTE')", (invoice, due))
        c.commit()
        c.close()

    def execute(self, sql):
        c = base.db()
        c.executescript(sql)
        c.commit()
        c.close()

    def test_second_invoice_controls_cut_date_and_time(self):
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 10, 6, 15), dry_run=True), [])
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 11, 4, 15), dry_run=True), [])
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 11, 5, 13, 59), dry_run=True), [])
        self.assertEqual(len(cuts.process_zone_cuts(datetime(2026, 11, 5, 14), dry_run=True)), 1)

    def test_three_requires_three_overdue_invoices(self):
        self.execute('UPDATE zones SET suspend_invoice_count=3')
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 11, 6, 15), dry_run=True), [])
        self.assertEqual(len(cuts.process_zone_cuts(datetime(2026, 12, 6, 14), dry_run=True)), 1)

    def test_paid_invoice_does_not_count_but_partial_payment_does(self):
        self.execute("INSERT INTO payments(customer_id,invoice_id,amount,paid_at) VALUES(1,1,1000,'2026-10-01')")
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 11, 6, 15), dry_run=True), [])
        self.execute('UPDATE payments SET amount=500')
        self.assertEqual(len(cuts.process_zone_cuts(datetime(2026, 11, 6, 15), dry_run=True)), 1)

    def test_valid_promise_prevents_cut(self):
        self.execute("INSERT INTO payment_promises(customer_id,promise_date,status) VALUES(1,'2026-11-07','PENDIENTE')")
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 11, 6, 15), dry_run=True), [])

    def test_twelve_requires_all_twelve_unpaid_invoices(self):
        import calendar
        c = base.db()
        c.execute('DELETE FROM invoices')
        c.execute('UPDATE zones SET suspend_invoice_count=12')
        for month in range(1, 13):
            due = f'2026-{month:02d}-{calendar.monthrange(2026, month)[1]}'
            c.execute("INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date,status) VALUES(1,'Internet',1000,'2026-01-01',?,'PENDIENTE')", (due,))
        c.commit()
        c.close()
        self.assertEqual(cuts.process_zone_cuts(datetime(2026, 12, 30, 15), dry_run=True), [])
        self.assertEqual(len(cuts.process_zone_cuts(datetime(2027, 1, 6, 14), dry_run=True)), 1)
        self.execute("UPDATE invoices SET status='PAGADO' WHERE id=(SELECT MIN(id) FROM invoices)")
        self.assertEqual(cuts.process_zone_cuts(datetime(2027, 1, 6, 15), dry_run=True), [])

    def test_zone_form_saves_and_restores_threshold(self):
        client = base.app.test_client()
        with client.session_transaction() as session:
            session['auth'] = True
        data = dict(action='save', zone_id='1', name='Prueba', billing_day='30', invoice_days_before='5', cut_days_after='6', cut_time='14:00', suspend_invoice_count='12')
        client.post('/zones', data=data)
        html = client.get('/zones?edit=1').get_data(as_text=True)
        self.assertIn('<option value="12" selected>12 facturas vencidas</option>', html)
        data['suspend_invoice_count'] = '0'
        client.post('/zones', data=data)
        c = base.db()
        self.assertEqual(c.execute('SELECT suspend_invoice_count FROM zones WHERE id=1').fetchone()[0], 12)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM router_commands').fetchone()[0], 0)
        c.close()


if __name__ == '__main__':
    unittest.main()
