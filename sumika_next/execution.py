"""Durable at-most-once dispatch at the Harness boundary, not an Agent loop."""
import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path

from .authorization import Authority, Approval, AuthorizationError
from .contracts import Harness, Recovery, TaskEvent, TaskState, ToolRequest, WorkBinding


def binding_key(binding: WorkBinding) -> str:
    return json.dumps(asdict(binding), sort_keys=True, separators=(",", ":"))


class Execution:
    def __init__(self, harness: Harness, authority: Authority, database: Path):
        if harness.instance != authority.instance:
            raise AuthorizationError("authority belongs to another harness")
        self.harness, self.authority = harness, authority
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS steps (binding TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, binding TEXT NOT NULL, state TEXT NOT NULL)")
        self.db.commit()
        self.lock = threading.RLock()

    def dispatch(self, request: ToolRequest, approval: Approval) -> dict:
        key = binding_key(request.binding)
        with self.lock:
            # Retain unknown before crossing the transport boundary. Never guess not-sent.
            try:
                self.db.execute("BEGIN IMMEDIATE")
                if self.db.execute("SELECT 1 FROM steps WHERE binding=?", (key,)).fetchone():
                    raise AuthorizationError("step already attempted; inspect instead of replay")
                if request.action != "session.cancel":
                    unknown = self.db.execute("SELECT binding FROM steps WHERE state=?", (TaskState.UNKNOWN.value,)).fetchall()
                    if any(json.loads(row[0])["request_id"] == request.binding.request_id for row in unknown):
                        raise AuthorizationError("request has an unknown operation; replan cannot bypass it")
                self.authority.consume(request, approval)
                digest = hashlib.sha256(request.arguments).hexdigest()
                self.db.execute("INSERT INTO steps VALUES (?, ?, ?)", (key, digest, TaskState.UNKNOWN.value))
                self.db.execute("INSERT INTO events(binding, state) VALUES (?, ?)", (key, TaskState.UNKNOWN.value))
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
        try:
            result = self.harness.execute(request)
        except Exception:
            # A timeout, cancellation or crash is not evidence that a write did not happen.
            self.authority.revoke(request.binding)
            raise
        with self.lock:
            self.db.execute("UPDATE steps SET state=? WHERE binding=?", (TaskState.COMPLETED.value, key))
            self.db.execute("INSERT INTO events(binding, state) VALUES (?, ?)", (key, TaskState.COMPLETED.value))
            self.db.commit()
            self.authority.revoke(request.binding)
        return result

    def inspect(self, binding: WorkBinding) -> Recovery:
        with self.lock:
            row = self.db.execute("SELECT state FROM steps WHERE binding=?", (binding_key(binding),)).fetchone()
        return Recovery(binding, TaskState(row[0]) if row else TaskState.PLANNED)

    def close(self):
        self.db.close()

    def events(self, binding: WorkBinding, after=0):
        """Read only journal events; remote/model event injection has no entrypoint."""
        with self.lock:
            rows = self.db.execute("SELECT sequence, state FROM events WHERE binding=? AND sequence>? ORDER BY sequence", (binding_key(binding), after)).fetchall()
        return tuple(TaskEvent(binding, sequence, TaskState(state)) for sequence, state in rows)
