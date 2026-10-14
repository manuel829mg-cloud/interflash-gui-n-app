"""Commercial plan selection with server-validated, pool-compatible profiles."""
import ipaddress
import re
from functools import wraps
from flask import request, jsonify, redirect, flash
from werkzeug.datastructures import ImmutableMultiDict
import app as base
import pbr_client


def _value(row, key, default=''):
    return row[key] if row is not None and key in row.keys() and row[key] is not None else default


def _rate(value):
    token = str(value or '').split()
    parts = token[0].split('/') if token else []
    if len(parts) == 1:
        parts *= 2
    def number(text):
        m = re.fullmatch(r'(\d+(?:\.\d+)?)([kKmMgG]?)', text)
        return float(m[1]) * {'': 1, 'k': 1000, 'm': 1000000, 'g': 1000000000}[m[2].lower()] if m else None
    return tuple(number(p) for p in parts) if len(parts) == 2 else ()


def _contains(ranges, address):
    try:
        ip = ipaddress.ip_address(address)
        for part in str(ranges or '').split(','):
            part = part.strip()
            if '-' in part:
                a, b = map(ipaddress.ip_address, part.split('-', 1))
                if a.version == ip.version == b.version and int(a) <= int(ip) <= int(b):
                    return True
            elif '/' in part:
                if ip in ipaddress.ip_network(part, strict=False):
                    return True
            elif part and ip == ipaddress.ip_address(part):
                return True
    except ValueError:
        pass
    return False


def resolve(c, plan_id, router, line, address, customer=None):
    old_plan = str(_value(customer, 'plan_id'))
    old_profile = str(_value(customer, 'mikrotik_profile'))
    old_router = _value(customer, 'router_name', 'CCR2116') or 'CCR2116'
    if not plan_id:
        return old_profile
    plan = c.execute('SELECT * FROM plans WHERE id=? AND active=1', (plan_id,)).fetchone()
    if not plan:
        raise ValueError('Selecciona uno de los seis planes disponibles.')
    profiles = c.execute('SELECT * FROM push_ppp_profiles WHERE router_name=? ORDER BY name', (router,)).fetchall()
    expected = (float(plan['upload_mbps']) * 1000000, float(plan['download_mbps']) * 1000000)
    candidates = [p for p in profiles if _rate(p['rate_limit']) == expected]
    current = next((p for p in profiles if p['name'] == old_profile), None)
    # The explicitly assigned IP determines installation connectivity. A saved
    # profile can be stale after an earlier failed edit and must not lock the
    # customer to a different pool.
    if address and pbr_client._table_exists(c, 'mikrotik_ip_pools'):
        pools = {p['name'] for p in c.execute('SELECT name,ranges FROM mikrotik_ip_pools WHERE router_name=?', (router,)) if _contains(p['ranges'], address)}
        candidates = [p for p in candidates if p['remote_address'] in pools or p['remote_address'] == address]
    elif current and router == old_router and current['remote_address'] and current['local_address']:
        candidates = [p for p in candidates if (p['remote_address'], p['local_address']) == (current['remote_address'], current['local_address'])]
    else:
        candidates = []
    # Existing static PPP remote addresses override the profile's pool.
    # Only fall back for the customer's unchanged address on the same router,
    # keeping the old local address and pool; never migrate a new IP this way.
    if (not candidates and customer is not None and address
            and address == _value(customer, 'ip_address')
            and router == old_router and current is not None
            and current['remote_address'] and current['local_address']):
        candidates = [p for p in profiles if _rate(p['rate_limit']) == expected
                      and (p['remote_address'], p['local_address'])
                      == (current['remote_address'], current['local_address'])]
    if not candidates:
        raise ValueError(f'Falta un perfil compatible de {plan["download_mbps"]}/{plan["upload_mbps"]} Mbps para este cliente. Sincroniza los perfiles o configura esa velocidad en su pool.')
    # Use the same commercial catalog as the form's server validation.
    # A legacy pool-compatible profile must not win alphabetically and then
    # be rejected as a noncommercial selection by the save wrapper.
    import customer_provisioning
    commercial = {item['name'] for item in customer_provisioning._commercial_profiles(c, router)
                  if len(item['plan_ids']) == 1 and str(item['plan_ids'][0]) == str(plan_id)}
    candidates = [p for p in candidates if p['name'] in commercial]
    if not candidates:
        raise ValueError(f'Falta vincular un perfil comercial de {plan["download_mbps"]}/{plan["upload_mbps"]} Mbps compatible con el pool del cliente. Sincroniza los perfiles después de crearlo.')
    mapped = c.execute('SELECT profile_name FROM plan_profile_map WHERE router_name=? AND plan_id=? AND pbr_line IN (?,\'\') ORDER BY pbr_line DESC', (router, plan_id, line)).fetchall()
    names = {p['name'] for p in candidates}
    for mapping in mapped:
        if mapping['profile_name'] in names:
            return mapping['profile_name']
    if old_profile in names:
        return old_profile
    connectivity = {(p['remote_address'], p['local_address']) for p in candidates}
    if len(connectivity) != 1:
        raise ValueError('Hay varios pools compatibles. Selecciona una IP del pool de instalación.')
    # Explicit PBR remains independent; never infer speed or pools from names.
    line_number = str(line).split('-')[1] if line in pbr_client.PBR_LISTS else ''
    candidates.sort(key=lambda p: (0 if line_number and (f'Linea-{line_number}-' in p['name'] or p['name'].startswith(line_number + '-')) else 1, p['name']))
    return candidates[0]['name']


