import re
from datetime import datetime
from flask import request, jsonify
import app as base
import pbr_client
import suspension_agent


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def ensure_schema():
    c = base.db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS push_ppp_profiles(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      router_name TEXT,
      name TEXT,
      remote_address TEXT,
      local_address TEXT,
      rate_limit TEXT,
      comment TEXT
    );
    CREATE TABLE IF NOT EXISTS plan_profile_map(
      router_name TEXT NOT NULL,
      plan_id INTEGER NOT NULL,
      pbr_line TEXT NOT NULL DEFAULT '',
      profile_name TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(router_name, plan_id, pbr_line)
    );
    ''')
    c.commit(); c.close()


def profile_state_v2():
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    ensure_schema()
    router = str(request.form.get('router') or 'CCR2116')[:80]
    kind = str(request.form.get('kind') or '').strip().lower()
    now = datetime.now().isoformat(timespec='seconds')
    c = base.db()
    try:
        if kind == 'reset':
            c.execute('DELETE FROM push_ppp_profiles WHERE router_name=?', (router,))
            c.commit()
            return jsonify(ok=True, kind='reset', router=router)

        if kind == 'profile':
            name = str(request.form.get('name') or '').strip()[:255]
            if not name:
                return jsonify(ok=False, error='missing-name'), 400
            c.execute('''INSERT INTO push_ppp_profiles(router_name,name,remote_address,local_address,rate_limit,comment)
                         VALUES(?,?,?,?,?,?)''', (
                router,
                name,
                str(request.form.get('remote_address') or '')[:255],
                str(request.form.get('local_address') or '')[:255],
                str(request.form.get('rate_limit') or '')[:255],
                ''
            ))
            c.commit()
            return jsonify(ok=True, kind='profile', router=router, name=name)

        if kind == 'finish':
            total = c.execute('SELECT COUNT(*) c FROM push_ppp_profiles WHERE router_name=?', (router,)).fetchone()['c']
            if _table_exists(c, 'push_router_agents'):
                c.execute('UPDATE push_router_agents SET ppp_profiles=?,last_sync=? WHERE name=?', (total, now, router))
            c.commit()
            return jsonify(ok=True, kind='finish', router=router, profiles=total)

        return jsonify(ok=False, error='invalid-kind'), 400
    finally:
        c.close()


def profiles_api():
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    ensure_schema()
    router = str(request.args.get('router') or 'CCR2116')[:80]
    c = base.db()
    rows = c.execute('''SELECT name,MAX(rate_limit) rate_limit,MAX(local_address) local_address,MAX(remote_address) remote_address
                        FROM push_ppp_profiles
                        WHERE router_name=? AND COALESCE(name,'')<>''
                        GROUP BY name ORDER BY name''', (router,)).fetchall()
    c.close()
    return jsonify(ok=True, router=router, items=[dict(x) for x in rows], count=len(rows))


def profiles_refresh_api():
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    ensure_schema()
    router = str(request.args.get('router') or 'CCR2116')[:80]
    c = base.db()
    try:
        pending = c.execute("""SELECT id FROM router_commands
                               WHERE router_name=? AND action='SYNC_PROFILES'
                               AND status IN ('PENDIENTE','EN_PROCESO')
                               ORDER BY id DESC LIMIT 1""", (router,)).fetchone()
        if pending:
            cid = pending['id']; queued = False
        else:
            pbr_client._queue(c, None, '', router, 'SYNC_PROFILES', {})
            cid = c.execute('SELECT last_insert_rowid() id').fetchone()['id']
            queued = True
        c.commit()
        return jsonify(ok=True, router=router, command_id=cid, queued=queued)
    finally:
        c.close()


def _save_plan_profile(c, router, plan_id, pbr, profile):
    if not plan_id or not profile:
        return
    exists = c.execute('SELECT 1 FROM push_ppp_profiles WHERE router_name=? AND name=? LIMIT 1', (router, profile)).fetchone()
    if not exists:
        return
    c.execute('''INSERT INTO plan_profile_map(router_name,plan_id,pbr_line,profile_name,updated_at)
                 VALUES(?,?,?,?,?)
                 ON CONFLICT(router_name,plan_id,pbr_line) DO UPDATE SET
                   profile_name=excluded.profile_name,updated_at=excluded.updated_at''',
              (router, int(plan_id), pbr or '', profile, datetime.now().isoformat(timespec='seconds')))


def plan_profile_api():
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    ensure_schema()
    router = str(request.values.get('router') or 'CCR2116')[:80]
    pbr = str(request.values.get('pbr_line') or '')[:80]
    try:
        plan_id = int(request.values.get('plan_id') or 0)
    except (TypeError, ValueError):
        plan_id = 0
    if not plan_id:
        return jsonify(ok=True, profile='')

    c = base.db()
    try:
        if request.method == 'POST':
            profile = str(request.form.get('profile') or '').strip()[:255]
            if not profile:
                c.execute('DELETE FROM plan_profile_map WHERE router_name=? AND plan_id=? AND pbr_line=?', (router, plan_id, pbr))
            else:
                exists = c.execute('SELECT 1 FROM push_ppp_profiles WHERE router_name=? AND name=? LIMIT 1', (router, profile)).fetchone()
                if not exists:
                    return jsonify(ok=False, error='profile-not-synced'), 400
                _save_plan_profile(c, router, plan_id, pbr, profile)
            c.commit()
            return jsonify(ok=True, profile=profile)

        row = c.execute('''SELECT profile_name FROM plan_profile_map
                           WHERE router_name=? AND plan_id=? AND pbr_line=?''', (router, plan_id, pbr)).fetchone()
        if not row and pbr:
            row = c.execute('''SELECT profile_name FROM plan_profile_map
                               WHERE router_name=? AND plan_id=? AND pbr_line=?''', (router, plan_id, '')).fetchone()
        return jsonify(ok=True, profile=(row['profile_name'] if row else ''))
    finally:
        c.close()


def _profile_script(root, token):
    return f'''
