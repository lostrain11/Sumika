import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
from types import SimpleNamespace

from extensions.desktop.audio_loopback import capture_loopback


class AudioLoopbackTests(unittest.TestCase):
    def test_process_specific_request_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'process-specific'):
            capture_loopback('x.wav', approved=True, process_id=42)

    def test_endpoint_capture_writes_wave(self):
        class Recorder:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def record(self, numframes):
                import numpy as np
                return np.zeros((numframes, 1), dtype='float32')
        class Loopback:
            isloopback = True
            def recorder(self, **kwargs): return Recorder()
        class Speaker:
            id = 'test-speaker'
        def get_microphone(device_id, include_loopback=False):
            self.assertEqual(device_id, 'test-speaker')
            self.assertTrue(include_loopback)
            return Loopback()
        fake_soundcard = SimpleNamespace(default_speaker=lambda: Speaker(), get_microphone=get_microphone)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'soundcard': fake_soundcard}):
            result = capture_loopback(Path(directory) / 'capture.wav', seconds=.1, approved=True)
            self.assertTrue(Path(result['path']).is_file())
            self.assertFalse(result['process_isolation'])

    def test_requires_consent(self):
        with self.assertRaises(PermissionError): capture_loopback('x.wav')
