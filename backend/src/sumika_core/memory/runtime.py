"""Sumika host adapter for assistant-scoped long-term memory."""

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
from .contracts import MemoryContractError, MemoryScope, safe_provider_error


class MemoryRuntimeError(ValueError):
    """Raised when memory is disabled or violates its host policy."""


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
        capabilities: dict[str, Any] | None = None
        if module["enabled"] and provider_id != "none" and self.providers.has(provider_id):
            provider = self.providers.get(provider_id)
            provider_status = provider.info.status
            capabilities = self.providers.describe(provider_id)
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
            "contract": capabilities,
        }

    def list(
        self,
        assistant_id: str | None = None,
        *,
        character_id: str | None = None,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        scope = self._scope(assistant_id=assistant_id, character_id=character_id)
        provider_id, module = self._ready("list")
        categories = self._allowed_categories(module["config"])
        if category is not None:
            self._validate_category(category)
            if category not in categories:
                raise MemoryRuntimeError(f"Memory category is not enabled: {category}")
        if query is not None and len(query) > 200:
            raise MemoryRuntimeError("Memory query is too long")
        try:
            return self.providers.list_memories(
                provider_id,
                scope,
                category=category,
                query=query,
                limit=limit,
            )
        except MemoryContractError as exc:
            raise MemoryRuntimeError(str(exc)) from exc
        except Exception as exc:
            raise MemoryRuntimeError(safe_provider_error()) from exc

    def add(
        self,
        *,
        assistant_id: str | None = None,
        character_id: str | None = None,
        category: str,
        content: str,
        source: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(assistant_id=assistant_id, character_id=character_id)
        provider_id, module = self._ready("add")
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
                scope=scope,
                memory_id=memory_id,
                category=category,
                content=content,
                source=source.strip(),
                metadata=metadata,
            )
        except MemoryContractError as exc:
            raise MemoryRuntimeError(str(exc)) from exc
        except Exception as exc:
            raise MemoryRuntimeError(safe_provider_error()) from exc
        self._publish(
            "memory.created",
            {"memory": self._audit_record(record, content=content)},
            character_id=scope.character_id,
        )
        return record

    def delete(
        self,
        memory_id: str,
        *,
        assistant_id: str | None = None,
        character_id: str | None = None,
    ) -> bool:
        scope = self._scope(assistant_id=assistant_id, character_id=character_id)
        provider_id, _ = self._ready("scoped_delete")
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise MemoryRuntimeError("memory_id must not be empty")
        try:
            deleted = self.providers.delete_memory(provider_id, scope=scope, memory_id=memory_id)
        except MemoryContractError as exc:
            raise MemoryRuntimeError(str(exc)) from exc
        except Exception as exc:
            raise MemoryRuntimeError(safe_provider_error()) from exc
        if not deleted:
            raise MemoryRuntimeError(f"Unknown memory: {memory_id}")
        self._publish("memory.deleted", {"memory_id": memory_id}, character_id=scope.character_id)
        return True

    def context_sources(
        self,
        *,
        assistant_id: str | None = None,
        character_id: str | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        scope = self._scope(assistant_id=assistant_id, character_id=character_id)
        provider_id, _ = self._ready("context_sources")
        if query is not None and len(query) > 200:
            raise MemoryRuntimeError("Memory query is too long")
        try:
            return self.providers.list_context_sources(provider_id, scope=scope, query=query, limit=limit)
        except MemoryContractError as exc:
            raise MemoryRuntimeError(str(exc)) from exc
        except Exception as exc:
            raise MemoryRuntimeError(safe_provider_error()) from exc

    def _ready(self, capability: str) -> tuple[str, dict[str, Any]]:
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
        try:
            self.providers.require_capability(provider_id, capability)
        except MemoryContractError as exc:
            raise MemoryRuntimeError(str(exc)) from exc
        return provider_id, module

    def _scope(self, *, assistant_id: str | None, character_id: str | None) -> MemoryScope:
        try:
            scope = MemoryScope.from_ids(assistant_id=assistant_id, character_id=character_id)
        except MemoryContractError as exc:
            raise MemoryRuntimeError(str(exc)) from exc
        if self.storage.get_character(scope.character_id) is None:
            raise MemoryRuntimeError(f"Unknown character: {scope.character_id}")
        return scope

    @classmethod
    def _allowed_categories(cls, config: dict[str, Any]) -> tuple[str, ...]:
        raw = config.get("categories", cls.DEFAULT_CATEGORIES)
        if not isinstance(raw, list):
            return cls.DEFAULT_CATEGORIES
        return tuple(
            str(item).strip()
            for item in raw
            if isinstance(item, str) and item.strip() and len(item.strip()) <= 64
        )

    @staticmethod
    def _validate_category(category: str) -> None:
        if not isinstance(category, str) or not category.strip() or len(category.strip()) > 64:
            raise MemoryRuntimeError("Memory category must be a non-empty short string")

    @staticmethod
    def _audit_record(record: dict[str, Any], *, content: str) -> dict[str, Any]:
        return {
            "id": record.get("id"),
            "assistant_id": record.get("assistant_id"),
            "character_id": record.get("character_id"),
            "category": record.get("category"),
            "source": record.get("source"),
            "revision": record.get("revision"),
            "status": record.get("status"),
            "content_length": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    def _publish(self, event_type: str, payload: dict[str, Any], *, character_id: str | None = None) -> None:
        self.events.publish(EventEnvelope(event_type, payload, character_id=character_id))


__all__ = ["MemoryRuntime", "MemoryRuntimeError"]
