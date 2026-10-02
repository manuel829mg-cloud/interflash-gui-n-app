import os
from flask import Flask, request, redirect, make_response

app = Flask(__name__)
ADMIN_USER = os.environ.get("ADMIN_USER", "manuel")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

LOGIN_HTML = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash</title><style>body{margin:0;font-family:Arial;background:#111827;display:grid;place-items:center;min-height:100vh}.box{width:min(420px,90vw);background:white;padding:32px;border-radius:18px}input,button{width:100%;box-sizing:border-box;padding:13px;margin:8px 0;border-radius:10px;border:1px solid #d0d5dd;font-size:16px}button{background:#0a8f54;color:white;border:0;font-weight:700}</style></head><body><form class="box" method="post"><h1>INTER Flash</h1><p>Acceso al panel de administración</p><input name="username" placeholder="Usuario" required><input name="password" type="password" placeholder="Contraseña" required><button>Entrar</button></form></body></html>'''

DASHBOARD_HTML = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash</title><style>body{margin:0;font-family:Arial;background:#f5f7fa;color:#182230}aside{position:fixed;left:0;top:0;bottom:0;width:240px;background:#111820;color:white;padding:22px}aside a{display:block;color:#d5dae0;text-decoration:none;padding:10px 8px}main{margin-left:240px;padding:28px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:15px}.card{background:white;border:1px solid #e7e9ef;border-radius:14px;padding:20px}.n{font-size:30px;font-weight:800;margin-top:8px}</style></head><body><aside><h2>INTER Flash</h2><a href="/dashboard">Dashboard</a><a href="/clientes">Clientes</a><a href="/finanzas">Finanzas</a><a href="/facturas">Facturas</a><a href="/pagos">Pagos pendientes</a><a href="/routers">Routers</a><a href="/planes">Planes</a><a href="/zonas">Zonas</a><a href="/whatsapp">WhatsApp</a><a href="/soporte">Soporte Técnico</a><a href="/administracion">Administración</a></aside><main><h1>Dashboard</h1><p>Estado actual de tu red</p><div class="cards">%s</div></main></body></html>'''

MODULES = ["clientes","finanzas","facturas","pagos","routers","planes","zonas","whatsapp","soporte","administracion"]

def logged_in():
    return request.cookies.get("if_session") == "ok"

@app.get("/health")
def health():
    return "ok", 200

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASSWORD:
            response = make_response(redirect("/dashboard"))
            response.set_cookie("if_session", "ok", httponly=True, samesite="Lax")
            return response
        return LOGIN_HTML, 401
    return LOGIN_HTML

@app.get("/")
def home():
    return redirect("/dashboard" if logged_in() else "/login")

@app.get("/dashboard")
def dashboard():
    if not logged_in():
        return redirect("/login")
    labels = ["Clientes totales","Clientes activos","Suspendidos","Instalaciones","Reporte de pagos","Promesas de pago","Tickets","Vence hoy"]
    cards = "".join(f'<div class="card"><div>{label}</div><div class="n">0</div></div>' for label in labels)
    return DASHBOARD_HTML % cards

for name in MODULES:
    def module_page(name=name):
        if not logged_in():
            return redirect("/login")
        return f"<h1>{name.title()}</h1><p>0 registros. Módulo listo para configurar.</p>"
    app.add_url_rule(f"/{name}", endpoint=name, view_func=module_page)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
