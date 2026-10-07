"""UltraMsg adapter. Administrator setup, encrypted credentials and authenticated callbacks."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
import urllib.request
import urllib.parse
import urllib.error
from flask import request, session, abort, jsonify, redirect, url_for, flash, current_app
from cryptography.fernet import Fernet, InvalidToken
import app as base


def schema():
    c=base.db()
    c.executescript('''CREATE TABLE IF NOT EXISTS ultramsg_config(
      id INTEGER PRIMARY KEY CHECK(id=1),instance TEXT NOT NULL DEFAULT '', token TEXT NOT NULL DEFAULT '',
      hook TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 0);
      INSERT OR IGNORE INTO ultramsg_config(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS ultramsg_acks(provider_id TEXT PRIMARY KEY,status TEXT NOT NULL);
    ''')
    c.commit();c.close()


def cipher():
    key=str(current_app.secret_key or '')
    if len(key)<24 or key=='change-this-secret':
        raise ValueError('Configura una SECRET_KEY segura en Railway antes de guardar credenciales.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def config():
    c=base.db();row=dict(c.execute('SELECT * FROM ultramsg_config WHERE id=1').fetchone());c.close()
    row['instance']=row['instance'] or os.getenv('ULTRAMSG_INSTANCE_ID','')
    if row['token']:
        try: row['token']=cipher().decrypt(row['token'].encode()).decode()
        except (InvalidToken,ValueError): row['token']=''
    else: row['token']=os.getenv('ULTRAMSG_TOKEN','')
    return row


def enabled():
    c=base.db()
    try: return bool(c.execute('SELECT active FROM ultramsg_config WHERE id=1').fetchone()[0])
    finally: c.close()


class APIError(Exception): pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def api(path,values=None,cfg=None):
    cfg=cfg or config()
    if not re.fullmatch(r'instance[0-9]+',cfg['instance']) or not cfg['token']:
        raise APIError('Falta el ID de instancia o el token de UltraMsg.')
    params={'token':cfg['token'],**(values or {})}
    url='https://api.ultramsg.com/'+cfg['instance']+'/'+path
    data=None
    if values is None: url+='?'+urllib.parse.urlencode(params)
    else: data=urllib.parse.urlencode(params).encode()
    req=urllib.request.Request(url,data=data,headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as r:
            result=json.loads(r.read(2_000_000))
    except urllib.error.HTTPError as exc:
        raise APIError('UltraMsg rechazó la solicitud (HTTP '+str(exc.code)+'). Comprueba tu instancia y token.') from None
    except Exception:
        raise APIError('No se pudo contactar con UltraMsg. Revisa la conexión antes de reintentar.') from None
    if not isinstance(result,dict) or result.get('error') or result.get('errors'):
        raise APIError('UltraMsg no aceptó la solicitud. Revisa las credenciales y el estado de tu instancia.')
    return result


def auth_state(data):
    value=data.get('status',{})
    if isinstance(value,dict): value=value.get('accountStatus',{})
    if isinstance(value,dict): value=value.get('status','')
    return str(value).lower()


def send_text(phone,body):
    cfg=config()
    try:
        if auth_state(api('instance/status',cfg=cfg))!='authenticated':
            return False,'','Vincula tu WhatsApp en UltraMsg antes de enviar.'
        ref='iflash-'+uuid.uuid4().hex
        data=api('messages/chat',{'to':'+'+phone,'body':body[:4096],'referenceId':ref},cfg)
        if str(data.get('sent','')).lower() not in ('true','1') or not data.get('id'):
            return False,'','UltraMsg no confirmó la aceptación. Revisa su cola antes de reintentar.'
        return True,'ultra:'+cfg['instance']+':'+ref,''
    except APIError as exc: return False,'',str(exc)


def confirmed_status(c,pid,status):
    row=c.execute('SELECT status FROM ultramsg_acks WHERE provider_id=?',(pid,)).fetchone()
    return row['status'] if row else status


def admin_check():
    if not base.logged_in(): abort(401)
    if session.get('role','ADMIN')!='ADMIN': abort(403)
    if request.method=='POST':
        expected=session.get('ultra_csrf','')
        if not expected or not hmac.compare_digest(expected,request.form.get('csrf','')): abort(403)


def settings():
    import whatsapp_suite as wa
    admin_check();cfg=config()
    if request.method=='POST':
        action=request.form.get('action','save')
        try:
            if action=='meta':
                c=base.db();c.execute('UPDATE ultramsg_config SET active=0 WHERE id=1');c.execute('UPDATE whapi_config SET active=0 WHERE id=1');c.execute('UPDATE greenapi_config SET active=0');c.commit();c.close()
                flash('El envío vuelve a utilizar Meta.');return redirect(url_for('ultramsg_settings'))
            instance=request.form.get('instance','').strip()
            if instance.isdigit(): instance='instance'+instance
            token=request.form.get('token','').strip() or cfg['token']
            if not re.fullmatch(r'instance[0-9]+',instance) or not token:
                raise ValueError('Introduce el ID de instancia y su token.')
            ciphertext=cipher().encrypt(token.encode()).decode()
            new={'instance':instance,'token':token}
            state=auth_state(api('instance/status',cfg=new))
            if state!='authenticated': raise ValueError('UltraMsg todavía no está autenticado. Escanea su QR y vuelve a conectar.')
            hook=cfg['hook'] or secrets.token_urlsafe(32)
            callback=url_for('ultramsg_webhook',_external=True,_scheme='https')+'?key='+hook
            previous=api('instance/settings',cfg=new)
            api('instance/settings',{'sendDelay':previous.get('sendDelay',1),'sendDelayMax':previous.get('sendDelayMax',15),
                'webhook_url':callback,'webhook_message_received':'true','webhook_message_ack':'true',
                'webhook_message_create':'false','webhook_message_download_media':'false'},new)
            verify=api('instance/settings',cfg=new)
            if verify.get('webhook_url')!=callback: raise APIError('No se pudo confirmar la recepción en UltraMsg. Intenta conectar nuevamente.')
            c=base.db();c.execute('UPDATE ultramsg_config SET instance=?,token=?,hook=?,active=1 WHERE id=1',(instance,ciphertext,hook));c.execute('UPDATE whapi_config SET active=0 WHERE id=1');c.execute('UPDATE greenapi_config SET active=0');c.commit();c.close()
            flash('UltraMsg conectado. Ya puedes probar el envío y la recepción en tu bandeja.')
        except (ValueError,APIError) as exc: flash(str(exc))
        return redirect(url_for('ultramsg_settings'))
    csrf=session.setdefault('ultra_csrf',secrets.token_urlsafe(32))
    body=f'''<div class="head"><div><h1>Conectar UltraMsg</h1><p>Vincula tu WhatsApp por QR en UltraMsg y conecta esa instancia a INTER Flash.</p></div><a class="btn" href="/whatsapp">Volver a WhatsApp</a></div>
    <div class="panel"><b>Proveedor de envío: {wa.esc(wa._provider_label())}</b><p>Primero escanea el QR en tu cuenta de UltraMsg. Luego completa estos campos.</p>
    <form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}"><div class="formgrid">
    <label>ID de instancia<input name="instance" value="{wa.esc(cfg['instance'])}" placeholder="instance193640" required></label>
    <label>Token de UltraMsg<input type="password" name="token" autocomplete="new-password" placeholder="{'Guardado; deja vacío para conservarlo' if cfg['token'] else 'Pega aquí el token'}"></label></div>
    <p>El token se guarda cifrado y nunca se muestra. Conectar configura la recepción de mensajes y cambia el proveedor de envío.</p>
    <button class="btn green" name="action" value="save">Comprobar y conectar UltraMsg</button></form></div>
    <div class="panel"><p>La primera versión admite mensajes de texto. Los archivos recibidos se muestran como avisos; no se descargan automáticamente.</p>
    <form method="post"><input type="hidden" name="csrf" value="{wa.esc(csrf)}"><button class="btn" name="action" value="meta">Usar Meta para enviar</button></form></div>'''
    response=current_app.make_response(base.shell('UltraMsg',body,'whatsapp_inbox'))
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return response


def webhook():
    import whatsapp_suite as wa
    cfg=config()
    if not cfg['hook'] or not hmac.compare_digest(cfg['hook'],request.args.get('key','')): abort(403)
    if request.content_length and request.content_length>1_000_000: abort(413)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or not isinstance(payload.get('data'),dict): abort(400)
    if str(payload.get('instanceId','')).removeprefix('instance')!=cfg['instance'].removeprefix('instance'): abort(403)
    data=payload['data'];event=payload.get('event_type');c=base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        if event=='message_received' and data.get('fromMe') in (False,None,0,'false'):
            sender=str(data.get('from',''));pid=data.get('id')
            if not re.fullmatch(r'[1-9][0-9]{7,14}@(c\.us|s\.whatsapp\.net)',sender) or not isinstance(pid,str) or not pid:
                return jsonify(ok=True,ignored=True)
            phone=sender.split('@')[0];pid='ultra:'+cfg['instance']+':in:'+pid
            if not c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?',(pid,)).fetchone():
                customer=wa._customer_by_phone(c,phone)
                t=wa._thread_for_phone(c,phone,customer['name'] if customer else '',customer['id'] if customer else None)
                body=str(data.get('body') or '[Archivo o mensaje sin texto]')[:16000]
                c.execute("INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,created_at) VALUES(?,'IN',?,?,?,'RECIBIDO',?)",(t['id'],str(data.get('type','chat'))[:40],body,pid,wa._now()))
                c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=?,unread=unread+1 WHERE id=?',(body[:500],wa._now(),t['id']))
                c.execute('UPDATE whatsapp_webhook_health SET last_event=?,last_incoming=? WHERE id=1',(wa._now(),wa._now()))
        elif event=='message_ack':
            ref=payload.get('referenceId') or data.get('referenceId')
            mapped={'server':'ENVIADO','device':'ENTREGADO','read':'LEÍDO','played':'LEÍDO','1':'ENVIADO','2':'ENTREGADO','3':'LEÍDO','4':'LEÍDO'}.get(str(data.get('ack','')).lower())
            if isinstance(ref,str) and re.fullmatch(r'iflash-[a-f0-9]{32}',ref) and mapped:
                pid='ultra:'+cfg['instance']+':'+ref
                old=c.execute('SELECT status FROM ultramsg_acks WHERE provider_id=?',(pid,)).fetchone()
                ranks={'ENVIADO':1,'ENTREGADO':2,'LEÍDO':3}
                if not old or ranks[mapped]>=ranks[old['status']]:
                    c.execute('INSERT INTO ultramsg_acks(provider_id,status) VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET status=excluded.status',(pid,mapped))
                    c.execute('UPDATE whatsapp_messages SET status=? WHERE provider_id=?',(mapped,pid))
                    c.execute('UPDATE whatsapp_queue SET status=? WHERE provider_id=?',(mapped,pid))
        c.commit()
    except Exception as exc:
        c.rollback();current_app.logger.error('UltraMsg callback failed type=%s',type(exc).__name__)
        return jsonify(error='No se pudo guardar el evento'),500
    finally: c.close()
    return jsonify(ok=True)


def setup(app):
    schema()
    app.add_url_rule('/whatsapp/ultramsg',endpoint='ultramsg_settings',view_func=settings,methods=['GET','POST'])
    app.add_url_rule('/webhooks/ultramsg',endpoint='ultramsg_webhook',view_func=webhook,methods=['POST'])
