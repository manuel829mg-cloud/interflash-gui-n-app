"""Standalone test harness for Inter Flash TV; not connected to production."""
import os
from flask import Flask, session, redirect, request, render_template_string, url_for
from interflash_tv_catalog import setup

app = Flask(__name__)
app.secret_key = os.environ["TV_TEST_SECRET"]
admin_password = os.environ["TV_TEST_ADMIN_PASSWORD"]

def is_admin():
    return session.get("tv_admin") is True

setup(app, db_path=os.environ.get("TV_TEST_DB", "/tmp/interflash-tv-test.sqlite3"), admin_check=is_admin)

@app.route("/tv/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        import hmac
        if hmac.compare_digest(request.form.get("password", ""), admin_password):
            session["tv_admin"] = True
            return redirect(url_for("dashboard"))
    return render_template_string("""<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Inter Flash TV - Acceso</title><body><h1>Inter Flash TV</h1><form method="post"><label>Clave de pruebas <input type="password" name="password" required></label><button>Entrar</button></form></body></html>""")

@app.get("/tv")
def dashboard():
    if not is_admin():
        return redirect(url_for("login"))
    return render_template_string("""<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Inter Flash TV</title><style>body{font:16px system-ui;max-width:900px;margin:35px auto;padding:15px;background:#f7f8fa;color:#152334}input,button{padding:10px;margin:6px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #ccc}</style><h1>Inter Flash TV · Panel de pruebas</h1><p>Catálogo de canales autorizados. Este panel no está conectado al sistema de facturación.</p><form id="form"><input name="name" placeholder="Nombre del canal" required maxlength="120"><input name="category" placeholder="Categoría" value="General" maxlength="80"><input name="stream_url" placeholder="https://.../playlist.m3u8" type="url" required><label><input name="rights_confirmed" type="checkbox" required> Confirmo derechos para distribuir este canal</label><button>Agregar canal</button></form><p id="message" role="status"></p><table><thead><tr><th>Canal</th><th>Categoría</th><th>Activo</th></tr></thead><tbody id="rows"></tbody></table><script>
async function refresh(){const r=await fetch('/interflash-tv/api/channels');if(!r.ok)return;const d=await r.json();const body=document.getElementById('rows');body.replaceChildren();for(const c of d.channels){const tr=document.createElement('tr');for(const value of [c.name,c.category,c.enabled?'Sí':'No']){const td=document.createElement('td');td.textContent=value;tr.appendChild(td)}body.appendChild(tr)}}
document.getElementById('form').addEventListener('submit',async e=>{e.preventDefault();const f=e.target;const r=await fetch('/interflash-tv/api/channels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.name.value,category:f.category.value,stream_url:f.stream_url.value,rights_confirmed:f.rights_confirmed.checked})});const d=await r.json();document.getElementById('message').textContent=r.ok?'Canal agregado':(d.error||'Error');if(r.ok){f.reset();refresh()}});refresh();
</script></html>""")

@app.get("/health")
def health():
    return {"status": "ok", "service": "interflash-tv-test"}
