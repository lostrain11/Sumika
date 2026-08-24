"""SQLite persistence with explicit schema versioning and event history."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .protocol.models import Message, utc_now


SCHEMA_VERSION = 11

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
    "tasks": "id",
    "avatar_models": "id",
    "audio_permissions": "permission_id",
    "vision_permissions": "permission_id",
    "memories": "id",
}
_SNAPSHOT_SCOPE_TABLES = {
    "system": tuple(_SNAPSHOT_TABLE_COLUMNS),
    "modules": ("module_settings", "provider_profiles"),
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

    @staticmethod
    def _plugin_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["manifest"] = json.loads(value.pop("manifest_json"))
        value["launcher"] = json.loads(value.pop("launcher_json", "{}"))
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
