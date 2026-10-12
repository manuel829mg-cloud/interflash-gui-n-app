"""Read-only readiness page; intentionally contains no failover executor."""
from datetime import datetime
from html import escape
from flask import abort,redirect,session,url_for
import app as base

COMMANDS = '''/ppp active print detail without-paging where name="prueba de nuevo"
/ip firewall mangle print detail without-paging
/ip firewall filter print detail without-paging where action=fasttrack-connection
/routing table print detail without-paging
/routing rule print detail without-paging
/ip route print detail without-paging where dst-address=0.0.0.0/0
/ip firewall nat print detail without-paging'''

def page():
    if not base.logged_in(): return redirect(url_for('login'))
    if (session.get('role') or 'ADMIN').upper() != 'ADMIN': abort(403)
    c=base.db()
    try:
        rows=c.execute('SELECT name,address,profile FROM push_pppoe_active LEFT JOIN push_pppoe_secrets USING(router_name,name) WHERE router_name=? AND name=?',('CCR2116','prueba de nuevo')).fetchall()
        agent=c.execute('SELECT last_sync FROM push_router_agents WHERE name=?',('CCR2116',)).fetchone()
    finally: c.close()
    esc=lambda v:escape(str(v or ''))
    stamp=agent['last_sync'] if agent else None
    try: fresh=0 <= (datetime.now()-datetime.fromisoformat(stamp)).total_seconds() <= 45
    except (TypeError,ValueError): fresh=False
    if len(rows)==1 and fresh:
        state=f'Sesión sincronizada: {esc(rows[0]["name"])} · IP {esc(rows[0]["address"])} · Perfil {esc(rows[0]["profile"])}.'
    else: state='No hay una única sesión de prueba con sincronización reciente confirmada. No usar una IP histórica.'
    body=f'''<div class="head"><h1>Preparación de prueba de respaldo</h1></div><div class="panel"><p>{state}</p><p>Última sincronización: {esc(stamp or 'Sin datos')}.</p><p><b>Prueba pendiente: no se ha ejecutado ningún cambio.</b> La plataforma no recibe actualmente las reglas mangle, FastTrack y NAT necesarias para preparar una prueba aislada.</p><ol><li>Confirmar sesión e IP del cliente de laboratorio.</li><li>Revisar mangle, FastTrack, NAT, reglas de enrutamiento y rutas.</li><li>Preparar una tabla exclusiva para ese cliente y una restauración automática.</li><li>Presentar los comandos concretos para autorización.</li><li>Probar nuevas conexiones por respaldo y medir el tiempo; después restaurar.</li></ol><p>No se deshabilitan WAN ni rutas de producción. Retirar la principal en la tabla de prueba comprueba selección de respaldo, no la detección de una caída real.</p><h3>Lectura que falta del MikroTik</h3><p>Estos comandos solo muestran datos; no cambian configuración. No incluyen contraseñas PPPoE.</p><pre style="white-space:pre-wrap">{esc(COMMANDS)}</pre></div>'''
    return base.shell('Prueba de respaldo',body,'failover_preflight')

def setup(app):
    app.add_url_rule('/mikrotik/prueba-respaldo',endpoint='failover_preflight',view_func=page)
    base.NAV.append(('failover_preflight','✓','Prueba de respaldo'))
