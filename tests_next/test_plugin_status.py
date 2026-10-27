import json
import tempfile
import unittest
from pathlib import Path

from sumika_next.plugins import profile_plugins


class ProfilePluginStatusTests(unittest.TestCase):
    def test_reports_installed_and_active_without_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            profile = home / "profiles" / "web"
            package = profile / "node_modules" / "dsh-a" / "package.json"
            package.parent.mkdir(parents=True)
            package.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (profile / "package.json").write_text(json.dumps({
                "dependencies": {"dsh-a": "^1.0.0", "dsh-b": "file:D:/local/b"},
                "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "dsh-a"]}},
            }), encoding="utf-8")
            status = profile_plugins(home)
            self.assertTrue(status["available"])
            self.assertEqual(status["count"], 2)
            self.assertEqual(status["active_count"], 1)
            by_name = {item["name"]: item for item in status["installed"]}
            self.assertEqual(by_name["dsh-a"]["version"], "1.2.3")
            self.assertTrue(by_name["dsh-a"]["active"])
            self.assertIsNone(by_name["dsh-b"]["version"])
            self.assertNotIn("path", json.dumps(status).casefold())

    def test_missing_or_malformed_profile_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.assertFalse(profile_plugins(home)["available"])
            profile = home / "profiles" / "web"
            profile.mkdir(parents=True)
            (profile / "package.json").write_text("not json", encoding="utf-8")
            self.assertFalse(profile_plugins(home)["available"])
            self.assertFalse(profile_plugins(None)["available"])
