"""Additional host review cases beyond the immutable development acceptance."""
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from tools.development_tasks import restore_preflight_tests as acceptance
from tools import restore_preflight


class RestorePreflightBoundaries(acceptance.RestorePreflightAcceptance):
    def test_windows_internal_names_preserve_filesystem_case_semantics(self):
        if sys.platform != 'win32':
            self.skipTest('Windows case-insensitive path semantics')
        (self.payload/'Role').mkdir()
        (self.payload/'Role/card.json').write_text('{}')
        (self.payload/'Memory.db').write_bytes(b'db')
        self.fixture({'role':{'role_dir':str(self.source/'role'),'database':str(self.source/'memory.DB')}})
        self.assertEqual(restore_preflight.inspect_snapshot(self.snapshot)['status'],'ready')

    def test_empty_role_directory_is_not_recoverable_in_v1(self):
        (self.payload/'empty-role').mkdir()
        (self.payload/'db').write_bytes(b'db')
        self.fixture({'role':{'role_dir':str(self.source/'empty-role'),'database':str(self.source/'db')}})
        result=restore_preflight.inspect_snapshot(self.snapshot)
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(self.deps(result)['role.role_dir']['availability'],'missing')

    def test_excluded_lock_is_not_a_recoverable_database(self):
        self.fixture({'role':{'role_dir':str(self.source),'database':str(self.source/'sumika-bridge.lock')}})
        (self.payload/'sumika-bridge.lock').write_bytes(b'not-a-backed-up-file')
        result=restore_preflight.inspect_snapshot(self.snapshot)
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(self.deps(result)['role.database']['availability'],'missing')

    def test_source_shape_and_network_names_are_unknown(self):
        for source in (None, 7, '', 'relative', r'\\server\share', r'\\?\UNC\server\share'):
            self.fixture({'role': {'role_dir': str(self.root), 'database': str(self.root/'db')}})
            manifest_path=self.snapshot/'snapshot.json'
            manifest=json.loads(manifest_path.read_text())
            manifest['source']=source
            manifest_path.write_text(json.dumps(manifest))
            result=restore_preflight.inspect_snapshot(self.snapshot)
            self.assertEqual(result['status'],'unknown')
            self.assertTrue(all(d['scope']=='unknown' for d in result['dependencies']))

    def test_device_and_network_variants_never_reach_presence(self):
        for value in (r'\\?\C:\data', r'\\.\pipe\thing', '//server/share/data', r'\\server\share\data'):
            self.fixture({'role': {'role_dir': value, 'database': value}})
            with patch.object(restore_preflight,'presence',side_effect=AssertionError('unsafe path probed')):
                result=restore_preflight.inspect_snapshot(self.snapshot)
            self.assertEqual(result['status'],'unknown')

    def test_inaccessible_is_unknown_not_missing(self):
        with patch.object(Path,'lstat',side_effect=PermissionError('private path')):
            self.assertEqual(restore_preflight.presence(self.root,'directory'),'unknown')

    def test_boolean_schema_is_not_version_one(self):
        manifest=self.fixture()
        manifest['schema_version']=True
        (self.snapshot/'snapshot.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            restore_preflight.inspect_snapshot(self.snapshot)

    def test_malformed_complete_journal_is_not_ready(self):
        for journal in ({'schema_version':True,'status':'complete'}, {'schema_version':1,'status':'complete'}, []):
            self.fixture(journal=journal)
            result=restore_preflight.inspect_snapshot(self.snapshot)
            self.assertEqual(result['status'],'unknown')
            self.assertIn('role_rebind_state_invalid',result['issues'])

    def test_cli_package_mode_and_conflict_with_destination(self):
        self.fixture()
        command=[sys.executable,'-B','-m','tools.backup_personal_data','--inspect','--source',str(self.snapshot)]
        result=subprocess.run(command,capture_output=True,encoding='utf8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'ready')
        destination=self.root/'no-output'
        for mode in ('--restore','--resume-role-rebind','--rebind-role-paths'):
            result=subprocess.run(command+[mode,'--destination',str(destination)],capture_output=True,encoding='utf8',timeout=30)
            self.assertNotEqual(result.returncode,0)
        self.assertFalse(destination.exists())

    def test_cli_corrupt_manifest_reports_no_raw_path_or_content(self):
        self.fixture()
        (self.snapshot/'snapshot.json').write_text('private-fixture-key')
        result=subprocess.run([sys.executable,'-B','-m','tools.backup_personal_data','--inspect','--source',str(self.snapshot)],
                              capture_output=True,encoding='utf8',timeout=30)
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stdout)['issues'],['snapshot_verification_failed'])
        self.assertNotIn('private-fixture-key',result.stdout+result.stderr)
        self.assertNotIn(str(self.root),result.stdout+result.stderr)
