"""Automatic WhatsApp reply with bank account numbers only.

Independent from the welcome menu/AI. Responds to new inbound account-number
requests using active bank_accounts, with a single provider attempt per
incoming message. Never changes a customer's billing, status or router.
"""
import os
import re
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


def numbers_message(c):
    if not c.execute(
        "SELECT 1 FROM sqlite_master WHERE name='bank_accounts' AND type='table'"
    ).fetchone():
        return None
    rows = c.execute("""SELECT account_number FROM bank_accounts
        WHERE active=1 AND TRIM(COALESCE(account_number,''))<>''
        ORDER BY id""").fetchall()
    nums = []
    for row in rows:
        num = str(row['account_number'] or '').strip()
        if re.fullmatch(r'[0-9 -]{6,40}', num) and num not in nums:
            nums.append(num)
    # Do not guess or take old account numbers from an outdated image.
    return '\n'.join(nums) if nums else None


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
        numbers = numbers_message(c)
        if numbers is None:
            # Do not send incorrect/missing financial details to customers.
            c.execute("""INSERT INTO whatsapp_bank_number_jobs
                (message_id,phone,state,created_at) VALUES(?,?,'SIN_CUENTAS',?)""",
                (incoming_id,row['phone'],wa._now()))
            c.commit()
            return 'SIN_CUENTAS'
        if not wa._meta_ready():
            c.execute("""INSERT INTO whatsapp_bank_number_jobs
                (message_id,phone,state,created_at) VALUES(?,?,'SIN_PROVEEDOR',?)""",
                (incoming_id,row['phone'],wa._now()))
            c.commit()
            return 'SIN_PROVEEDOR'
        # Recorded before sending, so a worker restart can never send twice.
        qid = c.execute("""INSERT INTO whatsapp_queue(
            thread_id,customer_id,phone,kind,body,status,created_at)
            VALUES(?,?,?,'text',?,'PENDIENTE',?)""",
            (row['thread_id'],None,row['phone'],numbers,wa._now())
        ).lastrowid
        c.execute("""INSERT INTO whatsapp_bank_number_jobs
            (message_id,phone,state,queue_id,created_at)
            VALUES(?,?,'EN_PROCESO',?,?)""",
            (incoming_id,row['phone'],qid,wa._now()))
        c.commit()
        job = c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(qid,)).fetchone()
        ok, err = wa._process_queue_item(c,job)
        status = c.execute('SELECT status FROM whatsapp_queue WHERE id=?',(qid,)).fetchone()[0]
        c.execute('UPDATE whatsapp_bank_number_jobs SET state=? WHERE message_id=?',
                  ('ACEPTADO' if ok else 'ERROR',incoming_id))
        c.commit()
        return status
    finally:
        c.close()


def setup(app):
    schema()
    if os.getenv('INTERFLASH_TESTING') == '1':
        return

    def worker():
        while True:
            try:
                with app.app_context():
                    process_one()
            except Exception:
                app.logger.error('WhatsApp bank-number reply worker failed')
            time.sleep(2)

    threading.Thread(target=worker,name='whatsapp-bank-numbers',daemon=True).start()
