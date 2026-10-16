"""Opt-in fixed IP proposals. Never changes a router or a saved customer.

Only explicitly configured static ranges are eligible. They must be outside
all dynamic MikroTik pools. Proposals are advisory; save-time guards still run.
"""
import ipaddress
import json
from datetime import datetime, timedelta
from flask import request, jsonify
import app as base
import pbr_client
from commercial_service import _contains, _rate

MAX_AGE = timedelta(minutes=15)


def suggest(c, router, plan_id, customer_id=None):
    customer = c.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone() if customer_id else None
    plan = c.execute('SELECT * FROM plans WHERE id=? AND active=1', (plan_id,)).fetchone()
    if not plan:
        raise ValueError('Selecciona el plan antes de buscar una IP automática.')
    expected = (float(plan['upload_mbps']) * 1000000, float(plan['download_mbps']) * 1000000)
    profiles = c.execute('SELECT * FROM push_ppp_profiles WHERE router_name=?', (router,)).fetchall()
    pools = c.execute('SELECT * FROM mikrotik_ip_pools WHERE router_name=?', (router,)).fetchall()
    occupied = c.execute('SELECT * FROM mikrotik_ip_used WHERE router_name=?', (router,)).fetchall()
    # A recent pool snapshot alone does not establish fresh occupancy.
    now = datetime.now()
    try:
        fresh = (pools and occupied and all(timedelta(0) <= now-datetime.fromisoformat(r['updated_at']) <= MAX_AGE
                                           for r in [*pools, *occupied]))
    except (ValueError, TypeError):
        fresh = False
    if not fresh:
        raise ValueError('Sincroniza los pools y las IP ocupadas del MikroTik antes de continuar.')
    compatible = [p for p in profiles if _rate(p['rate_limit']) == expected]
    if not compatible:
        raise ValueError('No hay un perfil sincronizado con la velocidad del plan.')
    # Preserve existing assignments. Static PPP remote IP overrides profile pool.
    if customer and customer['ip_address'] and router == (customer['router_name'] or 'CCR2116'):
        current = next((p for p in profiles if p['name'] == customer['mikrotik_profile']), None)
        choices = [p for p in compatible if p['remote_address'] == customer['ip_address'] or
                   any(pool['name'] == p['remote_address'] and _contains(pool['ranges'], customer['ip_address']) for pool in pools) or
                   (current and (p['remote_address'],p['local_address']) == (current['remote_address'],current['local_address']))]
        if choices:
            return {'ip': customer['ip_address'], 'preserved': True, 'confirmation_required': False}
    row = c.execute("SELECT value FROM app_settings WHERE key='automatic_ip_static_ranges'").fetchone()
    try:
        settings = json.loads(row[0]) if row else []
        if not isinstance(settings, list): raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('La configuración del rango reservado no es válida.')
    ranges = [r for r in settings if isinstance(r,dict) and r.get('router') == router
              and str(r.get('plan_id')) == str(plan_id)]
    if not ranges:
        raise ValueError('Primero configura un rango reservado para IP fijas de este router y plan; no se tomará una IP de los pools dinámicos.')
    from free_ip_picker import _expand_segment
    used = {r['address'] for r in occupied}
    used.update(r[0] for r in c.execute("SELECT ip_address FROM customers WHERE COALESCE(router_name,'CCR2116')=?", (router,)))
    # Require one explicit profile / connectivity, never guess among networks.
    candidates = []
    for entry in ranges:
        profile = next((p for p in compatible if p['name'] == entry.get('profile')), None)
        if not profile:
            raise ValueError('El perfil del rango reservado no coincide con la velocidad del plan.')
        for segment in str(entry.get('ranges') or '').split(','):
            expanded = _expand_segment(segment)
            if not expanded: raise ValueError('El rango reservado contiene una dirección o intervalo no válido.')
            # Reject the whole range when it overlaps a dynamic pool, even if
            # the first available address happens to be outside that overlap.
            if any(_contains(pool['ranges'], ip) for pool in pools for ip in expanded):
                raise ValueError('El rango reservado se solapa con un pool dinámico del MikroTik. Corrige la reserva antes de continuar.')
            candidates.extend((ip, profile['name']) for ip in expanded if ip not in used and ip != profile['local_address'])
    if not candidates:
        raise ValueError('No quedan IP disponibles en el rango reservado para este servicio.')
    if len({profile for _,profile in candidates}) != 1:
        raise ValueError('Hay varios perfiles de instalación posibles. Selecciona el rango de instalación antes de continuar.')
    ip, profile = min(candidates, key=lambda pair:int(ipaddress.IPv4Address(pair[0])))
    return {'ip':ip, 'profile':profile, 'preserved':False, 'confirmation_required':True}


def proposal():
    if not base.logged_in():
        return jsonify(ok=False,error='login-required'),401
    c=base.db()
    try:
        cid=request.args.get('customer_id',type=int)
        result=suggest(c,request.args.get('router') or 'CCR2116',request.args.get('plan_id'),cid)
        return jsonify(ok=True,**result)
    except ValueError as error:
        return jsonify(ok=False,error=str(error)),409
    finally:
        c.close()


SCRIPT = r'''<div class="full" id="automatic-ip-proposal">
<button type="button" class="btn blue" id="automatic-ip-button">Proponer IP automáticamente</button>
<p role="status" aria-live="polite" id="automatic-ip-status">La IP actual se conserva. Las propuestas se revisan antes de guardar.</p></div>
<script>
(()=>{
 const button=document.getElementById('automatic-ip-button'), status=document.getElementById('automatic-ip-status');
 const field=n=>document.querySelector('[name="'+n+'"]');
 button.onclick=async()=>{
  button.disabled=true;
  const router=field('router_name')?.value||'CCR2116';
  const selection=field('mikrotik_profile')?.value||'';
  const plan=selection.startsWith('plan:')?selection.slice(5):(field('plan_id')?.value||'');
  const current=field('ip_address')?.value||'';
  const match=location.pathname.match(/\/customers\/(\d+)\/edit/);
  const query=new URLSearchParams({router,plan_id:plan,...(match?{customer_id:match[1]}:{})});
  status.textContent='Comprobando el rango reservado y las IP ocupadas…';
  try{
   const response=await fetch('/api/customers/ip-proposal?'+query,{cache:'no-store'}), data=await response.json();
   if(!response.ok||!data.ok)throw new Error(data.error||'No se pudo comprobar la IP.');
   if(router!==(field('router_name')?.value||'CCR2116')||current!==(field('ip_address')?.value||'')||selection!==(field('mikrotik_profile')?.value||''))throw new Error('El formulario cambió. Solicita otra propuesta.');
   if(data.preserved){status.textContent='Se conserva la IP actual: '+data.ip;return;}
   if(confirm('IP propuesta: '+data.ip+(current?'\nIP actual: '+current:'')+'\n¿Usar esta propuesta en el formulario? Solo se aplicará al guardar el cliente.')){
    field('ip_address').value=data.ip;
    field('ip_address').dispatchEvent(new Event('change',{bubbles:true}));
    status.textContent='Propuesta seleccionada: '+data.ip+'. Todavía no está guardada ni reservada; se debe verificar al guardar.';
   }else{status.textContent='Se conserva el formulario sin cambios.';}
  }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
 };
})();
</script>'''


def setup_preview(app):
    """Draft-only installation. Does not enable automatic saves or router writes."""
    original=pbr_client.customer_form
    def form(row=None):
        return original(row)+SCRIPT
    pbr_client.customer_form=form
    app.add_url_rule('/api/customers/ip-proposal',endpoint='automatic_ip_proposal',view_func=proposal,methods=['GET'])
