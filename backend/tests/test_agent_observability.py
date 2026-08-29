import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sumika_core.observability import AgentObservability, classify_rpc_method


class AgentObservabilityTests(unittest.TestCase):
    def test_disabled_sink_does_not_create_runtime_files(self):
        sink = AgentObservability(None)
        self.assertFalse(sink.enabled)
        self.assertIsNone(sink.record(component="agent", capability="test", phase="start"))
        self.assertEqual(sink.aggregate()["record_count"], 0)

    def test_receipts_are_content_independent_and_aggregate_by_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = AgentObservability(directory, max_bytes=4096)
            operation = sink.start(
                component="agent",
                capability="session.prompt",
                session_id="private-session",
                turn_id="private-turn",
                adapter_id="dsh",
                adapter_version="0.1.1-rc.2",
                provider_kind="openai-compatible",
                processing_location="cloud",
            )
            sink.finish(
                operation,
                component="agent",
                capability="session.prompt",
                outcome="completed",
                duration_ms=100,
                session_id="private-session",
                turn_id="private-turn",
                adapter_id="dsh",
                adapter_version="0.1.1-rc.2",
                provider_kind="openai-compatible",
                processing_location="cloud",
                output_units=12,
            )
            sink.record(
                component="agent",
                capability="session.prompt",
                phase="failure",
                outcome="failed",
                duration_ms=300,
                error_class="TimeoutError",
                session_id="private-session",
                turn_id="private-turn-2",
                adapter_id="dsh",
                adapter_version="0.1.1-rc.2",
                provider_kind="openai-compatible",
                processing_location="cloud",
            )
            report = sink.aggregate()
            self.assertEqual(report["record_count"], 3)
            self.assertEqual(len(report["groups"]), 1)
            group = report["groups"][0]
            self.assertEqual(group["outcomes"]["completed"], 1)
            self.assertEqual(group["outcomes"]["failed"], 1)
            self.assertEqual(group["duration_ms"]["p50"], 200)
            self.assertEqual(group["duration_ms"]["p95"], 290)
            raw = "".join(path.read_text(encoding="utf-8") for path in Path(directory, "logs", "agent-observability").glob("*.jsonl"))
            self.assertNotIn("private-session", raw)
            self.assertNotIn("private-turn", raw)
            self.assertIn("TimeoutError", raw)
            self.assertNotIn("prompt body", raw)
            summary = sink.write_daily_summary()
            self.assertTrue(Path(directory, "logs", "agent-observability", f"{summary['day']}.summary.json").is_file())

    def test_rotation_keeps_jsonl_parts_and_unknown_fields_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = AgentObservability(directory, max_bytes=4096)
            for index in range(12):
                sink.record(
                    component="memory",
                    capability="retrieve",
                    phase="end",
                    outcome="completed",
                    duration_ms=index + 1,
                    adapter_id="memory-plugin",
                )
            root = Path(directory, "logs", "agent-observability")
            parts = list(root.glob("*.jsonl"))
            self.assertGreaterEqual(len(parts), 1)
            for part in parts:
                for line in part.read_text(encoding="utf-8").splitlines():
                    self.assertIsInstance(json.loads(line), dict)
            # A malformed line is counted, not allowed to poison the report.
            with (root / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl").open("ab") as stream:
                stream.write(b"not-json\n")
            report = sink.aggregate()
            self.assertGreaterEqual(report["invalid_lines"], 1)

    def test_date_and_rpc_classification_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            sink = AgentObservability(directory)
            with self.assertRaises(ValueError):
                sink.aggregate("2026-99-99")
        self.assertEqual(classify_rpc_method("agent.session.prompt"), ("agent", "agent.session.prompt"))
        self.assertEqual(classify_rpc_method("chat.send"), ("provider", "chat.send"))
        component, capability = classify_rpc_method("unknown/with secret")
        self.assertEqual(component, "rpc")
        self.assertTrue(capability.startswith("hash-"))


if __name__ == "__main__":
    unittest.main()