/system scheduler remove [find where name="interflash-profile-sync-scheduler"]
/system script remove [find where name="interflash-profile-sync"]
/system script add name="interflash-profile-sync" policy=read,test,sensitive source={{
  :local base "{root}";
  :local token "{token}";
  :local hdr ("Content-Type:application/x-www-form-urlencoded,X-InterFlash-Agent: " . $token);
  /tool fetch url=($base . "/api/mikrotik/profile-state-v2") http-method=post http-header-field=$hdr http-data="router=CCR2116&kind=reset" output=none check-certificate=yes;
  :foreach i in=[/ppp profile find] do={{
    :local n [/ppp profile get $i name];
    :local rate [/ppp profile get $i rate-limit];
    :local localA [/ppp profile get $i local-address];
    :local remoteA [/ppp profile get $i remote-address];
    :local data ("router=CCR2116&kind=profile&name=" . $n . "&rate_limit=" . $rate . "&local_address=" . $localA . "&remote_address=" . $remoteA);
    /tool fetch url=($base . "/api/mikrotik/profile-state-v2") http-method=post http-header-field=$hdr http-data=$data output=none check-certificate=yes;
  }}
  /tool fetch url=($base . "/api/mikrotik/profile-state-v2") http-method=post http-header-field=$hdr http-data="router=CCR2116&kind=finish" output=none check-certificate=yes;
}}
/system scheduler add name="interflash-profile-sync-scheduler" interval=10m on-event="/system script run interflash-profile-sync" policy=read,test,sensitive start-time=startup
/system script run interflash-profile-sync
'''


def _patch_agent_builder():
    if getattr(suspension_agent._agent_rsc, '_interflash_profiles_patched', False):
        return
    original = suspension_agent._agent_rsc

    def with_profiles(root, token):
        body = original(root, token)
        action = '''    :if ($action="SYNC_PROFILES") do={
      :local profileScript [/system script find where name="interflash-profile-sync"];
      :if ([:len $profileScript] = 0) do={ :error "interflash-profile-sync no instalado"; }
      /system script run $profileScript;
      :set ok true;
      :set result "PERFILES_SINCRONIZADOS";
    }
