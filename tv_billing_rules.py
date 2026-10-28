"""Pure TV subscription billing rules; isolated from internet invoices.

No network calls, database migrations, or production side effects.
"""
import calendar
from datetime import date, datetime, timedelta


def next_month_same_day(value: date, anchor_day: int) -> date:
    """Advance one calendar month, clamping to month end when necessary."""
    year = value.year + (value.month == 12)
    month = value.month % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def paid_through_after_payment(today: date, paid_through: date | None,
                               anchor_day: int) -> date:
    """One RD$600 payment buys one month; keep original billing-day anchor.

    When current, extend the existing paid-through date. When expired, the
    first new period ends on the next occurrence of the billing anchor day.
    This avoids charging for months spent suspended.
    """
    if not 1 <= anchor_day <= 31:
        raise ValueError('Invalid billing anchor day')
    if paid_through is not None and paid_through > today:
        return next_month_same_day(paid_through, anchor_day)
    this_month_anchor = date(today.year, today.month,
                             min(anchor_day, calendar.monthrange(today.year, today.month)[1]))
    if today < this_month_anchor:
        return this_month_anchor
    return next_month_same_day(this_month_anchor, anchor_day)


def access_state(today: date, paid_through: date | None,
                 trial_until: datetime | None = None,
                 now: datetime | None = None) -> str:
    if trial_until is not None:
        if now is None:
            raise ValueError('Current timestamp required for trial')
        if now < trial_until:
            return 'TRIAL'
    return 'ACTIVE' if paid_through is not None and today < paid_through else 'SUSPENDED'


def trial_expiry(start: datetime, used_before: bool) -> datetime:
    if used_before:
        raise ValueError('Trial already used')
    if start.tzinfo is None:
        raise ValueError('Timezone-aware start required')
    return start + timedelta(hours=24)


def months_overdue(today: date, due_date: date, anchor_day: int) -> int:
    """Count consecutive unpaid monthly due dates, including due date."""
    if today < due_date:
        return 0
    count = 0
    cursor = due_date
    while cursor <= today:
        count += 1
        cursor = next_month_same_day(cursor, anchor_day)
    return count


def unlink_due(today: date, due_date: date, anchor_day: int) -> bool:
    """Unlink on third consecutive missed monthly due date."""
    return months_overdue(today, due_date, anchor_day) >= 3
