"""Stable, runtime-neutral Agent contracts used by the Sumika UI.

``extensions`` contains only a bridge's bounded presentation metadata. Raw
harness arguments, results, prompts, and transient queue messages stay outside
the Sumika event log.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4


@dataclass(slots=True)
class AgentEvent:
    event_type: str
    session_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    status: str = "unknown"
    content: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if not value["timestamp"]:
            from ..protocol.models import utc_now

            value["timestamp"] = utc_now()
        return value


@dataclass(slots=True)
class AgentApproval:
    request_id: str
    session_id: str | None
    action: str
    reason: str
    scope: str = "once"
    status: Literal["pending", "allowed-once", "rejected", "cancelled", "unavailable"] = "pending"
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if not value["created_at"]:
            from ..protocol.models import utc_now

            value["created_at"] = utc_now()
        return value
