import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sumika_core.agent import AgentCapability, create_agent_runtime
from sumika_core.agent.adapters.zcode.config import ZCodeRuntimeConfig, config_from_env
from sumika_core.agent.adapters.zcode.runtime import (
    ZCodeAgentRuntime,
    _normalize_models,
    _sanitize_runtime_message,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "zcode_app_server.py"
MODERN_FIXTURE = ROOT / "tests" / "fixtures" / "zcode_modern_app_server.py"


class ZCodeRuntimeTests(unittest.TestCase):
    def make_runtime(self):
        config = ZCodeRuntimeConfig(
            executable=sys.executable,
            arguments=(str(FIXTURE),),
            working_directory=str(ROOT),
            request_timeout=5.0,
            startup_timeout=5.0,
        )
        runtime = ZCodeAgentRuntime(":memory:", config=config)
        self.addCleanup(runtime.close)
        return runtime

    def make_modern_runtime(self):
        config = ZCodeRuntimeConfig(
            executable=sys.executable,
            arguments=(str(MODERN_FIXTURE),),
            working_directory=str(ROOT),
            request_timeout=5.0,
            startup_timeout=5.0,
        )
        runtime = ZCodeAgentRuntime(":memory:", config=config)
        self.addCleanup(runtime.close)
        return runtime

    def test_current_zcode_wire_uses_workspace_protocol_and_modern_events(self):
        runtime = self.make_modern_runtime()
        events = []
        runtime.set_event_sink(events.append)

        self.assertTrue(runtime.health()["ok"])
        self.assertEqual(runtime.status()["wire_protocol"], "zcode")
        models = runtime.runtime_models({"cwd": str(ROOT)})
        self.assertEqual(models["groups"][0]["models"][0]["id"], "fixture-model")
        created = runtime.create_session({"cwd": str(ROOT), "mode": "plan"})
        self.assertTrue(created["sessionId"].startswith("modern-session-"))
        receipt = runtime.prompt({"sessionId": created["sessionId"], "text": "hello", "mode": "plan"})
        self.assertTrue(receipt["accepted"])
        self.assertTrue(any(event["status"] == "completed" for event in events))
        self.assertEqual(runtime.mcp_inventory({"cwd": str(ROOT)})["server_count"], 1)
        self.assertEqual(runtime.list_subagents({"sessionId": created["sessionId"]})["subagents"], [])

    def test_modern_model_selection_never_invents_provider_or_runtime_envelope(self):
        runtime = self.make_modern_runtime()
        runtime.health()
        with self.assertRaisesRegex(Exception, "explicit provider"):
            runtime._modern_model_ref("fixture-model")

        created = runtime.create_session({"title": "model selection"})
        with patch.object(runtime._transport, "request", wraps=runtime._transport.request) as request:
            runtime.prompt(
                {
                    "sessionId": created["sessionId"],
                    "text": "hello",
                    "providerId": "fixture-provider",
                    "model": "fixture-model",
                }
            )
        calls = [(call.args[0], call.args[1]) for call in request.call_args_list]
        self.assertIn("session/setModel", [method for method, _ in calls])
        send_params = next(params for method, params in calls if method == "session/send")
        self.assertNotIn("runtimeModel", send_params)

    def test_modern_select_model_accepts_a_model_reference_object(self):
        runtime = self.make_modern_runtime()
        runtime.health()
        created = runtime.create_session({"title": "model ref"})
        selected = runtime.select_model(
            {
                "sessionId": created["sessionId"],
                "model": {"providerId": "fixture-provider", "modelId": "fixture-model"},
            }
        )
        self.assertEqual(selected["model_ref"], {"providerId": "fixture-provider", "modelId": "fixture-model"})

    def test_modern_complete_runtime_model_is_sanitized_and_forwarded(self):
        runtime = self.make_modern_runtime()
        runtime.health()
        created = runtime.create_session({"title": "runtime model"})
        runtime_model = {
            "revision": "fixture-runtime-1",
            "generatedAt": 1,
            "model": {"providerId": "fixture-provider", "modelId": "fixture-model"},
            "provider": {
                "providerId": "fixture-provider",
                "kind": "openai-compatible",
                "source": "ephemeral",
                "baseURL": "http://127.0.0.1:1/v1",
                "models": [{"modelId": "fixture-model", "label": "Fixture"}],
                "apiKey": {"source": "env", "name": "SUMIKA_TEST_KEY"},
            },
        }
        with patch.object(runtime._transport, "request", wraps=runtime._transport.request) as request:
            runtime.prompt(
                {
                    "sessionId": created["sessionId"],
                    "text": "hello",
                    "runtimeModel": runtime_model,
                }
            )
        send_params = next(call.args[1] for call in request.call_args_list if call.args[0] == "session/send")
        self.assertEqual(send_params["runtimeModel"]["generatedAt"], 1)
        self.assertEqual(send_params["runtimeModel"]["provider"]["apiKey"], {"source": "env", "name": "SUMIKA_TEST_KEY"})
        with self.assertRaisesRegex(Exception, "inline credentials"):
            runtime._modern_runtime_model(
                {**runtime_model, "provider": {**runtime_model["provider"], "apiKey": {"source": "inline", "value": "secret"}}}
            )

    def test_modern_session_title_falls_back_to_requested_title(self):
        runtime = self.make_modern_runtime()
        runtime.health()
        with patch.object(runtime._transport, "request", wraps=runtime._transport.request):
            # The fixture omits its generated title for the edit mode.
            created = runtime.create_session({"title": "requested title", "mode": "edit"})
        self.assertEqual(created["title"], "requested title")

    def test_available_model_options_are_projected_without_provider_configs(self):
        catalog = _normalize_models(
            {
                "revision": 1,
                "providers": [],
                "available": [
                    {
                        "ref": {"providerId": "available-provider", "modelId": "available-model"},
                        "label": "Available Model",
                        "providerLabel": "Available Provider",
                    }
                ],
            }
        )
        self.assertEqual(catalog["groups"], [{
            "id": "available-provider",
            "name": "Available Provider",
            "models": [{"id": "available-model", "name": "Available Model"}],
        }])

    def test_zcode_environment_supports_explicit_node_script_and_wire_protocol(self):
        config = config_from_env(
            ROOT,
            {
                "SUMIKA_ZCODE_NODE": "node-test",
                "SUMIKA_ZCODE_SCRIPT": "zcode-test.cjs",
                "SUMIKA_ZCODE_PROTOCOL": "jsonrpc",
            },
        )
        self.assertEqual(config.executable, "node-test")
        self.assertEqual(config.arguments, ("zcode-test.cjs", "app-server", "--stdio"))
        self.assertEqual(config.wire_protocol, "jsonrpc")

    def test_zcode_auto_discovery_normalizes_electron_bundle_to_node_script(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "ZCode.exe"
            script = root / "resources" / "glm" / "zcode.cjs"
            executable.write_bytes(b"fixture")
            script.parent.mkdir(parents=True)
            script.write_text("// fixture\n", encoding="utf-8")
            node = root / "node.exe"
            node.write_bytes(b"fixture")
            config = config_from_env(
                root,
                {
                    "SUMIKA_ZCODE_AUTODISCOVER": "1",
                    "SUMIKA_ZCODE_INSTALL_DIR": str(root),
                    "SUMIKA_ZCODE_NODE": str(node),
                },
            )
        self.assertEqual(config.executable, str(node))
        self.assertEqual(
            config.arguments,
            (str(script.resolve()), "app-server", "--stdio"),
        )

    def test_zcode_explicit_electron_path_uses_adjacent_public_script(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "ZCode.exe"
            script = root / "resources" / "glm" / "zcode.cjs"
            executable.write_bytes(b"fixture")
            script.parent.mkdir(parents=True)
            script.write_text("// fixture\n", encoding="utf-8")
            with patch("sumika_core.agent.adapters.zcode.config.shutil.which", return_value="node"):
                config = config_from_env(
                    root,
                    {"SUMIKA_ZCODE_EXECUTABLE": str(executable)},
                )
        self.assertEqual(config.executable, "node")
        self.assertEqual(config.arguments, (str(script.resolve()), "app-server", "--stdio"))

    def test_zcode_discovery_remains_opt_in(self):
        with patch("sumika_core.agent.adapters.zcode.config.shutil.which", return_value="zcode"):
            config = config_from_env(Path("."), {})
        self.assertIsNone(config.executable)

    def test_modern_capabilities_do_not_claim_readonly_or_legacy_queue(self):
        runtime = self.make_modern_runtime()
        runtime.health()
        self.assertFalse(runtime.supports(AgentCapability.READONLY))
        self.assertFalse(runtime.supports(AgentCapability.QUEUE))
        with self.assertRaisesRegex(Exception, "readonly"):
            runtime.prompt({"sessionId": "s", "text": "x", "mode": "readonly"})

    def test_modern_permission_request_uses_decision_response(self):
        runtime = self.make_modern_runtime()
        runtime.health()
        runtime._call_variants(("trigger/permission",), {"sessionId": "modern-session-1"})
        self.assertEqual(runtime.interactions()["interactions"][0]["rpc_id"], "permission-1")
        with patch.object(runtime._transport, "respond", wraps=runtime._transport.respond) as respond:
            result = runtime.respond_interaction({"rpcId": "permission-1", "outcome": "allowed-once", "sessionId": "modern-session-1"})
        self.assertTrue(result["accepted"])
        self.assertEqual(respond.call_args.kwargs["result"], {"decision": "allow"})
        self.assertEqual(runtime.interactions()["interactions"], [])

    def test_explicit_wire_protocol_is_validated(self):
        with self.assertRaises(ValueError):
            ZCodeRuntimeConfig(protocol="unknown")
        self.assertNotIn(r"C:\Users\private", _sanitize_runtime_message(r"missing C:\Users\private\.zcode\config.json"))

    def test_stdio_lifecycle_session_prompt_and_models(self):
        runtime = self.make_runtime()
        events = []
        runtime.set_event_sink(events.append)

        health = runtime.health()
        self.assertTrue(health["ok"])
        self.assertEqual(runtime.status()["state"], "ready")
        self.assertTrue(runtime.supports(AgentCapability.MODELS))
        self.assertIn("mcp", runtime.runtime_capabilities())

        created = runtime.create_session({"title": "Fixture"})
        self.assertTrue(created["sessionId"].startswith("z-session-"))
        listed = runtime.list_sessions()
        self.assertEqual(listed["sessions"][0]["id"], created["sessionId"])

        receipt = runtime.prompt({"sessionId": created["sessionId"], "text": "hello", "mode": "plan"})
        self.assertTrue(receipt["accepted"])
        self.assertEqual(receipt["session_id"], created["sessionId"])
        self.assertTrue(any(event["event_type"] == "session/event" for event in events))

        models = runtime.session_models({"sessionId": created["sessionId"]})
        self.assertEqual(models["groups"][0]["models"][0]["id"], "qwen3:4b")
        cancelled = runtime.cancel({"sessionId": created["sessionId"]})
        self.assertTrue(cancelled["accepted"])

    def test_public_runtime_model_directory_is_available_before_session_creation(self):
        runtime = self.make_runtime()
        models = runtime.runtime_models()
        self.assertEqual(models["groups"][0]["models"][0]["id"], "qwen3:4b")

    def test_quota_stays_unknown_when_app_server_does_not_advertise_it(self):
        runtime = self.make_runtime()
        result = runtime.quota_status()
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["source"], "zcode-app-server-not-exposed")

    def test_public_quota_is_compacted_and_state_is_derived(self):
        runtime = self.make_runtime()

        def initialize():
            runtime._advertised_features = {"quota/status"}

        with patch.object(runtime, "_initialize", side_effect=initialize), patch.object(
            runtime,
            "_call_variants",
            return_value={"remaining": 2, "total": 100, "unit": "USD"},
        ) as call:
            result = runtime.quota_status()

        self.assertEqual(result["state"], "low")
        self.assertEqual(result["remaining"], 2.0)
        self.assertEqual(result["unit"], "USD")
        call.assert_called_once_with(
            ("quota/status", "quota.status", "usage/status", "account/usage"),
            {},
        )

    def test_server_request_is_pending_until_explicit_response(self):
        runtime = self.make_runtime()
        events = []
        runtime.set_event_sink(events.append)
        runtime.health()
        runtime._call_variants(("trigger/approval",), {"sessionId": "s1"})
        interactions = runtime.interactions()
        self.assertEqual(interactions["interactions"][0]["rpc_id"], "approval-1")
        self.assertTrue(any(event["event_type"] == "approval/requested" for event in events))
        response = runtime.respond({"rpcId": "approval-1", "approved": True})
        self.assertTrue(response["accepted"])
        self.assertEqual(runtime.interactions()["interactions"], [])

    def test_mcp_inventory_is_compacted(self):
        runtime = self.make_runtime()
        runtime.health()
        inventory = runtime.mcp_inventory()
        self.assertTrue(inventory["available"])
        self.assertEqual(inventory["server_count"], 1)
        self.assertEqual(inventory["tool_count"], 1)
        self.assertNotIn("raw", json.dumps(inventory))

    def test_missing_executable_fails_closed_without_fallback(self):
        runtime = ZCodeAgentRuntime(":memory:", config=ZCodeRuntimeConfig(executable=None))
        self.addCleanup(runtime.close)
        health = runtime.health()
        self.assertFalse(health["ok"])
        self.assertEqual(runtime.status()["runtime_id"], "zcode")
        self.assertFalse(runtime.status()["ready"])

    def test_registry_exposes_zcode_but_selection_is_explicit(self):
        registry_runtime = create_agent_runtime(None, env={"SUMIKA_AGENT_RUNTIME": "zcode"})
        self.assertEqual(registry_runtime.runtime_id, "zcode")
        self.assertFalse(registry_runtime.status()["ready"])

        default_runtime = create_agent_runtime(None, env={"SUMIKA_AGENT_RUNTIME": "missing"})
        self.assertEqual(default_runtime.runtime_id, "unavailable")
        default_runtime.close()
        registry_runtime.close()

    def test_event_normalization_redacts_sensitive_fields(self):
        runtime = self.make_runtime()
        event = runtime.normalize_event(
            {
                "method": "item/completed",
                "params": {
                    "sessionId": "s1",
                    "text": "safe",
                    "token": "do-not-copy",
                    "tool": {"name": "read"},
                },
            }
        )
        self.assertEqual(event["session_id"], "s1")
        self.assertEqual(event["content"], "safe")
        self.assertNotIn("do-not-copy", json.dumps(event))


if __name__ == "__main__":
    unittest.main()
