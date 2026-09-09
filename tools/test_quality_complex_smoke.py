import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from decimal import Decimal

from quality_routing import Candidate, Outcome, Scope, Verification
from quality_routing.costs import RouteQuote
from sumika_core.providers.guard import RequestNotSent
from tools.quality_complex_smoke import SmokeGuard, _upgrade_assertions, expected, fixture_service, grade, main, run_workflow


class ComplexSmokeTests(unittest.TestCase):
    def test_purchased_credits_count_towards_smoke_budget(self):
        quote = RouteQuote(cash_due_cny=Decimal(0), resource_value_cny=Decimal('0.2'),
                           effective_cost_cny=Decimal('0.2'), funding_kind='purchased')
        candidate = Candidate('leader', 'account', 'model', 'api', authorized=True, available=True,
                              quote_provider=lambda *args: quote)
        guard = SmokeGuard(['leader'], budget='0.1')
        sent = []
        with self.assertRaises(RequestNotSent):
            guard.wrap(lambda *args: sent.append(True))(candidate, Scope('one', 'session'), 'synthetic', threading.Event(), 100)
        self.assertFalse(sent)
        self.assertEqual(guard.reserved, 0)

    def test_offline_complex_workflow_repair_upgrade_and_goal_revision(self):
        for target, injection, revise in (("schedule", 0, False), ("schedule", 1, False), ("facts", 1, False),
                                          ("facts", 2, False), ("boundaries", 2, False), ("facts", 2, True)):
            with self.subTest(target=target, injection=injection, revise=revise):
                service = fixture_service()
                try:
                    guard = SmokeGuard(["leader", "cheap"])
                    report = run_workflow(service, assistant_id="synthetic", allowed=["leader", "cheap"], guard=guard,
                                          inject_validation_failures=injection, inject_validation_node=target, revise_goal=revise)
                    self.assertTrue(report["passed"], report)
                    self.assertEqual(report["mode"], "offline-scripted-fixture")
                    self.assertEqual(report["injected_validation_failures"], injection)
                    self.assertEqual(report["injection_target_node"], target)
                    self.assertEqual(report["requested_validation_failures"], injection)
                    self.assertIn("not evidence of real model", report["fault_interpretation"])
                    injected = [attempt for attempt in report["verification_attempts"] if attempt["host_injected_failure"]]
                    self.assertEqual(len(injected), injection)
                    self.assertTrue(all(attempt["node_id"] == target and attempt["model_review_passed"]
                                        and not attempt["effective_verification_passed"] for attempt in injected))
                    if injection == 2:
                        self.assertIn(target, report["upgraded_nodes"])
                        evidence = report["upgrade_evidence"]
                        self.assertEqual(evidence["initial_candidate_id"], "cheap")
                        self.assertEqual(evidence["upgraded_candidate_id"], "leader")
                        target_attempts = [attempt for attempt in report["verification_attempts"] if attempt["node_id"] == target]
                        self.assertEqual([attempt["candidate_id"] for attempt in target_attempts[:3]], ["cheap", "cheap", "leader"])
                        self.assertTrue(report["checks"]["same_candidate_failed_twice"])
                        self.assertEqual(evidence["failure_sources"], ["host-injected", "host-injected"])
                        self.assertTrue(report["checks"]["upgraded_execution_verified"])
                    self.assertTrue(all(attempt["candidate_id"] == "leader" for attempt in report["verification_attempts"]
                                        if attempt["node_id"] in {"schedule", "final"}))
                    if revise:
                        self.assertTrue(report["checks"]["unaffected_result_reused"])
                        self.assertTrue(report["checks"]["semantic_change_reconfirmed"])
                    self.assertIsNone(report["actual_billed_cny"])
                    self.assertNotIn("09:00", json.dumps(report))
                    self.assertNotIn("12.50", json.dumps(report))
                    self.assertLessEqual(report["model_call_attempts"], 24)
                finally:
                    service.close()
                    service.app.storage.close()

    def test_default_schedule_target_cannot_claim_upgrade_when_executor_is_already_leader(self):
        service = fixture_service()
        try:
            report = run_workflow(service, assistant_id="synthetic", allowed=["leader", "cheap"],
                                  guard=SmokeGuard(["leader", "cheap"]), inject_validation_failures=2)
            self.assertEqual(report["injection_target_node"], "schedule")
            self.assertFalse(report["passed"])
            self.assertFalse(report["checks"]["upgrade_started_with_non_leader"])
            self.assertFalse(report["checks"]["upgraded_candidate_changed"])
            self.assertIsNone(report["upgrade_evidence"]["upgraded_candidate_id"])
        finally:
            service.close()
            service.app.storage.close()

    def test_natural_review_failure_is_not_relabelled_or_injected_into_upgraded_candidate(self):
        service = fixture_service()
        original = service.engine._verifier
        rejected = []
        def reject_first(execution, outcome):
            if execution.node.node_id == "facts" and not rejected:
                rejected.append(True)
                return Verification(False, ("fixture-review-rejection",), "offline-fixture-review-rejection")
            return original(execution, outcome)
        service.engine._verifier = reject_first
        try:
            report = run_workflow(service, assistant_id="synthetic", allowed=["leader", "cheap"],
                                  guard=SmokeGuard(["leader", "cheap"]), inject_validation_failures=2, inject_validation_node="facts")
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["injected_validation_failures"], 1)
            self.assertTrue(report["checks"]["same_candidate_failed_twice"])
            self.assertEqual(report["upgrade_evidence"]["failure_sources"], ["model-review", "host-injected"])
            target = [attempt for attempt in report["verification_attempts"] if attempt["node_id"] == "facts"]
            self.assertFalse(target[0]["model_review_passed"])
            self.assertFalse(target[0]["host_injected_failure"])
            self.assertTrue(all(not attempt["host_injected_failure"] for attempt in target if attempt["candidate_id"] == "leader"))
        finally:
            service.close()
            service.app.storage.close()

    def test_upgrade_acceptance_requires_real_same_revision_candidate_transition_and_verified_execution(self):
        def attempt(candidate="cheap", revision=1, injected=True, passed=True):
            return {"node_id": "facts", "candidate_id": candidate, "revision": revision, "model_review_passed": passed,
                    "host_injected_failure": injected, "effective_verification_passed": passed and not injected}
        valid = [attempt(), attempt(), attempt("leader", injected=False)]
        checks, _ = _upgrade_assertions(valid, "facts", "leader", ["facts"])
        self.assertTrue(all(checks.values()))
        for attempts, upgrades in ((valid[:2], ["facts"]),
                                   ([*valid[:2], attempt("cheap", injected=False)], ["facts"]),
                                   ([*valid[:2], attempt("leader", revision=2, injected=False)], ["facts"]),
                                   ([*valid[:2], attempt("leader", injected=False, passed=False)], ["facts"]),
                                   ([attempt(injected=False), *valid[1:]], ["facts"]),
                                   (valid, [])):
            with self.subTest(attempts=attempts, upgrades=upgrades):
                checks, _ = _upgrade_assertions(attempts, "facts", "leader", upgrades)
                self.assertFalse(all(checks.values()))

    def test_injection_target_is_validated_before_any_planning(self):
        with self.assertRaises(ValueError):
            run_workflow(None, assistant_id="synthetic", allowed=[], guard=SmokeGuard([]), inject_validation_node="unrelated")

    def test_guard_reserves_before_send_never_logs_body_and_blocks_unknown_replay(self):
        candidate = Candidate("leader", "account", "model", "api", authorized=True, available=True, external=False, fixed_cash="0.1")
        guard = SmokeGuard(["leader"], budget="0.2", max_calls=2)
        sent = []
        def invoke(*args):
            sent.append(True)
            self.assertEqual(str(guard.reserved), "0.1")
            return Outcome("unknown", possibly_sent=True)
        guarded = guard.wrap(invoke)
        guarded(candidate, Scope("one", "session"), "private-prompt-and-secret", threading.Event(), 100)
        with self.assertRaises(RequestNotSent):
            guarded(candidate, Scope("one", "session"), "do not resend", threading.Event(), 100)
        self.assertEqual(len(sent), 1)
        self.assertNotIn("private", json.dumps(guard.summary()))
        self.assertNotIn("secret", json.dumps(guard.summary()))

    def test_guard_budget_unknown_cost_and_route_checks_happen_before_transport(self):
        for price, allowed, budget in (("0.3", ["leader"], "0.2"), (None, ["leader"], "0.2"), ("0", [], "0.2")):
            guard = SmokeGuard(allowed, budget=budget)
            candidate = Candidate("leader", "account", "model", "api", authorized=True, available=True, fixed_cash=price)
            sent = []
            with self.assertRaises(RequestNotSent):
                guard.wrap(lambda *args: sent.append(True))(candidate, Scope("one", "session"), "test", threading.Event(), 100)
            self.assertFalse(sent)
            self.assertFalse(guard.calls)

    def test_known_not_sent_releases_only_its_reservation_and_allows_bounded_retry(self):
        candidate = Candidate("leader", "account", "model", "api", authorized=True, available=True,
                              external=False, fixed_cash="0.1")
        guard = SmokeGuard(["leader"], budget="0.1", max_calls=2)
        attempts = []
        def invoke(*args):
            attempts.append(True)
            if len(attempts) == 1:
                raise RequestNotSent("private-preflight-reason-and-secret")
            return Outcome("completed", "checked", input_tokens=10, output_tokens=5)
        guarded = guard.wrap(invoke)
        with self.assertRaises(RequestNotSent):
            guarded(candidate, Scope("one", "session"), "private-body", threading.Event(), 100)
        self.assertFalse(guard.stopped)
        self.assertEqual(guard.reserved, 0)
        self.assertEqual(guard.calls[0]["status"], "not-sent")
        self.assertEqual(guard.calls[0]["reserved_upper_cny"], "0")
        self.assertEqual(guard.calls[0]["released_upper_cny"], "0.1")
        self.assertEqual(guard.calls[0]["input_tokens"], 0)
        self.assertEqual(guard.calls[0]["output_tokens"], 0)
        self.assertEqual(guarded(candidate, Scope("one", "session"), "retry", threading.Event(), 100).status, "completed")
        self.assertEqual(str(guard.reserved), "0.1")
        self.assertEqual(guard.summary()["known_not_sent_attempts"], 1)
        self.assertIsNone(guard.summary()["actual_billed_cny"])
        self.assertNotIn("private", json.dumps(guard.summary()))
        self.assertNotIn("secret", json.dumps(guard.summary()))
        with self.assertRaises(RequestNotSent):
            guarded(candidate, Scope("one", "session"), "over-call-cap", threading.Event(), 100)
        self.assertEqual(len(attempts), 2)

    def test_unknown_exception_keeps_reservation_and_stops_all_dispatch(self):
        candidate = Candidate("leader", "account", "model", "api", authorized=True, available=True,
                              external=False, fixed_cash="0.1")
        guard = SmokeGuard(["leader"], budget="0.2")
        def invoke(*args):
            raise TimeoutError("private-error-after-possible-send")
        with self.assertRaises(TimeoutError):
            guard.wrap(invoke)(candidate, Scope("one", "session"), "prompt", threading.Event(), 100)
        self.assertTrue(guard.stopped)
        self.assertEqual(str(guard.reserved), "0.1")
        self.assertEqual(guard.calls[0]["status"], "submission-unknown")
        self.assertEqual(guard.summary()["known_not_sent_attempts"], 0)
        self.assertNotIn("private", json.dumps(guard.summary()))

    def test_known_not_sent_does_not_clear_concurrent_unknown_stop(self):
        candidate = Candidate("leader", "account", "model", "api", authorized=True, available=True,
                              external=False, fixed_cash="0.1")
        guard = SmokeGuard(["leader"], budget="0.2")
        entered, release = threading.Event(), threading.Event()
        def invoke(candidate, scope, prompt, cancelled, max_tokens):
            if prompt == "known-not-sent":
                entered.set()
                release.wait(3)
                raise RequestNotSent("not submitted")
            return Outcome("unknown", possibly_sent=True)
        guarded = guard.wrap(invoke)
        def unsent():
            with self.assertRaises(RequestNotSent):
                guarded(candidate, Scope("one", "session"), "known-not-sent", threading.Event(), 100)
        worker = threading.Thread(target=unsent)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            guarded(candidate, Scope("one", "session"), "unknown", threading.Event(), 100)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(guard.stopped)
        self.assertEqual(str(guard.reserved), "0.1")
        self.assertEqual([record["status"] for record in guard.calls], ["not-sent", "unknown"])

    def test_grading_rejects_changed_facts_even_with_valid_json(self):
        answer = expected()
        self.assertTrue(grade("Warm introduction.\n" + json.dumps(answer)))
        for key, value in (("fee", "10"), ("quota", "free"), ("executed", True), ("resubmit_unknown", True), ("normal_end", "10:00")):
            self.assertFalse(grade(json.dumps({**answer, key: value})))

    def test_cli_default_is_offline_and_never_overwrites_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            with patch("builtins.print"):
                self.assertEqual(main(["--report", str(report)]), 0)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["mode"], "offline-scripted-fixture")
            with self.assertRaises(SystemExit):
                main(["--report", str(report)])
            self.assertTrue(report.exists())

    def test_cli_selected_injection_target_exercises_upgrade_and_preserves_goal_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upgrade-revision.json"
            with patch("builtins.print"):
                self.assertEqual(main(["--report", str(path), "--inject-validation-node", "facts",
                                       "--inject-validation-failures", "2", "--revise-goal"]), 0)
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["fault_source"], "host-injected-after-successful-review")
            self.assertEqual(report["injection_target_node"], "facts")
            self.assertTrue(report["checks"]["upgraded_candidate_changed"])
            self.assertTrue(report["checks"]["unaffected_result_reused"])
            self.assertTrue(report["checks"]["semantic_change_reconfirmed"])
            target = [attempt for attempt in report["verification_attempts"] if attempt["node_id"] == "facts"]
            self.assertEqual(len(target), 3)
            self.assertTrue(all(attempt["revision"] == 1 for attempt in target))

    def test_cli_rejects_unknown_injection_nodes_before_opening_a_runtime(self):
        with tempfile.TemporaryDirectory() as directory, patch("tools.quality_complex_smoke.fixture_service") as create:
            report = Path(directory) / "invalid.json"
            with self.assertRaises(SystemExit):
                main(["--report", str(report), "--inject-validation-node", "unknown-node"])
            create.assert_not_called()
            self.assertFalse(report.exists())

    def test_live_requires_an_explicit_isolated_runtime(self):
        with self.assertRaises(SystemExit):
            main(["--live", "--report", "unused-complex-report.json"])
        with self.assertRaises(SystemExit):
            main(["--live", "--data-dir", ".", "--credential-data-dir", ".", "--report", "unused-complex-report.json"])


if __name__ == "__main__":
    unittest.main()
