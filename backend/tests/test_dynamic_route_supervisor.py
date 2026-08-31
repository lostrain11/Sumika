"""Focused contract tests for the runtime-neutral route supervisor."""

from __future__ import annotations

import json
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from sumika_core.agent.supervisor import (
    EVENT_BOUNDARIES,
    DynamicRouteEvidence,
    DynamicRouteSupervisor,
    DynamicSubtaskDispatch,
    EvidenceResolver,
    ExternalHarnessWorker,
    ProviderWorker,
    RuntimeRouteDescriptor,
    WorkerRegistry,
)
from sumika_core.storage import Storage


def _route(route_id: str, *, kind: str = "provider", **overrides):
    values = {
        "route_id": route_id,
        "kind": kind,
        "label": route_id,
        "status": "ready",
        "routable": True,
        "capabilities": ("text", "code"),
        "quality_tier": "standard",
        "cost_class": "local",
        "processing_location": "local",
        "auth_state": "not-required",
        "health_state": "healthy",
        "quota_state": "not-applicable",
        "runtime_id": "fixture",
        "executor": route_id,
    }
    values.update(overrides)
    return RuntimeRouteDescriptor(**values)


class DynamicRouteSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.supervisors: list[DynamicRouteSupervisor] = []

    def tearDown(self):
        for supervisor in self.supervisors:
            supervisor.close()

    def make_supervisor(self, routes, workers, **kwargs):
        registry = WorkerRegistry()
        for worker_id, worker in workers:
            registry.register(worker_id, worker)
        supervisor = DynamicRouteSupervisor(registry, routes=routes, **kwargs)
        self.supervisors.append(supervisor)
        return supervisor

    def test_evidence_is_ranked_and_expiry_downgrades_to_unknown(self):
        resolver = EvidenceResolver()
        fresh = DynamicRouteEvidence(
            evidence_type="smoke",
            source="fixture",
            route_id="route-a",
            confidence="high",
        )
        expired = DynamicRouteEvidence(
            evidence_type="real-run",
            source="fixture",
            route_id="route-a",
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            confidence="high",
        )
        resolver.add(fresh)
        resolver.add(expired)
        selected = resolver.resolve("route-a", purpose="capability")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.effective_type, "smoke")
        self.assertTrue(selected.fresh)
        only_expired = EvidenceResolver([expired]).resolve("route-a", purpose="capability")
        self.assertIsNotNone(only_expired)
        self.assertEqual(only_expired.effective_type, "unknown")
        self.assertEqual(only_expired.effective_confidence, "unknown")
        self.assertEqual(selected.to_dict()["schema"], "route-evidence/v1")

    def test_catalog_exposes_runtime_worker_transport_and_evidence(self):
        route = _route("route-catalog")
        worker = ProviderWorker(lambda dispatch: {"status": "completed", "answer": "ok"}, worker_id="route-catalog", runtime_id="fixture")
        supervisor = self.make_supervisor([route], [("route-catalog", worker)])
        evidence = supervisor.add_evidence(
            {"evidence_type": "protocol-probe", "source": "fixture", "route_id": route.route_id},
            route_id=route.route_id,
        )
        supervisor.register_route(_route("route-evidence", evidence_refs=(evidence.evidence_id,)))
        catalog = supervisor.catalog()
        item = next(value for value in catalog["routes"] if value["route_id"] == "route-catalog")
        self.assertEqual(item["runtime_id"], "fixture")
        self.assertIn("kind", catalog["workers"][0])
        self.assertEqual(catalog["evidence_schema"], "route-evidence/v1")

    def test_only_event_boundaries_replan_and_duplicate_event_is_ignored(self):
        route = _route("route-event", cost_class="local")
        worker = ProviderWorker(lambda dispatch: {"status": "completed", "answer": "event-result"}, worker_id="route-event")
        supervisor = self.make_supervisor([route], [("route-event", worker)])
        request = {
            "parent_session_id": "session-event",
            "parent_turn_id": "turn-event",
            "question": "small task",
            "route_id": route.route_id,
            "min_quality_tier": "basic",
            "confirmation_mode": "automatic",
            "auto_dispatch": True,
        }
        rejected = supervisor.handle_event({"event_type": "model.streaming", "event_id": "e-1"}, request)
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["reason"], "not-event-boundary")
        accepted = supervisor.handle_event({"event_type": "turn.started", "event_id": "e-2"}, request)
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["status"], "dispatched")
        duplicate = supervisor.handle_event({"event_type": "turn.started", "event_id": "e-2"}, request)
        self.assertTrue(duplicate["duplicate"])
        self.assertIn("turn.started", EVENT_BOUNDARIES)
        dispatch_id = accepted["dispatch"]["dispatch_id"]
        self.assertEqual(supervisor.wait(dispatch_id, timeout=2)["status"], "completed")

    def test_three_concurrent_and_four_total_dispatch_limits_are_enforced(self):
        started = [threading.Event() for _ in range(3)]
        release = threading.Event()

        def execute(dispatch, route, cancel_event):
            index = int(dispatch.question.rsplit("-", 1)[-1])
            if index < len(started):
                started[index].set()
            release.wait(timeout=2)
            return {"status": "completed", "answer": dispatch.question}

        route = _route("route-limit")
        worker = ProviderWorker(execute, worker_id="route-limit")
        supervisor = self.make_supervisor([route], [("route-limit", worker)])
        ids = []
        for index in range(3):
            result = supervisor.dispatch(
                {
                    "parent_session_id": "session-limit",
                    "parent_turn_id": "turn-limit",
                    "route_id": route.route_id,
                    "question": f"job-{index}",
                    "worker_kind": "provider",
                }
            )
            self.assertTrue(result["accepted"])
            ids.append(result["dispatch_id"])
        for event in started:
            self.assertTrue(event.wait(timeout=1))
        blocked = supervisor.dispatch(
            {
                "parent_session_id": "session-limit",
                "parent_turn_id": "turn-limit",
                "route_id": route.route_id,
                "question": "job-3",
            }
        )
        self.assertFalse(blocked["accepted"])
        self.assertEqual(blocked["error_code"], "max-concurrent-workers")
        release.set()
        for dispatch_id in ids:
            self.assertEqual(supervisor.wait(dispatch_id, timeout=2)["status"], "completed")
        fourth = supervisor.dispatch(
            {
                "parent_session_id": "session-limit",
                "parent_turn_id": "turn-limit",
                "route_id": route.route_id,
                "question": "job-4",
            }
        )
        self.assertTrue(fourth["accepted"])
        self.assertEqual(supervisor.wait(fourth["dispatch_id"], timeout=2)["status"], "completed")
        fifth = supervisor.dispatch(
            {
                "parent_session_id": "session-limit",
                "parent_turn_id": "turn-limit",
                "route_id": route.route_id,
                "question": "job-5",
            }
        )
        self.assertFalse(fifth["accepted"])
        self.assertEqual(fifth["error_code"], "max-dispatches-per-turn")

    def test_duplicate_dispatch_is_deduplicated_without_second_execution(self):
        calls = []
        route = _route("route-dedupe")

        def execute(dispatch):
            calls.append(dispatch.dispatch_id)
            return {"status": "completed", "answer": "one"}

        supervisor = self.make_supervisor([route], [(route.route_id, ProviderWorker(execute, worker_id=route.route_id))])
        payload = {
            "parent_session_id": "session-dedupe",
            "parent_turn_id": "turn-dedupe",
            "route_id": route.route_id,
            "question": "same question",
        }
        first = supervisor.dispatch(payload, wait=True)
        second = supervisor.dispatch(payload, wait=True)
        self.assertEqual(first["status"], "completed")
        self.assertTrue(second["deduplicated"])
        self.assertEqual(first["dispatch_id"], second["dispatch_id"])
        self.assertEqual(len(calls), 1)

    def test_depth_and_sensitive_context_are_rejected(self):
        route = _route("route-security")
        supervisor = self.make_supervisor([route], [(route.route_id, ProviderWorker(lambda _: "ok", worker_id=route.route_id))])
        too_deep = supervisor.dispatch(
            {
                "parent_session_id": "session-security",
                "parent_turn_id": "turn-security",
                "route_id": route.route_id,
                "question": "nested",
                "depth": 2,
            }
        )
        self.assertFalse(too_deep["accepted"])
        self.assertEqual(too_deep["error_code"], "max-depth")
        with self.assertRaises(Exception):
            supervisor.dispatch(
                {
                    "parent_session_id": "session-security",
                    "parent_turn_id": "turn-security-2",
                    "route_id": route.route_id,
                    "question": "unsafe",
                    "context_refs": {"path": "C:\\repo\\.env"},
                }
            )

    def test_external_harness_worker_returns_structured_result(self):
        route = _route("route-zcode", kind="external-harness", runtime_id="zcode", executor="zcode-worker", cost_class="free-limited", processing_location="cloud", auth_state="authorized", quota_state="unknown")
        worker = ExternalHarnessWorker(
            lambda dispatch, route: {"status": "completed", "structured_result": {"session": "opaque-id", "ok": True}},
            worker_id="zcode-worker",
            runtime_id="zcode",
        )
        supervisor = self.make_supervisor([route], [("zcode-worker", worker)])
        result = supervisor.dispatch(
            DynamicSubtaskDispatch(
                dispatch_id="dispatch-zcode",
                parent_session_id="session-zcode",
                parent_turn_id="turn-zcode",
                route_id=route.route_id,
                question="run isolated check",
                worker_kind="external-harness",
                quota_consent=True,
            ),
            wait=True,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["runtime_id"], "zcode")
        self.assertIn("opaque-id", json.dumps(result, ensure_ascii=False))

    def test_metadata_sink_never_receives_prompt_or_answer(self):
        captured = []
        route = _route("route-metadata")
        supervisor = self.make_supervisor(
            [route],
            [(route.route_id, ProviderWorker(lambda _: {"status": "completed", "answer": "secret answer"}, worker_id=route.route_id))],
            metadata_sink=captured.append,
        )
        result = supervisor.dispatch(
            {
                "parent_session_id": "session-metadata",
                "parent_turn_id": "turn-metadata",
                "route_id": route.route_id,
                "question": "private prompt",
            },
            wait=True,
        )
        self.assertEqual(result["status"], "completed")
        serialized = json.dumps(captured, ensure_ascii=False)
        self.assertNotIn("private prompt", serialized)
        self.assertNotIn("secret answer", serialized)
        self.assertTrue(any(item.get("summary_hash") for item in captured if item.get("status") == "completed"))
        self.assertTrue(all("context_refs" not in item for item in captured))

    def test_paid_or_unknown_quota_route_is_recommendation_only(self):
        route = _route("route-paid", cost_class="paid-high", processing_location="cloud", auth_state="authorized", quota_state="unknown")
        supervisor = self.make_supervisor([route], [(route.route_id, ProviderWorker(lambda _: "must-not-run", worker_id=route.route_id))])
        result = supervisor.replan(
            {
                "parent_session_id": "session-paid",
                "parent_turn_id": "turn-paid",
                "route_id": route.route_id,
                "question": "expensive task",
                "confirmation_mode": "automatic",
                "auto_dispatch": True,
            }
        )
        self.assertEqual(result["status"], "needs-confirmation")
        self.assertTrue(result["requires_confirmation"])
        self.assertIsNone(result["dispatch"])
        self.assertIn("cost_or_quota_confirmation_required", result["reason_codes"])

    def test_consultation_runs_members_in_parallel_and_deduplicates_provider(self):
        started = [threading.Event() for _ in range(3)]
        release = threading.Event()

        def make_worker(worker_id, answer, index):
            def execute(dispatch, route, cancel_event):
                started[index].set()
                release.wait(timeout=2)
                return {"status": "completed", "answer": answer}

            return worker_id, ProviderWorker(execute, worker_id=worker_id, runtime_id="browser")

        routes = [
            _route(
                "web-panel-a",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-a",
                provider_key="provider-a",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
            # Same provider, different profile: it must not consume another
            # panel slot.
            _route(
                "web-panel-a-duplicate",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-a-2",
                provider_key="provider-a",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
            _route(
                "web-panel-b",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-b",
                provider_key="provider-b",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
            _route(
                "web-panel-c",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-c",
                provider_key="provider-c",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
        ]
        workers = [
            make_worker("web-panel-a", "answer-a", 0),
            make_worker("web-panel-a-duplicate", "duplicate-must-not-run", 0),
            make_worker("web-panel-b", "answer-b", 1),
            make_worker("web-panel-c", "answer-c", 2),
        ]
        supervisor = self.make_supervisor(routes, workers)
        started_at = time.monotonic()
        result = supervisor.start_consultation(
            {
                "consultation_id": "consultation-parallel",
                "parent_session_id": "session-panel",
                "question": "independent opinions",
                "decision_kind": "brainstorm",
                "max_members": 3,
            }
        )
        self.assertEqual(result["status"], "running")
        for event in started:
            self.assertTrue(event.wait(timeout=1), "all selected panel members should start concurrently")
        self.assertLess(time.monotonic() - started_at, 1.5)
        self.assertEqual(
            {item["route_id"] for item in supervisor.consultation_status("consultation-parallel")["members"]},
            {"web-panel-a", "web-panel-b", "web-panel-c"},
        )
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            final = supervisor.consultation_status("consultation-parallel")
            if final["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["successful_count"], 3)
        self.assertEqual({item["answer"] for item in final["members"]}, {"answer-a", "answer-b", "answer-c"})

    def test_consultation_partial_and_total_failure_are_explicit(self):
        def result_worker(worker_id, payload):
            return worker_id, ProviderWorker(lambda dispatch, route, cancel_event: payload, worker_id=worker_id)

        partial_routes = [
            _route("web-partial-ok", kind="web-worker", source_kind="web-chat", provider_profile_id="partial-ok", provider_key="ok", quota_consent="granted", cost_class="unknown"),
            _route("web-partial-fail", kind="web-worker", source_kind="web-chat", provider_profile_id="partial-fail", provider_key="fail", quota_consent="granted", cost_class="unknown"),
        ]
        partial = self.make_supervisor(
            partial_routes,
            [
                result_worker("web-partial-ok", {"status": "completed", "answer": "one real opinion"}),
                result_worker("web-partial-fail", {"status": "failed", "error_code": "site-unavailable"}),
            ],
        ).start_consultation(
            {
                "consultation_id": "consultation-partial-modern",
                "parent_session_id": "session-partial-modern",
                "question": "check failure handling",
                "decision_kind": "fact-check",
                "max_members": 2,
            },
            wait=True,
            timeout=2,
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["successful_count"], 1)
        self.assertEqual(partial["failed_count"], 1)
        failed = next(item for item in partial["members"] if item["status"] == "failed")
        self.assertIsNone(failed["answer"])

        total_supervisor = self.make_supervisor(
            [_route("web-total-fail", kind="web-worker", source_kind="web-chat", provider_profile_id="total-fail", provider_key="total", quota_consent="granted", cost_class="unknown")],
            [result_worker("web-total-fail", {"status": "failed", "error_code": "offline"})],
        )
        total = total_supervisor.start_consultation(
            {
                "consultation_id": "consultation-total-modern",
                "parent_session_id": "session-total-modern",
                "question": "do not fabricate",
                "decision_kind": "small-answer",
                "max_members": 1,
            },
            wait=True,
            timeout=2,
        )
        self.assertEqual(total["status"], "failed")
        self.assertEqual(total["failed_count"], 1)
        self.assertIsNone(total["members"][0]["answer"])

    def test_unknown_quota_requires_profile_consent_and_unavailable_filter_is_honest(self):
        calls = []

        def execute(dispatch, route, cancel_event):
            calls.append(dispatch.dispatch_id)
            return {"status": "completed", "answer": "must not run"}

        unknown = _route(
            "route-unknown-quota",
            cost_class="unknown",
            quota_state="unknown",
            quota_consent="unknown",
        )
        unavailable = _route("route-unavailable", status="unavailable", routable=False)
        supervisor = self.make_supervisor(
            [unknown, unavailable],
            [(unknown.route_id, ProviderWorker(execute, worker_id=unknown.route_id))],
        )
        catalog = supervisor.catalog(include_unavailable=False)
        self.assertEqual([item["route_id"] for item in catalog["routes"]], [unknown.route_id])
        result = supervisor.dispatch(
            {
                "parent_session_id": "session-unknown-quota",
                "route_id": unknown.route_id,
                "question": "requires consent",
            }
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["status"], "needs-confirmation")
        self.assertEqual(result["error_code"], "confirmation-required")
        self.assertEqual(calls, [])

    def test_dispatch_rejects_terminal_quota_and_busy_panel_profiles(self):
        calls = []

        def execute(dispatch, route, cancel_event):
            calls.append(dispatch.dispatch_id)
            return {"status": "completed", "answer": "must not run"}

        exhausted = _route("route-exhausted", quota_state="exhausted")
        busy = _route(
            "web-busy",
            kind="web-worker",
            source_kind="web-chat",
            provider_profile_id="busy-profile",
            provider_key="busy-provider",
            quota_consent="granted",
            cost_class="unknown",
            occupancy="agent",
            capabilities=("text", "chat", "browser"),
        )
        supervisor = self.make_supervisor(
            [exhausted, busy],
            [
                (exhausted.route_id, ProviderWorker(execute, worker_id=exhausted.route_id)),
                (busy.route_id, ProviderWorker(execute, worker_id=busy.route_id)),
            ],
        )
        rejected = supervisor.dispatch(
            {
                "parent_session_id": "session-terminal-quota",
                "route_id": exhausted.route_id,
                "question": "do not use exhausted route",
            }
        )
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["error_code"], "quota-exhausted")
        panel = supervisor.start_consultation(
            {
                "consultation_id": "consultation-busy",
                "parent_session_id": "session-busy",
                "question": "wait for lease",
                "decision_kind": "small-answer",
                "max_members": 1,
            }
        )
        self.assertEqual(panel["status"], "failed")
        self.assertEqual(panel["members"], [])
        self.assertEqual(calls, [])

    def test_occupancy_projection_blocks_and_then_restores_a_profile_route(self):
        route = _route(
            "web-occupancy",
            kind="web-worker",
            source_kind="web-chat",
            provider_profile_id="profile-occupancy",
            provider_key="occupancy-provider",
            capabilities=("text", "chat", "browser"),
            processing_location="cloud",
            runtime_id="browserskill",
            transport="browser-dom",
            quota_consent="granted",
            quota_state="unknown",
            cost_class="unknown",
        )
        worker = ProviderWorker(lambda _: {"status": "completed", "answer": "ok"}, worker_id=route.route_id)
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])

        occupied = supervisor.update_occupancy("profile-occupancy", "manual")
        self.assertEqual(occupied["updated_routes"], 1)
        row = supervisor.catalog()["routes"][0]
        self.assertEqual(row["occupancy"], "manual")
        self.assertFalse(row["available"])
        self.assertTrue(row["routable"], "lease state must not erase source routability")
        self.assertEqual(row["reason"], "profile-occupied")

        released = supervisor.update_occupancy("profile-occupancy", "idle")
        self.assertEqual(released["updated_routes"], 1)
        row = supervisor.catalog()["routes"][0]
        self.assertEqual(row["occupancy"], "idle")
        self.assertTrue(row["available"])
        self.assertTrue(row["routable"])
        self.assertIsNone(row["reason"])

    def test_close_marks_active_consultation_and_members_interrupted(self):
        storage = Storage(":memory:")
        release = threading.Event()
        started = threading.Event()

        def execute(dispatch, route, cancel_event):
            started.set()
            release.wait(timeout=2)
            return {"status": "completed", "answer": "late result"}

        route = _route(
            "web-close",
            kind="web-worker",
            source_kind="web-chat",
            provider_profile_id="web-profile-close",
            provider_key="close-provider",
            runtime_id="browserskill",
            transport="browser-dom",
            processing_location="cloud",
            quota_consent="granted",
        )
        registry = WorkerRegistry()
        worker = ProviderWorker(execute, worker_id="web-close", runtime_id="browserskill")
        registry.register("web-close", worker)
        supervisor = DynamicRouteSupervisor(registry, routes=[route], storage=storage)
        request = {
            "consultation_id": "consultation-close",
            "parent_session_id": "session-close",
            "parent_turn_id": "turn-close",
            "question": "shutdown boundary",
            "decision_kind": "small-answer",
            "max_members": 1,
        }
        started_result = supervisor.start_consultation(request)
        self.assertEqual(started_result["status"], "running")
        self.assertTrue(started.wait(timeout=1))

        supervisor.close()
        status = supervisor.consultation_status("consultation-close")
        self.assertEqual(status["status"], "interrupted")
        self.assertTrue(status["found"])
        self.assertEqual(status["members"][0]["status"], "interrupted")
        row = storage.get_agent_consultation("consultation-close")
        self.assertEqual(row["status"], "interrupted")
        self.assertEqual(row["member_metadata"][0]["status"], "interrupted")

        # A late worker callback must not overwrite the shutdown outcome.
        release.set()
        time.sleep(0.05)
        self.assertEqual(supervisor.consultation_status("consultation-close")["status"], "interrupted")
        storage.close()


if __name__ == "__main__":
    unittest.main()
