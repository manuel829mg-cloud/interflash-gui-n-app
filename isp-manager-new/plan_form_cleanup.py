import re
import pbr_client


def setup(app):
    """Hide the duplicate commercial Plan selector on existing-customer edits.

    The customer's current plan_id is preserved in a hidden input so saving
    technical PPPoE/PBR changes never clears or changes the commercial plan.
    New-customer creation keeps the Plan selector because an initial plan still
    needs to be chosen there.
    """
    current = pbr_client.customer_form
    if getattr(current, '_interflash_plan_cleanup_patched', False):
        return

    pattern = re.compile(
        r'<div><label>Plan<select name="plan_id">.*?</select></label></div>',
        re.S,
    )

    def customer_form(row=None):
        html = current(row)
        if row is None:
            return html
        try:
            plan_id = row['plan_id'] if 'plan_id' in row.keys() and row['plan_id'] is not None else ''
        except Exception:
            plan_id = ''
        hidden = f'<input type="hidden" name="plan_id" value="{plan_id}">'
        return pattern.sub(hidden, html, count=1)

    customer_form._interflash_plan_cleanup_patched = True
    pbr_client.customer_form = customer_form
