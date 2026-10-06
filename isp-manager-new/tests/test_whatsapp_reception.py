"""Isolated webhook regression tests; no calls to Meta or production DB."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(_tmp.name) / 'wa.db')
os.environ['SECRET_KEY'] = 'test-only'
import app as base
import whatsapp_suite as wa
wa.setup(base.app)
base.app.config['TESTING'] = True
class ReceptionTests(unittest.TestCase):
    def setUp(self):
        self.client=base.app.test_client()
        c=base.db()
        for table in ('whatsapp_messages','whatsapp_queue','whatsapp_threads'): c.execute('DELETE FROM '+table)
        c.execute('UPDATE whatsapp_webhook_health SET last_event=NULL,last_incoming=NULL')
        c.commit(); c.close()
    def event(self,value):
        return self.client.post('/webhooks/whatsapp',json={'object':'whatsapp_business_account','entry':[{'changes':[{'field':'messages','value':value}]}]})
    def test_receive_once_and_render(self):
        with self.client.session_transaction() as s: s['auth']=True
        old=self.client.get('/whatsapp/revision').json
        value={'messages':[{'from':'18095550123','id':'test-1','type':'text','text':{'body':'Respuesta de prueba'}}]}
        self.assertEqual(self.event(value).status_code,200)
        self.assertEqual(self.event(value).status_code,200)
        c=base.db()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],1)
        self.assertEqual(c.execute('SELECT unread FROM whatsapp_threads').fetchone()[0],1)
        self.assertTrue(c.execute('SELECT last_incoming FROM whatsapp_webhook_health').fetchone()[0]); c.close()
        self.assertNotEqual(old,self.client.get('/whatsapp/revision').json)
        page=self.client.get('/whatsapp').get_data(as_text=True)
        self.assertIn('Respuesta de prueba',page)
        self.assertIn('setInterval(refresh, 5000)',page)
        self.assertIn('https://localhost/webhooks/whatsapp',page)
        self.assertNotIn('lista para enviar y recibir',page)
    def test_status(self):
        c=base.db();t=wa._thread_for_phone(c,'18095550123');wa._record_outgoing(c,t['id'],'test','out-1','ACEPTADO');c.commit();c.close()
        self.event({'statuses':[{'id':'out-1','status':'read'}]})
        self.event({'statuses':[{'id':'out-1','status':'sent'}]})
        c=base.db();self.assertEqual(c.execute('SELECT status FROM whatsapp_messages').fetchone()[0],'LEÍDO');c.close()
        self.event({'statuses':[{'id':'out-1','status':'failed','errors':[{'code':131030,'title':'Recipient not allowed'}]}]})
        c=base.db();r=c.execute('SELECT status,error FROM whatsapp_messages').fetchone();c.close()
        self.assertEqual(r['status'],'ERROR');self.assertIn('131030',r['error'])
    def test_auth_input_and_verification(self):
        self.assertEqual(self.client.get('/whatsapp/revision').status_code,401)
        self.assertEqual(self.client.post('/webhooks/whatsapp',json=[]).status_code,400)
        with patch.object(wa,'VERIFY_TOKEN','test-verify'):
            self.assertEqual(self.client.get('/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=bad').status_code,403)
            self.assertEqual(self.client.get('/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=test-verify&hub.challenge=abc').data,b'abc')
    def test_database_failure(self):
        with patch.object(wa,'_customer_by_phone',side_effect=RuntimeError('test')):
            r=self.event({'messages':[{'from':'18095550123','id':'broken','type':'text','text':{'body':'test'}}]})
        self.assertEqual(r.status_code,500)
        c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],0);c.close()
