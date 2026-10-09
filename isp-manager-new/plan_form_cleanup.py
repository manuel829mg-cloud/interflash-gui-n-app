import re
from flask import request
import pbr_client


def setup(app):
    """Tidy the customer form and keep configured zones selected correctly.

    - Keep the commercial Plan selector available for manual reassignment.
    - Swap the visual positions of Zona and Usuario PPPoE so Usuario PPPoE
      appears where Zona used to be, and Zona appears where Usuario PPPoE was.
    - Render Zona as a selector populated from the configured zones table and
      mark the customer's current zone as selected.
    - Keep customers.zone_id synchronized with the selected zone.
    """
    current = pbr_client.customer_form
    if getattr(current, '_interflash_plan_cleanup_patched', False):
        return

    plan_pattern = re.compile(
        r'<div><label>Plan<select name="plan_id">.*?</select></label></div>',
        re.S,
    )
    zone_input_pattern = re.compile(
        r'<div><label>Zona<input name="zone".*?</label></div>',
        re.S,
    )
    zone_any_pattern = re.compile(
        r'(<div><label>Zona(?:<input name="zone".*?|<select name="zone">.*?</select>)</label></div>)',
        re.S,
    )
    pppoe_pattern = re.compile(
        r'(<div><label>Usuario PPPoE<input name="pppoe".*?</label></div>)',
        re.S,
    )

    def _zone_rows():
        c = pbr_client.base.db()
        try:
            return c.execute('SELECT id,name,active FROM zones ORDER BY name').fetchall()
        except Exception:
            return []
        finally:
            c.close()

    def _current_zone_name(row):
        if row is None:
            return ''
        try:
            zid = row['zone_id'] if 'zone_id' in row.keys() else None
        except Exception:
            zid = None
        if zid:
            c = pbr_client.base.db()
            try:
                zr = c.execute('SELECT name FROM zones WHERE id=?', (zid,)).fetchone()
                if zr and zr['name']:
                    return str(zr['name'])
            except Exception:
                pass
            finally:
                c.close()
        try:
            return str(row['zone'] or '') if 'zone' in row.keys() else ''
        except Exception:
            return ''

    def _zone_select(row):
        current_zone = _current_zone_name(row)
        zones = _zone_rows()
        names = {str(z['name']) for z in zones if z['name']}
        opts = ['<option value="">Seleccionar zona</option>']
        if current_zone and current_zone not in names:
            opts.append(
                f'<option value="{pbr_client.esc(current_zone)}" selected>{pbr_client.esc(current_zone)}</option>'
            )
        for z in zones:
            name = str(z['name'] or '')
            if not name:
                continue
            selected = ' selected' if name == current_zone else ''
            inactive = ' · inactiva' if not int(z['active'] or 0) else ''
            opts.append(
                f'<option value="{pbr_client.esc(name)}"{selected}>{pbr_client.esc(name + inactive)}</option>'
            )
        return '<div><label>Zona<select name="zone">' + ''.join(opts) + '</select></label></div>'

    def swap_zone_pppoe(html):
        zone_match = zone_any_pattern.search(html)
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
        html = current(row)
        html = zone_input_pattern.sub(_zone_select(row), html, count=1)
        html = swap_zone_pppoe(html)
        return html

    customer_form._interflash_plan_cleanup_patched = True
    pbr_client.customer_form = customer_form

    def _sync_zone_id(customer_id):
        zone_name = (request.form.get('zone') or '').strip()
        c = pbr_client.base.db()
        try:
            zone_id = None
            if zone_name:
                zr = c.execute('SELECT id FROM zones WHERE name=? LIMIT 1', (zone_name,)).fetchone()
                zone_id = zr['id'] if zr else None
            c.execute('UPDATE customers SET zone_id=? WHERE id=?', (zone_id, customer_id))
            c.commit()
        finally:
            c.close()

    if 'customer_edit' in app.view_functions and not getattr(app.view_functions['customer_edit'], '_interflash_zone_sync_patched', False):
        original_edit = app.view_functions['customer_edit']

        def edit_wrapper(id, *args, **kwargs):
            response = original_edit(id, *args, **kwargs)
            if request.method == 'POST':
                _sync_zone_id(id)
            return response

        edit_wrapper._interflash_zone_sync_patched = True
        app.view_functions['customer_edit'] = edit_wrapper

    if 'customer_new' in app.view_functions and not getattr(app.view_functions['customer_new'], '_interflash_zone_sync_patched', False):
        original_new = app.view_functions['customer_new']

        def new_wrapper(*args, **kwargs):
            response = original_new(*args, **kwargs)
            if request.method == 'POST':
                name = (request.form.get('name') or '').strip()
                pppoe = (request.form.get('pppoe') or '').strip()
                c = pbr_client.base.db()
                try:
                    if pppoe:
                        r = c.execute('SELECT id FROM customers WHERE name=? AND pppoe=? ORDER BY id DESC LIMIT 1', (name, pppoe)).fetchone()
                    else:
                        phone = request.form.get('phone') or ''
                        r = c.execute('SELECT id FROM customers WHERE name=? AND COALESCE(phone,\'\')=? ORDER BY id DESC LIMIT 1', (name, phone)).fetchone()
                finally:
                    c.close()
                if r:
                    _sync_zone_id(r['id'])
            return response

        new_wrapper._interflash_zone_sync_patched = True
        app.view_functions['customer_new'] = new_wrapper
