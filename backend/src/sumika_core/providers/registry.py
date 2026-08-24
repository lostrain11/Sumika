from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..protocol.models import ChatRequest, ProviderInfo
from .base import LLMProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        provider_id = provider.info.id
        if provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> LLMProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {provider_id}") from exc

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

    def stream(self, provider_id: str, request: ChatRequest) -> Iterable[str]:
        return self.get(provider_id).stream(request)

    def configure(self, provider_id: str, config: dict[str, Any]) -> None:
        self.get(provider_id).configure(config)

    def health(self) -> list[dict[str, Any]]:
        results = []
        for provider in self._providers.values():
            try:
                results.append(provider.health_check())
            except Exception as exc:  # provider boundary: report, do not crash core
                results.append({"ok": False, "provider_id": provider.info.id, "error": str(exc)})
        return results

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()
