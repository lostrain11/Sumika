"""Immutable acceptance suite for the isolated restore-preflight development task.

Run from the repository or beside the two candidate modules. The isolated runner
must supply the real ui.data_lease dependency through PYTHONPATH; no lock mocks.
Fixtures are retained as evidence and contain no personal data.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid


HERE = Path(__file__).resolve().parent
MODULES = HERE if (HERE / 'backup_personal_data.py').is_file() else HERE.parent
sys.path.insert(0, str(MODULES))
backup_module = importlib.import_module('backup_personal_data')
preflight = importlib.import_module('restore_preflight')


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob('*') if p.is_file()}


class RestorePreflightAcceptance(unittest.TestCase):
    def setUp(self):
        base = Path.cwd() / '.sumika-next' / 'restore-preflight-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / uuid.uuid4().hex
        self.root.mkdir()
        self.source = self.root / 'original-personal'
        self.snapshot = self.root / 'snapshot'
        self.payload = self.snapshot / 'data'
        self.payload.mkdir(parents=True)

    def fixture(self, settings=None, journal=None):
        if settings is not None:
            (self.payload / 'role-model-settings.json').write_text(
                settings if isinstance(settings, str) else json.dumps(settings), encoding='utf8')
        if journal is not None:
            (self.payload / 'role-restore-state.json').write_text(
                journal if isinstance(journal, str) else json.dumps(journal), encoding='utf8')
        files = {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                 for name, data in tree_bytes(self.payload).items()}
        manifest = dict(schema_version=1, kind='sumika-private-offline-snapshot',
                        status='verified', source=str(self.source), files=files)
        (self.snapshot / 'snapshot.json').write_text(json.dumps(manifest), encoding='utf8')
        return manifest

    def inspect_unchanged(self):
        before = tree_bytes(self.root)
        directories = {str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_dir()}
        result = preflight.inspect_snapshot(self.snapshot)
        self.assertEqual(tree_bytes(self.root), before)
        self.assertEqual({str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_dir()}, directories)
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['integrity'], 'verified')
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn('private-fixture-key', rendered)
        self.assertNotIn('role-model-settings', rendered)
        return result

    def deps(self, result):
        dependencies = result['dependencies']
        self.assertEqual(len(dependencies), 2)
        self.assertEqual({d['field'] for d in dependencies}, {'role.role_dir', 'role.database'})
        return {d['field']: d for d in dependencies}

    def test_unconfigured_first_start_ready_and_pure(self):
        self.fixture()
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['dependencies'], [])

    def test_internal_paths_resolve_only_inside_snapshot(self):
        (self.payload / 'roles' / 'person').mkdir(parents=True)
        (self.payload / 'roles' / 'person' / 'card.json').write_text('{}')
        (self.payload / 'memory.sqlite3').write_bytes(b'opaque-existing-database')
        self.fixture({'role': {'role_dir': str(self.source / 'roles' / 'person'),
                              'database': str(self.source / 'memory.sqlite3')},
                      'api_key': 'private-fixture-key'})
        self.assertFalse(self.source.exists())
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'ready')
        for dep in self.deps(result).values():
            self.assertEqual((dep['scope'], dep['availability']), ('internal', 'present'))

    def test_external_presence_and_missing_database_without_creation(self):
        external = self.root / 'external-role'
        external.mkdir()
        database = self.root / 'external-memory.sqlite3'
        self.fixture({'role': {'role_dir': str(external), 'database': str(database)}})
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'needs_attention')
        deps = self.deps(result)
        self.assertEqual((deps['role.role_dir']['scope'], deps['role.role_dir']['availability']),
                         ('external', 'present'))
        self.assertEqual((deps['role.database']['scope'], deps['role.database']['availability']),
                         ('external', 'missing'))
        self.assertFalse(database.exists())

    def test_internal_missing_not_replaced_by_original_resource(self):
        self.source.mkdir()
        (self.source / 'person').mkdir()
        (self.source / 'memory.sqlite3').write_bytes(b'original-must-not-be-used')
        self.fixture({'role': {'role_dir': str(self.source / 'person'),
                              'database': str(self.source / 'memory.sqlite3')}})
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'needs_attention')
        for dep in self.deps(result).values():
            self.assertEqual((dep['scope'], dep['availability']), ('internal', 'missing'))

    def test_resource_kind_mismatch_is_missing(self):
        (self.payload / 'person').write_text('not-a-directory')
        (self.payload / 'memory.sqlite3').mkdir()
        self.fixture({'role': {'role_dir': str(self.source / 'person'),
                              'database': str(self.source / 'memory.sqlite3')}})
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'needs_attention')
        self.assertTrue(all(d['availability'] == 'missing' for d in self.deps(result).values()))

    def test_relative_and_unc_are_unknown_without_network_probe(self):
        self.fixture({'role': {'role_dir': 'relative/person',
                              'database': r'\\sumika-never-contact.invalid\share\memory.sqlite3'}})
        real_stat = os.stat
        def guarded_stat(path, *args, **kwargs):
            value = os.fspath(path) if isinstance(path, (str, bytes, os.PathLike)) else ''
            if isinstance(value, str) and 'sumika-never-contact.invalid' in value:
                raise AssertionError('preflight probed a network dependency')
            return real_stat(path, *args, **kwargs)
        with patch('os.stat', side_effect=guarded_stat):
            result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'unknown')
        for dep in self.deps(result).values():
            self.assertEqual((dep['scope'], dep['availability']), ('unknown', 'unknown'))

    def test_malformed_settings_are_unknown_not_leaked(self):
        self.fixture('{"private-fixture-key":')
        self.assertEqual(self.inspect_unchanged()['status'], 'unknown')

    def test_pending_role_rebind_requires_attention(self):
        self.fixture(journal={'schema_version': 1, 'status': 'pending'})
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'needs_attention')
        self.assertIn('role_rebind_pending', result['issues'])

    def test_invalid_role_rebind_state_unknown(self):
        self.fixture(journal='{broken')
        result = self.inspect_unchanged()
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('role_rebind_state_invalid', result['issues'])

    def test_shared_verification_used_by_inspection_and_restore(self):
        expected = self.fixture()
        self.assertEqual(backup_module.verify_snapshot(self.snapshot), expected)
        with patch.object(backup_module, 'verify_snapshot', side_effect=ValueError('verification-sentinel')):
            with self.assertRaises(ValueError):
                backup_module.restore(self.snapshot, self.root / 'never-created')
        self.assertFalse((self.root / 'never-created').exists())

    def test_tampering_rejected_without_mutation(self):
        self.fixture({'role': {}})
        (self.payload / 'role-model-settings.json').write_text('tampered')
        before = tree_bytes(self.root)
        for operation in (backup_module.verify_snapshot, preflight.inspect_snapshot):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(self.snapshot)
        with self.assertRaises(ValueError):
            backup_module.restore(self.snapshot, self.root / 'never-created')
        self.assertEqual(tree_bytes(self.root), before)
        self.assertFalse((self.root / 'never-created').exists())

    def test_invalid_manifest_rejected(self):
        self.fixture()
        (self.snapshot / 'snapshot.json').write_text('{"schema_version":999}')
        before = tree_bytes(self.root)
        for operation in (backup_module.verify_snapshot, preflight.inspect_snapshot):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(self.snapshot)
        self.assertEqual(tree_bytes(self.root), before)

    def test_cli_inspect_no_destination_and_incompatible_flags(self):
        self.fixture()
        command = [sys.executable, '-B', str(MODULES / 'backup_personal_data.py'),
                   '--inspect', '--source', str(self.snapshot)]
        before = tree_bytes(self.root)
        result = subprocess.run(command, capture_output=True, encoding='utf8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'ready')
        for flag in ('--restore', '--rebind-role-paths', '--resume-role-rebind'):
            result = subprocess.run(command + [flag], capture_output=True, encoding='utf8', timeout=30)
            self.assertNotEqual(result.returncode, 0, flag)
        self.assertEqual(tree_bytes(self.root), before)


if __name__ == '__main__':
    unittest.main()
