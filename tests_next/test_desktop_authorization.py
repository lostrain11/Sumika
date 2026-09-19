import hashlib,json,unittest
from extensions.desktop.control.uia import WindowsController

class DesktopAuthTests(unittest.TestCase):
    def test_api_requires_snapshot_when_supplied_and_returns_hash(self):
        source=open('extensions/desktop/control/uia.py',encoding='utf8').read()
        self.assertIn('expected_snapshot_hash',source)
        self.assertIn('verification_hash',source)
    def test_missing_approval_stops_before_target_lookup(self):
        with self.assertRaises(PermissionError): WindowsController().act(1,1,'invoke',expected_snapshot_hash='x')
