import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=str(Path(_tmp.name)/'qr.db')
os.environ['SECRET_KEY']='test-only'
import app as base
import whatsapp_suite as wa
import whatsapp_qr as qr
wa.setup(base.app)
base.app.config['TESTING']=True
class QRTests(unittest.TestCase):
    def setUp(self):
        self.client=base.app.test_client()
        c=base.db()
        for t in ('whatsapp_messages','whatsapp_queue','whatsapp_threads'): c.execute('DELETE FROM '+t)
        c.commit();c.close()
    def login(self,role='ADMIN'):
        with self.client.session_transaction() as s: s.update(auth=True,role=role,wa_qr_csrf='csrf')
    def event(self,sender='18095550123@c.us',key='hook'):
        with patch.object(qr,'HOOK_KEY','hook'):
            return self.client.post('/webhooks/whatsapp-qr',json={'session':'default','event':'message','payload':{'id':sender,'from':sender,'body':'Hola'}},headers={'X-Interflash-Webhook':key})
    def test_access(self):
        self.assertEqual(self.client.get('/whatsapp/qr').status_code,401)
        self.login('TECNICO');self.assertEqual(self.client.get('/whatsapp/qr').status_code,403)
        self.login();self.assertEqual(self.client.post('/whatsapp/qr/start',json={}).status_code,403)
        self.assertEqual(self.client.get('/whatsapp/qr/start').status_code,404)
        self.assertEqual(self.client.get('/whatsapp/qr').headers['Cache-Control'],'no-store')
    def test_receive_authenticated_once(self):
        self.assertEqual(self.event(key='wrong').status_code,403)
        self.assertEqual(self.event().status_code,200);self.assertEqual(self.event().status_code,200)
        c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],1)
        self.assertEqual(c.execute('SELECT unread FROM whatsapp_threads').fetchone()[0],1);c.close()
    def test_hidden_ids_not_phone(self):
        for sender in ('123456789@lid','123456789@g.us','status@broadcast'): self.event(sender)
        c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_threads').fetchone()[0],0);c.close()
    def test_qr_errors(self):
        self.login()
        with patch.object(qr,'api',side_effect=qr.BridgeError(401)):
            self.assertEqual(self.client.get('/whatsapp/qr/image').status_code,502)
        with patch.object(qr,'api',return_value={'data':'not-base64'}):
            self.assertEqual(self.client.get('/whatsapp/qr/image').status_code,502)
    def test_pairing(self):
        self.login()
        with patch.object(qr,'api',return_value={'code':'ABCD-EFGH'}) as api:
            self.assertEqual(self.client.post('/whatsapp/qr/code',json={'phone':'1'},headers={'X-CSRF-Token':'csrf'}).status_code,400);api.assert_not_called()
            self.assertEqual(self.client.post('/whatsapp/qr/code',json={'phone':'+18095550123'},headers={'X-CSRF-Token':'csrf'}).json['code'],'ABCD-EFGH')
    def test_providers(self):
        with patch.dict(os.environ,{'WHATSAPP_PROVIDER':'meta'}),patch.object(wa,'ACCESS_TOKEN','x'),patch.object(wa,'PHONE_NUMBER_ID','id'),patch.object(wa,'_meta_post',return_value=(True,{'messages':[{'id':'meta-id'}]},'')):
            self.assertEqual(wa._send_text('18095550123','hello'),(True,'meta-id',''))
        with patch.dict(os.environ,{'WHATSAPP_PROVIDER':'waha'}),patch.object(qr,'api',side_effect=[{'status':'WORKING'},{'id':'qr-id'}]):
            self.assertEqual(wa._send_text('18095550123','hello'),(True,'waha:qr-id',''))
        with patch.object(qr,'api',return_value={'status':'SCAN_QR_CODE'}) as api:
            self.assertFalse(qr.send_text('18095550123','hello')[0]);self.assertEqual(api.call_count,1)
    def test_db_retry(self):
        with patch.object(wa,'_customer_by_phone',side_effect=RuntimeError()): self.assertEqual(self.event().status_code,500)
        c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],0);c.close()
