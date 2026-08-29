"""SQLite persistence with explicit schema versioning and event history."""

from __future__ import annotations

import json
import hashlib
import math
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .protocol.models import Message, utc_now


SCHEMA_VERSION = 14

SNAPSHOT_FORMAT_VERSION = 1

# These are the durable application tables that can be restored. Events and
# snapshots deliberately stay outside this list so the audit trail remains
# append-only when user data is rolled back.
_SNAPSHOT_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "sessions": ("id", "title", "character_id", "created_at", "updated_at"),
    "messages": ("id", "session_id", "role", "content", "character_id", "created_at"),
    "characters": ("id", "name", "config_json", "created_at", "updated_at"),
    "module_settings": ("module_id", "enabled", "implementation_id", "config_json", "updated_at"),
    "provider_profiles": (
        "id",
        "name",
        "capability",
        "adapter_id",
        "template_id",
        "processing_location",
        "status",
        "config_json",
        "credential_ref",
        "secret_fields_json",
        "source_json",
        "created_at",
        "updated_at",
        "last_used_at",
        "archived_at",
    ),
    "browser_profiles": (
        "id",
        "name",
        "character_id",
        "agent_id",
        "status",
        "created_at",
        "updated_at",
        "last_used_at",
        "archived_at",
    ),
    "tasks": (
        "id",
        "title",
        "status",
        "autonomy_level",
        "character_id",
        "progress",
        "budget_json",
        "result_json",
        "permissions_json",
        "logs_json",
        "artifacts_json",
        "created_at",
        "updated_at",
    ),
    "avatar_models": (
        "id",
        "name",
        "kind",
        "path",
        "size_bytes",
        "modified_at",
        "metadata_json",
        "created_at",
    ),
    "audio_permissions": ("permission_id", "state", "updated_at"),
    "vision_permissions": ("permission_id", "state", "updated_at"),
    "memories": (
        "id",
        "character_id",
        "category",
        "content",
        "source",
        "metadata_json",
        "created_at",
        "updated_at",
    ),
}
_SNAPSHOT_TABLE_KEYS = {
    "sessions": "id",
    "messages": "id",
    "characters": "id",
    "module_settings": "module_id",
    "provider_profiles": "id",
    "browser_profiles": "id",
    "tasks": "id",
    "avatar_models": "id",
    "audio_permissions": "permission_id",
    "vision_permissions": "permission_id",
    "memories": "id",
}
_SNAPSHOT_SCOPE_TABLES = {
    "system": tuple(_SNAPSHOT_TABLE_COLUMNS),
    "modules": ("module_settings", "provider_profiles", "browser_profiles"),
    "characters": ("characters",),
    "memories": ("memories",),
}
_SNAPSHOT_SCOPE_ALIASES = {
    "system": "system",
    "module": "modules",
    "modules": "modules",
    "character": "characters",
    "characters": "characters",
    "memory": "memories",
    "memories": "memories",
}


