"""WAHA text transport with encrypted credentials and authenticated callbacks."""
import hmac
import ipaddress
import json
import re
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from flask import abort, current_app, flash, jsonify, redirect, request, session, url_for
from cryptography.fernet import InvalidToken
import app as base
import ultramsg_suite as ultra

class APIError(ValueError):
    pass

def schema():
    c=base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS waha_config (
      id INTEGER PRIMARY KEY CHECK(id=1), api_url TEXT NOT NULL DEFAULT '',
      token TEXT NOT NULL DEFAULT '', session_name TEXT NOT NULL DEFAULT 'default',
      hook TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 0);
      INSERT OR IGNORE INTO waha_config(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS waha_acks(provider_id TEXT PRIMARY KEY,status TEXT NOT NULL);
    ''')
    c.commit();c.close()

def config():
    c=base.db();row=dict(c.execute('SELECT * FROM waha_config WHERE id=1').fetchone());c.close()
    if row['token']:
        try:row['token']=ultra.cipher().decrypt(row['token'].encode()).decode()
        except (InvalidToken,ValueError):row['token']=''
    return row

def enabled():
    c=base.db()
    try:return bool(c.execute('SELECT active FROM waha_config WHERE id=1').fetchone()[0])
    finally:c.close()

def validate(cfg):
    parsed=urllib.parse.urlsplit(cfg['api_url'])
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or parsed.port not in (None,443):
        raise APIError('Introduce la dirección HTTPS del túnel de WAHA, sin /dashboard ni /api.')
    try:
        addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise APIError('Railway necesita una dirección pública HTTPS; localhost pertenece a tu computadora.')
    except socket.gaierror:
        raise APIError('No se pudo resolver la dirección de WAHA.') from None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',cfg['session_name']):raise APIError('Revisa el nombre de sesión, normalmente default.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,256}',cfg['token']):raise APIError('Pega la API key de WAHA.')

def api(path,values=None,cfg=None,method=None):
    cfg=cfg or config();validate(cfg)
    req=urllib.request.Request(cfg['api_url'].rstrip('/')+path,
        data=json.dumps(values).encode() if values is not None else None,
        method=method or ('POST' if values is not None else 'GET'),
        headers={'X-Api-Key':cfg['token'],'Content-Type':'application/json','Accept':'application/json'})
    try:
        with urllib.request.build_opener(ultra.NoRedirect).open(req,timeout=20) as response:
            result=json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        raise APIError('WAHA respondió HTTP '+str(exc.code)+'. Revisa el túnel, la clave y la sesión.') from None
    except Exception:
        raise APIError('No se confirmó la respuesta de WAHA. Comprueba el chat antes de reenviar para evitar duplicados.') from None
    if not isinstance(result,(dict,list)):raise APIError('WAHA devolvió una respuesta inválida.')
    return result

def send_text(phone,body):
    cfg=config()
    if not re.fullmatch(r'[1-9][0-9]{7,14}',phone):return False,'','Número de teléfono inválido.'
    try:
        result=api('/api/sendText',{'session':cfg['session_name'],'chatId':phone+'@c.us','text':body[:4096]},cfg)
        mid=result.get('id')
        if not isinstance(mid,str) or not mid:raise APIError('WAHA no confirmó el mensaje. Comprueba el chat antes de reenviar.')
        return True,'waha:'+cfg['session_name']+':'+mid,''
    except APIError as exc:return False,'',str(exc)

def confirmed_status(c,pid,default):
    row=c.execute('SELECT status FROM waha_acks WHERE provider_id=?',(pid,)).fetchone()
    return row['status'] if row else default

def settings():
    import whatsapp_suite as wa
    if not base.logged_in():abort(401)
    if session.get('role','ADMIN')!='ADMIN':abort(403)
    cfg=config()
    if request.method=='POST':
        if not session.get('waha_csrf') or not hmac.compare_digest(session['waha_csrf'],request.form.get('csrf','')):abort(403)
        try:
            if request.form.get('action')=='disconnect':
                c=base.db();c.execute('UPDATE waha_config SET active=0');c.commit();c.close()
                flash('WAHA desconectado de la plataforma.');return redirect(url_for('waha_settings'))
            new={'api_url':request.form.get('api_url','').strip().rstrip('/'),'token':request.form.get('token','').strip() or cfg['token'],'session_name':request.form.get('session_name','default').strip()}
            validate(new)
            state=api('/api/sessions/'+new['session_name'],cfg=new)
            if not isinstance(state,dict) or state.get('status')!='WORKING':raise APIError('La sesión de WAHA debe mostrar WORKING antes de conectar.')
            hook=cfg['hook'] or secrets.token_urlsafe(32)
            callback=url_for('waha_webhook',_external=True,_scheme='https')
            remote=state.get('config') or {}
            if not isinstance(remote,dict):raise APIError('La configuración de sesión no es válida.')
            remote=dict(remote)
            hooks=remote.get('webhooks') or []
            if not isinstance(hooks,list):raise APIError('La configuración de recepción no es válida.')
            desired={'url':callback,'events':['message','message.ack'],'customHeaders':[{'name':'Authorization','value':'Bearer '+hook}]}
            remote['webhooks']=[h for h in hooks if isinstance(h,dict) and h.get('url')!=callback]+[desired]
            # Persist the callback key before WAHA begins sending events.
            c=base.db();c.execute("UPDATE waha_config SET hook=? WHERE id=1",(hook,));c.commit();c.close()
            api('/api/sessions/'+new['session_name'],{'name':new['session_name'],'config':remote},new,method='PUT')
            verified=api('/api/sessions/'+new['session_name'],cfg=new)
            if not any(isinstance(h,dict) and all(h.get(k)==v for k,v in desired.items()) for h in ((verified.get('config') or {}).get('webhooks') or [])):
                raise APIError('WAHA no confirmó la recepción; el proveedor activo no se cambió.')
            encrypted=ultra.cipher().encrypt(new['token'].encode()).decode()
            c=base.db()
            c.execute('UPDATE waha_config SET api_url=?,token=?,session_name=?,hook=?,active=1 WHERE id=1',(new['api_url'],encrypted,new['session_name'],hook))
            for table in ('greenapi_config','whapi_config','ultramsg_config'):c.execute('UPDATE '+table+' SET active=0')
            c.commit();c.close();flash('WAHA conectado. GREEN-API desactivado. Comprueba un envío desde Inter Flash.')
        except ValueError as exc:flash(str(exc))
        return redirect(url_for('waha_settings'))
    live_state = 'SIN COMPROBAR'
    engine = 'DESCONOCIDO'
    if cfg['active']:
        try:
            state = api('/api/sessions/' + cfg['session_name'], cfg=cfg)
            candidate = state.get('status') if isinstance(state, dict) else None
            live_state = candidate if candidate in ('WORKING','STARTING','SCAN_QR_CODE','FAILED','STOPPED') else 'RESPUESTA INESPERADA'
            raw_engine = state.get('engine', {}) if isinstance(state, dict) else {}
            candidate = raw_engine.get('engine') if isinstance(raw_engine, dict) else raw_engine
            engine = candidate if candidate in ('WEBJS','WPP','GOWS','NOWEB','VENOM') else 'DESCONOCIDO'
        except APIError as exc:
            live_state = str(exc)
    csrf=session.setdefault('waha_csrf',secrets.token_urlsafe(32))
    body=f'''<div class="head"><div><h1>Conectar WAHA</h1><p>Usa el WhatsApp que vinculaste en tu computadora.</p></div><a class="btn" href="/whatsapp">Volver a WhatsApp</a></div>
    <div class="panel"><p>Configuración: {'ACTIVA' if cfg['active'] else 'PENDIENTE'}.</p><p>Estado comprobado: {wa.esc(live_state)}.</p><p>Motor WAHA: {wa.esc(engine)}.</p><p>La dirección local http://localhost:3000 funciona en tu PC. Para conectarla con esta plataforma necesitas su dirección pública HTTPS mediante un túnel.</p>
    <form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}">
    <label>Dirección HTTPS de WAHA<input name="api_url" type="url" value="{wa.esc(cfg['api_url'])}" placeholder="https://tu-tunel.trycloudflare.com" required></label>
    <label>Sesión<input name="session_name" value="{wa.esc(cfg['session_name'])}" required></label>
    <label>API key<input type="password" name="token" autocomplete="new-password" placeholder="{'Guardada; deja vacío para conservarla' if cfg['token'] else 'Pega la API key de WAHA'}"></label>
    <p>La clave se guarda cifrada. Al comprobar la conexión, WAHA sustituye a GREEN-API para los envíos nuevos.</p><button class="btn green">Comprobar y conectar WAHA</button></form></div>'''
    if cfg['active']:
        body+=f'''<div class="panel"><form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}"><button class="btn" name="action" value="disconnect">Desconectar WAHA</button></form></div>'''
    response=current_app.make_response(base.shell('WAHA',body,'whatsapp_inbox'))
    response.headers['Cache-Control']='no-store';return response


