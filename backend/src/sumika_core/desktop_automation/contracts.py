"""Runtime-neutral contracts for controlled desktop software automation.

The desktop automation boundary is deliberately separate from BrowserSkill and
from the one-shot ``ToolRuntime``.  Adapters may speak an application protocol,
Electron CDP, Windows UI Automation, or (only after an explicit opt-in) the
foreground desktop.  The Core owns registration, permissions, leases,
idempotency, and redacted audit metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


DESKTOP_AUTOMATION_SCHEMA = "desktop-automation/v1"
DESKTOP_ACTION_SCHEMA = "desktop-action/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_TRANSPORTS = frozenset({"app-protocol", "electron-cdp", "windows-uia", "foreground"})
_APP_STATES = frozenset(
    {
        "unconfigured",
        "configured",
        "ready",
        "running",
        "unavailable",
        "disabled",
        "error",
        "revoked",
    }
)
_ACTION_STATUSES = frozenset(
    {
        "accepted",
        "running",
        "completed",
        "denied",
        "waiting-approval",
        "waiting-human",
        "failed",
        "cancelled",
        "unknown",
    }
)
_RISKS = frozenset({"read", "control", "send", "sensitive", "takeover"})


class DesktopAutomationError(RuntimeError):
    """A controlled failure safe to expose at the Core RPC boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "desktop-automation-error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DesktopRegistrationError(DesktopAutomationError):
    """The application is not registered or its declaration is invalid."""


class DesktopLeaseError(DesktopAutomationError):
    """A profile/window lease cannot be acquired or is owned elsewhere."""


class DesktopPermissionError(DesktopAutomationError):
    """An action needs an explicit approval or human takeover."""


def safe_identifier(value: Any, field: str = "identifier") -> str:
    candidate = str(value or "").strip()
    if not candidate or not _IDENTIFIER_RE.fullmatch(candidate):
        raise DesktopAutomationError(f"{field} is invalid", code="invalid-identifier")
    return candidate


def safe_text(value: Any, field: str, limit: int = 2000, *, allow_empty: bool = True) -> str:
    if value is None:
        if allow_empty:
            return ""
        raise DesktopAutomationError(f"{field} is required", code="invalid-{field}")
    if not isinstance(value, str):
        raise DesktopAutomationError(f"{field} must be text", code="invalid-{field}")
    candidate = value.strip()
    if len(candidate) > limit or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise DesktopAutomationError(f"{field} is invalid", code="invalid-{field}")
    if not candidate and not allow_empty:
        raise DesktopAutomationError(f"{field} is required", code="invalid-{field}")
    return candidate


def hash_value(value: Any) -> str:
    """Hash a canonical value without retaining its body in audit records."""

    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        encoded = repr(value)
    return hashlib.sha256(encoded.encode("utf-8", "replace")).hexdigest()


def action_risk(action: str) -> str:
    """Return the least permissive risk class for an action name."""

    normalized = str(action or "").strip().lower().replace("-", "_")
    if normalized in {"observe", "read", "snapshot", "inspect", "health", "list", "status"}:
        return "read"
    if normalized in {"send", "prompt", "type", "write", "submit"}:
        return "send"
    if normalized in {"login", "credential", "password", "otp", "captcha", "delete", "publish", "purchase", "upload", "download", "permission_change"}:
        return "sensitive"
    if normalized in {"takeover", "foreground", "foreground_takeover", "global_input"}:
        return "takeover"
    return "control"


def _safe_tuple(value: Any, *, limit: int = 32, item_limit: int = 120) -> tuple[str, ...]:
    if value is None:
        return ()
    values = [value] if isinstance(value, str) else value if isinstance(value, (list, tuple, set, frozenset)) else []
    result: list[str] = []
    for item in list(values)[:limit]:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or len(text) > item_limit or any(ord(char) < 32 or ord(char) == 127 for char in text):
            continue
        if text not in result:
            result.append(text)
    return tuple(result)


def _safe_metadata(value: Any, *, depth: int = 2) -> dict[str, Any]:
    """Keep public metadata bounded and reject credential/path-shaped fields."""

    if not isinstance(value, Mapping) or depth <= 0:
        return {}
    result: dict[str, Any] = {}
    blocked = {"token", "secret", "password", "cookie", "authorization", "api_key", "apikey", "credential", "path", "file", "directory", "executable"}
    for raw_key, raw_value in list(value.items())[:48]:
        key = str(raw_key).strip().lower()
        if not key or len(key) > 80 or any(part in key for part in blocked):
            continue
        if isinstance(raw_value, Mapping):
            result[key] = _safe_metadata(raw_value, depth=depth - 1)
        elif isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            if isinstance(raw_value, str) and (len(raw_value) > 300 or "\\" in raw_value or "/" in raw_value):
                continue
            result[key] = raw_value
        elif isinstance(raw_value, (list, tuple)):
            values: list[Any] = []
            for item in list(raw_value)[:16]:
                if isinstance(item, (str, int, float, bool)) or item is None:
                    if isinstance(item, str) and (len(item) > 160 or "\\" in item or "/" in item):
                        continue
                    values.append(item)
            result[key] = values
    return result


