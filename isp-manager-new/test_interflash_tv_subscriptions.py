import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from interflash_tv_subscribers import init_subscribers, set_subscription, is_entitled

class TvSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tv.sqlite")
        init_subscribers(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_inactive_by_default(self):
        self.assertFalse(is_entitled(self.db, "101"))

    def test_active_until_expiry(self):
        now = datetime.now(timezone.utc)
        expiry = (now + timedelta(days=30)).isoformat()
        set_subscription(self.db, "101", "active", expiry)
        self.assertTrue(is_entitled(self.db, "101", now=now))
        self.assertFalse(is_entitled(self.db, "101", now=now + timedelta(days=31)))

    def test_suspension_blocks_access(self):
        set_subscription(self.db, "101", "active")
        self.assertTrue(is_entitled(self.db, "101"))
        set_subscription(self.db, "101", "suspended")
        self.assertFalse(is_entitled(self.db, "101"))

    def test_reject_naive_expiry(self):
        with self.assertRaises(ValueError):
            set_subscription(self.db, "101", "active", "2026-11-01T00:00:00")

if __name__ == "__main__":
    unittest.main()
