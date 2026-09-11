import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quality_routing import Candidate, Outcome, RoutingError, Scope
from quality_routing.development import DevelopmentReply, run_development
from quality_routing.development_journal import SCHEMA, append_event, evidence_digest
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

    def workflow(self):
        storage = Storage(self.base / "recovery.sqlite")
        self.addCleanup(storage.close)
        storage.save_record("projects/v1", "project", "one", {"directory": str(self.source)})
        candidate = Candidate("candidate", "account", "model", "api", authorized=True, available=True, fixed_cash=0)
        quality = SimpleNamespace(_scope=lambda params: Scope("one", "session"),
            settings=lambda owner: {"candidate_pool": ["candidate"]},
            select_bindings=lambda owner: {"leader_candidate_id": "candidate", "role_candidate_id": "candidate"},
            engine=SimpleNamespace(candidates=lambda: (candidate,)), invoke_development=Mock())
        work = WorkService(storage, quality, development_factory=lambda spec, cancelled:
                           DevelopmentWorkspace(self.base / "copies", spec, self.checkpoints, cancelled))
        self.addCleanup(work.close)
        work.preflight({"request_id": "dev", "goal": "fix", "project_id": "project", "development": {"test_commands": []}})
        work.confirm({"request_id": "dev", "assistant_id": "one", "revision": 1, "max_cny": "0"})
        return work, storage, quality

    def intent(self, kind="tool"):
        if kind == "model":
            return {"schema_version": SCHEMA, "kind": "model", "turn": 1, "operation_id": "model-1",
                    "phase": "started", "input_digest": evidence_digest("fixture")}
        return {"schema_version": SCHEMA, "kind": "tool", "turn": 1, "slot": 0,
                "operation_id": "tool-1-0", "name": "write_file", "phase": "started",
                "input_digest": evidence_digest("fixture")}

    def test_sqlite_restart_preserves_unknown_tool_and_blocks_revise_and_submit(self):
        work, storage, quality = self.workflow()
        value = work.get("dev", "one")
        value.update(status="executing", development_journal=append_event([], self.intent()))
        storage.save_record(work.namespace, "dev", "one", value)
        work.close()
        storage.close()
        reopened = Storage(self.base / "recovery.sqlite")
        self.addCleanup(reopened.close)
        restored = WorkService(reopened, quality, owner_ids=("one",))
        self.addCleanup(restored.close)
        current = restored.get("dev", "one")
        self.assertEqual(current["status"], "submission-unknown")
        self.assertEqual(current["development_recovery"]["pending_operations"][0]["name"], "write_file")
        self.assertFalse(current["development_recovery"]["automatic_replay"])
        self.assertEqual(restored.submit({"request_id": "dev", "assistant_id": "one"})["status"], "submission-unknown")
        self.assertEqual(restored.cancel({"request_id": "dev", "assistant_id": "one"})["status"], "cancel-requested")
        with self.assertRaises(RoutingError):
            restored.revise({"request_id": "dev", "assistant_id": "one"})
        with self.assertRaises(RoutingError):
            restored.confirm({"request_id": "dev", "assistant_id": "one", "revision": 1, "max_cny": "0"})
        with self.assertRaises(RoutingError):
            restored.get("dev", "two")
        quality.invoke_development.assert_not_called()

    def test_restart_retains_model_reservation_and_safe_boundary_is_interrupted(self):
        work, storage, quality = self.workflow()
        value = work.get("dev", "one")
        value.update(status="executing", development_journal=append_event([], self.intent("model")))
        value["attempts"] = {"attempt": {"status": "reserved", "upper_cny": "1"}}
        value["authorization"]["reserved_cny"] = "1"
        storage.save_record(work.namespace, "dev", "one", value)
        work.close()
        restored = WorkService(storage, quality, owner_ids=("one",))
        self.addCleanup(restored.close)
        self.assertEqual(restored.get("dev", "one")["authorization"]["reserved_cny"], "1")
        self.assertTrue(restored.get("dev", "one")["attempts"]["attempt"]["submission_unknown"])
        value.update(status="executing", development_journal=[])
        value["attempts"] = {}
        value["authorization"]["reserved_cny"] = "0"
        storage.save_record(work.namespace, "dev", "one", value)
        restored.close()
        safe = WorkService(storage, quality, owner_ids=("one",))
        self.addCleanup(safe.close)
        self.assertEqual(safe.get("dev", "one")["status"], "interrupted")
        self.assertEqual(safe.submit({"request_id": "dev", "assistant_id": "one"})["status"], "interrupted")
        quality.invoke_development.assert_not_called()

    def test_tool_write_then_exception_is_unknown_in_actual_work_service(self):
        work, storage, quality = self.workflow()
        quality.invoke_development.return_value = DevelopmentReply("", [{"name": "write_file", "arguments": json.dumps(
            {"path": "answer.py", "content": "answer = 2\n", "expected_sha256": hashlib.sha256(b"answer = 1\n").hexdigest()})}])
        original = DevelopmentWorkspace.execute
        def broken_receipt(workspace, name, arguments):
            original(workspace, name, arguments)
            raise OSError("receipt lost after write")
        value = work.get("dev", "one")
        value["status"] = "planning"
        storage.save_record(work.namespace, "dev", "one", value)
        with patch.object(DevelopmentWorkspace, "execute", broken_receipt):
            work._run(value)
        result = work.get("dev", "one")
        self.assertEqual(result["status"], "submission-unknown")
        self.assertEqual((Path(result["development_workspace"]["path"]) / "answer.py").read_text(), "answer = 2\n")
        self.assertEqual((self.source / "answer.py").read_text(), "answer = 1\n")
        work.submit({"request_id": "dev", "assistant_id": "one"})
        quality.invoke_development.assert_called_once()

    def test_reserve_requires_executing_intent_and_rejects_duplicate_turn(self):
        work, storage, quality = self.workflow()
        candidate = quality.engine.candidates()[0]
        with self.assertRaises(RoutingError):
            work.reserve("dev", Scope("one", "session"), candidate, 1, 1)
        value = work.get("dev", "one")
        value.update(status="executing", development_journal=append_event([], self.intent("model")))
        storage.save_record(work.namespace, "dev", "one", value)
        attempt = work.reserve("dev", Scope("one", "session"), candidate, 1, 1)
        self.assertEqual(work.get("dev", "one")["attempts"][attempt]["development_operation_id"], "model-1")
        with self.assertRaises(RoutingError):
            work.reserve("dev", Scope("one", "session"), candidate, 1, 1)

    def test_submit_transaction_conflict_does_not_dispatch(self):
        work, storage, quality = self.workflow()
        with patch.object(storage, "save_record_group", side_effect=ValueError("concurrent request")), patch.object(work._pool, "submit") as dispatch:
            work.submit({"request_id": "dev", "assistant_id": "one"})
        dispatch.assert_not_called()
        quality.invoke_development.assert_not_called()

    def test_executor_binding_cannot_switch_after_confirmation(self):
        work, storage, quality = self.workflow()
        value = work.get("dev", "one")
        self.assertEqual(value["development_executor_id"], "api-source-copy/v1")
        self.assertEqual(value["authorization"]["development_executor_id"], value["development_executor_id"])
        replacement = SimpleNamespace(executor_id="different/v1", run=Mock())
        work.development_executor = replacement
        work._run(value)
        replacement.run.assert_not_called()
        quality.invoke_development.assert_not_called()
        self.assertEqual(work.get("dev", "one")["status"], "failed")
        self.assertFalse((self.base / "copies").exists())

    def test_legacy_executor_binding_is_only_compatible_with_original_adapter(self):
        work, storage, quality = self.workflow()
        value = work.get("dev", "one")
        value.pop("development_executor_id")
        value["authorization"].pop("development_executor_id")
        work._check_development(value)
        work.development_executor = SimpleNamespace(executor_id="different/v1")
        with self.assertRaises(RoutingError):
            work._check_development(value)
        quality.invoke_development.assert_not_called()

    def test_saved_inspection_is_read_only_scoped_and_detects_stale_evidence(self):
        work, storage, quality = self.workflow()
        workspace = self.workspace()
        prepared = {"path": str(workspace.root), "checkpoint_id": workspace.checkpoint_id,
                    "files": list(workspace.source_paths), "workspace_digest": workspace.source_digest()}
        value = work.get("dev", "one")
        value["development"] = self.spec
        from quality_routing.workflow import delegation_digest
        value["authorization"]["development_digest"] = delegation_digest([self.spec])
        value.update(status="completed", development_workspace=prepared,
                     development_result={"status": "completed", "workspace_digest": workspace.source_digest()})
        storage.save_record(work.namespace, "dev", "one", value)
        fresh = work.rpc("work.task.inspect", {"request_id": "dev", "assistant_id": "one"})
        self.assertTrue(fresh["test_evidence_current"])
        self.assertFalse(fresh["independently_verified"])
        (workspace.root / "answer.py").write_bytes(b"answer = 3\n")
        inspected = work.rpc("work.task.inspect", {"request_id": "dev", "assistant_id": "one"})
        self.assertFalse(inspected["test_evidence_current"])
        self.assertIn("+answer = 3", inspected["diff"]["patch"])
        self.assertEqual(storage.get_record(work.namespace, "dev", "one"), value)
        with self.assertRaises(RoutingError):
            work.rpc("work.task.inspect", {"request_id": "dev", "assistant_id": "two"})
        quality.invoke_development.assert_not_called()

    def test_saved_inspection_rejects_another_workspace_checkpoint(self):
        first = self.workspace()
        other = self.workspace()
        with self.assertRaises(ValueError):
            first.inspect_saved({"path": str(other.root), "checkpoint_id": first.checkpoint_id,
                                 "files": list(first.source_paths)})
        with self.assertRaises(RoutingError):
            first.inspect_saved({"path": str(self.source), "checkpoint_id": first.checkpoint_id,
                                 "files": list(first.source_paths)})

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

    def test_test_receipt_is_invalidated_by_external_source_change(self):
        workspace = self.workspace()
        first = workspace.execute("run_test", {"index": 0})
        self.assertNotEqual(first["exit_code"], 0)
        (workspace.root / "notes.py").write_text("note = True\n", encoding="utf-8")
        second = workspace.execute("run_test", {"index": 0})
        self.assertNotEqual(first["workspace_digest"], second["workspace_digest"])
        self.assertEqual(len(second["workspace_digest"]), 64)

    def test_source_digest_is_stable_and_changes_for_new_visible_file(self):
        workspace = self.workspace()
        original = workspace.source_digest()
        self.assertEqual(original, workspace.source_digest())
        (workspace.root / "notes.py").write_text("note = True\n", encoding="utf-8")
        self.assertNotEqual(original, workspace.source_digest())

    def test_digest_tracks_deleted_and_gitignored_source_but_not_runtime_cache(self):
        (self.source / ".gitignore").write_bytes(b"extra.py\n")
        workspace = self.workspace()
        original = workspace.source_digest()
        (workspace.root / "__pycache__").mkdir()
        (workspace.root / "__pycache__" / "answer.pyc").write_bytes(b"cache")
        self.assertEqual(original, workspace.source_digest())
        (workspace.root / "extra.py").write_bytes(b"extra = 1\n")
        self.assertNotEqual(original, workspace.source_digest())
        added = workspace.source_digest()
        (workspace.root / "answer.py").unlink()
        self.assertNotEqual(added, workspace.source_digest())

    def test_test_cannot_certify_the_tree_it_mutated(self):
        command = [sys.executable, "-c", "from pathlib import Path; Path('answer.py').write_text('answer = 2\\n')"]
        workspace = self.workspace({**self.spec, "test_commands": [command]})
        reply = DevelopmentReply("", [{"name": "run_test", "arguments": '{"index":0}'}])
        replies = iter([reply, DevelopmentReply("done")])
        result = run_development("test", invoke=lambda messages, tools: next(replies), execute=workspace.execute,
                                 cancelled=lambda: False, context="fixture", required_tests=1, max_calls=2,
                                 workspace_digest=workspace.source_digest)
        self.assertEqual(result["tests"][0]["exit_code"], 0)
        self.assertFalse(result["tests"][0]["workspace_unchanged"])
        self.assertEqual(result["status"], "limit-reached")

    def test_external_edit_after_passing_test_prevents_completion(self):
        workspace = self.workspace({**self.spec, "test_commands": [[sys.executable, "-c", "pass"]]})
        calls = []
        def invoke(messages, tools):
            calls.append(True)
            if len(calls) == 1:
                return DevelopmentReply("", [{"name": "run_test", "arguments": '{"index":0}'}])
            (workspace.root / "answer.py").write_bytes(b"answer = 9\n")
            return DevelopmentReply("done")
        result = run_development("test", invoke=invoke, execute=workspace.execute, cancelled=lambda: False,
                                 context="fixture", required_tests=1, max_calls=2, workspace_digest=workspace.source_digest)
        self.assertEqual(result["tests"][0]["exit_code"], 0)
        self.assertEqual(result["status"], "limit-reached")

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
        records = result["development_journal"]
        self.assertEqual(len(records), 18)
        self.assertEqual(records[0]["phase"], "started")
        self.assertEqual(records[-1]["phase"], "finished")
        self.assertNotIn("Fixed answer", json.dumps(records))
        self.assertNotIn("answer = 2", json.dumps(records))
        self.assertFalse((Path(result["development_workspace"]["path"]) / ".sumika" / "journal.jsonl").exists())
        self.assertIn("+answer = 2", result["development_diff"]["patch"])
        self.assertEqual((self.source / "answer.py").read_text(), "answer = 1\n")

    def test_tool_message_roundtrip_preserves_call_ids_and_reasoning(self):
        source = {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}], "reasoning_content": "context"}
        self.assertEqual(ToolMessage(**source).wire_dict(), source)
        receipt = {"role": "tool", "content": "done", "tool_call_id": "call-1"}
        self.assertEqual(ToolMessage(**receipt).wire_dict(), receipt)


if __name__ == "__main__":
    unittest.main()
