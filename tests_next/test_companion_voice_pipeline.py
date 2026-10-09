import unittest
import threading
from extensions.companion.voice_pipeline import AudioRoute, CompanionVoicePipeline


class CompanionVoicePipelineTests(unittest.TestCase):
    def test_new_question_stops_existing_playback(self):
        cancelled = []
        p = CompanionVoicePipeline(asr=lambda audio: 'question',
            answer=lambda text, route: 'answer', tts=lambda text, token: None,
            cancel=lambda: cancelled.append(True))
        p.start(AudioRoute('mic'), approved=True)
        first = p.begin_turn()
        p.submit_audio(b'pcm', token=first)
        second = p.begin_turn()
        self.assertEqual(cancelled, [True])
        self.assertNotEqual(first, second)
        with self.assertRaises(RuntimeError): p.playback_done(first)
        self.assertEqual(p.session.snapshot()['state'], 'listening')

    def test_provider_failure_has_explicit_error_state(self):
        for stage in ('asr', 'answer'):
            with self.subTest(stage=stage):
                def fail(*args, **kwargs): raise OSError('provider unavailable')
                p = CompanionVoicePipeline(
                    asr=fail if stage == 'asr' else lambda audio: 'question',
                    answer=fail if stage == 'answer' else lambda text, route: 'answer',
                    tts=lambda text, token: self.fail('failed turn must not play'))
                p.start(AudioRoute('mic'), approved=True)
                token = p.begin_turn()
                with self.assertRaises(OSError): p.submit_audio(b'pcm', token=token)
                self.assertEqual(p.session.snapshot()['state'], 'error')
                p.interrupt()
                self.assertIsNotNone(p.begin_turn())

    def test_late_provider_failure_does_not_fail_new_turn(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def asr(audio):
            entered.set()
            if not release.wait(3): raise TimeoutError('test stalled')
            raise OSError('old provider failed')
        p = CompanionVoicePipeline(asr=asr, answer=lambda text, route: 'answer',
                                   tts=lambda text, token: None)
        p.start(AudioRoute('mic'), approved=True)
        first = p.begin_turn()
        def submit():
            try: p.submit_audio(b'pcm', token=first)
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=submit)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            p.interrupt()
            second = p.begin_turn()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(errors[0], OSError)
        self.assertEqual(p.session.snapshot()['state'], 'listening')
        self.assertEqual(p._token(), second)

    def test_requires_consent_and_keeps_microphone_separate(self):
        p = CompanionVoicePipeline(asr=lambda audio: '问题', answer=lambda text, route: '回答',
                                   tts=lambda text, token: None)
        route = AudioRoute('mic:1', application='browser', process_id=123)
        with self.assertRaises(PermissionError): p.start(route)
        started = p.start(route, approved=True)
        self.assertEqual(started['route']['microphone'], 'mic:1')
        self.assertEqual(started['route']['process_id'], 123)

    def test_turn_runs_asr_answer_tts_and_playback(self):
        spoken = []
        p = CompanionVoicePipeline(asr=lambda audio: '问题', answer=lambda text, route: '回答',
                                   tts=lambda text, token: spoken.append((text, token)))
        p.start(AudioRoute('mic'), approved=True)
        token = p.begin_turn()
        state = p.submit_audio(b'pcm', token=token)
        self.assertEqual(state['state'], 'playing')
        self.assertEqual(spoken[0][0], '回答')
        self.assertEqual(p.playback_done(token)['state'], 'idle')

    def test_interrupt_invalidates_late_provider(self):
        p = CompanionVoicePipeline(asr=lambda audio: '问题', answer=lambda text, route: '回答',
                                   tts=lambda text, token: None)
        p.start(AudioRoute('mic'), approved=True)
        token = p.begin_turn()
        p.interrupt()
        with self.assertRaises(RuntimeError): p.submit_audio(b'pcm', token=token)

    def test_interrupt_allows_next_turn(self):
        p = CompanionVoicePipeline(asr=lambda audio: '问题', answer=lambda text, route: '回答',
                                   tts=lambda text, token: None)
        p.start(AudioRoute('mic'), approved=True)
        first = p.begin_turn()
        p.interrupt()
        second = p.begin_turn()
        self.assertNotEqual(first, second)
        self.assertEqual(p.submit_audio(b'pcm', token=second)['state'], 'playing')

    def test_process_route_is_explicit(self):
        with self.assertRaises(ValueError): AudioRoute('mic', application='browser')

    def test_tts_failure_releases_playback_gate(self):
        events = []
        def tts(text, token): raise OSError('device unavailable')
        p = CompanionVoicePipeline(asr=lambda audio: '问题', answer=lambda text, route: '回答',
            tts=tts, on_event=lambda event, token: events.append((event, token)))
        p.start(AudioRoute('mic'), approved=True)
        token = p.begin_turn()
        with self.assertRaises(OSError): p.submit_audio(b'pcm', token=token)
        self.assertEqual(events[-2:], [('playback_started', token), ('playback_ended', token)])
        self.assertEqual(p.session.snapshot()['state'], 'error')

    def test_failed_provider_stop_still_fences_pipeline_and_releases_gate(self):
        events = []
        def cancel(): raise OSError('provider stop failed')
        p = CompanionVoicePipeline(asr=lambda audio: '问题', answer=lambda text, route: '回答',
            tts=lambda text, token: None, cancel=cancel,
            on_event=lambda event, token: events.append((event, token)))
        p.start(AudioRoute('mic'), approved=True)
        token = p.begin_turn()
        p.submit_audio(b'pcm', token=token)
        with self.assertRaises(OSError): p.stop()
        self.assertEqual(events[-1], ('stopped', token))
        with self.assertRaisesRegex(RuntimeError, 'not started'): p.begin_turn()
