import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from extensions.capabilities import CapabilityStore
from extensions.desktop.service import execute
from ui.management import Management


class MicrophonePermissionTests(unittest.TestCase):
    def test_permission_separate_from_module_and_per_capture_approval(self):
        with tempfile.TemporaryDirectory(dir='.sumika-next') as folder:
            database=Path(folder)/'capabilities.db'
            store=CapabilityStore(database)
            try:
                store.configure('microphone','sounddevice',options={'existing':'preserve'})
                command={'capability':'microphone','operation':'capture','arguments':{'output':str(Path(folder)/'test.wav'),'approved':True}}
                with patch('extensions.desktop.perception.capture_audio') as capture:
                    with self.assertRaises(PermissionError):execute(store,command)
                    capture.assert_not_called()
                manager=Management(SimpleNamespace(capability_database=database,workbench=SimpleNamespace(root=Path(folder)),stop_speech=Mock()))
                with patch('ui.management.service_capabilities',return_value=[]):
                    state=manager.modules()
                    payload={'id':'microphone','enabled':True,'expected_revision':state['revision']}
                    with self.assertRaises(ValueError):manager.modules('microphone_authorization',payload)
                    granted=manager.modules('microphone_authorization',{**payload,'confirmed':True})
                    self.assertTrue(granted['modules'][0]['options']['user_authorized'])
                    self.assertEqual(granted['modules'][0]['options']['existing'],'preserve')
                    command['arguments']['approved']=False
                    with self.assertRaisesRegex(PermissionError,'native authorization'):execute(store,command)
                    manager.modules('microphone_authorization',{'id':'microphone','enabled':False,'confirmed':True,'expected_revision':granted['revision']})
                    with self.assertRaisesRegex(PermissionError,'permission is disabled'):execute(store,command)
            finally:store.close()
