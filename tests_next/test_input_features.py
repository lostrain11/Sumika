"""P11 pure input aggregation: classification, whitelist, grids, frames."""
import json
import unittest

from extensions.behavior.input_features import (
    FrameAggregator, MAX_FRAME_BYTES, classify_key, classify_shortcut,
    grid_cell)


def identity():
    return {'user_scope': 'project-1', 'worker_epoch': 3,
            'foreground_epoch': 5, 'focus_epoch': 2, 'window_instance': 77}


class ClassificationTests(unittest.TestCase):
    def test_key_classes(self):
        self.assertEqual(classify_key(0x41), 'text_entry')      # A
        self.assertEqual(classify_key(0x20), 'text_entry')      # space
        self.assertEqual(classify_key(0x0D), 'navigation')      # enter
        self.assertEqual(classify_key(0x25), 'navigation')      # left
        self.assertEqual(classify_key(0x2E), 'editing')         # delete
        self.assertEqual(classify_key(0x70), 'function')        # F1
        self.assertEqual(classify_key(0xA0), 'modifier')        # shift
        self.assertEqual(classify_key(0xF0), 'other')

    def test_shortcut_whitelist(self):
        self.assertEqual(classify_shortcut(0x43, {'ctrl'}), 'copy')
        self.assertEqual(classify_shortcut(0x46, {'ctrl'}), 'find')
        self.assertEqual(classify_shortcut(0x4E, {'ctrl'}), 'other_shortcut')
        self.assertEqual(classify_shortcut(0x43, {'ctrl', 'alt'}),
                         'other_shortcut')
        self.assertEqual(classify_shortcut(0x43, set()), 'other_shortcut')

    def test_grid_cell_bounds_and_validation(self):
        self.assertEqual(grid_cell(0, 0), 0)
        self.assertEqual(grid_cell(1, 1), 255)
        self.assertEqual(grid_cell(0.9, 0.05), 14)
        with self.assertRaises(ValueError):
            grid_cell(1.2, 0.5)
        with self.assertRaises(ValueError):
            grid_cell(-0.1, 0.5)


class FrameAggregatorTests(unittest.TestCase):
    def aggregator(self):
        return FrameAggregator(identity=identity(), observed_from='100.0',
                               sequence=1)

    def test_frame_carries_fixed_identity_and_schema(self):
        frame = self.aggregator().seal('101.0')
        self.assertEqual(frame['schema'], 'input-frame-v1')
        for key, value in identity().items():
            self.assertEqual(frame[key], value)
        self.assertEqual(frame['sequence'], 1)
        self.assertEqual(frame['observed_from'], '100.0')
        self.assertEqual(frame['observed_to'], '101.0')

    def test_key_counts_and_interval_buckets_never_timestamps(self):
        aggregator = self.aggregator()
        for index, at in enumerate((100.0, 100.03, 100.05, 100.4, 102.0)):
            aggregator.key(0x41, at)
        frame = aggregator.seal('103.0')
        self.assertEqual(frame['keys']['counts']['text_entry'], 5)
        buckets = frame['keys']['interval_buckets']
        self.assertEqual(buckets['0-50'], 2)
        self.assertEqual(buckets['300-1000'], 1)
        self.assertEqual(buckets['1000+'], 1)
        self.assertEqual(buckets['50-120'], 0)
        self.assertNotIn('intervals', frame['keys'])

    def test_shortcut_merge_and_other_shortcut_has_no_content(self):
        aggregator = self.aggregator()
        aggregator.shortcut(0x43, {'ctrl'})
        aggregator.shortcut(0x43, {'ctrl'})
        aggregator.shortcut(0x4E, {'ctrl'})
        frame = aggregator.seal('1.0')
        self.assertEqual(frame['shortcuts']['copy'], 2)
        self.assertEqual(frame['shortcuts']['other_shortcut'], 1)
        self.assertNotIn('N', json.dumps(frame['shortcuts']))

    def test_click_grid_and_pointer_absence(self):
        aggregator = self.aggregator()
        aggregator.click('left', 0.1, 0.2)
        aggregator.click('left', 0.1, 0.2, double_candidate=True)
        frame = aggregator.seal('1.0')
        self.assertEqual(frame['mouse']['left'], 2)
        self.assertEqual(frame['mouse']['double_click_candidates'], 1)
        packed = frame['mouse']['grid']
        self.assertEqual(len(packed), 16)
        self.assertEqual(sum(int(char, 16) for row in packed for char in row), 2)
        self.assertNotIn('absolute', json.dumps(frame['mouse']))

    def test_scroll_and_drag_buckets(self):
        aggregator = self.aggregator()
        aggregator.scroll('vertical', -3)
        aggregator.scroll('vertical', 3)
        aggregator.drag(0.5, 0.5, 7)
        frame = aggregator.seal('1.0')
        self.assertEqual(frame['scroll']['vertical']['count'], 2)
        self.assertEqual(frame['scroll']['vertical']['reversed'], 1)
        self.assertEqual(frame['drag']['candidates'], 1)
        self.assertIn(136, frame['drag']['cells'])  # row 8, column 8
        self.assertIn(7 // 5, frame['drag']['duration_buckets'])

    def test_password_pause_clears_fine_grained_data(self):
        aggregator = self.aggregator()
        aggregator.key(0x41, 1.0)
        aggregator.click('left', 0.5, 0.5)
        aggregator.focus('password_paused')
        frame = aggregator.seal('2.0')
        self.assertEqual(frame['focus_quality'], 'password_paused')
        self.assertEqual(frame['keys']['counts'], {})
        self.assertEqual(frame['mouse']['left'], 0)
        self.assertEqual(frame['semantic_ops'], [])

    def test_unknown_context_marks_coarse_coverage(self):
        aggregator = self.aggregator()
        aggregator.focus('privacy_context_unknown')
        frame = aggregator.seal('1.0')
        self.assertEqual(frame['input_source_coverage'], 'coarse_only')

    def test_semantic_ops_cap_merges_and_marks_truncated(self):
        aggregator = self.aggregator()
        for _ in range(40):
            aggregator.click('left', 0.5, 0.5)   # one merged op
            aggregator.shortcut(0x4E, {'ctrl'})  # 40 distinct other ops
        frame = aggregator.seal('1.0')
        self.assertLessEqual(len(frame['semantic_ops']), 32)
        self.assertEqual(frame['semantic_total'], 80)
        self.assertTrue(frame['truncated'])

    def test_frame_budget_shrinks_instead_of_overflowing(self):
        aggregator = FrameAggregator(identity={
            'user_scope': 'project-1', 'worker_epoch': 1,
            'foreground_epoch': 1, 'focus_epoch': 1, 'window_instance': 1},
            observed_from='0.0', sequence=0)
        for index in range(4000):
            aggregator.drag((index % 16) / 16,
                            min(index // 16, 15) / 16, index)
        frame = aggregator.seal('1.0')
        self.assertLessEqual(
            len(json.dumps(frame, ensure_ascii=False).encode('utf8')),
            MAX_FRAME_BYTES)
        self.assertTrue(frame['truncated'])
        self.assertLessEqual(len(frame['drag']['duration_buckets']), 64)


if __name__ == '__main__':
    unittest.main()