def profile_api():
    if not base.logged_in():
        return jsonify(ok=False, error='login-required'), 401
    c = base.db()
    try:
        customer = c.execute('SELECT * FROM customers WHERE id=?', (request.args.get('customer_id'),)).fetchone()
        profile = resolve(c, request.args.get('plan_id'), request.args.get('router') or _value(customer, 'router_name', 'CCR2116'), request.args.get('pbr_line') or _value(customer, 'pbr_line'), request.args.get('ip') or _value(customer, 'ip_address'), customer)
        return jsonify(ok=True, profile=profile)
    except ValueError as error:
        if request.args.get('debug') == '1':
            router = request.args.get('router') or 'CCR2116'
            plan = c.execute('SELECT * FROM plans WHERE id=?', (request.args.get('plan_id'),)).fetchone()
            expected = (float(plan['upload_mbps']) * 1000000, float(plan['download_mbps']) * 1000000) if plan else ()
            current_name = _value(customer, 'mikrotik_profile')
            rows = c.execute('SELECT name,rate_limit,remote_address,local_address FROM push_ppp_profiles WHERE router_name=?', (router,)).fetchall()
            detail = [dict(p) for p in rows if p['name'] == current_name or _rate(p['rate_limit']) == expected]
            return jsonify(ok=False, error=str(error), current_profile=current_name, profiles=detail), 400
        return jsonify(ok=False, error=str(error)), 400
    finally:
        c.close()


SCRIPT = r'''<script>
(() => {
 const hidden=document.querySelector('[name="mikrotik_profile"]');if(!hidden)return;
 const form=hidden.closest('form'), plan=form.querySelector('[name="plan_id"]');
 const initial=plan.value, note=document.getElementById('if-commercial-note');
 let pending=false, failed=false, revision=0;
 const field=(name,fallback)=>{const e=form.querySelector('[name="'+name+'"]');return e?e.value:fallback;};
 async function update(){
  const seq=++revision;pending=true;failed=false;note.textContent='Verificando el plan…';
  try{
   const q=new URLSearchParams({customer_id:hidden.dataset.customer,plan_id:plan.value,router:field('router_name',hidden.dataset.router),pbr_line:field('pbr_line',hidden.dataset.line),ip:field('ip_address',hidden.dataset.ip)});
   const r=await fetch('/api/mikrotik/commercial-profile?'+q,{cache:'no-store'}),d=await r.json();if(seq!==revision)return;
   if(!d.ok)throw new Error(d.error);hidden.value=d.profile||'';
   note.textContent=plan.value===initial&&hidden.dataset.customer?'Se conserva el servicio actual.':'Perfil asignado automáticamente para este plan.';
  }catch(e){if(seq!==revision)return;failed=true;hidden.value='';note.textContent=e.message||'No se pudo verificar el plan.';}
  finally{if(seq===revision)pending=false;}
 }
 plan.addEventListener('change',update);
 ['router_name','pbr_line','ip_address'].forEach(name=>{const e=form.querySelector('[name="'+name+'"]');if(e)e.addEventListener('change',update);});
 form.addEventListener('submit',e=>{if(pending||failed){e.preventDefault();alert(pending?'Espera a que termine la verificación del plan.':note.textContent);}});
})();
</script>'''


