import json
import sys
import tempfile
import unittest
from pathlib import Path

from sumika_core.plugins import PluginCatalog, PluginCatalogError
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import (
    ASRRequest,
    PluginASRProvider,
    PluginLLMProvider,
    PluginMemoryProvider,
    PluginTTSProvider,
    PluginVADProvider,
    PluginVisionProvider,
    ProviderRegistry,
    TTSRequest,
    VADRequest,
    VisionRequest,
)
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.storage import Storage
from fixtures.providers import FakeProvider


class PluginCatalogTests(unittest.TestCase):
    def _write_plugin(self, root: Path, *, version: str = "0.1.0", capability: str = "llm") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "entry.py").write_text("# metadata-only test entrypoint\n", encoding="utf-8")
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "test.plugin",
                    "version": version,
                    "capabilities": [capability],
                    "entrypoint": "entry.py",
                    "runtime": "external-process",
                }
            ),
            encoding="utf-8",
        )
        return root

    def test_discovery_is_metadata_only_and_approval_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._write_plugin(Path(directory) / "plugin", capability="tool")
            storage = Storage()
            catalog = PluginCatalog(storage)

            discovered = catalog.discover(root.parent)
            self.assertEqual(len(discovered), 1)
            candidate = discovered[0]
            self.assertEqual(candidate["state"], "discovered")
            self.assertEqual(catalog.list()[0]["state"], "discovered")

            approved = catalog.approve(candidate["candidate_id"])
            self.assertEqual(approved["state"], "approved")
            self.assertEqual(approved["manifest"]["entrypoint"], "entry.py")
            self.assertNotIn("plugin_registrations", storage.export_snapshot_state("system")["tables"])

            revoked = catalog.revoke(candidate["candidate_id"])
            self.assertEqual(revoked["state"], "revoked")
            storage.close()

    def test_changed_manifest_requires_rediscovery_before_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._write_plugin(Path(directory) / "plugin")
            storage = Storage()
            catalog = PluginCatalog(storage)
            candidate = catalog.discover(root)[0]
            (root / "manifest.json").write_text(
                (root / "manifest.json").read_text(encoding="utf-8").replace("0.1.0", "0.2.0"),
                encoding="utf-8",
            )
            with self.assertRaises(PluginCatalogError):
                catalog.approve(candidate["candidate_id"])
            changed = catalog.discover(root)[0]
            self.assertEqual(changed["state"], "changed")
            self.assertEqual(catalog.approve(changed["candidate_id"])["version"], "0.2.0")
            storage.close()

    def test_manifest_entrypoint_must_not_escape_plugin_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            root.mkdir()
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "test.escape",
                        "version": "0.1.0",
                        "capabilities": ["tool"],
                        "entrypoint": "../outside.py",
                    }
                ),
                encoding="utf-8",
            )
            storage = Storage()
            candidate = PluginCatalog(storage).discover(root)[0]
            self.assertEqual(candidate["state"], "invalid")
            self.assertIn("entrypoint", candidate["error"])
            storage.close()

    def test_tool_launcher_must_reference_entrypoint_and_revalidates_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._write_plugin(Path(directory) / "plugin", capability="tool")
            storage = Storage()
            catalog = PluginCatalog(storage)
            candidate = catalog.discover(root)[0]
            with self.assertRaises(PluginCatalogError):
                catalog.configure_launcher(
                    candidate["candidate_id"],
                    {"executable": sys.executable, "arguments": []},
                )
            with self.assertRaises(PluginCatalogError):
                catalog.prepare_tool_run(candidate["candidate_id"])
            approved = catalog.approve(candidate["candidate_id"])
            configured = catalog.configure_launcher(
                approved["candidate_id"],
                {
                    "executable": sys.executable,
                    "arguments": [str(root / "entry.py")],
                    "working_directory": str(root),
                    "timeout_seconds": 10,
                },
            )
            self.assertEqual(configured["launcher"]["executable"], str(Path(sys.executable).resolve()))
            self.assertEqual(catalog.prepare_tool_run(approved["candidate_id"])["plugin_id"], "test.plugin")
            (root / "entry.py").write_text("# changed entrypoint\n", encoding="utf-8")
            with self.assertRaises(PluginCatalogError):
                catalog.prepare_tool_run(approved["candidate_id"])
            changed_entrypoint = catalog.discover(root)[0]
            self.assertEqual(changed_entrypoint["state"], "discovered")
            approved = catalog.approve(changed_entrypoint["candidate_id"])
            (root / "manifest.json").write_text(
                (root / "manifest.json").read_text(encoding="utf-8").replace("0.1.0", "0.3.0"),
                encoding="utf-8",
            )
            with self.assertRaises(PluginCatalogError):
                catalog.prepare_tool_run(approved["candidate_id"])
            storage.close()

    def test_approved_llm_plugin_is_a_revalidated_provider_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            root.mkdir(parents=True)
            entrypoint = root / "entry.py"
            entrypoint.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'type': 'token', 'text': request['config'].get('prefix', 'ok')}), flush=True)\n"
                "print(json.dumps({'type': 'done'}), flush=True)\n",
                encoding="utf-8",
            )
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "test.llm-plugin",
                        "version": "0.1.0",
                        "capabilities": ["llm"],
                        "entrypoint": "entry.py",
                        "runtime": "external-process",
                        "config_schema": {
                            "type": "object",
                            "properties": {"prefix": {"type": "string"}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            storage = Storage()
            catalog = PluginCatalog(storage)
            candidate = catalog.discover(root)[0]
            approved = catalog.approve(candidate["candidate_id"])
            catalog.configure_launcher(
                approved["candidate_id"],
                {
                    "executable": sys.executable,
                    "arguments": [str(entrypoint)],
                    "working_directory": str(root),
                    "timeout_seconds": 10,
                },
            )
            provider = PluginLLMProvider(catalog, approved["candidate_id"])
            provider.configure({"prefix": "plugin-ok"})
            request = ChatRequest("session", [Message("user", "hello")])
            self.assertEqual("".join(provider.stream(request)), "plugin-ok")
            self.assertEqual(provider.info.status, "available")

            entrypoint.write_text(entrypoint.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            with self.assertRaises(PluginCatalogError):
                list(provider.stream(request))
            storage.close()

    def test_approved_multi_capability_plugin_adapters_use_the_same_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            root.mkdir(parents=True)
            entrypoint = root / "entry.py"
            entrypoint.write_text(
                "import base64, json, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "kind = request.get('type')\n"
                "if kind == 'chat':\n"
                "    print(json.dumps({'type': 'token', 'text': 'llm-ok'}), flush=True)\n"
                "    print(json.dumps({'type': 'done'}), flush=True)\n"
                "elif kind == 'asr':\n"
                "    print(json.dumps({'type': 'result', 'text': 'asr-ok'}), flush=True)\n"
                "elif kind == 'tts':\n"
                "    print(json.dumps({'type': 'audio', 'audio_base64': base64.b64encode(b'tts-ok').decode()}), flush=True)\n"
                "elif kind == 'vad':\n"
                "    print(json.dumps({'type': 'result', 'speech': True}), flush=True)\n"
                "elif kind == 'memory.list':\n"
                "    print(json.dumps({'items': [{'id': 'memory-1', 'character_id': request['character_id']}]}), flush=True)\n"
                "elif kind == 'memory.add':\n"
                "    print(json.dumps({'memory': request['memory']}), flush=True)\n"
                "elif kind == 'memory.delete':\n"
                "    print(json.dumps({'deleted': True}), flush=True)\n"
                "elif kind == 'vision.observe':\n"
                "    print(json.dumps({'type': 'result', 'summary': 'vision-ok'}), flush=True)\n"
                "else:\n"
                "    print(json.dumps({'type': 'error', 'message': 'unknown request'}), flush=True)\n",
                encoding="utf-8",
            )
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "test.multi-provider",
                        "version": "0.1.0",
                        "capabilities": ["llm", "asr", "tts", "vad", "memory", "vision"],
                        "entrypoint": "entry.py",
                        "runtime": "external-process",
                    }
                ),
                encoding="utf-8",
            )
            storage = Storage()
            try:
                catalog = PluginCatalog(storage)
                discovered = catalog.discover(root)[0]
                approved = catalog.approve(discovered["candidate_id"])
                catalog.configure_launcher(
                    approved["candidate_id"],
                    {
                        "executable": sys.executable,
                        "arguments": [str(entrypoint)],
                        "working_directory": str(root),
                        "timeout_seconds": 10,
                    },
                )
                candidate_id = approved["candidate_id"]
                self.assertEqual("llm-ok", "".join(PluginLLMProvider(catalog, candidate_id).stream(ChatRequest("s", [Message("user", "hi")]))))
                self.assertEqual("asr-ok", PluginASRProvider(catalog, candidate_id).transcribe(ASRRequest(b"audio")))
                self.assertEqual(b"tts-ok", PluginTTSProvider(catalog, candidate_id).synthesize(TTSRequest("speak")).audio)
                self.assertTrue(PluginVADProvider(catalog, candidate_id).detect(VADRequest(b"audio")))
                memory = PluginMemoryProvider(catalog, candidate_id)
                self.assertEqual("memory-1", memory.list_memories("sumika")[0]["id"])
                added = memory.add_memory(
                    memory_id="memory-2",
                    character_id="sumika",
                    category="preferences",
                    content="local",
                    source="test",
                    metadata={},
                )
                self.assertEqual("memory-2", added["id"])
                self.assertTrue(memory.delete_memory("memory-2"))
                self.assertEqual("vision-ok", PluginVisionProvider(catalog, candidate_id).summarize(VisionRequest("screen", b"image", "image/png")).summary)
            finally:
                storage.close()

    def test_revoking_registration_removes_provider_from_registry_and_module_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            self._write_plugin(root, capability="llm")
            storage = Storage()
            try:
                catalog = PluginCatalog(storage)
                candidate = catalog.discover(root)[0]
                approved = catalog.approve(candidate["candidate_id"])
                catalog.configure_launcher(
                    approved["candidate_id"],
                    {
                        "executable": sys.executable,
                        "arguments": [str(root / "entry.py")],
                        "working_directory": str(root),
                        "timeout_seconds": 10,
                    },
                )
                providers = ProviderRegistry()
                providers.register(FakeProvider())
                provider = PluginLLMProvider(catalog, approved["candidate_id"])
                providers.register(provider)
                modules = ModuleCatalog(storage, providers)
                modules.update("llm", enabled=True, implementation_id=provider.info.id)
                self.assertIn(provider.info.id, {item["id"] for item in modules.list()[0]["implementations"]})
                self.assertTrue(providers.unregister(provider.info.id))
                modules.refresh()
                setting = storage.get_module_setting("llm")
                self.assertEqual(setting["implementation_id"], "none")
                self.assertFalse(setting["enabled"])
            finally:
                storage.close()
