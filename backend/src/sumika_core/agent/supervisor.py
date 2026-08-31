"""Runtime-neutral dynamic route supervision.

The supervisor is deliberately a *scheduler*, not another Agent loop.  A
Harness owns the semantic goal and decides which subtask should be requested;
this module only validates that request, applies evidence/permission/ budget
gates, and runs an already registered worker.  Keeping that boundary small
means a DSH, ZCode, or future Harness can use the same Core implementation.

The older web-only :mod:`sumika_core.agent.routes` coordinator remains the
compatibility entry point for existing RPCs.  This module accepts its route
descriptors and result objects where possible, while adding the fields needed
by non-web workers and turn-level scheduling.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol
from uuid import uuid4

from .routes import (
    AGENT_CONSULTATION_SCHEMA,
    AGENT_ROUTE_SCHEMA,
    ConsultationMemberResult,
    ConsultationRequest,
    ConsultationResult,
    ROUTE_EVIDENCE_SCHEMA,
    RouteDescriptor as LegacyRouteDescriptor,
    RouteError,
    RouteEvidence as LegacyRouteEvidence,
    RouteValidationError,
    SubtaskResult as LegacySubtaskResult,
    sanitize_context,
    sanitize_text,
)


SUPERVISOR_SCHEMA = AGENT_ROUTE_SCHEMA
EVENT_BOUNDARIES = frozenset(
    {
        "turn.started",
        "tool.completed",
        "approval.resolved",
        "turn.completed",
        "turn.failed",
        "turn.cancelled",
    }
)
WORKER_KINDS = frozenset(
    {
        "provider",
        "web",
        "web-worker",
        "external-harness",
        "zcode",
        "native-child-agent",
        "child-agent",
        "desktop-app",
    }
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
        "needs-confirmation",
    }
)
SIDE_EFFECTS = frozenset({"none", "read", "write", "external"})
WORKSPACE_ACCESS = frozenset({"none", "read-only", "isolated-worktree"})
EVIDENCE_ORDER = {
    # A declaration is useful for discovery but is never as strong as a
    # repeatable observation.
    "adapter-declaration": 0,
    "protocol-probe": 1,
    "smoke": 2,
    "fixed-smoke": 2,
    "real-run": 3,
    "repeated-real-run": 4,
    "usage": 3,
    "official-usage-api": 3,
    "official-pricing": 2,
    "user-confirmation": 1,
    "evaluation": 3,
    "unknown": -1,
}
QUALITY_ORDER = {"unknown": 0, "basic": 1, "standard": 2, "strong": 3, "premium": 4}
COST_ORDER = {"free-limited": 0, "local": 1, "paid-low": 2, "paid-high": 3, "unknown": 4}


class SupervisorError(RouteError):
    """A controlled, safe-to-present supervisor error."""


class SupervisorValidationError(SupervisorError, RouteValidationError):
    """Malformed route, request, or worker input."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: Any, field_name: str, *, required: bool = True) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        if required:
            raise SupervisorValidationError(f"{field_name} is required")
        return None
    if len(candidate) > 240 or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise SupervisorValidationError(f"{field_name} is invalid")
    # Keep the same portable identifier alphabet used by the legacy route
    # contracts.  This also prevents values from becoming log/control syntax.
    import re

    if re.fullmatch(r"[A-Za-z0-9._:-]+", candidate) is None:
        raise SupervisorValidationError(f"{field_name} is invalid")
    return candidate


def _token(value: Any, field_name: str, *, default: str = "unknown") -> str:
    candidate = str(value or default).strip().lower()
    if not candidate or len(candidate) > 120:
        raise SupervisorValidationError(f"{field_name} is invalid")
    import re

    if re.fullmatch(r"[A-Za-z0-9._:-]+", candidate) is None:
        raise SupervisorValidationError(f"{field_name} is invalid")
    return candidate


_MISSING = object()


def _strict_bool(value: Any, field_name: str, *, default: Any = _MISSING) -> bool:
    """Accept only JSON booleans at public contract boundaries.

    Python's ``bool`` coercion turns values such as ``"false"`` and ``1`` into
    ``True``.  That is unsafe for routing and approval fields, so callers must
    either provide a real boolean or omit the field and use the declared
    default.
    """

    if value is _MISSING:
        if default is _MISSING:
            raise SupervisorValidationError(f"{field_name} must be boolean")
        value = default
    if type(value) is not bool:
        raise SupervisorValidationError(f"{field_name} must be boolean")
    return value


def _safe_context(value: Any, *, budget: int = 28_000) -> Any:
    """Use the established conservative sanitizer for worker context."""

    try:
        return sanitize_context(value, budget=budget)
    except (RouteValidationError, ValueError) as exc:
        raise SupervisorValidationError(str(exc)) from exc


def _safe_question(value: Any, *, limit: int = 16_000) -> str:
    if not isinstance(value, str):
        raise SupervisorValidationError("question must be text")
    if not value.strip():
        raise SupervisorValidationError("question is required")
    try:
        return sanitize_text(value.strip(), limit=limit)
    except RouteValidationError as exc:
        raise SupervisorValidationError(str(exc)) from exc


def _safe_timestamp(value: Any, field_name: str, *, optional: bool = True) -> str | None:
    if value in (None, "") and optional:
        return None
    candidate = str(value or "").strip()
    if len(candidate) > 100:
        raise SupervisorValidationError(f"{field_name} is invalid")
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise SupervisorValidationError(f"{field_name} is invalid") from exc
    return candidate


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8", "replace")).hexdigest()[:32]


def _summary(value: Any, limit: int = 600) -> str | None:
    if value in (None, ""):
        return None
    try:
        text = sanitize_text(" ".join(str(value).split()), limit=min(limit, 1_200))
    except RouteValidationError as exc:
        raise SupervisorValidationError(str(exc)) from exc
    return text[:limit]


def _call_with_supported_signature(target: Callable[..., Any], dispatch: Any, route: Any, cancel_event: threading.Event) -> Any:
    """Invoke fixtures/adapters with 1, 2, or 3 conventional arguments.

    Inspecting first avoids catching a ``TypeError`` raised *inside* an
    executor and accidentally invoking it a second time (which could send a
    duplicate external request).
    """

    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return target(dispatch, route, cancel_event)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(parameter.kind == parameter.VAR_POSITIONAL for parameter in signature.parameters.values())
    count = 3 if has_varargs else len(positional)
    if count >= 3:
        return target(dispatch, route, cancel_event)
    if count == 2:
        return target(dispatch, route)
    if count == 1:
        return target(dispatch)
    return target()


@dataclass(frozen=True, slots=True)
class DynamicRouteEvidence:
    """Runtime-neutral evidence wrapper.

    ``RouteEvidence`` in ``routes.py`` is the public web contract and is
    reused directly by the resolver.  This wrapper exists for callers that
    need a route association or a textual confidence level; ``to_legacy``
    converts it without exposing any content.
    """

    evidence_type: str
    source: str
    route_id: str = ""
    version: str = ""
    observed_at: str = field(default_factory=_now)
    expires_at: str | None = None
    valid_until: str | None = None
    confidence: str | float | None = "unknown"
    evidence_id: str = field(default_factory=lambda: f"evidence-{uuid4().hex[:16]}")
    refs: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id") or "")
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id", required=False) or "")
        object.__setattr__(self, "evidence_type", _token(self.evidence_type, "evidence_type"))
        object.__setattr__(self, "source", sanitize_text(str(self.source or "unknown"), limit=400))
        object.__setattr__(self, "version", sanitize_text(str(self.version or ""), limit=120))
        object.__setattr__(self, "observed_at", _safe_timestamp(self.observed_at, "observed_at", optional=False) or _now())
        expiry = self.expires_at or self.valid_until
        object.__setattr__(self, "expires_at", _safe_timestamp(expiry, "expires_at") if expiry else None)
        object.__setattr__(self, "valid_until", self.expires_at)
        confidence = self.confidence
        if isinstance(confidence, bool):
            confidence = "unknown"
        elif isinstance(confidence, (int, float)):
            confidence = round(max(0.0, min(1.0, float(confidence))), 3)
        else:
            confidence = str(confidence or "unknown").strip().lower()
            if confidence not in {"unknown", "low", "medium", "high"}:
                confidence = "unknown"
        object.__setattr__(self, "confidence", confidence)
        refs: list[str] = []
        for ref in tuple(self.refs or ())[:16]:
            normalized = _identifier(ref, "evidence_ref", required=False)
            if normalized:
                refs.append(normalized)
        object.__setattr__(self, "refs", tuple(refs))
        object.__setattr__(self, "details", _safe_context(self.details, budget=4_000) if isinstance(self.details, Mapping) else {})

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

    @property
    def effective_type(self) -> str:
        return self.evidence_type if self.fresh else "unknown"

    @property
    def stale(self) -> bool:
        return not self.fresh

    @property
    def is_expired(self) -> bool:
        return self.stale

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    @property
    def effective_confidence(self) -> str | float:
        return self.confidence if self.fresh else "unknown"

    def effective(self) -> "DynamicRouteEvidence":
        if self.fresh:
            return self
        return replace(self, evidence_type="unknown", confidence="unknown")

    def to_legacy(self) -> LegacyRouteEvidence:
        # ``RouteEvidence`` accepts a numeric confidence.  Preserve levels in
        # details so no evidence strength is silently invented.
        numeric = self.confidence if isinstance(self.confidence, (int, float)) else None
        details = dict(self.details)
        if isinstance(self.confidence, str):
            details.setdefault("confidence_level", self.confidence)
        if self.route_id:
            details.setdefault("route_id", self.route_id)
        return LegacyRouteEvidence(
            evidence_id=self.evidence_id,
            evidence_type=self.evidence_type if self.evidence_type in {"adapter-declaration", "protocol-probe", "smoke", "real-run", "usage", "official-pricing", "user-confirmation", "unknown"} else "unknown",
            source=self.source,
            version=self.version,
            observed_at=self.observed_at,
            expires_at=self.expires_at,
            confidence=numeric,
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_EVIDENCE_SCHEMA,
            "evidence_id": self.evidence_id,
            "route_id": self.route_id or None,
            "evidence_type": self.evidence_type,
            "effective_type": self.effective_type,
            "source": self.source,
            "version": self.version,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "valid_until": self.valid_until,
            "confidence": self.effective_confidence,
            "fresh": self.fresh,
            "refs": list(self.refs),
            "details": self.details,
        }

    @classmethod
    def from_value(cls, value: Any, *, route_id: str = "") -> "DynamicRouteEvidence":
        if isinstance(value, cls):
            return value
        if isinstance(value, LegacyRouteEvidence):
            raw = value.to_dict()
            return cls(
                evidence_id=raw.get("evidence_id") or f"evidence-{uuid4().hex[:16]}",
                evidence_type=raw.get("evidence_type") or "unknown",
                source=raw.get("source") or "unknown",
                route_id=route_id,
                version=raw.get("version") or "",
                observed_at=raw.get("observed_at") or _now(),
                expires_at=raw.get("expires_at"),
                confidence=raw.get("confidence"),
                details=raw.get("details") if isinstance(raw.get("details"), Mapping) else {},
            )
        if isinstance(value, Mapping):
            return cls(
                evidence_id=str(value.get("evidence_id") or value.get("evidenceId") or f"evidence-{uuid4().hex[:16]}"),
                evidence_type=str(value.get("evidence_type") or value.get("type") or value.get("kind") or "unknown"),
                source=str(value.get("source") or "unknown"),
                route_id=str(value.get("route_id") or value.get("routeId") or route_id),
                version=str(value.get("version") or ""),
                observed_at=str(value.get("observed_at") or value.get("observedAt") or _now()),
                expires_at=value.get("expires_at") or value.get("expiresAt") or value.get("valid_until"),
                confidence=value.get("confidence"),
                refs=tuple(value.get("refs") or value.get("evidence_refs") or ()),
                details=value.get("details") if isinstance(value.get("details"), Mapping) else {},
            )
        raise SupervisorValidationError("route evidence must be an object")


