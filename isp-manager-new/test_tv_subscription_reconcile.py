import sqlite3
import unittest
from datetime import date
from tv_subscriptions_isolated import create_schema, status
from tv_subscription_reconcile import reconcile_tv_day


class ReconcileTVTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        create_schema(self.db)
        self.db.execute(
            """INSERT INTO tv_subscriptions
               (id,customer_id,device_token_hash,billing_day,
                paid_through,created_at)
               VALUES(1,100,'device_hash',5,'2026-08-05','2026-07-01')"""
        )

    def tearDown(self):
        self.db.close()

    def test_suspend_once_and_keep_device(self):
        first = reconcile_tv_day(self.db,date(2026,8,5))
        second = reconcile_tv_day(self.db,date(2026,8,5))
        self.assertEqual([e['event_type'] for e in first],['TV_SUSPENDED'])
        self.assertEqual(second, [])
        self.assertEqual(status(self.db,1,date(2026,8,5)),'SUSPENDED')
        self.assertEqual(self.db.execute('SELECT device_token_hash FROM tv_subscriptions').fetchone()[0], 'device_hash')

    def test_unlink_only_on_third_missed_cutoff(self):
        reconcile_tv_day(self.db,date(2026,8,5))
        reconcile_tv_day(self.db,date(2026,10,4))
        self.assertEqual(self.db.execute('SELECT device_token_hash FROM tv_subscriptions').fetchone()[0], 'device_hash')
        events = reconcile_tv_day(self.db,date(2026,10,5))
        self.assertEqual([e['event_type'] for e in events], ['TV_UNLINK_NOTICE'])
        self.assertEqual(self.db.execute(
            'SELECT device_token_hash FROM tv_subscriptions WHERE id=1'
        ).fetchone()[0], 'device_hash')
        self.assertEqual(status(self.db,1,date(2026,10,5)), 'UNLINKED')
        self.assertEqual(reconcile_tv_day(self.db,date(2026,10,5)), [])

    def test_reminder_one_day_before_cutoff(self):
        self.db.execute("UPDATE tv_subscriptions SET paid_through='2026-11-05' WHERE id=1")
        events = reconcile_tv_day(self.db,date(2026,11,4))
        self.assertEqual([e['event_type'] for e in events], ['TV_REMINDER'])
        self.assertEqual(reconcile_tv_day(self.db,date(2026,11,4)), [])

    def test_never_alters_internet_tables(self):
        self.db.execute("CREATE TABLE internet_accounts(id INTEGER PRIMARY KEY, state TEXT)")
        self.db.execute("INSERT INTO internet_accounts VALUES(100,'ACTIVE')")
        reconcile_tv_day(self.db,date(2026,10,5))
        self.assertEqual(self.db.execute('SELECT state FROM internet_accounts').fetchone()[0], 'ACTIVE')


if __name__ == '__main__':
    unittest.main()
