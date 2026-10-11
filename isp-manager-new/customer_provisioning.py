import re
import unicodedata
from html import escape
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


def _commercial_profiles(c, router):
    """Only named commercial Plan profiles with a unique active price."""
    plans = c.execute('SELECT * FROM plans WHERE active=1').fetchall()
    rows = c.execute("SELECT name,MAX(rate_limit) rate_limit FROM push_ppp_profiles WHERE router_name=? GROUP BY name ORDER BY name", (router,)).fetchall()
    mappings = c.execute('SELECT plan_id,profile_name FROM plan_profile_map WHERE router_name=?', (router,)).fetchall()
    def normalized(value):
        return ''.join(ch for ch in unicodedata.normalize('NFKD', str(value or '').replace('_', ' ').casefold()) if not unicodedata.combining(ch))
    result = []
    for row in rows:
        name = row['name'] or ''
        if not re.match(r'^plan\s+(?:\d+\s+)?(?:basico|familiar|plus|premium|ultra|esencial|economico)\b', normalized(name)):
            continue
        mapped = {m['plan_id'] for m in mappings if m['profile_name'] == name}
        matches = [p for p in plans if p['id'] in mapped]
        if not matches:
            text = normalized(name)
            matches = [p for p in plans if re.search(r'(?<!\w)' + re.escape('esencial' if normalized(p['name']) == 'economico' and 'esencial' in text else normalized(p['name'])) + r'(?!\w)', text)
                       and re.search(r'(?<!\d)' + str(int(p['download_mbps'])) + r'\s*m\b', text, re.I)]
        prices = {float(p['price']) for p in matches}
        if len(prices) != 1:
            continue
        price = prices.pop()
        result.append({'name': name, 'rate_limit': row['rate_limit'], 'price': price,
                       'plan_ids': [p['id'] for p in matches], 'label': f'{name} · RD${price:,.0f}'})
    return result


def _resolve_plan_profile(c, router, plan_id, pbr, current=''):
    items = [x for x in _commercial_profiles(c, router) if int(plan_id) in x['plan_ids']]
    if pbr:
        items = [x for x in items if pbr.casefold() in x['name'].casefold()]
    names = {x['name'] for x in items}
    mapped = c.execute('SELECT profile_name FROM plan_profile_map WHERE router_name=? AND plan_id=? AND pbr_line=?', (router, plan_id, pbr)).fetchone()
    if mapped and mapped['profile_name'] in names:
        return mapped['profile_name']
    if current in names:
        return current
    return next(iter(names)) if len(names) == 1 else ''