class EvidenceResolver:
    """Store and rank bounded route evidence without making quality claims."""

    def __init__(self, evidence: Iterable[Any] | None = None, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._items: dict[str, DynamicRouteEvidence] = {}
        if evidence:
            self.add_many(evidence)

    def _fresh(self, item: DynamicRouteEvidence) -> bool:
        if not item.expires_at:
            return True
        try:
            expiry = datetime.fromisoformat(item.expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            now = self._clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            return expiry > now
        except (TypeError, ValueError, OverflowError):
            return False

    def _effective(self, item: DynamicRouteEvidence) -> DynamicRouteEvidence:
        return item if self._fresh(item) else replace(item, evidence_type="unknown", confidence="unknown")

    def add(self, evidence: Any, *, route_id: str = "") -> DynamicRouteEvidence:
        item = DynamicRouteEvidence.from_value(evidence, route_id=route_id)
        with self._lock:
            self._items[item.evidence_id] = item
            if len(self._items) > 1024:
                self._items = dict(list(self._items.items())[-1024:])
        return item

    register = add

    def add_many(self, evidence: Iterable[Any], *, route_id: str = "") -> list[DynamicRouteEvidence]:
        result: list[DynamicRouteEvidence] = []
        if isinstance(evidence, (Mapping, DynamicRouteEvidence, LegacyRouteEvidence)):
            evidence = [evidence]
        for item in list(evidence)[:1024]:
            result.append(self.add(item, route_id=route_id))
        return result

    register_many = add_many

    def remove(self, evidence_id: str) -> bool:
        identifier = _identifier(evidence_id, "evidence_id") or ""
        with self._lock:
            return self._items.pop(identifier, None) is not None

    def all(self, *, fresh_only: bool = False) -> list[DynamicRouteEvidence]:
        with self._lock:
            values = list(self._items.values())
        if fresh_only:
            return [item for item in values if self._fresh(item)]
        return values

    def for_route(self, route_id: str, *, refs: Iterable[str] | None = None, fresh_only: bool = False) -> list[DynamicRouteEvidence]:
        identifier = _identifier(route_id, "route_id") or ""
        wanted = {str(item) for item in refs or () if item}
        with self._lock:
            values = [item for item in self._items.values() if (not item.route_id or item.route_id == identifier)]
            if wanted:
                values = [item for item in values if item.evidence_id in wanted]
        if fresh_only:
            values = [item for item in values if self._fresh(item)]
        return sorted(values, key=lambda item: (EVIDENCE_ORDER.get(self._effective(item).effective_type, -1), item.observed_at, item.evidence_id), reverse=True)

    def resolve(self, route_id: str, *, purpose: str = "capability", refs: Iterable[str] | None = None) -> DynamicRouteEvidence | None:
        values = self.for_route(route_id, refs=refs)
        if not values:
            return None
        purpose = str(purpose or "capability").strip().lower()
        # Cost observations and capability observations have different useful
        # types.  We still return the strongest available item if no exact
        # purpose evidence exists, but stale values are visibly downgraded.
        preferred = {
            "capability": {"adapter-declaration", "protocol-probe", "smoke", "fixed-smoke", "real-run", "repeated-real-run"},
            "cost": {"usage", "official-usage-api", "official-pricing", "user-confirmation"},
            "quality": {"smoke", "fixed-smoke", "real-run", "repeated-real-run", "evaluation"},
        }.get(purpose, set())
        matching = [item for item in values if item.effective_type in preferred]
        selected = (matching or values)[0]
        return self._effective(selected)

    def resolve_dict(self, route_id: str, *, purpose: str = "capability", refs: Iterable[str] | None = None) -> dict[str, Any] | None:
        item = self.resolve(route_id, purpose=purpose, refs=refs)
        return item.to_dict() if item else None

    def references(self, route_id: str, *, refs: Iterable[str] | None = None) -> list[dict[str, Any]]:
        return [self._effective(item).to_dict() for item in self.for_route(route_id, refs=refs)]

    def hashes(self, route_id: str, *, refs: Iterable[str] | None = None) -> list[str]:
        return [_hash(item.to_dict()) for item in self.for_route(route_id, refs=refs)]


@dataclass(frozen=True, slots=True)
class RuntimeRouteDescriptor:
    """Extended route descriptor understood by any Harness adapter."""

    route_id: str
    kind: str
    label: str
    runtime_id: str = "unknown"
    executor: str = "unknown"
    transport: str = "unknown"
    side_effect: str = "none"
    quota_consent: str | bool = "unknown"
    evidence_refs: tuple[str, ...] = ()
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
    source: str = "core"
    source_kind: str = "provider"
    quality_tier: str = "unknown"
    cost_class: str = "unknown"
    processing_location: str = "cloud"
    auth_state: str = "unknown"
    health_state: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id") or "")
        object.__setattr__(self, "kind", _token(self.kind, "kind"))
        object.__setattr__(self, "label", sanitize_text(str(self.label or self.route_id), limit=200))
        object.__setattr__(self, "runtime_id", _token(self.runtime_id, "runtime_id"))
        object.__setattr__(self, "executor", _token(self.executor, "executor"))
        object.__setattr__(self, "transport", _token(self.transport, "transport"))
        side = str(self.side_effect or "none").strip().lower()
        if side not in SIDE_EFFECTS:
            raise SupervisorValidationError("route side_effect is invalid")
        object.__setattr__(self, "side_effect", side)
        consent = self.quota_consent
        if isinstance(consent, bool):
            consent = "granted" if consent else "unknown"
        consent = _token(consent, "quota_consent")
        object.__setattr__(self, "quota_consent", consent)
        refs: list[str] = []
        for ref in tuple(self.evidence_refs or ())[:16]:
            normalized = _identifier(ref, "evidence_ref", required=False)
            if normalized:
                refs.append(normalized)
        object.__setattr__(self, "evidence_refs", tuple(refs))
        object.__setattr__(self, "provider_profile_id", _identifier(self.provider_profile_id, "provider_profile_id", required=False))
        object.__setattr__(self, "adapter_id", _token(self.adapter_id, "adapter_id") if self.adapter_id else None)
        object.__setattr__(self, "provider_key", _token(self.provider_key, "provider_key"))
        object.__setattr__(self, "domains", tuple(sanitize_text(str(item), limit=200) for item in tuple(self.domains or ())[:8]))
        object.__setattr__(self, "capabilities", tuple(_token(item, "capability") for item in tuple(self.capabilities or ())[:24]) or ("text",))
        status = str(self.status or "unavailable").strip().lower()
        if status not in {"queued", "running", "completed", "partial", "failed", "cancelled", "waiting-human", "unknown", "interrupted", "ready", "available", "configured", "needs-auth", "archived", "unavailable"}:
            raise SupervisorValidationError("route status is invalid")
        occupancy = str(self.occupancy or "idle").strip().lower()
        if occupancy not in {"idle", "agent", "manual", "waiting"}:
            raise SupervisorValidationError("route occupancy is invalid")
        quota_state = str(self.quota_state or "unknown").strip().lower()
        if quota_state not in {"available", "low", "exhausted", "expired", "needs-auth", "blocked", "unknown", "not-applicable"}:
            quota_state = "unknown"
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "occupancy", occupancy)
        object.__setattr__(self, "quota_state", quota_state)
        object.__setattr__(self, "routable", _strict_bool(self.routable, "routable"))
        object.__setattr__(self, "requires_confirmation", _strict_bool(self.requires_confirmation, "requires_confirmation"))
        object.__setattr__(self, "source", sanitize_text(str(self.source or "core"), limit=120))
        object.__setattr__(self, "source_kind", _token(self.source_kind, "source_kind"))
        quality = str(self.quality_tier or "unknown").strip().lower()
        cost = str(self.cost_class or "unknown").strip().lower()
        if quality not in QUALITY_ORDER:
            quality = "unknown"
        if cost not in COST_ORDER:
            cost = "unknown"
        object.__setattr__(self, "quality_tier", quality)
        object.__setattr__(self, "cost_class", cost)
        object.__setattr__(self, "processing_location", _token(self.processing_location, "processing_location"))
        object.__setattr__(self, "auth_state", _token(self.auth_state, "auth_state"))
        object.__setattr__(self, "health_state", _token(self.health_state, "health_state"))
        object.__setattr__(self, "metadata", _safe_context(self.metadata, budget=4_000) if isinstance(self.metadata, Mapping) else {})

    @property
    def available(self) -> bool:
        return bool(self.routable and self.status in {"ready", "available", "configured"} and self.occupancy in {"idle", "agent"})

    # Short aliases used by the route-evidence/agent-route prose contract.
    # Keeping them as properties avoids duplicating mutable state or changing
    # the serialized field names already used by the Core APIs.
    @property
    def runtime(self) -> str:
        return self.runtime_id

    @property
    def executor_id(self) -> str:
        return self.executor

    @property
    def side_effect_class(self) -> str:
        return self.side_effect

    @property
    def requires_browser(self) -> bool:
        return self.transport in {"browser", "browser-dom", "cdp"} or self.kind in {"web", "web-worker"}

    @classmethod
    def from_value(cls, value: Any) -> "RuntimeRouteDescriptor":
        if isinstance(value, cls):
            return value
        if isinstance(value, LegacyRouteDescriptor):
            raw = value.to_dict()
        elif isinstance(value, Mapping):
            raw = dict(value)
        else:
            raise SupervisorValidationError("route descriptor must be an object")
        aliases = {
            "runtime": "runtime_id",
            "runtimeId": "runtime_id",
            "executor_id": "executor",
            "executorId": "executor",
            "side_effect_class": "side_effect",
            "sideEffect": "side_effect",
            "quotaConsent": "quota_consent",
            "evidenceRefs": "evidence_refs",
            "sourceKind": "source_kind",
            "qualityTier": "quality_tier",
            "costClass": "cost_class",
            "processingLocation": "processing_location",
            "authState": "auth_state",
            "healthState": "health_state",
        }
        for old, new in aliases.items():
            if new not in raw and old in raw:
                raw[new] = raw[old]
        model_fields = {
            key: raw[key]
            for key in (
                "route_id", "provider_id", "model_id", "display_name",
                "provider_profile_id", "harness_id", "capabilities",
                "quality_tier", "cost_class", "processing_location",
                "auth_state", "quota_state", "health_state", "observed_at",
                "version", "source_kind", "transport", "metadata",
            )
            if key in raw
        }
        if model_fields.get("provider_id") and model_fields.get("model_id"):
            metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), Mapping) else {}
            metadata.setdefault("model_entry", model_fields)
            raw["metadata"] = metadata
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in raw.items() if key in allowed})

    def to_dict(self, *, evidence: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "schema": SUPERVISOR_SCHEMA,
            "route_id": self.route_id,
            "kind": self.kind,
            "worker_kind": self.kind,
            "label": self.label,
            "runtime_id": self.runtime_id,
            "runtime": self.runtime_id,
            "executor": self.executor,
            "executor_id": self.executor,
            "transport": self.transport,
            "side_effect": self.side_effect,
            "side_effect_class": self.side_effect,
            "quota_consent": self.quota_consent,
            "evidence_refs": list(self.evidence_refs),
            "evidence": list(evidence or ()),
            "provider_profile_id": self.provider_profile_id,
            "provider_key": self.provider_key,
            "adapter_id": self.adapter_id,
            "domains": list(self.domains),
            "capabilities": list(self.capabilities),
            "status": self.status,
            "routable": self.routable,
            "available": self.available,
            "occupancy": self.occupancy,
            "quota_state": self.quota_state,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
            "source": self.source,
            "source_kind": self.source_kind,
            "quality_tier": self.quality_tier,
            "cost_class": self.cost_class,
            "processing_location": self.processing_location,
            "auth_state": self.auth_state,
            "health_state": self.health_state,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass(frozen=True, slots=True)
class DynamicRoutingRequest:
    """A turn-scoped routing request supplied by the main Agent."""

    parent_session_id: str
    question: str
    parent_turn_id: str | None = None
    task_kind: str = "chat"
    phase: str = "execute"
    task_stage: str | None = None
    trigger_event: str | None = None
    risk: str = "normal"
    difficulty: str = "auto"
    required_capabilities: tuple[str, ...] = ()
    privacy_constraints: tuple[str, ...] = ()
    budget_remaining: float | None = None
    remaining_budget: float | None = None
    budget_unit: str = "tokens"
    latency_target_ms: int | None = None
    confirmation_mode: str = "recommendation-then-confirmation"
    budget_policy: str = "prefer-free"
    preferred_route: str | None = None
    min_quality_tier: str | None = None
    workspace_access: str = "none"
    depth: int = 0
    decision_key: str | None = None
    route_id: str | None = None
    context_refs: Any = field(default_factory=dict)
    auto_dispatch: bool = False
    quota_consent: bool = False
    confirmed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_session_id", _identifier(self.parent_session_id, "parent_session_id") or "")
        object.__setattr__(self, "parent_turn_id", _identifier(self.parent_turn_id, "parent_turn_id", required=False))
        object.__setattr__(self, "question", _safe_question(self.question))
        object.__setattr__(self, "task_kind", _token(self.task_kind, "task_kind", default="chat"))
        phase = self.task_stage if self.task_stage not in (None, "") else self.phase
        object.__setattr__(self, "phase", _token(phase, "phase", default="execute"))
        object.__setattr__(self, "task_stage", self.phase)
        event = str(self.trigger_event or "").strip().lower() or None
        if event and event not in EVENT_BOUNDARIES:
            raise SupervisorValidationError("trigger_event is not a replan boundary")
        object.__setattr__(self, "trigger_event", event)
        risk = str(self.risk or "normal").strip().lower()
        if risk not in {"low", "normal", "high", "critical"}:
            raise SupervisorValidationError("risk is invalid")
        object.__setattr__(self, "risk", risk)
        difficulty = str(self.difficulty or "auto").strip().lower()
        if difficulty not in {"auto", "trivial", "basic", "moderate", "complex", "critical"}:
            raise SupervisorValidationError("difficulty is invalid")
        object.__setattr__(self, "difficulty", difficulty)
        object.__setattr__(self, "required_capabilities", tuple(_token(item, "required_capability") for item in tuple(self.required_capabilities or ())[:24]))
        object.__setattr__(self, "privacy_constraints", tuple(_token(item, "privacy_constraint") for item in tuple(self.privacy_constraints or ())[:24]))
        budget = self.budget_remaining if self.budget_remaining is not None else self.remaining_budget
        if budget is not None:
            if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0:
                raise SupervisorValidationError("budget_remaining must be non-negative")
            budget = float(budget)
        object.__setattr__(self, "budget_remaining", budget)
        object.__setattr__(self, "remaining_budget", budget)
        object.__setattr__(self, "budget_unit", _token(self.budget_unit, "budget_unit", default="tokens"))
        if self.latency_target_ms is not None and (isinstance(self.latency_target_ms, bool) or not isinstance(self.latency_target_ms, int) or self.latency_target_ms < 1 or self.latency_target_ms > 3_600_000):
            raise SupervisorValidationError("latency_target_ms is invalid")
        confirmation = _token(self.confirmation_mode, "confirmation_mode", default="recommendation-then-confirmation")
        if confirmation not in {"recommendation-then-confirmation", "automatic", "manual"}:
            raise SupervisorValidationError("confirmation_mode is invalid")
        budget_policy = _token(self.budget_policy, "budget_policy", default="prefer-free")
        if budget_policy not in {"prefer-free", "free-only", "allow-paid", "no-paid"}:
            raise SupervisorValidationError("budget_policy is invalid")
        object.__setattr__(self, "confirmation_mode", confirmation)
        object.__setattr__(self, "budget_policy", budget_policy)
        object.__setattr__(self, "preferred_route", _identifier(self.preferred_route, "preferred_route", required=False))
        quality = str(self.min_quality_tier or "").strip().lower() or None
        if quality and quality not in QUALITY_ORDER:
            raise SupervisorValidationError("min_quality_tier is invalid")
        object.__setattr__(self, "min_quality_tier", quality)
        access = str(self.workspace_access or "none").strip().lower()
        if access not in WORKSPACE_ACCESS:
            raise SupervisorValidationError("workspace_access is invalid")
        object.__setattr__(self, "workspace_access", access)
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise SupervisorValidationError("depth is invalid")
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id", required=False))
        object.__setattr__(self, "context_refs", _safe_context(self.context_refs))
        object.__setattr__(self, "decision_key", _safe_question(self.decision_key, limit=240) if self.decision_key else None)
        object.__setattr__(self, "auto_dispatch", _strict_bool(self.auto_dispatch, "auto_dispatch"))
        object.__setattr__(self, "quota_consent", _strict_bool(self.quota_consent, "quota_consent"))
        object.__setattr__(self, "confirmed", _strict_bool(self.confirmed, "confirmed"))
        object.__setattr__(self, "metadata", _safe_context(self.metadata, budget=2_000) if isinstance(self.metadata, Mapping) else {})

    @classmethod
    def from_value(cls, value: Any) -> "DynamicRoutingRequest":
        if isinstance(value, cls):
            return value
        # Accept model-policy RoutingRequest-like objects without importing or
        # requiring that module, preserving runtime neutrality.
        if not isinstance(value, Mapping):
            raw = {name: getattr(value, name) for name in cls.__dataclass_fields__ if hasattr(value, name)}
            # ``model_policy.RoutingRequest`` uses ``task_text`` and
            # ``remaining_budget`` names; copy those optional fields when a
            # caller hands the policy object directly to the supervisor.
            for name in ("task_text", "task_stage", "remaining_budget", "trigger_event", "parent_turn_id"):
                if hasattr(value, name):
                    raw[name] = getattr(value, name)
            if not raw:
                raise SupervisorValidationError("routing request must be an object")
        else:
            raw = dict(value)
        aliases = {
            "session_id": "parent_session_id",
            "parentSessionId": "parent_session_id",
            "parentTurnId": "parent_turn_id",
            "taskKind": "task_kind",
            "triggerEvent": "trigger_event",
            "taskStage": "phase",
            "task_stage": "phase",
            "requiredCapabilities": "required_capabilities",
            "privacyConstraints": "privacy_constraints",
            "budgetRemaining": "budget_remaining",
            "remainingBudget": "budget_remaining",
            "budgetRemainingTokens": "budget_remaining",
            "latencyTargetMs": "latency_target_ms",
            "confirmationMode": "confirmation_mode",
            "budgetPolicy": "budget_policy",
            "preferredRoute": "preferred_route",
            "minQualityTier": "min_quality_tier",
            "workspaceAccess": "workspace_access",
            "decisionKey": "decision_key",
            "routeId": "route_id",
            "contextRefs": "context_refs",
            "autoDispatch": "auto_dispatch",
            "quotaConsent": "quota_consent",
            "approved": "confirmed",
            "routingApproved": "confirmed",
            "routing_approved": "confirmed",
        }
        for old, new in aliases.items():
            if new not in raw and old in raw:
                raw[new] = raw[old]
        if "question" not in raw:
            raw["question"] = raw.get("task_text") or raw.get("taskText") or ""
        if "parent_session_id" not in raw:
            raw["parent_session_id"] = ""
        for key in ("required_capabilities", "privacy_constraints"):
            if isinstance(raw.get(key), str):
                raw[key] = (raw[key],)
        return cls(**{key: item for key, item in raw.items() if key in cls.__dataclass_fields__})

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        value = {
            "schema": SUPERVISOR_SCHEMA,
            "parent_session_id": self.parent_session_id,
            "parent_turn_id": self.parent_turn_id,
            "task_kind": self.task_kind,
            "phase": self.phase,
            "task_stage": self.phase,
            "trigger_event": self.trigger_event,
            "risk": self.risk,
            "difficulty": self.difficulty,
            "required_capabilities": list(self.required_capabilities),
            "privacy_constraints": list(self.privacy_constraints),
            "budget_remaining": self.budget_remaining,
            "remaining_budget": self.remaining_budget,
            "budget_unit": self.budget_unit,
            "latency_target_ms": self.latency_target_ms,
            "confirmation_mode": self.confirmation_mode,
            "budget_policy": self.budget_policy,
            "preferred_route": self.preferred_route,
            "min_quality_tier": self.min_quality_tier,
            "workspace_access": self.workspace_access,
            "depth": self.depth,
            "decision_key": self.decision_key,
            "route_id": self.route_id,
            "auto_dispatch": self.auto_dispatch,
            "quota_consent": self.quota_consent,
            "confirmed": self.confirmed,
        }
        if include_content:
            value.update({"question": self.question, "context_refs": self.context_refs})
        return value

    def to_model_request(self) -> Any:
        """Convert to ``model_policy.RoutingRequest`` when that layer exists."""

        try:
            from ..model_policy import RoutingRequest

            return RoutingRequest(
                task_kind=self.task_kind,
                difficulty=self.difficulty,
                risk=self.risk,
                context_size=len(json.dumps(self.context_refs, ensure_ascii=False, default=str)),
                required_capabilities=self.required_capabilities,
                latency_target_ms=self.latency_target_ms,
                privacy_constraints=self.privacy_constraints,
                budget_policy=self.budget_policy,
                confirmation_mode=self.confirmation_mode,
                preferred_route=self.preferred_route,
                min_quality_tier=self.min_quality_tier,
                task_text=self.question,
            )
        except ImportError:
            return self


@dataclass(frozen=True, slots=True)
class DynamicSubtaskDispatch:
    """Dispatch contract that supports every worker kind, not just web."""

    dispatch_id: str
    parent_session_id: str
    route_id: str
    question: str
    worker_kind: str = "provider"
    parent_turn_id: str | None = None
    context_refs: Any = field(default_factory=dict)
    requested_capabilities: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    deadline_ms: int | None = None
    deadline_at: str | None = None
    workspace_access: str = "none"
    depth: int = 0
    continuation_of: str | None = None
    decision_key: str | None = None
    trigger_event: str | None = None
    side_effect: str = "none"
    runtime_id: str = "unknown"
    executor: str = "unknown"
    transport: str = "unknown"
    quota_consent: bool = False
    confirmed: bool = False
    budget_policy: str = "prefer-free"
    risk: str = "normal"
    difficulty: str = "auto"
    privacy_constraints: tuple[str, ...] = ()
    min_quality_tier: str | None = None
    budget_remaining: float | None = None
    role: str = "worker"
    consultation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _identifier(self.dispatch_id, "dispatch_id") or "")
        object.__setattr__(self, "parent_session_id", _identifier(self.parent_session_id, "parent_session_id") or "")
        object.__setattr__(self, "parent_turn_id", _identifier(self.parent_turn_id, "parent_turn_id", required=False))
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id") or "")
        object.__setattr__(self, "question", _safe_question(self.question))
        kind = str(self.worker_kind or "provider").strip().lower()
        if kind not in WORKER_KINDS:
            raise SupervisorValidationError("worker_kind is invalid")
        object.__setattr__(self, "worker_kind", kind)
        object.__setattr__(self, "context_refs", _safe_context(self.context_refs))
        capabilities = self.requested_capabilities or self.required_capabilities
        capabilities = tuple(_token(item, "requested_capability") for item in tuple(capabilities or ())[:24])
        object.__setattr__(self, "requested_capabilities", capabilities)
        object.__setattr__(self, "required_capabilities", capabilities)
        if self.deadline_ms is not None and (isinstance(self.deadline_ms, bool) or not isinstance(self.deadline_ms, int) or self.deadline_ms < 1 or self.deadline_ms > 3_600_000):
            raise SupervisorValidationError("deadline_ms is invalid")
        object.__setattr__(self, "deadline_at", _safe_timestamp(self.deadline_at, "deadline_at"))
        access = str(self.workspace_access or "none").strip().lower()
        if access not in WORKSPACE_ACCESS:
            raise SupervisorValidationError("workspace_access is invalid")
        object.__setattr__(self, "workspace_access", access)
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise SupervisorValidationError("depth is invalid")
        object.__setattr__(self, "depth", self.depth)
        object.__setattr__(self, "continuation_of", _identifier(self.continuation_of, "continuation_of", required=False))
        object.__setattr__(self, "decision_key", _safe_question(self.decision_key, limit=240) if self.decision_key else None)
        event = str(self.trigger_event or "").strip().lower() or None
        if event and event not in EVENT_BOUNDARIES:
            raise SupervisorValidationError("trigger_event is not a replan boundary")
        object.__setattr__(self, "trigger_event", event)
        side = str(self.side_effect or "none").strip().lower()
        if side not in SIDE_EFFECTS:
            raise SupervisorValidationError("side_effect is invalid")
        object.__setattr__(self, "side_effect", side)
        object.__setattr__(self, "runtime_id", _token(self.runtime_id, "runtime_id"))
        object.__setattr__(self, "executor", _token(self.executor, "executor"))
        object.__setattr__(self, "transport", _token(self.transport, "transport"))
        object.__setattr__(self, "quota_consent", _strict_bool(self.quota_consent, "quota_consent"))
        object.__setattr__(self, "confirmed", _strict_bool(self.confirmed, "confirmed"))
        budget_policy = _token(self.budget_policy, "budget_policy", default="prefer-free")
        if budget_policy not in {"prefer-free", "free-only", "allow-paid", "no-paid"}:
            raise SupervisorValidationError("budget_policy is invalid")
        object.__setattr__(self, "budget_policy", budget_policy)
        risk = str(self.risk or "normal").strip().lower()
        if risk not in {"low", "normal", "high", "critical"}:
            raise SupervisorValidationError("risk is invalid")
        object.__setattr__(self, "risk", risk)
        difficulty = str(self.difficulty or "auto").strip().lower()
        if difficulty not in {"auto", "trivial", "basic", "moderate", "complex", "critical"}:
            raise SupervisorValidationError("difficulty is invalid")
        object.__setattr__(self, "difficulty", difficulty)
        privacy = self.privacy_constraints
        if isinstance(privacy, str):
            privacy = (privacy,)
        object.__setattr__(self, "privacy_constraints", tuple(_token(item, "privacy_constraint") for item in tuple(privacy or ())[:24]))
        quality = str(self.min_quality_tier or "").strip().lower() or None
        if quality and quality not in QUALITY_ORDER:
            raise SupervisorValidationError("min_quality_tier is invalid")
        object.__setattr__(self, "min_quality_tier", quality)
        if self.budget_remaining is not None:
            if isinstance(self.budget_remaining, bool) or not isinstance(self.budget_remaining, (int, float)) or self.budget_remaining < 0:
                raise SupervisorValidationError("budget_remaining must be non-negative")
            object.__setattr__(self, "budget_remaining", float(self.budget_remaining))
        object.__setattr__(self, "role", sanitize_text(str(self.role or "worker"), limit=240))
        object.__setattr__(self, "consultation_id", _identifier(self.consultation_id, "consultation_id", required=False))
        object.__setattr__(self, "metadata", _safe_context(self.metadata, budget=2_000) if isinstance(self.metadata, Mapping) else {})

    @classmethod
    def from_value(cls, value: Any, *, route_id: str | None = None, worker_kind: str | None = None) -> "DynamicSubtaskDispatch":
        if isinstance(value, cls):
            return value
        # Legacy web dispatches are converted without losing their context.
        if hasattr(value, "to_dict") and not isinstance(value, Mapping):
            raw = {name: getattr(value, name) for name in ("dispatch_id", "parent_session_id", "parent_turn_id", "route_id", "question", "context_refs", "continuation_of", "role", "consultation_id", "deadline_at", "workspace_access", "required_capabilities", "depth") if hasattr(value, name)}
            raw["worker_kind"] = worker_kind or ("web" if getattr(value, "mode", "") in {"web-worker", "consultation-panel"} else "provider")
        elif isinstance(value, Mapping):
            raw = dict(value)
        else:
            raise SupervisorValidationError("subtask dispatch must be an object")
        aliases = {
            "dispatchId": "dispatch_id",
            "parentSessionId": "parent_session_id",
            "parentTurnId": "parent_turn_id",
            "routeId": "route_id",
            "workerKind": "worker_kind",
            "kind": "worker_kind",
            "contextRefs": "context_refs",
            "requestedCapabilities": "requested_capabilities",
            "requiredCapabilities": "requested_capabilities",
            "deadlineMs": "deadline_ms",
            "deadlineAt": "deadline_at",
            "workspaceAccess": "workspace_access",
            "decisionKey": "decision_key",
            "triggerEvent": "trigger_event",
            "sideEffect": "side_effect",
            "runtimeId": "runtime_id",
            "executorId": "executor",
            "quotaConsent": "quota_consent",
            "budgetPolicy": "budget_policy",
            "privacyConstraints": "privacy_constraints",
            "minQualityTier": "min_quality_tier",
            "consultationId": "consultation_id",
            # Bridges commonly call the user-facing field ``text`` or
            # ``prompt``.  Normalize it before validation so every worker
            # receives the same immutable question field.
            "text": "question",
            "prompt": "question",
        }
        for old, new in aliases.items():
            if new not in raw and old in raw:
                raw[new] = raw[old]
        if not raw.get("worker_kind") and raw.get("mode"):
            mode = str(raw.get("mode") or "").lower()
            raw["worker_kind"] = "web" if mode in {"web-worker", "consultation-panel", "web"} else mode.removesuffix("-worker")
        if route_id and not raw.get("route_id"):
            raw["route_id"] = route_id
        if worker_kind and not raw.get("worker_kind"):
            raw["worker_kind"] = worker_kind
        for key in ("requested_capabilities", "required_capabilities", "privacy_constraints"):
            if isinstance(raw.get(key), str):
                raw[key] = (raw[key],)
        raw.setdefault("dispatch_id", f"dispatch-{uuid4().hex[:16]}")
        raw.setdefault("worker_kind", "provider")
        return cls(**{key: item for key, item in raw.items() if key in cls.__dataclass_fields__})

    @property
    def mode(self) -> str:
        return "consultation-panel" if self.consultation_id else f"{self.worker_kind}-worker"

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        value = {
            "schema": SUPERVISOR_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "parent_session_id": self.parent_session_id,
            "parent_turn_id": self.parent_turn_id,
            "route_id": self.route_id,
            "worker_kind": self.worker_kind,
            "mode": self.mode,
            "requested_capabilities": list(self.requested_capabilities),
            "required_capabilities": list(self.required_capabilities),
            "deadline_ms": self.deadline_ms,
            "deadline": self.deadline_ms,
            "deadline_at": self.deadline_at,
            "workspace_access": self.workspace_access,
            "depth": self.depth,
            "continuation_of": self.continuation_of,
            "decision_key": self.decision_key,
            "trigger_event": self.trigger_event,
            "side_effect": self.side_effect,
            "runtime_id": self.runtime_id,
            "executor": self.executor,
            "transport": self.transport,
            "quota_consent": self.quota_consent,
            "confirmed": self.confirmed,
            "budget_policy": self.budget_policy,
            "risk": self.risk,
            "difficulty": self.difficulty,
            "privacy_constraints": list(self.privacy_constraints),
            "min_quality_tier": self.min_quality_tier,
            "budget_remaining": self.budget_remaining,
            "role": self.role,
            "consultation_id": self.consultation_id,
        }
        if include_content:
            value.update({"question": self.question, "context_refs": self.context_refs})
        return value


