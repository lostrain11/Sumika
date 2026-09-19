import contextlib
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from tools import verify_native_source_patches as tool


def tar_bytes(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, raw in files.items():
            info = tarfile.TarInfo(name); info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


class NativeSourcePatchTests(unittest.TestCase):
    def fixture(self):
        root = Path(__file__).resolve().parents[1]/'.sumika-next'/'native-patch-tests'/uuid.uuid4().hex
        root.mkdir(parents=True)
        delta = b'--- a/file.c\n+++ b/file.c\n@@ -1 +1 @@\n-old\n+new\n'
        buffers = {
            'mxe-build-scripts.tar.gz': tar_bytes({'build/build/overrides.mk': b'',
                                                  'build/build/patches/second-1-fix.patch': delta}),
            'mxe-d973945-source.tar.gz': tar_bytes({'mxe/src/first.mk': b''}),
        }
        entries = []
        for name, raw in buffers.items():
            (root/name).write_bytes(raw); entries.append({'file': name, 'sha256': tool.sha(raw)})
        binding = root/'bindings.json'
        binding.write_text(json.dumps({'archives': entries}))
        recipes = {'components': [
            {'component': 'first', 'shipped_version': '1', 'recipes': [
                {'path': 'mxe/src/first.mk', 'archive': 'mxe-d973945-source.tar.gz', 'text': ''}]},
            {'component': 'second', 'shipped_version': '1', 'recipes': [
                {'path': 'build/build/second.mk', 'archive': 'mxe-build-scripts.tar.gz',
                 'text': '$(PKG)_PATCHES := /patches/$(PKG)-[0-9]*.patch'}]},
        ]}
        (root/'windows-component-recipes.json').write_text(json.dumps(recipes))
        source = tar_bytes({'source/file.c': b'old\n'})
        (root/'component-sources').mkdir()
        (root/'component-sources/second.source').write_bytes(source)
        (root/'materials.json').write_text(json.dumps({'archives': [{'component': 'second', 'sha256': tool.sha(source)}]}))
        return root, binding, entries

    def invoke(self, root, bindings):
        before = set(root.glob('patch-check-*'))
        with contextlib.redirect_stdout(io.StringIO()):
            code = tool.main(['--evidence', str(root), '--materials', str(root/'materials.json'),
                              '--recipe-materials', str(bindings), '--patch', 'unused-test-patch.exe'])
        created = set(root.glob('patch-check-*')) - before
        self.assertEqual(len(created), 1)
        folder = created.pop()
        return code, json.loads((folder/'report.json').read_text()), folder

    def test_verified_buffers_and_bad_bindings(self):
        root, binding, entries = self.fixture()
        self.assertEqual(set(tool.verified_recipe_bytes(root, binding)), tool.RECIPE_ARCHIVES)
        cases = [None, {}, [], {'archives': []}, {'archives': entries[:1]},
                 {'archives': entries+entries[:1]}, {'archives': [None]},
                 {'archives': [{'file': '../escape', 'sha256': '0'*64}]},
                 {'archives': [dict(entries[0], sha256='x'), entries[1]]}]
        for value in cases:
            with self.subTest(value=value):
                binding.write_text(json.dumps(value))
                with self.assertRaises(ValueError): tool.verified_recipe_bytes(root, binding)

    def test_tampering_rejected_before_archive_parsing(self):
        root, binding, entries = self.fixture()
        (root/entries[1]['file']).write_bytes(b'changed')
        with patch.object(tool.tarfile, 'open', side_effect=AssertionError('must not parse')):
            code, report, _ = self.invoke(root, binding)
        self.assertEqual(code, 1)
        self.assertEqual(report['failure']['stage'], 'recipe_checksums')
        self.assertIn('checksum mismatch', report['failure']['reason'])

    def test_missing_binding_file_has_retained_report(self):
        root, binding, entries = self.fixture()
        code, report, _ = self.invoke(root, root/'missing.json')
        self.assertEqual(code, 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['failure']['stage'], 'recipe_checksums')

    def test_setup_failure_retains_new_report_without_overwrite(self):
        root, binding, entries = self.fixture()
        (root/'windows-component-recipes.json').write_text('invalid JSON')
        code, report, folder = self.invoke(root, binding)
        original = (folder/'report.json').read_bytes()
        self.invoke(root, binding)
        self.assertEqual((folder/'report.json').read_bytes(), original)
        self.assertEqual(code, 1)
        self.assertEqual(report['failure']['stage'], 'setup')

    def test_source_failure_keeps_completed_component(self):
        root, binding, entries = self.fixture()
        (root/'component-sources/second.source').write_bytes(b'wrong')
        code, report, _ = self.invoke(root, binding)
        self.assertEqual(code, 1)
        self.assertEqual(report['failure']['stage'], 'source_checksum')
        self.assertTrue(report['components'][0]['passed'])
        self.assertFalse(report['components'][1]['passed'])

    def test_patch_failure_keeps_tool_output_and_prior_component(self):
        root, binding, entries = self.fixture()
        with patch.object(tool.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='hunk failed', stderr='')) as run:
            code, report, _ = self.invoke(root, binding)
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 1)
        self.assertIn('--dry-run', run.call_args.args[0])
        self.assertIn('--fuzz=0', run.call_args.args[0])
        self.assertTrue(report['components'][0]['passed'])
        self.assertFalse(report['components'][1]['passed'])
        self.assertEqual(report['components'][1]['patches'][0]['dry_run']['output'], 'hunk failed')

    def test_patch_success_uses_verified_source_bytes(self):
        root, binding, entries = self.fixture()
        def apply(command, cwd, **kwargs):
            self.assertEqual((cwd/'file.c').read_bytes(), b'old\n')
            if '--dry-run' not in command: (cwd/'file.c').write_bytes(b'new\n')
            return SimpleNamespace(returncode=0, stdout='ok', stderr='')
        with patch.object(tool.subprocess, 'run', side_effect=apply) as run:
            code, report, folder = self.invoke(root, binding)
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'])
        self.assertEqual(run.call_count, 2)
        self.assertEqual((folder/'second/file.c').read_bytes(), b'new\n')
        self.assertNotEqual(report['components'][1]['before'], report['components'][1]['after'])
