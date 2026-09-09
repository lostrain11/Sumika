from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import threading
import time
import unittest

from quality_routing import BudgetRule, Candidate, Coordinator, Node, Outcome, Plan, QualityEvidence, Quote, RoutingError, Scope, Verification


SCOPE = Scope("synthetic", "complex")
QUOTE = Quote("0", "1", "3", 40, 1000000)


def node(name="draft", **values):
    return Node(name, "Synthetic scheduling analysis", "synthetic-scheduling-v1", "leader",
                acceptance=("Preserve dependencies and exact fees",), **values)


def candidate(name="leader", **values):
    return Candidate(name, "account-" + name, name, "api", authorized=True, available=True,
                     external=False, **values)


class ComplexCoordinatorTests(unittest.TestCase):
    def engine(self, *, nodes=None, pool=None, executor=None, verifier=None, quote=QUOTE, allowed=None):
        candidates = pool or [candidate(fixed_cash="1"), candidate("cheap", fixed_cash="0", quality=(
            QualityEvidence("synthetic-scheduling-v1", "leader", time.time() + 60, "synthetic-fixture-only"),))]
        engine = Coordinator(candidates, executor=executor or (lambda execution: Outcome("completed", "synthetic", cash_cny="0")),
                             verifier=verifier or (lambda execution, outcome: Verification(False, reason="injected-test-fault")),
                             permission=lambda execution: True)
        self.addCleanup(engine.close)
        engine.submit(Plan("task", SCOPE, 1, tuple(nodes or [node()])), quote, BudgetRule(),
                      allowed_ids=allowed or [item.candidate_id for item in candidates])
        engine.approve("task", SCOPE, 1)
        return engine

    def exhaust_repair(self, engine):
        engine.wait("task", SCOPE)
        engine.retry("task", SCOPE, "draft")
        return engine.wait("task", SCOPE)

    def test_repair_pins_original_then_upgrade_uses_baseline_once(self):
        seen = []
        engine = self.engine(executor=lambda execution: (seen.append(execution.candidate.candidate_id) or
                                                        Outcome("completed", "synthetic", cash_cny="0")))
        engine.wait("task", SCOPE)
        cheaper = candidate("a-new-cheaper", fixed_cash="0", quality=engine.candidates()[1].quality)
        engine.set_candidates([*engine.candidates(), cheaper])
        engine.retry("task", SCOPE, "draft")
        engine.wait("task", SCOPE)
        engine.upgrade("task", SCOPE, "draft")
        engine.wait("task", SCOPE)
        self.assertEqual(seen, ["cheap", "cheap", "leader"])
        with self.assertRaises(RoutingError):
            engine.upgrade("task", SCOPE, "draft")
        with self.assertRaises(RoutingError):
            engine.retry("task", SCOPE, "draft")

    def test_upgrade_rechecks_quality_authority_identity_and_budget(self):
        for alteration in ("unauthorized", "identity", "capability", "budget", "external"):
            with self.subTest(alteration=alteration):
                engine = self.engine(quote=replace(QUOTE, max_calls=2) if alteration == "budget" else QUOTE)
                self.exhaust_repair(engine)
                leader, cheap = engine.candidates()
                changes = {"unauthorized": {"authorized": False}, "identity": {"execution_revision": "changed"},
                           "capability": {"capabilities": ("code",)}, "external": {"external": True}}
                if alteration == "budget":
                    engine.upgrade("task", SCOPE, "draft")
                    self.assertEqual(engine.advance("task", SCOPE)["reason"], "budget-call-limit")
                else:
                    engine.set_candidates([replace(leader, **changes[alteration]), cheap])
                    with self.assertRaises(RoutingError):
                        engine.upgrade("task", SCOPE, "draft")
                self.assertEqual(engine.status("task", SCOPE)["budget"]["calls"], 2)

    def test_restart_preserves_exhausted_repair_and_upgrade_limits(self):
        engine = self.engine()
        self.exhaust_repair(engine)
        engine.upgrade("task", SCOPE, "draft")
        engine.wait("task", SCOPE)
        restored = Coordinator(engine.candidates())
        self.addCleanup(restored.close)
        restored.restore(engine.snapshot("task", SCOPE))
        restored.approve("task", SCOPE, 1)
        self.assertEqual(restored.snapshot("task", SCOPE)["assignments"], {"draft": "leader"})
        with self.assertRaises(RoutingError):
            restored.upgrade("task", SCOPE, "draft")
        with self.assertRaises(RoutingError):
            restored.retry("task", SCOPE, "draft")

    def test_upgrade_requires_task_specific_stronger_baseline_evidence(self):
        engine = self.engine()
        self.exhaust_repair(engine)
        with self.assertRaises(RoutingError):
            engine.upgrade("task", SCOPE, "draft", "unqualified")
        bounded = replace(node(), baseline_id="bounded-text-v1", task_type="bounded-text")
        cheap = candidate("cheap", fixed_cash="0", quality=(QualityEvidence("bounded-text", "bounded-text-v1", time.time() + 60, "bounded"),))
        engine = self.engine(nodes=[bounded], pool=[candidate(fixed_cash="1"), cheap])
        self.exhaust_repair(engine)
        with self.assertRaisesRegex(RoutingError, "quality-equivalent"):
            engine.upgrade("task", SCOPE, "draft", "leader")

    def test_replacement_must_independently_meet_original_task_baseline(self):
        bounded = replace(node(), baseline_id="bounded-text-v1", task_type="bounded-text")
        proof = QualityEvidence("bounded-text", "bounded-text-v1", time.time() + 60, "bounded-fixture")
        cheap = candidate("cheap", fixed_cash="0", quality=(proof,))
        replacement = candidate("replacement", fixed_cash="1", quality=(proof,))
        for change in ({}, {"expires_at": 1}, {"task_type": "other"}, {"baseline_id": "other"}):
            with self.subTest(change=change):
                target = replace(replacement, quality=(replace(proof, **change),))
                engine = self.engine(nodes=[bounded], pool=[cheap, target],
                                     verifier=lambda execution, outcome: Verification(execution.candidate.candidate_id == "replacement", ("synthetic-check",)))
                self.exhaust_repair(engine)
                if change:
                    with self.assertRaises(RoutingError):
                        engine.upgrade("task", SCOPE, "draft", "replacement")
                else:
                    engine.upgrade("task", SCOPE, "draft", "replacement")
                    result = engine.wait("task", SCOPE)
                    self.assertEqual(result["states"]["draft"], "completed")
                    self.assertEqual(result["plan"]["nodes"][0]["baseline_id"], "bounded-text-v1")
                    self.assertEqual(result["results"]["draft"]["candidate_id"], "replacement")

    def test_unknown_cannot_be_dropped_renamed_retried_or_reconfirmed_into_replay(self):
        engine = self.engine(executor=lambda execution: Outcome("unknown", possibly_sent=True))
        value = engine.wait("task", SCOPE)
        before = value["budget"]
        with self.assertRaises(RoutingError):
            engine.revise(Plan("task", SCOPE, 2, (node("replacement"),)), quote=QUOTE)
        with self.assertRaises(RoutingError):
            engine.retry("task", SCOPE, "draft")
        engine.approve("task", SCOPE, 1)
        self.assertEqual(engine.advance("task", SCOPE)["budget"], before)

    def test_known_completed_submission_can_be_repaired_after_failed_review(self):
        engine = self.engine(executor=lambda execution: Outcome("completed", "known answer", possibly_sent=True))
        result = engine.wait("task", SCOPE)
        self.assertEqual(result["states"]["draft"], "verification-failed")
        self.assertEqual(result["budget"]["reservations"], {})
        engine.retry("task", SCOPE, "draft")
        self.assertEqual(engine.wait("task", SCOPE)["states"]["draft"], "needs-replan")

    def test_unknown_auxiliary_blocks_all_dispatch_and_survives_restart(self):
        engine = self.engine()
        engine.reserve_auxiliary("task", SCOPE, "review-unknown", Decimal("1"), 10, "leader")
        engine.mark_unknown("task", SCOPE, "review-unknown")
        snapshot = engine.snapshot("task", SCOPE)
        self.assertEqual(engine.advance("task", SCOPE)["states"]["draft"], "pending")
        restored = Coordinator(engine.candidates())
        self.addCleanup(restored.close)
        restored.restore(snapshot)
        restored.approve("task", SCOPE, 1)
        self.assertEqual(restored.status("task", SCOPE)["unknown_attempts"], ["review-unknown"])
        with self.assertRaises(RoutingError):
            restored.reserve_auxiliary("task", SCOPE, "another", Decimal("1"), 10, "leader")

    def test_revision_transitively_invalidates_only_affected_branches_and_refreshes_quote(self):
        nodes = [node("facts"), node("costs"), node("draft", dependencies=("facts",)), node("final", dependencies=("draft", "costs"))]
        engine = self.engine(nodes=nodes, verifier=lambda execution, outcome: Verification(True, ("fixture",)))
        previous = engine.wait("task", SCOPE)
        revised = [replace(nodes[0], goal="Changed facts"), *nodes[1:], node("risks", dependencies=("facts",))]
        quote = replace(QUOTE, high_cny=Decimal("4"))
        result = engine.revise(Plan("task", SCOPE, 2, tuple(revised)), quote=quote, require_confirmation=True)
        self.assertEqual(result["status"], "awaiting-confirmation")
        self.assertEqual(result["states"], {"facts": "pending", "costs": "completed", "draft": "pending", "final": "pending", "risks": "pending"})
        self.assertEqual(result["results"]["costs"], previous["results"]["costs"])
        self.assertEqual(result["budget"]["calls"], previous["budget"]["calls"])
        self.assertEqual(result["budget"]["quote"], quote.to_dict())
        with self.assertRaises(RoutingError):
            engine.approve("task", SCOPE, 1)

    def test_mixed_plan_cannot_switch_strong_node_to_existing_weaker_baseline(self):
        engine = self.engine(nodes=[node(), replace(node("bounded"), baseline_id="bounded-text-v1")])
        with self.assertRaisesRegex(RoutingError, "quality baseline"):
            engine.revise(Plan("task", SCOPE, 2, (replace(node(), baseline_id="bounded-text-v1"),)))

    def test_renaming_cannot_replace_strong_terminal_with_a_weak_one(self):
        engine = self.engine(nodes=[node(), replace(node("bounded"), baseline_id="bounded-text-v1")])
        with self.assertRaisesRegex(RoutingError, "quality baseline"):
            engine.revise(Plan("task", SCOPE, 2, (replace(node("renamed"), baseline_id="bounded-text-v1"),)),
                          quote=QUOTE, require_confirmation=True)

    def test_pause_drains_known_inflight_without_dispatching_dependents(self):
        entered, release = threading.Event(), threading.Event()
        def execute(execution):
            entered.set()
            release.wait(2)
            return Outcome("completed", "known", cash_cny="0")
        engine = self.engine(nodes=[node("facts"), node("draft", dependencies=("facts",))], executor=execute,
                             verifier=lambda execution, outcome: Verification(True, ("fixture",)))
        engine.advance("task", SCOPE)
        self.assertTrue(entered.wait(2))
        engine.pause("task", SCOPE)
        release.set()
        value = engine.wait("task", SCOPE)
        self.assertEqual(value["status"], "paused")
        self.assertEqual(value["states"], {"facts": "completed", "draft": "pending"})

    def test_cancel_during_upgrade_suppresses_late_result(self):
        entered, release = threading.Event(), threading.Event()
        def execute(execution):
            if execution.candidate.candidate_id == "leader":
                entered.set()
                release.wait(2)
            return Outcome("completed", "late", cash_cny="1")
        engine = self.engine(executor=execute)
        self.exhaust_repair(engine)
        prior = engine.status("task", SCOPE)["results"]
        engine.upgrade("task", SCOPE, "draft")
        engine.advance("task", SCOPE)
        self.assertTrue(entered.wait(2))
        engine.cancel("task", SCOPE)
        release.set()
        engine.close()
        value = engine.status("task", SCOPE)
        self.assertEqual(value["status"], "cancelled")
        self.assertEqual(value["results"], prior)
        self.assertEqual(value["budget"]["calls"], 3)


if __name__ == "__main__":
    unittest.main()
