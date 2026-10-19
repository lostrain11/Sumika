import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.repository import message_evidence
from extensions.models.settings import example, save
from extensions.roles.conversations import Conversations
from extensions.roles.material_purge import purge_material
from extensions.roles.roles import import_card
from ui.data_lease import DataLease


class MaterialPurgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path('.sumika-next'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        card = self.root / 'card.json'
        card.write_text(json.dumps({'spec': 'chara_card_v2', 'data': {
            'name': 'Fixture', 'description': 'Synthetic'}}), encoding='utf8')
        role = import_card(card, self.root / 'roles', 'fixture')
        self.settings = self.root / 'settings.json'
        self.database = self.root / 'memory.sqlite3'
        save(example(role, self.database), self.settings)
        self.scope = dict(user_id='local-user', role_id='fixture', project_id='sumika')
        self.store = Conversations(self.root / 'role-conversations.sqlite3')
        self.chat_scope = self.store.scope_for('local-user', str(role), 'sumika')
        self.secret = 'PURGE_ONLY_SECRET_83abe721'
        self.turn = self.store.begin(self.chat_scope, 'room-fixture', self.secret)
        self.message = self.turn + ':user'
        self.store.complete(self.turn, {'text': 'reply ' + self.secret})
        draft = self.store.prepare('local-user', self.chat_scope, self.message)
        self.store.receive_handoff('local-user', draft['id'], {'reference': self.secret})
        self.other = self.store.begin('foreign', 'room-fixture', 'foreign material')
        with_memory = EmbeddedMemory(self.database)
        try:
            self.record = with_memory.add(self.secret, source='auto-extract',
                event_id=self.message + ':0', evidence=message_evidence(self.message), **self.scope)
            with_memory.put_proposal(event_id=self.message + ':proposal:0', text=self.secret,
                quote=self.secret, message_id=self.message, **self.scope)
            with_memory.add('independent manual fact', source='user', **self.scope)
            with_memory.add('foreign fact', user_id='other', role_id='fixture', project_id='sumika')
            with_memory.relate('user', 'likes', 'manual relation', **self.scope)
            with_memory.db.execute('CREATE TABLE embeddings(memory_id INTEGER,model TEXT,vector TEXT)')
            with_memory.db.execute('INSERT INTO embeddings VALUES (?,?,?)',
                                   (self.record['id'], 'fixture', '[1,0]'))
            with_memory.db.commit()
            self.old = self.root / 'before.json'
            with_memory.export_json(self.old, **self.scope)
            legacy = json.loads(self.old.read_text(encoding='utf8'))
            legacy['schema_version'] = 4
            legacy.pop('purge_tombstones')
            self.old.write_text(json.dumps(legacy), encoding='utf8')
        finally:
            with_memory.close()

    def preview(self):
        return purge_material(self.settings, [self.message])

    def erase(self, preview=None):
        return purge_material(self.settings, [self.message], confirmed=True,
                              expected_plan=(preview or self.preview())['plan_digest'])

    def test_preview_and_erasure_cover_cleared_material_handoffs_and_derived_bodies(self):
        self.store.clear(self.chat_scope, 'room-fixture')
        preview = self.preview()
        self.assertEqual(preview['status'], 'preview')
        self.assertEqual(preview['materials']['turn_rows'], 1)
        self.assertEqual(preview['materials']['handoffs'], 1)
        self.assertEqual(preview['materials']['handoff_events'], 1)
        result = self.erase(preview)
        self.assertEqual(result['derived'], dict(memory_records=1, proposals=1))
        self.assertEqual(result['compaction'], dict(main='complete', materials='complete'))
        self.assertFalse(result['backups_deleted'])
        self.assertFalse(result['disk_sanitized'])
        with self.store.connect() as db:
            for table in ('role_handoffs', 'role_handoff_events', 'cleared_role_turns'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM role_purged_turns').fetchone()[0], 1)
        self.assertEqual(self.store.messages('foreign', 'room-fixture')[0]['text'], 'foreign material')
        memory = EmbeddedMemory(self.database)
        try:
            self.assertIsNone(memory.get_record(self.record['record_id'], **self.scope))
            self.assertEqual(memory.list_proposals(**self.scope), [])
            self.assertEqual(memory.db.execute('SELECT count(*) FROM embeddings').fetchone()[0], 0)
            self.assertEqual(len(memory.list_relations(**self.scope)), 1)
            self.assertEqual(memory.list_records(**self.scope)[0]['text'], 'independent manual fact')
            self.assertEqual(memory.search('foreign', user_id='other', role_id='fixture', project_id='sumika')[0]['text'], 'foreign fact')
        finally:
            memory.close()
        # Current compacted database files contain no synthetic erased body.
        # This is not a statement about old backups or recoverable disk sectors.
        for path in (self.database, self.store.path):
            self.assertNotIn(self.secret.encode(), path.read_bytes())
        self.assertIn(self.secret, self.old.read_text(encoding='utf8'))

    def test_old_snapshots_replay_and_fresh_export_cannot_restore_erased_bodies(self):
        self.erase()
        memory = EmbeddedMemory(self.database)
        try:
            for operation in (memory.import_json, memory.restore_json):
                operation(self.old, **self.scope)
                self.assertIsNone(memory.get_record(self.record['record_id'], **self.scope))
                self.assertEqual(memory.list_proposals(**self.scope), [])
            late = memory.add('late rewording', source='auto-extract', event_id=self.message + ':1',
                              evidence=message_evidence(self.message), **self.scope)
            self.assertEqual(late['status'], 'suppressed')
            self.assertEqual(memory.put_proposal(event_id='late-new-index', text='late proposal',
                quote='old', message_id=self.message, **self.scope)['status'], 'suppressed')
            current = self.root / 'after.json'
            memory.export_json(current, **self.scope)
            self.assertNotIn(self.secret, current.read_text(encoding='utf8'))
            fresh = EmbeddedMemory(self.root / 'fresh.sqlite3')
            try:
                fresh.import_json(current, **self.scope)
                fresh.import_json(self.old, **self.scope)
                self.assertIsNone(fresh.get_record(self.record['record_id'], **self.scope))
                self.assertEqual(fresh.list_proposals(**self.scope), [])
            finally:
                fresh.close()
        finally:
            memory.close()
        # A new user event is independent and may explicitly state a fact again.
        memory = EmbeddedMemory(self.database)
        try:
            self.assertIn('record_id', memory.add('new statement', source='user', event_id='new', **self.scope))
        finally:
            memory.close()

    def test_attached_failure_rolls_back_both_owners_and_replay_guards(self):
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail_purge BEFORE DELETE ON role_turns BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        preview = self.preview()
        before = EmbeddedMemory(self.database)
        try:
            fence = before.scope_revision(**self.scope)
        finally:
            before.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.erase(preview)
        self.assertEqual(self.store.messages(self.chat_scope, 'room-fixture')[0]['text'], self.secret)
        memory = EmbeddedMemory(self.database)
        try:
            self.assertTrue(memory.get_record(self.record['record_id'], **self.scope)['active'])
            self.assertEqual(memory.db.execute('SELECT count(*) FROM memory_purge_tombstones').fetchone()[0], 0)
            self.assertEqual(memory.scope_revision(**self.scope), fence)
        finally:
            memory.close()

    def test_stale_plan_foreign_identity_and_unconfirmed_execution_fail_closed(self):
        preview = self.preview()
        self.store.complete(self.other, {'text': 'foreign reply'})
        with self.assertRaises(ValueError):
            purge_material(self.settings, [self.other + ':user'])
        with self.assertRaises(ValueError):
            purge_material(self.settings, [self.message], confirmed=True)
        memory = EmbeddedMemory(self.database)
        try:
            memory.add('concurrent fact', **self.scope)
        finally:
            memory.close()
        with self.assertRaisesRegex(ValueError, 'plan changed'):
            self.erase(preview)
        self.assertEqual(self.store.messages(self.chat_scope, 'room-fixture')[0]['text'], self.secret)

    def test_live_bridge_lease_and_wal_are_rejected_without_erasure(self):
        lease = DataLease(self.root).acquire()
        try:
            with self.assertRaises(OSError):
                self.preview()
        finally:
            lease.release()
        with self.store.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
        with self.assertRaisesRegex(ValueError, 'rollback journals'):
            self.preview()
        self.assertEqual(self.store.messages(self.chat_scope, 'room-fixture')[0]['text'], self.secret)

    def test_erased_legacy_material_cannot_be_reimported_or_completed(self):
        legacy = [{'who': 'me', 'text': 'legacy source', 'at': '2026-01-01'}]
        self.store.import_legacy(self.chat_scope, 'legacy', legacy)
        message = self.store.messages(self.chat_scope, 'legacy')[0]['id']
        preview = purge_material(self.settings, [message])
        purge_material(self.settings, [message], confirmed=True, expected_plan=preview['plan_digest'])
        self.assertEqual(self.store.import_legacy(self.chat_scope, 'legacy', legacy), 0)
        self.store.complete(message[:-5], {'text': 'late result'})
        self.assertEqual(self.store.messages(self.chat_scope, 'legacy'), [])

    def test_accepted_inactive_and_multisource_dependencies_removed_but_foreign_kept(self):
        memory = EmbeddedMemory(self.database)
        try:
            memory.resolve_proposal(self.message + ':proposal:0', True, **self.scope)
            memory.forget_record(self.record['record_id'], **self.scope)
            # An independent source remains a separate canonical record. A
            # mixed conclusion is removed conservatively, not re-inferred.
            mixed = memory.add('mixed conclusion', source='user-confirmed',
                evidence=message_evidence(self.message) + message_evidence('other-message'), **self.scope)
            self.assertEqual(mixed['status'], 'suppressed')
            # Use a still-active second material for a genuine mixed record.
            turn = self.store.begin(self.chat_scope, 'room-fixture', 'second source')
            message = turn + ':user'
            memory.add('mixed conclusion', source='user-confirmed',
                evidence=message_evidence(message) + message_evidence('other-message'), **self.scope)
            memory.add('same ref foreign scope', evidence=message_evidence(message),
                       user_id='other', role_id='fixture', project_id='sumika')
        finally:
            memory.close()
        preview = purge_material(self.settings, [self.message, message])
        self.assertEqual(preview['derived'], dict(memory_records=3, proposals=1))
        result = purge_material(self.settings, [self.message, message], confirmed=True,
                                expected_plan=preview['plan_digest'])
        self.assertEqual(result['derived'], preview['derived'])
        memory = EmbeddedMemory(self.database)
        try:
            self.assertEqual([r['text'] for r in memory.list_records(**self.scope)], ['independent manual fact'])
            self.assertTrue(memory.search('same ref foreign scope', user_id='other', role_id='fixture', project_id='sumika'))
        finally:
            memory.close()

    def test_incomplete_recovery_blocks_maintenance(self):
        (self.root / 'role-restore-state.json').write_text(json.dumps({
            'schema_version': 1, 'status': 'complete', 'destination': 'different-directory'}), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'recovery incomplete'):
            self.preview()
        self.assertEqual(self.store.messages(self.chat_scope, 'room-fixture')[0]['text'], self.secret)

    def test_inflight_retrieval_cannot_return_pre_erasure_hit(self):
        from extensions.memory.retrieval import MemoryRetrieval
        memory = EmbeddedMemory(self.database)
        case = self
        class Provider:
            def capabilities(self):
                return dict(scope_filter=True, source_filter=True, revisioned_hits=True)
            def search(self, query, *, scope, source, limit):
                old = memory.get_record(case.record['record_id'], **scope)
                case.erase()
                return [old]
        try:
            self.assertEqual(MemoryRetrieval(memory, Provider()).search(self.secret, **self.scope), [])
        finally:
            memory.close()
