import unittest
import threading
from dataclasses import replace
from datetime import timedelta
from extensions.companion import CompanionQuestionService
from extensions.companion import ObservationBundle, ObservationScheduler, PerceptionService
from extensions.companion.voice_pipeline import AudioRoute, CompanionVoicePipeline


class ObservationSchedulerTests(unittest.TestCase):
    def test_timestamp_refresh_does_not_reset_content_settling(self):
        now = [0.0]
        text = ['lesson']
        perception = PerceptionService(lambda target: ObservationBundle.now(
            source='window-visual', target=target, valid=True, text=text[0],
            metadata={'visual_observed_at':str(now[0]),
                      'text_observed_at':str(now[0]), 'text_source':'document-visible'}))
        perception.select_target('tab'); perception.start()
        calls = []
        scheduler = ObservationScheduler(perception, on_proactive=calls.append,
            settled_seconds=3, clock=lambda:now[0])
        self.assertFalse(scheduler.tick()['proactive'])
        now[0] = 2
        self.assertFalse(scheduler.tick()['proactive'])
        now[0] = 3
        self.assertTrue(scheduler.tick()['proactive'])
        now[0] = 200
        self.assertFalse(scheduler.tick()['proactive'])
        self.assertEqual(len(calls), 1)
        text[0] = 'next chapter'
        now[0] = 201
        self.assertFalse(scheduler.tick()['proactive'])
        now[0] = 204
        self.assertTrue(scheduler.tick()['proactive'])
        self.assertEqual([bundle.text for bundle in calls], ['lesson', 'next chapter'])
    def test_playback_gates_proactive_until_actual_end_and_gap(self):
        now = [0.0]
        def collect(target):
            return ObservationBundle.now(source='web', target=target, valid=True, text='lesson')
        perception = PerceptionService(collect)
        perception.select_target('tab'); perception.start()
        proactive = []
        scheduler = ObservationScheduler(perception, on_proactive=proactive.append,
            clock=lambda: now[0], playback_gap=2)
        voice = CompanionVoicePipeline(asr=lambda audio: 'question',
            answer=lambda text, route: 'answer', tts=lambda text, token: None,
            on_event=scheduler.voice_event)
        voice.start(AudioRoute('mic'), approved=True)
        token = voice.begin_turn()
        voice.submit_audio(b'pcm', token=token)
        now[0] = 10
        self.assertFalse(scheduler.tick()['proactive'])
        voice.playback_done(token)
        now[0] = 11
        self.assertFalse(scheduler.tick()['proactive'])
        now[0] = 12
        self.assertTrue(scheduler.tick()['proactive'])
        self.assertEqual(len(proactive), 1)

    def test_old_playback_end_cannot_release_new_turn(self):
        perception = PerceptionService(lambda target:
            ObservationBundle.now(source='web', target=target, valid=True, text='lesson'))
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception)
        scheduler.playback_started((1, 1))
        scheduler.playback_started((2, 2))
        self.assertEqual(scheduler.playback_ended((1, 1))['status'], 'rejected')
        self.assertFalse(scheduler.tick()['proactive'])
        scheduler.playback_ended((2, 2))

    def test_pending_expires_during_playback_without_model_call(self):
        now = [0.0]
        text = ['old']
        perception = PerceptionService(lambda target:
            ObservationBundle.now(source='web', target=target, valid=True, text=text[0]))
        perception.select_target('tab'); perception.start()
        calls = []
        scheduler = ObservationScheduler(perception, on_proactive=calls.append,
            pending_ttl=5, playback_gap=0, clock=lambda: now[0])
        scheduler.playback_started('voice')
        scheduler.tick()
        now[0] = 6
        scheduler.playback_ended('voice')
        self.assertFalse(scheduler.tick()['proactive'])
        self.assertEqual(calls, [])
        text[0] = 'fresh'
        self.assertTrue(scheduler.tick()['proactive'])
        self.assertEqual(calls[0].text, 'fresh')

    def test_change_only_proactive_and_user_activity_wins(self):
        now = [0.0]
        rows = [ObservationBundle.now(source='web', target='tab', valid=True, text='A'),
                ObservationBundle.now(source='web', target='tab', valid=True, text='A'),
                ObservationBundle.now(source='web', target='tab', valid=True, text='B')]
        proactive = []
        perception = PerceptionService(lambda target: rows.pop(0))
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception, on_proactive=proactive.append,
                                          proactive_interval=120, clock=lambda: now[0])
        self.assertTrue(scheduler.tick()['proactive'])
        self.assertFalse(scheduler.tick()['proactive'])
        scheduler.notify_user_activity(10)
        now[0] = 5
        self.assertFalse(scheduler.tick()['proactive'])
        self.assertEqual([x.text for x in proactive], ['A'])

    def test_latest_change_is_coalesced_until_rate_limit(self):
        now = [0.0]
        values = [ObservationBundle.now(source='web', target='tab', valid=True, text=x) for x in 'ABCC']
        perception = PerceptionService(lambda target: values.pop(0)); perception.select_target('tab'); perception.start()
        proactive = []
        scheduler = ObservationScheduler(perception, on_proactive=proactive.append,
                                          proactive_interval=100, clock=lambda: now[0])
        scheduler.tick(); now[0] = 1; scheduler.tick(); now[0] = 2; scheduler.tick()
        self.assertEqual([x.text for x in proactive], ['A'])
        now[0] = 101; scheduler.tick()
        self.assertEqual([x.text for x in proactive], ['A', 'C'])

    def test_scheduler_start_requires_running_perception(self):
        perception = PerceptionService(lambda target: ObservationBundle.now(source='web', target=target, valid=True))
        scheduler = ObservationScheduler(perception)
        with self.assertRaises(RuntimeError): scheduler.start()

    def test_invalid_and_stale_observations_never_trigger_old_pending(self):
        now = [0.0]
        first = ObservationBundle.now(source='web', target='tab', valid=True, text='A')
        changed = replace(first, observed_at=first.observed_at + timedelta(seconds=1), text='B')
        invalid = replace(changed, observed_at=changed.observed_at + timedelta(seconds=1), valid=False)
        values = iter([first, changed, invalid, first])
        proactive, observed = [], []
        perception = PerceptionService(lambda target: next(values))
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception, on_proactive=proactive.append,
            on_observation=observed.append, clock=lambda: now[0])
        scheduler.tick(); now[0] = 1; scheduler.tick()
        now[0] = 130
        self.assertFalse(scheduler.tick()['proactive'])
        self.assertEqual(scheduler.tick()['status'], 'rejected')
        self.assertEqual(len(proactive), 1)
        self.assertEqual(len(observed), 3)

    def test_image_changes_and_service_binding_use_current_observation(self):
        first = ObservationBundle.now(source='visual', target='tab', valid=True,
            image={'media_type':'image/jpeg','data_base64':'first'})
        second = replace(first, observed_at=first.observed_at + timedelta(seconds=1),
            image={'media_type':'image/jpeg','data_base64':'second'})
        values = iter([first, second])
        calls = []
        service = CompanionQuestionService(lambda prompt, **kw: calls.append(kw) or {'text':'answer'})
        perception = PerceptionService(lambda target: next(values))
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception)
        scheduler.bind_question_service(service)
        scheduler.tick()
        self.assertTrue(scheduler.tick()['changed'])
        self.assertIs(service.latest, second)
        self.assertEqual(calls[0]['images'][0]['data_base64'], 'first')
        scheduler.stop()
        self.assertIsNone(service.latest)

    def test_stop_during_capture_drops_late_frame(self):
        entered, release = threading.Event(), threading.Event()
        observed, errors = [], []
        def collect(target):
            entered.set()
            if not release.wait(5): raise RuntimeError('fixture timed out')
            return ObservationBundle.now(source='web', target=target, valid=True, text='late')
        perception = PerceptionService(collect)
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception, on_observation=observed.append)
        def tick():
            try: scheduler.tick()
            except RuntimeError as error: errors.append(str(error))
        worker = threading.Thread(target=tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            scheduler.stop()
        finally:
            release.set(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, [])
        self.assertEqual(len(errors), 1)

    def test_pause_resume_during_capture_invalidates_old_epoch(self):
        perception = None
        def collect(target):
            perception.pause(); perception.start()
            return ObservationBundle.now(source='web', target=target, valid=True)
        perception = PerceptionService(collect)
        perception.select_target('tab'); perception.start()
        with self.assertRaisesRegex(RuntimeError, 'superseded'): perception.observe()

    def test_failed_capture_revokes_bound_question_context(self):
        service = CompanionQuestionService(lambda *a, **kw: {'text':'answer'})
        service.update(ObservationBundle.now(source='web', target='tab', valid=True, text='old'))
        def collect(target): raise OSError('window closed')
        perception = PerceptionService(collect)
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception)
        scheduler.bind_question_service(service)
        with self.assertRaises(OSError): scheduler.tick()
        self.assertIsNone(service.latest)
        self.assertIsNone(scheduler.latest)

    def test_proactive_failure_is_reported_and_does_not_escape_tick(self):
        first = ObservationBundle.now(source='web', target='tab', valid=True, text='lesson')
        errors = []
        perception = PerceptionService(lambda target: first)
        perception.select_target('tab'); perception.start()
        scheduler = ObservationScheduler(perception, proactive_interval=1,
            on_proactive=lambda observation: (_ for _ in ()).throw(RuntimeError('provider down')),
            on_error=errors.append)
        result = scheduler.tick()
        self.assertEqual(result['status'], 'proactive_error')
        self.assertFalse(result['proactive'])
        self.assertEqual(scheduler.error['type'], 'RuntimeError')
        self.assertNotIn('message', errors[0])
        self.assertFalse(scheduler.tick()['proactive'])
        scheduler.stop()
        self.assertIsNone(scheduler.error)
