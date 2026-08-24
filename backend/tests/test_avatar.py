import json
import tempfile
import unittest
from pathlib import Path

from sumika_core.avatar import AvatarError, AvatarManager
from sumika_core.avatar.manager import inspect_live2d_manifest
from sumika_core.storage import Storage


class AvatarManagerTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.storage.create_character("c1", "测试角色", {"avatar_driver": "none"})
        self.manager = AvatarManager(self.storage)

    def tearDown(self):
        self.storage.close()

    def test_import_is_metadata_only_and_selects_preview_driver(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "sumika.model3.json"
            model_path.write_text('{"FileReferences": {}}', encoding="utf-8")
            model = self.manager.import_model(str(model_path))
            self.assertEqual(model["kind"], "live2d")
            self.assertEqual(model["size_bytes"], model_path.stat().st_size)
            self.assertEqual(model["metadata"]["availability"], "available")
            result = self.manager.select("c1", model_id=model["id"], driver_id="live2d")
            self.assertEqual(result["state"]["driver"], "live2d")
            self.assertEqual(result["state"]["driver_status"], "preview")
            self.assertEqual(result["state"]["model"]["id"], model["id"])
            self.assertEqual(self.storage.get_character("c1")["config"]["avatar_model_id"], model["id"])

    def test_unsupported_files_and_mismatched_driver_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            unsupported = Path(directory) / "notes.txt"
            unsupported.write_text("not a model", encoding="utf-8")
            with self.assertRaises(AvatarError):
                self.manager.import_model(str(unsupported))
            vrm = Path(directory) / "sample.vrm"
            vrm.write_bytes(b"preview")
            model = self.manager.import_model(str(vrm))
            with self.assertRaises(AvatarError):
                self.manager.select("c1", model_id=model["id"], driver_id="live2d")

    def test_refresh_updates_metadata_without_loading_and_missing_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "sumika.model3.json"
            model_path.write_text("{}", encoding="utf-8")
            model = self.manager.import_model(str(model_path))
            model_path.write_text('{"updated": true}', encoding="utf-8")

            refreshed = self.manager.refresh_model(model["id"])
            self.assertEqual(refreshed["size_bytes"], model_path.stat().st_size)
            self.assertEqual(refreshed["metadata"]["availability"], "available")

            model_path.unlink()
            with self.assertRaises(AvatarError):
                self.manager.refresh_model(model["id"])
            self.assertIsNotNone(self.storage.get_avatar_model(model["id"]))

    def test_discover_directory_registers_supported_models_without_touching_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vrm_path = root / "sample.vrm"
            live2d_path = root / "character.model3.json"
            ignored_path = root / "preview.png"
            vrm_path.write_bytes(b"glTF")
            live2d_path.write_text("{}", encoding="utf-8")
            ignored_path.write_bytes(b"png")

            discovered = self.manager.discover_directory(root, metadata={"auto_discovered": True})

            self.assertEqual({model["kind"] for model in discovered}, {"vrm", "live2d"})
            self.assertTrue(all(model["metadata"]["auto_discovered"] for model in discovered))
            self.assertTrue(vrm_path.exists())
            self.assertTrue(live2d_path.exists())
            self.assertEqual(len(self.manager.discover_directory(root)), 2)

    def test_inspect_live2d_manifest_reports_references_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "character.model3.json"
            (root / "character.moc3").write_bytes(b"moc")
            (root / "texture.png").write_bytes(b"png")
            (root / "idle.motion3.json").write_text("{}", encoding="utf-8")
            manifest_path.write_text(
                '{"Version": 3, "FileReferences": {'
                '"Moc": "character.moc3", "Textures": ["texture.png"], '
                '"Physics": "missing.physics3.json", '
                '"Expressions": [{"Name": "smile", "File": "missing.exp3.json"}], '
                '"Motions": {"Idle": [{"File": "idle.motion3.json"}]}}}',
                encoding="utf-8",
            )

            inspection = inspect_live2d_manifest(manifest_path)

            self.assertTrue(inspection["valid"])
            self.assertEqual(inspection["status"], "warning")
            self.assertEqual(inspection["counts"], {"textures": 1, "motions": 1, "expressions": 1})
            self.assertEqual(inspection["model_file"], "character.moc3")
            self.assertEqual(len(inspection["referenced_files"]), 5)
            self.assertTrue(any("missing.physics3.json" in warning for warning in inspection["warnings"]))
            self.assertTrue(all("FileReferences" not in json.dumps(item) for item in inspection["referenced_files"]))

    def test_inspect_live2d_manifest_rejects_unsafe_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsafe_path = root / "unsafe.model3.json"
            unsafe_path.write_text(
                '{"FileReferences": {"Moc": "../outside.moc3"}}',
                encoding="utf-8",
            )
            unsafe = inspect_live2d_manifest(unsafe_path)
            self.assertFalse(unsafe["valid"])
            self.assertEqual(unsafe["status"], "error")
            self.assertFalse(unsafe["referenced_files"][0]["safe"])
            self.assertTrue(any("unsafe model reference" in error for error in unsafe["errors"]))

            invalid_path = root / "invalid.model3.json"
            invalid_path.write_text("{", encoding="utf-8")
            invalid = inspect_live2d_manifest(invalid_path)
            self.assertFalse(invalid["valid"])
            self.assertEqual(invalid["status"], "error")
            self.assertTrue(invalid["errors"])

    def test_unregister_is_blocked_while_bound_and_keeps_file(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "sumika.model3.json"
            model_path.write_text("{}", encoding="utf-8")
            model = self.manager.import_model(str(model_path))
            self.manager.select("c1", model_id=model["id"], driver_id="live2d")

            with self.assertRaisesRegex(AvatarError, "测试角色"):
                self.manager.unregister_model(model["id"])
            self.assertTrue(model_path.exists())

            self.manager.select("c1", model_id=None, driver_id="none")
            result = self.manager.unregister_model(model["id"])
            self.assertEqual(result["model"]["id"], model["id"])
            self.assertIsNone(self.storage.get_avatar_model(model["id"]))
            self.assertTrue(model_path.exists())

    def test_clear_selection_restores_null_driver(self):
        result = self.manager.select("c1", model_id=None, driver_id="none")
        self.assertEqual(result["state"]["driver"], "none")
        self.assertIsNone(self.storage.get_character("c1")["config"].get("avatar_model_id"))
