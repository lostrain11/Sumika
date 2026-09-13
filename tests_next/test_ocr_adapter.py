import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OCR = ROOT/'extensions/desktop/ocr/ocr.py'


class OcrAdapterTests(unittest.TestCase):
    def test_status_is_json_and_no_provider_is_explicit(self):
        result = subprocess.run([sys.executable, '-B', str(OCR), 'status'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('providers', json.loads(result.stdout))

    def test_missing_image_fails_closed(self):
        result = subprocess.run([sys.executable, '-B', str(OCR), 'recognize', 'missing.png'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_unavailable_provider_fails_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            image = Path(d)/'input.png'; image.write_bytes(b'not an image')
            result = subprocess.run([sys.executable, '-B', str(OCR), 'recognize', str(image), '--provider', 'tesseract'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('No OCR provider available', result.stdout)


if __name__ == '__main__': unittest.main()
