"""Runtime-neutral routing and web consultation contracts.

The harness remains the owner of an Agent session.  This module is a small
capability bridge used by Sumika when the Agent asks an independent web chat
profile for advice.  It deliberately does not know anything about DSH's
internal session objects: callers provide a parent session/turn id and receive
bounded, structured results.

Only the in-memory run object retains question/context/answer text.  When a
``Storage`` instance is supplied, the coordinator writes the metadata
projection through ``upsert_agent_route_run`` and
``upsert_agent_consultation``; those methods intentionally discard content.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4


AGENT_ROUTE_SCHEMA = "agent-route/v1"
AGENT_CONSULTATION_SCHEMA = "agent-consultation/v1"
ROUTE_EVIDENCE_SCHEMA = "route-evidence/v1"
UNTRUSTED_WEB_RESULT_LABEL = "UNTRUSTED_WEB_RESULT"

ROUTE_MODES = frozenset({"web-worker", "consultation-panel"})
DECISION_KINDS = frozenset(
    {"brainstorm", "plan-review", "fact-check", "counterexample", "small-answer"}
)
RUN_STATES = frozenset(
    {
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "cancelled",
        "waiting-human",
        "unknown",
        "interrupted",
    }
)
EVIDENCE_TYPES = frozenset(
    {
        "adapter-declaration",
        "protocol-probe",
        "smoke",
        "real-run",
        "usage",
        "official-pricing",
        "user-confirmation",
        "unknown",
    }
)
WORKSPACE_ACCESS = frozenset({"none", "read-only", "isolated-worktree"})
SIDE_EFFECTS = frozenset({"none", "read", "write", "external"})


class RouteError(RuntimeError):
    """A safe, user-actionable routing error."""


class RouteValidationError(RouteError):
    """Raised when a route request cannot be safely represented."""


_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,240}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"(?:sk|pk)-[A-Za-z0-9_-]{12,}"
    r"|bearer\s+[A-Za-z0-9._~+/=-]{12,}"
    r"|(?:api[_ -]?key|token|secret|password|passwd|cookie|authorization|otp)"
    r"\s*[:=]\s*[^\s,;]+"
    r")"
)
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization|bearer|cookie|credential|password|passwd|secret|token|otp|private[_ -]?key)"
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?:(?:[A-Za-z]:[\\/])|(?:\\\\[^\\/]+[\\/][^\\/]+)|(?:/(?:Users|home|root|mnt|private)/[^\s\"']+))"
)
_SENSITIVE_FILE_RE = re.compile(
    r"(?i)(?:^|[\\/])(?:\.env(?:\.[^\\/]*)?|credentials?\.json|cookies?\.json|token\.json|secrets?\.(?:json|toml|yaml|yml))$"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(value: Any, field: str, *, required: bool = True) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        if required:
            raise RouteValidationError(f"{field} is required")
        return None
    if len(candidate) > 240 or _ID_RE.fullmatch(candidate) is None:
        raise RouteValidationError(f"{field} is invalid")
    return candidate


def _bounded_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise RouteValidationError(f"{field} must be text")
    candidate = value.strip()
    if not candidate or len(candidate) > limit:
        raise RouteValidationError(f"{field} must contain 1-{limit} characters")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in candidate):
        raise RouteValidationError(f"{field} contains control characters")
    return candidate


def _optional_text(value: Any, field: str, limit: int) -> str | None:
    if value in (None, ""):
        return None
    return _bounded_text(value, field, limit)


def _token(value: Any, field: str, *, default: str = "unknown") -> str:
    candidate = str(value or default).strip()
    if not candidate or len(candidate) > 120 or _TOKEN_RE.fullmatch(candidate) is None:
        raise RouteValidationError(f"{field} is invalid")
    return candidate


def _call_web_method_once(method: Callable[..., Any], profile_id: str, text: str, *, owner: str) -> Any:
    """Invoke one web adapter method at most once.

    Older adapters do not accept the keyword-only ``owner`` argument while
    current adapters do.  Inspect and bind the signature *before* invoking so
    an implementation ``TypeError`` is never mistaken for a signature
    mismatch and followed by a duplicate browser send.
    """

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        # An opaque callable gets the smallest legacy-compatible invocation.
        # If it actually requires ``owner`` it fails closed; it is never
        # retried after the call begins.
        return method(profile_id, text)

    parameters = signature.parameters
    owner_parameter = parameters.get("owner")
    accepts_owner = bool(
        owner_parameter
        and owner_parameter.kind != inspect.Parameter.POSITIONAL_ONLY
    ) or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if accepts_owner:
        try:
            signature.bind(profile_id, text, owner=owner)
        except TypeError:
            pass
        else:
            return method(profile_id, text, owner=owner)

    try:
        signature.bind(profile_id, text)
    except TypeError as error:
        # This is a pre-invocation contract error, so no request could have
        # been sent and there is still no safe alternate invocation.
        raise TypeError("web adapter method signature is unsupported") from error
    return method(profile_id, text)


def _safe_secret_replacement(match: re.Match[str]) -> str:
    raw = match.group(0)
    # Keep the key name (useful to a reviewer) but never retain its value.
    if ":" in raw:
        key = raw.split(":", 1)[0]
    elif "=" in raw:
        key = raw.split("=", 1)[0]
    else:
        key = "secret"
    return f"{key.strip()}=<REDACTED>"


def sanitize_text(value: Any, *, limit: int = 24_000) -> str:
    """Return bounded text safe for an external web model.

    Secrets are replaced with stable markers, while personal absolute paths
    are normalized.  This is intentionally conservative; callers should still
    avoid passing credential files and raw browser snapshots.
    """

    if not isinstance(value, str):
        value = str(value or "")
    if len(value) > limit:
        raise RouteValidationError("context-too-large")
    value = _SECRET_RE.sub(_safe_secret_replacement, value)
    value = _ABSOLUTE_PATH_RE.sub("<LOCAL_PATH>", value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    return bool(_SECRET_KEY_RE.search(str(key or "")))


def sanitize_context(value: Any, *, depth: int = 0, budget: int = 28_000) -> Any:
    """Sanitize a small structured context reference without executing it."""

    if depth > 6:
        raise RouteValidationError("context-too-deep")
    if isinstance(value, str):
        return sanitize_text(value, limit=min(24_000, budget))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        remaining = budget
        for raw_key, raw_item in list(value.items())[:64]:
            key = sanitize_text(str(raw_key), limit=120)
            if _is_sensitive_key(key):
                # Do not transmit credential-bearing values at all.  A stable
                # marker lets the parent Agent know why context was omitted.
                result[key] = "<REDACTED>"
                continue
            if key.casefold() in {"path", "file", "filename", "workspace_path"}:
                candidate = str(raw_item or "")
                if _SENSITIVE_FILE_RE.search(candidate):
                    raise RouteValidationError("sensitive-context")
            item = sanitize_context(raw_item, depth=depth + 1, budget=max(256, remaining))
            result[key] = item
            remaining -= len(json.dumps(item, ensure_ascii=False, default=str))
            if remaining <= 0:
                raise RouteValidationError("context-too-large")
        return result
    if isinstance(value, (list, tuple)):
        result = []
        remaining = budget
        for item in list(value)[:64]:
            safe = sanitize_context(item, depth=depth + 1, budget=max(256, remaining))
            result.append(safe)
            remaining -= len(json.dumps(safe, ensure_ascii=False, default=str))
            if remaining <= 0:
                raise RouteValidationError("context-too-large")
        return result
    raise RouteValidationError("context contains unsupported values")


def _summary(answer: str, *, limit: int = 600) -> str:
    compact = " ".join(str(answer or "").split())
    return compact[:limit]


def _confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number < 0 or number > 1:
        return None
    return round(number, 3)


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    """Traceable evidence used to describe a route.

    Evidence is advisory metadata: the supervisor still applies hard safety
    and capability gates.  Expired observations are exposed as ``unknown``
    instead of silently being treated as current.
    """

    evidence_id: str
    evidence_type: str
    source: str
    version: str = ""
    observed_at: str = field(default_factory=_now)
    expires_at: str | None = None
    confidence: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _id(self.evidence_id, "evidence_id") or "")
        kind = _token(self.evidence_type, "evidence_type", default="unknown").lower()
        if kind not in EVIDENCE_TYPES:
            raise RouteValidationError("evidence_type is invalid")
        object.__setattr__(self, "evidence_type", kind)
        object.__setattr__(self, "source", _bounded_text(self.source, "source", 400))
        object.__setattr__(self, "version", sanitize_text(str(self.version or ""), limit=120))
        object.__setattr__(self, "observed_at", _bounded_text(str(self.observed_at or _now()), "observed_at", 80))
        object.__setattr__(self, "expires_at", _bounded_text(str(self.expires_at), "expires_at", 80) if self.expires_at else None)
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        safe_details = sanitize_context(self.details, budget=4_000) if isinstance(self.details, Mapping) else {}
        object.__setattr__(self, "details", safe_details)

    @property
    def fresh(self) -> bool:
        if not self.expires_at:
            return True
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry > datetime.now(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_EVIDENCE_SCHEMA,
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "source": self.source,
            "version": self.version,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "confidence": self.confidence,
            "details": self.details,
            "fresh": self.fresh,
            "effective_type": self.evidence_type if self.fresh else "unknown",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RouteEvidence":
        if not isinstance(value, Mapping):
            raise RouteValidationError("route evidence must be an object")
        return cls(
            evidence_id=str(value.get("evidence_id") or value.get("evidenceId") or f"evidence-{uuid4().hex[:16]}"),
            evidence_type=str(value.get("evidence_type") or value.get("type") or value.get("kind") or "unknown"),
            source=str(value.get("source") or "unknown"),
            version=str(value.get("version") or ""),
            observed_at=str(value.get("observed_at") or value.get("observedAt") or _now()),
            expires_at=value.get("expires_at") or value.get("expiresAt"),
            confidence=value.get("confidence"),
            details=value.get("details") if isinstance(value.get("details"), Mapping) else {},
        )


@dataclass(frozen=True, slots=True)
class RouteDescriptor:
    route_id: str
    kind: str
    label: str
    provider_profile_id: str | None = None
    provider_key: str = "unknown"
    adapter_id: str | None = None
    domains: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("text",)
    status: str = "unavailable"
    routable: bool = False
    occupancy: str = "idle"
    quota_state: str = "unknown"
    requires_confirmation: bool = False
    reason: str | None = None
    source: str = "web-chat"
    runtime_id: str = "unknown"
    executor: str = "web"
    transport: str = "unknown"
    side_effect: str = "none"
    quota_consent: str = "unknown"
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _id(self.route_id, "route_id") or "")
        object.__setattr__(self, "kind", _token(self.kind, "kind"))
        object.__setattr__(self, "label", _bounded_text(self.label, "label", 200))
        if self.provider_profile_id:
            object.__setattr__(self, "provider_profile_id", _id(self.provider_profile_id, "provider_profile_id", required=False))
        object.__setattr__(self, "provider_key", _token(self.provider_key, "provider_key"))
        object.__setattr__(self, "adapter_id", _token(self.adapter_id, "adapter_id", default="unknown") if self.adapter_id else None)
        object.__setattr__(self, "domains", tuple(str(item)[:200] for item in self.domains[:8]))
        object.__setattr__(self, "capabilities", tuple(_token(item, "capability") for item in self.capabilities[:16]))
        if self.status not in RUN_STATES and self.status not in {"ready", "available", "configured", "needs-auth", "unavailable", "archived"}:
            raise RouteValidationError("route status is invalid")
        if self.occupancy not in {"idle", "agent", "manual", "waiting"}:
            raise RouteValidationError("route occupancy is invalid")
        object.__setattr__(self, "runtime_id", _token(self.runtime_id, "runtime_id", default="unknown"))
        object.__setattr__(self, "executor", _token(self.executor, "executor", default="web"))
        object.__setattr__(self, "transport", _token(self.transport, "transport", default="unknown"))
        side_effect = str(self.side_effect or "none").strip().lower()
        if side_effect not in SIDE_EFFECTS:
            raise RouteValidationError("route side_effect is invalid")
        object.__setattr__(self, "side_effect", side_effect)
        object.__setattr__(self, "quota_consent", _token(self.quota_consent, "quota_consent", default="unknown"))
        refs = []
        for ref in self.evidence_refs[:16]:
            refs.append(_id(ref, "evidence_ref") or "")
        object.__setattr__(self, "evidence_refs", tuple(ref for ref in refs if ref))

    @property
    def available(self) -> bool:
        return bool(self.routable and self.status in {"ready", "available"} and self.occupancy in {"idle", "agent"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_ROUTE_SCHEMA,
            "route_id": self.route_id,
            "kind": self.kind,
            "label": self.label,
            "provider_profile_id": self.provider_profile_id,
            "provider_key": self.provider_key,
            "adapter_id": self.adapter_id,
            "domains": list(self.domains),
            "capabilities": list(self.capabilities),
            "status": self.status,
            "routable": self.routable,
            "occupancy": self.occupancy,
            "quota_state": self.quota_state,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
            "source": self.source,
            "runtime_id": self.runtime_id,
            "executor": self.executor,
            "transport": self.transport,
            "side_effect": self.side_effect,
            "quota_consent": self.quota_consent,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class ConsultationRequest:
    consultation_id: str
    parent_session_id: str
    question: str
    decision_kind: str
    parent_turn_id: str | None = None
    required_capabilities: tuple[str, ...] = ("text",)
    context_refs: Any = field(default_factory=dict)
    max_members: int = 3
    route_constraints: dict[str, Any] = field(default_factory=dict)
    continuation_of: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "consultation_id", _id(self.consultation_id, "consultation_id") or "")
        object.__setattr__(self, "parent_session_id", _id(self.parent_session_id, "parent_session_id") or "")
        object.__setattr__(self, "parent_turn_id", _id(self.parent_turn_id, "parent_turn_id", required=False))
        object.__setattr__(self, "question", sanitize_text(_bounded_text(self.question, "question", 16_000), limit=16_000))
        kind = str(self.decision_kind or "").strip().lower()
        if kind not in DECISION_KINDS:
            raise RouteValidationError("decision_kind is invalid")
        object.__setattr__(self, "decision_kind", kind)
        capabilities = tuple(_token(item, "required_capability") for item in self.required_capabilities[:16])
        object.__setattr__(self, "required_capabilities", capabilities or ("text",))
        object.__setattr__(self, "context_refs", sanitize_context(self.context_refs))
        if isinstance(self.max_members, bool) or not isinstance(self.max_members, int) or not 1 <= self.max_members <= 3:
            raise RouteValidationError("max_members must be between 1 and 3")
        object.__setattr__(self, "route_constraints", sanitize_context(self.route_constraints) if isinstance(self.route_constraints, Mapping) else {})
        object.__setattr__(self, "continuation_of", _id(self.continuation_of, "continuation_of", required=False))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConsultationRequest":
        if not isinstance(value, Mapping):
            raise RouteValidationError("consultation request must be an object")
        consultation_id = value.get("consultation_id") or value.get("consultationId") or f"consultation-{uuid4().hex[:16]}"
        return cls(
            consultation_id=str(consultation_id),
            parent_session_id=str(value.get("parent_session_id") or value.get("parentSessionId") or ""),
            parent_turn_id=value.get("parent_turn_id") or value.get("parentTurnId"),
            question=value.get("question", ""),
            decision_kind=value.get("decision_kind") or value.get("decisionKind") or "small-answer",
            required_capabilities=tuple(value.get("required_capabilities") or value.get("requiredCapabilities") or ("text",)),
            context_refs=value.get("context_refs") or value.get("contextRefs") or {},
            max_members=int(value.get("max_members") or value.get("maxMembers") or 3),
            route_constraints=value.get("route_constraints") or value.get("routeConstraints") or {},
            continuation_of=value.get("continuation_of") or value.get("continuationOf"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_CONSULTATION_SCHEMA,
            "consultation_id": self.consultation_id,
            "parent_session_id": self.parent_session_id,
            "parent_turn_id": self.parent_turn_id,
            "question": self.question,
            "decision_kind": self.decision_kind,
            "required_capabilities": list(self.required_capabilities),
            "context_refs": self.context_refs,
            "max_members": self.max_members,
            "route_constraints": self.route_constraints,
            "continuation_of": self.continuation_of,
        }


@dataclass(frozen=True, slots=True)
class SubtaskDispatch:
    dispatch_id: str
    parent_session_id: str
    route_id: str
    question: str
    mode: str = "web-worker"
    parent_turn_id: str | None = None
    context_refs: Any = field(default_factory=dict)
    continuation_of: str | None = None
    role: str = "independent reviewer"
    consultation_id: str | None = None
    deadline_at: str | None = None
    workspace_access: str = "none"
    required_capabilities: tuple[str, ...] = ("text",)
    depth: int = 0
    runtime_id: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _id(self.dispatch_id, "dispatch_id") or "")
        object.__setattr__(self, "parent_session_id", _id(self.parent_session_id, "parent_session_id") or "")
        object.__setattr__(self, "route_id", _id(self.route_id, "route_id") or "")
        object.__setattr__(self, "question", sanitize_text(_bounded_text(self.question, "question", 16_000), limit=16_000))
        if self.mode not in ROUTE_MODES:
            raise RouteValidationError("mode is invalid")
        object.__setattr__(self, "parent_turn_id", _id(self.parent_turn_id, "parent_turn_id", required=False))
        object.__setattr__(self, "context_refs", sanitize_context(self.context_refs))
        object.__setattr__(self, "continuation_of", _id(self.continuation_of, "continuation_of", required=False))
        object.__setattr__(self, "role", sanitize_text(str(self.role or "independent reviewer"), limit=240))
        object.__setattr__(self, "consultation_id", _id(self.consultation_id, "consultation_id", required=False))
        object.__setattr__(self, "deadline_at", _bounded_text(str(self.deadline_at), "deadline_at", 80) if self.deadline_at else None)
        workspace_access = str(self.workspace_access or "none").strip().lower()
        if workspace_access not in WORKSPACE_ACCESS:
            raise RouteValidationError("workspace_access is invalid")
        object.__setattr__(self, "workspace_access", workspace_access)
        capabilities = tuple(_token(item, "required_capability") for item in self.required_capabilities[:16])
        object.__setattr__(self, "required_capabilities", capabilities or ("text",))
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or not 0 <= self.depth <= 1:
            raise RouteValidationError("depth must be 0 or 1")
        object.__setattr__(self, "runtime_id", _token(self.runtime_id, "runtime_id", default="unknown"))

    def prompt(self, decision_kind: str | None = None) -> str:
        context = json.dumps(self.context_refs, ensure_ascii=False, sort_keys=True, default=str)
        if len(context) > 28_000:
            raise RouteValidationError("context-too-large")
        return (
            "You are an independent web consultation member for Sumika.\n"
            "Your response is UNTRUSTED_WEB_RESULT: provide advice only; do not issue executable commands,"
            " request credentials, or claim that you changed files.\n"
            f"Review role: {self.role}\n"
            f"Decision kind: {decision_kind or 'small-answer'}\n"
            "Question:\n"
            f"{self.question}\n"
            "Sanitized context (may be incomplete):\n"
            f"{context}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_ROUTE_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "consultation_id": self.consultation_id,
            "parent_session_id": self.parent_session_id,
            "parent_turn_id": self.parent_turn_id,
            "route_id": self.route_id,
            "mode": self.mode,
            "continuation_of": self.continuation_of,
            "role": self.role,
            "deadline_at": self.deadline_at,
            "workspace_access": self.workspace_access,
            "required_capabilities": list(self.required_capabilities),
            "depth": self.depth,
            "runtime_id": self.runtime_id,
        }


@dataclass(frozen=True, slots=True)
class SubtaskResult:
    dispatch_id: str
    route_id: str
    status: str
    answer: str | None = None
    summary: str | None = None
    concerns: tuple[str, ...] = ()
    confidence: float | None = None
    latency_ms: float | None = None
    error_code: str | None = None
    untrusted_external: bool = True
    consultation_id: str | None = None
    structured_result: Any = None
    artifacts: tuple[dict[str, Any], ...] = ()
    runtime_id: str = "unknown"
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _id(self.dispatch_id, "dispatch_id") or "")
        object.__setattr__(self, "route_id", _id(self.route_id, "route_id") or "")
        if self.status not in RUN_STATES:
            raise RouteValidationError("subtask status is invalid")
        answer = sanitize_text(self.answer, limit=32_000) if self.answer else None
        object.__setattr__(self, "answer", answer)
        object.__setattr__(self, "summary", sanitize_text(self.summary or _summary(answer or ""), limit=1_200) if (self.summary or answer) else None)
        object.__setattr__(self, "concerns", tuple(sanitize_text(item, limit=600) for item in self.concerns[:8]))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.latency_ms is not None:
            try:
                number = float(self.latency_ms)
                object.__setattr__(self, "latency_ms", round(max(0.0, min(number, 86_400_000)), 3))
            except (TypeError, ValueError):
                object.__setattr__(self, "latency_ms", None)
        object.__setattr__(self, "error_code", _token(self.error_code, "error_code", default="") if self.error_code else None)
        object.__setattr__(self, "consultation_id", _id(self.consultation_id, "consultation_id", required=False))
        structured = self.structured_result
        if structured is not None and not isinstance(structured, (Mapping, list, tuple, str, int, float, bool)):
            raise RouteValidationError("structured_result contains unsupported values")
        if isinstance(structured, tuple):
            structured = list(structured)
        if isinstance(structured, Mapping):
            structured = sanitize_context(structured, budget=8_000)
        elif isinstance(structured, list):
            structured = sanitize_context(structured, budget=8_000)
        elif isinstance(structured, str):
            structured = sanitize_text(structured, limit=8_000)
        object.__setattr__(self, "structured_result", structured)
        safe_artifacts: list[dict[str, Any]] = []
        for item in self.artifacts[:16]:
            if not isinstance(item, Mapping):
                continue
            safe_artifacts.append(sanitize_context(dict(item), budget=2_000))
        object.__setattr__(self, "artifacts", tuple(safe_artifacts))
        object.__setattr__(self, "runtime_id", _token(self.runtime_id, "runtime_id", default="unknown"))
        object.__setattr__(self, "retryable", bool(self.retryable))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_ROUTE_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "consultation_id": self.consultation_id,
            "route_id": self.route_id,
            "status": self.status,
            "answer": self.answer,
            "summary": self.summary,
            "concerns": list(self.concerns),
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "untrusted_external": True,
            "trust_label": UNTRUSTED_WEB_RESULT_LABEL,
            "structured_result": self.structured_result,
            "artifacts": list(self.artifacts),
            "runtime_id": self.runtime_id,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class ConsultationMemberResult(SubtaskResult):
    provider_profile_id: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "provider_profile_id", _id(self.provider_profile_id, "provider_profile_id", required=False))

    def to_dict(self) -> dict[str, Any]:
        value = super().to_dict()
        value["provider_profile_id"] = self.provider_profile_id
        return value


@dataclass(frozen=True, slots=True)
class ConsultationResult:
    consultation_id: str
    status: str
    members: tuple[ConsultationMemberResult, ...] = ()
    successful_count: int = 0
    failed_count: int = 0
    disagreement_detected: bool = False
    untrusted_external: bool = True
    decision_kind: str | None = None
    parent_session_id: str | None = None
    opinion_mode: str = "panel"

    def __post_init__(self) -> None:
        object.__setattr__(self, "consultation_id", _id(self.consultation_id, "consultation_id") or "")
        if self.status not in RUN_STATES:
            raise RouteValidationError("consultation status is invalid")
        object.__setattr__(self, "members", tuple(self.members[:3]))
        object.__setattr__(self, "successful_count", max(0, int(self.successful_count)))
        object.__setattr__(self, "failed_count", max(0, int(self.failed_count)))
        object.__setattr__(self, "decision_kind", _token(self.decision_kind, "decision_kind", default="") if self.decision_kind else None)
        object.__setattr__(self, "parent_session_id", _id(self.parent_session_id, "parent_session_id", required=False))
        mode = str(self.opinion_mode or "panel").strip().lower()
        if mode not in {"panel", "single-opinion"}:
            mode = "panel"
        object.__setattr__(self, "opinion_mode", mode)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_CONSULTATION_SCHEMA,
            "consultation_id": self.consultation_id,
            "parent_session_id": self.parent_session_id,
            "decision_kind": self.decision_kind,
            "status": self.status,
            "members": [member.to_dict() for member in self.members],
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "disagreement_detected": self.disagreement_detected,
            "untrusted_external": True,
            "trust_label": UNTRUSTED_WEB_RESULT_LABEL,
            "opinion_mode": self.opinion_mode,
            "single_opinion": self.opinion_mode == "single-opinion",
        }


def _hash_summary(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:32]


class RouteCoordinator:
    """Coordinate isolated web workers without becoming a second Agent loop."""

    def __init__(self, web_chat: Any, storage: Any = None, *, logger: Any = None, event_sink: Callable[[dict[str, Any]], None] | None = None, max_workers: int = 4) -> None:
        self.web_chat = web_chat
        self.storage = storage
        self.logger = logger
        self.event_sink = event_sink
        self._executor = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 8)), thread_name_prefix="sumika-route")
        self._lock = threading.RLock()
        self._profile_locks: dict[str, threading.Lock] = {}
        self._occupancy: dict[str, str] = {}
        self._runs: dict[str, dict[str, Any]] = {}
        self._dispatches: dict[str, SubtaskDispatch] = {}
        self._consultations: dict[str, dict[str, Any]] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._closed = False
        self._recover_stale_metadata()

    def _recover_stale_metadata(self) -> None:
        if not self.storage:
            return
        try:
            for row in self.storage.list_agent_route_runs(limit=500):
                if row.get("status") in {"queued", "running"}:
                    self.storage.upsert_agent_route_run({**row, "status": "interrupted", "error_code": "core-restarted"})
            for row in self.storage.list_agent_consultations(limit=500):
                if row.get("status") in {"queued", "running"}:
                    members = row.get("member_metadata") or []
                    self.storage.upsert_agent_consultation({**row, "status": "interrupted", "member_metadata": members})
        except Exception as error:  # diagnostics must never prevent startup
            self._log("warning", "route metadata recovery skipped", error)

    def _log(self, level: str, message: str, error: Exception | None = None) -> None:
        if self.logger:
            try:
                getattr(self.logger, level)("%s error_type=%s", message, type(error).__name__ if error else "none")
            except Exception:
                pass

    def _emit(self, event_type: str, **payload: Any) -> None:
        event = {"event_type": event_type, **{key: value for key, value in payload.items() if value is not None}}
        if self.event_sink:
            try:
                self.event_sink(event)
            except Exception as error:
                self._log("warning", "route event sink failed", error)

    def _profile_lock(self, profile_id: str) -> threading.Lock:
        with self._lock:
            return self._profile_locks.setdefault(profile_id, threading.Lock())

    def set_occupancy(self, profile_id: str, owner: str = "manual") -> dict[str, Any]:
        profile_id = _id(profile_id, "profile_id") or ""
        owner = owner if owner in {"manual", "agent", "waiting", "idle"} else "manual"
        with self._lock:
            if owner == "idle":
                self._occupancy.pop(profile_id, None)
            else:
                self._occupancy[profile_id] = owner
        self._emit("agent.route.occupancy", profile_id=profile_id, occupancy=owner)
        return {"profile_id": profile_id, "occupancy": owner}

    def request_takeover(self, profile_id: str) -> dict[str, Any]:
        profile_id = _id(profile_id, "profile_id") or ""
        cancelled: list[str] = []
        with self._lock:
            for dispatch_id, run in self._runs.items():
                if run.get("provider_profile_id") == profile_id and run.get("status") in {"queued", "running"}:
                    cancelled.append(dispatch_id)
        for dispatch_id in cancelled:
            self.cancel(dispatch_id)
        self.set_occupancy(profile_id, "manual")
        return {"profile_id": profile_id, "requested": True, "cancelled_dispatches": cancelled}

    def catalog(self, *, include_templates: bool = True) -> dict[str, Any]:
        descriptors: list[RouteDescriptor] = []
        profiles: list[dict[str, Any]] = []
        try:
            profiles = self.web_chat.list_profiles(include_archived=False)
        except Exception as error:
            self._log("warning", "web route catalog profile read failed", error)
        seen_adapters: set[str] = set()
        for profile in profiles:
            profile_id = str(profile.get("id") or "").strip()
            if not profile_id:
                continue
            adapter_id = str(profile.get("adapter_id") or "unknown").strip() or "unknown"
            seen_adapters.add(adapter_id)
            with self._lock:
                occupancy = self._occupancy.get(profile_id, "idle")
            # A lease owned by another Core/Workbench is an explicit human
            # handoff boundary.  Never turn it into a generic route failure.
            if occupancy == "idle" and str(profile.get("browser_profile_lease_owner") or "none") == "other-core":
                occupancy = "waiting"
            ready = bool(
                profile.get("status") == "ready"
                and profile.get("auth_state") == "authorized"
                and profile.get("auto_chat_enabled")
                and "chat.send" in set(profile.get("allowed_actions") or [])
            )
            status = "ready" if ready else str(profile.get("status") or "unavailable")
            descriptor = RouteDescriptor(
                route_id=f"web-chat:{profile_id}",
                kind="web-worker",
                label=str(profile.get("name") or adapter_id),
                provider_profile_id=profile_id,
                provider_key=adapter_id,
                adapter_id=adapter_id,
                domains=tuple((profile.get("config") or {}).get("domains") or ([profile.get("site_key")] if profile.get("site_key") else [])),
                status=status,
                routable=ready and occupancy not in {"manual", "waiting"},
                occupancy=occupancy,
                quota_state="unknown",
                requires_confirmation=False,
                reason=None if ready else "profile-not-ready",
            )
            descriptors.append(descriptor)
        if include_templates:
            try:
                adapters = self.web_chat.list_adapters()
            except Exception:
                adapters = []
            for adapter in adapters:
                adapter_id = str(adapter.get("id") or "").strip()
                if not adapter_id or adapter_id in seen_adapters:
                    continue
                descriptors.append(
                    RouteDescriptor(
                        route_id=f"web-template:{adapter_id}",
                        kind="web-worker",
                        label=str(adapter.get("name") or adapter_id),
                        provider_key=adapter_id,
                        adapter_id=adapter_id,
                        domains=tuple(str(item) for item in (adapter.get("domains") or [])[:8]),
                        status="unavailable",
                        routable=False,
                        reason="profile-not-configured",
                    )
                )
        return {
            "schema": AGENT_ROUTE_SCHEMA,
            "routes": [item.to_dict() for item in descriptors],
            "count": len(descriptors),
            "routable_count": sum(1 for item in descriptors if item.routable),
            "quota_state": "unknown",
        }

    def _continuation_route_refs(self, continuation_of: str) -> tuple[set[str], set[str]] | None:
        """Resolve prior web members without reading any message content."""

        identifier = _id(continuation_of, "continuation_of") or ""
        member_rows: list[Any] = []
        with self._lock:
            consultation = self._consultations.get(identifier)
            if consultation is not None:
                member_rows = list(consultation.get("member_metadata") or ())
            else:
                run = self._runs.get(identifier)
                if run is not None:
                    member_rows = [run]
        if not member_rows and self.storage:
            try:
                row = self.storage.get_agent_consultation(identifier)
            except Exception:
                row = None
            if isinstance(row, Mapping):
                member_rows = list(row.get("member_metadata") or ())
            if not member_rows:
                try:
                    row = self.storage.get_agent_route_run(identifier)
                except Exception:
                    row = None
                if isinstance(row, Mapping):
                    member_rows = [row]
        route_ids: set[str] = set()
        profile_ids: set[str] = set()
        for item in member_rows[:8]:
            if not isinstance(item, Mapping):
                continue
            try:
                route_id = _id(item.get("route_id") or item.get("routeId"), "route_id", required=False)
                profile_id = _id(
                    item.get("provider_profile_id") or item.get("providerProfileId"),
                    "provider_profile_id",
                    required=False,
                )
            except RouteValidationError:
                continue
            if route_id:
                route_ids.add(route_id)
            if profile_id:
                profile_ids.add(profile_id)
        if not route_ids and not profile_ids:
            return None
        return route_ids, profile_ids

    def _routes_for_request(self, request: ConsultationRequest) -> list[RouteDescriptor]:
        raw = self.catalog(include_templates=False).get("routes", [])
        routes = [
            RouteDescriptor(
                **{
                    key: value
                    for key, value in {
                        **item,
                        "domains": tuple(item.get("domains") or []),
                        "capabilities": tuple(item.get("capabilities") or ["text"]),
                    }.items()
                    if key != "schema"
                }
            )
            for item in raw
            if item.get("routable")
        ]
        constraints = request.route_constraints
        allowed = constraints.get("route_ids") or constraints.get("routeIds") if isinstance(constraints, Mapping) else None
        if isinstance(allowed, list) and allowed:
            routes = [route for route in routes if route.route_id in {str(item) for item in allowed}]
        required = set(request.required_capabilities)
        routes = [route for route in routes if required.issubset(set(route.capabilities))]
        continuation_refs = (
            self._continuation_route_refs(request.continuation_of)
            if request.continuation_of
            else None
        )
        if request.continuation_of and continuation_refs is None:
            return []
        continuation_route_ids, continuation_profiles = continuation_refs or (set(), set())
        if request.continuation_of:
            routes = [
                route
                for route in routes
                if route.route_id in continuation_route_ids
                or (
                    route.provider_profile_id is not None
                    and route.provider_profile_id in continuation_profiles
                )
            ]
        # One panel slot per provider/site adapter.  Preserve profile order,
        # which is already last-used order in Storage.
        selected: list[RouteDescriptor] = []
        providers: set[str] = set()
        for route in routes:
            if route.provider_key in providers:
                continue
            providers.add(route.provider_key)
            selected.append(route)
            if len(selected) >= request.max_members:
                break
        return selected

    def _persist_run(self, run: Mapping[str, Any]) -> None:
        if not self.storage:
            return
        try:
            self.storage.upsert_agent_route_run(dict(run))
        except Exception as error:
            self._log("warning", "route metadata write failed", error)

    def _persist_consultation(self, consultation: Mapping[str, Any]) -> None:
        if not self.storage:
            return
        try:
            self.storage.upsert_agent_consultation(dict(consultation))
        except Exception as error:
            self._log("warning", "consultation metadata write failed", error)

    def _run_public(self, run: Mapping[str, Any]) -> dict[str, Any]:
        value = {key: run.get(key) for key in ("dispatch_id", "consultation_id", "parent_session_id", "parent_turn_id", "mode", "route_id", "provider_profile_id", "continuation_of", "status", "started_at", "completed_at", "latency_ms", "error_code", "retryable")}
        result = run.get("result")
        if isinstance(result, SubtaskResult):
            value["result"] = result.to_dict()
        elif isinstance(result, Mapping):
            value["result"] = dict(result)
        return value

    def _execute_dispatch(self, dispatch: SubtaskDispatch, descriptor: RouteDescriptor, cancel_event: threading.Event, decision_kind: str = "small-answer") -> SubtaskResult:
        started = time.monotonic()
        profile_id = descriptor.provider_profile_id
        if not profile_id:
            return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "failed", error_code="profile-not-configured", consultation_id=dispatch.consultation_id)
        lock = self._profile_lock(profile_id)
        if not lock.acquire(blocking=False):
            return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "waiting-human", error_code="profile-occupied", consultation_id=dispatch.consultation_id)
        with self._lock:
            occupancy = self._occupancy.get(profile_id, "idle")
            if occupancy == "manual":
                lock.release()
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "waiting-human", error_code="profile-occupied", consultation_id=dispatch.consultation_id)
            self._occupancy[profile_id] = "agent"
        set_agent_occupancy = getattr(self.web_chat, "set_agent_occupancy", None)
        if callable(set_agent_occupancy):
            set_agent_occupancy(profile_id, True)
        try:
            if cancel_event.is_set():
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "cancelled", error_code="cancelled", consultation_id=dispatch.consultation_id)
            try:
                prompt = dispatch.prompt(decision_kind)
                starter = getattr(self.web_chat, "start_message", None)
                waiter = getattr(self.web_chat, "wait_message", None)
                if callable(starter) and callable(waiter):
                    # One browser send creates one durable-in-process attempt.
                    # A short wait is only a polling window; it must never turn
                    # into a second fill/click/press action.
                    response = _call_web_method_once(starter, profile_id, prompt, owner="agent")
                    attempt_id = str(response.get("attempt_id") or "").strip() if isinstance(response, Mapping) else ""
                    if isinstance(response, Mapping) and response.get("accepted") and attempt_id:
                        deadline = time.monotonic() + 300.0
                        while True:
                            if cancel_event.is_set():
                                cancel = getattr(self.web_chat, "cancel_message", None)
                                if callable(cancel):
                                    try:
                                        cancel(attempt_id)
                                    except Exception:
                                        pass
                                response = {
                                    "ok": False,
                                    "status": "cancelled",
                                    "possibly_sent": True,
                                    "error_code": "cancelled",
                                    "reason": "网页消息已取消；不会重发",
                                }
                                break
                            remaining = max(0.0, deadline - time.monotonic())
                            if remaining <= 0:
                                response = {
                                    "ok": False,
                                    "status": "possibly-sent",
                                    "pending": True,
                                    "possibly_sent": True,
                                    "error_code": "response-timeout",
                                    "reason": "网页消息已发送但在有界观察窗口内未确认回复",
                                }
                                break
                            # ``wait_message`` is a read-only poll, but use
                            # signature binding for old adapters as well.
                            try:
                                wait_signature = inspect.signature(waiter)
                            except (TypeError, ValueError):
                                response = waiter(attempt_id)
                            else:
                                try:
                                    wait_signature.bind(attempt_id, timeout=min(2.0, remaining))
                                except TypeError:
                                    try:
                                        wait_signature.bind(attempt_id)
                                    except TypeError as error:
                                        raise TypeError("web adapter wait signature is unsupported") from error
                                    response = waiter(attempt_id)
                                else:
                                    response = waiter(attempt_id, timeout=min(2.0, remaining))
                            status = str(response.get("status") or "unknown") if isinstance(response, Mapping) else "unknown"
                            if status not in {"accepted", "running"}:
                                break
                    # Rejected starts are already bounded by the web runtime;
                    # do not invoke the compatibility send path a second time.
                else:
                    response = _call_web_method_once(
                        self.web_chat.send_message,
                        profile_id,
                        prompt,
                        owner="agent",
                    )
            except Exception as error:
                self._log("info", "web route dispatch failed", error)
                response = {
                    "ok": False,
                    # Once an adapter invocation has begun, the coordinator
                    # cannot prove that a remote message was not accepted.
                    # Keep the result non-replayable and do not offer retry.
                    "status": "unknown",
                    "possibly_sent": True,
                    "reason": "web-chat-send-failed",
                    "error_code": type(error).__name__,
                }
            elapsed = (time.monotonic() - started) * 1000
            if not isinstance(response, Mapping):
                # A malformed adapter response must not crash the worker or be
                # interpreted as a safe pre-send failure.  It follows the same
                # non-replayable boundary as an ambiguous transport result.
                response = {
                    "ok": False,
                    "status": "unknown",
                    "possibly_sent": True,
                    "error_code": "invalid-adapter-response",
                    "reason": "web adapter returned a non-object response",
                }
            if cancel_event.is_set():
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "cancelled", latency_ms=elapsed, error_code="cancelled", consultation_id=dispatch.consultation_id)
            if response.get("ok") is True and isinstance(response.get("text"), str):
                answer = response["text"]
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "completed", answer=answer, latency_ms=elapsed, confidence=None, consultation_id=dispatch.consultation_id)
            if response.get("requires_human") or response.get("error_code") == "profile-occupied":
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "waiting-human", latency_ms=elapsed, error_code="requires-human", consultation_id=dispatch.consultation_id)
            if response.get("status") == "cancelled":
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "cancelled", latency_ms=elapsed, error_code="cancelled", consultation_id=dispatch.consultation_id)
            if response.get("pending") or response.get("possibly_sent") or response.get("status") in {"possibly-sent", "unknown"}:
                return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "unknown", latency_ms=elapsed, error_code=str(response.get("error_code") or "response-pending"), consultation_id=dispatch.consultation_id)
            error_code = str(response.get("error_code") or "route-unavailable").strip().replace(" ", "-")[:100]
            return SubtaskResult(dispatch.dispatch_id, descriptor.route_id, "failed", latency_ms=elapsed, error_code=error_code or "route-unavailable", consultation_id=dispatch.consultation_id)
        finally:
            if callable(set_agent_occupancy):
                set_agent_occupancy(profile_id, False)
            with self._lock:
                if self._occupancy.get(profile_id) == "agent":
                    self._occupancy.pop(profile_id, None)
            lock.release()

    def execute_runtime_dispatch(self, dispatch: Any, route: Any, cancel_event: threading.Event) -> SubtaskResult:
        """Execute a modern runtime-neutral web dispatch.

        ``DynamicRouteSupervisor`` owns admission and lifecycle; this method is
        only the compatibility adapter that supplies the legacy coordinator's
        BrowserSkill lease and the asynchronous ``start_message`` contract.
        Keeping the conversion here avoids making the supervisor depend on the
        legacy route dataclasses.
        """

        profile_id = str(getattr(route, "provider_profile_id", "") or "").strip()
        if not profile_id:
            return SubtaskResult(
                str(getattr(dispatch, "dispatch_id", "dispatch-unknown")),
                str(getattr(route, "route_id", "route-unknown")),
                "failed",
                error_code="profile-not-configured",
            )
        legacy = SubtaskDispatch(
            dispatch_id=str(getattr(dispatch, "dispatch_id", "")),
            consultation_id=getattr(dispatch, "consultation_id", None),
            parent_session_id=str(getattr(dispatch, "parent_session_id", "")),
            parent_turn_id=getattr(dispatch, "parent_turn_id", None),
            route_id=f"web-chat:{profile_id}",
            mode="consultation-panel" if getattr(dispatch, "consultation_id", None) else "web-worker",
            question=str(getattr(dispatch, "question", "")),
            context_refs=getattr(dispatch, "context_refs", {}) or {},
            continuation_of=getattr(dispatch, "continuation_of", None),
            role=str(getattr(dispatch, "role", "independent reviewer") or "independent reviewer"),
        )
        descriptor = RouteDescriptor(
            route_id=f"web-chat:{profile_id}",
            kind="web-worker",
            label=str(getattr(route, "label", profile_id) or profile_id),
            provider_profile_id=profile_id,
            provider_key=str(getattr(route, "provider_key", "web-chat") or "web-chat"),
            adapter_id=str(getattr(route, "adapter_id", "web-chat") or "web-chat"),
            domains=tuple(getattr(route, "domains", ()) or ()),
            capabilities=tuple(getattr(route, "capabilities", ("text",)) or ("text",)),
            status="ready",
            routable=True,
            occupancy="idle",
            quota_state=str(getattr(route, "quota_state", "unknown") or "unknown"),
            source="web-chat",
        )
        return self._execute_dispatch(legacy, descriptor, cancel_event)

    def _submit(self, dispatch: SubtaskDispatch, descriptor: RouteDescriptor, *, decision_kind: str = "small-answer") -> dict[str, Any]:
        now = _now()
        run = {
            "dispatch_id": dispatch.dispatch_id,
            "consultation_id": dispatch.consultation_id,
            "parent_session_id": dispatch.parent_session_id,
            "parent_turn_id": dispatch.parent_turn_id,
            "mode": dispatch.mode,
            "route_id": descriptor.route_id,
            "provider_profile_id": descriptor.provider_profile_id,
            "continuation_of": dispatch.continuation_of,
            "status": "queued",
            "started_at": now,
            "completed_at": None,
            "latency_ms": None,
            "error_code": None,
            "result_length": 0,
            "summary_hash": None,
            "retryable": False,
            "result": None,
        }
        cancel_event = threading.Event()
        with self._lock:
            self._runs[dispatch.dispatch_id] = run
            self._dispatches[dispatch.dispatch_id] = dispatch
            self._cancel_events[dispatch.dispatch_id] = cancel_event
        self._persist_run(run)
        self._emit("agent.route.queued", dispatch_id=dispatch.dispatch_id, consultation_id=dispatch.consultation_id, route_id=descriptor.route_id)

        def worker() -> None:
            with self._lock:
                run["status"] = "running"
            self._persist_run(run)
            self._emit("agent.route.started", dispatch_id=dispatch.dispatch_id, consultation_id=dispatch.consultation_id, route_id=descriptor.route_id)
            result = self._execute_dispatch(dispatch, descriptor, cancel_event, decision_kind)
            with self._lock:
                run["status"] = result.status
                run["completed_at"] = _now()
                run["latency_ms"] = result.latency_ms
                run["error_code"] = result.error_code
                run["result_length"] = len(result.answer or "")
                run["summary_hash"] = _hash_summary(result.summary)
                run["retryable"] = result.status == "failed" and result.error_code in {"route-unavailable", "web-chat-send-failed", "profile-not-ready"}
                run["result"] = result
            self._persist_run(run)
            self._emit("agent.route.completed" if result.status == "completed" else "agent.route.failed", dispatch_id=dispatch.dispatch_id, consultation_id=dispatch.consultation_id, route_id=descriptor.route_id, status=result.status, error_code=result.error_code)
            self._update_consultation(dispatch.consultation_id)

        try:
            future = self._executor.submit(worker)
        except RuntimeError:
            with self._lock:
                run["status"] = "unknown"
                run["error_code"] = "coordinator-closed"
            self._persist_run(run)
            return self._run_public(run)
        with self._lock:
            self._futures[dispatch.dispatch_id] = future
        return self._run_public(run)

    def dispatch(self, value: Mapping[str, Any] | SubtaskDispatch, *, route_id: str | None = None, wait: bool = False) -> dict[str, Any]:
        if self._closed:
            raise RouteError("route coordinator is closed")
        if isinstance(value, SubtaskDispatch):
            dispatch = value
        else:
            raw = dict(value)
            dispatch = SubtaskDispatch(
                dispatch_id=str(raw.get("dispatch_id") or raw.get("dispatchId") or f"dispatch-{uuid4().hex[:16]}"),
                consultation_id=raw.get("consultation_id") or raw.get("consultationId"),
                parent_session_id=str(raw.get("parent_session_id") or raw.get("parentSessionId") or ""),
                parent_turn_id=raw.get("parent_turn_id") or raw.get("parentTurnId"),
                route_id=str(route_id or raw.get("route_id") or raw.get("routeId") or ""),
                mode=str(raw.get("mode") or "web-worker"),
                question=raw.get("question") or raw.get("text") or "",
                context_refs=raw.get("context_refs") or raw.get("contextRefs") or {},
                continuation_of=raw.get("continuation_of") or raw.get("continuationOf"),
                role=str(raw.get("role") or "independent reviewer"),
            )
        catalog = self.catalog(include_templates=False)
        raw_descriptor = next((item for item in catalog["routes"] if item.get("route_id") == dispatch.route_id), None)
        if not raw_descriptor:
            raise RouteError("unknown or unavailable route")
        descriptor = RouteDescriptor(
            **{
                key: value
                for key, value in {
                    **raw_descriptor,
                    "domains": tuple(raw_descriptor.get("domains") or []),
                    "capabilities": tuple(raw_descriptor.get("capabilities") or ["text"]),
                }.items()
                if key != "schema"
            }
        )
        if not descriptor.routable:
            return {"accepted": False, "dispatch": {**dispatch.to_dict(), "status": "failed", "error_code": "route-unavailable"}, "reason": descriptor.reason or "route-unavailable"}
        result = self._submit(dispatch, descriptor)
        if wait:
            return self.wait(dispatch.dispatch_id)
        return {"accepted": True, "dispatch": result}

    def wait(self, dispatch_id: str, timeout: float | None = None) -> dict[str, Any]:
        dispatch_id = _id(dispatch_id, "dispatch_id") or ""
        with self._lock:
            future = self._futures.get(dispatch_id)
        if future:
            try:
                future.result(timeout=timeout)
            except TimeoutError:
                pass
        return self.status(dispatch_id)

    def status(self, dispatch_id: str) -> dict[str, Any]:
        dispatch_id = _id(dispatch_id, "dispatch_id") or ""
        with self._lock:
            run = self._runs.get(dispatch_id)
            if run is not None:
                return self._run_public(run)
        if self.storage:
            row = self.storage.get_agent_route_run(dispatch_id)
            if row:
                return {"dispatch": {**row, "status": row.get("status") or "unknown"}, "found": True}
        return {"found": False, "dispatch_id": dispatch_id}

    def start_consultation(self, value: Mapping[str, Any] | ConsultationRequest, *, wait: bool = False) -> dict[str, Any]:
        if self._closed:
            raise RouteError("route coordinator is closed")
        request = value if isinstance(value, ConsultationRequest) else ConsultationRequest.from_dict(value)
        routes = self._routes_for_request(request)
        now = _now()
        consultation = {
            "consultation_id": request.consultation_id,
            "parent_session_id": request.parent_session_id,
            "parent_turn_id": request.parent_turn_id,
            "decision_kind": request.decision_kind,
            "status": "queued" if routes else "failed",
            "max_members": request.max_members,
            "successful_count": 0,
            "failed_count": 0,
            "disagreement_detected": False,
            "untrusted_external": True,
            "member_metadata": [],
            "created_at": now,
            "updated_at": now,
            "request": request,
            "continuation_of": request.continuation_of,
        }
        with self._lock:
            if request.consultation_id in self._consultations:
                raise RouteError("consultation_id is already active")
            self._consultations[request.consultation_id] = consultation
        self._persist_consultation(consultation)
        if not routes:
            self._emit("agent.consultation.failed", consultation_id=request.consultation_id, error_code="no-routable-profile")
            return self.consultation_status(request.consultation_id)
        roles = ("方案设计顾问", "反例审查顾问", "风险检查顾问")
        for index, route in enumerate(routes):
            dispatch = SubtaskDispatch(
                dispatch_id=f"dispatch-{uuid4().hex[:16]}",
                consultation_id=request.consultation_id,
                parent_session_id=request.parent_session_id,
                parent_turn_id=request.parent_turn_id,
                route_id=route.route_id,
                mode="consultation-panel",
                question=request.question,
                context_refs=request.context_refs,
                continuation_of=request.continuation_of,
                role=roles[index % len(roles)],
            )
            consultation["member_metadata"].append({
                "dispatch_id": dispatch.dispatch_id,
                "route_id": route.route_id,
                "provider_profile_id": route.provider_profile_id,
                "status": "queued",
            })
            # Add the member metadata before submitting the worker.  A very
            # fast test/browser response must still be visible to the
            # consultation aggregator.
            self._submit(dispatch, route, decision_kind=request.decision_kind)
        # A member can finish immediately on a local fixture.  Recompute from
        # the authoritative in-memory run records instead of writing the
        # initial queued object back over a completed result.
        self._update_consultation(request.consultation_id)
        self._emit("agent.consultation.started", consultation_id=request.consultation_id, member_count=len(routes))
        if wait:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                current = self.consultation_status(request.consultation_id)
                if current.get("status") not in {"queued", "running"}:
                    return current
                time.sleep(0.02)
        return self.consultation_status(request.consultation_id)

    def _update_consultation(self, consultation_id: str | None) -> None:
        if not consultation_id:
            return
        with self._lock:
            consultation = self._consultations.get(consultation_id)
            if not consultation:
                return
            members: list[ConsultationMemberResult] = []
            metadata: list[dict[str, Any]] = []
            for item in consultation["member_metadata"]:
                run = self._runs.get(str(item.get("dispatch_id")))
                result = run.get("result") if run else None
                if not isinstance(result, SubtaskResult):
                    members.append(ConsultationMemberResult(str(item.get("dispatch_id")), str(item.get("route_id")), str(run.get("status") if run else "queued"), provider_profile_id=item.get("provider_profile_id"), consultation_id=consultation_id))
                else:
                    members.append(ConsultationMemberResult(result.dispatch_id, result.route_id, result.status, answer=result.answer, summary=result.summary, concerns=result.concerns, confidence=result.confidence, latency_ms=result.latency_ms, error_code=result.error_code, provider_profile_id=item.get("provider_profile_id"), consultation_id=consultation_id))
                metadata.append({
                    "dispatch_id": item.get("dispatch_id"), "route_id": item.get("route_id"), "provider_profile_id": item.get("provider_profile_id"),
                    "status": members[-1].status, "latency_ms": members[-1].latency_ms, "result_length": len(members[-1].answer or ""), "error_code": members[-1].error_code,
                })
            successful = sum(1 for member in members if member.status == "completed")
            finished = sum(1 for member in members if member.status not in {"queued", "running"})
            failed = sum(1 for member in members if member.status != "completed" and member.status not in {"queued", "running"})
            if finished < len(members):
                status = "running"
            elif successful == len(members):
                status = "completed"
            elif successful:
                status = "partial"
            elif any(member.status == "cancelled" for member in members):
                status = "cancelled"
            elif any(member.status == "waiting-human" for member in members):
                status = "waiting-human"
            else:
                status = "failed"
            answers = [member.summary for member in members if member.status == "completed" and member.summary]
            disagreement = len({item.casefold() for item in answers}) > 1 if len(answers) > 1 else False
            consultation["status"] = status
            consultation["successful_count"] = successful
            consultation["failed_count"] = failed
            consultation["disagreement_detected"] = disagreement
            consultation["member_metadata"] = metadata
            consultation["updated_at"] = _now()
            consultation["members"] = tuple(members)
        self._persist_consultation(consultation)
        if status in {"completed", "partial", "failed", "cancelled", "waiting-human"}:
            self._emit("agent.consultation.completed", consultation_id=consultation_id, status=status, successful_count=successful, failed_count=failed, disagreement_detected=disagreement)

    def consultation_status(self, consultation_id: str) -> dict[str, Any]:
        consultation_id = _id(consultation_id, "consultation_id") or ""
        self._update_consultation(consultation_id)
        with self._lock:
            value = self._consultations.get(consultation_id)
            if value:
                members = value.get("members") or tuple(
                    ConsultationMemberResult(str(item.get("dispatch_id")), str(item.get("route_id")), str(item.get("status") or "queued"), provider_profile_id=item.get("provider_profile_id"), consultation_id=consultation_id)
                    for item in value.get("member_metadata", [])
                )
                result = ConsultationResult(
                    consultation_id,
                    value.get("status", "unknown"),
                    tuple(members),
                    value.get("successful_count", 0),
                    value.get("failed_count", 0),
                    bool(value.get("disagreement_detected")),
                    True,
                    value.get("decision_kind"),
                    value.get("parent_session_id"),
                    "single-opinion" if len(members) == 1 else "panel",
                )
                return result.to_dict()
        if self.storage:
            row = self.storage.get_agent_consultation(consultation_id)
            if row:
                return {
                    "schema": AGENT_CONSULTATION_SCHEMA,
                    "consultation_id": consultation_id,
                    "parent_session_id": row.get("parent_session_id"),
                    "decision_kind": row.get("decision_kind"),
                    "status": row.get("status", "unknown"),
                    "members": row.get("member_metadata") or [],
                    "successful_count": row.get("successful_count", 0),
                    "failed_count": row.get("failed_count", 0),
                    "disagreement_detected": bool(row.get("disagreement_detected")),
                    "untrusted_external": True,
                    "trust_label": UNTRUSTED_WEB_RESULT_LABEL,
                    "opinion_mode": "single-opinion" if len(row.get("member_metadata") or []) == 1 else "panel",
                    "single_opinion": len(row.get("member_metadata") or []) == 1,
                }
        return {"schema": AGENT_CONSULTATION_SCHEMA, "consultation_id": consultation_id, "status": "unknown", "members": [], "found": False, "untrusted_external": True, "trust_label": UNTRUSTED_WEB_RESULT_LABEL}

    def list_consultations(self, *, parent_session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if parent_session_id:
            parent_session_id = _id(parent_session_id, "parent_session_id")
        with self._lock:
            values = list(self._consultations.values())
        values.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        result = [self.consultation_status(str(item["consultation_id"])) for item in values if not parent_session_id or item.get("parent_session_id") == parent_session_id]
        if self.storage and len(result) < limit:
            for row in self.storage.list_agent_consultations(parent_session_id=parent_session_id, limit=limit):
                if not any(item.get("consultation_id") == row.get("consultation_id") for item in result):
                    result.append(self.consultation_status(str(row.get("consultation_id"))))
        return result[: max(1, min(int(limit), 100))]

    def cancel(self, dispatch_id: str) -> dict[str, Any]:
        dispatch_id = _id(dispatch_id, "dispatch_id") or ""
        with self._lock:
            event = self._cancel_events.get(dispatch_id)
            run = self._runs.get(dispatch_id)
            if event is None or run is None:
                return {"dispatch_id": dispatch_id, "cancelled": False, "reason": "unknown-dispatch"}
            if run.get("status") in {"completed", "failed", "cancelled", "unknown", "interrupted"}:
                return {"dispatch_id": dispatch_id, "cancelled": False, "reason": "already-finished", "status": run.get("status")}
            event.set()
            run["status"] = "cancelled"
            run["error_code"] = "cancelled"
        self._persist_run(run)
        self._emit("agent.route.cancelled", dispatch_id=dispatch_id, consultation_id=run.get("consultation_id"))
        self._update_consultation(run.get("consultation_id"))
        return {"dispatch_id": dispatch_id, "cancelled": True, "status": "cancelled"}

    def cancel_consultation(self, consultation_id: str) -> dict[str, Any]:
        consultation_id = _id(consultation_id, "consultation_id") or ""
        ids: list[str] = []
        with self._lock:
            value = self._consultations.get(consultation_id)
            if value:
                ids = [str(item.get("dispatch_id")) for item in value.get("member_metadata", [])]
        results = [self.cancel(item) for item in ids]
        self._update_consultation(consultation_id)
        return {"consultation_id": consultation_id, "cancelled": any(item.get("cancelled") for item in results), "dispatches": results}

    def retry(self, dispatch_id: str) -> dict[str, Any]:
        dispatch_id = _id(dispatch_id, "dispatch_id") or ""
        with self._lock:
            run = self._runs.get(dispatch_id)
        if not run:
            raise RouteError("unknown dispatch")
        if run.get("status") != "failed" or not run.get("retryable"):
            raise RouteError("only a confirmed pre-send failure can be retried")
        with self._lock:
            previous = self._dispatches.get(dispatch_id)
        if previous is None:
            raise RouteError("retry context is no longer available")
        return self.dispatch(
            SubtaskDispatch(
                dispatch_id=f"dispatch-{uuid4().hex[:16]}",
                consultation_id=previous.consultation_id,
                parent_session_id=previous.parent_session_id,
                parent_turn_id=previous.parent_turn_id,
                route_id=previous.route_id,
                mode=previous.mode,
                question=previous.question,
                context_refs=previous.context_refs,
                continuation_of=dispatch_id,
                role=previous.role,
            )
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            runs = [run for run in self._runs.values() if run.get("status") in {"queued", "running"}]
            for run in runs:
                event = self._cancel_events.get(str(run.get("dispatch_id")))
                if event:
                    event.set()
                run["status"] = "interrupted"
                run["error_code"] = "core-shutdown"
                self._persist_run(run)
            consultations = [item for item in self._consultations.values() if item.get("status") in {"queued", "running"}]
            for item in consultations:
                item["status"] = "interrupted"
                item["updated_at"] = _now()
                self._persist_consultation(item)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def manual_send(self, profile_id: str, text: str) -> dict[str, Any]:
        """Serialize a direct workbench send with Agent workers."""

        profile_id = _id(profile_id, "profile_id") or ""
        lock = self._profile_lock(profile_id)
        if not lock.acquire(blocking=False):
            return {"ok": False, "requires_human": True, "profile_id": profile_id, "error_code": "profile-occupied", "reason": "该网页 Profile 正由 Agent 使用"}
        with self._lock:
            if self._occupancy.get(profile_id) == "agent":
                lock.release()
                return {"ok": False, "requires_human": True, "profile_id": profile_id, "error_code": "profile-occupied", "reason": "该网页 Profile 正由 Agent 使用"}
            previous = self._occupancy.get(profile_id)
            self._occupancy[profile_id] = "manual"
        try:
            sender = getattr(self.web_chat, "send_message")
            return _call_web_method_once(sender, profile_id, text, owner="manual")
        finally:
            with self._lock:
                if previous:
                    self._occupancy[profile_id] = previous
                else:
                    self._occupancy.pop(profile_id, None)
            lock.release()


# Descriptive alias used by callers that want to emphasize the web-only first
# implementation.  A future API or local-model coordinator can reuse the same
# contracts without changing the Agent UI.
WebRouteCoordinator = RouteCoordinator


__all__ = [
    "AGENT_ROUTE_SCHEMA",
    "AGENT_CONSULTATION_SCHEMA",
    "ROUTE_EVIDENCE_SCHEMA",
    "UNTRUSTED_WEB_RESULT_LABEL",
    "RouteEvidence",
    "ConsultationMemberResult",
    "ConsultationRequest",
    "ConsultationResult",
    "RouteCoordinator",
    "RouteDescriptor",
    "RouteError",
    "RouteValidationError",
    "SubtaskDispatch",
    "SubtaskResult",
    "WebRouteCoordinator",
    "sanitize_context",
    "sanitize_text",
]
