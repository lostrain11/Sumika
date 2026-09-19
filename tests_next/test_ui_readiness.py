import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ui import readiness


class ReadinessTests(unittest.TestCase):
    def _probes(self, folder, present_modules=(), tesseract=None):
        root = Path(folder)
        def fake_find_spec(name, *args, **kwargs):
            return object() if name in present_modules else None
        with patch("ui.readiness.importlib.util.find_spec", side_effect=fake_find_spec), \
                patch("ui.readiness.shutil.which", return_value=tesseract), \
                patch.dict("os.environ", {"SUMIKA_RAPIDOCR_JSON": str(Path(folder) / "missing-umi.exe")}), \
                patch("ui.readiness.platform.system", return_value="Windows"):
            return {row["id"]: row for row in readiness.probes(root, home=root)}

    def test_missing_dependencies_are_reported_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            rows = self._probes(d)
            self.assertFalse(rows["ocr"]["ready"])
            self.assertIn("未安装", rows["ocr"]["detail"])
            self.assertFalse(rows["voice"]["ready"])
            self.assertFalse(rows["browser"]["ready"])
            self.assertFalse(rows["desktop"]["ready"])
            self.assertFalse(rows["office"]["ready"])
            self.assertFalse(rows["memory-semantic"]["ready"])
            self.assertTrue(rows["schedule"]["ready"])
            self.assertEqual(set(rows), {"ocr", "voice", "browser", "desktop", "office",
                                        "camera", "memory-semantic", "schedule"})

    def test_present_dependencies_flip_only_their_own_capability(self):
        with tempfile.TemporaryDirectory() as d:
            rows = self._probes(d, present_modules=("rapidocr_onnxruntime", "vosk", "sounddevice",
                                                    "pywinauto", "docx", "cv2", "fastembed"))
            self.assertTrue(rows["ocr"]["ready"])
            self.assertFalse(rows["voice"]["ready"], "voice also needs a model directory")
            self.assertTrue(rows["desktop"]["ready"])
            self.assertTrue(rows["office"]["ready"])
            self.assertTrue(rows["camera"]["ready"])
            self.assertTrue(rows["memory-semantic"]["ready"])
            self.assertFalse(rows["browser"]["ready"])

    def test_browser_and_voice_depend_on_local_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "runtime" / "browserskill").mkdir(parents=True)
            (root / "runtime" / "browserskill" / "bsk.exe").write_bytes(b"stub")
            (root / ".sumika-next" / "voice-models" / "vosk-model-small-cn-0.22").mkdir(parents=True)
            rows = self._probes(root, present_modules=("vosk", "sounddevice"))
            self.assertTrue(rows["browser"]["ready"])
            self.assertTrue(rows["voice"]["ready"])
            self.assertIn("bsk.exe", rows["browser"]["detail"])

    def test_tesseract_binary_is_accepted_for_ocr(self):
        with tempfile.TemporaryDirectory() as d:
            rows = self._probes(d, tesseract="C:/tools/tesseract.exe")
            self.assertTrue(rows["ocr"]["ready"])
            self.assertIn("tesseract", rows["ocr"]["detail"])

    def test_isolated_extension_envs_count_as_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            layout = {"office-env": ("docx", "openpyxl", "pptx", "pymupdf-1.9.dist-info"),
                      "desktop-env": ("pywinauto-0.6.9.dist-info", "pywinctl-0.4.1.dist-info", "cv2"),
                      "memory-env": ("fastembed-0.8.0.dist-info",)}
            for env, entries in layout.items():
                site = root / ".sumika-next" / env / "Lib" / "site-packages"
                site.mkdir(parents=True)
                for entry in entries:
                    (site / entry).mkdir()
            (root / ".sumika-next" / "voice-models" / "vosk-model-small-cn-0.22").mkdir(parents=True)
            (root / "runtime" / "browserskill").mkdir(parents=True)
            (root / "runtime" / "browserskill" / "bsk.exe").write_bytes(b"stub")
            rows = self._probes(root)
            self.assertTrue(rows["office"]["ready"], rows["office"]["detail"])
            self.assertEqual(rows["office"]["detail"], "隔离环境 office-env：docx, openpyxl, pptx, pymupdf")
            self.assertTrue(rows["desktop"]["ready"])
            self.assertTrue(rows["camera"]["ready"])
            self.assertTrue(rows["memory-semantic"]["ready"])
            self.assertFalse(rows["voice"]["ready"], "vosk still missing even though the model exists")


if __name__ == "__main__":
    unittest.main()
