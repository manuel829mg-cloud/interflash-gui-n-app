"""Explicit, read-only provider imports into the local WhatsApp inbox."""
import re
import secrets
from datetime import datetime
from urllib.parse import urlsplit
from flask import request, session, abort, redirect, url_for, flash
import app as base
import greenapi_suite as green


def check():
    if not base.logged_in(): abort(401)
    if session.get('role') != 'ADMIN': abort(403)
    if not secrets.compare_digest(session.get('green_sync_csrf', ''), request.form.get('csrf', '')) or not session.get('green_sync_csrf'): abort(403)
    if not green.enabled(): abort(409)


def sync():
    check()
    import whatsapp_suite as wa
    cfg = green.config()
    try:
        rows = green.api('getChats', cfg=cfg)
        if not isinstance(rows, list): raise green.APIError('No se recibió una lista de chats.')
        c = base.db()
        count = 0; skipped = 0
        try:
            for row in rows[:2000]:
                if not isinstance(row, dict): continue
                chat = str(row.get('id', ''))
                if not re.fullmatch(r'[1-9][0-9]{7,14}@c\.us', chat):
                    skipped += 1; continue
                phone = chat.split('@')[0]
                cu = wa._customer_by_phone(c, phone)
                t = wa._thread_for_phone(c, phone, str(row.get('name') or phone)[:200], cu['id'] if cu else None)
                name = str(row.get('name') or '').strip()[:200]
                if name: c.execute('UPDATE whatsapp_threads SET display_name=? WHERE id=?', (name,t['id']))
                c.execute('INSERT OR IGNORE INTO greenapi_chat_profiles(instance,thread_id,avatar) VALUES(?,?,?)', (cfg['channel'],t['id'],''))
                count += 1
            c.commit()
        except Exception:
            c.rollback(); raise
        finally: c.close()
        flash(f'{count} chats individuales sincronizados. Abre un chat y pulsa Cargar historial o foto. Grupos y otros chats omitidos: {skipped}.')
    except green.APIError as exc: flash(str(exc))
    return redirect(url_for('whatsapp_inbox'))


def load(thread_id):
    check()
    import whatsapp_suite as wa
    cfg = green.config()
    c = base.db(); t = c.execute('SELECT * FROM whatsapp_threads WHERE id=?',(thread_id,)).fetchone(); c.close()
    if not t or not re.fullmatch(r'[1-9][0-9]{7,14}',t['phone']): abort(404)
    chat = t['phone']+'@c.us'
    try:
        if request.form.get('action') == 'avatar':
            result = green.api('getAvatar', {'chatId':chat},cfg)
            url = str(result.get('urlAvatar') or '')
            parsed = urlsplit(url)
            host = parsed.hostname or ''
            if parsed.scheme != 'https' or not (host.endswith('.whatsapp.net') or host.endswith('.green-api.com') or host.endswith('.greenapi.com')) or parsed.username:
                url = ''
            c = base.db()
            c.execute('INSERT INTO greenapi_chat_profiles(instance,thread_id,avatar) VALUES(?,?,?) ON CONFLICT(instance,thread_id) DO UPDATE SET avatar=excluded.avatar',(cfg['channel'],thread_id,url))
            c.commit();c.close()
            flash('Foto actualizada.' if url else 'Este contacto no tiene una foto disponible para mostrar.')
        else:
            rows = green.api('getChatHistory', {'chatId':chat,'count':100},cfg)
            if not isinstance(rows,list): raise green.APIError('No se recibió el historial del chat.')
            c = base.db(); added=0
            try:
                c.execute('BEGIN IMMEDIATE')
                for item in rows[:100]:
                    if not isinstance(item,dict) or item.get('chatId') != chat or item.get('type') not in ('incoming','outgoing'): continue
                    mid = item.get('idMessage')
                    if not isinstance(mid,str) or not mid: continue
                    incoming = item['type']=='incoming'
                    pid = 'greenapi:'+cfg['channel']+(':in:' if incoming else ':')+mid
                    if c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?',(pid,)).fetchone(): continue
                    try: at=datetime.fromtimestamp(float(item['timestamp'])).isoformat(timespec='seconds')
                    except (KeyError,ValueError,TypeError,OverflowError,OSError): continue
                    text = '[Mensaje eliminado]' if item.get('isDeleted') else str(item.get('textMessage') or item.get('caption') or '[Archivo o mensaje sin texto]')[:10000]
                    status = 'RECIBIDO' if incoming else {'sent':'ENVIADO','delivered':'ENTREGADO','read':'LEÍDO','failed':'ERROR'}.get(item.get('statusMessage'),'ACEPTADO')
                    c.execute('INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,created_at) VALUES(?,?,?,?,?,?,?)',(thread_id,'IN' if incoming else 'OUT',str(item.get('typeMessage') or 'text'),text,pid,status,at));added+=1
                last=c.execute('SELECT body,created_at FROM whatsapp_messages WHERE thread_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(thread_id,)).fetchone()
                if last:c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=? WHERE id=?',(last['body'][:500],last['created_at'],thread_id))
                c.commit()
            except Exception:
                c.rollback();raise
            finally:c.close()
            flash(f'{added} mensajes incorporados. Se cargan hasta 100 mensajes disponibles; los archivos se muestran como avisos.')
    except green.APIError as exc: flash(str(exc))
    return redirect(url_for('whatsapp_inbox',thread=thread_id))


def setup(app):
    c=base.db();c.execute('CREATE TABLE IF NOT EXISTS greenapi_chat_profiles(instance TEXT,thread_id INTEGER,avatar TEXT,PRIMARY KEY(instance,thread_id))');c.commit();c.close()
    app.add_url_rule('/whatsapp/greenapi/sync',endpoint='greenapi_sync',view_func=sync,methods=['POST'])
    app.add_url_rule('/whatsapp/greenapi/chat/<int:thread_id>',endpoint='greenapi_chat_load',view_func=load,methods=['POST'])
