import os,tempfile,unittest,base64
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=str(Path(_tmp.name)/'waha.db')
os.environ['SECRET_KEY']='test-secret-key-with-at-least-32-characters'
import app as base
import whatsapp_suite as wa
import waha_suite as w
wa.setup(base.app);base.app.config['TESTING']=True
class WahaTests(unittest.TestCase):
 def setUp(self):
  self.client=base.app.test_client()
  c=base.db();c.execute("UPDATE waha_config SET active=0,token='',hook='hook'");c.execute('UPDATE greenapi_config SET active=1');c.commit();c.close()
  with self.client.session_transaction() as s:s.update(auth=True,role='ADMIN',waha_csrf='csrf')
 def test_verified_switch_encrypts_and_preserves_config(self):
  calls=[];remote={'debug':False,'webhooks':[{'url':'https://existing.example','events':['message']}]}
  def api(path,values=None,cfg=None,method=None):
   if values is not None:remote.update(values['config']);calls.append(values);return {}
   return {'status':'WORKING','config':remote}
  with patch.object(w,'validate'),patch.object(w,'api',side_effect=api):
   self.client.post('/whatsapp/waha',data={'csrf':'csrf','api_url':'https://waha.example','session_name':'default','token':'test-api-key-12345678'})
  self.assertTrue(w.enabled());self.assertFalse(wa.greenapi.enabled());self.assertEqual(len(remote['webhooks']),2)
  c=base.db();self.assertNotIn('test-api-key',c.execute('SELECT token FROM waha_config').fetchone()[0]);c.close()
  self.assertNotIn(b'test-api-key',self.client.get('/whatsapp/waha').data)
  with base.app.app_context(),patch.object(w,'api',return_value={'id':'mid'}) as api:
   self.assertEqual(wa._send_text('8095550123','Hola'),(True,'waha:default:mid',''))
   self.assertEqual(api.call_args.args[1]['chatId'],'18095550123@c.us')

 def test_business_notice_sends_image_data_without_link_preview(self):
  with patch.object(w,'enabled',return_value=True), patch.object(w,'config',return_value={'session_name':'default'}), patch.object(wa,'_render_notice_image',return_value=b'png-bytes'), patch.object(w,'api',return_value={'id':'media-mid'}) as api:
   self.assertEqual(wa._send_business_notice('8095550123','Hola Prueba'),(True,'waha:default:media-mid',''))
  path,payload,cfg=api.call_args.args
  self.assertEqual(path,'/api/sendImage')
  self.assertEqual(payload['chatId'],'18095550123@c.us')
  self.assertEqual(payload['file']['data'],base64.b64encode(b'png-bytes').decode('ascii'))
  self.assertEqual(payload['caption'],'Hola Prueba')
  self.assertNotIn('url',payload['file'])
  self.assertNotIn('linkPreview',payload)
 def test_notice_image_is_three_by_four_png(self):
  png=wa._render_notice_image('Hola, Prueba. Tu aviso de INTER Flash está listo.')
  from PIL import Image
  image=Image.open(BytesIO(png))
  self.assertEqual(image.size,(900,1200))
  self.assertEqual(image.format,'PNG')

 def test_failed_verification_keeps_old_provider(self):
  with patch.object(w,'validate'),patch.object(w,'api',return_value={'status':'FAILED'}):
   self.client.post('/whatsapp/waha',data={'csrf':'csrf','api_url':'https://waha.example','session_name':'default','token':'test-api-key-12345678'})
  self.assertFalse(w.enabled());self.assertTrue(wa.greenapi.enabled())
  self.assertEqual(self.client.post('/whatsapp/waha',data={}).status_code,403)
 def test_callback_auth_dedup_and_monotonic_ack(self):
  c=base.db();c.execute('UPDATE waha_config SET active=1');c.commit();c.close()
  event={'event':'message','session':'default','payload':{'id':'in','from':'18095550123@c.us','fromMe':False,'body':'Hola'}}
  self.assertEqual(self.client.post('/webhooks/waha',json=event).status_code,403)
  for _ in range(2):self.assertEqual(self.client.post('/webhooks/waha',json=event,headers={'Authorization':'Bearer hook'}).status_code,200)
  for ack in (3,1):
   self.client.post('/webhooks/waha',json={'event':'message.ack','session':'default','payload':{'id':'out','fromMe':True,'ack':ack}},headers={'Authorization':'Bearer hook'})
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],1);self.assertEqual(w.confirmed_status(c,'waha:default:out','ACEPTADO'),'LEÍDO');c.close()
 def test_localhost_rejected(self):
  with self.assertRaises(w.APIError):w.validate({'api_url':'http://localhost:3000','session_name':'default','token':'test-api-key-12345678'})
  with patch.object(w.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
   with self.assertRaises(w.APIError):w.validate({'api_url':'https://local.example','session_name':'default','token':'test-api-key-12345678'})