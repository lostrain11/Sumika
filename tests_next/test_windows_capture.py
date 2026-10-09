import os
import unittest
from unittest.mock import patch

from extensions.desktop.windows_capture import capability, capture_window, capture_frame


class WindowsCaptureTests(unittest.TestCase):
    def test_capability_is_explicit(self):
        result = capability()
        self.assertEqual(result['provider'], 'windows-graphics-capture')
        self.assertIn('supported', result)

    def test_invalid_window_rejected(self):
        with self.assertRaises(ValueError): capture_window(handle=0, output='x')

    def test_capture_requires_consent_and_exact_process(self):
        with self.assertRaises(ValueError):
            capture_frame(handle=42, process_id=None, approved=True)
        with self.assertRaises(PermissionError):
            capture_frame(handle=42, process_id=7)

    @patch('extensions.desktop.windows_capture.os.name', 'nt')
    def test_capture_host_property_is_rejected(self):
        fake = type('User32', (), {})()
        fake.IsWindow = lambda handle: True
        fake.IsWindowVisible = lambda handle: True
        fake.IsIconic = lambda handle: False
        fake.GetAncestor = lambda handle, flags: handle
        fake.GetPropW = lambda handle, name: 1 if name == 'Sumika.Companion.CaptureHost' else 0
        # Simulate the native write through ctypes.byref().
        def get_pid(handle, value):
            ctypes_obj = getattr(value, '_obj', None)
            if ctypes_obj is not None:
                ctypes_obj.value = 99
        fake.GetWindowThreadProcessId = get_pid
        with patch('extensions.desktop.windows_capture.ctypes.WinDLL', return_value=fake), \
             patch('extensions.desktop.windows_capture.os.getpid', return_value=123):
            from extensions.desktop.windows_capture import _identity
            with self.assertRaisesRegex(RuntimeError, 'cannot be a learning capture target'):
                _identity(10, 99)
