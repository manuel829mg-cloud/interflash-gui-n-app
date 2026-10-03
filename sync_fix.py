import os
import json
import time
import threading
import urllib.request
from datetime import datetime
from flask import request, jsonify
from app import con
from push_agent import _authorized, _safe, _touch_agent

RELAY_URL = 'https://interflash-isp-manager.up.railway.app/api/mikrotik/relay-sync'
RELAY_TOKEN = os.getenv('MIKROTIK_RELAY_TOKEN','')


def _relay(payload):
    if not RELAY_TOKEN:
        return
    try:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            RELAY_URL,
            data=data,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'X-InterFlash-Relay': RELAY_TOKEN,
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read(64)
    except Exception as ex:
        print('MIKROTIK_RELAY_ERROR:', str(ex)[:300], flush=True)


def _chunks(items, size=50):
    for i in range(0, len(items), size):
        yield items[i:i+size]


def _relay_current_snapshot():
    # Give the worker a moment to finish booting, then copy the already-stored
    # read-only MikroTik snapshot to the new ISP Manager.
    time.sleep(3)
    try:
        c = con()
        agent = c.execute('SELECT * FROM router_agents ORDER BY id DESC LIMIT 1').fetchone()
        if not agent:
            c.close()
            return
        name = agent['name'] or 'CCR2116'
        secrets = [dict(r) for r in c.execute('SELECT * FROM router_pppoe_secrets WHERE router_name=? ORDER BY id',(name,)).fetchall()]
        active = [dict(r) for r in c.execute('SELECT * FROM router_pppoe_active WHERE router_name=? ORDER BY id',(name,)).fetchall()]
        profiles = [dict(r) for r in c.execute('SELECT * FROM router_ppp_profiles WHERE router_name=? ORDER BY id',(name,)).fetchall()]
        c.close()

        _relay({'router':name,'kind':'start','items':[],'identity':agent['identity'] or name,'version':agent['ros_version'] or ''})
        for batch in _chunks(secrets):
            _relay({'router':name,'kind':'secrets','items':[{
                'name':x.get('name',''),'profile':x.get('profile',''),'service':x.get('service',''),
                'remote-address':x.get('remote_address',''),'caller-id':x.get('caller_id',''),
                'disabled':x.get('disabled',''),'comment':x.get('comment','')
            } for x in batch]})
        for batch in _chunks(active):
            _relay({'router':name,'kind':'active','items':[{
                'name':x.get('name',''),'address':x.get('address',''),'caller-id':x.get('caller_id',''),
                'service':x.get('service',''),'uptime':x.get('uptime','')
            } for x in batch]})
        for batch in _chunks(profiles):
            _relay({'router':name,'kind':'profiles','items':[{
                'name':x.get('name',''),'remote-address':x.get('remote_address',''),
                'local-address':x.get('local_address',''),'rate-limit':x.get('rate_limit',''),
                'comment':x.get('comment','')
            } for x in batch]})
        _relay({'router':name,'kind':'finish','items':[],'identity':agent['identity'] or name,'version':agent['ros_version'] or ''})
        print(f'MIKROTIK_RELAY_SNAPSHOT sent {name}: {len(active)}/{len(secrets)} PPPoE', flush=True)
    except Exception as ex:
        print('MIKROTIK_RELAY_SNAPSHOT_ERROR:', str(ex)[:300], flush=True)


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

    # Forward a copy to the new ISP Manager. Failure here never breaks the existing page.
    _relay(payload)
    return jsonify(ok=True, kind=kind, received=len(items))


def setup(app):
    app.view_functions['mikrotik_sync'] = sync_compat
    threading.Thread(target=_relay_current_snapshot, daemon=True).start()
