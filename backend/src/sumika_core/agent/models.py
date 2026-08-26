"""Stable, runtime-neutral Agent contracts used by the Sumika UI.

``extensions`` contains only the bridge's bounded presentation metadata. Raw
DSH arguments, results, prompts, and transient queue messages stay outside the
Sumika event log.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


DSH_VERSION = "0.1.1-rc.2"
DSH_COMMIT = "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
DSH_REPOSITORY = "https://github.com/deepseek-ai/deepseek-harness"
DSH_DEFAULT_ENDPOINT = "http://127.0.0.1:3080"

BROWSERSKILL_COMMIT = "a004291848e8641400b973b8d612b4c4b74cdc90"
BROWSERSKILL_EXTENSION_VERSION = "0.1.6"
BROWSERSKILL_DSH_PLUGIN_VERSION = "0.1.1"


@dataclass(slots=True)
class DSHRuntimeConfig:
    version: str = DSH_VERSION
    commit: str = DSH_COMMIT
    repository: str = DSH_REPOSITORY
    endpoint: str = DSH_DEFAULT_ENDPOINT
    profile_dir: str = ""
    executable: str | None = None
    managed: bool = True
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def default_profile_dir(data_dir: str | Path | None) -> str:
    if data_dir is None:
        return ""
    return str((Path(data_dir) / "dsh-profile").resolve())
