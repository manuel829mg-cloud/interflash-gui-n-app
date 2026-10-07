"""Regression coverage for cached/subsecond MikroTik counter reports."""
import ast
import sqlite3
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# Exercise the production counter calculation without starting the web app.
source = ast.parse((Path(__file__).parents[1] / 'push_sync.py').read_text())
functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
             and node.name in ('_safe', '_save_traffic')]
push_sync = types.ModuleType('traffic_under_test')
push_sync.datetime = datetime
exec(compile(ast.Module(body=functions, type_ignores=[]), 'push_sync.py', 'exec'),
     push_sync.__dict__)

class TrafficSamplingTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('''CREATE TABLE push_router_traffic(
            router_name TEXT, interface_name TEXT, rx_bytes INTEGER,
            tx_bytes INTEGER, rx_bps REAL, tx_bps REAL, updated_at TEXT,
            UNIQUE(router_name, interface_name))''')
        self.start = datetime(2026, 10, 7, 12)
    def tearDown(self):
        self.c.close()
    def report(self, second, rx, tx=1000):
        with patch.object(push_sync, 'datetime') as clock:
            clock.now.return_value = self.start + timedelta(seconds=second)
            clock.fromisoformat = datetime.fromisoformat
            push_sync._save_traffic(self.c, 'CCR2116', [{'name': 'WAN1-CLARO', 'rx_bytes': rx, 'tx_bytes': tx}])
        row = self.c.execute('SELECT * FROM push_router_traffic').fetchone()
        return dict(row) if row else None
    def test_cached_and_burst_reports_keep_baseline(self):
        self.report(0, 0)
        measured = self.report(2, 100_000_000)
        self.assertEqual(measured['rx_bps'], 400_000_000)
        self.assertEqual(self.report(2.4, 100_000_000), measured)
        self.assertEqual(self.report(3, 150_000_000), measured)
        self.assertEqual(self.report(4, 200_000_000)['rx_bps'], 400_000_000)
    def test_real_zero_is_not_hidden(self):
        self.report(0, 0)
        self.report(2, 100_000_000)
        self.assertEqual(self.report(4, 100_000_000)['rx_bps'], 0)
    def test_invalid_sample_does_not_destroy_measurement(self):
        self.report(0, 0)
        measured = self.report(2, 100_000_000)
        for invalid in (None, '', 'bad', '-1', 'NaN'):
            self.assertEqual(self.report(4, invalid), measured)
        self.assertEqual(self.report(4, 200_000_000)['rx_bps'], 400_000_000)
    def test_large_counters_keep_integer_precision(self):
        counter = 2**54 + 1
        self.report(0, counter)
        self.assertEqual(self.report(2, counter + 3)['rx_bps'], 12)
    def test_reset_rebaselines_and_recovers(self):
        self.report(0, 100_000_000)
        self.assertEqual(self.report(2, 0)['rx_bps'], 0)
        self.assertEqual(self.report(4, 100_000_000)['rx_bps'], 400_000_000)
if __name__ == '__main__':
    unittest.main()
