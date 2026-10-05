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

    # Instalador mínimo y seguro para validar primero suspensión/reactivación.
    # El scheduler se crea DESHABILITADO y no se ejecuta ninguna orden al instalar.
    script = f'''/system script remove [find where name="interflash-agent"]
/system scheduler remove [find where name="interflash-agent-scheduler"]
/system script add name="interflash-agent" policy=read,write,test,sensitive source={{
  :local base "{root}";
  :local token "{token}";
  :local hdr ("X-InterFlash-Agent: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/agent/next?router=CCR2116") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local d [:deserialize from=json value=($r->"data")];
  :if (($d->"ok") != true) do={{ :return; }}
  :local id ($d->"id");
  :if ($id = 0) do={{ :return; }}
  :local action ($d->"action");
  :local user ($d->"pppoe");
  :local ok false;
  :local result "ACCION_NO_SOPORTADA";
  :do {{
    :if ($action="SUSPEND") do={{
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={{ :error "PPPoE no encontrado"; }}
      /ppp secret set $sec disabled=yes;
      :local act [/ppp active find where name=$user];
      :if ([:len $act] > 0) do={{ /ppp active remove $act; }}
      :set ok true;
      :set result "SUSPENDIDO";
    }}
    :if ($action="REACTIVATE") do={{
      :local sec [/ppp secret find where name=$user];
      :if ([:len $sec] = 0) do={{ :error "PPPoE no encontrado"; }}
      /ppp secret set $sec disabled=no;
      :set ok true;
      :set result "REACTIVADO";
    }}
  }} on-error={{
    :set ok false;
    :set result "ERROR";
  }}
  :local data ("{{\\\"id\\\":" . $id . ",\\\"ok\\\":" . $ok . ",\\\"result\\\":\\\"" . $result . "\\\"}}");
  /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/json," . $hdr) http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-agent-scheduler" interval=5s on-event="/system script run interflash-agent" policy=read,write,test,sensitive start-time=startup disabled=yes
'''

    body = f'''<div class="head"><div><h1>Agente MikroTik</h1><p>Instalación segura para suspensión y reactivación PPPoE.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Cola</a></div>
    <div class="panel">
      <div class="notice" style="background:#063f2a;color:#b8f6d6;margin-bottom:12px"><b>Versión de prueba segura:</b> solo ejecuta Suspender y Reactivar. Al instalar, el scheduler queda deshabilitado y no ejecuta órdenes automáticamente.</div>
      <div class="notice" style="background:#4e3707;color:#fff;margin-bottom:12px">Copia el bloque completo una sola vez en el CCR2116. Luego verifica que el script exista antes de hacer una prueba con un solo cliente.</div>
      <textarea class="field" style="width:100%;height:520px;font-family:Consolas,monospace">{pbr_client.esc(script)}</textarea>
    </div>'''
    return base.shell('Agente MikroTik', body, 'routers')


def setup(app):
    app.view_functions['pbr_control_script'] = control_script_fast
