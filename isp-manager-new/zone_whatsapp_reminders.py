"""One unpaid invoice reminder on its due date, using Dominican local time."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import app as base

RD = ZoneInfo('America/Santo_Domingo')

def candidates(c, now):
    rows = c.execute("""SELECT cu.id customer_id,cu.name,i.id invoice_id,i.due_date,
        i.amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0) balance
        FROM invoices i JOIN customers cu ON cu.id=i.customer_id
        WHERE i.status='PENDIENTE' AND i.due_date=?
        AND COALESCE(cu.status,'ACTIVO')<>'ELIMINADO'
        AND COALESCE(cu.phone,'')<>''
        AND i.amount>COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0)
        AND NOT EXISTS(SELECT 1 FROM payment_promises p WHERE p.customer_id=cu.id
            AND p.status='PENDIENTE' AND (p.promise_date>? OR
            (p.promise_date=? AND COALESCE(p.promise_time,'23:59')>?)))""",
        (now.date().isoformat(),now.date().isoformat(),now.date().isoformat(),now.strftime('%H:%M'))).fetchall()
    for row in rows:
        yield dict(row,event_key=f"INVOICE_DUE:{row['invoice_id']}")

def message_for(row):
    when=date.fromisoformat(row['due_date']).strftime('%d/%m/%Y')
    return f"Hola {row['name']}, tu factura IF-{row['invoice_id']:06d} de INTER Flash vence hoy, {when}. Balance pendiente: RD${row['balance']:,.2f}. Adjuntamos tu factura. Si ya pagaste, envíanos tu comprobante."

def process(now=None):
    from whatsapp_events import enqueue
    now=now or datetime.now(RD)
    if now.tzinfo is not None: now=now.astimezone(RD).replace(tzinfo=None)
    if not 10<=now.hour<20: return 0
    c=base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        count=0
        for row in candidates(c,now):
            count+=int(enqueue(c,row['event_key'],row['customer_id'],
                'INVOICE_PDF_DUE:'+str(row['invoice_id']),message_for(row)))
        c.commit()
        return count
    finally: c.close()

def valid(c,outbox_id,now=None):
    now=now or datetime.now(RD)
    if now.tzinfo is not None: now=now.astimezone(RD).replace(tzinfo=None)
    if not 10<=now.hour<20: return False
    event=c.execute('SELECT event_key FROM whatsapp_event_keys WHERE outbox_id=?',(outbox_id,)).fetchone()
    if event:
        for row in candidates(c,now):
            if row['event_key']==event[0]:
                c.execute('UPDATE whatsapp_outbox SET message=? WHERE id=?',(message_for(row),outbox_id))
                return True
    return False
