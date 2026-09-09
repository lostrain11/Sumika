import copy
import json
import unittest

from sumika_core.domain.contracts import DomainContractError, Scene
from sumika_core.domain.projections import (
    assistant_from_character,
    assistants_from_characters,
    capability_from_module,
)
from sumika_core.events import EventBus
from sumika_core.memory import MemoryRuntime
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import MemoryProviderRegistry, ProviderRegistry, SQLiteMemoryProvider
from sumika_core.storage import Storage


class DomainProjectionTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.addCleanup(self.storage.close)
        self.modules = ModuleCatalog(self.storage, ProviderRegistry())

    def test_existing_characters_project_without_migration_or_private_config(self):
        original = self.storage.create_character("one", "助手一", {
            "avatar_model_id": "legacy-vrm",
            "persona": {"system_prompt": "private-persona-fixture"},
            "avatar_path": "D:\\private\\avatar.vrm",
            "api_key": "not-a-real-credential",
        })
        before = copy.deepcopy(original)
        assistant = assistant_from_character(original)
        self.assertEqual(assistant.assistant_id, original["id"])
        self.assertEqual(assistant.character_id, original["id"])
        self.assertEqual(assistant.legacy_avatar_id, "legacy-vrm")
        self.assertIsNone(assistant.avatar)
        self.assertIsNone(assistant.voice)
        self.assertEqual(assistant.memory.namespace_id, "one")
        self.assertEqual(assistant.memory.shared_with, ())
        serialized = json.dumps(assistant.to_dict())
        for sensitive in ("system_prompt", "private-persona-fixture", "avatar_path", "api_key", "not-a-real-credential"):
            self.assertNotIn(sensitive, serialized)
        self.assertEqual(original, before)
        self.assertEqual(self.storage.get_character("one"), before)

    def test_two_assistants_share_scene_but_not_actual_memory(self):
        for character_id in ("one", "two"):
            self.storage.create_character(character_id, character_id)
        providers = MemoryProviderRegistry()
        providers.register(SQLiteMemoryProvider(self.storage))
        modules = ModuleCatalog(self.storage, ProviderRegistry(), memory=providers)
        modules.update("memory", enabled=True, implementation_id="sqlite-reference", config={"categories": ["preferences"]})
        runtime = MemoryRuntime(self.storage, modules, providers, EventBus(self.storage))
        runtime.add(character_id="one", category="preferences", content="first private fixture")
        runtime.add(character_id="two", category="preferences", content="second private fixture")
        assistants = assistants_from_characters(self.storage.list_characters())
        scene = Scene("shared-room", tuple(assistant.assistant_id for assistant in assistants))
        self.assertEqual(scene.assistant_ids, ("one", "two"))
        self.assertNotEqual(assistants[0].memory, assistants[1].memory)
        self.assertEqual([item["content"] for item in runtime.list("one")], ["first private fixture"])
        self.assertEqual([item["content"] for item in runtime.list("two")], ["second private fixture"])

    def test_duplicate_or_malformed_legacy_ids_are_not_silently_merged(self):
        record = {"id": "one", "name": "One", "config": {}}
        with self.assertRaises(DomainContractError):
            assistants_from_characters((record, record))
        for invalid in (None, {**record, "id": "../one"}, {**record, "config": []},
                        {**record, "config": {"avatar_model_id": False}}):
            with self.subTest(invalid=invalid), self.assertRaises(DomainContractError):
                assistant_from_character(invalid)
        with self.assertRaises(DomainContractError):
            assistants_from_characters({"id": f"char-{index}", "name": "Name"} for index in range(65))

    def test_real_module_catalog_projects_without_enabling_or_changing_config(self):
        records = self.modules.list()
        before = copy.deepcopy(records)
        projected = [capability_from_module(record) for record in records]
        self.assertEqual(len(projected), len(records))
        for record, capability in zip(records, projected):
            self.assertEqual(record["id"], capability.module_id)
            self.assertEqual(record["enabled"], capability.enabled)
            if not record["enabled"]:
                self.assertFalse(capability.visible)
            self.assertNotIn("config", capability.to_dict())
        self.assertEqual(records, before)
        self.assertEqual(self.modules.list(), before)

    def test_module_statuses_do_not_upgrade_unknown_or_disabled_to_ready(self):
        base = {"id": "vision", "capability": "vision", "implementation_id": "vision-local",
                "enabled": True, "permissions": ["screen.read", "camera.read"],
                "config": {"executable": "private-path-fixture"}}
        for status, expected in (("available", "ready"), ("error", "error"),
                                 ("unconfigured", "unconfigured"), ("preview", "unknown"),
                                 ("needs-auth", "unknown"), ("surprising", "unknown")):
            with self.subTest(status=status):
                capability = capability_from_module({**base, "status": status})
                self.assertEqual(capability.state, expected)
                self.assertEqual(capability.required_permissions, ("screen.read", "camera.read"))
                self.assertNotIn("private-path-fixture", json.dumps(capability.to_dict()))
        disabled = capability_from_module({**base, "enabled": False, "status": "ready"})
        self.assertEqual(disabled.state, "disabled")
        self.assertFalse(disabled.visible)
        missing = capability_from_module({**base, "implementation_id": "none", "status": "ready"})
        self.assertEqual(missing.state, "unconfigured")
        self.assertFalse(missing.visible)

    def test_malformed_module_records_fail_without_truthy_string_enablement(self):
        for invalid in (None, {}, {"enabled": "false"}, {"enabled": True, "permissions": "screen.read"}):
            with self.subTest(invalid=invalid), self.assertRaises(DomainContractError):
                capability_from_module(invalid)


if __name__ == "__main__":
    unittest.main()
