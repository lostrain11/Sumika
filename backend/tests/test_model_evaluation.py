import json
import tempfile
import unittest
from pathlib import Path

from sumika_core.model_evaluation import (
    CAPTURE_SCHEMA_VERSION,
    EVALUATION_SCHEMA_VERSION,
    EvaluationManifest,
    EvaluationRecord,
    EvaluationTaskSet,
    EvaluationValidationError,
    aggregate_evaluations,
    capture_evaluation_payload,
    capture_evaluation_records,
    capture_evaluation_sample,
    load_records,
)


ROOT = Path(__file__).resolve().parents[2]
TASK_SET_PATH = ROOT / "tools" / "fixtures" / "model-evaluation-v1.json"


def manifest(model_id="model-a", model_version="1", cache_state="cold", route_provider="fixture"):
    return {
        "task_set_id": "sumika-agent-core",
        "task_set_version": "1.0.0",
        "harness_id": "dsh",
        "harness_version": "0.1.1-rc.2",
        "adapter_id": "dsh-adapter",
        "adapter_version": "1",
        "provider_kind": route_provider,
        "model_id": model_id,
        "model_version": model_version,
        "hardware_class": "local-rx5700xt",
        "privacy_policy": "local-only",
        "cache_state": cache_state,
    }


def record(task_id, *, model_id="model-a", route_id="route-a", success=True, latency=100, **extra):
    value = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "task_id": task_id,
        "route_id": route_id,
        "manifest": manifest(model_id=model_id, cache_state=extra.pop("cache_state", "cold")),
        "success": success,
        "outcome": "completed" if success else "failed",
        "tool_success": extra.pop("tool_success", True),
        "retry_count": extra.pop("retry_count", 0),
        "latency_ms": latency,
        "estimated_cost": extra.pop("estimated_cost", 0),
        "quota_units": extra.pop("quota_units", 0),
        "quality_passed": extra.pop("quality_passed", success),
        "user_correction": extra.pop("user_correction", False),
        "approval_count": extra.pop("approval_count", 0),
        "observed_at": "2026-08-30T00:00:00+00:00",
    }
    value.update(extra)
    return value


class ModelEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task_set = EvaluationTaskSet.from_file(TASK_SET_PATH)

    def test_fixed_task_set_covers_required_workloads(self):
        self.assertEqual(len(self.task_set.tasks), 8)
        self.assertEqual(
            {task.id for task in self.task_set.tasks},
            {
                "read-only-question",
                "single-file-edit",
                "multi-file-refactor",
                "tool-call",
                "plan-review",
                "mcp-call",
                "browser-approval",
                "workspace-recovery",
            },
        )

    def test_record_rejects_content_and_credential_fields(self):
        with self.assertRaises(EvaluationValidationError) as context:
            EvaluationRecord.from_dict(
                record("read-only-question", prompt="never store this"),
                self.task_set,
            )
        self.assertEqual(context.exception.code, "forbidden-field")
        with self.assertRaises(EvaluationValidationError):
            EvaluationRecord.from_dict(
                record("read-only-question", api_key="secret"),
                self.task_set,
            )

    def test_aggregate_calculates_rates_percentiles_and_coverage(self):
        rows = []
        for task in self.task_set.tasks:
            rows.append(record(task.id, latency=100))
            rows.append(record(task.id, latency=300, retry_count=1, success=False, tool_success=False))
        report = aggregate_evaluations(
            [EvaluationRecord.from_dict(row, self.task_set) for row in rows],
            self.task_set,
            min_repetitions=2,
        )
        candidate = report["cohorts"][0]["candidates"][0]
        self.assertEqual(report["record_count"], 16)
        self.assertEqual(candidate["evidence_status"], "ready")
        self.assertEqual(candidate["covered_task_count"], 8)
        self.assertEqual(candidate["success_rate"], 0.5)
        self.assertEqual(candidate["latency_ms"], {"p50": 200.0, "p95": 300.0})
        self.assertEqual(candidate["retry_total"], 8)
        self.assertEqual(candidate["tool_success_rate"], 0.5)

    def test_cold_and_hot_runs_are_separate_cohorts(self):
        rows = [record("read-only-question", cache_state="cold"), record("read-only-question", cache_state="hot")]
        parsed = [EvaluationRecord.from_dict(row, self.task_set) for row in rows]
        report = aggregate_evaluations(parsed, self.task_set, min_repetitions=1)
        self.assertEqual(report["cohort_count"], 2)
        self.assertEqual({item["comparison"]["cache_state"] for item in report["cohorts"]}, {"cold", "hot"})

    def test_recommendation_requires_separated_confidence_and_never_changes_routing(self):
        rows = []
        for task in self.task_set.tasks:
            for _ in range(4):
                rows.append(record(task.id, model_id="model-a", route_id="route-a", success=True, latency=100))
                rows.append(record(task.id, model_id="model-b", route_id="route-b", success=False, latency=80))
        parsed = [EvaluationRecord.from_dict(row, self.task_set) for row in rows]
        report = aggregate_evaluations(parsed, self.task_set, min_repetitions=4)
        recommendation = report["cohorts"][0]["recommendation"]
        self.assertEqual(recommendation["status"], "diagnostic-recommendation")
        self.assertEqual(recommendation["candidate_route_id"], "route-a")
        self.assertEqual(report["routing_action"], "none")

    def test_partial_input_returns_safe_line_errors_without_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text(
                json.dumps(record("read-only-question"), ensure_ascii=False)
                + "\n"
                + json.dumps(record("read-only-question", prompt="private"), ensure_ascii=False)
                + "\nnot-json\n",
                encoding="utf-8",
            )
            records, errors = load_records(path, self.task_set)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(errors), 2)
        serialized = json.dumps(errors, ensure_ascii=False)
        self.assertNotIn("private", serialized)
        self.assertNotIn("prompt", serialized)

    def test_manifest_dimensions_are_validated(self):
        row = record("read-only-question")
        row["manifest"]["task_set_id"] = "other-set"
        with self.assertRaises(EvaluationValidationError) as context:
            EvaluationRecord.from_dict(row, self.task_set)
        self.assertEqual(context.exception.code, "manifest-task-set-mismatch")

    def test_bounds_and_timestamp_are_strict(self):
        row = record("read-only-question")
        row["retry_count"] = 101
        with self.assertRaises(EvaluationValidationError) as context:
            EvaluationRecord.from_dict(row, self.task_set)
        self.assertEqual(context.exception.code, "retry-count-out-of-range")
        row = record("read-only-question")
        row["observed_at"] = "2026-99-99T00:00:00+00:00"
        with self.assertRaises(EvaluationValidationError) as context:
            EvaluationRecord.from_dict(row, self.task_set)
        self.assertEqual(context.exception.code, "observed-at-invalid")

    def test_capture_requires_opt_in_and_terminal_run(self):
        run = {
            "route_id": "route-a",
            "status": "completed",
            "latency_ms": 123,
            "retry_count": 0,
            "completed_at": "2026-08-31T00:00:00+00:00",
        }
        with self.assertRaisesRegex(EvaluationValidationError, "capture-opt-in-required"):
            capture_evaluation_sample(run, self.task_set, task_id="read-only-question")
        running = dict(run, status="running")
        with self.assertRaisesRegex(EvaluationValidationError, "run-not-terminal"):
            capture_evaluation_sample(running, self.task_set, task_id="read-only-question", opt_in=True, manifest=manifest())

    def test_capture_projects_only_safe_metrics_and_never_run_content(self):
        run = {
            "route_id": "route-a",
            "status": "completed",
            "latency_ms": 123,
            "retry_count": 1,
            "error_code": None,
            "completed_at": "2026-08-31T00:00:00+00:00",
        }
        record_value = capture_evaluation_sample(
            run,
            self.task_set,
            task_id="read-only-question",
            opt_in=True,
            manifest=manifest(),
            metrics={"tool_success": True, "quality_passed": True, "approval_count": 1},
        )
        serialized = json.dumps(record_value.to_dict(), ensure_ascii=False)
        self.assertEqual(record_value.route_id, "route-a")
        self.assertEqual(record_value.latency_ms, 123.0)
        self.assertNotIn("answer", serialized)
        self.assertNotIn("question-body", serialized)
        self.assertEqual(capture_evaluation_payload([record_value])["schema_version"], CAPTURE_SCHEMA_VERSION)

    def test_capture_rejects_sensitive_or_arbitrary_fields(self):
        run = {"route_id": "route-a", "status": "completed", "prompt": "private"}
        with self.assertRaisesRegex(EvaluationValidationError, "forbidden-field"):
            capture_evaluation_sample(run, self.task_set, task_id="read-only-question", opt_in=True, manifest=manifest())
        run = {"route_id": "route-a", "status": "completed"}
        with self.assertRaisesRegex(EvaluationValidationError, "forbidden-field"):
            capture_evaluation_sample(run, self.task_set, task_id="read-only-question", opt_in=True, manifest=manifest(), metrics={"answer": "private"})

    def test_capture_batch_uses_explicit_task_ids(self):
        runs = [
            {"route_id": "route-a", "status": "completed", "completed_at": "2026-08-31T00:00:00+00:00"},
            {"route_id": "route-a", "status": "failed", "completed_at": "2026-08-31T00:00:01+00:00"},
        ]
        captured = capture_evaluation_records(
            runs,
            self.task_set,
            task_ids=["read-only-question", "tool-call"],
            manifest=manifest(),
            opt_in=True,
        )
        self.assertEqual([item.task_id for item in captured], ["read-only-question", "tool-call"])
        self.assertEqual(captured[1].outcome, "failed")


if __name__ == "__main__":
    unittest.main()
