"""Small, serialisable contracts shared by the core and UI.

The dataclasses intentionally contain no provider-specific fields. Provider
configuration stays in a manifest/schema owned by the implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now)
    character_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatRequest:
    session_id: str
    messages: list[Message]
    provider_id: str = "openai-compatible"
    character_id: str | None = None
    temperature: float = 0.7
    max_tokens: int = 512


@dataclass(slots=True)
class ProviderInfo:
    id: str
    name: str
    capability: str = "llm"
    status: Literal["available", "unconfigured", "error"] = "available"
    description: str = ""
    config_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProviderStatus = Literal["starting", "ready", "running", "stopped", "error"]


@dataclass(slots=True)
class EventEnvelope:
    event_type: str
    payload: dict[str, Any]
    session_id: str | None = None
    character_id: str | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
