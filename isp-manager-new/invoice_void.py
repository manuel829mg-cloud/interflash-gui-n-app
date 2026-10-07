"""Auditable invoice cancellation without erasing financial records."""
import hmac
from datetime import date, datetime
from flask import request, session, abort, flash, redirect, url_for
import app as base


def cancel_invoice(invoice_id, reason, actor):
    reason = str(reason or '').strip()
    if not 5 <= len(reason) <= 500:
        raise ValueError('Escribe un motivo de entre 5 y 500 caracteres.')
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        inv = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
        if not inv:
            raise ValueError('Factura no encontrada.')
        if inv['status'] == 'ANULADA':
            return False
        if inv['status'] != 'PENDIENTE' or c.execute('SELECT 1 FROM payments WHERE invoice_id=? LIMIT 1', (invoice_id,)).fetchone():
            raise ValueError('No se puede anular una factura con pagos registrados o que no esté pendiente.')
        c.execute("UPDATE invoices SET status='ANULADA' WHERE id=?", (invoice_id,))
        c.execute('INSERT INTO invoice_cancellations(invoice_id,reason,actor,created_at) VALUES(?,?,?,?)',
                  (invoice_id, reason, actor, datetime.now().isoformat(timespec='seconds')))
        c.execute("UPDATE payment_promises SET status='CANCELADA' WHERE invoice_id=? AND status='PENDIENTE'", (invoice_id,))
        # Pending automatic cuts must no longer use a cancelled debt.
        overdue = c.execute("SELECT 1 FROM invoices WHERE customer_id=? AND status='PENDIENTE' AND due_date<=? LIMIT 1", (inv['customer_id'], date.today().isoformat())).fetchone()
        if not overdue:
            c.execute("UPDATE router_commands SET status='CANCELADO',result='Factura anulada; sin deuda vencida' WHERE customer_id=? AND action='SUSPEND' AND status='PENDIENTE' AND (requested_by LIKE 'ZONA:%' OR requested_by='AUTOMATICO')", (inv['customer_id'],))
        pending = c.execute("SELECT 1 FROM invoices WHERE customer_id=? AND status='PENDIENTE' LIMIT 1", (inv['customer_id'],)).fetchone()
        if not pending:
            c.execute("UPDATE whatsapp_outbox SET status='CANCELADO',error='Sin facturas pendientes tras anulación' WHERE customer_id=? AND status='PENDIENTE' AND template_code IN ('INVOICE','DUE','OVERDUE')", (inv['customer_id'],))
        c.commit()
        return True
    except Exception:
        c.rollback(); raise
    finally:
        c.close()


def endpoint(id):
    if not base.logged_in(): return redirect(url_for('login'))
    if (session.get('role') or 'ADMIN').upper() != 'ADMIN': abort(403)
    if not hmac.compare_digest(session.get('invoice_void_csrf',''), request.form.get('csrf','missing')): abort(403)
    try:
        changed = cancel_invoice(id, request.form.get('reason'), session.get('user') or base.ADMIN_USER)
        flash('Factura anulada. Ya no cuenta como deuda.' if changed else 'Esta factura ya estaba anulada.')
    except ValueError as exc:
        flash(str(exc))
    return redirect(url_for('invoice_detail', id=id))


def setup(app):
    c=base.db()
    c.execute('''CREATE TABLE IF NOT EXISTS invoice_cancellations(
        invoice_id INTEGER PRIMARY KEY,reason TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL)''')
    c.commit();c.close()
    app.add_url_rule('/invoices/<int:id>/cancel', endpoint='invoice_cancel', view_func=endpoint, methods=['POST'])
