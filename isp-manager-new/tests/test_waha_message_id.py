"""WAHA send/ack identifier regression tests without network or credentials."""
import ast
from pathlib import Path
import re
import unittest
from unittest.mock import Mock

class MessageIdTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'waha_suite.py').read_text())
        nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in ('message_id', 'send_text')]
        self.api = Mock()
        self.scope = {'re': re, 'api': self.api, 'config': lambda: {'session_name': 'default'}, 'APIError': ValueError}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'waha', 'exec'), self.scope)

    def test_string_and_webjs_ids_match(self):
        mid = 'true_18095550123@c.us_ABC123'
        for response in ({'id': mid}, {'id': {'_serialized': mid, 'id': 'ABC123'}}):
            with self.subTest(response=response):
                self.api.return_value = response
                self.assertEqual(self.scope['send_text']('18095550123', 'Hola'), (True, 'waha:default:' + mid, ''))
                self.assertEqual(self.scope['message_id'](response), mid)

    def test_missing_or_malformed_id_is_not_confirmed(self):
        for response in ([], {}, {'success': True}, {'id': ''}, {'id': '   '}, {'id': 1}, {'id': {'id': 'ABC123'}}, {'id': {'_serialized': {}}}):
            with self.subTest(response=response):
                self.api.return_value = response
                ok, pid, error = self.scope['send_text']('18095550123', 'Hola')
                self.assertFalse(ok)
                self.assertEqual(pid, '')
                self.assertIn('Comprueba el chat', error)

    def test_provider_failure_is_preserved(self):
        self.api.side_effect = ValueError('WAHA respondió HTTP 500')
        self.assertEqual(self.scope['send_text']('18095550123', 'Hola'), (False, '', 'WAHA respondió HTTP 500'))

if __name__ == '__main__':
    unittest.main()
