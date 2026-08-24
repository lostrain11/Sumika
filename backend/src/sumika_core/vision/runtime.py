"""Permission-gated visual observation orchestration.

The runtime does not capture devices. A desktop bridge supplies an in-memory
image buffer after the user grants a source permission. Raw bytes are passed
to the selected provider for the request lifetime only and are never included
in durable events.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from ..events import EventBus
from ..modules.catalog import ModuleCatalog
from ..providers.vision import VisionRequest
from ..providers.vision_registry import VisionProviderRegistry
from ..protocol.models import EventEnvelope
from ..storage import Storage


class VisionRuntimeError(ValueError):
    """Raised when a visual action is not allowed by module or permission state."""


class VisionRuntime:
    _SOURCES = ("screen", "camera")
    _PERMISSIONS = ("screen.read", "camera.read")
    _SOURCE_PERMISSIONS = {"screen": ("screen.read",), "camera": ("camera.read",)}
    _MAX_IMAGE_BYTES = 10 * 1024 * 1024
    _ALLOWED_MIME_PREFIXES = ("image/",)

    def __init__(
        self,
        storage: Storage,
        modules: ModuleCatalog,
        providers: VisionProviderRegistry,
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
            sources = [self._source_status(source) for source in self._SOURCES]
        return {"permissions": permissions, "sources": sources}

    def set_permission(self, permission_id: str, granted: bool) -> dict[str, Any]:
        if permission_id not in self._PERMISSIONS:
            raise VisionRuntimeError(f"Unknown vision permission: {permission_id}")
        if not isinstance(granted, bool):
            raise VisionRuntimeError("granted must be a boolean")
        state = "granted" if granted else "denied"
        self.storage.upsert_vision_permission(permission_id, state)
        self._publish("vision.permission.changed", {"permission_id": permission_id, "state": state})
        self.reconcile()
        return self.status()

    def start(self, source: str) -> dict[str, Any]:
        self._validate_source(source)
        with self._lock:
            module = self.modules.get("vision")
            if not module["enabled"]:
                raise VisionRuntimeError("Vision module is disabled")
            provider_id = str(module["implementation_id"])
            if provider_id == "none":
                raise VisionRuntimeError("Vision has no selected implementation")
            if not self.providers.has(provider_id):
                raise VisionRuntimeError(f"Unknown vision provider: {provider_id}")
            provider = self.providers.get(provider_id)
            if provider.info.status != "available":
                raise VisionRuntimeError(f"Vision provider is {provider.info.status}: {provider_id}")
            self._require_permissions(source)
            self._running.add(source)
        self._publish("vision.status.changed", {"source": source, "state": "running", "provider_id": provider_id})
        return self.status()

    def stop(self, source: str) -> dict[str, Any]:
        self._validate_source(source)
        with self._lock:
            was_running = source in self._running
            self._running.discard(source)
        if was_running:
            self._publish("vision.status.changed", {"source": source, "state": "stopped"})
        return self.status()

    def reconcile(self) -> None:
        """Stop active sources after module, provider, or permission changes."""
        stopped: list[str] = []
        with self._lock:
            for source in tuple(self._running):
                module = self.modules.get("vision")
                provider_id = str(module["implementation_id"])
                allowed = (
                    module["enabled"]
                    and provider_id != "none"
                    and self.providers.has(provider_id)
                    and self.providers.get(provider_id).info.status == "available"
                    and self._permissions_granted(source)
                )
                if not allowed:
                    self._running.remove(source)
                    stopped.append(source)
        for source in stopped:
            self._publish("vision.status.changed", {"source": source, "state": "stopped", "reason": "configuration_changed"})

    def observe(
        self,
        source: str,
        image: bytes,
        *,
        mime_type: str = "image/png",
        prompt: str | None = None,
    ) -> dict[str, Any]:
        self._validate_source(source)
        self._require_running(source)
        self._validate_image(image, mime_type)
        provider_id = self._selected_provider()
        content_length = len(image)
        content_sha256 = hashlib.sha256(image).hexdigest()
        try:
            result = self.providers.summarize(provider_id, VisionRequest(source, image, mime_type, prompt))
        except Exception as exc:
            raise VisionRuntimeError(f"Vision provider failed: {exc}") from exc
        if not isinstance(result.summary, str) or not result.summary.strip():
            raise VisionRuntimeError("Vision provider returned an empty summary")
        self._publish(
            "vision.observed",
            {
                "source": source,
                "provider_id": provider_id,
                "mime_type": mime_type,
                "content_length": content_length,
                "content_sha256": content_sha256,
                "summary_length": len(result.summary),
            },
        )
        return {"source": source, "provider_id": provider_id, "summary": result.summary}

    def close(self) -> None:
        with self._lock:
            self._running.clear()

    def _source_status(self, source: str) -> dict[str, Any]:
        module = self.modules.get("vision")
        provider_id = str(module["implementation_id"])
        provider_status = "unconfigured"
        if provider_id != "none" and self.providers.has(provider_id):
            provider_status = self.providers.get(provider_id).info.status
        permission_states = {permission: self._permission(permission)["state"] for permission in self._SOURCE_PERMISSIONS[source]}
        if not module["enabled"]:
            state = "disabled"
        elif provider_id == "none":
            state = "unconfigured"
        elif provider_status != "available":
            state = provider_status
        elif not all(value == "granted" for value in permission_states.values()):
            state = "permission_required"
        elif source in self._running:
            state = "running"
        else:
            state = "ready"
        return {
            "id": source,
            "enabled": bool(module["enabled"]),
            "provider_id": provider_id,
            "provider_status": provider_status,
            "state": state,
            "running": source in self._running,
            "permissions": permission_states,
        }

    def _permission(self, permission_id: str) -> dict[str, Any]:
        stored = self.storage.get_vision_permission(permission_id)
        if stored is not None:
            return stored
        return {"permission_id": permission_id, "state": "unknown", "updated_at": None}

    def _require_permissions(self, source: str) -> None:
        missing = [
            f"{permission} ({self._permission(permission)['state']})"
            for permission in self._SOURCE_PERMISSIONS[source]
            if self._permission(permission)["state"] != "granted"
        ]
        if missing:
            raise VisionRuntimeError(f"Vision permission required: {', '.join(missing)}")

    def _permissions_granted(self, source: str) -> bool:
        return all(self._permission(permission)["state"] == "granted" for permission in self._SOURCE_PERMISSIONS[source])

    def _selected_provider(self) -> str:
        module = self.modules.get("vision")
        provider_id = str(module["implementation_id"])
        if provider_id == "none" or not self.providers.has(provider_id):
            raise VisionRuntimeError("Vision has no available provider")
        if self.providers.get(provider_id).info.status != "available":
            raise VisionRuntimeError(f"Vision provider is not available: {provider_id}")
        return provider_id

    def _require_running(self, source: str) -> None:
        with self._lock:
            if source not in self._running:
                raise VisionRuntimeError(f"{source} observation is not started")

    @classmethod
    def _validate_source(cls, source: str) -> None:
        if source not in cls._SOURCES:
            raise VisionRuntimeError(f"Unknown vision source: {source}")

    @classmethod
    def _validate_image(cls, image: bytes, mime_type: str) -> None:
        if not isinstance(image, bytes) or not image:
            raise VisionRuntimeError("image must be a non-empty bytes buffer")
        if len(image) > cls._MAX_IMAGE_BYTES:
            raise VisionRuntimeError("image buffer is too large")
        if not isinstance(mime_type, str) or not mime_type.strip() or not mime_type.startswith(cls._ALLOWED_MIME_PREFIXES):
            raise VisionRuntimeError("mime_type must be an image MIME type")
        if len(mime_type) > 128:
            raise VisionRuntimeError("mime_type is too long")

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.publish(EventEnvelope(event_type, payload))


__all__ = ["VisionRuntime", "VisionRuntimeError"]
