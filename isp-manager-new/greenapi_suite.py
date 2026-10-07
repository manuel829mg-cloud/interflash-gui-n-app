"""GREEN-API text adapter, private callbacks and administrator setup."""
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
    c.executescript('''CREATE TABLE IF NOT EXISTS greenapi_config(
      id INTEGER PRIMARY KEY CHECK(id=1), channel TEXT NOT NULL DEFAULT '',
      token TEXT NOT NULL DEFAULT '', hook TEXT NOT NULL DEFAULT '',
      phone TEXT NOT NULL DEFAULT '', api_url TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 0);
      INSERT OR IGNORE INTO greenapi_config(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS greenapi_acks(provider_id TEXT PRIMARY KEY,status TEXT NOT NULL);
    ''')
    c.commit(); c.close()


def config():
    c = base.db()
    row = dict(c.execute('SELECT * FROM greenapi_config WHERE id=1').fetchone()); c.close()
    if row['token']:
        try: row['token'] = ultra.cipher().decrypt(row['token'].encode()).decode()
        except (InvalidToken, ValueError): row['token'] = ''
    return row


def enabled():
    c = base.db()
    try: return bool(c.execute('SELECT active FROM greenapi_config WHERE id=1').fetchone()[0])
    finally: c.close()


class APIError(Exception): pass


def validate(cfg):
    if not re.fullmatch(r'[0-9]{4,15}', cfg.get('channel', '')):
        raise APIError('Introduce el idInstance de GREEN-API.')
    if not re.fullmatch(r'https://[0-9]{4,8}\.api\.greenapi\.com', cfg.get('api_url', '')):
        raise APIError('Copia apiUrl de GREEN-API, por ejemplo https://7107.api.greenapi.com.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', cfg.get('token', '')):
        raise APIError('Pega únicamente apiTokenInstance de GREEN-API.')


