import os
import subprocess
import hashlib
import json
from pathlib import Path
import unittest
import uuid
import xml.etree.ElementTree as ET

from tools.prepare_clean_windows import configuration, prepare


class CleanWindowsBundleTests(unittest.TestCase):
    def test_only_package_readonly_and_dedicated_results_writable(self):
        root = ET.fromstring(configuration(Path('D:/test & inputs'), Path('D:/results')))
        folders = root.findall('MappedFolders/MappedFolder')
        self.assertEqual(len(folders), 2)
        self.assertEqual(folders[0].findtext('HostFolder'), 'D:\\test & inputs')
        self.assertEqual([f.findtext('ReadOnly') for f in folders], ['true', 'false'])
        self.assertEqual(root.findtext('Networking'), 'Disable')
        self.assertEqual(root.findtext('ClipboardRedirection'), 'Disable')
        self.assertEqual(root.findtext('AudioInput'), 'Disable')

    def test_bad_hash_no_output_and_existing_directory_preserved(self):
        base = Path('.sumika-next')/('clean-bundle-test-'+uuid.uuid4().hex)
        base.mkdir()
        source = base/'fixture.zip'
        source.write_bytes(b'synthetic archive identity fixture')
        destination = base/'bundle'
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            prepare(source, '0'*64, destination)
        self.assertFalse(destination.exists())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        prepare(source, digest, destination)
        spec = json.loads((destination/'input/input.json').read_text())
        self.assertEqual(spec['archive_sha256'], digest)
        self.assertEqual(spec['status'], 'prepared_not_executed')
        self.assertEqual((destination/'input/Sumika-internal.zip').read_bytes(), source.read_bytes())
        self.assertEqual(list((destination/'results').iterdir()), [])
        with self.assertRaisesRegex(ValueError, 'existing evidence'):
            prepare(source, digest, destination)


    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell required')
    def test_guest_start_failure_and_repeat_preserve_evidence(self):
        base = Path('.sumika-next') / ('guest-progress-test-' + uuid.uuid4().hex)
        base.mkdir()
        output = base / 'results'
        output.mkdir()
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-File', 'packaging/verify_clean_windows.ps1',
                   '-InputRoot', str(base / 'missing-input'), '-OutputRoot', str(output),
                   '-WorkRoot', str(base)]
        result = subprocess.run(command, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        progress = json.loads((output / 'progress.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(progress['stage'], 'input-validation')
        self.assertEqual(progress['status'], 'failed')
        report = json.loads((output / 'report.json').read_text(encoding='utf-8-sig'))
        self.assertFalse(report['passed'])
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        work_before = sorted(p.name for p in base.iterdir())
        result = subprocess.run(command, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
        self.assertEqual(work_before, sorted(p.name for p in base.iterdir()))


if __name__ == '__main__':
    unittest.main()
