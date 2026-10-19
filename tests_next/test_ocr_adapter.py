import tempfile
import unittest
import subprocess
import contextlib
import io
import json
import sys
import types
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
                                          "rapidocr_env_python", "windows", "windows_env_python"})
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

    def test_empty_office_environment_does_not_claim_rapidocr(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{},clear=True):
            root=Path(folder)
            python=root/'.sumika-next/office-env/Scripts/python.exe'
            python.parent.mkdir(parents=True);python.touch()
            with patch.object(ocr,'ROOT',root),patch.object(ocr,'_has_module',return_value=False):
                self.assertIsNone(ocr.env_python())
                self.assertFalse(ocr.providers()['rapidocr'])
                package=python.parent.parent/'Lib/site-packages/rapidocr'
                package.mkdir(parents=True)
                self.assertEqual(ocr.env_python(),str(python))
                with patch.dict('os.environ',{'SUMIKA_OCR_PYTHON':str(root/'missing.exe')}):
                    self.assertIsNone(ocr.env_python())
                    self.assertFalse(ocr.providers()['rapidocr'])

    def test_rapidocr_json_accepts_arrays_and_ignores_non_line_records(self):
        with tempfile.TemporaryDirectory() as folder:
            output='[ {"text":"你好", "score":0.9} ]\n{"data":[{"text":"world"}]}\nnull\n{"data":7}\n'
            inventory={'rapidocr_json':'tool.exe','rapidocr':False,'tesseract':None}
            result=subprocess.CompletedProcess([],0,stdout=output,stderr='')
            with patch.object(ocr,'providers',return_value=inventory),patch.object(ocr.subprocess,'run',return_value=result):
                recognized=ocr.recognize(self._image(folder),provider='rapidocr_json')
            self.assertEqual(recognized['text'],'你好\nworld')

    def test_windows_provider_passes_language_to_selected_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.CompletedProcess([],0,stdout='{"lines":[{"text":"English", "score":null, "box":[]}]}',stderr='')
            inventory={'windows':True,'windows_env_python':'selected.exe'}
            with patch.object(ocr,'providers',return_value=inventory),patch.object(ocr.subprocess,'run',return_value=result) as run:
                recognized=ocr.recognize(self._image(folder),provider='windows',language='eng')
                self.assertEqual(run.call_args.args[0][0],'selected.exe')
                self.assertEqual(run.call_args.args[0][-1],'en-US')
            self.assertEqual(recognized['provider'],'windows')

    def test_legacy_rapidocr_rows_and_empty_result(self):
        box = [[0, 0], [10, 0], [10, 5], [0, 5]]
        rows = [[box, 'legacy text', None]]
        with patch.object(ocr, '_engine', return_value=lambda *a, **k: (rows, [0.1])):
            result = ocr._rapidocr_in_process(Path('fixture.png'))
        self.assertEqual(result['text'], 'legacy text')
        self.assertEqual(result['lines'][0]['box'], box)
        self.assertIsNone(result['lines'][0]['score'])
        self.assertEqual(ocr._rapidocr_lines((None, None)), [])

    def test_isolated_script_supports_legacy_package(self):
        legacy = types.ModuleType('rapidocr_onnxruntime')
        legacy.RapidOCR = lambda: lambda *a, **k: ([[[], 'legacy text', 0.9]], [0.1])
        output = io.StringIO()
        with patch.dict(sys.modules, {'rapidocr': None, 'rapidocr_onnxruntime': legacy}), \
                patch.object(sys, 'argv', ['ocr', 'fixture.png', '1']), \
                contextlib.redirect_stdout(output):
            exec(ocr.ENV_SCRIPT, {})
        self.assertEqual(json.loads(output.getvalue())['lines'][0]['text'], 'legacy text')


if __name__ == "__main__":
    unittest.main()
