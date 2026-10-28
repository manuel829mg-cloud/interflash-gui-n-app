import sqlite3
import unittest
from datetime import date, datetime, timezone
from tv_subscriptions_isolated import (
    create_schema, due_on, extend_paid_through, missed_cutoffs,
    record_payment, status, start_one_time_trial
)

class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        create_schema(self.db)
        self.db.execute("""INSERT INTO tv_subscriptions
            (id,customer_id,device_token_hash,billing_day,paid_through,created_at)
            VALUES (1,100,'example_hash',5,'2026-08-05','2026-07-01')""")

    def tearDown(self):
        self.db.close()

    def test_anchor_survives_late_payment(self):
        due = record_payment(self.db, 1, 'payment-1', date(2026,10,27))
        self.assertEqual(due, date(2026,11,5))
        self.assertEqual(status(self.db,1,date(2026,10,27)), 'ACTIVE')

    def test_duplicate_payment_not_double_charged(self):
        a = record_payment(self.db,1,'same-ref',date(2026,10,27))
        b = record_payment(self.db,1,'same-ref',date(2026,10,27))
        self.assertEqual(a,b)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM tv_subscription_payments').fetchone()[0],1)

    def test_prepaid_extends_month(self):
        self.assertEqual(extend_paid_through(date(2026,10,20),date(2026,11,5),5),date(2026,12,5))

    def test_month_end(self):
        self.assertEqual(due_on(2026,2,31), date(2026,2,28))
        self.assertEqual(extend_paid_through(date(2026,2,27),date(2026,2,28),31),date(2026,3,31))

    def test_three_missed_due_days(self):
        self.assertEqual(missed_cutoffs(date(2026,10,4),date(2026,8,5),5),2)
        self.assertEqual(missed_cutoffs(date(2026,10,5),date(2026,8,5),5),3)

    def test_trial_once(self):
        self.db.execute('UPDATE tv_subscriptions SET paid_through=NULL WHERE id=1')
        clock=datetime(2026,10,28,12,tzinfo=timezone.utc)
        end = start_one_time_trial(self.db,1,clock)
        self.assertEqual(status(self.db,1,date(2026,10,28),clock), 'TRIAL')
        self.assertEqual(status(self.db,1,date(2026,10,29),end), 'SUSPENDED')
        with self.assertRaises(ValueError):
            start_one_time_trial(self.db,1,clock)

    def test_internet_is_not_in_database_schema(self):
        tables={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse('invoices' in tables or 'pppoe' in tables)

if __name__ == '__main__':
    unittest.main()
