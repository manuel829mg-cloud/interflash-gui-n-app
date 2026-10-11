from datetime import datetime
from flask import request, redirect, url_for, jsonify, Response
import app as base
import pbr_client


def _root_url():
    root = request.url_root.rstrip('/')
    if root.startswith('http://'):
        root = 'https://' + root[len('http://'):]
    return root


def _agent_rsc(root, token):
    # Minimal provisioning agent. It can only consume CREATE_PPPOE commands.
    # The scheduler is installed disabled so the first execution can be tested manually.
    template = '''/system scheduler remove [find where name="interflash-agent-scheduler"]
/system script remove [find where name="interflash-agent"]
/system script remove [find where name="interflash-agent-candidate"]
/system script add name="interflash-agent" policy=read,write,test,sensitive source={
  :local base "__ROOT__";
  :local token "__TOKEN__";
  :local hdr ("X-InterFlash-Agent: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/agent/next?router=CCR2116&action=CREATE_PPPOE") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local d [:deserialize from=json value=($r->"data")];
  :if (($d->"ok") != true) do={ :return; }
  :local id ($d->"id");
  :if (([:typeof $id] = "nil") || ($id = 0)) do={ :return; }
  :local action ($d->"action");
  :if ($action != "CREATE_PPPOE") do={ :return; }
  :local user ($d->"pppoe");
  :local p ($d->"payload");
  :local prof ($p->"profile");
  :local pass ($p->"password");
  :local rip ($p->"remote_address");
  :if ([:len $user] = 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=USUARIO_VACIO") output=none check-certificate=yes;
    :return;
  }
  :if ([:len $prof] = 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PERFIL_VACIO") output=none check-certificate=yes;
    :return;
  }
  :if ([:len $pass] = 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PASSWORD_VACIO") output=none check-certificate=yes;
    :return;
  }
  :if ([:len [/ppp secret find where name=$user]] > 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PPPOE_YA_EXISTE") output=none check-certificate=yes;
    :return;
  }
  :if ([:len [/ppp profile find where name=$prof]] != 1) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PERFIL_NO_EXISTE") output=none check-certificate=yes;
    :return;
  }
  :if (([:typeof $rip] = "str") && ([:len $rip] > 0)) do={
    :if ([:len [/ppp active find where address=$rip]] > 0) do={
      /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=IP_ACTIVA") output=none check-certificate=yes;
      :return;
    }
    :if ([:len [/ppp secret find where remote-address=$rip]] > 0) do={
      /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=IP_RESERVADA") output=none check-certificate=yes;
      :return;
    }
    /ppp secret add name=$user password=$pass profile=$prof remote-address=$rip service=pppoe disabled=no;
  } else={
    /ppp secret add name=$user password=$pass profile=$prof service=pppoe disabled=no;
  }
  /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=true&result=PPPOE_CREADO") output=none check-certificate=yes;
}
/system scheduler add name="interflash-agent-scheduler" interval=5s on-event="/system script run interflash-agent" policy=read,write,test,sensitive start-time=startup disabled=yes
:log info "INTERFLASH-CREATE-PPPOE-AGENT-INSTALLED"
'''
    return template.replace('__ROOT__', root).replace('__TOKEN__', token)


def bootstrap_rsc():
    if not pbr_client._auth():
        return Response('unauthorized\n', status=401, mimetype='text/plain')
    body = _agent_rsc(_root_url(), pbr_client.TOKEN)
    return Response(
        body,
        status=200,
        mimetype='text/plain',
        headers={'Content-Disposition': 'attachment; filename=interflash-bootstrap.rsc'},
    )


