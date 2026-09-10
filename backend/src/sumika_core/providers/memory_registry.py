"""Registry for replaceable memory backends."""

from __future__ import annotations

from typing import Any

from ..memory.contracts import (
    MemoryScope,
    describe_capabilities,
    require_capability,
    safe_provider_error,
    validate_delete_result,
    validate_memory_record,
    validate_memory_records,
)
from ..protocol.models import ProviderInfo
from .memory import MemoryProvider


class MemoryProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MemoryProvider] = {}

    def register(self, provider: MemoryProvider) -> None:
        provider_id = provider.info.id
        if provider.info.capability != "memory":
            raise ValueError(f"Unsupported memory capability: {provider.info.capability}")
        describe_capabilities(provider)
        if provider_id in self._providers:
            raise ValueError(f"Memory provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> MemoryProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown memory provider: {provider_id}") from exc

    def has(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def unregister(self, provider_id: str) -> bool:
        provider = self._providers.pop(provider_id, None)
        if provider is None:
            return False
        provider.close()
        return True

    def list(self) -> list[ProviderInfo]:
        return [provider.info for provider in self._providers.values()]

    def describe(self, provider_id: str) -> dict[str, Any]:
        provider = self.get(provider_id)
        return {"provider_id": provider.info.id, **describe_capabilities(provider)}

    def configure(self, provider_id: str, config: dict[str, Any]) -> None:
        self.get(provider_id).configure(config)

    def require_capability(self, provider_id: str, capability: str) -> None:
        require_capability(self.get(provider_id), capability)

    def list_memories(
        self,
        provider_id: str,
        scope: MemoryScope,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        provider = self.get(provider_id)
        require_capability(provider, "list")
        records = provider.list_memories(scope.assistant_id, category=category, query=query, limit=limit)
        return validate_memory_records(
            records,
            scope=scope,
            allow_legacy_fields=bool(getattr(provider, "legacy_record_compatibility", False)),
        )

    def add_memory(self, provider_id: str, *, scope: MemoryScope, **kwargs: Any) -> dict[str, Any]:
        provider = self.get(provider_id)
        require_capability(provider, "add")
        record = provider.add_memory(assistant_id=scope.assistant_id, **kwargs)
        return validate_memory_record(
            record,
            scope=scope,
            expected_memory_id=kwargs.get("memory_id"),
            allow_legacy_fields=bool(getattr(provider, "legacy_record_compatibility", False)),
        )

    def delete_memory(self, provider_id: str, *, scope: MemoryScope, memory_id: str) -> bool:
        provider = self.get(provider_id)
        require_capability(provider, "delete")
        require_capability(provider, "scoped_delete")
        result = provider.delete_memory(memory_id, assistant_id=scope.assistant_id)
        return validate_delete_result(result, scope=scope, memory_id=memory_id)

    def list_context_sources(
        self,
        provider_id: str,
        *,
        scope: MemoryScope,
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        provider = self.get(provider_id)
        require_capability(provider, "context_sources")
        records = provider.list_context_sources(scope.assistant_id, query=query, limit=limit)
        return validate_memory_records(
            records,
            scope=scope,
            allow_legacy_fields=bool(getattr(provider, "legacy_record_compatibility", False)),
        )

    def health(self) -> list[dict[str, Any]]:
        results = []
        for provider in self._providers.values():
            try:
                results.append(provider.health_check())
            except Exception:
                results.append(
                    {
                        "ok": False,
                        "provider_id": provider.info.id,
                        "capability": "memory",
                        "error": safe_provider_error(),
                    }
                )
        return results

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()


__all__ = ["MemoryProviderRegistry"]
