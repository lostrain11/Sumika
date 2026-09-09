import ast
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from sumika_core.domain import contracts
from sumika_core.domain.contracts import (
    DOMAIN_SCHEMA_VERSION,
    Assistant,
    Capability,
    Device,
    DomainContractError,
    MemoryNamespace,
    Permission,
    ResourceRef,
    Scene,
    contract_from_dict,
)


class DomainContractTests(unittest.TestCase):
    def setUp(self):
        self.memory = MemoryNamespace("assistant-one", "assistant-one")
        self.assistant = Assistant("assistant-one", "character-one", "助手一", self.memory)
        self.avatar = ResourceRef("avatar-pack", "1.0.0", "avatar-one", "avatar")

    def test_all_contracts_have_versioned_json_round_trip(self):
        samples = (
            self.avatar,
            self.memory,
            replace(self.assistant, avatar=self.avatar),
            Scene("desk", ("assistant-one",), active_assistant_id="assistant-one"),
            Capability("vision", "vision"),
            Permission("assistant-one", "screen.read", "display-one"),
            Device("camera-one", "camera"),
        )
        for sample in samples:
            with self.subTest(kind=sample.kind):
                payload = json.loads(json.dumps(sample.to_dict(), ensure_ascii=False))
                self.assertEqual(payload["schema_version"], DOMAIN_SCHEMA_VERSION)
                self.assertEqual(contract_from_dict(payload), sample)

    def test_memory_is_private_and_immutable_by_default(self):
        self.assertEqual(self.memory.shared_with, ())
        with self.assertRaises(FrozenInstanceError):
            self.memory.shared_with = ("assistant-two",)
        explicit = replace(self.memory, shared_with=("assistant-two",))
        self.assertEqual(explicit.shared_with, ("assistant-two",))
        self.assertEqual(self.memory.shared_with, ())

    def test_memory_owner_cannot_be_rebound_to_another_assistant(self):
        with self.assertRaises(DomainContractError):
            replace(self.assistant, assistant_id="assistant-two")
        for sharing in (("assistant-one",), ("assistant-two", "assistant-two"), ["assistant-two"]):
            with self.subTest(sharing=sharing), self.assertRaises(DomainContractError):
                replace(self.memory, shared_with=sharing)

    def test_resource_references_do_not_invent_versions_or_accept_paths(self):
        for field_name, value in (
            ("version", "unknown"), ("version", "latest"),
            ("asset_id", "../avatar.vrm"), ("asset_id", "D:\\assets\\avatar.vrm"),
            ("package_id", "https://example.invalid/pack"), ("resource_kind", "script"),
        ):
            with self.subTest(field=field_name), self.assertRaises(DomainContractError):
                replace(self.avatar, **{field_name: value})
        with self.assertRaises(DomainContractError):
            replace(self.assistant, voice=self.avatar)

    def test_scene_separates_pet_drawers_and_assistant_membership(self):
        scene = Scene("desk", ("assistant-one", "assistant-two"), active_assistant_id="assistant-one")
        self.assertEqual(replace(scene, mode="pet").drawer, None)
        for changes in (
            {"assistant_ids": ("assistant-one", "assistant-one")},
            {"active_assistant_id": "missing"}, {"mode": "unknown"},
            {"mode": "pet", "drawer": "settings"}, {"drawer": "duplicate-provider-page"},
            {"background": self.avatar},
        ):
            with self.subTest(changes=changes), self.assertRaises(DomainContractError):
                replace(scene, **changes)

    def test_world_close_policy_is_paused_and_catch_up_is_bounded(self):
        scene = Scene("room", mode="home")
        self.assertTrue(scene.pause_when_closed)
        self.assertEqual(scene.resume_budget_seconds, 0)
        self.assertEqual(replace(scene, resume_budget_seconds=300).resume_budget_seconds, 300)
        for changes in ({"pause_when_closed": False}, {"resume_budget_seconds": True},
                        {"resume_budget_seconds": -1}, {"resume_budget_seconds": 301}):
            with self.subTest(changes=changes), self.assertRaises(DomainContractError):
                replace(scene, **changes)

    def test_capability_visibility_is_not_permission_or_readiness(self):
        ready = Capability("vision", "vision", "vision-local", True, "ready", ("screen.read",))
        self.assertTrue(ready.visible)
        self.assertFalse(replace(ready, enabled=False, state="disabled").visible)
        self.assertFalse(replace(ready, state="unconfigured").visible)
        self.assertTrue(replace(ready, state="error").visible)
        self.assertEqual(replace(ready, state="unknown").state, "unknown")
        self.assertEqual(ready.required_permissions, ("screen.read",))
        for changes in ({"enabled": "false"}, {"implementation_id": None}, {"enabled": False}):
            with self.subTest(changes=changes), self.assertRaises(DomainContractError):
                replace(ready, **changes)

    def test_permission_defaults_to_unknown_and_grant_requires_evidence(self):
        permission = Permission("assistant-one", "screen.read", "display-one")
        self.assertEqual(permission.state, "unknown")
        self.assertEqual(permission.scope, "once")
        with self.assertRaises(DomainContractError):
            replace(permission, state="granted")
        observed = replace(permission, state="granted", evidence_id="receipt-one")
        self.assertEqual(observed.evidence_id, "receipt-one")
        for changes in ({"scope": "all-devices"}, {"resource_id": "*"}, {"state": "allow"}):
            with self.subTest(changes=changes), self.assertRaises(DomainContractError):
                replace(permission, **changes)

    def test_devices_do_not_enable_remote_or_motion_capabilities(self):
        device = Device("camera-one", "camera")
        self.assertEqual(device.state, "unconfigured")
        self.assertTrue(device.read_only)
        self.assertFalse(device.remote_enabled)
        for changes in ({"read_only": False}, {"remote_enabled": True}, {"transport": "internet"},
                        {"device_kind": "car"}, {"remote_enabled": 0}, {"read_only": 1}):
            with self.subTest(changes=changes), self.assertRaises(DomainContractError):
                replace(device, **changes)

    def test_invalid_wire_types_versions_and_unknown_fields_fail_closed(self):
        payload = self.assistant.to_dict()
        invalid = [None, [], {}, {**payload, "schema_version": "sumika.domain/v2"},
                   {**payload, "kind": []}, {**payload, "api_key": "not-a-real-credential"},
                   {**payload, "memory": self.avatar.to_dict()}, {**payload, "memory": None}]
        missing = dict(payload)
        del missing["character_id"]
        invalid.append(missing)
        for sample in invalid:
            with self.subTest(sample=sample), self.assertRaises(DomainContractError):
                contract_from_dict(sample)
        memory = self.memory.to_dict()
        for shared in ("assistant-two", None, list(range(65))):
            with self.subTest(shared=shared), self.assertRaises(DomainContractError):
                contract_from_dict({**memory, "shared_with": shared})

    def test_identifiers_fail_without_echoing_sensitive_values(self):
        sensitive = "D:\\private\\not-a-real-credential"
        with self.assertRaises(DomainContractError) as raised:
            replace(self.assistant, assistant_id=sensitive)
        self.assertNotIn(sensitive, str(raised.exception))
        for value in (True, [], "", "a" * 161, "../one", "one\n"):
            with self.subTest(value=value), self.assertRaises(DomainContractError):
                MemoryNamespace(value, "assistant-one")

    def test_serialized_nested_state_cannot_mutate_original(self):
        payload = self.assistant.to_dict()
        payload["memory"]["shared_with"].append("assistant-two")
        self.assertEqual(self.assistant.memory.shared_with, ())

    def test_domain_package_has_no_runtime_provider_or_storage_imports(self):
        for source in Path(contracts.__file__).parent.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name, {"re"})
                elif isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module, {"__future__", "dataclasses", "typing", "contracts"})


if __name__ == "__main__":
    unittest.main()
