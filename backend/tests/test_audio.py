import sys
import unittest

from sumika_core.audio import AudioRuntime, AudioRuntimeError
from sumika_core.events import EventBus
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import (
    AudioProviderRegistry,
    CommandASRProvider,
    CommandTTSProvider,
    CommandVADProvider,
    ProviderRegistry,
)
from sumika_core.providers.audio import ASRRequest, TTSRequest, VADRequest
from sumika_core.storage import Storage
from fixtures.providers import FakeASRProvider, FakeProvider, FakeTTSProvider, FakeVADProvider


class AudioProviderTests(unittest.TestCase):
    def test_fake_providers_and_registry(self):
        registry = AudioProviderRegistry()
        registry.register(FakeASRProvider("hello"))
        registry.register(FakeTTSProvider("say:"))
        registry.register(FakeVADProvider(2))

        self.assertEqual(registry.transcribe("fake-asr", ASRRequest(b"audio")), "hello")
        self.assertEqual(registry.synthesize("fake-tts", TTSRequest("hello")).audio, b"say:hello")
        self.assertFalse(registry.detect("fake-vad", VADRequest(b"x")))
        self.assertTrue(registry.detect("fake-vad", VADRequest(b"xx")))

    def test_external_jsonl_audio_contracts(self):
        code = (
            "import base64,json,sys; "
            "request=json.loads(sys.stdin.readline()); "
            "kind=request['type']; "
            "print(json.dumps({'type':'result','text':'external text'}) if kind=='asr' else "
            "json.dumps({'type':'audio','audio_base64':base64.b64encode(request['text'].encode()).decode(),'content_type':'audio/test'}) if kind=='tts' else "
            "json.dumps({'type':'speech','speech':len(base64.b64decode(request['audio_base64'])) > 1}),flush=True)"
        )
        asr = CommandASRProvider(sys.executable, ["-c", code])
        tts = CommandTTSProvider(sys.executable, ["-c", code])
        vad = CommandVADProvider(sys.executable, ["-c", code])
        self.assertEqual(asr.transcribe(ASRRequest(b"x")), "external text")
        result = tts.synthesize(TTSRequest("hello"))
        self.assertEqual(result.audio, b"hello")
        self.assertEqual(result.content_type, "audio/test")
        self.assertTrue(vad.detect(VADRequest(b"xx")))


class AudioRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.events = EventBus(self.storage)
        self.llm = ProviderRegistry()
        self.llm.register(FakeProvider("ok"))
        self.audio = AudioProviderRegistry()
        self.audio.register(FakeASRProvider("heard"))
        self.audio.register(FakeTTSProvider("tts:"))
        self.audio.register(FakeVADProvider())
        self.modules = ModuleCatalog(self.storage, self.llm, self.audio)
        self.runtime = AudioRuntime(self.storage, self.modules, self.audio, self.events)

    def tearDown(self):
        self.storage.close()

    def test_permissions_gate_start_and_runtime_calls(self):
        self.modules.update("asr", enabled=True, implementation_id="fake-asr")
        with self.assertRaises(AudioRuntimeError):
            self.runtime.start("asr")
        self.runtime.set_permission("microphone", True)
        status = self.runtime.start("asr")
        asr = next(item for item in status["capabilities"] if item["id"] == "asr")
        self.assertEqual(asr["state"], "running")
        self.assertEqual(self.runtime.transcribe(b"audio", sample_rate=16_000, channels=1), "heard")
        self.modules.update("asr", enabled=False)
        self.runtime.reconcile()
        self.assertFalse(next(item for item in self.runtime.status()["capabilities"] if item["id"] == "asr")["running"])

    def test_module_catalog_exposes_audio_implementations(self):
        asr = self.modules.get("asr")
        self.assertEqual([item["id"] for item in asr["implementations"]], ["none", "fake-asr"])


if __name__ == "__main__":
    unittest.main()
