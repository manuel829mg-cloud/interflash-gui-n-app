import ipaddress
import re
from datetime import datetime
from flask import request, jsonify
import app as base
import pbr_client


def ensure_schema():
    c = base.db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS mikrotik_ip_pools(
      router_name TEXT NOT NULL,
      name TEXT NOT NULL,
      ranges TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(router_name,name)
    );
    CREATE TABLE IF NOT EXISTS mikrotik_ip_used(
      router_name TEXT NOT NULL,
      address TEXT NOT NULL,
      source TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(router_name,address,source)
    );
    CREATE INDEX IF NOT EXISTS idx_mikrotik_ip_used_router ON mikrotik_ip_used(router_name,address);
    ''')
    c.commit(); c.close()


def _is_ip(value):
    try:
        ipaddress.ip_address(str(value or '').strip())
        return True
    except ValueError:
        return False


def pool_state_sync():
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    payload = request.get_json(silent=True) or {}
    router = str(payload.get('router') or 'CCR2116')[:80]
    pools = payload.get('pools') or []
    secrets = payload.get('secrets') or []
    active = payload.get('active') or []
    if isinstance(pools, dict): pools = [pools]
    if isinstance(secrets, dict): secrets = [secrets]
    if isinstance(active, dict): active = [active]
    if not isinstance(pools, list) or not isinstance(secrets, list) or not isinstance(active, list):
        return jsonify(ok=False, error='invalid-payload'), 400

    now = datetime.now().isoformat(timespec='seconds')
    c = base.db()
    c.execute('DELETE FROM mikrotik_ip_pools WHERE router_name=?', (router,))
    c.execute('DELETE FROM mikrotik_ip_used WHERE router_name=?', (router,))

    saved_pools = 0
    for item in pools:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()[:160]
        ranges = str(item.get('ranges') or '').strip()[:2000]
        if not name or not ranges:
            continue
        c.execute('INSERT OR REPLACE INTO mikrotik_ip_pools(router_name,name,ranges,updated_at) VALUES(?,?,?,?)',
                  (router, name, ranges, now))
        saved_pools += 1

    saved_used = 0
    for source, items, key in (('SECRET', secrets, 'remote-address'), ('ACTIVE', active, 'address')):
        for item in items:
            value = item.get(key) if isinstance(item, dict) else item
            value = str(value or '').strip()
            if not _is_ip(value):
                continue
            c.execute('INSERT OR IGNORE INTO mikrotik_ip_used(router_name,address,source,updated_at) VALUES(?,?,?,?)',
                      (router, value, source, now))
            saved_used += 1

    c.commit(); c.close()
    return jsonify(ok=True, router=router, pools=saved_pools, used=saved_used, updated_at=now)


def pool_state_sync_v2():
    """RouterOS-friendly sync using one form-encoded item per request."""
    if not pbr_client._auth():
        return jsonify(ok=False, error='unauthorized'), 401
    ensure_schema()
    router = str(request.form.get('router') or 'CCR2116')[:80]
    kind = str(request.form.get('kind') or '').strip().lower()
    now = datetime.now().isoformat(timespec='seconds')
    c = base.db()
    try:
        if kind == 'reset':
            c.execute('DELETE FROM mikrotik_ip_pools WHERE router_name=?', (router,))
            c.execute('DELETE FROM mikrotik_ip_used WHERE router_name=?', (router,))
            c.commit()
            return jsonify(ok=True, kind='reset', router=router)

        if kind == 'pool':
            name = str(request.form.get('name') or '').strip()[:160]
            ranges = str(request.form.get('ranges') or '').strip()[:2000]
            if not name or not ranges:
                return jsonify(ok=False, error='missing-pool-data'), 400
            c.execute('INSERT OR REPLACE INTO mikrotik_ip_pools(router_name,name,ranges,updated_at) VALUES(?,?,?,?)',
                      (router, name, ranges, now))
            c.commit()
            return jsonify(ok=True, kind='pool', router=router, name=name)

        if kind == 'used':
            address = str(request.form.get('address') or '').strip()
            source = str(request.form.get('source') or 'ROUTER').strip().upper()[:24]
            if not _is_ip(address):
                return jsonify(ok=True, kind='used', ignored=True)
            c.execute('INSERT OR IGNORE INTO mikrotik_ip_used(router_name,address,source,updated_at) VALUES(?,?,?,?)',
                      (router, address, source, now))
            c.commit()
            return jsonify(ok=True, kind='used', router=router, address=address)

        return jsonify(ok=False, error='invalid-kind'), 400
    finally:
        c.close()


def _expand_segment(segment):
    segment = segment.strip()
    if not segment:
        return []
    try:
        if '-' in segment:
            a, b = [x.strip() for x in segment.split('-', 1)]
            start = ipaddress.ip_address(a); end = ipaddress.ip_address(b)
            if start.version != 4 or end.version != 4 or int(end) < int(start):
                return []
            span = int(end) - int(start) + 1
            if span > 65536:
                return []
            return [str(ipaddress.ip_address(i)) for i in range(int(start), int(end) + 1)]
        if '/' in segment:
            net = ipaddress.ip_network(segment, strict=False)
            if net.version != 4 or net.num_addresses > 65536:
                return []
            return [str(x) for x in net.hosts()]
        ip = ipaddress.ip_address(segment)
        return [str(ip)] if ip.version == 4 else []
    except ValueError:
        return []


def _latest_for_router(c, router):
    row = c.execute('SELECT MAX(updated_at) updated_at FROM mikrotik_ip_pools WHERE router_name=?', (router,)).fetchone()
    return (row['updated_at'] or '') if row else ''


def free_ips_refresh_api():
    """Ask the pull-agent on the selected MikroTik to refresh pools immediately."""
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    ensure_schema()
    router = (request.args.get('router') or 'CCR2116')[:80]
    c = base.db()
    try:
        before = _latest_for_router(c, router)
        pending = c.execute(
            """SELECT id FROM router_commands
               WHERE router_name=? AND action='SYNC_POOLS'
               AND status IN ('PENDIENTE','EN_PROCESO')
               ORDER BY id DESC LIMIT 1""",
            (router,)
        ).fetchone()
        if pending:
            command_id = pending['id']
            queued = False
        else:
            pbr_client._queue(c, None, '', router, 'SYNC_POOLS', {})
            command_id = c.execute('SELECT last_insert_rowid() id').fetchone()['id']
            queued = True
        c.commit()
        return jsonify(ok=True, router=router, command_id=command_id, queued=queued, before=before)
    finally:
        c.close()


def free_ips_api():
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    ensure_schema()
    router = (request.args.get('router') or 'CCR2116')[:80]
    q = (request.args.get('q') or '').strip().lower()
    c = base.db()
    pools = c.execute('SELECT * FROM mikrotik_ip_pools WHERE router_name=? ORDER BY name', (router,)).fetchall()
    used = {r['address'] for r in c.execute('SELECT address FROM mikrotik_ip_used WHERE router_name=?', (router,)).fetchall()}
    try:
        used.update(r['ip_address'] for r in c.execute(
            "SELECT ip_address FROM customers WHERE router_name=? AND COALESCE(ip_address,'')<>''", (router,)
        ).fetchall() if r['ip_address'])
    except Exception:
        pass
    c.close()

    items = []
    seen = set()
    latest = ''
    for pool in pools:
        latest = max(latest, pool['updated_at'] or '')
        for segment in str(pool['ranges'] or '').split(','):
            for ip in _expand_segment(segment):
                if ip in used or ip in seen:
                    continue
                seen.add(ip)
                if q and q not in ip.lower() and q not in (pool['name'] or '').lower() and q not in (pool['ranges'] or '').lower():
                    continue
                items.append({'ip': ip, 'pool': pool['name'], 'range': pool['ranges']})
                if len(items) >= 3000:
                    break
            if len(items) >= 3000:
                break
        if len(items) >= 3000:
            break

    return jsonify(ok=True, router=router, items=items, pools=len(pools), used=len(used), updated_at=latest)


def _inject_picker(html):
    if 'if-free-ip-modal' in html:
        return html
    pattern = re.compile(r'<div><label>IP asignada<input name="ip_address"([^>]*)></label></div>')
    replacement = r'''<div class="ip-picker-field"><label>IP remota (opcional)<div class="ip-picker-input"><input id="if-ip-address" name="ip_address"\1><button class="btn blue" type="button" onclick="IFIP.open()" title="Ver IPs libres de los pools del MikroTik"><span style="font-size:18px">⌕</span><span>Ver IPs libres</span></button></div><small class="muted">Consulta los pools del MikroTik y selecciona una IP disponible.</small></label></div>'''
    html, count = pattern.subn(replacement, html, count=1)
    if count == 0:
        return html

    modal = r'''
