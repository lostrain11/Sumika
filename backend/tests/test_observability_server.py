import tempfile
import unittest
from pathlib import Path

from sumika_core.protocol.models import EventEnvelope
from sumika_core.server import CoreApplication


class ObservabilityServerTests(unittest.TestCase):
    def test_rpc_exposes_safe_daily_report_and_core_diagnostics_path(self):
        with tempfile.TemporaryDirectory() as directory:
            application = CoreApplication(Path(directory))
            try:
                application.events.publish(
                    EventEnvelope(
                        "agent.session.event",
                        {"content": "private prompt", "session_id": "session-private"},
                        session_id="session-private",
                    )
                )
                report = application.rpc("agent.observability.daily", {})
                self.assertEqual(report["schema_version"], 1)
                self.assertGreaterEqual(report["record_count"], 1)
                diagnostics = application.rpc("core.diagnostics", {})
                self.assertTrue(diagnostics["agent_observability"]["enabled"])
                self.assertEqual(diagnostics["agent_observability"]["relative_path"], "logs/agent-observability")
            finally:
                application.close()
            summary_files = list(Path(directory, "logs", "agent-observability").glob("*.summary.json"))
            self.assertTrue(summary_files)
            self.assertNotIn("private prompt", "".join(path.read_text(encoding="utf-8") for path in summary_files))

    def test_memory_application_keeps_observability_disabled(self):
        application = CoreApplication(":memory:")
        try:
            self.assertFalse(application.rpc("agent.observability.status", {})["enabled"])
        finally:
            application.close()


if __name__ == "__main__":
    unittest.main()
