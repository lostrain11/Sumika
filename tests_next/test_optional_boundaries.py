from pathlib import Path
import tempfile
import unittest
from extensions.roles.voice import synthesize,transcribe
from extensions.desktop.perception import capture_audio,capture_camera
from extensions.desktop.translation import translate_image
from extensions.desktop.control.uia import WindowsController
from extensions.office.render import convert


class OptionalBoundaryTests(unittest.TestCase):
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
