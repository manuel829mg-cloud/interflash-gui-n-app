"""Isolated TV renewal reconciliation.

No direct WhatsApp, MikroTik, internet billing, player or destructive side effects.
Scheduled callers may use returned events to queue WhatsApp after authorization.
Assumes the TV subscription schema from tv_subscriptions_isolated is present.
"""
from datetime import date, datetime, timezone
from tv_subscriptions_isolated import missed_cutoffs


def reconcile_tv_day(db, today: date, now=None):
    """Advance TV-only state and return newly created outbox events.

    This function must only run after migrating and associating customers in a
    test environment. It does not delete registered devices; on the third
    missed cutoff it marks TV subscriptions unlinked to require a new pairing.
    It does not change ISP service or send WhatsApp.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    timestamp = now.isoformat()
    events = []
    db.execute("BEGIN IMMEDIATE")
    try:
        rows = db.execute(
            """SELECT id, billing_day, paid_through, first_unpaid_due,
                      device_token_hash, unlinked_at
               FROM tv_subscriptions"""
        ).fetchall()
        for sid, anchor, paid_until, first_unpaid, token, unlinked_at in rows:
            if paid_until is None:
                # No first payment means no billing obligation yet.
                continue
            due = date.fromisoformat(paid_until)
            if today < due:
                # Reminder exactly one local calendar day ahead, once.
                if (due - today).days == 1 and token:
                    _emit(db, events, sid, "TV_REMINDER", today, timestamp)
                continue
            first = date.fromisoformat(first_unpaid) if first_unpaid else due
            if not first_unpaid:
                db.execute(
                    "UPDATE tv_subscriptions SET first_unpaid_due=? WHERE id=?",
                    (first.isoformat(), sid)
                )
            if missed_cutoffs(today, first, anchor) >= 3:
                if token and not unlinked_at:
                    db.execute(
                        """UPDATE tv_subscriptions
                           SET unlinked_at=?
                           WHERE id=?""", (timestamp, sid)
                    )
                    _emit(db, events, sid, "TV_UNLINK_NOTICE", today, timestamp)
            elif token:
                _emit(db, events, sid, "TV_SUSPENDED", due, timestamp)
        db.commit()
        return events
    except Exception:
        db.rollback()
        raise


def _emit(db, events, sid, kind, day, created_at):
    inserted = db.execute(
        """INSERT OR IGNORE INTO tv_subscription_events
           (subscription_id,event_type,effective_day,created_at)
           VALUES (?,?,?,?)""",
        (sid,kind,day.isoformat(),created_at)
    )
    if inserted.rowcount:
        events.append(dict(subscription_id=sid, event_type=kind,
                           effective_day=day.isoformat()))
