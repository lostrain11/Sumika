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
        self.assertEqual([p['id'] for p in data['plan']['phases']],
                         ['P0', 'P1', 'P2', 'P3', 'P4', 'P4-UI', 'P5', 'P6', 'P7'])

    def test_missing_or_misplaced_ui_stage_fails(self):
        self.change('plan', lambda x: x['phases'].insert(6, x['phases'].pop(5)))
        with self.assertRaises(ValueError): validate(self.root)
        self.change('plan', lambda x: x.update(phases=[p for p in x['phases'] if p['id'] != 'P4-UI']))
        with self.assertRaises(ValueError): validate(self.root)

    def test_legacy_eight_stage_plan_remains_readable(self):
        self.change('plan', lambda x: x.update(plan_version=2,
                    phases=[p for p in x['phases'] if p['id'] != 'P4-UI']))
        for name in ['handoff', 'progress']:
            self.change(name, lambda x: x.update(current_phase='P5'))
        validate(self.root)

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
