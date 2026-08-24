import json
import sys
import unittest

from sumika_core.events import EventBus
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import (
    CommandVisionProvider,
    ProviderRegistry,
    VisionProviderRegistry,
    VisionRequest,
)
from sumika_core.storage import Storage
from sumika_core.vision import VisionRuntime, VisionRuntimeError
from fixtures.providers import FakeProvider, FakeVisionProvider


class VisionProviderTests(unittest.TestCase):
    def test_fake_provider_and_external_jsonl_contract(self):
        fake = FakeVisionProvider("固定摘要")
        self.assertEqual(fake.summarize(VisionRequest("screen", b"image", "image/png")).summary, "固定摘要")

        code = (
            "import json,sys,base64; "
            "request=json.loads(sys.stdin.readline()); "
            "assert request['type']=='vision.observe'; "
            "assert base64.b64decode(request['image_base64'])==b'image'; "
            "print(json.dumps({'type':'result','summary':'外部摘要'}),flush=True)"
        )
        external = CommandVisionProvider(sys.executable, ["-c", code])
        result = external.summarize(VisionRequest("camera", b"image", "image/jpeg", "简短描述"))
        self.assertEqual(result.summary, "外部摘要")


class VisionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.storage.create_character("sumika", "Sumika", {})
        llm = ProviderRegistry()
        llm.register(FakeProvider("ok"))
        vision = VisionProviderRegistry()
        vision.register(FakeVisionProvider("不要写入事件的摘要"))
        self.modules = ModuleCatalog(self.storage, llm, vision=vision)
        self.events = EventBus(self.storage)
        self.runtime = VisionRuntime(self.storage, self.modules, vision, self.events)

    def tearDown(self):
        self.storage.close()

    def test_permission_gating_and_redacted_observation_audit(self):
        self.assertEqual(self.runtime.status()["sources"][0]["state"], "disabled")
        with self.assertRaises(VisionRuntimeError):
            self.runtime.start("screen")

        self.modules.update("vision", enabled=True, implementation_id="fake-vision")
        with self.assertRaisesRegex(VisionRuntimeError, "permission"):
            self.runtime.start("screen")
        self.runtime.set_permission("screen.read", True)
        started = self.runtime.start("screen")
        self.assertEqual(started["sources"][0]["state"], "running")
        result = self.runtime.observe("screen", b"private-image", mime_type="image/png")
        self.assertEqual(result["summary"], "不要写入事件的摘要")

        event = next(item for item in self.storage.list_events() if item["event_type"] == "vision.observed")
        event_text = json.dumps(event["payload"], ensure_ascii=False)
        self.assertNotIn("private-image", event_text)
        self.assertNotIn("不要写入事件的摘要", event_text)
        self.assertEqual(event["payload"]["content_length"], len(b"private-image"))

        self.runtime.set_permission("screen.read", False)
        self.assertFalse(next(item for item in self.runtime.status()["sources"] if item["id"] == "screen")["running"])


if __name__ == "__main__":
    unittest.main()
