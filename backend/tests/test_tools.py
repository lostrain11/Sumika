import json
import sys
import tempfile
import unittest
from pathlib import Path

from sumika_core.events import EventBus
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import ProviderRegistry
from fixtures.providers import FakeProvider
from sumika_core.storage import Storage
from sumika_core.tools import ToolRuntime, ToolRuntimeError


class ToolRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.events = EventBus(self.storage)
        providers = ProviderRegistry()
        providers.register(FakeProvider())
        self.modules = ModuleCatalog(self.storage, providers)
        self.runtime = ToolRuntime(self.modules, self.events)

    def tearDown(self):
        self.storage.close()

    def test_disabled_and_unapproved_calls_never_start_a_process(self):
        with self.assertRaisesRegex(ToolRuntimeError, "disabled"):
            self.runtime.run(tool_id="demo", input={}, approved=True)
        self.modules.update(
            "tools",
            enabled=True,
            implementation_id="external-process",
            config={"executable": sys.executable},
        )
        with self.assertRaisesRegex(ToolRuntimeError, "explicit approval"):
            self.runtime.run(tool_id="demo", input={}, approved=False)
        self.assertEqual(self.storage.list_events(), [])

    def test_external_jsonl_call_requires_absolute_path_and_redacts_events(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "echo_tool.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'type': 'result', 'result': {'echo': request['input']}}))\n",
                encoding="utf-8",
            )
            self.modules.update(
                "tools",
                enabled=True,
                implementation_id="external-process",
                config={"executable": sys.executable, "arguments": [str(script)], "timeout_seconds": 5},
            )
            result = self.runtime.run(
                tool_id="echo",
                input={"secret": "do-not-store"},
                approved=True,
            )
            self.assertEqual(result["runner"], "external-process")
            self.assertEqual(result["result"], {"echo": {"secret": "do-not-store"}})
            events = self.storage.list_events()
            self.assertEqual(
                {event["event_type"] for event in events},
                {"tool.started", "tool.completed"},
            )
            self.assertNotIn("do-not-store", json.dumps(events, ensure_ascii=False))

        self.modules.update(
            "tools",
            enabled=True,
            implementation_id="external-process",
            config={"executable": "relative-tool"},
        )
        with self.assertRaisesRegex(ToolRuntimeError, "absolute path"):
            self.runtime.run(tool_id="demo", input={}, approved=True)

    def test_external_jsonl_failure_is_audited_without_raw_output(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "failing_tool.py"
            script.write_text(
                "import json, sys\n"
                "json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'type': 'error', 'message': 'tool failed'}))\n",
                encoding="utf-8",
            )
            self.modules.update(
                "tools",
                enabled=True,
                implementation_id="external-process",
                config={"executable": sys.executable, "arguments": [str(script)]},
            )
            with self.assertRaisesRegex(ToolRuntimeError, "tool failed"):
                self.runtime.run(tool_id="failing", input={"value": 1}, approved=True)
            self.assertIn("tool.failed", {event["event_type"] for event in self.storage.list_events()})


if __name__ == "__main__":
    unittest.main()
