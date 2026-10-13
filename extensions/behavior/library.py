"""Behavior sub-memory local library: layered tables and the management
contract (P08, behavior-memory-plan §3.1).

Harness-neutral SQLite store in the behavior root. The HOST assigns every
scope (user/session/epoch) — a page or a model can never declare
``origin=user`` or a confirmed verdict. Events are idempotent on the host's
event id: the same id with the same payload is a no-op, the same id with a
different payload is rejected. Persisted fields are bounded labeled facts —
screen text, screenshots, PCM, full URLs, raw key strings and clipboard
bodies are structurally impossible here. Deletion is an explicit, confirmed
transaction that also expires pending prompts, deactivates derived patterns
and bumps the behavior epoch; nothing deletes itself over time.
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
EVENT_KINDS = ('flip_burst', 'long_dwell', 'revisit', 'app_focus', 'note')
PROMPT_STATES = ('pending', 'answered', 'dismissed', 'expired', 'superseded')
FEEDBACK_VERDICTS = ('confirm', 'correct', 'ignore', 'mute')
_LABEL_LIMIT = 256
_FEATURES_LIMIT = 2048
_FORBIDDEN_KEYS = ('text', 'pcm', 'screenshot', 'image', 'url', 'keys',
                   'clipboard', 'audio', 'transcript')
_FORBIDDEN = frozenset(_FORBIDDEN_KEYS)
_REVISION = 'revision'
_EPOCH = 'behavior_epoch'
_KEY = 'material_hmac_key'
_ENABLED = 'enabled'


def _utc_iso(clock):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(clock(), tz=timezone.utc).isoformat()


def _bounded_label(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > _LABEL_LIMIT:
        raise ValueError(f'bounded {field} label required')
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f'{field} must not contain control characters')
    return value.strip()


class BehaviorLibrary:
    """SQLite behavior store; one short connection per operation."""

    def __init__(self, database, *, clock=time.time):
        if isinstance(database, sqlite3.Connection):
            raise ValueError('behavior library requires its own database path')
        self._database = str(database)
        self._clock = clock
        self._lock = threading.Lock()
        self._prepare()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self._database, timeout=10)
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _prepare(self):
        Path(self._database).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS management ('
                       'key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            row = db.execute('SELECT value FROM management WHERE key=?',
                             ('schema_version',)).fetchone()
            if row is None:
                self._create_schema(db)
                db.execute('INSERT INTO management(key,value) VALUES(?,?)',
                           ('schema_version', str(SCHEMA_VERSION)))
                db.execute('INSERT INTO management(key,value) VALUES(?,?)',
                           (_REVISION, '1'))
                db.execute('INSERT INTO management(key,value) VALUES(?,?)',
                           (_EPOCH, '1'))
                db.execute('INSERT INTO management(key,value) VALUES(?,?)',
                           (_ENABLED, '1'))
                db.execute('INSERT INTO management(key,value) VALUES(?,?)',
                           (_KEY, secrets.token_hex(32)))
            elif int(row[0]) > SCHEMA_VERSION:
                raise ValueError('behavior database is newer than this build')
            # Migration journal: every schema change records prepare/complete
            # here before touching user tables (idempotent, per the plan).

    def _create_schema(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS events ('
                   'scope_user TEXT NOT NULL, event_id TEXT NOT NULL, '
                   'session TEXT NOT NULL, epoch INTEGER NOT NULL, '
                   'at TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, '
                   'app_category TEXT, target TEXT, material TEXT, '
                   'features TEXT, payload_hash TEXT NOT NULL, '
                   'PRIMARY KEY(scope_user, event_id))')
        db.execute('CREATE INDEX IF NOT EXISTS events_scope_at '
                   'ON events(scope_user, at DESC)')
        db.execute('CREATE TABLE IF NOT EXISTS episodes ('
                   'scope_user TEXT NOT NULL, episode_id TEXT PRIMARY KEY, '
                   'started_at TEXT, ended_at TEXT, effective_seconds REAL, '
                   'pattern TEXT, features TEXT, detector_version TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS prompts ('
                   'scope_user TEXT NOT NULL, prompt_id TEXT PRIMARY KEY, '
                   'event_id TEXT, episode_id TEXT, state TEXT NOT NULL, '
                   'at TEXT NOT NULL, reason TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS feedback ('
                   'scope_user TEXT NOT NULL, feedback_id TEXT PRIMARY KEY, '
                   'user_event_id TEXT NOT NULL, prompt_id TEXT, '
                   'event_id TEXT, episode_id TEXT, original TEXT, '
                   'verdict TEXT NOT NULL, corrected TEXT, at TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS patterns ('
                   'scope_user TEXT NOT NULL, pattern_id TEXT PRIMARY KEY, '
                   'signature TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, '
                   'supports TEXT, counterexamples TEXT, sample_count INTEGER, '
                   'last_confirmed TEXT, derived_version TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS progress ('
                   'scope_user TEXT NOT NULL, record_id TEXT PRIMARY KEY, '
                   'material TEXT, position TEXT, effective_seconds REAL, '
                   'source TEXT, at TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS feedback_event '
                   'ON feedback(scope_user, event_id)')

    # -- management internals -------------------------------------------------
    def _meta(self, db, key):
        row = db.execute('SELECT value FROM management WHERE key=?',
                         (key,)).fetchone()
        return row[0] if row else None

    def _require_revision(self, db, expected):
        if type(expected) is not int:
            raise ValueError('revision required for mutations')
        current = int(self._meta(db, _REVISION))
        if expected != current:
            raise ValueError(f'revision conflict: expected {expected}, '
                             f'current {current}')

    def _bump_revision(self, db):
        db.execute('UPDATE management SET value=? WHERE key=?',
                   (str(int(self._meta(db, _REVISION)) + 1), _REVISION))

    @staticmethod
    def _scope(scope):
        if not isinstance(scope, dict):
            raise ValueError('host scope required')
        user = scope.get('user')
        if not isinstance(user, str) or not user.strip() or len(user) > 128:
            raise ValueError('host-assigned scope user required')
        session = scope.get('session')
        if session is not None and (not isinstance(session, str)
                                    or len(session) > 256):
            raise ValueError('invalid scope session')
        return user.strip(), session

    @staticmethod
    def _payload_hash(event):
        canonical = json.dumps(event, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf8')).hexdigest()

    def material_identity(self, raw):
        """Stable opaque material id: HMAC under the local key, never exported."""
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('material raw id required')
        with self._connection() as db:
            key = self._meta(db, _KEY)
        return hmac.new(key.encode('ascii'), raw.strip().encode('utf8'),
                        hashlib.sha256).hexdigest()[:32]

    # -- writes ---------------------------------------------------------------
    def observe(self, event, *, scope):
        """Persist one host-identified behavior event, idempotently.

        ``event_id`` comes from the host and the payload must match what was
        already stored under it — a reused id with different content is a
        contract violation, not a duplicate to merge.
        """
        if not isinstance(event, dict):
            raise ValueError('behavior event required')
        disallowed = _FORBIDDEN & set(event)
        if disallowed:
            raise ValueError(f'event must not carry raw content: {sorted(disallowed)}')
        if set(event) - {'event_id', 'kind', 'source', 'app_category',
                         'target', 'material', 'features'}:
            raise ValueError('unknown behavior event fields')
        event_id = _bounded_label(event.get('event_id'), 'event_id')
        kind = _bounded_label(event.get('kind'), 'kind')
        if kind not in EVENT_KINDS:
            raise ValueError('unknown behavior kind')
        source = _bounded_label(event.get('source'), 'source')
        target = event.get('target')
        if target is not None:
            target = _bounded_label(target, 'target')
        material = event.get('material')
        if material is not None:
            material = _bounded_label(material, 'material')
        features = event.get('features')
        if features is not None:
            if not isinstance(features, dict) or len(features) > 32 or any(
                    key in _FORBIDDEN_KEYS for key in features):
                raise ValueError('flat bounded features required')
            encoded = json.dumps(features, ensure_ascii=False, sort_keys=True)
            if len(encoded) > _FEATURES_LIMIT or any(
                    not isinstance(value, (str, int, float, bool))
                    for value in features.values()):
                raise ValueError('features must be flat bounded values')
        payload = {key: event.get(key) for key in ('event_id', 'kind', 'source',
                                                   'app_category', 'target',
                                                   'material', 'features')}
        payload_hash = self._payload_hash(payload)
        user, session = self._scope(scope)
        at = _utc_iso(self._clock)
        with self._lock, self._connection() as db:
            existing = db.execute('SELECT payload_hash FROM events '
                                  'WHERE scope_user=? AND event_id=?',
                                  (user, event_id)).fetchone()
            if existing is not None:
                if existing[0] != payload_hash:
                    raise ValueError('event id reuse with a different payload')
                return {'status': 'duplicate'}
            epoch = int(self._meta(db, _EPOCH))
            db.execute('INSERT INTO events(scope_user,event_id,session,epoch,'
                       'at,kind,source,app_category,target,material,features,'
                       'payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (user, event_id, session or '', epoch, at, kind, source,
                        event.get('app_category'), target, material,
                        json.dumps(features, ensure_ascii=False)
                        if features is not None else None, payload_hash))
            return {'status': 'recorded', 'event_id': event_id, 'at': at}

    def feedback(self, entry, *, scope):
        """Persist one explicit user verdict; scope and ids are host-filled."""
        if not isinstance(entry, dict):
            raise ValueError('feedback entry required')
        if set(entry) - {'feedback_id', 'user_event_id', 'prompt_id',
                         'event_id', 'episode_id', 'original', 'verdict',
                         'corrected'}:
            raise ValueError('unknown feedback fields')
        feedback_id = _bounded_label(entry.get('feedback_id'), 'feedback_id')
        user_event_id = _bounded_label(entry.get('user_event_id'), 'user_event_id')
        verdict = entry.get('verdict')
        if verdict not in FEEDBACK_VERDICTS:
            raise ValueError('feedback verdict required')
        corrected = entry.get('corrected')
        if corrected is not None and (not isinstance(corrected, str)
                                      or len(corrected) > 2000):
            raise ValueError('corrected text must be user text within budget')
        original = entry.get('original')
        if original is not None and (not isinstance(original, str)
                                     or len(original) > 2000):
            raise ValueError('original text must stay within budget')
        user, _ = self._scope(scope)
        at = _utc_iso(self._clock)
        with self._lock, self._connection() as db:
            exists = db.execute('SELECT 1 FROM feedback WHERE scope_user=? '
                                'AND feedback_id=?', (user, feedback_id)).fetchone()
            if exists:
                return {'status': 'duplicate'}
            db.execute('INSERT INTO feedback(scope_user,feedback_id,user_event_id,'
                       'prompt_id,event_id,episode_id,original,verdict,corrected,'
                       'at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (user, feedback_id, user_event_id, entry.get('prompt_id'),
                        entry.get('event_id'), entry.get('episode_id'), original,
                        verdict, corrected, at))
            self._bump_revision(db)
            return {'status': 'recorded', 'feedback_id': feedback_id, 'at': at}

    def correct(self, feedback_id, corrected, *, scope, revision):
        """User correction on an existing verdict; the corrected reading is
        what later recalls must honor."""
        feedback_id = _bounded_label(feedback_id, 'feedback_id')
        if not isinstance(corrected, str) or not corrected.strip() \
                or len(corrected) > 2000:
            raise ValueError('corrected user text required')
        user, _ = self._scope(scope)
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            row = db.execute('SELECT 1 FROM feedback WHERE scope_user=? AND '
                             'feedback_id=?', (user, feedback_id)).fetchone()
            if row is None:
                raise ValueError('feedback record not found')
            db.execute('UPDATE feedback SET corrected=?, verdict=? '
                       'WHERE scope_user=? AND feedback_id=?',
                       (corrected.strip(), 'correct', user, feedback_id))
            self._bump_revision(db)
            return {'status': 'corrected', 'feedback_id': feedback_id}

    def delete_records(self, *, scope, event_ids=(), kinds=(), before=None,
                       confirmed=False, revision=None):
        """Explicit, confirmed deletion of a stated selection.

        The transaction covers the selected events, the feedback bound to
        them, pending prompts and derived patterns; the behavior epoch
        advances so no cache or in-flight consumer can resurrect the deleted
        material. Nothing here claims to erase snapshots or SSD history.
        """
        user, session = self._scope(scope)
        if not confirmed:
            raise ValueError('deletion requires explicit confirmation')
        ids = [_bounded_label(value, 'event_id') for value in event_ids]
        selected_kinds = [kind for kind in kinds if kind in EVENT_KINDS]
        if kinds and len(selected_kinds) != len(kinds):
            raise ValueError('unknown behavior kind in deletion')
        if before is not None and not isinstance(before, str):
            raise ValueError('deletion before-cursor must be an ISO time')
        if not ids and not selected_kinds and before is None:
            raise ValueError('deletion needs an explicit selection')
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            query, args = 'scope_user=?', [user]
            if ids:
                query += f' AND event_id IN ({",".join("?" * len(ids))})'
                args.extend(ids)
            if selected_kinds:
                query += f' AND kind IN ({",".join("?" * len(selected_kinds))})'
                args.extend(selected_kinds)
            if before is not None:
                query += ' AND at<?'
                args.append(before)
            if session:
                query += ' AND session=?'
                args.append(session)
            selected = [row[0] for row in db.execute(
                f'SELECT event_id FROM events WHERE {query}', args).fetchall()]
            if not selected:
                return {'status': 'nothing_selected', 'deleted_events': 0}
            marks = ','.join('?' * len(selected))
            deleted = db.execute(f'DELETE FROM events WHERE scope_user=? AND '
                                 f'event_id IN ({marks})', [user, *selected]).rowcount
            feedback = db.execute(f'DELETE FROM feedback WHERE scope_user=? AND '
                                  f'event_id IN ({marks})',
                                  [user, *selected]).rowcount
            db.execute(f'UPDATE prompts SET state=? WHERE scope_user=? AND '
                       f'event_id IN ({marks}) AND state=?',
                       ('expired', user, *selected, 'pending'))
            db.execute('UPDATE patterns SET active=0 WHERE scope_user=?', (user,))
            db.execute('UPDATE management SET value=? WHERE key=?',
                       (str(int(self._meta(db, _EPOCH)) + 1), _EPOCH))
            self._bump_revision(db)
            return {'status': 'deleted', 'deleted_events': deleted,
                    'deleted_feedback': feedback,
                    'behavior_epoch': int(self._meta(db, _EPOCH))}

    # -- reads ----------------------------------------------------------------
    def list_records(self, *, scope, kind=None, cursor=None, limit=50):
        user, session = self._scope(scope)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('query limit must be 1..100 (default 50)')
        query = 'SELECT event_id, at, kind, source, app_category, target, ' \
                'material, session, epoch FROM events WHERE scope_user=?'
        args = [user]
        if kind is not None:
            if kind not in EVENT_KINDS:
                raise ValueError('unknown behavior kind')
            query += ' AND kind=?'
            args.append(kind)
        if session:
            query += ' AND session=?'
            args.append(session)
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) > 256:
                raise ValueError('invalid page cursor')
            query += ' AND (at<? OR (at=? AND event_id<?))'
            args.extend([cursor[:cursor.index('|')] if '|' in cursor else cursor,
                         cursor[:cursor.index('|')] if '|' in cursor else cursor,
                         cursor[cursor.index('|') + 1:] if '|' in cursor else ''])
        query += ' ORDER BY at DESC, event_id DESC LIMIT ?'
        args.append(limit + 1)
        with self._connection() as db:
            rows = db.execute(query, args).fetchall()
        page = [{'event_id': row[0], 'at': row[1], 'kind': row[2],
                 'source': row[3], 'app_category': row[4], 'target': row[5],
                 'material': row[6], 'session': row[7], 'epoch': row[8]}
                for row in rows[:limit]]
        next_cursor = (f'{page[-1]["at"]}|{page[-1]["event_id"]}'
                       if len(rows) > limit and page else None)
        return {'records': page, 'next_cursor': next_cursor}

    def context(self, *, scope, limit=3):
        """Bounded recent behavior facts for prompt building."""
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError('context limit must be 1..10')
        user, session = self._scope(scope)
        with self._connection() as db:
            rows = db.execute('SELECT at, kind, target, material FROM events '
                              'WHERE scope_user=? ORDER BY at DESC, event_id '
                              'DESC LIMIT ?', (user, limit)).fetchall()
        return [{'at': row[0], 'kind': row[1], 'target': row[2],
                 'material': row[3]} for row in rows]

    def export(self, *, scope):
        """Bounded JSON export of one scope's events and feedback.

        The material HMAC key never leaves the library.
        """
        user, _ = self._scope(scope)
        with self._connection() as db:
            events = db.execute('SELECT event_id,session,epoch,at,kind,source,'
                                'app_category,target,material,features FROM '
                                'events WHERE scope_user=? ORDER BY at',
                                (user,)).fetchall()
            feedback = db.execute('SELECT feedback_id,user_event_id,prompt_id,'
                                  'event_id,episode_id,original,verdict,'
                                  'corrected,at FROM feedback WHERE '
                                  'scope_user=? ORDER BY at', (user,)).fetchall()
        return {'schema_version': SCHEMA_VERSION, 'scope_user': user,
                'events': [dict(zip(('event_id', 'session', 'epoch', 'at',
                                     'kind', 'source', 'app_category',
                                     'target', 'material', 'features'), row))
                           for row in events],
                'feedback': [dict(zip(('feedback_id', 'user_event_id',
                                       'prompt_id', 'event_id', 'episode_id',
                                       'original', 'verdict', 'corrected',
                                       'at'), row)) for row in feedback]}

    def configure(self, settings, *, revision):
        """Revision-guarded library settings (currently: enabled)."""
        if not isinstance(settings, dict) or set(settings) - {'enabled'}:
            raise ValueError('unknown behavior settings')
        enabled = settings.get('enabled')
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            db.execute('UPDATE management SET value=? WHERE key=?',
                       ('1' if enabled else '0', _ENABLED))
            self._bump_revision(db)
            return {'status': 'configured', 'enabled': enabled}

    def status(self):
        with self._connection() as db:
            values = dict(db.execute('SELECT key,value FROM management').fetchall())
            counts = db.execute('SELECT kind,COUNT(*) FROM events '
                                'GROUP BY kind').fetchall()
        return {'schema_version': int(values.get('schema_version', '0')),
                'revision': int(values.get(_REVISION, '0')),
                'behavior_epoch': int(values.get(_EPOCH, '0')),
                'enabled': values.get(_ENABLED) == '1',
                'events_by_kind': {kind: count for kind, count in counts}}

    def stop(self):
        pass  # Path mode owns no persistent handle.
