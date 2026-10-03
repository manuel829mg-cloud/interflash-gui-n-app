import os, hmac, json
from datetime import datetime
from html import escape
from flask import request, jsonify, redirect, url_for, flash, session
import app as base

TOKEN=os.getenv('MIKROTIK_CONTROL_TOKEN','')


def _auth():
    supplied=request.headers.get('X-InterFlash-Control','')
    return bool(TOKEN) and hmac.compare_digest(supplied,TOKEN)


def _safe(v,n=500):
    return '' if v is None else str(v)[:n]


def queue(customer_id,action,payload=None):
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(customer_id,)).fetchone()
    if not cu or not cu['pppoe']:
        c.close(); return False,'El cliente no tiene usuario PPPoE.'
    action=action.upper()
    allowed={'SUSPEND','REACTIVATE','CHANGE_PROFILE','CHANGE_PASSWORD','CREATE_PPPOE','DELETE_PPPOE'}
    if action not in allowed:
        c.close(); return False,'Acción no permitida.'
    c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(
        cu['router_name'] or 'CCR2116',customer_id,cu['pppoe'],action,json.dumps(payload or {},ensure_ascii=False),'PENDIENTE',datetime.now().isoformat(timespec='seconds'),session.get('user') or base.ADMIN_USER))
    c.commit(); c.close(); return True,'Comando agregado a la cola.'


def queue_customer_command(id,action):
    if not base.logged_in(): return redirect(url_for('login'))
    payload={}
    if action.upper()=='CHANGE_PROFILE': payload={'profile':request.form.get('profile','')}
    if action.upper()=='CHANGE_PASSWORD': payload={'password':request.form.get('password','')}
    ok,msg=queue(id,action,payload); flash(msg); return redirect(url_for('customer_profile',id=id))


def commands_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); rows=c.execute('''SELECT rc.*,cu.name customer FROM router_commands rc LEFT JOIN customers cu ON cu.id=rc.customer_id ORDER BY rc.id DESC LIMIT 200''').fetchall(); c.close()
    trs=[]
    for r in rows:
        cls='ok' if r['status']=='COMPLETADO' else 'bad' if r['status']=='ERROR' else 'warn'
        trs.append(f'''<tr><td>#{r['id']}</td><td>{escape(r['router_name'] or '')}</td><td>{escape(r['customer'] or '-')}</td><td>{escape(r['pppoe'] or '-')}</td><td>{escape(r['action'])}</td><td><span class="tag {cls}">{escape(r['status'])}</span></td><td>{escape(r['created_at'] or '-')}</td><td>{escape(r['result'] or '-')}</td></tr>''')
    body=f'''<div class="head"><div><h1>Control MikroTik</h1><p>Cola segura de cambios para PPPoE</p></div><a class="btn blue" href="{url_for('mikrotik_control_script')}">Ver script del agente</a></div><div class="panel"><div class="notice" style="background:#4e3707;color:#fff">Los botones de clientes agregan órdenes aquí. Para ejecutar órdenes reales en el CCR2116 debes instalar una sola vez el agente de control mostrado en “Ver script del agente”.</div><table class="table"><tr><th>#</th><th>Router</th><th>Cliente</th><th>PPPoE</th><th>Acción</th><th>Estado</th><th>Fecha</th><th>Resultado</th></tr>{''.join(trs) or '<tr><td colspan=8 class=muted>Sin comandos.</td></tr>'}</table></div>'''
    return base.shell('Control MikroTik',body,'routers')


def command_next():
    if not _auth(): return jsonify(ok=False,error='unauthorized'),401
    router=_safe(request.args.get('router') or 'CCR2116',80)
    c=base.db(); row=c.execute("SELECT * FROM router_commands WHERE router_name=? AND status='PENDIENTE' ORDER BY id LIMIT 1",(router,)).fetchone()
    if not row: c.close(); return jsonify(ok=True,id=0)
    c.execute("UPDATE router_commands SET status='EN_PROCESO' WHERE id=?",(row['id'],)); c.commit(); c.close()
    try: payload=json.loads(row['payload'] or '{}')
    except: payload={}
    return jsonify(ok=True,id=row['id'],action=row['action'],pppoe=row['pppoe'],payload=payload)


