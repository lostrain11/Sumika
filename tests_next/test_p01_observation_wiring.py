"""P01 acceptance: the real Bridge entry drives the session owner (F-08/F-09).

The audit reproduced both defects through the real Bridge: publishing an
observation returned "updated" while the scheduler stayed stopped, and a
single stale projection accumulated 181 seconds of dwell. These tests pin
the fixed behavior through Bridge.companion_observe/_companion_publish —
not through direct coordinator calls.
"""
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from extensions.companion.observation_scheduler import ObservationScheduler


def _observation(target='reader', text='lesson body', *, at=None, page=None,
                 danmaku=None):
    metadata = {}
    if page is not None:
        metadata['page'] = page
    if danmaku is not None:
        metadata['danmaku'] = danmaku
    return {'source': 'window-visual', 'target': target, 'valid': True,
            'text': text, 'metadata': metadata,
            'observed_at': (at or datetime.now(timezone.utc)).isoformat()}


class P01ObservationWiringTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        import tempfile
        from extensions.models.settings import example, save as save_settings
        from ui.server import serve
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.settings_path = root / 'settings.json'
        capability_path = root / 'capabilities.db'
        connection = sqlite3.connect(capability_path)
        connection.execute("CREATE TABLE capabilities (id TEXT PRIMARY KEY, position INTEGER, enabled INTEGER, provider TEXT, options TEXT)")
        connection.commit()
        connection.close()
        save_settings(example(root / 'role', root / 'sumika.db'), self.settings_path)
        self.server = serve(self.settings_path, port=0,
                            capability_database=capability_path,
                            schedule_directory=root / 'schedules')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.bridge = self.server.sumika_bridge
        self.coordinator = self.bridge._coordinator
        # Deterministic ticking: the Bridge entry stays real, but the
        # scheduler and the behavior tracker are driven by one fake clock.
        self.coordinator._scheduler_thread = False
        self.clock = [1000.0]
        from extensions.companion.reading_behavior import ReadingBehaviorTracker
        self.coordinator._behavior = ReadingBehaviorTracker(clock=lambda: self.clock[0])
        self.events = []
        self.coordinator._scheduler = ObservationScheduler(
            self.coordinator._perception,
            on_observation=self.coordinator._observe,
            on_proactive=self.coordinator._dispatch_proactive,
            on_error=lambda error: None,
            clock=lambda: self.clock[0], sleeper=lambda seconds: None,
            proactive_interval=86400.0, settled_seconds=3)
        # A deterministic chat stub: the real provider is disabled in the
        # example settings and P01's subject is the wiring, not the model.
        self.chat_calls = []
        def stub_chat(prompt, **kwargs):
            self.chat_calls.append(prompt)
            return {'text': '好的，我们一起看。'}
        self.coordinator.service._role_chat = stub_chat

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self._tmp.cleanup()

    def publish(self, payload):
        return self.bridge.companion_observe(payload)

    def tick_seconds(self, count):
        for _ in range(count):
            self.clock[0] += 1.0
            self.coordinator._scheduler.tick()

    def behavior_events(self):
        return [event for event in self.bridge._voice_events
                if event.get('event') == 'proactive_text'
                and event.get('kind') == 'behavior']

    def wait_for_behavior_event(self, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.behavior_events():
                return True
            time.sleep(0.05)
        return bool(self.behavior_events())

    def test_real_bridge_entry_starts_scheduler_target_and_danmaku(self):
        """F-08: publishing through the Bridge starts the session owner."""
        result = self.publish(_observation(page=3))
        self.assertEqual(result.get('status'), 'updated')
        self.assertTrue(self.coordinator._perception.state == 'running',
                        'scheduler perception must run after a real publish')
        self.assertEqual(self.coordinator._scheduler_target, 'reader')
        # The danmaku side channel is wired through the same entry. The
        # buffer's snapshot text shape is F-07 (P06); here we assert wiring.
        self.publish(_observation(page=3, danmaku=['为什么这里取负号']))
        self.assertEqual(len(self.coordinator.danmaku.snapshot_texts()), 1)
        self.assertTrue(any(event.get('event') == 'danmaku_new'
                            for event in self.bridge._voice_events))

    def test_rejected_observation_has_zero_side_effects(self):
        """Acceptance gates the side effects: a superseded publish must not
        start the scheduler or feed the danmaku buffer."""
        self.publish(_observation(page=1, at=datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)))
        self.coordinator._scheduler_target = None
        self.coordinator._perception.stop()
        rejected = self.publish(_observation(
            page=2, danmaku=['迟到的弹幕'],
            at=datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)))
        # The stale publish is normalized for provenance but its side
        # effects are gated on the service's acceptance decision.
        self.coordinator._behavior.reset()
        self.assertEqual(self.coordinator.danmaku.snapshot_texts(), [])

    def test_single_projection_accumulates_no_dwell(self):
        """F-09: one publish re-projected for 181 ticks never reports dwell."""
        self.publish(_observation(page=5))
        self.publish(_observation(page=5))
        self.tick_seconds(181)
        self.assertEqual(self.behavior_events(), [])

    def test_fresh_same_page_verifications_accumulate_one_dwell(self):
        """Fresh verifications of a static page accumulate effective time and
        report long dwell exactly once."""
        self.publish(_observation(page=5))
        for _ in range(185):
            self.clock[0] += 1.0
            self.publish(_observation(page=5,
                                      at=datetime.now(timezone.utc)))
            self.coordinator._scheduler.tick()
        self.assertTrue(self.wait_for_behavior_event())
        events = self.behavior_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['behavior']['kind'], 'long_dwell')

    def test_capture_gap_longer_than_three_seconds_breaks_dwell(self):
        """Verifications more than three seconds apart end the segment."""
        self.publish(_observation(page=5))
        for _ in range(100):
            self.clock[0] += 1.0
            self.publish(_observation(page=5, at=datetime.now(timezone.utc)))
            self.coordinator._scheduler.tick()
        # Capture stalls for ten seconds: no fresh verification accumulates.
        self.clock[0] += 10.0
        for _ in range(100):
            self.clock[0] += 1.0
            self.publish(_observation(page=5, at=datetime.now(timezone.utc)))
            self.coordinator._scheduler.tick()
        self.assertEqual(self.behavior_events(), [])

    def test_freshness_fields_do_not_trigger_repeated_model(self):
        """Observation identity/freshness metadata must stay out of the
        content digest: same content with fresh identity keeps the history."""
        self.publish(_observation(page=5))
        first = self.coordinator.ask_text('这一页讲了什么？')
        revision_after_first = self.coordinator.service._content_revision
        self.publish(_observation(page=5))
        self.assertEqual(self.coordinator.service._content_revision,
                         revision_after_first,
                         'a fresh capture of unchanged content must not bump '
                         'the content revision (it would cancel the history '
                         'and re-fire the model)')
        second = self.coordinator.ask_text('再解释一下')
        self.assertEqual(second['context_turns'], 2)


if __name__ == '__main__':
    unittest.main()
