from __future__ import annotations

import threading
import unittest
from dataclasses import replace
from decimal import Decimal

from quality_routing import Budget, BudgetRule, Candidate, Coordinator, Node, Outcome, Plan, QualityEvidence, Quote, RoutingError, Scope, Verification, estimate_quote, select_candidate


def candidate(name="leader", **values):
    return Candidate(name, "account-" + name, name, "api", authorized=True, available=True,
                     external=False, **values)


def node(name="first", **values):
    return Node(name, "Compute and verify", "arithmetic", "leader", acceptance=("Exact value",), **values)


SCOPE = Scope("assistant-a", "conversation-a")
QUOTE = Quote("1", "2", "3", 30, 1000000)


class BudgetTests(unittest.TestCase):
    def test_strict_and_threshold(self):
        for cost, accepted in (("6", True), ("8", True), ("8.01", False)):
            budget = Budget(QUOTE)
            if accepted:
                budget.reserve("one", Decimal(cost), 10)
            else:
                with self.assertRaisesRegex(RoutingError, "extreme"):
                    budget.reserve("one", Decimal(cost), 10)

    def test_only_amount_condition_does_not_pause(self):
        budget = Budget(Quote("1", "4", "10", 10, 100))
        self.assertEqual(budget.reserve("one", Decimal("16"), 10), "overrun-warning")

    def test_concurrent_reservations_are_counted(self):
        budget = Budget(QUOTE)
        budget.reserve("one", Decimal(5), 10)
        with self.assertRaisesRegex(RoutingError, "extreme"):
            budget.reserve("two", Decimal(4), 10)
        budget.settle("one", Decimal(4), 8)
        budget.settle("one", Decimal(4), 8)
        self.assertEqual(budget.spent_cny, 4)
        self.assertEqual(budget.calls, 1)
        budget.reserve("two", Decimal(4), 10)

    def test_unknown_cost_and_usage_remain_bounded(self):
        budget = Budget(Quote(None, None, None, 1, 20))
        self.assertEqual(budget.reserve("one", None, 20), "unpriced-bounded")
        budget.settle("one", None, None)
        self.assertEqual(budget.unpriced_calls, 1)
        self.assertEqual(budget.tokens, 20)
        with self.assertRaisesRegex(RoutingError, "call-limit"):
            budget.reserve("two", None, 1)

    def test_invalid_rules(self):
        for value in ("NaN", "Infinity", "-1", True, "0.99"):
            with self.assertRaises(RoutingError):
                BudgetRule(multiplier=value)
        with self.assertRaises(RoutingError):
            BudgetRule(extra_cny="-0.1")

    def test_restore_preserves_inflight_and_rule(self):
        budget = Budget(QUOTE, BudgetRule("3", "9"))
        budget.reserve("one", Decimal("2.5"), 10)
        restored = Budget.restore(budget.to_dict())
        self.assertEqual(restored.to_dict(), budget.to_dict())

    def test_extreme_overrun_does_not_stop_verified_zero_cost_call(self):
        budget = Budget(QUOTE)
        budget.record_prior_call("prior", Decimal(9), None, 10)
        budget.reserve("local", Decimal(0), 10)
        with self.assertRaisesRegex(RoutingError, "extreme"):
            budget.reserve("paid", Decimal("0.01"), 10)


