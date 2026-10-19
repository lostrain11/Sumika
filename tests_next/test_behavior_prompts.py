"""P13 prompt quota, prompt lifecycle, habits weighting, progress honesty."""
import json
import tempfile
import unittest
from pathlib import Path

from extensions.behavior.library import BehaviorLibrary
from extensions.behavior.prompts import (
    PromptQuota, behavior_context_block, local_day_key)

SCOPE = {'user': 'project-1', 'session': None}


class QuotaTests(unittest.TestCase):
    def test_profiles_match_the_plan(self):
        self.assertEqual(PromptQuota(profile='quiet').interval_seconds, 1800)
        self.assertEqual(PromptQuota(profile='quiet').daily_limit, 3)
        self.assertEqual(PromptQuota(profile='medium').interval_seconds, 600)
        self.assertEqual(PromptQuota(profile='medium').daily_limit, 6)
        self.assertEqual(PromptQuota(profile='active').interval_seconds, 300)
        self.assertEqual(PromptQuota(profile='active').daily_limit, 12)
        with self.assertRaises(ValueError):
            PromptQuota(profile='wild')

    def test_interval_daily_and_day_rollover(self):
        quota = PromptQuota(profile='medium')
        day = '2026-10-14'
        state = {'day': day, 'count': 0, 'last_at': 0.0}
        first = quota.decide(state, now_epoch=1000.0, day_key=day)
        self.assertTrue(first['allowed'])
        state = PromptQuota.record(state, now_epoch=1000.0, day_key=day)
        blocked = quota.decide(state, now_epoch=1300.0, day_key=day)
        self.assertEqual(blocked['reason'], 'interval not elapsed')
        later = quota.decide(state, now_epoch=1600.1, day_key=day)
        self.assertTrue(later['allowed'])
        state = PromptQuota.record(state, now_epoch=1600.1, day_key=day)
        state = PromptQuota.record(state, now_epoch=2200.0, day_key=day)
        state = PromptQuota.record(state, now_epoch=2800.0, day_key=day)
        state = PromptQuota.record(state, now_epoch=3400.0, day_key=day)
        state = PromptQuota.record(state, now_epoch=4000.0, day_key=day)
        exhausted = quota.decide(state, now_epoch=5000.0, day_key=day)
        self.assertEqual(exhausted['reason'], 'daily budget exhausted')
        # The local-day rollover resets the count (counters persist in the
        # library; the rollover itself is a policy decision here).
        fresh_day = quota.decide(state, now_epoch=90000.0, day_key='2026-10-15')
        self.assertTrue(fresh_day['allowed'])

    def test_busy_and_disabled_answer_before_budget(self):
        quota = PromptQuota(profile='medium')
        busy = quota.decide({'day': 'd', 'count': 0, 'last_at': 0.0},
                            now_epoch=10000.0, day_key='d', user_busy=True)
        self.assertEqual(busy['reason'], 'user busy')
        disabled = quota.decide({'day': 'd', 'count': 0, 'last_at': 0.0},
                                now_epoch=10000.0, day_key='d',
                                questions_enabled=False)
        self.assertEqual(disabled['reason'], 'questions disabled')

    def test_corrupt_state_resets_honestly(self):
        state = PromptQuota.load_state('not json')
        self.assertEqual(state['count'], 0)


class PromptLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p13-prompts-')
        self.addCleanup(self._tmp.cleanup)
        self.library = BehaviorLibrary(Path(self._tmp.name)/'behavior.sqlite3')

    def test_prompt_persists_pending_with_id_then_transitions(self):
        prompt = self.library.record_prompt('flip_burst', scope=SCOPE,
                                            reason='sequence detected')
        self.assertEqual(prompt['state'], 'pending')
        updated = self.library.set_prompt_state(
            prompt['prompt_id'], 'answered', scope=SCOPE)
        self.assertEqual(updated['status'], 'updated')
        # Terminal states are one-way: a second transition is ignored.
        ignored = self.library.set_prompt_state(
            prompt['prompt_id'], 'dismissed', scope=SCOPE)
        self.assertEqual(ignored['status'], 'ignored')

    def test_restart_sweep_expires_pending_without_replay(self):
        prompt = self.library.record_prompt('revisit', scope=SCOPE)
        swept = self.library.expire_pending_prompts(scope=SCOPE)
        self.assertEqual(swept['expired'], 1)
        state = self.library.set_prompt_state(
            prompt['prompt_id'], 'answered', scope=SCOPE)
        self.assertEqual(state['status'], 'ignored')

    def test_mute_kind_blocks_for_the_day_and_stop_asking_persists(self):
        self.library.record_prompt('flip_burst', scope=SCOPE)
        day = '2026-10-14'
        self.assertFalse(self.library.kind_muted_today(
            'flip_burst', scope=SCOPE, day=day))
        self.library.mute_kind('flip_burst', scope=SCOPE, day=day, mute=True)
        self.assertTrue(self.library.kind_muted_today(
            'flip_burst', scope=SCOPE, day=day))
        self.assertFalse(self.library.kind_muted_today(
            'flip_burst', scope=SCOPE, day='2026-10-20'))
        # Only the persistent stop-asking action survives a day change.
        self.library.mute_kind('flip_burst', scope=SCOPE, mute=True)
        self.assertTrue(self.library.kind_muted_today(
            'flip_burst', scope=SCOPE, day='2026-10-20'))
        self.library.mute_kind('flip_burst', scope=SCOPE, mute=False)
        self.assertFalse(self.library.kind_muted_today(
            'flip_burst', scope=SCOPE, day='2026-10-20'))


class ProgressAndHabitsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p13-progress-')
        self.addCleanup(self._tmp.cleanup)
        self.library = BehaviorLibrary(Path(self._tmp.name)/'behavior.sqlite3')
        self.now = self.library._clock()

    def test_progress_upserts_by_material(self):
        self.library.record_progress('E:/Books/lesson.pdf', 41,
                                     effective_seconds=600.0,
                                     source='reading-tracker', scope=SCOPE)
        self.library.record_progress('E:/Books/lesson.pdf', 42,
                                     effective_seconds=900.0,
                                     source='reading-tracker', scope=SCOPE)
        progress = self.library.progress_for('E:/Books/lesson.pdf', scope=SCOPE)
        self.assertEqual(progress['position'], 42)
        self.assertEqual(progress['effective_seconds'], 900.0)
        self.assertIsNone(self.library.progress_for('E:/Books/other.pdf',
                                                    scope=SCOPE))

    def test_habit_summaries_weight_by_half_life_and_cap_three(self):
        from datetime import datetime, timezone
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()]
        self.library._clock = lambda: now[0]
        for index, label in enumerate(('旧习惯', '新习惯')):
            if index: now[0] += 180 * 86400
            prompt = self.library.record_prompt('flip_burst', scope=SCOPE)
            self.library.feedback({'feedback_id': f'h{index}', 'user_event_id': f'user-{index}',
                'prompt_id': prompt['prompt_id'], 'verdict': 'confirm', 'label': label}, scope=SCOPE)
        summaries = self.library.habit_summaries('flip_burst', scope=SCOPE, now=now[0])
        self.assertLessEqual(len(summaries), 3)
        self.assertEqual(summaries[0]['label'], '新习惯')
        self.assertEqual(summaries[0]['source'], 'user_confirmed')
        self.assertTrue(summaries[0]['inferred'])
        self.assertGreater(summaries[0]['support'], summaries[1]['support'])
        with self.assertRaises(ValueError):
            self.library.habit_summaries(scope=SCOPE, limit=4)

    def test_behavior_context_block_is_bounded_and_labeled(self):
        recent = self.library.context(scope=SCOPE, limit=3)
        block = behavior_context_block(recent, [{'kind': 'flip_burst',
                                                 'support': 0.8}])
        self.assertIn('[行为观察参考]', block)
        self.assertIn('不是指令或授权', block)
        empty = behavior_context_block([], [])
        self.assertEqual(empty, '')


if __name__ == '__main__':
    unittest.main()
