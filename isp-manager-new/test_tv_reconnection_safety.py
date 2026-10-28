import sqlite3
import unittest
from datetime import date, datetime, timezone
from tv_subscriptions_isolated import create_schema, record_payment, status, start_one_time_trial


class TVReconnectionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        create_schema(self.db)
        self.db.execute("""INSERT INTO tv_subscriptions
            (id,customer_id,device_token_hash,billing_day,paid_through,
             first_unpaid_due,unlinked_at,created_at)
            VALUES (1,12,NULL,10,'2026-08-10','2026-08-10',
                    '2026-10-10T00:00:00+00:00','2026-07-01')""")

    def tearDown(self):
        self.db.close()

    def test_payment_does_not_restore_old_unlinked_device(self):
        due = record_payment(self.db,1,'receipt-123',date(2026,10,28))
        self.assertEqual(due, date(2026,11,10))
        self.assertEqual(status(self.db,1,date(2026,10,28)),'UNLINKED')
        row=self.db.execute(
            "SELECT device_token_hash,unlinked_at FROM tv_subscriptions WHERE id=1"
        ).fetchone()
        self.assertIsNone(row[0])
        self.assertIsNotNone(row[1])

    def test_after_repair_paid_subscription_is_active(self):
        record_payment(self.db,1,'receipt-123',date(2026,10,28))
        self.db.execute("UPDATE tv_subscriptions SET device_token_hash='new-token' WHERE id=1")
        self.assertEqual(status(self.db,1,date(2026,10,28)),'ACTIVE')

    def test_same_receipt_cannot_pay_two_customers(self):
        self.db.execute("""INSERT INTO tv_subscriptions
            (id,customer_id,billing_day,created_at)
            VALUES (2,22,10,'2026-07-01')""")
        record_payment(self.db,1,'shared-receipt',date(2026,10,28))
        with self.assertRaises(ValueError):
            record_payment(self.db,2,'shared-receipt',date(2026,10,28))
        self.assertIsNone(self.db.execute(
            "SELECT paid_through FROM tv_subscriptions WHERE id=2"
        ).fetchone()[0])

    def test_payment_cancels_trial_without_deducting_days(self):
        self.db.execute(
            "UPDATE tv_subscriptions SET device_token_hash='token',paid_through=NULL,trial_used=0 WHERE id=1"
        )
        start_one_time_trial(self.db,1,datetime(2026,10,28,tzinfo=timezone.utc))
        record_payment(self.db,1,'receipt-456',date(2026,10,28))
        self.assertIsNone(self.db.execute(
            "SELECT trial_end_utc FROM tv_subscriptions WHERE id=1"
        ).fetchone()[0])

    def test_paid_accounts_cannot_restart_trial(self):
        self.db.execute(
            "UPDATE tv_subscriptions SET device_token_hash='token',paid_through='2026-11-10',trial_used=0 WHERE id=1"
        )
        with self.assertRaises(ValueError):
            start_one_time_trial(self.db,1,datetime(2026,10,28,tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
