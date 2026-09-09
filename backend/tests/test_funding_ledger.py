import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sumika_core.funding_ledger import FundingLedger


def stamp(hours=0):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def snapshot(**overrides):
    return {
        "provider": "provider-a", "account_revision": "account-v1", "balance": "100.00", "unit": "CNY",
        "source": "cash", "observed_at": stamp(-1), "expires_at": stamp(2), "entitlement_expires_at": stamp(24),
        **overrides,
    }


class FundingLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledgers = []

    def tearDown(self):
        for ledger in reversed(self.ledgers):
            ledger.close()

    def ledger(self, data_dir=None):
        instance = FundingLedger(data_dir)
        self.ledgers.append(instance)
        return instance

    def close_ledger(self, ledger):
        ledger.close()
        self.ledgers.remove(ledger)

    def test_exact_cash_and_arbitrary_credit_units(self):
        ledger = self.ledger()
        ledger.observe(snapshot(balance="10.50"))
        ledger.observe(snapshot(unit="magicube", source="grant", balance="7", unit_value_cny="0.125", observed_at=stamp(-0.5), expires_at=stamp(3)))
        self.assertEqual(ledger.quote("provider-a", "account-v1", "1.25", "CNY", source="cash")["available"], Decimal("10.50"))
        self.assertEqual(ledger.quote("provider-a", "account-v1", 4, "magicube", source="grant")["available"], Decimal(7))

    def test_request_trace_is_durable_idempotent_and_never_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.ledger(directory)
            ledger.observe(snapshot())
            ledger.reserve("request", "provider-a", "account-v1", "1", "CNY", source="cash")
            ledger.record_request_trace("request", "a" * 64, "model")
            ledger.record_request_trace("request", "a" * 64, "model")
            ledger.reserve("other", "provider-a", "account-v1", "1", "CNY", source="cash")
            with self.assertRaisesRegex(ValueError, "another request"):
                ledger.record_request_trace("other", "a" * 64, "model")
            with self.assertRaisesRegex(ValueError, "different upstream trace"):
                ledger.record_request_trace("request", "b" * 64, "model")
            self.close_ledger(ledger)
            ledger = self.ledger(directory)
            self.assertEqual(ledger.match_request_trace("provider-a", "account-v1", "a" * 64, "model")[0]["request_id"], "request")
            self.assertEqual(ledger.match_request_trace("provider-a", "other-account", "a" * 64, "model"), [])
            with self.assertRaisesRegex(ValueError, "model"):
                ledger.match_request_trace("provider-a", "account-v1", "a" * 64, "other-model")
            self.close_ledger(ledger)

    def test_released_request_cannot_gain_a_receipt_trace(self):
        ledger = self.ledger()
        ledger.observe(snapshot())
        ledger.reserve("request", "provider-a", "account-v1", "1", "CNY", source="cash")
        ledger.settle("request", request_not_sent=True)
        with self.assertRaises(ValueError):
            ledger.record_request_trace("request", "a" * 64, "model")

    def test_account_revision_and_source_are_isolated(self):
        ledger = self.ledger()
        ledger.observe(snapshot())
        ledger.observe(snapshot(account_revision="account-v2", source="purchased", balance="30", observed_at=stamp(-0.5), expires_at=stamp(3)))
        ledger.reserve("cash-a", "provider-a", "account-v1", 80, "CNY", source="cash")
        self.assertEqual(ledger.projection("provider-a", "account-v2", "CNY", source="purchased")["available"], Decimal(30))
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(20))
        with self.assertRaisesRegex(ValueError, "fresh funding"):
            ledger.reserve("wrong-source", "provider-a", "account-v1", 1, "CNY", source="purchased")

    def test_same_account_grant_cash_and_unknown_pockets_never_mix(self):
        ledger = self.ledger()
        ledger.observe(snapshot(provider="deepseek-official", source="grant", pocket_id="grant-early", balance="9.50", entitlement_expires_at=stamp(4)))
        ledger.observe(snapshot(provider="deepseek-official", source="cash", pocket_id="cash", balance="20", observed_at=stamp(-0.5), expires_at=stamp(3)))
        ledger.observe(snapshot(provider="moark", source="unknown", pocket_id="package-9.9965", balance="9.9965", observed_at=stamp(-0.25), expires_at=stamp(4)))
        ledger.reserve("deepseek-grant", "deepseek-official", "account-v1", 9, "CNY", source="grant", pocket_id="grant-early")
        self.assertEqual(ledger.projection("deepseek-official", "account-v1", "CNY", source="cash", pocket_id="cash")["available"], Decimal(20))
        self.assertEqual(ledger.quote("moark", "account-v1", "9.9965", "CNY", source="unknown", pocket_id="package-9.9965")["available"], Decimal("9.9965"))

    def test_duplicate_reservation_is_idempotent_and_conflicts_reject(self):
        ledger = self.ledger()
        ledger.observe(snapshot())
        first = ledger.reserve("request-a", "provider-a", "account-v1", "25.00", "CNY", source="cash")
        second = ledger.reserve("request-a", "provider-a", "account-v1", "25.00", "CNY", source="cash")
        self.assertEqual(first, second)
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(75))
        with self.assertRaises(ValueError):
            ledger.reserve("request-a", "provider-a", "account-v1", 20, "CNY", source="cash")

    def test_concurrent_ledger_instances_cannot_overspend(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.ledger(directory)
            second = self.ledger(directory)
            try:
                first.observe(snapshot())

                def reserve(ledger, request_id):
                    try:
                        ledger.reserve(request_id, "provider-a", "account-v1", 80, "CNY", source="cash")
                        return True
                    except ValueError:
                        return False

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda pair: reserve(*pair), ((first, "one"), (second, "two"))))
                self.assertEqual(sum(results), 1)
            finally:
                self.close_ledger(first)
                self.close_ledger(second)

    def test_unknown_send_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.ledger(directory)
            reopened = None
            try:
                ledger.observe(snapshot())
                ledger.reserve("unknown-send", "provider-a", "account-v1", 80, "CNY", source="cash")
                ledger.settle("unknown-send")
                reopened = self.ledger(directory)
                self.assertEqual(reopened.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(20))
                with self.assertRaisesRegex(ValueError, "fresh funding"):
                    reopened.reserve("too-large", "provider-a", "account-v1", 30, "CNY", source="cash")
            finally:
                self.close_ledger(ledger)
                if reopened is not None:
                    self.close_ledger(reopened)

    def test_stale_and_expiring_evidence_cannot_be_reserved(self):
        ledger = self.ledger()
        ledger.observe(snapshot(observed_at=stamp(-3), expires_at=stamp(-1), entitlement_expires_at=stamp(4)))
        with self.assertRaisesRegex(ValueError, "fresh funding"):
            ledger.reserve("stale", "provider-a", "account-v1", 1, "CNY", source="cash")
        ledger.observe(snapshot(observed_at=stamp(0), expires_at=stamp(3), entitlement_expires_at=stamp(1)))
        with self.assertRaisesRegex(ValueError, "outlives entitlement"):
            ledger.reserve("late", "provider-a", "account-v1", 1, "CNY", source="cash", valid_until=stamp(2))

    def test_bill_reconciliation_is_explicit_and_replayed_balance_cannot_restore_spend(self):
        ledger = self.ledger()
        ledger.observe(snapshot(balance=100))
        receipt = ledger.reserve("sent", "provider-a", "account-v1", 70, "CNY", source="cash")
        ledger.settle("sent", 60)
        settled = ledger.reconcile_receipt("sent", 60, "receipt-sent")
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(40))
        ledger.observe(snapshot(balance=100, observed_at=stamp(-0.5), expires_at=stamp(3)))
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(40))
        reconciled_at = settled["settled_at"] + timedelta(seconds=1)
        ledger.observe(snapshot(balance=80, observed_at=reconciled_at.isoformat(), expires_at=(reconciled_at + timedelta(hours=4)).isoformat(), included_request_ids=["sent"]), now=reconciled_at)
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(80))
        with self.assertRaisesRegex(ValueError, "replay"):
            ledger.observe(snapshot(balance=100, observed_at=stamp(-1), expires_at=stamp(2)), now=reconciled_at)
        self.assertEqual(receipt["sequence"], 1)

    def test_zero_settlement_releases_hold_and_cannot_be_reconciled_early(self):
        ledger = self.ledger()
        base = datetime.now(timezone.utc)
        initial = {
            **snapshot(), "observed_at": (base - timedelta(hours=2)).isoformat(),
            "expires_at": (base + timedelta(hours=2)).isoformat(), "entitlement_expires_at": (base + timedelta(hours=4)).isoformat(),
        }
        ledger.observe(initial, now=base)
        ledger.reserve("zero", "provider-a", "account-v1", 40, "CNY", source="cash", now=base)
        settled_at = base + timedelta(minutes=30)
        ledger.settle("zero", estimated=0, now=base)
        receipt = ledger.reconcile_receipt("zero", 0, "receipt-zero", now=settled_at)
        self.assertEqual(receipt["settled_at"], settled_at)
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash", now=settled_at)["available"], Decimal(100))
        with self.assertRaisesRegex(ValueError, "predates settlement"):
            ledger.observe({**initial, "balance": 100, "observed_at": (base + timedelta(minutes=15)).isoformat(),
                            "expires_at": (base + timedelta(hours=3)).isoformat(), "included_request_ids": ["zero"]}, now=settled_at)

    def test_bundle_reservation_is_atomic_and_idempotent(self):
        ledger = self.ledger()
        ledger.observe(snapshot(balance=30))
        ledger.observe(snapshot(source="grant", pocket_id="grant", balance=20, observed_at=stamp(-0.5), expires_at=stamp(3)))
        allocations = [
            {"provider": "provider-a", "account_revision": "account-v1", "unit": "CNY", "source": "cash", "amount": 20},
            {"provider": "provider-a", "account_revision": "account-v1", "unit": "CNY", "source": "grant", "pocket_id": "grant", "amount": 20},
        ]
        first = ledger.reserve_bundle("bundle", allocations)
        self.assertEqual(first, ledger.reserve_bundle("bundle", allocations))
        self.assertEqual(len(first["allocations"]), 2)
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(10))
        settled = ledger.settle("bundle", [10, 0])
        self.assertEqual([row["actual"] for row in settled["allocations"]], [Decimal(10), Decimal(0)])
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="grant", pocket_id="grant")["available"], Decimal(20))
        failed = self.ledger()
        failed.observe(snapshot(balance=30))
        failed.observe(snapshot(source="grant", pocket_id="grant", balance=20, observed_at=stamp(-0.5), expires_at=stamp(3)))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            failed.reserve_bundle("fails", [{**allocations[0], "amount": 20}, {**allocations[1], "amount": 30}])
        self.assertEqual(failed.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(30))

    def test_sequence_reconciliation_only_absorbs_known_settled_requests(self):
        ledger = self.ledger()
        ledger.observe(snapshot())
        first = ledger.reserve("one", "provider-a", "account-v1", 20, "CNY", source="cash")
        ledger.reserve("two", "provider-a", "account-v1", 20, "CNY", source="cash")
        ledger.settle("one", 10)
        settled = ledger.reconcile_receipt("one", 10, "receipt-one")
        ledger.settle("two")
        reconciled_at = settled["settled_at"] + timedelta(seconds=1)
        ledger.observe(snapshot(balance=90, observed_at=reconciled_at.isoformat(), expires_at=(reconciled_at + timedelta(hours=3)).isoformat(), includes_through=first["sequence"]), now=reconciled_at)
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(70))

    def test_usage_estimate_is_not_a_receipt_and_receipt_can_adjust_it(self):
        ledger = self.ledger()
        ledger.observe(snapshot())
        ledger.reserve("estimated", "provider-a", "account-v1", 40, "CNY", source="cash")
        estimate = ledger.settle("estimated", estimated=10)
        self.assertEqual(estimate["state"], "estimated")
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(90))
        with self.assertRaisesRegex(ValueError, "receipt-confirmed"):
            ledger.observe(snapshot(balance=90, observed_at=stamp(-0.5), expires_at=stamp(3), included_request_ids=["estimated"]))
        receipt = ledger.reconcile_receipt("estimated", 2, "receipt-estimated")
        self.assertEqual(receipt["actual"], Decimal(2))
        self.assertEqual(receipt["estimated"], Decimal(10))
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(98))
        self.assertEqual(ledger.reconcile_receipt("estimated", 2, "receipt-estimated"), receipt)
        with self.assertRaises(ValueError):
            ledger.reconcile_receipt("estimated", 3, "receipt-other")

    def test_only_proven_unsent_requests_release_funding(self):
        ledger = self.ledger()
        ledger.observe(snapshot())
        ledger.reserve("unsent", "provider-a", "account-v1", 40, "CNY", source="cash")
        ledger.settle("unsent", request_not_sent=True)
        self.assertEqual(ledger.projection("provider-a", "account-v1", "CNY", source="cash")["available"], Decimal(100))
        ledger.reserve("uncertain", "provider-a", "account-v1", 40, "CNY", source="cash")
        ledger.settle("uncertain")
        with self.assertRaisesRegex(ValueError, "cannot be released"):
            ledger.settle("uncertain", request_not_sent=True)


if __name__ == "__main__":
    unittest.main()
