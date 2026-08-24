"""Registry for ASR, TTS and VAD implementations."""

from __future__ import annotations

from typing import Any

from .audio import ASRProvider, ASRRequest, AudioProvider, TTSProvider, TTSRequest, TTSResult, VADProvider, VADRequest
from ..protocol.models import ProviderInfo


class AudioProviderRegistry:
    """Keep capability-specific providers replaceable at runtime."""

    _CAPABILITIES = {"asr", "tts", "vad"}

    def __init__(self) -> None:
        self._providers: dict[str, AudioProvider] = {}

    def register(self, provider: AudioProvider) -> None:
        provider_id = provider.info.id
        if provider.info.capability not in self._CAPABILITIES:
            raise ValueError(f"Unsupported audio capability: {provider.info.capability}")
        if provider_id in self._providers:
            raise ValueError(f"Audio provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> AudioProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"Unknown audio provider: {provider_id}") from exc

    def has(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def unregister(self, provider_id: str) -> bool:
        provider = self._providers.pop(provider_id, None)
        if provider is None:
            return False
        provider.close()
        return True

    def list(self, capability: str | None = None) -> list[ProviderInfo]:
        providers = self._providers.values()
        if capability is not None:
            providers = (provider for provider in providers if provider.info.capability == capability)
        return [provider.info for provider in providers]

    def configure(self, provider_id: str, config: dict[str, Any]) -> None:
        self.get(provider_id).configure(config)

    def transcribe(self, provider_id: str, request: ASRRequest) -> str:
        provider = self.get(provider_id)
        if not isinstance(provider, ASRProvider):
            raise TypeError(f"Provider is not ASR: {provider_id}")
        return provider.transcribe(request)

    def synthesize(self, provider_id: str, request: TTSRequest) -> TTSResult:
        provider = self.get(provider_id)
        if not isinstance(provider, TTSProvider):
            raise TypeError(f"Provider is not TTS: {provider_id}")
        return provider.synthesize(request)

    def detect(self, provider_id: str, request: VADRequest) -> bool:
        provider = self.get(provider_id)
        if not isinstance(provider, VADProvider):
            raise TypeError(f"Provider is not VAD: {provider_id}")
        return provider.detect(request)

    def health(self) -> list[dict[str, Any]]:
        results = []
        for provider in self._providers.values():
            try:
                results.append(provider.health_check())
            except Exception as exc:  # provider boundary: report, do not crash core
                results.append({"ok": False, "provider_id": provider.info.id, "capability": provider.info.capability, "error": str(exc)})
        return results

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()


__all__ = ["AudioProviderRegistry"]
