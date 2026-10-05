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
    template = '''/system scheduler remove [find where name="interflash-agent-scheduler"]
/system script remove [find where name="interflash-agent"]
/system script add name="interflash-agent" policy=read,write,test,sensitive source={
  :local base "__ROOT__";
  :local token "__TOKEN__";
  :local hdr ("X-InterFlash-Agent: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/agent/next?router=CCR2116") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local d [:deserialize from=json value=($r->"data")];
  :if (($d->"ok") != true) do={ :return; }
  :local id ($d->"id");
  :if ($id = 0) do={ :return; }
  :local action ($d->"action");
  :local user ($d->"pppoe");
  :local p ($d->"payload");
  :local ok false;
  :local result "ACCION_NO_SOPORTADA";
  :do {
    :if ($action="SUSPEND") do={
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={ :error "PPPoE no encontrado"; }
      /ppp secret set $sec disabled=yes;
      :local act [/ppp active find where name=$user];
      :if ([:len $act] > 0) do={ /ppp active remove $act; }
      :set ok true;
      :set result "SUSPENDIDO";
    }
    :if ($action="REACTIVATE") do={
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={ :error "PPPoE no encontrado"; }
      /ppp secret set $sec disabled=no;
      :set ok true;
      :set result "REACTIVADO";
    }
    :if ($action="CREATE_PPPOE") do={
      :local prof ($p->"profile");
      :local pass ($p->"password");
      :local rip ($p->"remote_address");
      :if ([:len $user] = 0) do={ :error "Usuario PPPoE vacio"; }
      :if ([:len $prof] = 0) do={ :error "Perfil PPPoE vacio"; }
      :if ([:len $pass] = 0) do={ :error "Password PPPoE vacio"; }
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={
        /ppp secret add name=$user password=$pass profile=$prof service=pppoe disabled=no;
        :set sec [/ppp secret find where name=$user];
      } else={
        /ppp secret set $sec password=$pass profile=$prof service=pppoe disabled=no;
      }
      :if ([:len $rip] > 0) do={ /ppp secret set $sec remote-address=$rip; }
      :set ok true;
      :set result "PPPOE_CREADO";
    }
    :if ($action="CHANGE_PROFILE") do={
      :local prof ($p->"profile");
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={ :error "PPPoE no encontrado"; }
      :if ([:len $prof] = 0) do={ :error "Perfil PPPoE vacio"; }
      /ppp secret set $sec profile=$prof;
      :set ok true;
      :set result "PERFIL_CAMBIADO";
    }
    :if ($action="APPLY_PBR") do={
      :local ip ($p->"ip");
      :local target ($p->"address_list");
      :if ([:len $ip] = 0) do={ :error "IP vacia"; }
      :if (($target != "Linea-1-Claro") && ($target != "Linea-2-Claro") && ($target != "Linea-3-Altice") && ($target != "Linea-4-Altice")) do={ :error "Lista PBR invalida"; }
      :foreach l in={"Linea-1-Claro";"Linea-2-Claro";"Linea-3-Altice";"Linea-4-Altice"} do={
        /ip firewall address-list remove [find where list=$l and address=$ip];
      }
      /ip firewall address-list add list=$target address=$ip comment=("INTERFLASH:" . $user);
      :set ok true;
      :set result "PBR_APLICADO";
    }
    :if ($action="REMOVE_PBR") do={
      :local ip ($p->"ip");
      :if ([:len $ip] = 0) do={ :error "IP vacia"; }
      :foreach l in={"Linea-1-Claro";"Linea-2-Claro";"Linea-3-Altice";"Linea-4-Altice"} do={
        /ip firewall address-list remove [find where list=$l and address=$ip];
      }
      :set ok true;
      :set result "PBR_REMOVIDO";
    }
  } on-error={
    :set ok false;
    :set result "ERROR";
  }
  :local data ("id=" . $id . "&ok=" . $ok . "&result=" . $result);
  /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=$data output=none check-certificate=yes;
}
/system scheduler add name="interflash-agent-scheduler" interval=5s on-event="/system script run interflash-agent" policy=read,write,test,sensitive start-time=startup
:log info "INTERFLASH-AGENT-INSTALLED"
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
    cmd = c.execute('SELECT * FROM router_commands WHERE id=?', (cid,)).fetchone()
    if not cmd:
        c.close()
        return jsonify(ok=False, error='not-found'), 404

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

    body = f'''<div class="head"><div><h1>Agente MikroTik</h1><p>Control PPPoE y PBR desde la plataforma.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Cola</a></div>
    <div class="panel">
      <div class="notice" style="background:#063f2a;color:#b8f6d6;margin-bottom:12px"><b>Instalación:</b> copia estas 3 líneas en el CCR2116. Actualiza el agente sin cambiar tu configuración de rutas, mangle o failover.</div>
      <textarea class="field" style="width:100%;height:150px;font-family:Consolas,monospace">{pbr_client.esc(installer)}</textarea>
      <div class="notice" style="background:#4e3707;color:#fff;margin:14px 0 10px">El agente procesa SUSPEND, REACTIVATE, CREATE_PPPOE, CHANGE_PROFILE, APPLY_PBR y REMOVE_PBR cada 5 segundos.</div>
      <div class="muted" style="margin-bottom:6px">Verificación opcional:</div>
      <textarea class="field" style="width:100%;height:90px;font-family:Consolas,monospace">{pbr_client.esc(verify)}</textarea>
    </div>'''
    return base.shell('Agente MikroTik', body, 'routers')


def setup(app):
    app.view_functions['pbr_control_script'] = control_script_fast
    app.view_functions['pbr_control_result'] = control_result_compat
    app.add_url_rule('/api/mikrotik/bootstrap.rsc', endpoint='mikrotik_bootstrap_rsc', view_func=bootstrap_rsc, methods=['GET'])
