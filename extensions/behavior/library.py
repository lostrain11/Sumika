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
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class CapacityPaused(Exception):
    """Recording is hard-paused (disk guard or SQLITE_FULL) until the user
    explicitly resumes; nothing is deleted and nothing claims to be recorded."""


class MigrationActive(Exception):
    """A root migration owns the library; new records fail loudly."""


DEFAULT_CAPACITY = {'remind_tier_bytes': 5 * 1024 ** 3,
                    'low_free_bytes': 10 * 1024 ** 3,
                    'low_free_ratio': 0.10,
                    'pause_free_bytes': 1 * 1024 ** 3}

SCHEMA_VERSION = 3
FRAMES_SCHEMA = 'input-frame-v1'
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

    def __init__(self, database, *, clock=time.time, capacity_overrides=None,
                 locator=None):
        if isinstance(database, sqlite3.Connection):
            raise ValueError('behavior library requires its own database path')
        self._database = str(database)
        self._locator = locator
        self._clock = clock
        self._lock = threading.Lock()
        self._capacity = {**DEFAULT_CAPACITY, **(capacity_overrides or {})}
        self._capacity_checked_at = None
        self._retired = False
        self._prepare()

    @contextmanager
    def _connection(self):
        if self._retired:
            raise RuntimeError('this behavior library was migrated away; '
                               'rebuild it from the locator')
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
            elif int(row[0]) < SCHEMA_VERSION:
                # Additive migrations with the journal anchor §3.1 requires;
                # the steps are CREATE/ALTER IF-missing, safe to re-run.
                columns = {item[1] for item in
                           db.execute('PRAGMA table_info(episodes)').fetchall()}
                if 'session' not in columns:
                    db.execute('ALTER TABLE episodes ADD COLUMN session TEXT')
                db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('migration_1_to_2',
                            json.dumps({'state': 'complete',
                                        'step': 'frames + episodes.session'})))
                db.execute("UPDATE management SET value=? "
                           "WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            # Migration journal: every schema change records prepare/complete
            # here before touching user tables (idempotent, per the plan).
            self._reconcile_migration(db)

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
                   'session TEXT, started_at TEXT, ended_at TEXT, '
                   'effective_seconds REAL, pattern TEXT, features TEXT, '
                   'detector_version TEXT)')
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
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS progress_material '
                   'ON progress(scope_user, record_id)')
        db.execute('CREATE TABLE IF NOT EXISTS frames ('
                   'scope_user TEXT NOT NULL, worker_epoch INTEGER NOT NULL, '
                   'sequence INTEGER NOT NULL, at TEXT NOT NULL, '
                   'frame TEXT NOT NULL, PRIMARY KEY(scope_user, worker_epoch, '
                   'sequence))')

    # -- capacity guard (§3.2) -----------------------------------------------
    def _usage_bytes(self):
        with self._connection() as db:
            pages = db.execute('PRAGMA page_count').fetchone()[0]
            size = db.execute('PRAGMA page_size').fetchone()[0]
        return pages * size

    def _meta_int(self, db, key, default):
        row = self._meta(db, key)
        try:
            return int(row) if row is not None else default
        except (TypeError, ValueError):
            return default

    def _capacity_state(self, db):
        paused = self._meta(db, 'capacity_paused') == '1'
        raw = self._meta(db, 'capacity_notice')
        notice = json.loads(raw) if raw else None
        return paused, notice

    def _capacity_allow(self, *, writing):
        """Bounded cadence (>=10s between probes); a persisted pause always
        applies immediately. Hard pause at the byte floor; notices otherwise.
        Growth and free space land in management as low-frequency samples."""
        now = time.monotonic()
        if (self._capacity_checked_at is not None
                and now - self._capacity_checked_at < 10):
            return
        self._capacity_checked_at = now
        with self._connection() as db:
            if self._meta(db, 'capacity_paused') == '1':
                raise CapacityPaused('behavior recording is paused; resume '
                                     'explicitly after freeing space')
        usage = self._usage_bytes()
        free, total = shutil.disk_usage(Path(self._database).parent)[1:3]
        notices = []
        with self._connection() as db:
            tier = self._meta_int(db, 'capacity_tier_reminded', 0)
            reached = usage // self._capacity['remind_tier_bytes']
            if reached >= 1 and reached > tier:
                notices.append({'kind': 'usage_tier', 'usage_bytes': usage})
            if free < self._capacity['low_free_bytes'] or (
                    total and free / total < self._capacity['low_free_ratio']):
                notices.append({'kind': 'disk_low', 'free_bytes': free})
            sample = json.dumps({'at': _utc_iso(self._clock),
                                 'usage_bytes': usage, 'free_bytes': free,
                                 'notices': notices}, ensure_ascii=False)
            key = 'capacity_notice' if notices else 'usage_sample'
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, sample))
            if reached >= 1 and reached > tier:
                db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('capacity_tier_reminded', str(reached)))
        # Persist the pause in its own committed transaction: raising inside
        # the connection context would roll the marker back with it.
        if writing and free < self._capacity['pause_free_bytes']:
            with self._connection() as db:
                db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('capacity_paused', '1'))
            self._capacity_checked_at = None
            raise CapacityPaused('behavior recording paused: disk space '
                                 'below the pause floor')

    def resume_recording(self):
        """Explicit user resume; refused while the byte floor still holds."""
        free, _total = shutil.disk_usage(Path(self._database).parent)[1:3]
        if free < self._capacity['pause_free_bytes']:
            raise CapacityPaused('still below the pause floor; free space first')
        with self._lock, self._connection() as db:
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('capacity_paused', '0'))
            self._bump_revision(db)
        self._capacity_checked_at = None
        return {'status': 'resumed'}

    def _guard_write(self):
        self._capacity_allow(writing=True)
        with self._connection() as db:
            if self._meta(db, 'migration_active') == '1':
                raise MigrationActive('a behavior root migration is running')

    def _pause_on_full(self, error):
        if 'database or disk is full' in str(error).lower():
            with self._connection() as db:
                db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('capacity_paused', '1'))
            raise CapacityPaused('behavior recording paused: disk full') from error
        raise error

    def _reconcile_migration(self, db):
        """Crash recovery per §3.2: after locator_committed the journal and
        the LOCATOR must agree — the pointer file is the authority, so a
        drifted locator refuses to open the migrated library at all."""
        raw = self._meta(db, 'migration_journal')
        if not raw:
            return
        journal = json.loads(raw)
        if journal.get('state') == 'locator_committed':
            if self._locator is not None:
                active_root = str(self._locator.resolve())
            else:
                active_root = str(Path(self._database).resolve().parent)
            if journal.get('destination') != active_root:
                raise ValueError('behavior locator diverges from the '
                                 'migration journal; refusing to guess')
            journal['state'] = 'complete'
            db.execute('UPDATE management SET value=? WHERE key=?',
                       (json.dumps(journal), 'migration_journal'))

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
        self._guard_write()
        try:
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
        except sqlite3.OperationalError as error:
            self._pause_on_full(error)

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
        self._guard_write()
        try:
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
        except sqlite3.OperationalError as error:
            self._pause_on_full(error)

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

    # -- episodes and pattern candidates (P12) -------------------------------
    def record_episode(self, episode, *, scope):
        """Persist one finished detection episode, idempotent on episode_id."""
        if not isinstance(episode, dict):
            raise ValueError('episode required')
        for key in ('episode_id', 'pattern', 'started_at', 'ended_at'):
            if not isinstance(episode.get(key), str) or not episode[key]:
                raise ValueError(f'episode {key} required')
        if 'session' not in episode:
            raise ValueError('episode session required (host-assigned)')
        features = json.dumps(episode.get('features') or {}, ensure_ascii=False)
        if len(features) > 2048:
            raise ValueError('episode features exceed budget')
        user, _ = self._scope(scope)
        with self._lock, self._connection() as db:
            exists = db.execute('SELECT 1 FROM episodes WHERE scope_user=? '
                                'AND episode_id=?',
                                (user, episode['episode_id'])).fetchone()
            if exists:
                return {'status': 'duplicate'}
            db.execute('INSERT INTO episodes(scope_user,episode_id,session,'
                       'started_at,ended_at,effective_seconds,pattern,'
                       'features,detector_version) VALUES(?,?,?,?,?,?,?,?,?)',
                       (user, episode['episode_id'], episode['session'],
                        episode['started_at'], episode['ended_at'],
                        episode.get('effective_seconds'), episode['pattern'],
                        features, episode.get('detector_version')))
            self._bump_revision(db)
            return {'status': 'recorded', 'episode_id': episode['episode_id']}

    def pattern_candidates(self, signature, *, scope):
        """Support counts for one signature: distinct episodes and distinct
        real sessions (the host's session field decides, never the target)."""
        user, _ = self._scope(scope)
        with self._connection() as db:
            row = db.execute(
                'SELECT COUNT(*), COUNT(DISTINCT session) FROM episodes '
                'WHERE scope_user=? AND pattern=?',
                (user, signature)).fetchone()
            confirmed = db.execute(
                'SELECT active FROM patterns WHERE scope_user=? AND '
                'signature=?', (user, signature)).fetchone()
        return {'episodes': row[0] or 0, 'sessions': row[1] or 0,
                'confirmed': bool(confirmed and confirmed[0])}

    def promote_pattern(self, signature, *, scope, derived_version,
                        supports=None):
        """Record a candidate pattern (active=0 until a user confirms it)."""
        user, _ = self._scope(scope)
        pattern_id = hashlib.sha256(
            f'{user}|{signature}'.encode('utf8')).hexdigest()[:24]
        with self._lock, self._connection() as db:
            exists = db.execute('SELECT 1 FROM patterns WHERE scope_user=? '
                                'AND pattern_id=?',
                                (user, pattern_id)).fetchone()
            if exists:
                return {'status': 'duplicate'}
            db.execute('INSERT INTO patterns(scope_user,pattern_id,signature,'
                       'active,supports,sample_count,derived_version) '
                       'VALUES(?,?,?,?,?,?,?)',
                       (user, pattern_id, signature, 0,
                        json.dumps(supports or []), len(supports or []),
                        derived_version))
            self._bump_revision(db)
            return {'status': 'promoted', 'pattern_id': pattern_id}

    def confirmed_patterns(self, *, scope):
        user, _ = self._scope(scope)
        with self._connection() as db:
            rows = db.execute('SELECT signature FROM patterns WHERE '
                              'scope_user=? AND active=1',
                              (user,)).fetchall()
        return [row[0] for row in rows]

    # -- prompts, progress and habits (P13) -----------------------------------
    PROMPT_STATES = ('pending', 'answered', 'dismissed', 'expired',
                     'superseded')

    def record_prompt(self, kind, *, scope, reason=None):
        """Persist a prompt BEFORE it is displayed; pending, with an id.

        The id travels with every display and reply so the host can bind the
        user's answer to exactly what was asked.
        """
        kind = _bounded_label(kind, 'prompt kind')
        user, session = self._scope(scope)
        prompt_id = secrets.token_hex(8)
        at = _utc_iso(self._clock)
        with self._lock, self._connection() as db:
            db.execute('INSERT INTO prompts(scope_user,prompt_id,state,at,'
                       'reason) VALUES(?,?,?,?,?)',
                       (user, prompt_id, 'pending', at, reason))
            self._bump_revision(db)
        return {'prompt_id': prompt_id, 'state': 'pending', 'at': at,
                'kind': kind}

    def set_prompt_state(self, prompt_id, state, *, scope):
        """pending -> answered/dismissed/expired/superseded; one-way."""
        prompt_id = _bounded_label(prompt_id, 'prompt_id')
        if state not in self.PROMPT_STATES or state == 'pending':
            raise ValueError('invalid prompt target state')
        user, _ = self._scope(scope)
        with self._lock, self._connection() as db:
            row = db.execute('SELECT state FROM prompts WHERE scope_user=? '
                             'AND prompt_id=?', (user, prompt_id)).fetchone()
            if row is None:
                raise ValueError('prompt not found')
            if row[0] != 'pending':
                return {'status': 'ignored', 'previous': row[0]}
            db.execute('UPDATE prompts SET state=? WHERE scope_user=? AND '
                       'prompt_id=?', (state, user, prompt_id))
            self._bump_revision(db)
        return {'status': 'updated', 'state': state}

    def expire_pending_prompts(self, *, scope, state='expired'):
        """Restart sweep: old pending prompts never auto-pop; they expire
        (or become superseded when the host explicitly replaces them)."""
        if state not in ('expired', 'superseded'):
            raise ValueError('sweep target must be expired or superseded')
        user, _ = self._scope(scope)
        with self._lock, self._connection() as db:
            count = db.execute(
                "UPDATE prompts SET state=? WHERE scope_user=? AND "
                "state='pending'", (state, user)).rowcount
            if count:
                self._bump_revision(db)
        return {'status': 'swept', 'expired': count}

    def mute_kind(self, kind, *, scope, day=None, mute=True):
        """"Stop asking about this kind": recorded as mute feedback for the
        LOCAL DAY (ignore same kind) or persistently (stop-asking keeps its
        own record; history is never deleted by it). Un-muting removes the
        day record, or every record when no day is given."""
        kind = _bounded_label(kind, 'prompt kind')
        if day is not None:
            _bounded_label(day, 'day key')
        user, _ = self._scope(scope)
        feedback_id = secrets.token_hex(8)
        with self._lock, self._connection() as db:
            if mute:
                db.execute('INSERT INTO feedback(scope_user,feedback_id,'
                           'user_event_id,verdict,corrected,at) '
                           'VALUES(?,?,?,?,?,?)',
                           (user, feedback_id, 'host:'+day,
                            'mute', 'kind:' + kind, _utc_iso(self._clock)))
            else:
                if day is not None:
                    db.execute("DELETE FROM feedback WHERE scope_user=? AND "
                               "verdict='mute' AND corrected=? AND at>=?",
                               (user, 'kind:' + kind, day + 'T00:00:00'))
                else:
                    db.execute("DELETE FROM feedback WHERE scope_user=? AND "
                               "verdict='mute' AND corrected=?",
                               (user, 'kind:' + kind))
            self._bump_revision(db)
        return {'status': 'muted' if mute else 'unmuted', 'kind': kind}

    def kind_muted_today(self, kind, *, scope, day):
        user, _ = self._scope(scope)
        with self._connection() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM feedback WHERE scope_user=? AND "
                "verdict='mute' AND corrected=?", (user, 'kind:' + kind)).fetchone()
            persistent = row[0] or 0
            row = db.execute(
                "SELECT COUNT(*) FROM feedback WHERE scope_user=? AND "
                "verdict='mute' AND corrected=? AND at>=?",
                (user, 'kind:' + kind, day + 'T00:00:00')).fetchone()
        return persistent > 0 or (row[0] or 0) > 0

    def record_progress(self, material_identity, position, *,
                        effective_seconds=None, source, scope):
        """Upsert one material's reliable progress: last visible page/video
        position plus effective observation time. Never a completion claim."""
        user, _ = self._scope(scope)
        record_id = self.material_identity(material_identity)
        at = _utc_iso(self._clock)
        with self._lock, self._connection() as db:
            db.execute('INSERT INTO progress(scope_user,record_id,material,'
                       'position,effective_seconds,source,at) VALUES(?,?,?,?,?,?,?) '
                       'ON CONFLICT(scope_user,record_id) DO UPDATE SET '
                       'position=excluded.position,'
                       'effective_seconds=excluded.effective_seconds,'
                       'source=excluded.source,at=excluded.at',
                       (user, record_id, material_identity[:128],
                        json.dumps(position) if position is not None else None,
                        effective_seconds, source, at))
            self._bump_revision(db)
        return {'status': 'recorded', 'material': record_id, 'position': position}

    def progress_for(self, material_identity, *, scope):
        user, _ = self._scope(scope)
        record_id = self.material_identity(material_identity)
        with self._connection() as db:
            row = db.execute('SELECT position,effective_seconds,source,at '
                             'FROM progress WHERE scope_user=? AND record_id=?',
                             (user, record_id)).fetchone()
        return (None if row is None else
                {'position': json.loads(row[0]) if row[0] else None,
                 'effective_seconds': row[1], 'source': row[2],
                 'at': row[3]})

    def habit_summaries(self, kind, *, scope, limit=3, now=None,
                        half_life_days=90.0):
        """Up to 3 weighted behavior/feedback summaries for one kind.

        Time weight uses a 90-day half-life and only affects RANKING —
        history is never deleted by it. Counter-evidence (correct) counts
        immediately; model-derived entries never appear as confirmed.
        """
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError('habit limit must be 1..10')
        user, _ = self._scope(scope)
        now_epoch = self._clock() if now is None else now
        with self._connection() as db:
            rows = db.execute(
                'SELECT verdict,corrected,at FROM feedback WHERE scope_user=? '
                'AND (corrected LIKE ? OR verdict=?) ORDER BY at DESC '
                'LIMIT 200', (user, 'kind:' + kind, 'mute')).fetchall()
        weighted = {}
        for verdict, corrected, at in rows:
            try:
                from datetime import datetime
                age_days = max(0.0, (now_epoch - datetime.fromisoformat(at)
                                     .timestamp()) / 86400)
            except ValueError:
                continue
            weight = 0.5 ** (age_days / half_life_days)
            if corrected and corrected.startswith('kind:'):
                key = corrected.split(':', 1)[1]
            else:
                key = kind
            entry = weighted.setdefault(key, {'confirm': 0.0, 'mute': 0.0})
            entry[verdict if verdict in ('confirm', 'mute') else 'mute'] += weight
        summaries = [{'kind': key, 'support': round(value['confirm'], 3),
                      'muted': value['mute'] > 0}
                     for key, value in weighted.items()]
        summaries.sort(key=lambda item: item['support'], reverse=True)
        return summaries[:limit]

    # -- input frames (P11) ---------------------------------------------------
    def record_frames(self, batch, *, scope):
        """Transactional InputFeatureFrame persistence, idempotent on
        (scope, worker_epoch, sequence): the same frame replays as a no-op,
        a changed frame is rejected like any event-id reuse."""
        if not isinstance(batch, list) or not batch or len(batch) > 256:
            raise ValueError('bounded frame batch required')
        user, _ = self._scope(scope)
        prepared = []
        for frame in batch:
            if not isinstance(frame, dict) or frame.get('schema') != FRAMES_SCHEMA:
                raise ValueError('unknown frame schema')
            for key in ('worker_epoch', 'sequence'):
                if type(frame.get(key)) is not int or frame[key] < 0:
                    raise ValueError(f'frame {key} required')
            encoded = json.dumps(frame, ensure_ascii=False,
                                 separators=(',', ':'))
            if len(encoded.encode('utf8')) > 16 * 1024:
                raise ValueError('frame exceeds the 16KiB budget')
            prepared.append((frame['worker_epoch'], frame['sequence'],
                             frame.get('observed_to'), encoded))
        with self._lock, self._connection() as db:
            for worker_epoch, sequence, at, encoded in prepared:
                existing = db.execute(
                    'SELECT frame FROM frames WHERE scope_user=? AND '
                    'worker_epoch=? AND sequence=?',
                    (user, worker_epoch, sequence)).fetchone()
                if existing is not None:
                    if existing[0] != encoded:
                        raise ValueError('frame replay with different content')
                    continue
                db.execute('INSERT INTO frames(scope_user,worker_epoch,'
                           'sequence,at,frame) VALUES(?,?,?,?,?)',
                           (user, worker_epoch, sequence, at, encoded))
        return {'status': 'recorded', 'frames': len(prepared)}

    # -- root migration (§3.2) -----------------------------------------------
    @staticmethod
    def _file_digest(path):
        import hashlib
        accumulator = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                accumulator.update(chunk)
        return accumulator.hexdigest()

    def _journal(self, state, destination, **extra):
        with self._connection() as db:
            payload = json.dumps({'state': state,
                                  'destination': str(destination.resolve()),
                                  **extra}, ensure_ascii=False)
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('migration_journal', payload))

    def migrate(self, destination, *, locator, confirmed=False):
        """Move the library to a new dedicated root (§3.2).

        Journal order: prepare → paused → copied → verified →
        locator_committed → complete. The source stays live until the atomic
        locator switch; a failure before the switch leaves the source as the
        only live copy, and after the switch this instance is retired so the
        old path can never be written again (no dual write, no rollback by
        impression). The caller rebuilds the library from the locator.
        """
        if confirmed is not True:
            raise ValueError('migration requires explicit confirmation')
        if self._retired:
            # A retired instance may still ANSWER the idempotency question by
            # reading its journal; it must never write again.
            connection = sqlite3.connect(self._database)
            try:
                row = connection.execute(
                    'SELECT value FROM management WHERE key=?',
                    ('migration_journal',)).fetchone()
            finally:
                connection.close()
            journal = json.loads(row[0]) if row else {}
            # This instance is only retired AFTER the atomic switch, so a
            # source journal at 'verified' with the same destination means
            # the switch already happened for this exact target.
            if journal.get('destination') == str(Path(destination).resolve())                     and journal.get('state') in ('verified', 'locator_committed',
                                                 'complete'):
                return {'status': 'complete', 'idempotent': True,
                        'destination': journal['destination']}
            raise RuntimeError('this behavior library was migrated away; '
                               'rebuild it from the locator')
        with self._connection() as db:
            if self._meta(db, 'migration_active') == '1':
                raise ValueError('a migration is already running')
            raw = self._meta(db, 'migration_journal')
        if raw:
            previous = json.loads(raw)
            if previous.get('state') == 'complete' and \
                    previous.get('destination') == str(Path(destination).resolve()):
                return {'status': 'complete', 'idempotent': True,
                        'destination': previous['destination']}
        destination = locator._validate_destination(
            destination, current=Path(self._database).parent)
        self._journal('prepare', destination)
        with self._connection() as db:
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('migration_active', '1'))
        self._journal('paused', destination)
        try:
            source_lease = locator.lease(Path(self._database).parent).acquire()
            try:
                destination_lease = locator.lease(destination).acquire()
                try:
                    self._journal('copied', destination)
                    with self._connection() as db:
                        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                    destination.mkdir(parents=True, exist_ok=True)
                    manifest = {}
                    base = Path(self._database).name
                    for suffix in ('', '-wal', '-shm'):
                        source_file = Path(self._database + suffix)
                        if source_file.is_file():
                            target = destination/(base + suffix)
                            shutil.copyfile(source_file, target)
                            manifest[target.name] = self._file_digest(target)
                    self._journal('copied', destination, manifest=manifest)
                    self._journal('verified', destination, manifest=manifest)
                    copy_connection = sqlite3.connect(
                        str(destination/base))
                    try:
                        check = copy_connection.execute(
                            'PRAGMA integrity_check').fetchone()[0]
                    finally:
                        copy_connection.close()
                    if check != 'ok':
                        raise ValueError('migrated database failed integrity_check')
                    for name, expected in manifest.items():
                        if self._file_digest(destination/name) != expected:
                            raise ValueError('migrated file hash mismatch')
                    # The destination journal already names its own root as
                    # locator_committed: a crash after the switch reconciles
                    # on the next open, and the source stays retained.
                    copy_db = sqlite3.connect(str(destination/base))
                    try:
                        copy_db.execute(
                            'INSERT INTO management(key,value) VALUES(?,?) '
                            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                            ('migration_journal', json.dumps(
                                {'state': 'locator_committed',
                                 'destination': str(destination.resolve())})))
                        copy_db.commit()
                    finally:
                        copy_db.close()
                finally:
                    destination_lease.release()
            finally:
                source_lease.release()
        except BaseException:
            with self._connection() as db:
                db.execute("DELETE FROM management WHERE key='migration_active'")
            raise
        locator.select(destination, confirmed=True,
                       current=Path(self._database).parent)
        self._retired = True
        return {'status': 'complete', 'destination': str(destination.resolve()),
                'source_retained': True,
                'boundary': 'Rebuild the library instance from the locator; '
                            'the old directory is retained, never deleted.'}

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
            paused, notice = self._capacity_state(db)
        usage = self._usage_bytes()
        free, total = shutil.disk_usage(Path(self._database).parent)[1:3]
        return {'schema_version': int(values.get('schema_version', '0')),
                'revision': int(values.get(_REVISION, '0')),
                'behavior_epoch': int(values.get(_EPOCH, '0')),
                'enabled': values.get(_ENABLED) == '1',
                'events_by_kind': {kind: count for kind, count in counts},
                'capacity': {'usage_bytes': usage, 'free_bytes': free,
                             'paused': paused,
                             'notice': notice,
                             'migration_active':
                                 values.get('migration_active') == '1',
                             'migration_journal': values.get('migration_journal')}}

    def stop(self):
        pass  # Path mode owns no persistent handle.
