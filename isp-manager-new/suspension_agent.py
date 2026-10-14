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
    # Provisioning and service agent: only supported provisioning and service commands.
    # The scheduler is installed disabled so the first execution can be tested manually.
    template = '''/system scheduler remove [find where name="interflash-agent-scheduler"]
/system script remove [find where name="interflash-agent"]
/system script remove [find where name="interflash-agent-candidate"]
/system script add name="interflash-agent" policy=read,write,test,sensitive source={
  :local base "__ROOT__";
  :local token "__TOKEN__";
  :local hdr ("X-InterFlash-Agent: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/service-next?router=CCR2116&agent=7&after=__AFTER__") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local d [:deserialize from=json value=($r->"data")];
  :if (($d->"ok") != true) do={ :return 0; }
  :local id ($d->"id");
  :if (([:typeof $id] = "nil") || ($id = 0)) do={ :return 0; }
  :local action ($d->"action");
  :if (($action != "CREATE_PPPOE") && ($action != "SUSPEND") && ($action != "REACTIVATE") && ($action != "CHANGE_PROFILE") && ($action != "RESTART_PPPOE") && ($action != "DELETE_PPPOE") && ($action != "CHANGE_PASSWORD") && ($action != "CHANGE_REMOTE_IP") && ($action != "APPLY_PBR") && ($action != "REMOVE_PBR")) do={ :return 0; }
  :local user ($d->"pppoe");
  :if (($action = "CHANGE_PASSWORD") || ($action = "CHANGE_REMOTE_IP") || ($action = "APPLY_PBR") || ($action = "REMOVE_PBR")) do={
    :local success false;
    :local result "USUARIO_NO_EXISTE";
    :local secret [/ppp secret find where name=$user];
    :if (([:len $user] > 0) && ([:len $secret] = 1)) do={
      :do {
        :local p ($d->"payload");
        :if ($action = "CHANGE_PASSWORD") do={
          :local pass ($p->"password");
          :if (([:typeof $pass] != "str") || ([:len $pass] = 0)) do={ :error "PASSWORD_VACIO"; }
          /ppp secret set $secret password=$pass;
          :if ([/ppp secret get $secret password] != $pass) do={ :error "PASSWORD_NO_CONFIRMADO"; }
          :set result "PASSWORD_CONFIRMADO";
        }
        :if ($action = "CHANGE_REMOTE_IP") do={
          :local rip ($p->"remote_address");
          :if (([:typeof $rip] != "str") || ([:len $rip] = 0)) do={ :error "IP_VACIA"; }
          :foreach other in=[/ppp secret find where remote-address=$rip] do={
            :if ($other != $secret) do={ :error "IP_RESERVADA"; }
          }
          :foreach active in=[/ppp active find where address=$rip] do={
            :if ([/ppp active get $active name] != $user) do={ :error "IP_ACTIVA"; }
          }
          /ppp secret set $secret remote-address=$rip;
          :if ([/ppp secret get $secret remote-address] != $rip) do={ :error "IP_NO_CONFIRMADA"; }
          :set result "IP_CONFIRMADA_REQUIERE_RECONEXION";
        }
        :if (($action = "APPLY_PBR") || ($action = "REMOVE_PBR")) do={
          :local ip ($p->"ip");
          :local target ($p->"address_list");
          :if (([:typeof $ip] != "str") || ([:len $ip] = 0)) do={ :error "IP_VACIA"; }
          :if ($action = "APPLY_PBR") do={
            :if (($target != "Linea-1-Claro") && ($target != "Linea-2-Claro") && ($target != "Linea-3-Altice") && ($target != "Linea-4-Altice")) do={ :error "LINEA_INVALIDA"; }
            :if ([/ppp secret get $secret remote-address] != $ip) do={ :error "IP_NO_PERTENECE_AL_CLIENTE"; }
          }
          :foreach other in=[/ppp secret find where remote-address=$ip] do={
            :if ($other != $secret) do={ :error "IP_RESERVADA"; }
          }
          :foreach active in=[/ppp active find where address=$ip] do={
            :if ([/ppp active get $active name] != $user) do={ :error "IP_ACTIVA"; }
          }
          :foreach l in={"Linea-1-Claro";"Linea-2-Claro";"Linea-3-Altice";"Linea-4-Altice"} do={
            /ip firewall address-list remove [find where list=$l and address=$ip];
          }
          :if ($action = "APPLY_PBR") do={
            /ip firewall address-list add list=$target address=$ip comment=("INTERFLASH:" . $user);
            :if ([:len [/ip firewall address-list find where list=$target and address=$ip]] = 0) do={ :error "PBR_NO_CONFIRMADO"; }
          }
          :set result "PBR_CONFIRMADO";
        }
        :set success true;
      } on-error={ :set result "ERROR_ACTUALIZACION_CLIENTE"; }
    }
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=" . $success . "&result=" . $result) output=none check-certificate=yes;
    :return 0;
  }
  :if (($action = "SUSPEND") || ($action = "REACTIVATE")) do={
    :local success false;
    :local result "USUARIO_NO_EXISTE";
    :local secret [/ppp secret find where name=$user];
    :if (([:len $user] > 0) && ([:len $secret] = 1)) do={
      :do {
        :if ($action = "SUSPEND") do={
          /ppp secret set $secret disabled=yes;
          /ppp active remove [/ppp active find where name=$user];
          :delay 2s;
          :if (([/ppp secret get $secret disabled] = true) && ([:len [/ppp active find where name=$user]] = 0)) do={
            :set success true;
            :set result "SUSPENDIDO_CONFIRMADO";
          } else={ :set result "CORTE_NO_CONFIRMADO"; }
        } else={
          /ppp secret set $secret disabled=no;
          :if ([/ppp secret get $secret disabled] = false) do={
            :set success true;
            :set result "REACTIVADO_CONFIRMADO";
          } else={ :set result "REACTIVACION_NO_CONFIRMADA"; }
        }
      } on-error={ :set result "ERROR_CAMBIO_SERVICIO"; }
    }
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=" . $success . "&result=" . $result) output=none check-certificate=yes;
    :return 0;
  }
  :if ($action = "DELETE_PPPOE") do={
    :local success false;
    :local result "USUARIO_VACIO";
    :if ([:len $user] > 0) do={
      :do {
        :local secret [/ppp secret find where name=$user];
        :if ([:len $secret] > 1) do={ :error "USUARIO_DUPLICADO"; }
        :if ([:len $secret] = 1) do={ /ppp secret set $secret disabled=yes; }
        /ppp active remove [/ppp active find where name=$user];
        :if ([:len $secret] = 1) do={ /ppp secret remove $secret; }
        :if (([:len [/ppp secret find where name=$user]] = 0) && ([:len [/ppp active find where name=$user]] = 0)) do={
          :set success true;
          :set result "PPPOE_ELIMINADO_CONFIRMADO";
        } else={ :set result "ELIMINACION_NO_CONFIRMADA"; }
      } on-error={ :set result "ERROR_ELIMINACION_PPPOE"; }
    }
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=" . $success . "&result=" . $result) output=none check-certificate=yes;
    :return 0;
  }
  :if (($action = "CHANGE_PROFILE") || ($action = "RESTART_PPPOE")) do={
    :local success false;
    :local result "USUARIO_NO_EXISTE";
    :local secret [/ppp secret find where name=$user];
    :if (([:len $user] > 0) && ([:len $secret] = 1)) do={
      :do {
        :if ($action = "CHANGE_PROFILE") do={
          :local payload ($d->"payload");
          :local profile ($payload->"profile");
          :set result "PERFIL_NO_EXISTE";
          :if (([:typeof $profile] = "str") && ([:len $profile] > 0) && ([:len [/ppp profile find where name=$profile]] = 1)) do={
            /ppp secret set $secret profile=$profile;
            :if ([/ppp secret get $secret profile] = $profile) do={
              :set success true;
              :set result "PERFIL_CONFIRMADO";
            } else={ :set result "PERFIL_NO_CONFIRMADO"; }
          }
        } else={
          :if ([/ppp secret get $secret disabled] = false) do={
            /ppp active remove [/ppp active find where name=$user];
            :set result "SESION_REINICIADA";
          } else={ :set result "REINICIO_OMITIDO_USUARIO_SUSPENDIDO"; }
          :set success true;
        }
      } on-error={ :set result "ERROR_CAMBIO_PERFIL"; }
    }
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=" . $success . "&result=" . $result) output=none check-certificate=yes;
    :return 0;
  }
  :local p ($d->"payload");
  :local prof ($p->"profile");
  :local pass ($p->"password");
  :local rip ($p->"remote_address");
  :if ([:len $user] = 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=USUARIO_VACIO") output=none check-certificate=yes;
    :return 0;
  }
  :if ([:len $prof] = 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PERFIL_VACIO") output=none check-certificate=yes;
    :return 0;
  }
  :if ([:len $pass] = 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PASSWORD_VACIO") output=none check-certificate=yes;
    :return 0;
  }
  :if ([:len [/ppp secret find where name=$user]] > 0) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PPPOE_YA_EXISTE") output=none check-certificate=yes;
    :return 0;
  }
  :if ([:len [/ppp profile find where name=$prof]] != 1) do={
    /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=PERFIL_NO_EXISTE") output=none check-certificate=yes;
    :return 0;
  }
  :if (([:typeof $rip] = "str") && ([:len $rip] > 0)) do={
    :if ([:len [/ppp active find where address=$rip]] > 0) do={
      /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=IP_ACTIVA") output=none check-certificate=yes;
      :return 0;
    }
    :if ([:len [/ppp secret find where remote-address=$rip]] > 0) do={
      /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=false&result=IP_RESERVADA") output=none check-certificate=yes;
      :return 0;
    }
    /ppp secret add name=$user password=$pass profile=$prof remote-address=$rip service=pppoe disabled=no;
  } else={
    /ppp secret add name=$user password=$pass profile=$prof service=pppoe disabled=no;
  }
  /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/x-www-form-urlencoded," . $hdr) http-data=("id=" . $id . "&ok=true&result=PPPOE_CREADO") output=none check-certificate=yes;
}
/system scheduler add name="interflash-agent-scheduler" interval=5s on-event="/system script run interflash-agent" policy=read,write,test,sensitive start-time=startup disabled=yes
:log info "INTERFLASH-SERVICE-AGENT-V7-EDIT-INSTALLED"
'''
    return template.replace('__ROOT__', root).replace('__TOKEN__', token).replace('__AFTER__', datetime.now().isoformat(timespec='microseconds'))


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
            '{}' if cmd['action'] in ('CREATE_PPPOE','CHANGE_PASSWORD') else cmd['payload'],
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

    verify = '''/system script print where name="interflash-agent"
/system scheduler print where name="interflash-agent-scheduler"'''

    body = f'''<div class="head"><div><h1>Agente MikroTik</h1><p>Creación de PPPoE, suspensión, reactivación y cambios de perfil y eliminación de PPPoE confirmados por el router.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Cola</a></div>
    <div class="panel">
      <div class="notice" style="background:#063f2a;color:#b8f6d6;margin-bottom:12px"><b>Instalación:</b> copia estas 3 líneas en el CCR2116. El agente se instalará DESACTIVADO para revisar primero la cola de órdenes; no cambia rutas, mangle ni failover.</div>
      <textarea class="field" style="width:100%;height:150px;font-family:Consolas,monospace">{pbr_client.esc(installer)}</textarea>
      <div class="notice" style="background:#4e3707;color:#fff;margin:14px 0 10px">Agente v7: actualiza contraseña, IP y listas de línea del cliente; crea PPPoE, suspende, reactiva, cambia el perfil y elimina el usuario PPPoE del cliente enviado a la papelera. La eliminación desconecta su sesión y se confirma en la cola. Después de confirmar el perfil, renueva la sesión del cliente activo para aplicar la velocidad. Suspender deshabilita el usuario y desconecta su sesión activa. Solo ejecuta órdenes nuevas posteriores a esta instalación; las órdenes antiguas no se ejecutan. Queda desactivado al instalar.</div>
      <div class="muted" style="margin-bottom:6px">Verificación opcional:</div>
      <textarea class="field" style="width:100%;height:90px;font-family:Consolas,monospace">{pbr_client.esc(verify)}</textarea>
    </div>'''
    return base.shell('Agente MikroTik', body, 'routers')



