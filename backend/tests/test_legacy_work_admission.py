import threading
import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quality_routing import RoutingError, Scope
from quality_routing.harness import RuntimeBinding
from quality_routing.workflow import ExternalQuote
from sumika_core.providers.guard import RequestNotSent
from sumika_core.quality.legacy_admission import LegacyWorkAdmission
from sumika_core.quality.work import WorkService
from sumika_core.server import create_server
from sumika_core.storage import Storage
from trusted_host_fixture import trusted_rpc


class ExternalWorkTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.quality = SimpleNamespace(_scope=lambda params: Scope(params["assistant_id"], params["session_id"]))
        self.work = WorkService(self.storage, self.quality)
        self.addCleanup(self.storage.close)
        self.addCleanup(self.work.close)
        self.params = {"client_request_id": "request-1", "text": "翻译：你好", "profile_id": "profile"}
        self.offer = {"source": "web", "candidate_id": "web:profile", "identity": ["profile", "v1"],
                      "high_cny": "0", "limit_enforced": True, "free": True,
                      "funding": "free-policy", "complexity": "simple", "execution_key": "profile"}

    def dispatch(self, execute, params=None):
        return self.work.external_dispatch(params or self.params, self.offer, execute,
                                           refresh_offer=lambda: self.offer)

    def confirm(self, value, max_cny="0"):
        return self.work.confirm({"request_id": value["request_id"], "assistant_id": "sumika",
                                  "revision": value["revision"], "max_cny": max_cny})

    def test_free_web_dispatches_once_and_persists_source_result(self):
        execute = Mock(return_value={"status": "completed", "ok": True, "text": "Hello"})
        first = self.dispatch(execute)
        second = self.dispatch(execute)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(first["text"], second["text"])
        self.assertEqual(second["work_request"]["status"], "completed")
        self.assertEqual(second["work_request"]["authorization"]["reserved_cny"], "0")

    def test_paid_ignores_boolean_approval_until_versioned_confirmation(self):
        self.offer.update(high_cny="1.50", free=False, funding="cash")
        execute = Mock(return_value={"status": "completed", "ok": True})
        pending = self.dispatch(execute, {**self.params, "approved": True, "routingApproved": True})
        self.assertEqual(pending["status"], "awaiting-confirmation")
        execute.assert_not_called()
        self.confirm(pending["work_request"], "1.50")
        completed = self.dispatch(execute)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(completed["work_request"]["authorization"]["spent_cny"], "1.50")

    def test_unknown_cost_never_becomes_zero_or_a_hard_limit(self):
        self.offer.update(limit_enforced=False, high_cny=None, free=False)
        execute = Mock()
        pending = self.dispatch(execute)
        self.assertIsNone(pending["work_request"]["quote"]["high_cny"])
        self.assertIsNone(pending["work_request"]["quote"]["max_tokens"])
        with self.assertRaises(RoutingError):
            self.confirm(pending["work_request"], "10")
        execute.assert_not_called()

    def test_complex_free_agent_requires_scope_confirmation(self):
        self.offer.update(source="agent", complexity="complex")
        execute = Mock(return_value={"status": "completed"})
        pending = self.dispatch(execute)
        execute.assert_not_called()
        self.confirm(pending["work_request"])
        self.assertEqual(self.dispatch(execute)["work_request"]["status"], "completed")

    def test_changed_request_and_stale_revision_do_not_reuse_authorization(self):
        self.offer.update(high_cny="1", free=False)
        pending = self.dispatch(Mock())
        with self.assertRaises(RoutingError):
            self.work.confirm({"request_id": "request-1", "assistant_id": "sumika", "revision": 0, "max_cny": "1"})
        self.confirm(pending["work_request"], "1")
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.dispatch(execute, {**self.params, "text": "另一项任务"})
        execute.assert_not_called()

    def test_frozen_route_change_does_not_silently_switch(self):
        self.offer.update(high_cny="1", free=False)
        pending = self.dispatch(Mock())
        self.confirm(pending["work_request"], "1")
        self.offer["identity"] = ["profile", "v2"]
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.dispatch(execute)
        execute.assert_not_called()

    def test_unknown_submission_keeps_reservation_and_never_resends(self):
        self.offer.update(high_cny="2", free=False)
        execute = Mock(return_value={"status": "unknown", "possibly_sent": True, "attempt_id": "upstream"})
        self.confirm(self.dispatch(execute)["work_request"], "2")
        unknown = self.dispatch(execute)
        self.assertEqual(unknown["status"], "submission-unknown")
        self.assertEqual(unknown["work_request"]["authorization"]["reserved_cny"], "2")
        self.dispatch(execute)
        self.assertEqual(execute.call_count, 1)
        recovered = self.work.external_observe("request-1", "sumika", {"status": "completed", "ok": True})
        self.assertEqual(recovered["work_request"]["authorization"]["reserved_cny"], "0")
        self.assertEqual(recovered["work_request"]["authorization"]["spent_cny"], "2")

    def test_exception_after_dispatch_is_unknown_but_explicit_not_sent_releases(self):
        with self.assertRaises(TimeoutError):
            self.dispatch(Mock(side_effect=TimeoutError("transport uncertain")))
        self.assertEqual(self.work.get("request-1", "sumika")["status"], "submission-unknown")
        self.offer["execution_key"] = "other-profile"
        with self.assertRaises(RequestNotSent):
            self.dispatch(Mock(side_effect=RequestNotSent("preflight failed")),
                          {**self.params, "client_request_id": "request-2"})
        value = self.work.get("request-2", "sumika")
        self.assertEqual(value["status"], "failed")
        self.assertEqual(next(iter(value["attempts"].values()))["status"], "not-sent")

    def test_concurrent_duplicate_and_new_id_cannot_dispatch_twice(self):
        entered = threading.Event()
        release = threading.Event()
        def execute():
            entered.set()
            self.assertTrue(release.wait(3))
            return {"accepted": True, "status": "running", "attempt_id": "upstream"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.dispatch, execute)
            self.assertTrue(entered.wait(3))
            duplicate = Mock()
            self.dispatch(duplicate)
            self.dispatch(duplicate, {**self.params, "client_request_id": "other-request"})
            duplicate.assert_not_called()
            release.set()
            self.assertEqual(future.result()["work_request"]["status"], "executing")

    def test_external_request_cannot_be_submitted_as_api_text(self):
        self.offer.update(complexity="complex")
        value = self.dispatch(Mock())["work_request"]
        self.confirm(value)
        with self.assertRaises(RoutingError):
            self.work.submit({"request_id": value["request_id"], "assistant_id": "sumika"})

    def test_external_quote_does_not_invent_token_or_call_limits(self):
        quote = ExternalQuote("0", "0", "0")
        self.assertIsNone(quote.max_tokens)
        self.assertIsNone(quote.max_calls)
        with self.assertRaises(RoutingError):
            ExternalQuote("0", "0", "0", max_tokens=0)

    def test_consultation_quote_uses_constraints_and_stable_catalog_order(self):
        profiles = [{"id": "first", "budget_policy": "free-only"}, {"id": "second", "budget_policy": "free-only"}]
        routes = [SimpleNamespace(route_id="web:second", executor="web", kind="web", provider_profile_id="second"),
                  SimpleNamespace(route_id="web:first", executor="web", kind="web", provider_profile_id="first")]
        admission = LegacyWorkAdmission(self.work, profiles=lambda: profiles, routes=lambda: routes, agent_offer=lambda params: {})
        request = {"question": "check sources", "route_constraints": {"route_ids": ["web:first"]}}
        original = admission.offer("sumika.consultation.start", request)
        profiles[1]["budget_policy"] = "allow-paid"
        routes.reverse()
        self.assertEqual(original, admission.offer("sumika.consultation.start", request))
        self.assertEqual(original["execution_key"], "web-profile:first")
        self.assertTrue(original["free"])
        all_routes = admission.offer("sumika.consultation.start", {"question": "all sources"})
        routes.reverse()
        self.assertEqual(all_routes, admission.offer("sumika.consultation.start", {"question": "all sources"}))

    def test_cancel_preserves_unknown_reservation_and_does_not_resend(self):
        self.offer.update(high_cny="2", free=False)
        execute = Mock(return_value={"status": "unknown", "attempt_id": "upstream", "possibly_sent": True})
        self.confirm(self.dispatch(execute)["work_request"], "2")
        self.dispatch(execute)
        cancelled = self.work.cancel({"request_id": "request-1", "assistant_id": "sumika"})
        self.assertEqual(cancelled["status"], "cancel-requested")
        self.assertEqual(cancelled["authorization"]["reserved_cny"], "2")
        self.dispatch(execute)
        self.assertEqual(execute.call_count, 1)

    def test_same_account_different_assistant_cannot_dispatch_or_read_active_request(self):
        self.dispatch(Mock(return_value={"status": "running", "attempt_id": "upstream", "accepted": True}))
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.dispatch(execute, {**self.params, "assistant_id": "other", "client_request_id": "other-request"})
        execute.assert_not_called()

    def test_completion_keeps_clean_artifact_and_late_running_does_not_reopen(self):
        result = self.dispatch(Mock(return_value={"status": "completed", "text": '{"answer": 42}'}))
        artifact = result["work_request"]["artifacts"][0]
        self.assertEqual(artifact["content"], '{"answer": 42}')
        self.assertEqual(artifact["verification"], "source-completed")
        late = self.work.external_observe("request-1", "sumika", {"status": "running"})
        self.assertEqual(late["work_request"]["status"], "completed")

    def test_status_id_collision_cannot_complete_another_source(self):
        self.dispatch(Mock(return_value={"status": "running", "attempt_id": "same-id", "accepted": True}))
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [], routes=lambda: [], agent_offer=lambda params: {})
        admission.observe("sumika.route.status", {"dispatch_id": "same-id"}, {"status": "completed"})
        self.assertEqual(self.work.get("request-1", "sumika")["status"], "executing")

    def test_restart_keeps_inflight_attempt_unknown_and_does_not_resubmit(self):
        self.dispatch(Mock(return_value={"status": "running", "attempt_id": "upstream", "accepted": True}))
        restored = WorkService(self.storage, self.quality, owner_ids=iter(["sumika"]))
        self.addCleanup(restored.close)
        execute = Mock()
        result = restored.external_dispatch(self.params, self.offer, execute, refresh_offer=lambda: self.offer)
        self.assertEqual(result["status"], "submission-unknown")
        self.assertEqual(next(iter(result["work_request"]["attempts"].values()))["status"], "reserved")
        execute.assert_not_called()

    def test_cancel_is_forwarded_once_without_claiming_upstream_completion(self):
        self.dispatch(Mock(return_value={"status": "running", "attempt_id": "upstream", "accepted": True}))
        value = self.work.cancel({"request_id": "request-1", "assistant_id": "sumika"})
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [], routes=lambda: [], agent_offer=lambda params: {})
        execute = Mock(return_value={"cancelled": True})
        first = admission.cancel_external(value, execute)
        admission.cancel_external(first, execute)
        execute.assert_called_once_with("browser.web_chat.message.cancel", {"attempt_id": "upstream"})
        self.assertEqual(first["status"], "cancel-requested")
        self.assertEqual(next(iter(first["attempts"].values()))["status"], "reserved")

    def test_deferred_route_rechecks_price_before_event_dispatch(self):
        profile = {"id": "profile", "budget_policy": "free-only"}
        binding = RuntimeBinding("fixture", "profile", "release", "v1", "managed", "evidence", "launch", "receipt")
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [profile], routes=lambda: [], agent_offer=lambda params: {},
                                        runtime_binding=lambda: binding)
        params = {"route_id": "web-chat:profile", "parent_session_id": "session", "parent_turn_id": "turn",
                  "text": "research", "client_request_id": "deferred"}
        arm = Mock(return_value={"armed": True, "parent_session_id": "session", "parent_turn_id": "turn"})
        pending = admission.dispatch("sumika.route.arm", params, arm)
        self.confirm(pending["work_request"])
        admission.dispatch("sumika.route.arm", params, arm)
        profile["budget_policy"] = "allow-paid"
        execute = Mock()
        event = {"session_id": "session", "turn_id": "turn"}
        for wrong in (None, replace(binding, instance_id="other"), replace(binding, launch_id="new")):
            rejected = admission.advance_boundary(event, execute, source_binding=wrong)
            self.assertFalse(rejected["accepted"])
            execute.assert_not_called()
            self.assertEqual(self.work.get("deferred", "sumika")["status"], "executing")
        result = admission.advance_boundary(event, execute, source_binding=binding)
        self.assertEqual(result["status"], "awaiting-confirmation")
        execute.assert_not_called()
        self.assertEqual(next(iter(self.work.get("deferred", "sumika")["attempts"].values()))["status"], "not-sent")

    def test_agent_event_requires_exact_session_turn_and_host_binding(self):
        binding = RuntimeBinding("fixture", "profile-one", "release-one", "v1", "managed",
                                 "fixture-evidence", "launch-one", "launch-evidence")
        self.offer.update(source="agent", complexity="complex", execution_key="agent:session",
                          runtime_binding=binding.to_dict(), high_cny="2", free=False, funding="fixture")
        params = {**self.params, "sessionId": "session"}
        execute = Mock(return_value={"accepted": True, "turn_id": "turn", "status": "running"})
        self.confirm(self.dispatch(execute, params)["work_request"], "2")
        self.dispatch(execute, params)
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [], routes=lambda: [], agent_offer=lambda params: {})
        admission.observe_agent_event({"session_id": "other", "turn_id": "turn"}, "turn.completed", source_binding=binding)
        admission.observe_agent_event({"session_id": "session", "turn_id": "older"}, "turn.completed", source_binding=binding)
        event = {"session_id": "session", "turn_id": "turn", "runtime_binding": binding.to_dict()}
        for wrong in (None, replace(binding, harness_id="other"), replace(binding, instance_id="other"),
                      replace(binding, launch_id="restarted"), replace(binding, distribution_id="upgraded"),
                      replace(binding, launch_id=None, launch_evidence_ref=None)):
            admission.observe_agent_event(event, "turn.completed", source_binding=wrong)
            current = self.work.get("request-1", "sumika")
            self.assertEqual(current["status"], "executing")
            self.assertEqual(next(iter(current["attempts"].values()))["status"], "reserved")
            self.assertEqual(current["authorization"]["reserved_cny"], "2")
            self.assertEqual(current["authorization"]["spent_cny"], "0")
        self.assertEqual(self.work.get("request-1", "sumika")["status"], "executing")
        self.assertEqual(next(iter(current["attempts"].values()))["runtime_binding"], binding.to_dict())
        admission.observe_agent_event(event, "turn.completed", source_binding=binding)
        self.assertEqual(self.work.get("request-1", "sumika")["status"], "completed")
        self.assertEqual(self.work.get("request-1", "sumika")["authorization"]["spent_cny"], "2")

    def test_legacy_agent_record_without_binding_is_not_settled_by_same_name_event(self):
        self.offer.update(source="agent", complexity="complex")
        params = {**self.params, "sessionId": "session"}
        execute = Mock(return_value={"accepted": True, "turn_id": "turn", "status": "running"})
        self.confirm(self.dispatch(execute, params)["work_request"])
        self.dispatch(execute, params)
        binding = RuntimeBinding("fixture", "profile", "release", "v1", "managed", "evidence", "launch", "receipt")
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [], routes=lambda: [], agent_offer=lambda params: {})
        admission.observe_agent_event({"session_id": "session", "turn_id": "turn"}, "turn.completed", source_binding=binding)
        self.assertEqual(self.work.get("request-1", "sumika")["status"], "executing")

    def test_agent_offer_uses_host_binding_and_rechecks_before_reservation(self):
        binding = RuntimeBinding("fixture", "profile", "release", "v1", "managed", "evidence", "launch", "receipt")
        current = [binding]
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [], routes=lambda: [],
            agent_offer=lambda params: {**self.offer, "runtime_binding": {"forged": True}},
            runtime_binding=lambda: current[0])
        params = {**self.params, "sessionId": "session", "runtime_binding": {"forged": True}}
        offer = admission.offer("agent.session.prompt", params)
        self.assertEqual(offer["runtime_binding"], binding.to_dict())
        value = self.work.external_preflight(params, offer)
        self.confirm(value)
        current[0] = replace(binding, launch_id="restarted")
        execute = Mock()
        with self.assertRaisesRegex(RoutingError, "changed before dispatch"):
            self.work.external_dispatch(params, offer, execute,
                refresh_offer=lambda: admission.offer("agent.session.prompt", params))
        execute.assert_not_called()
        saved = self.work.get(value["request_id"], "sumika")
        self.assertEqual(saved["attempts"], {})
        self.assertEqual(saved["authorization"]["reserved_cny"], "0")
        restarted = admission.offer("agent.session.prompt", params)
        self.assertEqual(offer["execution_key"], restarted["execution_key"])
        current[0] = replace(binding, instance_id="another-profile")
        self.assertNotEqual(offer["execution_key"], admission.offer("agent.session.prompt", params)["execution_key"])

    def test_stable_profile_without_launch_evidence_cannot_dispatch(self):
        binding = RuntimeBinding("fixture", "profile", "release", "v1", "managed", "evidence")
        self.offer.update(source="agent", complexity="complex", runtime_binding=binding.to_dict())
        execute = Mock()
        self.confirm(self.dispatch(execute)["work_request"])
        with self.assertRaisesRegex(RoutingError, "launch identity is unverified"):
            self.dispatch(execute)
        execute.assert_not_called()
        self.assertEqual(self.work.get("request-1", "sumika")["attempts"], {})


class LegacyAdmissionEntryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"SUMIKA_AGENT_RUNTIME": "none", "SUMIKA_AGENT_AUTOSTART": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        self.server, self.app = create_server("127.0.0.1", 0, ":memory:")
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.app.close)

    def test_agent_public_entry_does_not_call_uncontrolled_harness(self):
        with patch.object(self.app.agent, "prompt") as execute:
            result = self.app.rpc("agent.session.prompt", {"sessionId": "remote", "text": "执行任务",
                                                          "approved": True, "routingApproved": True})
        self.assertEqual(result["status"], "awaiting-confirmation")
        self.assertIn("硬上限", result["work_request"]["status_detail"])
        execute.assert_not_called()

    def test_public_agent_parent_confirmation_covers_frozen_child_only(self):
        offer = {"candidate_id": "fixture:bounded", "identity": ["fixture", "v1"], "high_cny": "2",
                 "limit_enforced": True, "free": False, "funding": "cash"}
        params = {"sessionId": "parent", "text": "整理研究", "client_request_id": "parent-work", "external_steps": [
            {"id": "verify", "purpose": "核验结论", "method": "agent.session.prompt", "params": {"sessionId": "child", "text": "验证研究结论"}}
        ]}
        received = []
        def execute(request):
            received.append(request)
            self.assertFalse({"parent_work_request_id", "parent_revision", "parent_step_id", "external_steps", "work_request_id"}.intersection(request))
            return {"status": "completed", "turn_id": request["sessionId"] + "-turn", "text": "完成"}
        with patch.object(self.app.agent, "execution_quote", return_value=offer), patch.object(
            self.app, "_agent_workspace_safety_active", return_value=False
        ), patch.object(self.app.agent, "prompt", side_effect=execute):
            pending = self.app.rpc("agent.session.prompt", params)
            self.assertEqual(received, [])
            self.assertEqual(pending["work_request"]["quote"]["high_cny"], "4")
            trusted_rpc(self.app, "work.authorization.confirm", {"request_id": "parent-work", "assistant_id": "sumika", "revision": 1, "max_cny": "4"})
            parent = self.app.rpc("agent.session.prompt", params)["work_request"]
            step = parent["external_steps"][0]
            child_params = {**step["params"], "parent_work_request_id": "parent-work", "parent_revision": 1, "parent_step_id": "verify"}
            self.app.rpc("agent.session.prompt", child_params)
            self.app.rpc("agent.session.prompt", child_params)
            self.assertEqual(len(received), 2)
            final = self.app.rpc("work.task.get", {"request_id": "parent-work", "assistant_id": "sumika"})
            self.assertEqual(final["status"], "completed")
            self.assertEqual(final["authorization"]["spent_cny"], "4")

    def test_paid_and_unknown_web_are_blocked_even_with_approved_true(self):
        for policy in ("allow-paid", None):
            profile = {"id": "profile", "budget_policy": policy}
            with patch.object(self.app.storage, "list_web_chat_profiles", return_value=[profile]), patch.object(
                self.app.web_chat, "start_message"
            ) as execute:
                result = self.app.rpc("browser.web_chat.message.start",
                                      {"profile_id": "profile", "text": "hello", "client_request_id": str(policy), "approved": True})
                self.assertEqual(result["status"], "awaiting-confirmation")
                execute.assert_not_called()

    def test_controlled_fixture_checkpoint_follows_budget_confirmation(self):
        order = []
        params = {"sessionId": "external-session", "text": "完成工作区任务", "client_request_id": "agent-work"}
        offer = {"candidate_id": "fixture:bounded", "identity": ["fixture", "v1"], "high_cny": "2",
                 "limit_enforced": True, "free": False, "funding": "cash"}
        def checkpoint(*args, **kwargs):
            order.append("checkpoint")
            return {"checkpoint": {"id": "checkpoint", "workspace_id": "workspace"}}
        def execute(request):
            order.append("execute")
            self.assertNotIn("client_request_id", request)
            return {"accepted": True, "status": "completed", "turn_id": "turn"}
        with patch.object(self.app.agent, "execution_quote", return_value=offer), patch.object(
            self.app, "_agent_workspace_safety_active", return_value=True
        ), patch.object(self.app, "_agent_workspace_binding", return_value=({"id": "workspace"}, "fixture-path")), patch.object(
            self.app.workspace, "create_checkpoint", side_effect=checkpoint
        ), patch.object(self.app.agent, "prompt", side_effect=execute):
            pending = self.app.rpc("agent.session.prompt", params)
            self.assertEqual(order, [])
            trusted_rpc(self.app, "work.authorization.confirm", {"request_id": pending["work_request_id"],
                         "assistant_id": "sumika", "revision": 1, "max_cny": "2"})
            result = self.app.rpc("agent.session.prompt", params)
        self.assertEqual(order, ["checkpoint", "execute"])
        self.assertEqual(result["workspace_checkpoint"]["id"], "checkpoint")
        self.assertEqual(result["work_request"]["authorization"]["spent_cny"], "2")

    def test_route_and_consultation_unknown_cost_cannot_dispatch(self):
        with patch.object(self.app.route_supervisor, "dispatch") as dispatch, patch.object(
            self.app.route_supervisor, "start_consultation"
        ) as consultation:
            for method in ("sumika.route.dispatch", "sumika.consultation.start"):
                result = self.app.rpc(method, {"goal": "执行工作", "approved": True})
                self.assertEqual(result["status"], "awaiting-confirmation")
            dispatch.assert_not_called()
            consultation.assert_not_called()

    def test_event_cannot_invent_authorized_dispatch(self):
        with patch.object(self.app.route_supervisor, "dispatch") as execute:
            result = self.app._handle_route_boundary_event({
                "event_type": "turn.started", "event_id": "untrusted-event", "session_id": "session",
                "routing_request": {"goal": "spend", "approved": True, "confirmed": True},
                "dispatch_selected": True,
            })
        execute.assert_not_called()
        self.assertFalse(result.get("replanned", False))

    def test_free_web_public_entry_reuses_one_work_record_and_observes_completion(self):
        profile = {"id": "profile", "budget_policy": "free-only"}
        with patch.object(self.app.storage, "list_web_chat_profiles", return_value=[profile]), patch.object(
            self.app.web_chat, "list_profiles", return_value=[profile]
        ), patch.object(self.app.web_chat, "start_message", return_value={
            "accepted": True, "status": "running", "attempt_id": "upstream"
        }) as execute, patch.object(self.app, "_sync_web_chat_providers"):
            params = {"profile_id": "profile", "text": "hello", "client_request_id": "web-request"}
            result = self.app.rpc("browser.web_chat.message.start", params)
            self.app.rpc("browser.web_chat.message.start", params)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(result["work_request_id"], "web-request")
        with patch.object(self.app.web_chat, "message_status", return_value={
            "status": "completed", "ok": True, "attempt_id": "upstream", "text": "answer"
        }), patch.object(self.app, "_sync_web_chat_providers"), patch.object(self.app, "_refresh_route_supervisor_catalog"):
            result = self.app.rpc("browser.web_chat.message.status", {"attempt_id": "upstream"})
        self.assertEqual(result["work_request"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
