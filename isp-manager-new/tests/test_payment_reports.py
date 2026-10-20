import os
import tempfile
import unittest
from unittest.mock import patch

_tmp=tempfile.TemporaryDirectory()
os.environ['DB_PATH']=_tmp.name+'/reports.db'
os.environ['APP_URL']='https://interflash.example'
os.environ['INTERFLASH_TESTING']='1'
with patch('threading.Thread.start'):
    import wsgi
import app as base
import payment_reports as reports

class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.client=base.app.test_client()
        c=base.db()
        for table in ('whatsapp_payment_reports','whatsapp_messages','whatsapp_threads','whatsapp_outbox','customers'):
            c.execute('DELETE FROM '+table)
        c.execute("INSERT INTO customers(id,name,phone,status) VALUES(1,'Cliente','8095550123','ACTIVO')")
        c.execute("UPDATE waha_config SET active=1,hook='hook',session_name='default'")
        for key,value in [('wan_alert_phone','8094121799'),('whatsapp_enabled','1')]:
            c.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
        c.execute("DELETE FROM app_settings WHERE key='payment_report_phone'")
        c.commit();c.close()
    def post(self,mid='one',extra=None):
        payload={'id':mid,'from':'18095550123@c.us','fromMe':False,'hasMedia':True,'media':{'mimetype':'image/jpeg'},'body':'recibo'}
        if extra: payload.update(extra)
        return self.client.post('/webhooks/waha',json={'event':'message','session':'default','payload':payload},headers={'Authorization':'Bearer hook'})
    def rows(self,sql):
        c=base.db()
        try:return c.execute(sql).fetchall()
        finally:c.close()
    def test_image_dedup_notice_and_no_payment(self):
        before=len(self.rows('SELECT * FROM payments'))
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(len(self.rows('SELECT * FROM whatsapp_payment_reports')),1)
        notice=self.rows("SELECT * FROM whatsapp_outbox WHERE template_code='PAYMENT_REPORT'")[0]
        self.assertEqual(notice['phone'],'18094121799')
        self.assertIsNone(notice['customer_id'])
        self.assertIn('https://interflash.example/pagos/reportados/',notice['message'])
        self.assertEqual(len(self.rows('SELECT * FROM payments')),before)
        self.assertEqual(self.rows('SELECT message_type FROM whatsapp_messages')[0][0],'image')
    def test_pdf_detected_text_and_audio_ignored(self):
        self.post('pdf',{'media':{'mimetype':'application/pdf'}})
        self.post('text',{'hasMedia':False,'media':{},'body':'hola'})
        self.post('audio',{'media':{'mimetype':'audio/ogg'}})
        self.assertEqual(len(self.rows('SELECT * FROM whatsapp_payment_reports')),1)
    def test_duplicate_phone_not_assigned_and_secondary_supported(self):
        c=base.db();c.execute("INSERT INTO customers(id,name,phone,status) VALUES(2,'Otro','8095550123','ACTIVO')");c.commit();c.close()
        self.post()
        self.assertIsNone(self.rows('SELECT customer_id FROM whatsapp_payment_reports')[0][0])
    def test_access_review_csrf_and_no_payment_on_get(self):
        self.post()
        rid=self.rows('SELECT id FROM whatsapp_payment_reports')[0][0]
        path='/pagos/reportados/'+str(rid)
        self.assertEqual(self.client.get(path).status_code,302)
        with self.client.session_transaction() as s:s.update(auth=True,role='SOPORTE')
        self.assertEqual(self.client.get(path).status_code,403)
        with self.client.session_transaction() as s:s.update(auth=True,role='ADMIN',payment_report_csrf='csrf')
        self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.rows('SELECT status FROM whatsapp_payment_reports')[0][0],'PENDIENTE')
        self.assertEqual(self.client.post(path,data={}).status_code,403)
        self.assertEqual(self.client.post(path,data={'csrf':'csrf'}).status_code,302)
        self.assertEqual(self.rows('SELECT status FROM whatsapp_payment_reports')[0][0],'REVISADO')
    def test_no_destination_still_records_without_sending(self):
        c=base.db();c.execute("DELETE FROM app_settings WHERE key='wan_alert_phone'");c.commit();c.close()
        self.post()
        self.assertEqual(len(self.rows('SELECT * FROM whatsapp_payment_reports')),1)
        self.assertEqual(len(self.rows('SELECT * FROM whatsapp_outbox')),0)
    def test_secondary_phone_match(self):
        c=base.db();c.execute("UPDATE customers SET phone='8095550000',phone_secondary='8095550123' WHERE id=1");c.commit();c.close()
        self.post()
        self.assertEqual(self.rows('SELECT customer_id FROM whatsapp_payment_reports')[0][0],1)

if __name__=='__main__':unittest.main()