@dataclass(frozen=True, slots=True)
class DynamicSubtaskResult:
    dispatch_id: str
    route_id: str
    worker_kind: str
    status: str = "unknown"
    answer: str | None = None
    summary: str | None = None
    structured_result: Any = None
    concerns: tuple[str, ...] = ()
    confidence: float | None = None
    latency_ms: float | None = None
    error_code: str | None = None
    artifacts_metadata: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()
    retryable: bool = False
    possibly_sent: bool = False
    untrusted_external: bool = True
    runtime_id: str = "unknown"
    budget_impact: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispatch_id", _identifier(self.dispatch_id, "dispatch_id") or "")
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id") or "")
        object.__setattr__(self, "worker_kind", _token(self.worker_kind, "worker_kind", default="provider"))
        status = str(self.status or "unknown").strip().lower()
        if status not in RUN_STATES:
            status = "unknown"
        object.__setattr__(self, "status", status)
        if self.answer not in (None, ""):
            object.__setattr__(self, "answer", sanitize_text(str(self.answer), limit=32_000))
        else:
            object.__setattr__(self, "answer", None)
        object.__setattr__(self, "summary", _summary(self.summary or self.answer))
        object.__setattr__(self, "concerns", tuple(sanitize_text(str(item), limit=600) for item in tuple(self.concerns or ())[:8]))
        confidence = self.confidence
        if confidence is not None:
            try:
                number = float(confidence)
                confidence = round(max(0.0, min(1.0, number)), 3) if number == number else None
            except (TypeError, ValueError):
                confidence = None
        object.__setattr__(self, "confidence", confidence)
        if self.latency_ms is not None:
            try:
                object.__setattr__(self, "latency_ms", round(max(0.0, min(86_400_000, float(self.latency_ms))), 3))
            except (TypeError, ValueError):
                object.__setattr__(self, "latency_ms", None)
        object.__setattr__(self, "error_code", _token(self.error_code, "error_code", default="") if self.error_code else None)
        structured = self.structured_result
        if structured is not None:
            if isinstance(structured, tuple):
                structured = list(structured)
            if isinstance(structured, (Mapping, list)):
                structured = _safe_context(structured, budget=8_000)
            elif isinstance(structured, str):
                structured = sanitize_text(structured, limit=8_000)
            elif not isinstance(structured, (bool, int, float)):
                structured = None
        object.__setattr__(self, "structured_result", structured)
        artifacts: list[dict[str, Any]] = []
        raw_artifacts = self.artifacts_metadata or self.artifacts
        for item in tuple(raw_artifacts or ())[:16]:
            if isinstance(item, Mapping):
                safe = _safe_context(dict(item), budget=2_000)
                if isinstance(safe, dict):
                    # Artifact metadata may contain paths/hashes, but never
                    # file contents or opaque payload fields.
                    safe.pop("content", None)
                    safe.pop("body", None)
                    artifacts.append(safe)
        object.__setattr__(self, "artifacts_metadata", tuple(artifacts))
        object.__setattr__(self, "artifacts", tuple(artifacts))
        object.__setattr__(self, "runtime_id", _token(self.runtime_id, "runtime_id"))
        possibly_sent = _strict_bool(self.possibly_sent, "possibly_sent")
        retryable = _strict_bool(self.retryable, "retryable")
        object.__setattr__(self, "possibly_sent", possibly_sent)
        object.__setattr__(self, "retryable", retryable and not possibly_sent)
        object.__setattr__(self, "untrusted_external", _strict_bool(self.untrusted_external, "untrusted_external"))
        object.__setattr__(self, "budget_impact", _safe_context(self.budget_impact, budget=1_000) if isinstance(self.budget_impact, Mapping) else {})

    @classmethod
    def from_value(cls, value: Any, dispatch: DynamicSubtaskDispatch, *, latency_ms: float | None = None) -> "DynamicSubtaskResult":
        if isinstance(value, cls):
            if latency_ms is not None and value.latency_ms is None:
                return replace(value, latency_ms=latency_ms)
            return value
        if isinstance(value, LegacySubtaskResult):
            raw = value.to_dict()
        elif isinstance(value, Mapping):
            raw = dict(value)
        elif isinstance(value, str):
            raw = {"status": "completed", "answer": value}
        elif value is None:
            raw = {"status": "failed", "error_code": "empty-result"}
        else:
            raw = {"status": "completed", "structured_result": str(value)}
        artifacts = raw.get("artifacts_metadata", raw.get("artifacts", ()))
        possibly_sent_value = raw.get("possibly_sent", _MISSING)
        if possibly_sent_value is _MISSING:
            sent_state = raw.get("sent_state")
            possibly_sent_value = isinstance(sent_state, str) and sent_state in {"possibly-sent", "unknown"}
        untrusted_default = dispatch.worker_kind in {"web", "web-worker", "external-harness", "zcode"}
        return cls(
            dispatch_id=str(raw.get("dispatch_id") or dispatch.dispatch_id),
            route_id=str(raw.get("route_id") or dispatch.route_id),
            worker_kind=str(raw.get("worker_kind") or dispatch.worker_kind),
            status=str(raw.get("status") or "unknown"),
            answer=raw.get("answer") or raw.get("text"),
            summary=raw.get("summary"),
            structured_result=raw.get("structured_result"),
            concerns=tuple(raw.get("concerns") or ()),
            confidence=raw.get("confidence"),
            latency_ms=raw.get("latency_ms", latency_ms),
            error_code=raw.get("error_code"),
            artifacts_metadata=tuple(artifacts or ()) if isinstance(artifacts, (list, tuple)) else (),
            artifacts=tuple(artifacts or ()) if isinstance(artifacts, (list, tuple)) else (),
            retryable=_strict_bool(raw.get("retryable", False), "retryable"),
            possibly_sent=_strict_bool(possibly_sent_value, "possibly_sent"),
            untrusted_external=_strict_bool(raw.get("untrusted_external", untrusted_default), "untrusted_external"),
            runtime_id=str(raw.get("runtime_id") or "unknown"),
            budget_impact=raw.get("budget_impact") if isinstance(raw.get("budget_impact"), Mapping) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SUPERVISOR_SCHEMA,
            "dispatch_id": self.dispatch_id,
            "route_id": self.route_id,
            "worker_kind": self.worker_kind,
            "status": self.status,
            "answer": self.answer,
            "summary": self.summary,
            "structured_result": self.structured_result,
            "concerns": list(self.concerns),
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "artifacts_metadata": list(self.artifacts_metadata),
            "artifacts": list(self.artifacts),
            "retryable": self.retryable,
            "possibly_sent": self.possibly_sent,
            "untrusted_external": self.untrusted_external,
            "runtime_id": self.runtime_id,
            "budget_impact": self.budget_impact,
        }


