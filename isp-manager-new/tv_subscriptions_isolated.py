"""Isolated Inter Flash TV subscription domain. Not imported by production.

Uses a standalone SQLite store, with no PPPoE, MikroTik or internet invoice side effects.
Deployment is intentionally opt-in after API/player integration and migration review.
"""
import calendar
import sqlite3
from datetime import date, datetime, timedelta, timezone

TV_PRICE_DOP = 600

def due_on(year, month, anchor):
    if not 1 <= anchor <= 31:
        raise ValueError("Billing day must be 1..31")
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))

def next_due_after(day, anchor):
    y, m = day.year, day.month
    due = due_on(y, m, anchor)
    if due <= day:
        y += (m == 12)
        m = m % 12 + 1
        due = due_on(y, m, anchor)
    return due

def extend_paid_through(today, prior_due, anchor):
    """Advance prepaid month or reactivate for RD$600 without arrears.

    If overdue, payment restores service only until the next established
    billing day. Deliberately maintains the original billing-day anchor.
    """
    if prior_due and today < prior_due:
        return next_due_after(prior_due, anchor)
    return next_due_after(today, anchor)

def missed_cutoffs(today, first_unpaid_due, anchor):
    if not first_unpaid_due or today < first_unpaid_due:
        return 0
    count, cursor = 0, first_unpaid_due
    while cursor <= today:
        count += 1
        cursor = next_due_after(cursor, anchor)
    return count

def create_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tv_subscriptions (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL UNIQUE,
        device_token_hash TEXT UNIQUE,
        billing_day INTEGER NOT NULL CHECK(billing_day BETWEEN 1 AND 31),
        paid_through TEXT,
        trial_end_utc TEXT,
        trial_used INTEGER NOT NULL DEFAULT 0 CHECK(trial_used IN (0,1)),
        first_unpaid_due TEXT,
        unlinked_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tv_subscription_payments (
        id INTEGER PRIMARY KEY,
        subscription_id INTEGER NOT NULL,
        amount_dop INTEGER NOT NULL CHECK(amount_dop=600),
        idempotency_key TEXT NOT NULL UNIQUE,
        paid_at TEXT NOT NULL,
        previous_due TEXT,
        new_due TEXT NOT NULL,
        FOREIGN KEY(subscription_id) REFERENCES tv_subscriptions(id)
    );
    CREATE TABLE IF NOT EXISTS tv_subscription_events (
        id INTEGER PRIMARY KEY,
        subscription_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        effective_day TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(subscription_id,event_type,effective_day)
    );
    """)

def record_payment(db, subscription_id, key, today, now=None):
    """Atomic, idempotent bookkeeping. Caller must authenticate admin/payment.

    Paying after automatic unlink must not silently rebind the old TV token.
    """
    if not key or len(key) > 128:
        raise ValueError("Valid payment idempotency key required")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute(
            "SELECT new_due FROM tv_subscription_payments WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing:
            db.commit()
            return date.fromisoformat(existing[0])
        row = db.execute(
            "SELECT billing_day,paid_through FROM tv_subscriptions WHERE id=?", (subscription_id,)
        ).fetchone()
        if not row:
            raise LookupError("TV subscription not found")
        previous = date.fromisoformat(row[1]) if row[1] else None
        due = extend_paid_through(today, previous, row[0])
        db.execute(
            "UPDATE tv_subscriptions SET paid_through=?,first_unpaid_due=NULL,trial_end_utc=NULL WHERE id=?",
            (due.isoformat(), subscription_id)
        )
        db.execute(
            """INSERT INTO tv_subscription_payments
               (subscription_id,amount_dop,idempotency_key,paid_at,previous_due,new_due)
               VALUES(?,?,?,?,?,?)""",
            (subscription_id,TV_PRICE_DOP,key,now.isoformat(),
             previous.isoformat() if previous else None,due.isoformat())
        )
        db.commit()
        return due
    except Exception:
        db.rollback()
        raise

def status(db, subscription_id, today, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    row = db.execute(
        """SELECT paid_through,trial_end_utc,device_token_hash,first_unpaid_due,billing_day
           FROM tv_subscriptions WHERE id=?""", (subscription_id,)
    ).fetchone()
    if not row:
        return "NOT_FOUND"
    paid, trial, token, unpaid, anchor = row
    if not token:
        return "UNLINKED"
    if paid and today < date.fromisoformat(paid):
        return "ACTIVE"
    if trial and now_utc < datetime.fromisoformat(trial):
        return "TRIAL"
    if unpaid and missed_cutoffs(today, date.fromisoformat(unpaid), anchor) >= 3:
        return "UNLINK_REQUIRED"
    return "SUSPENDED"

def start_one_time_trial(db, subscription_id, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    end = now + timedelta(hours=24)
    cur = db.execute(
        """UPDATE tv_subscriptions SET trial_used=1,trial_end_utc=?
           WHERE id=? AND trial_used=0 AND paid_through IS NULL""", (end.isoformat(), subscription_id)
    )
    db.commit()
    if cur.rowcount != 1:
        raise ValueError("Trial already used or subscription missing")
    return end
