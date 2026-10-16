"""Distinct normalized recipients for customer business notices."""
def recipients(customer):
    from whatsapp_suite import _wa_phone
    values = dict(customer)
    result = []
    for field in ('phone', 'phone_secondary'):
        phone = _wa_phone(values.get(field))
        if phone and phone not in result:
            result.append(phone)
    return result
