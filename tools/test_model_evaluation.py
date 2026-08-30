import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

try:
    import evaluate_models as command
except ModuleNotFoundError:  # Running as ``tools.test_model_evaluation``.
    from tools import evaluate_models as command


def _record():
    return {
        "schema_version": "sumika.model-evaluation/v1",
        "task_id": "read-only-question",
        "route_id": "route-a",
        "manifest": {
            "task_set_id": "sumika-agent-core",
            "task_set_version": "1.0.0",
            "harness_id": "dsh",
            "harness_version": "0.1.1-rc.2",
            "adapter_id": "dsh-adapter",
            "adapter_version": "1",
            "provider_kind": "ollama",
            "model_id": "qwen3:4b",
            "model_version": "local",
            "hardware_class": "local-rx5700xt",
            "privacy_policy": "local-only",
            "cache_state": "cold",
        },
        "success": True,
        "outcome": "completed",
        "tool_success": None,
        "retry_count": 0,
        "latency_ms": 420,
        "estimated_cost": 0,
        "quota_units": 0,
        "quality_passed": True,
        "user_correction": False,
        "approval_count": 0,
    }


class ModelEvaluationCommandTests(unittest.TestCase):
    def test_cli_reports_insufficient_evidence_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "records.jsonl"
            input_path.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = command.main(["--input", str(input_path)])
        self.assertEqual(code, 0)
        self.assertIn("Sumika model evaluation: passed", output.getvalue())
        self.assertIn("recommendation=insufficient-evidence", output.getvalue())

    def test_cli_rejects_bad_record_and_does_not_echo_content(self):
        row = _record()
        row["prompt"] = "private content"
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "records.jsonl"
            input_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = command.main(["--input", str(input_path), "--json"])
        self.assertEqual(code, 1)
        serialized = output.getvalue()
        self.assertNotIn("private content", serialized)
        self.assertNotIn("prompt", serialized)

    def test_output_path_is_scoped_and_old_report_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=command.ROOT) as directory:
            input_path = Path(directory) / "records.jsonl"
            input_path.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
            target = Path(directory) / "report.json"
            target.write_text("old\n", encoding="utf-8")
            code = command.main(["--input", str(input_path), "--output", str(target)])
            self.assertEqual(code, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertTrue((Path(directory) / "report-1.json").is_file())


if __name__ == "__main__":
    unittest.main()
