"""Optional recurring Telecable charge, snapshotted on each new invoice."""
PRICE = 500
OPTIONS = (500, 600, 800, 1000)

def charge(customer):
    keys = customer.keys()
    amount = 0
    if 'telecable_amount' in keys:
        try:
            amount = int(round(float(customer['telecable_amount'] or 0)))
        except (TypeError, ValueError):
            amount = 0
    if amount in OPTIONS:
        return amount
    # Keep existing subscribers with the former checkbox enabled at RD$500.
    return PRICE if 'telecable_enabled' in keys and str(customer['telecable_enabled']) == '1' else 0

def snapshot(c, invoice_id, customer):
    c.execute('UPDATE invoices SET telecable_amount=? WHERE id=?', (charge(customer), invoice_id))
