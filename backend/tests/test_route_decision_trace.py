import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sumika_core.agent.route_trace import ROUTE_TRACE_SCHEMA, RouteDecisionTrace
from sumika_core.agent.supervisor import (
    DynamicRouteEvidence,
    DynamicRouteSupervisor,
    ProviderWorker,
    RuntimeRouteDescriptor,
    SupervisorError,
    WorkerRegistry,
)


def _route(route_id: str, **overrides):
    values = {
        "route_id": route_id,
        "kind": "provider",
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


class RouteDecisionTraceTests(unittest.TestCase):
    def test_sink_allowlists_fields_hashes_correlations_and_aggregates(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = RouteDecisionTrace(directory, max_bytes=4096)
            record = sink.record(
                "candidate.evaluated",
                trace_id="trace-safe",
                session_id="private-session",
                turn_id="private-turn",
                dispatch_id="private-dispatch",
                provider_profile_id="private-profile",
                route_id="route-safe",
                eligible=False,
                rejection_code="quality-gate",
                evidence=[
                    {
                        "evidence_hash": "a" * 24,
                        "source_hash": "b" * 24,
                        "evidence_type": "real-run",
                        "effective_type": "unknown",
                        "confidence": "unknown",
                        "fresh": False,
                        "details": "must-not-be-written",
                    }
                ],
                usage={"input_tokens": 12, "prompt": "must-not-be-written"},
                charge={"provider_charge": 0.01, "provider_currency": "CNY", "invoice": "must-not-be-written"},
                prompt="private prompt",
                answer="private answer",
                path="C:\\Users\\private\\repo",
                credential="sk-not-a-real-key",
            )
            self.assertEqual(record["schema"], ROUTE_TRACE_SCHEMA)
            self.assertNotEqual(record["session_hash"], "private-session")
            self.assertEqual(record["usage"], {"input_tokens": 12})
            self.assertNotIn("details", record["evidence"][0])
            raw = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory, "logs", "route-decision-trace").glob("*.jsonl")
            )
            for forbidden in (
                "private-session",
                "private-turn",
                "private-dispatch",
                "private-profile",
                "private prompt",
                "private answer",
                "must-not-be-written",
                "C:\\Users",
                "sk-not-a-real-key",
            ):
                self.assertNotIn(forbidden, raw)
            report = sink.aggregate()
            self.assertEqual(report["record_count"], 1)
            self.assertEqual(report["candidate_routes"], {"route-safe": 1})
            self.assertEqual(report["rejection_codes"], {"quality-gate": 1})
            self.assertEqual(report["routes"][0]["candidate_count"], 1)
            sink.close()

    def test_supervisor_records_candidate_evidence_decision_and_terminal_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = RouteDecisionTrace(directory)
            registry = WorkerRegistry()
            registry.register(
                "route-selected",
                ProviderWorker(
                    lambda _dispatch: {
                        "status": "completed",
                        "answer": "private worker answer",
                        "budget_impact": {
                            "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                            "charge_receipt": {
                                "provider_charge": 0.002,
                                "provider_currency": "USD-credit",
                                "cash_charge": 0.001,
                                "cash_currency": "CNY",
                                "evidence_level": "request-usage-estimate",
                            },
                        },
                    },
                    worker_id="route-selected",
                ),
            )
            expired = DynamicRouteEvidence(
                evidence_type="real-run",
                source="private-source-url",
                route_id="route-rejected",
                expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                confidence="high",
            )
            selected_evidence = DynamicRouteEvidence(
                evidence_type="fixed-smoke",
                source="fixture",
                route_id="route-selected",
                confidence="high",
            )
            supervisor = DynamicRouteSupervisor(
                registry,
                routes=[
                    _route("route-rejected", capabilities=("text",), evidence_refs=(expired.evidence_id,)),
                    _route("route-selected", evidence_refs=(selected_evidence.evidence_id,)),
                ],
                trace_sink=sink,
            )
            supervisor.add_evidence(expired)
            supervisor.add_evidence(selected_evidence)
            try:
                decision = supervisor.replan(
                    {
                        "parent_session_id": "private-session",
                        "parent_turn_id": "private-turn",
                        "question": "private routing question",
                        "context_refs": {"snippet": "private source code"},
                        "required_capabilities": ["code"],
                        "difficulty": "moderate",
                        "confirmation_mode": "automatic",
                        "auto_dispatch": True,
                    }
                )
                terminal = supervisor.wait(decision["dispatch"]["dispatch_id"], timeout=2)
                self.assertEqual(terminal["status"], "completed")
            finally:
                supervisor.close()
                sink.close()

            records = []
            raw = ""
            for path in Path(directory, "logs", "route-decision-trace").glob("*.jsonl"):
                text = path.read_text(encoding="utf-8")
                raw += text
                records.extend(json.loads(line) for line in text.splitlines())
            events = [item["event"] for item in records]
            for expected in (
                "replan.requested",
                "candidate.evaluated",
                "decision.made",
                "dispatch.requested",
                "dispatch.queued",
                "dispatch.started",
                "dispatch.finished",
            ):
                self.assertIn(expected, events)
            candidates = [item for item in records if item["event"] == "candidate.evaluated"]
            rejected = next(item for item in candidates if item["route_id"] == "route-rejected")
            self.assertEqual(rejected["rejection_code"], "missing_capability")
            self.assertFalse(rejected["evidence"][0]["fresh"])
            selected = next(item for item in records if item["event"] == "decision.made")
            self.assertEqual(selected["route_id"], "route-selected")
            self.assertEqual(selected["filter_counts"], {"missing_capability": 1})
            terminal_trace = next(item for item in records if item["event"] == "dispatch.finished")
            self.assertEqual(terminal_trace["usage"]["total_tokens"], 14)
            self.assertEqual(terminal_trace["charge"]["cash_charge"], 0.001)
            report = sink.aggregate()
            route_report = next(item for item in report["routes"] if item["route_id"] == "route-selected")
            self.assertEqual(route_report["selected_count"], 1)
            self.assertEqual(route_report["terminal_count"], 1)
            self.assertEqual(route_report["usage"]["total_tokens"], 14)
            self.assertEqual(route_report["cash_charges"]["CNY"], 0.001)
            self.assertEqual({item["trace_id"] for item in records}, {decision["trace_id"]})
            for forbidden in (
                "private-session",
                "private-turn",
                "private routing question",
                "private source code",
                "private worker answer",
                "private-source-url",
            ):
                self.assertNotIn(forbidden, raw)

    def test_retry_and_deduplication_are_linked_without_replaying_possible_send(self):
        class PreSendError(RuntimeError):
            retryable = True
            possibly_sent = False

        class PossiblySentError(RuntimeError):
            retryable = True
            possibly_sent = True

        with tempfile.TemporaryDirectory() as directory:
            sink = RouteDecisionTrace(directory)
            calls = 0

            def execute(_dispatch):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PreSendError("private exception body")
                return {"status": "completed", "answer": "private answer"}

            registry = WorkerRegistry()
            registry.register("route-retry", ProviderWorker(execute, worker_id="route-retry"))
            registry.register(
                "route-possible-send",
                ProviderWorker(lambda _dispatch: (_ for _ in ()).throw(PossiblySentError("private sent error")), worker_id="route-possible-send"),
            )
            supervisor = DynamicRouteSupervisor(
                registry,
                routes=[_route("route-retry"), _route("route-possible-send")],
                trace_sink=sink,
            )
            try:
                first = supervisor.dispatch(
                    {
                        "parent_session_id": "session-retry",
                        "parent_turn_id": "turn-retry",
                        "route_id": "route-retry",
                        "question": "private retry question",
                    },
                    wait=True,
                )
                self.assertTrue(first["retryable"])
                retried = supervisor.retry(first["dispatch_id"], wait=True)
                self.assertEqual(retried["status"], "completed")
                duplicate = supervisor.dispatch(
                    {
                        "parent_session_id": "session-retry",
                        "parent_turn_id": "turn-retry",
                        "route_id": "route-retry",
                        "question": "private retry question",
                    },
                    wait=True,
                )
                self.assertTrue(duplicate["deduplicated"])
                possible = supervisor.dispatch(
                    {
                        "parent_session_id": "session-retry",
                        "parent_turn_id": "turn-possible-send",
                        "route_id": "route-possible-send",
                        "question": "private possible-send question",
                    },
                    wait=True,
                )
                self.assertTrue(possible["possibly_sent"])
                self.assertFalse(possible["retryable"])
                with self.assertRaises(SupervisorError):
                    supervisor.retry(possible["dispatch_id"])
            finally:
                supervisor.close()
                sink.close()

            raw = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory, "logs", "route-decision-trace").glob("*.jsonl")
            )
            records = [json.loads(line) for line in raw.splitlines()]
            self.assertIn("dispatch.retry.requested", {item["event"] for item in records})
            self.assertIn("dispatch.deduplicated", {item["event"] for item in records})
            possible_terminal = next(
                item
                for item in records
                if item["event"] == "dispatch.finished" and item.get("route_id") == "route-possible-send"
            )
            self.assertTrue(possible_terminal["possibly_sent"])
            self.assertFalse(possible_terminal["retryable"])
            self.assertNotIn("private exception body", raw)
            self.assertNotIn("private answer", raw)

    def test_confirmation_can_continue_the_original_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = RouteDecisionTrace(directory)
            route = _route(
                "route-confirm",
                cost_class="paid-low",
                quota_state="available",
                auth_state="authorized",
                processing_location="cloud",
            )
            registry = WorkerRegistry()
            registry.register("route-confirm", ProviderWorker(lambda _dispatch: "private answer", worker_id="route-confirm"))
            supervisor = DynamicRouteSupervisor(registry, routes=[route], trace_sink=sink)
            try:
                decision = supervisor.replan(
                    {
                        "parent_session_id": "session-confirm",
                        "parent_turn_id": "turn-confirm",
                        "route_id": route.route_id,
                        "question": "private paid question",
                        "confirmation_mode": "recommendation-then-confirmation",
                    }
                )
                self.assertEqual(decision["status"], "needs-confirmation")
                completed = supervisor.dispatch(
                    {
                        "parent_session_id": "session-confirm",
                        "parent_turn_id": "turn-confirm",
                        "route_id": route.route_id,
                        "question": "private paid question",
                        "confirmed": True,
                    },
                    trace_id=decision["trace_id"],
                    wait=True,
                )
                self.assertEqual(completed["status"], "completed")
            finally:
                supervisor.close()
                sink.close()
            raw = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory, "logs", "route-decision-trace").glob("*.jsonl")
            )
            records = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual({item["trace_id"] for item in records}, {decision["trace_id"]})
            self.assertIn("confirmation.required", {item["event"] for item in records})
            self.assertIn("confirmation.resolved", {item["event"] for item in records})
            self.assertNotIn("private paid question", raw)

    def test_cancel_records_one_terminal_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = RouteDecisionTrace(directory)
            started = threading.Event()
            release = threading.Event()

            def execute(_dispatch):
                started.set()
                release.wait(timeout=2)
                return {"status": "completed", "answer": "late private answer"}

            registry = WorkerRegistry()
            registry.register("route-cancel", ProviderWorker(execute, worker_id="route-cancel"))
            supervisor = DynamicRouteSupervisor(registry, routes=[_route("route-cancel")], trace_sink=sink)
            try:
                run = supervisor.dispatch(
                    {
                        "parent_session_id": "session-cancel",
                        "parent_turn_id": "turn-cancel",
                        "route_id": "route-cancel",
                        "question": "private cancellation question",
                    }
                )
                self.assertTrue(started.wait(timeout=1))
                cancelled = supervisor.cancel(run["dispatch_id"])
                self.assertTrue(cancelled["cancelled"])
                release.set()
            finally:
                supervisor.close()
                sink.close()
            raw = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory, "logs", "route-decision-trace").glob("*.jsonl")
            )
            records = [json.loads(line) for line in raw.splitlines()]
            self.assertIn("dispatch.cancel.requested", {item["event"] for item in records})
            terminal = [item for item in records if item["event"] == "dispatch.finished"]
            self.assertEqual(len(terminal), 1)
            self.assertEqual(terminal[0]["outcome"], "cancelled")
            self.assertNotIn("late private answer", raw)


if __name__ == "__main__":
    unittest.main()
