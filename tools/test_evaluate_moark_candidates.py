"""No-network checks of paid evaluation limits and content-free diagnostics."""
from decimal import Decimal
import unittest

from tools.evaluate_moark_candidates import CashBudget, diagnostics
from sumika_core.providers.guard import RequestNotSent


class MoarkEvaluationTests(unittest.TestCase):
    def test_exhaustion_stops_before_next_send(self):
        budget = CashBudget("0.50")
        budget.reserve("0.49")
        with self.assertRaises(RequestNotSent):
            budget.reserve("0.02")
        self.assertEqual(budget.reserved, Decimal("0.49"))
        budget.reserve("0.01")
        self.assertEqual(budget.reserved, budget.limit)

    def test_invalid_limits_and_default_free_only(self):
        for limit in (True, "NaN", "0.51", "-0.1"):
            with self.assertRaises(ValueError):
                CashBudget(limit)
        with self.assertRaises(RequestNotSent):
            CashBudget("0").reserve("0.000001")

    def test_diagnostics_never_return_answer(self):
        private = '<think>PRIVATE_TEXT</think>```json\n{"x":1}\n```'
        result = diagnostics(private)
        self.assertTrue(result["inline_reasoning"])
        self.assertFalse(result["valid_json"])
        self.assertTrue(all(type(value) is bool for value in result.values()))


if __name__ == "__main__":
    unittest.main()
