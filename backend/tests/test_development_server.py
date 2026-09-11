import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from quality_routing import Candidate
from quality_routing.development import DevelopmentReply
from sumika_core.server import CoreApplication, JsonRpcError


class DevelopmentServerTests(unittest.TestCase):
    def test_inspection_rpc_survives_core_reopen_without_dispatch_or_storage_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            subprocess.run(["git", "init", "--template=", str(source)], check=True, capture_output=True)
            (source / "answer.py").write_bytes(b"answer = 1\n")
            candidate = Candidate("fixture", "account", "model", "api", authorized=True, available=True, fixed_cash=0)
            application = CoreApplication(base / "data", route_sources=[])
            params = {"request_id": "inspect-fixture", "assistant_id": "sumika"}
            try:
                application.projects.create_project("sumika", project_id="project", directory=str(source))
                with patch.object(application.quality, "select_bindings", return_value={
                        "leader_candidate_id": "fixture", "role_candidate_id": "fixture"}), \
                     patch.object(application.quality.engine, "candidates", return_value=(candidate,)), \
                     patch.object(application.quality, "invoke_development", return_value=DevelopmentReply("fixture result")):
                    pending = application._rpc("work.task.preflight", {**params, "goal": "Inspect fixture source",
                                               "project_id": "project", "development": {"test_commands": []}})
                    self.assertEqual(pending["status"], "awaiting-confirmation")
                    application._rpc("work.authorization.confirm", {**params, "revision": 1, "max_cny": "0"})
                    application._rpc("work.task.submit", params)
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        value = application._rpc("work.task.get", params)
                        if value["status"] not in {"planning", "executing"}:
                            break
                        time.sleep(.02)
                    self.assertEqual(value["status"], "review-required", value)
                    inspected = application._rpc("work.task.inspect", params)
                    self.assertTrue(inspected["baseline_unchanged"])
                    self.assertFalse(inspected["test_evidence_current"])
                    self.assertFalse(inspected["independently_verified"])
            finally:
                application.close()
            application = CoreApplication(base / "data", route_sources=[])
            try:
                with patch.object(application.quality, "invoke_development") as invoke:
                    before = application._rpc("work.task.get", params)
                    self.assertEqual(application._rpc("work.task.inspect", params), inspected)
                    self.assertEqual(application._rpc("work.task.get", params), before)
                    with self.assertRaises(JsonRpcError):
                        application._rpc("work.task.inspect", {**params, "assistant_id": "another"})
                    invoke.assert_not_called()
                    self.assertEqual((source / "answer.py").read_bytes(), b"answer = 1\n")
            finally:
                application.close()
