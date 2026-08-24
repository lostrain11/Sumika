"""Permission-gated audio orchestration.

This layer deliberately does not open OS devices yet. The desktop shell or a
future Tauri bridge can capture bytes and pass them to the selected provider;
the runtime keeps the permission decision and provider lifecycle auditable.
"""

from __future__ import annotations

import threading
from typing import Any

from ..events import EventBus
from ..modules.catalog import ModuleCatalog
from ..providers.audio import ASRRequest, TTSRequest, TTSResult, VADRequest
from ..providers.audio_registry import AudioProviderRegistry
from ..protocol.models import EventEnvelope
from ..storage import Storage


class AudioRuntimeError(ValueError):
    """Raised when an audio action is not allowed by module or permission state."""


class AudioRuntime:
    _CAPABILITIES = ("asr", "tts", "vad")
    _PERMISSIONS = ("microphone", "audio_output")
    _CAPABILITY_PERMISSIONS = {
        "asr": ("microphone",),
        "tts": ("audio_output",),
        "vad": ("microphone",),
    }

    def __init__(
        self,
        storage: Storage,
        modules: ModuleCatalog,
        providers: AudioProviderRegistry,
        events: EventBus,
    ) -> None:
        self.storage = storage
        self.modules = modules
        self.providers = providers
        self.events = events
        self._running: set[str] = set()
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            permissions = [self._permission(permission_id) for permission_id in self._PERMISSIONS]
            capabilities = [self._capability_status(capability) for capability in self._CAPABILITIES]
        return {"permissions": permissions, "capabilities": capabilities}

    def set_permission(self, permission_id: str, granted: bool) -> dict[str, Any]:
        if permission_id not in self._PERMISSIONS:
            raise AudioRuntimeError(f"Unknown audio permission: {permission_id}")
        if not isinstance(granted, bool):
            raise AudioRuntimeError("granted must be a boolean")
        state = "granted" if granted else "denied"
        self.storage.upsert_audio_permission(permission_id, state)
        self._publish("audio.permission.changed", {"permission_id": permission_id, "state": state})
        self.reconcile()
        return self.status()

    def start(self, capability: str) -> dict[str, Any]:
        self._validate_capability(capability)
        with self._lock:
            module = self.modules.get(capability)
            if not module["enabled"]:
                raise AudioRuntimeError(f"{capability} module is disabled")
            provider_id = str(module["implementation_id"])
            if provider_id == "none":
                raise AudioRuntimeError(f"{capability} has no selected implementation")
            if not self.providers.has(provider_id):
                raise AudioRuntimeError(f"Unknown audio provider: {provider_id}")
            provider = self.providers.get(provider_id)
            if provider.info.status != "available":
                raise AudioRuntimeError(f"Audio provider is {provider.info.status}: {provider_id}")
            self._require_permissions(capability)
            self._running.add(capability)
        self._publish("audio.status.changed", {"capability": capability, "state": "running", "provider_id": provider_id})
        return self.status()

    def stop(self, capability: str) -> dict[str, Any]:
        self._validate_capability(capability)
        with self._lock:
            was_running = capability in self._running
            self._running.discard(capability)
        if was_running:
            self._publish("audio.status.changed", {"capability": capability, "state": "stopped"})
        return self.status()

    def reconcile(self) -> None:
        """Stop active capabilities after a module or permission change."""
        stopped: list[str] = []
        with self._lock:
            for capability in tuple(self._running):
                module = self.modules.get(capability)
                provider_id = str(module["implementation_id"])
                allowed = (
                    module["enabled"]
                    and provider_id != "none"
                    and self.providers.has(provider_id)
                    and self.providers.get(provider_id).info.status == "available"
                    and self._permissions_granted(capability)
                )
                if not allowed:
                    self._running.remove(capability)
                    stopped.append(capability)
        for capability in stopped:
            self._publish("audio.status.changed", {"capability": capability, "state": "stopped", "reason": "configuration_changed"})

    def transcribe(self, audio: bytes, *, sample_rate: int, channels: int, language: str | None = None) -> str:
        self._require_running("asr")
        self._validate_audio(audio, sample_rate, channels)
        provider_id = self._selected_provider("asr")
        try:
            return self.providers.transcribe(provider_id, ASRRequest(audio, sample_rate, channels, language))
        except Exception as exc:
            raise AudioRuntimeError(f"ASR provider failed: {exc}") from exc

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
        sample_rate: int | None = None,
    ) -> TTSResult:
        self._require_running("tts")
        if not isinstance(text, str) or not text.strip():
            raise AudioRuntimeError("text must be a non-empty string")
        if sample_rate is not None and (not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0):
            raise AudioRuntimeError("sample_rate must be a positive integer")
        provider_id = self._selected_provider("tts")
        try:
            result = self.providers.synthesize(provider_id, TTSRequest(text, voice, language, sample_rate))
        except Exception as exc:
            raise AudioRuntimeError(f"TTS provider failed: {exc}") from exc
        if len(result.audio) > 10 * 1024 * 1024:
            raise AudioRuntimeError("TTS audio output is too large")
        return result

    def detect(self, audio: bytes, *, sample_rate: int, channels: int) -> bool:
        self._require_running("vad")
        self._validate_audio(audio, sample_rate, channels)
        provider_id = self._selected_provider("vad")
        try:
            return self.providers.detect(provider_id, VADRequest(audio, sample_rate, channels))
        except Exception as exc:
            raise AudioRuntimeError(f"VAD provider failed: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            self._running.clear()

    def _capability_status(self, capability: str) -> dict[str, Any]:
        module = self.modules.get(capability)
        provider_id = str(module["implementation_id"])
        provider_status = "unconfigured"
        if provider_id != "none" and self.providers.has(provider_id):
            provider_status = self.providers.get(provider_id).info.status
        required_permissions = list(self._CAPABILITY_PERMISSIONS[capability])
        permission_states = {permission: self._permission(permission)["state"] for permission in required_permissions}
        if not module["enabled"]:
            state = "disabled"
        elif provider_id == "none":
            state = "unconfigured"
        elif provider_status != "available":
            state = provider_status
        elif not all(value == "granted" for value in permission_states.values()):
            state = "permission_required"
        elif capability in self._running:
            state = "running"
        else:
            state = "ready"
        return {
            "id": capability,
            "enabled": bool(module["enabled"]),
            "provider_id": provider_id,
            "provider_status": provider_status,
            "state": state,
            "running": capability in self._running,
            "permissions": permission_states,
        }

    def _permission(self, permission_id: str) -> dict[str, Any]:
        stored = self.storage.get_audio_permission(permission_id)
        if stored is not None:
            return stored
        return {"permission_id": permission_id, "state": "unknown", "updated_at": None}

    def _require_permissions(self, capability: str) -> None:
        missing = [
            f"{permission} ({self._permission(permission)['state']})"
            for permission in self._CAPABILITY_PERMISSIONS[capability]
            if self._permission(permission)["state"] != "granted"
        ]
        if missing:
            raise AudioRuntimeError(f"Audio permission required: {', '.join(missing)}")

    def _permissions_granted(self, capability: str) -> bool:
        return all(
            self._permission(permission)["state"] == "granted"
            for permission in self._CAPABILITY_PERMISSIONS[capability]
        )

    def _selected_provider(self, capability: str) -> str:
        module = self.modules.get(capability)
        provider_id = str(module["implementation_id"])
        if provider_id == "none" or not self.providers.has(provider_id):
            raise AudioRuntimeError(f"{capability} has no available provider")
        return provider_id

    def _require_running(self, capability: str) -> None:
        self._validate_capability(capability)
        with self._lock:
            if capability not in self._running:
                raise AudioRuntimeError(f"{capability} is not started")

    @classmethod
    def _validate_capability(cls, capability: str) -> None:
        if capability not in cls._CAPABILITIES:
            raise AudioRuntimeError(f"Unknown audio capability: {capability}")

    @staticmethod
    def _validate_audio(audio: bytes, sample_rate: int, channels: int) -> None:
        if not isinstance(audio, bytes):
            raise AudioRuntimeError("audio must be bytes")
        if len(audio) > 10 * 1024 * 1024:
            raise AudioRuntimeError("audio buffer is too large")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
            raise AudioRuntimeError("sample_rate must be a positive integer")
        if not isinstance(channels, int) or isinstance(channels, bool) or channels <= 0:
            raise AudioRuntimeError("channels must be a positive integer")

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.publish(EventEnvelope(event_type, payload))


__all__ = ["AudioRuntime", "AudioRuntimeError"]
