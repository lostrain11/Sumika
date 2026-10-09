import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extensions.desktop.runtime import capability_python, process_audio_helper


class CapabilityRuntimeTests(unittest.TestCase):
    def test_process_audio_helper_resolves_bundled_and_respects_explicit_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            target = root/'runtime/process-audio/SumikaProcessAudio.exe'
            self.assertIsNone(process_audio_helper(root=root))
            target.parent.mkdir(parents=True)
            target.touch()
            self.assertEqual(process_audio_helper(root=root), str(target))
            with patch.dict(os.environ, {'SUMIKA_PROCESS_AUDIO_HELPER': str(root/'missing.exe')}):
                self.assertIsNone(process_audio_helper(root=root))
    def test_bundled_runtime_precedes_development_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            for path in ('runtime/desktop/python.exe', '.sumika-next/desktop-env/Scripts/python.exe'):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            self.assertEqual(capability_python('desktop', root=root), str(root/'runtime/desktop/python.exe'))

    def test_explicit_missing_runtime_never_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root/'runtime/desktop/python.exe'
            target.parent.mkdir(parents=True)
            target.touch()
            with patch.dict(os.environ, {'SUMIKA_DESKTOP_PYTHON': str(root/'missing.exe')}):
                self.assertIsNone(capability_python('desktop', root=root))

    def test_voice_uses_bundled_desktop_when_dedicated_voice_is_absent(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            target = Path(folder)/'runtime/desktop/python.exe'
            target.parent.mkdir(parents=True)
            target.touch()
            self.assertEqual(capability_python('voice', root=folder), str(target))
