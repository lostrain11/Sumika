import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sumika_core.builtin_skills import BuiltinSkills
from sumika_core.storage import Storage


RESOURCES = Path(__file__).parents[1] / "src/sumika_core/builtin_skills/resources"
SCRIPT = RESOURCES / "tool-registry/scripts/check_paths.py"
SPEC = importlib.util.spec_from_file_location("independent_path_check", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def create_directory_link(link, target):
    if os.name == "nt":
        subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


class SkillPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="Skill 中文 空格 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "paths.json"
        self.configure([], "")

    def configure(self, tools, cache):
        self.config.write_text(json.dumps({"tool_directories": tools, "download_cache_directory": cache}), encoding="utf-8")

    def test_empty_recommendation_has_no_side_effects(self):
        before = self.config.read_bytes()
        for operation, leaf in (("reuse", "tools"), ("cache", "tool-cache")):
            result = CHECKER.check_paths(self.config, operation, str(self.root))
            self.assertEqual(result["status"], "configuration-empty")
            self.assertEqual(result["recommendation"]["path"], str(self.root / leaf))
            self.assertFalse(result["recommendation"]["exists"])
            self.assertEqual(json.loads(result["recommendation"]["copyable_configuration"]), result["recommendation"]["configuration"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.config])

    def test_independent_cli_outside_repository(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        response = subprocess.run([sys.executable, "-I", str(SCRIPT), "--config", str(self.config), "--operation", "reuse"], cwd=self.root, env=env, capture_output=True)
        self.assertEqual(response.returncode, 2)
        self.assertEqual(json.loads(response.stdout)["recommendation_unavailable"], "valid-data-root-not-provided")

    def test_operations_are_independent_and_success_is_short(self):
        self.configure([str(self.root)], "not-an-absolute-path")
        with patch.object(CHECKER.os, "scandir", side_effect=AssertionError("must not scan")):
            self.assertEqual(CHECKER.check_paths(self.config, "reuse"), {"status": "ready", "paths": [str(self.root)]})
        self.configure({"invalid": True}, str(self.root))
        self.assertEqual(CHECKER.check_paths(self.config, "cache"), {"status": "ready", "paths": [str(self.root)]})

    def test_invalid_paths_never_fall_back(self):
        for directory, reason in ((str(self.root / "missing"), "not-found"), (str(self.config), "not-a-directory"), ("relative", "absolute-directory-required"), ("", "empty")):
            self.configure([directory], "")
            result = CHECKER.check_paths(self.config, "reuse", str(self.root))
            self.assertEqual(result["status"], "path-unavailable")
            self.assertEqual(result["errors"][0]["reason"], reason)
            self.assertNotIn("recommendation", result)

    def test_apply_suggestion_using_host_file_operations_then_check(self):
        suggested = CHECKER.check_paths(self.config, "reuse", str(self.root))["recommendation"]
        Path(suggested["path"]).mkdir()
        self.config.write_text(suggested["copyable_configuration"], encoding="utf-8")
        self.assertEqual(CHECKER.check_paths(self.config, "reuse")["status"], "ready")

    def test_conflicting_recommendation_and_invalid_configuration(self):
        (self.root / "tools").write_text("existing file", encoding="utf-8")
        result = CHECKER.check_paths(self.config, "reuse", str(self.root))
        self.assertEqual(result["recommendation_unavailable"], "not-a-directory")
        self.config.write_text("[]", encoding="utf-8")
        self.assertEqual(CHECKER.check_paths(self.config, "reuse")["status"], "configuration-unavailable")

    def test_links_are_rejected_in_configuration_and_directories(self):
        link = self.root / "link"
        try:
            create_directory_link(link, self.root)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        self.configure([str(link)], "")
        self.assertEqual(CHECKER.check_paths(self.config, "reuse")["errors"][0]["reason"], "linked-directory-not-supported")
        self.assertEqual(CHECKER.check_paths(link / "paths.json", "reuse")["status"], "configuration-unavailable")


class BuiltinSkillTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = Storage()
        self.addCleanup(self.storage.close)
        self.resources = self.root / "resources"
        shutil.copytree(RESOURCES, self.resources, ignore=shutil.ignore_patterns("__pycache__"))
        self.library = BuiltinSkills(self.storage, resources=self.resources, install_root=self.root / "installed")

    def enable(self, identifier, enabled=True):
        row = next(row for row in self.library.list("owner")["skills"] if row["id"] == identifier)
        return self.library.set_enabled("owner", identifier, enabled, row["sha256"])

    def test_default_off_independent_and_owner_scoped(self):
        self.assertEqual(len(self.library.list("owner")["skills"]), 3)
        self.assertEqual(self.library.snapshot("owner"), [])
        self.assertFalse((self.root / "installed").exists())
        for identifier in self.library.entries:
            self.enable(identifier)
            self.assertEqual([row["id"] for row in self.library.snapshot("owner")], [identifier])
            self.assertEqual(self.library.snapshot("other"), [])
            self.enable(identifier, False)
        with self.assertRaisesRegex(ValueError, "not enabled"):
            self.library.helper("owner", [], "tool-registry", "check_paths", "reuse")

    def test_task_snapshot_is_frozen_and_helper_never_executes_local_edits(self):
        self.enable("tool-registry")
        snapshot = self.library.snapshot("owner")
        local = Path(snapshot[0]["directory"])
        (local / "scripts/check_paths.py").write_text("raise SystemExit(99)", encoding="utf-8")
        self.enable("tool-registry", False)
        result = self.library.helper("owner", snapshot, "tool-registry", "check_paths", "reuse", data_root=self.root)
        self.assertEqual(result["status"], "configuration-empty")
        self.assertEqual(self.library.snapshot("owner"), [])

    def test_upgrade_preserves_configuration_and_old_task(self):
        self.enable("tool-registry")
        snapshot = self.library.snapshot("owner")
        config = Path(snapshot[0]["directory"]) / "config/paths.json"
        personal = json.dumps({"tool_directories": [str(self.root)], "download_cache_directory": ""})
        config.write_text(personal, encoding="utf-8")
        document = self.resources / "tool-registry/SKILL.md"
        document.write_text(document.read_text(encoding="utf-8") + "\nNew version.\n", encoding="utf-8")
        self.assertEqual(self.library.snapshot("owner"), [])
        self.assertTrue(self.library.list("owner")["skills"][-1]["update_available"])
        self.assertEqual(self.library.helper("owner", snapshot, "tool-registry", "check_paths", "reuse")["status"], "ready")
        self.enable("tool-registry")
        self.assertEqual(config.read_text(encoding="utf-8"), personal)
        self.assertIn("New version.", (config.parents[1] / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((self.resources / "tool-registry/config/paths.json").read_text()), {"tool_directories": [], "download_cache_directory": ""})

    def test_stale_enable_and_linked_installation_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            self.library.set_enabled("owner", "project-progress", True, "old")
        installed = self.root / "installed"
        try:
            create_directory_link(installed, self.resources)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        with self.assertRaisesRegex(ValueError, "linked"):
            self.enable("project-progress")
