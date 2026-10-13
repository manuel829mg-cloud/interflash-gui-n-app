"""Regression checks for the generated MikroTik provisioning agent.

These checks are deliberately offline: never execute RouterOS commands in tests.
"""
import unittest
from unittest.mock import patch

import suspension_agent


class ProvisioningAgentTests(unittest.TestCase):
    def test_pppoe_creation_reports_router_errors(self):
        with patch.object(suspension_agent.datetime, "now") as now:
            now.return_value.isoformat.return_value = "2026-10-13T21:00:00.000000"
            script = suspension_agent._agent_rsc("https://example.invalid", "test-token")
        self.assertIn('on-error={ :set createResult "ERROR_CREACION_PPPOE"; }', script)
        self.assertIn('PPPOE_NO_VERIFICADO', script)
        self.assertIn('PPPOE_CREADO', script)
        self.assertIn('"&ok=" . $created . "&result=" . $createResult', script)
        self.assertIn('disabled=yes', script)

    def test_existing_pppoe_is_not_overwritten(self):
        script = suspension_agent._agent_rsc("https://example.invalid", "test-token")
        self.assertIn('result=PPPOE_YA_EXISTE', script)
        self.assertNotIn('/ppp secret set [find where name=$user] password=$pass', script)


if __name__ == "__main__":
    unittest.main()
