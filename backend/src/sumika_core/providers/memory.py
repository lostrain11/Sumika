"""Memory provider contracts and reference implementations."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..protocol.models import ProviderInfo
from ..storage import Storage


class MemoryProvider(ABC):
    """Capability contract for searchable, character-scoped memory."""

    info: ProviderInfo

    def health_check(self) -> dict[str, Any]:
        return {"ok": self.info.status == "available", "provider_id": self.info.id, "capability": "memory"}

    def configure(self, config: dict[str, Any]) -> None:
        return None

    @abstractmethod
    def list_memories(
        self,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return character-scoped records, optionally filtered by text."""

    @abstractmethod
    def add_memory(
        self,
        *,
        memory_id: str,
        character_id: str,
        category: str,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one record and return its serialisable representation."""

    @abstractmethod
    def delete_memory(self, memory_id: str) -> bool:
        """Delete one record and report whether it existed."""

    def close(self) -> None:
        return None


_MEMORY_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "title": "允许的记忆类别",
            "items": {"type": "string"},
            "default": ["preferences"],
        }
    },
}


class SQLiteMemoryProvider(MemoryProvider):
    """Local reference implementation backed by the core's SQLite store."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.info = ProviderInfo(
            id="sqlite-reference",
            name="SQLite reference",
            capability="memory",
            description="本地 SQLite 记忆实现；正文不写入事件日志。",
            config_schema=_MEMORY_CONFIG_SCHEMA,
        )

    def list_memories(
        self,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.storage.list_memories(character_id, category=category, query=query, limit=limit)

    def add_memory(
        self,
        *,
        memory_id: str,
        character_id: str,
        category: str,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.storage.create_memory(
            memory_id=memory_id,
            character_id=character_id,
            category=category,
            content=content,
            source=source,
            metadata=metadata,
        )

    def delete_memory(self, memory_id: str) -> bool:
        return self.storage.delete_memory(memory_id)


_COMMAND_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["executable"],
    "properties": {
        "executable": {"type": "string", "title": "软件路径"},
        "args": {"type": "array", "items": {"type": "string"}, "title": "启动参数", "default": []},
        "working_directory": {"type": "string", "title": "工作目录"},
        "timeout": {"type": "number", "title": "超时（秒）", "minimum": 1, "default": 30},
    },
}


class CommandMemoryProvider(MemoryProvider):
    """Non-shell JSONL adapter for an external memory application."""

    def __init__(
        self,
        executable: str = "",
        args: list[str] | None = None,
        working_directory: str | None = None,
        timeout: float = 30,
    ) -> None:
        self.executable = executable
        self.args = list(args or [])
        self.working_directory = working_directory
        self.timeout = timeout
        self.info = ProviderInfo(
            id="external-memory",
            name="External memory",
            capability="memory",
            status="unconfigured",
            description="调用明确配置路径的 JSONL 记忆软件。",
            config_schema=_COMMAND_CONFIG_SCHEMA,
        )
        self._refresh_status()

    def configure(self, config: dict[str, Any]) -> None:
        executable = config.get("executable")
        args = config.get("args")
        working_directory = config.get("working_directory")
        timeout = config.get("timeout")
        if isinstance(executable, str):
            self.executable = executable.strip()
        if isinstance(args, list) and all(isinstance(item, str) for item in args):
            self.args = list(args)
        if isinstance(working_directory, str):
            self.working_directory = working_directory.strip() or None
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout >= 1:
            self.timeout = float(timeout)
        self._refresh_status()

    def list_memories(
        self,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        responses = self._run(
            {
                "type": "memory.list",
                "character_id": character_id,
                "category": category,
                "query": query,
                "limit": limit,
            }
        )
        for response in responses:
            self._raise_if_error(response)
            if isinstance(response.get("items"), list):
                return [item for item in response["items"] if isinstance(item, dict)]
            if isinstance(response.get("memory"), dict):
                return [response["memory"]]
        return []

    def add_memory(
        self,
        *,
        memory_id: str,
        character_id: str,
        category: str,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        responses = self._run(
            {
                "type": "memory.add",
                "memory": {
                    "id": memory_id,
                    "character_id": character_id,
                    "category": category,
                    "content": content,
                    "source": source,
                    "metadata": metadata,
                },
            }
        )
        for response in responses:
            self._raise_if_error(response)
            if isinstance(response.get("memory"), dict):
                return response["memory"]
        raise RuntimeError("External memory provider returned no memory")

    def delete_memory(self, memory_id: str) -> bool:
        responses = self._run({"type": "memory.delete", "memory_id": memory_id})
        for response in responses:
            self._raise_if_error(response)
            if isinstance(response.get("deleted"), bool):
                return response["deleted"]
        return False

    def _refresh_status(self) -> None:
        self.info.status = "available" if self.executable.strip() and Path(self.executable).is_file() else "unconfigured"

    def _run(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.executable.strip():
            raise RuntimeError("External memory provider is not configured")
        process = subprocess.Popen(
            [self.executable, *self.args],
            cwd=self.working_directory or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            try:
                stdout, stderr = process.communicate(json.dumps(payload, ensure_ascii=False) + "\n", timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise TimeoutError("External memory provider timed out") from exc
            if process.returncode != 0:
                raise RuntimeError(f"External memory provider exited with {process.returncode}: {stderr[:500]}")
            responses: list[dict[str, Any]] = []
            for line in stdout.splitlines():
                value = line.strip()
                if not value:
                    continue
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    responses.append(parsed)
            return responses
        finally:
            if process.poll() is None:
                process.kill()

    @staticmethod
    def _raise_if_error(response: dict[str, Any]) -> None:
        if response.get("type") == "error":
            raise RuntimeError(str(response.get("message", "external memory error")))


__all__ = [
    "CommandMemoryProvider",
    "MemoryProvider",
    "SQLiteMemoryProvider",
]