def service_next():
    """Claim only supported commands and skip superseded service requests."""
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    router = (request.args.get('router') or 'CCR2116')[:80]
    after = request.args.get('after') or ''
    try:
        datetime.fromisoformat(after)
    except ValueError:
        return jsonify(ok=False, error='installation-cutoff-required'), 400
    c = base.db()
    c.execute('BEGIN IMMEDIATE')
    c.execute("""UPDATE router_commands AS old SET status='CANCELADO',
        result='Sustituida por una orden de servicio posterior'
        WHERE old.router_name=? AND old.status='PENDIENTE'
        AND old.action IN ('SUSPEND','REACTIVATE','DELETE_PPPOE')
        AND EXISTS (SELECT 1 FROM router_commands AS newer
          WHERE newer.router_name=old.router_name AND newer.pppoe=old.pppoe
          AND newer.id>old.id AND newer.action IN ('SUSPEND','REACTIVATE','DELETE_PPPOE')
          AND newer.status NOT IN ('CANCELADO','ERROR'))""", (router,))
    c.execute("""UPDATE router_commands AS old SET status='CANCELADO',
        result='Sustituida por un cambio de perfil posterior'
        WHERE old.router_name=? AND old.status='PENDIENTE' AND old.action='CHANGE_PROFILE'
        AND EXISTS (SELECT 1 FROM router_commands AS newer
          WHERE newer.router_name=old.router_name AND newer.pppoe=old.pppoe
          AND newer.id>old.id AND newer.action IN ('CHANGE_PROFILE','DELETE_PPPOE')
          AND newer.status NOT IN ('CANCELADO','ERROR'))""", (router,))
    supported = ['CREATE_PPPOE','SUSPEND','REACTIVATE','CHANGE_PROFILE','RESTART_PPPOE','DELETE_PPPOE']
    # Older installed agents must never claim actions they cannot execute.
    if request.args.get('agent') == '7':
        supported += ['CHANGE_PASSWORD','CHANGE_REMOTE_IP','APPLY_PBR','REMOVE_PBR']
    slots = ','.join('?' for _ in supported)
    row = c.execute(f"""SELECT * FROM router_commands WHERE router_name=?
        AND status='PENDIENTE' AND created_at>=?
        AND action IN ({slots})
        ORDER BY id LIMIT 1""", (router, after, *supported)).fetchone()
    if not row:
        c.commit(); c.close()
        return jsonify(ok=True, id=0)
    if row['action'] == 'DELETE_PPPOE':
        shared = c.execute("""SELECT 1 FROM customers WHERE pppoe=?
            AND COALESCE(router_name,'CCR2116')=? AND id!=?
            AND COALESCE(status,'ACTIVO')!='ELIMINADO' LIMIT 1""",
            (row['pppoe'], router, row['customer_id'] or 0)).fetchone()
        if shared:
            c.execute("UPDATE router_commands SET status='ERROR',result='PPPoE compartido con otro cliente; eliminacion bloqueada' WHERE id=?", (row['id'],))
            c.commit(); c.close()
            return jsonify(ok=True, id=0)
    c.execute("UPDATE router_commands SET status='EN_PROCESO' WHERE id=?", (row['id'],))
    c.commit(); c.close()
    return jsonify(ok=True, id=row['id'], action=row['action'],
                   pppoe=row['pppoe'], payload=pbr_client._dec_payload(row['payload']))

def setup(app):
    app.add_url_rule('/api/mikrotik/service-next', endpoint='interflash_service_next', view_func=service_next, methods=['GET'])
    app.view_functions['pbr_control_script'] = control_script_fast
    app.view_functions['pbr_control_result'] = control_result_compat
    app.add_url_rule('/api/mikrotik/bootstrap.rsc', endpoint='mikrotik_bootstrap_rsc', view_func=bootstrap_rsc, methods=['GET'])