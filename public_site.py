from flask import request, redirect, url_for, render_template_string
import app as appmodule


PUBLIC_CSS = r'''
:root{--navy:#0b1726;--navy2:#10243b;--blue:#1677ff;--cyan:#26c6da;--green:#11a767;--ink:#152033;--muted:#667085;--line:#e7ebf0;--bg:#f6f8fb;--card:#fff;--shadow:0 16px 50px rgba(15,35,60,.10)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--ink);background:var(--bg)}a{text-decoration:none;color:inherit}.wrap{width:min(1160px,92vw);margin:auto}.nav{position:sticky;top:0;z-index:50;background:rgba(11,23,38,.96);backdrop-filter:blur(10px);border-bottom:1px solid #ffffff18}.navin{height:72px;display:flex;align-items:center;justify-content:space-between;gap:18px}.brand{display:flex;align-items:center;gap:11px;color:#fff;font-weight:900;font-size:20px}.brandmark{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#0ca568,#28d499);color:#fff;box-shadow:0 8px 24px #0ca56855}.links{display:flex;gap:22px;align-items:center;color:#dbe6f0;font-size:14px;font-weight:700}.links a:hover{color:#fff}.btn{display:inline-flex;align-items:center;justify-content:center;border-radius:12px;padding:12px 17px;font-weight:800;border:1px solid var(--line);background:#fff;cursor:pointer}.btn.primary{background:linear-gradient(135deg,#0ca568,#078a56);color:#fff;border:0;box-shadow:0 10px 30px #0ca5683d}.btn.blue{background:linear-gradient(135deg,#1677ff,#0b5ccc);color:white;border:0}.hero{background:radial-gradient(circle at 80% 25%,#1f6d8d66,transparent 34%),linear-gradient(135deg,#071522,#102e48);color:#fff;padding:86px 0 74px;overflow:hidden}.hero-grid{display:grid;grid-template-columns:1.18fr .82fr;gap:48px;align-items:center}.eyebrow{display:inline-flex;gap:8px;align-items:center;padding:8px 12px;border-radius:999px;background:#ffffff12;border:1px solid #ffffff20;color:#bdebd7;font-size:13px;font-weight:800}.hero h1{font-size:clamp(42px,6vw,72px);line-height:1.02;margin:18px 0 18px;letter-spacing:-.04em}.hero p{font-size:19px;line-height:1.6;color:#cfdae5;max-width:650px}.hero-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}.hero-actions .ghost{border:1px solid #ffffff33;background:#ffffff0d;color:#fff}.speed-card{background:#fff;color:var(--ink);border-radius:24px;padding:26px;box-shadow:0 30px 90px #0007}.speed-card .meter{height:13px;border-radius:999px;background:#e8eef5;overflow:hidden;margin:18px 0}.speed-card .meter i{display:block;width:89%;height:100%;background:linear-gradient(90deg,#11a767,#26c6da,#1677ff)}.speed-big{font-size:48px;font-weight:900}.speed-sub{color:var(--muted)}.checks{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}.check{padding:11px 12px;border-radius:11px;background:#f4f8fb;font-size:13px;font-weight:700}.section{padding:72px 0}.section h2{font-size:36px;margin:0 0 9px;letter-spacing:-.025em}.sub{color:var(--muted);font-size:17px;margin:0 0 30px}.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.plan{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 10px 35px rgba(15,35,60,.05);display:flex;flex-direction:column;min-height:330px}.plan.featured{border:2px solid #11a767;transform:translateY(-5px);box-shadow:0 18px 50px #0ca56820}.plan-badge{display:inline-flex;width:max-content;padding:6px 9px;border-radius:999px;background:#e9f8f1;color:#08784b;font-size:11px;font-weight:900;text-transform:uppercase}.plan h3{margin:16px 0 4px;font-size:22px}.speed{font-size:42px;font-weight:900;line-height:1.1}.speed span{font-size:15px;color:var(--muted);font-weight:700}.price{font-size:25px;font-weight:900;margin:14px 0 4px}.price small{font-size:13px;color:var(--muted);font-weight:600}.plan ul{padding-left:18px;color:#4c5968;line-height:1.8;flex:1}.benefits{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.benefit{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px}.benefit .ico{font-size:28px}.benefit h3{margin:12px 0 7px}.benefit p{margin:0;color:var(--muted);line-height:1.55}.cta{background:linear-gradient(135deg,#0b1726,#143b5b);border-radius:24px;color:#fff;padding:36px;display:grid;grid-template-columns:1fr 1fr;gap:32px;align-items:center}.cta h2{color:#fff}.cta p{color:#c9d6e3;line-height:1.6}.form{background:#fff;border-radius:18px;padding:22px;color:var(--ink)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.field label{display:block;font-size:12px;font-weight:800;margin:0 0 6px;color:#536174}.field input,.field select,.field textarea{width:100%;border:1px solid #d8e0e8;border-radius:10px;padding:12px;font:inherit}.field textarea{min-height:92px;resize:vertical}.full{grid-column:1/-1}.notice{padding:12px 14px;border-radius:10px;background:#e8f8f0;color:#087349;font-weight:700;margin-bottom:12px}.footer{background:#07111d;color:#9db0c2;padding:34px 0}.footgrid{display:flex;justify-content:space-between;gap:20px;align-items:center}.footer b{color:#fff}.mobile-login{display:none}.note{font-size:12px;color:#8190a0;margin-top:9px}@media(max-width:900px){.links a:not(.login-link){display:none}.hero-grid,.cta{grid-template-columns:1fr}.plans{grid-template-columns:1fr 1fr}.benefits{grid-template-columns:1fr 1fr}.speed-card{max-width:560px}.plan.featured{transform:none}}@media(max-width:620px){.navin{height:64px}.links{gap:8px}.brand{font-size:17px}.brandmark{width:38px;height:38px}.hero{padding:58px 0}.hero p{font-size:17px}.plans,.benefits,.grid{grid-template-columns:1fr}.full{grid-column:auto}.section{padding:52px 0}.section h2{font-size:30px}.cta{padding:24px}.footgrid{display:block}.footgrid div+div{margin-top:12px}}
'''


