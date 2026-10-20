"""Fail-closed PPPoE IPv4 assignment guard for the customer create/edit endpoints."""
import ipaddress
import re
import fcntl
import os
import tempfile
from datetime import datetime, timedelta
from functools import wraps
from flask import request, flash, redirect, url_for
from werkzeug.datastructures import ImmutableMultiDict
import app as base
import free_ip_picker

MAX_SYNC_AGE = timedelta(minutes=15)

def _automatic_address(data, customer=None):
    """Fill an empty address or preserve/re-evaluate an existing customer's IP."""
    import commercial_service as commercial
    import customer_provisioning
    router = (data.get('router_name') or 'CCR2116').strip()
    old_ip = commercial._value(customer, 'ip_address')
    supplied = (data.get('ip_address') or '').strip()
    # Explicit selection through the existing picker stays available.
    if supplied and supplied != old_ip:
        return data
    c = base.db()
    try:
        selected = data.get('mikrotik_profile') or ''
        plan_id = selected.split(':', 1)[1] if selected.startswith('plan:') else data.get('plan_id')
        catalog = customer_provisioning._commercial_profiles(c, router)
        if selected and not selected.startswith('plan:'):
            match = next((p for p in catalog if p['name'] == selected), None)
            if match and len(match['plan_ids']) == 1:
                plan_id = str(match['plan_ids'][0])
        plan_id = plan_id or commercial._value(customer, 'plan_id')
        line = data.get('pbr_line', commercial._value(customer, 'pbr_line'))
        same_router = router == (commercial._value(customer, 'router_name') or 'CCR2116')
        duplicate = c.execute('SELECT id FROM customers WHERE ip_address=? AND COALESCE(router_name,?)=? AND id<>? LIMIT 1',
                              (old_ip, router, router, commercial._value(customer, 'id', -1))).fetchone()
        if old_ip and same_router and not duplicate:
            unchanged = (str(plan_id) == str(commercial._value(customer, 'plan_id'))
                         and line == commercial._value(customer, 'pbr_line')
                         and selected in ('', 'plan:' + str(plan_id), commercial._value(customer, 'mikrotik_profile')))
            if unchanged:
                data['ip_address'] = old_ip
                return data
            try:
                commercial.resolve(c, plan_id, router, line, old_ip, customer)
                data['ip_address'] = old_ip
                return data
            except ValueError:
                pass
        if not plan_id:
            raise ValueError('Selecciona el plan de internet para asignar una IP automáticamente.')
        plan = c.execute('SELECT * FROM plans WHERE id=? AND active=1', (plan_id,)).fetchone()
        if not plan:
            raise ValueError('Selecciona un plan activo para asignar la IP.')
        expected = (float(plan['upload_mbps']) * 1000000, float(plan['download_mbps']) * 1000000)
        names = {p['name'] for p in catalog if str(plan_id) in {str(x) for x in p['plan_ids']}}
        profiles = [p for p in c.execute('SELECT * FROM push_ppp_profiles WHERE router_name=?', (router,))
                    if p['name'] in names and commercial._rate(p['rate_limit']) == expected]
        if selected and not selected.startswith('plan:'):
            profiles = [p for p in profiles if p['name'] == selected]
        else:
            mapped = c.execute("SELECT profile_name FROM plan_profile_map WHERE router_name=? AND plan_id=? AND pbr_line=?", (router, plan_id, line or '')).fetchone()
            if mapped and any(p['name'] == mapped['profile_name'] for p in profiles):
                profiles = [p for p in profiles if p['name'] == mapped['profile_name']]
        if not profiles:
            raise ValueError('No hay un perfil sincronizado compatible con el plan para asignar la IP.')
        pools = c.execute('SELECT * FROM mikrotik_ip_pools WHERE router_name=? ORDER BY name', (router,)).fetchall()
        occupied = {r['address'] for r in c.execute('SELECT address FROM mikrotik_ip_used WHERE router_name=?', (router,))}
        occupied.update(r['ip_address'] for r in c.execute("SELECT ip_address FROM customers WHERE COALESCE(router_name,'CCR2116')=? AND COALESCE(ip_address,'')<>''", (router,)))
        choices = []
        for pool in pools:
            matching = [p for p in profiles if p['remote_address'] == pool['name']]
            if not matching:
                continue
            for segment in pool['ranges'].split(','):
                for ip in free_ip_picker._expand_segment(segment):
                    if ip in occupied:
                        continue
                    # Reuse the existing freshness and duplicate checks.
                    error = _validate(router, ip, commercial._value(customer, 'id', None))
                    if error:
                        raise ValueError(error)
                    try:
                        commercial.resolve(c, plan_id, router, line, ip, customer)
                    except ValueError:
                        continue
                    choices.append((ip, pool['name'], {(p['remote_address'], p['local_address']) for p in matching}))
                    break
                if choices and choices[-1][1] == pool['name']:
                    break
        if not choices:
            raise ValueError('No hay IP libres verificadas compatibles con este plan. Actualiza los pools del MikroTik.')
        if len({pair for choice in choices for pair in choice[2]}) != 1:
            raise ValueError('El plan tiene varios pools de instalación. Selecciona una IP del pool correcto en Ver IPs libres.')
        data['ip_address'] = min(choices, key=lambda choice: int(ipaddress.ip_address(choice[0])))[0]
        return data
    finally:
        c.close()

