from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from sumika_core.agent.runtime_workers import (
    ExternalHarnessClientWorker,
    ExternalHarnessRouteSource,
)
from sumika_core.agent.supervisor import (
    DynamicSubtaskDispatch,
    DynamicRouteSupervisor,
    ProviderWorker,
    RuntimeRouteDescriptor,
    WorkerRegistry,
)
from sumika_core.server import CoreApplication


class SessionHarnessFixture:
    runtime_id = "fixture-harness"

    def __init__(self, model: str = "fixture-model"):
        self.model = model
        self.calls: list[tuple[str, object]] = []
        self.closed = 0

    def health(self):
        self.calls.append(("health", None))
        return {"ready": True}

    def runtime_models(self, params=None):
        self.calls.append(("models", params))
        return {
            "models": [
                {
                    "id": self.model,
                    "provider": "fixture-provider",
                    "capabilities": ["chat", "code", "tools"],
                    "quality_tier": "standard",
                }
            ]
        }

    def quota_status(self):
        self.calls.append(("quota", None))
        return {"state": "available", "source": "fixture"}

    def create_session(self, params):
        self.calls.append(("create", params))
        return {"sessionId": "fixture-session"}

    def select_model(self, params):
        self.calls.append(("select", params))
        return {"selected": True}

    def prompt(self, params):
        self.calls.append(("prompt", params))
        return {"status": "running", "turnId": "fixture-turn"}

    def wait_for_turn(self, params, timeout=None):
        self.calls.append(("wait", {"params": params, "timeout": timeout}))
        return {"status": "completed", "turnId": "fixture-turn", "answer": "fixture answer"}

    def close_session(self, params):
        self.calls.append(("close-session", params))
        return {"closed": True}

    def close(self):
        self.closed += 1


def external_route(route_id: str = "harness:fixture:model") -> RuntimeRouteDescriptor:
    return RuntimeRouteDescriptor(
        route_id=route_id,
        kind="external-harness",
        label="Fixture Harness",
        runtime_id="fixture-harness",
        executor="external-fixture-harness",
        transport="stdio",
        provider_key="fixture-provider",
        capabilities=("chat", "code", "tools"),
        status="ready",
        routable=True,
        quota_state="available",
        auth_state="authorized",
        health_state="healthy",
        cost_class="unknown",
        processing_location="cloud",
        metadata={
            "model_entry": {
                "provider_id": "fixture-provider",
                "model_id": "fixture-model",
            }
        },
    )