@dataclass(frozen=True, slots=True)
class DesktopApplication:
    """A user-approved application declaration.

    ``config`` is intentionally internal.  It may contain an executable path
    needed by an adapter, but it is never returned by ``to_public`` or written
    to the metadata persistence projection.
    """

    app_id: str
    name: str
    adapter_id: str
    transport: str = "app-protocol"
    status: str = "unconfigured"
    approved: bool = False
    managed: bool = False
    capabilities: tuple[str, ...] = ("observe", "read", "send", "control")
    permissions: tuple[str, ...] = ()
    profile_id: str | None = None
    fingerprint: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", safe_identifier(self.app_id, "app_id"))
        object.__setattr__(self, "name", safe_text(self.name, "name", 240, allow_empty=False))
        object.__setattr__(self, "adapter_id", safe_identifier(self.adapter_id, "adapter_id"))
        transport = safe_text(self.transport, "transport", 40, allow_empty=False).lower()
        if transport not in _TRANSPORTS:
            raise DesktopAutomationError("transport is unsupported", code="invalid-transport")
        object.__setattr__(self, "transport", transport)
        status = safe_text(self.status, "status", 40).lower() or "unconfigured"
        if status not in _APP_STATES:
            raise DesktopAutomationError("application status is invalid", code="invalid-status")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "approved", bool(self.approved))
        object.__setattr__(self, "managed", bool(self.managed))
        object.__setattr__(self, "capabilities", _safe_tuple(self.capabilities, item_limit=80) or ("observe", "read"))
        object.__setattr__(self, "permissions", _safe_tuple(self.permissions, item_limit=120))
        if self.profile_id not in (None, ""):
            object.__setattr__(self, "profile_id", safe_identifier(self.profile_id, "profile_id"))
        else:
            object.__setattr__(self, "profile_id", None)
        object.__setattr__(self, "fingerprint", _safe_metadata(self.fingerprint))
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))
        object.__setattr__(self, "config", dict(self.config) if isinstance(self.config, Mapping) else {})

    def to_public(
        self,
        *,
        session_count: int = 0,
        lease_state: str = "idle",
        lease_owner: str = "none",
    ) -> dict[str, Any]:
        # The owner is a bounded lifecycle projection, never a lease token or
        # any other credential-bearing value.
        owner = str(lease_owner or "none").strip().lower()
        if owner not in {"none", "agent", "manual", "system", "unknown"}:
            owner = "unknown"
        return {
            "schema": DESKTOP_AUTOMATION_SCHEMA,
            "app_id": self.app_id,
            "name": self.name,
            "adapter_id": self.adapter_id,
            "transport": self.transport,
            "status": self.status,
            "approved": self.approved,
            "managed": self.managed,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "profile_configured": bool(self.profile_id),
            "fingerprint": dict(self.fingerprint),
            "metadata": dict(self.metadata),
            "session_count": max(0, int(session_count)),
            "lease_state": lease_state,
            "lease_owner": owner,
            "configured": bool(self.config),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_record(self) -> dict[str, Any]:
        """Return the persistence-safe subset; paths and launcher config stay out."""

        return {
            "app_id": self.app_id,
            "name": self.name,
            "adapter_id": self.adapter_id,
            "transport": self.transport,
            "status": self.status,
            "approved": self.approved,
            "managed": self.managed,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "profile_id": self.profile_id,
            "profile_configured": bool(self.profile_id),
            "fingerprint": dict(self.fingerprint),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class DesktopSession:
    session_id: str
    app_id: str
    profile_id: str
    profile_key: str
    owner: str
    transport: str
    native_session_id: str | None = None
    state: str = "open"
    foreground_takeover: bool = False
    opened_at: str | None = None
    lease_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return {
            "schema": DESKTOP_AUTOMATION_SCHEMA,
            "session_id": self.session_id,
            "app_id": self.app_id,
            "profile_id": self.profile_id,
            "owner": self.owner,
            "transport": self.transport,
            "state": self.state,
            "foreground_takeover": self.foreground_takeover,
            "opened_at": self.opened_at,
            "lease_id": self.lease_id,
            "metadata": _safe_metadata(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class DesktopActionRequest:
    session_id: str
    action: str
    target: str | None = None
    value: Any = None
    args: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    approved: bool = False
    approval_id: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DesktopActionRequest":
        if not isinstance(value, Mapping):
            raise DesktopAutomationError("action must be an object", code="invalid-action")
        session_id = safe_identifier(value.get("session_id") or value.get("sessionId"), "session_id")
        action = safe_text(value.get("action"), "action", 80, allow_empty=False).lower().replace("-", "_")
        target_value = value.get("target")
        target = None if target_value in (None, "") else safe_text(target_value, "target", 600, allow_empty=False)
        args = value.get("args", value.get("arguments", {}))
        if not isinstance(args, Mapping):
            raise DesktopAutomationError("args must be an object", code="invalid-action")
        idempotency = value.get("idempotency_key") or value.get("idempotencyKey")
        if idempotency not in (None, ""):
            idempotency = safe_identifier(idempotency, "idempotency_key")
        approval_id = value.get("approval_id") or value.get("approvalId")
        if approval_id not in (None, ""):
            approval_id = safe_identifier(approval_id, "approval_id")
        action_value = value.get("value")
        if isinstance(action_value, str) and len(action_value) > 64 * 1024:
            raise DesktopAutomationError("action value is too large", code="action-too-large")
        return cls(
            session_id=session_id,
            action=action,
            target=target,
            value=action_value,
            args=dict(args),
            idempotency_key=idempotency,
            approved=value.get("approved") is True,
            approval_id=approval_id,
        )

    @property
    def risk(self) -> str:
        return action_risk(self.action)

    def hash_input(self) -> str:
        return hash_value(
            {
                "session_id": self.session_id,
                "action": self.action,
                "target": self.target,
                "value": self.value,
                "args": self.args,
            }
        )


@dataclass(frozen=True, slots=True)
class DesktopActionResult:
    session_id: str
    action: str
    status: str
    risk: str
    input_sha256: str
    output_sha256: str | None = None
    result: Any = None
    error_code: str | None = None
    reason: str | None = None
    approval_id: str | None = None
    idempotent_replay: bool = False
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.status not in _ACTION_STATUSES:
            raise DesktopAutomationError("action result status is invalid", code="invalid-action-status")
        if self.risk not in _RISKS:
            raise DesktopAutomationError("action result risk is invalid", code="invalid-action-risk")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema": DESKTOP_ACTION_SCHEMA,
            "session_id": self.session_id,
            "action": self.action,
            "status": self.status,
            "risk": self.risk,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "result": self.result,
            "error_code": self.error_code,
            "reason": self.reason,
            "approval_id": self.approval_id,
            "idempotent_replay": self.idempotent_replay,
            "retryable": self.retryable,
        }
        return value


class DesktopAdapter(ABC):
    """Adapter contract implemented by a concrete desktop integration."""

    adapter_id = "unknown"
    transport = "app-protocol"
    capabilities: frozenset[str] = frozenset({"observe", "read"})

    @abstractmethod
    def health(self, application: DesktopApplication) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def open(self, application: DesktopApplication, profile_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def observe(self, session: DesktopSession, options: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def act(self, session: DesktopSession, request: DesktopActionRequest) -> dict[str, Any]:
        raise NotImplementedError

    def close(self, session: DesktopSession) -> dict[str, Any]:
        del session
        return {"closed": True}

    def takeover(self, session: DesktopSession, *, enabled: bool) -> dict[str, Any]:
        del session, enabled
        raise DesktopAutomationError(
            f"adapter '{self.adapter_id}' does not support foreground takeover",
            code="foreground-takeover-unavailable",
        )

    def bind_handle(self, session_id: str, opened: Mapping[str, Any]) -> None:
        """Optionally retain an adapter-specific native handle after opening."""

        del session_id, opened

    def shutdown(self) -> None:
        return None


__all__ = [
    "DESKTOP_ACTION_SCHEMA",
    "DESKTOP_AUTOMATION_SCHEMA",
    "DesktopActionRequest",
    "DesktopActionResult",
    "DesktopAdapter",
    "DesktopApplication",
    "DesktopAutomationError",
    "DesktopLeaseError",
    "DesktopPermissionError",
    "DesktopRegistrationError",
    "DesktopSession",
    "action_risk",
    "hash_value",
    "safe_identifier",
    "safe_text",
]
