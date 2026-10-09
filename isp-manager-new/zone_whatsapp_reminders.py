"""Opt-in reminders per zone, with a fresh debt check before dispatch."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import app as base

RD = ZoneInfo('America/Santo_Domingo')


def candidates(c, now):
    from zone_cut_scheduler import _zone_join, _parse_cut_time
    rows = c.execute(f'''SELECT cu.id customer_id,cu.name,z.id zone_id,
        z.cut_days_after,z.cut_time,z.whatsapp_reminder_days,
        MIN(i.due_date) oldest_due,
        SUM(i.amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0)) balance
        FROM customers cu JOIN zones z ON {_zone_join()}
        JOIN invoices i ON i.customer_id=cu.id AND i.status='PENDIENTE'
        WHERE COALESCE(z.active,1)=1 AND z.whatsapp_reminder_enabled=1
        AND COALESCE(cu.status,'ACTIVO') NOT IN ('ELIMINADO','SUSPENDIDO')
        AND i.amount>COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0)
        GROUP BY cu.id,z.id''').fetchall()
    for row in rows:
        try:
            cut = date.fromisoformat(row['oldest_due']) + timedelta(days=max(0,int(row['cut_days_after'])))
            days = int(row['whatsapp_reminder_days'])
            if not 0 <= days <= 31:
                continue
            if now.date() != cut - timedelta(days=days):
                continue
            if now >= datetime.combine(cut, _parse_cut_time(row['cut_time'])):
                continue
            if c.execute("SELECT 1 FROM payment_promises WHERE customer_id=? AND status='PENDIENTE' AND promise_date>=?",(row['customer_id'],now.date().isoformat())).fetchone():
                continue
            yield dict(row, cut_date=cut.isoformat(), event_key=f"ZONE_REMINDER:{row['customer_id']}:{row['zone_id']}:{cut.isoformat()}")
        except (ValueError, TypeError):
            continue


def message_for(row):
    when = date.fromisoformat(row['cut_date']).strftime('%d/%m/%Y')
    return f"Hola {row['name']}, INTER Flash te recuerda que tienes RD${row['balance']:,.2f} pendientes. Tu corte está programado para el {when}. Realiza tu pago antes de esa fecha. Si ya pagaste, envíanos tu comprobante."


def process(now=None):
    from whatsapp_events import enqueue
    now = now or datetime.now(RD).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(RD).replace(tzinfo=None)
    if not 8 <= now.hour < 20:
        return 0
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        count = 0
        for row in candidates(c, now):
            message = message_for(row)
            count += int(enqueue(c,row['event_key'],row['customer_id'],'ZONE_REMINDER',message))
        c.commit()
        return count
    finally:
        c.close()


def valid(c, outbox_id, now=None):
    now = now or datetime.now(RD).replace(tzinfo=None)
    if not 8 <= now.hour < 20:
        return False
    event = c.execute('SELECT event_key FROM whatsapp_event_keys WHERE outbox_id=?',(outbox_id,)).fetchone()
    if event:
        for row in candidates(c,now):
            if row['event_key'] == event[0]:
                c.execute('UPDATE whatsapp_outbox SET message=? WHERE id=?',(message_for(row),outbox_id))
                return True
    return False
