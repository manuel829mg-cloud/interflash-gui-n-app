"""One-time catalogue retirement; never rewrites customers or router commands."""
import app as base

PLANS = (
    ('Económico', 20, 800), ('Básico', 40, 1000),
    ('Familiar', 60, 1300), ('Plus', 100, 1500),
    ('Premium', 200, 2000), ('Ultra', 300, 3000),
)
MIGRATION = 'commercial-six-symmetric-20261008'

def setup(app):
    c = base.db()
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS catalog_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        if c.execute('SELECT 1 FROM catalog_migrations WHERE name=?', (MIGRATION,)).fetchone():
            c.rollback()
            return
        # Retain IDs, prices and profile mappings for every existing customer.
        c.execute('UPDATE plans SET active=0 WHERE active=1')
        for name, speed, price in PLANS:
            c.execute('INSERT INTO plans(name,download_mbps,upload_mbps,price,active) VALUES(?,?,?,?,1)',
                      (name, speed, speed, price))
        c.execute('INSERT INTO catalog_migrations(name) VALUES(?)', (MIGRATION,))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
