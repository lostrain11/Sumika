from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quality_routing.dsh_helper import HELPER_SCHEMA, capabilities


class DshHelperTests(unittest.TestCase):
    def test_capabilities_fail_closed_for_real_model_execution(self):
        value = capabilities()
        self.assertEqual(value["schema"], HELPER_SCHEMA)
        self.assertFalse(value["sumika_core_dependency"])
        self.assertFalse(value["real_model_execution"]["available"])
        self.assertFalse(value["offline_fixture"]["real_model"])
        self.assertFalse(value["model_tool_can_approve"])

    def test_stdio_helper_runs_fixture_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen(
                [sys.executable, "-m", "quality_routing.dsh_helper", "--data-dir", directory],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            requests = (
                {"id": 1, "method": "health", "params": {}},
                {"id": 2, "method": "offline_fixture", "params": {}},
                {"id": 3, "method": "shutdown", "params": {}},
            )
            output, errors = process.communicate("".join(json.dumps(item) + "\n" for item in requests), timeout=10)
            self.assertEqual(process.returncode, 0, errors)
            responses = [json.loads(line) for line in output.splitlines()]
            self.assertEqual(responses[0]["result"]["status"], "ready")
            fixture = responses[1]["result"]
            self.assertEqual(fixture["states"], ["awaiting-confirmation", "ready", "completed"])
            self.assertFalse(fixture["real_model"])
            lifecycle = json.loads((Path(directory) / "lifecycle.json").read_text(encoding="utf-8"))
            self.assertEqual(lifecycle["state"], "stopped")


if __name__ == "__main__":
    unittest.main()

