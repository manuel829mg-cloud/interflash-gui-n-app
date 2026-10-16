"""One transactional payment path for receipts, cashier and quick payment."""
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from flask import request, redirect, url_for, flash, session
import app as base


def money(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('0.01')):
            raise ValueError('El monto debe ser positivo y tener como máximo dos decimales.')
        return value
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('El monto del pago no es válido.')


def record_payment(customer_id=None, invoice_id=None, amount=None, method='EFECTIVO', reference='', actor='ADMIN', proof=''):
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        inv = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone() if invoice_id else None
        if invoice_id and not inv:
            raise ValueError('Factura no encontrada.')
        if inv:
            if customer_id and int(customer_id) != inv['customer_id']:
                raise ValueError('La factura no pertenece al cliente seleccionado.')
            customer_id = inv['customer_id']
            paid = c.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=?', (invoice_id,)).fetchone()[0]
            balance = Decimal(str(inv['amount'])).quantize(Decimal('0.01')) - Decimal(str(paid)).quantize(Decimal('0.01'))
            if inv['status'] != 'PENDIENTE' or balance <= 0:
                raise ValueError('Esta factura ya está pagada o no admite pagos.')
            amount = money(balance if amount is None else amount)
            if amount > balance:
                raise ValueError('El pago supera el balance pendiente de la factura.')
        else:
            amount = money(amount)
        cu = c.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
        if not cu or cu['status'] == 'ELIMINADO':
            raise ValueError('Cliente no disponible para registrar pagos.')
        now = datetime.now().isoformat(timespec='seconds')
        method = method.strip().upper()
        if method not in {'EFECTIVO','TRANSFERENCIA','DEPOSITO','DEPÓSITO','TARJETA','CHEQUE','OTRO'}:
            method = 'OTRO'
        pid = c.execute('''INSERT INTO payments(customer_id,invoice_id,amount,method,reference,paid_at,received_by,proof)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        (customer_id, invoice_id, float(amount), method, reference[:500], now, actor, proof[:1000])).lastrowid
        if inv and amount == balance:
            c.execute("UPDATE invoices SET status='PAGADA',paid_at=? WHERE id=?", (now, invoice_id))
        settings = dict(c.execute('SELECT key,value FROM app_settings').fetchall())
        overdue = c.execute("SELECT 1 FROM invoices WHERE customer_id=? AND status='PENDIENTE' AND due_date<=? LIMIT 1",
                            (customer_id, date.today().isoformat())).fetchone()
        # Only an allocated, fully settled invoice can trigger reconnection.
        if inv and amount == balance and not overdue:
            c.execute("UPDATE router_commands SET status='CANCELADO',result='Deuda pagada antes del corte' WHERE customer_id=? AND action='SUSPEND' AND status='PENDIENTE' AND requested_by LIKE 'ZONA:%'", (customer_id,))
            queued = c.execute("SELECT 1 FROM router_commands WHERE customer_id=? AND action='REACTIVATE' AND status IN ('PENDIENTE','EN_PROCESO') LIMIT 1", (customer_id,)).fetchone()
            # A failed cut acknowledgement can leave status ACTIVO while PPP is disabled.
            # Fully paid invoices must reconcile router access regardless of cached status.
            if settings.get('auto_reactivate') == '1' and cu['pppoe'] and not queued:
                c.execute('''INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by)
                             VALUES(?,?,?,'REACTIVATE','{}','PENDIENTE',?,'PAGO')''',
                          (cu['router_name'] or 'CCR2116',customer_id,cu['pppoe'],now))
        from customer_phones import recipients
        if settings.get('whatsapp_enabled') == '1' and recipients(cu):
            if inv and amount == balance:
                from whatsapp_events import enqueue
                enqueue(c, f"INVOICE_PAID:{invoice_id}", customer_id,
                        'INVOICE_PDF_PAID:'+str(invoice_id),
                        f"Hola {cu['name']}, recibimos tu pago de RD${amount:,.2f}. Adjuntamos tu factura IF-{int(invoice_id):06d} marcada PAGADA. Gracias por preferir INTER Flash.")
            else:
                message = f"Hola {cu['name']}, recibimos tu pago de RD${amount:,.2f}. Gracias."
                from whatsapp_events import enqueue
                enqueue(c, f'PAYMENT:{pid}', customer_id, 'PAYMENT', message)
        c.commit()
        return pid
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def payment_endpoint(invoice_id=None, quick=False):
    if not base.logged_in():
        return redirect(url_for('login'))
    if (session.get('role') or 'ADMIN').upper() not in ('ADMIN','CAJA','COBRADOR'):
        return 'Sin permiso para registrar pagos.', 403
    try:
        pid = record_payment(customer_id=request.form.get('customer_id') if invoice_id is None else None,
                             invoice_id=invoice_id or request.form.get('invoice_id') or None,
                             amount=None if quick else request.form.get('amount'),
                             method=request.form.get('method') or 'EFECTIVO',
                             reference=request.form.get('reference') or '',
                             actor=session.get('user') or base.ADMIN_USER,
                             proof=request.form.get('proof') or '')
    except (ValueError, TypeError) as exc:
        flash(str(exc))
        return redirect(url_for('invoice_detail',id=invoice_id) if invoice_id else url_for('payments'))
    try:
        base.audit('PAYMENT_CREATE', f'Pago #{pid}')
    except Exception:
        pass
    flash('Pago registrado. La reactivación, si corresponde, queda en la cola MikroTik.')
    return redirect(url_for('payment_receipt',id=pid))


def reconcile_paid_cut_errors():
    """Recover paid accounts whose last cut failed acknowledgement."""
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        enabled = c.execute("SELECT value FROM app_settings WHERE key='auto_reactivate'").fetchone()
        if not enabled or enabled[0] != '1':
            return 0
        now = datetime.now().isoformat(timespec='seconds')
        rows = c.execute("""SELECT cu.id,cu.pppoe,cu.router_name
            FROM customers cu JOIN router_commands cut ON cut.customer_id=cu.id
            WHERE cu.status<>'ELIMINADO' AND COALESCE(TRIM(cu.pppoe),'')<>''
              AND cut.action='SUSPEND' AND cut.status='ERROR'
              AND cut.result='CORTE_NO_CONFIRMADO'
              AND cut.id=(SELECT MAX(rc.id) FROM router_commands rc
                 WHERE rc.customer_id=cu.id AND rc.action IN ('SUSPEND','REACTIVATE')
                 AND rc.status<>'CANCELADO')
              AND EXISTS(SELECT 1 FROM payments p JOIN invoices i ON i.id=p.invoice_id
                 WHERE p.customer_id=cu.id AND i.customer_id=cu.id AND i.status='PAGADA'
                 AND p.paid_at>=cut.created_at
                 AND i.amount<=COALESCE((SELECT SUM(pp.amount) FROM payments pp WHERE pp.invoice_id=i.id),0))
              AND NOT EXISTS(SELECT 1 FROM invoices i WHERE i.customer_id=cu.id
                 AND i.status='PENDIENTE' AND i.due_date<=?
                 AND i.amount>COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0))
              AND NOT EXISTS(SELECT 1 FROM router_commands rc WHERE rc.customer_id=cu.id
                 AND rc.action='REACTIVATE' AND rc.status IN ('PENDIENTE','EN_PROCESO'))""",
              (date.today().isoformat(),)).fetchall()
        for cu in rows:
            c.execute("""INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by)
                VALUES(?,?,?,'REACTIVATE','{}','PENDIENTE',?,'PAGO_RECUPERACION')""",
                (cu['router_name'] or 'CCR2116',cu['id'],cu['pppoe'],now))
        c.commit()
        return len(rows)
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def setup(app):
    if __import__('os').environ.get('INTERFLASH_TESTING') != '1':
        recovered = reconcile_paid_cut_errors()
        print(f'INTERFLASH_PAID_CUT_RECOVERY={recovered}', flush=True)
    original = app.view_functions['payments']
    app.view_functions['payments'] = lambda: payment_endpoint() if request.method == 'POST' else original()
    app.view_functions['invoice_payment'] = lambda id: payment_endpoint(id)
    app.view_functions['invoice_pay'] = lambda id: payment_endpoint(id, quick=True)
