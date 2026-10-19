"""Activity domain regressions, isolated stores and fake clocks only."""
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from extensions.behavior.library import BehaviorLibrary


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'behavior.sqlite3'
        self.now = datetime(2026, 10, 17, 10, tzinfo=timezone.utc).timestamp()
        self.library = BehaviorLibrary(self.path, clock=lambda: self.now)
        self.scope = {'user': 'user-project', 'session': 'session-1'}

    def declare(self, label='画画', polarity='positive', **kw):
        return self.library.declare({'type': 'interest', 'label': label, 'polarity': polarity},
            scope=self.scope, revision=self.library.status()['revision'], **kw)

    def slice(self, eid, start=None, seconds=10, app='reader.exe', switches=0):
        start = self.now if start is None else start
        local = datetime.fromtimestamp(start).astimezone()
        return {'event_id': eid, 'kind': 'app_focus', 'source': 'foreground-v1', 'features': {
            'slice_version': 1, 'started_at': datetime.fromtimestamp(start, timezone.utc).isoformat(),
            'ended_at': datetime.fromtimestamp(start + seconds, timezone.utc).isoformat(),
            'effective_seconds': seconds, 'app_name': app, 'profile_id': 'study',
            'local_date': local.strftime('%Y-%m-%d'), 'local_hour': local.hour,
            'utc_offset_minutes': int(local.utcoffset().total_seconds() / 60),
            'quality': 'verified_foreground', 'switch_count': switches}}

    def test_declaration_correction_restart_and_delete(self):
        eid = self.declare()['event_id']
        self.declare(polarity='negative', event_id=eid)
        lib = BehaviorLibrary(self.path)
        records = lib.declarations(scope=self.scope)['records']
        self.assertEqual([(r['polarity'], r['version']) for r in records], [('negative', 2)])
        self.assertFalse(records[0]['inferred'])
        lib.forget_declaration(eid, scope=self.scope, revision=lib.status()['revision'])
        self.assertEqual(lib.declarations(scope=self.scope)['records'], [])

    def test_declaration_revision_and_role_isolation(self):
        self.declare(role_id='role-a')
        self.assertEqual(self.library.declarations(scope=self.scope)['records'], [])
        self.assertEqual(self.library.declarations(scope=self.scope, role_id='role-b')['records'], [])
        self.assertEqual(len(self.library.declarations(scope=self.scope, role_id='role-a')['records']), 1)
        with self.assertRaises(ValueError):
            self.library.declare({'type': 'interest', 'label': '游泳'}, scope=self.scope, revision=0)
        with self.assertRaises(ValueError):
            self.library.observe({'event_id': 'forged', 'kind': 'note', 'source': 'user-declaration-v1',
                                  'features': {'label': '助手猜的偏好'}}, scope=self.scope)

    def test_normalized_duplicate_is_idempotent_and_conflict_requires_edit(self):
        eid = self.declare('ＡＩ')['event_id']
        self.assertEqual(self.library.declarations(scope=self.scope)['records'][0]['label'], 'ＡＩ')
        self.assertEqual(self.declare('AI')['event_id'], eid)
        with self.assertRaises(ValueError):
            self.declare('AI', 'negative')

    def test_summaries_do_not_count_episodes_and_deletion_removes_statistics(self):
        self.library.observe(self.slice('a'), scope=self.scope)
        self.library.observe(self.slice('b', app='editor.exe', seconds=20, switches=1), scope=self.scope)
        self.library.record_episode({'episode_id': 'ep', 'pattern': 'a|b', 'session': 'session-1',
            'started_at': '2026-10-17T00:00:00+00:00', 'ended_at': '2026-10-17T00:01:00+00:00',
            'effective_seconds': 60}, scope=self.scope)
        summary = self.library.daily_summary(scope=self.scope)
        self.assertEqual(summary['effective_seconds'], 30)
        self.assertEqual(summary['switch_count'], 1)
        self.assertEqual(self.library.daily_summary(scope={'user': 'another'})['effective_seconds'], 0)
        self.library.delete_records(scope=self.scope, all_records=True, confirmed=True,
                                    revision=self.library.status()['revision'])
        self.assertEqual(self.library.daily_summary(scope=self.scope)['effective_seconds'], 0)

    def test_repeated_activity_is_inferred_and_not_an_interest(self):
        for day in range(3):
            self.library.observe(self.slice(str(day), self.now - day*86400), scope=self.scope)
        overview = self.library.activity_overview(scope=self.scope)
        self.assertEqual(overview['activity_affinity'][0]['day_count'], 3)
        self.assertEqual(overview['activity_affinity'][0]['status'], 'inferred')
        self.assertEqual(self.library.declarations(scope=self.scope)['records'], [])

    def test_closed_payloads_and_bounded_layer_queries(self):
        bad = self.slice('bad');bad['features']['effective_seconds'] = float('nan')
        with self.assertRaises(ValueError):
            self.library.observe(bad, scope=self.scope)
        bad = self.slice('bad');bad['features']['window_title'] = 'private'
        with self.assertRaises(ValueError):
            self.library.observe(bad, scope=self.scope)
        for i in range(4):
            self.library.observe(self.slice(str(i)), scope=self.scope)
        first = self.library.list_layer('events', scope=self.scope, limit=2)
        second = self.library.list_layer('events', scope=self.scope, limit=2, cursor=first['next_cursor'])
        self.assertEqual(len(first['records']) + len(second['records']), 4)
        self.assertFalse({r['event_id'] for r in first['records']} & {r['event_id'] for r in second['records']})
        with self.assertRaises(ValueError):
            self.library.list_layer('management', scope=self.scope)

    def feedback(self, identity, label, app='reader.exe', profile='study', session='session-1'):
        scope = {**self.scope, 'session': session}
        self.library.observe({'event_id': identity, 'kind': 'revisit', 'source': 'reading-tracker',
            'features': {'app_name': app, 'profile_id': profile}}, scope=scope)
        prompt = self.library.record_prompt('revisit', scope=scope, event_id=identity)
        self.library.feedback({'feedback_id': 'f-'+identity, 'user_event_id': 'u-'+identity,
            'prompt_id': prompt['prompt_id'], 'verdict': 'confirm', 'label': label}, scope=scope)

    def test_context_matched_support_correction_and_forgetting(self):
        for i in range(3):
            self.feedback(str(i), '比较定义', session='session-'+str(i%2))
        self.feedback('other', '找道具', app='game.exe', profile='game')
        query = {'kind': 'revisit', 'app_name': 'reader.exe', 'profile_id': 'study'}
        results = self.library.habit_summaries(scope=self.scope, query=query)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['stable'])
        self.assertEqual(results[0]['support_ratio'], 1)
        self.library.correct('f-0', '找公式', scope=self.scope, revision=self.library.status()['revision'])
        results = self.library.habit_summaries(scope=self.scope, query=query)
        self.assertEqual(results[0]['sample_count'], 2)
        self.assertFalse(results[0]['stable'])
        self.library.forget_feedback('f-0', scope=self.scope, revision=self.library.status()['revision'])
        self.assertNotIn('找公式', json.dumps(self.library.habit_summaries(scope=self.scope, query=query), ensure_ascii=False))
        # No current activity => no global historical guesses injected.
        self.assertFalse(any(r.get('label') for r in self.library.context(scope=self.scope)))

    def test_legacy_evidence_never_manufactures_stable_current_intent(self):
        self.library.observe({'event_id': 'old', 'kind': 'revisit', 'source': 'old'}, scope=self.scope)
        p = self.library.record_prompt('revisit', scope=self.scope, event_id='old')
        self.library.feedback({'feedback_id': 'f', 'user_event_id': 'u', 'prompt_id': p['prompt_id'],
                               'verdict': 'confirm', 'label': '旧解释'}, scope=self.scope)
        self.assertEqual(self.library.habit_summaries(scope=self.scope,
            query={'kind': 'revisit', 'app_name': 'reader.exe', 'profile_id': 'study'}), [])

    def test_input_totals_deduplicate_frames_and_keep_quality(self):
        from extensions.behavior.input_features import FrameAggregator
        agg = FrameAggregator(identity={'user_scope': self.scope['user'], 'worker_epoch': 1,
            'foreground_epoch': 1, 'focus_epoch': 1, 'window_instance': 1},
            observed_from='1', sequence=0)
        agg.key(0x41, 1.1);agg.key(0x42, 1.2);agg.click('left', .2, .2)
        frame = agg.seal('2')
        frame['received_at'] = datetime.fromtimestamp(self.now, timezone.utc).isoformat()
        self.library.record_frames([frame], scope=self.scope)
        self.library.record_frames([frame], scope=self.scope)
        data = self.library.activity_overview(scope=self.scope)
        self.assertEqual(data['feature_counts']['key_categories']['text_entry'], 2)
        self.assertEqual(data['feature_counts']['mouse']['left'], 1)
        self.assertEqual(data['input_quality'][0]['frames'], 1)
        self.assertNotIn('grid', data['feature_counts']['mouse'])

    def test_v5_upgrade_backup_retains_activity_and_declarations(self):
        self.library.observe(self.slice('a'), scope=self.scope)
        self.declare()
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute("UPDATE management SET value='5' WHERE key='schema_version'")
        upgraded = BehaviorLibrary(self.path, clock=lambda: self.now)
        self.assertEqual(upgraded.status()['schema_version'], 6)
        backup = self.path.with_name('behavior.sqlite3.schema-v5-backup.sqlite3')
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2)
        self.assertEqual(upgraded.daily_summary(scope=self.scope)['effective_seconds'], 10)
        self.assertEqual(upgraded.declarations(scope=self.scope)['records'][0]['label'], '画画')

    def test_multiple_sequence_rows_cannot_manufacture_independent_samples(self):
        for i in range(3):
            scope = {**self.scope, 'session': 'session-'+str(i)}
            self.library.record_episode({'episode_id': 'base-'+str(i), 'pattern': 'find|scroll',
                'session': scope['session'], 'started_at': '2026-10-17T00:00:00+00:00',
                'ended_at': '2026-10-17T00:01:00+00:00', 'effective_seconds': 30,
                'features': {'base_episode_id': 'one-physical-episode', 'app_name': 'reader.exe',
                             'profile_id': 'study'}, 'detector_version': 'sequence-v1'}, scope=scope)
            prompt = self.library.record_prompt('find|scroll', scope=scope, episode_id='base-'+str(i))
            self.library.feedback({'feedback_id': str(i), 'user_event_id': 'u-'+str(i),
                'prompt_id': prompt['prompt_id'], 'label': '查资料', 'verdict': 'confirm'}, scope=scope)
        results = self.library.habit_summaries(scope=self.scope, query={'kind': 'find|scroll',
            'app_name': 'reader.exe', 'profile_id': 'study', 'detector_version': 'sequence-v1'})
        self.assertEqual(results[0]['sample_count'], 1)
        self.assertFalse(results[0]['stable'])

