"""File ASR selection, bounded decoding and original Vosk compatibility."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from extensions.roles.voice import transcribe


class FileVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def wav(self, seconds=1, rate=16000):
        path = self.root/'sample.wav'
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes(b'\0\0' * int(seconds * rate))
        return path

    def test_sensevoice_long_file_is_bounded_and_preloaded(self):
        chunks = []
        loaded = []

        class Provider:
            max_bytes = 16000 * 2 * 30

            def __init__(self, model):
                self.model = model

            def load_model(self):
                loaded.append(True)

            async def __call__(self, audio, *, sample_rate):
                self.assert_loaded = bool(loaded)
                if not self.assert_loaded or sample_rate != 16000:
                    raise AssertionError('provider must be preloaded')
                chunks.append(len(audio))
                return '段落'

        with patch('extensions.companion.audio_providers.SenseVoicePcmProvider', Provider):
            result = transcribe(self.wav(seconds=61), model=self.root,
                                provider='sherpa-onnx-sensevoice')
        self.assertEqual(chunks, [960000, 960000, 32000])
        self.assertEqual(result['text'], '段落 段落 段落')
        self.assertEqual(result['provider'], 'sherpa-onnx-sensevoice')
        self.assertEqual(loaded, [True])

    def test_sensevoice_bad_rate_rejected_before_native_load(self):
        with patch('extensions.companion.audio_providers.SenseVoicePcmProvider') as provider:
            with self.assertRaisesRegex(ValueError, '16kHz'):
                transcribe(self.wav(rate=22050), model=self.root,
                           provider='sherpa-onnx-sensevoice')
            provider.assert_not_called()

    def test_sensevoice_load_failure_does_not_fallback(self):
        with patch('extensions.companion.audio_providers.SenseVoicePcmProvider') as provider:
            provider.return_value.load_model.side_effect = RuntimeError('native load failed')
            with self.assertRaisesRegex(RuntimeError, 'native load failed'):
                transcribe(self.wav(), model=self.root, provider='sherpa-onnx-sensevoice')

    def test_vosk_keeps_original_sapi_sample_rate(self):
        native = Mock()
        recognizer = native.KaldiRecognizer.return_value
        recognizer.AcceptWaveform.return_value = False
        recognizer.FinalResult.return_value = '{"text":"旧路径"}'
        with patch.dict(sys.modules, vosk=native):
            result = transcribe(self.wav(rate=22050), model=self.root)
        self.assertEqual(result['text'], '旧路径')
        self.assertEqual(native.KaldiRecognizer.call_args.args[1], 22050)

    def test_unknown_provider_rejected_without_opening_audio(self):
        with self.assertRaisesRegex(ValueError, 'no fallback'):
            transcribe('missing.wav', model=self.root, provider='unknown')

    def test_desktop_dispatch_uses_selected_provider(self):
        from extensions.desktop.service import execute
        store = Mock()
        store.resolve.return_value = {'provider': 'sherpa-onnx-sensevoice',
                                      'options': {'model': str(self.root)}}
        with patch('extensions.roles.voice.transcribe', return_value={'text':'课程'}) as decode:
            result = execute(store, {'capability':'asr', 'operation':'transcribe',
                                     'arguments':{'audio':'sample.wav'}})
        self.assertEqual(result['text'], '课程')
        decode.assert_called_once_with(audio='sample.wav', model=str(self.root),
                                       provider='sherpa-onnx-sensevoice')
