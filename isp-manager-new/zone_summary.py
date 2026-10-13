"""Read-only zone summaries and bounded invoice/WhatsApp history."""
from flask import request, redirect, url_for, abort
import app as base
from business_suite import esc
from zone_cut_scheduler import _zone_join


def customers(c, zone_id=None):
    clause = ' AND z.id=?' if zone_id is not None else ''
    return c.execute(f'''SELECT cu.id,cu.name,cu.status,z.id zone_id,
        COALESCE((SELECT SUM(MAX(0,i.amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0)))
        FROM invoices i WHERE i.customer_id=cu.id AND i.status='PENDIENTE'),0) balance
        FROM customers cu JOIN zones z ON {_zone_join()}
        WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO'{clause} ORDER BY cu.name''',
        (zone_id,) if zone_id is not None else ()).fetchall()


def totals(c):
    result = {}
    for cu in customers(c):
        row = result.setdefault(cu['zone_id'], {'clients': 0, 'balance': 0, 'suspended': 0, 'debtors': 0})
        row['clients'] += 1
        row['balance'] += cu['balance']
        row['suspended'] += int(cu['status'] == 'SUSPENDIDO')
        row['debtors'] += int(cu['balance'] > 0)
    return result


def page(zone_id):
    if not base.logged_in():
        return redirect(url_for('login'))
    c = base.db()
    try:
        zone = c.execute('SELECT * FROM zones WHERE id=?', (zone_id,)).fetchone()
        if not zone:
            abort(404)
        people = customers(c, zone_id)
        selected = request.args.get('filter', 'all')
        visible = [cu for cu in people if selected == 'all' or (selected == 'debt' and cu['balance'] > 0) or (selected == 'suspended' and cu['status'] == 'SUSPENDIDO')]
        invoices = c.execute(f'''SELECT i.*,cu.name FROM invoices i JOIN customers cu ON cu.id=i.customer_id
            JOIN zones z ON {_zone_join()} WHERE z.id=? ORDER BY i.id DESC LIMIT 50''', (zone_id,)).fetchall()
        notices = c.execute(f'''SELECT o.*,cu.name FROM whatsapp_outbox o JOIN customers cu ON cu.id=o.customer_id
            JOIN zones z ON {_zone_join()} WHERE z.id=? ORDER BY o.id DESC LIMIT 50''', (zone_id,)).fetchall()
    finally:
        c.close()
    root = url_for('zone_summary', zone_id=zone_id)
    balance = sum(cu['balance'] for cu in people)
    suspended = sum(cu['status'] == 'SUSPENDIDO' for cu in people)
    debtors = sum(cu['balance'] > 0 for cu in people)
    customer_rows = ''.join(f'<tr><td><a href="/customers/{cu["id"]}/edit">{esc(cu["name"])}</a></td><td>{esc(cu["status"])}</td><td>RD${cu["balance"]:,.2f}</td></tr>' for cu in visible)
    invoice_rows = ''.join(f'<tr><td><a href="/invoices/{i["id"]}">#{i["id"]}</a></td><td>{esc(i["name"])}</td><td>{esc(i["issue_date"])}</td><td>{esc(i["due_date"])}</td><td>RD${i["amount"]:,.2f}</td><td>{esc(i["status"])}</td></tr>' for i in invoices)
    notice_rows = ''.join(f'<tr><td>{esc(o["name"])}</td><td>{esc(o["template_code"])}</td><td>{esc(o["created_at"])}</td><td>{esc(o["status"])}</td><td>{esc(o["sent_at"] or "—")}</td><td>{esc(o["error"] or "—")}</td></tr>' for o in notices)
    body = f'''<div class="head"><div><h1>Resumen de {esc(zone['name'])}</h1><p>Clientes actuales de la zona y actividad registrada.</p></div><a class="btn" href="/zones">Volver a zonas</a></div>
    <div class="panel"><div style="display:flex;gap:18px;flex-wrap:wrap"><a href="{root}">Clientes: {len(people)}</a><a href="{root}?filter=debt">Con deuda: {debtors}</a><a href="{root}?filter=suspended">Suspendidos: {suspended}</a><b>Saldo pendiente: RD${balance:,.2f}</b></div></div>
    <div class="panel"><h2>Clientes</h2><div style="overflow:auto"><table class="table"><tr><th>Cliente</th><th>Estado</th><th>Saldo pendiente</th></tr>{customer_rows or '<tr><td colspan="3">Sin clientes para este filtro.</td></tr>'}</table></div></div>
    <div class="panel"><h2>Historial de facturas</h2><p>Últimas 50 facturas de los clientes actualmente asignados a esta zona.</p><div style="overflow:auto"><table class="table"><tr><th>Factura</th><th>Cliente</th><th>Emisión</th><th>Vencimiento</th><th>Monto</th><th>Estado</th></tr>{invoice_rows or '<tr><td colspan="6">Sin facturas registradas.</td></tr>'}</table></div></div>
    <div class="panel"><h2>Historial de avisos</h2><p>Últimos 50 avisos automáticos registrados de estos clientes. Un estado de envío no confirma que el cliente haya leído el mensaje.</p><div style="overflow:auto"><table class="table"><tr><th>Cliente</th><th>Tipo</th><th>Creado</th><th>Estado</th><th>Enviado</th><th>Error</th></tr>{notice_rows or '<tr><td colspan="6">Sin avisos registrados.</td></tr>'}</table></div></div>'''
    return base.shell('Resumen de zona', body, 'zones_page')


def setup(app):
    app.add_url_rule('/zones/<int:zone_id>/summary', endpoint='zone_summary', view_func=page)
