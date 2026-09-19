import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.desktop.review_install import install


class ReviewInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='.sumika-next')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.path = self.home / 'cordis.patch.yml'
        self.original = b'[ {"id":"other", "config":{"enabled":false}} ]\r\n'
        self.path.write_bytes(self.original)
        self.options = dict(root=Path.cwd(), python=sys.executable,
                            registry=self.home/'private.json', projects=[Path.cwd()])

    def test_backup_preservation_and_idempotence(self):
        result = install(self.home, **self.options)
        self.assertEqual(Path(result['backup']).read_bytes(), self.original)
        self.assertEqual(json.loads(self.path.read_bytes())[0], json.loads(self.original)[0])
        current = self.path.read_bytes()
        self.assertFalse(install(self.home, **self.options)['changed'])
        self.assertEqual(self.path.read_bytes(), current)
        self.assertEqual(len(list((self.home/'backups').iterdir())), 1)

    def test_toggle_only_changes_review_config(self):
        install(self.home, **self.options)
        before = json.loads(self.path.read_bytes())
        install(self.home, enabled=False, **self.options)
        after = json.loads(self.path.read_bytes())
        self.assertEqual(after[0], before[0])
        self.assertFalse(after[-1]['insert'][0]['config']['enabled'])
        after[-1]['insert'][0]['config']['enabled'] = True
        self.assertEqual(after, before)

    def test_replace_failure_preserves_original_and_removes_temp(self):
        with patch('extensions.desktop.review_install.os.replace', side_effect=OSError('fixture')):
            with self.assertRaises(OSError): install(self.home, **self.options)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.home.glob('review-patch-*.tmp')), [])
        backup = next((self.home/'backups').iterdir())
        self.assertEqual(backup.read_bytes(), self.original)

    def test_ambiguous_or_invalid_patch_not_modified(self):
        for data in ({}, [{'id':'sumika-web-review'}],
                     [{'insert':[{'id':'sumika-web-review'}, {'id':'sumika-web-review'}]}]):
            raw=json.dumps(data).encode()
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError): install(self.home, **self.options)
            self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse((self.home/'backups').exists())
