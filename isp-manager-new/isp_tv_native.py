"""Private TV source management and approval of individual native installations."""
import gzip
import calendar
from datetime import date
from zoneinfo import ZoneInfo
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, parse_qs
from flask import request, session, redirect, jsonify

def setup(app):
    if app.extensions.get('inter_tv_native'):
        return
    app.extensions['inter_tv_native'] = True
    import app as base
    import types, html, base64
    from cryptography.fernet import Fernet
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(base.SECRET_KEY.encode()).digest()))
    host = types.SimpleNamespace(con=base.db, auth=base.logged_in,
        PASSWORD=base.ADMIN_PASSWORD, shell=base.shell,
        e=lambda value: html.escape(str(value)),
        enc=lambda value: cipher.encrypt(value.encode()).decode(),
        dec=lambda value: cipher.decrypt(value.encode()).decode())

    @contextmanager
    def db():
        c = host.con()
        c.executescript('''
        CREATE TABLE IF NOT EXISTS tv_native_settings (
          id INTEGER PRIMARY KEY CHECK(id=1), source_enc TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS tv_native_m3u_files (
          id TEXT PRIMARY KEY, content_enc TEXT NOT NULL, access_hash TEXT NOT NULL,
          created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_native_m3u_previews (
          id TEXT PRIMARY KEY, content_enc TEXT NOT NULL, target_file_id TEXT NOT NULL DEFAULT '',
          created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_monthly_accounts (
          token_hash TEXT PRIMARY KEY, paid_until TEXT NOT NULL,
          created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_trial_uses (token_hash TEXT PRIMARY KEY, started_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_monthly_payments (
          id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, amount_dop INTEGER NOT NULL,
          confirmed_at INTEGER NOT NULL, previous_until TEXT, paid_until TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_manual_channels (id TEXT PRIMARY KEY, number INTEGER NOT NULL, name TEXT NOT NULL, url_enc TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_native_devices (
          token_hash TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
          created INTEGER NOT NULL, seen INTEGER NOT NULL);
        ''')
        initial = os.environ.get('TV_DEFAULT_PLAYLIST_URL', '')
        if initial:
            c.execute('INSERT OR IGNORE INTO tv_native_settings(id,source_enc,revision) VALUES(1,?,1)',
                      (host.enc(initial),))
        c.execute('DELETE FROM tv_native_m3u_previews WHERE created<?', (int(time.time())-172800,))
        c.commit()
        try:
            yield c
        finally:
            c.close()

    def tv_today():
        return __import__('datetime').datetime.now(ZoneInfo('America/Santo_Domingo')).date()

    def next_month_due(today):
        # A paid month always advances from the existing date when prepaid.
        month = 1 if today.month == 12 else today.month + 1
        year = today.year + (1 if today.month == 12 else 0)
        return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))

    def csrf():
        if 'tv_csrf' not in session:
            session['tv_csrf'] = secrets.token_urlsafe(32)
        return session['tv_csrf']

    def valid_csrf():
        return hmac.compare_digest(request.form.get('csrf', ''), session.get('tv_csrf', '!'))

    def source_config(raw):
        u = urlsplit(raw)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            raise ValueError('Introduce un enlace M3U válido, con http:// o https://.')
        q = parse_qs(u.query)
        username, password = q.get('username', [''])[0], q.get('password', [''])[0]
        base = u.scheme + '://' + u.netloc
        if username and password:
            return dict(kind='xtream', server=base, username=username, password=password)
        return dict(kind='m3u', url=raw)

    def playlist_entries(content):
        preamble, entries, current = [], [], None
        for line in content.splitlines():
            if line.startswith('#EXTINF:'):
                if current and any(v.strip() and not v.lstrip().startswith('#') for v in current[1:]):
                    entries.append(current)
                current = [line]
            elif current is None:
                preamble.append(line)
            else:
                current.append(line)
        if current and any(v.strip() and not v.lstrip().startswith('#') for v in current[1:]):
            entries.append(current)
        return preamble, entries

    def playlist_label(entry):
        info = next((line for line in entry if line.startswith('#EXTINF:')), '')
        name = info.rsplit(',', 1)[-1].strip() if ',' in info else ''
        if not name:
            match = re.search(r'tvg-name="([^"]+)"', info)
            name = match.group(1).strip() if match else 'Canal sin nombre'
        group = re.search(r'group-title="([^"]*)"', info)
        return name, (group.group(1).strip() if group else '')

    def tv_page():
        # Keep the existing Inter Flash administrator login, without a second TV password prompt.
        if not host.auth():
            return redirect('/login')
        session['tv_verified_at'] = int(time.time())
        note = ''
        if request.method == 'POST':
            if not valid_csrf():
                return 'Recarga la página e inténtalo de nuevo.', 403
            action = request.form.get('action')
            if action == 'unlock':
                if hmac.compare_digest(request.form.get('password', ''), host.PASSWORD):
                    session['tv_verified_at'] = int(time.time())
                    return redirect('/inter-tv')
                note = 'Contraseña incorrecta.'
            elif int(time.time()) - session.get('tv_verified_at', 0) < 1800:
                with db() as c:
                    if action == 'save':
                        raw = request.form.get('playlist', '').strip()
                        try:
                            source_config(raw)
                            if len(raw) > 8192:
                                raise ValueError('El enlace es demasiado largo.')
                            c.execute('''INSERT INTO tv_native_settings(id,source_enc,revision)
                              VALUES(1,?,1) ON CONFLICT(id) DO UPDATE SET
                              source_enc=excluded.source_enc,revision=revision+1''', (host.enc(raw),))
                            note = 'Lista guardada. Las apps vinculadas la consultarán al abrir.'
                        except ValueError as ex:
                            note = str(ex)
                    elif action in ('manual_add', 'manual_delete'):
                        if action == 'manual_delete':
                            c.execute('DELETE FROM tv_manual_channels WHERE id=?', (request.form.get('channel_id',''),))
                            c.execute('UPDATE tv_native_settings SET revision=revision+1 WHERE id=1')
                            note = 'Canal eliminado.'
                        else:
                            name = request.form.get('channel_name','').strip()
                            raw_number = request.form.get('channel_number','').strip()
                            url = request.form.get('channel_url','').strip()
                            try:
                                number = int(raw_number)
                                parsed = urlsplit(url)
                                if not 1 <= number <= 9999 or not name or len(name)>100 or any(ch in name for ch in ('\n','\r','"')):
                                    raise ValueError('Revisa el nombre y el número.')
                                if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or len(url)>4096 or any(ch.isspace() for ch in url):
                                    raise ValueError('Enlace de canal no válido.')
                                c.execute('INSERT INTO tv_manual_channels VALUES(?,?,?,?,?)', (secrets.token_urlsafe(12),number,name,host.enc(url),int(time.time())))
                                c.execute('UPDATE tv_native_settings SET revision=revision+1 WHERE id=1')
                                note = 'Canal guardado.'
                            except ValueError as ex:
                                note = str(ex)
                    elif action == 'upload_m3u':
                        upload = request.files.get('m3u_file')
                        if not upload or not upload.filename:
                            note = 'Elige un archivo .m3u.'
                        elif not upload.filename.lower().endswith(('.m3u', '.m3u8')):
                            note = 'El archivo debe terminar en .m3u o .m3u8.'
                        else:
                            raw_bytes = upload.stream.read(10 * 1024 * 1024 + 1)
                            if len(raw_bytes) > 10 * 1024 * 1024:
                                note = 'El archivo supera el límite de 10 MB.'
                            else:
                                try:
                                    content = raw_bytes.decode('utf-8-sig')
                                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                                    if not lines or not lines[0].startswith('#EXTM3U'):
                                        raise ValueError('El archivo no parece una lista M3U válida.')
                                    if not any(line.startswith(('http://', 'https://')) for line in lines):
                                        raise ValueError('La lista no contiene enlaces de canales.')
                                    _, items = playlist_entries(content)
                                    if not items:
                                        raise ValueError('No encontré canales con nombre en esa lista M3U.')
                                    preview_id = secrets.token_urlsafe(18)
                                    c.execute('INSERT INTO tv_native_m3u_previews(id,content_enc,target_file_id,created) VALUES(?,?,?,?)',
                                              (preview_id, host.enc(content), '', int(time.time())))
                                    session['tv_preview_id'] = preview_id
                                    note = 'Encontré ' + str(len(items)) + ' canales o títulos. Elige cuáles quieres conservar y guarda la selección.'
                                except (UnicodeDecodeError, ValueError) as ex:
                                    note = str(ex) or 'No se pudo leer el archivo. Usa formato UTF-8.'
                    elif action == 'append_vod_m3u':
                        # Add a separate VOD playlist without replacing working live TV channels.
                        media_type = request.form.get('media_type', '')                        upload = request.files.get('vod_file')
                        if media_type not in ('movie', 'series'):
                            note = 'Selecciona Películas o Series.'
                        elif not upload or not upload.filename or not upload.filename.lower().endswith(('.m3u', '.m3u8')):
                            note = 'Selecciona un archivo .m3u o .m3u8 válido.'
                        else:
                            raw = upload.stream.read(10 * 1024 * 1024 + 1)
                            if len(raw) > 10 * 1024 * 1024:
                                note = 'El archivo supera los 10 MB.'
                            else:
                                try:
                                    new_content = raw.decode('utf-8-sig')
                                    new_lines = [s.strip() for s in new_content.splitlines() if s.strip()]
                                    if not new_lines or not new_lines[0].startswith('#EXTM3U'):
                                        raise ValueError('El archivo no parece una lista M3U.')
                                    _, new_items = playlist_entries(new_content)
                                    if not new_items:
                                        raise ValueError('No hay títulos válidos en ese archivo.')
                                    current = c.execute('SELECT source_enc FROM tv_native_settings WHERE id=1').fetchone()
                                    if not current:
                                        raise ValueError('Primero guarda tu lista de canales desde el panel.')
                                    current_source = host.dec(current['source_enc'])
                                    if not current_source.startswith('m3ufile:'):
                                        raise ValueError('Para añadir películas o series sin reemplazar canales, primero utiliza una lista de canales subida como archivo M3U.')
                                    _, file_id, _ = current_source.split(':', 2)
                                    existing_file = c.execute('SELECT content_enc FROM tv_native_m3u_files WHERE id=?', (file_id,)).fetchone()
                                    if not existing_file:
                                        raise ValueError('No se encontró la lista actual. No se modificó nada.')
                                    existing_text = host.dec(existing_file['content_enc'])
                                    preamble, existing_items = playlist_entries(existing_text)
                                    def stream_url(item):
                                        return next((s.strip() for s in item[1:] if s.strip().startswith(('http://', 'https://'))), '')
                                    existing_urls = {stream_url(item) for item in existing_items}
                                    added = []
                                    for item in new_items:
                                        url = stream_url(item)
                                        if not url or url in existing_urls:
                                            continue
                                        info = item[0]
                                        # OwnTV uses the M3U type attribute to place content in Movies or Series.
                                        info = re.sub(r'\s+(?:type|tvg-type)="[^"]*"', '', info)
                                        info = info.replace('#EXTINF:', '#EXTINF: type="' + media_type + '" ', 1)
                                        added.append([info] + item[1:])
                                        existing_urls.add(url)
                                    if not added:
                                        raise ValueError('No encontré títulos nuevos; los enlaces ya estaban guardados.')
                                    merged = '\n'.join(preamble + [s for entry in existing_items + added for s in entry]).strip() + '\n'
                                    if len(merged.encode('utf-8')) > 10 * 1024 * 1024:
                                        raise ValueError('La lista combinada supera 10 MB. No se ha cambiado la lista actual.')
                                    c.execute('UPDATE tv_native_m3u_files SET content_enc=? WHERE id=?',
                                              (host.enc(merged), file_id))
                                    c.execute('UPDATE tv_native_settings SET revision=revision+1 WHERE id=1')
                                    session.pop('tv_preview_id', None)
                                    note = 'Agregados ' + str(len(added)) + (' títulos de películas.' if media_type == 'movie' else ' títulos de series.') + ' Los canales anteriores se conservan.'
                                except (UnicodeDecodeError, ValueError) as ex:
                                    note = str(ex)
                    elif action == 'save_m3u_selection':
                        preview_id = request.form.get('preview_id', '')
                        if not preview_id or preview_id != session.get('tv_preview_id'):
                            note = 'La lista de selección venció. Recarga la página e inténtalo otra vez.'
                        else:
                            preview = c.execute('SELECT * FROM tv_native_m3u_previews WHERE id=?', (preview_id,)).fetchone()
                            if not preview:
                                note = 'No encontré la lista para guardar. Vuelve a cargar el archivo.'
                            else:
                                content = host.dec(preview['content_enc'])
                                preamble, items = playlist_entries(content)
                                keep = set()
                                for value in request.form.getlist('keep'):
                                    try:
                                        index = int(value)
                                        if 0 <= index < len(items):
                                            keep.add(index)
                                    except (TypeError, ValueError):
                                        pass
                                if not keep:
                                    note = 'Marca al menos un canal para guardar la lista.'
                                else:
                                    selected = '\n'.join(preamble + [line for i, item in enumerate(items) if i in keep for line in item]).strip() + '\n'
                                    target_file_id = preview['target_file_id']
                                    if target_file_id:
                                        found = c.execute('SELECT id FROM tv_native_m3u_files WHERE id=?', (target_file_id,)).fetchone()
                                        if not found:
                                            note = 'El archivo original ya no está disponible. Vuelve a cargarlo.'
                                        else:
                                            c.execute('UPDATE tv_native_m3u_files SET content_enc=? WHERE id=?',
                                                      (host.enc(selected), target_file_id))
                                            c.execute('UPDATE tv_native_settings SET revision=revision+1 WHERE id=1')
                                            note = 'Selección guardada: ' + str(len(keep)) + ' canales o títulos quedan en la lista.'
                                    else:
                                        file_id = secrets.token_urlsafe(18)
                                        access_key = secrets.token_urlsafe(32)
                                        c.execute('INSERT INTO tv_native_m3u_files(id,content_enc,access_hash,created) VALUES(?,?,?,?)',
                                                  (file_id, host.enc(selected), hashlib.sha256(access_key.encode()).hexdigest(), int(time.time())))
                                        c.execute('''INSERT INTO tv_native_settings(id,source_enc,revision)
                                          VALUES(1,?,1) ON CONFLICT(id) DO UPDATE SET
                                          source_enc=excluded.source_enc,revision=revision+1''',
                                                  (host.enc('m3ufile:' + file_id + ':' + access_key),))
                                        target_file_id = file_id
                                        note = 'Selección guardada: ' + str(len(keep)) + ' canales o títulos quedan en la lista.'
                                    if target_file_id:
                                        c.execute('UPDATE tv_native_m3u_previews SET content_enc=?,target_file_id=?,created=? WHERE id=?',
                                                  (host.enc(selected), target_file_id, int(time.time()), preview_id))
                    elif action in ('tv_confirm_payment', 'tv_day_trial'):
                        code = request.form.get('code','').strip().upper()
                        device = c.execute('SELECT token_hash,approved FROM tv_native_devices WHERE code=?',(code,)).fetchone()
                        if not device or device['approved'] != 1:
                            note = 'Televisor no vinculado o desactivado.'
                        elif action == 'tv_day_trial':
                            used = c.execute('SELECT 1 FROM tv_trial_uses WHERE token_hash=?',(device['token_hash'],)).fetchone()
                            account = c.execute('SELECT 1 FROM tv_monthly_accounts WHERE token_hash=?',(device['token_hash'],)).fetchone()
                            if used or account:
                                note = 'La prueba es una sola vez y antes del primer pago.'
                            else:
                                now = int(time.time())
                                c.execute('INSERT INTO tv_trial_uses(token_hash,started_at,expires_at) VALUES(?,?,?)',(device['token_hash'],now,now+86400))
                                note = 'Prueba de 24 horas activada para '+host.e(code)+'.'
                        else:
                            months_raw = request.form.get('months','1')
                            if months_raw not in ('1','2','3'):
                                note = 'Selecciona 1, 2 o 3 meses.'
                            else:
                                months = int(months_raw)
                                current = c.execute('SELECT paid_until FROM tv_monthly_accounts WHERE token_hash=?',(device['token_hash'],)).fetchone()
                                old = date.fromisoformat(current['paid_until']) if current else None
                                anchor = max(tv_today(),old) if old else tv_today()
                                due = anchor
                                for _ in range(months):
                                    due = next_month_due(due)
                                amount = months*600
                                now = int(time.time())
                                c.execute('''INSERT INTO tv_monthly_accounts(token_hash,paid_until,created) VALUES(?,?,?)
                                ON CONFLICT(token_hash) DO UPDATE SET paid_until=excluded.paid_until''',(device['token_hash'],due.isoformat(),now))
                                c.execute('''INSERT INTO tv_monthly_payments(id,token_hash,amount_dop,confirmed_at,previous_until,paid_until)
                                VALUES(?,?,?,?,?,?)''',(secrets.token_urlsafe(15),device['token_hash'],amount,now,old.isoformat() if old else None,due.isoformat()))
                                note = 'Pago RD$'+str(amount)+' por '+str(months)+' mes(es) confirmado. Vence '+due.strftime('%d/%m/%Y')+'.'
                    elif action == 'approve':
                        code = request.form.get('code', '').strip().upper()
                        found = c.execute('SELECT * FROM tv_native_devices WHERE code=? AND created>?',
                                          (code, int(time.time())-900)).fetchone()
                        if found:
                            c.execute('UPDATE tv_native_devices SET approved=1,name=? WHERE code=?',
                                      ((request.form.get('name') or found['name'])[:100], code))
                            note = 'Televisor vinculado. La app puede recibir tu lista.'
                        else:
                            note = 'Código no encontrado o vencido. Abre de nuevo la app.'
                    elif action == 'unlink':
                        c.execute('UPDATE tv_native_devices SET approved=-1 WHERE code=? AND approved=1', (request.form.get('code', ''),))
                        note = 'Televisor desvinculado. La nueva app bloqueará los canales al recibir el aviso.'
                    elif action == 'reactivate':
                        c.execute('UPDATE tv_native_devices SET approved=1 WHERE code=? AND approved=-1', (request.form.get('code', ''),))
                        note = 'Televisor reactivado. Abre la app para sincronizar los canales.'
                    c.commit()
            else:
                return redirect('/inter-tv')
        token = host.e(csrf())
        head = '<style>.panel .field{display:grid;gap:7px;margin-bottom:12px}.panel .field input{width:100%;box-sizing:border-box;padding:11px;border:1px solid #354b64;border-radius:8px;background:#101f30;color:#e7eef8}.panel .field label{font-weight:600}.panel .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}</style><div class="head"><div><h1>Inter Flash TV</h1><p>Lista y televisores vinculados</p></div></div>'
        message = '<div class="notice">'+host.e(note)+'</div>' if note else ''
        if int(time.time()) - session.get('tv_verified_at', 0) >= 1800:
            body = head + message + '''<div class="panel"><p>Confirma tu contraseña de administrador para gestionar la lista de televisión.</p>
            <form method="post"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="unlock"><div class="field"><label>Contraseña</label>
            <input type="password" name="password" autocomplete="current-password" required></div>
            <button class="btn green">Entrar a televisión</button></form></div>'''
            return host.shell('Inter Flash TV', body, 'inter_tv')
        with db() as c:
            config = c.execute('SELECT revision FROM tv_native_settings WHERE id=1').fetchone()
            devices = c.execute('SELECT * FROM tv_native_devices WHERE approved IN (1,-1) ORDER BY seen DESC').fetchall()
            tv_dues = {r['token_hash']: r['paid_until'] for r in c.execute('SELECT token_hash,paid_until FROM tv_monthly_accounts').fetchall()}
            tv_trials = {r['token_hash']: r['expires_at'] for r in c.execute('SELECT token_hash,expires_at FROM tv_trial_uses').fetchall()}
        with db() as c:
            manual_channels = c.execute('SELECT id,number,name FROM tv_manual_channels ORDER BY number,name').fetchall()
        manual_rows = ''.join('<li>'+host.e(x['number'])+' — '+host.e(x['name'])+
            '<form method="post" style="display:inline"><input type="hidden" name="csrf" value="'+token+'">'+
            '<input type="hidden" name="action" value="manual_delete"><input type="hidden" name="channel_id" value="'+host.e(x['id'])+'">'+
            '<button class="btn small" type="submit">Eliminar</button></form></li>' for x in manual_channels)
        manual_panel = ('<div class="panel"><h2>Agregar canal manualmente</h2><p>Los canales manuales se añaden a la lista M3U subida, sin reemplazarla.</p>'+
            '<form method="post"><input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="action" value="manual_add">'+
            '<div class="field"><label>Nombre</label><input name="channel_name" maxlength="100" required></div>'+
            '<div class="field"><label>Número</label><input name="channel_number" type="number" min="1" max="9999" required></div>'+
            '<div class="field"><label>Enlace</label><input name="channel_url" type="url" required></div>'+
            '<button class="btn green">Guardar canal</button></form><h3>Canales manuales</h3><ul>'+manual_rows+'</ul></div>')
        rows = ''.join(
            '<tr><td>'+host.e(d['name'])+'</td><td>'+host.e(d['code'])+'</td><td>'+
            (('Vence '+host.e(tv_dues[d['token_hash']]) if tv_dues[d['token_hash']] > tv_today().isoformat() else 'Vencido '+host.e(tv_dues[d['token_hash']]))
              if d['token_hash'] in tv_dues else ('Prueba activa 24h' if tv_trials[d['token_hash']] > int(time.time()) else 'Prueba vencida') if d['token_hash'] in tv_trials else 'Sin suscripción: canales actuales sin cambios')+'</td><td>'+
            '<form method="post"><input type="hidden" name="csrf" value="'+token+'">'+
            '<input type="hidden" name="action" value="tv_confirm_payment"><input type="hidden" name="code" value="'+host.e(d['code'])+'">'+
            '<select name="months" aria-label="Meses"><option value="1">1 mes RD$600</option><option value="2">2 meses RD$1,200</option><option value="3">3 meses RD$1,800</option></select><button class="btn small" type="submit">Confirmar pago</button></form>'+ 
             '<form method="post"><input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="action" value="tv_day_trial"><input type="hidden" name="code" value="'+host.e(d['code'])+'"><button class="btn small" type="submit">Prueba de 1 día</button></form></td><td>'+
            '<form method="post"><input type="hidden" name="csrf" value="'+token+'">'+
            '<input type="hidden" name="action" value="'+('unlink' if d['approved']==1 else 'reactivate')+'"><input type="hidden" name="code" value="'+host.e(d['code'])+'">'+
            '<button class="btn small">'+('Desvincular' if d['approved']==1 else 'Reactivar')+'</button></form></td></tr>'
            for d in devices)
        preview_id = session.get('tv_preview_id', '')
        if not preview_id:
            with db() as c:
                active = c.execute('SELECT source_enc FROM tv_native_settings WHERE id=1').fetchone()
                if active:
                    try:                        saved = host.dec(active['source_enc'])
                        if saved.startswith('m3ufile:'):
                            _, target_file_id, _ = saved.split(':', 2)
                            file = c.execute('SELECT content_enc FROM tv_native_m3u_files WHERE id=?', (target_file_id,)).fetchone()
                            if file:
                                preview_id = secrets.token_urlsafe(18)
                                c.execute('INSERT INTO tv_native_m3u_previews(id,content_enc,target_file_id,created) VALUES(?,?,?,?)',
                                          (preview_id, file['content_enc'], target_file_id, int(time.time())))
                                session['tv_preview_id'] = preview_id
                    except Exception:
                        preview_id = ''
        selection_panel = ''
        if preview_id:
            with db() as c:
                preview = c.execute('SELECT * FROM tv_native_m3u_previews WHERE id=?', (preview_id,)).fetchone()
            if preview:
                _, items = playlist_entries(host.dec(preview['content_enc']))
                channel_rows = []
                for i, item in enumerate(items):
                    name, group = playlist_label(item)
                    search = (name + ' ' + group).lower()
                    channel_rows.append('<label class="tv-channel-row" data-search="'+host.e(search)+'"><input type="checkbox" name="keep" value="'+str(i)+'" checked><span>'+host.e(name)+'</span><small>'+host.e(group)+'</small></label>')
                selection_panel = '<div class="panel"><h2>Elige qué dejar en tu lista</h2><p>Encontré '+str(len(items))+' canales o títulos. Los que queden marcados se conservarán; los demás se quitarán.</p><input id="tv-search" type="search" placeholder="Buscar por nombre o categoría" style="width:100%;padding:10px;margin:8px 0"><div style="display:flex;gap:8px;margin-bottom:10px"><button class="btn small" type="button" onclick="document.querySelectorAll(\'.tv-channel-row input\').forEach(x=>x.checked=true)">Marcar todos</button><button class="btn small" type="button" onclick="document.querySelectorAll(\'.tv-channel-row input\').forEach(x=>x.checked=false)">Desmarcar todos</button></div><form method="post" id="tv-select-form"><input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="action" value="save_m3u_selection"><input type="hidden" name="preview_id" value="'+host.e(preview_id)+'"><div style="max-height:55vh;overflow:auto;border:1px solid #354b64;border-radius:8px;padding:8px">'+''.join(channel_rows)+'</div><button class="btn green" style="margin-top:12px">Guardar selección</button></form><script>document.getElementById(\'tv-search\').addEventListener(\'input\',function(){const q=this.value.toLowerCase();document.querySelectorAll(\'.tv-channel-row\').forEach(x=>x.style.display=x.dataset.search.includes(q)?\'grid\':\'none\')})</script><style>.tv-channel-row{display:grid;grid-template-columns:24px 1fr auto;align-items:center;gap:8px;padding:8px;border-bottom:1px solid #26394d}.tv-channel-row small{opacity:.7}.tv-channel-row input{width:18px;height:18px}</style></div>'
            else:
                session.pop('tv_preview_id', None)
        body = head + message + manual_panel + selection_panel + '<div class="panel"><h2>Lista de canales, películas y series</h2><p>' + (
            'Lista configurada · versión '+str(config['revision']) if config else 'Todavía no hay una lista guardada.') + '''</p>
            <form method="post"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="save"><div class="field"><label>Enlace M3U del proveedor</label>
            <input type="password" name="playlist" autocomplete="off" required placeholder="Pega aquí la lista completa"></div>
            <p class="muted">El enlace se guarda cifrado. HTTP transmite los datos sin cifrar entre el televisor y el proveedor.</p>
            <button class="btn green">Guardar lista</button></form></div>
            <div class="panel"><h2>O subir archivo M3U</h2><p>Selecciona la lista de canales que tienes guardada en tu computadora. El archivo se guarda cifrado.</p>
            <form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="upload_m3u"><div class="field"><label>Archivo de canales (.m3u o .m3u8)</label>
            <input type="file" name="m3u_file" accept=".m3u,.m3u8,audio/x-mpegurl,application/vnd.apple.mpegurl" required></div>
            <button class="btn blue">Cargar archivo M3U</button></form></div>
            <div class="panel"><h2>Añadir películas o series sin borrar canales</h2><p>Sube otra lista M3U con películas o episodios de series. Se agregarán a la lista de TV existente; no se reemplazarán los canales actuales.</p>
            <form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="append_vod_m3u">
            <div class="field"><label>Tipo de contenido</label><select name="media_type" required style="width:100%;padding:11px;background:#101f30;color:#e7eef8;border:1px solid #354b64;border-radius:8px">
            <option value="movie">Películas</option><option value="series">Series</option></select></div>
            <div class="field"><label>Archivo M3U de películas o series</label><input type="file" name="vod_file" accept=".m3u,.m3u8" required></div>
            <button class="btn blue">Añadir a Inter Flash TV</button></form></div>
            <div class="panel"><h2>Vincular la app nueva</h2><p>Introduce el código que aparece en el televisor. Válido durante 15 minutos.</p>
            <form method="post" class="grid"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="approve"><div class="field"><label>Código del televisor</label>
            <input name="code" maxlength="8" required></div><div class="field"><label>Nombre</label><input name="name" placeholder="TV de Manuel"></div>
            <div><button class="btn blue">Vincular televisor</button></div></form></div>
            <div class="panel"><h2>Televisores y pagos TV (RD$600/mes)</h2><table><tr><th>Nombre</th><th>Código</th><th>Suscripción TV</th><th>Pago mensual</th><th>Acción</th></tr>'''+(
                rows or '<tr><td colspan="5">Ningún televisor vinculado.</td></tr>')+'''</table>
            <p class="muted">Con la app actualizada, Desvincular detiene los canales de este televisor al recibir el aviso. Reactivar permite volver a sincronizarlos. Los enlaces directos del proveedor no se cancelan.</p></div>
            <div class="panel"><a class="btn blue" href="https://github.com/manuel829mg-cloud/InterFlashTV/releases/download/native-v9-panel-test/InterFlashTV-native-v9.apk">Descargar app nativa v9</a> <a class="btn" href="https://inter-tv-prueba-production.up.railway.app/" target="_blank" rel="noopener">Abrir reproductor web</a>
            <p class="muted">Instala la app nativa v9 para vincularla. Si Android informa un conflicto de firma, desinstala la versión de prueba anterior; se borrarán sus ajustes locales.</p></div>'''
        response = app.make_response(host.shell('Inter Flash TV', body, 'inter_tv'))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    # Preserve the endpoint name used by all existing navigation modules.
    app.view_functions['inter_tv'] = tv_page
    if '/inter-tv' not in {r.rule for r in app.url_map.iter_rules()}:
        app.add_url_rule('/inter-tv', 'inter_tv', tv_page, methods=['GET', 'POST'])
    else:
        # The old integration registered GET only; a distinct POST endpoint is safe.
        app.add_url_rule('/inter-tv', 'inter_tv_save', tv_page, methods=['POST'])

    @app.post('/api/tv-native/register')
    def tv_native_register():
        data = request.get_json(silent=True) or {}
        token = str(data.get('token', ''))
        if len(token) != 64 or any(ch not in '0123456789abcdef' for ch in token):
            return jsonify(error='Invalid token'), 400
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = int(time.time())
        with db() as c:
            c.execute('DELETE FROM tv_native_devices WHERE approved=0 AND created<?', (now-900,))
            found = c.execute('SELECT code,approved FROM tv_native_devices WHERE token_hash=?', (digest,)).fetchone()
            if not found:
                count = c.execute('SELECT count(*) FROM tv_native_devices WHERE approved=0').fetchone()[0]
                if count >= 100:
                    return jsonify(error='Busy'), 429
                code = secrets.token_hex(4).upper()
                c.execute('INSERT INTO tv_native_devices VALUES(?,?,?,?,?,?)',
                          (digest, code, str(data.get('name', 'Televisor'))[:100], 0, now, now))
                found = dict(code=code, approved=0)
            c.commit()
        response = jsonify(code=found['code'], approved=found['approved']==1, revoked=found['approved']==-1)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/tv-native/config')
    def tv_native_config():
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or len(auth) != 71:
            return jsonify(error='Unauthorized'), 401
        digest = hashlib.sha256(auth[7:].encode()).hexdigest()
        with db() as c:
            device = c.execute('SELECT approved FROM tv_native_devices WHERE token_hash=?', (digest,)).fetchone()
            if not device or device['approved'] != 1:
                return jsonify(error='Approval required'), 403
            subscription = c.execute('SELECT paid_until FROM tv_monthly_accounts WHERE token_hash=?', (digest,)).fetchone()
            trial = c.execute('SELECT expires_at FROM tv_trial_uses WHERE token_hash=?',(digest,)).fetchone()
            if (subscription and subscription['paid_until'] <= tv_today().isoformat()) or (not subscription and trial and trial['expires_at'] <= int(time.time())):
                return jsonify(error='TV subscription expired', amount_dop=600), 402
            c.execute('UPDATE tv_native_devices SET seen=? WHERE token_hash=?', (int(time.time()), digest))
            config = c.execute('SELECT * FROM tv_native_settings WHERE id=1').fetchone()
            c.commit()
        if not config:
            return jsonify(error='No playlist configured'), 409
        try:
            saved_source = host.dec(config['source_enc'])
            if saved_source.startswith('m3ufile:'):
                _, file_id, access_key = saved_source.split(':', 2)
                payload = dict(kind='m3u', url='https://interflash-isp-manager.up.railway.app/api/tv-native/playlist/' + file_id + '/' + access_key + '.m3u')
            else:
                payload = source_config(saved_source)
        except ValueError:
            return jsonify(error='Invalid stored source'), 503
        # Separate manual-channel source works alongside Xtream, external M3U and file M3U.
        with db() as c:
            manual_count = c.execute('SELECT COUNT(*) FROM tv_manual_channels').fetchone()[0]
        if manual_count:
            signature = hmac.new(host.PASSWORD.encode(), digest.encode(), hashlib.sha256).hexdigest()
            payload['manual_url'] = ('https://interflash-isp-manager.up.railway.app/api/tv-native/manual/'
                                     + digest + '/' + signature + '.m3u')
            payload['manual_revision'] = config['revision']
        payload.update(revision=config['revision'] + (2 if saved_source.startswith('m3ufile:') else 0), name='Inter Flash TV')
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/api/tv-native/manual/<digest>/<signature>.m3u')
    def tv_native_manual_playlist(digest, signature):
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or not re.fullmatch(r'[0-9a-f]{64}', signature):
            return 'No autorizado', 404
        expected = hmac.new(host.PASSWORD.encode(), digest.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return 'No autorizado', 404
        with db() as c:
            device = c.execute('SELECT approved FROM tv_native_devices WHERE token_hash=?', (digest,)).fetchone()
            if not device or device['approved'] != 1:
                return 'No autorizado', 403
            subscription = c.execute('SELECT paid_until FROM tv_monthly_accounts WHERE token_hash=?', (digest,)).fetchone()
            trial = c.execute('SELECT expires_at FROM tv_trial_uses WHERE token_hash=?', (digest,)).fetchone()
            if (subscription and subscription['paid_until'] <= tv_today().isoformat()) or (not subscription and trial and trial['expires_at'] <= int(time.time())):
                return 'Suscripcion vencida', 403
            channels = c.execute('SELECT number,name,url_enc FROM tv_manual_channels ORDER BY number,name').fetchall()
        lines = ['#EXTM3U']
        for item in channels:
            lines.extend(['#EXTINF:-1 tvg-chno="'+str(item['number'])+'" group-title="Canales Dominicanos",'+item['name'],
                          host.dec(item['url_enc'])])
        response = app.make_response(gzip.compress(('\\n'.join(lines) + '\\n').encode('utf-8'), compresslevel=6))
        response.headers['Content-Type'] = 'application/vnd.apple.mpegurl; charset=utf-8'
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/tv-native/playlist/<file_id>/<access_key>.m3u')
    def tv_native_playlist_file(file_id, access_key):
        with db() as c:
            row = c.execute('SELECT content_enc,access_hash FROM tv_native_m3u_files WHERE id=?', (file_id,)).fetchone()
        digest = hashlib.sha256(access_key.encode()).hexdigest()
        if not row or not hmac.compare_digest(digest, row['access_hash']):
            return 'No autorizado', 404
        try:
            content = host.dec(row['content_enc'])
            with db() as c:
                additions = c.execute('SELECT number,name,url_enc FROM tv_manual_channels ORDER BY number,name').fetchall()
            if additions:
                extra = []
                for item in additions:
                    extra.extend(['#EXTINF:-1 tvg-chno="'+str(item['number'])+'" group-title="Canales Dominicanos",'+item['name'], host.dec(item['url_enc'])])
                # Place this category first in the delivered M3U, without changing the saved original.
                existing_lines = content.splitlines()
                if existing_lines and existing_lines[0].strip().startswith('#EXTM3U'):
                    content = '\n'.join([existing_lines[0]] + extra + existing_lines[1:]).rstrip() + '\n'
                else:
                    content = '#EXTM3U\n' + '\n'.join(extra) + '\n' + content.lstrip()
        except Exception:
            return 'Archivo no disponible', 503
        response = app.make_response(gzip.compress(content.encode('utf-8'), compresslevel=6))
        response.headers['Content-Type'] = 'application/vnd.apple.mpegurl; charset=utf-8'
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response