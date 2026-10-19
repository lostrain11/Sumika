"""Canonical memory contracts and SQLite governance shared by local backends.

Materials stay with their domain owners. Evidence references identify host-owned
messages; they never contain copied transcripts or grant permission.
"""
import hashlib
import json
import re
import time
import uuid
from typing import Protocol


class MemoryRepository(Protocol):
    enabled: bool

    def add(self, text, **fields): ...
    def get_record(self, record_id, **scope): ...
    def list_records(self, **filters): ...
    def scope_revision(self, **scope): ...
    def retract_evidence(self, refs, **scope): ...
    def forget_record(self, record_id, **scope): ...
    def correct_record(self, record_id, text, **scope): ...
    def mutate_relation(self, record_id, **fields): ...
    def put_proposal(self, *, event_id, text, **fields): ...
    def list_proposals(self, **scope): ...
    def resolve_proposal(self, event_id, accept, **scope): ...


def evidence_refs(refs, *, source, event_id):
    if refs is None:
        match = re.fullmatch(r'(.+):[0-9]+', event_id or '') if source == 'auto-extract' else None
        refs = (message_evidence(match.group(1)) if match else
                [] if event_id is None else [dict(domain='memory_event',
                source_id=event_id, source_revision=1, evidence_kind=source)])
    if not isinstance(refs, list) or len(refs) > 32:
        raise ValueError('invalid evidence references')
    result = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {
                'domain', 'source_id', 'source_revision', 'evidence_kind'}:
            raise ValueError('invalid evidence reference')
        if any(not isinstance(ref[k], str) or not ref[k].strip() or len(ref[k]) > 512
               for k in ('domain', 'source_id', 'evidence_kind')):
            raise ValueError('invalid evidence identity')
        if type(ref['source_revision']) is not int or ref['source_revision'] < 1:
            raise ValueError('invalid evidence revision')
        result.append(dict(ref))
    return result


def message_evidence(message_id):
    return [dict(domain='role_user_message', source_id=message_id,
                 source_revision=1, evidence_kind='user_message')]


