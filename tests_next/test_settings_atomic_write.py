import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.models.settings import example, save


class SettingsAtomicWriteTests(unittest.TestCase):
    def test_transient_windows_sharing_failure_retries_same_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            value = example(directory, Path(directory) / 'memory.sqlite3')
            original = os.replace
            calls = []
            error = PermissionError('sharing')
            error.winerror = 5

            def replace(source, target):
                calls.append((source, target))
                if len(calls) == 1:
                    raise error
                return original(source, target)

            with patch('extensions.models.settings.os.replace', side_effect=replace), \
                 patch('extensions.models.settings.time.sleep') as pause:
                save(value, path)
            self.assertEqual(calls[0], calls[1])
            pause.assert_called_once_with(.02)
            self.assertTrue(path.is_file())
            self.assertFalse(list(Path(directory).glob('settings.json.tmp')))

    def test_permanent_failure_keeps_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            value = example(directory, Path(directory) / 'memory.sqlite3')
            save(value, path)
            before = path.read_bytes()
            error = PermissionError('sharing')
            error.winerror = 5
            with patch('extensions.models.settings.os.replace', side_effect=error), \
                 patch('extensions.models.settings.time.sleep'):
                with self.assertRaises(PermissionError):
                    save(value, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(list(Path(directory).glob('settings.json.tmp')))
