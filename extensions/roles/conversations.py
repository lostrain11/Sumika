"""Personal conversation journal. Independent of model providers and Harnesses."""
import json
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Conversations:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS role_turns (id TEXT PRIMARY KEY, scope TEXT NOT NULL, session TEXT NOT NULL, at TEXT NOT NULL, original TEXT NOT NULL, state TEXT NOT NULL, reply TEXT, intent TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS role_turns_scope ON role_turns(scope, session, at)')
            db.execute('CREATE TABLE IF NOT EXISTS role_handoffs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS role_handoff_events (id TEXT PRIMARY KEY, handoff_id TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL, at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS role_scope_bindings (owner TEXT NOT NULL, project TEXT NOT NULL, location TEXT NOT NULL, scope TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner, project, location))')

    @staticmethod
    def _location(path):
        value=Path(path)
        if not value.is_absolute():
            raise ValueError('absolute role location required')
        return str(value.resolve())

    def scope_for(self, owner, location, project):
        """Adopt the old scope without rewriting history; bind future moves explicitly."""
        location=self._location(location)
        if not all(isinstance(v,str) and v.strip() for v in (owner,project)):
            raise ValueError('user and project required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT scope,retired FROM role_scope_bindings WHERE owner=? AND project=? AND location=?',
                           (owner,project,location)).fetchone()
            if row:
                if row[1]:raise ValueError('role location was relocated; explicit recovery required')
                return row[0]
            # This string becomes an opaque stable identity after adoption.
            # Retaining its exact legacy spelling preserves messages and clears.
            scope=json.dumps([owner,location,project],ensure_ascii=False)
            db.execute('INSERT INTO role_scope_bindings VALUES (?,?,?,?,0)',(owner,project,location,scope))
            return scope

    def relocate_scope(self, owner, project, source, target, *, expected_scope):
        """Explicit offline relocation binding, never a name-based merge or replay.

        The caller must verify the resource copy and retain a database backup
        before changing settings. This operation moves no files or credentials.
        """
        source,target=self._location(source),self._location(target)
        if source==target:raise ValueError('different source and target required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT scope,retired FROM role_scope_bindings WHERE owner=? AND project=? AND location=?',
                           (owner,project,source)).fetchone()
            new=db.execute('SELECT scope,retired FROM role_scope_bindings WHERE owner=? AND project=? AND location=?',
                           (owner,project,target)).fetchone()
            if not old or old[0]!=expected_scope:raise ValueError('source identity changed or not registered')
            if old[1] and new==(expected_scope,0):return expected_scope
            if old[1] or new:raise ValueError('relocation conflicts with existing binding')
            legacy=json.dumps([owner,target,project],ensure_ascii=False)
            for table in ('role_turns','cleared_role_turns'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    if db.execute(f'SELECT 1 FROM {table} WHERE scope=? LIMIT 1',(legacy,)).fetchone():
                        raise ValueError('target has history; automatic merge refused')
            db.execute('INSERT INTO role_scope_bindings VALUES (?,?,?,?,0)',(owner,project,target,expected_scope))
            db.execute('UPDATE role_scope_bindings SET retired=1 WHERE owner=? AND project=? AND location=?',
                       (owner,project,source))
            return expected_scope

    def relocated_locations(self, owner, project):
        with self.connect() as db:
            return [row[0] for row in db.execute('''SELECT a.location FROM role_scope_bindings a
                WHERE a.owner=? AND a.project=? AND a.retired=0 AND EXISTS
                (SELECT 1 FROM role_scope_bindings b WHERE b.scope=a.scope AND b.retired=1)''',(owner,project))]

    def draft(self, owner):
        with self.connect() as db:
            row=db.execute("SELECT payload FROM role_handoffs WHERE owner=? AND state='pending' ORDER BY rowid DESC LIMIT 1",(owner,)).fetchone()
        return json.loads(row[0]) if row else None

    def handoff(self, owner, handoff_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM role_handoffs WHERE owner=? AND id=?',(owner,handoff_id)).fetchone()
        return json.loads(row[0]) if row else None

    def import_legacy(self, scope, session, messages):
        """Import an explicitly scoped snapshot; never replay or infer tool intent."""
        turns = []
        for message in messages:
            if not isinstance(message, dict) or message.get('who') not in ('me', 'role'):
                raise ValueError('invalid legacy speaker')
            if not isinstance(message.get('text'), str) or not isinstance(message.get('at'), str):
                raise ValueError('invalid legacy message')
            if message['who'] == 'me':
                turns.append([message['at'], message['text'], None])
            elif not turns or turns[-1][2] is not None:
                raise ValueError('legacy reply has no unambiguous user message')
            else:
                turns[-1][2] = message['text']
        inserted = 0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM role_turns WHERE scope=? AND session=? AND id NOT LIKE 'legacy-%' LIMIT 1",
                          (scope, session)).fetchone():
                raise ValueError('target has new conversations; reconcile before import')
            for index, (at, original, reply) in enumerate(turns):
                identity = json.dumps([scope, session, index, at, original, reply], ensure_ascii=False)
                turn_id = 'legacy-' + hashlib.sha256(identity.encode()).hexdigest()
                state = 'completed' if reply and reply.strip() else 'unknown'
                inserted += db.execute('INSERT OR IGNORE INTO role_turns VALUES (?,?,?,?,?,?,?,NULL)',
                    (turn_id, scope, session, at, original, state, reply)).rowcount
        return inserted

    def prepare(self, owner, scope, source, expected=None):
        from extensions.roles.handoff import create_handoff
        if not isinstance(source,str) or not source.endswith(':user'):
            raise ValueError('persisted user message required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT original,state FROM role_turns WHERE id=? AND scope=?',(source[:-5],scope)).fetchone()
            if not row or row[1]!='completed': raise ValueError('source message unavailable in this role')
            current=db.execute("SELECT id FROM role_handoffs WHERE owner=? AND state='pending'",(owner,)).fetchone()
            if (current[0] if current else None)!=expected: raise ValueError('draft changed; reload before replacing')
            if current: db.execute("UPDATE role_handoffs SET state='replaced' WHERE id=?",(current[0],))
            value=create_handoff(source_message_id=source,original_user_text=row[0])
            value['id']=value['handoff_id']
            db.execute('INSERT INTO role_handoffs VALUES (?,?,?,?,?)',(value['id'],owner,source,json.dumps(value,ensure_ascii=False),'pending'))
        return value

    def dismiss(self, owner, draft_id):
        # This only clears a presentation draft. It does not attest task execution.
        with self.connect() as db:
            db.execute("UPDATE role_handoffs SET state='dismissed' WHERE owner=? AND id=? AND state='pending'",(owner,draft_id))

    def receive_handoff(self, owner, handoff_id, context):
        return self._transition(owner, handoff_id, 'received', {'context': context})

    def record_handoff_result(self, owner, handoff_id, receipt):
        if not isinstance(receipt, dict) or receipt.get('provenance') != 'host_verified':
            raise ValueError('only host-verified receipts are accepted')
        return self._transition(owner, handoff_id, receipt.get('status') if receipt.get('status') in ('unknown','failed') else 'completed', {'receipt': receipt})

    def _transition(self, owner, handoff_id, state, detail):
        allowed = {'pending': {'received','dismissed'}, 'received': {'accepted','running','completed','unknown','failed'}, 'accepted': {'running','completed','unknown','failed'}, 'running': {'completed','unknown','failed'}, 'completed': set(), 'unknown': set(), 'failed': set(), 'dismissed': set()}
        with self.connect() as db:
            row = db.execute('SELECT state,payload FROM role_handoffs WHERE id=? AND owner=?',(handoff_id,owner)).fetchone()
            if not row: raise ValueError('handoff not found')
            current = row[0]
            if state not in allowed.get(current, set()):
                if current == state: return json.loads(row[1])
                raise ValueError('invalid handoff state transition')
            payload = json.loads(row[1]); payload['state'] = state
            payload.update(detail)
            at = datetime.now(timezone.utc).isoformat()
            db.execute('UPDATE role_handoffs SET state=?,payload=? WHERE id=? AND owner=?',(state,json.dumps(payload,ensure_ascii=False),handoff_id,owner))
            db.execute('INSERT INTO role_handoff_events VALUES (?,?,?,?,?)',(uuid.uuid4().hex,handoff_id,state,json.dumps(detail,ensure_ascii=False),at))
            return payload

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, scope, session, original):
        turn_id = uuid.uuid4().hex
        with self.connect() as db:
            # Persist uncertainty before any provider request; never auto-replay.
            db.execute('INSERT INTO role_turns VALUES (?,?,?,?,?,?,NULL,NULL)',
                       (turn_id, scope, session, datetime.now(timezone.utc).isoformat(), original, 'unknown'))
        return turn_id

    def complete(self, turn_id, result):
        reply = result.get('text')
        state = 'completed' if isinstance(reply, str) and reply.strip() else 'unavailable'
        with self.connect() as db:
            db.execute('UPDATE role_turns SET state=?,reply=?,intent=? WHERE id=? AND state=?',
                       (state, reply if isinstance(reply, str) else None,
                        json.dumps(result.get('task_intent'), ensure_ascii=False), turn_id, 'unknown'))

    def messages(self, scope, session, limit=60, *, completed_only=False):
        with self.connect() as db:
            rows = db.execute('SELECT id,at,original,state,reply,intent FROM role_turns WHERE scope=? AND session=? ORDER BY rowid DESC LIMIT ?',
                              (scope, session, limit)).fetchall()
        out = []
        for turn_id, at, original, state, reply, intent in reversed(rows):
            if completed_only and state != 'completed':
                continue
            out.append({'id':turn_id+':user','who':'me','text':original,'at':at,'state':state,
                        'task_intent':json.loads(intent) if intent else None})
            if reply:
                out.append({'id':turn_id+':assistant','who':'role','text':reply,'at':at,'state':state})
        return out

    def context(self, scope, session, limit=12):
        rows = self.messages(scope, session, limit=limit, completed_only=True)
        return [{'role':'user' if r['who']=='me' else 'assistant','content':r['text']} for r in rows][-limit:]

    def page(self, scope, session, before=None, limit=3):
        if type(limit) is not int or not 1 <= limit <= 60:
            raise ValueError('invalid page size')
        if before is not None and (type(before) is not int or before < 1):
            raise ValueError('invalid history cursor')
        with self.connect() as db:
            rows = db.execute('''SELECT * FROM (
                SELECT rowid*2 AS cursor,id||':user' AS id,at,original AS text,'me' AS who,state,intent
                FROM role_turns WHERE scope=? AND session=?
                UNION ALL
                SELECT rowid*2+1,id||':assistant',at,reply,'role',state,NULL
                FROM role_turns WHERE scope=? AND session=? AND reply IS NOT NULL AND reply!=''
                ) WHERE (? IS NULL OR cursor<?) ORDER BY cursor DESC LIMIT ?''',
                (scope,session,scope,session,before,before,limit+1)).fetchall()
        selected=rows[:limit]
        messages=[{'id':r[1],'at':r[2],'text':r[3],'who':r[4],'state':r[5],
                   'task_intent':json.loads(r[6]) if r[6] else None} for r in reversed(selected)]
        return {'messages':messages,'has_more':len(rows)>limit,
                'before':selected[-1][0] if selected else None}

    def clear(self, scope, session):
        # Preserve a recovery copy, but remove this chat from model context.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS cleared_role_turns AS SELECT *, NULL AS cleared_at FROM role_turns WHERE 0')
            db.execute('INSERT INTO cleared_role_turns SELECT *,? FROM role_turns WHERE scope=? AND session=?',
                       (datetime.now(timezone.utc).isoformat(),scope,session))
            db.execute("UPDATE role_handoffs SET state='dismissed' WHERE state='pending' AND source IN (SELECT id||':user' FROM role_turns WHERE scope=? AND session=?)",(scope,session))
            count=db.execute('DELETE FROM role_turns WHERE scope=? AND session=?',(scope,session)).rowcount
        return count
