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

    def test_managed_relocation_preserves_disabled_and_existing_scope(self):
        install(self.home, enabled=False, work_presets=['custom-work'], **self.options)
        rows=json.loads(self.path.read_bytes())
        entry=rows[-1]['insert'][0]
        entry['config']['root']='D:/previous-product'
        self.path.write_text(json.dumps(rows),encoding='utf8')
        install(self.home, root=Path.cwd(), python=sys.executable,
                registry=self.home/'moved/private.json', registered_workspaces=True, managed=True)
        entry=json.loads(self.path.read_bytes())[-1]['insert'][0]
        self.assertFalse(entry['config']['enabled'])
        self.assertEqual(entry['config']['workPresets'],['custom-work'])
        self.assertEqual(entry['config']['projects'],[str(Path.cwd().resolve())])
        self.assertNotIn('registeredWorkspaces',entry['config'])
        self.assertEqual(entry['config']['root'],str(Path.cwd().resolve()))
        self.assertEqual(entry['config']['registry'],str(self.home/'moved/private.json'))

    def test_fresh_managed_profile_uses_native_scope_and_packaged_runner(self):
        options={k:v for k,v in self.options.items() if k!='projects'}
        install(self.home, registered_workspaces=True, managed=True, **options)
        config=json.loads(self.path.read_bytes())[-1]['insert'][0]['config']
        self.assertTrue(config['registeredWorkspaces'])
        self.assertEqual(config['projects'],[])
        self.assertEqual(config['workPresets'],['standard'])
        self.assertEqual(config['runner'],str(Path.cwd()/'tools/run_module.py'))
        self.assertFalse((self.home/'private.json').exists())
        self.assertFalse(install(self.home, registered_workspaces=True, managed=True, **options)['changed'])

    def test_managed_install_preserves_native_disabled_and_override_rows(self):
        install(self.home, **self.options)
        rows=json.loads(self.path.read_bytes())
        rows[-1]['insert'][0]['disabled']=True
        self.path.write_text(json.dumps(rows),encoding='utf8')
        options={k:v for k,v in self.options.items() if k!='projects'}
        install(self.home, registered_workspaces=True, managed=True, **options)
        self.assertTrue(json.loads(self.path.read_bytes())[-1]['insert'][0]['disabled'])
        rows=json.loads(self.path.read_bytes())
        rows.append({'id':'sumika-web-review','disabled':True})
        original=json.dumps(rows).encode()
        self.path.write_bytes(original)
        result=install(self.home, registered_workspaces=True, managed=True, **options)
        self.assertFalse(result['changed'])
        self.assertEqual(self.path.read_bytes(),original)

    def test_replace_failure_preserves_original_and_removes_temp(self):
        with patch('extensions.desktop.review_install.os.replace', side_effect=OSError('fixture')):
            with self.assertRaises(OSError): install(self.home, **self.options)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.home.glob('review-patch-*.tmp')), [])
        backup = next((self.home/'backups').iterdir())
        self.assertEqual(backup.read_bytes(), self.original)

    def test_transient_windows_replace_failure_retries_without_corrupting_profile(self):
        error = PermissionError('transient sharing lock')
        error.winerror = 5
        with patch('extensions.desktop.review_install.os.replace', side_effect=[error, None]) as replace, \
                patch('extensions.desktop.review_install.time.sleep') as sleep:
            result = install(self.home, **self.options)
        self.assertTrue(result['changed'])
        self.assertEqual(replace.call_count, 2)
        sleep.assert_called_once_with(0.02)
        self.assertEqual(json.loads(self.path.read_bytes())[0], json.loads(self.original)[0])
        self.assertFalse(list(self.home.glob('review-patch-*.tmp')))

    def test_permanent_windows_replace_failure_keeps_original_and_retries_boundlessly_only(self):
        error = PermissionError('permanent sharing lock')
        error.winerror = 5
        with patch('extensions.desktop.review_install.os.replace', side_effect=error) as replace, \
                patch('extensions.desktop.review_install.time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                install(self.home, **self.options)
        self.assertEqual(replace.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.home.glob('review-patch-*.tmp')))

    def test_non_retryable_windows_replace_failure_is_not_retried(self):
        error = OSError('disk failure')
        error.winerror = 87
        with patch('extensions.desktop.review_install.os.replace', side_effect=error) as replace, \
                patch('extensions.desktop.review_install.time.sleep') as sleep:
            with self.assertRaises(OSError):
                install(self.home, **self.options)
        replace.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.home.glob('review-patch-*.tmp')))

    def test_ambiguous_or_invalid_patch_not_modified(self):
        for data in ({}, [{'id':'sumika-web-review'}],
                     [{'insert':[{'id':'sumika-web-review'}, {'id':'sumika-web-review'}]}]):
            raw=json.dumps(data).encode()
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError): install(self.home, **self.options)
            self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse((self.home/'backups').exists())
