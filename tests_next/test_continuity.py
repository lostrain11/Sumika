import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from sumika_next.continuity import validate, handoff

try:
    from tests_next.scratch import ScratchDirectory
except ImportError:  # ``unittest discover -s tests_next`` imports modules top-level
    from scratch import ScratchDirectory

ROOT = Path(__file__).resolve().parents[1]


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = ScratchDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "docs/project", self.root / "docs/project")

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, name, edit):
        path = self.root / "docs/project" / (name + ".json")
        data = json.loads(path.read_text(encoding="utf-8"))
        edit(data)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_only_project_records_reconstruct_handoff(self):
        result = handoff(self.root)
        data = validate(self.root)
        self.assertIn(data["plan"]["goal"], result)
        self.assertIn(data["handoff"]["next_action"], result)
        for item in data["requirements"]["entries"]:
            self.assertIn(item["original"], result)
        self.assertEqual(len(data["plan"]["phases"]), 8)

    def test_empty_originals_fail(self):
        self.change("requirements", lambda x: x.update(entries=[]))
        with self.assertRaises(ValueError): validate(self.root)

    def test_original_tamper_fails(self):
        self.change("requirements", lambda x: x["entries"][0].update(original="rewritten"))
        with self.assertRaises(ValueError): validate(self.root)

    def test_missing_phase_fails(self):
        self.change("plan", lambda x: x["phases"].pop())
        with self.assertRaises(ValueError): validate(self.root)

    def test_stale_handoff_fails(self):
        self.change("handoff", lambda x: x.update(current_phase="wrong"))
        with self.assertRaises(ValueError): validate(self.root)

    def test_unsupported_completion_fails(self):
        self.change("plan", lambda x: x["phases"][0].update(status="complete", evidence=[]))
        with self.assertRaises(ValueError): validate(self.root)