'''
        marker = '  } on-error={'
        if marker in body and 'SYNC_PROFILES' not in body:
            body = body.replace(marker, action + marker, 1)
        return body + _profile_script(root, token)

    with_profiles._interflash_profiles_patched = True
    suspension_agent._agent_rsc = with_profiles


def _profile_widget(options, outer_div=True):
    inner = f'''<label>Perfil MikroTik
      <div class="if-profile-row"><select id="if-profile-select" name="mikrotik_profile">{options}</select><button class="btn blue" type="button" onclick="IFPROFILE.refresh()">↻ Perfiles</button></div>
      <small id="if-profile-note" class="muted">Perfiles sincronizados directamente desde el CCR2116.</small>
    </label>'''
    return f'<div class="if-profile-field">{inner}</div>' if outer_div else inner


def _inject_profile_tools(html):
    if 'window.IFPROFILE=' in html:
        return html

    pattern_outer = re.compile(r'<div><label>Perfil MikroTik<select name="mikrotik_profile">(.*?)</select></label></div>', re.S)
    match = pattern_outer.search(html)
    if match:
        html = pattern_outer.sub(_profile_widget(match.group(1), True), html, count=1)
    else:
        pattern_plain = re.compile(r'<label>Perfil MikroTik<select name="mikrotik_profile">(.*?)</select></label>', re.S)
        match = pattern_plain.search(html)
        if not match:
            return html
        html = pattern_plain.sub(_profile_widget(match.group(1), False), html, count=1)

    extra = r'''
