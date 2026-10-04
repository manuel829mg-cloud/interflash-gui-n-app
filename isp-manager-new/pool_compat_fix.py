import json
from datetime import datetime
from flask import request, jsonify
import app as base
import pbr_client
import free_ip_picker


def _decode_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except Exception:
            pass
    return []


def _recover_legacy_body(raw):
    """Recover the old RouterOS body where JSON arrays were inserted inside quoted fields."""
    raw = (raw or '').strip()
    prefix = '{"router":"'
    if not raw.startswith(prefix):
        return None
    body = raw[len(prefix):]
    try:
        router, body = body.split('","pools":"', 1)
        pools_raw, body = body.split('","secrets":"', 1)
        secrets_raw, body = body.split('","active":"', 1)
        if body.endswith('"}'):
            active_raw = body[:-2]
        else:
            active_raw = body
        return {
            'router': router,
            'pools': _decode_list(pools_raw),
            'secrets': _decode_list(secrets_raw),
            'active': _decode_list(active_raw),
        }
    except Exception:
        return None


def pool_state_sync_compat():
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401

    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        router = str(payload.get('router') or 'CCR2116')[:80]
        pools = _decode_list(payload.get('pools'))
        secrets = _decode_list(payload.get('secrets'))
        active = _decode_list(payload.get('active'))
    else:
        recovered = _recover_legacy_body(request.get_data(as_text=True))
        if recovered is None:
            return jsonify(ok=False, error='invalid-payload'), 400
        router = str(recovered.get('router') or 'CCR2116')[:80]
        pools = recovered['pools']
        secrets = recovered['secrets']
        active = recovered['active']

    # Do not erase a good previous reading if a broken/empty legacy request arrives.
    if not pools:
        c = base.db()
        current = c.execute('SELECT COUNT(*) c FROM mikrotik_ip_pools WHERE router_name=?', (router,)).fetchone()['c']
        c.close()
        return jsonify(ok=True, router=router, pools=current, used=0, ignored_empty=True)

    now = datetime.now().isoformat(timespec='seconds')
    c = base.db()
    try:
        c.execute('DELETE FROM mikrotik_ip_pools WHERE router_name=?', (router,))
        c.execute('DELETE FROM mikrotik_ip_used WHERE router_name=?', (router,))

        saved_pools = 0
        for item in pools:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()[:160]
            ranges = str(item.get('ranges') or '').strip()[:2000]
            if not name or not ranges:
                continue
            c.execute(
                'INSERT OR REPLACE INTO mikrotik_ip_pools(router_name,name,ranges,updated_at) VALUES(?,?,?,?)',
                (router, name, ranges, now)
            )
            saved_pools += 1

        saved_used = 0
        for source, items, key in (('SECRET', secrets, 'remote-address'), ('ACTIVE', active, 'address')):
            for item in items:
                value = item.get(key) if isinstance(item, dict) else item
                value = str(value or '').strip()
                if not free_ip_picker._is_ip(value):
                    continue
                c.execute(
                    'INSERT OR IGNORE INTO mikrotik_ip_used(router_name,address,source,updated_at) VALUES(?,?,?,?)',
                    (router, value, source, now)
                )
                saved_used += 1

        c.commit()
        print(f'INTERFLASH_POOL_COMPAT router={router} pools={saved_pools} used={saved_used}', flush=True)
        return jsonify(ok=True, router=router, pools=saved_pools, used=saved_used, updated_at=now, compatibility='legacy')
    finally:
        c.close()


def setup(app):
    # free_ip_picker already registered this endpoint; replace only its view function.
    app.view_functions['mikrotik_pool_state_sync'] = pool_state_sync_compat