def _ensure_table():
    c = appmodule.con()
    c.execute('''CREATE TABLE IF NOT EXISTS sales_leads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        sector TEXT,
        address TEXT,
        plan TEXT,
        status TEXT DEFAULT 'NUEVA',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.commit(); c.close()


def _plans():
    c = appmodule.con()
    rows = c.execute('SELECT id,name,speed,price FROM plans ORDER BY price ASC, id ASC').fetchall()
    c.close()
    return rows


def public_home():
    plans = _plans()
    cards = ''
    if plans:
        for idx, p in enumerate(plans):
            featured = ' featured' if idx == min(1, len(plans)-1) else ''
            badge = '<span class="plan-badge">Más solicitado</span>' if featured else '<span class="plan-badge">Fibra óptica</span>'
            price = f"RD${float(p['price'] or 0):,.0f}" if p['price'] is not None else 'Consultar'
            speed = appmodule.e(p['speed'] or p['name'] or 'Internet')
            name = appmodule.e(p['name'] or 'Plan Internet')
            cards += f'''<article class="plan{featured}">{badge}<h3>{name}</h3><div class="speed">{speed}</div><div class="price">{price} <small>/ mes</small></div><ul><li>Internet ilimitado</li><li>Conexión por fibra óptica</li><li>Soporte técnico</li><li>Router incluido si aplica</li></ul><a class="btn primary choose-plan" href="#solicitud" data-plan="{name}">Solicitar este plan</a></article>'''
    else:
        cards = '''<article class="plan featured"><span class="plan-badge">INTER Flash</span><h3>Planes de fibra</h3><div class="speed">Alta velocidad</div><div class="price">Consulta disponibilidad</div><ul><li>Internet ilimitado</li><li>Fibra óptica</li><li>Soporte técnico</li></ul><a class="btn primary" href="#solicitud">Solicitar instalación</a></article>'''

    plan_options = ''.join(f"<option value='{appmodule.e(p['name'])}'>{appmodule.e(p['name'])} · {appmodule.e(p['speed'])}</option>" for p in plans)
    sent = request.args.get('enviado') == '1'
    notice = '<div class="notice">✅ Solicitud recibida. INTER Flash se pondrá en contacto contigo.</div>' if sent else ''

    html = r'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="INTER Flash - Internet por fibra óptica. Consulta planes y solicita instalación."><title>INTER Flash · Internet por fibra óptica</title><style>{{css}}</style></head><body>
<nav class="nav"><div class="wrap navin"><a class="brand" href="/"><span class="brandmark">IF</span><span>INTER Flash</span></a><div class="links"><a href="#planes">Planes</a><a href="#beneficios">Beneficios</a><a href="#solicitud">Instalación</a><a class="btn ghost login-link" href="{{url_for('login')}}">Portal / Admin</a></div></div></nav>
<header class="hero"><div class="wrap hero-grid"><div><span class="eyebrow">⚡ Fibra óptica INTER Flash</span><h1>Internet rápido para tu hogar y negocio.</h1><p>Navega, trabaja, estudia, juega y disfruta streaming con una conexión estable y planes pensados para tus necesidades.</p><div class="hero-actions"><a class="btn primary" href="#planes">Ver planes</a><a class="btn ghost" href="#solicitud">Solicitar instalación</a></div></div><div class="speed-card"><div class="speed-sub">Tu conexión merece más velocidad</div><div class="speed-big">100% Fibra</div><div class="meter"><i></i></div><div class="checks"><div class="check">✓ Internet ilimitado</div><div class="check">✓ Baja latencia</div><div class="check">✓ Soporte técnico</div><div class="check">✓ Instalación rápida*</div></div><div class="note">*Sujeto a cobertura y disponibilidad técnica.</div></div></div></header>
<main><section class="section" id="planes"><div class="wrap"><h2>Elige tu plan</h2><p class="sub">Planes disponibles actualmente en INTER Flash.</p><div class="plans">{{cards|safe}}</div></div></section>
<section class="section" id="beneficios" style="padding-top:18px"><div class="wrap"><h2>¿Por qué INTER Flash?</h2><p class="sub">Una experiencia de Internet pensada para mantenerte conectado.</p><div class="benefits"><div class="benefit"><div class="ico">⚡</div><h3>Alta velocidad</h3><p>Planes de fibra para navegación, streaming, trabajo y juegos.</p></div><div class="benefit"><div class="ico">♾️</div><h3>Internet ilimitado</h3><p>Disfruta tu servicio sin preocuparte por consumir una cuota de datos.</p></div><div class="benefit"><div class="ico">🛠️</div><h3>Soporte técnico</h3><p>Atención para ayudarte cuando presentes una avería o necesites asistencia.</p></div><div class="benefit"><div class="ico">📡</div><h3>Fibra óptica</h3><p>Tecnología preparada para ofrecer mayor estabilidad y capacidad.</p></div></div></div></section>
<section class="section" id="solicitud"><div class="wrap"><div class="cta"><div><h2>Solicita tu instalación</h2><p>Déjanos tus datos y el plan que te interesa. Revisaremos cobertura y disponibilidad para tu dirección antes de confirmar la instalación.</p><p><b>INTER Flash</b><br>Internet para tu hogar y negocio.</p></div><div class="form">{{notice|safe}}<form method="post" action="{{url_for('sales_request')}}"><div class="grid"><div class="field"><label>Nombre completo</label><input name="name" required></div><div class="field"><label>Teléfono / WhatsApp</label><input name="phone" required></div><div class="field"><label>Sector</label><input name="sector" placeholder="Ej. El Manguito"></div><div class="field"><label>Plan</label><select name="plan"><option value="">Seleccionar plan</option>{{plan_options|safe}}</select></div><div class="field full"><label>Dirección o referencia</label><textarea name="address" placeholder="Calle, número y una referencia cercana"></textarea></div><div class="full"><button class="btn blue" style="width:100%">Enviar solicitud</button></div></div></form></div></div></div></section></main>
<footer class="footer"><div class="wrap footgrid"><div><b>INTER Flash</b><br>Internet por fibra óptica</div><div>© 2026 INTER Flash · Todos los derechos reservados</div></div></footer>
<script>document.querySelectorAll('.choose-plan').forEach(a=>a.addEventListener('click',()=>{const s=document.querySelector('select[name="plan"]');if(s)s.value=a.dataset.plan||'';}));</script></body></html>'''
    return render_template_string(html, css=PUBLIC_CSS, cards=cards, plan_options=plan_options, notice=notice)


def sales_request():
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    if not name or not phone:
        return redirect(url_for('home'))
    c = appmodule.con()
    c.execute('INSERT INTO sales_leads(name,phone,sector,address,plan) VALUES(?,?,?,?,?)', (
        name,
        phone,
        (request.form.get('sector') or '').strip(),
        (request.form.get('address') or '').strip(),
        (request.form.get('plan') or '').strip(),
    ))
    c.commit(); c.close()
    return redirect(url_for('home', enviado=1) + '#solicitud')


def sales_leads():
    if not appmodule.auth():
        return redirect(url_for('login'))
    c = appmodule.con()
    rows = c.execute('SELECT * FROM sales_leads ORDER BY id DESC').fetchall()
    c.close()
    trs = ''.join(f"<tr><td>#{r['id']}</td><td><b>{appmodule.e(r['name'])}</b></td><td>{appmodule.e(r['phone'])}</td><td>{appmodule.e(r['sector']) or '-'}</td><td>{appmodule.e(r['plan']) or '-'}</td><td>{appmodule.e(r['created_at'])}</td><td><span class='tag pending'>{appmodule.e(r['status'])}</span></td></tr>" for r in rows)
    body = f'''<div class="head"><div><h1>Solicitudes de Internet</h1><p>Personas interesadas desde la página pública de INTER Flash</p></div><a class="btn" href="/" target="_blank">Ver página pública</a></div><div class="panel"><table><tr><th>ID</th><th>Cliente</th><th>Teléfono</th><th>Sector</th><th>Plan</th><th>Fecha</th><th>Estado</th></tr>{trs or '<tr><td colspan="7" class="empty">Todavía no hay solicitudes.</td></tr>'}</table></div>'''
    return appmodule.shell('Solicitudes de Internet', body, 'installations')


def setup(flask_app):
    _ensure_table()
    flask_app.view_functions['home'] = public_home
    if 'sales_request' not in flask_app.view_functions:
        flask_app.add_url_rule('/solicitar-instalacion', 'sales_request', sales_request, methods=['POST'])
    if 'sales_leads' not in flask_app.view_functions:
        flask_app.add_url_rule('/solicitudes-internet', 'sales_leads', sales_leads, methods=['GET'])
