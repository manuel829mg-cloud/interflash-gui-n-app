"""Bounded server-side checks for the Dominican TV catalog."""
import concurrent.futures
import hashlib
import ipaddress
import json
import socket
import threading
import time
import unicodedata
from urllib.parse import urlsplit, urljoin
import urllib.request
import urllib.error
from flask import jsonify


def public_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('unsupported')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('private address')
    return url


def sample(url, limit=65536):
    # Never retain a provider response or include its URL/credentials in status output.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for _ in range(4):
        public_url(url)
        req = urllib.request.Request(url, headers={'User-Agent': 'InterFlash-ChannelCheck/1.0'})
        try:
            with opener.open(req, timeout=7) as r:
                data = bytearray()
                deadline = time.monotonic() + 8
                while len(data) < limit and time.monotonic() < deadline:
                    chunk = r.read(min(4096,limit-len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                return 'ok', bytes(data), url
        except urllib.error.HTTPError as error:
            if error.code in (301,302,303,307,308):
                url = urljoin(url,error.headers.get('Location',''))
                error.close()
                continue
            code = error.code
            error.close()
            return ('unknown' if code in (401,403,429) else 'failed'), b'', url
    return 'unknown', b'', url


def media_bytes(data):
    # MPEG-TS, fragmented MP4, FLV or Matroska; this is a signal sample, not a TV playback test.
    return ((len(data) > 376 and any(data[i] == 71 and data[i+188] == 71 for i in range(min(188, len(data)-188))))
            or (len(data) > 16 and data[4:8] in (b'ftyp', b'styp', b'moof'))
            or data.startswith((b'FLV', b'\x1aE\xdf\xa3')))


def probe(url):
    try:
        for _ in range(4):
            state, data, final = sample(url)
            if state != 'ok':
                return state
            if data.lstrip().startswith(b'#EXTM3U'):
                text = data.decode('utf-8-sig', errors='replace')
                if '#EXT-X-KEY' in text and 'METHOD=NONE' not in text:
                    return 'unknown'
                targets = [x.strip() for x in text.splitlines() if x.strip() and not x.startswith('#')]
                if not targets:
                    return 'failed'
                url = urljoin(final, targets[-1] if '#EXTINF:' in text else targets[0])
                continue
            return 'ok' if media_bytes(data) else 'unknown'
        return 'unknown'
    except (TimeoutError, socket.timeout):
        return 'failed'
    except urllib.error.URLError:
        return 'failed'
    except Exception:
        return 'unknown'


def setup(app, host, db, entries, label):
    def catalog():
        result = []
        with db() as c:
            manual = c.execute('SELECT id,name,url_enc FROM tv_manual_channels ORDER BY number,name').fetchall()
            config = c.execute('SELECT source_enc FROM tv_native_settings WHERE id=1').fetchone()
            for row in manual:
                result.append((row['name'], host.dec(row['url_enc'])))
            source = host.dec(config['source_enc']) if config else ''
            content = ''
            if source.startswith('m3ufile:'):
                parts = source.split(':')
                row = c.execute('SELECT content_enc FROM tv_native_m3u_files WHERE id=?', (parts[1],)).fetchone()
                content = host.dec(row['content_enc']) if row else ''
        if source and not source.startswith('m3ufile:'):
            try:
                status, data, _ = sample(source, 8*1024*1024)
                if status != 'ok' or not data.lstrip().startswith(b'#EXTM3U'):
                    raise ValueError('catalog unavailable')
                content = data.decode('utf-8-sig')
            except Exception:
                raise ValueError('catalog unavailable') from None
        _, items = entries(content)
        for item in items:
            name, group = label(item)
            normalized = ''.join(c for c in unicodedata.normalize('NFD', group.lower()) if not unicodedata.combining(c))
            if 'dominican' in normalized:
                url = next((x.strip() for x in item[1:] if x.strip() and not x.startswith('#')), '')
                if url:
                    result.append((name, url))
        return {hashlib.sha256((name+'\0'+url).encode()).hexdigest(): (name,url) for name,url in result}

    def schema(c):
        c.execute('CREATE TABLE IF NOT EXISTS tv_channel_health (id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, failures INTEGER NOT NULL DEFAULT 0, checked INTEGER NOT NULL, changed INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS tv_channel_health_job (id INTEGER PRIMARY KEY, lease INTEGER NOT NULL)')
        c.commit()

    def cycle():
        now = int(time.time())
        with db() as c:
            schema(c)
            c.execute('INSERT OR IGNORE INTO tv_channel_health_job VALUES(1,0)')
            claimed = c.execute('UPDATE tv_channel_health_job SET lease=? WHERE id=1 AND lease<?', (now+1800,now)).rowcount
            c.commit()
        if not claimed:
            return
        try:
            channels = catalog()
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(probe,url): (key,name) for key,(name,url) in channels.items()}
                for future in concurrent.futures.as_completed(futures):
                    key,name = futures[future]
                    outcome = future.result()
                    checked = int(time.time())
                    with db() as c:
                        old = c.execute('SELECT * FROM tv_channel_health WHERE id=?',(key,)).fetchone()
                        failures = (old['failures'] if old else 0)+1 if outcome == 'failed' else 0
                        state = 'down' if failures >= 2 else 'checking' if outcome == 'failed' else outcome
                        changed = old['changed'] if old and old['state']==state else checked
                        c.execute('INSERT OR REPLACE INTO tv_channel_health VALUES(?,?,?,?,?,?)',(key,name,state,failures,checked,changed))
                        c.commit()
            with db() as c:
                for row in c.execute('SELECT id FROM tv_channel_health').fetchall():
                    if row['id'] not in channels:
                        c.execute('DELETE FROM tv_channel_health WHERE id=?',(row['id'],))
                c.commit()
        finally:
            with db() as c:
                c.execute('UPDATE tv_channel_health_job SET lease=? WHERE id=1',(int(time.time())+300,))
                c.commit()

    @app.get('/inter-tv/channel-health')
    def status():
        if not host.auth():
            return jsonify(error='authentication required'), 401
        with db() as c:
            schema(c)
            rows = [dict(r) for r in c.execute('SELECT id,name,state,checked,changed FROM tv_channel_health ORDER BY name')]
        # A stale result must never look like a current working signal.
        for row in rows:
            if int(time.time())-row['checked'] > 900:
                row['state'] = 'unknown'
        response = jsonify(channels=rows)
        response.headers['Cache-Control'] = 'no-store'
        return response

    def worker():
        while True:
            try:
                cycle()
            except Exception:
                app.logger.warning('TV channel checks unavailable; retrying later')
            time.sleep(60)
    # Start after the first real request, so gunicorn preload never loses the worker.
    lock = threading.Lock()
    started = [False]
    @app.before_request
    def start():
        with lock:
            if not started[0]:
                started[0] = True
                threading.Thread(target=worker, daemon=True, name='tv-channel-health').start()


def badge(name, url, group='Canales Dominicanos'):
    import html
    normalized = ''.join(c for c in unicodedata.normalize('NFD', group.lower()) if not unicodedata.combining(c))
    if 'dominican' not in normalized:
        return ''
    key = hashlib.sha256((name+'\\0'+url).encode()).hexdigest()
    return '<span class="tv-health-badge" data-health-id="'+html.escape(key)+'" style="font-size:12px;display:inline-block;margin-left:8px" aria-live="polite">⚪ Pendiente de revisión</span>'

PANEL = '''<div id="tv-health-alert" role="status" aria-live="polite"></div>
<script>(function(){async function refresh(){try{const r=await fetch('/inter-tv/channel-health',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();const byId=new Map(d.channels.map(c=>[c.id,c]));const labels={ok:'✅ Señal detectada',down:'❌ No responde',checking:'⏳ Confirmando fallo',unknown:'⚪ No comprobado'};document.querySelectorAll('.tv-health-badge').forEach(el=>{const c=byId.get(el.dataset.healthId);el.textContent=c?(labels[c.state]||labels.unknown)+' · '+new Date(c.checked*1000).toLocaleString('es-DO',{timeZone:'America/Santo_Domingo'}):'⚪ Pendiente de revisión';});const down=d.channels.filter(c=>c.state==='down');document.getElementById('tv-health-alert').textContent=down.length?'⚠ No responden: '+down.map(c=>c.name).join(', '):'';}catch(e){document.querySelectorAll('.tv-health-badge').forEach(el=>el.textContent='⚪ No se pudo actualizar el estado');}}if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',refresh);}else{refresh();}setInterval(refresh,30000);})();</script>'''
