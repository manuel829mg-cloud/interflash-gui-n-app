import json
import re
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


def _objects_from_raw(raw):
    """Best-effort parser for RouterOS legacy bodies that are not valid JSON."""
    text = (raw or '').strip().replace('\\"', '"')
    pools = []
    secrets = []
    active = []

    # RouterOS serializes each row as a flat object. Parse each flat object
    # independently, so a malformed outer JSON wrapper does not matter.
    field_re = r'"([^"\\]+)"\s*:\s*(?:"((?:\\.|[^"\\])*)"|([^,}\]]+))'
    for obj in re.findall(r'\{[^{}]*\}', text):
        fields = {}
        for key, quoted, bare in re.findall(field_re, obj):
            v = quoted if quoted != '' else bare
            fields[key] = str(v or '').replace('\\"', '"').strip().strip('"')

        name = fields.get('name', '')
        ranges = fields.get('ranges', '')
        if name and ranges:
            pools.append({'name': name, 'ranges': ranges})

        remote = fields.get('remote-address', '')
        if remote:
            secrets.append({'remote-address': remote})

        addr = fields.get('address', '')
        if addr:
            active.append({'address': addr})

    # Fallback regexes for bodies where braces/quoting are damaged.
    if not pools:
        names = re.findall(r'"name"\s*:\s*"([^"]+)"', text)
        ranges = re.findall(r'"ranges"\s*:\s*"([^"]+)"', text)
        pools = [{'name': n, 'ranges': r} for n, r in zip(names, ranges) if n and r]
    if not secrets:
        secrets = [{'remote-address': x} for x in re.findall(r'"remote-address"\s*:\s*"([^"]+)"', text)]
    if not active:
        active = [{'address': x} for x in re.findall(r'"address"\s*:\s*"([^"]+)"', text)]

    router_m = re.search(r'"router"\s*:\s*"([^"]+)"', text)
    return {
        'router': router_m.group(1) if router_m else 'CCR2116',
        'pools': pools,
        'secrets': secrets,
        'active': active,
    }


def _recover_legacy_body(raw):
    raw = (raw or '').strip()
    if not raw:
        return None

    # First try the exact old quoted-field wrapper.
    prefix = '{"router":"'
    if raw.startswith(prefix):
        body = raw[len(prefix):]
        try:
            router, body = body.split('\",\"pools\":\"', 1)
            pools_raw, body = body.split('\",\"secrets\":\"', 1)
            secrets_raw, body = body.split('\",\"active\":\"', 1)
            active_raw = body[:-2] if body.endswith('\"}') else body
            recovered = {
                'router': router,
                'pools': _decode_list(pools_raw),
                'secrets': _decode_list(secrets_raw),
                'active': _decode_list(active_raw),
            }
            if recovered['pools']:
                return recovered
        except Exception:
            pass

    # Then parse the malformed raw RouterOS payload directly.
    recovered = _objects_from_raw(raw)
    if recovered['pools'] or recovered['secrets'] or recovered['active']:
        return recovered
    return None


def pool_state_sync_compat():
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401

    raw = request.get_data(as_text=True)
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        router = str(payload.get('router') or 'CCR2116')[:80]
        pools = _decode_list(payload.get('pools'))
        secrets = _decode_list(payload.get('secrets'))
        active = _decode_list(payload.get('active'))
        # Some old RouterOS payloads decode as a dict but contain broken string fields.
        if not pools:
            recovered = _recover_legacy_body(raw)
            if recovered:
                router = str(recovered.get('router') or router)[:80]
                pools = recovered['pools']
                secrets = recovered['secrets']
                active = recovered['active']
    else:
        recovered = _recover_legacy_body(raw)
        if recovered is None:
            # Keep endpoint non-destructive and log only structure, never the token header.
            print('INTERFLASH_POOL_COMPAT invalid legacy payload len=' + str(len(raw)), flush=True)
            return jsonify(ok=False, error='invalid-payload'), 400
        router = str(recovered.get('router') or 'CCR2116')[:80]
        pools = recovered['pools']
        secrets = recovered['secrets']
        active = recovered['active']

    # Never erase a good previous reading if a broken/empty legacy request arrives.
    if not pools:
        c = base.db()
        current = c.execute('SELECT COUNT(*) c FROM mikrotik_ip_pools WHERE router_name=?', (router,)).fetchone()['c']
        c.close()
        print(f'INTERFLASH_POOL_COMPAT empty router={router} existing={current}', flush=True)
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
    app.view_functions['mikrotik_pool_state_sync'] = pool_state_sync_compat