import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from extensions.companion.microphone_process import MicrophoneProcess


class MicrophoneProcessTests(unittest.TestCase):
    def test_speech_interrupts_text_token_without_closing_listener(self):
        from extensions.models.cancellation import RequestCancelled
        script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
for line in sys.stdin:
 packet=json.loads(line)
 if packet['action'] in ('text_begin','text_end'):
  print(json.dumps({'event':'control_ack','request':packet['request']}),flush=True)
 else:
  print(json.dumps({'event':'text_interrupted','turn':2}),flush=True)
  print(json.dumps({'event':'user_started','turn':3}),flush=True)
'''
        def exercise(owner, config, events):
            owner.start(config)
            interrupted = threading.Event()
            owner.on_event = lambda packet: interrupted.set() if packet['event']=='text_interrupted' else None
            process = owner._process
            with owner.text_question() as token:
                owner.observe(config['observation'])
                self.assertTrue(interrupted.wait(3))
                with self.assertRaises(RequestCancelled): token.check()
                self.assertTrue(owner.status()['alive'])
            self.assertIs(owner._process, process)
            with owner.text_question() as next_token:
                next_token.check()
            self.assertEqual(owner._control_ack, 4)
        self.run_fixture(script, exercise)

    def test_text_control_acknowledges_without_restarting_worker(self):
        script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
for line in sys.stdin:
 packet=json.loads(line)
 if packet['action'] in ('text_begin','text_end'):
  print(json.dumps({'event':'control_ack','request':packet['request']}),flush=True)
'''
        def exercise(owner, config, events):
            owner.start(config)
            process = owner._process
            for _ in range(2):
                with owner.text_question():
                    self.assertEqual(owner._control_ack, owner._control_sequence)
                    self.assertTrue(owner.status()['alive'])
                self.assertIs(owner._process, process)
            self.assertEqual(owner._control_sequence, 4)
            with self.assertRaisesRegex(ValueError, 'model failed'):
                with owner.text_question(): raise ValueError('model failed')
            self.assertEqual(owner._control_ack, 6)
            self.assertEqual([event['event'] for event in events], ['listening'])
            owner.stop()
            owner.start(config)
            with owner.text_question(): pass
            self.assertEqual(owner._control_ack, 2)
        self.run_fixture(script, exercise)

    def test_revoke_wakes_pending_text_control(self):
        script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
