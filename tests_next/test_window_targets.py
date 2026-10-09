import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock
from extensions.desktop.window_targets import _entry


class WindowTargetsTests(unittest.TestCase):
    def api(self, title='Tutorial'):
        api = Mock()
        def process(handle, pointer): ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0] = 42
        def text(handle, buffer, size): buffer.value = title[:size-1]; return len(buffer.value)
        api.GetWindowThreadProcessId.side_effect = process
        api.GetWindowTextLengthW.return_value = len(title)
        api.GetWindowTextW.side_effect = text
        return api

    def test_inventory_binds_pid_creation_and_reuses_capture_validation(self):
        validate = Mock()
        result = _entry(123, self.api(), identity=lambda pid:'creation', validate=validate)
        self.assertEqual(result, {'handle':123,'process_id':42,'process_creation':'creation','title':'Tutorial'})
        validate.assert_called_once_with(123,42)

    def test_excluded_or_disappeared_window_not_offered(self):
        with self.assertRaises(RuntimeError):
            _entry(123,self.api(),identity=lambda pid:'creation',validate=Mock(side_effect=RuntimeError('pet')))
        self.assertIsNone(_entry(123,self.api(),identity=lambda pid:None,validate=Mock()))
        self.assertIsNone(_entry(123,self.api(''),identity=lambda pid:'creation',validate=Mock()))

    def test_title_is_bounded(self):
        api=self.api('x'*3000)
        result=_entry(123,api,identity=lambda pid:'creation',validate=Mock())
        self.assertLessEqual(len(result['title']),1024)