<style>
.ip-picker-input{display:flex;gap:8px;align-items:center}.ip-picker-input input{flex:1;min-width:0}.ip-picker-input .btn{white-space:nowrap;margin-top:6px;height:40px}
#if-free-ip-modal{position:fixed;inset:0;background:#0009;z-index:9999;display:none;align-items:center;justify-content:center;padding:18px}.if-ip-box{width:min(760px,96vw);max-height:84vh;background:#0d1a29;border:1px solid #2a4058;border-radius:14px;box-shadow:0 24px 80px #000c;display:flex;flex-direction:column;overflow:hidden}.if-ip-head{display:flex;align-items:center;justify-content:space-between;padding:17px 18px;border-bottom:1px solid #22374e}.if-ip-head h2{margin:0;font-size:22px}.if-ip-close{border:0;background:transparent;color:#aebdcb;font-size:28px;cursor:pointer}.if-ip-tools{padding:14px 18px;border-bottom:1px solid #22374e}.if-ip-searchline{display:flex;gap:8px}.if-ip-tools input{flex:1;width:100%;background:#101f30;border:1px solid #2b4259;color:#fff;border-radius:9px;padding:12px}.if-ip-refresh{min-width:44px;border:1px solid #2b4259;background:#132336;color:#fff;border-radius:9px;cursor:pointer;font-size:20px}.if-ip-meta{font-size:12px;color:#8da1b6;margin-top:8px}.if-ip-list{overflow:auto;padding:6px 0 12px}.if-ip-group{padding:9px 18px 5px;color:#8da1b6;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;background:#0b1725;position:sticky;top:0}.if-ip-row{width:100%;display:block;text-align:left;border:0;border-bottom:1px solid #1c3044;background:transparent;color:#e8eef8;padding:12px 18px;cursor:pointer}.if-ip-row:hover{background:#122438}.if-ip-row strong{display:block;font-family:Consolas,monospace;font-size:18px}.if-ip-row small{display:block;color:#8297ab;margin-top:4px}.if-ip-empty{padding:28px 18px;text-align:center;color:#8da1b6}.if-ip-loading{padding:34px 18px;text-align:center;color:#c4d4e5}.if-ip-spinner{display:inline-block;width:20px;height:20px;border:2px solid #385069;border-top-color:#e8eef8;border-radius:50%;animation:ifspin .8s linear infinite;vertical-align:middle;margin-right:10px}@keyframes ifspin{to{transform:rotate(360deg)}}@media(max-width:650px){.ip-picker-input{align-items:stretch;flex-direction:column}.ip-picker-input .btn{margin-top:0;width:100%}}
</style>
<div id="if-free-ip-modal" role="dialog" aria-modal="true" aria-label="IPs libres del MikroTik">
  <div class="if-ip-box">
    <div class="if-ip-head"><div><h2>IPs libres (pools MikroTik)</h2><div class="muted" style="margin-top:4px">Selecciona una IP para colocarla automáticamente en el cliente.</div></div><button class="if-ip-close" type="button" onclick="IFIP.close()">×</button></div>
    <div class="if-ip-tools"><div class="if-ip-searchline"><input id="if-ip-filter" type="text" placeholder="Filtrar por IP o pool..." oninput="IFIP.render()"><button class="if-ip-refresh" type="button" onclick="IFIP.refresh()" title="Consultar de nuevo">↻</button></div><div id="if-ip-meta" class="if-ip-meta"></div></div>
    <div id="if-ip-list" class="if-ip-list"></div>
  </div>
