"""Behavior evidence lifecycle regressions, always using isolated temporary data."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.behavior.library import BehaviorLibrary, CapacityPaused, MigrationActive
from extensions.behavior.locator import BehaviorLocator
from extensions.behavior.input_features import FrameAggregator
from tools.backup_personal_data import backup, restore, verify_snapshot
from ui.data_lease import DataLease


class EvidenceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='behavior-evidence-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = [1800000000.]
        self.scope = {'user': 'user-project', 'session': 'session-1'}
        self.library = BehaviorLibrary(self.root/'behavior.sqlite3', clock=lambda: self.now[0])

    def event(self, eid, kind='revisit'):
        self.library.observe({'event_id': eid, 'kind': kind, 'source': 'test'}, scope=self.scope)

    def episode(self, eid='ep1', event_ids=(), frame_refs=()):
        return self.library.record_episode({'episode_id': eid, 'pattern': 'revisit',
            'session': self.scope['session'], 'started_at': '2026-10-14T00:00:00+00:00',
            'ended_at': '2026-10-14T00:01:00+00:00', 'effective_seconds': 45},
            scope=self.scope, event_ids=list(event_ids), frame_refs=list(frame_refs))

    def reply(self, fid, label='找公式', role_id=None, episode_id=None, event_id=None):
        prompt = self.library.record_prompt('revisit', scope=self.scope, role_id=role_id,
            episode_id=episode_id, event_id=event_id)
        result = self.library.feedback({'feedback_id': fid, 'user_event_id': 'host-' + fid,
            'prompt_id': prompt['prompt_id'], 'verdict': 'confirm', 'label': label}, scope=self.scope)
        return prompt, result

    def delete(self, **selection):
        return self.library.delete_records(scope=self.scope, confirmed=True,
            revision=self.library.status()['revision'], **selection)

    def test_feedback_requires_prompt_host_event_and_explicit_label(self):
        prompt = self.library.record_prompt('revisit', scope=self.scope)
        entry = {'feedback_id': 'f1', 'user_event_id': 'host1',
            'prompt_id': prompt['prompt_id'], 'verdict': 'confirm', 'label': '找公式'}
        for field in ('user_event_id', 'prompt_id', 'label'):
            bad = dict(entry); bad.pop(field)
            with self.assertRaises(ValueError): self.library.feedback(bad, scope=self.scope)
        # Assistant/proposed wording cannot become a user label.
        bad = dict(entry); bad.pop('label'); bad['original'] = 'assistant proposal'
        with self.assertRaises(ValueError): self.library.feedback(bad, scope=self.scope)
        self.assertEqual(self.library.habit_summaries(scope=self.scope), [])

    def test_feedback_derives_associations_and_rejects_forgery(self):
        self.event('e1'); self.episode(event_ids=['e1'])
        prompt = self.library.record_prompt('revisit', scope=self.scope,
            event_id='e1', episode_id='ep1', role_id='role-a')
        entry = {'feedback_id': 'f1', 'user_event_id': 'host1', 'prompt_id': prompt['prompt_id'],
            'verdict': 'confirm', 'label': '找公式'}
        with self.assertRaises(ValueError):
            self.library.feedback(dict(entry, event_id='forged'), scope=self.scope)
        result = self.library.feedback(entry, scope=self.scope)
        self.assertEqual((result['event_id'], result['episode_id'], result['kind'], result['role_id']),
            ('e1', 'ep1', 'revisit', 'role-a'))
        self.assertEqual(self.library.feedback(entry, scope=self.scope)['status'], 'duplicate')
        with self.assertRaises(ValueError): self.library.feedback(dict(entry, label='different'), scope=self.scope)
        with self.assertRaises(ValueError): self.library.feedback(dict(entry, feedback_id='f2'), scope=self.scope)

    def test_expired_and_cross_session_prompt_cannot_confirm(self):
        prompt = self.library.record_prompt('revisit', scope=self.scope)
        entry = {'feedback_id': 'f1', 'user_event_id': 'host1', 'prompt_id': prompt['prompt_id'],
            'verdict': 'confirm', 'corrected': '比较定义'}
        with self.assertRaises(ValueError): self.library.feedback(entry, scope=dict(self.scope, session='other'))
        self.now[0] += 120
        with self.assertRaisesRegex(ValueError, 'expired'): self.library.feedback(entry, scope=self.scope)
        self.assertEqual(self.library.export(scope=self.scope)['prompts'][0]['state'], 'expired')
        self.assertEqual(self.library.habit_summaries(scope=self.scope), [])

    def test_roles_share_general_labels_and_isolate_interactions(self):
        self.reply('general', label='通用习惯')
        self.reply('private', label='角色私有习惯', role_id='role-a')
        a = self.library.habit_summaries(scope=self.scope, role_id='role-a')
        b = self.library.habit_summaries(scope=self.scope, role_id='role-b')
        self.assertEqual({r['label'] for r in a}, {'通用习惯', '角色私有习惯'})
        self.assertEqual({r['label'] for r in b}, {'通用习惯'})
        self.assertEqual({r['label'] for r in self.library.habit_summaries(scope=self.scope)}, {'通用习惯'})

    def test_confirmation_survives_restart_and_correction_forgets_old_label(self):
        self.event('e1'); self.episode(event_ids=['e1'])
        self.library.promote_pattern('revisit', scope=self.scope, derived_version='v1', supports=['ep1'])
        self.assertEqual(self.library.confirmed_patterns(scope=self.scope), [])
        self.reply('f1', episode_id='ep1', event_id='e1')
        self.assertEqual(self.library.confirmed_patterns(scope=self.scope), ['revisit'])
        reopened = BehaviorLibrary(self.root/'behavior.sqlite3', clock=lambda: self.now[0])
        self.assertEqual(reopened.context(scope=self.scope, query={'kind': 'revisit'})[0]['label'], '找公式')
        reopened.correct('f1', '比较定义', scope=self.scope, revision=reopened.status()['revision'])
        summaries = reopened.habit_summaries(scope=self.scope)
        self.assertEqual([r['label'] for r in summaries], ['比较定义'])
        self.assertTrue(summaries[0]['confirmed']); self.assertTrue(summaries[0]['inferred'])
        self.assertNotIn('找公式', json.dumps(reopened.context(scope=self.scope), ensure_ascii=False))

    def test_selective_delete_removes_all_dependent_layers_and_retains_other_evidence(self):
        self.event('e1'); self.event('e2', kind='long_dwell')
        identity = dict(user_scope=self.scope['user'], worker_epoch=1, foreground_epoch=1, focus_epoch=1, window_instance=1)
        frame = FrameAggregator(identity=identity, observed_from='100', sequence=1).seal('101')
        self.library.record_frames([frame], scope=self.scope)
        self.episode(event_ids=['e1'], frame_refs=[(1, 1)])
        self.library.promote_pattern('revisit', scope=self.scope, derived_version='v1', supports=['ep1'])
        self.reply('f1', episode_id='ep1', event_id='e1')
        self.library.record_progress('file-id', 3, source='test', scope=self.scope,
            event_id='e1', episode_id='ep1', kind='revisit')
        self.library.record_progress('other-file', 7, source='test', scope=self.scope,
            event_id='e2', kind='long_dwell')
        self.reply('f2', label='另一个习惯', event_id='e2')
        result = self.delete(event_ids=['e1'])
        exported = self.library.export(scope=self.scope)
        for table in ('episodes', 'frames', 'patterns'):
            self.assertEqual(exported[table], [], table)
        self.assertEqual([r['event_id'] for r in exported['events']], ['e2'])
        self.assertEqual([r['event_id'] for r in exported['progress']], ['e2'])
        self.assertEqual([r['feedback_id'] for r in exported['feedback']], ['f2'])
        self.assertEqual(len(exported['prompts']), 1)
        self.assertEqual(result['deleted_frames'], 1)
        self.assertEqual([r['label'] for r in self.library.habit_summaries(scope=self.scope)], ['另一个习惯'])

    def test_delete_all_covers_all_sessions_and_empty_event_layers(self):
        self.reply('f1')
        self.scope['session'] = 'session-2'
        self.episode('ep2')
        self.library.record_progress('file', 3, source='test', scope=self.scope)
        self.delete(all_records=True)
        for key, value in self.library.export(scope=self.scope).items():
            if isinstance(value, list): self.assertEqual(value, [], key)
        self.assertGreater(self.library.status()['behavior_epoch'], 1)

    def test_before_and_kind_deletion_cleans_prompt_without_event(self):
        self.reply('f1')
        self.delete(kinds=['revisit'])
        self.assertEqual(self.library.habit_summaries(scope=self.scope), [])
        self.assertEqual(self.library.export(scope=self.scope)['prompts'], [])
        self.reply('f2')
        self.delete(before='2035-01-01T00:00:00+00:00')
        self.assertEqual(self.library.export(scope=self.scope)['feedback'], [])

    def test_episode_replay_conflict_and_invalid_closure(self):
        self.episode()
        self.assertEqual(self.episode()['status'], 'duplicate')
        with self.assertRaises(ValueError): self.episode(event_ids=['missing'])
        bad = dict(episode_id='bad', pattern='revisit', session='session-1',
            started_at='2026-10-14T00:02:00+00:00', ended_at='2026-10-14T00:01:00+00:00')
        with self.assertRaises(ValueError): self.library.record_episode(bad, scope=self.scope)

    def test_every_learning_write_obeys_persisted_pause_and_migration(self):
        for key, exception in (('capacity_paused', CapacityPaused), ('migration_active', MigrationActive)):
            with self.library._connection() as db:
                db.execute('INSERT INTO management(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, '1'))
            writes = [lambda: self.event('e'), lambda: self.episode(),
                lambda: self.library.record_prompt('revisit', scope=self.scope),
                lambda: self.library.record_progress('id', 1, source='test', scope=self.scope),
                lambda: self.library.promote_pattern('sig', scope=self.scope, derived_version='v1'),
                lambda: self.library.mute_kind('revisit', scope=self.scope)]
            for write in writes:
                with self.assertRaises(exception): write()
            with self.library._connection() as db: db.execute('DELETE FROM management WHERE key=?', (key,))

    def test_capacity_guard_uses_free_space_instead_of_used_bytes(self):
        import shutil
        disk = shutil._ntuple_diskusage(total=20 * 1024**3, used=1, free=19 * 1024**3)
        self.library._capacity_checked_at = None
        with patch('extensions.behavior.library.shutil.disk_usage', return_value=disk):
            self.event('e1')
            self.assertEqual(self.library.status()['capacity']['free_bytes'], disk.free)
            self.assertFalse(self.library.status()['capacity']['paused'])

    def test_legacy_scope_adoption_is_atomic_isolated_and_idempotent(self):
        self.event('e1'); self.reply('f1', event_id='e1')
        target = dict(self.scope, user='new-user-project')
        result = self.library.migrate_legacy_scope(self.scope['user'], scope=target)
        self.assertGreater(result['records'], 0)
        self.assertEqual(self.library.habit_summaries(scope=self.scope), [])
        self.assertEqual(self.library.habit_summaries(scope=target)[0]['label'], '找公式')
        self.assertTrue(self.library.migrate_legacy_scope(self.scope['user'], scope=target)['idempotent'])
        with self.assertRaises(ValueError): self.library.migrate_legacy_scope(self.scope['user'], scope=dict(target, user='different'))

    def test_export_includes_all_layers_without_material_secret(self):
        self.event('e1'); self.episode(event_ids=['e1']); self.reply('f1', event_id='e1', episode_id='ep1')
        self.library.record_progress('raw-private-material', 3, source='test', scope=self.scope)
        self.library.promote_pattern('revisit', scope=self.scope, derived_version='v1', supports=['ep1'])
        exported = self.library.export(scope=self.scope)
        self.assertTrue(set(('events', 'episodes', 'frames', 'prompts', 'feedback', 'patterns', 'progress', 'management')) <= set(exported))
        with self.library._connection() as db: key = self.library._meta(db, 'material_hmac_key')
        encoded = json.dumps(exported)
        self.assertNotIn(key, encoded)
        self.assertNotIn('raw-private-material', encoded)


class StorageLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='behavior-roots-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.personal = self.root/'personal'; self.personal.mkdir()
        self.locator = BehaviorLocator(self.personal)
        self.library = BehaviorLibrary(self.locator.resolve()/'behavior.sqlite3', locator=self.locator)

    def test_migration_preserves_permission_quota_and_allows_new_records(self):
        permission = self.locator.resolve()/'permission.json'; permission.write_text('{"paused":true}')
        self.library.record_prompt('revisit', scope={'user': 'u'}, quota={'day': 'd', 'count': 3, 'last_at': 1})
        destination = self.root/'external'
        self.library.migrate(destination, locator=self.locator, confirmed=True)
        self.assertEqual((destination/'permission.json').read_bytes(), permission.read_bytes())
        fresh = BehaviorLibrary(destination/'behavior.sqlite3', locator=self.locator)
        self.assertFalse(fresh.status()['capacity']['migration_active'])
        self.assertEqual(fresh.prompt_quota(scope={'user': 'u'})['count'], 3)
        fresh.record_prompt('revisit', scope={'user': 'u'})

    def test_failed_source_lease_keeps_source_writable_and_locator(self):
        held = self.locator.lease().acquire()
        try:
            with self.assertRaises(OSError): self.library.migrate(self.root/'external', locator=self.locator, confirmed=True)
        finally: held.release()
        self.assertFalse(self.library.status()['capacity']['migration_active'])
        self.assertEqual(self.locator.resolve(), self.personal/'behavior')
        self.library.record_prompt('revisit', scope={'user': 'u'})

    def test_failure_before_locator_commit_preserves_live_source_and_assets(self):
        permission = self.locator.resolve()/'permission.json'
        permission.write_text('{"startup_resume":true}')
        with patch.object(self.locator, '_commit_selection', side_effect=OSError('commit failed')):
            with self.assertRaises(OSError):
                self.library.migrate(self.root/'external', locator=self.locator, confirmed=True)
        self.assertEqual(self.locator.resolve(), self.personal/'behavior')
        self.assertFalse(self.library.status()['capacity']['migration_active'])
        self.assertEqual(permission.read_text(), '{"startup_resume":true}')
        self.library.record_prompt('revisit', scope={'user': 'u'})

    def test_locator_switch_holds_source_and_target_leases(self):
        original = self.locator._commit_selection
        def commit(destination):
            for root in (self.personal/'behavior', destination):
                with self.assertRaises(OSError): self.locator.lease(root).acquire()
            return original(destination)
        with patch.object(self.locator, '_commit_selection', side_effect=commit):
            self.library.migrate(self.root/'external', locator=self.locator, confirmed=True)

    def test_backup_discovers_external_root_and_restores_fresh_locator(self):
        self.library.migrate(self.root/'external', locator=self.locator, confirmed=True)
        snapshot = self.root/'snapshot'
        backup(self.personal, snapshot)
        self.assertEqual(verify_snapshot(snapshot)['schema_version'], 2)
        restored = self.root/'restored'; restore(snapshot, restored)
        rebound = BehaviorLocator(restored)
        self.assertEqual(rebound.resolve(), restored/'behavior')
        BehaviorLibrary(rebound.resolve()/'behavior.sqlite3', locator=rebound)
        self.assertTrue(any(restored.glob('behavior-retained-*')))

    def test_missing_external_root_fails_before_creating_destination(self):
        locator = self.personal/'behavior-locator.json'
        missing = self.root/'missing'
        locator.write_text(json.dumps(dict(schema_version=1, root=str(missing), owner_id='owner')))
        with self.assertRaises(ValueError): backup(self.personal, self.root/'snapshot')
        self.assertFalse(missing.exists()); self.assertFalse((self.root/'snapshot').exists())

    def test_external_writer_failure_releases_personal_lease(self):
        self.library.migrate(self.root/'external', locator=self.locator, confirmed=True)
        held = self.locator.lease().acquire()
        try:
            with self.assertRaises(OSError): backup(self.personal, self.root/'snapshot')
        finally: held.release()
        held = DataLease(self.personal).acquire(); held.release()
        self.assertFalse((self.root/'snapshot').exists())

    def test_schema_upgrade_keeps_backup_and_existing_management(self):
        database = Path(self.library._database)
        with self.library._connection() as db:
            db.execute("UPDATE management SET value='4' WHERE key='schema_version'")
            db.execute("INSERT INTO management(key,value) VALUES('permission-revision','7')")
        fresh = BehaviorLibrary(database)
        self.assertEqual(fresh.status()['schema_version'], 6)
        with fresh._connection() as db:
            self.assertEqual(fresh._meta(db, 'permission-revision'), '7')
        previous = sqlite3.connect(str(database) + '.schema-v4-backup.sqlite3')
        try:
            self.assertEqual(previous.execute("SELECT value FROM management WHERE key='schema_version'").fetchone()[0], '4')
        finally: previous.close()


if __name__ == '__main__':
    unittest.main()
