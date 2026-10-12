import os,tempfile,unittest
from datetime import datetime,timedelta
from unittest.mock import patch
_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=_tmp.name+'/wan.db'
os.environ['INTERFLASH_TESTING']='1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
import wan_monitor,wan_alerts,whatsapp_events

class WanIntegration(unittest.TestCase):
    def setUp(self):
        self.client=wsgi.app.test_client()
        with self.client.session_transaction() as s:
            s['auth']=True;s['role']='ADMIN';s['wan_alert_csrf']='test'
        c=base.db()
        for t in ('wan_line_health','wan_alert_state','wan_alert_events','whatsapp_outbox','whatsapp_outbox_links','whatsapp_queue','whatsapp_threads'):
            c.execute('DELETE FROM '+t)
        c.execute("DELETE FROM app_settings WHERE key IN ('wan_alert_phone','wan_alert_whatsapp')")
        c.execute("UPDATE app_settings SET value='1' WHERE key='whatsapp_enabled'")
        c.execute("UPDATE app_settings SET value='0' WHERE key='whatsapp_event_floor'")
        c.commit();c.close()
    def test_auth_validation_and_pages(self):
        with patch('push_sync._auth',return_value=False):
            self.assertEqual(self.client.post('/api/mikrotik/wan-health').status_code,401)
        with patch('push_sync._auth',return_value=True):
            for raw in ('','WAN1-CLARO,5,3','OTHER,0,3','WAN1-CLARO,0,0'):
                self.assertEqual(self.client.post('/api/mikrotik/wan-health',data={'health':raw}).status_code,422)
            self.assertEqual(self.client.post('/api/mikrotik/wan-health',data={'health':'WAN1-CLARO,3,3'}).json['received'],1)
        for url in ('/wan-alerts','/wan-lines','/mikrotik/prueba-respaldo'):
            self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.post('/wan-alerts',data={'enabled':'1','phone':'18095550123'}).status_code,403)
    def test_admin_alert_uses_existing_outbox_once(self):
        self.assertEqual(self.client.post('/wan-alerts',data={'csrf':'test','enabled':'1','phone':'8095550123'}).status_code,302)
        now=datetime.now()
        for i in range(3):
            stamp=now+timedelta(seconds=i*10)
            with patch.object(wan_monitor,'datetime') as clock,patch.object(wan_alerts,'datetime') as alerts_clock,patch('push_sync._auth',return_value=True):
                clock.now.return_value=stamp
                alerts_clock.now.return_value=stamp
                alerts_clock.fromisoformat=datetime.fromisoformat
                self.assertEqual(self.client.post('/api/mikrotik/wan-health',data={'health':'WAN1-CLARO,0,3'}).status_code,200)
        with patch.object(whatsapp_events.wa,'_meta_ready',return_value=True),patch.object(whatsapp_events.wa,'_send_text',return_value=(True,'test-id','')) as send:
            self.assertEqual(whatsapp_events.send_outbox()[0],1)
            self.assertEqual(whatsapp_events.send_outbox()[0],0)
            send.assert_called_once()
        c=base.db()
        row=c.execute("SELECT * FROM whatsapp_outbox WHERE template_code='WAN_ALERT'").fetchone()
        self.assertEqual(row['status'],'ACEPTADO');self.assertIsNone(row['customer_id'])
        self.assertEqual(row['phone'],'18095550123');c.close()
if __name__=='__main__':unittest.main()
