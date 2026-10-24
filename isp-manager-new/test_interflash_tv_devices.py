import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask
sys.path.insert(0, os.path.dirname(__file__))
from interflash_tv_catalog import setup as catalog_setup
from interflash_tv_devices import setup as device_setup
from interflash_tv_subscribers import init_subscribers, set_subscription

class DeviceAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "tv.sqlite")
        self.app = Flask(__name__)
        catalog_setup(self.app, db_path=self.path, admin_check=lambda: True)
        device_setup(self.app, db_path=self.path, admin_check=lambda: True)
        init_subscribers(self.path)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_device_catalog_requires_token(self):
        response = self.client.get("/interflash-tv/api/device/channels")
        self.assertEqual(response.status_code, 401)

    def test_only_rights_confirmed_channels_are_available(self):
        expiry = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        set_subscription(self.path, "42", "active", expiry)
        token = self.client.post("/interflash-tv/api/devices", json={"isp_client_id":"42"}).json["device_token"]
        created = self.client.post("/interflash-tv/api/channels", json={
            "name":"Licensed Test Channel",
            "category":"Test",
            "stream_url":"https://example.com/authorized-test.m3u8",
            "rights_confirmed":True
        })
        self.assertEqual(created.status_code, 201)
        response = self.client.get("/interflash-tv/api/device/channels",
                                   headers={"Authorization":"Bearer "+token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["channels"]), 1)

    def test_subscription_required_and_revocable(self):
        self.assertEqual(self.client.post("/interflash-tv/api/devices", json={"isp_client_id":"42"}).status_code, 409)
        expires = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        set_subscription(self.path, "42", "active", expires)
        response = self.client.post("/interflash-tv/api/devices", json={"isp_client_id":"42"})
        self.assertEqual(response.status_code, 201)
        token = response.json["device_token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.client.get("/interflash-tv/api/device/channels", headers=headers).status_code, 200)
        set_subscription(self.path, "42", "suspended")
        self.assertEqual(self.client.get("/interflash-tv/api/device/channels", headers=headers).status_code, 403)
        set_subscription(self.path, "42", "active", expires)
        self.assertEqual(self.client.post("/interflash-tv/api/devices/revoke", json={"isp_client_id":"42"}).status_code, 200)
        self.assertEqual(self.client.get("/interflash-tv/api/device/channels", headers=headers).status_code, 403)

if __name__ == "__main__":
    unittest.main()
