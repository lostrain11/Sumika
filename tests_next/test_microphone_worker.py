import asyncio
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.capabilities import CapabilityStore
from extensions.companion.microphone_worker import require_configuration, run_session


class MicrophoneWorkerTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_proactive_start_failure_reports_nonfatal_event_and_releases_session(self):
        from extensions.companion.observation_scheduler import ObservationScheduler
        now = [0.0]
        failed = threading.Event()
        events, stopped = [], []
        class Input:
            def readline(self, size):
                failed.wait(5)
                return ''
        class Player:
            def close(self): stopped.append('player')
        class Turn:
            busy = False
            def start_discussion(self, prompt):
                raise RuntimeError('private screen and provider details')
            async def cleanup(self): pass
        def scheduler(*args, **kwargs):
            kwargs['settled_seconds'] = 0
            return ObservationScheduler(*args, clock=lambda:now[0], **kwargs)
        def emit(packet):
            events.append(packet)
            if packet.get('stage') == 'proactive_start': failed.set()
        async def microphone(worker, *, stop_event, on_started, **kwargs):
            on_started()
            now[0] = 121
            await stop_event.wait()
            stopped.append('microphone')
        with patch('extensions.companion.microphone_worker.ObservationScheduler', side_effect=scheduler), \
             patch('extensions.companion.pipecat_voice.build_sapi_study_worker', return_value=(object(), Turn())), \
             patch('extensions.companion.pipecat_voice.run_microphone', side_effect=microphone), \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()):
            await asyncio.wait_for(run_session(self.config, Input(), emit), 6)
        self.assertTrue(failed.is_set())
        errors = [event for event in events if event.get('stage') == 'proactive_start']
        self.assertEqual(errors, [{'event':'error', 'reason':'RuntimeError',
                                   'stage':'proactive_start', 'fatal':False}])
        self.assertEqual(stopped, ['microphone', 'player'])

    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_session_scheduler_discussion_and_pipe_revoke_stop_actual_pipeline(self):
        from extensions.companion.pipecat_voice import build_study_voice_worker
        from extensions.companion.observation_scheduler import ObservationScheduler
        from pipecat.workers.runner import WorkerRunner
        now = [0.0]
        playing = threading.Event()
        stopped, events, services = [], [], []
        acknowledged = [threading.Event(), threading.Event()]
        class Input:
            index = 0
            def readline(self, size):
                if not playing.wait(6):
                    return ''
                self.index += 1
                if self.index == 1:
                    return json.dumps({'action':'text_begin','request':1})+'\n'
                if not acknowledged[min(self.index-2, 1)].wait(6):
                    return ''
                if self.index == 2:
                    return json.dumps({'action':'text_end','request':2})+'\n'
                return json.dumps({'action':'revoke'})+'\n'
        def emit(value):
            events.append(value)
            if value['event'] == 'control_ack':
                acknowledged[value['request']-1].set()
        class Player:
            def close(self): stopped.append('owner')
        class ASR:
            async def __call__(self, *args, **kwargs):
                raise AssertionError('proactive session must not use ASR')
        class Chat:
            def __init__(self, settings): pass
            def reply(self, prompt, on_delta, **kwargs):
                self_test.assertFalse(kwargs['memory_writes'])
                on_delta('learning point.')
                return {'text':'learning point.'}
        self_test = self
        async def play(text):
            playing.set()
            try: await asyncio.Event().wait()
            finally: stopped.append('segment')
        async def stop(): stopped.append('stop')
        def factory(**kwargs):
            services.append(kwargs['question_service'])
            return build_study_voice_worker(model_path='fixture',
                question_service=kwargs['question_service'], approved=True,
                play_segment=play, stop_playback=stop, on_event=kwargs['on_event'],
                on_delta=kwargs['on_delta'], observation_scheduler=kwargs['observation_scheduler'])
        async def microphone(worker, *, stop_event, on_started, **kwargs):
            runner = WorkerRunner(handle_sigint=False)
            await runner.add_workers(worker)
            running = asyncio.create_task(runner.run())
            try:
                on_started()
                await asyncio.sleep(.1)
                now[0] = 121
                await asyncio.sleep(1.1)
                now[0] = 125
                await stop_event.wait()
            finally:
                await worker.cancel()
                await running
                stopped.append('microphone')
        with patch('extensions.companion.microphone_worker.ObservationScheduler',
                   side_effect=lambda *args, **kwargs: ObservationScheduler(*args, clock=lambda:now[0], **kwargs)), \
             patch('extensions.companion.pipecat_voice.build_sapi_study_worker', side_effect=factory), \
             patch('extensions.companion.pipecat_voice.run_microphone', side_effect=microphone), \
             patch('extensions.companion.audio_providers.VoskPcmProvider', return_value=ASR()), \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()), \
             patch('extensions.roles.chat.RoleChat', Chat):
            await asyncio.wait_for(run_session(self.config, Input(), emit), 8)
        self.assertTrue(playing.is_set())
        self.assertIn('proactive_started', [event['event'] for event in events])
        self.assertIn('playback_started', [event['event'] for event in events])
        self.assertIn('segment', stopped)
        self.assertEqual([event['request'] for event in events if event['event']=='control_ack'], [1,2])
        self.assertEqual(sum(event['event']=='listening' for event in events), 1)
        self.assertEqual(stopped[-2:], ['microphone','owner'])
        self.assertEqual(services[0]._histories, {})
        self.assertEqual(services[0]._active_requests, set())

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        store = CapabilityStore(root/'capabilities.sqlite')
        try:
            for kind, provider in (('microphone','sounddevice'), ('asr','vosk'), ('voice','windows-sapi')):
                store.configure(kind, provider, options={'user_authorized': True} if kind == 'microphone' else {})
            selected = {kind:store.resolve(kind) for kind in ('microphone','asr','voice')}
        finally: store.close()
        self.settings = {'enabled':True, 'voice':{'enabled':True,'sample_rate':16000,
            'input_device':7,'tts_voice':'fixture'}, 'role':{'role_dir':str(root)}}
        self.config = {'settings_path':str(root/'settings.json'), 'settings':self.settings,
            'capabilities':str(root/'capabilities.sqlite'), 'selected':selected, 'role_id':'fixture',
            'microphone_consent':True,'playback_consent':True,'root':str(root),
            'model':str(root),'runtime_directory':str(root/'voice'),
            'observation':{'observed_at':'2026-10-08T00:00:00+00:00','source':'window-visual',
                           'target':'lesson','valid':True,'text':'diagram'}}
        self.settings_patch = patch('extensions.companion.microphone_worker.load_settings', return_value=self.settings)
        self.role_patch = patch('extensions.companion.microphone_worker.load_role', return_value={'id':'fixture'})
        self.settings_patch.start(); self.role_patch.start()
        self.addCleanup(self.settings_patch.stop); self.addCleanup(self.role_patch.stop)

    async def test_microphone_and_playback_require_separate_consent(self):
        for key in ('microphone_consent','playback_consent'):
            config = {**self.config,key:False}
            with self.assertRaises(PermissionError): require_configuration(config)

    async def test_live_capability_changes_refuse_configuration(self):
        require_configuration(self.config)
        store = CapabilityStore(self.config['capabilities'])
        try: store.configure('microphone','sounddevice', enabled=False)
        finally: store.close()
        with self.assertRaises(PermissionError): require_configuration(self.config)

    async def test_discussion_respects_disable_and_minimum_interval(self):
        require_configuration({**self.config, 'proactive':{'enabled':False,'interval_seconds':600}})
        for mode in ({'enabled':True,'interval_seconds':1},
                     {'enabled':'yes','interval_seconds':120},
                     {'enabled':True,'interval_seconds':float('nan')}):
            with self.assertRaises(ValueError):
                require_configuration({**self.config,'proactive':mode})

    async def test_sensevoice_is_explicit_and_revalidated_without_fallback(self):
        store = CapabilityStore(self.config['capabilities'])
        try:
            store.configure('asr', 'sherpa-onnx-sensevoice')
            self.config['selected']['asr'] = store.resolve('asr')
            require_configuration(self.config)
            store.configure('asr', 'vosk')
            with self.assertRaises(PermissionError):
                require_configuration(self.config)
            store.configure('asr', 'unimplemented-asr')
            self.config['selected']['asr'] = store.resolve('asr')
            with self.assertRaises(PermissionError):
                require_configuration(self.config)
        finally:
            store.close()

    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_factory_failure_closes_owned_player(self):
        release = threading.Event()
        closed = []
        class Input:
            def readline(self, size): release.wait(3); return ''
        class Player:
            def close(self): closed.append(True); release.set()
        with patch('extensions.companion.pipecat_voice.build_sapi_study_worker', side_effect=RuntimeError('load failed')), \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()):
            with self.assertRaisesRegex(RuntimeError, 'load failed'):
                await run_session(self.config, Input(), lambda value:None)
        self.assertEqual(closed, [True])

    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_withdrawal_during_model_load_never_opens_microphone(self):
        loading, withdrawn = threading.Event(), threading.Event()
        cleanup = []
        class Input:
            def readline(self, size):
                loading.wait(3)
                withdrawn.set()
                return json.dumps({'action':'revoke'})+'\n'
        class Turn:
            busy = False
            async def cleanup(self): cleanup.append('turn')
        class Player:
            def close(self): cleanup.append('player')
        def factory(**kwargs):
            loading.set()
            withdrawn.wait(3)
            # Wait until the control thread has consumed the withdrawal.
            import time
            time.sleep(0.05)
            return object(), Turn()
        with patch('extensions.companion.pipecat_voice.build_sapi_study_worker', side_effect=factory), \
             patch('extensions.companion.pipecat_voice.run_microphone') as microphone, \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()):
            await run_session(self.config, Input(), lambda value:None)
        microphone.assert_not_called()
        self.assertEqual(cleanup, ['turn','player'])

    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_invalid_target_during_loading_is_not_overwritten_by_valid_frame(self):
        loading, received = threading.Event(), threading.Event()
        cleanup, reads = [], []
        class Input:
            def readline(inner, size):
                loading.wait(3)
                reads.append(True)
                received.set()
                value = {**self.config['observation'], 'valid':len(reads) != 1}
                return json.dumps({'action':'observe','observation':value})+'\n'
        class Turn:
            busy = False
            async def cleanup(self): cleanup.append('turn')
        class Player:
            def close(self): cleanup.append('player')
        def factory(**kwargs):
            loading.set()
            received.wait(3)
            import time
            time.sleep(0.05)
            return object(), Turn()
        with patch('extensions.companion.pipecat_voice.build_sapi_study_worker', side_effect=factory), \
             patch('extensions.companion.pipecat_voice.run_microphone') as microphone, \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()):
            with self.assertRaisesRegex(RuntimeError, 'target changed'):
                await run_session(self.config, Input(), lambda value:None)
        microphone.assert_not_called()
        self.assertEqual(len(reads), 1)
        self.assertEqual(cleanup, ['turn','player'])

    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_owner_eof_stops_microphone_and_owned_player(self):
        started = threading.Event()
        events, stopped = [], []
        class Input:
            def readline(self, size): started.wait(3); return ''
        class Turn:
            busy = False
            async def cleanup(self): pass
        class Player:
            def close(self): stopped.append('player')
        async def microphone(worker, *, approved, device, stop_event, on_started):
            self.assertTrue(approved)
            self.assertEqual(device, 7)
            on_started()
            started.set()
            await stop_event.wait()
            stopped.append('microphone')
        with patch('extensions.companion.pipecat_voice.build_sapi_study_worker', return_value=(object(),Turn())), \
             patch('extensions.companion.pipecat_voice.run_microphone', side_effect=microphone), \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()):
            await asyncio.wait_for(run_session(self.config, Input(), events.append), 3)
        self.assertEqual(events[0]['event'], 'listening')
        self.assertEqual(stopped, ['microphone','player'])

    @unittest.skipUnless(importlib.util.find_spec('pipecat'), 'isolated voice environment required')
    async def test_target_switch_cancels_voice_without_rebinding_to_other_window(self):
        started = threading.Event()
        sent = False
        stopped = []
        class Input:
            def readline(inner, size):
                nonlocal sent
                started.wait(3)
                if not sent:
                    sent = True
                    value = {**self.config['observation'], 'target':'other'}
                    return json.dumps({'action':'observe','observation':value})+'\n'
                threading.Event().wait(0.5)
                return ''
        class Turn:
            busy = False
            async def cleanup(self): pass
        class Player:
            def close(self): stopped.append('player')
        async def microphone(worker, *, stop_event, on_started, **kwargs):
            started.set()
            await stop_event.wait()
            stopped.append('microphone')
        with patch('extensions.companion.pipecat_voice.build_sapi_study_worker', return_value=(object(),Turn())), \
             patch('extensions.companion.pipecat_voice.run_microphone', side_effect=microphone), \
             patch('extensions.companion.sapi_playback.DirectSapiPlayback', return_value=Player()):
            with self.assertRaisesRegex(RuntimeError, 'target changed'):
                await asyncio.wait_for(run_session(self.config, Input(), lambda value:None), 3)
        self.assertEqual(stopped, ['microphone','player'])
