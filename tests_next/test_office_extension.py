"""Portable installer and execution boundary checks; no office dependencies needed."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'extensions/office'
spec = importlib.util.spec_from_file_location('office_install', BASE/'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class OfficeExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sumika-office-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.skill = installer.install(self.work, sys.executable)
        self.config = self.skill/'runtime.json'
        self.script = self.work/'task with spaces.py'
        self.script.write_text('import sys,json\nfrom pathlib import Path\n'
                               'Path("result.json").write_text(json.dumps(sys.argv[1:]))\n', encoding='utf-8')

    def call(self, *args):
        return subprocess.run([sys.executable, '-B', str(self.skill/'scripts/run.py'), *args],
                              cwd=self.work, capture_output=True, text=True, encoding='utf-8')

    def settings(self, **changes):
        config = json.loads(self.config.read_text(encoding='utf-8'))
        config.update(changes)
        self.config.write_text(json.dumps(config), encoding='utf-8')

    def test_arguments_are_literal_and_cwd_is_preserved(self):
        values = ['中文', 'a b', '$(write-host bad);`literal`', '--flag']
        result = self.call('exec', str(self.script), *values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.work/'result.json').read_text()), values)

    def test_disabled_prevents_work_and_reinstall_keeps_disabled(self):
        self.settings(enabled=False)
        installer.install(self.work, sys.executable)
        self.assertEqual(self.call('exec', str(self.script)).returncode, 2)
        self.assertFalse((self.work/'result.json').exists())
        status = self.call('status')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)['enabled'], False)

    def test_unknown_state_never_executes(self):
        for changes in ({'enabled': 'false'}, {'enabled': None},
                        {'enabled': True, 'provider': 'unknown'}):
            with self.subTest(changes=changes):
                self.settings(**changes)
                self.assertEqual(self.call('exec', str(self.script)).returncode, 2)
                self.assertFalse((self.work/'result.json').exists())

    def test_failure_exit_is_not_reported_as_success(self):
        self.script.write_text('raise SystemExit(7)\n')
        self.assertEqual(self.call('exec', str(self.script)).returncode, 7)

    def test_modified_skill_is_preserved(self):
        skill = self.skill/'SKILL.md'
        skill.write_text('user local changes\n', encoding='utf-8')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, 'differs'):
            installer.install(self.work, sys.executable)
        self.assertEqual(skill.read_text(), 'user local changes\n')
        self.assertEqual(self.config.read_bytes(), before)

    def test_missing_environment_fails_before_execution(self):
        self.settings(python=str(self.work/'missing.exe'))
        self.assertEqual(self.call('exec', str(self.script)).returncode, 2)
        self.assertFalse((self.work/'result.json').exists())

    def test_malformed_config_fails_without_running_or_traceback(self):
        for value in ([], {'enabled': True}, 'not a config'):
            with self.subTest(value=value):
                self.config.write_text(json.dumps(value), encoding='utf-8')
                result = self.call('exec', str(self.script))
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse((self.work/'result.json').exists())


if __name__ == '__main__':
    unittest.main()
