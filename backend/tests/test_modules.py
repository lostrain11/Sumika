import sys
import unittest

from sumika_core.modules import ModuleCatalog, ModuleError
from sumika_core.providers import OpenAICompatibleProvider, ProviderRegistry
from sumika_core.storage import Storage
from fixtures.providers import FakeProvider


class ModuleCatalogTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.providers = ProviderRegistry()
        self.providers.register(FakeProvider("默认回复"))
        self.providers.register(OpenAICompatibleProvider())
        self.catalog = ModuleCatalog(self.storage, self.providers)

    def tearDown(self):
        self.storage.close()

    def test_defaults_expose_capabilities_and_implementations(self):
        modules = {module["id"]: module for module in self.catalog.list()}
        self.assertTrue(modules["llm"]["enabled"])
        self.assertEqual(modules["llm"]["implementation_id"], "openai-compatible")
        self.assertFalse(modules["memory"]["enabled"])
        self.assertIn("sqlite-reference", {item["id"] for item in modules["memory"]["implementations"]})

    def test_update_persists_profile_reference_and_rejects_inline_secrets(self):
        result = self.catalog.update(
            "llm",
            implementation_id="openai-compatible",
            config={"profile_id": "local-test"},
        )
        self.assertEqual(result["config"], {"profile_id": "local-test"})
        with self.assertRaisesRegex(ModuleError, "profile_id"):
            self.catalog.update(
                "llm",
                implementation_id="openai-compatible",
                config={"profile_id": "local-test", "api_key": "must-not-persist"},
            )

        memory = self.catalog.update("memory", enabled=True, implementation_id="sqlite-reference", config={"categories": ["work"]})
        self.assertTrue(memory["enabled"])
        self.assertEqual(self.storage.get_module_setting("memory")["config"], {"categories": ["work"]})

    def test_disabling_llm_is_persisted(self):
        self.catalog.update("llm", enabled=False)
        self.assertFalse(self.catalog.is_enabled("llm"))

    def test_external_tool_config_validates_timeout_and_argument_types(self):
        with self.assertRaisesRegex(ModuleError, "above maximum"):
            self.catalog.update(
                "tools",
                implementation_id="external-process",
                config={"executable": sys.executable, "timeout_seconds": 121},
            )
        with self.assertRaisesRegex(ModuleError, "array items"):
            self.catalog.update(
                "tools",
                implementation_id="external-process",
                config={"executable": sys.executable, "arguments": [1]},
            )

    def test_refresh_disables_selection_when_external_implementation_disappears(self):
        self.catalog.update("llm", enabled=True, implementation_id="openai-compatible", config={})
        self.storage.upsert_module_setting("llm", enabled=True, implementation_id="missing-plugin", config={"stale": True})
        self.catalog.refresh()
        setting = self.storage.get_module_setting("llm")
        self.assertEqual(setting["implementation_id"], "openai-compatible")
        self.assertFalse(setting["enabled"])
        self.assertEqual(setting["config"], {})
