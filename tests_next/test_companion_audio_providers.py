import asyncio
import sys
import types
import tempfile
import unittest
from unittest import mock
import threading


class AudioProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_sensevoice_bounds_without_loading(self):
        from extensions.companion.audio_providers import SenseVoicePcmProvider
        with tempfile.TemporaryDirectory() as folder:
            provider = SenseVoicePcmProvider(folder, max_bytes=4)
            for audio in (b'', b'123', b'123456'):
                with self.assertRaises(ValueError): await provider(audio)
            with self.assertRaises(ValueError): await provider(b'12', sample_rate=8000)
            with self.assertRaises(ValueError): SenseVoicePcmProvider(folder, num_threads=0)

    async def test_sensevoice_cancel_waits_for_native_call(self):
        from extensions.companion.audio_providers import SenseVoicePcmProvider
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            provider = SenseVoicePcmProvider(folder)
            def blocked(audio, rate, cancelled):
                entered.set(); release.wait(3)
                self.assertTrue(cancelled.is_set())
                return ''
            provider._recognize = blocked
            task = asyncio.create_task(provider(bytes(320)))
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            task.cancel(); await asyncio.sleep(0)
            self.assertFalse(task.done()); release.set()
            with self.assertRaises(asyncio.CancelledError): await task

    async def test_vosk_uses_pcm_and_caches_model(self):
        from extensions.companion.audio_providers import VoskPcmProvider
        created = []
        class Model:
            def __init__(self, path): created.append(path)
        class Recognizer:
            def __init__(self, model, rate): self.parts = []
            def AcceptWaveform(self, chunk): self.parts.append(chunk); return True
            def Result(self): return '{"text":"hello"}'
            def FinalResult(self): return '{"text":"world"}'
        fake = types.SimpleNamespace(Model=Model, KaldiRecognizer=Recognizer)
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(sys.modules, vosk=fake):
                provider = VoskPcmProvider(folder, max_bytes=64000)
                self.assertEqual(await provider(b'\0' * 320), 'hello world')
                self.assertEqual(await provider(b'\0' * 320), 'hello world')
        self.assertEqual(len(created), 1)

    async def test_cancel_fences_late_vosk_result(self):
        from extensions.companion.audio_providers import VoskPcmProvider
        with tempfile.TemporaryDirectory() as folder:
            provider = VoskPcmProvider(folder)
            original = provider._recognize
            entered = threading.Event()
            release = threading.Event()
            def blocked(*args):
                entered.set()
                release.wait(10)
                return 'late'
            provider._recognize = blocked
            task = asyncio.create_task(provider(b'\0' * 320))
            await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
            provider._recognize = original

    async def test_pcm_limits(self):
        from extensions.companion.audio_providers import VoskPcmProvider
        with tempfile.TemporaryDirectory() as folder:
            provider = VoskPcmProvider(folder, max_bytes=4)
            with self.assertRaises(ValueError): await provider(b'123456')

    async def test_cancel_stops_before_next_native_chunk(self):
        from extensions.companion.audio_providers import VoskPcmProvider
        entered, release = threading.Event(), threading.Event()
        chunks = []
        class Recognizer:
            def __init__(self, model, rate): pass
            def AcceptWaveform(self, chunk):
                chunks.append(chunk)
                entered.set()
                release.wait(3)
                return False
            def FinalResult(self): raise AssertionError('cancelled turn must not finalize')
        with tempfile.TemporaryDirectory() as folder:
            fake = types.SimpleNamespace(Model=lambda path: object(), KaldiRecognizer=Recognizer)
            with mock.patch.dict(sys.modules, vosk=fake):
                provider = VoskPcmProvider(folder)
                task = asyncio.create_task(provider(bytes(24000)))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                    task.cancel()
                    await asyncio.sleep(0)
                finally:
                    release.set()
                with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(len(chunks), 1)
