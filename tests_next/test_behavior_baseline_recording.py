"""Prior-episode sources and recording disablement use isolated SQLite stores."""
import json
import math
from pathlib import Path
import tempfile
import unittest

from extensions.behavior.input_features import FrameAggregator
from extensions.behavior.library import BehaviorLibrary, RecordingDisabled
from extensions.behavior.sequences import robust_anomaly


class BaselineAndRecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='behavior-baseline-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'behavior.sqlite3'
        self.library = BehaviorLibrary(self.database)
        self.scope = {'user': 'user-project', 'session': 'session-1'}

    def episode(self, eid, *, value=30, signature='typing|scroll', version='v1', session='session-1', user=None):
        return self.library.record_episode(dict(episode_id=eid, pattern=signature,
            detector_version=version, effective_seconds=value, session=session,
            started_at='2026-10-14T00:00:00+00:00', ended_at='2026-10-14T00:10:00+00:00'),
            scope={'user': user or self.scope['user']})

    def baseline(self, **kwargs):
        return self.library.episode_baseline('typing|scroll', scope=self.scope, detector_version='v1', **kwargs)

    def test_baseline_uses_prior_matching_version_scope_and_real_sessions(self):
        self.episode('a', value=0)
        self.episode('b', value=60, session='session-2')
        self.episode('other-version', version='v2')
        self.episode('other-signature', signature='copy|paste')
        self.episode('other-user', user='other-user')
        self.episode('no-session', session=None)
        self.episode('blank-session', session='   ')
        values = self.baseline()
        self.assertEqual(values, [{'value': 60., 'session': 'session-2'}, {'value': 0., 'session': 'session-1'}])
        self.assertEqual(len(self.baseline(limit=1)), 1)
        self.assertTrue(all(set(item) == {'value', 'session'} for item in values))

    def test_baseline_filters_invalid_legacy_values_before_applying_limit(self):
        self.episode('a-valid')
        bad_values = [-1, float('inf'), -float('inf'), None, 'unknown', 900]
        with self.library._connection() as db:
            for index, value in enumerate(bad_values):
                db.execute('INSERT INTO episodes(scope_user,episode_id,session,started_at,ended_at,'
                    'effective_seconds,pattern,detector_version) VALUES(?,?,?,?,?,?,?,?)',
                    (self.scope['user'], f'z-invalid-{index}', 's-real', '2026-10-14T00:00:00+00:00',
                     '2026-10-14T00:10:00+00:00', value, 'typing|scroll', 'v1'))
        self.assertEqual(self.baseline(limit=1), [{'value': 30., 'session': 'session-1'}])
        self.assertTrue(all(math.isfinite(r['value']) for r in self.baseline()))

    def test_current_sample_is_kept_out_of_prior_anomaly_baseline(self):
        for index in range(20):
            self.episode(f'ep-{index:02}', value=20 + index, session=f's-{index % 3}')
        before = self.baseline()
        self.assertEqual(len(before), 20)
        self.assertIsNotNone(robust_anomaly(before, 500))
        self.episode('current', value=500)
        self.assertEqual(self.baseline(exclude_episode_id='current'), before)
        self.assertEqual(len(self.baseline()), 21)

    def test_baseline_and_support_queries_enforce_bounds(self):
        for limit in (0, 201, True, 1.5):
            with self.assertRaises(ValueError): self.baseline(limit=limit)
        for limit in (0, 257, True, 1.5):
            with self.assertRaises(ValueError): self.library.pattern_supports('typing|scroll', scope=self.scope, limit=limit)
        with self.assertRaises(ValueError):
            self.library.episode_baseline('typing|scroll', scope=self.scope, detector_version='')

    def test_supports_are_real_matching_episode_sources_and_bounded(self):
        with self.library._connection() as db:
            for index in range(270):
                db.execute('INSERT INTO episodes(scope_user,episode_id,session,started_at,ended_at,'
                    'effective_seconds,pattern,detector_version) VALUES(?,?,?,?,?,?,?,?)',
                    (self.scope['user'], f'episode-{index:03}-' + 'x'*80, 's1', '2026-10-14T00:00:00+00:00',
                     '2026-10-14T00:10:00+00:00', 30, 'typing|scroll', 'v1'))
        self.episode('other-signature', signature='copy|paste')
        self.episode('other-user', user='other-user')
        sources = self.library.pattern_supports('typing|scroll', scope=self.scope)
        self.assertEqual(len(sources), 256)
        self.assertEqual(len(self.library.pattern_supports('typing|scroll', scope=self.scope, limit=2)), 2)
        self.library.promote_pattern('typing|scroll', scope=self.scope, derived_version='v1', supports=sources)
        stored = self.library.export(scope=self.scope)['patterns'][0]
        self.assertEqual(json.loads(stored['supports']), sources)
        self.assertEqual(stored['sample_count'], 256)
        self.assertEqual(stored['active'], 0)
        self.assertEqual(len(self.baseline()), 200)

    def test_promotion_rejects_forged_cross_scope_and_wrong_signature_sources(self):
        self.episode('real')
        self.episode('other-pattern', signature='copy|paste')
        self.episode('private', user='other-user')
        for sources in (['missing'], ['other-pattern'], ['private'], [{'episodes': 999}]):
            with self.assertRaises(ValueError):
                self.library.promote_pattern('typing|scroll', scope=self.scope, derived_version='v1', supports=sources)
        self.library.promote_pattern('typing|scroll', scope=self.scope, derived_version='v1')
        self.assertEqual(json.loads(self.library.export(scope=self.scope)['patterns'][0]['supports']), ['real'])

    def test_promotion_refreshes_existing_legacy_candidate_with_actual_sources(self):
        self.episode('first')
        promoted = self.library.promote_pattern('typing|scroll', scope=self.scope, derived_version='v1')
        with self.library._connection() as db:
            db.execute('UPDATE patterns SET supports=? WHERE pattern_id=?',
                       (json.dumps([{'episodes': 999}]), promoted['pattern_id']))
        self.episode('second')
        updated = self.library.promote_pattern('typing|scroll', scope=self.scope, derived_version='v1')
        self.assertEqual(updated['status'], 'updated')
        pattern = self.library.export(scope=self.scope)['patterns'][0]
        self.assertEqual(json.loads(pattern['supports']), ['second', 'first'])
        self.assertEqual(pattern['sample_count'], 2)
        self.assertEqual(pattern['active'], 0)

    def configure(self, enabled):
        self.library.configure({'enabled': enabled}, revision=self.library.status()['revision'])

    def test_disabled_recording_blocks_new_observations_and_learning_after_restart(self):
        self.configure(False)
        self.library = BehaviorLibrary(self.database)
        identity = dict(user_scope=self.scope['user'], worker_epoch=1, foreground_epoch=1, focus_epoch=1, window_instance=1)
        frame = FrameAggregator(identity=identity, observed_from='100', sequence=1).seal('101')
        writes = [lambda: self.library.observe({'event_id': 'e', 'kind': 'revisit', 'source': 'test'}, scope=self.scope),
            lambda: self.library.record_frames([frame], scope=self.scope), lambda: self.episode('ep'),
            lambda: self.library.record_progress('material', 2, source='test', scope=self.scope),
            lambda: self.library.record_prompt('revisit', scope=self.scope),
            lambda: self.library.promote_pattern('typing|scroll', scope=self.scope, derived_version='v1')]
        for write in writes:
            with self.assertRaises(RecordingDisabled): write()
        exported = self.library.export(scope=self.scope)
        for table in ('events', 'frames', 'episodes', 'progress', 'prompts', 'patterns'):
            self.assertEqual(exported[table], [])
        self.configure(True)
        self.episode('resumed')
        self.assertEqual(self.library.pattern_supports('typing|scroll', scope=self.scope), ['resumed'])

    def test_disabled_recording_allows_pending_reply_correction_and_data_governance(self):
        prompt = self.library.record_prompt('revisit', scope=self.scope)
        pending = self.library.record_prompt('revisit', scope=self.scope)
        self.configure(False)
        self.library.feedback({'feedback_id': 'f1', 'user_event_id': 'host1', 'prompt_id': prompt['prompt_id'],
            'verdict': 'confirm', 'label': '找公式'}, scope=self.scope)
        self.library.correct('f1', '比较定义', scope=self.scope, revision=self.library.status()['revision'])
        self.library.mute_kind('revisit', scope=self.scope)
        self.library.set_prompt_state(pending['prompt_id'], 'dismissed', scope=self.scope)
        self.library.expire_pending_prompts(scope=self.scope)
        self.assertEqual(self.library.habit_summaries(scope=self.scope)[0]['label'], '比较定义')
        self.assertEqual(self.library.export(scope=self.scope)['feedback'][0]['verdict'], 'correct')
        self.library.delete_records(scope=self.scope, all_records=True, confirmed=True, revision=self.library.status()['revision'])
        self.assertEqual(self.library.habit_summaries(scope=self.scope), [])


if __name__ == '__main__':
    unittest.main()
