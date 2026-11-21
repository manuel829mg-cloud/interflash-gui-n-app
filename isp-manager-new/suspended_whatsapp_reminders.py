"""Dos avisos de pago para clientes suspendidos: a los 2 y 4 días.

La primera notificación vencida de una suspensión antigua se envía una sola
vez durante el horario permitido; la segunda espera dos días desde el primer
envío confirmado. Nunca se notifican clientes activos o sin saldo pendiente.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import app as base

RD = ZoneInfo('America/Santo_Domingo')
FOOTER = '\n\n⚡ Inter Flash, siempre conectado contigo.'
CODES = {2: 'SUSPENDED_D2', 4: 'SUSPENDED_D4'}


def _local_now(now=None):
    if now is None:
        return datetime.now(RD).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(RD).replace(tzinfo=None)
    return now


def _in_window(now):
    return 9 <= now.hour < 20


def _sent_at(c, key):
    row = c.execute("""
        SELECT o.status, o.sent_at
          FROM whatsapp_event_keys k
          JOIN whatsapp_outbox o ON o.id=k.outbox_id
         WHERE k.event_key=?
    """, (key,)).fetchone()
    if not row or row['status'] not in ('ACEPTADO', 'ENVIADO', 'ENTREGADO', 'LEIDO'):
        return None
    try:
        return datetime.fromisoformat(str(row['sent_at']))
    except (ValueError, TypeError):
        return None


def candidates(c, now):
    """Returns only due, unpaid, currently suspended customers.

    The latest confirmed router action must be a suspension. A manual status
    change with no verifiable suspension date is deliberately excluded.
    """
    now = _local_now(now)
    rows = c.execute("""
        SELECT cu.id customer_id, cu.name, cmd.id suspension_id, cmd.executed_at suspended_at
        FROM customers cu
        JOIN router_commands cmd ON cmd.customer_id=cu.id
        WHERE cu.status='SUSPENDIDO'
          AND COALESCE(cu.service_status, cu.status)='SUSPENDIDO'
          AND cmd.action='SUSPEND' AND cmd.status='COMPLETADO'
          AND cmd.executed_at IS NOT NULL
          AND cmd.id=(
              SELECT MAX(last.id) FROM router_commands last
              WHERE last.customer_id=cu.id
                AND last.action IN ('SUSPEND','REACTIVATE')
                AND last.status='COMPLETADO'
          )
          AND EXISTS (
              SELECT 1 FROM invoices i
              WHERE i.customer_id=cu.id AND i.status='PENDIENTE'
                AND i.amount>COALESCE(
                    (SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id), 0)
          )
          AND NOT EXISTS (
              SELECT 1 FROM payment_promises p
              WHERE p.customer_id=cu.id AND p.status='PENDIENTE'
                AND (p.promise_date>?
                     OR (p.promise_date=? AND COALESCE(p.promise_time,'23:59')>?))
          )
    """, (now.date().isoformat(), now.date().isoformat(), now.strftime('%H:%M'))).fetchall()
    for row in rows:
        try:
            suspended_at = datetime.fromisoformat(str(row['suspended_at']))
            if suspended_at.tzinfo:
                suspended_at = suspended_at.astimezone(RD).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
        if now < suspended_at + timedelta(days=2):
            continue
        prefix = f"SUSPENDED_REMINDER:{row['customer_id']}:{row['suspension_id']}"
        first_key = prefix + ':2'
        second_key = prefix + ':4'
        first = c.execute(
            'SELECT 1 FROM whatsapp_event_keys WHERE event_key=?',
            (first_key,)
        ).fetchone()
        if not first:
            yield dict(row, days=2, event_key=first_key)
            continue
        if now < suspended_at + timedelta(days=4):
            continue
        sent = _sent_at(c, first_key)
        if sent and now >= sent + timedelta(days=2):
            yield dict(row, days=4, event_key=second_key)


def message_for(row):
    name = row['name']
    if row['days'] == 2:
        return (
            f"Hola, {name}.\n\nTe recordamos que tu servicio de Internet de "
            "Inter Flash continúa suspendido por un pago pendiente. "
            "Queremos que vuelvas a disfrutar de tu conexión lo antes posible. "
            "Puedes realizar tu pago y enviarnos el comprobante para gestionar "
            "tu reconexión.\n\nGracias por preferir Inter Flash." + FOOTER
        )
    return (
        f"Hola, {name}.\n\nTu servicio de Internet continúa suspendido. "
        "Queremos ayudarte a recuperar tu conexión. Si tienes alguna dificultad "
        "para realizar el pago, puedes comunicarte con nosotros y consultar "
        "las opciones disponibles." + FOOTER
    )


def process(now=None):
    from whatsapp_events import enqueue
    now = _local_now(now)
    if not _in_window(now):
        return 0
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        count = 0
        for row in candidates(c, now):
            count += int(enqueue(
                c, row['event_key'], row['customer_id'], CODES[row['days']],
                message_for(row)
            ))
        c.commit()
        return count
    finally:
        c.close()


def valid(c, outbox_id, now=None):
    """Recheck payment and status just before provider submission."""
    now = _local_now(now)
    if not _in_window(now):
        return None
    event = c.execute(
        'SELECT event_key FROM whatsapp_event_keys WHERE outbox_id=?',
        (outbox_id,)
    ).fetchone()
    if not event:
        return False
    key = event['event_key'].split('|PHONE:', 1)[0]
    for row in candidates(c, now):
        if row['event_key'] == key:
            c.execute(
                'UPDATE whatsapp_outbox SET message=? WHERE id=?',
                (message_for(row), outbox_id)
            )
            return True
    return False
