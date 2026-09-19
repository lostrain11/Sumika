import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from extensions.roles.speech_input import SpeechInput


class SpeechInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = dict(python=sys.executable, root=str(self.root), device=1)
        self.children = []
        self.services = []

    def tearDown(self):
        for service in self.services:
            service.close()
        for child in self.children:
            self.assertIsNotNone(child.poll())
        self.temp.cleanup()

    def service(self, code):
        def spawn(argv, **options):
            child = subprocess.Popen([sys.executable, '-c', code], **options)
            self.children.append(child)
            return child
        service = SpeechInput(self.root/'recordings', lambda role: dict(self.config), spawn=spawn)
        self.services.append(service)
        return service

    def settle(self, service):
        service.thread.join(timeout=5)
        self.assertFalse(service.thread.is_alive())

    def test_permission_before_process_and_success_no_model_dispatch(self):
        service = self.service('import sys,json;json.load(sys.stdin);print(json.dumps({"text":"local draft"}))')
        with self.assertRaises(PermissionError):
            service.start('role')
        self.assertEqual(self.children, [])
        request = service.start('role', approved=True)
        self.settle(service)
        self.assertEqual(service.status(request['id'])['text'], 'local draft')
        self.assertEqual(service.status(request['id'])['state'], 'completed')

    def test_cancel_reclaims_owned_process_and_discards_late_result(self):
        service = self.service('import time;time.sleep(20);print("{\\"text\\":\\"late\\"}")')
        request = service.start('role', approved=True)
        with self.assertRaises(ValueError):
            service.start('role', approved=True)
        service.cancel(request['id'])
        self.settle(service)
        self.assertEqual(service.status(request['id'])['state'], 'cancelled')
        self.assertEqual(service.status(request['id'])['text'], '')

    def test_changed_configuration_discards_result(self):
        service = self.service('import time;time.sleep(.2);print("{\\"text\\":\\"stale\\"}")')
        request = service.start('role', approved=True)
        self.config['device'] = 2
        self.settle(service)
        self.assertEqual(service.status(request['id'])['state'], 'unknown')
        self.assertEqual(service.status(request['id'])['text'], '')

    def test_invalid_worker_shapes_settle_unknown_for_input_and_playback(self):
        from extensions.roles.speech_playback import SpeechPlayback
        for kind in (SpeechInput, SpeechPlayback):
            for output in ('null', '[]', '"text"', '42', '{}', '{"text":null}',
                           '{"text":" "}', 'not-json'):
                with self.subTest(kind=kind.__name__, output=output):
                    service = kind(self.root/'fake', lambda role: self.config)
                    child, job = Mock(), Mock()
                    child.poll.return_value = child.returncode = 0
                    child.communicate.return_value = (output, None)
                    service.process, service.job = child, job
                    service.record = dict(id='request', role_id='role',
                                          state=service.pending_state, text='')
                    service._finish(child, {}, self.config, job)
                    self.assertEqual(service.status('request')['state'], 'unknown')
                    self.assertEqual(service.status('request')['text'], '')
                    self.assertIsNone(service.process)
                    self.assertIsNone(service.job)
                    job.close.assert_called_once()

    def test_invalid_json_shape_from_real_child_does_not_leave_recording(self):
        service = self.service('import sys,json;json.load(sys.stdin);print("null")')
        request = service.start('role', approved=True)
        self.settle(service)
        self.assertEqual(service.status(request['id'])['state'], 'unknown')
        self.assertIsNone(service.process)
        self.assertIsNone(service.job)

    def test_close_reclaims_worker_and_prevents_new_capture(self):
        service = self.service('import time;time.sleep(20)')
        service.start('role', approved=True)
        service.close()
        with self.assertRaises(ValueError):
            service.start('role', approved=True)

    def test_job_assignment_failure_never_sends_capture_payload(self):
        marker = self.root/'should-not-start'
        code = ('import sys,json;from pathlib import Path;json.load(sys.stdin);'
                'Path('+repr(str(marker))+').write_text("started")')
        service = self.service(code)
        with patch('extensions.roles.speech_input.ChildJob.assign', side_effect=OSError('fixture assignment failed')):
            with self.assertRaises(ValueError):
                service.start('role', approved=True)
        self.assertFalse(marker.exists())
        self.assertIsNone(service.process)
        self.assertIsNotNone(self.children[0].poll())

    def test_failed_stop_retains_ownership_until_explicit_retry(self):
        service = SpeechInput(self.root/'fake', lambda role: self.config)
        child = Mock()
        child.poll.return_value = None
        child.terminate.side_effect = OSError('stop denied')
        job = Mock()
        service.process, service.job = child, job
        service.record = dict(id='request', role_id='role', state='recording', text='')
        with self.assertRaisesRegex(RuntimeError, 'unknown'):
            service.cancel('request')
        self.assertEqual(service.status('request')['state'], 'unknown')
        self.assertIs(service.process, child)
        job.close.assert_not_called()
        with self.assertRaises(ValueError):
            service.start('role', approved=True)
        child.poll.return_value = 0
        self.assertEqual(service.cancel('request')['state'], 'cancelled')
        self.assertIsNone(service.process)
        self.assertIsNone(service.job)

    def test_worker_timeout_and_failed_cleanup_remain_unknown(self):
        service = SpeechInput(self.root/'fake', lambda role: self.config)
        child, job = Mock(), Mock()
        child.poll.return_value = None
        child.communicate.side_effect = subprocess.TimeoutExpired('worker', 60)
        child.wait.side_effect = subprocess.TimeoutExpired('worker', 5)
        service.process, service.job = child, job
        service.record = dict(id='request', role_id='role', state='recording', text='')
        service._finish(child, {}, self.config, job)
        self.assertEqual(service.status('request')['state'], 'unknown')
        self.assertIs(service.process, child)
        child.kill.assert_called_once()
        with self.assertRaises(RuntimeError):
            service.close()
        child.poll.return_value = 0
        service.close()

    def test_job_close_failure_discards_transcript_and_blocks_restart(self):
        service = SpeechInput(self.root/'fake', lambda role: self.config)
        child, job = Mock(), Mock()
        child.poll.return_value = child.returncode = 0
        child.communicate.return_value = ('{"text":"draft"}', None)
        job.close.side_effect = OSError('close failed')
        service.process, service.job = child, job
        service.record = dict(id='request', role_id='role', state='recording', text='')
        service._finish(child, {}, self.config, job)
        self.assertEqual(service.status('request')['state'], 'unknown')
        self.assertEqual(service.status('request')['text'], '')
        self.assertIs(service.job, job)
        with self.assertRaises(ValueError):
            service.start('role', approved=True)
        job.close.side_effect = None
        service.close()

    def test_assignment_and_cleanup_failure_retains_child_without_payload(self):
        child, job = Mock(), Mock()
        child.poll.return_value = None
        child.terminate.side_effect = OSError('stop failed')
        job.assign.side_effect = OSError('assignment failed')
        service = SpeechInput(self.root/'fake', lambda role: self.config, spawn=Mock(return_value=child))
        with patch('extensions.roles.speech_input.ChildJob', return_value=job):
            with self.assertRaises(ValueError):
                service.start('role', approved=True)
        self.assertEqual(service.record['state'], 'unknown')
        self.assertIs(service.process, child)
        child.communicate.assert_not_called()
        with self.assertRaises(ValueError):
            service.start('role', approved=True)
        child.poll.return_value = 0
        service.close()


if __name__ == '__main__':
    unittest.main()
