"""Offline regression tests for TV billing. Run: python -m unittest discover -s tests -p 'test_tv_billing_rules.py'"""
import unittest
from datetime import date, datetime, timedelta, timezone
from tv_billing_rules import (
    next_month_same_day, paid_through_after_payment, access_state,
    trial_expiry, months_overdue, unlink_due,
)


class TVBillingRulesTests(unittest.TestCase):
    def test_month_end_anchor(self):
        self.assertEqual(next_month_same_day(date(2026, 1, 31), 31), date(2026, 2, 28))
        self.assertEqual(next_month_same_day(date(2026, 2, 28), 31), date(2026, 3, 31))

    def test_advance_payment_adds_month(self):
        self.assertEqual(paid_through_after_payment(date(2026, 10, 10), date(2026, 10, 20), 20),
                         date(2026, 11, 20))

    def test_late_payment_does_not_charge_suspended_months(self):
        self.assertEqual(paid_through_after_payment(date(2026, 10, 27), date(2026, 7, 5), 5),
                         date(2026, 11, 5))

    def test_pay_on_cutoff_keeps_original_day(self):
        self.assertEqual(paid_through_after_payment(date(2026, 10, 5), date(2026, 9, 5), 5),
                         date(2026, 11, 5))

    def test_suspend_on_due_date(self):
        self.assertEqual(access_state(date(2026, 10, 5), date(2026, 10, 5)), 'SUSPENDED')
        self.assertEqual(access_state(date(2026, 10, 4), date(2026, 10, 5)), 'ACTIVE')

    def test_trial_once_and_exactly_24_hours(self):
        start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        until = trial_expiry(start, False)
        self.assertEqual(until, start + timedelta(hours=24))
        self.assertEqual(access_state(date(2026, 10, 28), None, until, until - timedelta(seconds=1)), 'TRIAL')
        self.assertEqual(access_state(date(2026, 10, 28), None, until, until), 'SUSPENDED')
        with self.assertRaises(ValueError):
            trial_expiry(start, True)

    def test_unlink_on_third_unpaid_due_date(self):
        due = date(2026, 8, 5)
        self.assertEqual(months_overdue(date(2026, 10, 4), due, 5), 2)
        self.assertFalse(unlink_due(date(2026, 10, 4), due, 5))
        self.assertTrue(unlink_due(date(2026, 10, 5), due, 5))

    def test_no_unlink_before_first_due_date(self):
        self.assertEqual(months_overdue(date(2026, 8, 4), date(2026, 8, 5), 5), 0)


if __name__ == '__main__':
    unittest.main()
