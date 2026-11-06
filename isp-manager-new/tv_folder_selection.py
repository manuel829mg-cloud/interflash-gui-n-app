"""Non-destructive category selection for the currently configured provider playlist."""
import gzip
import hashlib
import hmac
import json
import re
import unicodedata
import time
from collections import Counter
from urllib.request import Request, urlopen
from flask import request, redirect

MAX_BYTES = 32 * 1024 * 1024


def setup(app, host, db, entries, label, csrf, valid_csrf, today, manual_info):
    def schema(c):
        c.execute('''CREATE TABLE IF NOT EXISTS tv_folder_catalog (
            source_id TEXT PRIMARY KEY, content_enc TEXT NOT NULL,
            selected_json TEXT, updated INTEGER NOT NULL)''')

    def source(c):
        row = c.execute('SELECT source_enc FROM tv_native_settings WHERE id=1').fetchone()
        raw = host.dec(row['source_enc']) if row else ''
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    def catalog(c, sid):
        schema(c)
        return c.execute('SELECT * FROM tv_folder_catalog WHERE source_id=?', (sid,)).fetchone()

    def group(item):
        return label(item)[1] or 'Sin carpeta'

    def category_key(name):
        value = unicodedata.normalize('NFKD', name.casefold())
        return ' '.join(''.join(ch if ch.isalnum() else ' ' for ch in value
                                if not unicodedata.combining(ch)).split())

    def merged_items(content):
        preamble, items = entries(content)
        # Share the existing manual-channel category, not the provider's RD category.
        target = 'Canales Dominicanos'
        result = []
        cultural_number = 50
        for item in items:
            if category_key(group(item)) in ('cultural', 'culturales'):
                item = list(item)
                item[0] = re.sub(r'group-title="[^"]*"',
                                 lambda _: 'group-title="'+target+'"', item[0])
                item[0] = re.sub(r'\s+tvg-chno="[^"]*"', '', item[0])
                item[0] = item[0].replace('#EXTINF:-1', '#EXTINF:-1 tvg-chno="'+str(cultural_number)+'"', 1)
                cultural_number += 1
            result.append(item)
        return preamble, result, target

    def selected_groups(row, content):
        if row['selected_json'] is None:
            return set(counts(content))
        target = merged_items(content)[2]
        return {target if category_key(name) in ('cultural', 'culturales') else name
                for name in json.loads(row['selected_json'])}

    def counts(content):
        return Counter(group(item) for item in merged_items(content)[1])

    def download(raw, c):
        if raw.startswith('m3ufile:'):
            _, fid, _ = raw.split(':', 2)
            row = c.execute('SELECT content_enc FROM tv_native_m3u_files WHERE id=?', (fid,)).fetchone()
            if not row:
                raise ValueError('No se encontró el archivo guardado.')
            return host.dec(row['content_enc'])
        if not raw.startswith(('http://', 'https://')):
            raise ValueError('Primero guarda el enlace M3U del proveedor.')
        # Use the complete original M3U, including every group, not only live Xtream categories.
        with urlopen(Request(raw, headers={'User-Agent': 'InterFlashTV/1.0'}), timeout=18) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('La lista supera el tamaño permitido de 32 MB.')
        content = data.decode('utf-8-sig', errors='replace')
        if not content.lstrip().startswith('#EXTM3U') or not entries(content)[1]:
            raise ValueError('El proveedor no entregó una lista M3U con canales.')
        return content

    @app.route('/inter-tv/folders', methods=['GET', 'POST'])
    def tv_folders():
        if not host.auth():
            return redirect('/login')
        message = ''
        with db() as c:
            raw, sid = source(c)
            row = catalog(c, sid)
            if request.method == 'POST':
                if not valid_csrf():
                    return 'Recarga la página e inténtalo de nuevo.', 403
                if request.form.get('source_id') != sid:
                    return 'La fuente cambió. Recarga antes de guardar.', 409
                action = request.form.get('action')
                if action == 'refresh':
                    try:
                        content = download(raw, c)
                        groups = counts(content)
                        selected = None
                        if row and row['selected_json'] is not None:
                            # Newly discovered groups start hidden once a selection exists.
                            selected = [x for x in selected_groups(row, content) if x in groups]
                        c.execute('''INSERT INTO tv_folder_catalog VALUES(?,?,?,?)
                            ON CONFLICT(source_id) DO UPDATE SET content_enc=excluded.content_enc,
                            selected_json=excluded.selected_json,updated=excluded.updated''',
                            (sid, host.enc(content), json.dumps(selected) if selected is not None else None, time.time_ns()))
                        if selected is not None:
                            c.execute('UPDATE tv_native_settings SET revision=revision+1 WHERE id=1')
                        c.commit()
                        row = catalog(c, sid)
                        message = 'Carpetas actualizadas. Marca cuáles quieres mostrar y guarda.'
                    except Exception:
                        message = 'No pude leer la lista completa del proveedor. La selección anterior se conserva; puedes volver a intentar.'
                elif action == 'save' and row:
                    if request.form.get('catalog_version') != str(row['updated']):
                        return 'La lista se actualizó. Recarga antes de guardar.', 409
                    groups = counts(host.dec(row['content_enc']))
                    selected = sorted(set(request.form.getlist('folder')) & set(groups))
                    c.execute('UPDATE tv_folder_catalog SET selected_json=? WHERE source_id=?', (json.dumps(selected), sid))
                    c.execute('UPDATE tv_native_settings SET revision=revision+1 WHERE id=1')
                    c.commit()
                    row = catalog(c, sid)
                    message = 'Selección guardada. La app recibirá estas carpetas al sincronizar o volver a abrir.'
            token = host.e(csrf())
            hidden = '<input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="source_id" value="'+sid+'">'
            body = '<div class="head"><h1>Carpetas de la lista</h1></div><a class="btn" href="/inter-tv">Volver a Inter Flash TV</a>'
            if message:
                body += '<div class="notice">'+host.e(message)+'</div>'
            body += '<div class="panel"><p>Elige qué carpetas de la lista del proveedor aparecen en la aplicación. Las desmarcadas se conservan aquí para reactivarlas. Los canales añadidos manualmente se gestionan por separado.</p><form method="post">'+hidden+'<input type="hidden" name="action" value="refresh"><button class="btn blue">Cargar / actualizar todas las carpetas</button></form></div>'
            if row:
                groups = counts(host.dec(row['content_enc']))
                selected = selected_groups(row, host.dec(row['content_enc']))
                body += '<div class="panel"><h2>'+str(len(groups))+' carpetas · '+str(sum(groups.values()))+' entradas</h2><input id="folder-search" type="search" placeholder="Buscar carpeta" style="width:100%;padding:10px"><p><button type="button" class="btn small" onclick="markFolders(true)">Marcar todas</button> <button type="button" class="btn small" onclick="markFolders(false)">Desmarcar todas</button></p><form method="post">'+hidden+'<input type="hidden" name="action" value="save"><input type="hidden" name="catalog_version" value="'+str(row['updated'])+'"><div style="max-height:60vh;overflow:auto">'
                for name, total in sorted(groups.items(), key=lambda x: x[0].casefold()):
                    checked = ' checked' if name in selected else ''
                    body += '<label class="tv-folder" data-name="'+host.e(name.lower())+'" style="display:flex;gap:10px;padding:10px;border-bottom:1px solid #354b64"><input type="checkbox" name="folder" value="'+host.e(name)+'"'+checked+'><span>'+host.e(name)+'</span><small>'+str(total)+'</small></label>'
                body += '</div><button class="btn green" style="margin-top:12px">Guardar carpetas para la aplicación</button></form></div><script>function markFolders(v){document.querySelectorAll(".tv-folder input").forEach(x=>x.checked=v)}document.getElementById("folder-search").addEventListener("input",function(){const q=this.value.toLowerCase();document.querySelectorAll(".tv-folder").forEach(x=>x.style.display=x.dataset.name.includes(q)?"flex":"none")})</script>'
            else:
                body += '<div class="panel">Pulsa Cargar / actualizar todas las carpetas para leer la lista completa. Esto no cambia los canales de la aplicación.</div>'
            c.commit()
        response = app.make_response(host.shell('Carpetas de TV', body, 'inter_tv'))
        response.headers['Cache-Control'] = 'no-store'
        return response

    def apply_selection(payload, digest):
        with db() as c:
            _, sid = source(c)
            row = catalog(c, sid)
            c.commit()
        if row and row['selected_json'] is not None:
            sig = hmac.new(host.PASSWORD.encode(), ('folders:'+digest+':'+sid).encode(), hashlib.sha256).hexdigest()
            for key in ('server', 'username', 'password', 'url', 'manual_url', 'manual_revision'):
                payload.pop(key, None)
            payload.update(kind='m3u', url=request.url_root.rstrip('/')+'/api/tv-native/folders/'+digest+'/'+sid+'/'+sig+'.m3u?v=5')
            payload['revision'] = payload.get('revision', 0) + 4
        return payload

    @app.get('/api/tv-native/folders/<digest>/<sid>/<signature>.m3u')
    def tv_folder_playlist(digest, sid, signature):
        expected = hmac.new(host.PASSWORD.encode(), ('folders:'+digest+':'+sid).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return 'No autorizado', 404
        with db() as c:
            device = c.execute('SELECT approved FROM tv_native_devices WHERE token_hash=?', (digest,)).fetchone()
            if not device or device['approved'] != 1:
                return 'No autorizado', 403
            paid = c.execute('SELECT paid_until FROM tv_monthly_accounts WHERE token_hash=?', (digest,)).fetchone()
            trial = c.execute('SELECT expires_at FROM tv_trial_uses WHERE token_hash=?', (digest,)).fetchone()
            if (paid and paid['paid_until'] <= today().isoformat()) or (not paid and trial and trial['expires_at'] <= int(time.time())):
                return 'Suscripción vencida', 403
            _, current_sid = source(c)
            row = catalog(c, sid) if current_sid == sid else None
            if not row or row['selected_json'] is None:
                return 'Lista no disponible; sincroniza la aplicación.', 409
            content = host.dec(row['content_enc'])
            selected = selected_groups(row, content)
            manual = c.execute('SELECT number,name,url_enc FROM tv_manual_channels ORDER BY number,name').fetchall()
            epg = c.execute('SELECT url_enc FROM tv_native_epg_settings WHERE id=1').fetchone()
        preamble, items, _ = merged_items(content)
        lines = preamble or ['#EXTM3U']
        if epg and host.dec(epg['url_enc']):
            header = re.sub(r'\s+(?:url-tvg|x-tvg-url)="[^"]*"', '', lines[0], flags=re.IGNORECASE)
            lines[0] = header + ' url-tvg="' + host.dec(epg['url_enc']) + '"'
        # Deliver manual and provider channels in one playlist so the app groups them together.
        for channel in manual:
            lines.extend([manual_info(channel), host.dec(channel['url_enc'])])
        for item in items:
            if group(item) in selected:
                lines.extend(item)
        response = app.make_response(gzip.compress(('\n'.join(lines)+'\n').encode(), compresslevel=6))
        response.headers.update({'Content-Type': 'application/vnd.apple.mpegurl; charset=utf-8', 'Content-Encoding': 'gzip', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
        return response

    return apply_selection