def clean_form(html, customer=None):
    # The commercial profile selector supplies both the profile and billing plan.
    return html


def setup(app):
    if getattr(pbr_client.customer_form, '_commercial_service', False):
        return
    original_form = pbr_client.customer_form
    def form(row=None):
        return clean_form(original_form(row), row)
    form._commercial_service = True
    pbr_client.customer_form = form
    original_profile = app.view_functions.get('customer_profile')
    if original_profile:
        @wraps(original_profile)
        def page(id, *args, **kwargs):
            response = original_profile(id, *args, **kwargs)
            c = base.db()
            try:
                row = c.execute('SELECT * FROM customers WHERE id=?', (id,)).fetchone()
            finally:
                c.close()
            if isinstance(response, str):
                return clean_form(response, row)
            if hasattr(response, 'get_data') and response.status_code == 200:
                response.set_data(clean_form(response.get_data(as_text=True), row))
            return response
        app.view_functions['customer_profile'] = page
    def protect(original, endpoint):
        @wraps(original)
        def wrapped(*args, **kwargs):
            if request.method != 'POST' or not base.logged_in():
                return original(*args, **kwargs)
            c = base.db()
            try:
                customer = c.execute('SELECT * FROM customers WHERE id=?', (kwargs.get('id'),)).fetchone() if kwargs.get('id') else None
                data = request.form.copy()
                plan_id = data.get('plan_id') if 'plan_id' in data else _value(customer, 'plan_id')
                # A disabled inherited plan is not submitted by browsers.
                if 'plan_id' not in data:
                    data['plan_id'] = str(plan_id or '')
                import customer_provisioning
                router = data.get('router_name') or _value(customer, 'router_name', 'CCR2116')
                selected = data.get('mikrotik_profile') or ''
                if selected.startswith('plan:'):
                    chosen_id = selected.split(':', 1)[1]
                    if not chosen_id.isdigit():
                        raise ValueError('Selecciona un plan válido.')
                    line = data.get('pbr_line', _value(customer, 'pbr_line'))
                    address = data.get('ip_address', _value(customer, 'ip_address'))
                    keep_service = (endpoint == 'customer_edit' and customer is not None
                                    and chosen_id == str(_value(customer, 'plan_id'))
                                    and router == (_value(customer, 'router_name') or 'CCR2116')
                                    and line == _value(customer, 'pbr_line')
                                    and address == _value(customer, 'ip_address')
                                    and data.get('pppoe', _value(customer, 'pppoe')) == _value(customer, 'pppoe')
                                    and not data.get('create_in_router'))
                    selected = (str(_value(customer, 'mikrotik_profile')) if keep_service else
                                resolve(c, chosen_id, router, line, address, customer))
                    data['plan_id'] = chosen_id
                    data['mikrotik_profile'] = selected
                    plan_id = chosen_id
                items = [x for x in customer_provisioning._commercial_profiles(c, router) if x['name'] == selected]
                if items and len(items[0]['plan_ids']) == 1:
                    data['plan_id'] = str(items[0]['plan_ids'][0])
                    data['mikrotik_profile'] = selected
                elif customer is not None and selected == _value(customer, 'mikrotik_profile') and str(plan_id or '') == str(_value(customer, 'plan_id')):
                    data['mikrotik_profile'] = selected
                else:
                    raise ValueError('Selecciona un perfil comercial con precio antes de guardar.')

            except ValueError as error:
                flash(str(error))
                return redirect(request.path if endpoint != 'change_customer_plan' else f'/customers/{kwargs.get("id")}/profile')
            finally:
                c.close()
            old_form = request.form
            request.form = ImmutableMultiDict(data)
            try:
                return original(*args, **kwargs)
            finally:
                request.form = old_form
        return wrapped
    for endpoint in ('customer_new', 'customer_edit', 'change_customer_plan'):
        if endpoint in app.view_functions:
            app.view_functions[endpoint] = protect(app.view_functions[endpoint], endpoint)
    app.add_url_rule('/api/mikrotik/commercial-profile', endpoint='commercial_profile_api', view_func=profile_api)