def incoming_phone(data,cfg):
    """Resolve only a verified direct sender; never treat a LID as a phone."""
    chat=str(data.get('from') or '')
    match=re.fullmatch(r'([1-9][0-9]{7,14})@(c\.us|s\.whatsapp\.net)',chat)
    if match:
        return match.group(1)
    if not re.fullmatch(r'[0-9]{1,32}@lid',chat):
        return None
    result=api('/api/'+urllib.parse.quote(cfg['session_name'],safe='')+
               '/lids/'+urllib.parse.quote(chat,safe=''),cfg=cfg)
    if not isinstance(result,dict) or result.get('lid') not in (chat,chat.split('@')[0]):
        raise APIError('LID_NO_VERIFICADO')
    pn=str(result.get('pn') or '')
    match=re.fullmatch(r'([1-9][0-9]{7,14})@(c\.us|s\.whatsapp\.net)',pn)
    if not match:
        raise APIError('LID_SIN_TELEFONO')
    return match.group(1)

def webhook():
    import whatsapp_suite as wa
    cfg=config()
    if not cfg['active'] or not cfg['hook'] or not hmac.compare_digest('Bearer '+cfg['hook'],request.headers.get('Authorization','')):abort(403)
    if request.content_length and request.content_length>1_000_000:abort(413)
    event=request.get_json(silent=True)
    if not isinstance(event,dict) or event.get('session')!=cfg['session_name']:abort(400)
    data=event.get('payload')
    if not isinstance(data,dict):abort(400)
    mid=data.get('id')
    if not isinstance(mid,str) or not mid:return jsonify(ok=True)
    pid='waha:'+cfg['session_name']+':'+mid
    phone=None
    is_incoming=event.get('event') in ('message','message.any') and data.get('fromMe') is False
    if is_incoming:
        chat=str(data.get('from') or '')
        suffix=chat.rsplit('@',1)[-1]
        kind=suffix if suffix in ('c.us','s.whatsapp.net','lid','g.us','broadcast','newsletter') else 'otro'
        current_app.logger.warning('WAHA_RX kind=%s',kind)
        try:
            # Resolve before taking a database write lock.
            phone=incoming_phone(data,cfg)
        except APIError:
            current_app.logger.warning('WAHA_RX_UNRESOLVED kind=%s',kind)
            return jsonify(error='No se pudo verificar el remitente'),503
        if not phone:
            current_app.logger.warning('WAHA_RX_IGNORED kind=%s',kind)
    c=base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if is_incoming:
            if phone and not c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?',(pid,)).fetchone():
                customer=wa._customer_by_phone(c,phone)
                t=wa._thread_for_phone(c,phone,customer['name'] if customer else phone,customer['id'] if customer else None)
                body=str(data.get('body') or '[Archivo o mensaje sin texto]')[:16000]
                c.execute("INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,created_at) VALUES(?,'IN','text',?,?,'RECIBIDO',?)",(t['id'],body,pid,wa._now()))
                c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=?,unread=unread+1 WHERE id=?',(body[:500],wa._now(),t['id']))
                c.execute('UPDATE whatsapp_webhook_health SET last_event=?,last_incoming=? WHERE id=1',(wa._now(),wa._now()))
        elif event.get('event')=='message.ack' and data.get('fromMe') is True:
            mapped={1:'ENVIADO',2:'ENTREGADO',3:'LEÍDO',4:'LEÍDO'}.get(data.get('ack'))
            ranks={'ACEPTADO':0,'ENVIADO':1,'ENTREGADO':2,'LEÍDO':3}
            if mapped and ranks[mapped]>=ranks.get(confirmed_status(c,pid,'ACEPTADO'),0):
                c.execute('INSERT INTO waha_acks VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET status=excluded.status',(pid,mapped))
                c.execute('UPDATE whatsapp_messages SET status=? WHERE provider_id=?',(mapped,pid))
                c.execute('UPDATE whatsapp_queue SET status=? WHERE provider_id=?',(mapped,pid))
        c.commit()
    except Exception as exc:
        current_app.logger.error('WAHA_RX_SAVE_ERROR type=%s',type(exc).__name__)
        c.rollback();return jsonify(error='No se pudo guardar el evento'),500
    finally:c.close()
    return jsonify(ok=True)

def setup(app):
    schema()
    app.add_url_rule('/whatsapp/waha',endpoint='waha_settings',view_func=settings,methods=['GET','POST'])
    app.add_url_rule('/webhooks/waha',endpoint='waha_webhook',view_func=webhook,methods=['POST'])