def api(path, values=None, cfg=None):
    cfg = cfg or config(); validate(cfg)
    url = cfg['api_url'] + '/waInstance' + cfg['channel'] + '/' + path + '/' + cfg['token']
    req = urllib.request.Request(url, data=json.dumps(values).encode() if values is not None else None,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(ultra.NoRedirect).open(req, timeout=20) as response:
            result = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        raise APIError('GREEN-API rechazó la solicitud (HTTP ' + str(exc.code) + '). Revisa la instancia, el token y los límites del plan.') from None
    except Exception:
        # Provider URLs contain the credential: never return or log exception strings.
        raise APIError('No se pudo confirmar la respuesta de GREEN-API. Revisa su panel antes de reenviar para evitar duplicados.') from None
    if not isinstance(result, dict) or result.get('error'):
        raise APIError('GREEN-API no aceptó la solicitud.')
    return result


def send_text(phone, body):
    cfg = config()
    try:
        result = api('sendMessage', {'chatId': phone + '@c.us', 'message': body[:4096]}, cfg)
        mid = result.get('idMessage')
        if not isinstance(mid, str) or not mid:
            raise APIError('GREEN-API no confirmó la aceptación. Revisa su panel antes de reenviar.')
        return True, 'greenapi:' + cfg['channel'] + ':' + mid, ''
    except APIError as exc: return False, '', str(exc)


def confirmed_status(c, pid, default):
    row = c.execute('SELECT status FROM greenapi_acks WHERE provider_id=?', (pid,)).fetchone()
    return row['status'] if row else default


def settings():
    import whatsapp_suite as wa
    if not base.logged_in(): abort(401)
    if session.get('role', 'ADMIN') != 'ADMIN': abort(403)
    cfg = config()
    if request.method == 'POST':
        if not session.get('greenapi_csrf') or not hmac.compare_digest(session['greenapi_csrf'], request.form.get('csrf', '')): abort(403)
        try:
            if request.form.get('action') == 'meta':
                c = base.db()
                c.execute('UPDATE greenapi_config SET active=0'); c.execute('UPDATE ultramsg_config SET active=0'); c.execute('UPDATE whapi_config SET active=0')
                c.commit(); c.close(); flash('El envío vuelve a utilizar Meta.')
                return redirect(url_for('greenapi_settings'))
            token = request.form.get('token', '').strip() or cfg['token']
            instance = request.form.get('instance', '').strip()
            api_url = request.form.get('api_url', '').strip().rstrip('/')
            new = {'token': token, 'channel': instance, 'api_url': api_url}
            validate(new)
            encrypted = ultra.cipher().encrypt(token.encode()).decode()
            state = api('getStateInstance', cfg=new)
            if state.get('stateInstance') != 'authorized':
                raise ValueError('Vincula primero tu teléfono mediante el QR en GREEN-API.')
            hook = cfg['hook'] or secrets.token_urlsafe(32)
            # Keep the callback key stable while provider settings propagate.
            c = base.db(); c.execute("UPDATE greenapi_config SET hook=? WHERE id=1 AND hook=''", (hook,)); c.commit(); c.close()
            hook = config()['hook']
            callback = url_for('greenapi_webhook', _external=True, _scheme='https')
            previous = api('getSettings', cfg=new)
            if previous.get('webhookUrl') and previous['webhookUrl'] != callback:
                raise ValueError('Esta instancia ya tiene otro webhook. Usa una instancia dedicada o retira esa conexión en GREEN-API antes de conectar.')
            desired = {'webhookUrl': callback, 'webhookUrlToken': 'Bearer ' + hook,
                       'incomingWebhook': 'yes', 'outgoingWebhook': 'yes',
                       'outgoingAPIMessageWebhook': 'yes', 'outgoingMessageWebhook': 'yes'}
            result = api('setSettings', desired, new)
            if result.get('saveSettings') is not True:
                raise ValueError('GREEN-API no confirmó que guardó la recepción.')
            verified = api('getSettings', cfg=new)
            if not all(verified.get(k) == v for k, v in desired.items()):
                raise ValueError('Los ajustes aún no se confirman. Espera un minuto y vuelve a conectar; el proveedor no se cambió.')
            phone = str(verified.get('wid') or '').split('@')[0]
            if not re.fullmatch(r'[1-9][0-9]{7,14}', phone): phone = ''
            c = base.db()
            c.execute('UPDATE greenapi_config SET channel=?,api_url=?,token=?,hook=?,phone=?,active=1 WHERE id=1', (instance, api_url, encrypted, hook, phone))
            c.execute('UPDATE ultramsg_config SET active=0'); c.execute('UPDATE whapi_config SET active=0')
            c.commit(); c.close()
            flash('GREEN-API configurado. Falta comprobar un envío y un mensaje entrante real.')
        except (ValueError, APIError) as exc: flash(str(exc))
        return redirect(url_for('greenapi_settings'))
    csrf = session.setdefault('greenapi_csrf', secrets.token_urlsafe(32))
    body = f'''<div class="head"><div><h1>Conectar GREEN-API</h1><p>Conecta a INTER Flash el WhatsApp que vinculaste por QR.</p></div><a class="btn" href="/whatsapp">Volver a WhatsApp</a></div>
    <div class="panel"><b>Proveedor de envío: {wa.esc(wa._provider_label())}</b><p>Copia apiUrl, idInstance y apiTokenInstance del panel de GREEN-API.</p>
    <form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}">
    <label>apiUrl<input name="api_url" value="{wa.esc(cfg['api_url'] or 'https://7107.api.greenapi.com')}" required></label>
    <label>idInstance<input name="instance" value="{wa.esc(cfg['channel'] or '710722758220')}" required></label>
    <label>Token de GREEN-API<input type="password" name="token" autocomplete="new-password" placeholder="{'Guardado; deja vacío para conservarlo' if cfg['token'] else 'Pega aquí el token de GREEN-API'}"></label>
    <p>El token se guarda cifrado. Al conectar se comprueba el canal y se configura la recepción automáticamente.</p>
    <button class="btn green" name="action" value="save">Comprobar y conectar GREEN-API</button></form>
    <p>Canal: {wa.esc(cfg['channel'] or 'Sin configurar')} · Número: {wa.esc(cfg['phone'] or 'Se detecta al conectar')}</p></div>
    <div class="panel"><p>Envía y recibe texto. Los archivos entrantes aparecen como avisos; no se descargan. Se aplican los límites de tu plan de GREEN-API.</p>
</div>'''
    response = current_app.make_response(base.shell('GREEN-API', body, 'whatsapp_inbox'))
    response.headers['Cache-Control'] = 'no-store'; response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def webhook():
    import whatsapp_suite as wa
    cfg = config()
    if not cfg['hook'] or not hmac.compare_digest('Bearer ' + cfg['hook'], request.headers.get('Authorization', '')): abort(403)
    if request.content_length and request.content_length > 1_000_000: abort(413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict): abort(400)
    instance = payload.get('instanceData')
    if not isinstance(instance, dict): abort(400)
    if str(instance.get('idInstance', '')) != cfg['channel']: abort(403)
    kind = payload.get('typeWebhook')
    for key in ('senderData', 'messageData'):
        if key in payload and not isinstance(payload[key], dict): abort(400)
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if kind == 'incomingMessageReceived':
            sender = payload.get('senderData') or {}
            chat = str(sender.get('chatId', ''))
            mid = payload.get('idMessage')
            if re.fullmatch(r'[1-9][0-9]{7,14}@c\.us', chat) and isinstance(mid, str) and mid:
                phone = chat.split('@')[0]; pid = 'greenapi:' + cfg['channel'] + ':in:' + mid
                if not c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?', (pid,)).fetchone():
                    customer = wa._customer_by_phone(c, phone)
                    t = wa._thread_for_phone(c, phone, customer['name'] if customer else str(sender.get('senderName') or '')[:150], customer['id'] if customer else None)
                    data = payload.get('messageData') or {}
                    content = data.get('textMessageData') or data.get('extendedTextMessageData') or {}
                    body = str(content.get('textMessage') or content.get('text') or '[Archivo o mensaje sin texto]')[:16000] if isinstance(content, dict) else '[Archivo o mensaje sin texto]'
                    c.execute("INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,created_at) VALUES(?,'IN',?,?,?,'RECIBIDO',?)", (t['id'], str(data.get('typeMessage', 'textMessage'))[:40], body, pid, wa._now()))
                    c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=?,unread=unread+1 WHERE id=?', (body[:500], wa._now(), t['id']))
                    c.execute('UPDATE whatsapp_webhook_health SET last_event=?,last_incoming=? WHERE id=1', (wa._now(), wa._now()))
        elif kind == 'outgoingMessageStatus' and payload.get('sendByApi') is True:
            mapped = {'sent': 'ENVIADO', 'delivered': 'ENTREGADO', 'read': 'LEÍDO', 'failed': 'ERROR', 'noAccount': 'ERROR', 'suspended': 'ERROR', 'yellowCard': 'ERROR', 'notInGroup': 'ERROR'}.get(payload.get('status'))
            mid = payload.get('idMessage')
            if mapped and isinstance(mid, str) and mid:
                pid = 'greenapi:' + cfg['channel'] + ':' + mid
                ranks = {'ACEPTADO': 0, 'ERROR': 1, 'ENVIADO': 2, 'ENTREGADO': 3, 'LEÍDO': 4}
                old = confirmed_status(c, pid, 'ACEPTADO')
                if ranks[mapped] >= ranks[old]:
                    c.execute('INSERT INTO greenapi_acks(provider_id,status) VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET status=excluded.status', (pid, mapped))
                    c.execute('UPDATE whatsapp_messages SET status=? WHERE provider_id=?', (mapped, pid))
                    c.execute('UPDATE whatsapp_queue SET status=? WHERE provider_id=?', (mapped, pid))
        c.commit()
    except Exception as exc:
        c.rollback(); current_app.logger.error('GREEN-API callback failed type=%s', type(exc).__name__)
        return jsonify(error='No se pudo guardar el evento'), 500
    finally: c.close()
    return jsonify(ok=True)


def setup(app):
    schema()
    app.add_url_rule('/whatsapp/greenapi', endpoint='greenapi_settings', view_func=settings, methods=['GET', 'POST'])
    app.add_url_rule('/webhooks/greenapi', endpoint='greenapi_webhook', view_func=webhook, methods=['POST'])
