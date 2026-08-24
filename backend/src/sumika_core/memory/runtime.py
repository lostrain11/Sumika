"""Auditable orchestration for character-scoped long-term memory."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from ..events import EventBus
from ..modules.catalog import ModuleCatalog
from ..providers.memory_registry import MemoryProviderRegistry
from ..protocol.models import EventEnvelope
from ..storage import Storage


class MemoryRuntimeError(ValueError):
    """Raised when memory is disabled or a record violates its module policy."""


class MemoryRuntime:
    DEFAULT_CATEGORIES = ("preferences",)

    def __init__(
        self,
        storage: Storage,
        modules: ModuleCatalog,
        providers: MemoryProviderRegistry,
        events: EventBus,
    ) -> None:
        self.storage = storage
        self.modules = modules
        self.providers = providers
        self.events = events

    def status(self) -> dict[str, Any]:
        module = self.modules.get("memory")
        provider_id = str(module["implementation_id"])
        provider_status = "unconfigured"
        if provider_id != "none" and self.providers.has(provider_id):
            provider_status = self.providers.get(provider_id).info.status
        if not module["enabled"]:
            state = "disabled"
        elif provider_id == "none":
            state = "unconfigured"
        else:
            state = provider_status
        return {
            "enabled": bool(module["enabled"]),
            "provider_id": provider_id,
            "provider_status": provider_status,
            "state": state,
            "allowed_categories": list(self._allowed_categories(module["config"])),
            "permissions": list(module["permissions"]),
        }

    def list(
        self,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._validate_character(character_id)
        provider_id, module = self._ready()
        categories = self._allowed_categories(module["config"])
        if category is not None:
            self._validate_category(category)
            if category not in categories:
                raise MemoryRuntimeError(f"Memory category is not enabled: {category}")
        if query is not None and len(query) > 200:
            raise MemoryRuntimeError("Memory query is too long")
        try:
            records = self.providers.list_memories(
                provider_id,
                character_id,
                category=category,
                query=query,
                limit=limit,
            )
        except Exception as exc:
            raise MemoryRuntimeError(f"Memory provider failed: {exc}") from exc
        return [
            record
            for record in records
            if isinstance(record, dict) and record.get("category") in categories
        ]

    def add(
        self,
        *,
        character_id: str,
        category: str,
        content: str,
        source: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_character(character_id)
        provider_id, module = self._ready()
        self._validate_category(category)
        if category not in self._allowed_categories(module["config"]):
            raise MemoryRuntimeError(f"Memory category is not enabled: {category}")
        if not isinstance(content, str) or not content.strip():
            raise MemoryRuntimeError("Memory content must be a non-empty string")
        if len(content) > 20_000:
            raise MemoryRuntimeError("Memory content is too long")
        if not isinstance(source, str) or not source.strip() or len(source) > 128:
            raise MemoryRuntimeError("Memory source must be a non-empty short string")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise MemoryRuntimeError("Memory metadata must be an object")
        try:
            encoded_metadata = json.dumps(metadata, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise MemoryRuntimeError("Memory metadata must be JSON serialisable") from exc
        if len(encoded_metadata.encode("utf-8")) > 16_000:
            raise MemoryRuntimeError("Memory metadata is too large")
        memory_id = f"memory-{uuid4().hex[:12]}"
        try:
            record = self.providers.add_memory(
                provider_id,
                memory_id=memory_id,
                character_id=character_id,
                category=category,
                content=content,
                source=source.strip(),
                metadata=metadata,
            )
        except Exception as exc:
            raise MemoryRuntimeError(f"Memory provider failed: {exc}") from exc
        if not isinstance(record, dict):
            raise MemoryRuntimeError("Memory provider returned an invalid record")
        self._publish(
            "memory.created",
            {
                "memory": self._audit_record(record, content=content),
            },
            character_id=character_id,
        )
        return record

    def delete(self, memory_id: str) -> bool:
        provider_id, _ = self._ready()
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise MemoryRuntimeError("memory_id must not be empty")
        try:
            deleted = self.providers.delete_memory(provider_id, memory_id)
        except Exception as exc:
            raise MemoryRuntimeError(f"Memory provider failed: {exc}") from exc
        if not deleted:
            raise MemoryRuntimeError(f"Unknown memory: {memory_id}")
        self._publish("memory.deleted", {"memory_id": memory_id})
        return True

    def _ready(self) -> tuple[str, dict[str, Any]]:
        module = self.modules.get("memory")
        if not module["enabled"]:
            raise MemoryRuntimeError("Memory module is disabled")
        provider_id = str(module["implementation_id"])
        if provider_id == "none":
            raise MemoryRuntimeError("Memory has no selected implementation")
        if not self.providers.has(provider_id):
            raise MemoryRuntimeError(f"Unknown memory provider: {provider_id}")
        provider = self.providers.get(provider_id)
        if provider.info.status != "available":
            raise MemoryRuntimeError(f"Memory provider is {provider.info.status}: {provider_id}")
        return provider_id, module

    def _validate_character(self, character_id: str) -> None:
        if not isinstance(character_id, str) or not character_id.strip():
            raise MemoryRuntimeError("character_id must not be empty")
        if self.storage.get_character(character_id) is None:
            raise MemoryRuntimeError(f"Unknown character: {character_id}")

    @classmethod
    def _allowed_categories(cls, config: dict[str, Any]) -> tuple[str, ...]:
        raw = config.get("categories", cls.DEFAULT_CATEGORIES)
        if not isinstance(raw, list):
            return cls.DEFAULT_CATEGORIES
        categories = tuple(
            str(item).strip()
            for item in raw
            if isinstance(item, str) and item.strip() and len(item.strip()) <= 64
        )
        return categories

    @staticmethod
    def _validate_category(category: str) -> None:
        if not isinstance(category, str) or not category.strip() or len(category.strip()) > 64:
            raise MemoryRuntimeError("Memory category must be a non-empty short string")

    @staticmethod
    def _audit_record(record: dict[str, Any], *, content: str) -> dict[str, Any]:
        return {
            "id": record.get("id"),
            "character_id": record.get("character_id"),
            "category": record.get("category"),
            "source": record.get("source"),
            "content_length": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    def _publish(self, event_type: str, payload: dict[str, Any], *, character_id: str | None = None) -> None:
        self.events.publish(EventEnvelope(event_type, payload, character_id=character_id))


__all__ = ["MemoryRuntime", "MemoryRuntimeError"]
