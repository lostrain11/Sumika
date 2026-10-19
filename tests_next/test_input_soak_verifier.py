"""Acceptance must reject failed/interrupted captures and invalid private payloads."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests_next.test_input_process import frame
from tools.verify_input_keystroke_soak import assess_frames, main


class SoakVerifierTests(unittest.TestCase):
    def checks(self, frames, **overrides):
        options = dict(user_scope='project-1', completed=True,
            stopped={'status': 'stopped', 'error': None, 'alive': False})
        return assess_frames(frames, **{**options, **overrides})

    def active_frame(self, sequence=0):
        result = frame(sequence)
        result['mouse']['right'] = 1
        return result

    def test_valid_contiguous_activity_passes(self):
        self.assertTrue(all(self.checks([self.active_frame(), self.active_frame(1)]).values()))

    def test_zero_counts_and_sequence_gap_do_not_pass(self):
        item = self.active_frame()
        item['keys']['counts'] = {'text_entry': 0}
        self.assertFalse(self.checks([item])['key_counts_present'])
        self.assertFalse(self.checks([self.active_frame(), self.active_frame(2)])['sequences_contiguous'])

    def test_nested_raw_payload_and_wrong_scope_rejected(self):
        item = self.active_frame()
        raw = copy.deepcopy(item)
        raw['keys']['text'] = 'must not persist'
        self.assertFalse(self.checks([raw])['closed_anonymous_schema'])
        self.assertFalse(self.checks([item], user_scope='another')['closed_anonymous_schema'])

    def test_failed_worker_or_interruption_cannot_pass_with_valid_frames(self):
        items = [self.active_frame()]
        self.assertFalse(all(self.checks(items, completed=False).values()))
        self.assertFalse(all(self.checks(items, stopped={
            'status': 'failed', 'error': 'worker_unexpected_eof', 'alive': False}).values()))

    def test_start_failure_writes_report_and_stops_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'soak'
            with patch('tools.verify_input_keystroke_soak.InputFeatureProcess') as worker:
                worker.return_value.start.side_effect = RuntimeError('not interactive')
                worker.return_value.stop.return_value = {
                    'status': 'stopped', 'error': None, 'alive': False}
                self.assertEqual(main(['--allow-recording', '--seconds', '1',
                                       '--output', str(output)]), 2)
                permission = worker.return_value.start.call_args.kwargs['permission']
                self.assertTrue(permission['recording'])
                self.assertFalse(permission['paused'])
                worker.return_value.stop.assert_called_once()
            report = json.loads((output/'report.json').read_text(encoding='utf8'))
            self.assertFalse(report['passed'])
            self.assertIn('not interactive', report['error'])


if __name__ == '__main__':
    unittest.main()
