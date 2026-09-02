"""Tests for bounded OCR evidence used by the browser runtime."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sumika_core.browser.visual import RapidOcrJsonProbe


def _ocr_payload(*lines: tuple[str, float, tuple[int, int, int, int]]) -> str:
    data = []
    for text, score, (left, top, right, bottom) in lines:
        data.append(
            {
                "text": text,
                "score": score,
                "box": [[left, top], [right, top], [right, bottom], [left, bottom]],
            }
        )
    return "RapidOCR-json v1.1.0\nOCR init completed.\n" + json.dumps(
        {"code": 100, "data": data}, ensure_ascii=False
    )


class RapidOcrJsonProbeTests(unittest.TestCase):
    def _image(self, directory: str, name: str) -> Path:
        path = Path(directory) / name
        # The probe only needs the PNG IHDR dimensions; OCR output is supplied
        # by the fixed runner below.
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x03\x20\x00\x00\x02\x58"
            b"\x08\x06\x00\x00\x00"
        )
        return path

    def test_prompt_location_and_new_reply_are_compared_without_returning_ocr_text(self):
        outputs = [
            _ocr_payload(("检查这个方案", 0.98, (120, 500, 420, 550))),
            _ocr_payload(
                ("检查这个方案", 0.97, (120, 360, 420, 410)),
                ("建议先补回归测试，再修改状态机。", 0.96, (80, 120, 620, 200)),
            ),
        ]

        def runner(*_args, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=outputs.pop(0), stderr="")

        with tempfile.TemporaryDirectory() as directory:
            probe = RapidOcrJsonProbe(executable="RapidOCR-json.exe", runner=runner)
            baseline = probe.observe(self._image(directory, "before.png"))
            current = probe.observe(self._image(directory, "after.png"))
            result = probe.evaluate(
                current,
                baseline=baseline,
                expected_text="检查这个方案",
                scope="page",
            )

        self.assertFalse(result["prompt_in_input"])
        self.assertTrue(result["assistant_response_visible"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("检查这个方案", serialized)
        self.assertNotIn("建议先补回归", serialized)

    def test_same_prompt_location_proves_composer_is_still_filled(self):
        outputs = [
            _ocr_payload(("很长的待发送提示仍在这里", 0.99, (100, 480, 650, 545))),
            _ocr_payload(("很长的待发送提示仍在这里", 0.98, (102, 482, 648, 546))),
        ]

        def runner(*_args, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=outputs.pop(0), stderr="")

        with tempfile.TemporaryDirectory() as directory:
            probe = RapidOcrJsonProbe(executable="RapidOCR-json.exe", runner=runner)
            baseline = probe.observe(self._image(directory, "before.png"))
            current = probe.observe(self._image(directory, "after.png"))
            result = probe.evaluate(
                current,
                baseline=baseline,
                expected_text="很长的待发送提示仍在这里",
                scope="page",
            )

        self.assertTrue(result["prompt_in_input"])
        self.assertFalse(result["assistant_response_visible"])

    def test_blocking_surface_and_low_confidence_are_bounded(self):
        output = _ocr_payload(("请完成验证码后继续", 0.91, (180, 220, 620, 280)))

        def runner(*_args, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        with tempfile.TemporaryDirectory() as directory:
            probe = RapidOcrJsonProbe(executable="RapidOCR-json.exe", runner=runner)
            result = probe.evaluate(probe.observe(self._image(directory, "blocked.png")))

        self.assertTrue(result["blocking_surface_visible"])
        self.assertIn(result["confidence"], {"medium", "high"})
        self.assertEqual(set(result) - {
            "available", "confidence", "prompt_in_input",
            "assistant_response_visible", "blocking_surface_visible",
            "evidence", "error_code", "line_count",
        }, set())

    def test_no_text_is_a_valid_low_information_observation(self):
        def runner(*_args, **_kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout='RapidOCR-json v1.1.0\nOCR init completed.\n{"code":101,"data":"No text found"}',
                stderr="",
            )

        with tempfile.TemporaryDirectory() as directory:
            probe = RapidOcrJsonProbe(executable="RapidOCR-json.exe", runner=runner)
            result = probe.evaluate(probe.observe(self._image(directory, "empty.png")))

        self.assertTrue(result["available"])
        self.assertEqual(result["confidence"], "low")
        self.assertIsNone(result["prompt_in_input"])

    def test_missing_executable_reports_unavailable_without_running_ocr(self):
        probe = RapidOcrJsonProbe(executable=r"Z:\missing\RapidOCR-json.exe")

        self.assertFalse(probe.available)
        self.assertFalse(probe.status()["available"])
        self.assertFalse(probe.status()["exports_text"])


if __name__ == "__main__":
    unittest.main()
