import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.repository import message_evidence
from extensions.memory.retrieval import MemoryRetrieval, LocalRetrievalProvider
from extensions.memory.semantic_memory import SemanticMemory


SCOPE = dict(user_id='user', role_id='role')


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.memory = EmbeddedMemory(self.root / 'memory.db')
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.memory.close)

    def test_relation_cas_changes_one_duplicate_and_rejects_stale_or_foreign(self):
        for _ in range(2):
            self.memory.relate('user', 'likes', 'tea', **SCOPE)
        first, second = self.memory.list_relations(**SCOPE)
        fence = self.memory.scope_revision(**SCOPE)
        self.memory.mutate_relation(first['record_id'], expected_revision=first['revision'],
                                    new_object='coffee', **SCOPE)
        self.assertNotEqual(self.memory.scope_revision(**SCOPE), fence)
        self.assertEqual([r['object'] for r in self.memory.list_relations(**SCOPE)], ['coffee', 'tea'])
        for scope, revision in ((SCOPE, first['revision']),
                                ({**SCOPE, 'role_id': 'other'}, first['revision'] + 1)):
            with self.assertRaisesRegex(ValueError, 'revision conflict'):
                self.memory.mutate_relation(first['record_id'], expected_revision=revision,
                                            new_object='bad', **scope)
        before = self.root / 'before-relation-delete.json'
        self.memory.export_json(before, **SCOPE)
        self.memory.mutate_relation(first['record_id'], expected_revision=first['revision'] + 1,
                                    delete=True, **SCOPE)
        self.memory.import_json(before, **SCOPE)
        self.assertEqual([r['record_id'] for r in self.memory.list_relations(**SCOPE)], [second['record_id']])

    def test_relation_cas_failure_rolls_back_revision_and_text(self):
        self.memory.relate('user', 'likes', 'tea', **SCOPE)
        row = self.memory.list_relations(**SCOPE)[0]
        before = self.memory.scope_revision(**SCOPE)
        self.memory.db.execute("CREATE TRIGGER fail_relation BEFORE UPDATE ON relations BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.memory.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.memory.mutate_relation(row['record_id'], expected_revision=row['revision'],
                                        new_object='coffee', **SCOPE)
        self.assertEqual(self.memory.scope_revision(**SCOPE), before)
        self.assertEqual(self.memory.list_relations(**SCOPE), [row])

    def test_scope_fence_persists_is_scoped_and_rolls_back(self):
        before = self.memory.scope_revision(**SCOPE)
        self.memory.add('foreign', user_id='user', role_id='other')
        self.assertEqual(self.memory.scope_revision(**SCOPE), before)
        fact = self.memory.add('tea', **SCOPE)
        changed = self.memory.scope_revision(**SCOPE)
        self.assertNotEqual(changed, before)
        with closing(EmbeddedMemory(self.root / 'memory.db')) as other:
            self.assertEqual(other.scope_revision(**SCOPE), changed)
            with self.assertRaises(RuntimeError):
                with other.db:
                    other.db.execute('UPDATE memories SET text=? WHERE record_id=?', ('rolled back', fact['record_id']))
                    raise RuntimeError('abort')
            self.assertEqual(other.scope_revision(**SCOPE), changed)
            other.forget_record(fact['record_id'], **SCOPE)
            self.assertNotEqual(self.memory.scope_revision(**SCOPE), changed)

    def test_evidence_retraction_invalidates_dependencies_without_deleting_independent_facts(self):
        refs = message_evidence('material-1')
        dependent = self.memory.add('tea', evidence=refs, **SCOPE)
        composite = self.memory.add('tea and routine', evidence=refs + message_evidence('material-2'), **SCOPE)
        independent = self.memory.add('tea independent', evidence=message_evidence('material-2'), **SCOPE)
        foreign = self.memory.add('tea other role', evidence=refs, user_id='user', role_id='other')
        self.memory.put_proposal(event_id='proposal', text='tea', quote='tea', message_id='material-1', **SCOPE)
        before = self.root / 'before-retraction.json'
        self.memory.export_json(before, **SCOPE)
        old_revision = self.memory.scope_revision(**SCOPE)
        result = self.memory.retract_evidence(refs, expected_scope_revision=old_revision, **SCOPE)
        self.assertEqual(set(result['invalidated_record_ids']), {dependent['record_id'], composite['record_id']})
        self.assertEqual(result['rejected_proposal_events'], ['proposal'])
        self.assertFalse(result['material_deleted'])
        self.assertEqual([r['record_id'] for r in self.memory.list_records(**SCOPE)], [independent['record_id']])
        self.assertTrue(self.memory.get_record(foreign['record_id'], user_id='user', role_id='other')['active'])
        with self.assertRaisesRegex(ValueError, 'scope revision conflict'):
            self.memory.retract_evidence(refs, expected_scope_revision=old_revision, **SCOPE)
        self.memory.import_json(before, **SCOPE)
        self.memory.rebuild_indexes(**SCOPE)
        self.assertEqual([r['record_id'] for r in self.memory.list_records(**SCOPE)], [independent['record_id']])

    def test_evidence_retraction_before_extraction_and_failure_rollback(self):
        refs = message_evidence('in-flight-source')
        result = self.memory.retract_evidence(refs,
            expected_scope_revision=self.memory.scope_revision(**SCOPE), **SCOPE)
        self.assertEqual(result['invalidated_record_ids'], [])
        self.assertEqual(self.memory.add('late fact', evidence=refs, **SCOPE)['status'], 'suppressed')
        self.assertEqual(self.memory.put_proposal(event_id='late', text='late', quote='late',
            message_id='in-flight-source', **SCOPE)['status'], 'suppressed')
        with self.assertRaises(ValueError):
            self.memory.retract_evidence([], expected_scope_revision=self.memory.scope_revision(**SCOPE), **SCOPE)
        fresh_refs = message_evidence('failure-source')
        fact = self.memory.add('fresh fact', evidence=fresh_refs, **SCOPE)
        revision = self.memory.scope_revision(**SCOPE)
        self.memory.db.execute("CREATE TRIGGER fail_retraction BEFORE UPDATE ON memories BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.memory.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.memory.retract_evidence(fresh_refs, expected_scope_revision=revision, **SCOPE)
        self.assertEqual(self.memory.scope_revision(**SCOPE), revision)
        self.assertTrue(self.memory.get_record(fact['record_id'], **SCOPE)['active'])
        self.memory.db.execute('DROP TRIGGER fail_retraction')
        self.memory.db.commit()
        self.assertNotEqual(self.memory.add('another', evidence=fresh_refs, **SCOPE).get('status'), 'suppressed')

    def test_inflight_hydration_discarded_when_another_connection_forgets(self):
        first = self.memory.add('tea first', **SCOPE)
        second = self.memory.add('tea second', **SCOPE)
        original_get = self.memory.get_record
        with closing(EmbeddedMemory(self.root / 'memory.db')) as other:
            def racing_get(identity, **scope):
                record = original_get(identity, **scope)
                if identity == second['record_id']:
                    other.forget_record(first['record_id'], **SCOPE)
                return record
            self.memory.get_record = racing_get
            class OrderedProvider(LocalRetrievalProvider):
                def search(self, query, **kwargs):
                    return [first, second]
            retrieval = MemoryRetrieval(self.memory, OrderedProvider(self.memory))
            self.assertEqual(retrieval.search('tea', **SCOPE), [])

    def test_source_suppression_blocks_rephrased_extraction_and_proposal(self):
        refs = message_evidence('message-1')
        fact = self.memory.add('likes tea', evidence=refs, source='auto-extract', event_id='first', **SCOPE)
        self.memory.put_proposal(event_id='pending', text='tea preference', quote='tea', message_id='message-1', **SCOPE)
        self.assertEqual(self.memory.forget_record(fact['record_id'], user_id='user', role_id='other')['forgotten'], 0)
        self.memory.forget_record(fact['record_id'], expected_revision=1, **SCOPE)
        with self.assertRaises(ValueError):
            self.memory.forget_record(fact['record_id'], expected_revision=1, **SCOPE)
        with self.assertRaises(ValueError):
            self.memory.forget_record(fact['record_id'], expected_revision=True, **SCOPE)
        self.assertEqual(self.memory.add('prefers tea', evidence=refs, event_id='new-index', **SCOPE)['status'], 'suppressed')
        self.assertEqual(self.memory.put_proposal(event_id='new-proposal', text='tea', quote='tea', message_id='message-1', **SCOPE)['status'], 'suppressed')
        self.assertEqual(self.memory.list_proposals(**SCOPE)[0]['status'], 'rejected')
        fresh = self.memory.add('likes tea', evidence=message_evidence('message-2'), **SCOPE)
        self.assertEqual(len(self.memory.search('tea', **SCOPE)), 1)
        self.assertEqual(self.memory.search('tea', **SCOPE)[0]['record_id'], fresh['record_id'])

    def test_external_hits_are_hydrated_scoped_and_version_checked(self):
        fact = self.memory.add('canonical tea', **SCOPE)
        foreign = self.memory.add('private tea', user_id='user', role_id='other')

        class Provider:
            def capabilities(self):
                return LocalRetrievalProvider(None).capabilities()

            def search(self, query, *, scope, source, limit):
                scope['role_id'] = 'other'
                return [dict(foreign, text='fake'), dict(fact, revision=999),
                        dict(fact, text='forged content', source='user-confirmed'), dict(fact)]

        retrieval = MemoryRetrieval(self.memory, Provider())
        result = retrieval.search('tea', **SCOPE)
        self.assertEqual([r['text'] for r in result], ['canonical tea'])
        self.assertEqual(result[0]['source'], 'user')
        self.assertEqual(retrieval.search('tea', source='user-confirmed', **SCOPE), [])
        self.memory.forget_record(fact['record_id'], **SCOPE)
        self.assertEqual(retrieval.search('tea', **SCOPE), [])

    def test_correction_is_scoped_atomic_retryable_and_survives_old_merge(self):
        old = self.memory.add('likes tea', evidence=message_evidence('old-message'),
                              fact_key='drink', **SCOPE)
        snapshot = self.root / 'before-correction.json'
        self.memory.export_json(snapshot, **SCOPE)
        args = dict(expected_revision=1, event_id='correction-1', **SCOPE)
        with self.assertRaises(ValueError):
            self.memory.correct_record(old['record_id'], 'likes coffee',
                **{**args, 'role_id': 'other'})
        with self.assertRaises(ValueError):
            self.memory.correct_record(old['record_id'], 'likes coffee',
                **{**args, 'expected_revision': 2})
        corrected = self.memory.correct_record(old['record_id'], 'likes coffee', **args)
        self.assertEqual(self.memory.get_record(old['record_id'], **SCOPE)['status'], 'superseded')
        retry = self.memory.correct_record(old['record_id'], 'likes coffee', **args)
        self.assertEqual(retry['record_id'], corrected['record_id'])
        self.assertTrue(retry['duplicate'])
        with self.assertRaises(ValueError):
            self.memory.correct_record(old['record_id'], 'likes cocoa', **args)
        self.memory.import_json(snapshot, **SCOPE)
        self.memory.rebuild_indexes(**SCOPE)
        self.assertEqual(self.memory.search('tea', **SCOPE), [])
        self.assertEqual([r['text'] for r in self.memory.search('coffee', **SCOPE)], ['likes coffee'])
        self.assertEqual(self.memory.add('tea again', evidence=message_evidence('old-message'),
            **SCOPE)['status'], 'suppressed')
        self.memory.forget_record(corrected['record_id'], **SCOPE)
        self.assertTrue(self.memory.correct_record(old['record_id'], 'likes coffee', **args)['duplicate'])
        self.assertEqual(self.memory.list_records(**SCOPE), [])

    def test_correction_rolls_back_suppression_and_fact_when_write_fails(self):
        old = self.memory.add('likes tea', evidence=message_evidence('message'), **SCOPE)
        self.memory.db.execute("CREATE TRIGGER fail_correction BEFORE INSERT ON memories BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.memory.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.memory.correct_record(old['record_id'], 'likes coffee',
                expected_revision=1, event_id='correction', **SCOPE)
        self.assertEqual(self.memory.get_record(old['record_id'], **SCOPE)['revision'], 1)
        self.assertEqual(len(self.memory.search('tea', **SCOPE)), 1)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM memory_suppressions').fetchone()[0], 0)

    def test_stable_identity_and_deleted_snapshot_merge_without_event(self):
        original = self.memory.add('eventless tea', **SCOPE)
        active = self.root / 'active.json'
        deleted = self.root / 'deleted.json'
        self.memory.export_json(active, **SCOPE)
        self.memory.forget_record(original['record_id'], **SCOPE)
        self.memory.export_json(deleted, **SCOPE)
        other = EmbeddedMemory(self.root / 'other.db')
        self.addCleanup(other.close)
        other.import_json(active, **SCOPE)
        self.assertEqual(other.list_records(**SCOPE)[0]['record_id'], original['record_id'])
        other.import_json(deleted, **SCOPE)
        other.import_json(active, **SCOPE)
        self.assertEqual(other.search('tea', **SCOPE), [])
        revision = other.get_record(original['record_id'], **SCOPE)['revision']
        other.restore_json(active, **SCOPE)
        self.assertGreater(other.list_records(**SCOPE)[0]['revision'], revision)

    def test_proposal_confirmation_is_atomic_on_update_failure(self):
        self.memory.put_proposal(event_id='proposal', text='tea', **SCOPE)
        self.memory.db.execute("CREATE TRIGGER fail_proposal BEFORE UPDATE ON memory_proposals BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.memory.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.memory.resolve_proposal('proposal', True, **SCOPE)
        self.assertEqual(self.memory.list_records(**SCOPE), [])
        self.assertEqual(self.memory.list_proposals(**SCOPE)[0]['status'], 'pending')

    def test_rebuild_indexes_keeps_canonical_state_and_forgetting(self):
        self.memory.add('active tea', **SCOPE)
        fact = self.memory.add('forgotten tea', **SCOPE)
        self.memory.forget_record(fact['record_id'], **SCOPE)
        before = self.memory.list_records(include_inactive=True, **SCOPE)
        self.memory.db.execute("INSERT INTO memory_fts(memory_fts) VALUES ('delete-all')")
        self.memory.db.commit()
        self.memory.rebuild_indexes(**SCOPE)
        self.assertEqual(self.memory.list_records(include_inactive=True, **SCOPE), before)
        self.assertEqual([r['text'] for r in self.memory.search('tea', **SCOPE)], ['active tea'])
        self.assertEqual(self.memory.db.execute("SELECT rowid FROM memory_fts WHERE memory_fts MATCH 'forgotten'").fetchall(), [])

    def test_legacy_migration_backs_up_and_preserves_identity_across_reopen(self):
        path = self.root / 'legacy.db'
        scope = self.memory.scope_key(**SCOPE)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE memories(id INTEGER PRIMARY KEY,scope TEXT,text TEXT,source TEXT,active INTEGER,created REAL,updated REAL)')
            db.execute('INSERT INTO memories VALUES (1,?,?,?,?,?,?)', (scope, 'legacy tea', 'user', 1, 1., 1.))
        memory = EmbeddedMemory(path)
        try:
            record_id = memory.get_record(1, **SCOPE)['record_id']
        finally:
            memory.close()
        backups = list(self.root.glob('legacy.db.pre-repository-*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertNotIn('record_id', [r[1] for r in db.execute('PRAGMA table_info(memories)')])
        memory = EmbeddedMemory(path)
        try:
            self.assertEqual(memory.get_record(1, **SCOPE)['record_id'], record_id)
        finally:
            memory.close()

    def test_semantic_provider_returns_versioned_hits_without_real_model(self):
        # Exercise actual SemanticMemory.search with a deterministic embedder;
        # this test requires neither downloaded weights nor model services.
        class Embedder:
            def embed(self, texts):
                return iter([[1., 0.] for _ in texts])

            def query_embed(self, text):
                return iter([[1., 0.]])

        memory = SemanticMemory.__new__(SemanticMemory)
        EmbeddedMemory.__init__(memory, self.root / 'semantic.db')
        self.addCleanup(memory.close)
        memory.embedder, memory.model_id = Embedder(), 'fake-v1'
        memory.threshold, memory.embedding_python = .45, None
        memory.db.execute('CREATE TABLE embeddings(memory_id INTEGER,model TEXT,vector TEXT,PRIMARY KEY(memory_id,model))')
        memory.db.commit()
        fact = memory.add('tea', **SCOPE)
        retrieval = MemoryRetrieval(memory, LocalRetrievalProvider(memory))
        self.assertEqual(retrieval.search('tea', **SCOPE)[0]['record_id'], fact['record_id'])
        memory.forget_record(fact['record_id'], **SCOPE)
        memory.rebuild_indexes(**SCOPE)
        self.assertEqual(retrieval.search('tea', **SCOPE), [])
        self.assertEqual(memory.db.execute('SELECT count(*) FROM embeddings').fetchone()[0], 0)

    def test_old_auto_extract_event_uses_same_message_suppression(self):
        fact = self.memory.add('tea', source='auto-extract', event_id='host-message:0', **SCOPE)
        self.memory.forget_record(fact['record_id'], **SCOPE)
        self.assertEqual(self.memory.add('rephrased tea', evidence=message_evidence('host-message'),
                                        source='auto-extract', event_id='host-message:1', **SCOPE)['status'], 'suppressed')

    def test_semantic_embedding_race_cannot_repopulate_forgotten_cache(self):
        memory = SemanticMemory.__new__(SemanticMemory)
        path = self.root / 'semantic-race.db'
        EmbeddedMemory.__init__(memory, path)
        self.addCleanup(memory.close)
        memory.model_id, memory.threshold, memory.embedding_python = 'fake-v1', .45, None
        memory.db.execute('CREATE TABLE embeddings(memory_id INTEGER,model TEXT,vector TEXT,PRIMARY KEY(memory_id,model))')
        memory.db.commit()
        fact = memory.add('tea', **SCOPE)
        with closing(EmbeddedMemory(path)) as other:
            class RacingEmbedder:
                def embed(self, texts):
                    # Simulate another process deleting during model latency.
                    other.forget_record(fact['record_id'], **SCOPE)
                    return iter([[1., 0.] for _ in texts])

                def query_embed(self, text):
                    return iter([[1., 0.]])
            memory.embedder = RacingEmbedder()
            self.assertEqual(memory.search('tea', **SCOPE), [])
        self.assertEqual(memory.db.execute('SELECT count(*) FROM embeddings').fetchone()[0], 0)

    def test_relations_stable_identity_and_delete_merge(self):
        self.memory.relate('user', 'likes', 'tea', **SCOPE)
        active, deleted = self.root / 'relations.json', self.root / 'relations-deleted.json'
        self.memory.export_json(active, **SCOPE)
        self.memory.delete_relation('user', 'likes', 'tea', **SCOPE)
        self.memory.export_json(deleted, **SCOPE)
        other = EmbeddedMemory(self.root / 'relations.db')
        self.addCleanup(other.close)
        other.import_json(active, **SCOPE)
        other.import_json(deleted, **SCOPE)
        other.import_json(active, **SCOPE)
        self.assertEqual(other.related('user', **SCOPE), [])
        other.restore_json(active, **SCOPE)
        self.assertEqual(other.related('user', **SCOPE)[0]['object'], 'tea')

    def test_newer_snapshot_supersedes_old_fact_without_reviving_history(self):
        first = self.memory.add('tea', fact_key='drink', event_id='old', **SCOPE)
        old, new = self.root / 'before.json', self.root / 'after.json'
        self.memory.export_json(old, **SCOPE)
        self.memory.add('water', fact_key='drink', event_id='new', **SCOPE)
        self.memory.export_json(new, **SCOPE)
        other = EmbeddedMemory(self.root / 'merge.db')
        self.addCleanup(other.close)
        other.import_json(old, **SCOPE)
        other.import_json(new, **SCOPE)
        other.import_json(old, **SCOPE)
        self.assertEqual([r['text'] for r in other.list_records(**SCOPE)], ['water'])
        self.assertEqual(other.get_record(first['record_id'], **SCOPE)['status'], 'superseded')

    def test_disabled_never_calls_provider_or_creates_database(self):
        disabled = EmbeddedMemory(self.root / 'disabled.db', enabled=False)
        self.assertEqual(MemoryRetrieval(disabled, None).search('tea', **SCOPE), [])
        self.assertTrue(disabled.put_proposal(event_id='p', text='tea', **SCOPE)['disabled'])
        self.assertFalse((self.root / 'disabled.db').exists())

    def test_reset_rejects_pending_without_facts_and_blocks_same_old_message(self):
        self.memory.put_proposal(event_id='pending', text='tea', quote='tea', message_id='old-message', **SCOPE)
        self.memory.put_proposal(event_id='foreign', text='water', user_id='user', role_id='other')
        self.memory.reset_scope(**SCOPE)
        self.assertEqual(self.memory.list_proposals(**SCOPE)[0]['status'], 'rejected')
        with self.assertRaises(ValueError):
            self.memory.resolve_proposal('pending', True, **SCOPE)
        self.assertEqual(self.memory.put_proposal(event_id='rephrased', text='prefers tea', quote='tea',
                                                message_id='old-message', **SCOPE)['status'], 'suppressed')
        self.assertEqual(self.memory.list_proposals(user_id='user', role_id='other')[0]['status'], 'pending')

    def test_role_card_reset_does_not_erase_old_forgetting(self):
        fact = self.memory.add('tea', evidence=message_evidence('forgotten-message'), **SCOPE)
        self.memory.forget_record(fact['record_id'], **SCOPE)
        self.memory.add('coffee', evidence=message_evidence('current-message'), **SCOPE)
        self.memory.put_proposal(event_id='pending', text='coffee', quote='coffee', message_id='current-message', **SCOPE)
        self.memory.restore_role_snapshot(['role persona'], **SCOPE)
        self.assertEqual([r['text'] for r in self.memory.list_records(**SCOPE)], ['role persona'])
        for message in ('forgotten-message', 'current-message'):
            self.assertEqual(self.memory.add('rewritten', evidence=message_evidence(message), **SCOPE)['status'], 'suppressed')
        self.assertEqual(self.memory.list_proposals(**SCOPE)[0]['status'], 'rejected')
        self.memory.restore_role_snapshot([], **SCOPE)
        self.assertEqual(self.memory.list_records(**SCOPE), [])
