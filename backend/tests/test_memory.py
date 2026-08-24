import json
import sys
import unittest

from sumika_core.events import EventBus
from sumika_core.memory import MemoryRuntime, MemoryRuntimeError
from sumika_core.modules import ModuleCatalog
from sumika_core.providers import (
    CommandMemoryProvider,
    MemoryProviderRegistry,
    ProviderRegistry,
    SQLiteMemoryProvider,
)
from sumika_core.storage import Storage
from fixtures.providers import FakeMemoryProvider, FakeProvider


class MemoryProviderTests(unittest.TestCase):
    def test_sqlite_provider_lists_searches_and_deletes(self):
        storage = Storage()
        provider = SQLiteMemoryProvider(storage)
        provider.add_memory(
            memory_id="memory-1",
            character_id="sumika",
            category="preferences",
            content="喜欢绿茶",
            source="test",
            metadata={"confidence": 1},
        )
        self.assertEqual(len(provider.list_memories("sumika", query="绿茶")), 1)
        self.assertTrue(provider.delete_memory("memory-1"))
        self.assertEqual(provider.list_memories("sumika"), [])
        storage.close()

    def test_external_jsonl_memory_contract(self):
        code = (
            "import json,sys; "
            "request=json.loads(sys.stdin.readline()); "
            "kind=request['type']; "
            "print(json.dumps({'items':[{'id':'external-1','character_id':request.get('character_id','sumika'),'category':'preferences','content':'external memory','source':'external','metadata':{},'created_at':'now','updated_at':'now'}]}) if kind=='memory.list' else "
            "json.dumps({'memory':request['memory']}) if kind=='memory.add' else "
            "json.dumps({'deleted':True}),flush=True)"
        )
        provider = CommandMemoryProvider(sys.executable, ["-c", code])
        self.assertEqual(provider.list_memories("sumika")[0]["content"], "external memory")
        created = provider.add_memory(
            memory_id="memory-2",
            character_id="sumika",
            category="preferences",
            content="new",
            source="test",
            metadata={},
        )
        self.assertEqual(created["content"], "new")
        self.assertTrue(provider.delete_memory("memory-2"))


class MemoryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.storage.create_character("sumika", "Sumika", {})
        llm = ProviderRegistry()
        llm.register(FakeProvider("ok"))
        memories = MemoryProviderRegistry()
        memories.register(SQLiteMemoryProvider(self.storage))
        memories.register(FakeMemoryProvider())
        self.modules = ModuleCatalog(self.storage, llm, memory=memories)
        self.events = EventBus(self.storage)
        self.runtime = MemoryRuntime(self.storage, self.modules, memories, self.events)

    def tearDown(self):
        self.storage.close()

    def test_disabled_memory_rejects_writes_and_audit_redacts_content(self):
        with self.assertRaises(MemoryRuntimeError):
            self.runtime.add(character_id="sumika", category="preferences", content="secret")
        self.modules.update(
            "memory",
            enabled=True,
            implementation_id="sqlite-reference",
            config={"categories": ["preferences"]},
        )
        with self.assertRaises(MemoryRuntimeError):
            self.runtime.add(character_id="sumika", category="work", content="not allowed")
        memory = self.runtime.add(character_id="sumika", category="preferences", content="secret", source="test")
        self.assertEqual(self.runtime.list("sumika", query="sec")[0]["id"], memory["id"])
        event = next(item for item in self.storage.list_events() if item["event_type"] == "memory.created")
        self.assertNotIn("secret", json.dumps(event["payload"], ensure_ascii=False))
        self.assertTrue(self.runtime.delete(memory["id"]))


if __name__ == "__main__":
    unittest.main()
