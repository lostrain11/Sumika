"""P02 acceptance: user preemption arbitrates background generations (F-06).

The audit reproduced a background reply arriving AFTER the user's text
question on unchanged material. These tests pin the fixed arbitration:
user activity invalidates and cancels in-flight background generations,
text questions hold a busy span, and proactive/behavior emissions share a
speech fence.
"""
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from extensions.companion.contracts import ObservationBundle
from extensions.companion.observation_scheduler import ObservationScheduler
from extensions.companion.reading_behavior import ReadingBehaviorTracker
from extensions.companion.session_coordinator import StudySessionCoordinator


def bundle(page, tick=0, text='lesson body'):
    observed = datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=page + tick)
    return ObservationBundle(observed_at=observed, source='window-visual',
                             target='reader', valid=True, text=text, image=None,
                             media_time_seconds=None, metadata={'page': page})


class P02PreemptionTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.chat_calls = []
        self.events = []
        self.now = [1000.0]
        self.background_release = threading.Event()
        self.background_started = threading.Event()

        def chat(prompt, *, session_id, images=None, on_delta=None, **kwargs):
            self.chat_calls.append({'prompt': prompt, 'background': '[用户问题]' not in prompt})
            if '[用户问题]' not in prompt:
                self.background_started.set()
                self.background_release.wait(5)
            return {'text': '好的，我们一起看。'}

        self.tracker = ReadingBehaviorTracker(clock=lambda: self.now[0])
        self.coordinator = StudySessionCoordinator(
            chat=chat, current=lambda: None,
            on_event=lambda name, detail: self.events.append({'event': name, **detail}),
            include_images=lambda: False, scheduler_thread=False,
            behavior_tracker=self.tracker, speech_fence=0.5)
        self.scheduler = ObservationScheduler(
            self.coordinator._perception,
            on_observation=self.coordinator._observe,
            on_proactive=self.coordinator._dispatch_proactive,
            on_error=lambda error: None,
            clock=lambda: self.now[0], sleeper=lambda seconds: None,
            proactive_interval=86400.0, settled_seconds=0)
        self.coordinator._scheduler = self.scheduler

    def tearDown(self):
        self.background_release.set()
        self.coordinator.close()

    def start_background(self):
        """Publish once and tick: the proactive dispatch begins and blocks."""
        self.coordinator.publish_observation(bundle(4))
        self.scheduler.notify_user_activity(0)
        self.scheduler.tick()
        self.assertTrue(self.background_started.wait(3),
                        'background generation must start')

    def proactive_events(self):
        return [event for event in self.events if event.get('event') == 'proactive_text']

    def test_user_text_question_cancels_pending_background(self):
        self.start_background()
        result = self.coordinator.ask_text('这一页讲了什么？')
        self.assertEqual(result['text'], '好的，我们一起看。')
        self.background_release.set()
        self.coordinator._proactive_thread.join(3)
        self.assertFalse(self.coordinator._proactive_thread.is_alive(),
                         'background generation must be joined after cancellation')
        self.assertEqual(self.proactive_events(), [],
                         'a background generation superseded by the user '
                         'question must never be emitted')

    def test_ask_text_busy_defers_behavior_dispatch(self):
        ask_done = threading.Event()
        ask_result = []
        self.start_background()
        self.background_release.set()
        self.coordinator._proactive_thread.join(3)
        del self.chat_calls[:]

        def blocking_ask():
            ask_result.append(self.coordinator.ask_text('再讲讲这里'))
            ask_done.set()
        blocker = threading.Event()

        def chat2(prompt, *, session_id, images=None, on_delta=None, **kwargs):
            self.chat_calls.append({'prompt': prompt, 'background': '[用户问题]' not in prompt})
            if '[用户问题]' in prompt:
                blocker.wait(5)
            return {'text': '回答'}
        self.coordinator.service._role_chat = chat2
        worker = threading.Thread(target=blocking_ask, daemon=True)
        worker.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self.chat_calls:
            time.sleep(0.02)
        # A behavior report during the user's question must not dispatch.
        for step in range(30):
            self.now[0] += 1.0
            self.coordinator.publish_observation(bundle(4, tick=step))
            self.scheduler.notify_user_activity(0)
            self.scheduler.tick()
        notes = [call for call in self.chat_calls if '行为观察' in call['prompt']]
        self.assertEqual(notes, [], 'behavior notes must not interrupt a text question')
        blocker.set()
        self.assertTrue(ask_done.wait(3))
        worker.join(3)
        self.assertEqual(ask_result[0]['text'], '回答')

    def test_disabling_proactive_cancels_inflight_background(self):
        self.start_background()
        self.coordinator.set_proactive(enabled=False, interval_seconds=120)
        self.background_release.set()
        self.coordinator._proactive_thread.join(3)
        self.assertEqual(self.proactive_events(), [],
                         'disabling proactive must cancel the in-flight generation')

    def test_voice_user_started_cancels_pending_background(self):
        self.start_background()
        self.coordinator.voice_user_started('turn-1')
        self.background_release.set()
        self.coordinator._proactive_thread.join(3)
        self.assertEqual(self.proactive_events(), [],
                         'speech start must cancel the in-flight generation')

    def test_speech_fence_spaces_behavior_after_proactive(self):
        # A proactive emission opens the shared speech fence; behavior notes
        # wait until it closes (0.5s fence in this harness).
        self.coordinator.publish_observation(bundle(4))
        self.scheduler.notify_user_activity(0)
        self.scheduler.tick()
        self.assertTrue(self.background_started.wait(3))
        self.background_release.set()
        self.coordinator._proactive_thread.join(3)
        self.assertEqual(len(self.proactive_events()), 1)
        # Within the fence: behavior reports are queued, not dispatched.
        for step in range(60):
            self.now[0] += 1.0
            self.coordinator.publish_observation(bundle(4, tick=step))
            self.scheduler.notify_user_activity(0)
            self.scheduler.tick()
        notes = [call for call in self.chat_calls if '行为观察' in call['prompt']]
        self.assertEqual(notes, [], 'behavior notes must respect the shared speech fence')


if __name__ == '__main__':
    unittest.main()
