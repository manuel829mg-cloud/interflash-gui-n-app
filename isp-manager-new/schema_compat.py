import sqlite3
import app as base


def _columns(conn, table):
    try:
        return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    except sqlite3.Error:
        return set()


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def ensure_legacy_compat():
    """Make older INTER Flash SQLite files readable by the current app.

    This migration is additive only: it adds missing compatibility columns and,
    when possible, copies legacy client references/data into the current names.
    Existing rows are not deleted or overwritten.
    """
    conn = base.db()
    try:
        # Older builds used invoices.client_id / payments.client_id.
        inv_cols = _columns(conn, 'invoices')
        if inv_cols and 'customer_id' not in inv_cols:
            conn.execute('ALTER TABLE invoices ADD COLUMN customer_id INTEGER')
            inv_cols.add('customer_id')
        if 'customer_id' in inv_cols and 'client_id' in inv_cols:
            conn.execute(
                'UPDATE invoices SET customer_id=client_id '
                'WHERE customer_id IS NULL AND client_id IS NOT NULL'
            )

        pay_cols = _columns(conn, 'payments')
        if pay_cols and 'customer_id' not in pay_cols:
            conn.execute('ALTER TABLE payments ADD COLUMN customer_id INTEGER')
            pay_cols.add('customer_id')
        if 'customer_id' in pay_cols and 'client_id' in pay_cols:
            conn.execute(
                'UPDATE payments SET customer_id=client_id '
                'WHERE customer_id IS NULL AND client_id IS NOT NULL'
            )

        # Older plan tables may only have fields such as name/price/speed.
        # Add the columns the current Plans screen expects, without deleting data.
        plan_cols = _columns(conn, 'plans')
        if plan_cols:
            if 'download_mbps' not in plan_cols:
                conn.execute('ALTER TABLE plans ADD COLUMN download_mbps INTEGER DEFAULT 0')
                plan_cols.add('download_mbps')
            if 'upload_mbps' not in plan_cols:
                conn.execute('ALTER TABLE plans ADD COLUMN upload_mbps INTEGER DEFAULT 0')
                plan_cols.add('upload_mbps')
            if 'active' not in plan_cols:
                conn.execute('ALTER TABLE plans ADD COLUMN active INTEGER DEFAULT 1')
                plan_cols.add('active')
            if 'price' not in plan_cols:
                conn.execute('ALTER TABLE plans ADD COLUMN price REAL DEFAULT 0')
                plan_cols.add('price')

            # Copy common legacy speed columns when present and current values are empty.
            for legacy_name in ('download', 'download_speed', 'speed_down', 'down_mbps'):
                if legacy_name in plan_cols:
                    conn.execute(
                        f'UPDATE plans SET download_mbps=CAST({legacy_name} AS INTEGER) '
                        f'WHERE COALESCE(download_mbps,0)=0 AND {legacy_name} IS NOT NULL'
                    )
                    break
            for legacy_name in ('upload', 'upload_speed', 'speed_up', 'up_mbps'):
                if legacy_name in plan_cols:
                    conn.execute(
                        f'UPDATE plans SET upload_mbps=CAST({legacy_name} AS INTEGER) '
                        f'WHERE COALESCE(upload_mbps,0)=0 AND {legacy_name} IS NOT NULL'
                    )
                    break

        # Some older builds stored subscribers in `clients` instead of `customers`.
        # Preserve IDs so existing invoice/payment references keep matching.
        if _table_exists(conn, 'clients') and _table_exists(conn, 'customers'):
            customer_count = conn.execute('SELECT COUNT(*) AS c FROM customers').fetchone()['c']
            if customer_count == 0:
                legacy = _columns(conn, 'clients')
                dest = _columns(conn, 'customers')
                mapping = [
                    ('id', 'id'),
                    ('name', 'name'),
                    ('phone', 'phone'),
                    ('document', 'document'),
                    ('email', 'email'),
                    ('address', 'address'),
                    ('pppoe', 'pppoe'),
                    ('ip_address', 'ip_address'),
                    ('plan_id', 'plan_id'),
                    ('status', 'status'),
                    ('created_at', 'created_at'),
                ]
                pairs = [(dst, src) for dst, src in mapping if dst in dest and src in legacy]
                if 'id' in legacy and 'name' in legacy and pairs:
                    dst_cols = ','.join(dst for dst, _ in pairs)
                    src_cols = ','.join(src for _, src in pairs)
                    conn.execute(
                        f'INSERT OR IGNORE INTO customers({dst_cols}) '
                        f'SELECT {src_cols} FROM clients'
                    )

        conn.commit()
    finally:
        conn.close()


ensure_legacy_compat()
