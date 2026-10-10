"""Reading-behavior tracker: sustained patterns only, once per episode."""
import unittest

from extensions.companion.reading_behavior import ReadingBehaviorTracker


class ReadingBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.tracker = ReadingBehaviorTracker(clock=lambda: self.now[0])

    def feed(self, *pages, step=1.0):
        reports = []
        for page in pages:
            reports.append(self.tracker.feed(page))
            self.now[0] += step
        return reports

    def test_single_flip_and_single_jump_never_report(self):
        self.assertTrue(all(item is None for item in self.feed(3, 4, 40, 41, 42)))

    def test_sustained_fast_flipping_reports_once_per_episode(self):
        reports = self.feed(1, 2, 3, 4, 5, 6, 7)
        bursts = [item for item in reports if item and item['kind'] == 'flip_burst']
        self.assertEqual(len(bursts), 1)
        self.assertEqual(bursts[0]['flips'], 6)
        self.assertEqual(bursts[0]['page'], 7)
        # Continued flipping inside the same episode stays silent.
        self.assertTrue(all(item is None for item in self.feed(8, 9, 10, 11)))

    def test_burst_rearms_after_calm(self):
        self.feed(1, 2, 3, 4, 5, 6, 7)
        self.now[0] += 25.0
        self.assertIsNone(self.tracker.feed(7))
        reports = self.feed(8, 9, 10, 11, 12, 13)
        self.assertTrue(any(item and item['kind'] == 'flip_burst' for item in reports))

    def test_long_dwell_reports_once_per_page_stay(self):
        self.feed(5)
        self.now[0] += 180.0
        report = self.tracker.feed(5)
        self.assertEqual(report['kind'], 'long_dwell')
        self.assertAlmostEqual(report['dwell_seconds'], 181.0, delta=0.5)
        self.assertIsNone(self.tracker.feed(5))
        # Leaving and resting on a new page arms the dwell report again.
        self.feed(6)
        self.now[0] += 180.0
        self.assertEqual(self.tracker.feed(6)['kind'], 'long_dwell')

    def test_repeated_back_jumps_report_revisit(self):
        reports = self.feed(10, 12, 10, 12, 10)
        revisits = [item for item in reports if item and item['kind'] == 'revisit']
        self.assertEqual(len(revisits), 1)
        self.assertEqual(revisits[0]['backward_flips'], 2)

    def test_unknown_or_invalid_page_resets_state(self):
        self.feed(1, 2, 3, 4)
        self.assertIsNone(self.tracker.feed(None))
        self.assertIsNone(self.tracker.feed(5, valid=False))
        # Prior events cannot combine with post-reset ones into a burst.
        self.assertTrue(all(item is None for item in self.feed(6, 7, 8)))

    def test_backjumps_report_before_a_burst_forms(self):
        # Reports are per-pattern and honest: two back-jumps inside the
        # revisit window report revisit even if a burst forms moments later.
        reports = self.feed(10, 12, 11, 13, 12, 11, 13, 14)
        kinds = [item['kind'] for item in reports if item]
        self.assertEqual(kinds, ['revisit', 'flip_burst'])

    def test_invalid_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            ReadingBehaviorTracker(burst_flips=1)
        with self.assertRaises(ValueError):
            ReadingBehaviorTracker(calm_seconds=1.0, burst_window=5.0)
        with self.assertRaises(ValueError):
            ReadingBehaviorTracker(revisit_backjumps=0)


if __name__ == '__main__':
    unittest.main()
