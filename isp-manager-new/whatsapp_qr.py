"""Optional WAHA bridge. Credentials stay server-side; Meta remains the default."""
import base64
import functools
import hmac
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from flask import abort, jsonify, request, session, url_for, current_app
import app as base

URL = os.getenv('WHATSAPP_QR_URL', '').rstrip('/')
KEY = os.getenv('WHATSAPP_QR_API_KEY', '')
HOOK_KEY = os.getenv('WHATSAPP_QR_WEBHOOK_KEY', '')
PUBLIC_URL = os.getenv('WHATSAPP_QR_CALLBACK_URL', '')
SESSION = 'default'


def enabled():
    return os.getenv('WHATSAPP_PROVIDER', 'meta').lower() == 'waha'


def configured():
    return bool(URL and KEY and HOOK_KEY and PUBLIC_URL.startswith('https://'))


class BridgeError(Exception):
    def __init__(self, status=503):
        self.status = status
        super().__init__('No se pudo consultar la conexión QR. Revisa el servicio e intenta nuevamente.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(path, payload=None, method=None):
    if not configured():
        raise BridgeError()
    req = urllib.request.Request(URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method or ('POST' if payload is not None else 'GET'),
        headers={'X-Api-Key': KEY, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        raise BridgeError(exc.code) from None
    except Exception:
        raise BridgeError() from None


def send_text(phone, body):
    try:
        if api('/api/sessions/default').get('status') != 'WORKING':
            return False, '', 'Vincula tu WhatsApp en Conectar por QR antes de enviar.'
        data = api('/api/sendText', {'session': SESSION, 'chatId': phone + '@c.us', 'text': body[:4096]})
        pid = data.get('id')
        if isinstance(pid, dict):
            pid = pid.get('_serialized')
        if not isinstance(pid, str) or not pid:
            return False, '', 'El servicio no confirmó el envío. Revisa el chat antes de reintentar.'
        return True, 'waha:' + pid, ''
    except BridgeError as exc:
        return False, '', str(exc)


def admin(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        if not base.logged_in():
            abort(401)
        if session.get('role', 'ADMIN') != 'ADMIN':
            abort(403)
        if request.method == 'POST':
            expected = session.get('wa_qr_csrf', '')
            if not expected or not hmac.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
                abort(403)
        result = current_app.make_response(fn(*args, **kwargs))
        result.headers['Cache-Control'] = 'no-store'
        result.headers['Referrer-Policy'] = 'no-referrer'
        return result
    return wrapped


@admin
def page():
    import whatsapp_suite as wa
    token = session.setdefault('wa_qr_csrf', secrets.token_urlsafe(32))
    body = '''<div class="head"><h1>Conectar WhatsApp por QR</h1><a class="btn" href="/whatsapp">Volver al chat</a></div>
    <div class="panel"><p>En tu celular abre WhatsApp → Dispositivos vinculados → Vincular un dispositivo.</p>
    <p>Conexión mediante WAHA, independiente de Meta Cloud API. Puede requerir volver a vincular el teléfono.</p>
    <p id="qr-state" role="status">Consultando conexión…</p><button class="btn green" id="qr-start">Generar QR</button>
    <div><img id="qr-image" hidden alt="Código QR para vincular WhatsApp" width="280" style="background:white;padding:12px;margin:16px 0;max-width:100%"></div>
    <label>O vincular con tu número, incluyendo código de país:</label><div class="toolbar"><input class="field" id="qr-phone" inputmode="tel" placeholder="1809…"><button class="btn" id="qr-code">Obtener código</button></div>
    <p id="qr-pair" style="font-size:28px;font-weight:bold" aria-live="polite"></p>
    <p>Para usar el código, elige «Vincular con número de teléfono» en WhatsApp. Si no está disponible, utiliza el QR.</p>
    </div><script>
    (() => {
      const csrf = CSRF_VALUE, state = document.getElementById('qr-state'), img = document.getElementById('qr-image');
      let busy = false, linked = false;
      async function call(action, body) {
        const response = await fetch('/whatsapp/qr/' + action, {method:body ? 'POST':'GET',cache:'no-store',
          headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body ? JSON.stringify(body):undefined});
        const data = await response.json(); if (!response.ok) throw new Error(data.error || 'No se pudo completar la solicitud.'); return data;
      }
      async function refresh() {
        if (busy || document.hidden) return; busy = true;
        try {
          const data = await call('status'); state.textContent = data.label; linked = data.status === 'WORKING';
          img.hidden = true;
          if (linked) document.getElementById('qr-pair').textContent = '';
          if (data.status === 'SCAN_QR_CODE') {const qr = await call('image'); img.src = qr.image; img.hidden = false;}
          document.getElementById('qr-start').disabled = linked || !data.configured;
          document.getElementById('qr-code').disabled = data.status !== 'SCAN_QR_CODE';
        } catch (e) {state.textContent = e.message; img.hidden = true;} finally {busy = false;}
      }
      async function action(name, body) {
        if (busy) return; busy = true;
        try {const data = await call(name, body); if (data.code) document.getElementById('qr-pair').textContent = data.code;
          state.textContent = data.code ? 'Introduce este código en tu celular.' : 'Preparando QR…';
        } catch(e) {state.textContent=e.message;} finally {busy=false;}
        if(name === 'start') refresh();
      }
      document.getElementById('qr-start').onclick=()=>action('start',{});
      document.getElementById('qr-code').onclick=()=>action('code',{phone:document.getElementById('qr-phone').value});
      refresh(); setInterval(refresh,10000);
    })();</script>'''.replace('CSRF_VALUE', json.dumps(token))
    return base.shell('Conectar WhatsApp', body, 'whatsapp_inbox')


@admin
def control(action):
    try:
        if action == 'status' and request.method == 'GET':
            if not configured():
                return jsonify(status='NOT_CONFIGURED', configured=False, label='Pendiente de activar el servicio de vinculación QR.')
            try:
                data = api('/api/sessions/default')
            except BridgeError as exc:
                if exc.status != 404: raise
                data = {'status': 'STOPPED'}
            status = data.get('status', 'UNKNOWN')
            labels = {'WORKING':'WhatsApp vinculado.', 'STARTING':'Iniciando conexión…', 'STOPPED':'Pulsa Generar QR para comenzar.',
                'SCAN_QR_CODE':'Escanea el QR con tu celular.', 'FAILED':'La conexión falló. Revisa el servicio antes de reintentar.'}
            label = labels.get(status, 'La conexión necesita revisión: ' + str(status))
            if status == 'WORKING' and not enabled():
                label += ' El envío todavía está configurado con Meta.'
            return jsonify(status=status, configured=True, label=label)
        if action == 'image' and request.method == 'GET':
            data = api('/api/default/auth/qr?format=image')
            raw = base64.b64decode(data.get('data', ''), validate=True)
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'): raise BridgeError()
            return jsonify(image='data:image/png;base64,' + base64.b64encode(raw).decode())
        if action == 'start' and request.method == 'POST':
            try:
                data = api('/api/sessions/default')
            except BridgeError as exc:
                if exc.status != 404: raise
                data = api('/api/sessions', {'name':SESSION, 'config':{'webhooks':[{
                    'url':PUBLIC_URL, 'events':['message','message.ack'],
                    'customHeaders':[{'name':'X-Interflash-Webhook','value':HOOK_KEY}],
                    'retries':{'policy':'constant','delaySeconds':3,'attempts':10}
                }]}})
            if data.get('status') == 'STOPPED': api('/api/sessions/default/start', {})
            return jsonify(ok=True)
        if action == 'code' and request.method == 'POST':
            payload = request.get_json(silent=True)
            phone = re.sub(r'[^0-9]', '', str(payload.get('phone', ''))) if isinstance(payload, dict) else ''
            if not re.fullmatch(r'[1-9][0-9]{7,14}', phone):
                return jsonify(error='Introduce el número completo con código de país.'),400
            data = api('/api/default/auth/request-code', {'phoneNumber':phone})
            code = data.get('code')
            if not isinstance(code,str) or len(code)>32: raise BridgeError()
            return jsonify(code=code)
        abort(404)
    except (BridgeError, ValueError) as exc:
        return jsonify(error=str(exc) if isinstance(exc, BridgeError) else 'Respuesta QR no válida.'),502


def webhook():
    import whatsapp_suite as wa
    if not HOOK_KEY or not hmac.compare_digest(HOOK_KEY, request.headers.get('X-Interflash-Webhook', '')):
        abort(403)
    if request.content_length and request.content_length > 1_000_000: abort(413)
    data = request.get_json(silent=True)
    if not isinstance(data,dict) or not isinstance(data.get('payload'),dict): abort(400)
    if data.get('session') != SESSION: abort(400)
    payload=data['payload']; event=data.get('event'); pid=payload.get('id')
    if not isinstance(pid,str) or not pid: return jsonify(ok=True,ignored=True)
    pid='waha:'+pid
    wa.ensure_schema(); c=base.db()
    try:
        if event == 'message' and not payload.get('fromMe'):
            sender=str(payload.get('from',''))
            # Hidden IDs must not be mistaken for a customer's phone number.
            if not re.fullmatch(r'[1-9][0-9]{7,14}@c\.us',sender):
                return jsonify(ok=True,ignored=True)
            phone=sender.split('@')[0]
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?',(pid,)).fetchone():
                customer=wa._customer_by_phone(c,phone)
                thread=wa._thread_for_phone(c,phone,customer['name'] if customer else '',customer['id'] if customer else None)
                body=str(payload.get('body') or ('[Archivo recibido]' if payload.get('hasMedia') else '[Mensaje]'))[:16000]
                c.execute("INSERT INTO whatsapp_messages(thread_id,direction,body,provider_id,status,created_at) VALUES(?,'IN',?,?,'RECIBIDO',?)",(thread['id'],body,pid,wa._now()))
                c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=?,unread=unread+1 WHERE id=?',(body[:500],wa._now(),thread['id']))
                c.execute('UPDATE whatsapp_webhook_health SET last_event=?,last_incoming=? WHERE id=1',(wa._now(),wa._now()))
        elif event == 'message.ack':
            mapped={1:'ENVIADO',2:'ENTREGADO',3:'LEÍDO',4:'LEÍDO',-1:'ERROR'}.get(payload.get('ack'))
            if mapped:
                rank={'ACEPTADO':0,'ENVIADO':1,'ENTREGADO':2,'LEÍDO':3}
                old=c.execute('SELECT status FROM whatsapp_messages WHERE provider_id=?',(pid,)).fetchone()
                if old and (mapped=='ERROR' or rank.get(mapped,0)>=rank.get(old['status'],0)):
                    c.execute('UPDATE whatsapp_messages SET status=? WHERE provider_id=?',(mapped,pid))
                    c.execute('UPDATE whatsapp_queue SET status=? WHERE provider_id=?',(mapped,pid))
        c.commit()
    except Exception as exc:
        c.rollback(); current_app.logger.error('QR webhook failed type=%s',type(exc).__name__)
        return jsonify(error='No se pudo guardar el mensaje'),500
    finally:
        c.close()
    return jsonify(ok=True)


def setup(app):
    app.add_url_rule('/whatsapp/qr', 'whatsapp_qr_page', page)
    app.add_url_rule('/whatsapp/qr/<action>', 'whatsapp_qr_control', control, methods=['GET','POST'])
    app.add_url_rule('/webhooks/whatsapp-qr', 'whatsapp_qr_webhook', webhook, methods=['POST'])
