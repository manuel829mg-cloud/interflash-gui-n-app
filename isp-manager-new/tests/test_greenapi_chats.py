from test_greenapi import GreenTests, base, g
from unittest.mock import patch

class ChatTests(GreenTests):
 def test_sync_history_and_access(self):
  self.login();c=base.db();c.execute("UPDATE greenapi_config SET active=1,channel='710722758220'");c.commit();c.close()
  self.assertEqual(self.client.post('/whatsapp/greenapi/sync').status_code,403)
  with self.client.session_transaction() as s:s['green_sync_csrf']='sync'
  with patch.object(g,'api',return_value=[{'id':'18095550123@c.us','name':'Cliente <A>'},{'id':'123@g.us'}]):
   for _ in range(2):self.client.post('/whatsapp/greenapi/sync',data={'csrf':'sync'})
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_threads').fetchone()[0],1);t=c.execute('SELECT id FROM whatsapp_threads').fetchone()[0];c.close()
  item={'chatId':'18095550123@c.us','idMessage':'history','type':'incoming','timestamp':1706522263,'textMessage':'Anterior'}
  with patch.object(g,'api',return_value=[item]):
   for _ in range(2):self.client.post('/whatsapp/greenapi/chat/'+str(t),data={'csrf':'sync','action':'history'})
  c=base.db();self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_messages').fetchone()[0],1);self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_queue').fetchone()[0],0);c.close()
  page=self.client.get('/whatsapp').get_data(as_text=True);self.assertIn('>Chats</button>',page);self.assertIn('Anterior',page)
  with patch.object(g,'api',return_value={'urlAvatar':'https://evil.example/a.jpg'}):self.client.post('/whatsapp/greenapi/chat/'+str(t),data={'csrf':'sync','action':'avatar'})
  self.assertNotIn('evil.example',self.client.get('/whatsapp').get_data(as_text=True))
