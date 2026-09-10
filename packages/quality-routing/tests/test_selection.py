from __future__ import annotations

import unittest
from decimal import Decimal

from quality_routing import (
    Candidate,
    FixedEvaluationSample,
    RoutingError,
    SelectionCohort,
    SelectionEvidenceStore,
    qualify_candidate,
    resolve_binding,
)


NOW = 2_000_000_000.0


class MemoryMetadataStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_meta(self, key: str) -> str | None:
        return self.values.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self.values[key] = value


def candidate(candidate_id: str, price: str | None, *, effort: str | None = None) -> Candidate:
    return Candidate(
        candidate_id,
        "account-" + candidate_id.replace(":", "-"),
        "model-" + candidate_id,
        "api",
        reasoning_effort=effort,
        authorized=True,
        available=True,
        fixed_cash=price,
    )


def samples(candidate_id: str, *, purpose: str = "role", effort: str | None = None, total: int = 3):
    return tuple(
        FixedEvaluationSample(
            f"sample-{candidate_id.replace(':', '-')}-{index}",
            candidate_id,
            "build-1",
            purpose,
            "fixed-suite",
            "suite-1",
            Decimal("0.9"),
            True,
            NOW - 100,
            NOW + 100,
            effort,
        )
        for index in range(total)
    )


class SelectionCoreTests(unittest.TestCase):
    def test_store_uses_only_narrow_metadata_methods_and_round_trips(self):
        storage = MemoryMetadataStore()
        evidence = SelectionEvidenceStore(storage)
        cohort = SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"))
        evidence.register_cohort("assistant", cohort)
        for sample in samples("free"):
            self.assertTrue(evidence.record_sample("assistant", sample))
        self.assertFalse(evidence.record_sample("assistant", samples("free")[0]))
        cohorts, _priors, stored_samples = evidence.read("assistant")
        self.assertEqual(cohorts["role"], cohort)
        self.assertEqual(stored_samples, samples("free"))

    def test_three_fresh_fixed_samples_remain_required(self):
        with self.assertRaisesRegex(RoutingError, "at least three"):
            SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"), minimum_samples=2)
        cohort = SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"))
        result = qualify_candidate("free", "build-1", "role", None, cohort, (), samples("free", total=2), now=NOW)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["reason"], "successful-fixed-samples-required")

    def test_reasoning_effort_is_part_of_the_evidence_identity(self):
        cohort = SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"))
        candidate_id = "free:effort:high"
        wrong = qualify_candidate(candidate_id, "build-1", "role", "high", cohort, (),
                                  samples(candidate_id, effort="off"), now=NOW)
        right = qualify_candidate(candidate_id, "build-1", "role", "high", cohort, (),
                                  samples(candidate_id, effort="high"), now=NOW)
        self.assertFalse(wrong["qualified"])
        self.assertTrue(right["qualified"])

    def test_role_auto_uses_cost_order_for_free_candidates(self):
        cohort = SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"))
        candidates = [candidate("current", "0"), candidate("another", "0"), candidate("paid", "1")]
        evidence = samples("current") + samples("another") + samples("paid")
        result = resolve_binding(
            "role",
            "auto",
            "current",
            [item.candidate_id for item in candidates],
            candidates,
            {item.candidate_id: "build-1" for item in candidates},
            {item.candidate_id: "healthy" for item in candidates},
            cohort,
            (),
            evidence,
            now=NOW,
        )
        self.assertEqual(result["candidate_id"], "another")
        self.assertEqual(result["reason"], "cheapest-qualified-role")

    def test_role_auto_can_return_the_lowest_cost_paid_candidate(self):
        cohort = SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"))
        candidates = [candidate("costly", "2"), candidate("cheaper", "1")]
        evidence = samples("costly") + samples("cheaper")
        result = resolve_binding(
            "role",
            "auto",
            None,
            [item.candidate_id for item in candidates],
            candidates,
            {item.candidate_id: "build-1" for item in candidates},
            {item.candidate_id: "healthy" for item in candidates},
            cohort,
            (),
            evidence,
            now=NOW,
        )
        self.assertEqual(result["candidate_id"], "cheaper")
        self.assertEqual(result["reason"], "cheapest-qualified-role")

    def test_unknown_role_price_is_not_treated_as_free(self):
        cohort = SelectionCohort("role", "fixed-suite", "suite-1", Decimal("0.8"))
        unknown = candidate("unknown", None)
        result = resolve_binding(
            "role", "auto", None, ["unknown"], [unknown], {"unknown": "build-1"}, {"unknown": "healthy"},
            cohort, (), samples("unknown"), now=NOW,
        )
        self.assertIsNone(result["candidate_id"])
        self.assertEqual(result["candidates"][0]["reason"], "known-role-price-required")


if __name__ == "__main__":
    unittest.main()

