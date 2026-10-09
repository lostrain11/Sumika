import io
import json
import tempfile
import threading
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.companion.application_audio_worker import run, require_asr, snapshot_media_identity
from extensions.companion.application_audio_process import ApplicationAudioProcess
from extensions.capabilities import CapabilityStore


class ApplicationAudioWorkerTests(unittest.TestCase):
    def test_media_identity_snapshot_is_bounded_and_detached(self):
        identity = {'page': {'part': 1}}
        snapshot = snapshot_media_identity(identity)
        identity['page']['part'] = 2
        self.assertEqual(snapshot['page']['part'], 1)
        for invalid in ([], {'value': float('nan')}, {'value': 'x' * 4096}):
            with self.assertRaises(ValueError):
                snapshot_media_identity(invalid)

    def test_parent_fences_late_transcripts_from_different_media(self):
        for actual in (None, {'video': 'old'}, {'video': 'current'}):
            with self.subTest(actual=actual):
                values, clears = [], []
                owner = ApplicationAudioProcess(root='.', on_observation=values.append,
                                               on_clear=lambda: clears.append(True))
                owner._epoch = 1
                class Process:
                    stdout = io.StringIO(json.dumps({'observation': {
                        'source': 'application-audio-transcript', 'target': 'lesson',
                        'metadata': {'process_id': 5, 'process_creation': '7',
                                     'media_identity': actual}}}) + '\n')
                    def poll(self): return 0
                    def wait(self, timeout): return 0
                owner._read(Process(), 1, {'target': 'lesson', 'process_id': 5,
                    'creation': '7', 'media_identity': {'video': 'current'}})
                self.assertEqual(len(values), int(actual == {'video': 'current'}))
                self.assertEqual(clears, [True])

    def test_sensevoice_selection_is_revalidated_without_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder)/'caps.sqlite'
            store = CapabilityStore(database)
            try:
                store.configure('asr', 'sherpa-onnx-sensevoice')
                config = {'capabilities':str(database), 'asr':store.resolve('asr')}
                require_asr(config)
                store.configure('asr', 'sherpa-onnx-sensevoice', options={'changed':True})
                with self.assertRaises(PermissionError): require_asr(config)
                store.configure('asr', 'unknown')
                config['asr'] = store.resolve('asr')
                with self.assertRaises(PermissionError): require_asr(config)
            finally:
                store.close()

    def test_stop_reclaims_process_before_reporting_clear_failure(self):
        def clear(): raise OSError('context cleanup failed')
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None, on_clear=clear)
        class Process:
            stdin, stdout = io.StringIO(), io.StringIO()
            waited = False
            def wait(self, timeout): self.waited = True; return 0
            def poll(self): return 0 if self.waited else None
        class Job:
            closed = False
            def close(self): self.closed = True
        process, job = Process(), Job()
        owner._process, owner._job = process, job
        with self.assertRaisesRegex(RuntimeError, 'context cleanup'):
            owner.stop()
        self.assertTrue(process.waited and job.closed)
        self.assertTrue(process.stdin.closed and process.stdout.closed)
        self.assertFalse(owner.status()['alive'])

    def test_pause_fences_worker_and_reports_resumable_state(self):
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None,
                                        on_clear=lambda: None)
        class Process:
            stdin, stdout = io.StringIO(), io.StringIO()
            waited = False
            def wait(self, timeout): self.waited = True; return 0
            def poll(self): return 0 if self.waited else None
        class Job:
            closed = False
            def close(self): self.closed = True
        process, job = Process(), Job()
        owner._process, owner._job, owner._state = process, job, 'running'
        state = owner.pause()
        self.assertEqual(state['status'], 'paused')
        self.assertFalse(state['alive'])
        self.assertTrue(process.stdin.closed and process.stdout.closed and job.closed)
        owner._paused = False
        self.assertEqual(owner.status()['status'], 'stopped')

    def test_revoked_bridge_admission_cannot_start_new_worker(self):
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None,
                                        on_clear=lambda: None)
        token = owner.admission_token()
        owner.stop()
        with patch('extensions.companion.application_audio_process.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'revoked'):
                owner.start(process_id=5, creation='7', target='lesson', model='.',
                            approved=True, admission_token=token)
            spawn.assert_not_called()

    def test_reader_failure_closes_job_even_when_clear_callback_raises(self):
        def clear(): raise OSError('context cleanup failed')
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None, on_clear=clear)
        owner._epoch = 1
        class Process:
            stdout = io.StringIO('{}\n')
            killed = False
            def poll(self): return 0 if self.killed else None
            def kill(self): self.killed = True
            def wait(self, timeout): return 0
        class Job:
            closed = False
            def close(self): self.closed = True
        process, job = Process(), Job()
        owner._process, owner._job = process, job
        with self.assertRaisesRegex(OSError, 'cleanup'):
            owner._read(process, 1, {'target':'lesson','process_id':5,'creation':'7'})
        self.assertTrue(job.closed)
        self.assertTrue(process.killed)
        self.assertIsNone(owner._job)

    def test_stop_interrupts_pending_worker_handshake_and_reclaims_child(self):
        launch = subprocess.Popen
        launched = threading.Event()
        children, jobs, errors = [], [], []
        script = 'import sys; sys.stdin.readline(); sys.stdin.read()'
        def popen(command, **options):
            child = launch([sys.executable, '-u', '-c', script], **options)
            children.append(child)
            launched.set()
            return child
        class Job:
            def __init__(self): self.closed = False; jobs.append(self)
            def assign(self, child): pass
            def close(self): self.closed = True
        with tempfile.TemporaryDirectory() as folder:
            owner = ApplicationAudioProcess(root=folder, on_observation=lambda value: None,
                                             on_clear=lambda: None)
            def start():
                try:
                    owner.start(process_id=5, creation='7', target='lesson', model=folder,
                                capabilities=Path(folder)/'caps.sqlite', approved=True)
                except Exception as error: errors.append(error)
            with patch('extensions.companion.application_audio_process.process_identity', return_value='7'), \
                 patch('extensions.companion.application_audio_process.capability_python', return_value=sys.executable), \
                 patch('extensions.companion.application_audio_process.process_audio_helper', return_value='fixture'), \
                 patch('extensions.companion.application_audio_process.require_asr'), \
                 patch('extensions.companion.application_audio_process.ChildJob', Job), \
                 patch('extensions.companion.application_audio_process.subprocess.Popen', side_effect=popen):
                starting = threading.Thread(target=start)
                starting.start()
                try:
                    self.assertTrue(launched.wait(2))
                    before = time.monotonic()
                    owner.stop()
                    starting.join(3)
                    self.assertLess(time.monotonic()-before, 3)
                    self.assertFalse(starting.is_alive())
                    self.assertEqual(len(errors), 1)
                    self.assertIn('revoked', str(errors[0]))
                    self.assertTrue(all(child.poll() is not None for child in children))
                    self.assertTrue(all(job.closed for job in jobs))
                    self.assertFalse(owner.status()['alive'])
                finally:
                    owner.stop()
                    starting.join(3)

    def test_stop_during_preflight_prevents_spawn(self):
        entered, released = threading.Event(), threading.Event()
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None,
                                        on_clear=lambda: None)
        errors = []
        def identity(pid): entered.set(); released.wait(3); return '7'
        def start():
            try: owner.start(process_id=5, creation='7', target='lesson', model='.', approved=True)
            except Exception as error: errors.append(error)
        with patch('extensions.companion.application_audio_process.process_identity', side_effect=identity), \
             patch('extensions.companion.application_audio_process.capability_python', return_value=sys.executable), \
             patch('extensions.companion.application_audio_process.process_audio_helper', return_value='fixture'), \
             patch('extensions.companion.application_audio_process.require_asr'), \
             patch('extensions.companion.application_audio_process.subprocess.Popen') as spawn:
            thread = threading.Thread(target=start)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                owner.stop()
            finally:
                released.set()
                thread.join(3)
            spawn.assert_not_called()
            self.assertEqual(len(errors), 1)
            self.assertIn('revoked', str(errors[0]))

    def test_running_worker_stops_when_selected_asr_is_disabled(self):
        released = threading.Event()
        self.addCleanup(released.set)
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder)/'caps.sqlite'
            store = CapabilityStore(database)
            store.configure('asr', 'vosk')
            selected = store.resolve('asr')
            store.close()
            config = dict(consent=True, helper='fixture', process_id=5, creation='7',
                          model=folder, target='lesson', capabilities=str(database), asr=selected)
            class Input:
                def readline(self, size): return json.dumps(config)+'\n'
                def read(self, size): released.wait(3); return ''
            class Track:
                stopped = False
                def start(self):
                    registry = CapabilityStore(database)
                    try: registry.configure('asr', 'vosk', enabled=False)
                    finally: registry.close()
                def stop(self): self.stopped = True; released.set()
                def status(self): return {'state':'recording'}
            track, output = Track(), io.StringIO()
            with patch('extensions.companion.application_audio_worker.ApplicationAudioTrack.configured',
                       return_value=track):
                self.assertEqual(run(Input(), output), 1)
            self.assertTrue(track.stopped)
            self.assertEqual(json.loads(output.getvalue())['error'], 'PermissionError')

    def test_changed_asr_blocks_transcript_before_it_crosses_pipe(self):
        from extensions.companion.contracts import ObservationBundle
        released = threading.Event()
        self.addCleanup(released.set)
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder)/'caps.sqlite'
            store = CapabilityStore(database)
            store.configure('asr', 'vosk')
            selected = store.resolve('asr')
            store.close()
            config = dict(consent=True, helper='fixture', process_id=5, creation='7',
                          model=folder, target='lesson', capabilities=str(database), asr=selected)
            class Input:
                def readline(self, size): return json.dumps(config)+'\n'
                def read(self, size): released.wait(3); return ''
            class Track:
                stopped = False
                def start(self):
                    registry = CapabilityStore(database)
                    try: registry.configure('asr', 'vosk', options={'changed':True})
                    finally: registry.close()
                    callback(ObservationBundle.now(source='application-audio-transcript',
                        target='lesson', valid=True, text='late'))
                def stop(self): self.stopped = True; released.set()
            track, output = Track(), io.StringIO()
            def factory(**kwargs):
                nonlocal callback
                callback = kwargs['on_transcript']
                return track
            callback = None
            with patch('extensions.companion.application_audio_worker.ApplicationAudioTrack.configured',
                       side_effect=factory):
                self.assertEqual(run(Input(), output), 1)
            self.assertTrue(track.stopped)
            self.assertNotIn('observation', output.getvalue())
            self.assertIn('PermissionError', output.getvalue())

    def test_parent_real_pipe_start_stop_reclaims_job(self):
        launch = subprocess.Popen
        children, jobs = [], []
        script = ("import sys,json; c=json.loads(sys.stdin.readline()); "
                  "print(json.dumps(dict(status='running',target=c['target'])),flush=True); "
                  "sys.stdin.read()")
        def popen(command, **options):
            process = launch([sys.executable, '-u', '-c', script], **options)
            children.append(process)
            return process
        class Job:
            def __init__(self): self.closed = False; jobs.append(self)
            def assign(self, process): pass
            def close(self): self.closed = True
        with tempfile.TemporaryDirectory() as folder:
            owner = ApplicationAudioProcess(root=folder, on_observation=lambda value: None,
                                            on_clear=lambda: None)
            with patch('extensions.companion.application_audio_process.process_identity', return_value='7'), \
                 patch('extensions.companion.application_audio_process.capability_python', return_value=sys.executable), \
                 patch('extensions.companion.application_audio_process.process_audio_helper', return_value='fixture'), \
             patch('extensions.companion.application_audio_process.ChildJob', Job), \
                 patch('extensions.companion.application_audio_process.require_asr'), \
                 patch('extensions.companion.application_audio_process.subprocess.Popen', side_effect=popen):
                try:
                    self.assertEqual(owner.start(process_id=5, creation='7', target='lesson',
                        model=folder, approved=True, capabilities=Path(folder)/'caps.sqlite')['status'], 'running')
                finally:
                    owner.stop()
                    owner.stop()
            self.assertTrue(all(process.poll() is not None for process in children))
            self.assertTrue(all(job.closed for job in jobs))
            self.assertFalse(owner.status()['alive'])

    def test_media_anchor_and_rate_are_bounded_before_process_start(self):
        import math
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None,
                                        on_clear=lambda: None)
        with patch('extensions.companion.application_audio_process.process_identity', return_value='7'):
            for value in (-1, float('nan'), float('inf'), True, '1'):
                with self.assertRaises(ValueError):
                    owner.start(process_id=5, creation='7', target='lesson', model='.',
                                approved=True, media_time_seconds=value)
            for value in (0, -1, 16.1, float('nan'), float('inf'), True, '1'):
                with self.assertRaises(ValueError):
                    owner.start(process_id=5, creation='7', target='lesson', model='.',
                                approved=True, playback_rate=value)

    def test_worker_stops_on_owner_eof_and_never_retains_recording(self):
        closed = threading.Event()
        class Input:
            def readline(self, size):
                return json.dumps(dict(consent=True, helper='fixture', process_id=5,
                    creation='7', model='fixture', target='lesson'))+'\n'
            def read(self, size): closed.wait(2); return ''
        class Track:
            stopped = False
            def start(self): closed.set()
            def stop(self): self.stopped = True
            def status(self): return {'state':'recording'}
        track, output = Track(), io.StringIO()
        with patch('extensions.companion.application_audio_worker.ApplicationAudioTrack.configured',
                   return_value=track), patch('extensions.companion.application_audio_worker.require_asr'):
            self.assertEqual(run(Input(), output), 0)
        self.assertTrue(track.stopped)

    def test_worker_rejects_missing_consent_before_capture(self):
        with patch('extensions.companion.application_audio_worker.ApplicationAudioTrack.configured') as factory:
            output = io.StringIO()
            self.assertEqual(run(io.StringIO('{}\n'), output), 1)
            factory.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['error'], 'PermissionError')

    def test_worker_attaches_starting_media_to_transcript(self):
        from extensions.companion.contracts import ObservationBundle
        closed = threading.Event()
        class Input:
            def readline(self, size):
                return json.dumps(dict(consent=True, helper='fixture', process_id=5,
                    creation='7', model='fixture', target='lesson',
                    media_identity={'video': 'starting'})) + '\n'
            def read(self, size): closed.wait(2); return ''
        def configured(**options):
            class Track:
                def start(self):
                    options['on_transcript'](ObservationBundle.now(
                        source='application-audio-transcript', target='lesson',
                        valid=True, text='narration', metadata={'process_id': 5}))
                    closed.set()
                def stop(self): closed.set()
                def status(self): return {'state': 'recording'}
            return Track()
        output = io.StringIO()
        with patch('extensions.companion.application_audio_worker.ApplicationAudioTrack.configured',
                   side_effect=configured), patch('extensions.companion.application_audio_worker.require_asr'):
            self.assertEqual(run(Input(), output), 0)
        observations = [json.loads(line)['observation'] for line in output.getvalue().splitlines()
                        if 'observation' in json.loads(line)]
        self.assertEqual(observations[0]['metadata']['media_identity'], {'video': 'starting'})

    def test_sensevoice_preloads_before_stdin_watcher(self):
        loaded, closed = threading.Event(), threading.Event()
        class Input:
            def readline(self, size):
                return json.dumps(dict(consent=True, helper='fixture', process_id=5,
                    creation='7', model='fixture', target='lesson',
                    asr={'provider':'sherpa-onnx-sensevoice'}))+'\n'
            def read(self, size):
                self.preloaded = loaded.is_set()
                closed.wait(2)
                return ''
        class Provider:
            def load_model(self): loaded.set()
        class Track:
            provider = Provider()
            def prepare(self): self.provider.load_model()
            def start(self): closed.set()
            def stop(self): closed.set()
            def status(self): return {'state':'recording'}
        source = Input()
        with patch('extensions.companion.application_audio_worker.ApplicationAudioTrack.configured',
                   return_value=Track()), patch('extensions.companion.application_audio_worker.require_asr'):
            self.assertEqual(run(source, io.StringIO()), 0)
        self.assertTrue(source.preloaded)

    def test_parent_rejects_foreign_transcript_and_clears_context(self):
        values, clears = [], []
        owner = ApplicationAudioProcess(root='.', on_observation=values.append,
                                        on_clear=lambda: clears.append(True))
        owner._epoch = 1
        class Process:
            stdout = io.StringIO(json.dumps({'observation': {
                'source':'application-audio-transcript', 'target':'wrong',
                'metadata':{'process_id':5,'process_creation':'7'}}})+'\n')
            def poll(self): return 0
            def wait(self, timeout): return 0
        owner._read(Process(), 1, {'target':'lesson','process_id':5,'creation':'7'})
        self.assertEqual(values, [])
        self.assertEqual(clears, [True])
        self.assertEqual(owner.status()['status'], 'error')

    def test_parent_rejects_consent_and_runtime_before_spawn(self):
        owner = ApplicationAudioProcess(root='.', on_observation=lambda value: None,
                                        on_clear=lambda: None)
        with self.assertRaises(PermissionError):
            owner.start(process_id=5, creation='7', target='lesson', model='.')
        with patch('extensions.companion.application_audio_process.process_identity', return_value='7'), \
             patch('extensions.companion.application_audio_process.capability_python', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'runtime'):
                owner.start(process_id=5, creation='7', target='lesson', model='.', approved=True)
