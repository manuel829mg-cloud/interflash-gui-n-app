"""Read-only MikroTik AI diagnostics for INTER Flash.

This module intentionally cannot execute router commands. It analyzes the state
already synchronized into the platform and produces a repair plan that must be
approved separately before any future executor may act.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from html import escape
from flask import abort, redirect, request, session, url_for
import app as base
import finance_ai

MAX_TABLES = 10
MAX_ROWS = 4

def esc(v):
    return escape(str(v if v is not None else ''))

def admin():
    if not base.logged_in():
        return redirect(url_for('login'))
    if (session.get('role') or 'ADMIN').upper() != 'ADMIN':
        abort(403)

def csrf():
    if 'mikrotik_ai_csrf' not in session:
        import secrets
        session['mikrotik_ai_csrf'] = secrets.token_urlsafe(32)
    return session['mikrotik_ai_csrf']

def check_csrf():
    import hmac
    if not hmac.compare_digest(str(session.get('mikrotik_ai_csrf') or ''), str(request.form.get('csrf') or '')):
        abort(400)

def _safe_value(name, value):
    low = name.lower()
    if any(x in low for x in ('password','secret','token','key','phone','document','address')):
        return '[omitido]'
    text = str(value if value is not None else '')
    return text[:180]

def snapshot():
    c = base.db()
    tables = [r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    interesting = [t for t in tables if any(k in t.lower() for k in ('wan','traffic','router','pool','ppp','optical','onu'))][:MAX_TABLES]
    data = {'fecha': datetime.now().isoformat(timespec='seconds'), 'tablas': {}}
    for table in interesting:
        cols = [r['name'] for r in c.execute(f'PRAGMA table_info("{table}")').fetchall()]
        try:
            rows = c.execute(f'SELECT * FROM "{table}" ORDER BY rowid DESC LIMIT {MAX_ROWS}').fetchall()
        except Exception:
            rows = []
        data['tablas'][table] = {
            'columnas': cols,
            'muestras': [{k:_safe_value(k,row[k]) for k in row.keys()} for row in rows],
        }
    if 'router_commands' in tables:
        data['cola_comandos'] = [dict(r) for r in c.execute(
            "SELECT status,action,COUNT(*) cantidad FROM router_commands GROUP BY status,action ORDER BY status,action"
        ).fetchall()]
    if 'customers' in tables:
        data['clientes'] = [dict(r) for r in c.execute(
            "SELECT COALESCE(status,'ACTIVO') estado,COUNT(*) cantidad FROM customers WHERE COALESCE(status,'ACTIVO')<>'ELIMINADO' GROUP BY COALESCE(status,'ACTIVO')"
        ).fetchall()]
    c.close()
    return data

def ask_mikrotik(question, data):
    key = finance_ai.get_key()
    if not key:
        raise ValueError('La IA no está conectada. Revisa Configurar IA.')
    payload = {
        'model': os.getenv('OPENAI_MODEL') or finance_ai.MODEL,
        'store': False,
        'max_output_tokens': 1400,
        'instructions': (
            'Eres el técnico de diagnóstico MikroTik de INTER Flash para un ISP dominicano. '
            'Analiza únicamente los datos sincronizados que recibes. No tienes acceso directo al router. '
            'No afirmes haber ejecutado cambios. No inventes comandos, interfaces, gateways, IP, perfiles ni causas. '
            'Separa: hallazgos confirmados, posibles causas, datos que faltan, y plan de reparación propuesto. '
            'Toda reparación debe requerir autorización explícita del administrador antes de ejecutarse. '
            'Nunca pidas ni muestres contraseñas, tokens o claves. Prioriza no interrumpir clientes, PBR, failover, '
            'PPPoE, firewall ni rutas existentes. Responde en español claro.'
        ),
        'input': 'Estado sincronizado de INTER Flash (JSON):\n' + json.dumps(data, ensure_ascii=False) +
                 '\nConsulta del administrador:\n' + question,
    }
    req = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.load(response)
        answer = '\n'.join(
            p.get('text','') for item in result.get('output',[]) if item.get('type')=='message'
            for p in item.get('content',[]) if p.get('type')=='output_text'
        ).strip()
        if not answer:
            raise ValueError('La IA no devolvió una respuesta.')
        return answer
    except urllib.error.HTTPError as error:
        messages={401:'La clave API de OpenAI no es válida.',403:'La cuenta API no permite usar este modelo.',429:'OpenAI rechazó la consulta por límite o saldo.'}
        raise ValueError(messages.get(error.code,'No se pudo consultar OpenAI.')) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError('No se pudo conectar con OpenAI.') from None

def page():
    denied=admin()
    if denied:return denied
    data=snapshot(); answer=''; error=''; question=''
    if request.method=='POST':
        check_csrf()
        question=(request.form.get('question') or '').strip()
        if not question or len(question)>1600:
            error='Escribe una consulta de hasta 1600 caracteres.'
        else:
            try:
                answer=ask_mikrotik(question,data)
            except ValueError as e:
                error=str(e)
    queue=data.get('cola_comandos',[])
    queue_html=''.join(f'<tr><td>{esc(x["status"])}</td><td>{esc(x["action"])}</td><td>{x["cantidad"]}</td></tr>' for x in queue)
    body=f'''<div class="head"><div><h1>Diagnóstico MikroTik con IA</h1><p>Analiza la información sincronizada del router sin modificar la red.</p></div></div>
    <div class="panel"><div class="notice">Modo seguro: solo lectura. Ninguna reparación se ejecuta desde esta pantalla. Primero se muestra el diagnóstico y el plan; cualquier cambio futuro requerirá tu autorización.</div>
    <h3>Estado disponible</h3><p>Fuentes de red detectadas: <b>{len(data["tablas"])}</b> · Actualizado: {esc(data["fecha"])}</p>
    <table class="table"><tr><th>Estado cola</th><th>Acción</th><th>Cantidad</th></tr>{queue_html or '<tr><td colspan="3">Sin comandos registrados.</td></tr>'}</table></div>
    <div class="panel"><h3>Revisar un problema</h3>'''
    if error: body+=f'<p class="notice" role="alert">{esc(error)}</p>'
    if answer: body+=f'<div style="white-space:pre-wrap;line-height:1.65;padding:16px;border:1px solid #294159;border-radius:12px">{esc(answer)}</div>'
    body+=f'''<form method="post" id="mt-ai-form"><input type="hidden" name="csrf" value="{csrf()}">
    <label>Describe el problema<textarea class="field" name="question" maxlength="1600" required style="min-height:110px" placeholder="Ejemplo: revisa por qué la Línea 1 aparece con pérdida o por qué un PPPoE no conecta">{esc(question)}</textarea></label>
    <p><button class="btn green" {"disabled" if not finance_ai.get_key() else ""}>Diagnosticar con IA</button></p></form>
    <p class="muted">La IA recibe datos técnicos limitados y sanitizados. No se envían contraseñas, tokens, documentos, teléfonos ni direcciones.</p></div>
    <script>document.getElementById('mt-ai-form').addEventListener('submit',function(){{const b=this.querySelector('button');b.disabled=true;b.textContent='Analizando…';}});</script>'''
    return base.shell('Diagnóstico MikroTik IA',body,'mikrotik_ai_diagnostics')

def setup(app):
    app.add_url_rule('/mikrotik/diagnostico-ia', endpoint='mikrotik_ai_diagnostics', view_func=page, methods=['GET','POST'])
    if not any(x[0]=='mikrotik_ai_diagnostics' for x in base.NAV):
        base.NAV.append(('mikrotik_ai_diagnostics','✦','Diagnóstico MikroTik IA'))
