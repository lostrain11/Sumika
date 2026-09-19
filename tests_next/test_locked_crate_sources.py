import hashlib
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch
import uuid

from tools.collect_locked_crate_sources import fetch, registry_packages


class LockedCrateSourceTests(unittest.TestCase):
    def row(self):
        return dict(name='example', version='1.0.0', checksum='a'*64,
                    source='registry+https://github.com/rust-lang/crates.io-index')

    def test_unknown_registry_and_unsafe_identity_refused(self):
        for changes in ({'source':'git+https://example.org/repo'},
                        {'name':'../escape'}, {'version':'../x'}, {'checksum':'unknown'}):
            with self.assertRaises(ValueError):
                registry_packages({'package':[{**self.row(), **changes}]})
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            registry_packages({'package':[self.row(),self.row()]})
        self.assertEqual(registry_packages({'package':[{'name':'local','version':'1'}]}), [])

    def fixture(self):
        base = Path('.sumika-next')/('crate-source-test-'+uuid.uuid4().hex)
        base.mkdir()
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, body in [('example-1.0.0/Cargo.toml', b'[package]\nname="example"\nversion="1.0.0"\nlicense="MIT"\n'),
                               ('example-1.0.0/LICENSE', b'fixture license')]:
                item = tarfile.TarInfo(name); item.size = len(body)
                archive.addfile(item, io.BytesIO(body))
        raw = output.getvalue()
        row = {'name':'example','version':'1.0.0','sha256':hashlib.sha256(raw).hexdigest()}
        return base, raw, row

    def test_download_verified_and_cache_reused_without_network(self):
        base, raw, row = self.fixture()
        with patch('urllib.request.urlopen', return_value=io.BytesIO(raw)) as network:
            result = fetch(row, base)
        self.assertTrue(result['verified']); self.assertEqual(result['declared_license'], 'MIT')
        self.assertEqual(network.call_count, 1)
        with patch('urllib.request.urlopen', side_effect=AssertionError('cache should be reused')):
            self.assertTrue(fetch(row, base)['verified'])

    def test_corrupt_cache_preserved_not_silently_downloaded(self):
        base, raw, row = self.fixture()
        archive = base/'example-1.0.0.crate'; archive.write_bytes(b'corrupt evidence')
        with patch('urllib.request.urlopen', side_effect=AssertionError('no automatic repair')):
            result = fetch(row, base)
        self.assertFalse(result['verified'])
        self.assertEqual(archive.read_bytes(), b'corrupt evidence')

    def test_hash_correct_archive_with_wrong_manifest_refused(self):
        base, raw, row = self.fixture()
        (base/'other-1.0.0.crate').write_bytes(raw)
        self.assertFalse(fetch({**row,'name':'other'}, base)['verified'])


if __name__ == '__main__':
    unittest.main()
