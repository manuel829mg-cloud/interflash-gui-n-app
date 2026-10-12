import ast
import sqlite3
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path

source = ast.parse((Path(__file__).parents[1] / 'mikrotik_ai.py').read_text())
nodes = [n for n in source.body if isinstance(n, ast.FunctionDef)
         and n.name in ('snapshot', 'wan_snapshot', '_safe_value')]
module = types.ModuleType('snapshot_test')
module.datetime = datetime
module.MAX_TABLES = 10
module.MAX_ROWS = 4
module.WAN_INTERFACES = tuple(f'WAN{i}-{p}' for i, p in enumerate(('CLARO','CLARO','ALTICE','ALTICE'), 1))
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'mikrotik_ai.py', 'exec'), module.__dict__)

class SnapshotTests(unittest.TestCase):
    def database(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE wan_line_health(router_name,interface_name,packet_loss,updated_at)')
        c.execute('CREATE TABLE push_router_traffic(router_name,interface_name,rx_bps,updated_at,token)')
        return c

    def test_wans_survive_table_limit_and_other_routers(self):
        c = self.database()
        for i in range(12):
            c.execute(f'CREATE TABLE a_ppp_{i}(value)')
        for iface in module.WAN_INTERFACES:
            c.execute('INSERT INTO wan_line_health VALUES(?,?,?,?)', ('CCR2116', iface, 0, datetime.now().isoformat()))
            c.execute('INSERT INTO push_router_traffic VALUES(?,?,?,?,?)', ('CCR2116', iface, 100, datetime.now().isoformat(), 'private'))
        c.execute('INSERT INTO wan_line_health VALUES(?,?,?,?)', ('OTHER', module.WAN_INTERFACES[0], 100, datetime.now().isoformat()))
        module.base = types.SimpleNamespace(db=lambda:c)
        data = module.snapshot()
        self.assertIn('wan_line_health', data['tablas'])
        self.assertIn('push_router_traffic', data['tablas'])
        self.assertEqual(len(data['wan']), 4)
        self.assertEqual(len(data['wan'][0]['prueba_ping']), 2)
        for wan in data['wan']:
            self.assertEqual(wan['trafico'][0]['token'], '[omitido]')
            self.assertEqual(wan['trafico'][0]['vigencia'], 'reciente')

    def test_absent_and_stale_data_are_explicit(self):
        c = self.database()
        c.execute('INSERT INTO wan_line_health VALUES(?,?,?,?)', ('CCR2116', module.WAN_INTERFACES[0], 0, (datetime.now()-timedelta(hours=2)).isoformat()))
        c.execute('INSERT INTO wan_line_health VALUES(?,?,?,?)', ('CCR2116', module.WAN_INTERFACES[1], 0, None))
        data = module.wan_snapshot(c, ['wan_line_health'])
        self.assertEqual(data[0]['prueba_ping'][0]['vigencia'], 'desactualizada')
        self.assertEqual(data[1]['prueba_ping'][0]['vigencia'], 'desconocida')
        self.assertEqual(data[2]['prueba_ping'], [])
        self.assertEqual(data[0]['trafico'], [])
        c.close()

if __name__ == '__main__':
    unittest.main()
