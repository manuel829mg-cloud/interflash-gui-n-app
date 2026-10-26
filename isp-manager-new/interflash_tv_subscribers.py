"""Isolated TV subscriber storage prototype.

This module is not wired into the production ISP billing system.
All functions require a caller-provided, authenticated administrator context.
"""
import sqlite3
from datetime import datetime, timezone

def init_subscribers(db_path):
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tv_subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isp_client_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'inactive'
                CHECK(status IN ('inactive','active','suspended')),
            expires_at TEXT,
            created_at TEXT NOT NULL
        )""")

def set_subscription(db_path, isp_client_id, status, expires_at=None):
    if status not in {"inactive", "active", "suspended"}:
        raise ValueError("Invalid subscription status")
    if not str(isp_client_id).strip():
        raise ValueError("Client ID required")
    if expires_at:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Expiry requires timezone")
    with sqlite3.connect(db_path) as db:
        db.execute("""INSERT INTO tv_subscribers
            (isp_client_id,status,expires_at,created_at)
            VALUES (?,?,?,?)
            ON CONFLICT(isp_client_id) DO UPDATE SET
                status=excluded.status, expires_at=excluded.expires_at""",
            (str(isp_client_id), status, expires_at,
             datetime.now(timezone.utc).isoformat()))

def is_entitled(db_path, isp_client_id, now=None):
    now = now or datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT status,expires_at FROM tv_subscribers WHERE isp_client_id=?",
                         (str(isp_client_id),)).fetchone()
    if not row or row[0] != "active":
        return False
    if not row[1]:
        return True
    expiry = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        raise ValueError("Expiry requires a timezone")
    return now < expiry
