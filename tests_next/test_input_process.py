"""P11 parent supervision: frame persistence idempotency, bounded queue,
commit batching, and a real worker start/stop smoke (no keys pressed)."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from extensions.behavior.input_features import SCHEMA
from extensions.behavior.input_process import InputFeatureProcess
from extensions.behavior.library import BehaviorLibrary


def frame(sequence, worker_epoch=1, *, pad=None):
    frame = {'schema': SCHEMA, 'user_scope': 'project-1',
             'worker_epoch': worker_epoch, 'sequence': sequence,
             'foreground_epoch': 1, 'focus_epoch': 1, 'window_instance': 9,
             'observed_from': '0.0', 'observed_to': '1.0',
             'keys': {'counts': {'text_entry': 1}, 'repeat': 0,
                      'interval_buckets': {}},
             'shortcuts': {}, 'mouse': {'left': 0, 'right': 0, 'middle': 0,
                                        'double_click_candidates': 0,
                                        'moves': 1, 'grid': None},
             'scroll': {}, 'drag': {}, 'bursts': [], 'semantic_ops': [],
             'semantic_total': 0, 'focus_quality': 'ok',
             'input_source_coverage': 'full', 'dropped_count': 0,
             'truncated': False}
    if pad:
        frame['padding_field'] = pad
    return frame


class RecordFramesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p11-frames-')
        self.addCleanup(self._tmp.cleanup)
        self.library = BehaviorLibrary(Path(self._tmp.name)/'behavior.sqlite3')
        self.scope = {'user': 'project-1', 'session': None}

    def test_batch_persists_and_replays_idempotently(self):
        first = self.library.record_frames([frame(0), frame(1)],
                                           scope=self.scope)
        self.assertEqual(first['status'], 'recorded')
        again = self.library.record_frames([frame(0), frame(1)],
                                           scope=self.scope)
        self.assertEqual(again['status'], 'recorded')
        with self.library._connection() as db:
            count = db.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
        self.assertEqual(count, 2)

    def test_replayed_frame_with_changed_content_is_rejected(self):
        self.library.record_frames([frame(0)], scope=self.scope)
        with self.assertRaises(ValueError):
            self.library.record_frames([frame(0, pad='mutated')],
                                       scope=self.scope)

    def test_unknown_schema_and_budget_rejected(self):
        with self.assertRaises(ValueError):
            self.library.record_frames([{'schema': 'other'}], scope=self.scope)
        with self.assertRaises(ValueError):
            self.library.record_frames([frame(0, pad='x' * 20000)],
                                       scope=self.scope)


class ParentSupervisionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p11-parent-')
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.library = BehaviorLibrary(self.root/'behavior.sqlite3')

    def test_bounded_queue_drops_oldest_and_commit_persists(self):
        process = InputFeatureProcess(root=self.root, library=self.library,
                                      user_scope='project-1')
        for sequence in range(150):  # over the 120-frame queue bound
            process._enqueue(frame(sequence))
        self.assertLessEqual(process._queue.qsize(), 120)
        process._commit_batch()
        self.assertEqual(process._frames, 120)
        with self.library._connection() as db:
            count = db.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
        self.assertEqual(count, 120)

    def test_commit_failure_isolates_the_channel(self):
        class ExplodingLibrary:
            def record_frames(self, batch, *, scope):
                raise RuntimeError('disk went away')
        process = InputFeatureProcess(root=self.root,
                                      library=ExplodingLibrary(),
                                      user_scope='project-1')
        process._state = 'running'
        process._enqueue(frame(0))
        process._commit_batch()
        status = process.status()
        self.assertEqual(status['status'], 'failed')
        self.assertIn('disk went away', status['error'])


class WorkerSmokeTests(unittest.TestCase):
    """Real worker against the packaged desktop runtime; no keys pressed."""

    def setUp(self):
        from extensions.desktop.runtime import capability_python
        self.interpreter = capability_python('desktop')
        if self.interpreter is None:
            self.skipTest('packaged desktop runtime unavailable')

    def test_start_idle_stop_is_clean_and_persists_nothing(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p11-smoke-')
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        library = BehaviorLibrary(root/'behavior.sqlite3')
        workspace = Path(__file__).resolve().parents[1]
        process = InputFeatureProcess(root=root, library=library,
                                      user_scope='project-1',
                                      runtime_root=workspace)
        status = process.start()
        self.assertEqual(status['status'], 'starting')
        time.sleep(3)  # idle session: the worker registers and waits
        stopped = process.stop()
        self.assertEqual(stopped['status'], 'stopped')
        self.assertIsNone(stopped['error'])
        # An idle session produces no non-empty frames and stores nothing.
        with library._connection() as db:
            count = db.execute('SELECT COUNT(*) FROM frames').fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
