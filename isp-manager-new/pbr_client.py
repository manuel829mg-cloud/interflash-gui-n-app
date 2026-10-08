import math
import os, hmac, json, base64, hashlib
from datetime import date, datetime
from html import escape
from flask import request, redirect, url_for, flash, jsonify
from cryptography.fernet import Fernet
import app as base

PBR_LINES = [
    ('', 'Sin PBR asignado'),
    ('Linea-1-Claro', 'Línea 1 · Claro'),
    ('Linea-2-Claro', 'Línea 2 · Claro'),
    ('Linea-3-Altice', 'Línea 3 · Altice'),
    ('Linea-4-Altice', 'Línea 4 · Altice'),
]
PBR_LISTS = {x[0] for x in PBR_LINES if x[0]}
TOKEN = os.getenv('MIKROTIK_AGENT_TOKEN', '') or os.getenv('MIKROTIK_CONTROL_TOKEN', '')
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(base.SECRET_KEY.encode()).digest()))


def esc(v):
    return escape('' if v is None else str(v))


def _cols(c, table):
    return {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def ensure_schema():
    c = base.db()
    cols = _cols(c, 'customers')
    additions = [
        ('pbr_line', 'TEXT'),
        ('mikrotik_profile', 'TEXT'),
        ('router_name', 'TEXT DEFAULT "CCR2116"'),
        ('service_status', 'TEXT DEFAULT "ACTIVO"'),
    ]
    for name, ddl in additions:
        if name not in cols:
            c.execute(f'ALTER TABLE customers ADD COLUMN {name} {ddl}')
    c.commit(); c.close()


def _enc_payload(payload):
    raw = json.dumps(payload or {}, ensure_ascii=False).encode()
    return 'enc:' + FERNET.encrypt(raw).decode()


def _dec_payload(raw):
    raw = raw or '{}'
    try:
        if raw.startswith('enc:'):
            return json.loads(FERNET.decrypt(raw[4:].encode()).decode())
        return json.loads(raw)
    except Exception:
        return {}


def _queue(c, customer_id, pppoe, router_name, action, payload=None):
    c.execute('''INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by)
                 VALUES(?,?,?,?,?,?,?,?)''', (
        router_name or 'CCR2116', customer_id, pppoe or '', action,
        _enc_payload(payload or {}), 'PENDIENTE', datetime.now().isoformat(timespec='seconds'),
        base.ADMIN_USER
    ))


def _choices(row=None):
    c = base.db()
    plans = c.execute('SELECT * FROM plans WHERE active=1 ORDER BY price').fetchall()
    profiles = c.execute('SELECT DISTINCT name FROM push_ppp_profiles WHERE COALESCE(name,"")<>"" ORDER BY name').fetchall() if _table_exists(c, 'push_ppp_profiles') else []
    routers = c.execute('SELECT name,identity FROM push_router_agents ORDER BY id DESC').fetchall() if _table_exists(c, 'push_router_agents') else []
    c.close()
    return plans, profiles, routers


def customer_form(row=None):
    plans, profiles, routers = _choices(row)
    def v(k, default=''):
        if row is None:
            return default
        return row[k] if k in row.keys() and row[k] is not None else default

    plan_opts = ''.join(
        f'<option value="{p["id"]}" {"selected" if str(v("plan_id")) == str(p["id"]) else ""}>{esc(p["name"])} · {p["download_mbps"]}/{p["upload_mbps"]} Mbps · RD${p["price"]:,.0f}</option>'
        for p in plans
    )
    pbr_opts = ''.join(f'<option value="{esc(key)}" {"selected" if v("pbr_line") == key else ""}>{esc(label)}</option>' for key, label in PBR_LINES)
    profile_names = [r['name'] for r in profiles]
    current_profile = str(v('mikrotik_profile') or '')
    if current_profile and current_profile not in profile_names:
        profile_names.insert(0, current_profile)
    profile_opts = ''.join(f'<option value="{esc(name)}" {"selected" if current_profile == name else ""}>{esc(name)}</option>' for name in profile_names)
    router_names = [(r['name'], r['identity'] or r['name']) for r in routers]
    current_router = str(v('router_name', 'CCR2116') or 'CCR2116')
    if current_router and current_router not in {x[0] for x in router_names}:
        router_names.insert(0, (current_router, current_router))
    router_opts = ''.join(f'<option value="{esc(name)}" {"selected" if current_router == name else ""}>{esc(label)}</option>' for name, label in router_names)

    new_checked = 'checked' if row is None else ''
    return f'''<form method="post" class="panel formgrid">
      <div><label>Nombre completo<input name="name" value="{esc(v('name'))}" required></label></div>
      <div><label>Teléfono<input name="phone" value="{esc(v('phone'))}"></label></div>
      <div><label>Cédula / documento<input name="document" value="{esc(v('document'))}"></label></div>
      <div><label>Email<input name="email" value="{esc(v('email'))}"></label></div>
      <div class="full"><label>Dirección<textarea name="address" rows="2">{esc(v('address'))}</textarea></label></div>
      <div class="full" style="border:1px solid #29425b;border-radius:10px;padding:14px">
        <h3 style="margin:0 0 10px">Ubicación de la instalación</h3>
        <p class="muted">Fija este punto cuando estés en casa del cliente. Se guardará al pulsar Guardar cliente.</p>
        <div class="formgrid">
          <label>Latitud<input id="customer-latitude" name="latitude" type="number" min="-90" max="90" step="any" value="{esc(v('latitude'))}" placeholder="18.4861"></label>
          <label>Longitud<input id="customer-longitude" name="longitude" type="number" min="-180" max="180" step="any" value="{esc(v('longitude'))}" placeholder="-69.9312"></label>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><button id="customer-gps" class="btn blue" type="button">Fijar mi ubicación actual</button><a id="customer-map-preview" class="btn" target="_blank" rel="noopener noreferrer" hidden>Ver punto en el mapa</a></div>
        <p id="customer-gps-status" class="muted" role="status"></p>
      </div>
      <div><label>Zona<input name="zone" value="{esc(v('zone'))}"></label></div>
      <div><label>Plan<select name="plan_id"><option value="">Sin plan</option>{plan_opts}</select></label></div>
      <div><label>Usuario PPPoE<input name="pppoe" value="{esc(v('pppoe'))}"></label></div>
      <div><label>Contraseña PPPoE<input type="password" name="pppoe_password" autocomplete="new-password" placeholder="{'Requerida para crear PPPoE' if row is None else 'Solo si vas a crear/recrear PPPoE'}"></label></div>
      <div><label>Perfil MikroTik<select name="mikrotik_profile"><option value="">Sin perfil</option>{profile_opts}</select></label></div>
      <div><label>IP asignada<input name="ip_address" value="{esc(v('ip_address'))}" placeholder="Necesaria para aplicar PBR por lista"></label></div>
      <div><label>Línea / PBR<select name="pbr_line">{pbr_opts}</select></label></div>
      <div><label>Router<select name="router_name">{router_opts or '<option value="CCR2116">CCR2116</option>'}</select></label></div>
      <div><label>Serial ONU<input name="onu_serial" value="{esc(v('onu_serial'))}"></label></div>
      <div><label>Día de vencimiento<input type="number" min="1" max="31" name="due_day" value="{esc(v('due_day',30))}"></label></div>
      <div><label>Estado<select name="status"><option {"selected" if v('status','ACTIVO')=='ACTIVO' else ''}>ACTIVO</option><option {"selected" if v('status')=='SUSPENDIDO' else ''}>SUSPENDIDO</option></select></label></div>
      <div class="full" style="padding:12px;border:1px solid #29425b;border-radius:10px;background:#0b1725">
        <label style="display:flex;align-items:center;gap:9px"><input style="width:auto;margin:0" type="checkbox" name="create_in_router" value="1" {new_checked}> Crear/actualizar el PPPoE en MikroTik usando la cola segura</label>
        <div class="muted" style="margin-top:7px">El PBR solo agrega o mueve la IP de este cliente entre las listas de línea. No cambia reglas de mangle, rutas ni failover.</div>
      </div>
      <div class="full"><button class="btn green">Guardar cliente</button></div>
    </form><script>
    (() => {{
      const lat = document.getElementById('customer-latitude');
      const lng = document.getElementById('customer-longitude');
      const button = document.getElementById('customer-gps');
      const status = document.getElementById('customer-gps-status');
      const preview = document.getElementById('customer-map-preview');
      function updatePreview() {{
        const a = Number(lat.value), b = Number(lng.value);
        const valid = lat.value.trim() && lng.value.trim() && Number.isFinite(a) && Number.isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180;
        preview.hidden = !valid;
        preview.style.display = valid ? '' : 'none';
        if (valid) preview.href = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(a + ',' + b);
        else preview.removeAttribute('href');
      }}
      lat.addEventListener('input', updatePreview); lng.addEventListener('input', updatePreview);
      updatePreview();
      button.addEventListener('click', () => {{
        if (!navigator.geolocation) {{ status.textContent = 'Introduce las coordenadas manualmente; este navegador no permite obtener la ubicación.'; return; }}
        button.disabled = true; status.textContent = 'Buscando tu ubicación…';
        navigator.geolocation.getCurrentPosition(position => {{
          lat.value = position.coords.latitude.toFixed(7); lng.value = position.coords.longitude.toFixed(7);
          updatePreview(); button.disabled = false;
          status.textContent = 'Ubicación fijada. Pulsa Guardar cliente para guardarla con la instalación.';
        }}, error => {{
          button.disabled = false;
          status.textContent = error.code === 1 ? 'Permite el acceso a la ubicación o introduce las coordenadas manualmente.' : 'No se pudo obtener tu ubicación. Inténtalo de nuevo o introduce las coordenadas.';
        }}, {{enableHighAccuracy: true, timeout: 15000, maximumAge: 0}});
      }});
    }})();
    </script>'''


def _location_values():
    lat = (request.form.get('latitude') or '').strip()
    lng = (request.form.get('longitude') or '').strip()
    if not lat and not lng:
        return None, None
    try:
        a, b = float(lat), float(lng)
        if math.isfinite(a) and math.isfinite(b) and -90 <= a <= 90 and -180 <= b <= 180:
            return f'{a:.7f}', f'{b:.7f}'
    except ValueError:
        pass
    raise ValueError('La ubicación necesita una latitud entre -90 y 90 y una longitud entre -180 y 180.')


def _post_values():
    pbr = (request.form.get('pbr_line') or '').strip()
    if pbr not in PBR_LISTS:
        pbr = ''
    latitude, longitude = _location_values()
    return {
        'latitude': latitude, 'longitude': longitude,
        'name': (request.form.get('name') or '').strip(),
        'phone': request.form.get('phone'), 'document': request.form.get('document'),
        'email': request.form.get('email'), 'address': request.form.get('address'),
        'zone': request.form.get('zone'), 'pppoe': (request.form.get('pppoe') or '').strip(),
        'ip': (request.form.get('ip_address') or '').strip(), 'onu': request.form.get('onu_serial'),
        'plan_id': request.form.get('plan_id') or None, 'status': request.form.get('status','ACTIVO'),
        'due_day': int(request.form.get('due_day') or 30),
        'profile': (request.form.get('mikrotik_profile') or '').strip(),
        'pbr': pbr, 'router': (request.form.get('router_name') or 'CCR2116').strip() or 'CCR2116',
        'password': request.form.get('pppoe_password') or '',
        'create_in_router': request.form.get('create_in_router') == '1',
    }


def customer_new_pbr():
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema()
    if request.method == 'POST':
        try:
            x = _post_values()
        except ValueError as error:
            return base.shell('Nuevo cliente', f'<div class="notice" role="alert">{esc(error)}</div>' + customer_form(request.form), 'customers'), 400
        c = base.db()
        cur = c.execute('''INSERT INTO customers(code,name,phone,document,email,address,zone,pppoe,ip_address,onu_serial,plan_id,status,due_day,created_at,mikrotik_profile,pbr_line,router_name,service_status,latitude,longitude)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (None,x['name'],x['phone'],x['document'],x['email'],x['address'],x['zone'],x['pppoe'],x['ip'],x['onu'],x['plan_id'],x['status'],x['due_day'],date.today().isoformat(),x['profile'],x['pbr'],x['router'],x['status'],x['latitude'],x['longitude']))
        cid = cur.lastrowid; c.execute('UPDATE customers SET code=? WHERE id=?',(f'IF-{cid:05d}',cid))
        notes = []
        if x['create_in_router']:
            if x['pppoe'] and x['password'] and x['profile']:
                _queue(c,cid,x['pppoe'],x['router'],'CREATE_PPPOE',{'password':x['password'],'profile':x['profile'],'remote_address':x['ip']})
                notes.append('PPPoE enviado a la cola')
            else:
                notes.append('PPPoE no enviado: faltan usuario, contraseña o perfil')
        if x['pbr']:
            if x['ip']:
                _queue(c,cid,x['pppoe'],x['router'],'APPLY_PBR',{'ip':x['ip'],'address_list':x['pbr']})
                notes.append('PBR enviado a la cola')
            else:
                notes.append('PBR guardado, pero falta IP para aplicarlo')
        c.commit(); c.close()
        try: base.audit('CUSTOMER_CREATE',f'#{cid} {x["name"]} · PBR {x["pbr"] or "sin asignar"}')
        except Exception: pass
        flash('Cliente creado correctamente.' + (' ' + ' · '.join(notes) if notes else ''))
        return redirect(url_for('customer_profile',id=cid) if 'customer_profile' in base.app.view_functions else url_for('customers'))
    return base.shell('Nuevo cliente',f'<div class="head"><div><h1>Nuevo cliente</h1><p>Registro de abonado con PPPoE y PBR</p></div><a class="btn" href="{url_for("customers")}">Volver</a></div>{customer_form()}','customers')


def customer_edit_pbr(id):
    if not base.logged_in(): return redirect(url_for('login'))
    ensure_schema(); c = base.db(); row = c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
    if not row: c.close(); return redirect(url_for('customers'))
    if request.method == 'POST':
        try:
            x = _post_values()
        except ValueError as error:
            c.close()
            return base.shell('Editar cliente', f'<div class="notice" role="alert">{esc(error)}</div>' + customer_form(request.form), 'customers'), 400
        old_pbr = row['pbr_line'] or ''; old_ip = row['ip_address'] or ''; old_profile = row['mikrotik_profile'] or ''
        c.execute('''UPDATE customers SET name=?,phone=?,document=?,email=?,address=?,zone=?,pppoe=?,ip_address=?,onu_serial=?,plan_id=?,status=?,due_day=?,mikrotik_profile=?,pbr_line=?,router_name=?,service_status=? WHERE id=?''',
                  (x['name'],x['phone'],x['document'],x['email'],x['address'],x['zone'],x['pppoe'],x['ip'],x['onu'],x['plan_id'],x['status'],x['due_day'],x['profile'],x['pbr'],x['router'],x['status'],id))
        if 'latitude' in request.form or 'longitude' in request.form:
            c.execute('UPDATE customers SET latitude=?,longitude=? WHERE id=?', (x['latitude'],x['longitude'],id))
        notes=[]
        if x['create_in_router'] and x['pppoe'] and x['password'] and x['profile']:
            _queue(c,id,x['pppoe'],x['router'],'CREATE_PPPOE',{'password':x['password'],'profile':x['profile'],'remote_address':x['ip']}); notes.append('PPPoE enviado a la cola')
        elif x['profile'] != old_profile and x['pppoe'] and x['profile']:
            _queue(c,id,x['pppoe'],x['router'],'CHANGE_PROFILE',{'profile':x['profile']}); notes.append('cambio de perfil enviado a la cola')
        if x['pbr'] != old_pbr or x['ip'] != old_ip:
            if old_ip and (not x['pbr'] or old_ip != x['ip']):
                _queue(c,id,x['pppoe'],x['router'],'REMOVE_PBR',{'ip':old_ip})
            if x['pbr'] and x['ip']:
                _queue(c,id,x['pppoe'],x['router'],'APPLY_PBR',{'ip':x['ip'],'address_list':x['pbr']}); notes.append('PBR enviado a la cola')
            elif x['pbr'] and not x['ip']:
                notes.append('PBR guardado, pero falta IP para aplicarlo')
        c.commit(); c.close()
        try: base.audit('CUSTOMER_UPDATE',f'#{id} · PBR {x["pbr"] or "sin asignar"}')
        except Exception: pass
        flash('Cliente actualizado.' + (' ' + ' · '.join(notes) if notes else ''))
        return redirect(url_for('customer_edit',id=id))
    c.close()
    body=f'<div class="head"><div><h1>Editar cliente</h1><p>{esc(row["code"] or "")} · {esc(row["name"])}</p></div><a class="btn" href="{url_for("customers")}">Volver</a></div>{customer_form(row)}'
    return base.shell('Editar cliente',body,'customers')


def _auth():
    supplied = request.headers.get('X-InterFlash-Agent','')
    return bool(TOKEN) and hmac.compare_digest(supplied,TOKEN)


def control_next():
    if not _auth(): return jsonify(ok=False,error='unauthorized'),401
    router=(request.args.get('router') or 'CCR2116')[:80]
    c=base.db(); row=c.execute("SELECT * FROM router_commands WHERE router_name=? AND status='PENDIENTE' ORDER BY id LIMIT 1",(router,)).fetchone()
    if not row: c.close(); return jsonify(ok=True,id=0)
    c.execute("UPDATE router_commands SET status='EN_PROCESO' WHERE id=?",(row['id'],)); c.commit(); c.close()
    return jsonify(ok=True,id=row['id'],action=row['action'],pppoe=row['pppoe'],payload=_dec_payload(row['payload']))


def control_result():
    if not _auth(): return jsonify(ok=False,error='unauthorized'),401
    p=request.get_json(silent=True) or {}; cid=int(p.get('id') or 0); ok=bool(p.get('ok')); result=str(p.get('result') or '')[:500]
    c=base.db(); cmd=c.execute('SELECT * FROM router_commands WHERE id=?',(cid,)).fetchone()
    if not cmd: c.close(); return jsonify(ok=False,error='not-found'),404
    status='COMPLETADO' if ok else 'ERROR'
    c.execute('UPDATE router_commands SET status=?,executed_at=?,result=?,payload=? WHERE id=?',(status,datetime.now().isoformat(timespec='seconds'),result,'{}' if cmd['action']=='CREATE_PPPOE' else cmd['payload'],cid))
    if ok and cmd['customer_id']:
        if cmd['action']=='SUSPEND': c.execute("UPDATE customers SET status='SUSPENDIDO',service_status='SUSPENDIDO' WHERE id=?",(cmd['customer_id'],))
        elif cmd['action']=='REACTIVATE': c.execute("UPDATE customers SET status='ACTIVO',service_status='ACTIVO' WHERE id=?",(cmd['customer_id'],))
    c.commit(); c.close(); return jsonify(ok=True)


def control_script():
    if not base.logged_in(): return redirect(url_for('login'))
    if not TOKEN:
        return base.shell('Agente MikroTik','<div class="panel"><div class="notice">Falta configurar MIKROTIK_AGENT_TOKEN en Railway.</div></div>','routers')
    root=request.url_root.rstrip('/')
    script=f'''/system script remove [find where name="interflash-agent"]
/system scheduler remove [find where name="interflash-agent-scheduler"]
/system script add name="interflash-agent" policy=read,write,test source={{
  :local base "{root}";
  :local token "{TOKEN}";
  :local hdr ("X-InterFlash-Agent: " . $token);
  :local r [/tool fetch url=($base . "/api/mikrotik/agent/next?router=CCR2116") http-method=get http-header-field=$hdr output=user check-certificate=yes as-value];
  :local d [:deserialize from=json value=($r->"data")];
  :if (($d->"ok") != true) do={{ :return; }}
  :local id ($d->"id"); :if ($id = 0) do={{ :return; }}
  :local action ($d->"action"); :local user ($d->"pppoe"); :local p ($d->"payload");
  :local ok true; :local result "OK";
  :do {{
    :if ($action="SUSPEND") do={{ /ppp secret set [find where name=$user] disabled=yes; }}
    :if ($action="REACTIVATE") do={{ /ppp secret set [find where name=$user] disabled=no; }}
    :if ($action="CHANGE_PROFILE") do={{ /ppp secret set [find where name=$user] profile=($p->"profile"); }}
    :if ($action="CHANGE_PASSWORD") do={{ /ppp secret set [find where name=$user] password=($p->"password"); }}
    :if ($action="DELETE_PPPOE") do={{ /ppp secret remove [find where name=$user]; }}
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
  }} on-error={{ :set ok false; :set result "ERROR"; }}
  :local data ("{{\"id\":" . $id . ",\"ok\":" . $ok . ",\"result\":\"" . $result . "\"}}");
  /tool fetch url=($base . "/api/mikrotik/agent/result") http-method=post http-header-field=("Content-Type:application/json," . $hdr) http-data=$data output=none check-certificate=yes;
}}
/system scheduler add name="interflash-agent-scheduler" interval=1m on-event="/system script run interflash-agent" policy=read,write,test start-time=startup
'''
    return base.shell('Agente MikroTik',f'''<div class="head"><div><h1>Agente MikroTik</h1><p>Ejecuta PPPoE, suspensión y PBR desde la cola segura.</p></div><a class="btn" href="{url_for('mikrotik_commands')}">← Cola</a></div><div class="panel"><div class="notice" style="background:#4e3707;color:#fff"><b>Este script sí modifica clientes.</b> No cambia tus reglas PBR ni el failover; solo mueve la IP del cliente entre las cuatro listas existentes.</div><textarea class="field" style="width:100%;height:430px;font-family:Consolas,monospace">{esc(script)}</textarea></div>''','routers')


def commands_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); rows=c.execute('''SELECT rc.*,cu.name customer FROM router_commands rc LEFT JOIN customers cu ON cu.id=rc.customer_id ORDER BY rc.id DESC LIMIT 200''').fetchall(); c.close()
    trs=[]
    for r in rows:
        cls='ok' if r['status']=='COMPLETADO' else 'bad' if r['status']=='ERROR' else 'warn'
        trs.append(f'<tr><td>#{r["id"]}</td><td>{esc(r["customer"] or "-")}</td><td>{esc(r["pppoe"] or "-")}</td><td>{esc(r["action"])}</td><td><span class="tag {cls}">{esc(r["status"])}</span></td><td>{esc(r["created_at"] or "-")}</td><td>{esc(r["result"] or "-")}</td></tr>')
    return base.shell('Cola MikroTik',f'''<div class="head"><div><h1>Cola MikroTik</h1><p>PPPoE, suspensión, perfiles y PBR</p></div><a class="btn blue" href="{url_for('pbr_control_script')}">Agente MikroTik</a></div><div class="panel"><table class="table"><tr><th>#</th><th>Cliente</th><th>PPPoE</th><th>Acción</th><th>Estado</th><th>Fecha</th><th>Resultado</th></tr>{''.join(trs) or '<tr><td colspan=7 class=muted>Sin órdenes.</td></tr>'}</table></div>''','routers')


def setup(app):
    ensure_schema()
    app.view_functions['customer_new'] = customer_new_pbr
    app.view_functions['customer_edit'] = customer_edit_pbr
    if 'mikrotik_commands' in app.view_functions:
        app.view_functions['mikrotik_commands'] = commands_page
    app.add_url_rule('/api/mikrotik/agent/next', endpoint='pbr_control_next', view_func=control_next, methods=['GET'])
    app.add_url_rule('/api/mikrotik/agent/result', endpoint='pbr_control_result', view_func=control_result, methods=['POST'])
    app.add_url_rule('/mikrotik/agent-script', endpoint='pbr_control_script', view_func=control_script, methods=['GET'])
