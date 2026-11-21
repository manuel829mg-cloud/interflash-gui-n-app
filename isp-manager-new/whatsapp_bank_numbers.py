"""One-shot automatic banking flyer replies, independent of the welcome menu.

Send the existing verified Inter Flash banking flyer as an enhanced JPEG when
customers request CUENTA, CUENTAS or the bank account number. Never change a
customer's invoices, payments, account or router status.
"""
import os
import re
import base64
from io import BytesIO
from pathlib import Path
import threading
import time
import unicodedata
from datetime import datetime, timedelta

import app as base
import whatsapp_suite as wa


def bank_request(message):
    normalized = ''.join(
        char for char in unicodedata.normalize('NFD', str(message or '').lower())
        if unicodedata.category(char) != 'Mn'
    )
    words = re.findall(r'[a-z0-9]+', normalized)
    if not words or len(words) > 35:
        return False
    text = ' '.join(words)
    if text in ('cuenta','cuentas','cuenta bancaria','cuentas bancarias',
                'numero de cuenta','numeros de cuenta','numero de cuentas',
                'numeros de cuentas','datos bancarios','datos para transferir',
                'donde deposito','donde puedo depositar','donde pago'):
        return True
    # "Estado de cuenta", "mi cuenta" and "saldo de mi cuenta" mean something
    # other than a request for Inter Flash's bank account numbers.
    if any(phrase in text for phrase in (
        'estado de cuenta', 'mi cuenta', 'mi factura', 'saldo', 'deuda',
        'cuenta pendiente', 'crear cuenta', 'abrir cuenta')):
        return False
    if any(term in words for term in ('cuenta','cuentas','bancaria','bancarias')):
        return any(term in words for term in (
            'dame','manda','mandame','pasa','pasame','envia','enviame',
            'necesito','quiero','facilita','facilitar','numero','numeros',
            'pagar','pago','depositar','transferir','transferencia',
            'cual','cuales','donde','puedo','favor'))
    return False


