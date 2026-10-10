import calendar
import threading
import time as time_module
from datetime import date, datetime, time, timedelta

import app as base
import business_suite as bs

_started = False


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _columns(c, table):
    try:
        return {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
    except Exception:
        return set()


def ensure_zone_schema():
    """Add the zone fields required by the current billing/cut engine.

    Some production databases were created by older INTER Flash builds. SQLite's
    CREATE TABLE IF NOT EXISTS does not add new columns to an existing table, so
    we migrate the live table additively here before the scheduler starts.
    """
    c = base.db()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS zones(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            billing_day INTEGER DEFAULT 30,
            invoice_days_before INTEGER DEFAULT 5,
            cut_days_after INTEGER DEFAULT 6,
            cut_time TEXT DEFAULT '14:00',
            active INTEGER DEFAULT 1
        )''')
        cols = _columns(c, 'zones')
        additions = [
            ('billing_day', 'INTEGER DEFAULT 30'),
            ('invoice_days_before', 'INTEGER DEFAULT 5'),
            ('cut_days_after', 'INTEGER DEFAULT 6'),
            ('cut_time', "TEXT DEFAULT '14:00'"),
            ('active', 'INTEGER DEFAULT 1'),
            ('whatsapp_reminder_enabled', 'INTEGER NOT NULL DEFAULT 0'),
            ('whatsapp_reminder_days', 'INTEGER NOT NULL DEFAULT 2'),
        ]
        for name, ddl in additions:
            if name not in cols:
                c.execute(f'ALTER TABLE zones ADD COLUMN {name} {ddl}')
                cols.add(name)

        # Preserve values from a few older column names when they exist.
        legacy_map = {
            'billing_day': ('due_day', 'billing_date_day', 'day'),
            'invoice_days_before': ('invoice_before', 'invoice_days', 'days_before'),
            'cut_days_after': ('cut_after', 'cut_days', 'suspension_days', 'days_after'),
            'cut_time': ('suspension_time', 'cut_hour', 'hour'),
        }
        all_cols = _columns(c, 'zones')
        for target, candidates in legacy_map.items():
            legacy = next((x for x in candidates if x in all_cols), None)
            if not legacy:
                continue
            if target == 'cut_time':
                c.execute(
                    f"UPDATE zones SET {target}=CAST({legacy} AS TEXT) "
                    f"WHERE ({target} IS NULL OR TRIM({target})='' OR {target}='14:00') "
                    f"AND {legacy} IS NOT NULL AND TRIM(CAST({legacy} AS TEXT))<>''"
                )
            else:
                default = 30 if target == 'billing_day' else 5 if target == 'invoice_days_before' else 6
                c.execute(
                    f"UPDATE zones SET {target}=CAST({legacy} AS INTEGER) "
                    f"WHERE ({target} IS NULL OR {target}=?) AND {legacy} IS NOT NULL",
                    (default,),
                )

        c.commit()
        print('INTERFLASH_ZONE_SCHEMA_READY=' + ','.join(sorted(_columns(c, 'zones'))), flush=True)
    finally:
        c.close()


def _parse_cut_time(value):
    try:
        text = str(value or '14:00').strip()
        # Normal current format is 24-hour HH:MM. Also accept a legacy AM/PM value.
        upper = text.upper()
        if upper.endswith(' AM') or upper.endswith(' PM'):
            return datetime.strptime(upper, '%I:%M %p').time()
        parts = text.split(':')
        hour = max(0, min(int(parts[0]), 23))
        minute = max(0, min(int(parts[1]), 59))
        return time(hour, minute)
    except Exception:
        return time(14, 0)


def _zone_join():
    # New customers normally use zone_id. The name fallback keeps older
    # customers that were saved with only the legacy text zone working too.
    return """(
        z.id = cu.zone_id
        OR (
            cu.zone_id IS NULL
            AND COALESCE(TRIM(cu.zone),'') <> ''
            AND LOWER(TRIM(z.name)) = LOWER(TRIM(cu.zone))
        )
    )"""


def process_zone_cuts(now=None, dry_run=False):
    """Queue SUSPEND only when the configured zone cut date AND time have arrived."""
    if not dry_run and bs.setting('auto_suspend', '0') != '1':
        return 0

    now = now or datetime.now()
    c = base.db()
    try:
        if not _table_exists(c, 'zones') or not _table_exists(c, 'router_commands'):
            return [] if dry_run else 0

        if not dry_run:
            c.execute('BEGIN IMMEDIATE')
        rows = c.execute(f'''SELECT
                cu.id customer_id,
                cu.name customer_name,
                cu.pppoe,
                cu.router_name,
                cu.status customer_status,
                z.id zone_id,
                z.name zone_name,
                z.cut_days_after,
                z.cut_time,
                MIN(i.due_date) oldest_due
            FROM customers cu
            JOIN zones z ON {_zone_join()}
            JOIN invoices i ON i.customer_id=cu.id AND i.status='PENDIENTE'
            WHERE COALESCE(z.active,1)=1
              AND COALESCE(cu.status,'ACTIVO') NOT IN ('SUSPENDIDO','ELIMINADO')
              AND COALESCE(TRIM(cu.pppoe),'') <> ''
            GROUP BY cu.id,cu.name,cu.pppoe,cu.router_name,cu.status,
                     z.id,z.name,z.cut_days_after,z.cut_time''').fetchall()

        queued = 0
        preview = []
        retry_after = (now - timedelta(minutes=10)).isoformat(timespec='seconds')

        for row in rows:
            try:
                oldest_due = date.fromisoformat(str(row['oldest_due']))
            except Exception:
                continue

            try:
                cut_days = max(0, int(row['cut_days_after'] if row['cut_days_after'] is not None else 6))
            except Exception:
                cut_days = 6

            cut_date = oldest_due + timedelta(days=cut_days)
            scheduled_at = datetime.combine(cut_date, _parse_cut_time(row['cut_time']))
            if now < scheduled_at:
                continue

            promise = c.execute("""SELECT 1 FROM payment_promises WHERE customer_id=? AND status='PENDIENTE' AND (promise_date>? OR (promise_date=? AND COALESCE(promise_time,'23:59')>?)) LIMIT 1""", (row['customer_id'], now.date().isoformat(), now.date().isoformat(), now.strftime('%H:%M'))).fetchone()
            if promise:
                continue
            if dry_run:
                preview.append(dict(row, scheduled_at=scheduled_at.isoformat(timespec='minutes')))
                continue

            # Never stack duplicate suspension commands. If a previous attempt
            # failed, allow a retry after ten minutes rather than flooding the queue.
            recent = c.execute('''SELECT id FROM router_commands
                                  WHERE customer_id=? AND action='SUSPEND'
                                    AND (status IN ('PENDIENTE','EN_PROCESO') OR created_at>=?)
                                  ORDER BY id DESC LIMIT 1''',
                               (row['customer_id'], retry_after)).fetchone()
            if recent:
                continue

            c.execute('''INSERT INTO router_commands(
                           router_name,customer_id,pppoe,action,payload,status,
                           created_at,requested_by
                         ) VALUES(?,?,?,?,?,?,?,?)''', (
                row['router_name'] or 'CCR2116',
                row['customer_id'],
                row['pppoe'],
                'SUSPEND',
                '{}',
                'PENDIENTE',
                now.isoformat(timespec='seconds'),
                'ZONA:' + str(row['zone_name'] or row['zone_id']),
            ))
            queued += 1
            c.execute('INSERT INTO audit_log(action,detail,created_at) VALUES(?,?,?)', ('ZONE_AUTO_SUSPEND', f"Cliente #{row['customer_id']} · zona {row['zone_name']}", now.isoformat(timespec='seconds')))

        c.commit()
        return preview if dry_run else queued
    finally:
        c.close()


def run_billing():
    """Billing runner compatible with the old function, but zone-time aware."""
    if bs.setting('billing_enabled', '1') != '1':
        return 0, 0, 0
    today = date.today()
    period = today.strftime('%Y-%m')
    c = base.db()
    created = 0
    overdue_customers = 0

    try:
        c.execute('BEGIN IMMEDIATE')
        rows = c.execute(f'''SELECT
                cu.*,
                p.price plan_price,
                z.id effective_zone_id,
                z.name effective_zone_name,
                z.billing_day zone_billing_day,
                z.invoice_days_before,
                z.cut_days_after,
                z.cut_time
            FROM customers cu
            LEFT JOIN plans p ON p.id=cu.plan_id
            LEFT JOIN zones z ON {_zone_join()}
            WHERE cu.plan_id IS NOT NULL
              AND COALESCE(cu.status,'ACTIVO') <> 'ELIMINADO'
              AND (z.id IS NULL OR COALESCE(z.active,1)=1) ''').fetchall()

        last_day = calendar.monthrange(today.year, today.month)[1]

        for cu in rows:
            # Include next month's cycle when its issue date falls this month.
            next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            for cycle in (today.replace(day=1), next_month):
                period = cycle.strftime('%Y-%m')
                last_day = calendar.monthrange(cycle.year, cycle.month)[1]
                due_source = cu['zone_billing_day'] if cu['zone_billing_day'] is not None else cu['due_day']
                try:
                    due_day = max(1, min(int(due_source or 30), last_day))
                except Exception:
                    due_day = min(30, last_day)

                due = date(cycle.year, cycle.month, due_day)
                try:
                    before = max(0, int(cu['invoice_days_before'] if cu['invoice_days_before'] is not None else 5))
                except Exception:
                    before = 5
                issue = due - timedelta(days=before)

                if today >= issue and not c.execute(
                    'SELECT id FROM invoices WHERE customer_id=? AND period=?',
                    (cu['id'], period)
                ).fetchone():
                    c.execute('''INSERT INTO invoices(
                                   customer_id,concept,amount,issue_date,due_date,status,period,generated_by
                                 ) VALUES(?,?,?,?,?,?,?,?)''', (
                        cu['id'],
                        'Servicio de Internet ' + period,
                        float(cu['plan_price'] or 0),
                        today.isoformat(),
                        due.isoformat(),
                        'PENDIENTE',
                        period,
                        'AUTOMATICO',
                    ))
                    created += 1

                    if bs.setting('whatsapp_enabled', '0') == '1' and cu['phone']:
                        t = c.execute("SELECT body FROM whatsapp_templates WHERE code='INVOICE' AND active=1").fetchone()
                        if t:
                            msg = t['body'].format(
                                name=cu['name'],
                                amount='RD${:,.2f}'.format(float(cu['plan_price'] or 0)),
                                due_date=due.isoformat(),
                            )
                            c.execute('''INSERT INTO whatsapp_outbox(
                                           customer_id,phone,template_code,message,status,created_at
                                         ) VALUES(?,?,?,?,?,?)''', (
                                cu['id'], cu['phone'], 'INVOICE', msg, 'PENDIENTE',
                                datetime.now().isoformat(timespec='seconds')
                            ))

            if c.execute("""SELECT 1 FROM invoices
                            WHERE customer_id=? AND status='PENDIENTE' AND due_date<?
                            LIMIT 1""", (cu['id'], today.isoformat())).fetchone():
                overdue_customers += 1

        c.commit()
    finally:
        c.close()

    commands = process_zone_cuts(datetime.now())

    c = base.db()
    try:
        c.execute('''INSERT INTO billing_runs(run_date,status,detail,created_at)
                     VALUES(?,?,?,?)''', (
            today.isoformat(),
            'OK',
            f'Facturas {created}; morosos {overdue_customers}; comandos {commands}',
            datetime.now().isoformat(timespec='seconds'),
        ))
        c.commit()
    finally:
        c.close()

    return created, overdue_customers, commands


def _run_billing_once_per_day(now, last_billing_date):
    """Run invoice generation on startup and once on each Dominican local date."""
    if last_billing_date == now.date():
        return last_billing_date, None
    return now.date(), run_billing()


def _worker():
    # Generate invoices automatically once per local day; keep cut checks frequent.
    time_module.sleep(8)
    last_billing_date = None
    while True:
        now = datetime.now()
        try:
            last_billing_date, billing_result = _run_billing_once_per_day(now, last_billing_date)
            if billing_result is not None:
                created, overdue, commands = billing_result
                print(
                    f'INTERFLASH_DAILY_BILLING date={now.date().isoformat()} '
                    f'invoices={created} overdue={overdue} commands={commands}',
                    flush=True,
                )
            queued = process_zone_cuts(now)
            if queued:
                print(f'INTERFLASH_ZONE_CUTS_QUEUED={queued}', flush=True)
        except Exception as exc:
            print('INTERFLASH_ZONE_CUT_ERROR=' + str(exc)[:300], flush=True)
        time_module.sleep(30)


def setup(app):
    global _started

    ensure_zone_schema()

    # Keep the saved suspension preference across deployments.
    c = base.db()
    try:
        c.execute('''INSERT INTO app_settings(key,value) VALUES('auto_suspend','1')
                     ON CONFLICT(key) DO NOTHING ''')
        c.commit()
    finally:
        c.close()

    # All manual/daily billing entry points call business_suite.run_billing,
    # so replace it with the time-aware version too.
    bs.run_billing = run_billing

    if not _started and __import__('os').environ.get('INTERFLASH_TESTING') != '1':
        _started = True
        threading.Thread(target=_worker, name='interflash-zone-cut-worker', daemon=True).start()