def _ipv4(value):
    try:
        address = ipaddress.ip_address(str(value or '').strip())
        return str(address) if address.version == 4 else ''
    except ValueError:
        return ''

def _validate(router, ip, customer_id=None):
    if not ip:
        return None  # IP opcional: el router puede asignarla dinamicamente si no hay PBR.
    if not _ipv4(ip):
        return 'La IP remota no es una dirección IPv4 válida.'
    free_ip_picker.ensure_schema()
    c = base.db()
    try:
        pools = c.execute('SELECT ranges,updated_at FROM mikrotik_ip_pools WHERE router_name=?', (router,)).fetchall()
        if not pools:
            return 'No hay pools sincronizados del MikroTik. Actualiza Ver IPs libres antes de guardar.'
        latest = max((p['updated_at'] or '' for p in pools), default='')
        try:
            updated = datetime.fromisoformat(latest)
            if datetime.now() - updated > MAX_SYNC_AGE or updated > datetime.now() + timedelta(minutes=2):
                return 'La lectura de IPs del MikroTik está desactualizada. Sincroniza nuevamente antes de guardar.'
        except (ValueError, TypeError):
            return 'No se pudo verificar la fecha de sincronización de IPs.'
        occupancy = c.execute('SELECT MAX(updated_at) latest, COUNT(*) total FROM mikrotik_ip_used WHERE router_name=?', (router,)).fetchone()
        if not occupancy or not occupancy['total'] or not occupancy['latest']:
            return 'No hay datos de IP ocupadas del MikroTik. Sincroniza antes de guardar.'
        try:
            occupied_at = datetime.fromisoformat(occupancy['latest'])
            if datetime.now() - occupied_at > MAX_SYNC_AGE or occupied_at > datetime.now() + timedelta(minutes=2):
                return 'Las IP ocupadas están desactualizadas. Sincroniza antes de guardar.'
        except (ValueError, TypeError):
            return 'No se pudo verificar la fecha de las IP ocupadas.'
        # A static PPPoE IP must not overlap any dynamic pool unless the
        # network operator has explicitly excluded/reserved it there.
        # The picker already offers pool addresses; check occupancy in both sources.
        if not any(ip in free_ip_picker._expand_segment(segment)
                   for pool in pools for segment in str(pool['ranges']).split(',')):
            return 'La IP no pertenece a los pools sincronizados de este router.'
        row = c.execute('SELECT id FROM customers WHERE ip_address=? AND COALESCE(router_name,?)=? AND id<>? LIMIT 1',
                        (ip, router, router, customer_id or -1)).fetchone()
        if row:
            return 'IP duplicada: ya está asignada a otro cliente de Inter Flash.'
        # Snapshot contains active sessions and static PPP secrets. On edit,
        # allow the existing IP to remain unchanged; otherwise fail closed.
        used = c.execute('SELECT source FROM mikrotik_ip_used WHERE router_name=? AND address=? LIMIT 1',
                         (router, ip)).fetchone()
        if used:
            return 'IP ocupada en MikroTik (PPPoE configurado o sesión activa). Elige otra.'
        return None
    finally:
        c.close()