def command_result():
    if not _auth(): return jsonify(ok=False,error='unauthorized'),401
    p=request.get_json(silent=True) or {}; cid=int(p.get('id') or 0); ok=bool(p.get('ok')); result=_safe(p.get('result'),500)
    c=base.db(); cmd=c.execute('SELECT * FROM router_commands WHERE id=?',(cid,)).fetchone()
    if not cmd: c.close(); return jsonify(ok=False,error='not-found'),404
    status='COMPLETADO' if ok else 'ERROR'; c.execute('UPDATE router_commands SET status=?,executed_at=?,result=? WHERE id=?',(status,datetime.now().isoformat(timespec='seconds'),result,cid))
    if ok and cmd['customer_id']:
        if cmd['action']=='SUSPEND': c.execute("UPDATE customers SET status='SUSPENDIDO',service_status='SUSPENDIDO' WHERE id=?",(cmd['customer_id'],))
        elif cmd['action']=='REACTIVATE': c.execute("UPDATE customers SET status='ACTIVO',service_status='ACTIVO' WHERE id=?",(cmd['customer_id'],))
    c.commit(); c.close(); return jsonify(ok=True)


def mikrotik_control_script():
    if not base.logged_in(): return redirect(url_for('login'))
    if not TOKEN:
        return base.shell('Agente MikroTik','<div class="panel"><div class="notice">Falta MIKROTIK_CONTROL_TOKEN en Railway.</div></div>','routers')
    root=request.url_root.rstrip('/')
    script=f'''/system script remove [find where name="interflash-control"]
/system scheduler remove [find where name="interflash-control-scheduler"]
/system script add name="interflash-control" policy=read,write,test source={{
  :local base "{root}";
  :local token "{TOKEN}";
  :local hdr ("X-InterFlash-Control: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/control/next?router=CCR2116") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local body ($r->"data");
  :local d [:deserialize from=json value=$body];
  :if (($d->"ok") != true) do={{ :return; }}
  :local id ($d->"id");
  :if ($id = 0) do={{ :return; }}
  :local action ($d->"action");
  :local user ($d->"pppoe");
  :local p ($d->"payload");
  :local ok true;
  :local result "OK";
  :do {{
    :if ($action="SUSPEND") do={{ /ppp secret set [find where name=$user] disabled=yes; }}
    :if ($action="REACTIVATE") do={{ /ppp secret set [find where name=$user] disabled=no; }}
    :if ($action="CHANGE_PROFILE") do={{ /ppp secret set [find where name=$user] profile=($p->"profile"); }}
    :if ($action="CHANGE_PASSWORD") do={{ /ppp secret set [find where name=$user] password=($p->"password"); }}
    :if ($action="DELETE_PPPOE") do={{ /ppp secret remove [find where name=$user]; }}
  }} on-error={{ :set ok false; :set result "ERROR"; }}
  :local data ("{{\"id\":" . $id . ",\"ok\":" . $ok . ",\"result\":\"" . $result . "\"}}");
  /tool fetch url=($base . "/api/mikrotik/control/result") http-method=post http-header-field=("Content-Type:application/json," . $hdr) http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-control-scheduler" interval=1m on-event="/system script run interflash-control" policy=read,write,test start-time=startup
'''
    body=f'''<div class="head"><div><h1>Agente de control MikroTik</h1><p>Para ejecutar suspensión, reconexión y cambios PPPoE desde la plataforma.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Volver</a></div><div class="panel"><div class="notice" style="background:#4a161b;color:#fff"><b>Este script sí puede modificar PPPoE.</b> Revisa antes de instalarlo. Solo ejecuta órdenes autenticadas que estén en la cola de esta plataforma.</div><textarea class="field" style="width:100%;height:420px;font-family:Consolas,monospace">{escape(script)}</textarea></div>'''
    return base.shell('Agente MikroTik',body,'routers')


def setup(app):
    if not any(x[0]=='mikrotik_commands' for x in base.NAV): base.NAV.append(('mikrotik_commands','⚡','Control MikroTik'))
    app.add_url_rule('/customers/<int:id>/command/<action>',endpoint='queue_customer_command',view_func=queue_customer_command,methods=['POST'])
    app.add_url_rule('/mikrotik/commands',endpoint='mikrotik_commands',view_func=commands_page,methods=['GET'])
    app.add_url_rule('/mikrotik/control/script',endpoint='mikrotik_control_script',view_func=mikrotik_control_script,methods=['GET'])
    app.add_url_rule('/api/mikrotik/control/next',endpoint='mikrotik_control_next',view_func=command_next,methods=['GET'])
    app.add_url_rule('/api/mikrotik/control/result',endpoint='mikrotik_control_result',view_func=command_result,methods=['POST'])