<style>
.if-profile-row{display:flex;gap:8px;align-items:center}.if-profile-row select{flex:1;min-width:0}.if-profile-row .btn{flex:0 0 auto;white-space:nowrap;margin-top:6px;height:40px}
@media(max-width:700px){.if-profile-row{flex-direction:column;align-items:stretch}.if-profile-row .btn{margin-top:0;width:100%}}
</style>
<script>
window.IFPROFILE=(function(){
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const sel=()=>document.querySelector('[name="mikrotik_profile"]');
  const router=()=>{const e=document.querySelector('[name="router_name"]');return e&&e.value?e.value:'CCR2116';};
  const plan=()=>{const e=document.querySelector('[name="plan_id"]');return e&&e.value?e.value:'';};
  const pbr=()=>{const e=document.querySelector('[name="pbr_line"]');return e&&e.value?e.value:'';};
  const note=(t)=>{const e=document.getElementById('if-profile-note');if(e)e.textContent=t;};
  async function read(){
    const r=await fetch('/api/mikrotik/profiles?router='+encodeURIComponent(router()),{headers:{Accept:'application/json'},cache:'no-store'});
    const d=await r.json();if(!d.ok)throw new Error(d.error||'Error');return d;
  }
  function fill(d){
    const s=sel();if(!s)return;
    const keep=s.value;
    const emptyText=s.options.length?s.options[0].textContent:'Sin perfil';
    s.innerHTML='';
    const z=document.createElement('option');z.value='';z.textContent=emptyText||'Sin perfil';s.appendChild(z);
    (d.items||[]).forEach(x=>{const o=document.createElement('option');o.value=x.name;o.textContent=x.name+(x.rate_limit?' · '+x.rate_limit:'');s.appendChild(o);});
    if([...s.options].some(o=>o.value===keep))s.value=keep;
    note((d.count||0)+' perfil(es) disponibles desde '+router());
  }
  async function refresh(){
    note('Consultando perfiles del MikroTik...');
    try{
      const r=await fetch('/api/mikrotik/profiles/refresh?router='+encodeURIComponent(router()),{method:'POST',headers:{Accept:'application/json'},cache:'no-store'});
      const d=await r.json();if(!d.ok)throw new Error(d.error||'Error');
      for(let i=0;i<14;i++){await sleep(700);const p=await read();if((p.count||0)>0){fill(p);await applyMap();return;}}
      fill(await read());
    }catch(e){note('No pude sincronizar perfiles. Revisa que el agente nuevo esté instalado.');}
  }
  async function applyMap(){
    if(!plan())return;
    try{
      const u='/api/mikrotik/plan-profile?router='+encodeURIComponent(router())+'&plan_id='+encodeURIComponent(plan())+'&pbr_line='+encodeURIComponent(pbr());
      const r=await fetch(u,{headers:{Accept:'application/json'},cache:'no-store'});const d=await r.json();
      if(d.ok&&d.profile&&sel()&&[...sel().options].some(o=>o.value===d.profile)){sel().value=d.profile;note('Perfil recomendado cargado para este plan/línea.');}
    }catch(_e){}
  }
  async function saveMap(){
    if(!plan()||!sel()||!sel().value)return;
    const data=new URLSearchParams({router:router(),plan_id:plan(),pbr_line:pbr(),profile:sel().value});
    try{await fetch('/api/mikrotik/plan-profile',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded',Accept:'application/json'},body:data});}catch(_e){}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const s=sel();
    const p=document.querySelector('[name="plan_id"]');
    const l=document.querySelector('[name="pbr_line"]');
    if(s)s.addEventListener('change',saveMap);
    if(p)p.addEventListener('change',applyMap);
    if(l)l.addEventListener('change',applyMap);
    applyMap();
    const form=s&&s.closest('form');
    if(form){form.addEventListener('submit',e=>{
      const line=document.querySelector('[name="pbr_line"]');
      const ip=document.querySelector('[name="ip_address"]');
      const create=document.querySelector('[name="create_in_router"]');
      const user=document.querySelector('[name="pppoe"]');
      const pass=document.querySelector('[name="pppoe_password"]');
      if(line&&line.value&&ip&&!ip.value.trim()){e.preventDefault();alert('Selecciona una IP remota libre antes de aplicar PBR.');if(window.IFIP)IFIP.open();return;}
      if(create&&create.checked){
        if(!user||!user.value.trim()||!pass||!pass.value||!s||!s.value){e.preventDefault();alert('Para crear/actualizar el PPPoE faltan usuario, contraseña o Perfil MikroTik.');return;}
      }
    });}
  });
  return {refresh,read,fill,applyMap,saveMap};
})();
</script>
'''
    return html + extra


def _patch_customer_form():
    if getattr(pbr_client.customer_form, '_interflash_profiles_patched', False):
        return
    original = pbr_client.customer_form
    def form(row=None):
        return _inject_profile_tools(original(row))
    form._interflash_profiles_patched = True
    pbr_client.customer_form = form


def _patch_customer_profile(app):
    original = app.view_functions.get('customer_profile')
    if not original or getattr(original, '_interflash_profiles_patched', False):
        return
    def wrapped(id, _orig=original):
        resp = _orig(id)
        try:
            if hasattr(resp, 'get_data'):
                html = resp.get_data(as_text=True)
                new = _inject_profile_tools(html)
                if new != html:
                    resp.set_data(new)
                    resp.headers['Content-Length'] = str(len(resp.get_data()))
                return resp
            if isinstance(resp, str):
                return _inject_profile_tools(resp)
        except Exception:
            pass
        return resp
    wrapped._interflash_profiles_patched = True
    app.view_functions['customer_profile'] = wrapped


def _patch_change_plan(app):
    original = app.view_functions.get('change_customer_plan')
    if not original or getattr(original, '_interflash_mapping_patched', False):
        return
    def wrapped(id, _orig=original):
        if request.method == 'POST':
            try:
                plan_id = int(request.form.get('plan_id') or 0)
            except (TypeError, ValueError):
                plan_id = 0
            profile = str(request.form.get('mikrotik_profile') or '').strip()
            if plan_id and profile:
                c = base.db()
                try:
                    cu = c.execute('SELECT router_name,pbr_line FROM customers WHERE id=?', (id,)).fetchone()
                    if cu:
                        _save_plan_profile(c, cu['router_name'] or 'CCR2116', plan_id, cu['pbr_line'] or '', profile)
                        c.commit()
                finally:
                    c.close()
        return _orig(id)
    wrapped._interflash_mapping_patched = True
    app.view_functions['change_customer_plan'] = wrapped


def setup(app):
    ensure_schema()
    _patch_agent_builder()
    _patch_customer_form()
    _patch_customer_profile(app)
    _patch_change_plan(app)
    app.add_url_rule('/api/mikrotik/profile-state-v2', endpoint='mikrotik_profile_state_v2', view_func=profile_state_v2, methods=['POST'])
    app.add_url_rule('/api/mikrotik/profiles', endpoint='mikrotik_profiles_api', view_func=profiles_api, methods=['GET'])
    app.add_url_rule('/api/mikrotik/profiles/refresh', endpoint='mikrotik_profiles_refresh_api', view_func=profiles_refresh_api, methods=['POST'])
    app.add_url_rule('/api/mikrotik/plan-profile', endpoint='mikrotik_plan_profile_api', view_func=plan_profile_api, methods=['GET','POST'])