def setup(app):
    for endpoint in ('customer_new', 'customer_edit'):
        original = app.view_functions.get(endpoint)
        if not original:
            continue
        def guarded(*args, _original=original, _endpoint=endpoint, **kwargs):
            if request.method != 'POST' or not base.logged_in():
                return _original(*args, **kwargs)
            router = (request.form.get('router_name') or 'CCR2116').strip()
            ip = (request.form.get('ip_address') or '').strip()
            cid = kwargs.get('id') if _endpoint == 'customer_edit' else None
            # Editing unchanged IP must remain possible even if it is
            # already reflected in MikroTik's secrets or active sessions.
            if cid:
                c = base.db()
                try:
                    existing = c.execute('SELECT ip_address,router_name FROM customers WHERE id=?', (cid,)).fetchone()
                finally:
                    c.close()
                if existing and ip and ip == (existing['ip_address'] or '') and router == (existing['router_name'] or 'CCR2116'):
                    c = base.db()
                    try:
                        duplicate = c.execute('SELECT id FROM customers WHERE ip_address=? AND COALESCE(router_name,?)=? AND id<>? LIMIT 1', (ip, router, router, cid)).fetchone()
                    finally:
                        c.close()
                    if duplicate:
                        flash('IP duplicada: ya pertenece a otro cliente de Inter Flash.')
                        return redirect(url_for('customer_edit', id=cid)), 409
                    return _original(*args, **kwargs)
            pbr = (request.form.get('pbr_line') or '').strip()
            if pbr and not ip:
                flash('Selecciona una IP libre para aplicar PBR.')
                return redirect(url_for('customer_edit', id=cid) if cid else url_for('customer_new')), 409
            error = _validate(router, ip, cid)
            if error:
                flash(error)
                return redirect(url_for('customer_edit', id=cid) if cid else url_for('customer_new')), 409
            return _original(*args, **kwargs)
        app.view_functions[endpoint] = guarded

    # Serialize allocation through the customer + command commit across gunicorn
    # workers. The next save sees the first save's customer as occupied.
    for endpoint in ('customer_new', 'customer_edit'):
        original = app.view_functions.get(endpoint)
        if not original:
            continue
        def automatic(*args, _original=original, _endpoint=endpoint, **kwargs):
            if request.method != 'POST' or not base.logged_in():
                return _original(*args, **kwargs)
            cid = kwargs.get('id') if _endpoint == 'customer_edit' else None
            lock_path = os.path.join(tempfile.gettempdir(), 'interflash-ip-allocation.lock')
            with open(lock_path, 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                old_form = request.form
                try:
                    customer = None
                    if cid:
                        c = base.db()
                        try:
                            customer = c.execute('SELECT * FROM customers WHERE id=?', (cid,)).fetchone()
                        finally:
                            c.close()
                    request.form = ImmutableMultiDict(_automatic_address(old_form.copy(), customer))
                    return _original(*args, **kwargs)
                except ValueError as error:
                    flash(str(error))
                    return redirect(url_for('customer_edit', id=cid) if cid else url_for('customer_new')), 409
                finally:
                    request.form = old_form
                    fcntl.flock(lock, fcntl.LOCK_UN)
        app.view_functions[endpoint] = automatic

    import pbr_client
    original_form = pbr_client.customer_form
    def automatic_form(row=None):
        html = original_form(row)
        html = re.sub(
            r'(<button\b[^>]*onclick="IFIP.open\(\)"[^>]*>.*?</button>)',
            lambda match: (
                '<details class="if-ip-advanced" style="margin-top:6px">'
                '<summary style="cursor:pointer;padding:10px 0">Opciones avanzadas</summary>'
                '<div style="padding:6px 0">' + match.group(1) + '</div></details>'
            ),
            html, count=1, flags=re.S,
        )
        return html.replace('IP remota (opcional)', 'IP remota (automática)').replace(
            'Consulta los pools del MikroTik y selecciona una IP disponible.',
            'Deja el campo vacío: se asigna una IP libre compatible al guardar. Al editar, se conserva la IP válida. La selección manual está en Opciones avanzadas.')
    pbr_client.customer_form = automatic_form