sys.stdin.read()
'''
        def exercise(owner, config, events):
            owner.start(config)
            pending = threading.Event()
            failures = []
            encode = owner._encode
            def encoded(packet):
                if packet.get('action') == 'text_begin': pending.set()
                return encode(packet)
            def ask():
                try:
                    with owner.text_question(): self.fail('unacknowledged control admitted question')
                except Exception as error: failures.append(error)
            with patch.object(owner, '_encode', side_effect=encoded):
                thread = threading.Thread(target=ask)
                thread.start()
                self.assertTrue(pending.wait(2))
                owner.stop()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertFalse(owner.status()['alive'])
        self.run_fixture(script, exercise)

    def test_revoke_during_text_turn_does_not_resume_old_worker(self):
        script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
for line in sys.stdin:
 packet=json.loads(line)
 print(json.dumps({'event':'control_ack','request':packet['request']}),flush=True)
'''
        def exercise(owner, config, events):
            owner.start(config)
            with owner.text_question(): owner.stop()
            self.assertFalse(owner.status()['alive'])
            self.assertEqual(owner._control_sequence, 1)
        self.run_fixture(script, exercise)

    def test_revoked_admission_does_not_spawn(self):
        owner = MicrophoneProcess(root='.', on_event=lambda value:None)
        token = owner.admission_token()
        owner.stop()
        with patch('extensions.companion.microphone_process.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'revoked'):
                owner.start({}, admission_token=token)
            spawn.assert_not_called()

    def run_fixture(self, script, exercise):
        launch = subprocess.Popen
        children, jobs = [], []
        class Job:
            def __init__(self): self.closed = False; jobs.append(self)
            def assign(self, child): self.child = child
            def close(self):
                self.closed = True
                if self.child.poll() is None: self.child.kill()
        def popen(command, **options):
            child = launch([sys.executable, '-u', '-c', script], **options)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as folder:
            events = []
            owner = MicrophoneProcess(root=folder, on_event=events.append)
            value = {'observed_at':'2026-10-08T00:00:00+00:00', 'source':'window-visual',
                     'target':'lesson', 'valid':True, 'text':'diagram'}
            config = {'observation':value, 'model':folder}
            with patch('extensions.companion.microphone_process.require_configuration'), \
                 patch('extensions.companion.microphone_process.capability_python', return_value=sys.executable), \
                 patch('extensions.companion.microphone_process.ChildJob', Job), \
                 patch('extensions.companion.microphone_process.subprocess.Popen', side_effect=popen):
                try: exercise(owner, config, events)
                finally: owner.stop()
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertTrue(all(job.closed for job in jobs))

    def test_observation_and_target_withdrawal_over_real_pipes(self):
        script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
for line in sys.stdin:
 value=json.loads(line)['observation']
 print(json.dumps({'event':'transcribed','text':value['text']}),flush=True)
'''
        def exercise(owner, config, events):
            self.assertEqual(owner.start(config)['status'], 'listening')
            received = threading.Event()
            owner.on_event = lambda value: (events.append(value), received.set())
            self.assertTrue(owner.observe({**config['observation'], 'text':'next page'}))
            self.assertTrue(received.wait(3))
            self.assertEqual(events[-1]['text'], 'next page')
            self.assertFalse(owner.observe({**config['observation'], 'target':'other'}))
            self.assertFalse(owner.status()['alive'])
        self.run_fixture(script, exercise)

    def test_stop_interrupts_handshake(self):
        script = 'import sys; sys.stdin.readline(); sys.stdin.read()'
        def exercise(owner, config, events):
            failures = []
            def start():
                try: owner.start(config)
                except Exception as error: failures.append(error)
            thread = threading.Thread(target=start)
            thread.start()
            import time
            deadline = time.monotonic()+3
            while not owner.status()['alive'] and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(owner.status()['alive'])
            owner.stop()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertFalse(owner.status()['alive'])
        self.run_fixture(script, exercise)

    def test_malformed_event_reclaims_worker(self):
        script = "import sys; sys.stdin.readline(); print('{}',flush=True); sys.stdin.read()"
        def exercise(owner, config, events):
            with self.assertRaises(RuntimeError): owner.start(config)
            self.assertFalse(owner.status()['alive'])
            self.assertEqual(events, [])
        self.run_fixture(script, exercise)

    def test_segmented_playback_events_do_not_kill_voice_worker(self):
        script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
sys.stdin.readline()
for event in ('playback_started','segment_started','segment_ended','interrupted'):
 print(json.dumps({'event':event,'turn':1}),flush=True)
sys.stdin.read()
'''
        def exercise(owner, config, events):
            self.assertEqual(owner.start(config)['status'], 'listening')
            completed = threading.Event()
            def event(value):
                events.append(value)
                if value['event'] == 'interrupted': completed.set()
            owner.on_event = event
            owner.observe(config['observation'])
            self.assertTrue(completed.wait(3))
            self.assertEqual([value['event'] for value in events],
                ['listening','playback_started','segment_started','segment_ended','interrupted'])
            self.assertTrue(owner.status()['alive'])
        self.run_fixture(script, exercise)

    def test_turn_error_keeps_listening_but_fatal_error_reclaims_worker(self):
        for fatal in (False, True):
            script = '''import sys,json
config=json.loads(sys.stdin.readline())
print(json.dumps({'event':'listening','target':config['observation']['target']}),flush=True)
sys.stdin.readline()
print(json.dumps({'event':'error','reason':'TimeoutError','fatal':FATAL}),flush=True)
sys.stdin.read()
'''.replace('FATAL', repr(fatal))
            def exercise(owner, config, events):
                owner.start(config)
                reported = threading.Event()
                owner.on_event = lambda value: (events.append(value), reported.set())
                owner.observe(config['observation'])
                self.assertTrue(reported.wait(3))
                if fatal:
                    import time
                    deadline = time.monotonic()+3
                    while owner.status()['alive'] and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertFalse(owner.status()['alive'])
                else:
                    self.assertTrue(owner.status()['alive'])
                    self.assertEqual(owner.status()['status'], 'listening')
            self.run_fixture(script, exercise)

    def test_packet_budget_is_checked_before_queueing(self):
        owner = MicrophoneProcess(root='.', on_event=lambda value:None)
        with self.assertRaisesRegex(ValueError, 'budget'):
            owner.observe({'text':'x'*8_000_000})
