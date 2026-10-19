"""Domain queries over the existing behavior store, never a second memory DB.

Collectors own observation events; only explicit management actions create user
declarations. These two sources must never be interchangeable with inference.
"""
import json
import math
import uuid
import unicodedata
from datetime import datetime, timedelta, timezone

DECLARATION_TYPES = ('interest', 'preference', 'goal', 'constraint', 'routine')
LAYERS = ('events', 'episodes', 'feedback', 'patterns', 'progress', 'prompts')


def validate_activity(event):
    """Closed, versioned host source payloads inside the shared envelope."""
    source, f = event.get('source'), event.get('features') or {}
    if source == 'user-declaration-v1':
        raise ValueError('user declarations require the explicit management action')
    if source != 'foreground-v1':
        return
    expected = {'slice_version', 'started_at', 'ended_at', 'effective_seconds',
                'app_name', 'profile_id', 'local_date', 'local_hour',
                'utc_offset_minutes', 'quality', 'switch_count'}
    if event.get('kind') != 'app_focus' or set(f) != expected or f['slice_version'] != 1:
        raise ValueError('invalid foreground slice schema')
    seconds = f['effective_seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 60:
        raise ValueError('slice duration must be finite and <=60 seconds')
    start, end = (datetime.fromisoformat(f[key]) for key in ('started_at', 'ended_at'))
    if start.tzinfo is None or end.tzinfo is None or not 0 < (end - start).total_seconds() <= 60.01:
        raise ValueError('invalid slice wall interval')
    if abs((end - start).total_seconds() - seconds) > .01:
        raise ValueError('slice duration differs from verified interval')
    if (not isinstance(f['app_name'], str) or not 1 <= len(f['app_name']) <= 128
            or any(c in f['app_name'] for c in ('/', '\\', ':'))
            or f['quality'] != 'verified_foreground' or type(f['switch_count']) is not int
            or f['switch_count'] not in (0, 1) or type(f['local_hour']) is not int
            or not 0 <= f['local_hour'] <= 23 or type(f['utc_offset_minutes']) is not int
            or not -840 <= f['utc_offset_minutes'] <= 840
            or not isinstance(f['profile_id'], str) or len(f['profile_id']) > 128):
        raise ValueError('invalid foreground metadata')
    datetime.strptime(f['local_date'], '%Y-%m-%d')


def split_interval(start, end):
    """Split short verified wall intervals at local hour/day/DST boundaries."""
    cursor = start
    while cursor < end:
        local = datetime.fromtimestamp(cursor).astimezone()
        # Tick intervals are <=3s: per-second splitting also handles DST
        # without assuming every local day is 86400 seconds.
        stop = min(end, math.floor(cursor) + 1)
        yield cursor, stop, local.strftime('%Y-%m-%d'), local.hour, int(local.utcoffset().total_seconds() / 60)
        cursor = stop


class ActivityQueries:
    """Mixed into BehaviorLibrary to reuse its lock, guards and transactions."""

    def daily_summary(self, *, scope, days=7):
        if type(days) is not int or not 1 <= days <= 31:
            raise ValueError('summary days must be 1..31')
        user, _ = self._scope(scope)
        since = (datetime.fromtimestamp(self._clock()).astimezone().date()
                 - timedelta(days=days - 1)).isoformat()
        # Aggregate inside SQLite; no raw history materialized in the UI.
        with self._connection() as db:
            rows = db.execute("SELECT json_extract(features,'$.local_date'), "
                "json_extract(features,'$.local_hour'), json_extract(features,'$.app_name'), "
                "json_extract(features,'$.profile_id'), "
                "SUM(json_extract(features,'$.effective_seconds')),COUNT(*), "
                "SUM(COALESCE(json_extract(features,'$.switch_count'),0)) "
                "FROM events WHERE scope_user=? AND kind='app_focus' "
                "AND source='foreground-v1' AND at>=? AND json_extract(features,'$.local_date')>=? "
                "GROUP BY 1,2,3,4 ORDER BY 1 DESC,5 DESC LIMIT 1001",
                (user, (datetime.fromtimestamp(self._clock(), timezone.utc) - timedelta(days=days+1)).isoformat(), since)).fetchall()
            counts = dict(db.execute('SELECT kind,COUNT(*) FROM events WHERE scope_user=? GROUP BY kind', (user,)))
            latest = db.execute('SELECT MAX(at) FROM events WHERE scope_user=?', (user,)).fetchone()[0]
        truncated = len(rows) > 1000
        total = sum(row[4] or 0 for row in rows)
        switches = sum(row[6] or 0 for row in rows)
        if truncated:
            # Truncation limits rendered groups, never the numeric total.
            with self._connection() as db:
                total, switches = db.execute("SELECT SUM(json_extract(features,'$.effective_seconds')), "
                    "SUM(COALESCE(json_extract(features,'$.switch_count'),0)) FROM events "
                    "WHERE scope_user=? AND source='foreground-v1' AND kind='app_focus' "
                    "AND at>=? AND json_extract(features,'$.local_date')>=?",
                    (user, (datetime.fromtimestamp(self._clock(), timezone.utc)-timedelta(days=days+1)).isoformat(), since)).fetchone()
        rows = rows[:1000]
        return {'days': days, 'since': since, 'effective_seconds': round(total, 2),
                'switch_count': switches or 0,
                'buckets': [{'date': r[0], 'hour': r[1], 'app_name': r[2],
                             'profile_id': r[3], 'effective_seconds': round(r[4] or 0, 2),
                             'slices': r[5], 'switch_count': r[6] or 0} for r in rows],
                'truncated': truncated, 'events_by_kind': counts,
                'last_recorded_at': latest, 'source': 'observed',
                'coverage': 'verified_foreground_intervals; not attention or total computer usage'}

    def declarations(self, *, scope, role_id=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('declaration limit must be 1..100')
        user, _ = self._scope(scope)
        with self._connection() as db:
            rows = db.execute("SELECT event_id,at,features FROM events WHERE scope_user=? "
                "AND kind='note' AND source='user-declaration-v1' "
                "AND (json_extract(features,'$.role_id')='' OR json_extract(features,'$.role_id')=?) "
                "ORDER BY at DESC,event_id DESC LIMIT ?", (user, role_id or '', limit + 1)).fetchall()
        return {'records': [{'event_id': r[0], 'at': r[1], **json.loads(r[2]),
                             'source': 'user_declared', 'confirmed': True, 'inferred': False}
                            for r in rows[:limit]], 'has_more': len(rows) > limit}

    def declare(self, declaration, *, scope, role_id=None, revision, event_id=None):
        if not isinstance(declaration, dict) or set(declaration) - {'type', 'label', 'polarity'}:
            raise ValueError('bounded user declaration required')
        kind, label = declaration.get('type'), declaration.get('label')
        polarity = declaration.get('polarity', 'positive')
        if kind not in DECLARATION_TYPES or polarity not in ('positive', 'negative'):
            raise ValueError('invalid declaration type or polarity')
        if not isinstance(label, str) or not label.strip() or len(label) > 256 or any(ord(c) < 32 for c in label):
            raise ValueError('declaration label must be 1..256 visible characters')
        if role_id is not None and (not isinstance(role_id, str) or not 1 <= len(role_id) <= 256):
            raise ValueError('invalid declaration role')
        user, session = self._scope(scope)
        self._guard_write(recording=False)
        original_label = label.strip()
        label = unicodedata.normalize('NFKC', original_label).strip()
        if not label or len(label) > 256:
            raise ValueError('normalized declaration exceeds budget')
        features = {'type': kind, 'label': original_label, 'normalized_label': label, 'polarity': polarity,
                    'role_id': role_id or '', 'version': 1}
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            duplicate = db.execute("SELECT event_id,features FROM events WHERE scope_user=? "
                "AND source='user-declaration-v1' AND json_extract(features,'$.type')=? "
                "AND COALESCE(json_extract(features,'$.normalized_label'),json_extract(features,'$.label'))=? "
                "AND json_extract(features,'$.role_id')=?",
                (user, kind, label, role_id or '')).fetchone()
            if duplicate and duplicate[0] != event_id:
                if json.loads(duplicate[1]).get('polarity') == polarity:
                    return {'status': 'duplicate', 'event_id': duplicate[0]}
                raise ValueError('declaration already exists; edit its current record')
            if event_id is not None:
                row = db.execute("SELECT features FROM events WHERE scope_user=? AND event_id=? "
                    "AND kind='note' AND source='user-declaration-v1'", (user, event_id)).fetchone()
                if row is None:
                    raise ValueError('declaration not found')
                old = json.loads(row[0])
                if old.get('role_id', '') != (role_id or ''):
                    raise ValueError('declaration belongs to another role')
                features['version'] = old.get('version', 1) + 1
                # The superseded assertion must never survive as active memory.
                db.execute('DELETE FROM events WHERE scope_user=? AND event_id=?', (user, event_id))
            event_id = event_id or uuid.uuid4().hex
            payload = {'event_id': event_id, 'kind': 'note', 'source': 'user-declaration-v1',
                       'app_category': None, 'target': None, 'material': None, 'features': features}
            at = datetime.fromtimestamp(self._clock(), timezone.utc).isoformat()
            db.execute('INSERT INTO events(scope_user,event_id,session,epoch,at,kind,source,features,payload_hash) '
                       'VALUES(?,?,?,?,?,?,?,?,?)', (user, event_id, session or '',
                       int(self._meta(db, 'behavior_epoch')), at, 'note', 'user-declaration-v1',
                       json.dumps(features, ensure_ascii=False), self._payload_hash(payload)))
            self._bump_revision(db)
        return {'status': 'recorded', 'event_id': event_id}

    def forget_declaration(self, event_id, *, scope, role_id=None, revision):
        user, _ = self._scope(scope)
        # Forget remains possible at the disk guard, just like delete_records.
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            if self._meta(db, 'migration_active') == '1':
                raise ValueError('behavior root migration is running')
            changed = db.execute("DELETE FROM events WHERE scope_user=? AND event_id=? "
                "AND source='user-declaration-v1' AND kind='note' "
                "AND COALESCE(json_extract(features,'$.role_id'),'')=?",
                (user, event_id, role_id or '')).rowcount
            if not changed:
                raise ValueError('declaration not found in this scope')
            self._bump_revision(db)
        return {'status': 'deleted'}

    def forget_feedback(self, feedback_id, *, scope, revision):
        user, _ = self._scope(scope)
        with self._lock, self._connection() as db:
            self._require_revision(db, revision)
            if self._meta(db, 'migration_active') == '1':
                raise ValueError('behavior root migration is running')
            if not db.execute('DELETE FROM feedback WHERE scope_user=? AND feedback_id=?',
                              (user, feedback_id)).rowcount:
                raise ValueError('feedback not found')
            self._refresh_patterns(db, user)
            self._bump_revision(db)
        return {'status': 'deleted'}

    def activity_overview(self, *, scope, days=7):
        summary = self.daily_summary(scope=scope, days=days)
        user, _ = self._scope(scope)
        cutoff = (datetime.fromtimestamp(self._clock(), timezone.utc) - timedelta(days=days)).isoformat()
        apps = {}
        for b in summary['buckets']:
            item = apps.setdefault(b['app_name'], {'app_name': b['app_name'], 'seconds': 0., 'dates': set()})
            item['seconds'] += b['effective_seconds']
            item['dates'].add(b['date'])
        affinity = [{'app_name': v['app_name'], 'observed_seconds': round(v['seconds'], 2),
                     'day_count': len(v['dates']), 'status': 'inferred',
                     'meaning': 'repeated_activity; preference_unknown'} for v in apps.values() if len(v['dates']) >= 3]
        with self._connection() as db:
            # Frames retain received_at in UTC; their numeric at is monotonic,
            # and must never be interpreted as a wall date.
            operations = db.execute("SELECT json_extract(j.value,'$.kind'),SUM(json_extract(j.value,'$.count')) "
                "FROM frames f,json_each(f.frame,'$.semantic_ops') j "
                "WHERE f.scope_user=? AND json_extract(f.frame,'$.received_at')>=? "
                "GROUP BY 1 LIMIT 32", (user, cutoff)).fetchall()
            quality = db.execute("SELECT json_extract(frame,'$.focus_quality'),COUNT(*), "
                "SUM(COALESCE(json_extract(frame,'$.dropped_count'),0)) FROM frames "
                "WHERE scope_user=? AND json_extract(frame,'$.received_at')>=? GROUP BY 1 LIMIT 10",
                (user, cutoff)).fetchall()
            feature_counts = {}
            for name, path in (('key_categories', '$.keys.counts'), ('shortcuts', '$.shortcuts'),
                               ('mouse', '$.mouse')):
                # Flat category totals only: grid coordinates and raw keys are
                # never included in summary/context results.
                feature_counts[name] = dict(db.execute(
                    "SELECT j.key,SUM(j.value) FROM frames f,json_each(f.frame,?) j "
                    "WHERE f.scope_user=? AND json_extract(f.frame,'$.received_at')>=? "
                    "AND j.type IN ('integer','real') GROUP BY j.key LIMIT 32", (path, user, cutoff)))
            feature_counts['scroll'] = {axis: dict(db.execute(
                "SELECT j.key,SUM(j.value) FROM frames f,json_each(f.frame,?) j "
                "WHERE f.scope_user=? AND json_extract(f.frame,'$.received_at')>=? "
                "AND j.type IN ('integer','real') GROUP BY j.key LIMIT 8",
                ('$.scroll.' + axis, user, cutoff))) for axis in ('vertical', 'horizontal')}
            cur = db.execute('SELECT record_id,material,position,effective_seconds,source,at '
                             'FROM progress WHERE scope_user=? ORDER BY at DESC LIMIT 10', (user,))
            progress = [{'record_id': r[0], 'material': r[1], 'position': json.loads(r[2]) if r[2] else None,
                         'effective_seconds': r[3], 'source': r[4], 'at': r[5]} for r in cur]
        return {**summary, 'activity_affinity': affinity[:20], 'operations': dict(operations),
                'input_quality': [{'quality': r[0], 'frames': r[1], 'dropped': r[2]} for r in quality],
                'feature_counts': feature_counts, 'progress': progress,
                'affinity_truncated': summary['truncated']}

    def list_layer(self, layer, *, scope, cursor=0, limit=30):
        if layer not in LAYERS or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('bounded known layer required')
        if type(cursor) is not int or cursor < 0:
            raise ValueError('invalid layer cursor')
        user, _ = self._scope(scope)
        with self._connection() as db:
            query = db.execute(f'SELECT rowid,* FROM {layer} WHERE scope_user=? AND (?=0 OR rowid<?) '
                               'ORDER BY rowid DESC LIMIT ?', (user, cursor, cursor, limit + 1))
            names = [item[0] for item in query.description]
            rows = [dict(zip(names, row)) for row in query]
        records = rows[:limit]
        next_cursor = records[-1]['rowid'] if len(rows) > limit else None
        for item in records:
            item.pop('rowid', None)
            item.pop('scope_user', None)
            item.pop('payload_hash', None)
            for key in ('features', 'supports', 'counterexamples', 'event_ids', 'frame_refs', 'position'):
                if isinstance(item.get(key), str):
                    try:
                        item[key] = json.loads(item[key])
                    except ValueError:
                        pass
        return {'records': records, 'next_cursor': next_cursor}
