import subprocess
import sys
import unittest

from sumika_core.agent import (
    AgentCapability,
    AgentRuntime,
    AgentRuntimeError,
    AgentRuntimeRegistry,
    create_agent_runtime,
)
from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication


class MinimalAgentRuntime(AgentRuntime):
    """Contract fixture with no DSH-specific optional capabilities."""

    runtime_id = "minimal"

    def __init__(self):
        self.sessions = []
        self.event_sink = None

    def status(self):
        return {"state": "ready", "ready": True}

    def health(self):
        return {"ok": True, "state": "ready"}

    def create_session(self, params):
        session = {"id": f"session-{len(self.sessions) + 1}", "title": params.get("title", "")}
        self.sessions.append(session)
        return session

    def list_sessions(self, params=None):
        del params
        return {"sessions": list(self.sessions)}

    def snapshot(self, params):
        return {"session_id": params["session_id"], "state": "idle", "messages": []}

    def prompt(self, params):
        return {"accepted": True, "session_id": params["session_id"]}

    def cancel(self, params):
        return {"accepted": True, "session_id": params["session_id"]}

    def set_event_sink(self, sink):
        self.event_sink = sink


class AgentPortabilityTests(unittest.TestCase):
    def test_portable_package_import_does_not_load_dsh_transport(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import sumika_core.agent; "
                    "print('sumika_core.agent.adapters.dsh.runtime' in sys.modules)"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "False")

    def test_minimal_runtime_only_implements_stable_session_core(self):
        runtime = MinimalAgentRuntime()

        self.assertEqual(runtime.runtime_capabilities(), [])
        self.assertFalse(runtime.supports(AgentCapability.PRESETS))
        self.assertFalse(runtime.mcp_inventory()["available"])
        with self.assertRaisesRegex(AgentRuntimeError, "does not support preset listing"):
            runtime.list_presets()

    def test_registry_constructs_real_entries_and_fails_closed_for_unknown_ids(self):
        registry = AgentRuntimeRegistry()
        registry.register("minimal", lambda data_dir, env, logger: MinimalAgentRuntime())

        selected = registry.create("minimal", None, env={}, logger=None)
        missing = registry.create("missing", None, env={}, logger=None)

        self.assertIsInstance(selected, MinimalAgentRuntime)
        self.assertFalse(missing.status()["ready"])
        self.assertIn("not registered", missing.status()["reason"])

    def test_registry_rejects_ids_that_are_not_safe_protocol_identifiers(self):
        registry = AgentRuntimeRegistry()

        with self.assertRaisesRegex(ValueError, "invalid"):
            registry.register("../unsafe", lambda data_dir, env, logger: MinimalAgentRuntime())

    def test_factory_does_not_silently_fallback_to_dsh(self):
        runtime = create_agent_runtime(None, env={"SUMIKA_AGENT_RUNTIME": "missing"})

        self.assertEqual(runtime.runtime_id, "unavailable")
        self.assertIn("missing", runtime.status()["reason"])

    def test_core_accepts_runtime_injection_and_projects_portable_status(self):
        runtime = MinimalAgentRuntime()
        application = CoreApplication(":memory:", agent_runtime=runtime)
        self.addCleanup(application.close)

        status = application.rpc("agent.status", {})
        created = application.rpc("agent.session.create", {"title": "Portable"})
        sessions = application.rpc("agent.sessions", {})

        self.assertEqual(status["runtime_id"], "minimal")
        self.assertEqual(status["runtime_capabilities"], [])
        self.assertEqual(created["id"], "session-1")
        self.assertEqual(sessions["sessions"][0]["title"], "Portable")
        self.assertIsNotNone(runtime.event_sink)

        with self.assertRaisesRegex(JsonRpcError, "does not support event ingestion"):
            application.rpc("agent.event.ingest", {"event": {"type": "custom"}})


if __name__ == "__main__":
    unittest.main()