class ExternalHarnessWorkerTests(unittest.TestCase):
    def test_common_session_protocol_runs_once_and_closes_session(self):
        client = SessionHarnessFixture()
        worker = ExternalHarnessClientWorker(client, source_id="fixture-harness", worker_id="external-fixture-harness")
        dispatch = DynamicSubtaskDispatch(
            dispatch_id="dispatch-fixture",
            parent_session_id="session-fixture",
            parent_turn_id="turn-fixture",
            route_id="harness:fixture:model",
            question="answer a bounded question",
            worker_kind="external-harness",
        )

        result = worker.execute(dispatch, external_route(), threading.Event())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "fixture answer")
        names = [name for name, _ in client.calls]
        self.assertEqual(names, ["create", "select", "prompt", "wait", "close-session"])
        self.assertEqual(client.calls[0][1]["workspace"]["type"], "local")
        self.assertEqual(client.calls[2][1]["sessionId"], "fixture-session")

    def test_prompt_type_error_is_not_retried_and_is_possibly_sent(self):
        class FailingPrompt(SessionHarnessFixture):
            def prompt(self, params):
                self.calls.append(("prompt", params))
                raise TypeError("raised inside client")

        client = FailingPrompt()
        worker = ExternalHarnessClientWorker(client, source_id="fixture-harness")
        dispatch = DynamicSubtaskDispatch(
            dispatch_id="dispatch-type-error",
            parent_session_id="session-fixture",
            route_id="harness:fixture:model",
            question="send once",
            worker_kind="external-harness",
        )

        result = worker.execute(dispatch, external_route(), threading.Event())

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["possibly_sent"])
        self.assertEqual(sum(1 for name, _ in client.calls if name == "prompt"), 1)
        self.assertEqual(sum(1 for name, _ in client.calls if name == "close-session"), 1)

    def test_direct_dispatch_type_error_is_not_retried(self):
        class DirectFixture:
            runtime_id = "direct-fixture"

            def __init__(self):
                self.calls = 0

            def execute_dispatch(self, dispatch):
                self.calls += 1
                raise TypeError("client implementation error")

        client = DirectFixture()
        worker = ExternalHarnessClientWorker(client, source_id="direct-fixture")
        dispatch = DynamicSubtaskDispatch(
            dispatch_id="dispatch-direct-error",
            parent_session_id="session-fixture",
            route_id="harness:fixture:model",
            question="send once",
            worker_kind="external-harness",
        )

        result = worker.execute(dispatch, external_route(), threading.Event())

        self.assertEqual(client.calls, 1)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["possibly_sent"])

    def test_source_normalizes_boolean_consent_and_health_failure_is_unavailable(self):
        client = SessionHarnessFixture()
        source = ExternalHarnessRouteSource(client, source_id="fixture-harness", quota_consent=True)
        entry = source.model_entries(refresh=True)[0]
        self.assertEqual(source.quota_consent, "granted")
        self.assertTrue(entry.metadata["routable"])

        class Unhealthy(SessionHarnessFixture):
            def health(self):
                raise OSError("not reachable")

        unhealthy = ExternalHarnessRouteSource(Unhealthy(), source_id="unhealthy")
        unavailable = unhealthy.model_entries(refresh=True)[0]
        self.assertEqual(unavailable.health_state, "unavailable")
        self.assertFalse(unavailable.metadata["routable"])

    def test_model_catalog_failure_retains_cached_identity_but_fails_closed(self):
        class FlakyCatalog(SessionHarnessFixture):
            def __init__(self):
                super().__init__("cached-model")
                self.fail = False

            def runtime_models(self, params=None):
                if self.fail:
                    raise OSError("catalog unavailable")
                return super().runtime_models(params)

        client = FlakyCatalog()
        source = ExternalHarnessRouteSource(client, source_id="flaky-harness", quota_consent=True)
        first = source.model_entries(refresh=True)
        self.assertEqual([entry.model_id for entry in first], ["cached-model"])
        client.fail = True

        degraded = source.model_entries(refresh=True)
        self.assertEqual([entry.model_id for entry in degraded], ["cached-model"])
        self.assertEqual(degraded[0].health_state, "unavailable")
        self.assertFalse(degraded[0].metadata["routable"])
        self.assertEqual(degraded[0].metadata["catalog_error"], "model-catalog-unavailable")
        # A non-refresh read must not resurrect the last healthy projection.
        self.assertFalse(source.model_entries()[0].metadata["routable"])


class ExternalHarnessSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.registry = WorkerRegistry()
        self.supervisor = DynamicRouteSupervisor(self.registry, routes=[external_route()])

    def tearDown(self):
        self.supervisor.close()

    def test_dispatch_hydrates_selected_route_metadata(self):
        client = SessionHarnessFixture()
        worker = ExternalHarnessClientWorker(client, source_id="fixture-harness", worker_id="external-fixture-harness")
        self.supervisor.register_worker("external-fixture-harness", worker)
        self.supervisor.worker_registry.bind("harness:fixture:model", "external-fixture-harness")

        result = self.supervisor.dispatch(
            {
                "dispatch_id": "dispatch-hydrate",
                "parent_session_id": "session-fixture",
                "parent_turn_id": "turn-fixture",
                "route_id": "harness:fixture:model",
                "question": "metadata",
                "worker_kind": "external-harness",
                "confirmed": True,
                "quota_consent": True,
            },
            wait=True,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["dispatch"]["runtime_id"], "fixture-harness")
        self.assertEqual(result["dispatch"]["executor"], "external-fixture-harness")
        self.assertEqual(result["dispatch"]["transport"], "stdio")

    def test_explicit_route_metadata_mismatch_fails_closed(self):
        worker = ProviderWorker(lambda dispatch: {"status": "completed", "answer": "must not run"}, worker_id="external-fixture-harness")
        self.supervisor.register_worker("external-fixture-harness", worker)
        self.supervisor.worker_registry.bind("harness:fixture:model", "external-fixture-harness")

        result = self.supervisor.dispatch(
            {
                "dispatch_id": "dispatch-mismatch",
                "parent_session_id": "session-fixture",
                "route_id": "harness:fixture:model",
                "question": "mismatch",
                "worker_kind": "external-harness",
                "executor": "wrong-worker",
                "confirmed": True,
                "quota_consent": True,
            }
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["error_code"], "route-metadata-mismatch")


class ExternalHarnessCoreTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"SUMIKA_DSH_ENABLED": "0"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_core_registration_dispatch_and_unregistration_are_complete(self):
        first = SessionHarnessFixture("first-model")
        application = CoreApplication(":memory:", external_route_sources=[first])
        try:
            catalog = application.rpc("sumika.route.catalog", {"refresh": True})
            route = next(item for item in catalog["routes"] if item["runtime_id"] == "fixture-harness")
            result = application.rpc(
                "sumika.route.dispatch",
                {
                    "route_id": route["route_id"],
                    "parent_session_id": "core-session",
                    "parent_turn_id": "core-turn",
                    "question": "core dispatch",
                    "confirmed": True,
                    "quota_consent": True,
                    "wait": True,
                },
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"]["answer"], "fixture answer")

            replacement = SessionHarnessFixture("replacement-model")
            application.register_external_route_source(replacement, source_id="fixture-harness")
            self.assertEqual(first.closed, 1)
            refreshed = application.rpc("sumika.route.catalog", {"refresh": True})
            replacement_route = next(item for item in refreshed["routes"] if item["runtime_id"] == "fixture-harness")
            self.assertIn("replacement-model", replacement_route["label"])
            self.assertTrue(application.unregister_external_route_source("fixture-harness"))
            self.assertEqual(replacement.closed, 1)
            self.assertNotIn(
                "fixture-harness",
                [item["runtime_id"] for item in application.rpc("sumika.route.catalog", {})["routes"]],
            )
            self.assertNotIn(
                "external-fixture-harness",
                [item["worker_id"] for item in application.route_supervisor.catalog()["workers"]],
            )
        finally:
            application.close()

    def test_core_event_boundary_consumes_one_armed_request(self):
        client = SessionHarnessFixture()
        application = CoreApplication(":memory:", external_route_sources=[client])
        try:
            application.rpc("sumika.route.catalog", {"refresh": True})
            route = next(item for item in application.route_supervisor.catalog()["routes"] if item["runtime_id"] == "fixture-harness")
            armed = application.rpc(
                "sumika.route.arm",
                {
                    "parent_session_id": "event-session",
                    "parent_turn_id": "event-turn",
                    "route_id": route["route_id"],
                    "question": "event dispatch",
                    "confirmation_mode": "automatic",
                    "auto_dispatch": True,
                    "confirmed": True,
                    "quota_consent": True,
                },
            )
            self.assertTrue(armed["armed"])
            first = application._handle_route_boundary_event(
                {
                    "event_type": "turn.started",
                    "event_id": "event-boundary-1",
                    "session_id": "event-session",
                    "turn_id": "event-turn",
                }
            )
            self.assertEqual(first["status"], "dispatched")
            self.assertEqual(application.route_supervisor.wait(first["dispatch"]["dispatch_id"], timeout=2)["status"], "completed")
            duplicate = application._handle_route_boundary_event(
                {
                    "event_type": "turn.started",
                    "event_id": "event-boundary-2",
                    "session_id": "event-session",
                    "turn_id": "event-turn",
                }
            )
            self.assertEqual(duplicate["reason"], "no-routing-request")
        finally:
            application.close()


if __name__ == "__main__":
    unittest.main()
