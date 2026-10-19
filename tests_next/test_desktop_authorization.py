import hashlib,json,unittest
from unittest.mock import Mock,patch
from extensions.desktop.control.uia import WindowsController

class DesktopAuthTests(unittest.TestCase):
    def test_api_requires_snapshot_when_supplied_and_returns_hash(self):
        with open('extensions/desktop/control/uia.py',encoding='utf8') as handle:
            source=handle.read()
        self.assertIn('expected_snapshot_hash',source)
        self.assertIn('verification_hash',source)
    def test_missing_approval_stops_before_target_lookup(self):
        with self.assertRaises(PermissionError): WindowsController().act(1,1,'invoke',expected_snapshot_hash='x')

    def test_post_action_inspection_failure_returns_unknown_without_retry(self):
        controller=WindowsController();window=Mock()
        with patch.object(controller,'_window',return_value=window), \
                patch.object(controller,'inspect',side_effect=[[],RuntimeError('window closed')]):
            result=controller.act(1,2,'set_text',approved=True,text='new')
        window.set_edit_text.assert_called_once_with('new')
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['failure_phase'],'post_action_inspection')
        self.assertFalse(result['retry_allowed'])

    def test_native_mutation_error_returns_uncertainty(self):
        controller=WindowsController();window=Mock();window.invoke.side_effect=RuntimeError('native timeout')
        with patch.object(controller,'_window',return_value=window),patch.object(controller,'inspect',return_value=[]):
            result=controller.act(1,2,'invoke',approved=True)
        window.invoke.assert_called_once();self.assertEqual(result['failure_phase'],'mutation')
        self.assertTrue(result['action_attempted']);self.assertFalse(result['retry_allowed'])

    def test_snapshot_mismatch_never_mutates(self):
        controller=WindowsController();window=Mock()
        with patch.object(controller,'_window',return_value=window),patch.object(controller,'inspect',return_value=[]):
            with self.assertRaises(PermissionError):
                controller.act(1,2,'invoke',approved=True,expected_snapshot_hash='stale')
        window.invoke.assert_not_called()
