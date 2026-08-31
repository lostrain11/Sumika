import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

try:
    import capture_model_evaluations as command
except ModuleNotFoundError:  # Running as ``tools.test_capture_model_evaluations``.
    from tools import capture_model_evaluations as command


def _manifest():
    return {
        "task_set_id": "sumika-agent-core",
        "task_set_version": "1.0.0",
        "harness_id": "dsh",
        "harness_version": "fixture",
        "adapter_id": "fixture-adapter",
        "adapter_version": "1",
        "provider_kind": "local",
        "model_id": "fixture-model",
        "model_version": "1",
        "hardware_class": "fixture",
        "privacy_policy": "local-only",
        "cache_state": "cold",
    }


def _capture(task_id="read-only-question", **run):
    return {
        "schema_version": "sumika.model-evaluation-capture/v1",
        "task_id": task_id,
        "manifest": _manifest(),
        "run": {
            "route_id": "route-fixture",
            "status": "completed",
            "latency_ms": 100,
            "retry_count": 0,
            "completed_at": "2026-08-31T00:00:00+00:00",
            **run,
        },
        "metrics": {"tool_success": True, "quality_passed": True},
    }


class CaptureModelEvaluationCommandTests(unittest.TestCase):
    def test_opt_in_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "captures.json"
            source.write_text(json.dumps([_capture()]), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = command.main(["--input", str(source)])
        self.assertEqual(code, 1)
        self.assertIn("rejected=1", output.getvalue())
        self.assertNotIn("route-fixture", output.getvalue())

    def test_valid_capture_is_bounded_and_can_be_replayed_by_evaluator(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "captures.json"
            source.write_text(json.dumps([_capture()]), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = command.main(["--input", str(source), "--opt-in", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["schema_version"], "sumika.model-evaluation-capture/v1")
        self.assertEqual(payload["accepted_records"], 1)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("answer", serialized)

    def test_sensitive_capture_is_rejected_without_echoing_value(self):
        value = _capture()
        value["run"]["prompt"] = "private prompt"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "captures.json"
            source.write_text(json.dumps([value]), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = command.main(["--input", str(source), "--opt-in", "--json"])
        self.assertEqual(code, 1)
        self.assertNotIn("private prompt", output.getvalue())
        self.assertNotIn("prompt", output.getvalue())

    def test_output_does_not_overwrite_an_existing_report(self):
        with tempfile.TemporaryDirectory(dir=command.ROOT) as directory:
            source = Path(directory) / "captures.json"
            source.write_text(json.dumps([_capture()]), encoding="utf-8")
            target = Path(directory) / "capture.json"
            target.write_text("old\n", encoding="utf-8")
            code = command.main(["--input", str(source), "--opt-in", "--output", str(target)])
            self.assertEqual(code, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertTrue((Path(directory) / "capture-1.json").is_file())


if __name__ == "__main__":
    unittest.main()
