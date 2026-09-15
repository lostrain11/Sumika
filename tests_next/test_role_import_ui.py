"""User role import: the store, the asset attach step and the undo path."""
import json
from pathlib import Path
import tempfile
import unittest

from extensions.roles.roles import (attach_asset, import_card, list_roles, load_role,
                                    remove_role, verify_role)

CARD = {
    "spec": "chara_card_v2",
    "data": {
        "name": "导入测试角色",
        "description": "仅用于导入流程测试",
        "personality": "简洁",
        "scenario": "测试",
        "character_book": {"entries": [{"keys": ["测试"], "content": "条目"}]},
    },
}


class RoleImportTests(unittest.TestCase):
    def _store_with_card(self, directory):
        store = Path(directory) / "roles"
        card = Path(directory) / "card.json"
        card.write_text(json.dumps(CARD, ensure_ascii=False), encoding="utf8")
        import_card(card, store, "imported-one")
        return store

    def test_imported_role_is_listed_as_user_with_its_card(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            listed = {item["id"]: item for item in list_roles(Path(d) / "empty", store)}
            self.assertIn("imported-one", listed)
            self.assertEqual(listed["imported-one"]["kind"], "user")
            role = load_role(store / "imported-one")
            self.assertEqual(role["name"], "导入测试角色")
            self.assertIn("card", role["assets"])

    def test_attaching_a_model_keeps_verification_ok(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            model = Path(d) / "model.vrm"
            model.write_bytes(b"vrm-placeholder-bytes")
            target = attach_asset("imported-one", store, "model_3d", model)
            self.assertTrue(target.is_file())
            role = load_role(store / "imported-one")
            self.assertIn("model_3d", role["assets"])
            # The declared asset has to be inside the checksum manifest, otherwise
            # verification would fail for a file we just placed ourselves.
            self.assertEqual(role["verified"]["status"], "ok")
            self.assertEqual(verify_role(store / "imported-one")["status"], "ok")

    def test_asset_and_role_paths_are_confined_to_the_store(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            outside = Path(d) / "outside.txt"
            outside.write_text("x", encoding="utf8")
            with self.assertRaises(ValueError):
                attach_asset("../escape", store, "model_3d", outside)
            with self.assertRaises(ValueError):
                attach_asset("imported-one", store, "not-a-kind", outside)
            with self.assertRaises(ValueError):
                remove_role("../escape", store)

    def test_remove_role_only_deletes_the_named_user_role(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            remove_role("imported-one", store)
            self.assertFalse((store / "imported-one").exists())
            with tempfile.TemporaryDirectory() as keep:
                other = self._store_with_card(keep)
                self.assertTrue((other / "imported-one").is_dir())


if __name__ == "__main__":
    unittest.main()
