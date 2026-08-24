"""Registry for replaceable visual observation providers."""

from __future__ import annotations

from typing import Any

from ..protocol.models import ProviderInfo
from .vision import VisionProvider, VisionRequest, VisionResult


class VisionProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, VisionProvider] = {}

    def register(self, provider: VisionProvider) -> None:
        provider_id = provider.info.id
        if provider.info.capability != "vision":
            raise ValueError(f"Unsupported vision capability: {provider.info.capability}")
        if provider_id in self._providers:
            raise ValueError(f"Vision provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> VisionProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown vision provider: {provider_id}") from exc

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

    def summarize(self, provider_id: str, request: VisionRequest) -> VisionResult:
        return self.get(provider_id).summarize(request)

    def health(self) -> list[dict[str, Any]]:
        results = []
        for provider in self._providers.values():
            try:
                results.append(provider.health_check())
            except Exception as exc:  # provider boundary: report, do not crash core
                results.append({"ok": False, "provider_id": provider.info.id, "capability": "vision", "error": str(exc)})
        return results

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()


__all__ = ["VisionProviderRegistry"]
