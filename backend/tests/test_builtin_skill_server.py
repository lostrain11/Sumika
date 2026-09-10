import tempfile
import unittest
from pathlib import Path

from sumika_core.server import CoreApplication


class BuiltinSkillServerTests(unittest.TestCase):
    def test_persistent_core_registration_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            application = CoreApplication(directory, route_sources=[])
            try:
                rows = application._rpc("skill.builtin.list", {"assistant_id": "sumika"})["skills"]
                self.assertEqual(len(rows), 3)
                result = application._rpc("skill.builtin.set", {"assistant_id": "sumika", "skill_id": "tool-registry", "enabled": True, "sha256": rows[-1]["sha256"]})
                selected = result["skills"][-1]
                self.assertTrue(selected["enabled"])
                self.assertTrue(Path(selected["config_path"]).is_file())
                self.assertTrue(application.skills.list())
                self.assertFalse((Path(directory) / "tools").exists())
            finally:
                application.close()
            application = CoreApplication(directory, route_sources=[])
            try:
                self.assertTrue(application._rpc("skill.builtin.list", {"assistant_id": "sumika"})["skills"][-1]["enabled"])
            finally:
                application.close()
