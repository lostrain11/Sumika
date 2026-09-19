import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from ui.bridge_probe import probe


class BridgeProbeTests(unittest.TestCase):
    def check(self, *, identity='creation', owners='42', **overrides):
        root, settings = Path.cwd(), Path.cwd()/'personal/settings.json'
        data = dict(kind='sumika-ui-bridge', pid=42, creation='creation',
                    root=str(root.resolve()), settings=str(settings.resolve()))
        data.update(overrides)
        opener = MagicMock()
        opener.open.return_value = io.BytesIO(json.dumps(data).encode())
        with patch('ui.bridge_probe.socket.create_connection'), \
                patch('ui.bridge_probe.urllib.request.build_opener', return_value=opener), \
                patch('ui.bridge_probe.process_identity', return_value=identity), \
                patch('ui.bridge_probe.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=owners)):
            return probe(root, settings, 8765)

    def test_matching_instance(self):
        self.assertEqual(self.check(), 0)

    def test_conflicts(self):
        for mismatch in ({'kind': 'other'}, {'identity': 'reused-pid'}, {'identity': None},
                         {'owners': '43'}, {'owners': '42 43'}, {'root': 'different'},
                         {'settings': 'another-profile'}, {'pid': True}):
            with self.subTest(mismatch=mismatch):
                self.assertEqual(self.check(**mismatch), 3)

    def test_only_refused_connection_means_available(self):
        with patch('ui.bridge_probe.socket.create_connection', side_effect=ConnectionRefusedError):
            self.assertEqual(probe('.', '.', 8765), 2)
        with patch('ui.bridge_probe.socket.create_connection', side_effect=TimeoutError):
            self.assertEqual(probe('.', '.', 8765), 3)


if __name__ == '__main__':
    unittest.main()
