"""Release gate tests; all synthetic artifacts are retained under D: runtime data."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.verify_portable_staging import REQUIRED, verify, safe_path
from tools.build_portable_staging import browser_runtime_files, verify_reviewed_assets, physical_files, reference_registry_asset, executable_asset


class PortableInventoryTests(unittest.TestCase):
    def test_launcher_requires_real_pe_header_not_renamed_script(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'Sumika.exe'
            for contents in (b'param()\n', b'MZ'+bytes(62), b'MZ'+bytes(58)+(64).to_bytes(4,'little')+b'noPE'):
                path.write_bytes(contents)
                with self.assertRaises(ValueError):
                    executable_asset(path)
            path.write_bytes(b'MZ'+bytes(58)+(64).to_bytes(4,'little')+b'PE\x00\x00')
            self.assertEqual(executable_asset(path),path.resolve())

    def test_runtime_cache_excluded_but_dependencies_and_secrets_preserved_for_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('Lib/__pycache__/cached.pyc', 'Lib/loose.PYC',
                         'node_modules/pkg/index.js', 'Lib/site-packages/engine.pyd',
                         'private.key'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            selected = {relative.as_posix() for _, relative in physical_files(root)}
            self.assertEqual(selected, {'node_modules/pkg/index.js',
                                        'Lib/site-packages/engine.pyd', 'private.key'})
            with self.assertRaises(ValueError):
                safe_path('runtime/desktop/private.key')

    def test_reference_registry_relocates_as_exact_product_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'docs/project/reference-projects.json'
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({'schema_version':1,'projects':[{'id':'demo'}]}))
            selected,relative=reference_registry_asset(root)
            self.assertEqual(selected,source)
            self.assertEqual(safe_path(relative.as_posix()),'extensions/desktop/reference-projects.json')
            source.write_text('{}')
            with self.assertRaises(ValueError): reference_registry_asset(root)
    def test_certifi_public_bundle_is_only_pem_exception(self):
        for runtime in ('python', 'desktop', 'voice'):
            name = f'runtime/{runtime}/Lib/site-packages/certifi/cacert.pem'
            self.assertEqual(safe_path(name), name)
        for invalid in ('ui/cacert.pem', 'runtime/python/Lib/site-packages/certifi/private.key',
                        'runtime/python/Lib/site-packages/certifi/other.pem',
                        'runtime/python/Lib/site-packages/other/cacert.pem',
                        'runtime/voice/Lib/site-packages/certifi/private.pem',
                        'runtime/other/Lib/site-packages/certifi/cacert.pem'):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                safe_path(invalid)
    def test_current_ui_icons_and_notices_are_selected_for_distribution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('icon.svg', 'license.txt', 'tokens.css', 'secret.pyc'):
                (root / name).write_text('fixture')
            selected = {relative.name for _, relative in physical_files(root, product=True)}
            self.assertEqual(selected, {'icon.svg', 'license.txt', 'tokens.css'})

    def test_windows_device_and_invalid_component_names(self):
        for name in ('CON', 'con.txt', 'CON .txt', 'AUX.json', 'NUL', 'COM1.txt',
                     'LPT9.txt', 'COM\u00b9.txt', 'LPT\u00b2.txt', 'CONIN$', 'CONOUT$.txt',
                     'a?b', 'a*b', 'a<b', 'a>b', 'a|b', 'a"b', 'a\x01b', 'a\x7fb'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_path('ui/'+name)
        for name in ('context.js', 'auxiliary.py', 'COM10.txt', '中文.png'):
            self.assertEqual(safe_path('ui/'+name), 'ui/'+name)

    def setUp(self):
        base = Path('.sumika-next/portable-inventory-tests')
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=base))
        self.manifest = {'kind': 'portable-staging', 'schema_version': 2, 'files': []}
        for name in REQUIRED:
            self.add(name)

    def add(self, name, content=b'fixture'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.manifest['files'].append({'path': name, 'size': len(content),
                                      'sha256': hashlib.sha256(content).hexdigest()})

    def check(self):
        (self.root/'package-manifest.json').write_text(json.dumps(self.manifest), encoding='utf8')
        return verify(self.root)

    def test_integrity_does_not_claim_product_acceptance(self):
        self.assertEqual(self.check()['status'], 'inventory_verified')

    @unittest.skipUnless(os.name == 'nt', 'Windows extended paths')
    def test_deep_files_verified_without_machine_long_path_policy(self):
        name = 'ui/' + '/'.join(['deep-directory-' + str(i) for i in range(20)]) + '/asset.txt'
        target = Path('\\\\?\\' + str(self.root.absolute())) / name
        target.parent.mkdir(parents=True)
        target.write_bytes(b'deep fixture')
        self.manifest['files'].append({'path': name, 'size': 12,
                                      'sha256': hashlib.sha256(b'deep fixture').hexdigest()})
        original_walk = os.walk
        def legacy_walk(root, **kwargs):
            if not str(root).startswith('\\\\?\\'):
                raise OSError('legacy MAX_PATH')
            return original_walk(root, **kwargs)
        with patch('tools.verify_portable_staging.os.walk', side_effect=legacy_walk):
            self.assertEqual(self.check()['files'], len(REQUIRED) + 1)
            target.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                self.check()

    def test_tampered_file_rejected(self):
        (self.root/'Sumika.exe').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            self.check()

    def test_extra_file_rejected(self):
        (self.root/'ui/extra.py').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'differ from inventory'):
            self.check()

    def test_runtime_data_rejected_even_when_declared(self):
        self.add('runtime/dsh/.sumika-next/private.json')
        with self.assertRaisesRegex(ValueError, 'runtime data'):
            self.check()

    def test_credentials_rejected_even_when_declared(self):
        self.add('runtime/dsh/.env.local')
        with self.assertRaisesRegex(ValueError, 'credential'):
            self.check()

    def test_case_alias_and_traversal_rejected(self):
        self.manifest['files'].append({**self.manifest['files'][0], 'path': 'sumika.exe'})
        with self.assertRaises(ValueError):
            self.check()
        self.manifest['files'][-1]['path'] = 'ui/../outside'
        with self.assertRaisesRegex(ValueError, 'invalid inventory path'):
            self.check()

    def test_legacy_smoke_claim_is_not_evidence(self):
        self.manifest = {'kind': 'portable-staging', 'status': 'smoke-tested',
                         'model_policy': 'No model weights or credentials bundled'}
        with self.assertRaisesRegex(ValueError, 'version 2'):
            self.check()

    def test_browser_update_residue_never_selected_and_remains_on_disk(self):
        browser = self.root/'browser'
        browser.mkdir()
        for name in ('bsk.exe', 'LICENSE', 'bsk.exe.update-1', 'bsk.exe.update-1.cmd'):
            (browser/name).write_bytes(b'fixture')
        self.assertEqual({str(rel) for _, rel in browser_runtime_files(browser)}, {'bsk.exe', 'LICENSE'})
        self.assertTrue((browser/'bsk.exe.update-1').exists())

    def test_declared_update_residue_rejected(self):
        self.add('runtime/browserskill/bsk.exe.update-1.cmd')
        with self.assertRaises(ValueError):
            self.check()

    def test_changed_reviewed_binary_rejected(self):
        notices = self.root/'packaging/notices'
        notices.mkdir(parents=True)
        (notices/'sources.json').write_text('{"sources":[]}')
        (self.root/'packaging/reviewed-assets.json').write_text(json.dumps({
            'schema_version': 1, 'files': {'Sumika.exe': hashlib.sha256(b'fixture').hexdigest()}}))
        verify_reviewed_assets(self.root)
        (self.root/'Sumika.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'reviewed asset changed'):
            verify_reviewed_assets(self.root)


if __name__ == '__main__':
    unittest.main()
