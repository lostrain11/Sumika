import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from extensions.companion.perception_process import PerceptionProcess


class PerceptionProcessTests(unittest.TestCase):
    def test_bound_path_survives_resume_and_is_cleared_on_stop_or_new_start(self):
        owner = PerceptionProcess(root=Path.cwd(), python=sys.executable,
                                  on_observation=Mock(), on_clear=Mock())
        expected = str(Path('lesson.pdf').resolve())
        with patch('extensions.companion.perception_process.subprocess.Popen') as launch, \
             patch('extensions.companion.perception_process.threading.Thread') as thread:
            launch.return_value.poll.return_value = None
            launch.return_value.stdin.closed = False
            thread.return_value.is_alive.return_value = False
            owner.start(handle=1, process_id=2, approved=True, expected_document=expected)
            self.assertEqual(launch.call_args.args[0][-2:], ['--expected-document', expected])
            count = launch.call_count
            with self.assertRaises(ValueError):
                owner.start(handle=3, process_id=4, approved=True, expected_document='relative.pdf')
            self.assertEqual(launch.call_count, count)
            self.assertEqual(owner.status()['target']['handle'], 1)
            launch.return_value.wait.assert_not_called()
            owner.pause()
            self.assertEqual(owner.status()['target']['expected_document'], expected)
            owner.resume()
            self.assertEqual(launch.call_args.args[0][-2:], ['--expected-document', expected])
            owner.stop()
            self.assertIsNone(owner.status()['target'])
            owner.start(handle=3, process_id=4, approved=True)
            self.assertNotIn('--expected-document', launch.call_args.args[0])
            self.assertNotIn('expected_document', owner.status()['target'])
            owner.stop()
