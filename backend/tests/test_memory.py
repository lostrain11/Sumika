import json
import sys
import unittest
from typing import Any

from sumika_core.events import EventBus
from sumika_core.memory import MemoryRuntime, MemoryRuntimeError
from sumika_core.memory.contracts import MEMORY_BASE_CAPABILITIES, MemoryContractError
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import CommandMemoryProvider, MemoryProvider, MemoryProviderRegistry, ProviderRegistry, SQLiteMemoryProvider
from sumika_core.protocol.models import ProviderInfo
from sumika_core.storage import Storage
from fixtures.providers import FakeProvider


class FixtureMemoryProvider(MemoryProvider):
    capabilities = MEMORY_BASE_CAPABILITIES | frozenset({"scoped_delete"})
    legacy_record_compatibility = True

    def __init__(self, *, capabilities: frozenset[str] | None = None) -> None:
        if capabilities is not None:
            self.capabilities = capabilities
        self.info = ProviderInfo(id="fixture-memory", name="Fixture memory", capability="memory")
        self.calls: list[str] = []
        self.records: dict[str, dict[str, Any]] = {}
        self.list_override: list[dict[str, Any]] | None = None
        self.failure: Exception | None = None

    def list_memories(self, assistant_id: str, *, category: str | None = None, query: str | None = None, limit: int = 100):
        self.calls.append("list")
        if self.failure:
            raise self.failure
        if self.list_override is not None:
            return list(self.list_override)
        return [
            dict(record)
            for record in self.records.values()
            if record.get("character_id") == assistant_id and (category is None or record.get("category") == category)
        ][:limit]

    def add_memory(
        self,
        *,
        memory_id: str,
        assistant_id: str,
        category: str,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append("add")
        record = {
            "id": memory_id,
            "character_id": assistant_id,
            "category": category,
            "content": content,
            "source": source,
            "metadata": dict(metadata),
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        self.records[memory_id] = record
        return dict(record)

    def delete_memory(self, memory_id: str, *, assistant_id: str) -> dict[str, Any]:
        self.calls.append("delete")
        record = self.records.get(memory_id)
        if record is None:
            return {"deleted": False, "memory_id": memory_id, "assistant_id": assistant_id, "status": "deleted"}
        if record.get("character_id") != assistant_id:
            raise MemoryContractError("Memory record is outside the requested assistant scope")
        del self.records[memory_id]
        return {"deleted": True, "memory_id": memory_id, "assistant_id": assistant_id, "status": "deleted"}


class MemoryProviderTests(unittest.TestCase):
    def test_sqlite_provider_projects_legacy_schema_to_contract(self):
        storage = Storage()
        storage.create_character("sumika", "Sumika", {})
        storage.create_character("other", "Other", {})
        provider = SQLiteMemoryProvider(storage)
        record = provider.add_memory(
            memory_id="memory-1",
            assistant_id="sumika",
            category="preferences",
            content="green tea",
            source="test",
            metadata={"confidence": 1},
        )
        self.assertEqual(record["assistant_id"], "sumika")
        self.assertEqual(record["character_id"], "sumika")
        self.assertEqual(record["revision"], 1)
        self.assertEqual(record["status"], "active")
        self.assertEqual(len(provider.list_memories("sumika", query="tea")), 1)
        self.assertTrue(provider.delete_memory("memory-1", assistant_id="sumika")["deleted"])
        provider.add_memory(
            memory_id="memory-2",
            assistant_id="other",
            category="preferences",
            content="private",
            source="test",
            metadata={},
        )
        with self.assertRaises(MemoryContractError):
            provider.delete_memory("memory-2", assistant_id="sumika")
        storage.close()

    def test_external_jsonl_memory_contract_carries_scope(self):
        code = (
            "import json,sys; "
            "request=json.loads(sys.stdin.readline()); "
            "scope=request.get('assistant_id') or request.get('character_id','sumika'); "
            "kind=request['type']; "
            "record={'id':'external-1','assistant_id':scope,'character_id':scope,'category':'preferences','content':'external memory','source':'external','metadata':{},'created_at':'now','updated_at':'now'}; "
            "print(json.dumps({'items':[record]}) if kind=='memory.list' else json.dumps({'memory':request['memory']}) if kind=='memory.add' else json.dumps({'deleted':True,'memory_id':request['memory_id'],'assistant_id':scope,'status':'deleted'}),flush=True)"
        )
        provider = CommandMemoryProvider(sys.executable, ["-c", code])
        self.assertEqual(provider.list_memories("sumika")[0]["assistant_id"], "sumika")
        created = provider.add_memory(
            memory_id="memory-2",
            assistant_id="sumika",
            category="preferences",
            content="new",
            source="test",
            metadata={},
        )
        self.assertEqual(created["assistant_id"], "sumika")
        self.assertTrue(provider.delete_memory("memory-2", assistant_id="sumika")["deleted"])


class MemoryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.storage.create_character("sumika", "Sumika", {})
        self.storage.create_character("other", "Other", {})
        llm = ProviderRegistry()
        llm.register(FakeProvider("ok"))
        self.provider = FixtureMemoryProvider()
        memories = MemoryProviderRegistry()
        memories.register(self.provider)
        self.modules = ModuleCatalog(self.storage, llm, memory=memories)
        self.events = EventBus(self.storage)
        self.runtime = MemoryRuntime(self.storage, self.modules, memories, self.events)

    def tearDown(self):
        self.storage.close()

    def enable_fixture(self):
        self.modules.update(
            "memory",
            enabled=True,
            implementation_id="fixture-memory",
            config={"categories": ["preferences"]},
        )

    def test_disabled_module_makes_zero_provider_calls(self):
        self.runtime.status()
        for operation in (
            lambda: self.runtime.list("sumika"),
            lambda: self.runtime.add(character_id="sumika", category="preferences", content="secret"),
            lambda: self.runtime.delete("memory-1", assistant_id="sumika"),
        ):
            with self.assertRaises(MemoryRuntimeError):
                operation()
        self.assertEqual(self.provider.calls, [])

    def test_legacy_character_id_maps_to_stable_assistant_id_and_audits_without_content(self):
        self.enable_fixture()
        memory = self.runtime.add(character_id="sumika", category="preferences", content="secret", source="test")
        self.assertEqual(memory["assistant_id"], "sumika")
        self.assertEqual(memory["character_id"], "sumika")
        self.assertEqual(memory["revision"], 1)
        self.assertEqual(memory["status"], "active")
        self.assertEqual(self.runtime.list("sumika")[0]["id"], memory["id"])
        event = next(item for item in self.storage.list_events() if item["event_type"] == "memory.created")
        self.assertNotIn("secret", json.dumps(event["payload"]))
        self.assertTrue(self.runtime.delete(memory["id"], assistant_id="sumika"))

    def test_mismatched_identity_and_foreign_provider_record_are_rejected(self):
        self.enable_fixture()
        with self.assertRaisesRegex(MemoryRuntimeError, "must equal legacy"):
            self.runtime.list(assistant_id="sumika", character_id="other")
        self.provider.list_override = [
            {
                "id": "foreign",
                "assistant_id": "other",
                "category": "preferences",
                "content": "private",
                "source": "fixture",
                "metadata": {},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]
        with self.assertRaisesRegex(MemoryRuntimeError, "outside the requested assistant scope"):
            self.runtime.list("sumika")

    def test_inactive_or_unscoped_provider_results_are_migration_failures(self):
        self.enable_fixture()
        self.provider.list_override = [
            {
                "id": "old-memory",
                "character_id": "sumika",
                "category": "preferences",
                "content": "legacy",
                "source": "fixture",
                "metadata": {},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]
        record = self.runtime.list("sumika")[0]
        self.assertEqual(record["assistant_id"], "sumika")
        self.assertEqual(record["revision"], 1)
        self.provider.list_override[0]["status"] = "deleted"
        with self.assertRaisesRegex(MemoryRuntimeError, "inactive record"):
            self.runtime.list("sumika")
        self.provider.list_override[0].pop("status")
        self.provider.legacy_record_compatibility = False
        with self.assertRaisesRegex(MemoryRuntimeError, "invalid record revision"):
            self.runtime.list("sumika")

    def test_missing_capability_is_explicit_and_provider_faults_are_redacted(self):
        self.enable_fixture()
        with self.assertRaisesRegex(MemoryRuntimeError, "context_sources"):
            self.runtime.context_sources(assistant_id="sumika")
        self.provider.failure = RuntimeError("credential=never-expose")
        with self.assertRaises(MemoryRuntimeError) as caught:
            self.runtime.list("sumika")
        self.assertEqual(str(caught.exception), "Memory provider failed")

    def test_delete_requires_scoped_delete_capability(self):
        self.provider.capabilities = MEMORY_BASE_CAPABILITIES
        self.enable_fixture()
        with self.assertRaisesRegex(MemoryRuntimeError, "scoped_delete"):
            self.runtime.delete("memory-1", assistant_id="sumika")


if __name__ == "__main__":
    unittest.main()
