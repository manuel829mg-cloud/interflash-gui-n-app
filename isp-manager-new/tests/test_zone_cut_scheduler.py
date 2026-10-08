import ast
import unittest
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

source = ast.parse((Path(__file__).parents[1] / "zone_cut_scheduler.py").read_text())
helper = next(
    node for node in source.body
    if isinstance(node, ast.FunctionDef) and node.name == "_run_billing_once_per_day"
)
module = types.ModuleType("zone_scheduler_under_test")
module.run_billing = Mock(return_value=(2, 3, 0))
exec(
    compile(ast.Module(body=[helper], type_ignores=[]), "zone_cut_scheduler.py", "exec"),
    module.__dict__,
)


class ZoneBillingScheduleTests(unittest.TestCase):
    def test_runs_on_startup_then_once_per_dominican_local_date(self):
        first = datetime(2026, 10, 7, 9, 0)
        last_date, result = module._run_billing_once_per_day(first, None)
        self.assertEqual(last_date, first.date())
        self.assertEqual(result, (2, 3, 0))
        module.run_billing.assert_called_once_with()

        same_day = first + timedelta(hours=10)
        same_date, result = module._run_billing_once_per_day(same_day, last_date)
        self.assertEqual(same_date, first.date())
        self.assertIsNone(result)
        module.run_billing.assert_called_once_with()

        next_day = first + timedelta(days=1)
        next_date, result = module._run_billing_once_per_day(next_day, same_date)
        self.assertEqual(next_date, next_day.date())
        self.assertEqual(result, (2, 3, 0))
        self.assertEqual(module.run_billing.call_count, 2)


if __name__ == "__main__":
    unittest.main()
