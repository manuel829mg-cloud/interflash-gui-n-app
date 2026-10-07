import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=str(Path(_tmp.name)/'ultra.db')
os.environ['SECRET_KEY']='test-secret-key-with-at-least-32-characters'
import app as base
import whatsapp_suite as wa
import ultramsg_suite as u
wa.setup(base.app);base.app.config['TESTING']=True

class UltraTests(unittest.TestCase):
 def setUp(self):
  self.client=base.app.test_client()
  c=base.db()
  for t in ('whatsapp_messages','whatsapp_queue','whatsapp_threads','ultramsg_acks'): c.execute('DELETE FROM '+t)
  c.execute("UPDATE ultramsg_config SET instance='instance193640',token='',hook='test-hook',active=0");c.commit();c.close()
 def login(self,role='ADMIN'):
  with self.client.session_transaction() as s:s.update(auth=True,role=role,ultra_csrf='csrf')
 def post(self,**kw):
  return self.client.post('/whatsapp/ultramsg',data={'csrf':'csrf','instance':'193640','token':'secret-test-value',**kw})
 def event(self,data,key='test-hook',instance='193640',event='message_received',**extra):
  return self.client.post('/webhooks/ultramsg?key='+key,json={'instanceId':instance,'event_type':event,'data':data,**extra})
 def test_access_and_secret(self):
  self.assertEqual(self.client.get('/whatsapp/ultramsg').status_code,401)
  self.login('TECNICO');self.assertEqual(self.client.get('/whatsapp/ultramsg').status_code,403)
  self.login();self.assertEqual(self.client.post('/whatsapp/ultramsg',data={}).status_code,403)
  with patch.object(u,'api',side_effect=[{'status':{'accountStatus':{'status':'authenticated'}}},{'sendDelay':2},{'success':True},{'webhook_url':'https://localhost/webhooks/ultramsg?key=test-hook'}]):
   self.assertEqual(self.post().status_code,302)
  c=base.db();r=c.execute('SELECT * FROM ultramsg_config').fetchone();c.close()
  self.assertEqual(r['active'],1);self.assertNotIn('secret-test-value',r['token'])
  page=self.client.get('/whatsapp/ultramsg');self.assertNotIn(b'secret-test-value',page.data)
  self.assertEqual(page.headers['Cache-Control'],'no-store')
 def test_not_authenticated_no_activation(self):
  self.login()
  with patch.object(u,'api',return_value={'status':'qr'}) as api:self.post();self.assertEqual(api.call_count,1)
  self.assertFalse(u.enabled())
 def test_callback_auth_and_dedup(self):
  msg={'id':'incoming','from':'18095550123@c.us','fromMe':False,'body':'Hola'}
  self.assertEqual(self.event(msg,key='bad').status_code,403)
  self.assertEqual(self.event(msg,instance='999').status_code,403)
  self.assertEqual(self.event(msg).status_code,200);self.assertEqual(self.event(msg).status_code,200)
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],1)
  self.assertEqual(c.execute('SELECT unread FROM whatsapp_threads').fetchone()[0],1);c.close()
 def test_ack_before_record_and_no_regression(self):
  ref='iflash-'+'a'*32;pid='ultra:instance193640:'+ref
  self.event({'ack':'read'},event='message_ack',referenceId=ref)
  self.event({'ack':'server'},event='message_ack',referenceId=ref)
  c=base.db();t=wa._thread_for_phone(c,'18095550123');wa._record_outgoing(c,t['id'],'Hola',pid,'ACEPTADO');c.commit()
  self.assertEqual(c.execute('SELECT status FROM whatsapp_messages').fetchone()[0],'LEÍDO');c.close()
 def test_bad_phone_and_rollback(self):
  self.event({'id':'hidden','from':'123456789@lid','body':'Hola'})
  with patch.object(wa,'_customer_by_phone',side_effect=RuntimeError()):
   self.assertEqual(self.event({'id':'fail','from':'18095550123@c.us','body':'Hola'}).status_code,500)
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],0);c.close()
 def test_send_and_meta_isolation(self):
  with patch.object(u,'config',return_value={'instance':'instance193640','token':'secret'}),patch.object(u,'api',side_effect=[{'status':'authenticated'},{'sent':'true','id':123}]) as api:
   ok,pid,error=u.send_text('18095550123','Hola');self.assertTrue(ok);self.assertTrue(pid.startswith('ultra:instance193640:iflash-'));self.assertEqual(api.call_args.args[1]['to'],'+18095550123')
  with patch.object(u,'api',return_value={'status':'qr'}):self.assertFalse(u.send_text('18095550123','Hola')[0])
  with patch.object(wa,'ACCESS_TOKEN','secret'),patch.object(wa,'PHONE_NUMBER_ID','id'),patch.object(wa,'_meta_post',return_value=(True,{'messages':[{'id':'meta'}]},'')):
   self.assertEqual(wa._send_text('18095550123','Hola'),(True,'meta',''))
