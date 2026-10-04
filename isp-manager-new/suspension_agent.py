from flask import request, redirect, url_for
import app as base
import pbr_client


def control_script_fast():
    if not base.logged_in():
        return redirect(url_for('login'))
    if not pbr_client.TOKEN:
        return base.shell('Agente MikroTik','<div class="panel"><div class="notice">Falta configurar MIKROTIK_AGENT_TOKEN en Railway.</div></div>','routers')

    root = request.url_root.rstrip('/')
    if root.startswith('http://'):
        root = 'https://' + root[len('http://'):]
    token = pbr_client.TOKEN
    script = f'''/system script remove [find where name="interflash-agent"]
/system scheduler remove [find where name="interflash-agent-scheduler"]
/system script add name="interflash-agent" policy=read,write,test,sensitive source={{
  :local base "{root}";
  :local token "{token}";
  :local hdr ("X-InterFlash-Agent: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/agent/next?router=CCR2116") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local d [:deserialize from=json value=($r->"data")];
  :if (($d->"ok") != true) do={{ :return; }}
  :local id ($d->"id"); :if ($id = 0) do={{ :return; }}
  :local action ($d->"action"); :local user ($d->"pppoe"); :local p ($d->"payload");
  :local ok true; :local result "OK";
  :do {{
    :if ($action="SUSPEND") do={{
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={{ :error "PPPoE no encontrado"; }}
      /ppp secret set $sec disabled=yes;
      :local act [/ppp active find where name=$user];
      :if ([:len $act] > 0) do={{ /ppp active remove $act; }}
    }}
    :if ($action="REACTIVATE") do={{
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={{ :error "PPPoE no encontrado"; }}
      /ppp secret set $sec disabled=no;
    }}
    :if ($action="RESTART_PPPOE") do={{
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={{ :error "PPPoE no encontrado"; }}
      :if ([/ppp secret get $sec disabled] = true) do={{ :error "PPPoE suspendido"; }}
      :local act [/ppp active find where name=$user];
      :if ([:len $act] > 0) do={{ /ppp active remove $act; }}
    }}
    :if ($action="CHANGE_PROFILE") do={{ /ppp secret set [find where name=$user] profile=($p->"profile"); }}
    :if ($action="CHANGE_PASSWORD") do={{ /ppp secret set [find where name=$user] password=($p->"password"); }}
    :if ($action="DELETE_PPPOE") do={{ /ppp active remove [find where name=$user]; /ppp secret remove [find where name=$user]; }}
    :if ($action="CREATE_PPPOE") do={{
      :local prof ($p->"profile"); :local pass ($p->"password"); :local rip ($p->"remote_address");
      :if ([:len [/ppp secret find where name=$user]] = 0) do={{ /ppp secret add name=$user password=$pass profile=$prof service=pppoe disabled=no; }} else={{ /ppp secret set [find where name=$user] password=$pass profile=$prof service=pppoe disabled=no; }}
      :if ([:len $rip] > 0) do={{ /ppp secret set [find where name=$user] remote-address=$rip; }}
    }}
    :if ($action="APPLY_PBR") do={{
      :local ip ($p->"ip"); :local target ($p->"address_list");
      :foreach l in={{"Linea-1-Claro";"Linea-2-Claro";"Linea-3-Altice";"Linea-4-Altice"}} do={{ /ip firewall address-list remove [find where list=$l and address=$ip]; }}
      :if ([:len [/ip firewall address-list find where list=$target and address=$ip]] = 0) do={{ /ip firewall address-list add list=$target address=$ip comment=("INTERFLASH:" . $user); }}
    }}
    :if ($action="REMOVE_PBR") do={{
      :local ip ($p->"ip");
      :foreach l in={{"Linea-1-Claro";"Linea-2-Claro";"Linea-3-Altice";"Linea-4-Altice"}} do={{ /ip firewall address-list remove [find where list=$l and address=$ip]; }}
    }}
    :if ($action="BACKUP_ROUTER") do={{
      /system backup save name=interflash-auto dont-encrypt=yes;
      /export file=interflash-auto-export show-sensitive=no;
      :set result "Backup y export guardados en Files";
    }}
  }} on-error={{ :set ok false; :set result "ERROR"; }}
  :local data ("{{\"id\":" . $id . ",\"ok\":" . $ok . ",\"result\":\"" . $result . "\"}}");
  /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/json," . $hdr) http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-agent-scheduler" interval=5s on-event="/system script run interflash-agent" policy=read,write,test,sensitive start-time=startup
/system script run interflash-agent
'''

    body = f'''<div class="head"><div><h1>Agente MikroTik</h1><p>Suspensión, reactivación, reinicio, backups y cambios PPPoE desde la plataforma.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Cola</a></div>
    <div class="panel">
      <div class="notice" style="background:#063f2a;color:#b8f6d6;margin-bottom:12px"><b>Control real:</b> Suspender deshabilita y desconecta; Reactivar habilita; Reiniciar PPPoE tumba solo la sesión; Backup guarda una copia y un export en Files del MikroTik. El agente revisa órdenes cada 5 segundos.</div>
      <div class="notice" style="background:#4e3707;color:#fff;margin-bottom:12px">Pega este bloque una sola vez para actualizar el agente con todas las funciones nuevas.</div>
      <textarea class="field" style="width:100%;height:450px;font-family:Consolas,monospace">{pbr_client.esc(script)}</textarea>
    </div>'''
    return base.shell('Agente MikroTik', body, 'routers')


def setup(app):
    app.view_functions['pbr_control_script'] = control_script_fast
