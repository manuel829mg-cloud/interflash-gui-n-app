"""Optional Inter Flash TV integration for staging.

To enable, set INTERFLASH_TV_ENABLED=1 and INTERFLASH_TV_DB to a persistent
SQLite location, then call setup(app) from wsgi.py. Not enabled by default.
Only licensed channel URLs may be entered.
"""
import os
from flask import redirect, url_for, request, render_template_string, abort
import app as base
from interflash_tv_catalog import setup as setup_catalog
from interflash_tv_subscriptions_api import setup as setup_subscribers

def setup(app):
    if os.environ.get("INTERFLASH_TV_ENABLED") != "1":
        return
    db_path = os.environ.get("INTERFLASH_TV_DB")
    if not db_path:
        raise RuntimeError("INTERFLASH_TV_DB must point to persistent storage")
    setup_catalog(app, db_path=db_path, admin_check=base.logged_in)
    setup_subscribers(app, db_path=db_path, admin_check=base.logged_in)
    # Add the TV module to the existing Inter Flash navigation only in staging.
    if not any(item[0] == "interflash_tv_panel" for item in base.NAV):
        base.NAV.append(("interflash_tv_panel", "📺", "Inter Flash TV"))

    @app.get("/interflash-tv")
    def interflash_tv_panel():
        if not base.logged_in():
            return redirect(url_for("login"))
        return render_template_string("""<!doctype html>
<html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inter Flash TV</title>
<style>body{font:16px system-ui;max-width:920px;margin:2rem auto;padding:1rem;background:#101c30;color:#f4f7ff}input,button{padding:.7rem;margin:.25rem;border-radius:6px}button{cursor:pointer}table{width:100%;text-align:left}td,th{padding:.6rem;border-bottom:1px solid #536075}</style>
<h1>Inter Flash TV</h1><p>Panel de catálogo en pruebas. Solo canales con derechos de redistribución.</p>
<form id="channels"><input name="name" placeholder="Canal" required maxlength="120"><input name="category" placeholder="Categoría" maxlength="80" value="General"><input name="stream_url" type="url" placeholder="https://...m3u8" required><label><input name="rights_confirmed" type="checkbox" required>Confirmo derechos de distribución</label><button>Agregar</button></form>
<h2>Suscripciones de TV</h2>
<form id="subs"><input name="isp_client_id" inputmode="numeric" pattern="[0-9]+" placeholder="ID del cliente" required><select name="status"><option value="active">Activar</option><option value="suspended">Suspender</option><option value="inactive">Desactivar</option></select><input name="expires_at" type="datetime-local" aria-label="Vencimiento"><button>Guardar suscripción</button></form>
<p id="submessage" role="status"></p><table><thead><tr><th>Cliente</th><th>Estado TV</th><th>Vence</th></tr></thead><tbody id="subrows"></tbody></table>
<h2>Canales autorizados</h2>
<p id="message" role="status"></p><table><thead><tr><th>Canal</th><th>Categoría</th></tr></thead><tbody id="rows"></tbody></table>
<script>
async function load(){let r=await fetch('/interflash-tv/api/channels');if(!r.ok)return;let d=await r.json(),b=document.querySelector('#rows');b.replaceChildren();for(let c of d.channels){let tr=document.createElement('tr');for(let x of [c.name,c.category]){let td=document.createElement('td');td.textContent=x;tr.append(td)}b.append(tr)}}
document.querySelector('#channels').addEventListener('submit',async e=>{e.preventDefault();let f=e.target, v=new FormData(f);let r=await fetch('/interflash-tv/api/channels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:v.get('name'),category:v.get('category'),stream_url:v.get('stream_url'),rights_confirmed:v.has('rights_confirmed')})});document.querySelector('#message').textContent=r.ok?'Canal guardado':'No se pudo guardar';if(r.ok){f.reset();load()}});load();
async function loadSubs(){let r=await fetch('/interflash-tv/api/subscribers');if(!r.ok)return;let d=await r.json(),b=document.querySelector('#subrows');b.replaceChildren();for(let s of d.subscribers){let tr=document.createElement('tr');for(let x of [s.isp_client_id,s.status,s.expires_at||'—']){let td=document.createElement('td');td.textContent=x;tr.append(td)}b.append(tr)}}
document.querySelector('#subs').addEventListener('submit',async e=>{e.preventDefault();let v=new FormData(e.target),raw=v.get('expires_at'),expiry=raw?new Date(raw).toISOString():null;let r=await fetch('/interflash-tv/api/subscribers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({isp_client_id:v.get('isp_client_id'),status:v.get('status'),expires_at:expiry})});let d=await r.json();document.querySelector('#submessage').textContent=r.ok?'Suscripción guardada':(d.error||'Error al guardar');if(r.ok)loadSubs()});loadSubs();
</script></html>""")
