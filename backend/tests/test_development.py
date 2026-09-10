import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from quality_routing import Candidate, Outcome, RoutingError, Scope
from quality_routing.development import DevelopmentReply, run_development
from sumika_core.development import DevelopmentWorkspace, development_spec
from sumika_core.builtin_skills import BuiltinSkills
from sumika_core.protocol.models import ToolMessage
from sumika_core.quality.work import WorkService
from sumika_core.storage import Storage
from sumika_core.workspace import WorkspaceRuntime


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        subprocess.run(["git", "init", "--template=", str(self.source)], check=True, capture_output=True)
        (self.source / "answer.py").write_bytes(b"answer = 1\n")
        (self.source / "test_answer.py").write_bytes(b"from answer import answer\nassert answer == 2\n")
        self.spec = development_spec(str(self.source), {"test_commands": [[sys.executable, "test_answer.py"]]})
        self.checkpoints = WorkspaceRuntime(self.base / "data")

    def workspace(self, spec=None, cancelled=lambda: False):
        workspace = DevelopmentWorkspace(self.base / "copies", spec or self.spec, self.checkpoints, cancelled)
        workspace.prepare()
        return workspace

    def test_source_preserved_test_failure_repair_and_real_diff(self):
        (self.source / ".env").write_text("private", encoding="utf-8")
        workspace = self.workspace()
        self.assertIn(".env", workspace.skipped)
        self.assertFalse((workspace.root / ".env").exists())
        self.assertNotEqual(workspace.execute("run_test", {"index": 0})["exit_code"], 0)
        source = workspace.execute("read_file", {"path": "answer.py"})
        workspace.execute("write_file", {"path": "answer.py", "content": "answer = 2\n", "expected_sha256": source["sha256"]})
        self.assertEqual(workspace.execute("run_test", {"index": 0})["exit_code"], 0)
        self.assertEqual((self.source / "answer.py").read_text(), "answer = 1\n")
        self.assertIn("+answer = 2", workspace.diff()["patch"])

    def test_paths_hashes_unknown_tools_and_test_allowlist(self):
        workspace = self.workspace()
        for path in ("../answer.py", "C:/answer.py", ".git/config", ".env", "secret.pem"):
            with self.assertRaises(RoutingError):
                workspace.execute("read_file", {"path": path})
        with self.assertRaises(RoutingError):
            workspace.execute("write_file", {"path": "answer.py", "content": "bad", "expected_sha256": ""})
        with self.assertRaises(RoutingError):
            workspace.execute("run_test", {"index": True})
        with self.assertRaises(RoutingError):
            workspace.execute("run_test", {"index": 3})
        with self.assertRaises(RoutingError):
            workspace.execute("shell", {"command": "anything"})

    def test_test_timeout_and_cancel(self):
        spec = {**self.spec, "test_commands": [[sys.executable, "-c", "import time; time.sleep(30)"]], "test_timeout_seconds": .1}
        workspace = self.workspace(spec)
        self.assertEqual(workspace.execute("run_test", {"index": 0})["status"], "limit-reached")
        workspace.cancelled = lambda: True
        with self.assertRaises(RoutingError):
            workspace.execute("read_file", {"path": "answer.py"})

    def test_core_requires_tests_after_latest_write(self):
        workspace = self.workspace()
        replies = iter([
            DevelopmentReply("", [{"name": "run_test", "arguments": '{"index":0}'}]),
            DevelopmentReply("premature report"),
            DevelopmentReply("", [{"name": "write_file", "arguments": json.dumps({"path": "answer.py", "content": "answer = 2\n", "expected_sha256": hashlib.sha256(b"answer = 1\n").hexdigest()})}]),
            DevelopmentReply("", [{"name": "run_test", "arguments": '{"index":0}'}]),
            DevelopmentReply("Fixed; the authorized test passed."),
        ])
        result = run_development("fix answer", invoke=lambda messages, tools: next(replies), execute=workspace.execute,
                                 cancelled=lambda: False, context="offline fixture", required_tests=1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["tests"]), 2)
        self.assertNotEqual(result["tests"][0]["exit_code"], 0)

    def test_workflow_confirm_freeze_duplicate_and_durable_result(self):
        storage = Storage(self.base / "work.sqlite")
        self.addCleanup(storage.close)
        storage.save_record("projects/v1", "project", "one", {"directory": str(self.source)})
        candidate = Candidate("candidate", "account", "model", "api", authorized=True, available=True, fixed_cash=0)
        quality = SimpleNamespace(_scope=lambda params: Scope("one", "session"),
            settings=lambda owner: {"candidate_pool": ["candidate"]},
            select_bindings=lambda owner: {"leader_candidate_id": "candidate", "role_candidate_id": "candidate"},
            engine=SimpleNamespace(candidates=lambda: (candidate,)))
        skills = BuiltinSkills(storage, install_root=self.base / "skills")
        for row in skills.list("one")["skills"]:
            if row["id"] != "troubleshooting-notes":
                skills.set_enabled("one", row["id"], True, row["sha256"])
        work = WorkService(storage, quality, skill_library=skills, skill_data_root=self.base,
                           development_factory=lambda spec, cancelled: DevelopmentWorkspace(self.base / "copies", spec, self.checkpoints, cancelled))
        self.addCleanup(work.close)
        calls = []
        def invoke(selected, scope, messages, tools, cancelled, request_id, spec):
            attempt = work.reserve(request_id, scope, selected, 1000, 1000)
            calls.append(messages)
            work.settle(request_id, scope, attempt, Outcome("completed", input_tokens=1000, output_tokens=1000), selected)
            if len(calls) == 1:
                self.assertNotIn("troubleshooting-notes", str(messages))
                self.assertNotIn("import argparse", str(messages))
                self.assertIn("load_skill", str(tools))
                return DevelopmentReply("", [{"name": "load_skill", "arguments": '{"skill_id":"tool-registry"}'}])
            if len(calls) == 2:
                self.assertIn("check_paths", str(messages))
                self.assertNotIn("import argparse", str(messages))
                return DevelopmentReply("", [{"name": "run_skill_helper", "arguments": '{"skill_id":"tool-registry","helper":"check_paths","operation":"reuse"}'}])
            if len(calls) == 3:
                self.assertIn("configuration-empty", str(messages))
                return DevelopmentReply("", [{"name": "write_file", "arguments": json.dumps({"path": "answer.py", "content": "answer = 2\n", "expected_sha256": hashlib.sha256(b"answer = 1\n").hexdigest()})}])
            if len(calls) == 4:
                return DevelopmentReply("", [{"name": "run_test", "arguments": '{"index":0}'}])
            return DevelopmentReply("Fixed answer; test passed.")
        quality.invoke_development = invoke
        params = {"request_id": "dev", "goal": "fix answer", "project_id": "project", "development": {"test_commands": self.spec["test_commands"]}}
        pending = work.preflight(params)
        for row in skills.list("one")["skills"]:
            skills.set_enabled("one", row["id"], False, row["sha256"])
        self.assertEqual(pending["status"], "awaiting-confirmation")
        work.submit({"request_id": "dev", "assistant_id": "one"})
        self.assertFalse((self.base / "copies").exists())
        self.assertEqual(calls, [])
        with self.assertRaises(RoutingError):
            work.preflight({**params, "development": {"test_commands": []}})
        work.confirm({"request_id": "dev", "assistant_id": "one", "revision": 1, "max_cny": "0"})
        work.submit({"request_id": "dev", "assistant_id": "one"})
        work.submit({"request_id": "dev", "assistant_id": "one"})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = work.get("dev", "one")
            if result["status"] not in {"planning", "executing"}:
                break
            time.sleep(.05)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len(result["attempts"]), 5)
        self.assertIn("+answer = 2", result["development_diff"]["patch"])
        self.assertEqual((self.source / "answer.py").read_text(), "answer = 1\n")

    def test_tool_message_roundtrip_preserves_call_ids_and_reasoning(self):
        source = {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}], "reasoning_content": "context"}
        self.assertEqual(ToolMessage(**source).wire_dict(), source)
        receipt = {"role": "tool", "content": "done", "tool_call_id": "call-1"}
        self.assertEqual(ToolMessage(**receipt).wire_dict(), receipt)


if __name__ == "__main__":
    unittest.main()
