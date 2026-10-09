"""Explicit study notes with provenance; separate from long-term memory.

A note is saved only on an explicit user action and always carries the
observation source it was saved from (tab/video moment/PDF page). Screen
content never lands here automatically, and this store is never read by the
memory engine.
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager


class StudyNotes:
    def __init__(self, database, *, max_note_chars=8000, clock=time.time):
        self.max_note_chars = max_note_chars
        self._clock = clock
        self._lock = threading.Lock()
        if isinstance(database, sqlite3.Connection):
            self.db = database
            self._owns_connection = False
        else:
            # Path mode connects per operation: a bridge-held sqlite handle
            # must not keep personal-data directories busy on Windows.
            self.db = None
            self._database = database
            self._owns_connection = True

    @staticmethod
    def _create(db):
        db.execute('CREATE TABLE IF NOT EXISTS study_notes '
                   '(id INTEGER PRIMARY KEY, created_at TEXT, target TEXT, '
                   'text TEXT, source TEXT)')
        db.commit()

    @contextmanager
    def _connection(self):
        if self.db is not None:
            yield self.db
            return
        connection = sqlite3.connect(self._database)
        try:
            self._create(connection)
            yield connection
        finally:
            connection.close()

    def save(self, text, *, target, source):
        """Persist one explicit note; provenance is required, never guessed."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError('note text required')
        if len(text) > self.max_note_chars:
            raise ValueError('note exceeds the saved-note budget')
        if not isinstance(target, str) or not target.strip() or len(target) > 512:
            raise ValueError('note target required (learning observation target)')
        if source is None:
            source = {}
        if not isinstance(source, dict):
            raise ValueError('note source must be the observation provenance object')
        encoded = json.dumps(source, ensure_ascii=False)
        if len(encoded) > 4096:
            raise ValueError('note provenance exceeds budget')
        created = datetime_utc_iso(self._clock())
        with self._lock, self._connection() as db:
            cursor = db.execute(
                'INSERT INTO study_notes(created_at,target,text,source) VALUES(?,?,?,?)',
                (created, target.strip(), text.strip(), encoded))
            db.commit()
            identifier = cursor.lastrowid
        return {'status': 'saved', 'id': identifier,
                'created_at': created, 'target': target.strip()}

    def recent(self, *, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('note list limit out of range')
        with self._lock, self._connection() as db:
            rows = db.execute(
                'SELECT id,created_at,target,text,source FROM study_notes '
                'ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [{'id': row[0], 'created_at': row[1], 'target': row[2],
                 'text': row[3], 'source': json.loads(row[4])} for row in rows]

    def close(self):
        pass  # Path mode owns no persistent handle; connection mode is caller-owned.


def datetime_utc_iso(epoch_seconds):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


class DanmakuBuffer:
    """Local-rule dedup for scrolling comments; never a model call.

    Same normalized text inside the window collapses to one entry; the buffer
    is bounded and its content is side-channel material, never course facts.
    A summarizer hook may consume it asynchronously; failure only drops the
    summary and never touches the question loop.
    """

    def __init__(self, *, window_seconds=120, max_entries=200, clock=time.monotonic):
        if type(window_seconds) is not int or not 10 <= window_seconds <= 3600:
            raise ValueError('danmaku dedup window out of range')
        if type(max_entries) is not int or not 10 <= max_entries <= 2000:
            raise ValueError('danmaku buffer bound out of range')
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = {}  # normalized text -> (first_seen, count)

    @staticmethod
    def _normalize(text):
        return ''.join(str(text).split())

    def observe(self, texts):
        """Accept one snapshot's danmaku texts; return newly seen entries."""
        if not isinstance(texts, list):
            raise ValueError('danmaku snapshot must be a list')
        now = self._clock()
        fresh = []
        with self._lock:
            self._entries = {text: entry for text, entry in self._entries.items()
                             if now - entry[0] < self.window_seconds}
            for value in texts:
                if not isinstance(value, str):
                    continue
                normalized = self._normalize(value)
                if not normalized:
                    continue
                entry = self._entries.get(normalized)
                if entry is None:
                    if len(self._entries) >= self.max_entries:
                        oldest = min(self._entries, key=lambda key: self._entries[key][0])
                        del self._entries[oldest]
                    self._entries[normalized] = (now, 1)
                    fresh.append(value.strip())
                else:
                    self._entries[normalized] = (entry[0], entry[1] + 1)
        return fresh

    def snapshot_texts(self):
        with self._lock:
            return [text for text, _ in self._entries.values()]
