import ast
import sqlite3
import types
import unittest
from datetime import datetime as RealDateTime, timedelta
from pathlib import Path
from unittest.mock import patch

source = ast.parse((Path(__file__).parents[1] / "client_traffic.py").read_text())
functions = [
    node for node in source.body
    if isinstance(node, ast.FunctionDef) and node.name in ("_parse_bytes_pair", "save_samples")
]
client_traffic = types.ModuleType("traffic_under_test")
client_traffic.datetime = RealDateTime
exec(compile(ast.Module(body=functions, type_ignores=[]), "client_traffic.py", "exec"), client_traffic.__dict__)


class ClientTrafficTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""CREATE TABLE push_pppoe_traffic(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            router_name TEXT NOT NULL, pppoe TEXT NOT NULL,
            download_bytes INTEGER DEFAULT 0, upload_bytes INTEGER DEFAULT 0,
            download_bps REAL DEFAULT 0, upload_bps REAL DEFAULT 0,
            updated_at TEXT, UNIQUE(router_name, pppoe))""")
        self.now = RealDateTime(2026, 10, 7, 12, 0, 0)

    def tearDown(self):
        self.conn.close()

    def test_router_byte_pair_maps_download_then_upload(self):
        with patch.object(client_traffic, "datetime") as clock:
            clock.now.return_value = self.now
            clock.fromisoformat = RealDateTime.fromisoformat
            client_traffic.save_samples(
                self.conn, "CCR2116", [{"name": "cliente-1", "bytes": "1000/500"}]
            )
            clock.now.return_value = self.now + timedelta(seconds=2)
            client_traffic.save_samples(
                self.conn, "CCR2116", [{"name": "cliente-1", "bytes": "11000/2500"}]
            )
        row = self.conn.execute("SELECT * FROM push_pppoe_traffic").fetchone()
        self.assertEqual(row["download_bytes"], 11000)
        self.assertEqual(row["upload_bytes"], 2500)
        self.assertEqual(row["download_bps"], 40000)
        self.assertEqual(row["upload_bps"], 8000)

    def test_invalid_and_reset_samples_do_not_make_negative_rates(self):
        with patch.object(client_traffic, "datetime") as clock:
            clock.now.return_value = self.now
            clock.fromisoformat = RealDateTime.fromisoformat
            client_traffic.save_samples(
                self.conn, "CCR2116", [{"name": "cliente-1", "bytes": "1000/500"}]
            )
            clock.now.return_value = self.now + timedelta(seconds=2)
            client_traffic.save_samples(
                self.conn, "CCR2116", [{"name": "cliente-1", "bytes": "bad"}]
            )
            client_traffic.save_samples(
                self.conn, "CCR2116", [{"name": "cliente-1", "bytes": "10/5"}]
            )
        row = self.conn.execute("SELECT * FROM push_pppoe_traffic").fetchone()
        self.assertEqual(row["download_bytes"], 10)
        self.assertEqual(row["upload_bytes"], 5)
        self.assertEqual(row["download_bps"], 0)
        self.assertEqual(row["upload_bps"], 0)


if __name__ == "__main__":
    unittest.main()
