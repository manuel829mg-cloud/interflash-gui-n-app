"""Installable app and customer requests; never cache account data offline."""
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import abort, jsonify, redirect, render_template, request, session, url_for
import app as base


def csrf():
    if 'mobile_csrf' not in session:
        session['mobile_csrf'] = secrets.token_urlsafe(32)
    return session['mobile_csrf']


def verify_csrf():
    if not secrets.compare_digest(session.get('mobile_csrf', ''), request.form.get('csrf', '')) or not session.get('mobile_csrf'):
        abort(400, 'La sesión cambió. Recarga la página e inténtalo de nuevo.')


def customer():
    token = session.get('mobile_portal_token')
    c = base.db()
    row = c.execute('SELECT cu.*,pl.name plan_name FROM portal_tokens pt JOIN customers cu ON cu.id=pt.customer_id LEFT JOIN plans pl ON pl.id=cu.plan_id WHERE pt.token=? AND pt.enabled=1', (token,)).fetchone() if token else None
    c.close()
    return row


def home():
    return render_template('mobile/home.html', admin=base.logged_in(), customer=customer())


def portal_entry(token):
    c = base.db()
    valid = c.execute('SELECT 1 FROM portal_tokens WHERE token=? AND enabled=1', (token,)).fetchone()
    c.close()
    if not valid:
        abort(404)
    session['mobile_portal_token'] = token
    session['mobile_csrf'] = secrets.token_urlsafe(32)
    return redirect(url_for('mobile_customer'))


def portal():
    cu = customer()
    if not cu:
        return redirect(url_for('mobile_home'))
    error = None
    if request.method == 'POST':
        verify_csrf()
        kind = request.form.get('kind')
        detail = request.form.get('detail', '').strip()
        amount = None
        if kind not in ('PAGO', 'SOPORTE') or not 5 <= len(detail) <= 2000:
            error = 'Escribe una referencia o descripción de entre 5 y 2000 caracteres.'
        if kind == 'PAGO':
            try:
                amount = Decimal(request.form.get('amount', ''))
                if not amount.is_finite() or amount <= 0 or amount > 1000000 or amount != amount.quantize(Decimal('0.01')):
                    raise ValueError()
            except (InvalidOperation, ValueError):
                error = 'Escribe un monto válido con hasta dos decimales.'
        if not error:
            c = base.db()
            now = datetime.now().isoformat(timespec='seconds')
            c.execute('INSERT INTO mobile_requests(customer_id,kind,amount,detail,created_at) VALUES(?,?,?,?,?)', (cu['id'], kind, str(amount) if amount is not None else None, detail, now))
            if kind == 'SOPORTE':
                c.execute("INSERT INTO support_tickets(customer_id,subject,priority,status,opened_at,notes) VALUES(?,?,'MEDIA','ABIERTO',?,?)", (cu['id'], detail[:120], now, detail))
            c.commit()
            c.close()
            session['mobile_csrf'] = secrets.token_urlsafe(32)
            return redirect(url_for('mobile_customer', sent='1'))
    c = base.db()
    invoices = c.execute('SELECT * FROM invoices WHERE customer_id=? ORDER BY id DESC LIMIT 100', (cu['id'],)).fetchall()
    payments = c.execute('SELECT * FROM payments WHERE customer_id=? ORDER BY id DESC LIMIT 30', (cu['id'],)).fetchall()
    requests = c.execute('SELECT * FROM mobile_requests WHERE customer_id=? ORDER BY id DESC LIMIT 30', (cu['id'],)).fetchall()
    c.close()
    return render_template('mobile/portal.html', customer=cu, invoices=invoices, payments=payments, requests=requests, csrf=csrf(), error=error, sent=request.args.get('sent') == '1')


def requests_page():
    if not base.logged_in():
        return redirect(url_for('login'))
    if session.get('role', 'ADMIN') not in ('ADMIN', 'CAJA'):
        abort(403)
    if request.method == 'POST':
        verify_csrf()
        c = base.db()
        c.execute("UPDATE mobile_requests SET status='REVISADO' WHERE id=?", (request.form.get('id'),))
        c.commit()
        c.close()
        return redirect(url_for('mobile_requests'))
    c = base.db()
    rows = c.execute('SELECT mr.*,cu.name FROM mobile_requests mr JOIN customers cu ON cu.id=mr.customer_id ORDER BY mr.id DESC LIMIT 200').fetchall()
    c.close()
    return render_template('mobile/requests.html', rows=rows, csrf=csrf())


def logout():
    verify_csrf()
    session.pop('mobile_portal_token', None)
    session.pop('mobile_csrf', None)
    return redirect(url_for('mobile_home'))


def setup(app):
    c = base.db()
    c.execute("CREATE TABLE IF NOT EXISTS mobile_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER NOT NULL,kind TEXT NOT NULL,amount TEXT,detail TEXT NOT NULL,status TEXT DEFAULT 'PENDIENTE',created_at TEXT NOT NULL)")
    c.commit()
    c.close()
    app.add_url_rule('/app', 'mobile_home', home)
    app.add_url_rule('/app/cliente', 'mobile_customer', portal, methods=['GET', 'POST'])
    app.add_url_rule('/app/solicitudes', 'mobile_requests', requests_page, methods=['GET', 'POST'])
    app.add_url_rule('/app/salir', 'mobile_logout', logout, methods=['POST'])
    app.view_functions['customer_portal'] = portal_entry
    base.NAV.append(('mobile_requests', '▤', 'Solicitudes de clientes'))
    base.NAV.append(('mobile_home', '▣', 'Aplicación móvil'))

    @app.get('/manifest.webmanifest')
    def mobile_manifest():
        response = jsonify(id='/app', name='INTER Flash', short_name='INTER Flash', lang='es', start_url='/app', scope='/', display='standalone', background_color='#081522', theme_color='#081522', icons=[{'src': f'/static/mobile/icon-{size}.png', 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any maskable'} for size in (192, 512)])
        response.mimetype = 'application/manifest+json'
        return response

    @app.get('/sw.js')
    def mobile_worker():
        response = app.send_static_file('mobile/sw.js')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.after_request
    def mobile_headers(response):
        if response.mimetype == 'text/html' and not response.is_streamed and not response.direct_passthrough:
            html = response.get_data(as_text=True)
            if '<head>' in html:
                html = html.replace('</head>', '<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#081522"><link rel="apple-touch-icon" href="/static/mobile/icon-192.png"><link rel="stylesheet" href="/static/mobile/mobile.css"><script defer src="/static/mobile/mobile.js"></script></head>', 1)
                response.set_data(html)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response
