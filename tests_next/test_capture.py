import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from extensions.desktop.capture import (frame_is_usable, grab_window, plan_capture,
                                        resolve_window)


class WindowResolutionTests(unittest.TestCase):
    def _windows(self):
        return [{"handle": 1, "title": "GIRLS BAND CRY", "visible": True, "rect": [0, 0, 1280, 720]},
                {"handle": 2, "title": "Sumika Overlay", "visible": True, "rect": [0, 600, 1280, 120]},
                {"handle": 3, "title": "hidden", "visible": False, "rect": [0, 0, 10, 10]}]

    def test_exactly_one_visible_match(self):
        found = resolve_window("girls band", self._windows())
        self.assertEqual(found["status"], "ok")
        self.assertEqual(found["handle"], 1)
        self.assertEqual(found["rect"], (0, 0, 1280, 720))

    def test_invisible_windows_are_ignored(self):
        self.assertEqual(resolve_window("hidden", self._windows())["status"], "not_found")

    def test_ambiguity_and_missing_inventory_fail_closed(self):
        windows = self._windows() + [{"handle": 4, "title": "GIRLS BAND CRY (2)", "visible": True,
                                      "rect": [0, 0, 100, 100]}]
        self.assertEqual(resolve_window("girls band", windows)["status"], "ambiguous")
        self.assertEqual(resolve_window("nothing", self._windows())["status"], "not_found")
        bad = [{"handle": None, "title": "x", "visible": True, "rect": [0, 0, 10, 10]}]
        self.assertEqual(resolve_window("x", bad)["status"], "invalid_window")
        with self.assertRaises(ValueError):
            resolve_window("", self._windows())
        with self.assertRaises(ValueError):
            resolve_window("x", "not-a-list")


class CapturePlanTests(unittest.TestCase):
    def test_plan_targets_the_window_not_the_screen(self):
        plan = plan_capture({"handle": 1, "rect": (100, 50, 1280, 720)},
                            overlay={"rect": (100, 700, 1280, 120)})
        self.assertEqual(plan["status"], "ok")
        self.assertEqual(plan["method"], "window")
        self.assertEqual(plan["rect"], (100, 50, 1280, 720))
        self.assertTrue(plan["overlay_excluded"])
        self.assertTrue(plan["warnings"], "overlap is reported so the overlay can be re-checked")

    def test_overlay_outside_the_window_produces_no_warning(self):
        plan = plan_capture({"handle": 1, "rect": (0, 0, 1280, 720)},
                            overlay={"rect": (1400, 0, 400, 300)})
        self.assertEqual(plan["warnings"], [])

    def test_tiny_or_invalid_windows_are_not_captured(self):
        self.assertEqual(plan_capture({"handle": 1, "rect": (0, 0, 10, 10)})["status"], "unknown")
        with self.assertRaises(ValueError):
            plan_capture({"handle": 1, "rect": (0, 0, 0, 0)})


class FrameUsabilityTests(unittest.TestCase):
    def test_black_and_flat_frames_are_rejected_before_ocr(self):
        self.assertFalse(frame_is_usable((0.0, 0.0))["usable"])
        self.assertIn("black", frame_is_usable((0.4, 0.1))["reason"])
        self.assertIn("contrast", frame_is_usable((120.0, 0.5))["reason"])
        self.assertTrue(frame_is_usable((120.0, 24.0))["usable"])
        with self.assertRaises(ValueError):
            frame_is_usable((1,))
        with self.assertRaises(ValueError):
            frame_is_usable(("a", "b"))


class GrabWindowTests(unittest.TestCase):
    def test_grab_refuses_overwrite_and_invalid_rectangles(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "frame.png"
            target.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                grab_window((0, 0, 100, 100), target)
            with self.assertRaises(ValueError):
                grab_window((0, 0, 0, 100), Path(d) / "x.png")

    def test_grab_saves_one_image_without_touching_the_screen(self):
        with tempfile.TemporaryDirectory() as d:
            class FakeImage:
                def save(self, path):
                    Path(path).write_bytes(b"png")
            fake_module = MagicMock()
            fake_module.ImageGrab = fake_module
            fake_module.grab.return_value = FakeImage()
            with patch.dict("sys.modules", {"PIL": fake_module, "PIL.ImageGrab": fake_module}):
                result = grab_window((10, 20, 300, 200), Path(d) / "frame.png")
            self.assertEqual(fake_module.grab.call_args.kwargs["bbox"], (10, 20, 310, 220))
            self.assertEqual(result["rect"], (10, 20, 300, 200))
            self.assertTrue((Path(d) / "frame.png").is_file())


if __name__ == "__main__":
    unittest.main()
