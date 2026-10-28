"""Private TV source management and approval of individual native installations."""
import gzip
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
        # The legacy panel cookie is insufficient for disclosing provider secrets.
        # Require a signed Flask session after password verification for this module.
        if not host.auth():
            return redirect('/login')
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
                        c.execute('DELETE FROM tv_native_devices WHERE code=?', (request.form.get('code', ''),))
                        note = 'Dispositivo desvinculado. Ya no recibirá configuraciones nuevas.'
                    elif action in ('tv_sub_create', 'tv_sub_pay', 'tv_sub_trial', 'tv_sub_bind'):
                        if os.environ.get('TV_SUBSCRIPTIONS_ENABLED') != '1':
                            note = 'Suscripciones TV no habilitadas.'
                        else:
                            from datetime import date
                            from tv_subscriptions_isolated import (
                                create_schema, record_payment, start_one_time_trial
                            )
                            create_schema(c)
                            try:
                                if action == 'tv_sub_create':
                                    customer_id = int(request.form.get('customer_id') or 0)
                                    billing_day = int(request.form.get('billing_day') or 0)
                                    if customer_id <= 0 or not 1 <= billing_day <= 31:
                                        raise ValueError('Cliente o día de corte incorrecto.')
                                    c.execute('''INSERT INTO tv_subscriptions
                                        (customer_id,billing_day,created_at) VALUES(?,?,?)''',
                                        (customer_id,billing_day,
                                         __import__('datetime').datetime.now(
                                             __import__('datetime').timezone.utc).isoformat()))
                                    note = 'Suscripción de televisión creada sin afectar internet.'
                                elif action == 'tv_sub_pay':
                                    sid = int(request.form.get('subscription_id') or 0)
                                    receipt = (request.form.get('receipt_reference') or '').strip()
                                    new_due = record_payment(c,sid,receipt,date.today())
                                    note = 'Pago TV RD$600 registrado. Próximo corte: ' + new_due.isoformat()
                                elif action == 'tv_sub_trial':
                                    sid = int(request.form.get('subscription_id') or 0)
                                    ends = start_one_time_trial(c,sid)
                                    note = 'Prueba única de TV activada hasta ' + ends.isoformat()
                                else:
                                    sid = int(request.form.get('subscription_id') or 0)
                                    code = (request.form.get('code') or '').strip().upper()
                                    device = c.execute('''SELECT token_hash FROM tv_native_devices
                                        WHERE code=? AND approved=1''', (code,)).fetchone()
                                    sub = c.execute('SELECT * FROM tv_subscriptions WHERE id=?',
                                                    (sid,)).fetchone()
                                    if not device or not sub:
                                        raise ValueError('Aprueba el televisor y verifica la suscripción.')
                                    current = sub['device_token_hash']
                                    if current and not sub['unlinked_at'] and current != device['token_hash']:
                                        raise ValueError('Desvincula primero el televisor de esta suscripción.')
                                    found = c.execute('''SELECT id FROM tv_subscriptions WHERE
                                        device_token_hash=? AND id<>?''', (device['token_hash'],sid)).fetchone()
                                    history = c.execute('''SELECT subscription_id FROM
                                        tv_subscription_device_history WHERE token_hash=?''',
                                        (device['token_hash'],)).fetchone()
                                    if found or (history and history['subscription_id'] != sid):
                                        raise ValueError('El televisor ya pertenece a otra cuenta.')
                                    c.execute('''INSERT OR IGNORE INTO tv_subscription_device_history
                                        (token_hash,subscription_id,first_bound_at) VALUES(?,?,?)''',
                                        (device['token_hash'],sid,
                                         __import__('datetime').datetime.now(
                                             __import__('datetime').timezone.utc).isoformat()))
                                    c.execute('''UPDATE tv_subscriptions
                                        SET device_token_hash=?,unlinked_at=NULL WHERE id=?''',
                                        (device['token_hash'],sid))
                                    note = 'Televisor vinculado a la suscripción TV.'
                            except (ValueError, LookupError, sqlite3.IntegrityError) as ex:
                                note = str(ex) or 'No se pudo completar la operación TV.'
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
            devices = c.execute('SELECT * FROM tv_native_devices WHERE approved=1 ORDER BY seen DESC').fetchall()
        rows = ''.join('<tr><td>'+host.e(d['name'])+'</td><td>'+host.e(d['code'])+'</td><td>'
                       '<form method="post"><input type="hidden" name="csrf" value="'+token+'">'
                       '<input type="hidden" name="action" value="unlink"><input type="hidden" name="code" value="'+host.e(d['code'])+'">'
                       '<button class="btn small">Desvincular</button></form></td></tr>' for d in devices)
        preview_id = session.get('tv_preview_id', '')
        if not preview_id:
            with db() as c:
                active = c.execute('SELECT source_enc FROM tv_native_settings WHERE id=1').fetchone()
                if active:
                    try:
                        saved = host.dec(active['source_enc'])
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
        subscription_panel = ''
        if os.environ.get('TV_SUBSCRIPTIONS_ENABLED') == '1':
            from tv_subscriptions_isolated import create_schema, status
            from datetime import date
            with db() as c:
                create_schema(c)
                subs = c.execute('''SELECT id,customer_id,billing_day,paid_through,
                    device_token_hash FROM tv_subscriptions ORDER BY id DESC LIMIT 100''').fetchall()
            forms = '''<div class="panel"><h2>Suscripciones TV · RD$600/mes</h2>
            <p>La televisión se cobra por separado. No cambia el internet ni el MikroTik.</p>
            <form method="post" class="grid"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="tv_sub_create">
            <input name="customer_id" type="number" min="1" placeholder="ID de cliente" required>
            <input name="billing_day" type="number" min="1" max="31" placeholder="Día de corte" required>
            <button class="btn blue">Crear cuenta TV</button></form></div>'''
            entries = []
            for sub in subs:
                sid = str(sub['id'])
                state = status(c,sub['id'],date.today()) if False else ''
                entries.append('<tr><td>'+host.e(sub['customer_id'])+'</td><td>'+sid+
                    '</td><td>'+host.e(sub['paid_through'] or 'Sin pago')+
                    '</td><td>'+('Vinculado' if sub['device_token_hash'] else 'Sin TV')+'</td></tr>')
            for action, title, attrs in (
                ('tv_sub_pay','Registrar RD$600','<input name="receipt_reference" placeholder="Referencia bancaria única" required>'),
                ('tv_sub_trial','Prueba 24 horas',''),
                ('tv_sub_bind','Asociar TV aprobado','<input name="code" maxlength="8" placeholder="Código de televisor" required>'),
            ):
                forms += '<div class="panel"><h3>'+title+'</h3><form method="post" class="grid">'+\
                    '<input type="hidden" name="csrf" value="'+token+'">'+\
                    '<input type="hidden" name="action" value="'+action+'">'+\
                    '<input type="number" min="1" name="subscription_id" placeholder="ID de suscripción" required>'+\
                    attrs+'<button class="btn blue">'+title+'</button></form></div>'
            subscription_panel = forms + '<div class="panel"><h3>Últimas 100 cuentas TV</h3><table>'+\
                '<tr><th>Cliente</th><th>ID TV</th><th>Vence</th><th>Dispositivo</th></tr>'+\
                ''.join(entries)+'</table></div>'
        body = head + message + subscription_panel + selection_panel + '<div class="panel"><h2>Lista de canales, películas y series</h2><p>' + (
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
            <div class="panel"><h2>Vincular la app nueva</h2><p>Introduce el código que aparece en el televisor. Válido durante 15 minutos.</p>
            <form method="post" class="grid"><input type="hidden" name="csrf" value="'''+token+'''">
            <input type="hidden" name="action" value="approve"><div class="field"><label>Código del televisor</label>
            <input name="code" maxlength="8" required></div><div class="field"><label>Nombre</label><input name="name" placeholder="TV de Manuel"></div>
            <div><button class="btn blue">Vincular televisor</button></div></form></div>
            <div class="panel"><h2>Televisores vinculados</h2><table><tr><th>Nombre</th><th>Código</th><th>Acción</th></tr>'''+(
                rows or '<tr><td colspan="3">Ningún televisor vinculado.</td></tr>')+'''</table>
            <p class="muted">Desvincular impide recibir nuevas configuraciones; no cancela la cuenta del proveedor ni borra lo ya descargado.</p></div>
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
        response = jsonify(code=found['code'], approved=bool(found['approved']))
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
            if not device or not device['approved']:
                return jsonify(error='Approval required'), 403
            # TV billing is opt-in. Unmigrated devices preserve legacy behavior
            # until an administrator associates their existing token with a TV account.
            if os.environ.get('TV_SUBSCRIPTIONS_ENABLED') == '1':
                from tv_subscriptions_isolated import create_schema, status
                from datetime import date
                create_schema(c)
                sub = c.execute('''SELECT s.id,s.device_token_hash,s.unlinked_at
                    FROM tv_subscriptions s
                    LEFT JOIN tv_subscription_device_history h
                      ON h.subscription_id=s.id
                    WHERE s.device_token_hash=? OR h.token_hash=?
                    LIMIT 1''', (digest,digest)).fetchone()
                if sub:
                    # A former TV must not regain access by merely re-registering:
                    # authorization follows its immutable token history.
                    tv_state = ('UNLINKED' if sub['device_token_hash'] != digest
                                or sub['unlinked_at']
                                else status(c, sub['id'], date.today()))
                    if tv_state not in ('ACTIVE', 'TRIAL'):
                        reply = jsonify(error='Servicio suspendido por falta de pago',
                                        tv_status=tv_state)
                        reply.status_code = 402
                        reply.headers['Cache-Control'] = 'no-store'
                        return reply
            c.execute('UPDATE tv_native_devices SET seen=? WHERE token_hash=?', (int(time.time()), digest))
            config = c.execute('SELECT * FROM tv_native_settings WHERE id=1').fetchone()
            c.commit()
        if not config:
            return jsonify(error='No playlist configured'), 409
        try:
            saved_source = host.dec(config['source_enc'])
            if saved_source.startswith('m3ufile:'):
                _, file_id, access_key = saved_source.split(':', 2)
                payload = dict(kind='m3u', url=request.url_root.rstrip('/') + '/api/tv-native/playlist/' + file_id + '/' + access_key + '.m3u')
            else:
                payload = source_config(saved_source)
        except ValueError:
            return jsonify(error='Invalid stored source'), 503
        payload.update(revision=config['revision'] + (2 if saved_source.startswith('m3ufile:') else 0), name='Inter Flash TV')
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
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
        except Exception:
            return 'Archivo no disponible', 503
        response = app.make_response(gzip.compress(content.encode('utf-8'), compresslevel=6))
        response.headers['Content-Type'] = 'application/vnd.apple.mpegurl; charset=utf-8'
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response
