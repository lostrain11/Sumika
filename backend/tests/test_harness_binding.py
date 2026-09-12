import unittest
from dataclasses import replace
from unittest.mock import patch

from quality_routing.harness import RuntimeBinding
from sumika_core.agent.contracts import AgentRuntimeError, UnavailableAgentRuntime
from sumika_core.agent.adapters.dsh.runtime import DSHAgentRuntime
from sumika_core.agent.registry import AgentRuntimeRegistry
from sumika_core.server import CoreApplication
from sumika_core.protocol.jsonrpc import JsonRpcError
from trusted_host_fixture import trusted_rpc


class LocalFixtureRuntime(UnavailableAgentRuntime):
    runtime_id = "fixture"


class BindingTests(unittest.TestCase):
    def binding(self):
        return RuntimeBinding("fixture", "profile-one", "release-one", "v1", "external", "fixture-evidence")

    def test_non_dsh_registry_binding_is_explicit_and_immutable(self):
        registry = AgentRuntimeRegistry()
        registry.register("fixture", lambda data, env, logger: LocalFixtureRuntime())
        binding = self.binding()
        runtime = registry.create("fixture", None, env={}, binding=binding)
        self.assertEqual(runtime.runtime_binding(), binding)
        runtime.bind_runtime(binding)
        with self.assertRaises(AgentRuntimeError):
            runtime.bind_runtime(replace(binding, instance_id="changed"))
        with self.assertRaises(AgentRuntimeError):
            registry.create("fixture", None, env={}, binding=replace(binding, harness_id="dsh"))
        self.assertTrue(runtime.external_session_ref("session").belongs_to(binding))
        fresh = registry.create("fixture", None, env={})
        self.assertIsNone(fresh.runtime_binding())
        with self.assertRaises(AgentRuntimeError):
            fresh.external_session_ref("session")

    def test_dsh_does_not_invent_identity_from_config_or_health(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        with patch.object(runtime, "health", side_effect=AssertionError("no network")):
            self.assertIsNone(runtime.runtime_binding())
            with self.assertRaises(AgentRuntimeError):
                runtime.external_session_ref("session")

    def test_rpc_is_read_only_and_cannot_install_body_binding(self):
        with patch.dict("os.environ", {"SUMIKA_AGENT_RUNTIME": "none"}):
            app = CoreApplication(":memory:")
        try:
            with patch.object(app.agent, "health", side_effect=AssertionError("no network")):
                result = app.rpc("agent.runtime.binding", self.binding().to_dict())
                self.assertFalse(result["available"])
                self.assertIsNone(result["binding"])
                self.assertEqual(result["reason"], "runtime-identity-unverified")
        finally:
            app.close()

    def test_event_sink_keeps_original_host_binding_when_default_runtime_changes(self):
        original = LocalFixtureRuntime()
        binding = replace(self.binding(), launch_id="first", launch_evidence_ref="launch-receipt")
        original.bind_runtime(binding)
        with patch.object(original, "set_event_sink") as register:
            app = CoreApplication(":memory:", agent_runtime=original)
        try:
            callback = register.call_args.args[0]
            replacement = LocalFixtureRuntime()
            replacement.bind_runtime(replace(binding, launch_id="second"))
            app.agent = replacement
            event = {"runtime_binding": replacement.runtime_binding().to_dict()}
            with patch.object(app, "_on_agent_runtime_event") as receive:
                callback(event)
                receive.assert_called_once_with(event, source_binding=binding)
        finally:
            app.close()

    def test_unbound_event_sink_does_not_acquire_identity_from_later_binding(self):
        runtime = LocalFixtureRuntime()
        with patch.object(runtime, "set_event_sink") as register:
            app = CoreApplication(":memory:", agent_runtime=runtime)
        try:
            callback = register.call_args.args[0]
            runtime.bind_runtime(replace(self.binding(), launch_id="later", launch_evidence_ref="receipt"))
            with patch.object(app, "_on_agent_runtime_event") as receive:
                callback({})
                receive.assert_called_once_with({}, source_binding=None)
        finally:
            app.close()

    def test_model_and_preset_changes_do_not_rebind_an_unresolved_attempt(self):
        app = CoreApplication(":memory:", agent_runtime=LocalFixtureRuntime())
        try:
            offer = {"source": "agent", "candidate_id": "fixture", "identity": ["fixture"],
                     "high_cny": "0", "limit_enforced": True, "free": True, "complexity": "complex"}
            params = {"work_request_id": "bound-work", "sessionId": "live-session", "text": "fixture"}
            value = app.work.external_preflight(params, offer)
            app.work.confirm({"request_id": value["request_id"], "assistant_id": "sumika", "revision": 1, "max_cny": "0"})
            app.work.external_dispatch(params, offer, lambda: {"accepted": True, "status": "running", "turn_id": "turn"},
                                       refresh_offer=lambda: offer)
            with patch.object(app, "_rpc", return_value={"ok": True}) as upstream:
                for method in ("agent.session.select_model", "agent.session.select_preset", "model.policy.apply", "agent.provider.sync"):
                    with self.subTest(method=method), self.assertRaises(JsonRpcError) as failure:
                        trusted_rpc(app, method, {"sessionId": "live-session", "approved": True})
                    self.assertEqual(failure.exception.code, -32042)
                upstream.assert_not_called()
                self.assertEqual(trusted_rpc(app, "agent.session.select_model", {"sessionId": "other-session"}), {"ok": True})
        finally:
            app.close()

    def test_event_projection_uses_original_harness_and_overrides_body_provenance(self):
        app = CoreApplication(":memory:", agent_runtime=LocalFixtureRuntime())
        binding = replace(self.binding(), harness_id="original", launch_id="first", launch_evidence_ref="receipt")
        try:
            with patch.object(app.events, "publish") as publish:
                app._on_agent_runtime_event({"event_type": "custom", "runtime_binding": {"forged": True}}, source_binding=binding)
                event = publish.call_args.args[0]
                self.assertEqual(event.event_type, "agent.original.event")
                self.assertEqual(event.payload["runtime_binding"], binding.to_dict())
        finally:
            app.close()
