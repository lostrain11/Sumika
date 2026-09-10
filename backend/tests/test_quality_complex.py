from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch

from quality_routing import Outcome, QualityEvidence, RoutingError, Scope
import test_quality_routing as fixtures


class ComplexServiceTests(unittest.TestCase):
    setUp = fixtures.QualityHostTests.setUp
    tearDown = fixtures.QualityHostTests.tearDown

    def configure(self, *, failures=0, unknown=None, result_text="Fee: 12.50. Quota: unknown. Not executed."):
        cheap = replace(self.route, route_id="cheap", provider_profile_id="cheap-profile",
                        metadata={"model_entry": {"model_id": "synthetic-executor"}})
        self.app.route_supervisor.registered_routes = lambda: (self.route, cheap)
        self.service.register_quality_evidence("cheap", (QualityEvidence("synthetic-complex-v1", "local-model", time.time() + 60, "synthetic-fixture-only"),))
        self.nodes = [dict(node_id="facts", goal="Extract synthetic facts", task_type="synthetic-complex-v1", acceptance=["12.50 fee and unknown quota"]),
                      dict(node_id="draft", goal="Analyze synthetic constraints", task_type="synthetic-complex-v1", dependencies=["facts"], acceptance=["Preserve exact fee and uncertainty"])]
        self.calls = []
        rejected = 0
        def invoke(candidate, scope, prompt, cancelled, max_tokens):
            nonlocal rejected
            self.calls.append((candidate.candidate_id, prompt))
            if unknown and unknown in prompt:
                return Outcome("unknown", possibly_sent=True)
            if "Return only a JSON object with nodes" in prompt:
                text = json.dumps({"nodes": self.nodes})
            elif "Verify the task result" in prompt:
                fail = "Analyze synthetic constraints" in prompt and rejected < failures
                if fail:
                    rejected += 1
                text = json.dumps({"passed": not fail, "reason": "synthetic-injected-constraint-fault" if fail else "checked"})
            else:
                text = result_text
            return Outcome("completed", text, cash_cny="0", input_tokens=100, output_tokens=40)
        self.addCleanup(patch.stopall)
        patch.object(self.service, "_invoke", side_effect=invoke).start()
        return self.service.plan({**self.params, "goal": "Analyze synthetic schedule and cost constraints", "allowed_candidate_ids": ["cheap", "local-model"]})

    def run_task(self, task):
        scope = Scope("one", "session-one")
        self.service.engine.approve(task["task_id"], scope, task["revision"])
        self.service._run(task["task_id"], scope)
        return self.service.status(task["task_id"], scope)

    def test_intermediate_contract_excludes_conflicting_final_instructions(self):
        task = self.configure()
        result = self.run_task(task)
        self.assertEqual(result["status"], "completed")
        intermediate = next(prompt for _, prompt in self.calls if prompt.startswith("Complete only this task") and "Extract synthetic facts" in prompt)
        final = next(prompt for _, prompt in self.calls if prompt.startswith("Complete only this task") and "Analyze synthetic constraints" in prompt)
        self.assertNotIn("Original user goal", intermediate)
        self.assertIn("Original user goal", final)
        self.assertIn("Acceptance", intermediate)

    def test_actual_service_repairs_once_then_upgrades_without_replanning(self):
        task = self.configure(failures=2)
        result = self.run_task(task)
        self.assertEqual(result["status"], "completed", result)
        executions = [(candidate, prompt) for candidate, prompt in self.calls if prompt.startswith("Complete only this task") and "Analyze synthetic constraints" in prompt]
        self.assertEqual([candidate for candidate, prompt in executions], ["cheap", "cheap", "local-model"])
        self.assertIn("synthetic-injected-constraint-fault", executions[1][1])
        self.assertIn("Previous output", executions[1][1])
        self.assertEqual(result["revision"], 1)
        self.assertEqual(self.service._metadata[task["task_id"]]["replans"], 0)

    def test_bounded_failure_uses_qualified_replacement_without_inventing_leader_evidence(self):
        self.configure(failures=2)
        routes = self.app.route_supervisor.registered_routes()
        fallback = replace(self.route, route_id="fallback", provider_profile_id="fallback-profile")
        self.app.route_supervisor.registered_routes = lambda: (*routes, fallback)
        proof = QualityEvidence("bounded-text", "bounded-text-v1", time.time() + 60, "synthetic-bounded-fixture")
        self.service.register_quality_evidence("cheap", (*self.service._quality_evidence["cheap"], proof))
        self.service.register_quality_evidence("fallback", (proof,))
        self.nodes[1].update(task_type="bounded-text", risk="low")
        task = self.service.plan({**self.params, "goal": "Synthetic bounded failure recovery",
                                  "allowed_candidate_ids": ["cheap", "local-model", "fallback"]})
        result = self.run_task(task)
        self.assertEqual(result["status"], "completed", result)
        executions = [candidate for candidate, prompt in self.calls
                      if prompt.startswith("Complete only this task") and "Analyze synthetic constraints" in prompt]
        self.assertEqual(executions, ["cheap", "cheap", "fallback"])
        self.assertEqual(result["plan"]["nodes"][1]["baseline_id"], "bounded-text-v1")
        self.assertFalse(self.service._candidate("local-model").quality)
        self.assertEqual(self.service._metadata[task["task_id"]]["replans"], 0)

    def test_exhausted_upgrade_replans_with_failure_context_then_requires_confirmation(self):
        task = self.configure(failures=3)
        result = self.run_task(task)
        self.assertEqual(result["status"], "awaiting-confirmation", result)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["states"]["facts"], "completed")
        replans = [prompt for candidate, prompt in self.calls if "Revise only affected nodes" in prompt]
        self.assertEqual(len(replans), 1)
        self.assertIn("synthetic-injected-constraint-fault", replans[0])
        self.assertIsNone(result["final_message"])

    def test_explicit_goal_change_preserves_independent_results_and_requotes(self):
        task = self.configure()
        scope = Scope("one", "session-one")
        self.service.engine.approve(task["task_id"], scope, 1)
        previous = self.service.engine.wait(task["task_id"], scope)
        self.nodes.append(dict(node_id="risk", goal="Review cancellation boundaries", task_type="synthetic-complex-v1", dependencies=["facts"], acceptance=["No replay of unknown submission"]))
        result = self.service.rpc("quality.task.revise", {**self.params, "task_id": task["task_id"],
            "goal": "Add cancellation analysis while keeping all facts", "reason": "New user constraint"})
        self.assertEqual(result["status"], "awaiting-confirmation")
        self.assertEqual(result["goal"], "Add cancellation analysis while keeping all facts")
        self.assertEqual(result["results"]["facts"], previous["results"]["facts"])
        self.assertEqual(result["states"], {"facts": "completed", "draft": "pending", "risk": "pending"})
        prompt = next(prompt for candidate, prompt in self.calls if "Revise only affected nodes" in prompt)
        self.assertIn("New user constraint", prompt)
        self.assertIn("Add cancellation analysis", prompt)
        self.assertEqual(result["budget"]["quote"]["max_calls"], task["budget"]["quote"]["max_calls"])

    def test_price_change_at_confirmation_returns_new_quote_without_call(self):
        task = self.configure()
        before = len(self.calls)
        original = self.service._pricing
        self.service._pricing = lambda route, model: {**original(route, model), "fixed_cash": "0.01"}
        result = self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        self.assertEqual(result["status"], "awaiting-confirmation")
        self.assertEqual(result["confirmation_reason"], "execution-or-price-change")
        self.assertEqual(result["revision"], 2)
        self.assertNotEqual(result["budget"]["quote"]["high_cny"], task["budget"]["quote"]["high_cny"])
        self.assertEqual(len(self.calls), before)

    def test_replan_with_changed_price_defers_planning_until_new_confirmation(self):
        task = self.configure()
        scope = Scope("one", "session-one")
        self.service.engine.approve(task["task_id"], scope, 1)
        before = len(self.calls)
        original = self.service._pricing
        self.service._pricing = lambda route, model: {**original(route, model), "fixed_cash": "0.01"}
        result = self.service.rpc("quality.task.replan", {**self.params, "task_id": task["task_id"], "goal": "New goal"})
        self.assertEqual(result["status"], "awaiting-confirmation")
        self.assertEqual(result["pending_revision"]["goal"], "New goal")
        self.assertEqual(len(self.calls), before)
        result = self.run_task(result)
        self.assertEqual(result["status"], "awaiting-confirmation")
        self.assertEqual(result["goal"], "New goal")
        self.assertIsNone(result["pending_revision"])

    def test_unknown_executor_reviewer_or_replanner_is_never_resent(self):
        for location in ("Complete only this task", "Verify the task result", "Revise only affected nodes"):
            with self.subTest(location=location):
                task = self.configure(failures=3 if location == "Revise only affected nodes" else 0, unknown=location)
                result = self.run_task(task)
                before = len(self.calls)
                self.service._run(task["task_id"], Scope("one", "session-one"))
                with self.assertRaises(RoutingError):
                    self.service.rpc("quality.task.replan", {**self.params, "task_id": task["task_id"], "goal": "Do not replay"})
                self.assertEqual(len(self.calls), before)
                self.assertTrue(result["budget"]["reservations"])
                self.assertIsNone(result["final_message"])
                patch.stopall()

    def test_artifact_hash_and_template_commentary_preserve_json_code_and_markdown(self):
        for content in ('{"fee":"12.50","quota":null}', "```python\nfee = 12.50\n```", "# Checked\n\nFee: 12.50"):
            with self.subTest(content=content):
                task = self.configure(result_text=content)
                result = self.run_task(task)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["final_message"]["content"], content)
                self.assertEqual(result["artifacts"], [{
                    "schema_version": "quality-workflow/v1",
                    "id": task["task_id"] + ":0:artifact:1",
                    "task_id": task["task_id"] + ":0",
                    "assistant_id": "one",
                    "revision": 1,
                    "content": content,
                    "format": "markdown",
                    "source": "quality",
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "verification": "verified",
                }])
                self.assertEqual(result["commentary"], {
                    "assistant_id": "one", "task_id": task["task_id"], "status": "template",
                    "content": "整理好了，成果在这里。", "artifact_ids": [task["task_id"] + ":0:artifact:1"],
                })
                self.assertFalse(any("short in-character introduction" in prompt or "role-introduction fidelity" in prompt
                                     for _candidate, prompt in self.calls))
                patch.stopall()

    def test_unavailable_role_reference_does_not_block_verified_delivery(self):
        task = self.configure()
        self.service._metadata[task["task_id"]]["role_candidate_id"] = "removed-role"
        result = self.run_task(task)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["final_message"]["content"], "Fee: 12.50. Quota: unknown. Not executed.")
        self.assertEqual(result["commentary"]["status"], "template")
        self.assertFalse(any("short in-character introduction" in prompt or "role-introduction fidelity" in prompt
                             for _candidate, prompt in self.calls))

    def test_role_generation_failure_cannot_block_template_delivery(self):
        task = self.configure()
        invoke = self.service._invoke.side_effect

        def unavailable_role(candidate, scope, prompt, cancelled, max_tokens):
            if "short in-character introduction" in prompt:
                return Outcome("failed", cash_cny="0", input_tokens=0, output_tokens=0)
            return invoke(candidate, scope, prompt, cancelled, max_tokens)

        self.service._invoke.side_effect = unavailable_role
        result = self.run_task(task)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["final_message"]["content"], result["artifacts"][0]["content"])
        self.assertEqual(result["commentary"]["status"], "template")
        self.assertFalse(any("short in-character introduction" in prompt for _candidate, prompt in self.calls))

    def test_finalization_uses_no_role_call_or_reservation(self):
        task = self.configure(unknown="short in-character introduction")
        result = self.run_task(task)
        self.assertEqual(set(result["states"].values()), {"completed"})
        self.assertEqual(result["results"]["draft"]["text"], "Fee: 12.50. Quota: unknown. Not executed.")
        self.assertEqual(result["final_message"]["content"], result["results"]["draft"]["text"])
        self.assertEqual(result["budget"]["reservations"], {})
        self.assertFalse(result["unknown_attempts"])
        self.assertFalse(any("short in-character introduction" in prompt or "role-introduction fidelity" in prompt
                             for _candidate, prompt in self.calls))
        before = len(self.calls)
        self.service._run(task["task_id"], Scope("one", "session-one"))
        self.assertEqual(len(self.calls), before)
        self.assertEqual(sum(message["id"] == result["final_message"]["id"]
                             for message in self.storage.list_messages("session-one")), 1)

    def test_goal_change_drains_inflight_and_reuses_verified_result_without_dispatching_old_dependents(self):
        task = self.configure()
        entered, release = threading.Event(), threading.Event()
        original = self.service.engine._executor
        def execute(execution):
            entered.set()
            release.wait(3)
            return original(execution)
        self.service.engine._executor = execute
        self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        self.assertTrue(entered.wait(3))
        revised = []
        worker = threading.Thread(target=lambda: revised.append(self.service.rpc("quality.task.revise", {
            **self.params, "task_id": task["task_id"], "goal": "Keep facts; add explicit cancellation boundaries"})))
        worker.start()
        scope = Scope("one", "session-one")
        deadline = time.monotonic() + 3
        while not self.service.engine.snapshot(task["task_id"], scope)["dispatch_paused"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.service.engine.snapshot(task["task_id"], scope)["dispatch_paused"])
        release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(revised[0]["status"], "awaiting-confirmation")
        self.assertEqual(revised[0]["states"], {"facts": "completed", "draft": "pending"})
        self.assertFalse(any(prompt.startswith("Complete only this task") and "Analyze synthetic constraints" in prompt for candidate, prompt in self.calls))

    def test_cancel_during_repair_does_not_dispatch_upgrade_or_deliver(self):
        task = self.configure(failures=2)
        entered, release = threading.Event(), threading.Event()
        original = self.service.engine._executor
        def execute(execution):
            prior = self.service.engine.status(execution.task_id, execution.scope)["results"].get(execution.node.node_id)
            if prior and prior["status"] == "verification-failed":
                entered.set()
                release.wait(3)
            return original(execution)
        self.service.engine._executor = execute
        self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        try:
            self.assertTrue(entered.wait(3))
            self.service.rpc("quality.task.cancel", {**self.params, "task_id": task["task_id"]})
        finally:
            release.set()
        self.service.close()
        snapshot = self.service.engine.snapshot(task["task_id"], Scope("one", "session-one"))
        self.assertEqual(snapshot["status"], "cancelled")
        self.assertEqual(snapshot["upgrades"], [])
        self.assertEqual(self.storage.list_messages("session-one"), [])


if __name__ == "__main__":
    unittest.main()
