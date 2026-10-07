"""Operational visibility and daily maintenance independent of page visits."""
import os
import threading
from datetime import date, datetime
from html import escape
from flask import redirect, url_for, session
import app as base
import business_suite as bs
import admin_suite
import zone_cut_scheduler as zones

_started = False


def ensure_schema():
    c = base.db()
    c.execute('''CREATE TABLE IF NOT EXISTS maintenance_runs(
        task TEXT PRIMARY KEY, status TEXT, detail TEXT, updated_at TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS notice_events(event_key TEXT PRIMARY KEY,created_at TEXT)')
    c.commit(); c.close()


def _result(task, status, detail):
    c = base.db()
    c.execute('''INSERT INTO maintenance_runs VALUES(?,?,?,?) ON CONFLICT(task)
                 DO UPDATE SET status=excluded.status,detail=excluded.detail,updated_at=excluded.updated_at''',
              (task,status,str(detail)[:500],datetime.now().isoformat(timespec='seconds')))
    c.commit(); c.close()


def prepare_due_notices():
    """Queue today's reminders once; delivery remains with the configured sender."""
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        enabled = c.execute("SELECT value FROM app_settings WHERE key='whatsapp_enabled'").fetchone()
        if not enabled or enabled[0] != '1':
            return 0
        today = date.today().isoformat()
        rows = c.execute("""SELECT i.id, i.amount, i.customer_id, cu.name, cu.phone,
                     COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=i.id),0) paid
                     FROM invoices i JOIN customers cu ON cu.id=i.customer_id
                     WHERE i.status='PENDIENTE' AND i.due_date=?
                       AND COALESCE(cu.status,'ACTIVO')<>'ELIMINADO'
                       AND COALESCE(TRIM(cu.phone),'')<>''""", (today,)).fetchall()
        count = 0
        for row in rows:
            balance = float(row['amount']) - float(row['paid'])
            if balance <= 0:
                continue
            key = f"DUE:{row['id']}:{today}"
            now = datetime.now().isoformat(timespec='seconds')
            if not c.execute('INSERT OR IGNORE INTO notice_events VALUES(?,?)',(key,now)).rowcount:
                continue
            message = f"Hola {row['name']}, tu factura de INTER Flash vence hoy. Balance pendiente: RD${balance:,.2f}. Si ya pagaste, envíanos tu comprobante."
            c.execute("INSERT INTO whatsapp_outbox(customer_id,phone,template_code,message,status,created_at) VALUES(?,?,'DUE',?,'PENDIENTE',?)", (row['customer_id'],row['phone'],message,now))
            count += 1
        c.commit()
        return count
    finally:
        c.close()


def maintenance_tick():
    # An OS lock serializes workers sharing the same persistent SQLite volume.
    import fcntl
    lock_path = os.path.join(os.path.dirname(base.DB_PATH), 'maintenance.lock')
    with open(lock_path, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        today = date.today().isoformat()
        for task in ('Respaldo diario', 'Facturación diaria'):
            try:
                c = base.db()
                if task == 'Respaldo diario':
                    done = c.execute("SELECT filename FROM backup_runs WHERE kind='DATABASE' AND status='OK' AND substr(created_at,1,10)=? ORDER BY id DESC LIMIT 1", (today,)).fetchone()
                    c.close()
                    if not done or not os.path.isfile(os.path.join(admin_suite._backup_dir(),done['filename'])):
                        name = admin_suite._make_db_backup('daily')
                        _result(task, 'OK', name)
                    c = base.db()
                    queued = c.execute("SELECT 1 FROM router_commands WHERE action='BACKUP_ROUTER' AND substr(created_at,1,10)=? LIMIT 1", (today,)).fetchone()
                    c.close()
                    if not queued:
                        admin_suite._queue_router_backup('BACKUP_DIARIO')
                else:
                    done = c.execute("SELECT 1 FROM billing_runs WHERE run_date=? AND status='OK' LIMIT 1", (today,)).fetchone()
                    c.close()
                    if bs.setting('billing_enabled','1') != '1' or done:
                        continue
                    counts = bs.run_billing()
                    _result(task, 'OK', f'Facturas: {counts[0]}; morosos: {counts[1]}; órdenes: {counts[2]}')
            except Exception as exc:
                _result(task, 'ERROR', str(exc))
        try:
            count = prepare_due_notices()
            _result('Avisos de vencimiento', 'OK', f'{count} avisos nuevos en cola; envío según proveedor configurado')
        except Exception as exc:
            _result('Avisos de vencimiento', 'ERROR', str(exc))
        _result('Monitor de tareas', 'OK', 'Revisión automática cada 5 minutos')


def worker():
    import time
    time.sleep(20)
    while True:
        try:
            maintenance_tick()
        except Exception as exc:
            print('INTERFLASH_MAINTENANCE_ERROR=' + str(exc)[:300], flush=True)
        time.sleep(300)


def page():
    if not base.logged_in():
        return redirect(url_for('login'))
    if (session.get('role') or 'ADMIN').upper() != 'ADMIN':
        return 'Solo el administrador puede revisar las automatizaciones.', 403
    c = base.db()
    try:
        settings = dict(c.execute('SELECT key,value FROM app_settings').fetchall())
        runs = c.execute('SELECT * FROM maintenance_runs ORDER BY task').fetchall()
        invoices = c.execute('SELECT * FROM billing_runs ORDER BY id DESC LIMIT 10').fetchall()
        backups = c.execute('SELECT * FROM backup_runs ORDER BY id DESC LIMIT 5').fetchall()
        commands = c.execute('SELECT status,COUNT(*) n FROM router_commands GROUP BY status').fetchall()
        messages = c.execute('SELECT status,COUNT(*) n FROM whatsapp_outbox GROUP BY status').fetchall()
    finally:
        c.close()
    preview = zones.process_zone_cuts(dry_run=True)
    esc = lambda x: escape(str(x if x is not None else ''))
    cards = ''.join(f'<div class="panel"><b>{label}</b><p>{"ACTIVA" if settings.get(key)=="1" else "DESACTIVADA"}</p></div>' for key,label in [('billing_enabled','Facturación'),('auto_suspend','Corte por zona'),('auto_reactivate','Reactivación al pagar'),('whatsapp_enabled','Avisos por WhatsApp')])
    def rows(items, keys):
        return ''.join('<tr>'+''.join('<td>'+esc(r[k])+'</td>' for k in keys)+'</tr>' for r in items) or '<tr><td colspan="5">Sin registros todavía.</td></tr>'
    body = f'''<div class="head"><div><h1>Estado de automatizaciones</h1><p>Facturación, cortes, pagos, mensajes y copias de seguridad</p></div><a class="btn" href="{url_for('settings_page')}">Configuración</a></div>
    <div class="cards2">{cards}</div>
    <div class="panel"><h3>Simulación de cortes · {len(preview)} clientes</h3><p>Consulta de solo lectura. No ejecuta cortes. Respeta la zona, fecha, hora y promesas vigentes. Si el corte automático está desactivado, esta lista es solo una previsión.</p>
    <table class="table"><tr><th>Cliente</th><th>Zona</th><th>Factura vencida</th><th>Corte desde</th></tr>{rows(preview,['customer_name','zone_name','oldest_due','scheduled_at'])}</table></div>
    <div class="panel"><h3>Tareas automáticas</h3><table class="table"><tr><th>Tarea</th><th>Estado</th><th>Detalle</th><th>Última revisión</th></tr>{rows(runs,['task','status','detail','updated_at'])}</table></div>
    <div class="cards2"><div class="panel"><h3>Órdenes MikroTik</h3><table class="table">{rows(commands,['status','n'])}</table><a class="btn" href="{url_for('mikrotik_commands')}">Ver cola</a></div>
    <div class="panel"><h3>Avisos por WhatsApp</h3><p>Los avisos se preparan el día del vencimiento. PENDIENTE significa en cola, pendiente del emisor configurado; ENVIADO indica que el proveedor aceptó el envío, no confirma lectura.</p><table class="table">{rows(messages,['status','n'])}</table></div></div>
    <div class="panel"><h3>Últimas facturaciones</h3><table class="table"><tr><th>Fecha</th><th>Estado</th><th>Resultado</th></tr>{rows(invoices,['created_at','status','detail'])}</table></div>
    <div class="panel"><h3>Copias de seguridad</h3><p>Copia diaria de la base con verificación de integridad y hasta 30 archivos conservados. Descarga una copia para guardarla fuera del servidor.</p><table class="table"><tr><th>Fecha</th><th>Estado</th><th>Archivo</th></tr>{rows(backups,['created_at','status','filename'])}</table><a class="btn" href="{url_for('backup_center')}">Abrir respaldos</a></div>'''
    return base.shell('Estado de automatizaciones', body, 'operations_health')


def setup(app):
    global _started
    ensure_schema()
    app.add_url_rule('/operations/health',endpoint='operations_health',view_func=page)
    if not any(x[0]=='operations_health' for x in base.NAV):
        base.NAV.append(('operations_health','✓','Estado de automatizaciones'))
    if not _started and os.getenv('INTERFLASH_TESTING') != '1':
        _started = True
        threading.Thread(target=worker, name='interflash-maintenance', daemon=True).start()
