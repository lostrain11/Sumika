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
                application.route_trace.record(
                    "decision.made",
                    trace_id="trace-server-test",
                    session_id="private-session",
                    route_id="route-server-test",
                    outcome="recommended",
                )
                report = application.rpc("agent.observability.daily", {})
                self.assertEqual(report["schema_version"], 1)
                self.assertGreaterEqual(report["record_count"], 1)
                self.assertEqual(report["route_decision_trace"]["schema"], "route-decision-trace/v1")
                self.assertEqual(report["route_decision_trace"]["selected_routes"], {"route-server-test": 1})
                route_status = application.rpc("agent.route.trace.status", {})
                self.assertTrue(route_status["enabled"])
                self.assertEqual(route_status["relative_path"], "logs/route-decision-trace")
                diagnostics = application.rpc("core.diagnostics", {})
                self.assertTrue(diagnostics["agent_observability"]["enabled"])
                self.assertEqual(diagnostics["agent_observability"]["relative_path"], "logs/agent-observability")
                self.assertTrue(diagnostics["route_decision_trace"]["enabled"])
            finally:
                application.close()
            summary_files = list(Path(directory, "logs", "agent-observability").glob("*.summary.json"))
            self.assertTrue(summary_files)
            self.assertNotIn("private prompt", "".join(path.read_text(encoding="utf-8") for path in summary_files))
            route_summaries = list(Path(directory, "logs", "route-decision-trace").glob("*.summary.json"))
            self.assertTrue(route_summaries)
            self.assertNotIn("private-session", "".join(path.read_text(encoding="utf-8") for path in route_summaries))

    def test_memory_application_keeps_observability_disabled(self):
        application = CoreApplication(":memory:")
        try:
            self.assertFalse(application.rpc("agent.observability.status", {})["enabled"])
            self.assertFalse(application.rpc("agent.route.trace.status", {})["enabled"])
        finally:
            application.close()


if __name__ == "__main__":
    unittest.main()
