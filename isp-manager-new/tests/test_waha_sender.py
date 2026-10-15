"""Regression tests for authenticated WAHA sender normalization (no network)."""
import ast
import re
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import Mock

class SenderTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'waha_suite.py'
        if not path.exists(): path=Path('waha_suite_fixed.py')
        source=ast.parse(path.read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='incoming_phone')
        self.api=Mock()
        self.scope={'re':re,'urllib':urllib,'api':self.api,'APIError':ValueError}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'sender','exec'),self.scope)
        self.resolve=lambda sender:self.scope['incoming_phone']({'from':sender},{'session_name':'default'})
    def test_regular_phone_unchanged(self):
        self.assertEqual(self.resolve('18095550123@c.us'),'18095550123')
        self.api.assert_not_called()
    def test_internal_phone_normalized(self):
        self.assertEqual(self.resolve('18095550123@s.whatsapp.net'),'18095550123')
    def test_private_id_resolved_by_provider(self):
        self.api.return_value={'lid':'245896994390182@lid','pn':'18095550123@c.us'}
        self.assertEqual(self.resolve('245896994390182@lid'),'18095550123')
        self.assertIn('245896994390182%40lid',self.api.call_args.args[0])
    def test_unresolved_id_never_becomes_phone(self):
        self.api.return_value={'lid':'245896994390182@lid','pn':None}
        with self.assertRaises(ValueError):self.resolve('245896994390182@lid')
    def test_mismatched_mapping_rejected(self):
        self.api.return_value={'lid':'999999999999@lid','pn':'18095550123@c.us'}
        with self.assertRaises(ValueError):self.resolve('245896994390182@lid')
    def test_groups_and_status_are_not_customer_accounts(self):
        for sender in ('12345678@g.us','status@broadcast','12345678@newsletter'):
            self.assertIsNone(self.resolve(sender))
        self.api.assert_not_called()
    def test_malformed_phone_suffix_rejected(self):
        self.assertIsNone(self.resolve('18095550123@cxus'))
    def test_api_failure_is_not_silently_accepted(self):
        self.api.side_effect=ValueError('unreachable')
        with self.assertRaises(ValueError):self.resolve('245896994390182@lid')
if __name__=='__main__':unittest.main()
