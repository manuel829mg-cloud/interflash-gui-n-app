"""Tests for isolated Inter Flash TV prototype (no production services)."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from flask import Flask
from interflash_tv_catalog import setup
from interflash_tv_subscribers import init_subscribers, set_subscription, is_entitled


class TVTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tv.sqlite3")
        self.app = Flask(__name__)
        setup(self.app, db_path=self.db, admin_check=lambda: True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalog_requires_confirmed_rights(self):
        response = self.client.post("/interflash-tv/api/channels", json={
            "name": "Canal", "category": "Noticias",
            "stream_url": "https://example.org/live.m3u8",
            "rights_confirmed": False
        })
        self.assertEqual(response.status_code, 400)

    def test_catalog_add_and_list(self):
        response = self.client.post("/interflash-tv/api/channels", json={
            "name": "Canal de prueba", "category": "General",
            "stream_url": "https://example.org/live.m3u8",
            "rights_confirmed": True
        })
        self.assertEqual(response.status_code, 201)
        rows = self.client.get("/interflash-tv/api/channels").get_json()["channels"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Canal de prueba")
        self.assertNotIn("stream_url", rows[0])

    def test_denies_unauthenticated_admin(self):
        other = Flask("unauthenticated")
        setup(other, db_path=self.db, admin_check=lambda: False)
        self.assertEqual(other.test_client().get("/interflash-tv/api/channels").status_code, 403)

    def test_subscription_expiry_and_suspension(self):
        init_subscribers(self.db)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        set_subscription(self.db, "123", "active", expiry)
        self.assertTrue(is_entitled(self.db, "123"))
        set_subscription(self.db, "123", "suspended", expiry)
        self.assertFalse(is_entitled(self.db, "123"))


if __name__ == "__main__":
    unittest.main()
