import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sumika_core.protocol.models import Message
from sumika_core.storage import Storage


class StorageTests(unittest.TestCase):
    def test_application_metadata_round_trips_outside_user_tables(self):
        storage = Storage()
        self.assertIsNone(storage.get_meta("bootstrap.test"))
        storage.set_meta("bootstrap.test", "done")
        self.assertEqual(storage.get_meta("bootstrap.test"), "done")
        with self.assertRaises(ValueError):
            storage.set_meta("", "invalid")
        storage.close()

    def test_sessions_messages_events_and_snapshots(self):
        storage = Storage()
        storage.create_session("s1", "测试")
        storage.append_message("s1", Message("user", "你好"))
        self.assertEqual(storage.list_messages("s1")[0]["content"], "你好")
        storage.append_event({
            "event_id": "e1", "event_type": "test", "payload": {"ok": True},
            "session_id": "s1", "character_id": None, "correlation_id": "c1", "timestamp": "now",
        })
        self.assertTrue(storage.list_events())
        snapshot = storage.create_snapshot("snap", "before-change", {"value": 1})
        self.assertEqual(snapshot["payload"]["value"], 1)
        storage.close()

    def test_character_config_and_name_update_are_persisted(self):
        storage = Storage()
        storage.create_character("c1", "旧名称", {"language": "zh-CN"})
        updated = storage.update_character(
            "c1",
            name="新名称",
            config={"language": "ja-JP", "persona": {"greeting": "你好"}},
        )
        self.assertEqual(updated["name"], "新名称")
        self.assertEqual(updated["config"]["persona"]["greeting"], "你好")
        storage.close()

    def test_audio_permissions_are_versioned_and_persisted(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "sumika.sqlite3"
            storage = Storage(database)
            permission = storage.upsert_audio_permission("microphone", "granted")
            self.assertEqual(permission["state"], "granted")
            vision_permission = storage.upsert_vision_permission("screen.read", "granted")
            self.assertEqual(vision_permission["state"], "granted")
            storage.close()

            reopened = Storage(database)
            self.assertEqual(reopened.get_audio_permission("microphone")["state"], "granted")
            self.assertEqual(reopened.get_vision_permission("screen.read")["state"], "granted")
            reopened.create_memory(
                memory_id="memory-1",
                character_id="sumika",
                category="preferences",
                content="本地记忆",
                source="test",
                metadata={},
            )
            self.assertEqual(reopened.list_memories("sumika")[0]["content"], "本地记忆")
            reopened.close()

    def test_snapshot_state_diff_and_restore_are_atomic(self):
        storage = Storage()
        storage.create_character("sumika", "Sumika", {"language": "zh-CN"})
        storage.upsert_module_setting("memory", enabled=True, implementation_id="sqlite-reference", config={})
        storage.create_memory(
            memory_id="memory-1",
            character_id="sumika",
            category="preferences",
            content="恢复前内容",
            source="test",
            metadata={},
        )
        payload = storage.export_snapshot_state("system")
        storage.update_character("sumika", name="已修改")
        storage.delete_memory("memory-1")
        diff = storage.diff_snapshot_state(payload)
        self.assertTrue(diff["changed"])
        self.assertGreaterEqual(next(item for item in diff["tables"] if item["table"] == "characters")["changed"], 1)
        restored = storage.restore_snapshot_state(payload)
        self.assertEqual(restored["scope"], "system")
        self.assertEqual(storage.get_character("sumika")["name"], "Sumika")
        self.assertEqual(storage.get_memory("memory-1")["content"], "恢复前内容")
        snapshot = storage.create_snapshot("snap-1", "系统快照", payload)
        self.assertEqual(storage.get_snapshot("snap-1")["id"], snapshot["id"])
        self.assertEqual(storage.list_snapshots()[0]["scope"], "system")
        storage.close()

    def test_targeted_snapshot_only_restores_selected_record(self):
        storage = Storage()
        storage.create_character("one", "一号", {})
        storage.create_character("two", "二号", {})
        payload = storage.export_snapshot_state("characters", "one")
        storage.update_character("one", name="一号·修改")
        storage.update_character("two", name="二号·修改")
        storage.restore_snapshot_state(payload)
        self.assertEqual(storage.get_character("one")["name"], "一号")
        self.assertEqual(storage.get_character("two")["name"], "二号·修改")
        invalid = {**payload, "tables": {"characters": [{**payload["tables"]["characters"][0], "id": "two"}]}}
        with self.assertRaises(ValueError):
            storage.restore_snapshot_state(invalid)
        storage.close()

    def test_named_browser_profiles_are_snapshotable_without_leases(self):
        storage = Storage()
        profile = storage.create_browser_profile(
            profile_id="browser-profile-1",
            name="持久浏览器",
            character_id="sumika",
            agent_id=None,
        )
        storage.acquire_browser_profile_lease(
            profile_id=profile["id"],
            lease_id="lease-1",
            owner_token="owner-1",
            expires_at="2999-01-01T00:00:00+00:00",
        )
        payload = storage.export_snapshot_state("modules")
        self.assertEqual(payload["tables"]["browser_profiles"][0]["id"], profile["id"])
        self.assertNotIn("browser_profile_leases", payload["tables"])
        storage.update_browser_profile_state(profile["id"], archived=True)
        storage.restore_snapshot_state(payload)
        self.assertEqual(storage.get_browser_profile(profile["id"])["status"], "active")
        self.assertIsNotNone(storage.get_browser_profile_lease(profile["id"]))
        storage.close()
