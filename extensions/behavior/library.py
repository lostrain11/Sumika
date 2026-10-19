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
from .activity import ActivityQueries


class CapacityPaused(Exception):
    """Recording is hard-paused (disk guard or SQLITE_FULL) until the user
    explicitly resumes; nothing is deleted and nothing claims to be recorded."""


class MigrationActive(Exception):
    """A root migration owns the library; new records fail loudly."""


class RecordingDisabled(Exception):
    """The user disabled new behavior observation and learning."""


DEFAULT_CAPACITY = {'remind_tier_bytes': 5 * 1024 ** 3,
                    'low_free_bytes': 10 * 1024 ** 3,
                    'low_free_ratio': 0.10,
                    'pause_free_bytes': 1 * 1024 ** 3}

SCHEMA_VERSION = 6
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


class BehaviorLibrary(ActivityQueries):
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
        except sqlite3.OperationalError as error:
            connection.rollback()
            if 'database or disk is full' in str(error).lower():
                try:
                    connection.execute('INSERT INTO management(key,value) VALUES(?,?) '
                                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                       ('capacity_paused', '1'))
                    connection.commit()
                except sqlite3.Error:
                    pass
                raise CapacityPaused('behavior recording paused: disk full') from error
            raise
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _prepare(self):
        if self._locator is not None:
            active = self._locator.resolve()
            if active.resolve() != Path(self._database).parent.resolve():
                raise ValueError('behavior database does not match the active locator')
        Path(self._database).parent.mkdir(parents=True, exist_ok=True)
        database = Path(self._database).absolute()
        if database.is_file():
            old = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
            try:
                if old.execute("SELECT 1 FROM sqlite_master WHERE name='management'").fetchone():
                    version = old.execute("SELECT value FROM management WHERE key='schema_version'").fetchone()
                    if version and int(version[0]) < SCHEMA_VERSION:
                        backup = database.with_name(database.name + f'.schema-v{version[0]}-backup.sqlite3')
                        if not backup.exists():
                            temporary = backup.with_name(backup.name + '.' + secrets.token_hex(6) + '.tmp')
                            copied = sqlite3.connect(temporary)
                            try:
                                old.backup(copied)
                                if copied.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                                    raise ValueError('schema migration backup failed integrity_check')
                            finally:
                                copied.close()
                            temporary.replace(backup)
            finally:
                old.close()
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
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
            self._create_schema(db)
            additions = {
                'prompts': ('kind', 'session', 'role_id'),
                'feedback': ('label', 'kind', 'session', 'role_id', 'payload_hash'),
                'episodes': ('event_ids', 'frame_refs', 'payload_hash'),
                'progress': ('event_id', 'episode_id', 'kind'),
            }
            for table, required in additions.items():
                columns = {item[1] for item in db.execute(f'PRAGMA table_info({table})')}
                for column in required:
                    if column not in columns:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
            db.execute("UPDATE management SET value=? WHERE key='schema_version'",
                       (str(SCHEMA_VERSION),))
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('schema_migration_v5', json.dumps({'state': 'complete',
                        'step': 'add feedback labels and source associations'})))
            # Queries use persisted UTC received_at, never worker monotonic at.
            # The normal migration backup above protects existing v5 data.
            db.execute("CREATE INDEX IF NOT EXISTS frames_scope_received ON frames "
                       "(scope_user,json_extract(frame,'$.received_at'))")
            db.execute('CREATE INDEX IF NOT EXISTS events_scope_source_at '
                       'ON events(scope_user,source,at DESC)')
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('schema_migration_v6', json.dumps({'state': 'complete',
                        'step': 'activity source and input received-at indexes'})))
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
        db.execute('CREATE INDEX IF NOT EXISTS episodes_scope_baseline '
                   'ON episodes(scope_user,pattern,detector_version,ended_at DESC)')
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
        disk = shutil.disk_usage(Path(self._database).parent)
        free, total = disk.free, disk.total
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
        free = shutil.disk_usage(Path(self._database).parent).free
        if free < self._capacity['pause_free_bytes']:
            raise CapacityPaused('still below the pause floor; free space first')
        with self._lock, self._connection() as db:
            db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('capacity_paused', '0'))
            self._bump_revision(db)
        self._capacity_checked_at = None
        return {'status': 'resumed'}

    def _guard_write(self, *, recording=True):
        if recording:
            with self._connection() as db:
                if self._meta(db, _ENABLED) != '1':
                    raise RecordingDisabled('behavior recording is disabled')
        self._capacity_allow(writing=True)
        with self._connection() as db:
            if self._meta(db, 'capacity_paused') == '1':
                raise CapacityPaused('behavior recording is paused; resume explicitly')
            if self._meta(db, 'migration_active') == '1':
                raise MigrationActive('a behavior root migration is running')

    @staticmethod
    def _require_sources(db, user, event_id, episode_id):
        for table, field, value in (('events', 'event_id', event_id),
                                    ('episodes', 'episode_id', episode_id)):
            if value is not None and db.execute(
                    f'SELECT 1 FROM {table} WHERE scope_user=? AND {field}=?',
                    (user, value)).fetchone() is None:
                raise ValueError(f'{field} source not found in host scope')

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

    def migrate_legacy_scope(self, legacy_user, *, scope):
        """Host-bound adoption of old project-only records; never merge owners."""
        legacy_user, _ = self._scope({'user': legacy_user})
        user, _ = self._scope(scope)
        if legacy_user == user:
            return {'status': 'unchanged', 'records': 0}
        claim = 'legacy_scope:' + hashlib.sha256(legacy_user.encode('utf8')).hexdigest()
        self._guard_write(recording=False)
        with self._lock, self._connection() as db:
            previous = self._meta(db, claim)
            if previous is not None:
                if previous != user:
                    raise ValueError('legacy scope was already claimed by another host binding')
                return {'status': 'migrated', 'records': 0, 'idempotent': True}
            tables = ('events', 'frames', 'episodes', 'prompts', 'feedback', 'patterns', 'progress')
            if any(db.execute(f'SELECT 1 FROM {table} WHERE scope_user=? LIMIT 1',
                              (user,)).fetchone() for table in tables) or self._meta(db, 'prompt_quota:' + user) is not None:
                raise ValueError('target scope already contains records; explicit reconciliation required')
            count = 0
            for table in tables:
                count += db.execute(f'UPDATE {table} SET scope_user=? WHERE scope_user=?',
                                    (user, legacy_user)).rowcount
            quota = self._meta(db, 'prompt_quota:' + legacy_user)
            if quota is not None:
                db.execute('UPDATE management SET key=? WHERE key=?',
                           ('prompt_quota:' + user, 'prompt_quota:' + legacy_user))
            db.execute('INSERT INTO management(key,value) VALUES(?,?)', (claim, user))
            self._bump_revision(db)
        return {'status': 'migrated', 'records': count}

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
        from .activity import validate_activity
        validate_activity(event)
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
            import math
            if any(type(v) is float and not math.isfinite(v) for v in features.values()):
                raise ValueError('feature numbers must be finite')
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
        """Bind an explicit host user reply to exactly one live prompt."""
        if not isinstance(entry, dict) or set(entry) - {
                'feedback_id', 'user_event_id', 'prompt_id', 'event_id',
                'episode_id', 'original', 'verdict', 'corrected', 'label'}:
            raise ValueError('unknown feedback fields')
        feedback_id = _bounded_label(entry.get('feedback_id'), 'feedback_id')
        user_event_id = _bounded_label(entry.get('user_event_id'), 'user_event_id')
        prompt_id = _bounded_label(entry.get('prompt_id'), 'prompt_id')
        verdict = entry.get('verdict')
        if verdict not in FEEDBACK_VERDICTS:
            raise ValueError('feedback verdict required')
        for field in ('original', 'corrected', 'label'):
            value = entry.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > 2000):
                raise ValueError(f'{field} must be user text within budget')
        label = (entry.get('corrected') or entry.get('label') or '').strip()
        if verdict in ('confirm', 'correct') and not label:
            raise ValueError('confirm/correct requires an explicit user label or corrected text')
        user, session = self._scope(scope)
        payload_hash = self._payload_hash(entry)
        self._guard_write(recording=False)
        with self._lock, self._connection() as db:
            old = db.execute('SELECT payload_hash FROM feedback WHERE scope_user=? '
                             'AND feedback_id=?', (user, feedback_id)).fetchone()
            if old:
                if old[0] != payload_hash:
                    raise ValueError('feedback id reuse with a different payload')
                return {'status': 'duplicate'}
            if db.execute('SELECT 1 FROM feedback WHERE scope_user=? AND user_event_id=?',
                          (user, user_event_id)).fetchone():
                raise ValueError('host user event already bound to feedback')
            prompt = db.execute('SELECT state,at,event_id,episode_id,kind,session,role_id '
                                'FROM prompts WHERE scope_user=? AND prompt_id=?',
                                (user, prompt_id)).fetchone()
            if prompt is None or prompt[0] != 'pending':
                raise ValueError('feedback requires a pending prompt')
            from datetime import datetime
            if self._clock() - datetime.fromisoformat(prompt[1]).timestamp() >= 120:
                db.execute("UPDATE prompts SET state='expired' WHERE scope_user=? AND prompt_id=?",
                           (user, prompt_id))
                self._bump_revision(db)
                db.commit()
                raise ValueError('prompt expired')
            if session is not None and prompt[5] != session:
                raise ValueError('prompt belongs to another session')
            for field, value in (('event_id', prompt[2]), ('episode_id', prompt[3])):
                if entry.get(field) is not None and entry[field] != value:
                    raise ValueError('feedback association differs from host prompt')
            at = _utc_iso(self._clock)
            db.execute('INSERT INTO feedback(scope_user,feedback_id,user_event_id,'
                       'prompt_id,event_id,episode_id,original,verdict,corrected,at,'
                       'label,kind,session,role_id,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (user, feedback_id, user_event_id, prompt_id, prompt[2], prompt[3],
                        entry.get('original'), verdict, entry.get('corrected'), at,
                        label or None, prompt[4], prompt[5], prompt[6], payload_hash))
            db.execute('UPDATE prompts SET state=? WHERE scope_user=? AND prompt_id=?',
                       ('answered' if verdict in ('confirm', 'correct') else 'dismissed',
                        user, prompt_id))
            self._refresh_patterns(db, user)
            self._bump_revision(db)
        return {'status': 'recorded', 'feedback_id': feedback_id, 'at': at,
                'kind': prompt[4], 'event_id': prompt[2], 'episode_id': prompt[3],
                'role_id': prompt[6]}

    def _refresh_patterns(self, db, user):
        # Only explicit, currently valid user labels activate a candidate.
        db.execute('UPDATE patterns SET active=0 WHERE scope_user=?', (user,))
        db.execute("UPDATE patterns SET active=1 WHERE scope_user=? AND signature IN ("
                   "SELECT e.pattern FROM episodes e JOIN feedback f ON "
                   "e.scope_user=f.scope_user AND e.episode_id=f.episode_id "
                   "WHERE f.scope_user=? AND "
                   "f.verdict IN ('confirm','correct') AND length(trim(f.label))>0)",
                   (user, user))

    def correct(self, feedback_id, corrected, *, scope, revision):
        """User correction on an existing verdict; the corrected reading is
        what later recalls must honor."""
        feedback_id = _bounded_label(feedback_id, 'feedback_id')
        if not isinstance(corrected, str) or not corrected.strip() \
                or len(corrected) > 2000:
            raise ValueError('corrected user text required')
        user, _ = self._scope(scope)
        self._guard_write(recording=False)
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            row = db.execute('SELECT 1 FROM feedback WHERE scope_user=? AND '
                             'feedback_id=?', (user, feedback_id)).fetchone()
            if row is None:
                raise ValueError('feedback record not found')
            db.execute('UPDATE feedback SET corrected=?, label=?, verdict=? '
                       'WHERE scope_user=? AND feedback_id=?',
                       (corrected.strip(), corrected.strip(), 'correct', user, feedback_id))
            self._bump_revision(db)
            self._refresh_patterns(db, user)
            return {'status': 'corrected', 'feedback_id': feedback_id}

    def delete_records(self, *, scope, event_ids=(), kinds=(), before=None,
                       all_records=False, confirmed=False, revision=None):
        """Delete the explicit selection and every derived dependent layer."""
        user, session = self._scope(scope)
        if confirmed is not True or type(all_records) is not bool:
            raise ValueError('deletion requires explicit confirmation')
        ids = {_bounded_label(value, 'event_id') for value in event_ids}
        selected_kinds = set(kinds)
        if selected_kinds - set(EVENT_KINDS):
            raise ValueError('unknown behavior kind in deletion')
        from datetime import datetime
        if before is not None:
            try:
                cutoff = datetime.fromisoformat(before).timestamp()
            except (TypeError, ValueError):
                raise ValueError('deletion before-cursor must be an ISO time') from None
        if all_records and (ids or selected_kinds or before is not None):
            raise ValueError('all_records cannot be combined with filters')
        if not all_records and not ids and not selected_kinds and before is None:
            raise ValueError('deletion needs an explicit selection')
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            # Deletion remains available at the capacity floor, but never during migration.
            if self._meta(db, 'migration_active') == '1':
                raise MigrationActive('a behavior root migration is running')
            tables = ('events', 'episodes', 'frames', 'progress', 'prompts', 'feedback', 'patterns')
            if all_records:
                counts = {table: db.execute(f'DELETE FROM {table} WHERE scope_user=?',
                                           (user,)).rowcount for table in tables}
                db.execute('UPDATE management SET value=? WHERE key=?',
                           (str(int(self._meta(db, _EPOCH)) + 1), _EPOCH))
                self._bump_revision(db)
                return {'status': 'deleted', **{'deleted_' + k: v for k, v in counts.items()},
                        'behavior_epoch': int(self._meta(db, _EPOCH))}
            rows = {}
            for table in tables:
                if table == 'frames':
                    rows[table] = []
                    continue
                cur = db.execute(f'SELECT rowid,* FROM {table} WHERE scope_user=?', (user,))
                names = [col[0] for col in cur.description]
                rows[table] = [dict(zip(names, row)) for row in cur.fetchall()]
            def older(value):
                if before is None:
                    return True
                try:
                    try:
                        stamp = float(value)
                    except (TypeError, ValueError):
                        stamp = datetime.fromisoformat(value).timestamp()
                    return stamp < cutoff
                except (TypeError, ValueError):
                    return False
            def matches(row, kind=None, at=None):
                return (not ids or row.get('event_id') in ids) and (not selected_kinds or kind in selected_kinds) and older(at)
            selected_events = {r['event_id'] for r in rows['events'] if all_records or (
                (not session or r['session'] == session) and matches(r, r['kind'], r['at']))}
            selected_episodes = set()
            selected_frames = set()
            for r in rows['episodes']:
                origins = set(json.loads(r['event_ids'] or '[]'))
                if all_records or origins & selected_events or (not ids and
                        (not session or r['session'] == session) and matches(r, r['pattern'], r['ended_at'])):
                    selected_episodes.add(r['episode_id'])
                    selected_frames.update(tuple(ref) for ref in json.loads(r['frame_refs'] or '[]'))
            if all_records or (before is not None and not ids and not selected_kinds):
                # Stream raw frame history instead of materializing it in RAM.
                for epoch, sequence, at in db.execute('SELECT worker_epoch,sequence,at '
                        'FROM frames WHERE scope_user=?', (user,)):
                    if older(at): selected_frames.add((epoch, sequence))
            # A shared frame can invalidate further episodes and their sources.
            changed = True
            while changed:
                changed = False
                for r in rows['episodes']:
                    refs = set(tuple(ref) for ref in json.loads(r['frame_refs'] or '[]'))
                    if r['episode_id'] not in selected_episodes and refs & selected_frames:
                        selected_episodes.add(r['episode_id'])
                        selected_frames.update(refs)
                        changed = True
            for epoch, sequence in selected_frames:
                found = db.execute('SELECT rowid FROM frames WHERE scope_user=? AND '
                                   'worker_epoch=? AND sequence=?', (user, epoch, sequence)).fetchone()
                if found:
                    rows['frames'].append({'rowid': found[0], 'worker_epoch': epoch, 'sequence': sequence})
            selected_prompts = {r['prompt_id'] for r in rows['prompts'] if all_records or
                r['event_id'] in selected_events or r['episode_id'] in selected_episodes or
                (not ids and (not session or r['session'] == session) and matches(r, r['kind'], r['at']))}
            signatures = {r['pattern'] for r in rows['episodes'] if r['episode_id'] in selected_episodes}
            counts = {}
            for table in tables:
                chosen = []
                for r in rows[table]:
                    remove = all_records
                    if table == 'events': remove |= r['event_id'] in selected_events
                    elif table == 'episodes': remove |= r['episode_id'] in selected_episodes
                    elif table == 'frames': remove |= (r['worker_epoch'], r['sequence']) in selected_frames
                    elif table == 'prompts': remove |= r['prompt_id'] in selected_prompts
                    elif table in ('feedback', 'progress'):
                        remove |= r['event_id'] in selected_events or r['episode_id'] in selected_episodes
                        if table == 'feedback': remove |= r['prompt_id'] in selected_prompts
                        remove |= (not ids and matches(r, r.get('kind'), r['at']) and
                                   (not session or r.get('session', session) == session))
                    elif table == 'patterns':
                        supports = json.loads(r['supports'] or '[]')
                        remove |= r['signature'] in signatures or r['signature'] in selected_kinds
                        remove |= any(isinstance(item, str) and item in (selected_events | selected_episodes) for item in supports)
                    if remove: chosen.append(r['rowid'])
                counts[table] = len(chosen)
                for rowid in chosen:
                    db.execute(f'DELETE FROM {table} WHERE rowid=?', (rowid,))
            if not any(counts.values()):
                return {'status': 'nothing_selected', 'deleted_events': 0}
            self._refresh_patterns(db, user)
            db.execute('UPDATE management SET value=? WHERE key=?',
                       (str(int(self._meta(db, _EPOCH)) + 1), _EPOCH))
            self._bump_revision(db)
            return {'status': 'deleted', **{'deleted_' + k: v for k, v in counts.items()},
                    'behavior_epoch': int(self._meta(db, _EPOCH))}

    # -- episodes and pattern candidates (P12) -------------------------------
    def record_episode(self, episode, *, scope, event_ids=None, frame_refs=None):
        """Persist one closed episode; conflicting replays never overwrite it."""
        if not isinstance(episode, dict) or set(episode) - {
                'episode_id', 'pattern', 'started_at', 'ended_at', 'session',
                'effective_seconds', 'features', 'detector_version', 'event_ids', 'frame_refs'}:
            raise ValueError('bounded episode required')
        user, session = self._scope(scope)
        for key in ('episode_id', 'pattern', 'started_at', 'ended_at'):
            _bounded_label(episode.get(key), key)
        if 'session' not in episode or (session is not None and episode['session'] != session):
            raise ValueError('episode session required (host-assigned)')
        self._scope({'user': user, 'session': episode['session']})
        from datetime import datetime
        import math
        start = datetime.fromisoformat(episode['started_at']).timestamp()
        end = datetime.fromisoformat(episode['ended_at']).timestamp()
        seconds = episode.get('effective_seconds')
        if end < start or (seconds is not None and (type(seconds) not in (int, float)
                or not math.isfinite(seconds) or seconds < 0 or seconds > end - start)):
            raise ValueError('episode must be closed with valid effective time')
        features_obj = episode.get('features') or {}
        if not isinstance(features_obj, dict) or len(features_obj) > 32 or any(
                key in _FORBIDDEN for key in features_obj) or any(
                not isinstance(value, (str, int, float, bool)) for value in features_obj.values()):
            raise ValueError('flat bounded episode features required')
        features = json.dumps(features_obj, ensure_ascii=False, sort_keys=True)
        if len(features) > 2048:
            raise ValueError('episode features exceed budget')
        ids = event_ids if event_ids is not None else episode.get('event_ids', [])
        refs = frame_refs if frame_refs is not None else episode.get('frame_refs', [])
        if not isinstance(ids, (list, tuple)) or len(ids) > 256:
            raise ValueError('bounded episode event sources required')
        ids = sorted({_bounded_label(value, 'event_id') for value in ids})
        if not isinstance(refs, (list, tuple)) or len(refs) > 256 or any(
                not isinstance(ref, (list, tuple)) or len(ref) != 2 or
                any(type(value) is not int or value < 0 for value in ref) for ref in refs):
            raise ValueError('bounded episode frame references required')
        refs = sorted(set(tuple(ref) for ref in refs))
        payload = {**episode, 'event_ids': ids, 'frame_refs': refs, 'features': features_obj}
        digest = self._payload_hash(payload)
        self._guard_write()
        with self._lock, self._connection() as db:
            exists = db.execute('SELECT payload_hash FROM episodes WHERE scope_user=? '
                                'AND episode_id=?', (user, episode['episode_id'])).fetchone()
            if exists:
                if exists[0] != digest:
                    raise ValueError('episode id reuse with a different payload')
                return {'status': 'duplicate'}
            for event_id in ids:
                if db.execute('SELECT 1 FROM events WHERE scope_user=? AND event_id=?', (user, event_id)).fetchone() is None:
                    raise ValueError('episode source event not found')
            for epoch, sequence in refs:
                if db.execute('SELECT 1 FROM frames WHERE scope_user=? AND worker_epoch=? AND sequence=?', (user, epoch, sequence)).fetchone() is None:
                    raise ValueError('episode source frame not found')
            db.execute('INSERT INTO episodes(scope_user,episode_id,session,started_at,ended_at,'
                       'effective_seconds,pattern,features,detector_version,event_ids,frame_refs,payload_hash) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (user, episode['episode_id'], episode['session'], episode['started_at'],
                        episode['ended_at'], seconds, episode['pattern'], features,
                        episode.get('detector_version'), json.dumps(ids), json.dumps(refs), digest))
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
        return {'episodes': row[0] or 0, 'sessions': row[1] or 0,
                'confirmed': signature in self.confirmed_patterns(scope=scope)}

    def episode_baseline(self, signature, *, scope, detector_version, limit=200,
                         exclude_episode_id=None):
        """Read previous valid samples before recording the current episode.

        Callers evaluating an already stored episode must explicitly exclude its
        id. Only the host's actual session identity can contribute a baseline.
        """
        import sys
        signature = _bounded_label(signature, 'signature')
        detector_version = _bounded_label(detector_version, 'detector_version')
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('episode baseline limit must be 1..200')
        if exclude_episode_id is not None:
            exclude_episode_id = _bounded_label(exclude_episode_id, 'episode_id')
        user, _ = self._scope(scope)
        with self._connection() as db:
            rows = db.execute(
                "SELECT effective_seconds,session FROM episodes WHERE scope_user=? "
                "AND pattern=? AND detector_version=? AND typeof(effective_seconds) IN ('integer','real') "
                "AND effective_seconds>=0 AND effective_seconds<=? "
                "AND typeof(session)='text' AND length(trim(session)) BETWEEN 1 AND 256 "
                "AND julianday(ended_at)>=julianday(started_at) "
                "AND effective_seconds<=(julianday(ended_at)-julianday(started_at))*86400+.001 "
                "AND (? IS NULL OR episode_id<>?) ORDER BY ended_at DESC,episode_id DESC LIMIT ?",
                (user, signature, detector_version, sys.float_info.max,
                 exclude_episode_id, exclude_episode_id, limit)).fetchall()
        return [{'value': value, 'session': session} for value, session in rows]

    def pattern_supports(self, signature, *, scope, limit=256):
        """Bounded, matching episode source ids for candidate promotion."""
        signature = _bounded_label(signature, 'signature')
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError('pattern support limit must be 1..256')
        user, _ = self._scope(scope)
        with self._connection() as db:
            rows = db.execute('SELECT episode_id FROM episodes WHERE scope_user=? '
                              'AND pattern=? ORDER BY ended_at DESC,episode_id DESC LIMIT ?',
                              (user, signature, limit)).fetchall()
        return [row[0] for row in rows]

    def promote_pattern(self, signature, *, scope, derived_version,
                        supports=None):
        """Record a candidate pattern (active=0 until a user confirms it)."""
        user, _ = self._scope(scope)
        signature = _bounded_label(signature, 'signature')
        derived_version = _bounded_label(derived_version, 'derived_version')
        if supports is not None:
            if not isinstance(supports, list) or len(supports) > 256:
                raise ValueError('at most 256 episode source ids required')
            supports = list(dict.fromkeys(_bounded_label(item, 'episode_id') for item in supports))
        self._guard_write()
        pattern_id = hashlib.sha256(
            f'{user}|{signature}'.encode('utf8')).hexdigest()[:24]
        with self._lock, self._connection() as db:
            if supports is None:
                supports = [row[0] for row in db.execute(
                    'SELECT episode_id FROM episodes WHERE scope_user=? AND pattern=? '
                    'ORDER BY ended_at DESC,episode_id DESC LIMIT 256', (user, signature))]
            else:
                for episode_id in supports:
                    if db.execute('SELECT 1 FROM episodes WHERE scope_user=? AND pattern=? '
                                  'AND episode_id=?', (user, signature, episode_id)).fetchone() is None:
                        raise ValueError('pattern support must reference a matching host episode')
            exists = db.execute('SELECT supports,derived_version FROM patterns WHERE scope_user=? '
                                'AND pattern_id=?',
                                (user, pattern_id)).fetchone()
            if exists:
                if exists == (json.dumps(supports), derived_version):
                    return {'status': 'duplicate'}
                db.execute('UPDATE patterns SET supports=?,sample_count=?,derived_version=? '
                           'WHERE scope_user=? AND pattern_id=?',
                           (json.dumps(supports), len(supports), derived_version, user, pattern_id))
                self._bump_revision(db)
                self._refresh_patterns(db, user)
                return {'status': 'updated', 'pattern_id': pattern_id}
            db.execute('INSERT INTO patterns(scope_user,pattern_id,signature,'
                       'active,supports,sample_count,derived_version) '
                       'VALUES(?,?,?,?,?,?,?)',
                       (user, pattern_id, signature, 0,
                        json.dumps(supports or []), len(supports or []),
                        derived_version))
            self._bump_revision(db)
            self._refresh_patterns(db, user)
            return {'status': 'promoted', 'pattern_id': pattern_id}

    def confirmed_patterns(self, *, scope, role_id=None):
        user, _ = self._scope(scope)
        with self._connection() as db:
            rows = db.execute("SELECT DISTINCT p.signature FROM patterns p JOIN episodes e "
                              "ON p.scope_user=e.scope_user AND p.signature=e.pattern "
                              "JOIN feedback f ON e.scope_user=f.scope_user AND e.episode_id=f.episode_id "
                              "WHERE p.scope_user=? AND p.active=1 AND "
                              "f.verdict IN ('confirm','correct') AND length(trim(f.label))>0 "
                              "AND (f.role_id IS NULL OR f.role_id=?)",
                              (user, role_id)).fetchall()
        return [row[0] for row in rows]

    # -- prompts, progress and habits (P13) -----------------------------------
    PROMPT_STATES = ('pending', 'answered', 'dismissed', 'expired',
                     'superseded')

    def record_prompt(self, kind, *, scope, reason=None, event_id=None,
                      episode_id=None, role_id=None, quota=None):
        """Persist a prompt BEFORE it is displayed; pending, with an id.

        The id travels with every display and reply so the host can bind the
        user's answer to exactly what was asked.
        """
        kind = _bounded_label(kind, 'prompt kind')
        user, session = self._scope(scope)
        if event_id is not None: event_id = _bounded_label(event_id, 'event_id')
        if episode_id is not None: episode_id = _bounded_label(episode_id, 'episode_id')
        if role_id is not None: role_id = _bounded_label(role_id, 'role_id')
        if reason is not None: reason = _bounded_label(reason, 'reason')
        prompt_id = secrets.token_hex(8)
        at = _utc_iso(self._clock)
        self._guard_write()
        with self._lock, self._connection() as db:
            self._require_sources(db, user, event_id, episode_id)
            db.execute('INSERT INTO prompts(scope_user,prompt_id,state,at,'
                       'reason,kind,event_id,episode_id,session,role_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (user, prompt_id, 'pending', at, reason, kind, event_id,
                        episode_id, session, role_id))
            if quota is not None:
                key = 'prompt_quota:' + user
                db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, json.dumps(quota)))
            self._bump_revision(db)
        return {'prompt_id': prompt_id, 'state': 'pending', 'at': at,
                'kind': kind}

    def prompt_states(self, prompt_ids, *, scope):
        """Bounded delivery projection; old event text cannot resurrect a question."""
        if not isinstance(prompt_ids, list) or len(prompt_ids) > 512:
            raise ValueError('bounded prompt identities required')
        ids = list(dict.fromkeys(_bounded_label(item, 'prompt_id') for item in prompt_ids))
        if not ids:
            return {}
        user, session = self._scope(scope)
        from datetime import datetime
        result = dict.fromkeys(ids, 'unavailable')
        marks = ','.join('?' for _ in ids)
        with self._connection() as db:
            rows = db.execute(f'SELECT prompt_id,state,at FROM prompts WHERE scope_user=? '
                f'AND (? IS NULL OR session=?) AND prompt_id IN ({marks})',
                (user, session, session, *ids)).fetchall()
        for identity, state, at in rows:
            if state == 'pending' and self._clock() - datetime.fromisoformat(at).timestamp() >= 120:
                state = 'expired'
            result[identity] = state
        return result

    def prompt_quota(self, *, scope):
        user, _ = self._scope(scope)
        from .prompts import PromptQuota
        with self._connection() as db:
            return PromptQuota.load_state(self._meta(db, 'prompt_quota:' + user))

    def set_prompt_state(self, prompt_id, state, *, scope):
        """pending -> answered/dismissed/expired/superseded; one-way."""
        prompt_id = _bounded_label(prompt_id, 'prompt_id')
        if state not in self.PROMPT_STATES or state == 'pending':
            raise ValueError('invalid prompt target state')
        user, _ = self._scope(scope)
        self._guard_write(recording=False)
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
        self._guard_write(recording=False)
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
        self._guard_write(recording=False)
        with self._lock, self._connection() as db:
            if mute:
                db.execute('INSERT INTO feedback(scope_user,feedback_id,'
                           'user_event_id,verdict,corrected,at,kind) '
                           'VALUES(?,?,?,?,?,?,?)',
                           (user, feedback_id, 'host:'+(day or 'persistent'),
                            'mute', 'kind:' + kind, _utc_iso(self._clock), kind))
            else:
                if day is not None:
                    db.execute("DELETE FROM feedback WHERE scope_user=? AND "
                               "verdict='mute' AND corrected=? AND user_event_id=?",
                               (user, 'kind:' + kind, 'host:' + day))
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
                "verdict='mute' AND corrected=? AND user_event_id='host:persistent'",
                (user, 'kind:' + kind)).fetchone()
            persistent = row[0] or 0
            row = db.execute(
                "SELECT COUNT(*) FROM feedback WHERE scope_user=? AND "
                "verdict='mute' AND corrected=? AND user_event_id=?",
                (user, 'kind:' + kind, 'host:' + day)).fetchone()
        return persistent > 0 or (row[0] or 0) > 0

    def record_progress(self, material_identity, position, *,
                        effective_seconds=None, source, scope, event_id=None,
                        episode_id=None, kind=None):
        """Upsert one material's reliable progress: last visible page/video
        position plus effective observation time. Never a completion claim."""
        user, _ = self._scope(scope)
        if event_id is not None: event_id = _bounded_label(event_id, 'event_id')
        if episode_id is not None: episode_id = _bounded_label(episode_id, 'episode_id')
        if kind is not None: kind = _bounded_label(kind, 'kind')
        source = _bounded_label(source, 'source')
        import math
        if effective_seconds is not None and (type(effective_seconds) not in (int, float) or
                not math.isfinite(effective_seconds) or effective_seconds < 0):
            raise ValueError('progress effective time must be finite and nonnegative')
        if position is not None and (type(position) not in (int, float) or
                not math.isfinite(position) or position < 0):
            raise ValueError('progress position must be a finite page/time value')
        record_id = self.material_identity(material_identity)
        at = _utc_iso(self._clock)
        self._guard_write()
        with self._lock, self._connection() as db:
            self._require_sources(db, user, event_id, episode_id)
            db.execute('INSERT INTO progress(scope_user,record_id,material,'
                       'position,effective_seconds,source,at,event_id,episode_id,kind) VALUES(?,?,?,?,?,?,?,?,?,?) '
                       'ON CONFLICT(scope_user,record_id) DO UPDATE SET '
                       'position=excluded.position,'
                       'effective_seconds=excluded.effective_seconds,'
                       'source=excluded.source,at=excluded.at,event_id=excluded.event_id,'
                       'episode_id=excluded.episode_id,kind=excluded.kind',
                       (user, record_id, record_id,
                        json.dumps(position) if position is not None else None,
                        effective_seconds, source, at, event_id, episode_id, kind))
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

    def habit_summaries(self, kind=None, *, scope, role_id=None, limit=3, now=None,
                        half_life_days=90.0, query=None):
        """History is confirmed evidence; a current interpretation is inferred.

        Match only host-known context, keep legacy/partial evidence in separate
        denominators, and count one physical episode once across n-grams.
        """
        import math
        from datetime import datetime
        if type(limit) is not int or not 1 <= limit <= 3:
            raise ValueError('habit limit must be 1..3')
        if type(half_life_days) not in (float, int) or not math.isfinite(half_life_days) or half_life_days <= 0:
            raise ValueError('positive finite half life required')
        if role_id is not None:
            role_id = _bounded_label(role_id, 'role_id')
        if query is not None and (not isinstance(query, dict) or set(query) - {
                'kind', 'app_name', 'profile_id', 'app_category', 'detector_version'}):
            raise ValueError('invalid activity query')
        user, _ = self._scope(scope)
        now_epoch = self._clock() if now is None else now
        sql = ("SELECT f.label,f.kind,f.role_id,f.at,f.session,f.feedback_id,f.episode_id,"
               "f.event_id,e.features,v.features,e.detector_version,e.pattern "
               "FROM feedback f JOIN prompts p ON f.prompt_id=p.prompt_id AND f.scope_user=p.scope_user "
               "LEFT JOIN episodes e ON e.episode_id=f.episode_id AND e.scope_user=f.scope_user "
               "LEFT JOIN events v ON v.event_id=f.event_id AND v.scope_user=f.scope_user "
               "WHERE f.scope_user=? AND f.verdict IN ('confirm','correct') "
               "AND length(trim(f.label))>0 AND (f.role_id IS NULL OR f.role_id=?) "
               "AND ((f.episode_id IS NOT NULL AND e.episode_id IS NOT NULL) OR "
               "(f.event_id IS NOT NULL AND v.event_id IS NOT NULL) OR "
               "(f.episode_id IS NULL AND f.event_id IS NULL))")
        args = [user, role_id]
        selected_kind = kind or (query or {}).get('kind')
        if selected_kind is not None:
            sql += ' AND f.kind=?'
            args.append(selected_kind)
        sql += ' ORDER BY f.at DESC,f.feedback_id DESC LIMIT 201'
        with self._connection() as db:
            rows = db.execute(sql, args).fetchall()
        truncated = len(rows) > 200
        weighted, seen = {}, set()
        for label, item_kind, item_role, at, session, fid, episode, event, ef, vf, detector, signature in rows[:200]:
            features = json.loads(ef or vf or '{}')
            quality = 'exact'
            # Unassociated old prompts are kept only in the management view.
            if not ef and not vf:
                quality = 'legacy'
            if query is not None:
                missing, known = 0, 0
                conflict = False
                for field in ('app_name', 'profile_id', 'app_category', 'detector_version'):
                    wanted = query.get(field)
                    if not wanted:
                        continue
                    actual = detector if field == 'detector_version' else features.get(field)
                    if not actual:
                        missing += 1
                    elif actual != wanted:
                        conflict = True
                    else:
                        known += 1
                if conflict:
                    continue
                quality = ('legacy' if not known else 'partial') if missing else quality
                if quality == 'legacy':
                    continue  # No basis to predict the current scene.
            base = features.get('base_episode_id') or episode or event or fid
            evidence = (base, item_role)
            if evidence in seen:
                continue
            seen.add(evidence)
            try:
                age = max(0., (now_epoch - datetime.fromisoformat(at).timestamp()) / 86400)
            except (TypeError, ValueError):
                continue
            context = tuple(features.get(k, '') for k in ('profile_id', 'app_name', 'app_category'))
            key = (item_kind, label, item_role, context, quality)
            item = weighted.setdefault(key, {'kind': item_kind, 'label': label,
                'role_id': item_role, 'source': 'user_confirmed', 'evidence_source': 'user_confirmed',
                'current_status': 'inferred', 'support': 0., 'confirmed': True,
                'inferred': True, 'sample_count': 0, 'source_ids': [], '_sessions': set(),
                'match_quality': quality, 'profile_id': context[0], 'app_name': context[1],
                'app_category': context[2], 'last_confirmed_at': at, 'window_limit': 200,
                'truncated': truncated})
            item['support'] += 0.5 ** (age / half_life_days)
            item['sample_count'] += 1
            item['source_ids'].append(fid)
            if session:
                item['_sessions'].add(session)
        totals = {}
        for key, item in weighted.items():
            group = (key[0], key[2], key[3], key[4])
            totals[group] = totals.get(group, 0.) + item['support']
        for key, item in weighted.items():
            group = (key[0], key[2], key[3], key[4])
            item['support_ratio'] = round(item['support'] / totals[group], 3)
            item['session_count'] = len(item.pop('_sessions'))
            item['stable'] = (item['match_quality'] == 'exact' and item['sample_count'] >= 3
                              and item['session_count'] >= 2 and item['support_ratio'] >= .8)
            item['weighted_support'] = item['support'] = round(item['support'], 3)
            item['source_total'] = len(item['source_ids'])
            item['source_ids'] = item['source_ids'][:3]
        return sorted(weighted.values(), key=lambda i: (
            {'exact': 2, 'partial': 1, 'legacy': 0}[i['match_quality']], i['support']), reverse=True)[:limit]

    # -- input frames (P11) ---------------------------------------------------
    def record_frames(self, batch, *, scope):
        """Transactional InputFeatureFrame persistence, idempotent on
        (scope, worker_epoch, sequence): the same frame replays as a no-op,
        a changed frame is rejected like any event-id reuse."""
        if not isinstance(batch, list) or not batch or len(batch) > 256:
            raise ValueError('bounded frame batch required')
        user, _ = self._scope(scope)
        self._guard_write()
        prepared = []
        for frame in batch:
            if not isinstance(frame, dict) or frame.get('schema') != FRAMES_SCHEMA:
                raise ValueError('unknown frame schema')
            from .input_features import validate_frame
            validate_frame(frame, user_scope=user)
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
        source = Path(self._database).parent
        if locator.resolve().resolve() != source.resolve():
            raise ValueError('migration source differs from active locator')
        destination = locator._validate_destination(destination, current=source)
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('migration requires a new empty dedicated destination')
        from contextlib import ExitStack
        from tools.backup_personal_data import inventory
        with self._lock, ExitStack() as stack:
            held = locator.lease(source).acquire()
            stack.callback(held.release)
            # Acquire both writers before marking migration active. A failed
            # lease leaves the existing active library and locator untouched.
            target = locator.lease(destination).acquire()
            stack.callback(target.release)
            switched = False
            try:
                self._journal('prepare', destination)
                with self._connection() as db:
                    db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                               'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               ('migration_active', '1'))
                self._journal('paused', destination)
                with self._connection() as db:
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                before = inventory(source)
                for relative in before:
                    copied = destination/relative
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source/relative, copied)
                if inventory(source) != before or inventory(destination) != before:
                    raise ValueError('behavior migration copy changed or failed hash verification')
                self._journal('copied', destination, manifest=before)
                base = Path(self._database).name
                copy_db = sqlite3.connect(str(destination/base))
                try:
                    if copy_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('migrated database failed integrity_check')
                    copy_db.execute("DELETE FROM management WHERE key='migration_active'")
                    copy_db.execute('INSERT INTO management(key,value) VALUES(?,?) '
                                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                    ('migration_journal', json.dumps({'state': 'locator_committed',
                                     'destination': str(destination.resolve())})))
                    copy_db.commit()
                finally:
                    copy_db.close()
                self._journal('verified', destination, manifest=before)
                locator._commit_selection(destination)
                switched = True
                self._retired = True
            except BaseException:
                # Atomic replacement might have succeeded before an I/O error
                # surfaced. Reconcile the actual locator before allowing writes.
                try:
                    switched = locator.resolve().resolve() == destination.resolve()
                except (OSError, ValueError):
                    self._retired = True
                    raise
                if switched:
                    self._retired = True
                else:
                    with self._connection() as db:
                        db.execute("DELETE FROM management WHERE key='migration_active'")
                raise
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

    def context(self, *, scope, limit=3, role_id=None, query=None):
        """Confirmed label evidence; recent observations stay explicitly inferred."""
        if type(limit) is not int or not 1 <= limit <= 3:
            raise ValueError('context limit must be 1..3')
        summaries = (self.habit_summaries(scope=scope, role_id=role_id, limit=limit, query=query)
                     if query else [])
        if len(summaries) == limit:
            return summaries
        user, session = self._scope(scope)
        with self._connection() as db:
            rows = db.execute('SELECT at,kind,target,material FROM events WHERE '
                              'scope_user=? AND (? IS NULL OR session=?) '
                              'ORDER BY at DESC,event_id DESC LIMIT ?',
                              (user, session, session, limit - len(summaries))).fetchall()
        return summaries + [{'at': r[0], 'kind': r[1], 'target': r[2], 'material': r[3],
                             'source': 'observed', 'current_status': 'observed',
                             'confirmed': False, 'inferred': False} for r in rows]

    def export(self, *, scope):
        """Export every user-owned layer; management secrets never leave the store."""
        user, _ = self._scope(scope)
        result = {'schema_version': SCHEMA_VERSION, 'scope_user': user}
        with self._connection() as db:
            for table in ('events', 'frames', 'episodes', 'prompts', 'feedback', 'patterns', 'progress'):
                cur = db.execute(f'SELECT * FROM {table} WHERE scope_user=?', (user,))
                names = [col[0] for col in cur.description]
                result[table] = [dict(zip(names, row)) for row in cur.fetchall()]
            result['behavior_epoch'] = int(self._meta(db, _EPOCH))
            result['management'] = {key: self._meta(db, key) for key in
                                    ('schema_version', _REVISION, _EPOCH, _ENABLED)}
            quota = self._meta(db, 'prompt_quota:' + user)
            if quota is not None:
                result['management']['prompt_quota'] = json.loads(quota)
        return result

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
        disk = shutil.disk_usage(Path(self._database).parent)
        free, total = disk.free, disk.total
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