def suppression_key(ref):
    # Source-wide suppression is conservative: rephrasing or selecting another
    # proposal index from the same forgotten message cannot bypass it.
    value = [ref['domain'], ref['source_id']]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def purge_key(value):
    """Body-free identity for permanent-erasure replay guards."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


class SQLiteRepository:
    """Implementation detail of EmbeddedMemory, not a second memory store."""

    def mutate_relation(self, record_id, *, expected_revision, user_id, role_id,
                        project_id='default', new_object=None, delete=False):
        """Mutate one host-selected relation; old dialog snapshots fail closed."""
        if not self.enabled:
            return {'disabled': True}
        if (not isinstance(record_id, str) or not record_id.strip()
                or type(expected_revision) is not int or expected_revision < 1
                or type(delete) is not bool):
            raise ValueError('relation identity and revision required')
        if not delete and (not isinstance(new_object, str) or not new_object.strip()):
            raise ValueError('relation object required')
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT revision,active FROM relations WHERE scope=? AND record_id=?',
                                  (scope, record_id)).fetchone()
            if row is None or row != (expected_revision, 1):
                raise ValueError('relation revision conflict')
            if delete:
                self.db.execute("UPDATE relations SET active=0,status='deleted',revision=revision+1 "
                                'WHERE scope=? AND record_id=?', (scope, record_id))
            else:
                self.db.execute('UPDATE relations SET object=?,revision=revision+1 WHERE scope=? AND record_id=?',
                                (new_object, scope, record_id))
        return {'record_id': record_id, 'revision': expected_revision + 1,
                'deleted' if delete else 'updated': 1}

    def _migrate_repository(self):
        for table in ('memories', 'relations'):
            columns = {r[1] for r in self.db.execute(f'PRAGMA table_info({table})')}
            for name, declaration in [('record_id', 'TEXT'), ('revision', 'INTEGER NOT NULL DEFAULT 1'),
                                      ('status', "TEXT NOT NULL DEFAULT 'active'")]:
                if name not in columns:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
            for (rowid,) in self.db.execute(f'SELECT rowid FROM {table} WHERE record_id IS NULL').fetchall():
                self.db.execute(f'UPDATE {table} SET record_id=?,status=CASE WHEN active=1 '
                                "THEN 'active' ELSE 'superseded' END WHERE rowid=?",
                                (uuid.uuid4().hex, rowid))
            self.db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS {table}_record_identity ON {table}(record_id)')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(memories)')}
        if 'evidence_refs' not in columns:
            self.db.execute("ALTER TABLE memories ADD COLUMN evidence_refs TEXT NOT NULL DEFAULT '[]'")
            for rowid, source, event in self.db.execute('SELECT id,source,event_id FROM memories').fetchall():
                self.db.execute('UPDATE memories SET evidence_refs=? WHERE id=?',
                                (json.dumps(evidence_refs(None, source=source, event_id=event)), rowid))
        # Upgrade old proposal provenance once; only known host event formats
        # are mapped. Unknown origins keep their original event reference.
        for scope, event, raw in self.db.execute('SELECT scope,event,data FROM memory_proposals').fetchall():
            data = json.loads(raw)
            if 'evidence_refs' not in data:
                refs = (message_evidence(data['message_id']) if data.get('message_id') else
                        evidence_refs(None, source='model_proposal', event_id=event))
                data.update(evidence_refs=refs, revision=data.get('revision', 1))
                self.db.execute('UPDATE memory_proposals SET data=? WHERE scope=? AND event=?',
                                (json.dumps(data, ensure_ascii=False, sort_keys=True), scope, event))
                self.db.execute("UPDATE memories SET evidence_refs=? WHERE scope=? AND source='user-confirmed' AND event_id=?",
                                (json.dumps(refs), scope, event))
        self.db.execute('CREATE TABLE IF NOT EXISTS memory_suppressions '
                        '(scope TEXT, evidence_key TEXT, created REAL, PRIMARY KEY(scope,evidence_key))')
        self.db.execute('CREATE TABLE IF NOT EXISTS memory_purge_tombstones '
                        '(scope TEXT, kind TEXT, identity_hash TEXT, '
                        'PRIMARY KEY(scope,kind,identity_hash))')
        self.db.execute('CREATE TABLE IF NOT EXISTS memory_repository_identity '
                        '(singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL)')
        self.db.execute('INSERT OR IGNORE INTO memory_repository_identity VALUES (1,?)', (uuid.uuid4().hex,))
        self.db.execute('CREATE TABLE IF NOT EXISTS memory_scope_revisions '
                        '(scope TEXT PRIMARY KEY, revision INTEGER NOT NULL)')
        # Database triggers cover legacy writes, restore/import and other live
        # connections in the same transaction as the canonical mutation. Cache
        # writes do not advance the fence. Rollback rolls back its increments.
        for table in ('memories', 'relations', 'memory_proposals', 'memory_suppressions',
                      'memory_purge_tombstones'):
            for operation, aliases in (('INSERT', ('NEW',)), ('DELETE', ('OLD',)),
                                       ('UPDATE', ('OLD', 'NEW'))):
                statements = ' '.join(
                    'INSERT INTO memory_scope_revisions(scope,revision) '
                    f'VALUES ({alias}.scope,1) ON CONFLICT(scope) DO UPDATE SET revision=revision+1;'
                    for alias in aliases)
                self.db.execute(f'CREATE TRIGGER IF NOT EXISTS memory_fence_{table}_{operation.lower()} '
                                f'AFTER {operation} ON {table} BEGIN {statements} END')

    def scope_revision(self, *, user_id, role_id, project_id='default'):
        """Opaque persistent fence for one host-bound scope; no raw scope IDs.

        Not an authorization token or backup generation. An explicit whole-file
        historical restore must restart consumers and discard their old leases.
        """
        if not self.enabled:
            return None
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        row = self.db.execute('SELECT identity,COALESCE((SELECT revision FROM '
                              'memory_scope_revisions WHERE scope=?),0) '
                              'FROM memory_repository_identity WHERE singleton=1', (scope,)).fetchone()
        return f'{row[0]}:{row[1]}'

    def rebuild_indexes(self, *, user_id, role_id, project_id='default'):
        """Rebuild derived FTS and discard selected vector cache; never re-extract."""
        if not self.enabled:
            return {'disabled': True}
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            # The shared FTS index is rebuilt atomically from active canonical
            # rows only. No historical text is used to generate new facts.
            self.db.execute("INSERT INTO memory_fts(memory_fts) VALUES ('delete-all')")
            self.db.execute('INSERT INTO memory_fts(rowid,text) SELECT id,text FROM memories WHERE active=1')
            self._invalidate_vectors(scope)
        return {'rebuilt': True, 'scope': scope}

    def scope_key(self, *, user_id, role_id, project_id='default'):
        return self._scope(user_id, role_id, project_id)

    def _is_suppressed(self, scope, refs):
        return any(self.db.execute('SELECT 1 FROM memory_suppressions WHERE scope=? AND evidence_key=?',
                                   (scope, suppression_key(ref))).fetchone() for ref in refs)

    def _suppress(self, scope, refs):
        for ref in refs:
            self.db.execute('INSERT OR IGNORE INTO memory_suppressions VALUES (?,?,?)',
                            (scope, suppression_key(ref), time.time()))

    def _invalidate_vectors(self, scope):
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='embeddings'").fetchone():
            self.db.execute('DELETE FROM embeddings WHERE memory_id IN '
                            '(SELECT id FROM memories WHERE scope=?)', (scope,))

    def _is_purged(self, scope, *, refs=(), record_id=None, source=None, event_id=None,
                   proposal_event=None):
        keys = [('evidence', suppression_key(ref)) for ref in refs]
        if record_id is not None:
            keys.append(('record', purge_key(record_id)))
        if event_id is not None:
            keys.append(('event', purge_key([source, event_id])))
        if proposal_event is not None:
            keys.append(('proposal', purge_key(proposal_event)))
        return any(self.db.execute('SELECT 1 FROM memory_purge_tombstones '
            'WHERE scope=? AND kind=? AND identity_hash=?', (scope, kind, identity)).fetchone()
            for kind, identity in keys)

    def _purge_guard(self, scope, kind, identity_hash):
        self.db.execute('INSERT OR IGNORE INTO memory_purge_tombstones VALUES (?,?,?)',
                        (scope, kind, identity_hash))

    def _enforce_purges_in_transaction(self, scope):
        """Caller owns transaction; remove bodies, retain only hashed replay guards."""
        removed, proposals = 0, 0
        self._invalidate_vectors(scope)
        for rowid, record, source, event, raw in self.db.execute(
                'SELECT id,record_id,source,event_id,evidence_refs FROM memories WHERE scope=?',
                (scope,)).fetchall():
            if not self._is_purged(scope, refs=json.loads(raw), record_id=record,
                                   source=source, event_id=event):
                continue
            self._purge_guard(scope, 'record', purge_key(record))
            if event is not None:
                self._purge_guard(scope, 'event', purge_key([source, event]))
            self.db.execute('DELETE FROM memories WHERE id=? AND scope=?', (rowid, scope))
            removed += 1
        for event, raw in self.db.execute(
                'SELECT event,data FROM memory_proposals WHERE scope=?', (scope,)).fetchall():
            data = json.loads(raw)
            refs = data.get('evidence_refs', evidence_refs(None, source='model_proposal', event_id=event))
            if not self._is_purged(scope, refs=refs, proposal_event=event):
                continue
            self._purge_guard(scope, 'proposal', purge_key(event))
            self.db.execute('DELETE FROM memory_proposals WHERE scope=? AND event=?', (scope, event))
            proposals += 1
        # Drop old FTS segments too; rebuilding cannot reintroduce purged bodies.
        self.db.execute("INSERT INTO memory_fts(memory_fts) VALUES ('delete-all')")
        self.db.execute('INSERT INTO memory_fts(rowid,text) SELECT id,text FROM memories WHERE active=1')
        return {'memory_records': removed, 'proposals': proposals}

    def _purge_evidence_in_transaction(self, refs, *, user_id, role_id, project_id='default'):
        refs = evidence_refs(refs, source='host_purge', event_id=None)
        if not refs:
            raise ValueError('evidence required for purge')
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        self._suppress(scope, refs)
        for ref in refs:
            self._purge_guard(scope, 'evidence', suppression_key(ref))
        return self._enforce_purges_in_transaction(scope)

    def retract_evidence(self, refs, *, user_id, role_id, project_id='default',
                         expected_scope_revision):
        """Revoke host-owned material evidence before any material deletion.

        This is logical dependency invalidation, not physical purge. Multi-source
        conclusions touching a revoked source are conservatively invalidated;
        another surviving reference alone does not prove the entire conclusion.
        Independent records remain active. New host events may state facts again.
        """
        if not self.enabled:
            return {'disabled': True}
        refs = evidence_refs(refs, source='host_retraction', event_id=None)
        if not refs:
            raise ValueError('evidence required for retraction')
        if not isinstance(expected_scope_revision, str) or not expected_scope_revision:
            raise ValueError('expected scope revision required')
        fields = dict(user_id=user_id, role_id=role_id, project_id=project_id)
        scope = self.scope_key(**fields)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.scope_revision(**fields) != expected_scope_revision:
                raise ValueError('memory scope revision conflict')
            active = {row[0] for row in self.db.execute(
                'SELECT record_id FROM memories WHERE scope=? AND active=1', (scope,))}
            pending = {event for event, raw in self.db.execute(
                'SELECT event,data FROM memory_proposals WHERE scope=?', (scope,))
                if json.loads(raw).get('status', 'pending') == 'pending'}
            # Write suppression even when extraction has not committed yet.
            self._suppress(scope, refs)
            self._apply_suppressions(scope)
            self._invalidate_vectors(scope)
            remaining = {row[0] for row in self.db.execute(
                'SELECT record_id FROM memories WHERE scope=? AND active=1', (scope,))}
            still_pending = {event for event, raw in self.db.execute(
                'SELECT event,data FROM memory_proposals WHERE scope=?', (scope,))
                if json.loads(raw).get('status', 'pending') == 'pending'}
            return {'invalidated_record_ids': sorted(active - remaining),
                    'rejected_proposal_events': sorted(pending - still_pending),
                    'scope_revision': self.scope_revision(**fields),
                    'material_deleted': False, 'history_retained': True}

    def get_record(self, record_id, *, user_id, role_id, project_id='default'):
        if not self.enabled:
            return None
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        column = 'id' if type(record_id) is int else 'record_id'
        cursor = self.db.execute(f'SELECT * FROM memories WHERE {column}=? AND scope=?', (record_id, scope))
        row = cursor.fetchone()
        if row is None:
            return None
        record = dict(zip([c[0] for c in cursor.description], row))
        record['evidence_refs'] = json.loads(record['evidence_refs'])
        return record

    def list_records(self, *, user_id, role_id, project_id='default', include_inactive=False,
                     limit=500, after_id=0):
        if not self.enabled:
            return []
        if type(limit) is not int or not 1 <= limit <= 1000 or type(after_id) is not int or after_id < 0:
            raise ValueError('invalid memory pagination')
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        cursor = self.db.execute('SELECT * FROM memories WHERE scope=? AND id>?'
                                 + ('' if include_inactive else ' AND active=1')
                                 + ' ORDER BY id LIMIT ?', (scope, after_id, limit))
        records = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
        for record in records:
            record['evidence_refs'] = json.loads(record['evidence_refs'])
        return records

    def forget_record(self, record_id, *, user_id, role_id, project_id='default', expected_revision=None):
        if not self.enabled:
            return {'disabled': True}
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError('invalid expected revision')
        scope_fields = dict(user_id=user_id, role_id=role_id, project_id=project_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.get_record(record_id, **scope_fields)
            if row is None:
                return {'forgotten': 0}
            if expected_revision is not None and expected_revision != row['revision']:
                raise ValueError('memory revision conflict')
            if row['status'] == 'deleted':
                return {'forgotten': 0, 'record_id': row['record_id'], 'revision': row['revision']}
            self._suppress(row['scope'], row['evidence_refs'])
            self.db.execute("UPDATE memories SET active=0,status='deleted',revision=revision+1,updated=? WHERE id=?",
                            (time.time(), row['id']))
            # Invalidate other records/proposals extracted from this same old
            # message, even when a different extraction algorithm used new text.
            self._apply_suppressions(row['scope'])
            self._invalidate_vectors(row['scope'])
            return {'forgotten': 1, 'record_id': row['record_id'], 'revision': row['revision'] + 1}

    def correct_record(self, record_id, text, *, user_id, role_id,
                       project_id='default', expected_revision, event_id):
        """Explicit host correction, atomic with suppression and cache invalidation.

        Keep the original as history and issue a new canonical identity. A retry
        of the same event returns its original receipt, never another version.
        """
        if not self.enabled:
            return {'disabled': True}
        if (not isinstance(record_id, str) or not record_id.strip()
                or not isinstance(text, str) or not text.strip()
                or type(expected_revision) is not int or expected_revision < 1
                or not isinstance(event_id, str) or not event_id.strip()):
            raise ValueError('correction identity, text, revision and event required')
        fields = dict(user_id=user_id, role_id=role_id, project_id=project_id)
        scope = self.scope_key(**fields)
        refs = evidence_refs([dict(domain='memory_correction',
            source_id=record_id + ':' + event_id, source_revision=1,
            evidence_kind='user_correction')], source='user', event_id=event_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            prior = self.db.execute("SELECT record_id,text,evidence_refs,revision FROM memories "
                                    "WHERE scope=? AND source='user' AND event_id=?",
                                    (scope, event_id)).fetchone()
            if prior:
                if prior[1] != text or json.loads(prior[2]) != refs:
                    raise ValueError('correction event conflict')
                return dict(record_id=prior[0], revision=prior[3], duplicate=True)
            old = self.get_record(record_id, **fields)
            if old is None or not old['active'] or old['revision'] != expected_revision:
                raise ValueError('memory revision conflict')
            self._suppress(scope, old['evidence_refs'])
            self._apply_suppressions(scope)
            self.db.execute("UPDATE memories SET active=0,status='superseded',revision=?,updated=? WHERE id=?",
                            (old['revision'] + 1, time.time(), old['id']))
            result = self._add_in_transaction(text, scope=scope, source='user',
                fact_key=old['fact_key'], event_id=event_id, refs=refs)
            self._invalidate_vectors(scope)
            return {**result, 'supersedes': old['record_id']}

    def _apply_suppressions(self, scope):
        for rowid, raw in self.db.execute('SELECT id,evidence_refs FROM memories WHERE scope=? AND active=1', (scope,)).fetchall():
            if self._is_suppressed(scope, json.loads(raw)):
                self.db.execute("UPDATE memories SET active=0,status='deleted',revision=revision+1,updated=? WHERE id=?",
                                (time.time(), rowid))
        for event, raw in self.db.execute('SELECT event,data FROM memory_proposals WHERE scope=?', (scope,)).fetchall():
            data = json.loads(raw)
            if data.get('status', 'pending') == 'pending' and self._is_suppressed(scope, data.get('evidence_refs', [])):
                data['status'] = 'rejected'
                data['revision'] = data.get('revision', 1) + 1
                self.db.execute('UPDATE memory_proposals SET data=? WHERE scope=? AND event=?',
                                (json.dumps(data, ensure_ascii=False, sort_keys=True), scope, event))

    def _forget_scope_in_transaction(self, scope):
        """Reset learned facts and pending proposals without erasing suppression.

        The caller owns the transaction. Role-card reset uses this same path;
        historical snapshot restoration intentionally has different semantics.
        """
        for raw, in self.db.execute('SELECT evidence_refs FROM memories WHERE scope=? AND active=1', (scope,)).fetchall():
            self._suppress(scope, json.loads(raw))
        for event, raw in self.db.execute('SELECT event,data FROM memory_proposals WHERE scope=?', (scope,)).fetchall():
            data = json.loads(raw)
            if data.get('status', 'pending') != 'pending':
                continue
            refs = data.get('evidence_refs', evidence_refs(None, source='model_proposal', event_id=event))
            self._suppress(scope, refs)
            data.update(status='rejected', revision=data.get('revision', 1) + 1)
            self.db.execute('UPDATE memory_proposals SET data=? WHERE scope=? AND event=?',
                            (json.dumps(data, ensure_ascii=False, sort_keys=True), scope, event))
        for table in ('memories', 'relations'):
            self.db.execute(f"UPDATE {table} SET active=0,status='deleted',revision=revision+1 WHERE scope=? AND active=1", (scope,))
        self._apply_suppressions(scope)
        self._invalidate_vectors(scope)

    def put_proposal(self, *, event_id, text, user_id, role_id, project_id='default',
                     fact_key=None, quote=None, message_id=None):
        if not self.enabled:
            return {'disabled': True}
        if not isinstance(event_id, str) or not event_id.strip() or not isinstance(text, str) or not text.strip():
            raise ValueError('proposal identity and text required')
        if fact_key is not None and (not isinstance(fact_key, str) or not fact_key.strip()):
            raise ValueError('invalid proposal fact key')
        if (quote is None) != (message_id is None) or (quote is not None and
                any(not isinstance(x, str) or not x.strip() for x in (quote, message_id))):
            raise ValueError('invalid proposal evidence')
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        refs = (message_evidence(message_id) if message_id is not None else
                evidence_refs(None, source='model_proposal', event_id=event_id))
        data = dict(text=text, fact_key=fact_key, source='model_proposal', evidence_refs=refs,
                    revision=1, status='pending')
        if quote is not None:
            data.update(quote=quote, message_id=message_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self._is_purged(scope, refs=refs, proposal_event=event_id):
                return {'status': 'suppressed', 'event_id': event_id, 'retrievable': False}
            prior = self.db.execute('SELECT data FROM memory_proposals WHERE scope=? AND event=?', (scope, event_id)).fetchone()
            if prior:
                old = json.loads(prior[0])
                if any(old.get(k) != data.get(k) for k in ('text', 'fact_key', 'quote', 'message_id')):
                    raise ValueError('model proposal event conflict')
                return {'status': old.get('status', 'pending'), 'event_id': event_id, 'retrievable': False, 'duplicate': True}
            if self._is_suppressed(scope, refs):
                return {'status': 'suppressed', 'event_id': event_id, 'retrievable': False}
            self.db.execute('INSERT INTO memory_proposals VALUES (?,?,?)',
                            (scope, event_id, json.dumps(data, ensure_ascii=False, sort_keys=True)))
        return {'status': 'proposal', 'event_id': event_id, 'retrievable': False}

    def list_proposals(self, *, user_id, role_id, project_id='default'):
        if not self.enabled:
            return []
        scope = self.scope_key(user_id=user_id, role_id=role_id, project_id=project_id)
        return [dict(event_id=event, **json.loads(data)) for event, data in
                self.db.execute('SELECT event,data FROM memory_proposals WHERE scope=? ORDER BY rowid', (scope,))]

    def resolve_proposal(self, event_id, accept, *, user_id, role_id, project_id='default', expected_revision=None):
        if not self.enabled:
            return {'disabled': True}
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError('invalid expected revision')
        if type(accept) is not bool:
            raise ValueError('explicit proposal decision required')
        fields = dict(user_id=user_id, role_id=role_id, project_id=project_id)
        scope = self.scope_key(**fields)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            raw = self.db.execute('SELECT data FROM memory_proposals WHERE scope=? AND event=?', (scope, event_id)).fetchone()
            if raw is None:
                raise ValueError('proposal not found in selected role')
            data = json.loads(raw[0])
            if expected_revision is not None and expected_revision != data.get('revision', 1):
                raise ValueError('proposal revision conflict')
            status = 'accepted' if accept else 'rejected'
            if data.get('status', 'pending') != 'pending':
                if data['status'] != status:
                    raise ValueError('proposal already resolved')
                return {'status': status, 'duplicate': True}
            refs = data.get('evidence_refs', evidence_refs(None, source='model_proposal', event_id=event_id))
            if self._is_suppressed(scope, refs):
                raise ValueError('proposal evidence was forgotten')
            if accept:
                # _add_in_transaction is the canonical writer, sharing this
                # transaction so fact and proposal state cannot diverge.
                self._add_in_transaction(data['text'], scope=scope, source='user-confirmed',
                                         fact_key=None, event_id=event_id, refs=refs)
            data.update(status=status, revision=data.get('revision', 1) + 1)
            self.db.execute('UPDATE memory_proposals SET data=? WHERE scope=? AND event=?',
                            (json.dumps(data, ensure_ascii=False, sort_keys=True), scope, event_id))
        return {'status': status}

