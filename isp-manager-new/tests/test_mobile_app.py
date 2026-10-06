"""Run: python -m unittest discover -s tests -p test_mobile_app.py"""
import os
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(_tmp.name) / 'test.db')
os.environ['SECRET_KEY'] = 'isolated-test-key'
import app as base
import business_suite
import mobile_app
business_suite.setup(base.app)
mobile_app.setup(base.app)
base.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)

class MobileTests(unittest.TestCase):
    def setUp(self):
        self.client = base.app.test_client()
        c = base.db()
        for table in ('mobile_requests', 'support_tickets', 'portal_tokens', 'invoices', 'payments', 'customers'):
            c.execute('DELETE FROM ' + table)
        c.execute("INSERT INTO customers(id,code,name) VALUES(1,'A','Ana'),(2,'B','Bruno')")
        c.execute("INSERT INTO portal_tokens(customer_id,token,enabled) VALUES(1,'alpha',1),(2,'beta',1)")
        c.execute("INSERT INTO invoices(customer_id,concept,amount,issue_date,due_date) VALUES(1,'Factura Ana',800,'2026-10-01','2026-10-30'),(2,'Factura Bruno',900,'2026-10-01','2026-10-30')")
        c.commit(); c.close()

    def enter(self):
        self.client.get('/portal/alpha')
        with self.client.session_transaction() as s:
            return s['mobile_csrf']

    def test_install_and_no_cache(self):
        r = self.client.get('/app')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'/manifest.webmanifest', r.data)
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/manifest.webmanifest').json['start_url'], '/app')
        for path in ('/sw.js', '/static/mobile/icon-192.png', '/static/mobile/icon-512.png'):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_customer_isolation_and_revocation(self):
        self.assertEqual(self.client.get('/portal/missing').status_code, 404)
        self.enter()
        r = self.client.get('/app/cliente')
        self.assertIn(b'Factura Ana', r.data)
        self.assertNotIn(b'Factura Bruno', r.data)
        self.assertEqual(self.client.get('/app/solicitudes').status_code, 302)
        c = base.db(); c.execute("UPDATE portal_tokens SET enabled=0 WHERE token='alpha'"); c.commit(); c.close()
        self.assertEqual(self.client.get('/app/cliente').status_code, 302)

    def test_csrf_and_amount_validation(self):
        token = self.enter()
        self.assertEqual(self.client.post('/app/cliente', data={'kind':'SOPORTE','detail':'No tengo internet'}).status_code, 400)
        for amount in ('NaN','Infinity','-10','0','1.001','1000001'):
            r = self.client.post('/app/cliente', data={'csrf':token,'kind':'PAGO','detail':'Banco referencia 12345','amount':amount})
            self.assertIn('monto válido'.encode(), r.data)
        c = base.db(); self.assertEqual(c.execute('SELECT COUNT(*) FROM mobile_requests').fetchone()[0], 0); c.close()

    def test_payment_is_report_only_and_customer_id_not_trusted(self):
        token = self.enter()
        r = self.client.post('/app/cliente', data={'csrf':token,'kind':'PAGO','detail':'Transferencia 12345','amount':'800','customer_id':'2'})
        self.assertEqual(r.status_code, 302)
        c = base.db()
        row = c.execute('SELECT * FROM mobile_requests').fetchone()
        self.assertEqual(row['customer_id'], 1)
        self.assertEqual(row['status'], 'PENDIENTE')
        self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0], 0)
        self.assertEqual(c.execute('SELECT status FROM invoices WHERE customer_id=1').fetchone()[0], 'PENDIENTE')
        c.close()

    def test_support_escapes_html_and_creates_ticket(self):
        token = self.enter()
        self.client.post('/app/cliente', data={'csrf':token,'kind':'SOPORTE','detail':'<script>alert(1)</script>'})
        r = self.client.get('/app/cliente')
        self.assertIn(b'&lt;script&gt;', r.data)
        self.assertNotIn(b'<script>alert(1)</script>', r.data)
        c = base.db(); self.assertEqual(c.execute('SELECT COUNT(*) FROM support_tickets').fetchone()[0], 1); c.close()

    def test_admin_role_and_logout(self):
        self.enter()
        with self.client.session_transaction() as s:
            s['auth'] = True; s['role'] = 'TECNICO'
        self.assertEqual(self.client.get('/app/solicitudes').status_code, 403)
        with self.client.session_transaction() as s:
            s['role'] = 'ADMIN'; token = s['mobile_csrf']
        self.assertEqual(self.client.get('/app/solicitudes').status_code, 200)
        self.client.post('/app/salir', data={'csrf':token})
        self.assertEqual(self.client.get('/app/cliente').status_code, 302)

if __name__ == '__main__': unittest.main()