def control_result_compat():
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401

    p = request.get_json(silent=True)
    if not p:
        p = request.form.to_dict(flat=True)

    try:
        cid = int(p.get('id') or 0)
    except (TypeError, ValueError):
        cid = 0

    raw_ok = p.get('ok')
    if isinstance(raw_ok, bool):
        ok = raw_ok
    else:
        ok = str(raw_ok or '').strip().lower() in ('1', 'true', 'yes', 'on')
    result = str(p.get('result') or '')[:500]

    c = base.db()
    c.execute('BEGIN IMMEDIATE')
    cmd = c.execute('SELECT * FROM router_commands WHERE id=?', (cid,)).fetchone()
    if not cmd:
        c.close()
        return jsonify(ok=False, error='not-found'), 404

    if cmd['status'] in ('COMPLETADO', 'CANCELADO'):
        c.close()
        return jsonify(ok=True)

    status = 'COMPLETADO' if ok else 'ERROR'
    c.execute(
        'UPDATE router_commands SET status=?,executed_at=?,result=?,payload=? WHERE id=?',
        (
            status,
            datetime.now().isoformat(timespec='seconds'),
            result,
            '{}' if cmd['action'] == 'CREATE_PPPOE' else cmd['payload'],
            cid,
        ),
    )
    if ok and cmd['customer_id']:
        if cmd['action'] == 'SUSPEND':
            c.execute("UPDATE customers SET status='SUSPENDIDO',service_status='SUSPENDIDO' WHERE id=?", (cmd['customer_id'],))
        elif cmd['action'] == 'REACTIVATE':
            c.execute("UPDATE customers SET status='ACTIVO',service_status='ACTIVO' WHERE id=?", (cmd['customer_id'],))
    if ok and cmd['action'] == 'CHANGE_PROFILE' and cmd['customer_id'] and cmd['pppoe']:
        # The transaction and terminal-status guard make repeated acknowledgements safe.
        customer = c.execute(
            'SELECT status,service_status,pppoe,router_name FROM customers WHERE id=?',
            (cmd['customer_id'],),
        ).fetchone()
        if (customer and customer['status'] == 'ACTIVO'
                and customer['service_status'] == 'ACTIVO'
                and customer['pppoe'] == cmd['pppoe']
                and (customer['router_name'] or 'CCR2116') == (cmd['router_name'] or 'CCR2116')):
            pbr_client._queue(
                c, cmd['customer_id'], cmd['pppoe'], cmd['router_name'],
                'RESTART_PPPOE', {'after_profile_command': cid},
            )
    if ok and cmd['customer_id']:
        from whatsapp_events import command_notice
        command_notice(c, cmd)
    c.commit()
    c.close()
    return jsonify(ok=True)


def control_script_fast():
    if not base.logged_in():
        return redirect(url_for('login'))
    if not pbr_client.TOKEN:
        return base.shell('Agente MikroTik','<div class="panel"><div class="notice">Falta configurar MIKROTIK_AGENT_TOKEN en Railway.</div></div>','routers')

    root = _root_url()
    token = pbr_client.TOKEN
    installer = f'''/tool fetch url="{root}/api/mikrotik/bootstrap.rsc" http-header-field="X-InterFlash-Agent: {token}" dst-path=interflash-bootstrap.rsc output=file check-certificate=yes
/import file-name=interflash-bootstrap.rsc
/file remove interflash-bootstrap.rsc'''

    verify = '''/system script print detail where name="interflash-agent"
/system scheduler print where name="interflash-agent-scheduler"'''

    body = f'''<div class="head"><div><h1>Agente MikroTik</h1><p>Creación segura de PPPoE desde la plataforma.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Cola</a></div>
    <div class="panel">
      <div class="notice" style="background:#063f2a;color:#b8f6d6;margin-bottom:12px"><b>Instalación:</b> copia estas 3 líneas en el CCR2116. El agente se instalará DESACTIVADO para revisar primero la cola de órdenes; no cambia rutas, mangle ni failover.</div>
      <textarea class="field" style="width:100%;height:150px;font-family:Consolas,monospace">{pbr_client.esc(installer)}</textarea>
      <div class="notice" style="background:#4e3707;color:#fff;margin:14px 0 10px">Este agente solo procesa CREATE_PPPOE. Rechaza usuarios existentes y queda desactivado hasta completar una prueba manual.</div>
      <div class="muted" style="margin-bottom:6px">Verificación opcional:</div>
      <textarea class="field" style="width:100%;height:90px;font-family:Consolas,monospace">{pbr_client.esc(verify)}</textarea>
    </div>'''
    return base.shell('Agente MikroTik', body, 'routers')


def setup(app):
    app.view_functions['pbr_control_script'] = control_script_fast
    app.view_functions['pbr_control_result'] = control_result_compat
    app.add_url_rule('/api/mikrotik/bootstrap.rsc', endpoint='mikrotik_bootstrap_rsc', view_func=bootstrap_rsc, methods=['GET'])