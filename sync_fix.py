from datetime import datetime
from flask import request, jsonify
from app import con
from push_agent import _authorized, _safe, _touch_agent


def sync_compat():
    if not _authorized():
        return jsonify(ok=False, error='unauthorized'), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raw = request.get_data(as_text=True)[:500]
        print('MIKROTIK_SYNC_SKIPPED invalid-json:', raw, flush=True)
        return jsonify(ok=True, skipped=True, reason='invalid-json'), 200

    name = _safe(payload.get('router') or 'CCR2116', 80).strip()
    kind = _safe(payload.get('kind') or '', 20).lower()
    items = payload.get('items')
    if items is None:
        items = []

    # RouterOS may serialize a one-row slice as an object instead of an array.
    if isinstance(items, dict):
        items = [items]
    elif not isinstance(items, list):
        print('MIKROTIK_SYNC_SKIPPED invalid-items kind=', kind, 'type=', type(items).__name__, flush=True)
        return jsonify(ok=True, skipped=True, reason='invalid-items', kind=kind), 200

    c = con()
    try:
        if kind == 'start':
            c.execute('DELETE FROM router_pppoe_secrets WHERE router_name=?', (name,))
            c.execute('DELETE FROM router_pppoe_active WHERE router_name=?', (name,))
            c.execute('DELETE FROM router_ppp_profiles WHERE router_name=?', (name,))
            _touch_agent(c, name, _safe(payload.get('identity') or name, 80), _safe(payload.get('version') or '', 80), 'SYNCING')

        elif kind == 'secrets':
            for x in items:
                if not isinstance(x, dict):
                    continue
                c.execute('''INSERT INTO router_pppoe_secrets
                    (router_name,name,profile,service,remote_address,caller_id,disabled,comment)
                    VALUES(?,?,?,?,?,?,?,?)''', (
                    name, _safe(x.get('name')), _safe(x.get('profile')), _safe(x.get('service')),
                    _safe(x.get('remote-address')), _safe(x.get('caller-id')), _safe(x.get('disabled'), 20),
                    _safe(x.get('comment'), 500)
                ))
            _touch_agent(c, name, status='SYNCING')

        elif kind == 'active':
            for x in items:
                if not isinstance(x, dict):
                    continue
                c.execute('''INSERT INTO router_pppoe_active
                    (router_name,name,address,caller_id,service,uptime)
                    VALUES(?,?,?,?,?,?)''', (
                    name, _safe(x.get('name')), _safe(x.get('address')), _safe(x.get('caller-id')),
                    _safe(x.get('service')), _safe(x.get('uptime'))
                ))
            _touch_agent(c, name, status='SYNCING')

        elif kind == 'profiles':
            for x in items:
                if not isinstance(x, dict):
                    continue
                c.execute('''INSERT INTO router_ppp_profiles
                    (router_name,name,remote_address,local_address,rate_limit,comment)
                    VALUES(?,?,?,?,?,?)''', (
                    name, _safe(x.get('name')), _safe(x.get('remote-address')), _safe(x.get('local-address')),
                    _safe(x.get('rate-limit')), _safe(x.get('comment'), 500)
                ))
            _touch_agent(c, name, status='SYNCING')

        elif kind == 'finish':
            secrets = c.execute('SELECT count(*) c FROM router_pppoe_secrets WHERE router_name=?', (name,)).fetchone()['c']
            active = c.execute('SELECT count(*) c FROM router_pppoe_active WHERE router_name=?', (name,)).fetchone()['c']
            profiles = c.execute('SELECT count(*) c FROM router_ppp_profiles WHERE router_name=?', (name,)).fetchone()['c']
            now = datetime.now().isoformat(timespec='seconds')
            _touch_agent(c, name, _safe(payload.get('identity') or name, 80), _safe(payload.get('version') or '', 80), 'ONLINE')
            c.execute('''UPDATE router_agents
                         SET last_sync=?,pppoe_secrets=?,pppoe_active=?,ppp_profiles=?
                         WHERE name=?''', (now, secrets, active, profiles, name))
        else:
            print('MIKROTIK_SYNC_SKIPPED unknown-kind:', kind, flush=True)
            return jsonify(ok=True, skipped=True, reason='unknown-kind', kind=kind), 200

        c.commit()
    finally:
        c.close()

    return jsonify(ok=True, kind=kind, received=len(items))


def setup(app):
    app.view_functions['mikrotik_sync'] = sync_compat
