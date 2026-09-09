from __future__ import annotations

import json
import threading
import time
import unittest
from types import SimpleNamespace
from dataclasses import replace

from quality_routing import QualityEvidence, RoutingError, Scope
from sumika_core.agent.supervisor import RuntimeRouteDescriptor
from sumika_core.quality import QualityRoutingService
from sumika_core.quality.browser_bridge import ConsultationBridge
from sumika_core.storage import Storage


class Provider:
    def __init__(self):
        self.calls = []
        self.last_usage = {"input_tokens": 100, "output_tokens": 30}

    def stream(self, request):
        self.calls.append(request)
        prompt = request.messages[0].content
        if "Return only a JSON object with nodes" in prompt:
            yield json.dumps({"nodes": [{"node_id": "answer", "goal": "Calculate six times seven", "task_type": "arithmetic",
                                        "acceptance": ["Answer equals 42"], "capabilities": ["text"]}]})
        elif "Verify the task result" in prompt:
            yield '{"passed":true,"reason":"Six times seven equals 42"}'
        elif "short in-character introduction" in prompt:
            yield "Here is the checked answer."
        else:
            yield "42"


class QualityHostTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(":memory:")
        self.storage.create_character("one", "One", {"persona": {}})
        self.storage.create_character("two", "Two", {"persona": {}})
        self.storage.create_session("session-one", character_id="one")
        self.storage.create_session("session-two", character_id="two")
        self.provider = Provider()
        self.events = []
        self.route = RuntimeRouteDescriptor("local-model", label="local", kind="provider", status="ready", routable=True,
                                            capabilities=("text",), executor="fixture", provider_profile_id="profile",
                                            auth_state="authorized", health_state="healthy", cost_class="local",
                                            quota_state="not-applicable", processing_location="local",
                                            metadata={"model_entry": {"model_id": "fixture-model"}})
        self.app = SimpleNamespace(
            storage=self.storage, logger=SimpleNamespace(warning=lambda *args: None),
            events=SimpleNamespace(publish=self.events.append),
            provider_profiles=SimpleNamespace(runtime=lambda *args, **kwargs: self.provider,
                                              get=lambda *args: {"status": "available"}, mark_used=lambda *args: None),
            route_supervisor=SimpleNamespace(registered_routes=lambda: (self.route,)),
            _refresh_route_supervisor_catalog=lambda **kwargs: None,
        )
        self.service = QualityRoutingService(self.app)
        self.service.update_settings({"assistant_id": "one", "role_candidate_id": "local-model", "leader_candidate_id": "local-model"})
        self.params = {"assistant_id": "one", "session_id": "session-one"}

    def tearDown(self):
        self.service.close()
        self.storage.close()

    def test_complex_planning_reserves_reasoning_and_json_output_without_replaying_truncation(self):
        task = self.service.plan({**self.params, "goal": "Synthetic detailed requirements. " * 40,
                                  "allowed_candidate_ids": ["local-model"]})
        self.assertEqual(task["status"], "awaiting-confirmation")
        self.assertEqual(self.provider.calls[0].max_tokens, 16000)
        self.assertEqual(len(self.provider.calls), 1)

    def test_free_account_serializes_nodes_and_cancellation_drains_cooldown(self):
        import threading
        from quality_routing import Outcome
        self.app.model_policy = SimpleNamespace(free_models=SimpleNamespace(manages=lambda account: True))
        candidate = replace(self.service._candidate("local-model"), account_concurrency=3)
        entered = threading.Event()
        cancelled = threading.Event()
        calls = []
        original = self.service._invoke_unlocked
        def invoke(candidate, scope, prompt, stop, max_tokens):
            if stop.is_set():
                return Outcome("cancelled", cash_cny="0", input_tokens=0, output_tokens=0)
            calls.append(prompt)
            entered.set()
            return Outcome("completed", "fixture", cash_cny="0", input_tokens=1, output_tokens=1)
        self.service._invoke_unlocked = invoke
        arguments = (candidate, Scope("one", "session-one"), "fixture", cancelled, 32)
        first = threading.Thread(target=self.service._invoke, args=arguments)
        second = threading.Thread(target=self.service._invoke, args=arguments)
        try:
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            second.join(.15)
            self.assertEqual(len(calls), 1)
            self.assertTrue(second.is_alive())
        finally:
            cancelled.set()
            first.join(2)
            if second.ident is not None:
                second.join(2)
            self.service._invoke_unlocked = original
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(calls), 1)

    def test_plan_confirm_verify_and_role_delivery(self):
        task = self.service.rpc("quality.task.plan", {**self.params, "goal": "Calculate six times seven", "allowed_candidate_ids": ["local-model"]})
        self.assertEqual(task["status"], "awaiting-confirmation")
        self.assertEqual(len(self.provider.calls), 1)
        self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.service.status(task["task_id"], Scope("one", "session-one"))
            if result["final_message"]:
                break
            time.sleep(0.01)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["final_message"]["content"].endswith("42"))
        self.assertEqual(result["budget"]["calls"], 5)
        role_request = next(request for request in self.provider.calls if "short in-character introduction" in request.messages[0].content)
        self.assertEqual(role_request.max_tokens, 1024)
        self.assertEqual(self.storage.list_messages("session-two"), [])
        self.service._metadata[task["task_id"]]["final_message"] = None
        prior_calls = len(self.provider.calls)
        self.service._finalize(task["task_id"], Scope("one", "session-one"), result)
        self.assertEqual(len(self.storage.list_messages("session-one")), 1)
        self.assertEqual(len(self.provider.calls), prior_calls)

    def test_settings_and_task_rule_snapshots_are_independent(self):
        self.assertIsNone(self.service.settings("two")["leader_candidate_id"])
        task = self.service.plan({**self.params, "goal": "Compute", "allowed_candidate_ids": ["local-model"]})
        self.service.update_settings({"assistant_id": "one", "budget_rule": {"multiplier": "4", "extra_cny": "8"}})
        result = self.service.status(task["task_id"], Scope("one", "session-one"))
        self.assertEqual(result["budget"]["rule"], {"multiplier": "2", "extra_cny": "5"})

    def test_exact_deliverable_does_not_add_a_persona_preamble(self):
        task = self.service.plan({**self.params, "goal": "Calculate six times seven. Return only 42.", "allowed_candidate_ids": ["local-model"]})
        self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.service.status(task["task_id"], Scope("one", "session-one"))
            if result["final_message"]:
                break
            time.sleep(0.01)
        self.assertEqual(result["final_message"]["content"], "42")
        self.assertFalse(any("short in-character introduction" in request.messages[0].content for request in self.provider.calls))
        review = next(request for request in self.provider.calls if "Verify the task result" in request.messages[0].content)
        self.assertEqual(review.max_tokens, 4000)

    def test_truncated_or_filtered_api_answer_cannot_complete(self):
        candidate = self.service._candidate("local-model")
        for finish_reason in ("length", "content_filter", "stop"):
            with self.subTest(finish_reason=finish_reason):
                self.provider.last_finish_reason = finish_reason
                outcome = self.service._invoke(candidate, Scope("one", "session-one"), "Compute", threading.Event(), 300)
                self.assertEqual(outcome.status, "completed" if finish_reason == "stop" else "failed")
                self.assertEqual(outcome.output_tokens, 30)

    def test_execution_and_terminal_review_retain_original_output_constraint(self):
        goal = "Calculate six times seven. Return exactly two ASCII digits without punctuation."
        task = self.service.plan({**self.params, "goal": goal, "allowed_candidate_ids": ["local-model"]})
        self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.service.status(task["task_id"], Scope("one", "session-one"))
            if result["final_message"]:
                break
            time.sleep(0.01)
        self.assertEqual(result["status"], "completed")
        execution = next(request.messages[0].content for request in self.provider.calls if request.messages[0].content.startswith("Complete only this task"))
        review = next(request.messages[0].content for request in self.provider.calls if request.messages[0].content.startswith("Verify the task result"))
        self.assertIn(goal, execution)
        self.assertIn(goal, review)
        self.assertIn('"terminal_node": true', review)

    def test_cross_owner_task_read_is_rejected(self):
        task = self.service.plan({**self.params, "goal": "Compute", "allowed_candidate_ids": ["local-model"]})
        with self.assertRaises(RoutingError):
            self.service.rpc("quality.task.get", {"assistant_id": "two", "session_id": "session-two", "task_id": task["task_id"]})

    def test_conversation_cannot_be_rebound_by_client(self):
        with self.assertRaises(RoutingError):
            self.service.rpc("quality.task.list", {"assistant_id": "two", "session_id": "session-one"})

    def test_leader_cannot_supply_permissions_or_quality_baseline(self):
        for field in ("authorized", "baseline_id", "allowed_files"):
            with self.assertRaises(RoutingError):
                self.service._nodes({"nodes": [{"node_id": "x", "goal": "goal", "task_type": "text", "acceptance": ["ok"], field: True}]}, "local-model")

    def test_task_storage_rejects_ownership_change(self):
        self.storage.save_quality_task("task", "one", "session-one", {})
        with self.assertRaises(ValueError):
            self.storage.save_quality_task("task", "two", "session-two", {})

    def test_disabled_candidate_not_enabled_by_selection(self):
        self.route = __import__("dataclasses").replace(self.route, routable=False)
        with self.assertRaises(RoutingError):
            self.service.plan({**self.params, "goal": "Compute", "allowed_candidate_ids": ["local-model"]})

    def test_cancel_during_persona_delivery_never_appends_late_answer(self):
        started = threading.Event()
        release = threading.Event()
        original = self.provider.stream

        def stream(request):
            if "short in-character introduction" in request.messages[0].content:
                started.set()
                release.wait(3)
            yield from original(request)

        self.provider.stream = stream
        task = self.service.plan({**self.params, "goal": "Compute", "allowed_candidate_ids": ["local-model"]})
        try:
            self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
            self.assertTrue(started.wait(3))
            self.service.rpc("quality.task.cancel", {**self.params, "task_id": task["task_id"]})
        finally:
            release.set()
        self.service.close()
        result = self.service.status(task["task_id"], Scope("one", "session-one"))
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["final_message"])
        self.assertEqual(self.storage.list_messages("session-one"), [])

    def test_authorized_equivalent_executor_is_used_but_leader_verifies(self):
        cheap = replace(self.route, route_id="cheap", provider_profile_id="cheap-profile",
                        metadata={"model_entry": {"model_id": "cheap-model"}})
        self.app.route_supervisor.registered_routes = lambda: (self.route, cheap)
        self.service.register_quality_evidence("cheap", (QualityEvidence("arithmetic", "local-model", time.time() + 60, "exact-fixture"),))
        task = self.service.plan({**self.params, "goal": "Compute", "allowed_candidate_ids": ["local-model", "cheap"]})
        self.service.rpc("quality.task.confirm", {**self.params, "task_id": task["task_id"], "revision": 1})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = self.service.status(task["task_id"], Scope("one", "session-one"))
            if result["final_message"]:
                break
            time.sleep(0.01)
        self.assertEqual(result["results"]["answer"]["candidate_id"], "cheap")
        self.assertTrue(result["results"]["answer"]["evidence"][0].startswith("leader-review:"))
        self.assertEqual(self.storage.list_messages("session-two"), [])


class BrowserBridgeTests(unittest.TestCase):
    def test_unattached_browser_does_not_claim_consultation(self):
        bridge = ConsultationBridge()
        result = bridge.consult(Scope("one", "chat"), "Question", threading.Event())
        self.assertEqual(result["status"], "unavailable")

    def test_delivery_is_once_and_scope_is_bound(self):
        bridge = ConsultationBridge()
        token = bridge.attach()["token"]
        responses = []
        thread = threading.Thread(target=lambda: responses.append(bridge.consult(Scope("one", "chat"), "Question", threading.Event(), timeout=2)))
        thread.start()
        self.assertIsNone(bridge.poll(token, accept_requests=False)["request"])
        request = bridge.poll(token)["request"]
        self.assertEqual(request["owner_id"], "one")
        self.assertIsNone(bridge.poll(token)["request"])
        bridge.complete(token, request["attempt_id"], {"status": "completed", "text": "Answer"})
        thread.join(2)
        bridge.close()
        self.assertEqual(responses[0]["text"], "Answer")

    def test_wrong_bridge_token_rejected(self):
        bridge = ConsultationBridge()
        bridge.attach()
        with self.assertRaises(RoutingError):
            bridge.poll("wrong")


if __name__ == "__main__":
    unittest.main()
