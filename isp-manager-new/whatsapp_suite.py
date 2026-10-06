import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from html import escape
from flask import request, redirect, url_for, flash, jsonify
import app as base

GRAPH_VERSION = os.getenv('WHATSAPP_GRAPH_VERSION', 'v23.0').strip() or 'v23.0'
ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN', '').strip()
PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '').strip()
VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', '').strip()
BUSINESS_NUMBER = os.getenv('WHATSAPP_BUSINESS_NUMBER', '').strip()


def esc(v):
    return escape('' if v is None else str(v))


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _digits(v):
    return ''.join(ch for ch in str(v or '') if ch.isdigit())


def _wa_phone(v):
    d = _digits(v)
    if len(d) == 10:
        d = '1' + d
    return d


def ensure_schema():
    c = base.db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS whatsapp_threads(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      phone TEXT NOT NULL UNIQUE,
      customer_id INTEGER,
      display_name TEXT,
      last_message TEXT,
      last_at TEXT,
      unread INTEGER DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS whatsapp_messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      thread_id INTEGER NOT NULL,
      direction TEXT NOT NULL,
      message_type TEXT DEFAULT 'text',
      body TEXT,
      provider_id TEXT,
      status TEXT DEFAULT 'RECIBIDO',
      error TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(thread_id) REFERENCES whatsapp_threads(id)
    );
    CREATE INDEX IF NOT EXISTS idx_wa_messages_thread ON whatsapp_messages(thread_id,id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_messages_provider ON whatsapp_messages(provider_id) WHERE provider_id IS NOT NULL AND provider_id<>'';
    CREATE TABLE IF NOT EXISTS whatsapp_queue(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      thread_id INTEGER,
      customer_id INTEGER,
      phone TEXT NOT NULL,
      kind TEXT DEFAULT 'text',
      body TEXT,
      template_name TEXT,
      language_code TEXT DEFAULT 'es',
      status TEXT DEFAULT 'PENDIENTE',
      attempts INTEGER DEFAULT 0,
      last_error TEXT,
      provider_id TEXT,
      created_at TEXT NOT NULL,
      sent_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_wa_queue_status ON whatsapp_queue(status,id);
    CREATE TABLE IF NOT EXISTS whatsapp_local_templates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT UNIQUE NOT NULL,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      meta_template_name TEXT,
      active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS whatsapp_bot_rules(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      keyword TEXT NOT NULL,
      reply TEXT NOT NULL,
      active INTEGER DEFAULT 1,
      created_at TEXT NOT NULL
    );
    ''')
    if c.execute('SELECT COUNT(*) c FROM whatsapp_local_templates').fetchone()['c'] == 0:
        c.executemany('INSERT INTO whatsapp_local_templates(code,title,body,active) VALUES(?,?,?,1)', [
            ('bienvenida','Bienvenida','¡Hola! Bienvenido a INTER Flash. Estamos a tu orden para soporte, pagos y consultas.'),
            ('factura','Factura disponible','Hola, tu factura de INTER Flash ya está disponible. Puedes realizar tu pago por nuestros canales habituales.'),
            ('vencimiento','Aviso de vencimiento','Hola, te recordamos que tu servicio de internet INTER Flash tiene una factura próxima a vencer.'),
            ('suspension','Aviso de suspensión','Hola, tu servicio INTER Flash presenta una factura vencida. Regulariza el pago para evitar o levantar la suspensión.'),
            ('pago','Pago recibido','¡Gracias! Hemos recibido tu pago de INTER Flash correctamente.')
        ])
    for k,v in {
        'whatsapp_chatbot_enabled':'0','whatsapp_auto_invoice':'1','whatsapp_auto_payment':'1',
        'whatsapp_auto_overdue':'1','whatsapp_auto_suspend':'1','whatsapp_auto_reconnect':'1'
    }.items():
        c.execute('INSERT OR IGNORE INTO app_settings(key,value) VALUES(?,?)',(k,v))
    if c.execute('SELECT COUNT(*) c FROM whatsapp_bot_rules').fetchone()['c'] == 0:
        c.executemany('INSERT INTO whatsapp_bot_rules(keyword,reply,active,created_at) VALUES(?,?,1,?)',[
            ('factura','Para consultar tu factura, envíame tu nombre completo o cédula.',_now()),
            ('pago','Para registrar un pago, envía el comprobante y el nombre del titular.',_now()),
            ('soporte','Cuéntame qué problema presenta tu internet y te ayudamos.',_now()),
            ('planes','Tenemos planes de internet por fibra. Indícame tu sector para orientarte.',_now())
        ])
    c.commit(); c.close()


def _setting(key, default=''):
    c=base.db(); r=c.execute('SELECT value FROM app_settings WHERE key=?',(key,)).fetchone(); c.close()
    return r['value'] if r else default


def _set_setting(key,value):
    c=base.db(); c.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value))); c.commit(); c.close()


def _meta_ready():
    return bool(ACCESS_TOKEN and PHONE_NUMBER_ID)


def _thread_for_phone(c, phone, display_name='', customer_id=None):
    phone = _wa_phone(phone)
    row = c.execute('SELECT * FROM whatsapp_threads WHERE phone=?', (phone,)).fetchone()
    if row:
        updates=[]; args=[]
        if display_name and not row['display_name']:
            updates.append('display_name=?'); args.append(display_name)
        if customer_id and not row['customer_id']:
            updates.append('customer_id=?'); args.append(customer_id)
        if updates:
            args.append(row['id'])
            c.execute('UPDATE whatsapp_threads SET '+','.join(updates)+' WHERE id=?', args)
            row = c.execute('SELECT * FROM whatsapp_threads WHERE id=?', (row['id'],)).fetchone()
        return row
    cur = c.execute('INSERT INTO whatsapp_threads(phone,customer_id,display_name,created_at) VALUES(?,?,?,?)',
                    (phone,customer_id,display_name or phone,_now()))
    return c.execute('SELECT * FROM whatsapp_threads WHERE id=?', (cur.lastrowid,)).fetchone()


def _customer_by_phone(c, phone):
    target = _wa_phone(phone)
    if not target:
        return None
    for r in c.execute("SELECT id,name,phone FROM customers WHERE COALESCE(status,'ACTIVO')<>'ELIMINADO' AND COALESCE(phone,'')<>''").fetchall():
        if _wa_phone(r['phone']) == target:
            return r
    return None


def _meta_post(payload):
    url = f'https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages'
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization': 'Bearer ' + ACCESS_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return True, json.loads(body or '{}'), ''
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            detail = json.loads(raw)
            msg = ((detail.get('error') or {}).get('message')) or raw
        except Exception:
            msg = raw
        return False, {}, str(msg)[:500]
    except Exception as e:
        return False, {}, str(e)[:500]


def _send_text(phone, body):
    if not _meta_ready():
        return False, '', 'Meta Cloud API no está configurada todavía.'
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': _wa_phone(phone),
        'type': 'text',
        'text': {'preview_url': False, 'body': body[:4096]},
    }
    ok, data, err = _meta_post(payload)
    provider_id = ''
    if ok:
        try: provider_id = data['messages'][0]['id']
        except Exception: pass
    return ok, provider_id, err


def _send_template(phone, name, language='es'):
    if not _meta_ready():
        return False, '', 'Meta Cloud API no está configurada todavía.'
    payload = {
        'messaging_product': 'whatsapp',
        'to': _wa_phone(phone),
        'type': 'template',
        'template': {'name': name, 'language': {'code': language or 'es'}},
    }
    ok, data, err = _meta_post(payload)
    provider_id = ''
    if ok:
        try: provider_id = data['messages'][0]['id']
        except Exception: pass
    return ok, provider_id, err


def _record_outgoing(c, thread_id, body, provider_id, status, error=''):
    c.execute('''INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,error,created_at)
                 VALUES(?,?,?,?,?,?,?,?)''', (thread_id,'OUT','text',body,provider_id or None,status,error or None,_now()))
    c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=? WHERE id=?', (body[:500],_now(),thread_id))


def _process_queue_item(c, row):
    c.execute("UPDATE whatsapp_queue SET status='EN_PROCESO',attempts=attempts+1,last_error=NULL WHERE id=?", (row['id'],))
    c.commit()
    if row['kind'] == 'template' and row['template_name']:
        ok, provider_id, err = _send_template(row['phone'], row['template_name'], row['language_code'] or 'es')
        visible_body = '[Plantilla] ' + row['template_name']
    else:
        ok, provider_id, err = _send_text(row['phone'], row['body'] or '')
        visible_body = row['body'] or ''
    if ok:
        c.execute("UPDATE whatsapp_queue SET status='ENVIADO',provider_id=?,sent_at=?,last_error=NULL WHERE id=?",
                  (provider_id,_now(),row['id']))
        if row['thread_id']:
            _record_outgoing(c,row['thread_id'],visible_body,provider_id,'ENVIADO')
    else:
        c.execute("UPDATE whatsapp_queue SET status='ERROR',last_error=? WHERE id=?", (err,row['id']))
        if row['thread_id']:
            _record_outgoing(c,row['thread_id'],visible_body,'','ERROR',err)
    c.commit()
    return ok, err



def _tabs(active='chat'):
    items=[('chat','Chat','whatsapp_inbox'),('chatbot','Chatbot','whatsapp_chatbot'),('automaticos','Automáticos','whatsapp_automatics'),('cola','Cola de mensajes','whatsapp_queue'),('plantillas','Plantillas','whatsapp_templates_admin'),('general','General','whatsapp_general')]
    out=[]
    for key,label,ep in items:
        cls='wa-tab on' if key==active else 'wa-tab'
        out.append(f'<a class="{cls}" href="{url_for(ep)}">{label}</a>')
    return '<div class="wa-tabs">'+''.join(out)+'</div>'


def queue_event(customer_id, code, extra=None):
    ensure_schema()
    if _setting('whatsapp_enabled','0')!='1': return False
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(customer_id,)).fetchone()
    trow=c.execute('SELECT * FROM whatsapp_templates WHERE code=? AND active=1',(code,)).fetchone()
    if not cu or not cu['phone'] or not trow:
        c.close(); return False
    setting_key={'INVOICE':'whatsapp_auto_invoice','PAYMENT':'whatsapp_auto_payment','OVERDUE':'whatsapp_auto_overdue','SUSPEND':'whatsapp_auto_suspend','RECONNECT':'whatsapp_auto_reconnect'}.get(code)
    if setting_key and _setting(setting_key,'1')!='1':
        c.close(); return False
    data={'name':cu['name'],'amount':'','due_date':''}; data.update(extra or {})
    try: body=trow['body'].format(**data)
    except Exception: body=trow['body']
    t=_thread_for_phone(c,cu['phone'],cu['name'],cu['id'])
    cur=c.execute("""INSERT INTO whatsapp_queue(thread_id,customer_id,phone,kind,body,status,created_at)
                     VALUES(?,?,?,?,?,'PENDIENTE',?)""",(t['id'],cu['id'],_wa_phone(cu['phone']),'text',body,_now()))
    row=c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(cur.lastrowid,)).fetchone(); c.commit()
    ok,err=_process_queue_item(c,row); c.close()
    return ok



def process_legacy_outbox(limit=100):
    ensure_schema(); c=base.db()
    try:
        rows=c.execute("SELECT * FROM whatsapp_outbox WHERE status='PENDIENTE' ORDER BY id LIMIT ?",(limit,)).fetchall()
    except Exception:
        c.close(); return 0
    sent=0
    for r in rows:
        phone=_wa_phone(r['phone']); body=r['message'] or ''
        if not phone or not body: continue
        cu=c.execute('SELECT * FROM customers WHERE id=?',(r['customer_id'],)).fetchone() if r['customer_id'] else None
        t=_thread_for_phone(c,phone,cu['name'] if cu else '',cu['id'] if cu else None)
        ok,pid,err=_send_text(phone,body)
        if ok:
            _record_outgoing(c,t['id'],body,pid,'ENVIADO'); c.execute("UPDATE whatsapp_outbox SET status='ENVIADO',sent_at=?,error='' WHERE id=?",(_now(),r['id'])); sent+=1
        else:
            c.execute("UPDATE whatsapp_outbox SET status='ERROR',error=? WHERE id=?",(err,r['id']))
        c.commit()
    c.close(); return sent


def inbox():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema()
    q=(request.args.get('q') or '').strip()
    selected=request.args.get('thread')
    c=base.db()
    sql='''SELECT wt.*,cu.name customer_name FROM whatsapp_threads wt LEFT JOIN customers cu ON cu.id=wt.customer_id WHERE 1=1'''
    args=[]
    if q:
        like='%'+q+'%'; sql+=' AND (wt.phone LIKE ? OR wt.display_name LIKE ? OR cu.name LIKE ?)'; args=[like,like,like]
    sql+=' ORDER BY COALESCE(wt.last_at,wt.created_at) DESC LIMIT 200'
    threads=c.execute(sql,args).fetchall()
    if not selected and threads: selected=str(threads[0]['id'])
    thread=None; messages=[]
    if selected and str(selected).isdigit():
        thread=c.execute('''SELECT wt.*,cu.name customer_name FROM whatsapp_threads wt LEFT JOIN customers cu ON cu.id=wt.customer_id WHERE wt.id=?''',(int(selected),)).fetchone()
        if thread:
            c.execute('UPDATE whatsapp_threads SET unread=0 WHERE id=?',(thread['id'],))
            messages=c.execute('SELECT * FROM whatsapp_messages WHERE thread_id=? ORDER BY id DESC LIMIT 120',(thread['id'],)).fetchall()[::-1]
            c.commit()
    queue_pending=c.execute("SELECT COUNT(*) c FROM whatsapp_queue WHERE status IN ('PENDIENTE','EN_PROCESO')").fetchone()['c']
    queue_error=c.execute("SELECT COUNT(*) c FROM whatsapp_queue WHERE status='ERROR'").fetchone()['c']
    unread=c.execute('SELECT COALESCE(SUM(unread),0) c FROM whatsapp_threads').fetchone()['c']
    templates=c.execute('SELECT * FROM whatsapp_local_templates WHERE active=1 ORDER BY id').fetchall()
    c.close()

    trows=[]
    for t in threads:
        label=t['customer_name'] or t['display_name'] or t['phone']
        unread_badge=f'<span class="wa-unread">{int(t["unread"] or 0)}</span>' if t['unread'] else ''
        trows.append(f'''<a class="wa-thread {'on' if thread and t['id']==thread['id'] else ''}" href="{url_for('whatsapp_inbox',thread=t['id'],q=q)}"><div class="wa-avatar">{esc((label or '?')[:1].upper())}</div><div class="wa-thread-main"><b>{esc(label)}</b><small>{esc(t['phone'])}</small><span>{esc((t['last_message'] or 'Sin mensajes')[:78])}</span></div>{unread_badge}</a>''')
    bubbles=[]
    for m in messages:
        out=m['direction']=='OUT'
        meta=f"{esc((m['created_at'] or '')[11:16])} · {esc(m['status'] or '')}"
        if m['error']: meta += ' · ' + esc(m['error'][:80])
        bubbles.append(f'''<div class="wa-msg {'out' if out else 'in'}"><div>{esc(m['body'] or '['+str(m['message_type'] or 'mensaje')+']')}</div><small>{meta}</small></div>''')
    template_opts=''.join(f'<option value="{esc(x["body"])}">{esc(x["title"])}</option>' for x in templates)
    composer='''<div class="wa-empty">Selecciona una conversación o inicia una nueva.</div>'''
    if thread:
        composer=f'''<div class="wa-chat-head"><div><b>{esc(thread['customer_name'] or thread['display_name'] or thread['phone'])}</b><small>{esc(thread['phone'])}</small></div><span class="tag {'ok' if _meta_ready() else 'warn'}">{'Meta conectado' if _meta_ready() else 'Falta configurar Meta'}</span></div>
        <div class="wa-messages">{''.join(bubbles) or '<div class="wa-empty">Todavía no hay mensajes.</div>'}</div>
        <form class="wa-compose" method="post" action="{url_for('whatsapp_send')}"><input type="hidden" name="thread_id" value="{thread['id']}"><input type="hidden" name="phone" value="{esc(thread['phone'])}"><select class="field" onchange="if(this.value){{this.form.body.value=this.value;this.selectedIndex=0}}"><option value="">Plantillas rápidas…</option>{template_opts}</select><textarea class="field" name="body" rows="2" placeholder="Escribe un mensaje…" required></textarea><button class="btn green">Enviar</button></form>'''

    configured='Meta Cloud API lista para enviar y recibir.' if _meta_ready() else 'Faltan WHATSAPP_ACCESS_TOKEN y WHATSAPP_PHONE_NUMBER_ID en Railway.'
    webhook_state='Token de verificación listo.' if VERIFY_TOKEN else 'Falta WHATSAPP_VERIFY_TOKEN para activar el webhook.'
    body=f'''<style>
    .wa-kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.wa-layout{{display:grid;grid-template-columns:360px 1fr;gap:14px;min-height:640px}}.wa-side,.wa-chat{{background:#0d1a29;border:1px solid #22374e;border-radius:12px;overflow:hidden}}.wa-side-head{{padding:14px;border-bottom:1px solid #22374e}}.wa-side-head form{{display:flex;gap:7px}}.wa-side-head input{{width:100%}}.wa-threads{{max-height:590px;overflow:auto}}.wa-thread{{display:grid;grid-template-columns:44px 1fr auto;gap:10px;padding:12px;border-bottom:1px solid #1b3045;align-items:center}}.wa-thread:hover,.wa-thread.on{{background:#122438}}.wa-avatar{{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:#075e54;color:#fff;font-weight:900}}.wa-thread-main{{min-width:0}}.wa-thread-main b,.wa-thread-main small,.wa-thread-main span{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.wa-thread-main small{{color:#7f94aa;margin:2px 0}}.wa-thread-main span{{color:#9fb0c0;font-size:12px}}.wa-unread{{min-width:22px;height:22px;padding:0 6px;border-radius:999px;background:#16c784;color:#052d1f;display:grid;place-items:center;font-size:11px;font-weight:900}}.wa-chat{{display:flex;flex-direction:column}}.wa-chat-head{{padding:14px 16px;border-bottom:1px solid #22374e;display:flex;justify-content:space-between;align-items:center}}.wa-chat-head small{{display:block;color:#8397aa;margin-top:3px}}.wa-messages{{flex:1;overflow:auto;padding:18px;background:radial-gradient(circle at 30% 10%,#10243a,#0a1522 55%)}}.wa-msg{{max-width:72%;padding:10px 12px;border-radius:11px;margin:8px 0;line-height:1.35}}.wa-msg.in{{background:#182a3d;margin-right:auto}}.wa-msg.out{{background:#075e54;margin-left:auto}}.wa-msg small{{display:block;color:#b9c8d5;font-size:10px;margin-top:6px;text-align:right}}.wa-compose{{padding:12px;border-top:1px solid #22374e;display:grid;grid-template-columns:190px 1fr auto;gap:8px;align-items:end}}.wa-compose textarea{{resize:vertical;min-height:44px}}.wa-empty{{padding:40px;text-align:center;color:#8397aa}}.wa-config{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.wa-tabs{{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #22374e;margin:0 0 14px}}.wa-tab{{padding:11px 15px;color:#9fb3ca;font-weight:800;text-decoration:none;border-bottom:3px solid transparent}}.wa-tab:hover{{color:#fff}}.wa-tab.on{{color:#fff;border-bottom-color:#16c784;background:#11263a}}@media(max-width:950px){{.wa-layout{{grid-template-columns:1fr}}.wa-side{{max-height:360px}}.wa-kpis{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:650px){{.wa-compose{{grid-template-columns:1fr}}.wa-config{{grid-template-columns:1fr}}.wa-kpis{{grid-template-columns:1fr}}}}
    </style>
    <div class="head"><div><h1>WhatsApp administrador</h1><p>Chat, chatbot, automatizaciones, cola y conexión oficial de Meta.</p></div><span class="tag {'ok' if _meta_ready() else 'warn'}">{'ACTIVO' if _meta_ready() else 'PENDIENTE'}</span></div>
    {_tabs('chat')}
    <div class="wa-kpis"><div class="kpi green1"><div class="label">Conexión</div><div class="value" style="font-size:18px">{'ACTIVA' if _meta_ready() else 'PENDIENTE'}</div><div class="sub">Meta Cloud API</div></div><div class="kpi blue1"><div class="label">Chats</div><div class="value">{len(threads)}</div><div class="sub">Cargados</div></div><div class="kpi orange1"><div class="label">No leídos</div><div class="value">{unread}</div><div class="sub">Mensajes</div></div><div class="kpi red1"><div class="label">Cola</div><div class="value">{queue_pending}</div><div class="sub">Pendientes · {queue_error} error(es)</div></div></div>
    <div class="panel wa-config"><div><b>{esc(configured)}</b><div class="muted" style="margin-top:5px">Número: {esc(BUSINESS_NUMBER or 'por configurar')}</div></div><div><b>{esc(webhook_state)}</b><div class="muted" style="margin-top:5px">Webhook: {esc(request.url_root.rstrip('/') + '/webhooks/whatsapp')}</div></div></div>
    <div class="panel"><form method="post" action="{url_for('whatsapp_new_thread')}" class="toolbar" style="margin:0"><input class="field" name="phone" placeholder="Número para nueva conversación" required><input class="field" name="name" placeholder="Nombre (opcional)"><button class="btn green">+ Nueva conversación</button></form></div>
    <div class="wa-layout"><div class="wa-side"><div class="wa-side-head"><form method="get"><input class="field" name="q" value="{esc(q)}" placeholder="Buscar nombre o número"><button class="btn">Buscar</button></form></div><div class="wa-threads">{''.join(trows) or '<div class="wa-empty">Sin conversaciones todavía.</div>'}</div></div><div class="wa-chat">{composer}</div></div>'''
    return base.shell('WhatsApp',body,'whatsapp_inbox')


def new_thread():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema()
    phone=_wa_phone(request.form.get('phone'))
    name=(request.form.get('name') or '').strip()
    if not phone:
        flash('Número de WhatsApp inválido.'); return redirect(url_for('whatsapp_inbox'))
    c=base.db(); cu=_customer_by_phone(c,phone); t=_thread_for_phone(c,phone,name or (cu['name'] if cu else ''),cu['id'] if cu else None); c.commit(); c.close()
    return redirect(url_for('whatsapp_inbox',thread=t['id']))


def send():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema()
    phone=_wa_phone(request.form.get('phone')); body=(request.form.get('body') or '').strip(); thread_id=request.form.get('thread_id')
    if not phone or not body:
        flash('Falta número o mensaje.'); return redirect(url_for('whatsapp_inbox'))
    c=base.db(); t=None
    if thread_id and str(thread_id).isdigit(): t=c.execute('SELECT * FROM whatsapp_threads WHERE id=?',(int(thread_id),)).fetchone()
    if not t:
        cu=_customer_by_phone(c,phone); t=_thread_for_phone(c,phone,cu['name'] if cu else '',cu['id'] if cu else None)
    cur=c.execute('''INSERT INTO whatsapp_queue(thread_id,customer_id,phone,kind,body,status,created_at)
                     VALUES(?,?,?,?,?,'PENDIENTE',?)''',(t['id'],t['customer_id'],phone,'text',body,_now()))
    qrow=c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(cur.lastrowid,)).fetchone(); c.commit()
    ok,err=_process_queue_item(c,qrow); c.close()
    if ok: flash('Mensaje enviado a WhatsApp.')
    else: flash('Mensaje guardado, pero no pudo enviarse: '+err)
    return redirect(url_for('whatsapp_inbox',thread=t['id']))


def queue_page():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c=base.db(); rows=c.execute('SELECT * FROM whatsapp_queue ORDER BY id DESC LIMIT 250').fetchall(); c.close()
    trs=[]
    for r in rows:
        cls='ok' if r['status']=='ENVIADO' else 'bad' if r['status']=='ERROR' else 'warn'
        retry=f'''<form method="post" action="{url_for('whatsapp_retry',id=r['id'])}"><button class="btn">Reintentar</button></form>''' if r['status']=='ERROR' else ''
        trs.append(f'''<tr><td>#{r['id']}</td><td>{esc(r['phone'])}</td><td>{esc((r['body'] or ('Plantilla: '+str(r['template_name'] or '')))[:100])}</td><td><span class="tag {cls}">{esc(r['status'])}</span></td><td>{r['attempts']}</td><td>{esc(r['last_error'] or '-')}</td><td>{esc(r['created_at'])}</td><td>{retry}</td></tr>''')
    body=f'''<div class="head"><div><h1>Cola de WhatsApp</h1><p>Mensajes enviados, pendientes y con error.</p></div></div>{_tabs('cola')}<div class="panel"><table class="table"><tr><th>#</th><th>Número</th><th>Mensaje</th><th>Estado</th><th>Intentos</th><th>Error</th><th>Fecha</th><th></th></tr>{''.join(trs) or '<tr><td colspan="8" class="muted">Sin mensajes en cola.</td></tr>'}</table></div>'''
    return base.shell('Cola WhatsApp',body,'whatsapp_inbox')


def retry(id):
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c=base.db(); row=c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(id,)).fetchone()
    if not row: c.close(); return redirect(url_for('whatsapp_queue'))
    c.execute("UPDATE whatsapp_queue SET status='PENDIENTE' WHERE id=?",(id,)); c.commit(); row=c.execute('SELECT * FROM whatsapp_queue WHERE id=?',(id,)).fetchone(); ok,err=_process_queue_item(c,row); c.close()
    flash('Mensaje reenviado.' if ok else 'Sigue con error: '+err)
    return redirect(url_for('whatsapp_queue'))


def settings_page():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c=base.db(); templates=c.execute('SELECT * FROM whatsapp_local_templates ORDER BY id').fetchall(); c.close()
    trs=''.join(f'''<tr><td>{esc(x['title'])}</td><td><code>{esc(x['code'])}</code></td><td>{esc(x['body'])}</td><td>{esc(x['meta_template_name'] or 'Sin mapear')}</td></tr>''' for x in templates)
    vars_rows=[
        ('WHATSAPP_ACCESS_TOKEN',bool(ACCESS_TOKEN),'Token permanente de Meta'),
        ('WHATSAPP_PHONE_NUMBER_ID',bool(PHONE_NUMBER_ID),'ID del número de WhatsApp Business'),
        ('WHATSAPP_VERIFY_TOKEN',bool(VERIFY_TOKEN),'Token que usarás al verificar el webhook'),
        ('WHATSAPP_BUSINESS_NUMBER',bool(BUSINESS_NUMBER),'Número visible, por ejemplo 1809…'),
        ('WHATSAPP_GRAPH_VERSION',bool(GRAPH_VERSION),f'Actual: {GRAPH_VERSION}'),
    ]
    vr=''.join(f'''<tr><td><code>{esc(n)}</code></td><td><span class="tag {'ok' if ok else 'warn'}">{'LISTO' if ok else 'FALTA'}</span></td><td>{esc(desc)}</td></tr>''' for n,ok,desc in vars_rows)
    body=f'''<div class="head"><div><h1>Configuración WhatsApp</h1><p>Primera fase: Meta Cloud API oficial, bandeja, webhook y cola de mensajes.</p></div><a class="btn" href="{url_for('whatsapp_inbox')}">← WhatsApp</a></div><div class="panel"><h3>Conexión Meta</h3><div class="notice" style="background:#17304b;color:#bfdbfe">Los tokens no se guardan en la base de datos. Se configuran como variables privadas en Railway.</div><table class="table"><tr><th>Variable</th><th>Estado</th><th>Uso</th></tr>{vr}</table><p class="muted">Webhook público: <code>{esc(request.url_root.rstrip('/') + '/webhooks/whatsapp')}</code></p></div><div class="panel"><h3>Plantillas internas</h3><p class="muted">Estas sirven como respuestas rápidas. Más adelante se podrán mapear con plantillas aprobadas de Meta para mensajes fuera de la ventana de atención.</p><table class="table"><tr><th>Nombre</th><th>Código</th><th>Texto</th><th>Plantilla Meta</th></tr>{trs}</table></div>'''
    return base.shell('Configuración WhatsApp',body,'whatsapp_inbox')



def chatbot_page():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c=base.db()
    if request.method=='POST':
        action=request.form.get('action','save')
        if action=='toggle':
            rid=int(request.form['id']); c.execute('UPDATE whatsapp_bot_rules SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(rid,))
        elif action=='delete':
            c.execute('DELETE FROM whatsapp_bot_rules WHERE id=?',(int(request.form['id']),))
        else:
            kw=(request.form.get('keyword') or '').strip().lower(); reply=(request.form.get('reply') or '').strip()
            if kw and reply: c.execute('INSERT INTO whatsapp_bot_rules(keyword,reply,active,created_at) VALUES(?,?,1,?)',(kw,reply,_now()))
        c.commit(); flash('Chatbot actualizado.')
    rows=c.execute('SELECT * FROM whatsapp_bot_rules ORDER BY id').fetchall(); c.close()
    trs=''.join(f'''<tr><td><b>{esc(r["keyword"])}</b></td><td>{esc(r["reply"])}</td><td><span class="tag {'ok' if r["active"] else 'warn'}">{'ACTIVA' if r["active"] else 'PAUSADA'}</span></td><td><form method="post" style="display:inline"><input type="hidden" name="id" value="{r["id"]}"><button class="btn" name="action" value="toggle">{'Pausar' if r["active"] else 'Activar'}</button><button class="btn red" name="action" value="delete" onclick="return confirm('¿Eliminar esta regla?')">Eliminar</button></form></td></tr>''' for r in rows)
    body=f'''<style>.wa-tabs{{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #22374e;margin-bottom:14px}}.wa-tab{{padding:11px 15px;color:#9fb3ca;font-weight:800;border-bottom:3px solid transparent}}.wa-tab.on{{color:#fff;border-bottom-color:#16c784;background:#11263a}}</style>
    <div class="head"><div><h1>Chatbot</h1><p>Respuestas automáticas por palabras clave.</p></div></div>{_tabs('chatbot')}
    <div class="panel"><form method="post" class="toolbar"><input class="field" name="keyword" placeholder="Palabra: factura, pago, soporte..." required><input class="field" name="reply" placeholder="Respuesta automática" required style="min-width:360px"><button class="btn green">+ Agregar regla</button></form></div>
    <div class="panel"><table class="table"><tr><th>Palabra</th><th>Respuesta</th><th>Estado</th><th></th></tr>{trs}</table></div>'''
    return base.shell('Chatbot WhatsApp',body,'whatsapp_inbox')


def automatics_page():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema()
    keys=[('whatsapp_chatbot_enabled','Chatbot automático','Responde reglas de palabras clave'),('whatsapp_auto_invoice','Factura generada','Avisa cuando se crea una factura'),('whatsapp_auto_payment','Pago recibido','Confirma automáticamente los pagos'),('whatsapp_auto_overdue','Factura vencida','Recuerda facturas vencidas'),('whatsapp_auto_suspend','Suspensión','Avisa antes/al programar suspensión'),('whatsapp_auto_reconnect','Reconexión','Avisa cuando se programa reconexión')]
    if request.method=='POST':
        for k,_,__ in keys: _set_setting(k,'1' if request.form.get(k)=='1' else '0')
        _set_setting('whatsapp_enabled','1' if request.form.get('whatsapp_enabled')=='1' else '0'); flash('Automatizaciones guardadas.')
    cards=''.join(f'''<label style="display:flex;justify-content:space-between;gap:20px;align-items:center;padding:15px;border:1px solid #22374e;border-radius:10px"><span><b>{esc(name)}</b><small class="muted" style="display:block;margin-top:4px">{esc(desc)}</small></span><input type="checkbox" name="{k}" value="1" {'checked' if _setting(k,'0')=='1' else ''} style="width:22px;height:22px"></label>''' for k,name,desc in keys)
    body=f'''<style>.wa-tabs{{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #22374e;margin-bottom:14px}}.wa-tab{{padding:11px 15px;color:#9fb3ca;font-weight:800;border-bottom:3px solid transparent}}.wa-tab.on{{color:#fff;border-bottom-color:#16c784;background:#11263a}}</style>
    <div class="head"><div><h1>Mensajes automáticos</h1><p>Controla qué eventos de INTER Flash generan mensajes.</p></div></div>{_tabs('automaticos')}
    <form method="post"><div class="panel"><label style="display:flex;justify-content:space-between;align-items:center"><span><b>WhatsApp automático general</b><small class="muted" style="display:block">Interruptor principal</small></span><input type="checkbox" name="whatsapp_enabled" value="1" {'checked' if _setting('whatsapp_enabled','0')=='1' else ''} style="width:24px;height:24px"></label></div>
    <div class="panel" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px">{cards}</div><button class="btn green">Guardar automatizaciones</button></form>'''
    return base.shell('Automáticos WhatsApp',body,'whatsapp_inbox')


def templates_admin():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c=base.db()
    if request.method=='POST':
        code=(request.form.get('code') or '').strip().upper(); name=(request.form.get('name') or '').strip(); body=(request.form.get('body') or '').strip()
        if code and name and body:
            c.execute('INSERT INTO whatsapp_templates(code,name,body,active) VALUES(?,?,?,1) ON CONFLICT(code) DO UPDATE SET name=excluded.name,body=excluded.body',(code,name,body)); c.commit(); flash('Plantilla guardada.')
    rows=c.execute('SELECT * FROM whatsapp_templates ORDER BY id').fetchall(); c.close()
    forms=''.join(f'''<form class="panel" method="post"><div class="formgrid"><label>Código<input name="code" value="{esc(r["code"])}" readonly></label><label>Nombre<input name="name" value="{esc(r["name"])}"></label><label class="full">Mensaje<textarea name="body" rows="3">{esc(r["body"])}</textarea></label><div class="full"><button class="btn green">Guardar</button></div></div></form>''' for r in rows)
    body=f'''<style>.wa-tabs{{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #22374e;margin-bottom:14px}}.wa-tab{{padding:11px 15px;color:#9fb3ca;font-weight:800;border-bottom:3px solid transparent}}.wa-tab.on{{color:#fff;border-bottom-color:#16c784;background:#11263a}}</style>
    <div class="head"><div><h1>Plantillas</h1><p>Edita los textos usados por facturación y cobros.</p></div></div>{_tabs('plantillas')}
    <div class="notice">Variables disponibles según el evento: <code>{{name}}</code>, <code>{{amount}}</code>, <code>{{due_date}}</code>.</div>{forms}'''
    return base.shell('Plantillas WhatsApp',body,'whatsapp_inbox')


def general_page():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema()
    vars_rows=[('Meta Cloud API',_meta_ready(),'Canal oficial para enviar mensajes'),('Access Token',bool(ACCESS_TOKEN),'Credencial privada'),('Phone Number ID',bool(PHONE_NUMBER_ID),'Identificador del número'),('Webhook',bool(VERIFY_TOKEN),'Recepción de mensajes y estados'),('Número Business',bool(BUSINESS_NUMBER),BUSINESS_NUMBER or 'Por configurar')]
    trs=''.join(f'''<tr><td><b>{esc(n)}</b></td><td><span class="tag {'ok' if ok else 'warn'}">{'LISTO' if ok else 'FALTA'}</span></td><td>{esc(d)}</td></tr>''' for n,ok,d in vars_rows)
    body=f'''<style>.wa-tabs{{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid #22374e;margin-bottom:14px}}.wa-tab{{padding:11px 15px;color:#9fb3ca;font-weight:800;border-bottom:3px solid transparent}}.wa-tab.on{{color:#fff;border-bottom-color:#16c784;background:#11263a}}</style>
    <div class="head"><div><h1>WhatsApp · General</h1><p>Estado de la línea y conexión oficial.</p></div><span class="tag {'ok' if _meta_ready() else 'warn'}">{'VINCULADO' if _meta_ready() else 'POR CONFIGURAR'}</span></div>{_tabs('general')}
    <div class="panel"><h3>Línea de WhatsApp</h3><table class="table"><tr><th>Componente</th><th>Estado</th><th>Detalle</th></tr>{trs}</table><p class="muted">Webhook: <code>{esc(request.url_root.rstrip('/') + '/webhooks/whatsapp')}</code></p></div>
    <div class="panel"><h3>Conexión</h3><p>INTER Flash usa la API oficial de Meta. Esta modalidad no necesita escanear un código QR de WhatsApp Web.</p></div>'''
    return base.shell('WhatsApp General',body,'whatsapp_inbox')


def webhook():
    ensure_schema()
    if request.method=='GET':
        mode=request.args.get('hub.mode'); token=request.args.get('hub.verify_token'); challenge=request.args.get('hub.challenge','')
        if mode=='subscribe' and VERIFY_TOKEN and token==VERIFY_TOKEN:
            return challenge,200
        return 'verification failed',403
    payload=request.get_json(silent=True) or {}
    c=base.db()
    try:
        for entry in payload.get('entry') or []:
            for change in entry.get('changes') or []:
                value=change.get('value') or {}
                contacts={}
                for ct in value.get('contacts') or []:
                    wa_id=_wa_phone(ct.get('wa_id')); name=((ct.get('profile') or {}).get('name') or '').strip(); contacts[wa_id]=name
                for msg in value.get('messages') or []:
                    phone=_wa_phone(msg.get('from')); provider_id=str(msg.get('id') or '')
                    if provider_id and c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?',(provider_id,)).fetchone():
                        continue
                    cu=_customer_by_phone(c,phone); t=_thread_for_phone(c,phone,contacts.get(phone) or (cu['name'] if cu else ''),cu['id'] if cu else None)
                    mtype=str(msg.get('type') or 'unknown'); body=''
                    if mtype=='text': body=((msg.get('text') or {}).get('body') or '')
                    elif mtype=='button': body=((msg.get('button') or {}).get('text') or '')
                    elif mtype=='interactive':
                        inter=msg.get('interactive') or {}; body=((inter.get('button_reply') or {}).get('title') or (inter.get('list_reply') or {}).get('title') or '[Interactivo]')
                    else: body='['+mtype+']'
                    c.execute('''INSERT INTO whatsapp_messages(thread_id,direction,message_type,body,provider_id,status,created_at)
                                 VALUES(?,?,?,?,?,'RECIBIDO',?)''',(t['id'],'IN',mtype,body,provider_id or None,_now()))
                    c.execute('UPDATE whatsapp_threads SET last_message=?,last_at=?,unread=unread+1 WHERE id=?',(body[:500],_now(),t['id']))
                    if mtype=='text' and body and _setting('whatsapp_chatbot_enabled','0')=='1':
                        rules=c.execute('SELECT * FROM whatsapp_bot_rules WHERE active=1 ORDER BY id').fetchall()
                        low=body.lower()
                        for rule in rules:
                            if (rule['keyword'] or '').lower() in low:
                                ok,pid,err=_send_text(phone,rule['reply'])
                                if ok: _record_outgoing(c,t['id'],rule['reply'],pid,'ENVIADO')
                                else: _record_outgoing(c,t['id'],rule['reply'],'','ERROR',err)
                                break
                for st in value.get('statuses') or []:
                    pid=str(st.get('id') or ''); status=str(st.get('status') or '').upper()
                    if pid:
                        c.execute('UPDATE whatsapp_messages SET status=? WHERE provider_id=?',(status,pid))
                        c.execute('UPDATE whatsapp_queue SET status=? WHERE provider_id=?',(status,pid))
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True)


def setup(app):
    ensure_schema()
    app.add_url_rule('/whatsapp',endpoint='whatsapp_inbox',view_func=inbox,methods=['GET'])
    app.add_url_rule('/whatsapp/new',endpoint='whatsapp_new_thread',view_func=new_thread,methods=['POST'])
    app.add_url_rule('/whatsapp/send',endpoint='whatsapp_send',view_func=send,methods=['POST'])
    app.add_url_rule('/whatsapp/queue',endpoint='whatsapp_queue',view_func=queue_page,methods=['GET'])
    app.add_url_rule('/whatsapp/queue/<int:id>/retry',endpoint='whatsapp_retry',view_func=retry,methods=['POST'])
    app.add_url_rule('/whatsapp/settings',endpoint='whatsapp_settings',view_func=settings_page,methods=['GET'])
    app.add_url_rule('/whatsapp/chatbot',endpoint='whatsapp_chatbot',view_func=chatbot_page,methods=['GET','POST'])
    app.add_url_rule('/whatsapp/automatics',endpoint='whatsapp_automatics',view_func=automatics_page,methods=['GET','POST'])
    app.add_url_rule('/whatsapp/templates',endpoint='whatsapp_templates_admin',view_func=templates_admin,methods=['GET','POST'])
    app.add_url_rule('/whatsapp/general',endpoint='whatsapp_general',view_func=general_page,methods=['GET'])
    app.add_url_rule('/webhooks/whatsapp',endpoint='whatsapp_webhook',view_func=webhook,methods=['GET','POST'])
    if not any(x[0]=='whatsapp_inbox' for x in base.NAV):
        try:
            idx=next(i for i,x in enumerate(base.NAV) if x[0]=='audit_page')
        except StopIteration:
            idx=len(base.NAV)
        base.NAV.insert(idx,('whatsapp_inbox','◉','WhatsApp'))
