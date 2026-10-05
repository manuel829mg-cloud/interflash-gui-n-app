import re
import pbr_client


def setup(app):
    """Tidy the customer form without changing stored customer data.

    - Existing-customer edits hide the duplicate commercial Plan selector while
      preserving the current plan_id in a hidden input.
    - Swap the visual positions of Zona and Usuario PPPoE so Usuario PPPoE
      appears where Zona used to be, and Zona appears where Usuario PPPoE was.
    """
    current = pbr_client.customer_form
    if getattr(current, '_interflash_plan_cleanup_patched', False):
        return

    plan_pattern = re.compile(
        r'<div><label>Plan<select name="plan_id">.*?</select></label></div>',
        re.S,
    )
    zone_pattern = re.compile(
        r'(<div><label>Zona<input name="zone".*?</label></div>)',
        re.S,
    )
    pppoe_pattern = re.compile(
        r'(<div><label>Usuario PPPoE<input name="pppoe".*?</label></div>)',
        re.S,
    )

    def swap_zone_pppoe(html):
        zone_match = zone_pattern.search(html)
        pppoe_match = pppoe_pattern.search(html)
        if not zone_match or not pppoe_match:
            return html
        zone_html = zone_match.group(1)
        pppoe_html = pppoe_match.group(1)
        placeholder = '__INTERFLASH_ZONE_PPPOE_SWAP__'
        html = html.replace(zone_html, placeholder, 1)
        html = html.replace(pppoe_html, zone_html, 1)
        html = html.replace(placeholder, pppoe_html, 1)
        return html

    def customer_form(row=None):
        html = swap_zone_pppoe(current(row))
        if row is None:
            return html
        try:
            plan_id = row['plan_id'] if 'plan_id' in row.keys() and row['plan_id'] is not None else ''
        except Exception:
            plan_id = ''
        hidden = f'<input type="hidden" name="plan_id" value="{plan_id}">'
        return plan_pattern.sub(hidden, html, count=1)

    customer_form._interflash_plan_cleanup_patched = True
    pbr_client.customer_form = customer_form
