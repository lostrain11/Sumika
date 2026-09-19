import json
import unittest
from unittest.mock import patch

from extensions.desktop import audio_devices


class AudioDeviceListingTests(unittest.TestCase):
    def test_explicit_missing_runtime_never_discovers_another_environment(self):
        with patch.dict(audio_devices.os.environ, {'SUMIKA_VOICE_PYTHON': 'missing.exe'}), \
                patch.object(audio_devices.Path, 'is_file', side_effect=[False, True]) as exists, \
                patch.object(audio_devices.subprocess, 'run') as run:
            result = audio_devices.list_input_devices()
        self.assertIsNotNone(result['error'])
        self.assertEqual(exists.call_count, 1)
        run.assert_not_called()

    def test_unset_runtime_still_discovers_installed_environment(self):
        with patch.dict(audio_devices.os.environ, {}, clear=True), \
                patch.object(audio_devices.Path, 'is_file', return_value=True):
            self.assertIn('voice-env', audio_devices.env_python())

    def _run(self, stdout="", returncode=0, stderr=""):
        class Result:
            pass
        result = Result()
        result.stdout, result.returncode, result.stderr = stdout, returncode, stderr
        return result

    def test_devices_are_listed_with_default_flag(self):
        payload = {"devices": [{"index": 35, "name": "EMEET SmartCam", "channels": 2,
                                "default_samplerate": 48000},
                               {"index": 34, "name": "VoiceMeeter Output", "channels": 2,
                                "default_samplerate": 44100}],
                   "default_input": 34}
        with patch("extensions.desktop.audio_devices.subprocess.run",
                   return_value=self._run(json.dumps(payload))):
            value = audio_devices.list_input_devices(python="C:/fake/python.exe")
        self.assertIsNone(value["error"])
        self.assertEqual(value["default_input"], 34)
        self.assertEqual([d["index"] for d in value["devices"]], [35, 34])
        self.assertTrue(value["devices"][1]["is_default"])
        self.assertFalse(value["devices"][0]["is_default"])

    def test_missing_interpreter_and_probe_failure_are_reported_not_guessed(self):
        with patch("extensions.desktop.audio_devices.env_python", return_value=None):
            value = audio_devices.list_input_devices()
        self.assertEqual(value["devices"], [])
        self.assertIn("not found", value["error"])
        with patch("extensions.desktop.audio_devices.subprocess.run",
                   return_value=self._run(returncode=1, stderr="PortAudio error")):
            value = audio_devices.list_input_devices(python="C:/fake/python.exe")
        self.assertIn("PortAudio", value["error"])
        with patch("extensions.desktop.audio_devices.subprocess.run",
                   return_value=self._run(stdout="not json")):
            value = audio_devices.list_input_devices(python="C:/fake/python.exe")
        self.assertEqual(value["error"], "invalid device probe output")

    def test_output_channels_are_not_offered_as_inputs(self):
        # The probe filters in the child process; the parent keeps only what it gets.
        payload = {"devices": [], "default_input": None}
        with patch("extensions.desktop.audio_devices.subprocess.run",
                   return_value=self._run(json.dumps(payload))):
            value = audio_devices.list_input_devices(python="C:/fake/python.exe")
        self.assertEqual(value["devices"], [])
        self.assertIsNone(value["default_input"])


if __name__ == "__main__":
    unittest.main()
