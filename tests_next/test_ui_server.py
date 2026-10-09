import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from extensions.models.settings import example, save as save_settings, load as load_settings
from extensions.roles.roles import import_card
from ui.server import serve


def _role_dir(root):
    card = root / "card.json"
    card.write_text(json.dumps({"spec": "chara_card_v2", "data": {
        "name": "安和昴", "description": "人格",
        "extensions": {"sumika": {"language_policy": "默认简体中文，不出现日文假名。",
                                  "name_map": {"桃香さん": "桃香"}}},
        "character_book": {"entries": []}}}, ensure_ascii=False), encoding="utf8")
    return import_card(card, root / "store", "ui-role")


class UIServerTests(unittest.TestCase):
    def test_oneshot_configuration_accepts_sensevoice_and_checks_rate(self):
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        store = CapabilityStore(bridge.capability_database)
        try:
            store.configure('microphone','sounddevice', options={'user_authorized':True})
            store.configure('asr','sherpa-onnx-sensevoice')
        finally:
            store.close()
        settings = load_settings(self.settings_path)
        settings['voice'].update(enabled=True, input_device=7, sample_rate=16000,
                                 asr_model=str(self.settings_path.parent))
        with patch('ui.server.load_settings', return_value=settings), \
             patch('extensions.desktop.audio_devices.env_python', return_value='python.exe'):
            config = bridge.speech_configuration('ui-role')
            self.assertEqual(config['asr']['provider'], 'sherpa-onnx-sensevoice')
            settings['voice']['sample_rate'] = 22050
            with self.assertRaisesRegex(ValueError, '16kHz'):
                bridge.speech_configuration('ui-role')

    def test_pet_endpoint_uses_actual_bridge_port_and_no_custom_arguments(self):
        bridge=self.server.sumika_bridge
        with patch.object(bridge._pet_host,'start',return_value={'status':'running','alive':True}) as start:
            _, result=self.request('/api/companion/pet',method='POST',body={'action':'start'})
            self.assertTrue(result['alive'])
            start.assert_called_once_with(self.server.server_port)
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/companion/pet',method='POST',body={'action':'start','url':'https://example.com'})
            self.assertEqual(start.call_count,1)

    def test_pet_status_never_starts_and_shutdown_fences_launch(self):
        bridge=self.server.sumika_bridge
        with patch.object(bridge._pet_host,'start') as start:
            _, result=self.request('/api/companion/pet',method='POST',body={'action':'status'})
            self.assertFalse(result['alive'])
            bridge._shutdown_requested.set()
            try:
                with self.assertRaises(RuntimeError): bridge.companion_pet({'action':'start'})
            finally: bridge._shutdown_requested.clear()
            start.assert_not_called()

    def test_text_question_rejects_changed_capture_without_model_call(self):
        bridge=self.server.sumika_bridge
        with patch.object(bridge._companion,'ask') as ask:
            with self.assertRaisesRegex(ValueError,'stopped or changed'):
                bridge.companion_ask('why',expected_target='window:123:pid:42')
            ask.assert_not_called()

    def test_text_question_binds_target_and_keeps_voice_owner(self):
        bridge=self.server.sumika_bridge
        bridge.companion_observe({'source':'window-visual','target':'window:123:pid:42',
                                  'valid':True,'text':'lesson'})
        with patch.object(bridge._perception,'status',return_value={'alive':True,'target':{'handle':123,'process_id':42}}), \
             patch.object(bridge._microphone,'stop') as stop, \
             patch.object(bridge._companion,'ask',return_value={'text':'answer'}) as ask:
            bridge.companion_ask('why',expected_target='window:123:pid:42')
            stop.assert_not_called()
            self.assertEqual(ask.call_args.kwargs['binding'].observation.target,'window:123:pid:42')
    def test_voice_status_does_not_hold_event_lock_while_reading_capture_state(self):
        bridge = self.server.sumika_bridge
        failures = []
        def capture_status():
            finished = threading.Event()
            def callback():
                bridge._companion_microphone_event({'event':'delta','text':'parallel'})
                finished.set()
            thread = threading.Thread(target=callback)
            thread.start()
            if not finished.wait(1):
                failures.append('capture status blocked voice callback')
            thread.join(1)
            return {'status':'running','alive':True}
        with patch.object(bridge._perception,'status',side_effect=capture_status), \
             patch.object(bridge._application_audio,'status',return_value={'status':'running','alive':True}):
            result=bridge.companion_microphone({'action':'status'})
        self.assertEqual(failures, [])
        self.assertTrue(result['capture']['alive'])
        self.assertTrue(result['application_audio']['alive'])
        self.assertEqual(result['events'][-1]['text'],'parallel')

    def test_microphone_requires_both_consents_before_launch(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge._microphone, 'start') as launch:
            for payload in ({'action':'start'}, {'action':'start','microphone_consent':True},
                            {'action':'start','playback_consent':True}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/microphone', method='POST', body=payload)
            launch.assert_not_called()

    def test_microphone_events_are_bounded_and_cursor_filtered(self):
        bridge = self.server.sumika_bridge
        for index in range(100):
            bridge._companion_microphone_event({'event':'delta','text':str(index)})
        _, state = self.request('/api/companion/microphone', method='POST',
                                body={'action':'status','after':98})
        self.assertEqual(state['cursor'], 100)
        self.assertEqual([event['text'] for event in state['events']], ['98','99'])
        self.assertEqual(len(bridge._voice_events), 64)

    def test_visual_and_audio_updates_reach_microphone_as_fused_context(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge._microphone, 'status', return_value={'alive':True}), \
             patch.object(bridge._microphone, 'observe') as observe:
            self.request('/api/companion/observe', method='POST', body={
                'source':'window-visual','target':'lesson','valid':True,'text':'diagram'})
            self.assertIn('+00:00', observe.call_args.args[0]['observed_at'])
            bridge._companion_audio_observe({'observed_at':'2099-01-01T00:00:00+00:00',
                'source':'application-audio-transcript','target':'lesson', 'valid':True,
                'text':'narration', 'metadata':{}})
            self.assertIn('narration', observe.call_args.args[0]['text'])
            bridge._companion_audio_clear()
            self.assertEqual(observe.call_args.args[0]['text'], 'diagram')

    def test_microphone_start_revoked_during_settings_check_never_spawns(self):
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        store = CapabilityStore(bridge.capability_database)
        try:
            for kind, provider in (('microphone','sounddevice'),('asr','vosk'),('voice','windows-sapi')):
                store.configure(kind, provider, options={'user_authorized':True})
        finally: store.close()
        bridge.companion_observe({'source':'web','target':'lesson','valid':True,'text':'lesson'})
        settings = load_settings(self.settings_path)
        settings['voice'].update(enabled=True, input_device=7, asr_model=str(self.settings_path.parent))
        entered, release = threading.Event(), threading.Event()
        failures = []
        def blocked(path): entered.set(); release.wait(3); return settings
        def start():
            try: bridge.companion_microphone({'action':'start','microphone_consent':True,'playback_consent':True})
            except Exception as error: failures.append(error)
        with patch('ui.server.load_settings', side_effect=blocked), \
             patch('extensions.companion.microphone_process.subprocess.Popen') as spawn:
            worker = threading.Thread(target=start)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                bridge.companion_revoke()
            finally:
                release.set()
                worker.join(3)
            spawn.assert_not_called()
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIn('revoked', str(failures[0]))

    def test_target_switch_during_microphone_preflight_prevents_old_target_spawn(self):
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        store = CapabilityStore(bridge.capability_database)
        try:
            for kind, provider in (('microphone','sounddevice'),('asr','vosk'),('voice','windows-sapi')):
                store.configure(kind, provider, options={'user_authorized':True})
        finally: store.close()
        bridge.companion_observe({'source':'web','target':'lesson','valid':True,'text':'lesson'})
        settings = load_settings(self.settings_path)
        settings['voice'].update(enabled=True, input_device=7, asr_model=str(self.settings_path.parent))
        entered, release = threading.Event(), threading.Event()
        failures = []
        def blocked(path): entered.set(); release.wait(3); return settings
        def start():
            try: bridge.companion_microphone({'action':'start','microphone_consent':True,'playback_consent':True})
            except Exception as error: failures.append(error)
        with patch('ui.server.load_settings', side_effect=blocked), \
             patch('extensions.companion.microphone_process.subprocess.Popen') as spawn:
            worker = threading.Thread(target=start)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                bridge.companion_observe({'source':'web','target':'other','valid':True,'text':'other lesson'})
            finally:
                release.set()
                worker.join(3)
            spawn.assert_not_called()
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIn('revoked', str(failures[0]))
            self.assertEqual(bridge._companion.latest.target, 'other')

    def test_audio_start_revoked_while_bridge_checks_settings_never_spawns(self):
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        store = CapabilityStore(bridge.capability_database)
        try: store.configure('asr', 'vosk')
        finally: store.close()
        self.request('/api/companion/observe', method='POST', body={
            'source':'window-visual','target':'window:123:pid:456','valid':True,'text':'lesson'})
        settings = load_settings(self.settings_path)
        settings['voice']['enabled'] = True
        settings['voice']['asr_model'] = str(self.settings_path.parent)
        entered, release = threading.Event(), threading.Event()
        errors = []
        def blocked(path): entered.set(); release.wait(3); return settings
        def start():
            try: bridge.companion_audio({'action':'start','consent':True,
                                        'process_id':456,'process_creation':'7'})
            except Exception as error: errors.append(error)
        with patch('ui.server.load_settings', side_effect=blocked), \
             patch('extensions.companion.application_audio_process.subprocess.Popen') as spawn:
            thread = threading.Thread(target=start)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                bridge.companion_revoke()
            finally:
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            spawn.assert_not_called()
            self.assertEqual(len(errors), 1)
            self.assertIn('revoked', str(errors[0]))
            self.assertIsNone(bridge._companion.latest)

    def test_expired_audio_allows_new_visual_even_with_older_source_timestamp(self):
        bridge = self.server.sumika_bridge
        self.request('/api/companion/observe', method='POST', body={
            'observed_at':'2026-01-01T00:00:00+00:00','source':'window-visual',
            'target':'window:123:pid:456','valid':True,'text':'diagram'})
        bridge._companion_audio_observe({'observed_at':'2026-01-01T00:00:02+00:00',
            'source':'application-audio-transcript','target':'window:123:pid:456',
            'valid':True,'text':'tutorial narration','metadata':{}})
        bridge._fusion.clock = lambda: float('inf')
        _, result = self.request('/api/companion/observe', method='POST', body={
            'observed_at':'2026-01-01T00:00:01+00:00','source':'window-visual',
            'target':'window:123:pid:456','valid':True,'text':'next diagram'})
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(bridge._companion.latest.text, 'next diagram')
        self.assertEqual(bridge._companion.latest.metadata['visual_observed_at'],
                         '2026-01-01T00:00:01+00:00')

    def test_application_audio_fuses_visual_context_and_stop_removes_audio(self):
        bridge = self.server.sumika_bridge
        self.request('/api/companion/observe', method='POST', body={
            'source':'window-visual','target':'window:123:pid:456','valid':True,
            'text':'diagram','image':{'media_type':'image/jpeg','data_base64':'fixture'}})
        bridge._companion_audio_observe({'observed_at':'2099-01-01T00:00:00+00:00',
            'source':'application-audio-transcript','target':'window:123:pid:456',
            'valid':True,'text':'tutorial narration','metadata':{'capture_offset_seconds':2}})
        self.assertEqual(bridge._companion.latest.source, 'window-visual')
        self.assertIn('diagram', bridge._companion.latest.text)
        self.assertIn('tutorial narration', bridge._companion.latest.text)
        self.assertIsNotNone(bridge._companion.latest.image)
        self.request('/api/companion/audio', method='POST', body={'action':'stop'})
        self.assertEqual(bridge._companion.latest.text, 'diagram')

    def test_application_audio_pause_uses_resumable_owner_state(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge._application_audio, 'pause', return_value={
                'status':'paused','alive':False,'target':None} ) as pause:
            _, result = self.request('/api/companion/audio', method='POST',
                                     body={'action':'pause'})
        pause.assert_called_once_with()
        self.assertEqual(result['status'], 'paused')

    def test_media_state_pauses_owned_application_audio_and_clears_fusion(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge._application_audio, 'status', side_effect=[
                {'alive': True, 'target': 'video:1'},
                {'alive': False, 'target': None}]), \
             patch.object(bridge._application_audio, 'pause') as pause, \
             patch.object(bridge, '_companion_audio_clear') as clear:
            result = bridge.companion_media_state({'target':'video:1','state':'paused'})
        pause.assert_called_once_with()
        clear.assert_called_once_with()
        self.assertEqual(result['action'], 'paused_audio')

    def test_media_state_rejects_foreign_audio_target(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge._application_audio, 'status', return_value={
                'alive': True, 'target': 'video:old'}):
            with self.assertRaisesRegex(ValueError, 'does not own'):
                bridge.companion_media_state({'target':'video:new','state':'seeking'})

    def test_visual_observation_media_state_routes_through_shared_boundary(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge, 'companion_media_state', wraps=bridge.companion_media_state) as media:
            self.request('/api/companion/observe', method='POST', body={
                'source':'window-visual','target':'video:1','valid':True,
                'text':'paused frame','metadata':{'paused':True}})
        media.assert_called_once_with({'target':'video:1','state':'paused'})

    def test_application_audio_consent_and_target_checked_before_worker_launch(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge._application_audio, 'start') as launch:
            for payload in ({'action':'start'},
                            {'action':'start','consent':True,'process_id':456}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/audio', method='POST', body=payload)
            launch.assert_not_called()

    def test_media_change_stops_audio_even_when_window_is_unchanged(self):
        bridge = self.server.sumika_bridge
        payload = {'source': 'window-visual', 'target': 'window:123:pid:456',
                   'valid': True, 'text': 'new lesson',
                   'metadata': {'media_identity': {'video': 'current'}}}
        for identity, expected in (({'video': 'current'}, False), ({'video': 'old'}, True)):
            with self.subTest(identity=identity), \
                 patch.object(bridge._application_audio, 'status', return_value={
                     'target': payload['target'], 'media_identity': identity}), \
                 patch.object(bridge._application_audio, 'stop') as stop:
                bridge.companion_observe(payload)
                self.assertEqual(stop.called, expected)

    def test_capture_withdrawal_does_not_wait_for_active_answer(self):
        entered, release = threading.Event(), threading.Event()
        result, errors = [], []
        bridge = self.server.sumika_bridge
        def answer(*args, **kwargs):
            with bridge._chat_lock:
                entered.set()
                if not release.wait(5): raise RuntimeError('model fixture timed out')
                return {'text': 'old answer'}
        bridge._companion._role_chat = answer
        self.request('/api/companion/observe', method='POST', body={
            'source':'web', 'target':'lesson', 'valid':True, 'text':'lesson'})
        def ask():
            try: result.append(self.request('/api/companion/ask', method='POST', body={'question':'explain'})[1])
            except Exception as error: errors.append(str(error))
        worker = threading.Thread(target=ask)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            _, state = self.request('/api/companion/perception', method='POST', body={'action':'status'})
            self.assertFalse(state['alive'])
            _, audio = self.request('/api/companion/audio', method='POST', body={'action':'status'})
            _, microphone = self.request('/api/companion/microphone', method='POST', body={'action':'stop'})
            self.assertFalse(microphone['alive'])
            self.assertEqual(audio['status'], 'stopped')
            _, audio = self.request('/api/companion/audio', method='POST', body={'action':'stop'})
            self.assertEqual(audio['status'], 'stopped')
            _, state = self.request('/api/companion/revoke', method='POST', body={})
            self.assertEqual(state['status'], 'revoked')
            self.assertFalse(release.is_set())
        finally:
            release.set(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result[0]['status'], 'stale_response')
        self.assertNotIn('text', result[0])

    def test_perception_lifecycle_requires_consent_and_explicit_resume_state(self):
        with patch('extensions.companion.perception_process.subprocess.Popen') as launch:
            for payload in ({'action':'start','handle':123,'process_id':456},
                            {'action':'start','consent':True,'handle':'123','process_id':456},
                            {'action':'resume'}, {'action':'unknown'}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/perception', method='POST', body=payload)
            launch.assert_not_called()
            _, state = self.request('/api/companion/perception', method='POST', body={'action':'status'})
            self.assertEqual(state['status'], 'stopped')
            self.assertFalse(state['alive'])

    def test_perception_pdf_binding_validates_before_releasing_audio(self):
        bridge = self.server.sumika_bridge
        expected = str((Path(self._tmp.name) / 'lesson.pdf').resolve())
        with patch('extensions.desktop.windows_capture._identity'), \
             patch.object(bridge._application_audio, 'stop') as audio_stop, \
             patch.object(bridge._microphone, 'stop') as microphone_stop, \
             patch.object(bridge._perception, 'start', return_value={'status':'starting'}) as start:
            for invalid in ('relative.pdf', 123, expected.replace('.pdf', '.txt')):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/perception', method='POST', body={
                        'action':'start', 'handle':123, 'process_id':456,
                        'consent':True, 'expected_document':invalid})
            audio_stop.assert_not_called()
            microphone_stop.assert_not_called()
            start.assert_not_called()
            self.request('/api/companion/perception', method='POST', body={
                'action':'start', 'handle':123, 'process_id':456,
                'consent':True, 'expected_document':expected})
            start.assert_called_once_with(handle=123, process_id=456,
                approved=True, expected_document=expected)
            audio_stop.assert_called_once()
            microphone_stop.assert_called_once()

    def test_visual_capture_requires_consent_and_binds_image_observation(self):
        with patch('ui.server.subprocess.run') as run, patch('ui.server.Path.is_file', return_value=True):
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/companion/capture', method='POST', body={'handle':123,'process_id':456})
            run.assert_not_called()
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({'source':'window-visual','target':'window:123:pid:456',
                'valid':True,'image':{'media_type':'image/jpeg','data_base64':'fixture'}})
            _, observed = self.request('/api/companion/capture', method='POST', body={
                'consent':True,'handle':123,'process_id':456})
            self.assertTrue(observed['valid'])
            self.assertIn('extensions.companion.windows_visual', run.call_args.args[0])

    def test_visual_capture_failure_discards_previous_observation(self):
        self.request('/api/companion/observe', method='POST', body={
            'source':'web','target':'old','valid':True,'text':'old context'})
        with patch('ui.server.subprocess.run') as run, patch('ui.server.Path.is_file', return_value=True):
            run.return_value.returncode = 1
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/companion/capture', method='POST', body={
                    'consent':True,'handle':123,'process_id':456})
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/companion/ask', method='POST', body={'question':'Explain'})
    def test_browser_video_failure_clears_old_context(self):
        self.request('/api/companion/observe', method='POST', body={
            'source': 'video-subtitle', 'target': 'old-video', 'valid': True, 'text': 'old lesson'})
        with patch('extensions.companion.browser_video.collect_browser_video', side_effect=RuntimeError('no video')):
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/companion/browser-video', method='POST', body={
                    'consent': True, 'site': 'lesson.test'})
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/companion/ask', method='POST', body={'question': 'Explain'})

    def test_browser_video_requires_consent_and_binds_invalid_cue(self):
        from extensions.companion import ObservationBundle
        with patch('extensions.companion.browser_video.collect_browser_video') as collect:
            for payload in ({}, {'site': 'lesson.test'}, {'consent': True}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/browser-video', method='POST', body=payload)
            collect.assert_not_called()
            collect.return_value = ObservationBundle.now(source='video-subtitle', target='browser:study:tab:7',
                valid=False, text='', media_time_seconds=12)
            _, observed = self.request('/api/companion/browser-video', method='POST', body={
                'consent': True, 'site': 'lesson.test'})
            self.assertFalse(observed['valid'])
            _, answer = self.request('/api/companion/ask', method='POST', body={'question': 'Explain'})
            self.assertEqual(answer['status'], 'insufficient_context')

    def test_browser_video_paused_state_fences_owned_audio(self):
        from extensions.companion import ObservationBundle
        bridge = self.server.sumika_bridge
        with patch('extensions.companion.browser_video.collect_browser_video') as collect, \
             patch.object(bridge, 'companion_media_state', wraps=bridge.companion_media_state) as media:
            collect.return_value = ObservationBundle.now(source='video-subtitle',
                target='browser:study:tab:7', valid=True, text='paused lesson',
                metadata={'paused':True, 'ended':False, 'seeking':False})
            self.request('/api/companion/browser-video', method='POST', body={
                'consent':True, 'site':'lesson.test'})
        media.assert_called_once_with({'target':'browser:study:tab:7','state':'paused'})

    def test_companion_collection_requires_consent_and_exact_window(self):
        with patch('ui.server.subprocess.run') as run:
            for payload in ({}, {'consent': True, 'handle': '123', 'process_id': 456},
                            {'consent': True, 'handle': 123, 'process_id': 456, 'kind': 'screen'}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/collect', method='POST', body=payload)
            run.assert_not_called()

    def test_pdf_collection_requires_explicit_file_page_and_clears_failed_context(self):
        pdf = self.settings_path.parent/'lesson.pdf'
        pdf.write_bytes(b'fixture placeholder')
        with patch('ui.server.subprocess.run') as run:
            for payload in ({'kind':'pdf','pdf_path':str(pdf),'page':1},
                            {'kind':'pdf','consent':True,'pdf_path':'lesson.pdf','page':1},
                            {'kind':'pdf','consent':True,'pdf_path':str(pdf),'page':True}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request('/api/companion/collect', method='POST', body=payload)
            run.assert_not_called()
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({'source':'pdf-page','target':'pdf:'+str(pdf),
                'valid':True,'text':'current page','metadata':{'page':2}})
            _, result = self.request('/api/companion/collect', method='POST', body={
                'kind':'pdf','consent':True,'pdf_path':str(pdf),'page':2})
            self.assertTrue(result['valid'])
            command = run.call_args.args[0]
            self.assertIn('--page', command)
            self.assertTrue(any('pdf_learning.py' in item for item in command))
            run.return_value.returncode = 1
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/companion/collect', method='POST', body={
                    'kind':'pdf','consent':True,'pdf_path':str(pdf),'page':3})
            self.assertIsNone(self.server.sumika_bridge._companion.latest)

    def test_companion_collection_uses_isolated_collector_and_selection(self):
        with patch('ui.server.subprocess.run') as run, patch('ui.server.Path.is_file', return_value=True):
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({'source': 'ebook-selection', 'target': 'window:123:pid:456',
                'valid': True, 'text': '选中内容', 'metadata': {'selected': True}})
            _, result = self.request('/api/companion/collect', method='POST', body={
                'consent': True, 'handle': 123, 'process_id': 456, 'kind': 'ebook', 'selected': True})
            command = run.call_args.args[0]
            self.assertIn('extensions.companion.windows_text', command)
            self.assertIn('--selected', command)
            self.assertEqual(result['target'], 'window:123:pid:456')

    def test_pdf_explicit_missing_runtime_clears_context_without_office_fallback(self):
        import os
        pdf = self.settings_path.parent/'lesson.pdf'
        pdf.write_bytes(b'fixture placeholder')
        self.request('/api/companion/observe', method='POST', body={
            'source':'pdf-page','target':'old','valid':True,'text':'old page'})
        with patch.dict(os.environ, {'SUMIKA_DESKTOP_PYTHON':str(pdf.parent/'missing.exe')}), \
                patch('ui.server.subprocess.run') as run:
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/companion/collect', method='POST', body={
                    'kind':'pdf','consent':True,'pdf_path':str(pdf),'page':1})
            run.assert_not_called()
        self.assertIsNone(self.server.sumika_bridge._companion.latest)

    def test_companion_observation_is_ephemeral_and_never_a_memory_source(self):
        settings = load_settings(self.settings_path)
        settings['enabled'] = True
        settings['memory'].update(auto_extract=True, model_proposals=True)
        save_settings(settings, self.settings_path)
        with patch('extensions.roles.chat.CloudProvider') as provider, \
                patch('extensions.roles.chat.propose_facts', side_effect=AssertionError('screen is not user fact')), \
                patch('extensions.memory.model_proposer.instruction', side_effect=AssertionError('no memory proposals')):
            provider.return_value.generate.return_value = {'text': '第三页在讲导数。', 'usage_status': 'unknown'}
            self.request('/api/companion/observe', method='POST', body={
                'source': 'ebook-page', 'target': 'reader', 'valid': True,
                'text': '我喜欢茶。', 'metadata': {'page': 3}})
            _, result = self.request('/api/companion/ask', method='POST', body={'question': '这段是什么？'})
            self.assertEqual(result['memory_proposals'], 0)
            self.assertEqual(result['auto_extracted'], [])
            prompt = provider.return_value.generate.call_args.kwargs['messages'][-1]['content']
            self.assertIn('"page": 3', prompt)
            self.assertIn('我喜欢茶', prompt)
        db = sqlite3.connect(self.settings_path.parent/'role-conversations.sqlite3')
        try:
            self.assertNotIn('我喜欢茶', json.dumps(list(db.iterdump()), ensure_ascii=False))
        finally:
            db.close()

    def test_video_subtitle_observation_keeps_time_and_source(self):
        _, observed = self.request('/api/companion/video', method='POST', body={
            'consent': True, 'target': 'player:lesson', 'subtitles': '导数表示变化率。',
            'media_time_seconds': 42.5, 'title': '微积分教程'})
        self.assertEqual(observed['source'], 'video-subtitle')
        self.assertEqual(observed['target'], 'player:lesson')
        _, answer = self.request('/api/companion/ask', method='POST', body={'question': '这句话的时间？'})
        self.assertEqual(answer['observation_source'], 'video-subtitle')

    def test_video_webvtt_observation_selects_current_cue(self):
        _, observed = self.request('/api/companion/video', method='POST', body={
            'consent': True, 'target': 'player:vtt', 'media_time_seconds': 11,
            'webvtt': 'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n旧字幕\n\n00:00:10.000 --> 00:00:12.000\n当前字幕'})
        self.assertEqual(observed['source'], 'video-subtitle')

    def test_video_seek_outside_subtitles_invalidates_old_context(self):
        vtt='WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nCurrent lesson'
        self.request('/api/companion/video',method='POST',body={
            'consent':True,'target':'player:vtt','media_time_seconds':2,'webvtt':vtt})
        _,observed=self.request('/api/companion/video',method='POST',body={
            'consent':True,'target':'player:vtt','media_time_seconds':10,'webvtt':vtt})
        self.assertFalse(observed['valid'])
        self.assertEqual(self.server.sumika_bridge._companion.latest.text,'')
        with patch.object(self.server.sumika_bridge._companion,'_role_chat') as reply:
            _,answer=self.request('/api/companion/ask',method='POST',body={'question':'Explain current frame'})
        self.assertEqual(answer['status'],'insufficient_context')
        reply.assert_not_called()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.settings_path = root / "settings.json"
        capability_path = root / "capabilities.db"
        self.schedule_directory = root / "schedules"
        connection = sqlite3.connect(capability_path)
        connection.execute("CREATE TABLE capabilities (id TEXT PRIMARY KEY, position INTEGER, enabled INTEGER, provider TEXT, options TEXT)")
        connection.execute("INSERT INTO capabilities VALUES ('memory',0,1,'embedded','{}')")
        connection.commit()
        connection.close()
        settings = example(_role_dir(root), root / "sumika.db")
        save_settings(settings, self.settings_path)
        self.server = serve(self.settings_path, port=0, capability_database=capability_path,
                            schedule_directory=self.schedule_directory)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def request(self, path, *, method="GET", body=None):
        headers = {"Content-Type": "application/json"}
        if method not in ('GET', 'HEAD'):
            _, session = self.request('/api/manage/session')
            headers['X-Sumika-CSRF'] = session['csrf']
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf8"),
            headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf8"))

    def test_state_settings_and_modules_are_real(self):
        status, state = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["modules"][0]["id"], "memory")
        _, catalogue = self.request("/api/modules")
        self.assertEqual(catalogue["modules"][0]["label"], "长期记忆")
        self.assertEqual(catalogue["modules"][0]["purpose"], "角色事实与关系的本地存储")
        self.assertEqual(catalogue["modules"][0]["id"], "memory")
        self.assertEqual(state["role"]["language_policy_source"], "card")
        _, settings = self.request("/api/settings/role-model")
        self.assertFalse(settings["enabled"])
        self.assertNotIn("key", json.dumps(settings["language"]))
        _, roles = self.request("/api/roles")
        ids = {role["id"] for role in roles["roles"]}
        self.assertIn("sampleA", ids)
        sample = next(role for role in roles["roles"] if role["id"] == "sampleA")
        self.assertEqual(sample["verified"], "ok")
        self.assertTrue(sample["has_model_3d"])
        self.assertNotIn("D:\\", json.dumps(roles, ensure_ascii=False))

    def test_all_old_write_routes_require_the_same_authorization(self):
        paths = ['/api/memory/reset', '/api/memory/forget', '/api/roles/remove',
                 '/api/roles/import', '/api/roles/select', '/api/roles/attach',
                 '/api/workbench/start', '/api/workbench/stop', '/api/workbench/session',
                 '/api/role/chat', '/api/schedule/toggle', '/api/capabilities/toggle',
                 '/api/companion/collect', '/api/companion/observe', '/api/companion/ask',
                 '/api/companion/revoke', '/api/companion/video', '/api/companion/browser-video', '/api/companion/capture', '/api/companion/perception', '/api/companion/ask-stream']
        for path in paths:
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{}',
                                             headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(req)
                self.assertEqual(caught.exception.code, 403)
        _, session = self.request('/api/manage/session')
        for headers in ({'Origin':'http://127.0.0.1:9999'}, {'Origin':'https://evil.test'},
                        {'Sec-Fetch-Site':'cross-site'}, {'Host':'attacker.test'}):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/settings/role-model',
                method='PUT', data=b'{}', headers={**headers,'X-Sumika-CSRF':session['csrf']})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 403)

    def test_foreign_loopback_cannot_read_session_token(self):
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/manage/session',
                                   headers={'Origin':'http://localhost:9999'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 403)
        self.assertIsNone(caught.exception.headers.get('Access-Control-Allow-Origin'))

    def test_native_origin_tokens_are_bound_to_live_owned_instance(self):
        bridge = self.server.sumika_bridge
        origin = 'http://127.0.0.1:5175'
        def request(route, token=None, method='GET'):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}{route}', method=method,
                headers={'Origin':origin, 'X-Sumika-CSRF':token or ''},
                data=b'{}' if method == 'POST' else None)
            return urllib.request.urlopen(req, timeout=5)
        with patch.object(bridge.workbench, 'browser_binding', return_value=(origin,'first')) as binding:
            with request('/api/manage/session') as response:
                token = json.load(response)['csrf']
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
            self.assertNotEqual(token, bridge.management.csrf)
            # The generic bridge token cannot authorize native-origin writes.
            with self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/workbench/stop', bridge.management.csrf, 'POST')
            self.assertEqual(caught.exception.code, 403)
            with request('/api/workbench/stop', token, 'POST') as response:
                self.assertEqual(response.status, 200)
            binding.return_value = (origin, 'second')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/workbench/stop', token, 'POST')
            self.assertEqual(caught.exception.code, 403)
            binding.return_value = None
            with self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/manage/session')
            self.assertEqual(caught.exception.code, 403)

    def test_closing_rejects_queued_writes_without_starting_or_saving(self):
        bridge = self.server.sumika_bridge
        before = self.settings_path.read_bytes()
        with patch.object(bridge.workbench, 'start') as start:
            bridge._closing = True
            for route, method in [('/api/workbench/start', 'POST'),
                                  ('/api/manage/task-draft', 'POST'),
                                  ('/api/role/chat', 'POST'),
                                  ('/api/settings/role-model', 'PUT')]:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request(route, method=method, body={})
                self.assertEqual(caught.exception.code, 503)
            start.assert_not_called()
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_voice_input_disabled_and_unapproved_do_not_spawn(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge.speech, 'spawn') as spawn:
            for body in ({'role_id':'ui-role'}, {'role_id':'ui-role','approved':True}):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.request('/api/voice/input/start', method='POST', body=body)
                self.assertEqual(denied.exception.code, 403)
            spawn.assert_not_called()

    def test_voice_output_disabled_and_unapproved_do_not_spawn(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge.playback, 'spawn') as spawn:
            for approved in (False, True):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.request('/api/voice/output/start', method='POST',
                                 body={'role_id':'ui-role','text':'hello','approved':approved})
                self.assertEqual(denied.exception.code, 403)
            spawn.assert_not_called()

    def test_output_only_voice_needs_no_microphone_but_recording_stays_denied(self):
        import sys
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        settings = load_settings(self.settings_path)
        settings['voice'].update(enabled=True, input_device=None)
        save_settings(settings, self.settings_path)
        store = CapabilityStore(bridge.capability_database)
        try:
            store.configure('voice', 'windows-sapi')
            store.configure('microphone', 'sounddevice', enabled=False)
        finally:
            store.close()
        with patch('extensions.desktop.audio_devices.env_python', return_value=sys.executable):
            configured = bridge.playback_configuration('ui-role')
        self.assertEqual(configured['voice_name'], settings['voice']['tts_voice'])
        self.assertNotIn('device', configured)
        with patch.object(bridge.speech, 'spawn') as spawn:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.request('/api/voice/input/start', method='POST',
                             body={'role_id':'ui-role', 'approved':True})
            self.assertEqual(denied.exception.code,403)
            spawn.assert_not_called()

    def test_shutdown_attempts_playback_stop_even_when_input_stop_fails(self):
        from ui.workbench import WorkbenchError
        bridge = self.server.sumika_bridge
        with patch.object(bridge.speech, 'close', side_effect=RuntimeError('unknown')), \
                patch.object(bridge.playback, 'close') as playback, \
                patch.object(bridge.workbench, 'stop') as workbench:
            with self.assertRaises(WorkbenchError):
                bridge.shutdown()
            playback.assert_called_once()
            workbench.assert_not_called()
        self.assertTrue(bridge._shutdown_requested.is_set())
        self.assertFalse(bridge._closing)

    def test_both_module_write_routes_keep_disable_and_report_stop_unknown(self):
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        for route in ('/api/capabilities/toggle', '/api/manage/modules/toggle'):
            store=CapabilityStore(bridge.capability_database)
            try: store.configure('voice','windows-sapi',enabled=True)
            finally: store.close()
            body={'id':'voice','enabled':False}
            if '/manage/' in route:
                body['expected_revision']=bridge.management.modules()['revision']
            with patch.object(bridge.speech,'cancel_active',side_effect=RuntimeError('unknown')), \
                    patch.object(bridge.playback,'cancel_active') as playback:
                with self.assertRaises(urllib.error.HTTPError) as failed:
                    self.request(route, method='POST', body=body)
                self.assertEqual(failed.exception.code,502)
                self.assertEqual(json.load(failed.exception)['status'],'unknown')
                playback.assert_called_once()
            store=CapabilityStore(bridge.capability_database)
            try:self.assertFalse(next(r for r in store.list() if r['id']=='voice')['enabled'])
            finally:store.close()

    def test_failed_shutdown_keeps_service_open_and_reports_unknown(self):
        from ui.workbench import WorkbenchError
        bridge = self.server.sumika_bridge
        with patch.object(bridge.workbench, 'stop', side_effect=WorkbenchError('still running')):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/lifecycle/shutdown', method='POST', body={})
        self.assertEqual(caught.exception.code, 502)
        self.assertEqual(json.load(caught.exception)['status'], 'unknown')
        self.assertFalse(bridge._closing)
        self.assertEqual(self.request('/api/state')[0], 200)
        self.assertTrue(bridge._shutdown_requested.is_set())
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/workbench/start', method='POST', body={})
        self.assertEqual(denied.exception.code, 503)
        with patch.object(bridge.workbench, 'stop') as stop:
            self.assertEqual(self.request('/api/lifecycle/shutdown', method='POST', body={})[0], 200)
            stop.assert_called_once()

    def test_http_shutdown_fences_new_writes_while_chat_drains(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        bridge = self.server.sumika_bridge
        entered, release = threading.Event(), threading.Event()
        def reply(*args, **kwargs):
            entered.set()
            if not release.wait(8):
                raise RuntimeError('chat release timed out')
            return {'text': 'saved before exit'}
        chat = Mock(histories={}, history_limit=12)
        chat.reply.side_effect = reply
        with patch.object(bridge, '_role_chat', return_value=chat), \
                patch.object(bridge.workbench, 'stop') as stop, ThreadPoolExecutor(3) as pool:
            response = pool.submit(bridge.chat, 'admitted')
            try:
                self.assertTrue(entered.wait(5))
                shutdown = pool.submit(self.request, '/api/lifecycle/shutdown', method='POST', body={})
                self.assertTrue(bridge._shutdown_requested.wait(5))
                self.assertFalse(shutdown.done())
                stop.assert_not_called()
                for route, method in [('/api/role/chat','POST'), ('/api/settings/role-model','PUT')]:
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        self.request(route, method=method, body={})
                    self.assertEqual(denied.exception.code, 503)
            finally:
                release.set()
            response.result(timeout=5)
            self.assertEqual(shutdown.result(timeout=5)[0], 200)
            stop.assert_called_once()
        self.assertEqual(bridge.transcript('ui-role-chat')[-1]['text'], 'saved before exit')
        self.assertEqual(chat.reply.call_count, 1)

    def test_server_close_failure_retains_data_lease(self):
        from ui.data_lease import DataLease
        from ui.workbench import WorkbenchError
        bridge = self.server.sumika_bridge
        with patch.object(bridge.workbench, 'stop', side_effect=WorkbenchError('unknown stop')):
            with self.assertRaises(WorkbenchError):
                self.server.server_close()
        with self.assertRaises(OSError):
            DataLease(self.settings_path.parent).acquire()
        self.assertTrue(bridge._shutdown_requested.is_set())

    def test_shutdown_waits_for_admitted_chat_to_persist(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        bridge = self.server.sumika_bridge
        entered, release, stopping = threading.Event(), threading.Event(), threading.Event()
        def reply(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release chat')
            return {'text': '已落盘的回复'}
        chat = Mock(histories={}, history_limit=12)
        chat.reply.side_effect = reply
        def stop():
            stopping.set()
            bridge.shutdown()
        with patch.object(bridge, '_role_chat', return_value=chat), \
                patch.object(bridge.workbench, 'stop'), ThreadPoolExecutor(2) as pool:
            response = pool.submit(bridge.chat, '等待保存')
            try:
                self.assertTrue(entered.wait(5))
                shutdown = pool.submit(stop)
                self.assertTrue(stopping.wait(5))
                self.assertFalse(shutdown.done())
            finally:
                release.set()
            response.result(timeout=5)
            shutdown.result(timeout=5)
        self.assertTrue(bridge._closing)
        self.assertEqual(bridge.transcript('ui-role-chat')[-1]['text'], '已落盘的回复')

    def test_first_launch_initializes_disabled_settings_without_role_setup(self):
        from ui.server import Bridge
        path = Path(self._tmp.name) / 'new-user' / 'settings.json'
        with patch('extensions.roles.chat.RoleChat._provider') as provider:
            bridge = Bridge(path)
            self.assertFalse(bridge.settings()['enabled'])
            self.assertEqual(bridge.chat('你好')['disabled'], True)
            provider.assert_not_called()
        before=path.read_bytes()
        Bridge(path)
        self.assertEqual(path.read_bytes(), before)

    def test_clear_room_requires_role_and_only_clears_current_conversation(self):
        bridge=self.server.sumika_bridge
        scope=bridge._chat_scope(load_settings(self.settings_path))
        turn=bridge.conversations.begin(scope,'room-ui-role','fixture')
        bridge.conversations.complete(turn,{'text':'fixture reply'})
        _, page=self.request('/api/role/chat/history?session=room-ui-role&role_id=ui-role&limit=3')
        self.assertTrue(page['supports_clear'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/role/chat/clear',method='POST',body={'role_id':'other','session':'room-ui-role'})
        self.assertEqual(len(bridge.conversations.messages(scope,'room-ui-role')),2)
        _,result=self.request('/api/role/chat/clear',method='POST',body={'role_id':'ui-role','session':'room-ui-role'})
        self.assertTrue(result['cleared'])
        self.assertEqual(bridge.conversations.context(scope,'room-ui-role'),[])

    def test_history_rejects_stale_role_even_without_pagination(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/role/chat/history?session=room-ui-role&role_id=stale-role')
        self.assertEqual(caught.exception.code, 400)

    def test_role_asset_serving_and_capability_toggle(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/roles/sampleA/asset/model_3d")
        with urllib.request.urlopen(request, timeout=30) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "model/gltf-binary")
            self.assertGreater(len(response.read(64)), 0)
        for target in ("/api/roles/nope/asset/model_3d", "/api/roles/sampleA/asset/voice"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{target}", timeout=10)
            self.assertEqual(caught.exception.code, 404)
        status, toggled = self.request("/api/capabilities/toggle", method="POST",
                                       body={"id": "memory", "enabled": False})
        self.assertEqual(status, 200)
        self.assertEqual(toggled, {"id": "memory", "enabled": False, "provider": "embedded"})
        _, modules = self.request("/api/modules")
        self.assertFalse(modules["modules"][0]["enabled"])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/capabilities/toggle", method="POST", body={"id": "missing", "enabled": True})
        self.assertEqual(caught.exception.code, 400)

    def test_role_selection_switches_the_active_role(self):
        _, roles = self.request("/api/roles")
        self.assertIn("active", roles)
        target = next(role for role in roles["roles"] if role["id"] == "sampleA")
        self.assertTrue(target["assets"], "sampleA carries a 3D model")
        status, selected = self.request("/api/roles/select", method="POST", body={"id": "sampleA"})
        self.assertEqual(status, 200)
        self.assertEqual(selected["selected"], "sampleA")
        settings = load_settings(self.settings_path)
        self.assertTrue(settings["role"]["role_dir"].endswith("sampleA"))
        _, after = self.request("/api/roles")
        self.assertEqual(after["active"]["id"], "sampleA")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/roles/select", method="POST", body={"id": "missing-role"})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(load_settings(self.settings_path)["role"]["role_dir"],
                         settings["role"]["role_dir"], "a failed switch must not change the active role")

    def test_settings_save_roundtrip_and_secret_rejection(self):
        _, settings = self.request("/api/settings/role-model")
        payload = {k: v for k, v in settings.items() if k not in ("path", "configured", "language_policy_preview")}
        payload["enabled"] = True
        payload["language"] = {**payload["language"], "policy": "用户策略：只用简体中文。"}
        status, saved = self.request("/api/settings/role-model", method="PUT", body=payload)
        self.assertEqual(status, 200)
        self.assertEqual(saved["language_policy_preview"]["source"], "user")
        self.assertTrue(load_settings(self.settings_path)["enabled"])
        before = self.settings_path.read_text(encoding="utf8")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/settings/role-model", method="PUT",
                         body={**payload, "model": "sk-abcdef1234567890"})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.settings_path.read_text(encoding="utf8"), before)
        self.request("/api/settings/role-model", method="PUT",
                     body={**payload, "language": {**payload["language"], "policy": None}})
        _, cleared = self.request("/api/settings/role-model")
        self.assertEqual(cleared["language_policy_preview"]["source"], "card")

    def test_disabled_chat_makes_no_request_and_unknown_route_is_json(self):
        with patch("extensions.roles.chat.CloudProvider") as provider:
            status, result = self.request("/api/role/chat", method="POST", body={"message": "你好"})
            provider.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(result['disabled'])
        self.assertFalse(result['model_started'])
        self.assertTrue(result['source_message_id'].endswith(':user'))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/not-a-route")
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(json.loads(caught.exception.read().decode("utf8")), {"error": "unknown endpoint"})

    def test_provider_failure_returns_unknown_without_fallback(self):
        _, settings = self.request("/api/settings/role-model")
        payload = {k: v for k, v in settings.items() if k not in ("path", "configured", "language_policy_preview")}
        payload["enabled"] = True
        self.request("/api/settings/role-model", method="PUT", body=payload)
        from extensions.models.cloud import CloudError
        with patch("extensions.roles.chat.CloudProvider") as provider, \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-test-placeholder"}):
            provider.return_value.generate.side_effect = CloudError("auth", "provider returned HTTP 401")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("/api/role/chat", method="POST", body={"message": "你好"})
        self.assertEqual(caught.exception.code, 502)
        body = json.loads(caught.exception.read().decode("utf8"))
        self.assertEqual(body["status"], "unknown")
        self.assertFalse(body["fallback_used"])

    def test_static_serving_blocks_path_traversal(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/../AGENTS.md")
        self.assertIn(caught.exception.code, (403, 404))

    def test_schedule_endpoints_over_http(self):
        from extensions.desktop.scheduler import Schedule
        from ui.schedule import ScheduleController
        controller = ScheduleController(self.schedule_directory)
        controller.store.upsert(Schedule(id="s1", kind="daily", expression="08:00",
                                        action="提醒喝水", mode="reminder",
                                        timezone_name="Asia/Shanghai"))
        status, state = self.request("/api/schedule")
        self.assertEqual(status, 200)
        self.assertEqual([i["id"] for i in state["definitions"]], ["s1"])
        self.assertEqual(state["status"]["enabled"], True)
        self.request("/api/schedule/toggle", method="POST", body={"id": "s1", "enabled": False})
        _, after = self.request("/api/schedule")
        self.assertFalse(after["definitions"][0]["enabled"])
        self.request("/api/schedule/remove", method="POST", body={"id": "s1"})
        _, empty = self.request("/api/schedule")
        self.assertEqual(empty["definitions"], [])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/schedule/toggle", method="POST", body={"id": "s1", "enabled": True})
        self.assertEqual(caught.exception.code, 400)

    def test_memory_search_relations_forget_and_reset(self):
        from extensions.roles.chat import open_session
        settings = load_settings(self.settings_path)
        session = open_session(settings)
        try:
            session.request("remember", {"text": "小林喜欢晚上九点看动画", "fact_key": "user.anime"})
            session.request("relate", {"subject": "小林", "predicate": "关系", "object": "朋友"})
        finally:
            session.close()
        status, value = self.request("/api/memory?q=%E5%8A%A8%E7%94%BB")
        self.assertEqual(status, 200)
        self.assertEqual(value["provider"], "embedded")
        self.assertEqual(value["sources"], [{"source": "user", "count": 1}])
        self.assertTrue(value["results"])
        found = value["results"][0]
        self.assertIn("动画", found["text"])
        self.assertEqual([(r["subject"], r["predicate"], r["object"]) for r in value["relations"]],
                         [("小林", "关系", "朋友")])
        _, empty = self.request("/api/memory")
        self.assertEqual(empty["results"], [])
        self.request("/api/memory/forget", method="POST", body={"id": found["id"]})
        _, after = self.request("/api/memory?q=%E5%8A%A8%E7%94%BB")
        self.assertEqual(after["results"], [])
        self.request("/api/memory/reset", method="POST", body={})
        _, reset = self.request("/api/memory")
        self.assertEqual(reset["relations"], [])
        # Reset restores the role card itself as a memory, so provenance is kept.
        self.assertEqual(reset["sources"], [{"source": "role_card", "count": 1}])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/memory/forget", method="POST", body={"id": 0})
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/memory?limit=999")
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
