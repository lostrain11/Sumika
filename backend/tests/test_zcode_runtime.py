import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sumika_core.agent import AgentCapability, create_agent_runtime
from sumika_core.agent.adapters.zcode.config import ZCodeRuntimeConfig
from sumika_core.agent.adapters.zcode.runtime import ZCodeAgentRuntime


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "zcode_app_server.py"


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
