"""Fail-closed PPPoE IPv4 assignment guard for the customer create/edit endpoints."""
import ipaddress
from datetime import datetime, timedelta
from functools import wraps
from flask import request, flash, redirect, url_for
import app as base
import free_ip_picker

MAX_SYNC_AGE = timedelta(minutes=15)

def _ipv4(value):
    try:
        address = ipaddress.ip_address(str(value or '').strip())
        return str(address) if address.version == 4 else ''
    except ValueError:
        return ''

def _validate(router, ip, customer_id=None):
    if not ip:
        return 'Selecciona una IP libre antes de guardar el cliente.'
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
                        duplicate = c.execute('SELECT id FROM customers WHERE ip_address=? AND COALESCE(router_name,?)=? AND id<>? LIMIT 1', (ip, router, cid)).fetchone()
                    finally:
                        c.close()
                    if duplicate:
                        flash('IP duplicada: ya pertenece a otro cliente de Inter Flash.')
                        return redirect(url_for('customer_edit', id=cid)), 409
                    return _original(*args, **kwargs)
            error = _validate(router, ip, cid)
            if error:
                flash(error)
                return redirect(url_for('customer_edit', id=cid) if cid else url_for('customer_new')), 409
            return _original(*args, **kwargs)
        app.view_functions[endpoint] = guarded
