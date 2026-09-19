import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.desktop.ocr import ocr


class _Result:
    def __init__(self):
        self.boxes = [[[0, 0], [10, 0], [10, 5], [0, 5]]]
        self.txts = ["この先は危険だ"]
        self.scores = [0.99]


class _Engine:
    def __init__(self):
        self.calls = []

    def __call__(self, image, **options):
        self.calls.append((image, options))
        return _Result()


class OcrAdapterTests(unittest.TestCase):
    def _image(self, folder):
        path = Path(folder) / "fixture.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    def test_provider_inventory_reports_environment_paths(self):
        available = ocr.providers()
        self.assertEqual(set(available), {"tesseract", "rapidocr_json", "rapidocr",
                                          "rapidocr_env_python"})
        self.assertIsInstance(available["rapidocr"], bool)

    def test_recognition_shapes_lines_with_box_and_score(self):
        with tempfile.TemporaryDirectory() as d:
            engine = _Engine()
            with patch.object(ocr, "_engine", return_value=engine), \
                    patch.object(ocr.importlib.util, "find_spec", return_value=object()):
                result = ocr.recognize(self._image(d), provider="rapidocr")
            self.assertEqual(result["provider"], "rapidocr")
            self.assertEqual(result["text"], "この先は危険だ")
            self.assertTrue(result["lines"][0]["box"])
            self.assertAlmostEqual(result["lines"][0]["score"], 0.99)
            self.assertIsInstance(result["elapsed_ms"], float)
            self.assertTrue(result["needs_translation"])
            self.assertEqual(engine.calls[0][1], {"use_det": True})

    def test_detect_false_skips_the_detection_model(self):
        with tempfile.TemporaryDirectory() as d:
            engine = _Engine()
            with patch.object(ocr, "_engine", return_value=engine), \
                    patch.object(ocr.importlib.util, "find_spec", return_value=object()):
                ocr.recognize(self._image(d), provider="rapidocr", detect=False)
            self.assertEqual(engine.calls[0][1], {"use_det": False})

    def test_engine_is_reused_between_calls(self):
        with tempfile.TemporaryDirectory() as d:
            engine = _Engine()
            with patch.object(ocr, "RapidOCR", create=True), \
                    patch.object(ocr.importlib.util, "find_spec", return_value=object()), \
                    patch.object(ocr, "_ENGINE", None):
                with patch("rapidocr.RapidOCR", return_value=engine) if False else patch.object(
                        ocr, "_engine", return_value=engine):
                    ocr.recognize(self._image(d), provider="rapidocr")
                    ocr.recognize(self._image(d), provider="rapidocr")
            self.assertEqual(len(engine.calls), 2, "engine instance is reused, not rebuilt")

    def test_unknown_provider_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(ocr, "providers", return_value={"tesseract": None, "rapidocr_json": None,
                                                             "rapidocr": False,
                                                             "rapidocr_env_python": None}):
                with self.assertRaisesRegex(RuntimeError, "No OCR provider available"):
                    ocr.recognize(self._image(d), provider="auto")


if __name__ == "__main__":
    unittest.main()
