import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=str(Path(_tmp.name)/'whapi.db')
os.environ['SECRET_KEY']='test-secret-key-with-at-least-32-characters'
import app as base
import whatsapp_suite as wa
import whapi_suite as w
wa.setup(base.app);base.app.config['TESTING']=True

class WhapiTests(unittest.TestCase):
 def setUp(self):
  self.client=base.app.test_client()
  c=base.db()
  for t in ('whatsapp_messages','whatsapp_queue','whatsapp_threads','whapi_acks'):c.execute('DELETE FROM '+t)
  c.execute("UPDATE whapi_config SET channel='TEST-123',token='',hook='hook',active=0")
  c.execute('UPDATE ultramsg_config SET active=0');c.commit();c.close()
 def login(self,role='ADMIN'):
  with self.client.session_transaction() as s:s.update(auth=True,role=role,whapi_csrf='csrf',ultra_csrf='csrf')
 def event(self,kind='messages',items=None,key='hook',channel='TEST-123'):
  return self.client.post('/webhooks/whapi',headers={'X-Interflash-Key':key},json={'channel_id':channel,'event':{'type':kind,'method':'post'},kind:items or []})
 def test_setup_preserves_callbacks_encrypts_and_switches(self):
  self.assertEqual(self.client.get('/whatsapp/whapi').status_code,401)
  self.login('TECNICO');self.assertEqual(self.client.get('/whatsapp/whapi').status_code,403)
  self.login();self.assertEqual(self.client.post('/whatsapp/whapi',data={}).status_code,403)
  old={'url':'https://other.example/hook','events':[]};saved={}
  def api(path,values=None,cfg=None,method=None):
   if path=='health':return {'status':{'text':'AUTH'},'channel_id':'TEST-123','user':{'id':'18095550123'}}
   if method=='PATCH':saved.update(values);return {'success':True}
   return saved or {'webhooks':[old]}
  with patch.object(w,'api',side_effect=api):
   self.client.post('/whatsapp/whapi',data={'csrf':'csrf','token':'secret-for-test'})
  self.assertTrue(w.enabled());self.assertIn(old,saved['webhooks'])
  c=base.db();r=c.execute('SELECT * FROM whapi_config').fetchone();c.close()
  self.assertNotIn('secret-for-test',r['token'])
  page=self.client.get('/whatsapp/whapi');self.assertNotIn(b'secret-for-test',page.data)
  self.assertEqual(page.headers['Cache-Control'],'no-store')
  self.assertEqual(self.client.get('/whatsapp').status_code,200)
  self.assertIn(b'Whapi.Cloud',self.client.get('/whatsapp/settings').data)
  self.client.post('/whatsapp/ultramsg',data={'csrf':'csrf','action':'meta'})
  self.assertFalse(w.enabled())
 def test_failed_validation_keeps_provider(self):
  self.login()
  c=base.db();c.execute('UPDATE ultramsg_config SET active=1');c.commit();c.close()
  with patch.object(w,'api',return_value={'status':{'text':'QR'}}):
   self.client.post('/whatsapp/whapi',data={'csrf':'csrf','token':'test'})
  self.assertFalse(w.enabled());self.assertTrue(wa.ultra.enabled())
  with patch.object(w,'api',side_effect=[{'status':{'text':'AUTH'},'channel_id':'TEST-123'},{'webhooks':[]},{},{'webhooks':[]}]):
   self.client.post('/whatsapp/whapi',data={'csrf':'csrf','token':'test'})
  self.assertFalse(w.enabled());self.assertTrue(wa.ultra.enabled())
 def test_callback_auth_dedup_filter_and_rollback(self):
  msg={'id':'m1','chat_id':'18095550123@s.whatsapp.net','from_me':False,'text':{'body':'Hola'}}
  self.assertEqual(self.event(items=[msg],key='bad').status_code,403)
  self.assertEqual(self.event(items=[msg],channel='OTHER').status_code,403)
  self.assertEqual(self.event(items=[msg]).status_code,200);self.event(items=[msg])
  self.event(items=[dict(msg,id='self',from_me=True),dict(msg,id='group',chat_id='123@g.us'),dict(msg,id='lid',chat_id='123456789@lid')])
  c=base.db();self.assertEqual(c.execute('SELECT count(*) FROM whatsapp_messages').fetchone()[0],1)
  self.assertEqual(c.execute('SELECT unread FROM whatsapp_threads').fetchone()[0],1);c.close()
  with patch.object(wa,'_customer_by_phone',side_effect=RuntimeError()):
   self.assertEqual(self.event(items=[dict(msg,id='retry')]).status_code,500)
  self.assertEqual(self.event(items=[dict(msg,id='retry')]).status_code,200)
 def test_status_before_record_monotonic_and_isolated(self):
  self.event('statuses',[{'id':'out','status':'read'}]);self.event('statuses',[{'id':'out','status':'sent'}])
  c=base.db();t=wa._thread_for_phone(c,'18095550123')
  wa._record_outgoing(c,t['id'],'Hello','whapi:TEST-123:out','ACEPTADO')
  wa._record_outgoing(c,t['id'],'Hello','meta:out','ACEPTADO');c.commit()
  self.assertEqual([r[0] for r in c.execute('SELECT status FROM whatsapp_messages ORDER BY id')],['LEÍDO','ACEPTADO']);c.close()
 def test_send_no_fallback_and_template_refusal(self):
  with patch.object(w,'config',return_value={'channel':'TEST-123','token':'secret'}),patch.object(w,'api',return_value={'sent':True,'message':{'id':'out'}}) as api:
   self.assertEqual(w.send_text('18095550123','Hello'),(True,'whapi:TEST-123:out',''))
   self.assertEqual(api.call_args.args[1],{'to':'18095550123','body':'Hello'})
  with patch.object(w,'enabled',return_value=True),patch.object(w,'api',side_effect=w.APIError('HTTP 401')),patch.object(wa,'_meta_post') as meta:
   self.assertFalse(wa._send_text('18095550123','Hello')[0]);self.assertFalse(wa._send_template('18095550123','test')[0]);meta.assert_not_called()
