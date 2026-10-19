import subprocess
import tempfile
import unittest
from pathlib import Path


class BrowserExtensionRetryTests(unittest.TestCase):
    def test_transient_snapshot_failure_retries_with_full_frame(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='browser-ext-retry-') as directory:
            build = subprocess.run(
                ['node', str(repo/'tools/build_companion_extension.mjs'), directory],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            content = (Path(directory)/'content.js').read_text(encoding='utf8')
            worker = (Path(directory)/'worker.js').read_text(encoding='utf8')
            # A transport failure must keep the approved grant and force a new
            # full snapshot; only an explicit host rejection may end polling.
            self.assertIn('networkRetries<30', content)
            self.assertIn('needsFull=true', content)
            self.assertIn('retry:true', worker)
            self.assertNotIn("connection=null;lastStatus='network_failed'", worker)


if __name__ == '__main__':
    unittest.main()
