"""Durable single-admission boundary for host-approved browser submissions.

Callbacks belong to the trusted site adapter, never to a browser request body.
An acknowledgement only proves submission, not a completed model response.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ConsultationJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS consultations (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS consultation_steps (
                request_id TEXT NOT NULL, stage TEXT NOT NULL, at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS consultation_responses (
                request_id TEXT PRIMARY KEY, context TEXT NOT NULL,
                result TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS consultation_lanes (
                lane TEXT PRIMARY KEY, request_id TEXT NOT NULL)''')
            # Seed active response-aware requests created before lane admission
            # was introduced. Legacy records without binding evidence stay as-is.
            for request_id, raw in db.execute('''SELECT r.request_id,r.context
                    FROM consultation_responses r JOIN consultations c ON c.id=r.request_id
                    WHERE c.state!='completed' ORDER BY c.rowid''').fetchall():
                binding = json.loads(raw)['binding']
                db.execute('INSERT OR IGNORE INTO consultation_lanes VALUES (?,?)',
                           (self._lane(binding), request_id))

    @staticmethod
    def _lane(binding):
        return json.dumps([binding[k] for k in ('browser_instance_id','agent_window_id','tab_id')])

    def note(self, request_id, stage):
        if stage not in ('checking','filling','waiting_ready','clicking','acknowledged','interrupted'):
            raise ValueError('invalid consultation stage')
        with self._db() as db:
            if not db.execute('SELECT 1 FROM consultations WHERE id=?',(request_id,)).fetchone():
                raise KeyError('unknown consultation request')
            db.execute('INSERT INTO consultation_steps VALUES (?,?,?)',(request_id,stage,self._now()))

    def _db(self):
        # A connection per operation permits independent host request threads.
        from contextlib import closing
        return closing(sqlite3.connect(self.path, timeout=15, isolation_level=None))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def status(self, request_id):
        with self._db() as db:
            row = db.execute('SELECT state, updated_at FROM consultations WHERE id=?',
                             (request_id,)).fetchone()
            steps = [r[0] for r in db.execute('SELECT stage FROM consultation_steps WHERE request_id=? ORDER BY rowid',(request_id,))]
        if row is None:
            raise KeyError('unknown consultation request')
        result = {'request_id': request_id, 'state': row[0], 'updated_at': row[1], 'steps':steps}
        with self._db() as db:
            response = db.execute('SELECT result FROM consultation_responses WHERE request_id=?', (request_id,)).fetchone()
        if response:
            result['response'] = json.loads(response[0])
        return result

    def response_context(self, request_id):
        with self._db() as db:
            row = db.execute('SELECT context FROM consultation_responses WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            raise ValueError('no pre-submission baseline; historical evidence cannot be backfilled')
        return json.loads(row[0])

    def collect(self, request_id, *, binding, capture):
        """Read-only host adapter callback; never dispatch/retry a submission."""
        from .consultation_response import correlate
        context = self.response_context(request_id)
        if context['binding'] != binding:
            raise PermissionError('response binding changed')
        status = self.status(request_id)
        if status['state'] in ('completed', 'cancelled'):
            return status
        try:
            snapshot = capture()
        except Exception:
            snapshot = None
        # Re-read under the write transaction: cancellation and concurrent
        # collectors cannot overwrite a terminal result or a pinned thread.
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                state = db.execute('SELECT state FROM consultations WHERE id=?', (request_id,)).fetchone()[0]
                if state not in ('completed', 'cancelled'):
                    context = json.loads(db.execute('SELECT context FROM consultation_responses WHERE request_id=?', (request_id,)).fetchone()[0])
                    result = correlate(context, snapshot)
                    if result.get('thread_url'):
                        context['thread_url'] = result['thread_url']
                    db.execute('UPDATE consultation_responses SET context=?,result=? WHERE request_id=?',
                               (json.dumps(context), json.dumps(result, ensure_ascii=False), request_id))
                    if result['state'] == 'completed':
                        db.execute("UPDATE consultations SET state='completed',updated_at=? WHERE id=?", (self._now(), request_id))
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        return self.status(request_id)

    def cancel(self, request_id):
        self.status(request_id)
        with self._db() as db:
            db.execute("UPDATE consultations SET state='cancelled',updated_at=? WHERE id=? AND state IN ('unknown','submitted')", (self._now(), request_id))
        return {**self.status(request_id), 'boundary': 'Local cancellation only; remote generation may continue. Do not replay.'}

    def submit(self, request_id, *, site, prompt, binding, approved, preflight, dispatch, capture=None):
        if approved is not True:
            raise PermissionError('explicit submission approval required')
        if any(not isinstance(v, str) or not v.strip() for v in (request_id, site, prompt)):
            raise ValueError('request identity, site and prompt required')
        if not isinstance(binding, dict) or any(k not in binding for k in
                ('session_id','tab_id','browser_instance_id','agent_window_id')):
            raise ValueError('explicit owned binding required')
        digest = hashlib.sha256(json.dumps([site, prompt, binding], sort_keys=True,
                                          ensure_ascii=False).encode()).hexdigest()
        with self._db() as db:
            previous = db.execute('SELECT fingerprint FROM consultations WHERE id=?',
                                  (request_id,)).fetchone()
        if previous:
            if previous[0] != digest:
                raise ValueError('request id reused with changed payload or binding')
            return self.status(request_id)
        preflight()  # Read-only checks; failure admits no external operation.
        context = None
        if capture is not None:
            from .consultation_response import baseline
            context = baseline(capture(), site, prompt, binding)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            lane = self._lane(binding)
            active = db.execute('''SELECT l.request_id,c.state FROM consultation_lanes l
                JOIN consultations c ON c.id=l.request_id WHERE l.lane=?''', (lane,)).fetchone()
            if active and active[0] != request_id and active[1] != 'completed':
                db.execute('ROLLBACK')
                raise PermissionError('bound tab has an unresolved review; collect its result or explicitly bind another clean tab')
            claimed = db.execute('INSERT OR IGNORE INTO consultations VALUES (?,?,?,?)',
                                 (request_id, digest, 'unknown', self._now())).rowcount
            stored = db.execute('SELECT fingerprint FROM consultations WHERE id=?',
                                (request_id,)).fetchone()[0]
            if claimed and context is not None:
                db.execute('INSERT INTO consultation_responses VALUES (?,?,?)',
                           (request_id, json.dumps(context), json.dumps({'state': 'unknown', 'reason': 'awaiting_user_turn'})))
            if claimed:
                db.execute('INSERT OR REPLACE INTO consultation_lanes VALUES (?,?)', (lane, request_id))
            db.execute('COMMIT')
        if stored != digest:
            raise ValueError('concurrent request id conflict')
        if not claimed:
            return self.status(request_id)
        # UNKNOWN is committed before dispatch; a crash/timeout never replays.
        try:
            result = dispatch()
        except Exception:
            self.note(request_id,'interrupted')
            return self.status(request_id)
        if isinstance(result, dict) and result.get('submitted') is True:
            with self._db() as db:
                db.execute("UPDATE consultations SET state='submitted',updated_at=? WHERE id=? AND state='unknown'",
                           (self._now(), request_id))
        return self.status(request_id)
