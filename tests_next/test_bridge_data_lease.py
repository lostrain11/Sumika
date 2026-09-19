import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ui.server import serve


class BridgeDataLeaseTests(unittest.TestCase):
    def setUp(self):
        base = Path('.sumika-next/bridge-lease-tests')
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=base)).resolve()

    def test_second_bridge_cannot_write_same_data_on_another_port(self):
        settings = self.root/'role-model-settings.json'
        first = serve(settings, port=0)
        try:
            original = settings.read_bytes()
            with patch('ui.server.Bridge') as construct:
                with self.assertRaises(OSError):
                    serve(settings, port=0)
                construct.assert_not_called()
            self.assertEqual(settings.read_bytes(), original)
        finally:
            first.server_close()
        second = serve(settings, port=0)
        second.server_close()

    def test_constructor_failure_releases_lease(self):
        settings = self.root/'role-model-settings.json'
        with patch('ui.server.Bridge', side_effect=ValueError('fixture')):
            with self.assertRaises(ValueError):
                serve(settings, port=0)
        server = serve(settings, port=0)
        server.server_close()

    def test_process_exit_releases_os_lock_without_deleting_file(self):
        from ui.data_lease import DataLease
        code = 'from ui.data_lease import DataLease; import sys; lease=DataLease(sys.argv[1]).acquire(); print("locked",flush=True); sys.stdin.read()'
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.root)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            with self.assertRaises(OSError):
                DataLease(self.root).acquire()
        finally:
            child.terminate()
            child.wait(timeout=10)
            child.stdin.close()
            child.stdout.close()
        lease = DataLease(self.root).acquire()
        lease.release()
        self.assertTrue((self.root/'sumika-bridge.lock').exists())


if __name__ == '__main__':
    unittest.main()
