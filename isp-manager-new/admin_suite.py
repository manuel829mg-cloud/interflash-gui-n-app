import os, re, sqlite3
from datetime import date, datetime
from html import escape
from flask import request, redirect, url_for, flash, session, send_file, Response
from werkzeug.security import generate_password_hash
import app as base


def esc(v):
    return escape('' if v is None else str(v))


def _role():
    r=(session.get('role') or 'ADMIN').upper()
    return 'CAJA' if r=='COBRADOR' else r


def _admin():
    return _role()=='ADMIN'


def ensure_schema():
    c=base.db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS backup_runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      kind TEXT NOT NULL,
      filename TEXT,
      status TEXT DEFAULT 'OK',
      detail TEXT,
      created_at TEXT NOT NULL,
      created_by TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_backup_runs_created ON backup_runs(created_at DESC);
    ''')
    c.commit(); c.close()


def _backup_dir():
    root=os.path.dirname(base.DB_PATH) or '/data'
    path=os.path.join(root,'backups')
    os.makedirs(path,exist_ok=True)
    return path


def _make_db_backup(label='auto'):
    ensure_schema()
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    filename=f'interflash-{label}-{stamp}.db'
    path=os.path.join(_backup_dir(),filename)
    src=sqlite3.connect(base.DB_PATH,timeout=20)
    dst=sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    c=base.db(); c.execute('INSERT INTO backup_runs(kind,filename,status,detail,created_at,created_by) VALUES(?,?,?,?,?,?)',
        ('DATABASE',filename,'OK','Copia SQLite completa',datetime.now().isoformat(timespec='seconds'),session.get('user') or 'AUTOMATICO'))
    c.commit(); c.close()
    # Conservar las 30 copias más recientes.
    files=sorted([x for x in os.listdir(_backup_dir()) if x.endswith('.db')],reverse=True)
    for old in files[30:]:
        try: os.remove(os.path.join(_backup_dir(),old))
        except OSError: pass
    return filename


def _queue_router_backup(source='AUTOMATICO'):
    c=base.db()
    routers=[]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='push_router_agents'").fetchone():
        routers=[r['name'] for r in c.execute('SELECT name FROM push_router_agents ORDER BY id').fetchall() if r['name']]
    if not routers: routers=['CCR2116']
    now=datetime.now().isoformat(timespec='seconds')
    for name in routers:
        c.execute('''INSERT INTO router_commands(router_name,customer_id,pppoe,action,payload,status,created_at,requested_by)
                     VALUES(?,?,?,?,?,?,?,?)''',(name,None,'','BACKUP_ROUTER','{}','PENDIENTE',now,source))
    c.commit(); c.close()
    return len(routers)


def automatic_backup_tick():
    if not base.logged_in(): return None
    try:
        ensure_schema(); today=date.today().isoformat(); c=base.db()
        done=c.execute("SELECT id FROM backup_runs WHERE kind='DATABASE' AND status='OK' AND substr(created_at,1,10)=? LIMIT 1",(today,)).fetchone()
        c.close()
        if not done:
            _make_db_backup('daily')
            c=base.db()
            queued=c.execute("SELECT id FROM router_commands WHERE action='BACKUP_ROUTER' AND substr(created_at,1,10)=? LIMIT 1",(today,)).fetchone()
            c.close()
            if not queued: _queue_router_backup('BACKUP_DIARIO')
    except Exception:
        # El backup nunca debe tumbar la aplicación.
        pass
    return None


def role_guard_plus():
    if not base.logged_in(): return None
    ep=request.endpoint or ''
    role=_role()
    if role=='ADMIN': return None
    admin_only={'users_page','staff_update','staff_toggle','backup_center','backup_run','backup_file','backup_restore','backup_router_now','settings_page','audit_page','customer_trash_restore'}
    if ep in admin_only:
        flash('Solo el administrador puede entrar a esa sección.'); return redirect(url_for('dashboard'))
    if ep=='customer_service_action' and (request.view_args or {}).get('action','').upper()=='DELETE':
        flash('Solo el administrador puede eliminar clientes.'); return redirect(url_for('customers'))
    finance={'payments','invoice_pay','invoices','expenses_page','banks_page','reports_admin','reports_export'}
    if ep in finance and role not in ('CAJA',):
        flash('Tu rol no tiene permiso para finanzas.'); return redirect(url_for('dashboard'))
    network_prefixes=('mikrotik','router_push','pbr_','router_')
    if ep.startswith(network_prefixes) and role not in ('TECNICO',):
        flash('Tu rol no tiene permiso para cambios de red.'); return redirect(url_for('dashboard'))
    if ep in ('customer_new','customer_edit') and role not in ('TECNICO','SOPORTE'):
        flash('Tu rol no tiene permiso para modificar clientes.'); return redirect(url_for('customers'))
    return None


def users_page_plus():
    if not base.logged_in(): return redirect(url_for('login'))
    if not _admin(): return redirect(url_for('dashboard'))
    c=base.db()
    if request.method=='POST':
        username=(request.form.get('username') or '').strip(); password=request.form.get('password') or ''
        role=(request.form.get('role') or 'SOPORTE').upper()
        if role not in ('ADMIN','TECNICO','CAJA','SOPORTE'): role='SOPORTE'
        if not username or len(password)<6:
            c.close(); flash('El usuario es obligatorio y la contraseña debe tener al menos 6 caracteres.'); return redirect(url_for('users_page'))
        try:
            c.execute('INSERT INTO staff_users(username,password_hash,name,role,active) VALUES(?,?,?,?,1)',
                      (username,generate_password_hash(password),request.form.get('name'),role)); c.commit(); flash('Usuario creado.')
        except Exception:
            flash('No se pudo crear. Verifica que el nombre de usuario no exista.')
    rows=c.execute('SELECT * FROM staff_users ORDER BY id DESC').fetchall(); c.close()
    trs=[]
    for r in rows:
        status='<span class="tag ok">ACTIVO</span>' if r['active'] else '<span class="tag bad">INACTIVO</span>'
        trs.append(f'''<tr><td><b>{esc(r['username'])}</b><br><span class="muted">{esc(r['name'] or '-')}</span></td><td>{esc(r['role'])}</td><td>{status}</td><td>{esc(r['last_login'] or '-')}</td><td><form class="toolbar" method="post" action="{url_for('staff_update',id=r['id'])}" style="margin:0"><select class="field" name="role"><option {'selected' if r['role']=='ADMIN' else ''}>ADMIN</option><option {'selected' if r['role']=='TECNICO' else ''}>TECNICO</option><option {'selected' if r['role'] in ('CAJA','COBRADOR') else ''}>CAJA</option><option {'selected' if r['role']=='SOPORTE' else ''}>SOPORTE</option></select><input class="field" type="password" name="password" placeholder="Nueva clave (opcional)"><button class="btn">Guardar</button></form><form method="post" action="{url_for('staff_toggle',id=r['id'])}" style="margin-top:6px"><button class="btn">{'Desactivar' if r['active'] else 'Activar'}</button></form></td></tr>''')
    roles='''<div class="panel"><b>Permisos por rol</b><p class="muted"><b>ADMIN:</b> acceso total y acciones críticas. · <b>TECNICO:</b> clientes, red, MikroTik y ONU. · <b>CAJA:</b> facturas, pagos, gastos y reportes. · <b>SOPORTE:</b> clientes y atención, sin borrar ni tocar configuración crítica.</p></div>'''
    body=f'''<div class="head"><div><h1>Usuarios y permisos</h1><p>Control de acceso por empleado</p></div></div>{roles}<div class="panel"><form class="toolbar" method="post"><input class="field" name="username" placeholder="Usuario" required><input class="field" name="name" placeholder="Nombre"><input class="field" type="password" name="password" placeholder="Contraseña (mínimo 6)" required><select class="field" name="role"><option>ADMIN</option><option>TECNICO</option><option>CAJA</option><option>SOPORTE</option></select><button class="btn green">Crear usuario</button></form><table class="table"><tr><th>Usuario</th><th>Rol</th><th>Estado</th><th>Último acceso</th><th>Acciones</th></tr>{''.join(trs) or '<tr><td colspan=5 class=muted>Sin empleados.</td></tr>'}</table></div>'''
    return base.shell('Usuarios',body,'users_page')


def staff_update(id):
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    role=(request.form.get('role') or 'SOPORTE').upper()
    if role not in ('ADMIN','TECNICO','CAJA','SOPORTE'): role='SOPORTE'
    password=request.form.get('password') or ''
    c=base.db()
    if password:
        if len(password)<6: c.close(); flash('La nueva contraseña debe tener al menos 6 caracteres.'); return redirect(url_for('users_page'))
        c.execute('UPDATE staff_users SET role=?,password_hash=? WHERE id=?',(role,generate_password_hash(password),id))
    else: c.execute('UPDATE staff_users SET role=? WHERE id=?',(role,id))
    c.commit(); c.close(); flash('Usuario actualizado.'); return redirect(url_for('users_page'))


def staff_toggle(id):
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    c=base.db(); r=c.execute('SELECT active FROM staff_users WHERE id=?',(id,)).fetchone()
    if r: c.execute('UPDATE staff_users SET active=? WHERE id=?',(0 if r['active'] else 1,id)); c.commit()
    c.close(); flash('Estado del usuario actualizado.'); return redirect(url_for('users_page'))


def backup_center():
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    ensure_schema(); c=base.db(); runs=c.execute('SELECT * FROM backup_runs ORDER BY id DESC LIMIT 50').fetchall(); router=c.execute("SELECT * FROM router_commands WHERE action='BACKUP_ROUTER' ORDER BY id DESC LIMIT 20").fetchall(); c.close()
    files=[]
    for name in sorted([x for x in os.listdir(_backup_dir()) if x.endswith('.db')],reverse=True):
        p=os.path.join(_backup_dir(),name); files.append((name,os.path.getsize(p)))
    frows=''.join(f'''<tr><td>{esc(n)}</td><td>{size/1024/1024:.2f} MB</td><td><a class="btn" href="{url_for('backup_file',name=n)}">Descargar</a> <form method="post" action="{url_for('backup_restore',name=n)}" style="display:inline" onsubmit="return confirm('¿Restaurar esta copia? La base actual será reemplazada. Se hará una copia previa automáticamente.')"><button class="btn" style="background:#6b1b23">Restaurar</button></form></td></tr>''' for n,size in files)
    rrows=''.join(f'<tr><td>{esc(x["router_name"])}</td><td>{esc(x["status"])}</td><td>{esc(x["created_at"])}</td><td>{esc(x["result"] or "-")}</td></tr>' for x in router)
    body=f'''<div class="head"><div><h1>Copias de seguridad</h1><p>Base de datos diaria y backup del MikroTik</p></div><div><form method="post" action="{url_for('backup_run')}" style="display:inline"><button class="btn green">Crear copia ahora</button></form> <form method="post" action="{url_for('backup_router_now')}" style="display:inline"><button class="btn blue">Backup MikroTik ahora</button></form></div></div><div class="panel"><div class="notice" style="background:#063f2a;color:#b8f6d6"><b>Automático:</b> la plataforma conserva hasta 30 copias de la base. Una vez al día también encola una copia/export del CCR.</div><table class="table"><tr><th>Archivo</th><th>Tamaño</th><th>Acciones</th></tr>{frows or '<tr><td colspan=3 class=muted>Todavía no hay copias.</td></tr>'}</table></div><div class="panel"><h3>Backups MikroTik</h3><p class="muted">El agente guarda <b>interflash-auto.backup</b> y <b>interflash-auto-export.rsc</b> dentro de Files del MikroTik.</p><table class="table"><tr><th>Router</th><th>Estado</th><th>Fecha</th><th>Resultado</th></tr>{rrows or '<tr><td colspan=4 class=muted>Sin órdenes de backup.</td></tr>'}</table></div>'''
    return base.shell('Backups',body,'backup_center')


def backup_run():
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    name=_make_db_backup('manual'); flash('Copia creada: '+name); return redirect(url_for('backup_center'))


def backup_file(name):
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    safe=os.path.basename(name); path=os.path.join(_backup_dir(),safe)
    if not os.path.isfile(path): flash('Copia no encontrada.'); return redirect(url_for('backup_center'))
    return send_file(path,as_attachment=True,download_name=safe)


def backup_restore(name):
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    safe=os.path.basename(name); path=os.path.join(_backup_dir(),safe)
    if not os.path.isfile(path): flash('Copia no encontrada.'); return redirect(url_for('backup_center'))
    _make_db_backup('pre-restore')
    src=sqlite3.connect(path,timeout=20); dst=sqlite3.connect(base.DB_PATH,timeout=20)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    try: base.audit('DATABASE_RESTORE',safe)
    except Exception: pass
    flash('Base de datos restaurada desde '+safe+'.'); return redirect(url_for('backup_center'))


def backup_router_now():
    if not base.logged_in() or not _admin(): return redirect(url_for('dashboard'))
    n=_queue_router_backup(session.get('user') or base.ADMIN_USER); flash(f'Backup enviado a {n} router(es).'); return redirect(url_for('backup_center'))


def _report_data(month):
    if not re.match(r'^\d{4}-\d{2}$',month or ''): month=date.today().strftime('%Y-%m')
    c=base.db()
    income=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE substr(paid_at,1,7)=?",(month,)).fetchone()['s'] or 0)
    expenses=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE substr(paid_at,1,7)=?",(month,)).fetchone()['s'] or 0)
    billed=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM invoices WHERE substr(issue_date,1,7)=?",(month,)).fetchone()['s'] or 0)
    outstanding=float(c.execute("SELECT COALESCE(SUM(amount),0) s FROM invoices WHERE status='PENDIENTE'").fetchone()['s'] or 0)
    overdue=c.execute("SELECT COUNT(*) c,COALESCE(SUM(amount),0) s FROM invoices WHERE status='PENDIENTE' AND due_date<?",(date.today().isoformat(),)).fetchone()
    new_clients=int(c.execute("SELECT COUNT(*) c FROM customers WHERE substr(created_at,1,7)=?",(month,)).fetchone()['c'] or 0)
    methods=c.execute("SELECT COALESCE(method,'SIN METODO') label,COUNT(*) qty,COALESCE(SUM(amount),0) total FROM payments WHERE substr(paid_at,1,7)=? GROUP BY method ORDER BY total DESC",(month,)).fetchall()
    plans=c.execute("SELECT COALESCE(p.name,'Sin plan') label,COUNT(*) qty FROM customers cu LEFT JOIN plans p ON p.id=cu.plan_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' GROUP BY p.name ORDER BY qty DESC").fetchall()
    zones=c.execute("SELECT COALESCE(NULLIF(z.name,''),NULLIF(cu.zone,''),'Sin zona') label,COUNT(*) qty FROM customers cu LEFT JOIN zones z ON z.id=cu.zone_id WHERE COALESCE(cu.status,'ACTIVO')<>'ELIMINADO' GROUP BY label ORDER BY qty DESC LIMIT 15").fetchall()
    monthly=c.execute("SELECT substr(paid_at,1,7) m,COALESCE(SUM(amount),0) total FROM payments WHERE paid_at IS NOT NULL GROUP BY substr(paid_at,1,7) ORDER BY m DESC LIMIT 12").fetchall()
    c.close()
    return {'month':month,'income':income,'expenses':expenses,'billed':billed,'outstanding':outstanding,'overdue_count':int(overdue['c'] or 0),'overdue_total':float(overdue['s'] or 0),'new_clients':new_clients,'methods':methods,'plans':plans,'zones':zones,'monthly':monthly,'profit':income-expenses}


def reports_admin():
    if not base.logged_in(): return redirect(url_for('login'))
    if _role() not in ('ADMIN','CAJA'): return redirect(url_for('dashboard'))
    month=request.args.get('month') or date.today().strftime('%Y-%m'); d=_report_data(month)
    methods=''.join(f'<tr><td>{esc(x["label"])}</td><td>{x["qty"]}</td><td>RD${float(x["total"] or 0):,.2f}</td></tr>' for x in d['methods'])
    plans=''.join(f'<tr><td>{esc(x["label"])}</td><td>{x["qty"]}</td></tr>' for x in d['plans'])
    zones=''.join(f'<tr><td>{esc(x["label"])}</td><td>{x["qty"]}</td></tr>' for x in d['zones'])
    monthly=''.join(f'<tr><td>{esc(x["m"])}</td><td>RD${float(x["total"] or 0):,.2f}</td></tr>' for x in d['monthly'])
    cards=f'''<div class="grid6"><div class="kpi green1"><div class="label">Ingresos</div><div class="value">RD${d['income']:,.0f}</div><div class="sub">Mes seleccionado</div></div><div class="kpi red1"><div class="label">Gastos</div><div class="value">RD${d['expenses']:,.0f}</div><div class="sub">Egresos</div></div><div class="kpi blue1"><div class="label">Resultado</div><div class="value">RD${d['profit']:,.0f}</div><div class="sub">Ingresos - gastos</div></div><div class="kpi purple1"><div class="label">Facturado</div><div class="value">RD${d['billed']:,.0f}</div><div class="sub">Facturas emitidas</div></div><div class="kpi orange1"><div class="label">Por cobrar</div><div class="value">RD${d['outstanding']:,.0f}</div><div class="sub">Pendiente total</div></div><div class="kpi cyan1"><div class="label">Clientes nuevos</div><div class="value">{d['new_clients']}</div><div class="sub">Mes</div></div></div>'''
    body=f'''<style>@media print{{.side,.top,.head form,.noprint{{display:none!important}}.app{{display:block}}.content{{padding:0}}}}</style><div class="head"><div><h1>Reportes financieros</h1><p>Ingresos, gastos, deuda, planes y zonas</p></div><div class="noprint"><a class="btn" href="{url_for('reports_export',month=d['month'])}">Exportar Excel</a> <button class="btn" onclick="window.print()">Imprimir / PDF</button></div></div><form class="toolbar noprint"><input class="field" type="month" name="month" value="{d['month']}"><button class="btn blue">Ver mes</button></form>{cards}<div class="panel"><div class="notice" style="background:#4e3707;color:#fff"><b>Morosidad:</b> {d['overdue_count']} facturas vencidas · RD${d['overdue_total']:,.2f}</div></div><div class="cards2"><div class="panel"><h3>Pagos por método</h3><table class="table"><tr><th>Método</th><th>Cantidad</th><th>Total</th></tr>{methods or '<tr><td colspan=3>Sin pagos</td></tr>'}</table></div><div class="panel"><h3>Últimos 12 meses</h3><table class="table"><tr><th>Mes</th><th>Ingresos</th></tr>{monthly}</table></div></div><div class="cards2"><div class="panel"><h3>Clientes por plan</h3><table class="table"><tr><th>Plan</th><th>Clientes</th></tr>{plans}</table></div><div class="panel"><h3>Clientes por zona</h3><table class="table"><tr><th>Zona</th><th>Clientes</th></tr>{zones}</table></div></div>'''
    return base.shell('Reportes',body,'reports_admin')


def reports_export():
    if not base.logged_in() or _role() not in ('ADMIN','CAJA'): return redirect(url_for('dashboard'))
    month=request.args.get('month') or date.today().strftime('%Y-%m'); d=_report_data(month)
    rows=[('Mes',d['month']),('Ingresos',d['income']),('Gastos',d['expenses']),('Resultado',d['profit']),('Facturado',d['billed']),('Por cobrar total',d['outstanding']),('Morosidad',d['overdue_total']),('Clientes nuevos',d['new_clients'])]
    html='''<html><head><meta charset="utf-8"></head><body><table border="1"><tr><th>Indicador</th><th>Valor</th></tr>'''+''.join(f'<tr><td>{esc(a)}</td><td>{b}</td></tr>' for a,b in rows)+'''</table><br><table border="1"><tr><th>Método</th><th>Cantidad</th><th>Total</th></tr>'''+''.join(f'<tr><td>{esc(x["label"])}</td><td>{x["qty"]}</td><td>{x["total"]}</td></tr>' for x in d['methods'])+'</table></body></html>'
    return Response(html,mimetype='application/vnd.ms-excel',headers={'Content-Disposition':f'attachment; filename="reporte-interflash-{d["month"]}.xls"'})


def setup(app):
    ensure_schema()
    # Reemplaza la pantalla sencilla de usuarios por la versión con roles editables.
    app.view_functions['users_page']=users_page_plus
    for item in [('reports_admin','▥','Reportes'),('backup_center','⛁','Backups')]:
        if item[0] not in {x[0] for x in base.NAV}: base.NAV.append(item)
    app.before_request(role_guard_plus)
    app.before_request(automatic_backup_tick)
    app.add_url_rule('/users/<int:id>/update',endpoint='staff_update',view_func=staff_update,methods=['POST'])
    app.add_url_rule('/users/<int:id>/toggle',endpoint='staff_toggle',view_func=staff_toggle,methods=['POST'])
    app.add_url_rule('/backups',endpoint='backup_center',view_func=backup_center,methods=['GET'])
    app.add_url_rule('/backups/run',endpoint='backup_run',view_func=backup_run,methods=['POST'])
    app.add_url_rule('/backups/file/<name>',endpoint='backup_file',view_func=backup_file,methods=['GET'])
    app.add_url_rule('/backups/restore/<name>',endpoint='backup_restore',view_func=backup_restore,methods=['POST'])
    app.add_url_rule('/backups/router',endpoint='backup_router_now',view_func=backup_router_now,methods=['POST'])
    app.add_url_rule('/reports',endpoint='reports_admin',view_func=reports_admin,methods=['GET'])
    app.add_url_rule('/reports/export',endpoint='reports_export',view_func=reports_export,methods=['GET'])
