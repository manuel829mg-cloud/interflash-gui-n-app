"""Fixed optional recurring cable charge, snapshotted on each new invoice."""
PRICE = 500

def charge(customer):
    return PRICE if 'telecable_enabled' in customer.keys() and str(customer['telecable_enabled']) == '1' else 0

def snapshot(c, invoice_id, customer):
    c.execute('UPDATE invoices SET telecable_amount=? WHERE id=?', (charge(customer), invoice_id))
