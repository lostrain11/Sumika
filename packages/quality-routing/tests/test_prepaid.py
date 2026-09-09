import time
import unittest
from decimal import Decimal

from quality_routing import Candidate, RoutingError


class PrepaidTests(unittest.TestCase):
    def candidate(self, **values):
        return Candidate("route", "account", "model", "api", **values)

    def test_only_bounded_fresh_estimate_is_zero(self):
        candidate = self.candidate(prepaid_tokens=100, prepaid_until=time.time() + 60, funding_kind="grant")
        self.assertEqual(candidate.estimate(60, 40), Decimal(0))
        self.assertIsNone(candidate.estimate(60, 41))
        self.assertIsNone(self.candidate(prepaid_tokens=100, prepaid_until=time.time() - 1).estimate(60, 40))

    def test_base_price_is_preserved_without_silent_fallback_beyond_quota(self):
        candidate = self.candidate(prepaid_tokens=100, prepaid_until=time.time() + 60,
                                   cash_per_million_input="2", cash_per_million_output="3", funding_kind="grant")
        self.assertEqual(candidate.estimate(60, 40), Decimal(0))
        self.assertIsNone(candidate.estimate(60, 50))
        self.assertFalse(candidate.quote(60, 50).available)
        self.assertEqual(candidate.cash_per_million_input, Decimal("2"))
        self.assertEqual(candidate.cash_per_million_output, Decimal("3"))

    def test_invalid_or_partial_allowance_rejected(self):
        for values in ({"prepaid_tokens": 5}, {"prepaid_until": 0},
                       {"prepaid_tokens": True, "prepaid_until": time.time()},
                       {"prepaid_tokens": 1, "prepaid_until": float("nan")}):
            with self.subTest(values=values), self.assertRaises(RoutingError):
                self.candidate(**values)
