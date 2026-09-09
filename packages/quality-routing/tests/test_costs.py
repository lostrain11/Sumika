import time
import unittest
from decimal import Decimal

from quality_routing import Candidate, RoutingError
from quality_routing.costs import FundingLot, RouteQuote, cost_order, quote_cost


class FundingQuoteTests(unittest.TestCase):
    def lot(self, kind, **overrides):
        return FundingLot(**{"lot_id": "pool", "kind": kind, "remaining": 1000, "unit": "tokens",
                             "expires_at": time.time() + 3600, **overrides})

    def quote(self, lot, **overrides):
        return quote_cost(**{"input_tokens": 80, "output_tokens": 20, "cash_price_cny": "3", "lots": (lot,),
                             "funding_required": True, **overrides})

    def test_gift_and_purchased_resources_have_different_economic_costs(self):
        gift = self.quote(self.lot("grant"))
        purchased = self.quote(self.lot("purchased", value_per_unit_cny="0.002"))
        self.assertTrue(gift.free)
        self.assertFalse(purchased.free)
        self.assertEqual(gift.cash_due_cny, purchased.cash_due_cny)
        self.assertEqual(purchased.resource_value_cny, Decimal("0.2"))
        self.assertEqual(purchased.effective_cost_cny, Decimal("0.2"))
        self.assertLess(cost_order(gift), cost_order(purchased))

    def test_unknown_acquisition_source_or_price_is_not_free(self):
        for kind in ("unknown", "purchased"):
            quote = self.quote(self.lot(kind))
            self.assertEqual(quote.cash_due_cny, 0)
            self.assertIsNone(quote.effective_cost_cny)
            self.assertFalse(quote.free)

    def test_zero_price_purchased_pack_still_is_not_a_free_entitlement(self):
        self.assertFalse(self.quote(self.lot("purchased", value_per_unit_cny="0")).free)

    def test_earliest_expiry_order_is_identical_to_resource_reservations(self):
        early = self.lot("purchased", lot_id="early", remaining=50, value_per_unit_cny="0.01")
        later = self.lot("grant", lot_id="later", expires_at=early.expires_at + 100)
        result = quote_cost(input_tokens=80, output_tokens=20, cash_price_cny="4", lots=(later, early), funding_required=True)
        self.assertEqual([(row.lot_id, row.quantity) for row in result.allocations], [("early", 50), ("later", 50)])
        self.assertEqual(result.effective_cost_cny, Decimal("0.5"))
        self.assertEqual(result.funding_kind, "mixed")

    def test_resource_expiry_or_insufficiency_does_not_fall_back_to_cash(self):
        for lot in (self.lot("grant", remaining=99), self.lot("grant", expires_at=time.time() - 1)):
            quote = self.quote(lot)
            self.assertFalse(quote.available)
            self.assertIsNone(quote.effective_cost_cny)

    def test_cash_balance_is_not_zero_price_and_insufficient_balance_blocks(self):
        result = quote_cost(input_tokens=80, output_tokens=20, cash_price_cny="3", cash_balance_cny="10")
        self.assertEqual(result.funding_kind, "cash")
        self.assertEqual(result.cash_due_cny, 3)
        self.assertFalse(result.free)
        self.assertFalse(quote_cost(input_tokens=80, output_tokens=20, cash_price_cny="3", cash_balance_cny="2").available)

    def test_unknown_cash_balance_and_unknown_price_stay_distinct(self):
        quote = quote_cost(input_tokens=80, output_tokens=20, cash_price_cny=None, cash_balance_cny="10")
        self.assertIsNone(quote.effective_cost_cny)
        self.assertFalse(quote.free)
        self.assertEqual(quote.cash_balance_cny, 10)

    def test_request_allowance_and_mixed_units(self):
        request = self.lot("grant", unit="requests", remaining=1)
        self.assertTrue(self.quote(request).free)
        self.assertFalse(quote_cost(input_tokens=80, output_tokens=20, cash_price_cny="3",
                                   lots=(request, self.lot("grant", lot_id="other")), funding_required=True).available)

    def test_legacy_prepaid_without_provenance_stays_unknown(self):
        candidate = Candidate("model", "account", "model", "api", prepaid_tokens=1000, prepaid_until=time.time() + 3600)
        self.assertIsNone(candidate.estimate(80, 20))
        self.assertFalse(candidate.quote(80, 20).free)

    def test_serialization_preserves_money_and_funding(self):
        quote = self.quote(self.lot("purchased", value_per_unit_cny="0.000123456789"))
        self.assertEqual(RouteQuote.from_dict(quote.to_dict()), quote)

    def test_invalid_values_are_rejected(self):
        for value in (True, -1, "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(RoutingError):
                self.lot("purchased", value_per_unit_cny=value)
        with self.assertRaises(RoutingError):
            self.lot("grant", value_per_unit_cny="0.1")
