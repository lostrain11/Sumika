"""Tests for tools/build_native_source_materials.py using tiny synthetic fixtures.

Fixtures live under <project>/.sumika-next/source-material-tests/<uuid4.hex> and are retained (never
deleted). ROOT is mocked by passing a private fixture root containing
packaging/notices; no real downloads or evidence files are used.
"""
import hashlib
import json
import sys
import uuid
import zipfile
from pathlib import Path
import unittest
import unittest.mock as mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / 'tools'
sys.path.insert(0, str(TOOLS_DIR))

import build_native_source_materials as bnsm


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, content):
    if isinstance(content, str):
        content = content.encode('utf8')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class NativeSourceMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.base = PROJECT_ROOT / '.sumika-next' / 'source-material-tests' / uuid.uuid4().hex
        self.root = self.base / 'root'
        self.notices = self.root / 'packaging' / 'notices'
        self.notices.mkdir(parents=True, exist_ok=True)
        self.evidence = self.base / 'evidence'
        # Synthetic inputs: 2 native, 1 rust, 1 recipe, 1 notice (+3 ledgers as notices).
        self.native = [('alpha', b'alpha-source'), ('beta', b'beta-source')]
        self.rust = [('crate-a', '1.0.0', b'crate-a-bytes')]
        self.recipes = [('recipe.tar.gz', b'recipe-bytes')]
        self.notice_files = [('NOTICE.txt', 'synthetic notice\n')]

    # ---- fixture helpers ----

    def _native_ledger(self, components):
        return {'schema_version': 1, 'status': 'x',
                'archives': [{'component': c, 'sha256': _sha256(content)} for c, content in components]}

    def _rust_ledger(self, packages):
        return {'schema_version': 1, 'status': 'x',
                'packages': [{'name': n, 'version': v, 'sha256': _sha256(content)}
                             for n, v, content in packages]}

    def _recipes_ledger(self, archives):
        return {'schema_version': 1, 'status': 'x',
                'archives': [{'file': f, 'sha256': _sha256(content)} for f, content in archives]}

    def _write_ledgers(self, native_data=None, rust_data=None, recipes_data=None):
        _write(self.notices / 'native-source-materials.json',
               json.dumps(self._native_ledger(self.native) if native_data is None else native_data, indent=2))
        _write(self.notices / 'native-rust-source-materials.json',
               json.dumps(self._rust_ledger(self.rust) if rust_data is None else rust_data, indent=2))
        _write(self.notices / 'native-patch-materials.json',
               json.dumps(self._recipes_ledger(self.recipes) if recipes_data is None else recipes_data, indent=2))
        for name, content in self.notice_files:
            _write(self.notices / name, content)

    def _write_all_sources(self):
        for component, content in self.native:
            _write(self.evidence / 'component-sources' / (component + '.source'), content)
        for name, version, content in self.rust:
            _write(self.evidence / 'rsvg-crates' / (name + '-' + version + '.crate'), content)
        for file_name, content in self.recipes:
            _write(self.evidence / file_name, content)

    def _build_full_fixture(self):
        self._write_all_sources()
        self._write_ledgers()

    def _expected_notice_count(self):
        return len([p for p in self.notices.iterdir() if p.is_file()])

    def _dest(self):
        return self.base / 'out' / 'materials.zip'

    # ---- tests ----

    def test_success(self):
        self._build_full_fixture()
        destination = self._dest()
        report = bnsm.build(self.evidence, destination, root=self.root)
        self.assertTrue(report['passed'])
        self.assertEqual(report['status'], 'internal_material_bundle_verified_not_release_clearance')
        expected = 2 + 1 + 1 + self._expected_notice_count()
        self.assertEqual(report['verified_entries'], expected)
        with zipfile.ZipFile(destination) as archive:
            names = sorted(archive.namelist())
        for wanted in ('sources/alpha.source', 'sources/beta.source', 'rust/crate-a-1.0.0.crate',
                       'recipes/recipe.tar.gz', 'notices/NOTICE.txt', 'materials-manifest.json'):
            self.assertIn(wanted, names)
        manifest = json.loads(zipfile.ZipFile(destination).read('materials-manifest.json'))
        self.assertEqual(len(manifest['files']), expected)
        sidecar = json.loads(destination.with_suffix('.report.json').read_text())
        self.assertTrue(sidecar['passed'])

    def test_invalid_metadata_shape(self):
        self._build_full_fixture()
        self._write_ledgers(native_data={'schema_version': 1, 'archives': 'not-a-list'})
        destination = self._dest()
        with self.assertRaises(ValueError):
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_suffix('.report.json').exists())

    def test_invalid_entry_not_object(self):
        self._build_full_fixture()
        self._write_ledgers(native_data={'schema_version': 1, 'archives': ['not-an-object']})
        destination = self._dest()
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertIn('must be a JSON object', str(ctx.exception))
        self.assertFalse(destination.exists())

    def test_invalid_sha256_field(self):
        self._build_full_fixture()
        self._write_ledgers(recipes_data={'schema_version': 1, 'archives': [
            {'file': 'recipe.tar.gz', 'sha256': 'not-a-sha256'}]})
        destination = self._dest()
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertIn('SHA-256 hex digest', str(ctx.exception))
        self.assertFalse(destination.exists())

    def test_unsafe_name(self):
        self._build_full_fixture()
        self._write_ledgers(native_data={'schema_version': 1, 'archives': [
            {'component': '../evil', 'sha256': 'a' * 64}]})
        destination = self._dest()
        with self.assertRaises(ValueError):
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertFalse(destination.exists())

    def test_duplicate_destination(self):
        # Case-insensitive duplicate native destinations, no sources required.
        self._write_ledgers(native_data={'schema_version': 1, 'archives': [
            {'component': 'alpha', 'sha256': 'a' * 64},
            {'component': 'ALPHA', 'sha256': 'b' * 64}]})
        destination = self._dest()
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertIn('duplicate material destination', str(ctx.exception))
        self.assertFalse(destination.exists())

    def test_missing_metadata_ledger(self):
        self._write_all_sources()
        # Native ledger intentionally absent; the other two are written.
        _write(self.notices / 'native-rust-source-materials.json',
               json.dumps(self._rust_ledger(self.rust), indent=2))
        _write(self.notices / 'native-patch-materials.json',
               json.dumps(self._recipes_ledger(self.recipes), indent=2))
        destination = self._dest()
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertIn('metadata ledger load failed', str(ctx.exception))
        self.assertFalse(destination.exists())

    def test_missing_source(self):
        self._write_all_sources()
        # Drop beta source by building a native ledger without beta but keep files.
        self._write_ledgers()
        # Remove beta from disk expectation: delete is forbidden, so point evidence elsewhere.
        empty_evidence = self.base / 'evidence-missing'
        _write(empty_evidence / 'component-sources' / 'alpha.source', b'alpha-source')
        destination = self._dest()
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(empty_evidence, destination, root=self.root)
        self.assertIn('material missing or linked', str(ctx.exception))
        self.assertFalse(destination.exists())

    def test_early_checksum_failure(self):
        self._build_full_fixture()
        wrong = self._native_ledger(self.native)
        wrong['archives'][0]['sha256'] = _sha256(b'tampered-alpha')
        self._write_ledgers(native_data=wrong)
        destination = self._dest()
        with self.assertRaises(ValueError):
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertTrue(destination.exists())
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.namelist(), [])
        sidecar = json.loads(destination.with_suffix('.report.json').read_text())
        self.assertFalse(sidecar['passed'])
        self.assertEqual(sidecar['stage'], 'build-entries')
        self.assertEqual(sidecar['entries'], [])
        self.assertIn('checksum mismatch', sidecar['reason'])

    def test_later_checksum_failure(self):
        self._build_full_fixture()
        wrong = self._rust_ledger(self.rust)
        wrong['packages'][0]['sha256'] = _sha256(b'tampered-crate')
        self._write_ledgers(rust_data=wrong)
        destination = self._dest()
        with self.assertRaises(ValueError):
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertTrue(destination.exists())
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
        self.assertEqual(names, ['sources/alpha.source', 'sources/beta.source'])
        sidecar = json.loads(destination.with_suffix('.report.json').read_text())
        self.assertFalse(sidecar['passed'])
        self.assertEqual(sidecar['stage'], 'build-entries')
        self.assertEqual([e['path'] for e in sidecar['entries']],
                         ['sources/alpha.source', 'sources/beta.source'])

    def test_corrupt_output_verification(self):
        self._build_full_fixture()
        destination = self._dest()
        with mock.patch.object(bnsm, '_verify_bundle',
                               side_effect=ValueError('written material hash mismatch: simulated')):
            with self.assertRaises(ValueError):
                bnsm.build(self.evidence, destination, root=self.root)
        self.assertTrue(destination.exists())
        sidecar = json.loads(destination.with_suffix('.report.json').read_text())
        self.assertFalse(sidecar['passed'])
        self.assertEqual(sidecar['stage'], 'verify-entries')
        self.assertIn('written material hash mismatch', sidecar['reason'])
        self.assertEqual(len(sidecar['entries']), 2 + 1 + 1 + self._expected_notice_count())

    def test_verify_bundle_detects_corruption(self):
        zpath = self.base / 'corrupt.zip'
        with zipfile.ZipFile(zpath, 'w') as archive:
            archive.writestr('materials-manifest.json', '{}')
            archive.writestr('a.txt', b'original-bytes')
        inventory = [{'path': 'a.txt', 'sha256': _sha256(b'tampered-bytes'),
                      'bytes': len(b'original-bytes')}]
        with self.assertRaises(ValueError) as ctx:
            bnsm._verify_bundle(zpath, inventory)
        self.assertIn('written material hash mismatch', str(ctx.exception))

    def test_refuses_existing_destination(self):
        self._build_full_fixture()
        destination = self._dest()
        _write(destination, b'PREVIOUS BUNDLE')
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertIn('output exists', str(ctx.exception))
        self.assertEqual(destination.read_bytes(), b'PREVIOUS BUNDLE')
        self.assertFalse(destination.with_suffix('.report.json').exists())

    def test_refuses_existing_report(self):
        self._build_full_fixture()
        destination = self._dest()
        report_path = destination.with_suffix('.report.json')
        _write(report_path, 'PREVIOUS REPORT\n')
        with self.assertRaises(ValueError) as ctx:
            bnsm.build(self.evidence, destination, root=self.root)
        self.assertIn('report exists', str(ctx.exception))
        self.assertEqual(report_path.read_text(), 'PREVIOUS REPORT\n')
        self.assertFalse(destination.exists())

    def test_competing_report_is_not_overwritten(self):
        self._build_full_fixture()
        destination = self._dest()
        report = destination.with_suffix('.report.json')
        original = bnsm._collect_selected
        def racing(*args):
            result = original(*args)
            _write(report, 'COMPETING REPORT')
            return result
        with mock.patch.object(bnsm, '_collect_selected', side_effect=racing):
            with self.assertRaises(FileExistsError):
                bnsm.build(self.evidence, destination, root=self.root)
        self.assertEqual(report.read_text(), 'COMPETING REPORT')
        self.assertFalse(destination.exists())

    def test_competing_zip_is_not_overwritten(self):
        self._build_full_fixture()
        destination = self._dest()
        original = bnsm._collect_selected
        def racing(*args):
            result = original(*args)
            _write(destination, b'COMPETING ZIP')
            return result
        with mock.patch.object(bnsm, '_collect_selected', side_effect=racing):
            with self.assertRaises(FileExistsError):
                bnsm.build(self.evidence, destination, root=self.root)
        self.assertEqual(destination.read_bytes(), b'COMPETING ZIP')
        report = json.loads(destination.with_suffix('.report.json').read_text())
        self.assertFalse(report['passed'])
        self.assertEqual(report['stage'], 'claim-output')

    def test_reserved_and_control_names_rejected(self):
        for name in ('CON', 'nul.txt', 'bad\x00name', 'bad\nname'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bnsm._require_token(name, 'test token')

    def test_toolchain_materials_included_and_checked(self):
        self._build_full_fixture()
        body = b'synthetic standard library sources'
        ledger = {'archives': [{'component': 'rust', 'version': 'nightly', 'sha256': _sha256(body)}]}
        _write(self.notices / 'native-toolchain-source-materials.json', json.dumps(ledger))
        source = self.evidence / 'toolchain/rust-nightly.source'
        _write(source, body)
        report = bnsm.build(self.evidence, self._dest(), root=self.root)
        self.assertEqual(report['counts']['toolchain_archives'], 1)
        with zipfile.ZipFile(self._dest()) as archive:
            self.assertEqual(archive.read('toolchain/rust-nightly.source'), body)
        _write(source, b'partial or corrupt source')
        dest = self.base / 'bad.zip'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            bnsm.build(self.evidence, dest, root=self.root)
        self.assertFalse(json.loads(dest.with_suffix('.report.json').read_text())['passed'])

    def test_declared_toolchain_source_cannot_be_omitted(self):
        self._build_full_fixture()
        ledger = {'archives': [{'component': 'llvm', 'version': '22', 'sha256': 'a' * 64}]}
        _write(self.notices / 'native-toolchain-source-materials.json', json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, 'material missing'):
            bnsm.build(self.evidence, self._dest(), root=self.root)
        self.assertFalse(self._dest().exists())

    def test_real_ledgers_validate(self):
        real = PROJECT_ROOT / 'packaging' / 'notices'
        native = json.loads((real / 'native-source-materials.json').read_text())
        rust = json.loads((real / 'native-rust-source-materials.json').read_text())
        recipes = json.loads((real / 'native-patch-materials.json').read_text())
        native_items, rust_items, recipe_items = bnsm._validate_ledgers(native, rust, recipes)
        self.assertEqual(len(native_items), 28)
        self.assertEqual(len(recipe_items), 2)
        self.assertEqual(len(rust_items), 346)


if __name__ == '__main__':
    unittest.main()