class Storage:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    character_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    character_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    session_id TEXT,
                    character_id TEXT,
                    correlation_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS module_settings (
                    module_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    implementation_id TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    adapter_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    processing_location TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    credential_ref TEXT,
                    secret_fields_json TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_provider_profiles_capability
                    ON provider_profiles(capability, archived_at, last_used_at);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    autonomy_level TEXT NOT NULL,
                    character_id TEXT,
                    progress REAL NOT NULL,
                    budget_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    logs_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                -- Derived, discardable Agent task summaries.  This table is
                -- intentionally absent from _SNAPSHOT_TABLE_COLUMNS: user
                -- data restore must never rewind Runtime health or activity
                -- projections.
                CREATE TABLE IF NOT EXISTS agent_task_projections (
                    id TEXT PRIMARY KEY,
                    runtime_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    budget_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    logs_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    workspace_json TEXT,
                    runtime_updated_at TEXT,
                    observed_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_task_projections_runtime_session
                    ON agent_task_projections(runtime_id, session_id);
                CREATE INDEX IF NOT EXISTS idx_agent_task_projections_observed
                    ON agent_task_projections(observed_at DESC);
                CREATE TABLE IF NOT EXISTS avatar_models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    modified_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audio_permissions (
                    permission_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vision_permissions (
                    permission_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_character_category
                    ON memories(character_id, category, updated_at);
                 CREATE TABLE IF NOT EXISTS plugin_registrations (
                    candidate_id TEXT PRIMARY KEY,
                    plugin_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    manifest_path TEXT NOT NULL UNIQUE,
                    manifest_json TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    error TEXT,
                    discovered_at TEXT NOT NULL,
                    approved_at TEXT,
                    updated_at TEXT NOT NULL,
                    launcher_json TEXT NOT NULL DEFAULT '{}',
                    configured_at TEXT,
                     entrypoint_sha256 TEXT NOT NULL DEFAULT ''
                 );
                 CREATE INDEX IF NOT EXISTS idx_plugin_registrations_plugin
                     ON plugin_registrations(plugin_id, version, state);
                 CREATE TABLE IF NOT EXISTS skill_registrations (
                     candidate_id TEXT PRIMARY KEY,
                     skill_id TEXT NOT NULL,
                     name TEXT NOT NULL,
                     description TEXT NOT NULL,
                     version TEXT NOT NULL,
                     root_path TEXT NOT NULL,
                     skill_path TEXT NOT NULL UNIQUE,
                     source TEXT NOT NULL,
                     permissions_json TEXT NOT NULL,
                     metadata_json TEXT NOT NULL,
                     manifest_sha256 TEXT NOT NULL,
                     state TEXT NOT NULL,
                     error TEXT,
                     discovered_at TEXT NOT NULL,
                     approved_at TEXT,
                     updated_at TEXT NOT NULL
                 );
                 CREATE INDEX IF NOT EXISTS idx_skill_registrations_state
                     ON skill_registrations(state, updated_at DESC);
                 CREATE TABLE IF NOT EXISTS browser_profiles (
                     id TEXT PRIMARY KEY,
                     name TEXT NOT NULL,
                     character_id TEXT,
                     agent_id TEXT,
                     status TEXT NOT NULL,
                     created_at TEXT NOT NULL,
                     updated_at TEXT NOT NULL,
                     last_used_at TEXT,
                     archived_at TEXT
                 );
                 CREATE INDEX IF NOT EXISTS idx_browser_profiles_status
                     ON browser_profiles(status, archived_at, last_used_at);
                 CREATE TABLE IF NOT EXISTS browser_profile_leases (
                     profile_id TEXT PRIMARY KEY,
                     lease_id TEXT NOT NULL,
                     owner_token TEXT NOT NULL,
                     acquired_at TEXT NOT NULL,
                     expires_at TEXT NOT NULL,
                     FOREIGN KEY(profile_id) REFERENCES browser_profiles(id)
                 );
                 """
            )
            plugin_columns = {
                str(row[1])
                for row in self._connection.execute("PRAGMA table_info(plugin_registrations)").fetchall()
            }
            if "launcher_json" not in plugin_columns:
                self._connection.execute(
                    "ALTER TABLE plugin_registrations ADD COLUMN launcher_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "configured_at" not in plugin_columns:
                self._connection.execute(
                    "ALTER TABLE plugin_registrations ADD COLUMN configured_at TEXT"
                )
            if "entrypoint_sha256" not in plugin_columns:
                self._connection.execute(
                    "ALTER TABLE plugin_registrations ADD COLUMN entrypoint_sha256 TEXT NOT NULL DEFAULT ''"
                )
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def get_meta(self, key: str) -> str | None:
        """Read a small application-owned value outside user snapshot data."""
        if not isinstance(key, str) or not key.strip():
            raise ValueError("metadata key must not be empty")
        with self._lock:
            row = self._connection.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    def set_meta(self, key: str, value: str) -> None:
        """Persist a small application-owned value outside user snapshot data."""
        if not isinstance(key, str) or not key.strip():
            raise ValueError("metadata key must not be empty")
        if not isinstance(value, str):
            raise ValueError("metadata value must be a string")
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES(?, ?)",
                (key, value),
            )

    def create_session(self, session_id: str, title: str = "新会话", character_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO sessions(id, title, character_id, created_at, updated_at) VALUES(?,?,?,?,?)",
                (session_id, title, character_id, now, now),
            )
        return {"id": session_id, "title": title, "character_id": character_id, "created_at": now, "updated_at": now}

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def append_message(self, session_id: str, message: Message) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO messages(id, session_id, role, content, character_id, created_at) VALUES(?,?,?,?,?,?)",
                (message.id, session_id, message.role, message.content, message.character_id, message.created_at),
            )
            self._connection.execute("UPDATE sessions SET updated_at=? WHERE id=?", (message.created_at, session_id))

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, rowid", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def create_character(self, character_id: str, name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        payload = json.dumps(config or {}, ensure_ascii=False, sort_keys=True)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO characters(id, name, config_json, created_at, updated_at) VALUES(?,?,?,?,?)",
                (character_id, name, payload, now, now),
            )
        return {"id": character_id, "name": name, "config": config or {}, "created_at": now, "updated_at": now}

    def list_characters(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM characters ORDER BY created_at").fetchall()
        return [self._character_row(row) for row in rows]

    @staticmethod
    def _character_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        return value

    def get_character(self, character_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
        return self._character_row(row) if row is not None else None

    def update_character_config(self, character_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
        now = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE characters SET config_json=?, updated_at=? WHERE id=?",
                (json.dumps(config, ensure_ascii=False, sort_keys=True), now, character_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_character(character_id)

    def update_character(
        self,
        character_id: str,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_character(character_id)
        if current is None:
            return None
        next_name = current["name"] if name is None else name
        next_config = current["config"] if config is None else config
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE characters SET name=?, config_json=?, updated_at=? WHERE id=?",
                (next_name, json.dumps(next_config, ensure_ascii=False, sort_keys=True), now, character_id),
            )
        return self.get_character(character_id)

    def create_memory(
        self,
        *,
        memory_id: str,
        character_id: str,
        category: str,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO memories(
                    id, character_id, category, content, source, metadata_json,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    memory_id,
                    character_id,
                    category,
                    content,
                    source,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        return self.get_memory(memory_id)  # type: ignore[return-value]

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory_row(row) if row is not None else None

    def list_memories(
        self,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["character_id=?"]
        values: list[Any] = [character_id]
        if category:
            clauses.append("category=?")
            values.append(category)
        if query:
            clauses.append("instr(lower(content), lower(?)) > 0")
            values.append(query)
        values.append(max(1, min(limit, 500)))
        statement = (
            "SELECT * FROM memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        )
        with self._lock:
            rows = self._connection.execute(statement, values).fetchall()
        return [self._memory_row(row) for row in rows]

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        return cursor.rowcount > 0

    def upsert_plugin_registration(self, registration: dict[str, Any]) -> dict[str, Any]:
        required = (
            "candidate_id",
            "plugin_id",
            "version",
            "root_path",
            "manifest_path",
            "manifest",
            "manifest_sha256",
            "state",
            "discovered_at",
            "updated_at",
        )
        if any(key not in registration for key in required):
            raise ValueError("plugin registration is missing required fields")
        if not isinstance(registration["manifest"], dict):
            raise ValueError("plugin manifest must be an object")
        if registration["state"] not in {"discovered", "changed", "approved", "revoked", "invalid"}:
            raise ValueError("invalid plugin registration state")
        payload = json.dumps(registration["manifest"], ensure_ascii=False, sort_keys=True)
        values = (
            str(registration["candidate_id"]),
            str(registration["plugin_id"]),
            str(registration["version"]),
            str(registration["root_path"]),
            str(registration["manifest_path"]),
            payload,
            str(registration["manifest_sha256"]),
            str(registration["state"]),
            registration.get("error"),
            str(registration["discovered_at"]),
            registration.get("approved_at"),
            str(registration["updated_at"]),
            json.dumps(registration.get("launcher", {}), ensure_ascii=False, sort_keys=True),
            registration.get("configured_at"),
            str(registration.get("entrypoint_sha256", "")),
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO plugin_registrations(
                    candidate_id, plugin_id, version, root_path, manifest_path,
                    manifest_json, manifest_sha256, state, error, discovered_at,
                    approved_at, updated_at, launcher_json, configured_at,
                    entrypoint_sha256
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    plugin_id=excluded.plugin_id,
                    version=excluded.version,
                    root_path=excluded.root_path,
                    manifest_path=excluded.manifest_path,
                    manifest_json=excluded.manifest_json,
                    manifest_sha256=excluded.manifest_sha256,
                    state=excluded.state,
                    error=excluded.error,
                    discovered_at=excluded.discovered_at,
                    approved_at=excluded.approved_at,
                    updated_at=excluded.updated_at,
                    launcher_json=excluded.launcher_json,
                    configured_at=excluded.configured_at,
                    entrypoint_sha256=excluded.entrypoint_sha256
                """,
                values,
            )
        result = self.get_plugin_registration(str(registration["candidate_id"]))
        if result is None:
            raise RuntimeError("plugin registration was not persisted")
        return result

    def get_plugin_registration(self, candidate_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM plugin_registrations WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        return self._plugin_row(row) if row is not None else None

    def list_plugin_registrations(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM plugin_registrations ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [self._plugin_row(row) for row in rows]

    def update_plugin_launcher(
        self,
        candidate_id: str,
        launcher: dict[str, Any],
        configured_at: str,
        updated_at: str,
    ) -> dict[str, Any] | None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE plugin_registrations
                SET launcher_json=?, configured_at=?, updated_at=?
                WHERE candidate_id=?
                """,
                (
                    json.dumps(launcher, ensure_ascii=False, sort_keys=True),
                    configured_at,
                    updated_at,
                    candidate_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_plugin_registration(candidate_id)

    def upsert_skill_registration(self, registration: dict[str, Any]) -> dict[str, Any]:
        required = (
            "candidate_id",
            "skill_id",
            "name",
            "description",
            "version",
            "root_path",
            "skill_path",
            "source",
            "permissions",
            "metadata",
            "manifest_sha256",
            "state",
            "discovered_at",
            "updated_at",
        )
        if any(key not in registration for key in required):
            raise ValueError("skill registration is missing required fields")
        if registration["state"] not in {"discovered", "changed", "approved", "revoked", "invalid"}:
            raise ValueError("invalid skill registration state")
        if not isinstance(registration["permissions"], list) or not isinstance(registration["metadata"], dict):
            raise ValueError("skill registration metadata must be JSON objects")
        values = (
            str(registration["candidate_id"]),
            str(registration["skill_id"]),
            str(registration["name"]),
            str(registration["description"]),
            str(registration.get("version") or ""),
            str(registration["root_path"]),
            str(registration["skill_path"]),
            str(registration.get("source") or "local"),
            json.dumps(registration["permissions"], ensure_ascii=False, sort_keys=True),
            json.dumps(registration["metadata"], ensure_ascii=False, sort_keys=True),
            str(registration.get("manifest_sha256") or ""),
            str(registration["state"]),
            registration.get("error"),
            str(registration["discovered_at"]),
            registration.get("approved_at"),
            str(registration["updated_at"]),
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO skill_registrations(
                    candidate_id, skill_id, name, description, version,
                    root_path, skill_path, source, permissions_json, metadata_json,
                    manifest_sha256, state, error, discovered_at, approved_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    skill_id=excluded.skill_id,
                    name=excluded.name,
                    description=excluded.description,
                    version=excluded.version,
                    root_path=excluded.root_path,
                    skill_path=excluded.skill_path,
                    source=excluded.source,
                    permissions_json=excluded.permissions_json,
                    metadata_json=excluded.metadata_json,
                    manifest_sha256=excluded.manifest_sha256,
                    state=excluded.state,
                    error=excluded.error,
                    discovered_at=excluded.discovered_at,
                    approved_at=excluded.approved_at,
                    updated_at=excluded.updated_at
                """,
                values,
            )
        result = self.get_skill_registration(str(registration["candidate_id"]))
        if result is None:
            raise RuntimeError("skill registration was not persisted")
        return result

    def get_skill_registration(self, candidate_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM skill_registrations WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        return self._skill_row(row) if row is not None else None

    def list_skill_registrations(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM skill_registrations ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [self._skill_row(row) for row in rows]

    @staticmethod
    def _plugin_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["manifest"] = json.loads(value.pop("manifest_json"))
        value["launcher"] = json.loads(value.pop("launcher_json", "{}"))
        return value

    @staticmethod
    def _skill_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["permissions"] = json.loads(value.pop("permissions_json"))
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    @staticmethod
    def _memory_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def append_event(self, event: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO events(event_id, event_type, payload_json, session_id, character_id, correlation_id, timestamp) VALUES(?,?,?,?,?,?,?)",
                (
                    event["event_id"],
                    event["event_type"],
                    json.dumps(event["payload"], ensure_ascii=False),
                    event.get("session_id"),
                    event.get("character_id"),
                    event["correlation_id"],
                    event["timestamp"],
                ),
            )

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM events ORDER BY timestamp DESC, rowid DESC LIMIT ?", (max(1, min(limit, 1000)),)
            ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            result.append(value)
        return result

    def count_events(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"] if row else 0)

    def create_snapshot(self, snapshot_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError("snapshot id must not be empty")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("snapshot name must not be empty")
        if len(name.strip()) > 200:
            raise ValueError("snapshot name is too long")
        if not isinstance(payload, dict):
            raise ValueError("snapshot payload must be an object")
        created_at = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO snapshots(id, name, payload_json, created_at) VALUES(?,?,?,?)",
                (snapshot_id, name.strip(), json.dumps(payload, ensure_ascii=False, sort_keys=True), created_at),
            )
        return {"id": snapshot_id, "name": name.strip(), "created_at": created_at, "payload": payload}

    def list_snapshots(self) -> list[dict[str, Any]]:
        """List snapshot metadata without returning potentially large payloads."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, name, payload_json, created_at FROM snapshots ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = _decode_snapshot_payload(row["payload_json"])
            result.append(self._snapshot_metadata(row, payload))
        return result

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, name, payload_json, created_at FROM snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        payload = _decode_snapshot_payload(row["payload_json"])
        return {**self._snapshot_metadata(row, payload), "payload": payload}

    def export_snapshot_state(self, scope: str = "system", target_id: str | None = None) -> dict[str, Any]:
        """Capture durable user state for a complete or targeted snapshot."""
        normalized_scope = _normalize_snapshot_scope(scope)
        if normalized_scope == "system" and target_id is not None:
            raise ValueError("system snapshots cannot have a target id")
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in _SNAPSHOT_SCOPE_TABLES[normalized_scope]:
            key_column = _SNAPSHOT_TABLE_KEYS[table]
            where = ""
            values: tuple[Any, ...] = ()
            if target_id is not None:
                where = f" WHERE {key_column}=?"
                values = (target_id,)
            with self._lock:
                rows = self._connection.execute(
                    f"SELECT {', '.join(_SNAPSHOT_TABLE_COLUMNS[table])} FROM {table}{where}", values
                ).fetchall()
            tables[table] = [dict(row) for row in rows]
        return {
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "scope": normalized_scope,
            "target_id": target_id,
            "captured_at": utc_now(),
            "tables": tables,
        }

    def diff_snapshot_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a compact, non-sensitive diff suitable for confirmation UI."""
        scope, target_id, tables = _validate_snapshot_payload(payload)
        current = self.export_snapshot_state(scope, target_id)
        summaries: list[dict[str, Any]] = []
        for table in tables:
            key = _SNAPSHOT_TABLE_KEYS[table]
            current_rows = {str(row[key]): row for row in current["tables"].get(table, [])}
            snapshot_rows = {str(row[key]): row for row in tables.get(table, [])}
            added = sorted(set(snapshot_rows) - set(current_rows))
            removed = sorted(set(current_rows) - set(snapshot_rows))
            changed = sorted(
                item
                for item in set(current_rows) & set(snapshot_rows)
                if _row_signature(current_rows[item]) != _row_signature(snapshot_rows[item])
            )
            summaries.append(
                {
                    "table": table,
                    "current_count": len(current_rows),
                    "snapshot_count": len(snapshot_rows),
                    "added": len(added),
                    "removed": len(removed),
                    "changed": len(changed),
                    "added_ids": added[:10],
                    "removed_ids": removed[:10],
                    "changed_ids": changed[:10],
                }
            )
        return {
            "scope": scope,
            "target_id": target_id,
            "changed": any(item["added"] or item["removed"] or item["changed"] for item in summaries),
            "tables": summaries,
        }

    def restore_snapshot_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Atomically replace the state represented by a snapshot payload."""
        scope, target_id, tables = _validate_snapshot_payload(payload)
        # Older snapshots do not contain tables introduced in later schema
        # versions. Restore only tables explicitly present in the payload so
        # a legacy module snapshot cannot erase newer provider profiles.
        selected_tables = tuple(table for table in _SNAPSHOT_SCOPE_TABLES[scope] if table in tables)
        with self._lock, self._connection:
            for table in reversed(selected_tables):
                key_column = _SNAPSHOT_TABLE_KEYS[table]
                if target_id is None:
                    self._connection.execute(f"DELETE FROM {table}")
                else:
                    self._connection.execute(f"DELETE FROM {table} WHERE {key_column}=?", (target_id,))
            for table in selected_tables:
                columns = _SNAPSHOT_TABLE_COLUMNS[table]
                placeholders = ", ".join("?" for _ in columns)
                statement = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
                for row in tables.get(table, []):
                    self._connection.execute(statement, tuple(row[column] for column in columns))
        return {
            "scope": scope,
            "target_id": target_id,
            "tables": {table: len(tables.get(table, [])) for table in selected_tables},
        }

    @staticmethod
    def _snapshot_metadata(row: sqlite3.Row, payload: dict[str, Any]) -> dict[str, Any]:
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "scope": payload.get("scope", "unknown"),
            "target_id": payload.get("target_id"),
            "format_version": payload.get("format_version"),
            "size_bytes": len(str(row["payload_json"]).encode("utf-8")),
            "table_counts": {
                str(table): len(value) if isinstance(value, list) else 0
                for table, value in tables.items()
            },
        }

    def get_module_setting(self, module_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM module_settings WHERE module_id=?", (module_id,)
            ).fetchone()
        return self._module_row(row) if row is not None else None

    def list_module_settings(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM module_settings ORDER BY module_id"
            ).fetchall()
        return [self._module_row(row) for row in rows]

    def upsert_module_setting(
        self,
        module_id: str,
        *,
        enabled: bool,
        implementation_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        updated_at = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO module_settings(module_id, enabled, implementation_id, config_json, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(module_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    implementation_id=excluded.implementation_id,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (module_id, int(enabled), implementation_id, json.dumps(config, ensure_ascii=False, sort_keys=True), updated_at),
            )
        return {
            "module_id": module_id,
            "enabled": enabled,
            "implementation_id": implementation_id,
            "config": config,
            "updated_at": updated_at,
        }

    @staticmethod
    def _module_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["config"] = json.loads(value.pop("config_json"))
        return value

    def get_provider_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM provider_profiles WHERE id=?", (profile_id,)
            ).fetchone()
        return self._provider_profile_row(row) if row is not None else None

    def list_provider_profiles(
        self,
        *,
        capability: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if capability:
            conditions.append("capability=?")
            parameters.append(capability)
        if not include_archived:
            conditions.append("archived_at IS NULL")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM provider_profiles
                {where}
                ORDER BY
                    CASE status
                        WHEN 'available' THEN 0
                        WHEN 'unavailable' THEN 1
                        WHEN 'draft' THEN 2
                        ELSE 3
                    END,
                    COALESCE(last_used_at, updated_at) DESC,
                    name COLLATE NOCASE
                """,
                tuple(parameters),
            ).fetchall()
        return [self._provider_profile_row(row) for row in rows]

    def upsert_provider_profile(
        self,
        *,
        profile_id: str,
        name: str,
        capability: str,
        adapter_id: str,
        template_id: str,
        processing_location: str,
        status: str,
        config: dict[str, Any],
        credential_ref: str | None,
        secret_fields: list[str],
        source: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.get_provider_profile(profile_id)
        now = utc_now()
        created_at = existing["created_at"] if existing else now
        last_used_at = existing.get("last_used_at") if existing else None
        archived_at = existing.get("archived_at") if existing else None
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO provider_profiles(
                    id, name, capability, adapter_id, template_id,
                    processing_location, status, config_json, credential_ref,
                    secret_fields_json, source_json, created_at, updated_at,
                    last_used_at, archived_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    capability=excluded.capability,
                    adapter_id=excluded.adapter_id,
                    template_id=excluded.template_id,
                    processing_location=excluded.processing_location,
                    status=excluded.status,
                    config_json=excluded.config_json,
                    credential_ref=excluded.credential_ref,
                    secret_fields_json=excluded.secret_fields_json,
                    source_json=excluded.source_json,
                    updated_at=excluded.updated_at
                """,
                (
                    profile_id,
                    name,
                    capability,
                    adapter_id,
                    template_id,
                    processing_location,
                    status,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    credential_ref,
                    json.dumps(secret_fields, ensure_ascii=False, sort_keys=True),
                    json.dumps(source, ensure_ascii=False, sort_keys=True),
                    created_at,
                    now,
                    last_used_at,
                    archived_at,
                ),
            )
        profile = self.get_provider_profile(profile_id)
        assert profile is not None
        return profile

    def update_provider_profile_state(
        self,
        profile_id: str,
        *,
        status: str | None = None,
        mark_used: bool = False,
        archived: bool | None = None,
    ) -> dict[str, Any] | None:
        profile = self.get_provider_profile(profile_id)
        if profile is None:
            return None
        now = utc_now()
        next_status = status or profile["status"]
        archived_at = profile.get("archived_at")
        if archived is True:
            archived_at = now
            next_status = "archived"
        elif archived is False:
            archived_at = None
            if next_status == "archived":
                next_status = "draft"
        last_used_at = now if mark_used else profile.get("last_used_at")
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE provider_profiles
                SET status=?, last_used_at=?, archived_at=?, updated_at=?
                WHERE id=?
                """,
                (next_status, last_used_at, archived_at, now, profile_id),
            )
        return self.get_provider_profile(profile_id)

    @staticmethod
    def _provider_profile_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        value["secret_fields"] = json.loads(value.pop("secret_fields_json"))
        value["source"] = json.loads(value.pop("source_json"))
        return value

    def get_browser_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM browser_profiles WHERE id=?", (profile_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_browser_profiles(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM browser_profiles
                {where}
                ORDER BY
                    CASE status WHEN 'active' THEN 0 ELSE 1 END,
                    COALESCE(last_used_at, updated_at) DESC,
                    name COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_browser_profile(
        self,
        *,
        profile_id: str,
        name: str,
        character_id: str | None,
        agent_id: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO browser_profiles(
                    id, name, character_id, agent_id, status,
                    created_at, updated_at, last_used_at, archived_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (profile_id, name, character_id, agent_id, "active", now, now, None, None),
            )
        profile = self.get_browser_profile(profile_id)
        assert profile is not None
        return profile

    def update_browser_profile_state(
        self,
        profile_id: str,
        *,
        mark_used: bool = False,
        archived: bool | None = None,
    ) -> dict[str, Any] | None:
        profile = self.get_browser_profile(profile_id)
        if profile is None:
            return None
        now = utc_now()
        next_status = str(profile.get("status") or "active")
        archived_at = profile.get("archived_at")
        if archived is True:
            next_status = "archived"
            archived_at = now
        elif archived is False:
            next_status = "active"
            archived_at = None
        last_used_at = now if mark_used else profile.get("last_used_at")
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE browser_profiles
                SET status=?, updated_at=?, last_used_at=?, archived_at=?
                WHERE id=?
                """,
                (next_status, now, last_used_at, archived_at, profile_id),
            )
        return self.get_browser_profile(profile_id)

    def get_browser_profile_lease(self, profile_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM browser_profile_leases WHERE profile_id=?", (profile_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def acquire_browser_profile_lease(
        self,
        *,
        profile_id: str,
        lease_id: str,
        owner_token: str,
        expires_at: str,
    ) -> dict[str, Any] | None:
        """Acquire one write lease, reclaiming only an already expired lease."""

        acquired_at = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM browser_profile_leases WHERE profile_id=? AND expires_at<=?",
                (profile_id, acquired_at),
            )
            current = self._connection.execute(
                "SELECT * FROM browser_profile_leases WHERE profile_id=?", (profile_id,)
            ).fetchone()
            if current is not None:
                if str(current["lease_id"]) != lease_id or str(current["owner_token"]) != owner_token:
                    return None
                self._connection.execute(
                    "UPDATE browser_profile_leases SET acquired_at=?, expires_at=? WHERE profile_id=?",
                    (acquired_at, expires_at, profile_id),
                )
            else:
                self._connection.execute(
                    """
                    INSERT INTO browser_profile_leases(profile_id, lease_id, owner_token, acquired_at, expires_at)
                    VALUES(?,?,?,?,?)
                    """,
                    (profile_id, lease_id, owner_token, acquired_at, expires_at),
                )
        return self.get_browser_profile_lease(profile_id)

    def renew_browser_profile_lease(
        self, *, profile_id: str, lease_id: str, owner_token: str, expires_at: str
    ) -> dict[str, Any] | None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE browser_profile_leases
                SET acquired_at=?, expires_at=?
                WHERE profile_id=? AND lease_id=? AND owner_token=?
                """,
                (utc_now(), expires_at, profile_id, lease_id, owner_token),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_browser_profile_lease(profile_id)

    def release_browser_profile_lease(self, *, profile_id: str, lease_id: str, owner_token: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM browser_profile_leases WHERE profile_id=? AND lease_id=? AND owner_token=?",
                (profile_id, lease_id, owner_token),
            )
        return cursor.rowcount > 0

    def list_browser_profile_leases(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM browser_profile_leases ORDER BY expires_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_expired_browser_profile_leases(self, *, now: str | None = None) -> int:
        cutoff = now or utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM browser_profile_leases WHERE expires_at<=?", (cutoff,)
            )
        return cursor.rowcount

    def get_audio_permission(self, permission_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM audio_permissions WHERE permission_id=?", (permission_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_audio_permissions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audio_permissions ORDER BY permission_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_audio_permission(self, permission_id: str, state: str) -> dict[str, Any]:
        updated_at = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO audio_permissions(permission_id, state, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(permission_id) DO UPDATE SET
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (permission_id, state, updated_at),
            )
        return {"permission_id": permission_id, "state": state, "updated_at": updated_at}

    def get_vision_permission(self, permission_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM vision_permissions WHERE permission_id=?", (permission_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_vision_permissions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM vision_permissions ORDER BY permission_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_vision_permission(self, permission_id: str, state: str) -> dict[str, Any]:
        updated_at = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO vision_permissions(permission_id, state, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(permission_id) DO UPDATE SET
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (permission_id, state, updated_at),
            )
        return {"permission_id": permission_id, "state": state, "updated_at": updated_at}

    def create_task(
        self,
        *,
        task_id: str,
        title: str,
        status: str,
        autonomy_level: str,
        budget: dict[str, Any],
        character_id: str | None,
        progress: float,
        result: dict[str, Any],
        permissions: list[str],
        logs: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tasks(
                    id, title, status, autonomy_level, character_id, progress,
                    budget_json, result_json, permissions_json, logs_json,
                    artifacts_json, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    title,
                    status,
                    autonomy_level,
                    character_id,
                    progress,
                    json.dumps(budget, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(permissions, ensure_ascii=False),
                    json.dumps(logs, ensure_ascii=False),
                    json.dumps(artifacts, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._task_row(row) if row is not None else None

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM tasks ORDER BY updated_at DESC, created_at DESC").fetchall()
        return [self._task_row(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        progress: float,
        result: dict[str, Any],
        logs: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        updated_at = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE tasks SET status=?, progress=?, result_json=?, logs_json=?, artifacts_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    progress,
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(logs, ensure_ascii=False),
                    json.dumps(artifacts, ensure_ascii=False),
                    updated_at,
                    task_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_task(task_id)

    def replace_agent_task_projections(
        self,
        runtime_id: str,
        projections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace the bounded derived cache for one Agent runtime.

        Agent sessions remain owned by the harness.  This cache is only a
        discardable, redacted view used while the harness is temporarily
        unavailable, so it is deliberately kept outside user snapshots.
        """

        if not isinstance(runtime_id, str) or not runtime_id.strip():
            raise ValueError("runtime_id must not be empty")
        if not isinstance(projections, list):
            raise ValueError("agent projections must be an array")
        clean_runtime_id = runtime_id.strip()[:120]
        rows: list[dict[str, Any]] = []
        for projection in projections[:64]:
            rows.append(_normalize_agent_task_projection(projection, clean_runtime_id))
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM agent_task_projections WHERE runtime_id=?", (clean_runtime_id,)
            )
            for row in rows:
                self._insert_agent_task_projection(row)
        return [self._agent_task_projection_row_from_normalized(row, stale=False) for row in rows]

    def upsert_agent_task_projection(self, projection: dict[str, Any]) -> dict[str, Any]:
        """Persist one redacted Agent session summary without user content."""

        runtime_id = str(projection.get("runtime_id") or "").strip() if isinstance(projection, dict) else ""
        if not runtime_id:
            raise ValueError("agent projection runtime_id must not be empty")
        row = _normalize_agent_task_projection(projection, runtime_id)
        with self._lock, self._connection:
            self._insert_agent_task_projection(row)
        return self._agent_task_projection_row_from_normalized(row, stale=False)

    def _insert_agent_task_projection(self, row: dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO agent_task_projections(
                id, runtime_id, session_id, title, status, progress,
                budget_json, result_json, permissions_json, logs_json,
                artifacts_json, metrics_json, workspace_json,
                runtime_updated_at, observed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                runtime_id=excluded.runtime_id,
                session_id=excluded.session_id,
                title=excluded.title,
                status=excluded.status,
                progress=excluded.progress,
                budget_json=excluded.budget_json,
                result_json=excluded.result_json,
                permissions_json=excluded.permissions_json,
                logs_json=excluded.logs_json,
                artifacts_json=excluded.artifacts_json,
                metrics_json=excluded.metrics_json,
                workspace_json=excluded.workspace_json,
                runtime_updated_at=excluded.runtime_updated_at,
                observed_at=excluded.observed_at
            """,
            (
                row["id"],
                row["runtime_id"],
                row["session_id"],
                row["title"],
                row["status"],
                row["progress"],
                json.dumps(row["budget"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                json.dumps(row["result"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                json.dumps(row["permissions"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                json.dumps(row["logs"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                json.dumps(row["artifacts"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                json.dumps(row["metrics"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                json.dumps(row["workspace"], ensure_ascii=False, sort_keys=True, allow_nan=False)
                if row["workspace"] is not None
                else None,
                row["runtime_updated_at"],
                row["observed_at"],
            ),
        )

    def list_agent_task_projections(
        self,
        runtime_id: str | None = None,
        *,
        limit: int = 24,
        stale: bool = True,
    ) -> list[dict[str, Any]]:
        """Read the redacted derived Agent projection cache.

        ``stale`` is explicit so callers cannot accidentally present cached
        state as a live Runtime snapshot.
        """

        bounded_limit = max(1, min(int(limit), 64))
        clauses: list[str] = []
        values: list[Any] = []
        if runtime_id is not None:
            if not isinstance(runtime_id, str) or not runtime_id.strip():
                raise ValueError("runtime_id must not be empty")
            clauses.append("runtime_id=?")
            values.append(runtime_id.strip()[:120])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(bounded_limit)
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM agent_task_projections"
                f"{where} ORDER BY observed_at DESC, runtime_updated_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [self._agent_task_projection_row(row, stale=stale) for row in rows]

    @staticmethod
    def _agent_task_projection_row(row: sqlite3.Row, *, stale: bool) -> dict[str, Any]:
        value = dict(row)
        for key in ("budget_json", "result_json", "permissions_json", "logs_json", "artifacts_json", "metrics_json"):
            value[key.removesuffix("_json")] = json.loads(value.pop(key))
        workspace_json = value.pop("workspace_json")
        value["workspace"] = json.loads(workspace_json) if workspace_json else None
        value["progress"] = float(value["progress"])
        value["stale"] = bool(stale)
        value["projection_state"] = "stale" if stale else "live"
        value["read_only"] = True
        value["source"] = "agent-runtime-cache"
        value["autonomy_level"] = "L2"
        value["character_id"] = None
        return value

    @classmethod
    def _agent_task_projection_row_from_normalized(
        cls,
        row: dict[str, Any],
        *,
        stale: bool,
    ) -> dict[str, Any]:
        value = dict(row)
        value["stale"] = bool(stale)
        value["projection_state"] = "stale" if stale else "live"
        value["read_only"] = True
        value["source"] = "agent-runtime-cache"
        value["autonomy_level"] = "L2"
        value["character_id"] = None
        return value

    @staticmethod
    def _task_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for key in ("budget_json", "result_json", "permissions_json", "logs_json", "artifacts_json"):
            value[key.removesuffix("_json")] = json.loads(value.pop(key))
        value["progress"] = float(value["progress"])
        return value

    def create_avatar_model(
        self,
        *,
        model_id: str,
        name: str,
        kind: str,
        path: str,
        size_bytes: int,
        modified_at: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        created_at = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO avatar_models(id, name, kind, path, size_bytes, modified_at, metadata_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (model_id, name, kind, path, size_bytes, modified_at, json.dumps(metadata, ensure_ascii=False), created_at),
            )
        return self.get_avatar_model(model_id)  # type: ignore[return-value]

    def get_avatar_model(self, model_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM avatar_models WHERE id=?", (model_id,)).fetchone()
        return self._avatar_model_row(row) if row is not None else None

    def find_avatar_model(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM avatar_models WHERE path=?", (path,)).fetchone()
        return self._avatar_model_row(row) if row is not None else None

    def list_avatar_models(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM avatar_models ORDER BY created_at DESC").fetchall()
        return [self._avatar_model_row(row) for row in rows]

    def update_avatar_model(
        self,
        model_id: str,
        *,
        size_bytes: int,
        modified_at: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE avatar_models SET size_bytes=?, modified_at=?, metadata_json=? WHERE id=?",
                (size_bytes, modified_at, json.dumps(metadata, ensure_ascii=False), model_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_avatar_model(model_id)

    def list_character_avatar_bindings(self, model_id: str) -> list[dict[str, str]]:
        """Return characters that currently reference an Avatar model."""
        with self._lock:
            rows = self._connection.execute("SELECT id, name, config_json FROM characters ORDER BY created_at").fetchall()
        bindings: list[dict[str, str]] = []
        for row in rows:
            config = json.loads(row["config_json"])
            if isinstance(config, dict) and config.get("avatar_model_id") == model_id:
                bindings.append({"id": row["id"], "name": row["name"]})
        return bindings

    def remove_avatar_model_if_unbound(
        self, model_id: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        """Atomically remove a registration only when no character references it."""
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM avatar_models WHERE id=?", (model_id,)).fetchone()
            if row is None:
                return None, []
            model = self._avatar_model_row(row)
            bindings = self.list_character_avatar_bindings(model_id)
            if bindings:
                return model, bindings
            self._connection.execute("DELETE FROM avatar_models WHERE id=?", (model_id,))
            return model, []

    @staticmethod
    def _avatar_model_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _normalize_snapshot_scope(scope: str) -> str:
    if not isinstance(scope, str) or scope.strip().lower() not in _SNAPSHOT_SCOPE_ALIASES:
        raise ValueError("snapshot scope must be system, modules, characters, or memories")
    return _SNAPSHOT_SCOPE_ALIASES[scope.strip().lower()]


def _normalize_agent_task_projection(value: Any, runtime_id: str) -> dict[str, Any]:
    """Build a strictly bounded, content-free cache row.

    This validation intentionally runs at the storage boundary as well as in
    the projector.  A future caller must not be able to bypass the projector
    and accidentally persist a title, prompt, command, path, or nested runtime
    payload in the derived cache.
    """

    if not isinstance(value, dict):
        raise ValueError("agent projection must be an object")
    clean_runtime_id = _opaque_projection_id(runtime_id, "runtime")
    raw_session = str(value.get("session_id") or value.get("id") or "").strip()
    if raw_session.startswith("agent:"):
        raw_session = raw_session.rsplit(":", 1)[-1]
    session_id = _opaque_projection_id(raw_session, "session")
    status_values = {
        "pending", "queued", "running", "steering", "completed", "complete",
        "success", "succeeded", "failed", "error", "cancelled", "canceled", "aborted",
        "waiting_approval", "paused", "unknown",
    }
    status = str(value.get("status") or "unknown").strip().lower()
    status = status if status in status_values else "unknown"
    progress = value.get("progress", 0)
    if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress):
        progress = 0.0
    progress = max(0.0, min(1.0, float(progress)))

    def finite_count(candidate: Any, maximum: int = 1_000_000) -> int | None:
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            return None
        if not math.isfinite(candidate) or candidate < 0 or candidate > maximum:
            return None
        return int(candidate)

    def compact_numbers(candidate: Any) -> dict[str, int | float]:
        if not isinstance(candidate, dict):
            return {}
        allowed = {
            "turns", "steps", "llmMs", "toolMs", "ttftMs", "ttftSteps",
            "decodeMs", "decodeTokens", "uncachedInputTokens", "outputTokens",
            "cacheReadTokens", "cacheWriteTokens", "projectedTokens", "pressureTokens",
            "contextWindow", "systemTokens", "toolsTokens", "messageTokens",
        }
        result: dict[str, int | float] = {}
        for key in allowed:
            number = candidate.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                continue
            if not math.isfinite(number) or number < 0 or number > 10_000_000_000:
                continue
            result[key] = int(number) if isinstance(number, int) or number.is_integer() else float(number)
        return result

    raw_metrics = value.get("metrics") if isinstance(value.get("metrics"), dict) else {}
    metrics = {
        key: compact_numbers(raw_metrics.get(key))
        for key in ("stats", "token_usage", "context", "context_breakdown")
        if isinstance(raw_metrics.get(key), dict)
    }
    raw_budget = value.get("budget") if isinstance(value.get("budget"), dict) else {}
    budget: dict[str, Any] = {"available": bool(raw_budget.get("available")), "source": "agent-runtime"}
    for key in ("token_limit", "cost_limit", "time_limit_seconds", "disk_limit_bytes"):
        number = finite_count(raw_budget.get(key), maximum=10_000_000_000_000)
        if number is not None:
            budget[key] = number
    raw_result = value.get("result") if isinstance(value.get("result"), dict) else {}
    raw_plan = raw_result.get("plan") if isinstance(raw_result.get("plan"), dict) else {}
    turns = _normalize_agent_turns(raw_result.get("turns"))
    step_count = finite_count(raw_plan.get("step_count"), maximum=64)
    completed_steps = finite_count(raw_plan.get("completed_steps"), maximum=64)
    if step_count is None:
        raw_steps = raw_plan.get("steps")
        step_count = min(64, sum(1 for item in raw_steps if isinstance(item, dict))) if isinstance(raw_steps, list) else 0
    if completed_steps is None:
        raw_steps = raw_plan.get("steps")
        completed_steps = min(64, sum(
            1 for item in raw_steps
            if isinstance(item, dict)
            and str(item.get("status") or "").lower() in {"completed", "complete", "done", "skipped"}
        )) if isinstance(raw_steps, list) else 0
    result = {
        "summary": "",
        "plan": {
            "active": bool(raw_plan.get("active")),
            "pending": bool(raw_plan.get("pending")),
            "step_count": step_count,
            "completed_steps": min(completed_steps, step_count),
        },
        "turns": turns,
    }
    allowed_actions = {
        "read", "search", "edit", "write", "delete", "move", "shell", "pwsh", "bash",
        "python", "network", "upload", "download", "login", "publish", "tool", "user-confirmation",
    }
    permissions = [
        str(item).strip().lower() if str(item).strip().lower() in allowed_actions else "user-confirmation"
        for item in (value.get("permissions") if isinstance(value.get("permissions"), list) else [])[:16]
    ]

    def compact_records(candidate: Any) -> list[dict[str, Any]]:
        if not isinstance(candidate, list):
            return []
        records: list[dict[str, Any]] = []
        event_types = {
            "turn/start", "turn/end", "step/start", "step/end", "tool/call", "tool/result",
            "approval/requested", "approval/resolved", "question/requested", "question/resolved",
            "session/title", "runtime-event",
        }
        for item in candidate[:16]:
            if not isinstance(item, dict):
                continue
            record: dict[str, Any] = {}
            event_type = str(item.get("type") or "").strip().lower()
            if event_type:
                record["type"] = event_type if event_type in event_types else "runtime-event"
            item_status = str(item.get("status") or "").strip().lower()
            if item_status:
                record["status"] = item_status if item_status in status_values else "unknown"
            sequence = finite_count(item.get("sequence", item.get("seq")))
            if sequence is not None:
                record["sequence"] = sequence
            file_count = finite_count(item.get("file_count"), maximum=100_000)
            if file_count is not None:
                record["file_count"] = file_count
            identifier = str(item.get("id") or "").strip()
            if identifier and re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", identifier):
                record["id"] = identifier
            if record:
                records.append(record)
        return records

    raw_workspace = value.get("workspace") if isinstance(value.get("workspace"), dict) else None
    workspace = None
    if raw_workspace is not None:
        workspace = {
            "id": _opaque_projection_id(str(raw_workspace.get("id") or "workspace"), "workspace"),
            "dirty": bool(raw_workspace.get("dirty")),
            "file_count": finite_count(raw_workspace.get("file_count"), maximum=100_000) or 0,
            "checkpoint_count": finite_count(raw_workspace.get("checkpoint_count"), maximum=100_000) or 0,
        }
    runtime_updated_at = value.get("updated_at")
    if runtime_updated_at is not None:
        candidate_time = str(runtime_updated_at).strip()
        runtime_updated_at = candidate_time[:120] if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T[0-9:.+Z-]{1,40}", candidate_time
        ) else None
    return {
        "id": f"agent:{clean_runtime_id}:{session_id}",
        "runtime_id": clean_runtime_id,
        "session_id": session_id,
        # Never persist user-controlled session titles.  The UI reconstructs
        # a generic label for stale rows.
        "title": "Agent 会话（最后已知）",
        "status": status,
        "progress": progress,
        "budget": budget,
        "result": result,
        "permissions": permissions,
        "logs": compact_records(value.get("logs")),
        "artifacts": compact_records(value.get("artifacts")),
        "metrics": metrics,
        "workspace": workspace,
        "runtime_updated_at": runtime_updated_at,
        "observed_at": utc_now(),
    }


def _normalize_agent_turns(value: Any) -> list[dict[str, Any]]:
    """Normalize a content-free turn ledger at the persistence boundary."""

    if not isinstance(value, list):
        return []
    statuses = {
        "running", "completed", "cancelled", "aborted", "failed",
        "error", "interrupted", "stopped",
    }
    modes = {"plan", "execute", "readonly"}

    def bounded_count(candidate: Any) -> int:
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            return 0
        if not math.isfinite(candidate):
            return 0
        return max(0, min(10_000, int(candidate)))

    normalized: list[dict[str, Any]] = []
    for item in value[-16:]:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or "").strip()
        if not identifier or len(identifier) > 96 or re.fullmatch(r"[A-Za-z0-9._:-]+", identifier) is None:
            continue
        status = str(item.get("status") or "running").strip().lower()
        record: dict[str, Any] = {
            "id": identifier,
            "status": status if status in statuses else "running",
            "steps": bounded_count(item.get("steps")),
            "tools": bounded_count(item.get("tools")),
            "approvals": bounded_count(item.get("approvals")),
            "artifacts": bounded_count(item.get("artifacts")),
        }
        turn = item.get("turn")
        if isinstance(turn, int) and not isinstance(turn, bool) and 0 <= turn <= 10_000_000_000:
            record["turn"] = turn
        elif isinstance(turn, str) and turn.strip() and len(turn.strip()) <= 80 and not any(ord(char) < 32 or ord(char) == 127 for char in turn):
            record["turn"] = turn.strip()
        mode = str(item.get("mode") or "").strip().lower()
        if mode in modes:
            record["mode"] = mode
        for key in ("start_seq", "end_seq"):
            sequence = item.get(key)
            if isinstance(sequence, int) and not isinstance(sequence, bool) and 0 <= sequence <= 10_000_000_000:
                record[key] = sequence
        normalized.append(record)
    return normalized


def _opaque_projection_id(value: str, label: str) -> str:
    """Keep cache identifiers bounded without persisting arbitrary text."""

    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 240 or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise ValueError(f"agent projection {label}_id is invalid")
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", candidate):
        return candidate
    return f"{label}-{hashlib.sha256(candidate.encode('utf-8')).hexdigest()[:24]}"


def _decode_snapshot_payload(value: str) -> dict[str, Any]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("snapshot payload must be an object")
    return payload


def _validate_snapshot_payload(payload: dict[str, Any]) -> tuple[str, str | None, dict[str, list[dict[str, Any]]]]:
    if not isinstance(payload, dict):
        raise ValueError("snapshot payload must be an object")
    if payload.get("format_version") != SNAPSHOT_FORMAT_VERSION:
        raise ValueError("unsupported snapshot format")
    scope = _normalize_snapshot_scope(payload.get("scope", ""))
    target_id = payload.get("target_id")
    if target_id is not None and (not isinstance(target_id, str) or not target_id.strip()):
        raise ValueError("snapshot target_id must be a non-empty string")
    if scope == "system" and target_id is not None:
        raise ValueError("system snapshots cannot have a target id")
    raw_tables = payload.get("tables")
    if not isinstance(raw_tables, dict):
        raise ValueError("snapshot tables must be an object")
    selected_tables = set(_SNAPSHOT_SCOPE_TABLES[scope])
    unknown_tables = set(raw_tables) - selected_tables
    if unknown_tables:
        raise ValueError(f"snapshot contains unsupported tables: {', '.join(sorted(unknown_tables))}")
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in _SNAPSHOT_SCOPE_TABLES[scope]:
        if table not in raw_tables:
            continue
        rows = raw_tables[table]
        if not isinstance(rows, list):
            raise ValueError(f"snapshot table must be an array: {table}")
        columns = set(_SNAPSHOT_TABLE_COLUMNS[table])
        validated_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != columns:
                raise ValueError(f"snapshot row has invalid columns: {table}")
            if target_id is not None and str(row[_SNAPSHOT_TABLE_KEYS[table]]) != target_id:
                raise ValueError(f"snapshot row does not match target_id: {table}")
            validated_rows.append(row)
        tables[table] = validated_rows
    return scope, target_id, tables


def _row_signature(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
