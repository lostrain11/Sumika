"""The single companion session owner: one history, host-side dispatch."""
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from extensions.companion.contracts import ObservationBundle
from extensions.companion.observation_scheduler import ObservationScheduler
from extensions.companion.session_coordinator import (
    CoordinatorStopped, StudySessionCoordinator)


def bundle(text='lesson body', target='lesson', valid=True, *,
           observed_at=datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc),
           source='window-visual'):
    return ObservationBundle(observed_at=observed_at, source=source, target=target,
                             valid=valid, text=text, image=None,
                             media_time_seconds=None, metadata={})


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.chat_calls = []
        self.events = []
        lock = threading.Lock()
        def chat(prompt, *, session_id, images=None, on_delta=None, **kwargs):
            with lock:
                self.chat_calls.append(prompt)
            if on_delta is not None:
                on_delta({'text': '部分'})
            return {'text': '部分' + '回答'}
        self.coordinator = StudySessionCoordinator(chat=chat,
            current=lambda: None, on_event=lambda name, detail:
            self.events.append({'event': name, **detail}),
            include_images=lambda: False, scheduler_thread=False)
        scheduler = ObservationScheduler(self.coordinator._perception,
            on_observation=self.coordinator.service.update,
            on_proactive=self.coordinator._dispatch_proactive,
            on_error=lambda error: None,
            clock=lambda: self.now[0], sleeper=lambda seconds: None,
            proactive_interval=120.0, settled_seconds=0)
        self.coordinator._scheduler = scheduler
        self.scheduler = scheduler

    def tick(self):
        self.scheduler.notify_user_activity(0)
        return self.scheduler.tick()

    def wait_for(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.02)
        return predicate()

    def test_text_question_answers_without_microphone(self):
        self.coordinator.publish_observation(bundle())
        result = self.coordinator.ask_text('这一页讲了什么？')
        self.assertEqual(result['text'], '部分回答')
        self.assertEqual(result['context_turns'], 1)
        self.assertIsNone(self.coordinator.status()['failed'])
        self.assertFalse(self.coordinator.status()['speaker_attached'])

    def test_text_question_requires_context(self):
        with self.assertRaisesRegex(RuntimeError, 'no observation'):
            self.coordinator.ask_text('问题')

    def test_voice_flow_shares_history_with_text(self):
        self.coordinator.publish_observation(bundle())
        self.coordinator.ask_text('第一问')
        self.coordinator.voice_user_started('turn-1')
        result = self.coordinator.voice_request(request=1, turn='turn-1',
                                                text='第二问', record_history=True)
        self.assertEqual(result['text'], '部分回答')
        status = self.coordinator.status()
        self.assertEqual(status['active_requests'], 1)
        self.coordinator.voice_request_delivered(1)
        self.coordinator.voice_request_finished(1)
        self.assertEqual(self.coordinator.status()['active_requests'], 0)
        # The voice answer joined the same short-term history as text questions.
        third = self.coordinator.ask_text('第三问')
        self.assertEqual(third['context_turns'], 3)

    def test_late_voice_turn_is_dropped_without_dispatch(self):
        self.coordinator.publish_observation(bundle())
        with self.assertRaises(CoordinatorStopped):
            self.coordinator.voice_request(request=1, turn='never-bound',
                                           text='迟到的转写', record_history=True)
        self.assertEqual(self.chat_calls, [])
        # A second speech-start supersedes the first frozen binding.
        self.coordinator.voice_user_started('turn-1')
        self.coordinator.voice_user_started('turn-2')
        self.coordinator.voice_request(request=2, turn='turn-2',
                                       text='新 turn', record_history=True)
        with self.assertRaises(CoordinatorStopped):
            self.coordinator.voice_request(request=3, turn='turn-1',
                                           text='旧 turn', record_history=True)
        self.assertEqual(self.coordinator.status()['active_requests'], 1)

    def test_context_invalidation_cancels_speaking_request(self):
        self.coordinator.publish_observation(bundle())
        blocking = threading.Event()
        release = threading.Event()
        def chat(prompt, *, session_id, images=None, on_delta=None, **kwargs):
            blocking.set()
            release.wait(3)
            return {'text': '迟到的回答'}
        self.coordinator.service._role_chat = chat
        self.coordinator.voice_user_started('turn-1')
        result_box = []
        def run():
            result_box.append(self.coordinator.voice_request(request=7, turn='turn-1',
                text='问题', record_history=True))
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.assertTrue(blocking.wait(3))
        # A revoked context must cancel the in-flight model request; the
        # service may report either cancellation or a stale generation.
        self.coordinator.revoke()
        release.set()
        worker.join(3)
        self.assertIn(result_box[0].get('status'), ('cancelled', 'stale_response'))
        self.assertEqual(self.coordinator.status()['active_requests'], 0)

    def test_failure_stops_new_dispatch_until_reset(self):
        self.coordinator.publish_observation(bundle())
        self.coordinator.voice_user_started('turn-1')
        self.coordinator.fail('worker pipe failed')
        with self.assertRaises(CoordinatorStopped):
            self.coordinator.ask_text('问题')
        self.assertEqual(self.coordinator.failed, 'worker pipe failed')
        self.assertEqual(self.coordinator.status()['active_requests'], 0)
        self.coordinator.reset()
        self.coordinator.publish_observation(bundle(observed_at=datetime(
            2026, 10, 9, 12, 1, 0, tzinfo=timezone.utc)))
        result = self.coordinator.ask_text('恢复后的问题')
        self.assertEqual(result['text'], '部分回答')

    def test_proactive_dispatch_reaches_speaker_and_text_event(self):
        spoken = []
        self.coordinator.attach_speaker(lambda text: spoken.append(text))
        self.coordinator.publish_observation(bundle())
        self.now[0] += 121
        self.tick()
        deadline = time.monotonic() + 3
        while not spoken and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(spoken), 1)
        proactive = [event for event in self.events if event['event'] == 'proactive_text']
        self.assertEqual(len(proactive), 1)
        # Proactive discussion never enters the user question history.
        self.assertEqual([call for call in self.chat_calls if '值得一起讨论' in call],
                         self.chat_calls)

    def test_proactive_requires_change_and_respects_interval_and_disable(self):
        self.coordinator.publish_observation(bundle())
        self.now[0] += 121
        self.tick()  # first content settles and dispatches
        # The single-in-flight guard skips dispatch while the previous
        # generation thread is still exiting; wait for it to finish.
        self.assertTrue(self.wait_for(lambda: len(self.chat_calls) == 1
            and not self.coordinator._proactive_thread.is_alive()))
        self.now[0] += 1
        self.tick()  # unchanged content: no dispatch
        calls = len(self.chat_calls)
        self.now[0] += 30
        self.coordinator.publish_observation(bundle(text='new page',
            observed_at=bundle().observed_at + timedelta(seconds=1)))
        self.tick()  # inside the minimum interval: pending but quiet
        self.assertEqual(len(self.chat_calls), calls)
        self.now[0] += 121
        self.tick()
        self.assertTrue(self.wait_for(lambda: len(self.chat_calls) == calls + 1))
        self.coordinator.set_proactive(enabled=False, interval_seconds=120)
        self.coordinator.publish_observation(bundle(text='third page',
            observed_at=bundle().observed_at + timedelta(seconds=2)))
        self.now[0] += 121
        self.tick()
        self.assertEqual(len(self.chat_calls), calls + 1)


if __name__ == '__main__':
    unittest.main()