def schema():
    c = base.db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS whatsapp_bank_number_config(
            id INTEGER PRIMARY KEY CHECK(id=1),
            enabled INTEGER NOT NULL DEFAULT 1,
            floor INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS whatsapp_bank_number_jobs(
            message_id INTEGER PRIMARY KEY,
            phone TEXT NOT NULL,
            state TEXT NOT NULL,
            queue_id INTEGER,
            created_at TEXT NOT NULL
        );
    """)
    # New feature: never replay old customer conversations on deployment.
    c.execute("""INSERT OR IGNORE INTO whatsapp_bank_number_config(id, enabled, floor)
        SELECT 1,1,COALESCE(MAX(id),0) FROM whatsapp_messages""")
    c.commit()
    c.close()


CAPTION = ("Cuentas bancarias de Inter Flash. Luego de realizar el pago, "
           "envíanos el comprobante.\n\n⚡ Inter Flash, siempre conectado contigo.")


def image_bytes():
    """Load our existing account card and sharpen it for phone screens.

    The original embedded card is the source of truth; do not reconstruct
    financial numbers with AI or replace them with unverified database rows.
    """
    from PIL import Image, ImageEnhance, ImageFilter
    file = Path(__file__).resolve().parent / 'assets' / 'bank_accounts.jpg.b64'
    encoded = file.read_text(encoding='ascii').strip()
    raw = base64.b64decode(encoded, validate=True)
    with Image.open(BytesIO(raw)) as source:
        image = ImageEnhance.Contrast(source.convert('RGB')).enhance(1.07)
        image = image.filter(ImageFilter.UnsharpMask(radius=1.2,percent=140,threshold=2))
        output = BytesIO()
        image.save(output,format='JPEG',quality=92,optimize=True)
    data = output.getvalue()
    if not data or len(data) > 5_000_000:
        raise ValueError('La imagen bancaria no cumple el límite de WhatsApp.')
    return data


def send_bank_image(phone, caption=CAPTION):
    """Single provider send; preserve delivery IDs for tracking, no retries."""
    import greenapi_suite as green
    import whapi_suite as whapi
    import waha_suite as waha
    try:
        data = image_bytes()
    except (OSError,ValueError,base64.binascii.Error):
        return False,'','No se pudo leer la imagen bancaria configurada.'
    try:
        if waha.enabled():
            cfg = waha.config()
            result = waha.api('/api/sendImage',{
                'session':cfg['session_name'],'chatId':phone+'@c.us',
                'file':{'mimetype':'image/jpeg','filename':'cuentas-interflash.jpg',
                        'data':base64.b64encode(data).decode('ascii')},
                'caption':caption},cfg)
            mid = waha.message_id(result)
            if not mid:
                return False,'','WAHA no confirmó el envío de la imagen bancaria.'
            return True,'waha:'+cfg['session_name']+':'+mid,''
        if green.enabled():
            return green.send_image(phone,data,'cuentas-interflash.jpg',caption)
        if whapi.enabled():
            return whapi.send_image(phone,data,'cuentas-interflash.jpg',caption)
        return False,'','El proveedor activo no admite el envío de imágenes bancarias.'
    except waha.APIError:
        return False,'','El proveedor no confirmó el envío de la imagen bancaria.'


def process_one():
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        cfg = c.execute('SELECT * FROM whatsapp_bank_number_config WHERE id=1').fetchone()
        if not cfg or not cfg['enabled']:
            c.rollback()
            return None
        row = c.execute("""SELECT m.id, m.thread_id, m.body, m.message_type,
                m.created_at, t.phone
            FROM whatsapp_messages m JOIN whatsapp_threads t ON t.id=m.thread_id
            WHERE m.id>? AND m.direction='IN'
              AND NOT EXISTS (
                 SELECT 1 FROM whatsapp_bank_number_jobs j WHERE j.message_id=m.id)
            ORDER BY m.id LIMIT 1""", (cfg['floor'],)).fetchone()
        if not row:
            c.rollback()
            return None

        incoming_id = row['id']
        text = str(row['body'] or '')
        is_request = (row['message_type'] in (
            'text','textMessage','extendedTextMessage','chat'
        ) and bank_request(text))
        # Never reply to historical requests or after human agent's response.
        try:
            age = datetime.now() - datetime.fromisoformat(str(row['created_at'])).replace(tzinfo=None)
        except (ValueError, TypeError):
            age = timedelta(days=1)
        recent = timedelta(seconds=-30) <= age <= timedelta(minutes=5)
        human = c.execute("""SELECT 1 FROM whatsapp_messages
            WHERE thread_id=? AND id>? AND direction='OUT' LIMIT 1""",
            (row['thread_id'], incoming_id)).fetchone()
        if not is_request or not recent or human:
            c.execute("""INSERT INTO whatsapp_bank_number_jobs
                (message_id,phone,state,created_at) VALUES(?,?,'OMITIDO',?)""",
                (incoming_id,row['phone'],wa._now()))
            c.commit()
            return 'OMITIDO'
        if not wa._meta_ready():
            c.execute("""INSERT INTO whatsapp_bank_number_jobs
                (message_id,phone,state,created_at) VALUES(?,?,'SIN_PROVEEDOR',?)""",
                (incoming_id,row['phone'],wa._now()))
            c.commit()
            return 'SIN_PROVEEDOR'
        # Recorded before sending, so a worker restart can never send twice.
        qid = c.execute("""INSERT INTO whatsapp_queue(
            thread_id,customer_id,phone,kind,body,status,created_at)
            VALUES(?,?,?,'image',?,'PENDIENTE',?)""",
            (row['thread_id'],None,row['phone'],CAPTION,wa._now())
        ).lastrowid
        c.execute("""INSERT INTO whatsapp_bank_number_jobs
            (message_id,phone,state,queue_id,created_at)
            VALUES(?,?,'EN_PROCESO',?,?)""",
            (incoming_id,row['phone'],qid,wa._now()))
        c.commit()
        # One network call only. The job is already marked EN_PROCESO in the
        # database; uncertain provider outcomes must be inspected, not retried.
        ok,pid,err = send_bank_image(wa._wa_phone(row['phone']))
        status = 'ACEPTADO' if ok else 'ERROR'
        c.execute('UPDATE whatsapp_queue SET status=?,attempts=1,provider_id=?,last_error=?,sent_at=? WHERE id=?',
                  (status,pid or None,err or None,wa._now() if ok else None,qid))
        wa._record_outgoing(c,row['thread_id'],'[Imagen de cuentas bancarias] '+CAPTION,
                            pid or '',status,err)
        c.execute('UPDATE whatsapp_bank_number_jobs SET state=? WHERE message_id=?',
                  (status,incoming_id))
        c.commit()
        return status
    finally:
        c.close()


def setup(app):
    schema()
    if os.getenv('INTERFLASH_TESTING') == '1':
        return
    c = base.db()
    try:
        app.logger.info('INTERFLASH_BANK_FLYER_IMAGE_READY=%s',
                        (Path(__file__).resolve().parent/'assets'/'bank_accounts.jpg.b64').is_file())
    finally:
        c.close()

    def worker():
        while True:
            try:
                with app.app_context():
                    process_one()
            except Exception:
                app.logger.error('WhatsApp bank-number reply worker failed')
            time.sleep(2)

    threading.Thread(target=worker,name='whatsapp-bank-numbers',daemon=True).start()
