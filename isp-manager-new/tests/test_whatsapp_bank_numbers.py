import os
import tempfile
import unittest
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = _tmp.name + '/bank-numbers.db'
os.environ['INTERFLASH_TESTING'] = '1'
with patch('threading.Thread.start'):
    import wsgi

import app as base
import whatsapp_suite as wa
import whatsapp_bank_numbers as bot
import whatsapp_menu


class BankNumberReplyTests(unittest.TestCase):
    def setUp(self):
        c = base.db()
        for table in (
            'whatsapp_bank_number_jobs', 'whatsapp_menu_jobs',
            'whatsapp_menu_state','whatsapp_messages',
            'whatsapp_threads','whatsapp_queue','bank_accounts'
        ):
            c.execute('DELETE FROM ' + table)
        c.execute("UPDATE whatsapp_bank_number_config SET enabled=1,floor=0 WHERE id=1")
        c.execute("UPDATE whatsapp_menu_config SET enabled=0")
        c.execute("""INSERT INTO bank_accounts(bank,account_type,account_number,active)
            VALUES('BHD','Ahorros','1234567890',1),
                  ('Popular','Ahorros','9876543210',1),
                  ('Antigua','Ahorros','0000000000',0)""")
        c.commit()
        c.close()

    def inbound(self, message, provider='test-in'):
        c=base.db()
        thread=c.execute("""INSERT INTO whatsapp_threads(phone,created_at)
            VALUES(?,?)""",('18094121799',wa._now())).lastrowid
        mid=c.execute("""INSERT INTO whatsapp_messages(thread_id,direction,message_type,
            body,provider_id,status,created_at) VALUES(?,'IN','text',?,?,'RECIBIDO',?)""",
            (thread,message,provider,wa._now())).lastrowid
        c.commit();c.close()
        return mid

    def test_bank_flyer_in_one_reply_without_welcome_menu(self):
        mid=self.inbound('Por favor, mándame el número de cuenta')
        with patch.object(wa,'_meta_ready',return_value=True), \
             patch.object(bot,'send_bank_image',return_value=(True,'greenapi:test123','')) as send:
            self.assertEqual(bot.process_one(),'ACEPTADO')
            self.assertIsNone(bot.process_one())
            send.assert_called_once_with('18094121799')
        c=base.db()
        rows=c.execute('SELECT body,kind,status FROM whatsapp_queue').fetchall()
        self.assertEqual(len(rows),1)
        self.assertIn('cuentas bancarias',rows[0]['body'].lower())
        self.assertEqual(rows[0]['kind'],'image')
        self.assertEqual(rows[0]['status'],'ACEPTADO')
        self.assertEqual(c.execute('SELECT state FROM whatsapp_bank_number_jobs WHERE message_id=?',(mid,)).fetchone()[0],'ACEPTADO')
        self.assertEqual(c.execute('SELECT enabled FROM whatsapp_menu_config WHERE id=1').fetchone()[0],0)
        c.close()

    def test_meta_media_upload_then_send_image(self):
        from unittest.mock import MagicMock
        sample=b'\\xff\\xd8'+b'photo'
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"id":"media-123"}'
        with patch.object(wa,'ACCESS_TOKEN','test-token'), \\
             patch.object(wa,'PHONE_NUMBER_ID','123456'), \\
             patch.object(bot.urllib.request,'urlopen',return_value=response) as upload, \\
             patch.object(wa,'_meta_post',return_value=(True,{'messages':[{'id':'wamid-123'}]},'')) as post:
            ok,pid,error=bot.send_meta_image('18094121799',sample,'Cuentas bancarias')
        self.assertTrue(ok)
        self.assertEqual(pid,'wamid-123')
        self.assertEqual(error,'')
        self.assertIn('/123456/media',upload.call_args.args[0].full_url)
        self.assertIn(b'messaging_product',upload.call_args.args[0].data)
        self.assertIn(sample,upload.call_args.args[0].data)
        payload=post.call_args.args[0]
        self.assertEqual(payload['type'],'image')
        self.assertEqual(payload['image']['id'],'media-123')
        self.assertEqual(payload['to'],'18094121799')

    def test_no_old_messages_replayed_on_initial_setup(self):
        self.inbound('cuenta')
        c=base.db()
        c.execute('UPDATE whatsapp_bank_number_config SET floor=(SELECT MAX(id) FROM whatsapp_messages)')
        c.commit();c.close()
        with patch.object(wa,'_send_text') as send:
            self.assertIsNone(bot.process_one())
            send.assert_not_called()

    def test_original_banking_card_is_a_valid_jpeg(self):
        image=bot.image_bytes()
        self.assertTrue(image.startswith(bytes((255,216))))
        self.assertLess(len(image),5_000_000)

    def test_image_failed_provider_is_not_retried(self):
        self.inbound('CUENTAS')
        with patch.object(wa,'_meta_ready',return_value=True), \
             patch.object(bot,'send_bank_image',return_value=(False,'','No se confirmó')) as send:
            self.assertEqual(bot.process_one(),'ERROR')
            self.assertIsNone(bot.process_one())
            send.assert_called_once()
        c=base.db()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM whatsapp_bank_number_jobs').fetchone()[0],1)
        c.close()

    def test_not_account_balance_request(self):
        self.assertFalse(bot.bank_request('dime mi saldo de cuenta'))
        self.assertFalse(bot.bank_request('estado de cuenta'))
        self.assertTrue(bot.bank_request('cuenta'))
        self.assertTrue(bot.bank_request('CUENTAS'))
        self.assertTrue(bot.bank_request('¿A qué cuenta pago?'))
        self.assertTrue(bot.bank_request('Necesito el número de cuenta'))

    def test_no_second_reply_after_human_answer(self):
        mid=self.inbound('cuenta')
        c=base.db()
        thread_id=c.execute('SELECT thread_id FROM whatsapp_messages WHERE id=?',(mid,)).fetchone()[0]
        c.execute("""INSERT INTO whatsapp_messages(thread_id,direction,message_type,
            body,status,created_at) VALUES(?,'OUT','text','Atendido','ENVIADO',?)""",
            (thread_id,wa._now()))
        c.commit();c.close()
        with patch.object(wa,'_send_text') as send:
            self.assertEqual(bot.process_one(),'OMITIDO')
            send.assert_not_called()


if __name__=='__main__':
    unittest.main()
