"""User role import: the store, the asset attach step and the undo path."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

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

    def test_multifile_resources_keep_dependencies_through_export_restore(self):
        from extensions.roles.roles import export_package, import_package
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            source = Path(d) / 'community-model'
            (source / 'textures').mkdir(parents=True)
            (source / 'model.model3.json').write_text('{"texture":"textures/face.png"}', encoding='utf8')
            (source / 'textures/face.png').write_bytes(b'local-texture')
            for kind in ('model_2d', 'voice', 'scene'):
                attached = attach_asset('imported-one', store, kind, source)
                with zipfile.ZipFile(attached) as bundle:
                    self.assertEqual(set(bundle.namelist()), {'model.model3.json', 'textures/face.png'})
                    self.assertEqual(bundle.read('textures/face.png'), b'local-texture')
            exported = export_package('imported-one', store, Path(d) / 'export.zip')
            restored = load_role(import_package(exported, Path(d) / 'restored'))
            self.assertEqual(restored['verified']['status'], 'ok')
            for kind in ('model_2d', 'voice', 'scene'):
                with zipfile.ZipFile(restored['assets'][kind]) as bundle:
                    self.assertEqual(bundle.read('textures/face.png'), b'local-texture')
            self.assertTrue((source / 'model.model3.json').is_file())

    def test_failed_resource_update_preserves_original_bytes_and_verification(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            model = Path(d) / 'model.vrm'; model.write_bytes(b'original')
            old = attach_asset('imported-one', store, 'model_3d', model)
            role = store / 'imported-one'
            before = {p.relative_to(role): p.read_bytes() for p in role.rglob('*') if p.is_file()}
            model.write_bytes(b'replacement')
            with patch('extensions.roles.roles._refresh_checksums', side_effect=OSError('simulated disk failure')):
                with self.assertRaises(OSError): attach_asset('imported-one', store, 'model_3d', model)
            self.assertEqual({p.relative_to(role): p.read_bytes() for p in role.rglob('*') if p.is_file()}, before)
            self.assertEqual(old.read_bytes(), b'original')
            self.assertEqual(verify_role(role)['status'], 'ok')
            # Re-importing an existing declared file used to overwrite itself.
            new = attach_asset('imported-one', store, 'model_3d', old)
            self.assertEqual(new.read_bytes(), b'original')

    def test_empty_recursive_and_excessive_asset_directories_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store_with_card(d)
            empty = Path(d) / 'empty'; empty.mkdir()
            for source in (empty, store, store / 'imported-one'):
                with self.assertRaises(ValueError): attach_asset('imported-one', store, 'scene', source)
            source = Path(d) / 'large'; source.mkdir()
            for i in range(991): (source / f'{i}.bin').write_bytes(b'x')
            with self.assertRaises(ValueError): attach_asset('imported-one', store, 'voice', source)
            self.assertEqual(load_role(store / 'imported-one')['verified']['status'], 'ok')

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
