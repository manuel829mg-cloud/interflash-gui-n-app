import json
from datetime import datetime
from html import escape
from flask import request, redirect, url_for, flash, session
import app as base


def queue_customer_command(id,action):
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); cu=c.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
    if not cu or not cu['pppoe']:
        c.close(); flash('El cliente no tiene usuario PPPoE.'); return redirect(url_for('customer_profile',id=id))
    action=action.upper(); allowed={'SUSPEND','REACTIVATE','CHANGE_PROFILE','CHANGE_PASSWORD','DELETE_PPPOE'}
    if action not in allowed:
        c.close(); flash('Acción no permitida.'); return redirect(url_for('customer_profile',id=id))
    payload={}
    if action=='CHANGE_PROFILE': payload={'profile':request.form.get('profile','')}
    if action=='CHANGE_PASSWORD': payload={'password':request.form.get('password','')}
    c.execute('INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by) VALUES(?,?,?,?,?,?,?,?)',(cu['router_name'] or 'CCR2116',id,cu['pppoe'],action,json.dumps(payload,ensure_ascii=False),'PENDIENTE',datetime.now().isoformat(timespec='seconds'),session.get('user') or base.ADMIN_USER)); c.commit(); c.close(); flash('Orden guardada en la cola. Aún no se ejecuta en el MikroTik.'); return redirect(url_for('customer_profile',id=id))


def clear_pending_commands():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db()
    cur=c.execute("UPDATE router_commands SET status='CANCELADO' WHERE status IN ('PENDIENTE','EN_PROCESO')")
    n=cur.rowcount
    c.commit(); c.close()
    flash(f'{n} orden(es) pendientes/en proceso fueron canceladas. No se ejecutarán en el MikroTik.')
    return redirect(url_for('mikrotik_commands'))


def commands_page():
    if not base.logged_in(): return redirect(url_for('login'))
    c=base.db(); rows=c.execute('''SELECT rc.*,cu.name customer FROM router_commands rc LEFT JOIN customers cu ON cu.id=rc.customer_id ORDER BY rc.id DESC LIMIT 200''').fetchall(); c.close(); trs=[]
    for r in rows:
        cls='ok' if r['status']=='COMPLETADO' else 'bad' if r['status'] in ('ERROR','CANCELADO') else 'warn'; trs.append(f'''<tr><td>#{r['id']}</td><td>{escape(r['customer'] or '-')}</td><td>{escape(r['pppoe'] or '-')}</td><td>{escape(r['action'])}</td><td><span class="tag {cls}">{escape(r['status'])}</span></td><td>{escape(r['created_at'] or '-')}</td></tr>''')
    body=f'''<div class="head"><div><h1>Cola MikroTik</h1><p>Órdenes preparadas desde la plataforma</p></div><form method="post" action="{url_for('mikrotik_commands_clear')}" onsubmit="return confirm('¿Cancelar todas las órdenes PENDIENTES y EN PROCESO? No se ejecutarán en el MikroTik.');"><button class="btn" type="submit" style="background:#b42318;color:#fff">Limpiar órdenes pendientes</button></form></div><div class="panel"><div class="notice" style="background:#4e3707;color:#fff">Las órdenes pendientes esperan al agente del CCR2116. Usa “Limpiar órdenes pendientes” antes de reinstalar el agente si hay órdenes viejas que no deseas ejecutar.</div><table class="table"><tr><th>#</th><th>Cliente</th><th>PPPoE</th><th>Acción</th><th>Estado</th><th>Fecha</th></tr>{''.join(trs) or '<tr><td colspan=6 class=muted>Sin órdenes.</td></tr>'}</table></div>'''; return base.shell('Cola MikroTik',body,'routers')


def setup(app):
    if not any(x[0]=='mikrotik_commands' for x in base.NAV): base.NAV.append(('mikrotik_commands','⚡','Cola MikroTik'))
    app.add_url_rule('/customers/<int:id>/command/<action>',endpoint='queue_customer_command',view_func=queue_customer_command,methods=['POST'])
    app.add_url_rule('/mikrotik/commands',endpoint='mikrotik_commands',view_func=commands_page,methods=['GET'])
    app.add_url_rule('/mikrotik/commands/clear',endpoint='mikrotik_commands_clear',view_func=clear_pending_commands,methods=['POST'])
