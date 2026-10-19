from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from extensions.roles.voice import synthesize,transcribe
from extensions.desktop.perception import capture_audio,capture_camera,read_camera_frame
from extensions.desktop.translation import translate_image
from extensions.desktop.control.uia import WindowsController
from extensions.office.render import convert


class OptionalBoundaryTests(unittest.TestCase):
    def test_camera_warmup_and_release_on_read_failure(self):
        camera = Mock()
        frame = object()
        camera.isOpened.return_value = True
        camera.read.return_value = (True, frame)
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=camera), CAP_DSHOW=700)
        with patch.dict('sys.modules', {'cv2': cv2}):
            self.assertIs(read_camera_frame(approved=True, warmup=5), frame)
            self.assertEqual(camera.read.call_count, 6)
            camera.release.assert_called_once()
            camera.reset_mock(); camera.read.return_value = (False, None)
            with self.assertRaises(RuntimeError): read_camera_frame(approved=True)
            camera.release.assert_called_once()

    def test_windows_numeric_camera_uses_directshow_without_backend_retry(self):
        camera = Mock()
        camera.isOpened.return_value = False
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=camera), CAP_DSHOW=700)
        with patch.dict('sys.modules', {'cv2': cv2}), \
             patch('extensions.desktop.perception.sys.platform', 'win32'):
            with self.assertRaises(RuntimeError): read_camera_frame(approved=True)
        cv2.VideoCapture.assert_called_once_with(0, 700)
        camera.release.assert_called_once()

    def test_nonwindows_retains_native_backend(self):
        camera = Mock()
        camera.isOpened.return_value = False
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=camera))
        with patch.dict('sys.modules', {'cv2': cv2}), \
             patch('extensions.desktop.perception.sys.platform', 'linux'):
            with self.assertRaises(RuntimeError): read_camera_frame(approved=True)
        cv2.VideoCapture.assert_called_once_with(0)

    def test_disabled_performs_no_io_or_dependency_import(self):
        self.assertTrue(synthesize('text','absent',enabled=False)['disabled'])
        self.assertTrue(transcribe('absent',model='absent',enabled=False)['disabled'])
        self.assertTrue(capture_audio('absent',enabled=False)['disabled'])
        self.assertTrue(capture_camera('absent',enabled=False)['disabled'])
        self.assertTrue(convert('absent','absent',executable='absent',enabled=False)['disabled'])
        self.assertTrue(translate_image('absent',translate=None,enabled=False)['disabled'])

    def test_mutations_refuse_before_importing_dependencies(self):
        with self.assertRaises(PermissionError):capture_camera('absent')
        with self.assertRaises(PermissionError):capture_audio('absent')
        with self.assertRaises(PermissionError):WindowsController().act(1,1,'invoke')
        with self.assertRaises(PermissionError):WindowsController(enabled=False).inspect(1,1)

    def test_audio_duration_is_bounded(self):
        for value in (0,-1,31,float('nan')):
            with self.assertRaises(ValueError):capture_audio('absent',seconds=value,approved=True)