class SelectionTests(unittest.TestCase):
    def test_cheaper_without_quality_evidence_cannot_replace_baseline(self):
        leader = candidate(fixed_cash="3")
        cheap = candidate("cheap", fixed_cash="0")
        self.assertEqual(select_candidate(node(), [leader, cheap], {"leader", "cheap"}).candidate_id, "leader")

    def test_fresh_matching_evidence_allows_cheaper(self):
        leader = candidate(fixed_cash="3")
        cheap = candidate("cheap", fixed_cash="0", quality=(QualityEvidence("arithmetic", "leader", 100, "suite-a"),))
        self.assertEqual(select_candidate(node(), [leader, cheap], {"leader", "cheap"}, now=99).candidate_id, "cheap")
        self.assertEqual(select_candidate(node(), [leader, cheap], {"leader", "cheap"}, now=100).candidate_id, "leader")

    def test_authorization_and_external_are_not_quality_evidence(self):
        leader = replace(candidate(), external=True)
        with self.assertRaises(RoutingError):
            select_candidate(node(), [leader], {"leader"})
        with self.assertRaises(RoutingError):
            select_candidate(node(), [replace(leader, authorized=False)], {"leader"}, external_allowed=True)

    def test_cache_pricing_does_not_double_count_tokens(self):
        priced = candidate(cash_per_million_input="2", cash_per_million_output="8", cached_input_rate="0.5")
        self.assertEqual(priced.estimate(1000000, 1000000, 500000), Decimal("9.25"))

    def test_unknown_quote_not_zero(self):
        quote = estimate_quote([node()], [candidate()], {"leader"}, external_allowed=False)
        self.assertIsNone(quote.high_cny)
        self.assertGreater(quote.max_calls, 1)

    def test_quote_includes_expensive_baseline_review_of_free_execution(self):
        leader = candidate(fixed_cash="3")
        cheap = candidate("cheap", fixed_cash="0", quality=(QualityEvidence("arithmetic", "leader", 10**12, "suite-a"),))
        quote = estimate_quote([node()], [leader, cheap], {"leader", "cheap"}, external_allowed=False)
        self.assertEqual(quote.low_cny, Decimal(3))
        unknown_leader = candidate()
        unknown = estimate_quote([node()], [unknown_leader, cheap], {"leader", "cheap"}, external_allowed=False)
        self.assertIsNone(unknown.high_cny)

    def test_quote_uses_paid_reviewer_for_logical_bounded_text_baseline(self):
        bounded_node = Node("bounded-text", "Compute and verify", "arithmetic", "bounded-text-v1", acceptance=("Exact value",))
        runner = candidate(
            "runner", fixed_cash="0",
            quality=(QualityEvidence("arithmetic", "bounded-text-v1", 10**12, "suite-bounded-text"),),
        )
        reviewer = candidate("paid-reviewer", cash_per_million_input="2", cash_per_million_output="5")
        quote = estimate_quote(
            [bounded_node], [runner, reviewer], {"runner", "paid-reviewer"}, external_allowed=False,
            review_candidate_id="paid-reviewer", review_output_tokens=4000,
        )
        self.assertEqual(bounded_node.baseline_id, "bounded-text-v1")
        self.assertEqual(quote.low_cny, Decimal("0.034048"))
        self.assertIsNotNone(quote.high_cny)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            engine.close()

    def engine(self, **options):
        options.setdefault("executor", lambda execution: Outcome("completed", "42", cash_cny="0"))
        options.setdefault("verifier", lambda execution, result: Verification(result.text == "42", ("fixture-exact",)))
        options.setdefault("permission", lambda execution: True)
        engine = Coordinator([candidate(fixed_cash="0")], **options)
        self.engines.append(engine)
        return engine

    def submit(self, engine, nodes=None, task_id="task", scope=SCOPE):
        engine.submit(Plan(task_id, scope, 1, tuple(nodes or [node()])), QUOTE, BudgetRule(), allowed_ids={"leader"})
        return engine

    def test_no_execution_before_confirmation(self):
        engine = self.submit(self.engine())
        self.assertEqual(engine.advance("task", SCOPE)["status"], "awaiting-confirmation")
        self.assertEqual(engine.status("task", SCOPE)["budget"]["calls"], 0)

    def test_dependency_results_and_verified_completion(self):
        engine = self.submit(self.engine(), [node(), node("second", dependencies=("first",))])
        engine.approve("task", SCOPE, 1)
        result = engine.wait("task", SCOPE)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["budget"]["calls"], 2)

    def test_cross_assistant_access_denied(self):
        engine = self.submit(self.engine())
        other = Scope("assistant-b", SCOPE.session_id)
        self.assertEqual(engine.list_tasks(other), [])
        with self.assertRaises(RoutingError):
            engine.approve("task", other, 1)

    def test_revision_preserves_unaffected_results(self):
        engine = self.submit(self.engine(), [node(), node("second", dependencies=("first",))])
        engine.approve("task", SCOPE, 1)
        engine.wait("task", SCOPE)
        updated = Plan("task", SCOPE, 2, (node(), replace(node("second", dependencies=("first",)), goal="New goal")))
        result = engine.revise(updated)
        self.assertEqual(result["states"], {"first": "completed", "second": "pending"})
        self.assertEqual(result["budget"]["quote"], QUOTE.to_dict())

    def test_ambiguous_result_is_never_retried(self):
        engine = self.submit(self.engine(executor=lambda execution: Outcome("unknown", possibly_sent=True)))
        engine.approve("task", SCOPE, 1)
        result = engine.wait("task", SCOPE)
        self.assertEqual(result["states"]["first"], "unknown")
        self.assertEqual(len(result["budget"]["reservations"]), 1)
        with self.assertRaises(RoutingError):
            engine.retry("task", SCOPE, "first")

    def test_scope_violation_cannot_pass_verification(self):
        engine = self.submit(self.engine(executor=lambda execution: Outcome("completed", "42", changed_files=("secret.py",))))
        engine.approve("task", SCOPE, 1)
        result = engine.wait("task", SCOPE)
        self.assertEqual(result["results"]["first"]["reason"], "file-scope-violation")

    def test_one_repair_then_replan(self):
        engine = self.submit(self.engine(verifier=lambda execution, outcome: Verification(False, reason="incorrect")))
        engine.approve("task", SCOPE, 1)
        engine.wait("task", SCOPE)
        engine.retry("task", SCOPE, "first")
        self.assertEqual(engine.wait("task", SCOPE)["states"]["first"], "needs-replan")
        with self.assertRaises(RoutingError):
            engine.retry("task", SCOPE, "first")

    def test_missing_host_cannot_execute(self):
        engine = self.submit(self.engine(executor=None))
        engine.approve("task", SCOPE, 1)
        self.assertEqual(engine.advance("task", SCOPE)["reason"], "host-executor-verifier-or-permission-unavailable")

    def test_events_do_not_contain_task_text(self):
        events = []
        engine = self.submit(self.engine(event_sink=events.append))
        self.assertNotIn("Compute", str(events))
        self.assertNotIn("42", str(events))

    def test_cancelled_late_result_charges_but_does_not_publish(self):
        started = threading.Event()
        release = threading.Event()
        def execute(execution):
            started.set()
            release.wait(2)
            return Outcome("completed", "42", cash_cny="1")
        engine = self.submit(self.engine(executor=execute))
        engine.approve("task", SCOPE, 1)
        engine.advance("task", SCOPE)
        self.assertTrue(started.wait(2))
        engine.cancel("task", SCOPE)
        release.set()
        engine.close()
        result = engine.status("task", SCOPE)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["results"], {})
        self.assertEqual(result["budget"]["spent_cny"], "1")

    def test_restore_never_replays_inflight(self):
        engine = self.submit(self.engine())
        value = engine.snapshot("task", SCOPE)
        value["states"]["first"] = "running"
        restored = self.engine()
        restored.restore(value)
        restored.approve("task", SCOPE, 1)
        self.assertEqual(restored.advance("task", SCOPE)["states"]["first"], "unknown")

    def test_cycles_and_parent_paths_rejected(self):
        with self.assertRaises(RoutingError):
            Plan("task", SCOPE, 1, (node(dependencies=("first",)),))
        with self.assertRaises(RoutingError):
            node(allowed_files=("../credentials",))

    def test_revision_cannot_expand_file_grant_or_lower_baseline(self):
        engine = self.submit(self.engine(), [node(allowed_files=("src/**",))])
        engine.approve("task", SCOPE, 1)
        with self.assertRaisesRegex(RoutingError, "file scope"):
            engine.revise(Plan("task", SCOPE, 2, (node(allowed_files=("credentials/**",)),)))
        with self.assertRaisesRegex(RoutingError, "quality baseline"):
            engine.revise(Plan("task", SCOPE, 2, (replace(node(), baseline_id="cheap"),)))
        result = engine.revise(Plan("task", SCOPE, 2, (node(allowed_files=("src/module.py",)),)))
        self.assertNotEqual(result["status"], "awaiting-confirmation")

    def test_candidate_identity_swap_does_not_inherit_task_authority(self):
        engine = self.submit(self.engine())
        engine.approve("task", SCOPE, 1)
        engine.set_candidates([replace(candidate(fixed_cash="0"), model_id="different-model")])
        result = engine.advance("task", SCOPE)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["budget"]["calls"], 0)
        with self.assertRaisesRegex(RoutingError, "not authorized"):
            engine.reserve_auxiliary("task", SCOPE, "aux", Decimal(0), 10, "leader")

    def test_ambiguous_failed_result_retains_account_reservation(self):
        engine = self.submit(self.engine(executor=lambda execution: Outcome("failed", possibly_sent=True)))
        engine.set_account_balance("account-leader", Decimal(5))
        engine.set_candidates([candidate(fixed_cash="5")])
        engine.approve("task", SCOPE, 1)
        result = engine.wait("task", SCOPE)
        self.assertEqual(result["states"]["first"], "unknown")
        self.assertEqual(len(result["budget"]["reservations"]), 1)
        self.submit(engine, task_id="second")
        engine.approve("second", SCOPE, 1)
        self.assertEqual(engine.advance("second", SCOPE)["reason"], "account-balance-exhausted-or-unpriced")


if __name__ == "__main__":
    unittest.main()
