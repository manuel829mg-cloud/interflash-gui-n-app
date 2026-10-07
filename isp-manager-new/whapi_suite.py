"""Whapi.Cloud text adapter, private callbacks and administrator setup."""
import hmac
import json
import re
import secrets
import urllib.request
import urllib.error
from flask import request, session, abort, jsonify, redirect, url_for, flash, current_app
from cryptography.fernet import InvalidToken
import app as base
import ultramsg_suite as ultra


def schema():
    c = base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS whapi_config(
      id INTEGER PRIMARY KEY CHECK(id=1), channel TEXT NOT NULL DEFAULT '',
      token TEXT NOT NULL DEFAULT '', hook TEXT NOT NULL DEFAULT '',
      phone TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 0);
      INSERT OR IGNORE INTO whapi_config(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS whapi_acks(provider_id TEXT PRIMARY KEY,status TEXT NOT NULL);
    ''')
    c.commit(); c.close()


def config():
    c = base.db()
    row = dict(c.execute('SELECT * FROM whapi_config WHERE id=1').fetchone()); c.close()
    if row['token']:
        try: row['token'] = ultra.cipher().decrypt(row['token'].encode()).decode()
        except (InvalidToken, ValueError): row['token'] = ''
    return row


def enabled():
    c = base.db()
    try: return bool(c.execute('SELECT active FROM whapi_config WHERE id=1').fetchone()[0])
    finally: c.close()


class APIError(Exception): pass


def api(path, values=None, cfg=None, method=None):
    cfg = cfg or config()
    if not cfg.get('token'): raise APIError('Falta el token de Whapi.Cloud.')
    req = urllib.request.Request('https://gate.whapi.cloud/' + path,
        data=json.dumps(values).encode() if values is not None else None,
        method=method or ('POST' if values is not None else 'GET'),
        headers={'Authorization': 'Bearer ' + cfg['token'], 'Accept': 'application/json', 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(ultra.NoRedirect).open(req, timeout=20) as response:
            result = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        hint = {401: 'Revisa el token y la vinculación del teléfono.', 402: 'Revisa los límites de tu prueba o plan.',
                403: 'Whapi rechazó el acceso o el destinatario.', 429: 'Espera antes de intentar otra vez.'}.get(exc.code, 'Revisa el estado de tu canal.')
        raise APIError('Whapi.Cloud: HTTP ' + str(exc.code) + '. ' + hint) from None
    except Exception:
        raise APIError('No se pudo confirmar la respuesta de Whapi.Cloud. Revisa su panel antes de reenviar para evitar duplicados.') from None
    if not isinstance(result, dict) or result.get('error') or result.get('errors'):
        raise APIError('Whapi.Cloud no aceptó la solicitud. Revisa el estado de tu canal.')
    return result


def send_text(phone, body):
    cfg = config()
    try:
        result = api('messages/text', {'to': phone, 'body': body[:4096]}, cfg)
        msg = result.get('message') or {}
        if result.get('sent') is not True or not isinstance(msg, dict) or not msg.get('id'):
            raise APIError('Whapi no confirmó la aceptación. Revisa su panel antes de reenviar.')
        return True, 'whapi:' + cfg['channel'] + ':' + str(msg['id']), ''
    except APIError as exc: return False, '', str(exc)


def confirmed_status(c, pid, default):
    row = c.execute('SELECT status FROM whapi_acks WHERE provider_id=?', (pid,)).fetchone()
    return row['status'] if row else default


def settings():
    import whatsapp_suite as wa
    if not base.logged_in(): abort(401)
    if session.get('role', 'ADMIN') != 'ADMIN': abort(403)
    cfg = config()
    if request.method == 'POST':
        if not session.get('whapi_csrf') or not hmac.compare_digest(session['whapi_csrf'], request.form.get('csrf', '')): abort(403)
        try:
            if request.form.get('action') == 'meta':
                c = base.db()
                c.execute('UPDATE whapi_config SET active=0'); c.execute('UPDATE ultramsg_config SET active=0')
                c.commit(); c.close(); flash('El envío vuelve a utilizar Meta.')
                return redirect(url_for('whapi_settings'))
            token = request.form.get('token', '').strip() or cfg['token']
            if not token or any(x.isspace() for x in token): raise ValueError('Pega únicamente el token de Whapi.Cloud.')
            encrypted = ultra.cipher().encrypt(token.encode()).decode()
            new = {'token': token}
            health = api('health', cfg=new)
            if (health.get('status') or {}).get('text') != 'AUTH':
                raise ValueError('Vincula primero tu teléfono mediante el QR en Whapi.Cloud.')
            channel = health.get('channel_id', '')
            if not isinstance(channel, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,100}', channel):
                raise ValueError('Whapi no devolvió un canal válido.')
            hook = cfg['hook'] or secrets.token_urlsafe(32)
            callback = url_for('whapi_webhook', _external=True, _scheme='https')
            previous = api('settings', cfg=new)
            hooks = previous.get('webhooks') or []
            if not isinstance(hooks, list): raise ValueError('No se pudieron leer los webhooks del canal.')
            desired = {'url': callback, 'mode': 'body', 'headers': {'X-Interflash-Key': hook},
                       'events': [{'type': t, 'method': m} for t in ('messages', 'statuses') for m in ('post', 'put')]}
            hooks = [item for item in hooks if item.get('url') != callback] + [desired]
            api('settings', {'webhooks': hooks}, new, method='PATCH')
            verified = api('settings', cfg=new)
            if not any(item.get('url') == callback and item.get('headers', {}).get('X-Interflash-Key') == hook
                       and item.get('mode') == 'body' and all(e in item.get('events', []) for e in desired['events'])
                       for item in verified.get('webhooks', [])):
                raise ValueError('No se pudo verificar la recepción. El proveedor de envío no se cambió.')
            phone = str((health.get('user') or {}).get('id', '')).split('@')[0]
            if not re.fullmatch(r'[1-9][0-9]{7,14}', phone): phone = ''
            c = base.db()
            c.execute('UPDATE whapi_config SET channel=?,token=?,hook=?,phone=?,active=1 WHERE id=1', (channel, encrypted, hook, phone))
            c.execute('UPDATE ultramsg_config SET active=0 WHERE id=1'); c.commit(); c.close()
            flash('Whapi.Cloud configurado. Falta comprobar un envío y un mensaje entrante real.')
        except (ValueError, APIError) as exc: flash(str(exc))
        return redirect(url_for('whapi_settings'))
    csrf = session.setdefault('whapi_csrf', secrets.token_urlsafe(32))
    body = f'''<div class="head"><div><h1>Conectar Whapi.Cloud</h1><p>Conecta a INTER Flash el WhatsApp que vinculaste por QR.</p></div><a class="btn" href="/whatsapp">Volver a WhatsApp</a></div>
    <div class="panel"><b>Proveedor de envío: {wa.esc(wa._provider_label())}</b><p>En el panel de Whapi.Cloud copia el campo Token y pégalo aquí.</p>
    <form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}">
    <label>Token de Whapi.Cloud<input type="password" name="token" autocomplete="new-password" placeholder="{'Guardado; deja vacío para conservarlo' if cfg['token'] else 'Pega aquí el token de Whapi.Cloud'}"></label>
    <p>El token se guarda cifrado. Al conectar se comprueba el canal y se configura la recepción automáticamente.</p>
    <button class="btn green" name="action" value="save">Comprobar y conectar Whapi.Cloud</button></form>
    <p>Canal: {wa.esc(cfg['channel'] or 'Sin configurar')} · Número: {wa.esc(cfg['phone'] or 'Se detecta al conectar')}</p></div>
    <div class="panel"><p>Envía y recibe texto. Los archivos entrantes aparecen como avisos; no se descargan. Se aplican los límites de tu plan de Whapi.Cloud.</p>
    <form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}"><button class="btn" name="action" value="meta">Usar Meta para enviar</button></form></div>'''
    response = current_app.make_response(base.shell('Whapi.Cloud', body, 'whatsapp_inbox'))
    response.headers['Cache-Control'] = 'no-store'; response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def webhook():
    import whatsapp_suite as wa
    cfg = config()
    if not cfg['hook'] or not hmac.compare_digest(cfg['hook'], request.headers.get('X-Interflash-Key', '')): abort(403)
    if request.content_length and request.content_length > 1_000_000: abort(413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict): abort(400)
    if payload.get('channel_id') != cfg['channel']: abort(403)
    for key in ('messages', 'statuses'):
        if key in payload and (not isinstance(payload[key], list) or any(not isinstance(x, dict) for x in payload[key])): abort(400)
    event = payload.get('event') or {}
    if not isinstance(event, dict): abort(400)
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if event.get('type') == 'messages' and event.get('method') in ('post', 'put'):
            for msg in payload.get('messages', []):
                if msg.get('from_me') is not False: continue
                chat = str(msg.get('chat_id', ''))
                if not re.fullmatch(r'[1-9][0-9]{7,14}@(s\.whatsapp\.net|c\.us|lid)', chat): continue
                # LID identifiers are not phone numbers. Only use Whapi's explicit phone for those.
                phone = str(msg.get('phone', '')).lstrip('+') if chat.endswith('@lid') else chat.split('@')[0]
                if not re.fullmatch(r'[1-9][0-9]{7,14}', phone): continue
                mid = msg.get('id')
                if not isinstance(mid, str) or not mid: continue
                pid = 'whapi:' + cfg['channel'] + ':in:' + mid
                if c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?', (pid,)).fetchone(): continue
                customer = wa._customer_by_phone(c, phone)
                t = wa._thread_for_phone(c, phone, customer['name'] if customer else str(msg.get('from_name') or '')[:150], customer['id'] if customer else None)
                content = msg.get('text') or {}
                body = str(content.get('body') or '[Archivo o mensaje sin texto]')[:16000] if isinstance(content, dict) else '[Archivo o mensaje sin texto]'
                c.execute("INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,created_at) VALUES(?,'IN',?,?,?,'RECIBIDO',?)", (t['id'], str(msg.get('type', 'text'))[:40], body, pid, wa._now()))
                c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=?,unread=unread+1 WHERE id=?', (body[:500], wa._now(), t['id']))
                c.execute('UPDATE whatsapp_webhook_health SET last_event=?,last_incoming=? WHERE id=1', (wa._now(), wa._now()))
        if event.get('type') == 'statuses' and event.get('method') in ('post', 'put'):
            ranks = {'ACEPTADO': 0, 'ERROR': 1, 'ENVIADO': 2, 'ENTREGADO': 3, 'LEÍDO': 4}
            for status in payload.get('statuses', []):
                mapped = {'pending': 'ACEPTADO', 'failed': 'ERROR', 'sent': 'ENVIADO', 'delivered': 'ENTREGADO', 'read': 'LEÍDO', 'played': 'LEÍDO'}.get(status.get('status'))
                if not mapped or not isinstance(status.get('id'), str) or not status['id']: continue
                pid = 'whapi:' + cfg['channel'] + ':' + status['id']
                old = confirmed_status(c, pid, 'ACEPTADO')
                if ranks[mapped] < ranks[old]: continue
                c.execute('INSERT INTO whapi_acks(provider_id,status) VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET status=excluded.status', (pid, mapped))
                c.execute('UPDATE whatsapp_messages SET status=? WHERE provider_id=?', (mapped, pid))
                c.execute('UPDATE whatsapp_queue SET status=? WHERE provider_id=?', (mapped, pid))
        c.commit()
    except Exception as exc:
        c.rollback(); current_app.logger.error('Whapi callback failed type=%s', type(exc).__name__)
        return jsonify(error='No se pudo guardar el evento'), 500
    finally: c.close()
    return jsonify(ok=True)


def setup(app):
    schema()
    app.add_url_rule('/whatsapp/whapi', endpoint='whapi_settings', view_func=settings, methods=['GET', 'POST'])
    app.add_url_rule('/webhooks/whapi', endpoint='whapi_webhook', view_func=webhook, methods=['POST'])