</div>
<script>
window.IFIP=(function(){
  let items=[];
  let lastData=null;
  const modal=()=>document.getElementById('if-free-ip-modal');
  const list=()=>document.getElementById('if-ip-list');
  const meta=()=>document.getElementById('if-ip-meta');
  const filter=()=>document.getElementById('if-ip-filter');
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  function router(){const e=document.querySelector('[name="router_name"]');return e&&e.value?e.value:'CCR2116';}
  async function read(){
    const r=await fetch('/api/mikrotik/free-ips?router='+encodeURIComponent(router()),{headers:{'Accept':'application/json'},cache:'no-store'});
    const d=await r.json();
    if(!d.ok) throw new Error(d.error||'No se pudo leer');
    return d;
  }
  function applyData(d,note){
    lastData=d;
    items=Array.isArray(d.items)?d.items:[];
    meta().textContent=(d.pools||0)+' pools · '+items.length+' IPs libres'+(d.updated_at?' · lectura '+d.updated_at:'')+(note?' · '+note:'');
    render();
  }
  async function refresh(){
    list().innerHTML='<div class="if-ip-loading"><span class="if-ip-spinner"></span>Consultando MikroTik...</div>';
    meta().textContent='Leyendo pools e IPs ocupadas en tiempo real';
    let before='';
    try{
      try{const old=await read();before=old.updated_at||'';}catch(_e){}
      const rr=await fetch('/api/mikrotik/free-ips/refresh?router='+encodeURIComponent(router()),{method:'POST',headers:{'Accept':'application/json'},cache:'no-store'});
      const rd=await rr.json();
      if(!rd.ok) throw new Error(rd.error||'No se pudo solicitar la consulta');
      before=rd.before||before;
      for(let i=0;i<16;i++){
        await sleep(700);
        const d=await read();
        if((d.updated_at&&d.updated_at!==before&&d.pools>0) || (!before&&d.pools>0)){
          applyData(d,'actualizado ahora');
          return;
        }
      }
      const d=await read();
      applyData(d,'mostrando última lectura');
    }catch(e){
      try{applyData(await read(),'última lectura guardada');}
      catch(_e){items=[];lastData=null;meta().textContent='';list().innerHTML='<div class="if-ip-empty">No pude consultar el MikroTik. Verifica que el agente esté instalado y conectado.</div>';}
    }
  }
  function render(){
    const q=(filter().value||'').toLowerCase();
    const rows=items.filter(x=>!q||String(x.ip).toLowerCase().includes(q)||String(x.pool).toLowerCase().includes(q)||String(x.range).toLowerCase().includes(q));
    list().innerHTML='';
    if(!rows.length){
      list().innerHTML='<div class="if-ip-empty">'+((lastData&&lastData.pools)?'No encontré IPs libres con ese filtro.':'No llegaron pools del MikroTik todavía.')+'</div>';
      return;
    }
    let current='';
    rows.slice(0,1200).forEach(x=>{
      const key=String(x.pool||'Sin pool');
      if(key!==current){
        current=key;
        const h=document.createElement('div');h.className='if-ip-group';h.textContent=key+' · '+String(x.range||'');list().appendChild(h);
      }
      const b=document.createElement('button');b.type='button';b.className='if-ip-row';
      const s=document.createElement('strong');s.textContent=x.ip;
      const sm=document.createElement('small');sm.textContent='Pool: '+x.pool+' · Rango: '+x.range;
      b.appendChild(s);b.appendChild(sm);b.onclick=()=>choose(x.ip);list().appendChild(b);
    });
  }
  function choose(ip){
    const e=document.querySelector('[name="ip_address"]');
    if(e){e.value=ip;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}
    close();
  }
  function open(){modal().style.display='flex';document.body.style.overflow='hidden';filter().value='';refresh();setTimeout(()=>filter().focus(),100);}
  function close(){modal().style.display='none';document.body.style.overflow='';}
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&modal()&&modal().style.display==='flex')close();});
  return {open,close,render,choose,refresh};
})();
</script>
'''
    return html + modal


def setup(app):
    ensure_schema()
    original = pbr_client.customer_form
    def customer_form_with_ip_picker(row=None):
        return _inject_picker(original(row))
    pbr_client.customer_form = customer_form_with_ip_picker
    app.add_url_rule('/api/mikrotik/pool-state', endpoint='mikrotik_pool_state_sync', view_func=pool_state_sync, methods=['POST'])
    app.add_url_rule('/api/mikrotik/pool-state-v2', endpoint='mikrotik_pool_state_sync_v2', view_func=pool_state_sync_v2, methods=['POST'])
    app.add_url_rule('/api/mikrotik/free-ips', endpoint='mikrotik_free_ips_api', view_func=free_ips_api, methods=['GET'])
    app.add_url_rule('/api/mikrotik/free-ips/refresh', endpoint='mikrotik_free_ips_refresh_api', view_func=free_ips_refresh_api, methods=['POST'])
