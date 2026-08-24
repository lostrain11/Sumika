import tempfile
import unittest
from pathlib import Path

from sumika_core.diagnostics import redact_text, safe_error
from sumika_core.protocol.models import EventEnvelope
from sumika_core.server import CoreApplication


class DiagnosticsTests(unittest.TestCase):
    def test_redacts_common_secret_shapes(self):
        value = redact_text("Authorization: Bearer abc123 api_key=secret sk-test_value")
        self.assertNotIn("abc123", value)
        self.assertNotIn("secret", value)
        self.assertNotIn("sk-test_value", value)
        self.assertIn("[REDACTED]", value)

    def test_safe_error_keeps_type_and_redacts_message(self):
        detail = safe_error(RuntimeError("token=private-value"))
        self.assertEqual(detail["type"], "RuntimeError")
        self.assertNotIn("private-value", detail["message"])

    def test_core_diagnostics_and_rotating_log(self):
        with tempfile.TemporaryDirectory() as directory:
            application = CoreApplication(Path(directory))
            try:
                diagnostics = application.rpc("core.diagnostics", {})
                self.assertEqual(diagnostics["data_dir"], directory)
                self.assertEqual(diagnostics["pid"] > 0, True)
                self.assertTrue(diagnostics["log_path"])
                application.events.publish(EventEnvelope("diagnostics.test", {"content": "must stay out of core.log"}))
            finally:
                application.close()
            log_path = Path(directory) / "logs" / "core.log"
            self.assertTrue(log_path.is_file())
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("core initialized", log)
            self.assertIn("event published type=diagnostics.test", log)
            self.assertNotIn("must stay out of core.log", log)


if __name__ == "__main__":
    unittest.main()
