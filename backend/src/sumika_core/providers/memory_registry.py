"""Registry for replaceable memory backends."""

from __future__ import annotations

from typing import Any

from ..protocol.models import ProviderInfo
from .memory import MemoryProvider


class MemoryProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MemoryProvider] = {}

    def register(self, provider: MemoryProvider) -> None:
        provider_id = provider.info.id
        if provider.info.capability != "memory":
            raise ValueError(f"Unsupported memory capability: {provider.info.capability}")
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

    def configure(self, provider_id: str, config: dict[str, Any]) -> None:
        self.get(provider_id).configure(config)

    def list_memories(
        self,
        provider_id: str,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.get(provider_id).list_memories(character_id, category=category, query=query, limit=limit)

    def add_memory(self, provider_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.get(provider_id).add_memory(**kwargs)

    def delete_memory(self, provider_id: str, memory_id: str) -> bool:
        return self.get(provider_id).delete_memory(memory_id)

    def health(self) -> list[dict[str, Any]]:
        results = []
        for provider in self._providers.values():
            try:
                results.append(provider.health_check())
            except Exception as exc:  # provider boundary: report, do not crash core
                results.append({"ok": False, "provider_id": provider.info.id, "capability": "memory", "error": str(exc)})
        return results

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()


__all__ = ["MemoryProviderRegistry"]
