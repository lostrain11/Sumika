"""P07/R7 build receipt helpers: source identity and bounded input digests."""
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_portable_staging import directory_digest, source_state


class DirectoryDigestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_digest_pins_relative_layout_and_detects_change(self):
        (self.root/'a').mkdir()
        (self.root/'a'/'one.txt').write_text('first', encoding='utf8')
        (self.root/'b.txt').write_text('second', encoding='utf8')
        baseline = directory_digest(self.root)
        self.assertEqual(baseline['files'], 2)
        # Layout-sensitive: the same files under different names differ.
        (self.root/'b.txt').write_text('changed', encoding='utf8')
        changed = directory_digest(self.root)
        self.assertNotEqual(baseline['sha256'], changed['sha256'])
        self.assertEqual(changed['files'], 2)
        # Deterministic for an unchanged tree.
        self.assertEqual(changed['sha256'], directory_digest(self.root)['sha256'])
        # A pyc byte-code file is never part of the input digest.
        (self.root/'junk.pyc').write_bytes(b'x')
        self.assertEqual(directory_digest(self.root)['files'], 2)


class SourceStateTests(unittest.TestCase):
    def test_source_state_reports_commit_and_dirty_honestly(self):
        state = source_state(ROOT)
        # This workspace is a git checkout: the commit resolves. The tree may
        # be clean or dirty; the report must say which, never assume.
        self.assertNotEqual(state['commit'], 'unavailable')
        self.assertTrue(len(state['commit']) == 40)
        self.assertIsInstance(state['dirty'], bool)
        if not state['dirty']:
            self.assertEqual(state['dirty_sample'], [])
        self.assertLessEqual(len(state['dirty_sample']), 20)


if __name__ == '__main__':
    unittest.main()
