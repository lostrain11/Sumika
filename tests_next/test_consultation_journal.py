import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

from extensions.desktop.consultation_journal import ConsultationJournal


class JournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir='.sumika-next')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'requests.db'
        self.journal = ConsultationJournal(self.path)
        self.args = dict(site='chatgpt.com', prompt='test',
                         binding=dict(session_id='s',tab_id=1,browser_instance_id='b',agent_window_id=2),
                         approved=True, preflight=Mock(), dispatch=Mock(return_value={'submitted':True}))

    def test_restart_after_timeout_never_replays(self):
        self.args['dispatch'].side_effect = TimeoutError('may have submitted')
        self.assertEqual(self.journal.submit('r', **self.args)['state'], 'unknown')
        recovered = ConsultationJournal(self.path)
        self.assertEqual(recovered.submit('r', **self.args)['state'], 'unknown')
        self.args['dispatch'].assert_called_once()

    def test_acknowledgement_is_not_completion(self):
        self.assertEqual(self.journal.submit('r', **self.args)['state'], 'submitted')
        self.journal.submit('r', **self.args)
        self.args['dispatch'].assert_called_once()
        with self.assertRaises(ValueError):
            self.journal.submit('r', **{**self.args, 'prompt':'changed'})

    def test_approval_and_preflight_fail_before_admission(self):
        with self.assertRaises(PermissionError):
            self.journal.submit('r', **{**self.args, 'approved':False})
        self.args['preflight'].side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError): self.journal.submit('r', **self.args)
        with self.assertRaises(KeyError): self.journal.status('r')
        self.args['dispatch'].assert_not_called()

    def test_unknown_committed_before_external_effect(self):
        def dispatch():
            self.assertEqual(ConsultationJournal(self.path).status('r')['state'], 'unknown')
            return {'submitted':False}
        self.assertEqual(self.journal.submit('r', **{**self.args,'dispatch':dispatch})['state'], 'unknown')

    def test_two_writers_dispatch_once(self):
        barrier = Barrier(2)
        args = {**self.args, 'preflight':lambda:barrier.wait(timeout=5)}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(ConsultationJournal(self.path).submit, 'r', **args) for _ in range(2)]
            for future in futures: future.result()
        self.args['dispatch'].assert_called_once()

    def test_different_requests_cannot_dispatch_to_same_tab(self):
        barrier = Barrier(2)
        args = {**self.args, 'preflight':lambda:barrier.wait(timeout=5)}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(ConsultationJournal(self.path).submit, request_id, **args)
                       for request_id in ('one','two')]
            outcomes = []
            for future in futures:
                try: outcomes.append(future.result()['state'])
                except PermissionError: outcomes.append('blocked')
        self.assertCountEqual(outcomes, ['submitted','blocked'])
        self.args['dispatch'].assert_called_once()

    def test_cancel_and_restart_do_not_make_remote_tab_idle(self):
        self.journal.submit('one', **self.args)
        self.journal.cancel('one')
        with self.assertRaises(PermissionError):
            ConsultationJournal(self.path).submit('two', **self.args)
        self.args['dispatch'].assert_called_once()
        other = {**self.args, 'binding':{**self.args['binding'], 'tab_id':3}}
        self.assertEqual(self.journal.submit('two', **other)['state'], 'submitted')