def profiles_api():
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    ensure_schema()
    router = str(request.args.get('router') or 'CCR2116')[:80]
    c = base.db()
    try:
        items = _commercial_profiles(c, router)
    finally:
        c.close()
    return jsonify(ok=True, router=router, items=items, count=len(items))


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

        profile = _resolve_plan_profile(c, router, plan_id, pbr, str(request.args.get('current') or ''))
        return jsonify(ok=True, profile=profile)
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
      <small id="if-profile-note" class="muted">Perfiles comerciales nuevos con precio del catálogo de planes.</small>
    </label>'''
    return f'<div class="if-profile-field">{inner}</div>'


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
    (d.items||[]).forEach(x=>{const o=document.createElement('option');o.value=x.name;o.dataset.planId=String((x.plan_ids||[])[0]||'');o.textContent=x.label||x.name;s.appendChild(o);});
    if([...s.options].some(o=>o.value===keep))s.value=keep;
    note((d.count||0)+' perfil(es) comerciales con precio.');
  }
  async function refresh(){
    note('Consultando perfiles del MikroTik...');
    try{
      const r=await fetch('/api/mikrotik/profiles/refresh?router='+encodeURIComponent(router()),{method:'POST',headers:{Accept:'application/json'},cache:'no-store'});
      const d=await r.json();if(!d.ok)throw new Error(d.error||'Error');
      for(let i=0;i<14;i++){await sleep(700);const p=await read();if((p.count||0)>0){fill(p);return;}}
      fill(await read());
    }catch(e){note('No pude sincronizar perfiles. Revisa que el agente nuevo esté instalado.');}
  }
  async function applyMap(){
    if(!plan())return;
    try{
      const u='/api/mikrotik/plan-profile?router='+encodeURIComponent(router())+'&plan_id='+encodeURIComponent(plan())+'&pbr_line='+encodeURIComponent(pbr())+'&current='+encodeURIComponent(sel()?sel().value:'');
      const r=await fetch(u,{headers:{Accept:'application/json'},cache:'no-store'});const d=await r.json();
      if(sel()){sel().value=d.ok&&d.profile?d.profile:'';}
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
    if(s)s.addEventListener('change',()=>{const o=s.selectedOptions[0];if(p&&o&&o.dataset.planId)p.value=o.dataset.planId;});
    
    
    const rr=document.querySelector('[name="router_name"]');if(rr)rr.addEventListener('change',async()=>{fill(await read());});
    const form=s&&s.closest('form');
    if(form){form.addEventListener('submit',e=>{
      const line=document.querySelector('[name="pbr_line"]');
      const ip=document.querySelector('[name="ip_address"]');
      const create=document.querySelector('[name="create_in_router"]');
      const user=document.querySelector('[name="pppoe"]');
      const pass=document.querySelector('[name="pppoe_password"]');
      if(line&&line.value&&ip&&!ip.value.trim()){e.preventDefault();alert('Selecciona una IP remota libre antes de aplicar PBR.');if(window.IFIP)IFIP.open();return;}
      if(create&&create.checked){
        if(!user||!user.value.trim()||!pass||!pass.value||!s||!s.value){e.preventDefault();alert('Completa el usuario y la contraseña. El plan debe tener un perfil asociado a la línea elegida.');return;}
      }
    });}
  });
  return {refresh,read,fill,applyMap,saveMap};
})();
</script>
'''
    select_pattern = re.compile(r'(<select id="if-profile-select" name="mikrotik_profile">)(.*?)(</select>)', re.S)
    c = base.db()
    try:
        router_field = re.search(r'<select name="router_name">(.*?)</select>', html, re.S)
        selected_router = re.search(r'<option value="([^"]+)" selected', router_field.group(1)) if router_field else None
        router = selected_router.group(1) if selected_router else 'CCR2116'
        items = _commercial_profiles(c, router)
    finally:
        c.close()
    def commercial_options(match):
        selected = re.search(r'<option value="([^"]*)" selected[^>]*>', match.group(2))
        current = selected.group(1) if selected else ''
        options = '<option value="">Selecciona un perfil comercial</option>'
        allowed = {escape(x['name'], quote=True) for x in items}
        if current and current not in allowed:
            options += f'<option value="{current}" selected hidden>Perfil actual conservado</option>'
        for item in items:
            value = escape(item['name'], quote=True)
            chosen = ' selected' if current == value else ''
            options += f'<option value="{value}" data-plan-id="{item["plan_ids"][0]}"{chosen}>{escape(item["label"])}</option>'
        return match.group(1) + options + match.group(3)
    html = select_pattern.sub(commercial_options, html)
    html = re.sub(r'<div><label>Plan(<select name="plan_id">.*?</select>)</label></div>',
                  r'<div hidden style="display:none"><label>Plan\1</label></div>', html, flags=re.S)
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


def _patch_unified_plan_values():
    original = pbr_client._post_values
    def values():
        data = original()

        c = base.db()
        try:
            cid = (request.view_args or {}).get('id')
            old = c.execute('SELECT * FROM customers WHERE id=?', (cid,)).fetchone() if cid else None
            unchanged = (old and str(old['plan_id']) == str(data['plan_id'])
                         and (old['router_name'] or 'CCR2116') == data['router']
                         and (old['pbr_line'] or '') == data['pbr'])
            current = old['mikrotik_profile'] or '' if old else ''
            selected = data['profile']
            items = [x for x in _commercial_profiles(c, data['router']) if x['name'] == selected]
            if items:
                ids = items[0]['plan_ids']
                if len(ids) != 1:
                    raise ValueError('Este perfil tiene más de un plan asociado. Revisa el catálogo.')
                data['plan_id'] = str(ids[0])
                # The profile already encodes the provider line; keep PBR consistent.
                lines = [line for line in pbr_client.PBR_LISTS if line.casefold() in selected.casefold()]
                if len(lines) == 1:
                    data['pbr'] = lines[0]
                profile = selected
            elif selected == current and unchanged:
                profile = current
            elif not selected and not data['pppoe'] and not data['create_in_router']:
                profile = ''
                data['plan_id'] = None
            else:
                raise ValueError('Selecciona un perfil comercial con precio antes de guardar.')
            data['profile'] = profile
            return data
        finally:
            c.close()
    pbr_client._post_values = values


def setup(app):
    _patch_unified_plan_values()
    ensure_schema()
    _patch_agent_builder()
    _patch_customer_form()
    _patch_customer_profile(app)
    _patch_change_plan(app)
    app.add_url_rule('/api/mikrotik/profile-state-v2', endpoint='mikrotik_profile_state_v2', view_func=profile_state_v2, methods=['POST'])
    app.add_url_rule('/api/mikrotik/profiles', endpoint='mikrotik_profiles_api', view_func=profiles_api, methods=['GET'])
    app.add_url_rule('/api/mikrotik/profiles/refresh', endpoint='mikrotik_profiles_refresh_api', view_func=profiles_refresh_api, methods=['POST'])
    app.add_url_rule('/api/mikrotik/plan-profile', endpoint='mikrotik_plan_profile_api', view_func=plan_profile_api, methods=['GET','POST'])
