import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/telecable.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
import pbr_client
import zone_cut_scheduler
import invoice_pdf

class TelecableTests(unittest.TestCase):
    def setUp(self):
        c = base.db()
        for table in ('payments', 'invoices', 'customers', 'router_commands'):
            c.execute('DELETE FROM ' + table)
        c.execute('UPDATE plans SET price=800 WHERE id=1')
        for cid, enabled in ((1, 1), (2, 0)):
            c.execute("INSERT INTO customers(id,name,plan_id,status,due_day,telecable_enabled) VALUES(?, ?, 1, 'ACTIVO', 1, ?)", (cid, 'Prueba '+str(cid), enabled))
        c.commit(); c.close()
        self.client = wsgi.app.test_client()
        with self.client.session_transaction() as s:
            s['auth'] = True; s['role'] = 'ADMIN'; s['user'] = 'test'

    def test_manual_defaults_and_historical_snapshot(self):
        listing = self.client.get('/invoices?customer_id=1').get_data(as_text=True)
        self.assertIn('value="1300.00"', listing)
        for cid in (1, 2):
            response = self.client.post('/invoices', data={'customer_id': cid, 'issue_date': '2026-10-16', 'due_date': '2026-10-30'})
            self.assertEqual(response.status_code, 302)
        c = base.db()
        rows = c.execute('SELECT * FROM invoices ORDER BY id').fetchall()
        self.assertEqual([(r['amount'], r['telecable_amount']) for r in rows], [(1300, 500), (800, 0)])
        c.execute('UPDATE customers SET telecable_enabled=0 WHERE id=1'); c.commit()
        detail = self.client.get('/invoices/'+str(rows[0]['id'])).get_data(as_text=True)
        self.assertIn('Telecable adicional', detail)
        self.assertIn('800.00', detail); self.assertIn('500.00', detail); self.assertIn('1,300.00', detail)
        inv, company, banks = invoice_pdf.invoice_data(c, rows[0]['id'])
        self.assertTrue(invoice_pdf.render_pdf(inv, company, banks).startswith(b'%PDF'))
        c.close()

    def test_recurring_is_optional_and_deduplicated(self):
        with patch.object(zone_cut_scheduler.bs, 'setting', return_value='1'):
            zone_cut_scheduler.run_billing()
            zone_cut_scheduler.run_billing()
        c = base.db()
        rows = c.execute('SELECT customer_id,amount,telecable_amount FROM invoices WHERE period=? ORDER BY customer_id', (date.today().strftime('%Y-%m'),)).fetchall()
        self.assertEqual([tuple(r) for r in rows], [(1,1300,500),(2,800,0)])
        c.close()

    def test_form_and_save_toggle(self):
        c = base.db(); row = c.execute('SELECT * FROM customers WHERE id=1').fetchone(); c.close()
        with wsgi.app.test_request_context('/customers/1/edit'):
            html = pbr_client.customer_form(row)
        self.assertIn('Telecable adicional — RD$500', html)
        self.assertIn('style="width:auto" checked', html)
        data = {'name':'Prueba 1','plan_id':'1','telecable_present':'1','due_day':'1'}
        with wsgi.app.test_request_context('/customers/1/edit', method='POST', data=data):
            from flask import session
            session['auth'] = True
            pbr_client.customer_edit_pbr(1)
        c = base.db(); self.assertEqual(c.execute('SELECT telecable_enabled FROM customers WHERE id=1').fetchone()[0], 0); c.close()

if __name__ == '__main__':
    unittest.main()
