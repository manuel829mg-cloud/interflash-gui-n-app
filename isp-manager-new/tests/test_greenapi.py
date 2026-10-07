import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=str(Path(_tmp.name)/'green.db')
os.environ['SECRET_KEY']='test-secret-key-with-at-least-32-characters'
import app as base
import whatsapp_suite as wa
import greenapi_suite as g
wa.setup(base.app);base.app.config['TESTING']=True

class GreenTests(unittest.TestCase):
 def setUp(self):
  self.client=base.app.test_client()
  c=base.db()
  for t in ('whatsapp_messages','whatsapp_queue','whatsapp_threads','greenapi_acks'):c.execute('DELETE FROM '+t)
  c.execute("UPDATE greenapi_config SET channel='710722758220',api_url='https://7107.api.greenapi.com',token='',hook='hook',active=0")
  c.execute('UPDATE ultramsg_config SET active=0');c.execute('UPDATE whapi_config SET active=0');c.commit();c.close()
 def login(self,role='ADMIN'):
  with self.client.session_transaction() as s:s.update(auth=True,role=role,greenapi_csrf='csrf',whapi_csrf='csrf')
 def post(self,**extra):
  return self.client.post('/whatsapp/greenapi',data={'csrf':'csrf','instance':'710722758220','api_url':'https://7107.api.greenapi.com','token':'test-token-123456789',**extra})
 def event(self,kind='incomingMessageReceived',key='hook',instance=710722758220,**extra):
  return self.client.post('/webhooks/greenapi',headers={'Authorization':'Bearer '+key},json={'typeWebhook':kind,'instanceData':{'idInstance':instance},'idMessage':'mid','senderData':{'chatId':'18095550123@c.us','senderName':'Test'},'messageData':{'typeMessage':'textMessage','textMessageData':{'textMessage':'Hola'}},**extra})
 def test_setup_encrypt_and_switch(self):
  self.assertEqual(self.client.get('/whatsapp/greenapi').status_code,401)
  self.login('TECNICO');self.assertEqual(self.client.get('/whatsapp/greenapi').status_code,403)
  self.login();self.assertEqual(self.client.post('/whatsapp/greenapi',data={}).status_code,403)
  saved={}
  def api(path,values=None,cfg=None):
   if path=='getStateInstance':return {'stateInstance':'authorized'}
   if path=='setSettings':saved.update(values);return {'saveSettings':True}
   return saved or {'webhookUrl':''}
  with patch.object(g,'api',side_effect=api):self.post()
  self.assertTrue(g.enabled());self.assertEqual(saved['webhookUrlToken'],'Bearer hook')
  c=base.db();row=c.execute('SELECT token FROM greenapi_config').fetchone();c.close();self.assertNotIn('test-token',row[0])
  self.assertNotIn(b'test-token',self.client.get('/whatsapp/greenapi').data)
  self.assertEqual(self.client.get('/whatsapp').status_code,200)
  self.assertIn(b'GREEN-API',self.client.get('/whatsapp/settings').data)
  self.client.post('/whatsapp/whapi',data={'csrf':'csrf','action':'meta'});self.assertFalse(g.enabled())
 def test_validation_and_existing_webhook(self):
  good={'channel':'710722758220','api_url':'https://7107.api.greenapi.com','token':'test-token-123456789'}
  for url in ('https://evil.example','http://7107.api.greenapi.com','https://7107.api.greenapi.com.evil.example','https://user@7107.api.greenapi.com'):
   with self.assertRaises(g.APIError):g.validate(dict(good,api_url=url))
  self.login()
  with patch.object(g,'api',side_effect=[{'stateInstance':'authorized'},{'webhookUrl':'https://other.example'}]) as api:
   self.post();self.assertEqual(api.call_count,2)
  self.assertFalse(g.enabled())
  with patch.object(g,'api',return_value={'stateInstance':'notAuthorized'}):self.post()
  self.assertFalse(g.enabled())
 def test_callback_dedup_and_rollback(self):
  self.assertEqual(self.event(key='wrong').status_code,403);self.assertEqual(self.event(instance=1).status_code,403)
  self.event();self.event();self.event(idMessage='group',senderData={'chatId':'123@g.us'})
  self.event(kind='outgoingMessageReceived',idMessage='own')
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],1);self.assertEqual(c.execute('SELECT unread FROM whatsapp_threads').fetchone()[0],1);c.close()
  with patch.object(wa,'_customer_by_phone',side_effect=RuntimeError()):self.assertEqual(self.event(idMessage='retry').status_code,500)
  self.assertEqual(self.event(idMessage='retry').status_code,200)
 def test_status_and_send(self):
  self.event(kind='outgoingMessageStatus',status='read',sendByApi=True)
  self.event(kind='outgoingMessageStatus',status='sent',sendByApi=True)
  c=base.db();t=wa._thread_for_phone(c,'18095550123');wa._record_outgoing(c,t['id'],'Hola','greenapi:710722758220:mid','ACEPTADO');c.commit()
  self.assertEqual(c.execute('SELECT status FROM whatsapp_messages').fetchone()[0],'LEÍDO');c.close()
  with patch.object(g,'api',return_value={'idMessage':'sent-id'}) as api:
   self.assertEqual(g.send_text('18095550123','Hola'),(True,'greenapi:710722758220:sent-id',''))
   self.assertEqual(api.call_args.args[1]['chatId'],'18095550123@c.us')
  with patch.object(g,'enabled',return_value=True),patch.object(g,'api',side_effect=g.APIError('HTTP 403')),patch.object(wa,'_meta_post') as meta:
   self.assertFalse(wa._send_text('18095550123','Hola')[0]);self.assertFalse(wa._send_template('18095550123','t')[0]);meta.assert_not_called()
