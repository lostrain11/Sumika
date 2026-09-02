"""Focused contract tests for the runtime-neutral route supervisor."""

from __future__ import annotations

import json
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sumika_core.agent.supervisor import (
    EVENT_BOUNDARIES,
    DynamicRouteEvidence,
    DynamicRouteSupervisor,
    DynamicSubtaskDispatch,
    EvidenceResolver,
    ExternalHarnessWorker,
    ProviderWorker,
    RuntimeRouteDescriptor,
    SupervisorValidationError,
    WebWorker,
    WorkerRegistry,
)
from sumika_core.agent.runtime_workers import ProviderProfileWorker
from sumika_core.model_evaluation import EvaluationTaskSet
from sumika_core.route_pricing import RoutePricingService
from sumika_core.storage import Storage


TASK_SET_PATH = __import__("pathlib").Path(__file__).resolve().parents[2] / "tools" / "fixtures" / "model-evaluation-v1.json"


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

    def test_provider_worker_returns_request_usage_and_dual_currency_receipt(self):
        class Provider:
            def __init__(self):
                self.last_usage = {}

            def stream(self, _request):
                self.last_usage = {
                    "input_tokens": 1_000,
                    "output_tokens": 500,
                    "total_tokens": 1_500,
                }
                yield "provider answer"

        class Profiles:
            def __init__(self):
                self.provider = Provider()
                self.profile = {
                    "id": "priced-worker",
                    "adapter_id": "openai-compatible",
                    "status": "available",
                    "config": {
                        "model": "priced-model",
                        "models": [{"id": "priced-model"}],
                        "pricing": {
                            "source_type": "manual",
                            "billing_group": "default",
                            "rates": {
                                "currency": "USD-credit",
                                "input_price_per_million": 1,
                                "output_price_per_million": 2,
                            },
                            "cash_conversion": {
                                "paid_amount": 50,
                                "credited_amount": 100,
                                "currency": "CNY",
                            },
                        },
                    },
                }

            def list(self, *, include_archived=False):
                del include_archived
                return [self.profile]

            def get(self, profile_id):
                self.assert_profile(profile_id)
                return self.profile

            def runtime(self, profile_id, *, model_id=None):
                self.assert_profile(profile_id)
                if model_id != "priced-model":
                    raise AssertionError("worker did not select the route model")
                return self.provider

            def mark_used(self, profile_id):
                self.assert_profile(profile_id)
                return self.profile

            @staticmethod
            def assert_profile(profile_id):
                if profile_id != "priced-worker":
                    raise AssertionError("unexpected profile")

        profiles = Profiles()
        pricing = RoutePricingService(profiles)
        pricing.refresh_profiles(force=True)
        worker = ProviderProfileWorker(profiles, "priced-worker", pricing=pricing)
        route = _route(
            "profile:priced-worker:priced-model",
            provider_profile_id="priced-worker",
            metadata={
                "model_config": {"id": "priced-model"},
                "billing_group": "default",
            },
        )
        dispatch = DynamicSubtaskDispatch(
            dispatch_id="dispatch-priced-worker",
            parent_session_id="parent-session",
            route_id=route.route_id,
            question="answer briefly",
        )

        result = worker.execute(dispatch, route, threading.Event())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "provider answer")
        impact = result["budget_impact"]
        self.assertEqual(impact["usage"]["total_tokens"], 1_500)
        receipt = impact["charge_receipt"]
        self.assertEqual(receipt["evidence_level"], "request-usage-estimate")
        self.assertAlmostEqual(receipt["provider_charge"], 0.002)
        self.assertEqual(receipt["provider_currency"], "USD-credit")
        self.assertAlmostEqual(receipt["cash_charge"], 0.001)
        self.assertEqual(receipt["cash_currency"], "CNY")

    def test_public_boolean_contracts_reject_string_and_numeric_values(self):
        boolean_fields = (
            (RuntimeRouteDescriptor, {"route_id": "bool-route", "kind": "provider", "label": "bool", "routable": "false"}),
            (RuntimeRouteDescriptor, {"route_id": "bool-route-confirm", "kind": "provider", "label": "bool", "requires_confirmation": "false"}),
        )
        for constructor, values in boolean_fields:
            with self.subTest(values=values):
                with self.assertRaisesRegex(SupervisorValidationError, "boolean"):
                    constructor(**values)

        request_base = {"parent_session_id": "bool-session", "question": "boolean"}
        for field, value in (("auto_dispatch", "false"), ("quota_consent", 0), ("confirmed", "false")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(SupervisorValidationError, "boolean"):
                    from sumika_core.agent.supervisor import DynamicRoutingRequest

                    DynamicRoutingRequest(**request_base, **{field: value})

        route = _route("bool-result")
        dispatch = DynamicSubtaskDispatch(
            dispatch_id="bool-dispatch",
            parent_session_id="bool-session",
            route_id=route.route_id,
            question="boolean result",
        )
        for field, value in (("quota_consent", "false"), ("confirmed", 1)):
            with self.subTest(field=field):
                with self.assertRaisesRegex(SupervisorValidationError, "boolean"):
                    DynamicSubtaskDispatch(
                        dispatch_id=f"bool-dispatch-{field}",
                        parent_session_id="bool-session",
                        route_id=route.route_id,
                        question="boolean result",
                        **{field: value},
                    )
        for field, value in (("retryable", "false"), ("possibly_sent", 0), ("untrusted_external", "false")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(SupervisorValidationError, "boolean"):
                    from sumika_core.agent.supervisor import DynamicSubtaskResult

                    DynamicSubtaskResult.from_value({field: value}, dispatch)

    def test_worker_result_cannot_rename_the_accepted_dispatch_or_route(self):
        route = _route("web:modern-route", kind="web-worker")
        worker = ProviderWorker(
            lambda *_: {
                "dispatch_id": "legacy-dispatch",
                "route_id": "web-chat:legacy-route",
                "status": "completed",
                "answer": "ok",
            },
            worker_id=route.route_id,
        )
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])

        result = supervisor.dispatch(
            {
                "dispatch_id": "modern-dispatch",
                "parent_session_id": "modern-session",
                "route_id": route.route_id,
                "worker_kind": "web",
                "question": "keep modern identity",
            },
            wait=True,
            timeout=1,
        )

        self.assertEqual(result["result"]["dispatch_id"], "modern-dispatch")
        self.assertEqual(result["result"]["route_id"], "web:modern-route")

    def test_web_worker_accepts_a_response_just_after_nominal_deadline(self):
        route = _route("web-grace", kind="web-worker")

        def execute(_dispatch, _route, _cancel_event):
            time.sleep(0.04)
            return {"status": "completed", "answer": "arrived during transport grace"}

        worker = WebWorker(execute, worker_id=route.route_id, timeout_ms=20)
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])
        with patch("sumika_core.agent.supervisor.WORKER_TIMEOUT_GRACE_SECONDS", 0.05):
            result = supervisor.dispatch(
                {
                    "parent_session_id": "grace-session",
                    "parent_turn_id": "grace-turn",
                    "route_id": route.route_id,
                    "worker_kind": "web-worker",
                    "question": "grace boundary",
                },
                wait=True,
            )

        self.assertEqual(result["status"], "completed", result)
        self.assertGreaterEqual(result["latency_ms"], 20)

    def test_web_worker_that_misses_grace_is_deadline_exceeded(self):
        route = _route("web-grace-expired", kind="web-worker")

        def execute(_dispatch, _route, _cancel_event):
            time.sleep(0.08)
            return {"status": "completed", "answer": "late"}

        worker = WebWorker(execute, worker_id=route.route_id, timeout_ms=10)
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])
        with patch("sumika_core.agent.supervisor.WORKER_TIMEOUT_GRACE_SECONDS", 0.01):
            result = supervisor.dispatch(
                {
                    "parent_session_id": "grace-expired-session",
                    "parent_turn_id": "grace-expired-turn",
                    "route_id": route.route_id,
                    "worker_kind": "web-worker",
                    "question": "past grace",
                },
                wait=True,
            )

        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(result["error_code"], "deadline-exceeded")
        self.assertTrue(result["possibly_sent"])

    def test_provider_worker_does_not_receive_web_transport_grace(self):
        route = _route("provider-no-grace")

        def execute(_dispatch, _route, _cancel_event):
            time.sleep(0.04)
            return {"status": "completed", "answer": "too late for provider"}

        worker = ProviderWorker(execute, worker_id=route.route_id, timeout_ms=20)
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])
        with patch("sumika_core.agent.supervisor.WORKER_TIMEOUT_GRACE_SECONDS", 0.05):
            result = supervisor.dispatch(
                {
                    "parent_session_id": "provider-timeout-session",
                    "parent_turn_id": "provider-timeout-turn",
                    "route_id": route.route_id,
                    "question": "no grace",
                },
                wait=True,
            )

        self.assertEqual(result["status"], "unknown", result)
        self.assertEqual(result["error_code"], "deadline-exceeded")

    def test_dispatch_applies_capability_privacy_quality_and_evidence_gates(self):
        calls = []

        def execute(dispatch):
            calls.append(dispatch.dispatch_id)
            return {"status": "completed", "answer": "must not run"}

        routes = [
            _route("gate-capability", capabilities=("text",)),
            _route("gate-privacy", processing_location="cloud"),
            _route("gate-quality", quality_tier="basic"),
            _route("gate-evidence", quality_tier="strong"),
        ]
        supervisor = self.make_supervisor(routes, [(route.route_id, ProviderWorker(execute, worker_id=route.route_id)) for route in routes])

        cases = (
            ("gate-capability", {"required_capabilities": ("tools",)}, "missing-capability"),
            ("gate-privacy", {"privacy_constraints": ("local-only",)}, "privacy-constraint"),
            ("gate-quality", {"difficulty": "complex"}, "quality-gate"),
            ("gate-evidence", {"risk": "high"}, "evidence-insufficient"),
        )
        for route_id, options, error_code in cases:
            with self.subTest(route_id=route_id):
                result = supervisor.dispatch(
                    {
                        "parent_session_id": "gate-session",
                        "route_id": route_id,
                        "question": "gate check",
                        **options,
                    }
                )
                self.assertFalse(result["accepted"])
                self.assertEqual(result["error_code"], error_code)
        self.assertEqual(calls, [])

    def test_explicit_unknown_quality_route_remains_dispatchable(self):
        route = _route("gate-unknown-quality", quality_tier="unknown")
        supervisor = self.make_supervisor(
            [route],
            [(route.route_id, ProviderWorker(lambda _: {"status": "completed", "answer": "ok"}, worker_id=route.route_id))],
        )
        result = supervisor.dispatch(
            {
                "parent_session_id": "gate-explicit",
                "route_id": route.route_id,
                "question": "explicit compatibility route",
                "difficulty": "complex",
            },
            wait=True,
        )
        self.assertEqual(result["status"], "completed")

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

    def test_nested_event_envelope_id_is_deduplicated_but_result_id_is_ignored(self):
        route = _route("route-nested-event")
        calls = []

        def execute(dispatch):
            calls.append(dispatch.dispatch_id)
            return {"status": "completed", "answer": "nested-result"}

        supervisor = self.make_supervisor(
            [route],
            [(route.route_id, ProviderWorker(execute, worker_id=route.route_id))],
        )
        request = {
            "parent_session_id": "session-nested-event",
            "parent_turn_id": "turn-nested-event",
            "route_id": route.route_id,
            "question": "nested boundary",
            "confirmation_mode": "automatic",
            "auto_dispatch": True,
        }
        envelope = {
            "method": "session/event",
            "params": {
                "event": {
                    "type": "turn.started",
                    "id": "nested-event-1",
                    "sessionId": "session-nested-event",
                    "turnId": "turn-nested-event",
                },
                "result": {"id": "user-result-id"},
            },
        }
        first = supervisor.handle_event(envelope, request)
        self.assertEqual(first["status"], "dispatched")
        duplicate = supervisor.handle_event(envelope, request)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(supervisor.wait(first["dispatch"]["dispatch_id"], timeout=2)["status"], "completed")

        # A normal application result with ``status: completed`` and an ID is
        # not a turn boundary and must not cause a second dispatch.
        ordinary = supervisor.handle_event(
            {"result": {"status": "completed", "id": "ordinary-result"}},
            request,
        )
        self.assertFalse(ordinary["accepted"])
        self.assertEqual(ordinary["reason"], "not-event-boundary")
        self.assertEqual(len(calls), 1)

    def test_nested_extensions_event_id_consumes_session_armed_request_once(self):
        route = _route("route-armed-nested")
        worker = ProviderWorker(
            lambda dispatch: {"status": "completed", "answer": dispatch.question},
            worker_id=route.route_id,
        )
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])
        armed = supervisor.arm_turn(
            {
                "parent_session_id": "session-armed-nested",
                "parent_turn_id": "turn-armed-nested",
                "route_id": route.route_id,
                "question": "armed once",
                "trigger_event": "turn.completed",
                "confirmation_mode": "automatic",
                "auto_dispatch": True,
            }
        )
        self.assertTrue(armed["armed"])
        event = {
            "extensions": {
                "event": {
                    "eventId": "extensions-event-1",
                    "type": "turn.completed",
                    "sessionId": "session-armed-nested",
                    "turnId": "turn-armed-nested",
                }
            }
        }
        first = supervisor.handle_event(event)
        self.assertEqual(first["status"], "dispatched")
        duplicate = supervisor.handle_event(event)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(supervisor.wait(first["dispatch"]["dispatch_id"], timeout=2)["status"], "completed")

    def test_session_level_boundary_does_not_guess_when_multiple_turns_are_armed(self):
        route = _route("route-ambiguous-session")
        worker = ProviderWorker(
            lambda dispatch: {"status": "completed", "answer": dispatch.question},
            worker_id=route.route_id,
        )
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])
        for turn_id in ("turn-a", "turn-b"):
            supervisor.arm_turn(
                {
                    "parent_session_id": "session-ambiguous",
                    "parent_turn_id": turn_id,
                    "route_id": route.route_id,
                    "question": turn_id,
                    "trigger_event": "turn.completed",
                    "confirmation_mode": "automatic",
                    "auto_dispatch": True,
                }
            )
        result = supervisor.handle_event(
            {"event": {"type": "turn.completed", "event_id": "ambiguous-1", "sessionId": "session-ambiguous"}}
        )
        self.assertTrue(result["accepted"])
        self.assertFalse(result["replanned"])
        self.assertEqual(result["reason"], "no-routing-request")
        self.assertEqual(supervisor.active_runs(), [])

    def test_boundary_replan_can_select_a_new_worker_only_from_an_explicit_request(self):
        calls = []

        def make_worker(label):
            def execute(dispatch):
                calls.append(label)
                return {"status": "completed", "answer": f"{label}-answer"}

            return ProviderWorker(execute, worker_id=f"worker-{label}")

        first = _route("route-first")
        second = _route("route-second")
        supervisor = self.make_supervisor(
            [first, second],
            [(first.route_id, make_worker("first")), (second.route_id, make_worker("second"))],
        )
        initial = {
            "parent_session_id": "session-boundary",
            "parent_turn_id": "turn-boundary",
            "question": "initial worker",
            "route_id": first.route_id,
            "confirmation_mode": "automatic",
            "auto_dispatch": True,
        }
        started = supervisor.handle_event({"event_type": "turn.started", "event_id": "boundary-1"}, initial)
        self.assertEqual(started["status"], "dispatched")
        self.assertEqual(supervisor.wait(started["dispatch"]["dispatch_id"], timeout=2)["status"], "completed")

        # A streaming event cannot trigger an implicit semantic split.
        rejected = supervisor.handle_event(
            {"event_type": "model.streaming", "event_id": "boundary-stream"},
            dict(initial, route_id=second.route_id, question="must not dispatch"),
        )
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["reason"], "not-event-boundary")

        # At the next permitted boundary, the main Agent supplies a new,
        # explicit request.  The supervisor may then choose the other worker.
        next_request = dict(initial, route_id=second.route_id, question="follow-up worker")
        replanned = supervisor.handle_event({"event_type": "tool.completed", "event_id": "boundary-2"}, next_request)
        self.assertEqual(replanned["status"], "dispatched")
        self.assertEqual(supervisor.wait(replanned["dispatch"]["dispatch_id"], timeout=2)["status"], "completed")
        self.assertEqual(calls, ["first", "second"])

    def test_supervisor_evaluation_capture_is_explicit_and_terminal_only(self):
        task_set = EvaluationTaskSet.from_file(TASK_SET_PATH)
        route = _route("route-capture")
        worker = ProviderWorker(
            lambda dispatch: {"status": "completed", "answer": "answer-body-must-not-be-captured"},
            worker_id=route.route_id,
        )
        supervisor = self.make_supervisor([route], [(route.route_id, worker)])
        dispatched = supervisor.dispatch(
            {
                "parent_session_id": "session-capture",
                "parent_turn_id": "turn-capture",
                "route_id": route.route_id,
                "question": "question-body-must-not-be-captured",
            },
            wait=True,
        )
        dispatch_id = dispatched["dispatch_id"]
        with self.assertRaisesRegex(SupervisorValidationError, "capture-opt-in-required"):
            supervisor.capture_evaluation_sample(dispatch_id, task_set, task_id="read-only-question")
        captured = supervisor.capture_evaluation_sample(
            dispatch_id,
            task_set,
            task_id="read-only-question",
            opt_in=True,
            manifest={
                "task_set_id": "sumika-agent-core",
                "task_set_version": "1.0.0",
                "harness_id": "dsh",
                "harness_version": "fixture",
                "adapter_id": "fixture-adapter",
                "adapter_version": "1",
                "provider_kind": "local",
                "model_id": "fixture-model",
                "model_version": "1",
                "hardware_class": "fixture",
                "privacy_policy": "local-only",
                "cache_state": "cold",
            },
        )
        serialized = json.dumps(captured.to_dict(), ensure_ascii=False)
        self.assertNotIn("answer-body-must-not-be-captured", serialized)
        self.assertNotIn("question-body-must-not-be-captured", serialized)

    def test_three_concurrent_and_six_total_dispatch_limits_are_enforced(self):
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
        self.assertTrue(fifth["accepted"])
        self.assertEqual(supervisor.wait(fifth["dispatch_id"], timeout=2)["status"], "completed")
        sixth = supervisor.dispatch(
            {
                "parent_session_id": "session-limit",
                "parent_turn_id": "turn-limit",
                "route_id": route.route_id,
                "question": "job-6",
            }
        )
        self.assertTrue(sixth["accepted"])
        self.assertEqual(supervisor.wait(sixth["dispatch_id"], timeout=2)["status"], "completed")
        seventh = supervisor.dispatch(
            {
                "parent_session_id": "session-limit",
                "parent_turn_id": "turn-limit",
                "route_id": route.route_id,
                "question": "job-7",
            }
        )
        self.assertFalse(seventh["accepted"])
        self.assertEqual(seventh["error_code"], "max-dispatches-per-turn")

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

    def test_five_member_consultation_queues_in_three_plus_two_waves(self):
        lock = threading.Lock()
        active = 0
        peak = 0

        def execute(dispatch, route, cancel_event):
            nonlocal active, peak
            del dispatch, cancel_event
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return {"status": "completed", "answer": route.route_id}

        routes = [
            _route(
                f"web-five-{index}",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id=f"profile-five-{index}",
                provider_key=f"provider-five-{index}",
                quota_consent="granted",
                cost_class="unknown",
            )
            for index in range(5)
        ]
        supervisor = self.make_supervisor(
            routes,
            [
                (route.route_id, ProviderWorker(execute, worker_id=route.route_id))
                for route in routes
            ],
            max_concurrent=3,
            max_dispatches_per_turn=6,
        )

        result = supervisor.start_consultation(
            {
                "consultation_id": "consultation-five",
                "parent_session_id": "session-five",
                "parent_turn_id": "turn-five",
                "question": "five independent opinions",
                "decision_kind": "plan-review",
                "max_members": 5,
            },
            wait=True,
            timeout=3,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["successful_count"], 5)
        self.assertEqual(len(result["members"]), 5)
        self.assertEqual(peak, 3)

    def test_consultation_projects_a_started_second_wave_as_running(self):
        first_three_started = [threading.Event() for _ in range(3)]
        release_first = threading.Event()
        release_rest = threading.Event()
        fourth_started = threading.Event()

        def execute(dispatch, route, cancel_event):
            del dispatch, cancel_event
            index = int(route.route_id.rsplit("-", 1)[1])
            if index < 3:
                first_three_started[index].set()
                if index == 0:
                    release_first.wait(timeout=2)
                else:
                    release_rest.wait(timeout=2)
            else:
                fourth_started.set()
                release_rest.wait(timeout=2)
            return {"status": "completed", "answer": route.route_id}

        routes = [
            _route(
                f"web-wave-{index}",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id=f"profile-wave-{index}",
                provider_key=f"provider-wave-{index}",
                quota_consent="granted",
                cost_class="unknown",
            )
            for index in range(4)
        ]
        supervisor = self.make_supervisor(
            routes,
            [
                (route.route_id, ProviderWorker(execute, worker_id=route.route_id))
                for route in routes
            ],
            max_concurrent=3,
        )

        try:
            supervisor.start_consultation(
                {
                    "consultation_id": "consultation-wave-status",
                    "parent_session_id": "session-wave-status",
                    "question": "show the second wave state",
                    "max_members": 4,
                }
            )
            self.assertTrue(all(event.wait(timeout=1) for event in first_three_started))
            release_first.set()
            self.assertTrue(fourth_started.wait(timeout=1))
            status = supervisor.consultation_status("consultation-wave-status")
            fourth = next(item for item in status["members"] if item["route_id"] == "web-wave-3")
            self.assertEqual(fourth["status"], "running")
        finally:
            release_first.set()
            release_rest.set()

    def test_parent_turn_accepts_six_dispatches_but_rejects_seventh(self):
        route = _route("route-six")
        supervisor = self.make_supervisor(
            [route],
            [(route.route_id, ProviderWorker(lambda *_: {"status": "completed", "answer": "ok"}, worker_id=route.route_id))],
            max_dispatches_per_turn=6,
        )
        for index in range(6):
            result = supervisor.dispatch(
                {
                    "dispatch_id": f"dispatch-six-{index}",
                    "parent_session_id": "session-six",
                    "parent_turn_id": "turn-six",
                    "route_id": route.route_id,
                    "question": f"question {index}",
                },
                wait=True,
                timeout=1,
            )
            self.assertTrue(result["accepted"], index)

        rejected = supervisor.dispatch(
            {
                "dispatch_id": "dispatch-six-overflow",
                "parent_session_id": "session-six",
                "parent_turn_id": "turn-six",
                "route_id": route.route_id,
                "question": "overflow",
            }
        )
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["error_code"], "max-dispatches-per-turn")

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

    def test_consultation_continuation_reuses_only_prior_profiles(self):
        calls: list[str] = []

        routes = [
            _route(
                "web-cont-a",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-cont-a",
                provider_key="provider-cont-a",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                health_state="healthy",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
            _route(
                "web-cont-b",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-cont-b",
                provider_key="provider-cont-b",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                health_state="healthy",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
            _route(
                "web-cont-new",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-cont-new",
                provider_key="provider-cont-new",
                runtime_id="browserskill",
                transport="browser-dom",
                processing_location="cloud",
                auth_state="authorized",
                health_state="healthy",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
        ]

        def worker(dispatch, route, cancel_event):
            calls.append(route.route_id)
            return {"status": "completed", "answer": route.route_id}

        supervisor = self.make_supervisor(
            routes,
            [(route.route_id, ProviderWorker(worker, worker_id=route.route_id)) for route in routes],
        )
        first = supervisor.start_consultation(
            {
                "consultation_id": "consultation-cont-first",
                "parent_session_id": "session-continuation",
                "question": "first opinions",
                "decision_kind": "brainstorm",
                "max_members": 2,
            },
            wait=True,
            timeout=2,
        )
        self.assertEqual(first["status"], "completed")
        first_routes = {item["route_id"] for item in first["members"]}
        self.assertEqual(first_routes, {"web-cont-a", "web-cont-b"})

        second = supervisor.start_consultation(
            {
                "consultation_id": "consultation-cont-second",
                "parent_session_id": "session-continuation",
                "question": "follow-up opinions",
                "decision_kind": "fact-check",
                "max_members": 3,
                "continuation_of": "consultation-cont-first",
            },
            wait=True,
            timeout=2,
        )
        self.assertEqual(second["status"], "completed")
        second_routes = {item["route_id"] for item in second["members"]}
        self.assertEqual(second_routes, first_routes)
        self.assertNotIn("web-cont-new", second_routes)
        second_dispatches = [
            item
            for item in supervisor.list_runs(parent_session_id="session-continuation")
            if item["dispatch"].get("consultation_id") == "consultation-cont-second"
        ]
        self.assertTrue(second_dispatches)
        self.assertTrue(all(item["dispatch"].get("continuation_of") == "consultation-cont-first" for item in second_dispatches))

    def test_unknown_consultation_continuation_fails_closed(self):
        route = _route(
            "web-cont-only",
            kind="web-worker",
            source_kind="web-chat",
            provider_profile_id="profile-cont-only",
            provider_key="provider-cont-only",
            runtime_id="browserskill",
            transport="browser-dom",
            processing_location="cloud",
            auth_state="authorized",
            health_state="healthy",
            quota_state="unknown",
            quota_consent="granted",
            cost_class="unknown",
            capabilities=("text", "chat", "browser"),
        )
        calls: list[str] = []
        supervisor = self.make_supervisor(
            [route],
            [(route.route_id, ProviderWorker(lambda *_: calls.append("called"), worker_id=route.route_id))],
        )
        result = supervisor.start_consultation(
            {
                "consultation_id": "consultation-cont-missing",
                "parent_session_id": "session-continuation-missing",
                "question": "must not choose a replacement",
                "decision_kind": "small-answer",
                "continuation_of": "consultation-does-not-exist",
            },
            wait=True,
            timeout=1,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["members"], [])
        self.assertEqual(calls, [])

    def test_consultation_excludes_unverified_or_unconsented_web_routes(self):
        routes = [
            _route(
                "web-auth-unknown",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-auth-unknown",
                provider_key="provider-auth-unknown",
                auth_state="unknown",
                health_state="healthy",
                quota_state="unknown",
                quota_consent="granted",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
            _route(
                "web-quota-unknown",
                kind="web-worker",
                source_kind="web-chat",
                provider_profile_id="profile-quota-unknown",
                provider_key="provider-quota-unknown",
                auth_state="authorized",
                health_state="healthy",
                quota_state="unknown",
                quota_consent="unknown",
                cost_class="unknown",
                capabilities=("text", "chat", "browser"),
            ),
        ]
        supervisor = self.make_supervisor(
            routes,
            [(route.route_id, ProviderWorker(lambda *_: {"status": "completed", "answer": "must not run"}, worker_id=route.route_id)) for route in routes],
        )
        result = supervisor.start_consultation(
            {
                "consultation_id": "consultation-unverified-web",
                "parent_session_id": "session-unverified-web",
                "question": "requires verified profiles",
                "decision_kind": "small-answer",
                "max_members": 2,
            }
        )
        self.assertEqual(result["status"], "waiting-human")
        self.assertEqual(len(result["members"]), 1)
        self.assertEqual(result["members"][0]["status"], "waiting-human")
        self.assertEqual(result["members"][0]["error_code"], "confirmation-required")

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