class WorkerExecutor(Protocol):
    def __call__(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any: ...


class WorkerAdapter:
    """Small injectable worker wrapper used by all worker kinds."""

    kind = "provider"
    default_timeout_ms = 120_000

    def __init__(self, executor: Any = None, *, worker_id: str | None = None, timeout_ms: int | None = None, runtime_id: str = "unknown") -> None:
        self.executor = executor
        self.worker_id = _identifier(worker_id, "worker_id", required=False) or f"{self.kind}-{uuid4().hex[:10]}"
        self.timeout_ms = int(timeout_ms or self.default_timeout_ms)
        if self.timeout_ms < 1 or self.timeout_ms > 3_600_000:
            raise SupervisorValidationError("worker timeout_ms is invalid")
        self.runtime_id = _token(runtime_id, "runtime_id")

    def execute(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled"}
        target = self.executor
        if target is None:
            return {"status": "failed", "error_code": "worker-not-configured"}
        if not callable(target):
            target = getattr(target, "execute", None) or getattr(target, "run", None) or getattr(target, "dispatch", None)
        if not callable(target):
            return {"status": "failed", "error_code": "worker-not-callable"}
        return _call_with_supported_signature(target, dispatch, route, cancel_event)

    def descriptor(self) -> dict[str, Any]:
        return {"worker_id": self.worker_id, "kind": self.kind, "runtime_id": self.runtime_id, "timeout_ms": self.timeout_ms}


class ProviderWorker(WorkerAdapter):
    kind = "provider"
    default_timeout_ms = 120_000


class WebWorker(WorkerAdapter):
    kind = "web"
    default_timeout_ms = 300_000


class ChildAgentWorker(WorkerAdapter):
    kind = "child-agent"
    default_timeout_ms = 120_000


class NativeChildAgentWorker(ChildAgentWorker):
    kind = "native-child-agent"


class ExternalHarnessWorker(WorkerAdapter):
    kind = "external-harness"
    default_timeout_ms = 300_000


class DesktopAppWorker(WorkerAdapter):
    kind = "desktop-app"
    default_timeout_ms = 120_000


class WorkerRegistry:
    """Explicit worker and route binding registry.

    Registration is intentionally dependency-injected: no subprocess, DSH
    import, browser launch, or desktop discovery happens here.
    """

    def __init__(self) -> None:
        self._workers: dict[str, Any] = {}
        self._route_bindings: dict[str, str] = {}
        self._lock = threading.RLock()

    def register(self, worker_id: str | Any, worker: Any | None = None, *, kind: str | None = None, route_ids: Iterable[str] = ()) -> str:
        if worker is None and not isinstance(worker_id, str):
            worker = worker_id
            worker_id = getattr(worker, "worker_id", None)
        identifier = _identifier(worker_id, "worker_id", required=False) if worker_id is not None else None
        if not identifier:
            identifier = f"{getattr(worker, 'kind', kind or 'worker')}-{uuid4().hex[:10]}"
        if worker is None:
            worker = WorkerAdapter(worker_id=identifier, runtime_id="unknown")
        if kind and not hasattr(worker, "kind"):
            setattr(worker, "kind", _token(kind, "worker_kind"))
        with self._lock:
            self._workers[identifier] = worker
            for route_id in list(route_ids)[:64]:
                normalized = _identifier(route_id, "route_id", required=False)
                if normalized:
                    self._route_bindings[normalized] = identifier
            if len(self._workers) > 256:
                self._workers = dict(list(self._workers.items())[-256:])
        return identifier

    register_worker = register

    def unregister(self, worker_id: str) -> bool:
        identifier = _identifier(worker_id, "worker_id") or ""
        with self._lock:
            removed = self._workers.pop(identifier, None) is not None
            self._route_bindings = {route: worker for route, worker in self._route_bindings.items() if worker != identifier}
            return removed

    def bind(self, route_id: str, worker_id: str) -> None:
        route = _identifier(route_id, "route_id") or ""
        worker = _identifier(worker_id, "worker_id") or ""
        with self._lock:
            if worker not in self._workers:
                raise SupervisorError("worker is not registered")
            self._route_bindings[route] = worker

    bind_route = bind

    def register_route(self, route_id: str, worker_id: str | Any) -> None:
        """Compatibility spelling for plugins that register a route binding."""

        if not isinstance(worker_id, str):
            worker_id = self.register(worker_id)
        self.bind(route_id, worker_id)

    def resolve(self, route: RuntimeRouteDescriptor | Mapping[str, Any] | str, *, worker_kind: str | None = None) -> Any | None:
        descriptor = route if isinstance(route, RuntimeRouteDescriptor) else None
        route_id = descriptor.route_id if descriptor else (str(route) if isinstance(route, str) else str(route.get("route_id") or ""))
        executor_id = descriptor.executor if descriptor else None
        kind = worker_kind or (descriptor.kind if descriptor else None)
        with self._lock:
            candidate_ids = [self._route_bindings.get(route_id), executor_id, kind]
            for candidate in candidate_ids:
                if candidate and candidate in self._workers:
                    return self._workers[candidate]
            # A single worker of the requested kind is a convenient fixture
            # default, but never pick an arbitrary worker of another kind.
            for worker in self._workers.values():
                if kind and str(getattr(worker, "kind", "")).lower() == str(kind).lower():
                    return worker
        return None

    def get(self, worker_id: str) -> Any | None:
        identifier = _identifier(worker_id, "worker_id") or ""
        with self._lock:
            return self._workers.get(identifier)

    def catalog(self) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._workers.values())
        result: list[dict[str, Any]] = []
        for worker in values:
            if hasattr(worker, "descriptor") and callable(worker.descriptor):
                value = worker.descriptor()
            else:
                value = {
                    "worker_id": getattr(worker, "worker_id", None),
                    "kind": getattr(worker, "kind", "unknown"),
                    "runtime_id": getattr(worker, "runtime_id", "unknown"),
                    "timeout_ms": getattr(worker, "timeout_ms", None),
                }
            try:
                result.append(_safe_context(value, budget=1_000))
            except SupervisorValidationError:
                continue
        return result

    def close(self) -> None:
        with self._lock:
            values = list(self._workers.values())
        for worker in values:
            closer = getattr(worker, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    continue


@dataclass(slots=True)
class _Run:
    dispatch: DynamicSubtaskDispatch
    route: RuntimeRouteDescriptor
    worker: Any | None
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    completed_at: str | None = None
    latency_ms: float | None = None
    result: DynamicSubtaskResult | None = None
    error_code: str | None = None
    retryable: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future[Any] | None = None
    fingerprint: str = ""
    evidence_hashes: tuple[str, ...] = ()
    active_released: bool = False
    mailbox_acknowledged: bool = False
    finalized: bool = False
    terminal_event_emitted: bool = False


class DynamicRouteSupervisor:
    """Bounded turn-level scheduler for runtime-neutral workers."""

    def __init__(
        self,
        worker_registry: WorkerRegistry | None = None,
        *,
        runtime: Any = None,
        orchestrator: Any = None,
        routes: Iterable[Any] | Mapping[str, Any] | None = None,
        route_catalog: Iterable[Any] | Mapping[str, Any] | None = None,
        evidence_resolver: EvidenceResolver | None = None,
        model_router: Any = None,
        route_selector: Callable[[DynamicRoutingRequest, list[RuntimeRouteDescriptor]], Any] | None = None,
        storage: Any = None,
        metadata_sink: Callable[[dict[str, Any]], Any] | None = None,
        event_sink: Callable[[dict[str, Any]], Any] | None = None,
        logger: Any = None,
        max_concurrent: int = 3,
        max_dispatches_per_turn: int = 4,
        max_depth: int = 1,
        max_workers: int | None = None,
    ) -> None:
        self.worker_registry = worker_registry or WorkerRegistry()
        # Kept for observability/adapter metadata only.  The supervisor never
        # calls Harness-specific methods and therefore remains replaceable.
        self.runtime = runtime if runtime is not None else orchestrator
        self.evidence = evidence_resolver or EvidenceResolver()
        self.model_router = model_router
        self.route_selector = route_selector
        self.storage = storage
        self.metadata_sink = metadata_sink
        self.event_sink = event_sink
        self.logger = logger
        self.max_concurrent = max(1, min(int(max_workers if max_workers is not None else max_concurrent), 3))
        self.max_dispatches_per_turn = max(1, min(int(max_dispatches_per_turn), 4))
        self.max_depth = max(0, min(int(max_depth), 1))
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="sumika-route-supervisor")
        self._lock = threading.RLock()
        self._routes: dict[str, RuntimeRouteDescriptor] = {}
        # Keep the routability observed before a manual/foreign lease is
        # projected.  Without this small side table, releasing a lease would
        # leave the descriptor permanently non-routable after the first
        # ``manual`` update.
        self._base_routable: dict[str, bool] = {}
        self._runs: dict[str, _Run] = {}
        # Consultation metadata is kept in the same supervisor lifecycle as
        # its member dispatches.  The question/context remain in memory only;
        # persistence receives bounded member counters and hashes.
        self._consultations: dict[str, dict[str, Any]] = {}
        self._dedupe: dict[str, str] = {}
        self._turn_dispatch_counts: dict[tuple[str, str], int] = {}
        self._turn_active_counts: dict[tuple[str, str], int] = {}
        # A parent Harness reads completed worker results through this
        # volatile mailbox.  It is intentionally not reconstructed from
        # SQLite: a restart must never replay an external request.
        self._turn_requests: dict[tuple[str, str], DynamicRoutingRequest] = {}
        self._mailbox: dict[tuple[str, str], list[str]] = {}
        self._seen_events: list[str] = []
        self._closed = False
        initial_routes = routes if routes is not None else route_catalog
        if initial_routes:
            self.register_routes(initial_routes)

    # ---- route/evidence catalog -------------------------------------------------
    def register_route(self, route: Any, *, evidence: Iterable[Any] | None = None, worker: Any = None) -> RuntimeRouteDescriptor:
        descriptor = RuntimeRouteDescriptor.from_value(route)
        if evidence:
            items = self.evidence.add_many(evidence, route_id=descriptor.route_id)
            if not descriptor.evidence_refs:
                descriptor = replace(descriptor, evidence_refs=tuple(item.evidence_id for item in items[:16]))
        if worker is not None:
            worker_id = self.worker_registry.register(worker)
            if descriptor.executor in {"unknown", "web"}:
                descriptor = replace(descriptor, executor=worker_id)
            self.worker_registry.bind(descriptor.route_id, worker_id)
        with self._lock:
            if descriptor.occupancy in {"manual", "waiting"}:
                self._base_routable.setdefault(descriptor.route_id, bool(descriptor.routable))
            else:
                self._base_routable[descriptor.route_id] = bool(descriptor.routable)
            self._routes[descriptor.route_id] = descriptor
            if len(self._routes) > 512:
                self._routes = dict(list(self._routes.items())[-512:])
                retained = set(self._routes)
                self._base_routable = {
                    key: value for key, value in self._base_routable.items() if key in retained
                }
        return descriptor

    def register_routes(self, routes: Iterable[Any] | Mapping[str, Any]) -> list[RuntimeRouteDescriptor]:
        if callable(routes):
            routes = routes()
        values = routes.values() if isinstance(routes, Mapping) else routes
        result: list[RuntimeRouteDescriptor] = []
        for route in list(values)[:512]:
            result.append(self.register_route(route))
        return result

    def add_evidence(self, evidence: Any, *, route_id: str = "") -> DynamicRouteEvidence:
        return self.evidence.add(evidence, route_id=route_id)

    def catalog(self, *, include_unavailable: bool = True, include_evidence: bool = True, include_templates: bool | None = None) -> dict[str, Any]:
        del include_templates  # retained for compatibility with the web catalog RPC
        with self._lock:
            routes = list(self._routes.values())
        output: list[dict[str, Any]] = []
        for route in routes:
            if not include_unavailable and not route.available:
                continue
            refs = self.evidence.references(route.route_id, refs=route.evidence_refs) if include_evidence else []
            output.append(route.to_dict(evidence=refs))
        return {
            "schema": SUPERVISOR_SCHEMA,
            "routes": output,
            "workers": self.worker_registry.catalog(),
            "evidence_schema": ROUTE_EVIDENCE_SCHEMA,
            "limits": {
                "max_concurrent": self.max_concurrent,
                "max_dispatches_per_turn": self.max_dispatches_per_turn,
                "max_depth": self.max_depth,
            },
        }

    route_catalog = catalog
    list_routes = catalog

    def set_route_catalog(self, routes: Iterable[Any] | Mapping[str, Any]) -> list[RuntimeRouteDescriptor]:
        with self._lock:
            self._routes.clear()
            self._base_routable.clear()
        return self.register_routes(routes)

    def update_occupancy(self, profile_id: str, occupancy: str = "idle") -> dict[str, Any]:
        """Project a BrowserSkill/Profile lease into modern route entries.

        ``RouteCoordinator`` remains the owner of the actual BrowserSkill
        lease.  This method only updates the in-memory route projection so a
        modern consultation cannot race a manual takeover.  It is deliberately
        keyed by provider profile rather than by web adapter, because one
        provider may have multiple named profiles.
        """

        profile = _identifier(profile_id, "profile_id") or ""
        value = str(occupancy or "idle").strip().lower()
        if value not in {"idle", "agent", "manual", "waiting"}:
            raise SupervisorValidationError("route occupancy is invalid")
        changed = 0
        with self._lock:
            for route_id, route in list(self._routes.items()):
                if route.provider_profile_id != profile:
                    continue
                base = self._base_routable.get(route_id, bool(route.routable))
                routable = bool(base)
                reason = route.reason
                if value in {"manual", "waiting"} and base:
                    reason = "profile-occupied"
                elif reason == "profile-occupied":
                    reason = None
                self._routes[route_id] = replace(
                    route,
                    occupancy=value,
                    routable=routable,
                    reason=reason,
                )
                changed += 1
        return {
            "profile_id": profile,
            "occupancy": value,
            "updated_routes": changed,
        }

    # Naming used by a few adapter bridges.
    set_occupancy = update_occupancy

    def register_worker(self, worker_id: str | Any, worker: Any | None = None, **kwargs: Any) -> str:
        return self.worker_registry.register(worker_id, worker, **kwargs)

    # ---- event boundary / replanning -------------------------------------------
    def arm_turn(self, value: Any, *, replace: bool = False) -> dict[str, Any]:
        """Register explicit routing context for a future event boundary.

        Events alone are never allowed to invent a subtask.  A Harness may
        arm a turn with a validated request, then send a boundary event later;
        ``handle_event`` will consume that exact request once at the boundary.
        The request body remains memory-only.
        """

        if self._closed:
            raise SupervisorError("route supervisor is closed")
        request = DynamicRoutingRequest.from_value(value)
        key = self._turn_key(request.parent_session_id, request.parent_turn_id)
        with self._lock:
            existing = self._turn_requests.get(key)
            if existing is not None and not replace:
                return {
                    "schema": SUPERVISOR_SCHEMA,
                    "armed": False,
                    "reason": "turn-already-armed",
                    "parent_session_id": request.parent_session_id,
                    "parent_turn_id": request.parent_turn_id,
                    "request": existing.to_dict(),
                }
            self._turn_requests[key] = request
        self._emit(
            "route.turn.armed",
            {
                "parent_session_id": request.parent_session_id,
                "parent_turn_id": request.parent_turn_id,
                "trigger_event": request.trigger_event,
            },
        )
        return {
            "schema": SUPERVISOR_SCHEMA,
            "armed": True,
            "parent_session_id": request.parent_session_id,
            "parent_turn_id": request.parent_turn_id,
            "request": request.to_dict(),
        }

    def _event_parent_key(self, payload: Mapping[str, Any]) -> tuple[str, str] | None:
        """Extract IDs from common nested envelopes without guessing.

        A few Harness versions omit ``turnId`` on session-level notifications.
        In that case a session-level fallback is safe only when exactly one
        request is armed for the session.  If more than one candidate exists,
        returning ``None`` is intentional: dispatching to the wrong turn is
        worse than asking the parent Agent to provide an explicit ID.
        """

        def mappings(value: Any, depth: int = 0) -> list[Mapping[str, Any]]:
            if depth > 5:
                return []
            if not isinstance(value, Mapping):
                if isinstance(value, (list, tuple)):
                    result: list[Mapping[str, Any]] = []
                    for item in list(value)[:32]:
                        result.extend(mappings(item, depth + 1))
                    return result
                return []
            result = [value]
            for key in ("extensions", "event", "params", "data", "payload", "result"):
                nested = value.get(key)
                if isinstance(nested, (Mapping, list, tuple)):
                    result.extend(mappings(nested, depth + 1))
            return result

        rows = mappings(payload)

        def first(names: tuple[str, ...]) -> Any:
            for row in rows:
                for name in names:
                    value = row.get(name)
                    if value not in (None, ""):
                        return value
            return None

        session = first((
            "parent_session_id", "parentSessionId", "session_id", "sessionId",
            "thread_id", "threadId",
        ))
        turn = first(("parent_turn_id", "parentTurnId", "turn_id", "turnId"))
        if session in (None, ""):
            return None
        try:
            session_id = _identifier(session, "parent_session_id") or ""
            turn_id = _identifier(turn, "parent_turn_id", required=False)
        except SupervisorValidationError:
            return None
        if turn_id:
            return self._turn_key(session_id, turn_id)
        with self._lock:
            candidates = [key for key in self._turn_requests if key[0] == session_id]
        # Prefer an explicitly session-scoped request if one was armed.
        session_key = self._turn_key(session_id, None)
        if session_key in candidates:
            return session_key
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _event_type(payload: Mapping[str, Any]) -> str:
        """Find a boundary marker in a normalized or nested event envelope."""

        def walk(value: Any, depth: int = 0) -> list[Mapping[str, Any]]:
            if depth > 5:
                return []
            if not isinstance(value, Mapping):
                if isinstance(value, (list, tuple)):
                    result: list[Mapping[str, Any]] = []
                    for item in list(value)[:32]:
                        result.extend(walk(item, depth + 1))
                    return result
                return []
            result = [value]
            for key in ("extensions", "event", "params", "data", "payload", "result"):
                nested = value.get(key)
                if isinstance(nested, (Mapping, list, tuple)):
                    result.extend(walk(nested, depth + 1))
            return result

        def normalize(value: Any) -> str:
            return str(value or "").strip().lower().replace("/", ".").replace("_", ".").replace("-", ".")

        explicit: list[str] = []
        states: list[str] = []
        rows = walk(payload)
        for row in rows:
            for key in ("event_type", "type", "method", "name"):
                value = normalize(row.get(key))
                if value:
                    explicit.append(value)
            row_marker = normalize(row.get("event_type") or row.get("type") or row.get("method") or row.get("name"))
            if "turn" in row_marker:
                for key in ("state", "status"):
                    value = normalize(row.get(key))
                    if value:
                        states.append(value)
            turn = row.get("turn")
            if isinstance(turn, Mapping):
                for key in ("type", "event_type", "method"):
                    value = normalize(turn.get(key))
                    if value:
                        explicit.append(value)
                for key in ("state", "status"):
                    value = normalize(turn.get(key))
                    if value:
                        states.append(value)
        if any(value in {"turn.failed", "turn.fail", "turn.error", "turn.failure", "model.request.failed", "runtime.error", "turn.aborted"} or "model.request.failed" in value for value in explicit) or any(value in {"failed", "error", "failure"} for value in states):
            return "turn.failed"
        if any(value in {"turn.cancelled", "turn.canceled", "turn.cancel", "turn.stopped", "turn.interrupted", "turn.aborted"} for value in explicit) or any(value in {"cancelled", "canceled", "stopped", "interrupted", "aborted"} for value in states):
            return "turn.cancelled"
        if any(value in {"turn.started", "turn.start"} for value in explicit):
            return "turn.started"
        if any(value in {"turn.completed", "turn.complete", "turn.end", "turn.ended", "turn.success"} for value in explicit):
            return "turn.completed"
        if any(value in {"tool.completed", "tool.result"} for value in explicit):
            return "tool.completed"
        if any(value in {"approval.resolved", "approval.resolve"} for value in explicit):
            return "approval.resolved"
        return ""

    @staticmethod
    def _event_id(payload: Mapping[str, Any]) -> str:
        """Extract an event identity without treating arbitrary result IDs as events.

        Harness adapters use a few different envelopes.  ``event_id`` and
        ``eventId`` are explicit wherever they occur in a known envelope;
        bare ``id`` is accepted only on an ``event`` object or a mapping that
        carries an explicit boundary marker.  In particular, IDs under
        ``result`` are user payload and must not participate in event
        de-duplication.
        """

        def normalize(value: Any) -> str:
            return str(value or "").strip().lower().replace("/", ".").replace("_", ".").replace("-", ".")

        boundary_markers = {
            "turn.started", "turn.start", "turn.completed", "turn.complete",
            "turn.end", "turn.ended", "turn.success", "turn.failed", "turn.fail",
            "turn.error", "turn.failure", "turn.cancelled", "turn.canceled",
            "turn.cancel", "turn.stopped", "turn.interrupted", "turn.aborted",
            "tool.completed", "tool.result", "approval.resolved", "approval.resolve",
        }

        def valid(value: Any) -> str | None:
            candidate = str(value or "").strip()
            if not candidate or len(candidate) > 240 or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
                return None
            return candidate

        # ``result`` is intentionally absent from this traversal.  A result
        # may contain arbitrary application objects whose ``id`` has no
        # relationship to the transport event.
        queue: list[tuple[Mapping[str, Any], tuple[str, ...]]] = [(payload, ())]
        while queue:
            row, path = queue.pop(0)
            for key in ("event_id", "eventId"):
                found = valid(row.get(key))
                if found:
                    return found

            markers = {
                normalize(row.get(key))
                for key in ("event_type", "type", "method", "name")
                if row.get(key) not in (None, "")
            }
            is_event_object = path and path[-1] == "event"
            if is_event_object or markers.intersection(boundary_markers):
                found = valid(row.get("id"))
                if found:
                    return found

            for key in ("extensions", "event", "params", "data", "payload"):
                nested = row.get(key)
                if isinstance(nested, Mapping):
                    queue.append((nested, path + (key,)))
                elif isinstance(nested, (list, tuple)):
                    queue.extend(
                        (item, path + (key,))
                        for item in list(nested)[:32]
                        if isinstance(item, Mapping)
                    )
        return ""

    def handle_event(self, event: Mapping[str, Any] | Any, request: Any = None, *, dispatch_selected: bool | None = None) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            event_type = str(getattr(event, "event_type", getattr(event, "type", "")) or "").strip().lower()
            event_id = str(getattr(event, "event_id", getattr(event, "eventId", "")) or "")
            payload = {"event_type": event_type, "event_id": event_id}
        else:
            payload = dict(event)
            event_type = self._event_type(payload)
            event_id = self._event_id(payload)
        if event_type not in EVENT_BOUNDARIES:
            return {"schema": SUPERVISOR_SCHEMA, "accepted": False, "replanned": False, "reason": "not-event-boundary", "event_type": event_type or None}
        if event_id:
            with self._lock:
                if event_id in self._seen_events:
                    return {"schema": SUPERVISOR_SCHEMA, "accepted": True, "replanned": False, "duplicate": True, "event_type": event_type}
                self._seen_events.append(event_id)
                if len(self._seen_events) > 512:
                    self._seen_events = self._seen_events[-512:]
        armed_key: tuple[str, str] | None = None
        request_supplied = request is not None
        if request is None:
            request = payload.get("routing_request") or payload.get("routingRequest") or payload.get("route_request") or payload.get("routeRequest")
            request_supplied = request is not None
        if request is None:
            armed_key = self._event_parent_key(payload)
            if armed_key is not None:
                with self._lock:
                    request = self._turn_requests.get(armed_key)
                request_supplied = request is not None
        if request is None:
            self._emit("route.replan.boundary", {"event_type": event_type})
            return {"schema": SUPERVISOR_SCHEMA, "accepted": True, "replanned": False, "reason": "no-routing-request", "event_type": event_type}
        try:
            requested_event = DynamicRoutingRequest.from_value(request).trigger_event
        except SupervisorValidationError:
            requested_event = None
        if requested_event and requested_event != event_type:
            return {
                "schema": SUPERVISOR_SCHEMA,
                "accepted": True,
                "replanned": False,
                "reason": "waiting-for-trigger-event",
                "event_type": event_type,
                "trigger_event": requested_event,
            }
        result = self.replan(request, trigger_event=event_type, dispatch_selected=dispatch_selected)
        # Event-driven requests are one-shot.  ``replan`` stores a request so
        # callers can use it directly as a future arm, but ``handle_event``
        # has already consumed the current boundary and must not replay the
        # same dispatch on a later terminal notification.
        if request_supplied:
            try:
                armed_request = DynamicRoutingRequest.from_value(request)
                key = armed_key or self._turn_key(armed_request.parent_session_id, armed_request.parent_turn_id)
            except SupervisorValidationError:
                key = armed_key
            if key is not None:
                with self._lock:
                    self._turn_requests.pop(key, None)
        return result

    on_event = handle_event
    ingest_event = handle_event

    def replan(
        self,
        request: Any = None,
        *args: Any,
        trigger_event: str | None = None,
        event: Mapping[str, Any] | Any | None = None,
        routing_request: Any = None,
        dispatch_selected: bool | None = None,
    ) -> dict[str, Any]:
        # Accept both ``replan(request, trigger_event=...)`` and the natural
        # event-first form ``replan(event, request)`` used by some bridges.
        if routing_request is not None:
            request = routing_request
        if args:
            if isinstance(request, Mapping) and any(key in request for key in ("event_type", "type", "method")):
                event = request
                request = args[0]
            elif request is None:
                request = args[0]
        if event is not None:
            if isinstance(event, Mapping):
                trigger_event = trigger_event or str(event.get("event_type") or event.get("type") or event.get("method") or "").strip().lower() or None
                if request is None:
                    request = event.get("routing_request") or event.get("routingRequest") or event.get("route_request") or event.get("routeRequest")
            else:
                trigger_event = trigger_event or str(getattr(event, "event_type", getattr(event, "type", "")) or "").strip().lower() or None
        if request is None:
            raise SupervisorValidationError("routing request is required")
        routing = DynamicRoutingRequest.from_value(request)
        event = trigger_event or routing.trigger_event
        if event and event not in EVENT_BOUNDARIES:
            raise SupervisorValidationError("replan requires an event boundary")
        if event and routing.trigger_event != event:
            routing = replace(routing, trigger_event=event)
        # ``replan`` is itself an explicit semantic request, so it may arm
        # the same turn for a subsequent boundary without consulting logs.
        with self._lock:
            self._turn_requests[self._turn_key(routing.parent_session_id, routing.parent_turn_id)] = routing
        candidates, rejected = self._eligible_routes(routing)
        if not candidates:
            result = {
                "schema": SUPERVISOR_SCHEMA,
                "accepted": True,
                "replanned": True,
                "status": "no-compatible-route",
                "trigger_event": event,
                "selected_route": None,
                "alternatives": [],
                "reason_codes": ["no_compatible_route", *[f"{key}:{value}" for key, value in sorted(rejected.items())]],
                "requires_confirmation": True,
                "quality_gate": {"passed": False},
                "budget_impact": {"remaining": routing.budget_remaining},
                "replan_reason": "no-compatible-route",
                "dispatch": None,
            }
            self._emit("route.replanned", {"status": result["status"], "trigger_event": event, "reason_codes": result["reason_codes"]})
            return result
        ordered = self._sort_candidates(candidates, routing)
        ordered = self._apply_selector(routing, ordered)
        selected = ordered[0]
        alternatives = [item.to_dict() for item in ordered[1:8]]
        needs_confirmation, reasons = self._confirmation_needed(selected, routing)
        result: dict[str, Any] = {
            "schema": SUPERVISOR_SCHEMA,
            "accepted": True,
            "replanned": True,
            "status": "needs-confirmation" if needs_confirmation else "recommended",
            "trigger_event": event,
            "selected_route": selected.route_id,
            "selected_worker": self._worker_kind(selected),
            "selected_entry": selected.to_dict(evidence=self.evidence.references(selected.route_id, refs=selected.evidence_refs)),
            "alternatives": alternatives,
            "reason_codes": reasons,
            "requires_confirmation": needs_confirmation,
            "quality_gate": {"passed": True, "selected": selected.quality_tier},
            "budget_impact": {"remaining": routing.budget_remaining, "estimated": selected.metadata.get("estimated_cost") if isinstance(selected.metadata, Mapping) else None},
            "replan_reason": "event-boundary" if event else "explicit-request",
            "dispatch": None,
        }
        should_dispatch = routing.auto_dispatch if dispatch_selected is None else bool(dispatch_selected)
        if should_dispatch and not needs_confirmation:
            dispatch = DynamicSubtaskDispatch(
                dispatch_id=f"dispatch-{uuid4().hex[:16]}",
                parent_session_id=routing.parent_session_id,
                parent_turn_id=routing.parent_turn_id,
                route_id=selected.route_id,
                question=routing.question,
                worker_kind=self._worker_kind(selected),
                context_refs=routing.context_refs,
                requested_capabilities=routing.required_capabilities,
                privacy_constraints=routing.privacy_constraints,
                min_quality_tier=routing.min_quality_tier,
                difficulty=routing.difficulty,
                workspace_access=routing.workspace_access,
                depth=routing.depth,
                decision_key=routing.decision_key,
                trigger_event=event,
                side_effect=selected.side_effect,
                budget_remaining=routing.budget_remaining,
                quota_consent=routing.quota_consent,
                confirmed=routing.confirmed,
                budget_policy=routing.budget_policy,
                risk=routing.risk,
                runtime_id=selected.runtime_id,
                executor=selected.executor,
                transport=selected.transport,
                metadata=routing.metadata,
            )
            result["dispatch"] = self.dispatch(dispatch, wait=False)
            result["status"] = "dispatched" if result["dispatch"].get("accepted") else result["dispatch"].get("status", "failed")
        self._emit("route.replanned", {"status": result["status"], "trigger_event": event, "selected_route": selected.route_id, "requires_confirmation": needs_confirmation})
        return result

    def _apply_selector(self, request: DynamicRoutingRequest, candidates: list[RuntimeRouteDescriptor]) -> list[RuntimeRouteDescriptor]:
        """Apply an optional policy selector without making semantic choices."""

        selector = self.route_selector
        if callable(selector):
            try:
                selected = selector(request, list(candidates))
                if isinstance(selected, RuntimeRouteDescriptor):
                    return [selected, *[item for item in candidates if item.route_id != selected.route_id]]
                if isinstance(selected, str):
                    match = next((item for item in candidates if item.route_id == selected), None)
                    if match:
                        return [match, *[item for item in candidates if item.route_id != match.route_id]]
                if isinstance(selected, (list, tuple)):
                    by_id = {item.route_id: item for item in candidates}
                    ordered = [by_id[item.route_id] if isinstance(item, RuntimeRouteDescriptor) else by_id[str(item)] for item in selected if (isinstance(item, RuntimeRouteDescriptor) and item.route_id in by_id) or str(item) in by_id]
                    ordered.extend(item for item in candidates if item not in ordered)
                    if ordered:
                        return ordered
            except Exception as exc:
                self._log("debug", "route selector unavailable", exc)
        router = self.model_router
        decide = getattr(router, "decide", None) if router is not None else None
        if callable(decide):
            # A ModelRouter can participate when descriptors carry a
            # ``model_entry`` projection.  If they do not, leave deterministic
            # local ordering intact rather than inventing model metadata.
            entries = []
            by_route: dict[str, RuntimeRouteDescriptor] = {}
            try:
                from ..model_policy import ModelCatalogEntry

                for item in candidates:
                    raw = item.metadata.get("model_entry") if isinstance(item.metadata, Mapping) else None
                    if isinstance(raw, ModelCatalogEntry):
                        entry = raw
                    elif isinstance(raw, Mapping):
                        entry = ModelCatalogEntry(**{key: value for key, value in raw.items() if key in ModelCatalogEntry.__dataclass_fields__})
                    else:
                        continue
                    entries.append(entry)
                    by_route[entry.route_id] = item
                if entries:
                    decision = decide(request.to_model_request(), entries)
                    selected_route = getattr(decision, "selected_route", None) or (decision.get("selected_route") if isinstance(decision, Mapping) else None)
                    if selected_route in by_route:
                        selected = by_route[selected_route]
                        return [selected, *[item for item in candidates if item.route_id != selected.route_id]]
            except Exception as exc:
                self._log("debug", "model router unavailable", exc)
        return candidates

    replan_at_boundary = replan

    def _eligible_routes(self, request: DynamicRoutingRequest) -> tuple[list[RuntimeRouteDescriptor], dict[str, int]]:
        with self._lock:
            values = list(self._routes.values())
        rejected: dict[str, int] = {}

        def reject(code: str) -> None:
            rejected[code] = rejected.get(code, 0) + 1

        selected: list[RuntimeRouteDescriptor] = []
        for route in values:
            if request.route_id and route.route_id != request.route_id:
                reject("route_preference")
                continue
            # Desktop routes represent an application control surface, not a
            # general-purpose model.  They may only enter an automatic
            # recommendation when the Agent explicitly asks for desktop
            # capability or names the route.  This prevents an ordinary chat
            # request from being sorted onto a local UI adapter merely because
            # it is cheap and healthy.
            is_desktop = (
                route.kind in {"desktop-app", "desktop-automation"}
                or route.source_kind == "desktop-automation"
                or route.executor == "desktop-automation"
                or route.runtime_id == "desktop"
            )
            if is_desktop and not (
                request.route_id == route.route_id
                or request.preferred_route == route.route_id
                or "desktop" in {item.lower() for item in request.required_capabilities}
            ):
                reject("desktop_route_requires_explicit_request")
                continue
            if not route.available:
                reject("route_not_ready")
                continue
            compatibility_error = self._route_compatibility(
                route,
                required_capabilities=request.required_capabilities,
                privacy_constraints=request.privacy_constraints,
                difficulty=request.difficulty,
                risk=request.risk,
                min_quality_tier=request.min_quality_tier,
                explicit_route=request.route_id == route.route_id or request.preferred_route == route.route_id,
            )
            if compatibility_error:
                reject(compatibility_error)
                continue
            if request.budget_policy in {"free-only", "no-paid"} and route.cost_class not in {"free-limited", "local"}:
                reject("paid_disallowed")
                continue
            estimate = route.metadata.get("estimated_cost") if isinstance(route.metadata, Mapping) else None
            if request.budget_remaining is not None and isinstance(estimate, (int, float)) and not isinstance(estimate, bool) and float(estimate) > request.budget_remaining:
                reject("budget_exceeded")
                continue
            selected.append(route)
        return selected, rejected

    @staticmethod
    def _worker_kind(route: RuntimeRouteDescriptor) -> str:
        kind = route.kind.lower()
        if kind in {"web", "web-worker"} or route.source_kind == "web-chat":
            return "web"
        if kind in {"zcode", "external-harness"} or route.runtime_id == "zcode":
            return "external-harness"
        if kind in {"child-agent", "native-child-agent", "subagent"}:
            return "native-child-agent"
        if kind in {"desktop-app", "desktop-automation"}:
            return "desktop-app"
        return "provider"

    @staticmethod
    def _sort_candidates(candidates: list[RuntimeRouteDescriptor], request: DynamicRoutingRequest) -> list[RuntimeRouteDescriptor]:
        preferred = request.preferred_route
        return sorted(
            candidates,
            key=lambda route: (
                0 if preferred and route.route_id == preferred else 1,
                COST_ORDER.get(route.cost_class, 4),
                0 if route.quota_state in {"available", "not-applicable"} else 1,
                -QUALITY_ORDER.get(route.quality_tier, 0),
                route.route_id,
            ),
        )

    @staticmethod
    def _required_quality(*, difficulty: str = "auto", risk: str = "normal", min_quality_tier: str | None = None) -> str:
        """Return the same conservative quality floor for every dispatch path."""

        if min_quality_tier:
            required = min_quality_tier
        else:
            required = {
                "trivial": "basic",
                "basic": "basic",
                "moderate": "standard",
                "complex": "strong",
                "critical": "premium",
            }.get(difficulty, "standard")
        if risk in {"high", "critical"} and QUALITY_ORDER.get(required, 0) < QUALITY_ORDER["strong"]:
            required = "strong"
        return required

    def _route_compatibility(
        self,
        route: RuntimeRouteDescriptor,
        *,
        required_capabilities: Iterable[str] = (),
        privacy_constraints: Iterable[str] = (),
        difficulty: str = "auto",
        risk: str = "normal",
        min_quality_tier: str | None = None,
        explicit_route: bool = False,
    ) -> str | None:
        """Apply capability, privacy, health, quality, and evidence gates.

        The returned reason uses the catalog's stable underscore spelling.  The
        direct dispatch API converts it to its historical hyphenated error code.
        Keeping this in one helper prevents a hand-built dispatch from bypassing
        gates that are applied during ``replan``.
        """

        if not set(required_capabilities).issubset(set(route.capabilities)):
            return "missing_capability"
        privacy = {str(item).strip().lower() for item in privacy_constraints}
        if ("local-only" in privacy or "disallow-cloud" in privacy) and route.processing_location != "local":
            return "privacy_constraint"
        if "cloud-only" in privacy and route.processing_location == "local":
            return "privacy_constraint"
        if "no-browser" in privacy and route.requires_browser:
            return "privacy_constraint"
        if "no-third-party" in privacy and route.source_kind not in {"builtin", "local", "provider"}:
            return "privacy_constraint"
        if route.auth_state not in {"authorized", "not-required", "unknown"}:
            return "auth_not_ready"
        if route.health_state not in {"healthy", "ready", "available", "unknown"}:
            return "health_not_ready"
        if route.quota_state in {"exhausted", "expired", "blocked", "needs-auth"}:
            return f"quota_{route.quota_state}"

        required_quality = self._required_quality(
            difficulty=difficulty,
            risk=risk,
            min_quality_tier=min_quality_tier,
        )
        if QUALITY_ORDER.get(route.quality_tier, 0) < QUALITY_ORDER.get(required_quality, 0):
            # An explicitly selected route with unknown quality is retained for
            # backward compatibility, but it is never an automatic candidate.
            if not (explicit_route and route.quality_tier == "unknown"):
                return "quality_gate"
        if risk in {"high", "critical"}:
            evidence = self.evidence.resolve(route.route_id, purpose="capability", refs=route.evidence_refs)
            if evidence is None or evidence.effective_type not in {"smoke", "fixed-smoke", "real-run", "repeated-real-run"}:
                return "evidence_insufficient"
        return None

    @staticmethod
    def _confirmation_needed(route: RuntimeRouteDescriptor, request: DynamicRoutingRequest) -> tuple[bool, list[str]]:
        reasons = ["safety_and_capability_gates_passed"]
        needs = request.confirmation_mode != "automatic" and not request.confirmed
        if route.requires_confirmation:
            needs = not request.confirmed
            reasons.append("route_requires_confirmation")
        cost_consent = route.quota_consent in {"granted", "authorized", "approved"} or request.quota_consent
        if route.cost_class in {"paid-low", "paid-high"} and not request.confirmed:
            needs = True
            reasons.append("cost_or_quota_confirmation_required")
        if route.cost_class == "unknown" and not cost_consent and not request.confirmed:
            needs = True
            reasons.append("cost_or_quota_confirmation_required")
        if route.quota_state == "unknown" and not cost_consent and not request.confirmed:
            needs = True
            reasons.append("unknown_quota_consent_required")
        if route.side_effect in {"write", "external"} and not request.confirmed:
            needs = True
            reasons.append("side_effect_confirmation_required")
        if route.requires_browser:
            reasons.append("browser_authorization_required")
        return needs, reasons

    # ---- dispatch lifecycle -----------------------------------------------------
    @staticmethod
    def _hydrate_dispatch_metadata(
        dispatch: DynamicSubtaskDispatch,
        route: RuntimeRouteDescriptor,
    ) -> tuple[DynamicSubtaskDispatch | None, str | None]:
        """Fill omitted route metadata and reject explicit contradictions.

        RPC callers commonly provide only a ``route_id``.  The worker still
        needs the selected runtime, executor and transport in its receipt, so
        the neutral descriptor supplies values that are explicitly omitted
        (the contract's ``unknown`` defaults).  A caller-provided conflicting
        value is rejected instead of being silently overwritten; this keeps
        safety/audit metadata truthful and fail-closed.
        """

        updates: dict[str, Any] = {}
        mismatches: list[str] = []
        for field_name in ("runtime_id", "executor", "transport"):
            actual = str(getattr(dispatch, field_name, "") or "").strip().lower()
            expected = str(getattr(route, field_name, "") or "").strip().lower()
            if actual in {"", "unknown"}:
                if expected not in {"", "unknown"}:
                    updates[field_name] = expected
            elif expected not in {"", "unknown"} and actual != expected:
                mismatches.append(field_name)

        # ``none`` is the dispatch default, not permission to downgrade a
        # route declared as write/external.  Upgrade the omitted default so
        # the existing workspace and approval gates remain effective.
        actual_side_effect = str(dispatch.side_effect or "none").strip().lower()
        expected_side_effect = str(route.side_effect or "none").strip().lower()
        if actual_side_effect == "none":
            if expected_side_effect != "none":
                updates["side_effect"] = expected_side_effect
        elif expected_side_effect != "none" and actual_side_effect != expected_side_effect:
            mismatches.append("side_effect")

        if mismatches:
            return None, "route-metadata-mismatch"
        return replace(dispatch, **updates) if updates else dispatch, None

    def dispatch(self, value: Any, *, route_id: str | None = None, wait: bool = False, timeout: float | None = None) -> dict[str, Any]:
        if self._closed:
            raise SupervisorError("route supervisor is closed")
        dispatch = DynamicSubtaskDispatch.from_value(value, route_id=route_id)
        with self._lock:
            route = self._routes.get(dispatch.route_id)
        if route is None:
            return self._rejected_dispatch(dispatch, "route-not-found")
        if dispatch.worker_kind == "provider" and route.kind.lower() not in {"provider", "model", "api"}:
            dispatch = replace(dispatch, worker_kind=self._worker_kind(route))
        dispatch, metadata_error = self._hydrate_dispatch_metadata(dispatch, route)
        if metadata_error:
            # Keep the caller's original projection in the rejection so an
            # integration can see which supplied metadata was inconsistent.
            return self._rejected_dispatch(dispatch or DynamicSubtaskDispatch.from_value(value, route_id=route.route_id), metadata_error)
        if dispatch.depth > self.max_depth:
            return self._rejected_dispatch(dispatch, "max-depth")
        compatibility_error = self._route_compatibility(
            route,
            required_capabilities=dispatch.required_capabilities,
            privacy_constraints=dispatch.privacy_constraints,
            difficulty=dispatch.difficulty,
            risk=dispatch.risk,
            min_quality_tier=dispatch.min_quality_tier,
            explicit_route=True,
        )
        if compatibility_error:
            return self._rejected_dispatch(dispatch, compatibility_error.replace("_", "-"))
        if route.occupancy in {"manual", "waiting"}:
            return self._rejected_dispatch(dispatch, "route-occupied", status="waiting-human")
        # Dispatch is also a public boundary (not only ``replan``), so apply
        # the same hard cost/consent gates when a Harness submits a hand-built
        # request.  A caller can proceed only after carrying an explicit
        # confirmation or profile-level quota consent.
        if dispatch.budget_policy in {"free-only", "no-paid"} and route.cost_class not in {"free-limited", "local"}:
            return self._rejected_dispatch(dispatch, "paid-disallowed")
        estimate = route.metadata.get("estimated_cost") if isinstance(route.metadata, Mapping) else None
        if dispatch.budget_remaining is not None and isinstance(estimate, (int, float)) and not isinstance(estimate, bool) and float(estimate) > dispatch.budget_remaining:
            return self._rejected_dispatch(dispatch, "budget-exceeded")
        # Unknown cost is safe to run only after the route/profile has an
        # explicit quota/usage consent.  This preserves the no-silent-paid
        # rule while allowing a user-approved web or client subscription
        # route to run without a confirmation dialog on every turn.
        cost_consent = route.quota_consent in {"granted", "authorized", "approved"} or dispatch.quota_consent
        if route.cost_class in {"paid-low", "paid-high"} and not dispatch.confirmed:
            return self._rejected_dispatch(dispatch, "confirmation-required", status="needs-confirmation")
        if route.cost_class == "unknown" and not cost_consent and not dispatch.confirmed:
            return self._rejected_dispatch(dispatch, "confirmation-required", status="needs-confirmation")
        if route.quota_state == "unknown" and not cost_consent and not dispatch.confirmed:
            return self._rejected_dispatch(dispatch, "unknown-quota-consent-required", status="needs-confirmation")
        if (route.requires_confirmation or route.side_effect in {"write", "external"}) and not dispatch.confirmed:
            return self._rejected_dispatch(dispatch, "confirmation-required", status="needs-confirmation")
        turn_key = self._turn_key(dispatch.parent_session_id, dispatch.parent_turn_id)
        with self._lock:
            parent_run = self._runs.get(dispatch.continuation_of or "")
            if parent_run is not None and dispatch.depth <= parent_run.dispatch.depth:
                # A nested continuation must move one level deeper; a plain
                # retry keeps the original depth and is handled below.
                if dispatch.continuation_of and dispatch.continuation_of != parent_run.dispatch.dispatch_id:
                    return self._rejected_dispatch(dispatch, "invalid-depth")
            fingerprint = self._fingerprint(dispatch)
            existing_id = self._dedupe.get(fingerprint)
            if existing_id:
                return {**self.status(existing_id), "accepted": True, "deduplicated": True}
            count = self._turn_dispatch_counts.get(turn_key, 0)
            active = self._turn_active_counts.get(turn_key, 0)
            if count >= self.max_dispatches_per_turn:
                return self._rejected_dispatch(dispatch, "max-dispatches-per-turn")
            if active >= self.max_concurrent:
                return self._rejected_dispatch(dispatch, "max-concurrent-workers")
            if dispatch.workspace_access != "none" and dispatch.side_effect in {"write", "external"} and dispatch.workspace_access != "isolated-worktree":
                return self._rejected_dispatch(dispatch, "workspace-access-required")
        worker = self.worker_registry.resolve(route, worker_kind=dispatch.worker_kind)
        if worker is None:
            return self._rejected_dispatch(dispatch, "worker-not-registered")
        if not route.available:
            return self._rejected_dispatch(dispatch, "route-not-ready")
        fingerprint = self._fingerprint(dispatch)
        record = _Run(dispatch=dispatch, route=route, worker=worker, fingerprint=fingerprint, evidence_hashes=tuple(self.evidence.hashes(route.route_id, refs=route.evidence_refs)))
        with self._lock:
            self._runs[dispatch.dispatch_id] = record
            self._dedupe[fingerprint] = dispatch.dispatch_id
            self._turn_dispatch_counts[turn_key] = self._turn_dispatch_counts.get(turn_key, 0) + 1
            self._turn_active_counts[turn_key] = self._turn_active_counts.get(turn_key, 0) + 1
        self._persist(record)
        self._emit("route.dispatch.queued", self._event_metadata(record))
        try:
            future = self._executor.submit(self._execute, record)
        except Exception as exc:
            self._finish(record, DynamicSubtaskResult(dispatch.dispatch_id, route.route_id, dispatch.worker_kind, status="failed", error_code="executor-unavailable", retryable=True, runtime_id=getattr(worker, "runtime_id", "unknown")))
            self._log("warning", "route worker submission failed", exc)
        else:
            with self._lock:
                record.future = future
            future.add_done_callback(lambda done, current=record: self._future_done(current, done))
        result = self.status(dispatch.dispatch_id)
        if wait:
            return self.wait(dispatch.dispatch_id, timeout=timeout)
        return {**result, "accepted": True, "deduplicated": False}

    dispatch_subtask = dispatch
    submit = dispatch

    def _execute(self, record: _Run) -> DynamicSubtaskResult:
        with self._lock:
            if record.cancel_event.is_set() or record.status in {"cancelled", "interrupted"}:
                return DynamicSubtaskResult(record.dispatch.dispatch_id, record.route.route_id, record.dispatch.worker_kind, status="cancelled", error_code="cancelled", runtime_id=getattr(record.worker, "runtime_id", "unknown"))
            record.status = "running"
            record.started_at = _now()
        self._persist(record)
        self._emit("route.dispatch.started", self._event_metadata(record))
        started = time.monotonic()
        try:
            value = record.worker.execute(record.dispatch, record.route, record.cancel_event) if hasattr(record.worker, "execute") else _call_with_supported_signature(record.worker, record.dispatch, record.route, record.cancel_event)
            elapsed = (time.monotonic() - started) * 1000
            result = DynamicSubtaskResult.from_value(value, record.dispatch, latency_ms=elapsed)
            deadline = record.dispatch.deadline_ms or getattr(record.worker, "timeout_ms", None)
            if deadline and elapsed > float(deadline):
                result = DynamicSubtaskResult(
                    record.dispatch.dispatch_id,
                    record.route.route_id,
                    record.dispatch.worker_kind,
                    status="unknown",
                    latency_ms=elapsed,
                    error_code="deadline-exceeded",
                    retryable=False,
                    # The worker had the entire deadline to cross its
                    # transport boundary.  Even if an adapter omitted an
                    # explicit sent marker, a late callback must never be
                    # replayed automatically.
                    possibly_sent=True,
                    runtime_id=result.runtime_id,
                )
            worker_runtime = getattr(record.worker, "runtime_id", None)
            if worker_runtime and result.runtime_id == "unknown":
                result = replace(result, runtime_id=str(worker_runtime))
            return result
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000
            # Error class, not exception text, is safe metadata and enough for
            # retry diagnostics.  Never include worker response/prompt data.
            code = _token(type(exc).__name__, "error_code", default="worker-error")
            # Once a worker executor has started, the supervisor cannot prove
            # that a remote request was not accepted.  Treat the failure as
            # non-replayable unless the adapter explicitly raises a
            # pre-send marker with ``possibly_sent=False``.
            possibly_sent = bool(getattr(exc, "possibly_sent", True))
            retryable = bool(getattr(exc, "retryable", False)) and not possibly_sent
            return DynamicSubtaskResult(record.dispatch.dispatch_id, record.route.route_id, record.dispatch.worker_kind, status="failed", latency_ms=elapsed, error_code=code, retryable=retryable, possibly_sent=possibly_sent, runtime_id=getattr(record.worker, "runtime_id", "unknown"))

    def _future_done(self, record: _Run, future: Future[Any]) -> None:
        try:
            result = future.result()
        except Exception as exc:
            possibly_sent = bool(getattr(exc, "possibly_sent", True))
            result = DynamicSubtaskResult(record.dispatch.dispatch_id, record.route.route_id, record.dispatch.worker_kind, status="failed", error_code=_token(type(exc).__name__, "error_code", default="worker-error"), retryable=bool(getattr(exc, "retryable", False)) and not possibly_sent, possibly_sent=possibly_sent, runtime_id=getattr(record.worker, "runtime_id", "unknown"))
        if not isinstance(result, DynamicSubtaskResult):
            result = DynamicSubtaskResult.from_value(result, record.dispatch)
        self._finish(record, result)

    def _finish(self, record: _Run, result: DynamicSubtaskResult) -> None:
        """Finalize one run exactly once and publish its bounded outcome.

        Cancellation, deadline and shutdown can race with a worker callback.
        ``finalized`` is the single idempotence gate; a late callback is
        intentionally ignored so it cannot overwrite a non-replayable result
        or enqueue a duplicate mailbox item.
        """

        with self._lock:
            if record.finalized:
                return
            forced_status = record.status if record.status in {"cancelled", "interrupted", "unknown", "waiting-human", "needs-confirmation"} else None
            forced_error = record.error_code if forced_status else None
            if forced_status == "unknown" and forced_error != "deadline-exceeded":
                forced_error = forced_error or "unknown"
            if forced_status == "cancelled":
                forced_error = forced_error or "cancelled"
            if forced_status == "interrupted":
                forced_error = forced_error or "core-shutdown"
            if forced_status:
                # A forced lifecycle outcome never exposes a late answer.
                result = replace(
                    result,
                    status=forced_status,
                    answer=None,
                    summary=None,
                    error_code=forced_error,
                    retryable=False,
                    possibly_sent=bool(result.possibly_sent or record.started_at or forced_status in {"unknown", "cancelled", "interrupted"}),
                )
            elif result.status in {"queued", "running"}:
                result = replace(result, status="unknown", answer=None, summary=None, error_code="invalid-terminal-result", retryable=False, possibly_sent=True)
            record.result = result
            record.status = result.status
            record.completed_at = _now()
            record.latency_ms = result.latency_ms
            record.error_code = result.error_code
            record.retryable = bool(result.retryable and not result.possibly_sent)
            record.finalized = True
            self._release_active(record)
            self._queue_mailbox_result(record)
            emit = not record.terminal_event_emitted
            record.terminal_event_emitted = True
        self._persist(record)
        if emit:
            self._emit(f"route.dispatch.{result.status}", self._event_metadata(record))
        self._update_consultation(record.dispatch.consultation_id)

    def _rejected_dispatch(self, dispatch: DynamicSubtaskDispatch, error_code: str, *, status: str = "failed") -> dict[str, Any]:
        result = DynamicSubtaskResult(dispatch.dispatch_id, dispatch.route_id, dispatch.worker_kind, status=status, error_code=_token(error_code, "error_code", default="route-rejected"), retryable=False)
        with self._lock:
            known_route = self._routes.get(dispatch.route_id)
        rejection_route = known_route or RuntimeRouteDescriptor(route_id=dispatch.route_id, kind=dispatch.worker_kind, label=dispatch.route_id)
        record = _Run(
            dispatch=dispatch,
            route=rejection_route,
            worker=None,
            status=status,
            result=result,
            completed_at=_now(),
            error_code=error_code,
            finalized=True,
            terminal_event_emitted=True,
        )
        with self._lock:
            # Rejections are terminal outcomes too.  Keeping them in the
            # volatile run table lets the parent Agent explain why a planned
            # worker did not run and acknowledge that outcome consistently.
            existing = self._runs.get(dispatch.dispatch_id)
            if existing is not None:
                return {**self._public(existing), "accepted": False, "deduplicated": True}
            self._runs[dispatch.dispatch_id] = record
            self._queue_mailbox_result(record)
        self._persist(record)
        self._emit("route.dispatch.rejected", self._event_metadata(record))
        return {"schema": SUPERVISOR_SCHEMA, "accepted": False, "deduplicated": False, "status": status, "error_code": error_code, "dispatch": dispatch.to_dict()}

    def wait(self, dispatch_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        identifier = _identifier(dispatch_id, "dispatch_id") or ""
        with self._lock:
            record = self._runs.get(identifier)
            future = record.future if record else None
        if record is None:
            return {"schema": SUPERVISOR_SCHEMA, "found": False, "dispatch_id": identifier}
        if future is not None and record.status in {"queued", "running"}:
            limit = timeout if timeout is not None else self._timeout_seconds(record)
            try:
                future.result(timeout=max(0.0, float(limit)))
            except FutureTimeout:
                with self._lock:
                    still_active = record.status in {"queued", "running"} and not record.finalized
                    if still_active:
                        record.status = "unknown"
                        record.error_code = "deadline-exceeded"
                        record.cancel_event.set()
                if still_active:
                    self._finish(
                        record,
                        DynamicSubtaskResult(
                            record.dispatch.dispatch_id,
                            record.route.route_id,
                            record.dispatch.worker_kind,
                            status="unknown",
                            error_code="deadline-exceeded",
                            retryable=False,
                            possibly_sent=True,
                            runtime_id=getattr(record.worker, "runtime_id", "unknown"),
                        ),
                    )
            except Exception:
                pass
        return self.status(identifier)

    def _timeout_seconds(self, record: _Run) -> float:
        value = record.dispatch.deadline_ms or getattr(record.worker, "timeout_ms", None) or (300_000 if record.dispatch.worker_kind in {"web", "web-worker", "external-harness", "zcode"} else 120_000)
        return max(0.001, min(float(value) / 1000.0, 3_600.0))

    def status(self, dispatch_id: str) -> dict[str, Any]:
        identifier = _identifier(dispatch_id, "dispatch_id") or ""
        with self._lock:
            record = self._runs.get(identifier)
        if record is None and self.storage is not None:
            getter = getattr(self.storage, "get_agent_route_run", None)
            if callable(getter):
                try:
                    row = getter(identifier)
                except Exception:
                    row = None
                if row:
                    return {"schema": SUPERVISOR_SCHEMA, "found": True, "dispatch": row, "status": row.get("status", "unknown")}
            return {"schema": SUPERVISOR_SCHEMA, "found": False, "dispatch_id": identifier}
        return self._public(record)

    def pending_results(
        self,
        parent_session_id: str,
        parent_turn_id: str | None = None,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return terminal worker results waiting for parent acknowledgement.

        Only the bounded dispatch projection and sanitized result are exposed;
        the original question/context never appears in this mailbox API.
        """

        session = _identifier(parent_session_id, "parent_session_id") or ""
        turn = _identifier(parent_turn_id, "parent_turn_id", required=False)
        cap = max(1, min(int(limit), 100))
        with self._lock:
            keys = [self._turn_key(session, turn)] if turn else [key for key in self._mailbox if key[0] == session]
            dispatch_ids: list[str] = []
            for key in keys:
                dispatch_ids.extend(self._mailbox.get(key, ()))
            records = [self._runs[item] for item in dispatch_ids if item in self._runs]
        records.sort(key=lambda item: (item.completed_at or item.created_at, item.dispatch.dispatch_id))
        rows: list[dict[str, Any]] = []
        for record in records[:cap]:
            if record.result is None or record.mailbox_acknowledged:
                continue
            rows.append(
                {
                    "dispatch_id": record.dispatch.dispatch_id,
                    "parent_session_id": record.dispatch.parent_session_id,
                    "parent_turn_id": record.dispatch.parent_turn_id,
                    "route_id": record.route.route_id,
                    "worker_kind": record.dispatch.worker_kind,
                    "status": record.status,
                    "result": record.result.to_dict(),
                    "completed_at": record.completed_at,
                    "pending": True,
                }
            )
        return {
            "schema": SUPERVISOR_SCHEMA,
            "parent_session_id": session,
            "parent_turn_id": turn,
            "results": rows,
            "count": len(rows),
        }

    def acknowledge_result(self, dispatch_id: str) -> dict[str, Any]:
        """Acknowledge one mailbox result; repeated acknowledgements are safe."""

        identifier = _identifier(dispatch_id, "dispatch_id") or ""
        with self._lock:
            record = self._runs.get(identifier)
            if record is None:
                return {"schema": SUPERVISOR_SCHEMA, "found": False, "dispatch_id": identifier, "acknowledged": False}
            if record.result is None or record.status in {"queued", "running"}:
                return {
                    "schema": SUPERVISOR_SCHEMA,
                    "found": True,
                    "dispatch_id": identifier,
                    "acknowledged": False,
                    "reason": "result-not-terminal",
                }
            already = record.mailbox_acknowledged
            record.mailbox_acknowledged = True
            key = self._turn_key(record.dispatch.parent_session_id, record.dispatch.parent_turn_id)
            pending = self._mailbox.get(key)
            if pending and identifier in pending:
                self._mailbox[key] = [item for item in pending if item != identifier]
                if not self._mailbox[key]:
                    self._mailbox.pop(key, None)
        if not already:
            self._emit(
                "route.result.acknowledged",
                self._event_metadata(record),
            )
        return {
            "schema": SUPERVISOR_SCHEMA,
            "found": True,
            "dispatch_id": identifier,
            "acknowledged": True,
            "idempotent": already,
        }

    def capture_evaluation_sample(
        self,
        dispatch_id: str,
        task_set: Any,
        *,
        task_id: str,
        opt_in: bool = False,
        manifest: Any = None,
        metrics: Mapping[str, Any] | None = None,
        harness_id: str = "unknown",
        harness_version: str = "unknown",
        adapter_id: str | None = None,
        adapter_version: str = "unknown",
        hardware_class: str = "unknown",
        privacy_policy: str = "unknown",
        cache_state: str = "unknown",
    ) -> Any:
        """Project one terminal run into the offline evaluation contract.

        This is deliberately opt-in and run-scoped.  The supervisor does not
        scan logs or storage, and the evaluator reads only fixed scalar fields
        from its private ``_Run`` object.  Callers receive an
        ``EvaluationRecord`` and may explicitly serialize it for an offline
        evaluation job.
        """

        if opt_in is not True:
            raise SupervisorValidationError("capture-opt-in-required")
        identifier = _identifier(dispatch_id, "dispatch_id") or ""
        with self._lock:
            record = self._runs.get(identifier)
        if record is None:
            raise SupervisorValidationError("unknown-dispatch")
        if record.status in {"queued", "running"}:
            raise SupervisorValidationError("run-not-terminal")
        from ..model_evaluation import capture_evaluation_sample as _capture
        from ..model_evaluation import manifest_from_route as _manifest

        selected_manifest = manifest
        if selected_manifest is None:
            runtime = self.runtime
            runtime_id = getattr(runtime, "runtime_id", None) or getattr(runtime, "id", None) or harness_id
            runtime_version = getattr(runtime, "version", None) or harness_version
            selected_manifest = _manifest(
                record.route,
                task_set,
                harness_id=str(runtime_id or "unknown"),
                harness_version=str(runtime_version or "unknown"),
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                hardware_class=hardware_class,
                privacy_policy=privacy_policy,
                cache_state=cache_state,
            )
        return _capture(
            record,
            task_set,
            task_id=task_id,
            manifest=selected_manifest,
            opt_in=True,
            metrics=metrics,
        )

    get_status = status

    def list_runs(self, *, parent_session_id: str | None = None, parent_turn_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        session = str(parent_session_id) if parent_session_id else None
        turn = str(parent_turn_id) if parent_turn_id else None
        limit = max(1, min(int(limit), 500))
        with self._lock:
            records = list(self._runs.values())
        records.sort(key=lambda item: item.created_at, reverse=True)
        result = []
        for record in records:
            if session and record.dispatch.parent_session_id != session:
                continue
            if turn and record.dispatch.parent_turn_id != turn:
                continue
            result.append(self._public(record))
            if len(result) >= limit:
                break
        return result

    runs = list_runs

    # ---- consultation lifecycle -----------------------------------------------
    def _continuation_route_refs(
        self,
        continuation_of: str,
    ) -> tuple[set[str], set[str]] | None:
        """Resolve the exact routes/profiles used by a prior consultation.

        A consultation continuation is a transport/session reuse request, not
        permission to choose a fresh provider.  Resolve the previous member
        metadata from the live supervisor first and use the bounded SQLite
        projection only when the previous run is no longer in memory.  No
        question, answer, browser state, or credential is read here.
        """

        identifier = _identifier(continuation_of, "continuation_of") or ""
        member_rows: list[Any] = []
        with self._lock:
            consultation = self._consultations.get(identifier)
            if consultation is not None:
                member_rows = list(consultation.get("member_metadata") or ())
            else:
                run = self._runs.get(identifier)
                if run is not None:
                    member_rows = [
                        {
                            "route_id": run.route.route_id,
                            "provider_profile_id": run.route.provider_profile_id,
                        }
                    ]

        # A persisted consultation contains only the same bounded member
        # metadata.  A persisted route run is also accepted for callers that
        # use a dispatch id as ``continuation_of``.
        if not member_rows and self.storage is not None:
            getter = getattr(self.storage, "get_agent_consultation", None)
            if callable(getter):
                try:
                    row = getter(identifier)
                except Exception:
                    row = None
                if isinstance(row, Mapping):
                    member_rows = list(row.get("member_metadata") or ())
            if not member_rows:
                run_getter = getattr(self.storage, "get_agent_route_run", None)
                if callable(run_getter):
                    try:
                        row = run_getter(identifier)
                    except Exception:
                        row = None
                    if isinstance(row, Mapping):
                        member_rows = [row]

        route_ids: set[str] = set()
        profile_ids: set[str] = set()
        for item in member_rows[:8]:
            if not isinstance(item, Mapping):
                continue
            raw_route = item.get("route_id") or item.get("routeId")
            raw_profile = item.get("provider_profile_id") or item.get("providerProfileId")
            try:
                route_id = _identifier(raw_route, "route_id", required=False)
                profile_id = _identifier(raw_profile, "provider_profile_id", required=False)
            except SupervisorValidationError:
                continue
            if route_id:
                route_ids.add(route_id)
            if profile_id:
                profile_ids.add(profile_id)
        if not route_ids and not profile_ids:
            return None
        return route_ids, profile_ids

    def _consultation_routes(self, request: ConsultationRequest) -> list[RuntimeRouteDescriptor]:
        """Select distinct, ready web routes for one consultation panel.

        Consultation is intentionally a web-only convenience facade.  Other
        worker kinds still use ``dispatch`` directly so the supervisor does
        not become a second semantic Agent loop.
        """

        constraints = request.route_constraints if isinstance(request.route_constraints, Mapping) else {}
        allowed_ids = constraints.get("route_ids") or constraints.get("routeIds")
        allowed = {str(item) for item in allowed_ids} if isinstance(allowed_ids, (list, tuple, set)) else set()
        required = set(request.required_capabilities or ("text",))
        continuation_refs = (
            self._continuation_route_refs(request.continuation_of)
            if request.continuation_of
            else None
        )
        # A missing continuation must fail closed.  In particular, never
        # replace a vanished prior Profile with a different web provider.
        if request.continuation_of and continuation_refs is None:
            return []
        continuation_route_ids, continuation_profiles = continuation_refs or (set(), set())
        privacy = constraints.get("privacy_constraints") or constraints.get("privacyConstraints") or ()
        if isinstance(privacy, str):
            privacy = (privacy,)
        difficulty = str(constraints.get("difficulty") or "basic").strip().lower()
        risk = str(constraints.get("risk") or "normal").strip().lower()
        min_quality = constraints.get("min_quality_tier") or constraints.get("minQualityTier")
        # A consultation is advisory: an unmeasured web model may still be
        # useful as an opinion, so the default quality floor is deliberately
        # ``unknown``.  A caller can raise it explicitly through constraints.
        quality_floor = str(min_quality).strip() if min_quality else "unknown"
        with self._lock:
            values = list(self._routes.values())
        selected: list[RuntimeRouteDescriptor] = []
        providers: set[str] = set()
        for route in values:
            if route.kind not in {"web", "web-worker"} and route.source_kind != "web-chat":
                continue
            if allowed and route.route_id not in allowed:
                continue
            if request.continuation_of and not (
                route.route_id in continuation_route_ids
                or (
                    route.provider_profile_id is not None
                    and route.provider_profile_id in continuation_profiles
                )
            ):
                continue
            # A panel member gets an independent BrowserSkill/Profile lease.
            # Do not select a route already owned by another Agent or waiting
            # for a manual handoff; the caller can retry after the lease is
            # released instead of racing the existing writer.
            if route.occupancy != "idle":
                continue
            if not route.available or not required.issubset(set(route.capabilities)):
                continue
            # Automatic consultation may use only an already authorized and
            # recently healthy Profile.  Unknown quota and paid routes are
            # admitted only far enough for the normal dispatch gate to return
            # ``waiting-human``; that gate never sends the browser message
            # without explicit consent/confirmation.
            if route.auth_state not in {"authorized", "not-required"}:
                continue
            if route.health_state not in {"healthy", "ready", "available"}:
                continue
            if route.quota_state in {"exhausted", "expired", "blocked", "needs-auth"}:
                continue
            if self._route_compatibility(
                route,
                required_capabilities=required,
                privacy_constraints=privacy,
                difficulty=difficulty,
                risk=risk,
                min_quality_tier=quality_floor,
                explicit_route=False,
            ):
                continue
            provider = route.provider_key or route.adapter_id or route.route_id
            if provider in providers:
                continue
            providers.add(provider)
            selected.append(route)
            if len(selected) >= request.max_members:
                break
        return selected

    def _persist_consultation(self, value: Mapping[str, Any]) -> None:
        sink = getattr(self.storage, "upsert_agent_consultation", None) if self.storage is not None else None
        if not callable(sink):
            return
        try:
            sink({
                "consultation_id": value.get("consultation_id"),
                "parent_session_id": value.get("parent_session_id"),
                "parent_turn_id": value.get("parent_turn_id"),
                "decision_kind": value.get("decision_kind") or "small-answer",
                "status": value.get("status") or "unknown",
                "max_members": value.get("max_members") or 1,
                "successful_count": value.get("successful_count") or 0,
                "failed_count": value.get("failed_count") or 0,
                "disagreement_detected": bool(value.get("disagreement_detected")),
                "untrusted_external": True,
                "member_metadata": list(value.get("member_metadata") or ()),
                "created_at": value.get("created_at") or _now(),
            })
        except Exception as exc:
            self._log("debug", "consultation metadata persistence unavailable", exc)

    def _consultation_public(self, value: Mapping[str, Any]) -> dict[str, Any]:
        members = tuple(value.get("members") or ())
        result = ConsultationResult(
            str(value.get("consultation_id") or ""),
            str(value.get("status") or "unknown"),
            members,
            int(value.get("successful_count") or 0),
            int(value.get("failed_count") or 0),
            bool(value.get("disagreement_detected")),
            True,
            value.get("decision_kind"),
            value.get("parent_session_id"),
            "single-opinion" if len(members) == 1 else "panel",
        )
        return result.to_dict()

    def _update_consultation(self, consultation_id: str | None) -> None:
        if not consultation_id:
            return
        identifier = _identifier(consultation_id, "consultation_id", required=False)
        if not identifier:
            return
        with self._lock:
            consultation = self._consultations.get(identifier)
            if consultation is None:
                return
            member_results: list[ConsultationMemberResult] = []
            metadata: list[dict[str, Any]] = []
            for item in consultation.get("member_metadata", []):
                dispatch_id = str(item.get("dispatch_id") or "")
                run = self._runs.get(dispatch_id)
                result = run.result if run is not None else None
                if isinstance(result, DynamicSubtaskResult):
                    member_status = result.status
                    # The modern supervisor exposes a few lifecycle states
                    # that the older web consultation contract does not.  A
                    # member awaiting approval is a human boundary, never a
                    # completed/failed answer.
                    if member_status == "needs-confirmation":
                        member_status = "waiting-human"
                    elif member_status == "partial":
                        member_status = "unknown"
                    member = ConsultationMemberResult(
                        result.dispatch_id,
                        result.route_id,
                        member_status,
                        answer=result.answer,
                        summary=result.summary,
                        concerns=result.concerns,
                        confidence=result.confidence,
                        latency_ms=result.latency_ms,
                        error_code=result.error_code,
                        untrusted_external=True,
                        consultation_id=identifier,
                        structured_result=result.structured_result,
                        artifacts=tuple(result.artifacts_metadata),
                        runtime_id=result.runtime_id,
                        retryable=result.retryable,
                    )
                else:
                    member_status = str(item.get("status") or "queued")
                    if member_status == "needs-confirmation":
                        member_status = "waiting-human"
                    member = ConsultationMemberResult(
                        dispatch_id,
                        str(item.get("route_id") or "unknown"),
                        member_status,
                        error_code=item.get("error_code"),
                        consultation_id=identifier,
                        provider_profile_id=item.get("provider_profile_id"),
                    )
                if not member.provider_profile_id:
                    member = ConsultationMemberResult(
                        member.dispatch_id,
                        member.route_id,
                        member.status,
                        answer=member.answer,
                        summary=member.summary,
                        concerns=member.concerns,
                        confidence=member.confidence,
                        latency_ms=member.latency_ms,
                        error_code=member.error_code,
                        consultation_id=identifier,
                        provider_profile_id=item.get("provider_profile_id"),
                        structured_result=member.structured_result,
                        artifacts=member.artifacts,
                        runtime_id=member.runtime_id,
                        retryable=member.retryable,
                    )
                member_results.append(member)
                metadata.append({
                    "dispatch_id": member.dispatch_id,
                    "route_id": member.route_id,
                    "provider_profile_id": item.get("provider_profile_id"),
                    "status": member.status,
                    "latency_ms": member.latency_ms,
                    "result_length": len(member.answer or ""),
                    "error_code": member.error_code,
                })
            successful = sum(1 for item in member_results if item.status == "completed")
            finished = sum(1 for item in member_results if item.status not in {"queued", "running"})
            failed = sum(1 for item in member_results if item.status not in {"queued", "running", "completed"})
            interrupted = any(item.status == "interrupted" for item in member_results)
            if not member_results or finished < len(member_results):
                status = "running" if member_results else "failed"
            elif interrupted:
                # A Core shutdown is a terminal lifecycle boundary.  Keep an
                # otherwise successful panel distinguishable from a normal
                # partial/failed result so callers never replay it blindly.
                status = "interrupted"
            elif successful == len(member_results):
                status = "completed"
            elif successful:
                status = "partial"
            elif any(item.status == "cancelled" for item in member_results):
                status = "cancelled"
            elif any(item.status in {"waiting-human", "needs-confirmation"} for item in member_results):
                status = "waiting-human"
            else:
                status = "failed"
            summaries = [item.summary for item in member_results if item.status == "completed" and item.summary]
            disagreement = len({item.casefold() for item in summaries}) > 1 if len(summaries) > 1 else False
            consultation["status"] = status
            consultation["successful_count"] = successful
            consultation["failed_count"] = failed
            consultation["disagreement_detected"] = disagreement
            consultation["member_metadata"] = metadata
            consultation["members"] = tuple(member_results)
            consultation["updated_at"] = _now()
            terminal = status in {"completed", "partial", "failed", "cancelled", "waiting-human", "interrupted"}
            emit_completion = terminal and not consultation.get("completion_emitted")
            if emit_completion:
                consultation["completion_emitted"] = True
            snapshot = dict(consultation)
        self._persist_consultation(snapshot)
        if emit_completion:
            self._emit("consultation.completed", {
                "consultation_id": identifier,
                "parent_session_id": snapshot.get("parent_session_id"),
                "status": snapshot.get("status"),
                "successful_count": snapshot.get("successful_count"),
                "failed_count": snapshot.get("failed_count"),
                "disagreement_detected": snapshot.get("disagreement_detected"),
            })

    def start_consultation(self, value: Mapping[str, Any] | ConsultationRequest, *, wait: bool = False, timeout: float | None = None) -> dict[str, Any]:
        """Start a bounded panel using the supervisor's normal dispatch path."""

        if self._closed:
            raise SupervisorError("route supervisor is closed")
        request = value if isinstance(value, ConsultationRequest) else ConsultationRequest.from_dict(value)
        with self._lock:
            if request.consultation_id in self._consultations:
                raise SupervisorError("consultation_id is already active")
        routes = self._consultation_routes(request)
        now = _now()
        consultation: dict[str, Any] = {
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
            "members": (),
            "created_at": now,
            "updated_at": now,
            # Keep the request only in memory for worker prompt construction.
            "request": request,
            "completion_emitted": False,
            "continuation_of": request.continuation_of,
        }
        with self._lock:
            self._consultations[request.consultation_id] = consultation
        if not routes:
            self._persist_consultation(consultation)
            self._emit("consultation.failed", {"consultation_id": request.consultation_id, "parent_session_id": request.parent_session_id, "status": "failed", "error_code": "no-routable-profile"})
            return self.consultation_status(request.consultation_id)
        roles = ("方案设计顾问", "反例审查顾问", "风险检查顾问")
        for index, route in enumerate(routes):
            dispatch = DynamicSubtaskDispatch(
                dispatch_id=f"dispatch-{uuid4().hex[:16]}",
                parent_session_id=request.parent_session_id,
                parent_turn_id=request.parent_turn_id,
                route_id=route.route_id,
                question=request.question,
                worker_kind="web",
                context_refs=request.context_refs,
                requested_capabilities=request.required_capabilities,
                deadline_ms=300_000,
                depth=0,
                side_effect="none",
                quota_consent=route.quota_consent in {"granted", "authorized", "approved"},
                budget_policy="prefer-free",
                risk="normal",
                role=roles[index % len(roles)],
                consultation_id=request.consultation_id,
                continuation_of=request.continuation_of,
            )
            with self._lock:
                consultation["member_metadata"].append({
                    "dispatch_id": dispatch.dispatch_id,
                    "route_id": route.route_id,
                    "provider_profile_id": route.provider_profile_id,
                    "status": "queued",
                })
            result = self.dispatch(dispatch, wait=False)
            if not result.get("accepted"):
                with self._lock:
                    item = consultation["member_metadata"][-1]
                    item["status"] = result.get("status") or "failed"
                    item["error_code"] = result.get("error_code") or "route-rejected"
        self._update_consultation(request.consultation_id)
        self._emit("consultation.started", {"consultation_id": request.consultation_id, "parent_session_id": request.parent_session_id, "status": "running", "member_count": len(routes)})
        if wait:
            deadline = time.monotonic() + (float(timeout) if timeout is not None else 300.0)
            while time.monotonic() < deadline:
                current = self.consultation_status(request.consultation_id)
                if current.get("status") not in {"queued", "running"}:
                    return current
                time.sleep(0.02)
        return self.consultation_status(request.consultation_id)

    def consultation_status(self, consultation_id: str) -> dict[str, Any]:
        identifier = _identifier(consultation_id, "consultation_id") or ""
        self._update_consultation(identifier)
        with self._lock:
            value = self._consultations.get(identifier)
            if value is not None:
                result = self._consultation_public(value)
                result["found"] = True
                return result
        getter = getattr(self.storage, "get_agent_consultation", None) if self.storage is not None else None
        if callable(getter):
            try:
                row = getter(identifier)
            except Exception:
                row = None
            if row:
                members = row.get("member_metadata") or []
                return {
                    "schema": AGENT_CONSULTATION_SCHEMA,
                    "consultation_id": identifier,
                    "found": True,
                    "parent_session_id": row.get("parent_session_id"),
                    "decision_kind": row.get("decision_kind"),
                    "status": row.get("status", "unknown"),
                    "members": members,
                    "successful_count": row.get("successful_count", 0),
                    "failed_count": row.get("failed_count", 0),
                    "disagreement_detected": bool(row.get("disagreement_detected")),
                    "untrusted_external": True,
                    "trust_label": "UNTRUSTED_WEB_RESULT",
                    "opinion_mode": "single-opinion" if len(members) == 1 else "panel",
                    "single_opinion": len(members) == 1,
                }
        return {"schema": AGENT_CONSULTATION_SCHEMA, "consultation_id": identifier, "status": "unknown", "members": [], "found": False, "untrusted_external": True, "trust_label": "UNTRUSTED_WEB_RESULT"}

    def owns_consultation(self, consultation_id: str) -> bool:
        """Return whether this live supervisor owns the consultation.

        Core uses this small ownership check to distinguish an active modern
        consultation from a legacy web coordinator entry that happens to use
        the same metadata table.  It does not expose the question or answers.
        """

        identifier = _identifier(consultation_id, "consultation_id") or ""
        with self._lock:
            return identifier in self._consultations

    def list_consultations(self, *, parent_session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        parent = str(parent_session_id) if parent_session_id else None
        with self._lock:
            values = list(self._consultations.values())
        values.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        result = [self._consultation_public(item) for item in values if not parent or item.get("parent_session_id") == parent]
        getter = getattr(self.storage, "list_agent_consultations", None) if self.storage is not None else None
        if callable(getter) and len(result) < limit:
            try:
                rows = getter(parent_session_id=parent, limit=max(1, min(int(limit), 100)))
            except Exception:
                rows = []
            for row in rows:
                if not any(item.get("consultation_id") == row.get("consultation_id") for item in result):
                    result.append(self.consultation_status(str(row.get("consultation_id"))))
        return result[: max(1, min(int(limit), 100))]

    def cancel_consultation(self, consultation_id: str) -> dict[str, Any]:
        identifier = _identifier(consultation_id, "consultation_id") or ""
        with self._lock:
            value = self._consultations.get(identifier)
            ids = [str(item.get("dispatch_id")) for item in (value or {}).get("member_metadata", []) if item.get("dispatch_id")]
        results = [self.cancel(item) for item in ids]
        self._update_consultation(identifier)
        return {"schema": AGENT_CONSULTATION_SCHEMA, "consultation_id": identifier, "cancelled": any(item.get("cancelled") for item in results), "dispatches": results}

    def active_runs(self, *, parent_session_id: str | None = None, parent_turn_id: str | None = None) -> list[dict[str, Any]]:
        return [item for item in self.list_runs(parent_session_id=parent_session_id, parent_turn_id=parent_turn_id) if item.get("status") in {"queued", "running"}]

    def cancel(self, dispatch_id: str) -> dict[str, Any]:
        identifier = _identifier(dispatch_id, "dispatch_id") or ""
        with self._lock:
            record = self._runs.get(identifier)
            if record is None:
                return {"schema": SUPERVISOR_SCHEMA, "dispatch_id": identifier, "cancelled": False, "reason": "unknown-dispatch"}
            if record.finalized or record.status in {"completed", "failed", "cancelled", "interrupted", "unknown"}:
                return {**self._public(record), "cancelled": False, "reason": "already-finished"}
            record.cancel_event.set()
            record.status = "cancelled"
            record.error_code = "cancelled"
            if record.future:
                record.future.cancel()
        self._finish(
            record,
            DynamicSubtaskResult(
                record.dispatch.dispatch_id,
                record.route.route_id,
                record.dispatch.worker_kind,
                status="cancelled",
                error_code="cancelled",
                retryable=False,
                possibly_sent=bool(record.started_at),
                runtime_id=getattr(record.worker, "runtime_id", "unknown"),
            ),
        )
        return {**self._public(record), "cancelled": True}

    def cancel_all(self, *, parent_session_id: str | None = None, parent_turn_id: str | None = None) -> list[dict[str, Any]]:
        values = self.active_runs(parent_session_id=parent_session_id, parent_turn_id=parent_turn_id)
        return [self.cancel(str(item.get("dispatch_id"))) for item in values if item.get("dispatch_id")]

    def retry(self, dispatch_id: str, *, wait: bool = False) -> dict[str, Any]:
        identifier = _identifier(dispatch_id, "dispatch_id") or ""
        with self._lock:
            record = self._runs.get(identifier)
        if record is None:
            raise SupervisorError("unknown dispatch")
        if record.status != "failed" or not record.retryable:
            raise SupervisorError("only a confirmed pre-send failure can be retried")
        dispatch = replace(record.dispatch, dispatch_id=f"dispatch-{uuid4().hex[:16]}", continuation_of=record.dispatch.dispatch_id)
        return self.dispatch(dispatch, wait=wait)

    def _fingerprint(self, dispatch: DynamicSubtaskDispatch) -> str:
        context = _safe_context(dispatch.context_refs)
        return _hash(
            {
                "parent_session_id": dispatch.parent_session_id,
                "parent_turn_id": dispatch.parent_turn_id,
                "route_id": dispatch.route_id,
                "worker_kind": dispatch.worker_kind,
                "question": dispatch.question,
                "context_refs": context,
                "decision_key": dispatch.decision_key,
                "consultation_id": dispatch.consultation_id,
            }
        )

    def _turn_key(self, session_id: str, turn_id: str | None) -> tuple[str, str]:
        return session_id, turn_id or "__session__"

    def _queue_mailbox_result(self, record: _Run) -> None:
        """Queue one terminal result for its explicit parent turn."""

        if self._closed or record.result is None or record.status in {"queued", "running"}:
            return
        key = self._turn_key(record.dispatch.parent_session_id, record.dispatch.parent_turn_id)
        pending = self._mailbox.setdefault(key, [])
        dispatch_id = record.dispatch.dispatch_id
        if dispatch_id not in pending and not record.mailbox_acknowledged:
            pending.append(dispatch_id)
        # Bound volatile memory.  Prefer dropping already acknowledged ids;
        # otherwise retain the newest terminal outcomes.
        if len(pending) > 128:
            retained = [item for item in pending if item in self._runs and not self._runs[item].mailbox_acknowledged]
            self._mailbox[key] = retained[-128:]
        self._emit(
            "route.result.pending",
            {
                "dispatch_id": dispatch_id,
                "parent_session_id": record.dispatch.parent_session_id,
                "parent_turn_id": record.dispatch.parent_turn_id,
                "route_id": record.route.route_id,
                "status": record.status,
                "error_code": record.error_code,
            },
        )

    def _release_active(self, record: _Run) -> None:
        """Release a turn slot exactly once, even after cancellation/timeout."""

        if record.active_released:
            return
        record.active_released = True
        turn_key = self._turn_key(record.dispatch.parent_session_id, record.dispatch.parent_turn_id)
        self._turn_active_counts[turn_key] = max(0, self._turn_active_counts.get(turn_key, 1) - 1)

    # ---- metadata/public projection --------------------------------------------
    def _public(self, record: _Run) -> dict[str, Any]:
        if record is None:
            return {"schema": SUPERVISOR_SCHEMA, "found": False}
        with self._lock:
            result = record.result.to_dict() if record.result else None
            status = record.status
            dispatch = record.dispatch.to_dict()
            value = {
                "schema": SUPERVISOR_SCHEMA,
                "found": True,
                "accepted": True,
                "dispatch": dispatch,
                "dispatch_id": record.dispatch.dispatch_id,
                "status": status,
                "result": result,
                "runtime_id": record.route.runtime_id,
                "worker_kind": record.dispatch.worker_kind,
                "started_at": record.started_at,
                "completed_at": record.completed_at,
                "latency_ms": record.latency_ms,
                "error_code": record.error_code,
                "retryable": bool(record.retryable),
                "possibly_sent": bool(result.get("possibly_sent")) if result else bool(record.started_at),
                "result_pending": bool(record.result is not None and not record.mailbox_acknowledged),
                "result_acknowledged": bool(record.mailbox_acknowledged),
            }
            if result is not None and result.get("status") == "completed":
                value["completed"] = True
            return value

    def _event_metadata(self, record: _Run) -> dict[str, Any]:
        result = record.result
        return {
            "dispatch_id": record.dispatch.dispatch_id,
            "parent_session_id": record.dispatch.parent_session_id,
            "parent_turn_id": record.dispatch.parent_turn_id,
            "route_id": record.route.route_id,
            "runtime_id": record.route.runtime_id,
            "executor": record.route.executor,
            "transport": record.route.transport,
            "side_effect": record.route.side_effect,
            "worker_kind": record.dispatch.worker_kind,
            "status": record.status,
            "error_code": record.error_code,
            "latency_ms": record.latency_ms,
            "result_length": len(result.answer or "") if result else 0,
            "summary_hash": _hash(result.summary) if result and result.summary else None,
            "evidence_hashes": list(record.evidence_hashes),
            "workspace_access": record.dispatch.workspace_access,
            "depth": record.dispatch.depth,
        }

    def _persist(self, record: _Run) -> None:
        # This object is the only payload passed to persistence hooks.  It
        # intentionally has no question, context, answer, DOM, or artifact
        # body, so custom stores cannot accidentally retain sensitive content.
        result = record.result
        metadata = {
            "dispatch_id": record.dispatch.dispatch_id,
            "parent_session_id": record.dispatch.parent_session_id,
            "parent_turn_id": record.dispatch.parent_turn_id,
            "route_id": record.route.route_id,
            "runtime_id": record.route.runtime_id,
            "executor": record.route.executor,
            "transport": record.route.transport,
            "side_effect": record.route.side_effect,
            "evidence_hash": _hash(record.evidence_hashes) if record.evidence_hashes else None,
            "worker_kind": record.dispatch.worker_kind,
            "mode": "consultation-panel" if record.dispatch.consultation_id else "web-worker" if record.dispatch.worker_kind in {"web", "web-worker"} else "provider-worker",
            "status": record.status,
            "started_at": record.started_at or record.created_at,
            "completed_at": record.completed_at,
            "latency_ms": record.latency_ms,
            "error_code": record.error_code,
            "result_length": len(result.answer or "") if result else 0,
            "summary_hash": _hash(result.summary) if result and result.summary else None,
            "retryable": bool(record.retryable),
            "budget_impact": result.budget_impact if result else {},
            "evidence_hashes": list(record.evidence_hashes),
            "workspace_access": record.dispatch.workspace_access,
            "required_capabilities": list(record.dispatch.requested_capabilities or ("text",)),
            "depth": record.dispatch.depth,
            "updated_at": _now(),
        }
        if callable(self.metadata_sink):
            try:
                self.metadata_sink(dict(metadata))
            except Exception as exc:
                self._log("debug", "route metadata persistence unavailable", exc)

        # The SQLite projection accepts the runtime-neutral columns on current
        # schemas.  A bounded legacy fallback keeps older data directories
        # usable while never writing prompt/result content.
        storage_sink = getattr(self.storage, "upsert_agent_route_run", None) if self.storage is not None else None
        if callable(storage_sink):
            payload = dict(metadata)
            payload["consultation_id"] = record.dispatch.consultation_id
            payload["provider_profile_id"] = record.route.provider_profile_id
            payload["continuation_of"] = record.dispatch.continuation_of
            try:
                storage_sink(payload)
            except Exception as exc:
                # Older installations only know the original web columns.
                # Retry that narrow projection for web workers; non-web rows
                # remain available through the runtime-neutral hook.
                if record.dispatch.worker_kind in {"web", "web-worker"}:
                    legacy = {
                        key: payload.get(key)
                        for key in {
                            "dispatch_id", "consultation_id", "parent_session_id", "parent_turn_id", "mode", "route_id",
                            "provider_profile_id", "continuation_of", "status", "started_at", "completed_at",
                            "latency_ms", "error_code", "result_length", "summary_hash", "retryable",
                        }
                    }
                    try:
                        storage_sink(legacy)
                    except Exception as legacy_exc:
                        self._log("debug", "route metadata persistence unavailable", legacy_exc)
                else:
                    self._log("debug", "route metadata persistence unavailable", exc)

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if not self.event_sink:
            return
        event = {"event_type": event_type, **{key: value for key, value in payload.items() if value is not None}}
        try:
            self.event_sink(_safe_context(event, budget=4_000))
        except Exception as exc:
            self._log("debug", "route event sink unavailable", exc)

    def _log(self, level: str, message: str, error: Exception | None = None) -> None:
        logger = self.logger
        method = getattr(logger, level, None) if logger is not None else None
        if callable(method):
            try:
                method(message, error) if error is not None else method(message)
            except Exception:
                return

    def close(self) -> None:
        consultation_ids: set[str] = set()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            records = [record for record in self._runs.values() if record.status in {"queued", "running"} and not record.finalized]
            for record in records:
                record.cancel_event.set()
                record.status = "interrupted"
                record.error_code = "core-shutdown"
                if record.dispatch.consultation_id:
                    consultation_ids.add(record.dispatch.consultation_id)
            # A consultation can still be queued while all of its dispatches
            # are waiting for a worker slot.  Mark its metadata as interrupted
            # as well, so a restart never presents it as replayable work.
            for identifier, consultation in self._consultations.items():
                if consultation.get("status") not in {"queued", "running"}:
                    continue
                consultation_ids.add(identifier)
                for item in consultation.get("member_metadata", []):
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("status") or "") in {"queued", "running"}:
                        item["status"] = "interrupted"
                        item["error_code"] = "core-shutdown"
            # Mailbox entries and armed requests are process-local.  They are
            # deliberately discarded after interruption metadata is written so
            # a newly started Core cannot replay an external worker.
            self._mailbox.clear()
            self._turn_requests.clear()

        # Complete each active run through the same idempotent terminal path as
        # explicit cancellation/deadline handling.  Late futures now observe
        # ``finalized`` and cannot overwrite the interruption outcome.
        for record in records:
            self._finish(
                record,
                DynamicSubtaskResult(
                    record.dispatch.dispatch_id,
                    record.route.route_id,
                    record.dispatch.worker_kind,
                    status="interrupted",
                    error_code="core-shutdown",
                    retryable=False,
                    possibly_sent=True,
                    runtime_id=getattr(record.worker, "runtime_id", "unknown"),
                ),
            )

        # Recompute public member projections after the run records have been
        # marked.  This also persists the consultation-level interrupted state
        # and emits one bounded lifecycle event per panel.
        for consultation_id in consultation_ids:
            try:
                self._update_consultation(consultation_id)
            except Exception as exc:
                self._log("debug", "consultation shutdown projection failed", exc)

        # A direct Supervisor may be used without the legacy coordinator that
        # normally recovers stale rows at startup.  Keep that path safe too:
        # only active metadata rows are changed, and no content is read.
        getter = getattr(self.storage, "list_agent_consultations", None) if self.storage is not None else None
        sink = getattr(self.storage, "upsert_agent_consultation", None) if self.storage is not None else None
        if callable(getter) and callable(sink):
            try:
                for row in getter(limit=500):
                    if not isinstance(row, Mapping) or row.get("status") not in {"queued", "running"}:
                        continue
                    identifier = str(row.get("consultation_id") or "")
                    if not identifier or identifier in consultation_ids:
                        continue
                    sink({**dict(row), "status": "interrupted", "member_metadata": row.get("member_metadata") or []})
            except Exception as exc:
                self._log("debug", "persisted consultation shutdown recovery failed", exc)
        self._executor.shutdown(wait=False, cancel_futures=True)
        closer = getattr(self.worker_registry, "close", None)
        if callable(closer):
            closer()

    shutdown = close


# Public aliases chosen to make the contract discoverable without requiring
# callers to know the internal ``Dynamic*`` names.
RouteEvidenceV1 = DynamicRouteEvidence
RouteEvidence = DynamicRouteEvidence
RouteDescriptor = RuntimeRouteDescriptor
RoutingRequest = DynamicRoutingRequest
SubtaskDispatch = DynamicSubtaskDispatch
SubtaskResult = DynamicSubtaskResult
SupervisorRouteDescriptor = RuntimeRouteDescriptor


__all__ = [
    "SUPERVISOR_SCHEMA",
    "EVENT_BOUNDARIES",
    "DynamicRouteEvidence",
    "RouteEvidence",
    "RouteEvidenceV1",
    "EvidenceResolver",
    "RuntimeRouteDescriptor",
    "RouteDescriptor",
    "SupervisorRouteDescriptor",
    "DynamicRoutingRequest",
    "RoutingRequest",
    "DynamicSubtaskDispatch",
    "SubtaskDispatch",
    "DynamicSubtaskResult",
    "SubtaskResult",
    "WorkerExecutor",
    "WorkerAdapter",
    "ProviderWorker",
    "WebWorker",
    "ChildAgentWorker",
    "NativeChildAgentWorker",
    "ExternalHarnessWorker",
    "DesktopAppWorker",
    "WorkerRegistry",
    "DynamicRouteSupervisor",
    "SupervisorError",
    "SupervisorValidationError",
]
