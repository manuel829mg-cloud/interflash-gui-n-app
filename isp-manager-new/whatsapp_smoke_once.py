"""One-time explicitly requested WhatsApp transport test.

Only runs when INTERFLASH_WA_TEST_NUMBER is configured; no customer status,
invoices or scheduled reminders are touched.
"""
import os
import logging
import app as base
import whatsapp_suite as wa

KEY = 'WHATSAPP_SMOKE_TEST_20261120'
BODY = (
    "🧪 PRUEBA INTER FLASH — NO ES UN AVISO REAL DE SUSPENSIÓN.\n\n"
    "Este mensaje verifica que las notificaciones de Inter Flash "
    "pueden llegar por WhatsApp. No representa una deuda ni un corte "
    "de servicio.\n\n"
    "⚡ Inter Flash, siempre conectado contigo."
)


def send_once():
    raw = os.getenv('INTERFLASH_WA_TEST_NUMBER', '').strip()
    if not raw:
        return
    phone = wa._wa_phone(raw)
    if len(phone) != 11 or not phone.startswith('1'):
        logging.error('INTERFLASH_WA_SMOKE_TEST_INVALID_PHONE')
        return
    if not wa._meta_ready():
        logging.error('INTERFLASH_WA_SMOKE_TEST_PROVIDER_NOT_CONFIGURED')
        return
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        cur = c.execute('INSERT OR IGNORE INTO app_settings(key,value) VALUES(?,?)', (KEY,'queued'))
        if not cur.rowcount:
            c.rollback()
            logging.info('INTERFLASH_WA_SMOKE_TEST_ALREADY_ATTEMPTED')
            return
        # Queue without customer_id. This is not a billing event and cannot
        # alter client suspension, invoices, promises, or account balances.
        qid = c.execute("""INSERT INTO whatsapp_queue
            (customer_id,phone,kind,body,status,created_at)
            VALUES(NULL,?,'text',?,'PENDIENTE',?)""",
            (phone,BODY,wa._now())).lastrowid
        c.commit()
        row = c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(qid,)).fetchone()
        ok, error = wa._process_queue_item(c,row)
        state = c.execute('SELECT status FROM whatsapp_queue WHERE id=?',(qid,)).fetchone()['status']
        logging.warning('INTERFLASH_WA_SMOKE_TEST_RESULT queue_id=%s accepted=%s status=%s error=%s',
                        qid,ok,state,(error or '')[:180])
    finally:
        c.close()
