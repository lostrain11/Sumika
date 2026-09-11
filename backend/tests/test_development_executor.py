import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from quality_routing import RoutingError
from quality_routing.development import DevelopmentReply
from quality_routing.development_journal import append_event
from sumika_core.development.executor import ApiDevelopmentExecutor


class DevelopmentExecutorTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.workspace = SimpleNamespace(prepare=Mock(return_value={"path": "fixture"}),
            diff=Mock(return_value={"patch": ""}), source_digest=Mock(return_value="a" * 64),
            execute=Mock(), inspect_saved=Mock(return_value={"workspace_digest": "a" * 64}))
        self.factory = Mock(return_value=self.workspace)
        self.executor = ApiDevelopmentExecutor(self.factory)
        self.spec = {"max_calls": 2, "test_commands": []}

    def journal(self, event):
        self.records = append_event(self.records, event)

    def run_executor(self, **overrides):
        options = {"spec": self.spec, "skills": [], "invoke": Mock(return_value=DevelopmentReply("done")),
                   "helper": Mock(), "cancelled": lambda: False, "prepared": Mock(),
                   "journal": self.journal, "event": Mock()}
        options.update(overrides)
        return self.executor.run("fixture", **options)

    def test_adapter_runs_without_application_storage_or_quality_service(self):
        prepared = Mock()
        def invoke(messages, tools):
            prepared.assert_called_once_with({"path": "fixture"})
            self.assertEqual(self.records[-1]["phase"], "started")
            return DevelopmentReply("done")
        result = self.run_executor(invoke=invoke, prepared=prepared)
        self.assertEqual(result["schema_version"], "development-execution/v1")
        self.assertEqual(result["executor_id"], "api-source-copy/v1")
        self.assertEqual(result["result"]["status"], "review-required")
        self.assertEqual(self.spec, {"max_calls": 2, "test_commands": []})
        self.assertIsNot(self.factory.call_args.args[0], self.spec)

    def test_failed_preparation_receipt_prevents_model_and_tool_calls(self):
        invoke = Mock()
        with self.assertRaises(OSError):
            self.run_executor(prepared=Mock(side_effect=OSError("storage failure")), invoke=invoke)
        invoke.assert_not_called()
        self.workspace.execute.assert_not_called()
        self.assertEqual(self.records, [])

    def test_cancel_before_preparation_creates_nothing(self):
        with self.assertRaises(RoutingError):
            self.run_executor(cancelled=lambda: True)
        self.factory.assert_not_called()

    def test_readonly_inspection_does_not_prepare_or_execute(self):
        result = self.executor.inspect(self.spec, {"checkpoint_id": "fixture"})
        self.assertEqual(result["workspace_digest"], "a" * 64)
        self.workspace.prepare.assert_not_called()
        self.workspace.execute.assert_not_called()

    def test_receipt_after_diff_still_checks_source(self):
        self.spec["test_commands"] = [["fixture"]]
        self.workspace.execute.return_value = {"index": 0, "status": "finished", "exit_code": 0,
            "workspace_unchanged": True, "workspace_digest_before": "a" * 64, "workspace_digest": "a" * 64}
        replies = [DevelopmentReply("", [{"name": "run_test", "arguments": '{"index":0}'}]), DevelopmentReply("done")]
        self.workspace.source_digest.side_effect = ["a" * 64, "a" * 64, "b" * 64]
        result = self.run_executor(invoke=Mock(side_effect=replies))
        self.assertEqual(result["result"]["status"], "review-required")
        self.assertEqual(result["result"]["verification_error"], "source-changed-before-delivery")

    def test_adapter_dependency_boundary(self):
        root = Path(__file__).resolve().parents[1] / "src/sumika_core/development"
        for name in ("contracts.py", "executor.py"):
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            for module in modules:
                self.assertFalse(any(part in {"server", "storage", "quality", "tauri"} for part in module.split(".")), module)
