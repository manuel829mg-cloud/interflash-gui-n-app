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
            in_flight = c.execute("SELECT 1 FROM router_commands WHERE customer_id=? AND action='SUSPEND' AND status='EN_PROCESO' LIMIT 1", (customer_id,)).fetchone()
            queued = c.execute("SELECT 1 FROM router_commands WHERE customer_id=? AND action='REACTIVATE' AND status IN ('PENDIENTE','EN_PROCESO') LIMIT 1", (customer_id,)).fetchone()
            if settings.get('auto_reactivate') == '1' and cu['pppoe'] and (cu['status'] == 'SUSPENDIDO' or in_flight) and not queued:
                c.execute('''INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by)
                             VALUES(?,?,?,'REACTIVATE','{}','PENDIENTE',?,'PAGO')''',
                          (cu['router_name'] or 'CCR2116',customer_id,cu['pppoe'],now))
        if settings.get('whatsapp_enabled') == '1' and cu['phone']:
            template = c.execute("SELECT body FROM whatsapp_templates WHERE code='PAYMENT' AND active=1").fetchone()
            if template:
                try:
                    message = template['body'].format(name=cu['name'], amount=f'RD${amount:,.2f}', due_date=inv['due_date'] if inv else '')
                except (KeyError, ValueError):
                    message = f"Hola {cu['name']}, recibimos tu pago de RD${amount:,.2f}. Gracias."
                c.execute("INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(?,?,'PAYMENT',?,'PENDIENTE',?)", (customer_id,cu['phone'],message,now))
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


def setup(app):
    original = app.view_functions['payments']
    app.view_functions['payments'] = lambda: payment_endpoint() if request.method == 'POST' else original()
    app.view_functions['invoice_payment'] = lambda id: payment_endpoint(id)
    app.view_functions['invoice_pay'] = lambda id: payment_endpoint(id, quick=True)
