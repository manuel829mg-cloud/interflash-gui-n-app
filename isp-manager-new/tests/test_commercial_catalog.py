import os
import tempfile
import unittest
from pathlib import Path
_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(_tmp.name) / 'catalog.db')
os.environ['SECRET_KEY'] = 'catalog-isolated-key'
import app as base
import commercial_catalog
import pbr_client

class CatalogTests(unittest.TestCase):
    def test_preserve_retire_and_repeat(self):
        c = base.db()
        c.execute('DELETE FROM customers')
        c.execute('DELETE FROM plans')
        c.execute("INSERT INTO plans(id,name,download_mbps,upload_mbps,price) VALUES(101,'Viejo',25,10,950)")
        c.execute("INSERT INTO customers(id,name,plan_id) VALUES(1,'Ana',101)")
        c.commit(); c.close()
        commercial_catalog.setup(base.app)
        commercial_catalog.setup(base.app)
        c = base.db()
        old=c.execute('SELECT * FROM plans WHERE id=101').fetchone()
        self.assertEqual((old['active'],old['price'],old['download_mbps'],old['upload_mbps']),(0,950,25,10))
        customer=c.execute('SELECT * FROM customers WHERE id=1').fetchone()
        self.assertEqual(customer['plan_id'],101)
        active=c.execute('SELECT download_mbps,upload_mbps,price FROM plans WHERE active=1 ORDER BY price').fetchall()
        self.assertEqual([tuple(x) for x in active],[(20,20,800),(40,40,1000),(60,60,1300),(100,100,1500),(200,200,2000),(300,300,3000)])
        c.close()
        with base.app.test_request_context():
            self.assertIn(101,[x['id'] for x in pbr_client._choices(customer)[0]])
            self.assertNotIn(101,[x['id'] for x in pbr_client._choices()[0]])
if __name__=='__main__': unittest.main()
