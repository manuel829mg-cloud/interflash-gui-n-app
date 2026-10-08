"""On-demand per-client PPPoE traffic for INTER Flash."""
from datetime import datetime, timedelta
from flask import jsonify, redirect, url_for

import app as base

WATCH_TTL_SECONDS = 4


def ensure_schema():
    c = base.db()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS client_traffic_watch(
          router_name TEXT NOT NULL,
          pppoe TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          PRIMARY KEY(router_name, pppoe)
        );
        CREATE INDEX IF NOT EXISTS idx_client_traffic_watch_expiry
          ON client_traffic_watch(expires_at);
        CREATE TABLE IF NOT EXISTS push_pppoe_traffic(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          router_name TEXT NOT NULL,
          pppoe TEXT NOT NULL,
          download_bytes INTEGER DEFAULT 0,
          upload_bytes INTEGER DEFAULT 0,
          download_bps REAL DEFAULT 0,
          upload_bps REAL DEFAULT 0,
          updated_at TEXT,
          UNIQUE(router_name, pppoe)
        );
        CREATE INDEX IF NOT EXISTS idx_push_pppoe_traffic_router
          ON push_pppoe_traffic(router_name, pppoe);
        """)
        c.commit()
    finally:
        c.close()


def _parse_bytes_pair(value):
    """PPP Active stats: first transmitted, second received, from router view."""
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        parts = value[:2]
    else:
        parts = str(value or "").split("/", 1)
        if len(parts) != 2:
            return None
    try:
        transmitted = int(str(parts[0]).strip())
        received = int(str(parts[1]).strip())
    except (TypeError, ValueError):
        return None
    if transmitted < 0 or received < 0:
        return None
    return transmitted, received


def save_samples(conn, router_name, items):
    now = datetime.now()
    now_s = now.isoformat(timespec="microseconds")
    for item in items:
        if not isinstance(item, dict):
            continue
        pppoe = str(item.get("name") or "").strip()[:255]
        pair = _parse_bytes_pair(item.get("bytes"))
        if not pppoe or pair is None:
            continue
        download_bytes, upload_bytes = pair
        previous = conn.execute(
            """SELECT download_bytes,upload_bytes,updated_at
               FROM push_pppoe_traffic WHERE router_name=? AND pppoe=?""",
            (router_name, pppoe),
        ).fetchone()
        download_bps = upload_bps = 0.0
        if previous and previous["updated_at"]:
            try:
                before = datetime.fromisoformat(previous["updated_at"])
                seconds = (now - before).total_seconds()
                if seconds < 0.8:
                    continue
                old_down = int(previous["download_bytes"])
                old_up = int(previous["upload_bytes"])
                if seconds >= 0.8:
                    if download_bytes >= old_down:
                        download_bps = (download_bytes - old_down) * 8.0 / seconds
                    if upload_bytes >= old_up:
                        upload_bps = (upload_bytes - old_up) * 8.0 / seconds
            except (TypeError, ValueError):
                pass
        conn.execute(
            """INSERT INTO push_pppoe_traffic
               (router_name,pppoe,download_bytes,upload_bytes,download_bps,upload_bps,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(router_name,pppoe) DO UPDATE SET
                 download_bytes=excluded.download_bytes,
                 upload_bytes=excluded.upload_bytes,
                 download_bps=excluded.download_bps,
                 upload_bps=excluded.upload_bps,
                 updated_at=excluded.updated_at""",
            (router_name, pppoe, download_bytes, upload_bytes,
             download_bps, upload_bps, now_s),
        )


def customer_traffic_api(customer_id):
    if not base.logged_in():
        return redirect(url_for("login"))
    c = base.db()
    try:
        customer = c.execute(
            "SELECT id,pppoe,router_name FROM customers WHERE id=?",
            (customer_id,),
        ).fetchone()
        if not customer:
            return jsonify(ok=False, error="not-found"), 404
        pppoe = (customer["pppoe"] or "").strip()
        router = (customer["router_name"] or "CCR2116").strip()
        has_pppoe = bool(pppoe)
        now = datetime.now()
        if has_pppoe:
            expiry = (now + timedelta(seconds=WATCH_TTL_SECONDS)).isoformat(timespec="seconds")
            c.execute(
                """INSERT INTO client_traffic_watch(router_name,pppoe,expires_at)
                   VALUES(?,?,?) ON CONFLICT(router_name,pppoe)
                   DO UPDATE SET expires_at=excluded.expires_at""",
                (router, pppoe, expiry),
            )
        row = c.execute(
            """SELECT download_bytes,upload_bytes,download_bps,upload_bps,updated_at
               FROM push_pppoe_traffic WHERE router_name=? AND pppoe=?""",
            (router, pppoe),
        ).fetchone() if has_pppoe else None
        active = c.execute(
            """SELECT 1 FROM push_pppoe_active
               WHERE router_name=? AND name=? LIMIT 1""",
            (router, pppoe),
        ).fetchone() if has_pppoe else None
        c.commit()
        updated_at = row["updated_at"] if row else None
        recent = False
        if updated_at:
            try:
                recent = (now - datetime.fromisoformat(updated_at)).total_seconds() <= 6
            except (TypeError, ValueError):
                pass
        return jsonify(
            ok=True,
            has_pppoe=has_pppoe,
            online=bool(active and recent),
            download_bytes=int(row["download_bytes"] or 0) if row else 0,
            upload_bytes=int(row["upload_bytes"] or 0) if row else 0,
            download_bps=float(row["download_bps"] or 0) if row and recent else 0,
            upload_bps=float(row["upload_bps"] or 0) if row and recent else 0,
            updated_at=updated_at,
        )
    finally:
        c.close()


def setup(app):
    ensure_schema()
    app.add_url_rule(
        "/api/customers/<int:customer_id>/traffic",
        endpoint="customer_traffic_api",
        view_func=customer_traffic_api,
        methods=["GET"],
    )
