"""Product wiring regressions: real stores/coordinator, fake OS and providers."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from extensions.behavior.library import BehaviorLibrary
from extensions.behavior.permission import BehaviorPermissions
from extensions.behavior.profiles import CompanionProfileStore
from extensions.behavior.routing import RoutingEngine
from extensions.behavior.runtime import BehaviorRuntime
from extensions.companion.contracts import ObservationBundle
from extensions.companion.session_coordinator import StudySessionCoordinator
from extensions.models.cancellation import CancellationToken


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1000.
        self.wall = 1792137600.
        self.scope = {'user': 'u', 'session': 'real-session-one'}
        self.library = BehaviorLibrary(self.root/'behavior.sqlite3', clock=lambda: self.wall)
        self.permissions = BehaviorPermissions(self.root)
        self.profiles = CompanionProfileStore(self.root)
        self.profiles.load()
        self.events, self.captures, self.stops = [], [], []
        self.live = {'handle': 1, 'process_id': 2, 'process_creation': '3', 'image': 'reader.exe'}
        self.coordinator = StudySessionCoordinator(chat=lambda *a, **k: {'text': 'reply'},
            current=lambda: None, on_event=lambda name, detail: self.events.append((name, detail)),
            scheduler_thread=False, monotonic=lambda: self.now)
        self.addCleanup(self.coordinator.close)
        self.router = RoutingEngine(store=self.profiles, classifier=lambda request: None,
                                    clock=lambda: self.now)
        self.runtime = BehaviorRuntime(library=self.library, permissions=self.permissions,
            profiles=self.profiles, router=self.router, coordinator=self.coordinator,
            scope=lambda: self.scope, foreground=lambda: self.live,
            capture_start=self.captures.append, capture_stop=lambda: self.stops.append(True),
            clock=lambda: self.now, wall_clock=lambda: self.wall)
        self.addCleanup(self.runtime.close)
        self.runtime.sync_profile()

    def grant(self, **changes):
        return self.permissions.save(changes, revision=self.permissions.load()['revision'])

    def event(self, identity='e1', kind='revisit'):
        return {'event_id': identity, 'kind': kind, 'source': 'reading-tracker'}

    def test_new_default_does_not_create_capture_or_input(self):
        self.runtime.start(startup=True)
        self.runtime.tick()
        self.assertIsNone(self.runtime._thread)
        self.assertFalse(self.runtime.status()['armed'])
        self.assertEqual(self.captures, [])

    def activity_tick(self, delta=1):
        self.now += delta
        self.wall += delta
        self.runtime.tick()

    def test_daily_activity_switches_gaps_pause_and_no_double_count(self):
        self.grant(recording=True)
        self.runtime._armed = True
        self.runtime.tick()
        for _ in range(10): self.activity_tick()
        self.runtime.tick()  # Duplicate tick cannot add time.
        self.live = {**self.live, 'handle': 2, 'image': 'editor.exe'}
        self.activity_tick()
        for _ in range(5): self.activity_tick()
        self.live = {**self.live, 'handle': 1, 'image': 'reader.exe'}
        self.activity_tick()
        for _ in range(3): self.activity_tick()
        self.activity_tick(20)  # Unknown gap is never added.
        summary = self.library.daily_summary(scope=self.scope)
        self.assertEqual(summary['effective_seconds'], 18)
        self.assertEqual(summary['switch_count'], 2)
        self.activity_tick()
        self.permissions.pause(revision=self.permissions.load()['revision'])
        self.runtime.permissions_changed()
        self.runtime.close()
        self.assertEqual(self.library.daily_summary(scope=self.scope)['effective_seconds'], 18)

    def test_activity_midnight_and_hour_split_and_scope_does_not_leak(self):
        local = datetime.fromtimestamp(self.wall).astimezone()
        self.wall = local.replace(hour=23, minute=59, second=58, microsecond=0).timestamp()
        self.grant(recording=True)
        self.runtime._armed = True
        self.runtime.tick()
        for _ in range(4): self.activity_tick()
        self.runtime._flush_activity()
        buckets = self.library.daily_summary(scope=self.scope)['buckets']
        self.assertEqual(sorted(r['effective_seconds'] for r in buckets), [2, 2])
        self.assertEqual(len({r['date'] for r in buckets}), 2)
        self.activity_tick()
        self.scope = {'user': 'another-user', 'session': 'new'}
        self.activity_tick()
        self.runtime._flush_activity()
        self.assertEqual(self.library.daily_summary(scope=self.scope)['effective_seconds'], 0)

    def test_activity_excluded_app_and_wall_clock_jump_stop_accumulation(self):
        self.grant(recording=True)
        self.runtime._armed = True
        self.runtime.tick()
        self.activity_tick()
        self.wall -= 100
        self.now += 1
        self.runtime.tick()
        self.live = {**self.live, 'image': 'sumika.exe'}
        self.activity_tick()
        self.assertEqual(self.library.daily_summary(scope=self.scope)['effective_seconds'], 1)

    def test_activity_periodic_seals_do_not_count_as_switches(self):
        self.grant(recording=True)
        self.runtime._armed = True
        self.runtime.tick()
        for _ in range(65): self.activity_tick()
        self.runtime._flush_activity()
        summary = self.library.daily_summary(scope=self.scope)
        self.assertEqual(summary['effective_seconds'], 65)
        self.assertEqual(summary['switch_count'], 0)
        self.assertTrue(all(e['features']['effective_seconds'] <= 60
            for e in self.library.list_layer('events', scope=self.scope)['records']))

    def test_recording_without_startup_resume_never_restores(self):
        self.grant(recording=True)
        self.runtime.start(startup=True)
        self.assertFalse(self.runtime.status()['armed'])

    def test_foreground_follows_after_stability_exclusions_stop_immediately(self):
        self.grant(recording=True, startup_resume=True)
        # Drive exactly the same tick implementation without launching a thread.
        self.runtime._armed = True
        self.runtime.tick()
        self.now += 1.99
        self.runtime.tick()
        self.assertEqual(self.captures, [])
        self.now += .02
        self.runtime.tick()
        self.assertEqual(len(self.captures), 1)
        self.live = {**self.live, 'handle': 4, 'image': 'sumika.exe'}
        self.runtime.tick()
        self.assertEqual(len(self.stops), 1)
        self.assertFalse(self.runtime.status()['following'])
        self.live = None
        self.runtime.tick()
        self.assertEqual(self.router.view()['reason'], 'suspended')

    def test_recording_questions_and_memory_have_independent_effects(self):
        self.grant(recording=True, questions=False, use_memory=False)
        self.runtime.observe_event(self.event())
        self.assertEqual(len(self.library.export(scope=self.scope)['events']), 1)
        self.assertEqual(self.library.export(scope=self.scope)['prompts'], [])
        self.grant(recording=False, use_memory=True, questions=True)
        self.assertTrue(self.permissions.effective()['can_use_memory'])
        self.runtime.observe_event(self.event('e2'))
        self.assertEqual(len(self.library.export(scope=self.scope)['events']), 1)

    def test_prompt_persisted_before_display_and_quota_survives_restart(self):
        self.grant(recording=True, questions=True)
        self.runtime.observe_event(self.event())
        prompts = [detail for name, detail in self.events if name == 'behavior_prompt']
        self.assertEqual(len(prompts), 1)
        prompt_id = prompts[0]['prompt_id']
        self.assertEqual(self.library.export(scope=self.scope)['prompts'][0]['prompt_id'], prompt_id)
        self.assertEqual(self.library.prompt_quota(scope=self.scope)['count'], 1)
        self.library.feedback({'feedback_id': 'f1', 'user_event_id': 'user1',
            'prompt_id': prompt_id, 'verdict': 'confirm', 'corrected': '找公式'}, scope=self.scope)
        restarted = BehaviorLibrary(self.root/'behavior.sqlite3', clock=lambda: self.wall)
        self.assertEqual(restarted.habit_summaries('revisit', scope={'user': 'u', 'session': 'new'})[0]['label'], '找公式')
        self.now += 121
        self.runtime.observe_event(self.event('e2'))
        self.assertEqual(len([name for name, _ in self.events if name == 'behavior_prompt']), 1)
        self.assertEqual(restarted.prompt_quota(scope=self.scope)['count'], 1)

    def test_quiet_profile_stops_actual_coordinator_questions(self):
        state = self.profiles.load()
        quiet = state['profiles'][2]
        self.profiles.select('manual', quiet['id'], expected_revision=state['revision'])
        self.runtime.config_changed()
        self.grant(recording=True, questions=True)
        self.runtime.observe_event(self.event())
        self.assertFalse(self.coordinator.status()['proactive_enabled'])
        self.assertEqual(self.library.export(scope=self.scope)['prompts'], [])

    def test_expired_candidate_is_not_replayed_after_user_busy(self):
        self.grant(recording=True, questions=True)
        with self.coordinator.text_question_span():
            self.runtime.observe_event(self.event())
        self.now += 121
        self.runtime._maybe_prompt()
        self.assertEqual(self.library.export(scope=self.scope)['prompts'], [])

    def test_pause_discards_new_observations_and_cancels_owner(self):
        self.grant(recording=True, questions=True)
        token = CancellationToken()
        self.assertTrue(self.coordinator.reserve_background(token))
        self.permissions.pause(revision=self.permissions.load()['revision'])
        self.runtime.permissions_changed()
        self.runtime.observe_event(self.event())
        self.assertEqual(self.library.export(scope=self.scope)['events'], [])
        with self.assertRaises(RuntimeError): token.check()
        # Cancellation cannot free a provider's physical slot prematurely.
        self.assertFalse(self.coordinator.reserve_background(CancellationToken()))
        self.coordinator.release_background(token)

    def input_frame(self, sequence, *, epoch=1):
        from extensions.behavior.input_features import FrameAggregator
        aggregator = FrameAggregator(identity={'user_scope': self.scope['user'], 'worker_epoch': epoch,
            'foreground_epoch': 1, 'focus_epoch': 1, 'window_instance': 9},
            observed_from=str(self.now), sequence=sequence)
        aggregator.key(0x41, self.now + .1)
        aggregator.click('left', .2, .3)
        result = aggregator.seal(str(self.now + 1))
        result['received_at'] = datetime.fromtimestamp(self.wall + 1, timezone.utc).isoformat()
        return result

    def test_input_episodes_promote_real_sources_and_confirmation_activates_pattern(self):
        self.grant(recording=True, questions=True)
        for index in range(3):
            if index == 2:
                self.scope['session'] = 'real-session-two'
            frame = self.input_frame(index)
            self.library.record_frames([frame], scope=self.scope)
            self.runtime.observe_frames([frame])
            # Replaying a committed callback never doubles duration/support.
            self.runtime.observe_frames([frame])
            self.now += 62
            self.wall += 62
            self.runtime.tick()
        exported = self.library.export(scope=self.scope)
        self.assertEqual(len(exported['episodes']), 3)
        self.assertEqual([item['effective_seconds'] for item in exported['episodes']], [1., 1., 1.])
        self.assertTrue(all(json.loads(item['frame_refs']) for item in exported['episodes']))
        self.assertEqual(len(exported['patterns']), 1)
        self.assertEqual(len(json.loads(exported['patterns'][0]['supports'])), 3)
        self.assertEqual(self.library.confirmed_patterns(scope=self.scope), [])
        prompts = [detail for name, detail in self.events if name == 'behavior_prompt']
        self.assertEqual(len(prompts), 1)
        self.library.feedback({'feedback_id': 'source-feedback', 'user_event_id': 'real-reply',
            'prompt_id': prompts[0]['prompt_id'], 'verdict': 'confirm', 'corrected': '整理例题'}, scope=self.scope)
        self.assertEqual(self.library.confirmed_patterns(scope=self.scope), ['typing|left_click'])

    def test_input_gap_closes_episode_and_revocation_drops_unfinished_episode(self):
        self.grant(recording=True)
        first = self.input_frame(0)
        self.library.record_frames([first], scope=self.scope)
        self.runtime.observe_frames([first])
        self.now += 10
        self.wall += 10
        second = self.input_frame(1)
        self.library.record_frames([second], scope=self.scope)
        self.runtime.observe_frames([second])
        self.assertEqual(len(self.library.export(scope=self.scope)['episodes']), 1)
        self.permissions.revoke(revision=self.permissions.load()['revision'])
        self.runtime.permissions_changed()
        self.assertEqual(len(self.library.export(scope=self.scope)['episodes']), 1)

    def test_failed_input_isolated_without_automatic_restart(self):
        self.grant(recording=True)
        process = unittest.mock.Mock()
        process.status.return_value = {'status': 'failed', 'error': 'sequence_gap'}
        self.runtime._armed = True
        self.runtime._input = process
        self.runtime._input_factory = unittest.mock.Mock()
        self.runtime.tick()
        self.runtime.tick()
        process.stop.assert_called_once()
        self.runtime._input_factory.assert_not_called()
        self.assertEqual(self.runtime.status()['error'], 'sequence_gap')

    def test_progress_uses_reliable_pdf_identity_and_fresh_heartbeats(self):
        self.grant(recording=True)
        file = self.root/'material.pdf'
        file.write_bytes(b'%PDF-fixture')
        def observe(page, stamp=None, identity='file-url'):
            return ObservationBundle(datetime.fromtimestamp(self.wall if stamp is None else stamp, timezone.utc),
                'window-visual', 'reader', True, text='正文不允许落盘',
                metadata={'reader_context': {'document_identity': identity,
                    'document_path': str(file), 'page': page}})
        first = observe(1)
        self.runtime.observation(first)
        self.now += 1
        self.wall += 1
        self.runtime.observation(first)
        self.runtime.observation(observe(2))
        records = self.library.export(scope=self.scope)['progress']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['effective_seconds'], 1.)
        self.assertEqual(json.loads(records[0]['position']), 2)
        self.now += 20
        self.wall += 20
        self.runtime.observation(observe(3))
        self.runtime.observation(observe(99, stamp=self.wall-10))
        records = self.library.export(scope=self.scope)['progress']
        self.assertEqual(records[0]['effective_seconds'], 1.)
        self.assertEqual(json.loads(records[0]['position']), 3)
        self.assertNotIn('正文不允许落盘', json.dumps(records, ensure_ascii=False))
        self.assertNotIn(str(file), json.dumps(records))

    def test_unknown_material_never_guesses_cross_day_progress(self):
        self.grant(recording=True)
        self.runtime.observation(ObservationBundle.now(source='window-visual', target='reader', valid=True,
            metadata={'page': 12, 'reader_context': {'document': 'same-name.pdf', 'page': 12}}))
        self.assertEqual(self.library.export(scope=self.scope)['progress'], [])

    def test_subtitle_motion_does_not_reclassify_same_video(self):
        state = self.profiles.load()
        self.profiles.select('auto', expected_revision=state['revision'])
        calls = []
        self.router._classifier = lambda request: calls.append(request) or {'scores': {
            p['id']: .1 for p in self.profiles.load()['profiles'] if p['enabled_for_auto']}}
        for advance in (0, 2, 35, 70):
            self.now = 1000 + advance
            self.runtime.observation(ObservationBundle.now(source='video-subtitle', target='video', valid=True,
                text=f'字幕正在改变 {advance}', metadata={'media_identity': {'url': 'https://www.bilibili.com/video/BVtest', 'part': 1}}))
        self.assertEqual(len(calls), 1)


class BridgeWiringTests(unittest.TestCase):
    def setUp(self):
        from extensions.models.settings import example, save
        from ui.server import Bridge, BUILTIN_ROLES
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = self.root/'settings.json'
        save(example(BUILTIN_ROLES/'sampleA', self.root/'main.sqlite3'), self.settings)
        self.bridge = Bridge(self.settings, capability_database=self.root/'capabilities.db',
                             schedule_directory=self.root/'schedules')
        self.addCleanup(self.bridge.shutdown)
        self.bridge._coordinator._scheduler_thread = False

    def test_superseded_collection_clear_does_not_interrupt_new_session(self):
        bridge = self.bridge
        old_token = bridge._companion.collection_token()
        bridge.companion_paste_context({'text': '新的会话材料'})
        self.assertNotEqual(old_token, bridge._companion.collection_token())
        current = bridge._companion.latest
        target = bridge._coordinator._scheduler_target
        with patch.object(bridge._microphone, 'stop') as mic_stop, \
             patch.object(bridge._coordinator, 'cancel_voice_requests') as voice_cancel, \
             patch.object(bridge, '_stop_worker_playback') as playback_stop, \
             patch.object(bridge._coordinator, 'context_cleared') as clear:
            result = bridge._companion_clear(collection_token=old_token)
            self.assertEqual(result['status'], 'rejected')
            mic_stop.assert_not_called()
            voice_cancel.assert_not_called()
            playback_stop.assert_not_called()
            clear.assert_not_called()
        self.assertIs(bridge._companion.latest, current)
        self.assertEqual(bridge._coordinator._scheduler_target, target)
        self.assertTrue(bridge._paste_status()['active'])

    def test_clear_rechecks_token_before_voice_side_effects(self):
        bridge = self.bridge
        old_token = bridge._companion.collection_token()
        with patch.object(bridge._microphone, 'stop',
                          side_effect=lambda: bridge._companion.revoke()), \
             patch.object(bridge._coordinator, 'cancel_voice_requests') as voice_cancel, \
             patch.object(bridge, '_stop_worker_playback') as playback_stop, \
             patch.object(bridge._coordinator, 'context_cleared') as clear:
            result = bridge._companion_clear(collection_token=old_token)
            self.assertEqual(result['status'], 'rejected')
            voice_cancel.assert_not_called()
            playback_stop.assert_not_called()
            clear.assert_not_called()

    def test_paste_uses_real_owner_and_survives_same_target_capture_refresh(self):
        bridge = self.bridge
        calls = []
        bridge._coordinator.service._role_chat = lambda message, **kwargs: calls.append(message) or {'text': '解释'}
        result = bridge.companion_paste_context({'text': '这是一段用户粘贴的公式说明'})
        self.assertTrue(bridge._paste_status()['active'])
        self.assertEqual(bridge._coordinator._scheduler_target, result['target'])
        bridge.companion_observe({'source': 'window-visual', 'target': result['target'],
                                  'valid': True, 'text': '阅读器导航'})
        self.assertEqual(bridge._companion.latest.source, 'user-paste')
        reply = bridge.companion_ask('请解释', expected_target=result['target'])
        self.assertEqual(reply['text'], '解释')
        self.assertIn('用户粘贴的公式说明', calls[-1])
        bridge.companion_revoke()
        self.assertFalse(bridge._paste_status()['active'])
        with self.assertRaises(ValueError):
            bridge.companion_ask('旧问题', expected_target=result['target'])

    def test_complete_learning_lifecycle_controls_real_model_reference(self):
        bridge = self.bridge
        permission = bridge._behavior_permissions
        permission.save({'recording': True, 'questions': True, 'use_memory': True},
                        revision=permission.load()['revision'])
        bridge._record_behavior_event({'event_id': 'e', 'kind': 'revisit', 'source': 'test'})
        prompt = next(e for e in bridge._voice_events if e['event'] == 'behavior_prompt')
        result = bridge.behavior_manage({'action': 'prompt_feedback', 'prompt_id': prompt['prompt_id'],
                                        'verdict': 'confirm', 'corrected': '找公式'})
        self.assertIn('找公式', bridge._behavior_reference())
        state = bridge.behavior_manage({'action': 'status'})
        bridge.behavior_manage({'action': 'correct', 'feedback_id': result['feedback_id'],
                                'corrected': '比较定义', 'revision': state['revision']})
        # A correction invalidates the old current-scene reference. A fresh
        # matching observation may recall the corrected historical evidence.
        self.assertNotIn('找公式', bridge._behavior_reference() or '')
        bridge._record_behavior_event({'event_id': 'e-new', 'kind': 'revisit', 'source': 'test'})
        self.assertIn('比较定义', bridge._behavior_reference())
        self.assertNotIn('找公式', bridge._behavior_reference())
        state = bridge.behavior_manage({'action': 'status'})
        bridge.behavior_manage({'action': 'delete', 'all_records': True,
                                'confirmed': True, 'revision': state['revision']})
        self.assertIsNone(bridge._behavior_reference())
        exported = bridge.behavior_manage({'action': 'export'})
        self.assertTrue(all(not exported[t] for t in ('events', 'frames', 'episodes', 'prompts', 'feedback', 'patterns', 'progress')))

    def test_mode_selection_changes_actual_coordinator_without_ui_guess(self):
        bridge = self.bridge
        state = bridge._profile_store.load()
        bridge.companion_profiles_manage({'action': 'select', 'selection_policy': 'manual',
            'profile_id': state['profiles'][2]['id'], 'expected_revision': state['revision']})
        self.assertFalse(bridge._coordinator.status()['proactive_enabled'])
        view = bridge.companion_profiles_manage({'action': 'runtime'})
        self.assertEqual(view['effective_profile_id'], state['profiles'][2]['id'])

    def test_auxiliary_disabled_never_starts_network_or_consumes_budget(self):
        from extensions.behavior.routing import ClassificationDeferred
        with patch('extensions.models.auxiliary._generate') as generate:
            with self.assertRaises(ClassificationDeferred):
                self.bridge._classify_scene({'cancellation_token': CancellationToken()})
            generate.assert_not_called()
        self.assertEqual(self.bridge._coordinator._background_budget._starts, [])

    def test_real_bridge_classifier_scores_all_profiles_and_applies_after_2_and_8_seconds(self):
        from extensions.models.settings import load, save
        settings = load(self.settings)
        settings['auxiliary']['enabled'] = True
        save(settings, self.settings)
        bridge = self.bridge
        state = bridge._profile_store.load()
        bridge.companion_profiles_manage({'action': 'select', 'selection_policy': 'auto',
                                         'expected_revision': state['revision']})
        router = bridge._routing_engine
        router._asynchronous = False
        clock = [1000.]
        router._clock = lambda: clock[0]
        runtime = bridge._behavior_runtime
        runtime._clock = lambda: clock[0]
        selected = state['profiles'][1]['id']
        requests = []
        def provider(config, messages):
            request = json.loads(messages[-1]['content'])
            requests.append(request)
            scores = {item['id']: (.95 if item['id'] == selected else .1) for item in request['scenarios']}
            return {'status': 'reported', 'text': json.dumps({'scores': scores})}
        bundle = ObservationBundle.now(source='window-visual', target='game', valid=True, text='游戏画面')
        with patch('extensions.models.auxiliary._generate', side_effect=provider):
            runtime.observation(bundle)
            self.assertEqual(requests, [])
            clock[0] += 2
            runtime.observation(bundle)
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(requests[0]['scenarios']), 2)
            self.assertFalse(bridge._coordinator.status()['proactive_enabled'])
            clock[0] += 8
            runtime.observation(bundle)
            self.assertEqual(router.view()['effective_profile_id'], selected)
            self.assertEqual(bridge._coordinator._scheduler.proactive_interval, 180)
            clock[0] += 70
            runtime.observation(bundle)
            self.assertEqual(len(requests), 1)

    def test_migration_failure_restores_runtime_on_source(self):
        bridge = self.bridge
        old = bridge._behavior_runtime
        with patch.object(bridge._behavior_library, 'migrate', side_effect=OSError('copy failed')):
            with self.assertRaises(OSError):
                bridge.behavior_manage({'action': 'migrate', 'destination': str(self.root/'external-behavior'), 'confirmed': True})
        self.assertTrue(old._stop.is_set())
        self.assertIsNot(bridge._behavior_runtime, old)
        self.assertFalse(bridge._behavior_runtime._stop.is_set())
        self.assertEqual(bridge.behavior_manage({'action': 'status'})['schema_version'], 6)

    def test_user_scope_change_closes_old_runtime_and_rotates_session(self):
        from extensions.models.settings import load
        bridge = self.bridge
        old, scope = bridge._behavior_runtime, bridge._behavior_scope()
        settings = load(self.settings)
        settings['role']['user_id'] = 'different-user'
        with patch.object(bridge, 'apply_startup', return_value={}):
            bridge.save_settings(settings)
        self.assertTrue(old._stop.is_set())
        self.assertNotEqual(scope['user'], bridge._behavior_scope()['user'])
        self.assertNotEqual(scope['session'], bridge._behavior_scope()['session'])
        self.assertIsNone(bridge._behavior_runtime._thread)

    def test_profile_sources_filter_actual_question_context(self):
        bridge = self.bridge
        state = bridge._profile_store.load()
        profile = state['profiles'][0]
        changes = {'settings': {**profile['settings'], 'context_sources': []}}
        bridge.companion_profiles_manage({'action': 'update', 'profile_id': profile['id'],
            'changes': changes, 'expected_revision': state['revision']})
        bundle = ObservationBundle.now(source='window-visual', target='reader', valid=True,
            text='正文\n[Application audio reference;secret]', image={'secret': 'image'},
            metadata={'application_audio': [{'text': 'secret audio'}], 'text_metadata': {'text': 'secret OCR'}})
        result = bridge._profile_observation(bundle)
        self.assertEqual(result.text, '')
        self.assertIsNone(result.image)
        self.assertNotIn('secret', json.dumps(result.metadata))

    def test_optional_classifier_image_uses_bounded_thumbnail_only_when_enabled(self):
        import base64
        import io
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('optional Pillow thumbnail test requires desktop dependencies')
        from extensions.models.settings import load, save
        buffer = io.BytesIO()
        Image.new('RGB', (1200, 900)).save(buffer, format='PNG')
        image = {'media_type': 'image/png', 'data_base64': base64.b64encode(buffer.getvalue()).decode()}
        settings = load(self.settings)
        settings['auxiliary']['enabled'] = True
        settings['multimodal']['enabled'] = True
        save(settings, self.settings)
        with patch('extensions.models.auxiliary._generate', return_value={'status': 'unknown'}) as generate:
            self.bridge._classify_scene({'cancellation_token': CancellationToken(), 'material': {'image': image}, 'scenarios': []})
            thumbnail = generate.call_args.kwargs['images'][0]
            with Image.open(io.BytesIO(base64.b64decode(thumbnail['data_base64']))) as result:
                self.assertLessEqual(max(result.size), 640)
            self.assertNotIn('data_base64', generate.call_args.args[1][-1]['content'])
        settings['multimodal']['enabled'] = False
        save(settings, self.settings)
        with patch('extensions.models.auxiliary._generate', return_value={'status': 'unknown'}) as generate:
            self.bridge._classify_scene({'cancellation_token': CancellationToken(), 'material': {'image': image}, 'scenarios': []})
            self.assertEqual(generate.call_args.kwargs, {})

    def test_advisory_preserves_verbatim_message(self):
        from extensions.roles.chat import build_messages
        selected = {'role_context': {'name': '角色', 'recent': []}, 'original_user_content': '原文 $(保留)'}
        messages = build_messages(selected, advisory_context='用户过去说找公式；当前仅推测')
        self.assertEqual(messages[-1]['content'], selected['original_user_content'])
        self.assertIn('当前仅推测', messages[0]['content'])

    def test_corrupt_permission_fails_closed_and_client_can_restart(self):
        bridge = self.bridge
        permission_path = bridge._behavior_permissions.path
        permission_path.write_text('{broken', encoding='utf8')
        state = bridge.behavior_manage({'action': 'permission_status'})
        self.assertEqual(state['status'], 'unavailable')
        self.assertFalse(state['effective']['can_record'])
        bridge.shutdown()
        from ui.server import Bridge
        restarted = Bridge(self.settings, capability_database=self.root/'capabilities.db',
                           schedule_directory=self.root/'schedules')
        self.addCleanup(restarted.shutdown)
        self.assertIsNone(restarted._behavior_runtime)
        self.assertEqual(restarted.behavior_manage({'action': 'permission_status'})['status'], 'unavailable')
        self.assertEqual(permission_path.read_text(encoding='utf8'), '{broken')


if __name__ == '__main__':
    unittest.main()
