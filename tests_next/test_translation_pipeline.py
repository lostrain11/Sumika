import unittest

from extensions.desktop.translation_pipeline import (TextTracker, TranslationCache, cache_key,
                                                      normalize_text)


class NormalizeAndKeyTests(unittest.TestCase):
    def test_normalization_ignores_layout_but_not_content(self):
        self.assertEqual(normalize_text("  この先は 危険だ。\n"), "この先は危険だ。")
        self.assertNotEqual(normalize_text("危険"), normalize_text("危険だ"))
        with self.assertRaises(ValueError):
            normalize_text(None)

    def test_cache_key_isolates_region_language_provider_and_glossary(self):
        base = dict(region=(0, 0, 100, 40), text="危険", target_language="zh-CN", provider="p1")
        self.assertEqual(cache_key(**base), cache_key(**base))
        for change in ({"region": (0, 100, 100, 40)}, {"target_language": "en"},
                       {"provider": "p2"}, {"glossary_version": 1}):
            self.assertNotEqual(cache_key(**base), cache_key(**{**base, **change}))
        with self.assertRaises(ValueError):
            cache_key(region=None, text="x", target_language="", provider="p")

    def test_cache_is_bounded_and_tracks_hits(self):
        cache = TranslationCache(max_entries=2)
        cache.put(("a",), "1")
        cache.put(("b",), "2")
        self.assertEqual(cache.get(("a",)), "1")
        cache.put(("c",), "3")
        self.assertEqual(len(cache), 2)
        self.assertIsNone(cache.get(("b",)), "least recently used entry is evicted")
        self.assertEqual(cache.hits, 1)
        with self.assertRaises(ValueError):
            cache.put(("d",), 5)


class TextTrackerTests(unittest.TestCase):
    def _lines(self, text):
        return [{"text": text, "box": [[0, 0], [10, 0], [10, 5], [0, 5]], "score": 0.99}]

    def test_text_must_be_stable_before_it_is_translated_once(self):
        tracker = TextTracker(stable_frames=2, provider="rapidocr")
        first = tracker.observe(self._lines("この先は危険だ。"))
        self.assertEqual(first["requests"], [])
        second = tracker.observe(self._lines("この先は危険だ。"))
        self.assertEqual(len(second["requests"]), 1)
        request = second["requests"][0]
        self.assertEqual(request["text"], "この先は危険だ。")
        third = tracker.observe(self._lines("この先は危険だ。"))
        self.assertEqual(third["requests"], [], "identical text is not translated twice")
        accepted = tracker.accept(request["request_id"], "前面很危险。")
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["translation"], "前面很危险。")
        self.assertEqual(tracker.pending(), [])
        fourth = tracker.observe(self._lines("この先は危険だ。"))
        self.assertEqual(fourth["stable"][0]["status"], "cached")
        self.assertEqual(fourth["requests"], [])

    def test_changed_text_is_a_new_line_and_the_old_answer_is_dropped(self):
        tracker = TextTracker(stable_frames=1, provider="p")
        first = tracker.observe(self._lines("第一句"))
        request = first["requests"][0]
        self.assertEqual([g["text"] for g in tracker.observe(self._lines("第二句"))["gone"]], ["第一句"])
        late = tracker.accept(request["request_id"], "迟到的译文")
        self.assertFalse(late["accepted"])
        self.assertEqual(late["reason"], "stale or unknown request")
        self.assertEqual(len(tracker.cache), 0, "a stale answer is never cached")

    def test_gone_lines_release_pending_requests(self):
        tracker = TextTracker(stable_frames=1, provider="p")
        request = tracker.observe(self._lines("字幕"))["requests"][0]["request_id"]
        self.assertEqual(tracker.pending(), [request])
        tracker.observe([])
        self.assertEqual(tracker.pending(), [])
        self.assertFalse(tracker.accept(request, "x")["accepted"])

    def test_regions_do_not_share_cache_entries(self):
        tracker = TextTracker(stable_frames=1, provider="p")
        left = tracker.observe(self._lines("同一句"), region=(0, 0, 100, 40))["requests"][0]
        tracker.accept(left["request_id"], "译A")
        right = tracker.observe(self._lines("同一句"), region=(0, 100, 100, 40))
        self.assertEqual(len(right["requests"]), 1, "another region needs its own translation")
        self.assertEqual(right["stable"][0]["status"], "stable")

    def test_blank_and_invalid_input(self):
        tracker = TextTracker(stable_frames=1, provider="p")
        self.assertEqual(tracker.observe([{"text": "   "}])["requests"], [])
        self.assertEqual(tracker.observe([{"text": "x", "box": None}])["requests"][0]["box"], None)
        with self.assertRaises(ValueError):
            tracker.observe("not a list")
        with self.assertRaises(ValueError):
            tracker.observe(["not a dict"])
        with self.assertRaises(ValueError):
            TextTracker(stable_frames=0)


if __name__ == "__main__":
    unittest.main()
