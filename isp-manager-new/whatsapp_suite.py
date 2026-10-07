import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from html import escape
from flask import session, request, redirect, url_for, flash, jsonify, current_app
import app as base
import ultramsg_suite as ultra
import whapi_suite as whapi
import greenapi_suite as greenapi

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
    CREATE TABLE IF NOT EXISTS whatsapp_webhook_health(
      id INTEGER PRIMARY KEY CHECK(id=1), last_event TEXT, last_incoming TEXT,
      last_verification TEXT
    );
    INSERT OR IGNORE INTO whatsapp_webhook_health(id) VALUES(1);
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
    ''')
    if c.execute('SELECT COUNT(*) c FROM whatsapp_local_templates').fetchone()['c'] == 0:
        c.executemany('INSERT INTO whatsapp_local_templates(code,title,body,active) VALUES(?,?,?,1)', [
            ('bienvenida','Bienvenida','¡Hola! Bienvenido a INTER Flash. Estamos a tu orden para soporte, pagos y consultas.'),
            ('factura','Factura disponible','Hola, tu factura de INTER Flash ya está disponible. Puedes realizar tu pago por nuestros canales habituales.'),
            ('vencimiento','Aviso de vencimiento','Hola, te recordamos que tu servicio de internet INTER Flash tiene una factura próxima a vencer.'),
            ('suspension','Aviso de suspensión','Hola, tu servicio INTER Flash presenta una factura vencida. Regulariza el pago para evitar o levantar la suspensión.'),
            ('pago','Pago recibido','¡Gracias! Hemos recibido tu pago de INTER Flash correctamente.')
        ])
    c.commit(); c.close()


def _meta_ready():
    return greenapi.enabled() or whapi.enabled() or ultra.enabled() or bool(ACCESS_TOKEN and PHONE_NUMBER_ID)

def _provider_label():
    return 'GREEN-API' if greenapi.enabled() else 'Whapi.Cloud' if whapi.enabled() else 'UltraMsg' if ultra.enabled() else 'Meta Cloud API'


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
    if greenapi.enabled():
        return greenapi.send_text(_wa_phone(phone), body)
    if whapi.enabled():
        return whapi.send_text(_wa_phone(phone), body)
    if ultra.enabled():
        return ultra.send_text(_wa_phone(phone), body)
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
    if greenapi.enabled():
        return False, '', 'Con GREEN-API usa una respuesta rápida de texto; las plantillas de Meta requieren Meta.'
    if whapi.enabled():
        return False, '', 'Con Whapi.Cloud usa una respuesta rápida de texto; las plantillas de Meta requieren Meta.'
    if ultra.enabled():
        return False, '', 'Las plantillas aprobadas de Meta requieren Meta. Con UltraMsg usa una respuesta rápida de texto.'
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
    if provider_id.startswith('greenapi:'):
        status = greenapi.confirmed_status(c, provider_id, status)
    if provider_id.startswith('whapi:'):
        status = whapi.confirmed_status(c, provider_id, status)
    if provider_id.startswith('ultra:'):
        status = ultra.confirmed_status(c, provider_id, status)
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
        status=greenapi.confirmed_status(c,provider_id,'ACEPTADO') if provider_id.startswith('greenapi:') else whapi.confirmed_status(c,provider_id,'ACEPTADO') if provider_id.startswith('whapi:') else ultra.confirmed_status(c,provider_id,'ACEPTADO') if provider_id.startswith('ultra:') else 'ACEPTADO'
        c.execute("UPDATE whatsapp_queue SET status=?,provider_id=?,sent_at=?,last_error=NULL WHERE id=?",
                  (status,provider_id,_now(),row['id']))
        if row['thread_id']:
            _record_outgoing(c,row['thread_id'],visible_body,provider_id,'ACEPTADO')
    else:
        c.execute("UPDATE whatsapp_queue SET status='ERROR',last_error=? WHERE id=?", (err,row['id']))
        if row['thread_id']:
            _record_outgoing(c,row['thread_id'],visible_body,'','ERROR',err)
    c.commit()
    return ok, err


def _public_webhook_url():
    # Railway terminates TLS before forwarding requests to Gunicorn.
    return url_for('whatsapp_webhook', _external=True, _scheme='https')


def _reception_summary(c):
    row = c.execute('SELECT * FROM whatsapp_webhook_health WHERE id=1').fetchone()
    if row and row['last_incoming']:
        return 'Última entrada recibida: ' + row['last_incoming'] + ' (hora del servidor)'
    if row and row['last_event']:
        return 'Webhook recibido; todavía sin mensaje entrante registrado.'
    return 'Recepción sin comprobar: aún no se ha registrado un webhook con esta versión.'


def revision():
    if not base.logged_in():
        return jsonify(error='Sesión terminada'), 401
    c = base.db()
    try:
        rows = c.execute('SELECT status,COUNT(*),MAX(id) FROM whatsapp_messages GROUP BY status ORDER BY status').fetchall()
        health = c.execute('SELECT * FROM whatsapp_webhook_health WHERE id=1').fetchone()
        import hashlib
        value = hashlib.sha256(repr(([tuple(r) for r in rows], tuple(health) if health else None)).encode()).hexdigest()
        response = jsonify(revision=value)
        response.headers['Cache-Control'] = 'no-store'
        return response
    finally:
        c.close()


def _customer_card(c, thread):
    if not thread:
        return ''
    customer = None
    if thread['customer_id']:
        customer = c.execute("SELECT * FROM customers WHERE id=? AND COALESCE(status,'')<>'ELIMINADO'", (thread['customer_id'],)).fetchone()
    if not customer:
        match = _customer_by_phone(c, thread['phone'])
        if match: customer = c.execute('SELECT * FROM customers WHERE id=?', (match['id'],)).fetchone()
    actions = []
    def draft(label, text):
        return f'<button type="button" class="btn wa-draft" data-message="{esc(text)}">{esc(label)}</button>'
    if customer:
        plan = c.execute('SELECT name FROM plans WHERE id=?', (customer['plan_id'],)).fetchone()
        invoices = c.execute('''SELECT i.*, COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0) paid
            FROM invoices i WHERE i.customer_id=? AND i.status IN ('PENDIENTE','VENCIDA') ORDER BY i.due_date,i.id''', (customer['id'],)).fetchall()
        pending = [(i, max(0, float(i['amount'] or 0)-float(i['paid'] or 0))) for i in invoices]
        pending = [(i, amount) for i, amount in pending if amount > 0.005]
        balance = sum(amount for _, amount in pending)
        due = pending[0][0]['due_date'] if pending else 'Sin facturas pendientes'
        profile = url_for('customer_profile', id=customer['id']) if 'customer_profile' in current_app.view_functions else url_for('customers')
        details = f'''<b>{esc(customer['name'])}</b><span class="tag">{esc(customer['status'])}</span>
        <div class="wa-facts"><div><small>Plan</small>{esc(plan['name'] if plan else 'Sin plan asignado')}</div><div><small>Saldo de facturas</small>RD${balance:,.2f}</div><div><small>Vencimiento más próximo</small>{esc(due)}</div></div>
        <a class="btn" href="{profile}">Ver ficha completa</a>'''
        if pending:
            inv, amount = pending[0]
            actions.append(draft('Resumen de factura', f"Hola, {customer['name']}. Tu factura #{inv['id']} de INTER Flash: {inv['concept']}. Saldo pendiente: RD${amount:,.2f}. Vencimiento: {inv['due_date']}."))
            actions.append(draft('Recordar pago', f"Hola, {customer['name']}. Te recordamos que tienes RD${balance:,.2f} pendientes en facturas de INTER Flash. Vencimiento más próximo: {due}. Si ya pagaste, envíanos el comprobante para revisarlo. Gracias."))
    else:
        details = '<b>Contacto sin cliente asociado</b><p class="muted">No encontramos un cliente activo registrado con este número.</p>'
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bank_accounts'").fetchone():
        banks = c.execute("SELECT * FROM bank_accounts WHERE active=1 AND COALESCE(account_number,'')<>'' ORDER BY id").fetchall()
        if banks:
            text = 'Cuentas para pagos de INTER Flash:\n' + '\n\n'.join(f"{b['bank']} · {b['account_type'] or ''}\nCuenta: {b['account_number']}\n{b['label'] or ''}" for b in banks) + '\n\nEnvíanos tu comprobante después de pagar.'
            actions.append(draft('Cuentas bancarias', text))
    actions.append(draft('Solicitar comprobante', 'Hola, por favor envíanos el comprobante de pago y el nombre del titular del servicio para revisarlo. Gracias por elegir INTER Flash.'))
    return f'<div class="wa-customer"><h3>Ficha del cliente</h3>{details}<div class="wa-actions">{"".join(actions)}</div><small class="muted">Los botones preparan un borrador. Revísalo antes de enviar.</small></div>'


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
            messages=c.execute('SELECT * FROM whatsapp_messages WHERE thread_id=? ORDER BY created_at DESC,id DESC LIMIT 120',(thread['id'],)).fetchall()[::-1]
            c.commit()
    queue_pending=c.execute("SELECT COUNT(*) c FROM whatsapp_queue WHERE status IN ('PENDIENTE','EN_PROCESO')").fetchone()['c']
    queue_error=c.execute("SELECT COUNT(*) c FROM whatsapp_queue WHERE status='ERROR'").fetchone()['c']
    unread=c.execute('SELECT COALESCE(SUM(unread),0) c FROM whatsapp_threads').fetchone()['c']
    templates=c.execute('SELECT * FROM whatsapp_local_templates WHERE active=1 ORDER BY id').fetchall()
    reception = _reception_summary(c)
    customer_card = _customer_card(c, thread)
    c.close()

    import secrets
    sync_csrf = session.setdefault('green_sync_csrf', secrets.token_urlsafe(32))
    sync_button = ''; history_button = ''; avatars = {}
    if greenapi.enabled():
        c = base.db()
        avatars = {r['thread_id']: r['avatar'] for r in c.execute('SELECT * FROM greenapi_chat_profiles WHERE instance=?', (greenapi.config()['channel'],)).fetchall()}
        c.close()
        if session.get('role') == 'ADMIN':
            sync_button = f'<form method="post" action="{url_for("greenapi_sync")}"><input type="hidden" name="csrf" value="{esc(sync_csrf)}"><button class="btn green">Chats</button></form>'
            if thread:
                history_button = f'<form method="post" action="{url_for("greenapi_chat_load",thread_id=thread["id"])}" style="display:flex;gap:8px;padding:10px"><input type="hidden" name="csrf" value="{esc(sync_csrf)}"><button class="btn" name="action" value="history">Cargar historial</button><button class="btn" name="action" value="avatar">Cargar foto</button></form>'
    trows=[]
    for t in threads:
        label=t['customer_name'] or t['display_name'] or t['phone']
        unread_badge=f'<span class="wa-unread">{int(t["unread"] or 0)}</span>' if t['unread'] else ''
        avatar = f'<img src="{esc(avatars[t["id"]])}" alt="" referrerpolicy="no-referrer" loading="lazy" style="width:42px;height:42px;object-fit:cover;border-radius:50%">' if avatars.get(t['id']) else esc((label or '?')[:1].upper())
        trows.append(f'''<a class="wa-thread {'on' if thread and t['id']==thread['id'] else ''}" href="{url_for('whatsapp_inbox',thread=t['id'],q=q)}"><div class="wa-avatar">{avatar}</div><div class="wa-thread-main"><b>{esc(label)}</b><small>{esc(t['phone'])}</small><span>{esc((t['last_message'] or 'Sin mensajes')[:78])}</span></div>{unread_badge}</a>''')
    bubbles=[]
    for m in messages:
        out=m['direction']=='OUT'
        meta=f"{esc((m['created_at'] or '')[11:16])} · {esc(m['status'] or '')}"
        if m['error']: meta += ' · ' + esc(m['error'][:80])
        bubbles.append(f'''<div class="wa-msg {'out' if out else 'in'}"><div>{esc(m['body'] or '['+str(m['message_type'] or 'mensaje')+']')}</div><small>{meta}</small></div>''')
    template_opts=''.join(f'<option value="{esc(x["body"])}">{esc(x["title"])}</option>' for x in templates)
    composer='''<div class="wa-empty">Selecciona una conversación o inicia una nueva.</div>'''
    if thread:
        composer=f'''<div class="wa-chat-head"><div><b>{esc(thread['customer_name'] or thread['display_name'] or thread['phone'])}</b><small>{esc(thread['phone'])}</small></div><span class="tag {'ok' if _meta_ready() else 'warn'}">{'Credenciales cargadas' if _meta_ready() else 'Conexión pendiente'}</span></div>
        {customer_card}{history_button}<div class="wa-messages">{''.join(bubbles) or '<div class="wa-empty">Todavía no hay mensajes.</div>'}</div>
        <form class="wa-compose" method="post" action="{url_for('whatsapp_send')}"><input type="hidden" name="thread_id" value="{thread['id']}"><input type="hidden" name="phone" value="{esc(thread['phone'])}"><select class="field" onchange="if(this.value){{this.form.body.value=this.value;this.selectedIndex=0}}"><option value="">Plantillas rápidas…</option>{template_opts}</select><textarea class="field" name="body" rows="2" placeholder="Escribe un mensaje…" required></textarea><button class="btn green">Enviar</button></form>'''

    configured='Credenciales de envío cargadas. La entrega se confirma por mensaje.' if _meta_ready() else 'Faltan WHATSAPP_ACCESS_TOKEN y WHATSAPP_PHONE_NUMBER_ID en Railway.'
    if ultra.enabled():
        configured='UltraMsg configurado. La entrega se confirma por mensaje.'
    webhook_state='Token de verificación listo.' if VERIFY_TOKEN else 'Falta WHATSAPP_VERIFY_TOKEN para activar el webhook.'
    if ultra.enabled():
        webhook_state='Recepción de UltraMsg configurada.'
    if whapi.enabled():
        configured='Whapi.Cloud configurado. La entrega se confirma por mensaje.'
        webhook_state='Recepción de Whapi.Cloud configurada.'
    if greenapi.enabled():
        configured='GREEN-API configurado. La entrega se confirma por mensaje.'
        webhook_state='Recepción de GREEN-API configurada.'
    body=f'''<style>
    .wa-kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.wa-layout{{display:grid;grid-template-columns:360px 1fr;gap:14px;min-height:640px}}.wa-side,.wa-chat{{background:#0d1a29;border:1px solid #22374e;border-radius:12px;overflow:hidden}}.wa-side-head{{padding:14px;border-bottom:1px solid #22374e}}.wa-side-head form{{display:flex;gap:7px}}.wa-side-head input{{width:100%}}.wa-threads{{max-height:590px;overflow:auto}}.wa-thread{{display:grid;grid-template-columns:44px 1fr auto;gap:10px;padding:12px;border-bottom:1px solid #1b3045;align-items:center}}.wa-thread:hover,.wa-thread.on{{background:#122438}}.wa-avatar{{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:#075e54;color:#fff;font-weight:900}}.wa-thread-main{{min-width:0}}.wa-thread-main b,.wa-thread-main small,.wa-thread-main span{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.wa-thread-main small{{color:#7f94aa;margin:2px 0}}.wa-thread-main span{{color:#9fb0c0;font-size:12px}}.wa-unread{{min-width:22px;height:22px;padding:0 6px;border-radius:999px;background:#16c784;color:#052d1f;display:grid;place-items:center;font-size:11px;font-weight:900}}.wa-chat{{display:flex;flex-direction:column}}.wa-chat-head{{padding:14px 16px;border-bottom:1px solid #22374e;display:flex;justify-content:space-between;align-items:center}}.wa-chat-head small{{display:block;color:#8397aa;margin-top:3px}}.wa-messages{{height:520px;min-height:240px;flex:1;overflow:auto;padding:18px;background:radial-gradient(circle at 30% 10%,#10243a,#0a1522 55%)}}.wa-msg{{max-width:72%;padding:10px 12px;border-radius:11px;margin:8px 0;line-height:1.35}}.wa-msg.in{{background:#182a3d;margin-right:auto}}.wa-msg.out{{background:#075e54;margin-left:auto}}.wa-msg small{{display:block;color:#b9c8d5;font-size:10px;margin-top:6px;text-align:right}}.wa-compose{{padding:12px;border-top:1px solid #22374e;display:grid;grid-template-columns:190px 1fr auto;gap:8px;align-items:end}}.wa-compose textarea{{resize:vertical;min-height:44px}}.wa-empty{{padding:40px;text-align:center;color:#8397aa}}.wa-config{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media(max-width:950px){{.wa-layout{{grid-template-columns:1fr}}.wa-side{{max-height:360px}}.wa-kpis{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:650px){{.wa-compose{{grid-template-columns:1fr}}.wa-config{{grid-template-columns:1fr}}.wa-kpis{{grid-template-columns:1fr}}}}
    .wa-kpis .kpi{{padding:12px}}.wa-kpis .value{{font-size:24px}}.wa-status{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0;color:#aebdcb;font-size:12px}}.wa-customer{{padding:14px 16px;background:#102237;border-bottom:1px solid #22374e}}.wa-customer h3{{margin:0 0 8px;font-size:13px;color:#9fb0c0}}.wa-customer>.tag{{margin-left:10px}}.wa-facts{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}}.wa-facts small{{display:block;color:#9fb0c0;margin-bottom:4px}}.wa-actions{{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0 8px}}.wa-actions .btn{{font-size:12px;padding:8px 10px}}.wa-msg>div{{white-space:pre-wrap;overflow-wrap:anywhere}}.wa-messages{{height:420px}}@media(max-width:650px){{.wa-facts{{grid-template-columns:1fr}}.wa-msg{{max-width:90%}}}}
    </style>
    <div class="head"><div><h1>WhatsApp</h1><p>Bandeja de chats y cola de mensajes · {esc(_provider_label())}.</p></div><div style="display:flex;gap:8px;flex-wrap:wrap">{sync_button}<a class="btn" href="{url_for('whatsapp_queue')}">Cola</a><a class="btn green" href="{url_for('greenapi_settings')}">GREEN-API</a><a class="btn blue" href="{url_for('whatsapp_settings')}">Configuración</a></div></div>
    <div class="wa-status"><span class="tag">{esc(_provider_label())}</span><span id="wa-reception">{esc(reception)}</span><small id="wa-sync">Actualización automática</small></div><div class="wa-kpis"><div class="kpi green1"><div class="label">Conexión</div><div class="value" style="font-size:18px">{'CONFIGURADA' if _meta_ready() else 'PENDIENTE'}</div><div class="sub">{esc(_provider_label())}</div></div><div class="kpi blue1"><div class="label">Chats</div><div class="value">{len(threads)}</div><div class="sub">Cargados</div></div><div class="kpi orange1"><div class="label">No leídos</div><div class="value">{unread}</div><div class="sub">Mensajes</div></div><div class="kpi {\'orange1\' if queue_pending else \'green1\'}"><div class="label">Cola pendiente</div><div class="value">{queue_pending}</div><div class="sub">{\'En proceso o por enviar\' if queue_pending else \'Sin mensajes pendientes\'}</div></div></div>
    <div class="muted" style="margin:8px 0">{(str(queue_error) + \' envíos fallidos registrados en el historial. Consulta el detalle en Cola.\') if queue_error else \'\'}</div>\n    <details class="panel"><summary class="btn">+ Nueva conversación</summary><form method="post" action="{url_for('whatsapp_new_thread')}" class="toolbar" style="margin:0"><input class="field" name="phone" placeholder="Número para nueva conversación" required><input class="field" name="name" placeholder="Nombre (opcional)"><button class="btn green">Crear conversación</button></form></details>
    <div class="wa-layout"><div class="wa-side"><div class="wa-side-head"><form method="get"><input class="field" name="q" value="{esc(q)}" placeholder="Buscar nombre o número"><button class="btn">Buscar</button></form></div><div class="wa-threads">{''.join(trows) or '<div class="wa-empty">Sin conversaciones todavía.</div>'}</div></div><div class="wa-chat">{composer}</div></div>'''
    body += r"""<script>
    (() => {
      document.querySelectorAll('.wa-draft').forEach(button => button.addEventListener('click', () => {
        const input = document.querySelector('.wa-compose textarea');
        if (!input) return;
        if (input.value.trim() && !confirm('¿Reemplazar el borrador actual?')) return;
        input.value = button.dataset.message; input.focus();
        input.scrollIntoView({behavior:'smooth', block:'center'});
      }));
      let previous = null, busy = false;
      const box = document.querySelector('.wa-messages');
      if (box) box.scrollTop = box.scrollHeight;
      async function refresh() {
        if (busy || document.hidden) return;
        busy = true;
        try {
          const response = await fetch('/whatsapp/revision', {cache:'no-store'});
          if (!response.ok) throw new Error('session');
          const data = await response.json();
          if (previous !== data.revision) {
            const page = await fetch(location.href, {cache:'no-store'});
            if (!page.ok || page.redirected) throw new Error('session');
            const doc = new DOMParser().parseFromString(await page.text(), 'text/html');
            for (const selector of ['.wa-messages', '.wa-threads', '#wa-reception', '.wa-kpis']) {
              const old = document.querySelector(selector), fresh = doc.querySelector(selector);
              if (!old || !fresh) continue;
              const bottom = old.scrollHeight - old.scrollTop - old.clientHeight < 80;
              const scroll = old.scrollTop;
              old.replaceChildren(...fresh.childNodes);
              old.scrollTop = selector === '.wa-messages' && bottom ? old.scrollHeight : scroll;
            }
            previous = data.revision;
          }
          document.querySelector('#wa-sync').textContent = 'Actualizado: ' + new Date().toLocaleTimeString();
        } catch (_) {
          document.querySelector('#wa-sync').textContent = 'No se pudo actualizar. Revisa la conexión o recarga la página.';
        } finally { busy = false; }
      }
      refresh(); setInterval(refresh, 5000);
    })();
    </script>"""
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
    if ok: flash('El proveedor aceptó el mensaje. Esperando confirmación de entrega.')
    else: flash('Mensaje guardado, pero no pudo enviarse: '+err)
    return redirect(url_for('whatsapp_inbox',thread=t['id']))


def queue_page():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c=base.db(); rows=c.execute('SELECT * FROM whatsapp_queue ORDER BY id DESC LIMIT 250').fetchall(); c.close()
    trs=[]
    for r in rows:
        cls='ok' if r['status'] in ('ENVIADO','ENTREGADO','LEÍDO') else 'bad' if r['status']=='ERROR' else 'warn'
        retry=f'''<form method="post" action="{url_for('whatsapp_retry',id=r['id'])}"><button class="btn">Reintentar</button></form>''' if r['status']=='ERROR' else ''
        trs.append(f'''<tr><td>#{r['id']}</td><td>{esc(r['phone'])}</td><td>{esc((r['body'] or ('Plantilla: '+str(r['template_name'] or '')))[:100])}</td><td><span class="tag {cls}">{esc(r['status'])}</span></td><td>{r['attempts']}</td><td>{esc(r['last_error'] or '-')}</td><td>{esc(r['created_at'])}</td><td>{retry}</td></tr>''')
    body=f'''<div class="head"><div><h1>Cola de WhatsApp</h1><p>Historial de envíos: entregados, pendientes y fallidos.</p><p class="muted">Los errores conservan el resultado de cada intento anterior; no indican por sí solos que la conexión actual esté fallando. Reintentar envía el mensaje nuevamente.</p></div><a class="btn" href="{url_for('whatsapp_inbox')}">← WhatsApp</a></div><div class="panel"><table class="table"><tr><th>#</th><th>Número</th><th>Mensaje</th><th>Estado</th><th>Intentos</th><th>Error</th><th>Fecha</th><th></th></tr>{''.join(trs) or '<tr><td colspan="8" class="muted">Sin mensajes en cola.</td></tr>'}</table></div>'''
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
    trs=''.join(f'''<tr><td>{esc(x['title'])}</td><td><code>{esc(x['code'])}</code></td><td>{esc(x['body'])}</td></tr>''' for x in templates)
    vars_rows=[
        ('WHATSAPP_ACCESS_TOKEN',bool(ACCESS_TOKEN),'Token de acceso cargado; su vigencia no se comprueba aquí'),
        ('WHATSAPP_PHONE_NUMBER_ID',bool(PHONE_NUMBER_ID),'ID del número de WhatsApp Business'),
        ('WHATSAPP_VERIFY_TOKEN',bool(VERIFY_TOKEN),'Token que usarás al verificar el webhook'),
        ('WHATSAPP_BUSINESS_NUMBER',bool(BUSINESS_NUMBER),'Opcional: número visible; no controla la recepción'),
        ('WHATSAPP_GRAPH_VERSION',bool(GRAPH_VERSION),f'Actual: {GRAPH_VERSION}'),
    ]
    vr=''.join(f'''<tr><td><code>{esc(n)}</code></td><td><span class="tag {'ok' if ok else 'warn'}">{'CARGADO' if ok else 'OPCIONAL' if n=='WHATSAPP_BUSINESS_NUMBER' else 'FALTA'}</span></td><td>{esc(desc)}</td></tr>''' for n,ok,desc in vars_rows)
    body=f'''<div class="head"><div><h1>Configuración WhatsApp</h1><p>Proveedor de envío: {esc(_provider_label())}.</p></div><a class="btn" href="{url_for('whatsapp_inbox')}">← WhatsApp</a></div><div class="panel"><h3>GREEN-API por QR</h3><p>Conecta tu instancia autorizada de GREEN-API.</p><a class="btn green" href="{url_for('greenapi_settings')}">Configurar GREEN-API</a></div><div class="panel"><h3>Plantillas internas</h3><p class="muted">Textos disponibles como respuestas rápidas en tus conversaciones.</p><table class="table"><tr><th>Nombre</th><th>Código</th><th>Texto</th></tr>{trs}</table></div>'''
    c = base.db()
    reception = _reception_summary(c)
    c.close()
    webhook_url = url_for('greenapi_webhook', _external=True, _scheme='https')
    body += f'''<div class="panel"><h3>Estado de recepción</h3><p>{esc(reception)}</p><p class="muted">Webhook: {esc(webhook_url)}</p></div>
    <div class="panel"><h3>Prueba de envío</h3><form method="post" action="{url_for('whatsapp_send')}" class="toolbar"><input class="field" name="phone" placeholder="Número de otro teléfono, ej. 18095551234" required><input class="field" name="body" value="Hola, esta es una prueba de INTER Flash." required><button class="btn green">Enviar prueba</button></form><p class="muted">Comprueba la llegada en el teléfono destinatario. Se aplican los límites de tu plan.</p></div>'''
    return base.shell('Configuración WhatsApp',body,'whatsapp_inbox')


def _receive_webhook():
    ensure_schema()
    if request.method=='GET':
        mode=request.args.get('hub.mode'); token=request.args.get('hub.verify_token'); challenge=request.args.get('hub.challenge','')
        if mode=='subscribe' and VERIFY_TOKEN and token==VERIFY_TOKEN:
            c=base.db()
            c.execute('UPDATE whatsapp_webhook_health SET last_verification=? WHERE id=1', (_now(),))
            c.commit(); c.close()
            return challenge,200
        return 'verification failed',403
    payload=request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('entry'), list):
        return jsonify(error='Formato de webhook inválido'),400
    c=base.db()
    try:
        c.execute('UPDATE whatsapp_webhook_health SET last_event=? WHERE id=1', (_now(),))
        for entry in payload.get('entry') or []:
            for change in entry.get('changes') or []:
                value=change.get('value') or {}
                contacts={}
                for ct in value.get('contacts') or []:
                    wa_id=_wa_phone(ct.get('wa_id')); name=((ct.get('profile') or {}).get('name') or '').strip(); contacts[wa_id]=name
                for msg in value.get('messages') or []:
                    phone=_wa_phone(msg.get('from')); provider_id=str(msg.get('id') or '')
                    if not phone or not provider_id:
                        continue
                    if provider_id and c.execute('SELECT 1 FROM whatsapp_messages WHERE provider_id=?',(provider_id,)).fetchone():
                        continue
                    c.execute('UPDATE whatsapp_webhook_health SET last_incoming=? WHERE id=1', (_now(),))
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
                for st in value.get('statuses') or []:
                    pid=str(st.get('id') or ''); status=str(st.get('status') or '').upper()
                    mapped={'SENT':'ENVIADO','DELIVERED':'ENTREGADO','READ':'LEÍDO','FAILED':'ERROR'}.get(status)
                    if pid and mapped:
                        errors=st.get('errors') or []
                        detail='; '.join(str(e.get('code','')) + ': ' + str(e.get('title','')) for e in errors)[:500] or None
                        old=c.execute('SELECT status FROM whatsapp_messages WHERE provider_id=?',(pid,)).fetchone()
                        rank={'ENVIADO':1,'ENTREGADO':2,'LEÍDO':3}
                        if old and mapped!='ERROR' and rank.get(old['status'],0)>rank.get(mapped,0):
                            continue
                        c.execute('UPDATE whatsapp_messages SET status=?,error=? WHERE provider_id=?',(mapped,detail,pid))
                        c.execute('UPDATE whatsapp_queue SET status=?,last_error=? WHERE provider_id=?',(mapped,detail,pid))
        c.commit()
    finally:
        c.close()
    return jsonify(ok=True)


def webhook():
    try:
        result = _receive_webhook()
        current_app.logger.info('WhatsApp webhook processed method=%s', request.method)
        return result
    except Exception as exc:
        # Log the exception type without tokens, phone numbers or message bodies.
        current_app.logger.error('WhatsApp webhook failed type=%s', type(exc).__name__)
        return jsonify(error='No se pudo guardar el evento'), 500


def setup(app):
    ensure_schema()
    ultra.setup(app)
    whapi.setup(app)
    greenapi.setup(app)
    import greenapi_chats
    greenapi_chats.setup(app)
    app.add_url_rule('/whatsapp',endpoint='whatsapp_inbox',view_func=inbox,methods=['GET'])
    app.add_url_rule('/whatsapp/revision',endpoint='whatsapp_revision',view_func=revision,methods=['GET'])
    app.add_url_rule('/whatsapp/new',endpoint='whatsapp_new_thread',view_func=new_thread,methods=['POST'])
    app.add_url_rule('/whatsapp/send',endpoint='whatsapp_send',view_func=send,methods=['POST'])
    app.add_url_rule('/whatsapp/queue',endpoint='whatsapp_queue',view_func=queue_page,methods=['GET'])
    app.add_url_rule('/whatsapp/queue/<int:id>/retry',endpoint='whatsapp_retry',view_func=retry,methods=['POST'])
    app.add_url_rule('/whatsapp/settings',endpoint='whatsapp_settings',view_func=settings_page,methods=['GET'])
    app.add_url_rule('/webhooks/whatsapp',endpoint='whatsapp_webhook',view_func=webhook,methods=['GET','POST'])
    if not any(x[0]=='whatsapp_inbox' for x in base.NAV):
        try:
            idx=next(i for i,x in enumerate(base.NAV) if x[0]=='audit_page')
        except StopIteration:
            idx=len(base.NAV)
        base.NAV.insert(idx,('whatsapp_inbox','◉','WhatsApp'))
