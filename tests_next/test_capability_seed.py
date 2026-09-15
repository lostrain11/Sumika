"""First-run capability registry seeding.

The registry is what gates every device/desktop operation, so the seed has to
reflect what this machine can actually serve and must never rewrite a registry
the user has already configured.
"""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from extensions.capabilities import CapabilityStore
from ui import readiness
from ui.server import Bridge


class ServiceCapabilityTests(unittest.TestCase):
    def test_only_available_providers_are_registered(self):
        with mock.patch.object(readiness, "_resolve", return_value=([], "")):
            with mock.patch.object(readiness.shutil, "which", return_value=None):
                with mock.patch.object(readiness.platform, "system", return_value="Linux"):
                    with mock.patch.object(readiness, "_module", return_value=False):
                        with mock.patch.object(readiness, "_rapidocr_json", return_value=None):
                            with mock.patch.object(readiness, "soffice_path", return_value=None):
                                self.assertEqual(readiness.service_capabilities(), [])

    def test_entries_carry_the_options_their_providers_require(self):
        def resolve(_root, packages, _envs):
            return (list(packages), "test")

        with mock.patch.object(readiness, "_resolve", side_effect=resolve):
            with mock.patch.object(readiness.platform, "system", return_value="Windows"):
                with mock.patch.object(readiness, "_module", return_value=True):
                    with mock.patch.object(readiness, "voice_model",
                                           return_value=Path("C:/voice-models/zh")):
                        with mock.patch.object(readiness, "soffice_path",
                                               return_value=r"D:\Tools\LibreOffice\soffice.exe"):
                            entries = readiness.service_capabilities()
        by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(by_id["ocr"]["provider"], "rapidocr")
        self.assertEqual(by_id["desktop"]["provider"], "windows-uia")
        self.assertEqual(by_id["asr"]["options"]["model"], str(Path("C:/voice-models/zh")))
        self.assertEqual(by_id["office-render"]["options"]["executable"],
                         r"D:\Tools\LibreOffice\soffice.exe")
        for entry in entries:
            self.assertIs(entry["enabled"], True)


class BootstrapTests(unittest.TestCase):
    def _bridge(self, database):
        # The bridge owns the workbench controller, so give it a throwaway root.
        with tempfile.TemporaryDirectory() as workspace:
            return Bridge(settings_path=Path(workspace) / "settings.json",
                          capability_database=database,
                          workbench_root=workspace,
                          schedule_directory=Path(workspace) / "schedules")

    def test_first_start_seeds_the_registry(self):
        with tempfile.TemporaryDirectory() as d:
            database = Path(d) / "capabilities.db"
            entries = [{"id": "ocr", "provider": "rapidocr", "enabled": True, "options": {}},
                       {"id": "asr", "provider": "vosk", "enabled": True,
                        "options": {"model": "C:/voice-models/zh"}}]
            with mock.patch("ui.server.service_capabilities", return_value=entries):
                bridge = self._bridge(database)
            self.assertIsNotNone(bridge)
            store = CapabilityStore(str(database))
            try:
                listed = store.list()
                self.assertEqual([item["id"] for item in listed], ["ocr", "asr"])
                self.assertEqual(listed[1]["options"]["model"], "C:/voice-models/zh")
                # A seeded capability resolves, so the service can actually run it.
                self.assertEqual(store.resolve("ocr")["provider"], "rapidocr")
                store.configure("ocr", "rapidocr", enabled=False)
                with self.assertRaises(PermissionError):
                    store.resolve("ocr")
            finally:
                store.close()

    def test_existing_registry_is_never_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            database = Path(d) / "capabilities.db"
            store = CapabilityStore(str(database))
            store.configure("ocr", "tesseract", enabled=False)
            store.close()
            with mock.patch("ui.server.service_capabilities",
                            return_value=[{"id": "ocr", "provider": "rapidocr",
                                           "enabled": True, "options": {}}]):
                self._bridge(database)
            store = CapabilityStore(str(database))
            try:
                listed = store.list()
            finally:
                store.close()
            self.assertEqual(listed[0]["provider"], "tesseract")
            self.assertIs(listed[0]["enabled"], False)

    def test_bootstrap_adds_only_capabilities_that_are_missing(self):
        with tempfile.TemporaryDirectory() as d:
            database = Path(d) / "capabilities.db"
            store = CapabilityStore(str(database))
            store.configure("ocr", "tesseract", enabled=False)
            store.close()
            with mock.patch("ui.server.service_capabilities", return_value=[
                {"id": "ocr", "provider": "rapidocr", "enabled": True, "options": {}},
                {"id": "asr", "provider": "vosk", "enabled": True,
                 "options": {"model": "C:/voice-models/zh"}},
            ]):
                self._bridge(database)
            store = CapabilityStore(str(database))
            try:
                listed = {item["id"]: item for item in store.list()}
            finally:
                store.close()
            self.assertEqual(sorted(listed), ["asr", "ocr"])
            self.assertEqual(listed["ocr"]["provider"], "tesseract")
            self.assertIs(listed["ocr"]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
