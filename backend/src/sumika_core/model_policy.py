"""Harness-neutral model catalog, quota observations, and routing policy.

The policy layer deliberately knows nothing about a particular Agent harness.
Adapters publish bounded model entries and the router applies the same safety,
quality, privacy, cost, and confirmation rules to every source.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlparse

from .provider_profiles import configured_models
from .route_pricing import CostEstimate, RoutePricingService


MODEL_POLICY_VERSION = "model-policy/v1"
QUOTA_TTL_SECONDS = 15 * 60

QUALITY_RANK = {
    "unknown": 0,
    "basic": 1,
    "standard": 2,
    "strong": 3,
    "premium": 4,
}
QUALITY_LABELS = tuple(QUALITY_RANK)
COST_RANK = {
    "free-limited": 0,
    "local": 1,
    "paid-low": 2,
    "paid-high": 3,
    "unknown": 4,
}
VALID_QUOTA_STATES = {
    "available",
    "low",
    "exhausted",
    "expired",
    "needs-auth",
    "blocked",
    "unknown",
    "not-applicable",
}
VALID_HEALTH_STATES = {"healthy", "ready", "available", "unknown", "unavailable", "error"}
VALID_AUTH_STATES = {"authorized", "not-required", "needs-auth", "unknown", "blocked"}
VALID_CONFIRMATION_MODES = {"recommendation-then-confirmation", "automatic", "manual"}
VALID_BUDGET_POLICIES = {"prefer-free", "free-only", "allow-paid", "no-paid"}


class ModelPolicyError(ValueError):
    """Raised when a policy object is malformed or cannot be evaluated."""


class ModelRouteSource(Protocol):
    """Runtime-neutral source of externally managed model routes.

    A source is deliberately narrower than an Agent runtime.  It publishes
    safe model observations and may optionally expose a quota snapshot; the
    policy layer never reads source credentials or invokes arbitrary scripts.
    """

    source_id: str

    def model_entries(
        self,
        *,
        refresh: bool = False,
        session_id: str | None = None,
    ) -> Iterable[Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[:limit]
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ModelPolicyError("text fields must not contain control characters")
    return text


def _safe_tuple(value: Any, *, limit: int = 32) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ModelPolicyError("list fields must be arrays of strings")
    result: list[str] = []
    for item in list(value)[:limit]:
        text = _safe_text(item, 120)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _safe_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:64]:
        name = _safe_text(key, 80).lower()
        if not name or any(token in name for token in ("secret", "password", "token", "cookie", "authorization", "api_key", "apikey")):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, float) and not math.isfinite(item):
                continue
            result[name] = item
        elif isinstance(item, list):
            result[name] = [entry for entry in item[:16] if isinstance(entry, (str, int, float, bool)) or entry is None]
    return result


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """One routable (or intentionally not-yet-routable) model endpoint."""

    route_id: str
    provider_id: str
    model_id: str
    display_name: str
    provider_profile_id: str | None = None
    harness_id: str | None = None
    capabilities: tuple[str, ...] = ("chat",)
    quality_tier: str = "unknown"
    cost_class: str = "unknown"
    processing_location: str = "cloud"
    auth_state: str = "unknown"
    quota_state: str = "unknown"
    health_state: str = "unknown"
    observed_at: str = field(default_factory=_utc_now)
    version: str | None = None
    source_kind: str = "provider"
    transport: str = "http"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("route_id", "provider_id", "model_id", "display_name"):
            value = _safe_text(getattr(self, field_name), 240)
            if field_name in {"route_id", "provider_id", "model_id"} and not value:
                raise ModelPolicyError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        profile_id = _safe_text(self.provider_profile_id, 120) if self.provider_profile_id else None
        object.__setattr__(self, "provider_profile_id", profile_id)
        harness_id = _safe_text(self.harness_id, 80) if self.harness_id else None
        object.__setattr__(self, "harness_id", harness_id)
        capabilities = _safe_tuple(self.capabilities)
        object.__setattr__(self, "capabilities", capabilities or ("chat",))
        quality = _safe_text(self.quality_tier, 40).lower() or "unknown"
        cost = _safe_text(self.cost_class, 40).lower() or "unknown"
        location = _safe_text(self.processing_location, 40).lower() or "cloud"
        auth = _safe_text(self.auth_state, 40).lower() or "unknown"
        quota = _safe_text(self.quota_state, 40).lower() or "unknown"
        health = _safe_text(self.health_state, 40).lower() or "unknown"
        if quality not in QUALITY_RANK:
            raise ModelPolicyError(f"invalid quality_tier: {quality}")
        if cost not in COST_RANK:
            raise ModelPolicyError(f"invalid cost_class: {cost}")
        if auth not in VALID_AUTH_STATES:
            raise ModelPolicyError(f"invalid auth_state: {auth}")
        if quota not in VALID_QUOTA_STATES:
            raise ModelPolicyError(f"invalid quota_state: {quota}")
        if health not in VALID_HEALTH_STATES:
            raise ModelPolicyError(f"invalid health_state: {health}")
        object.__setattr__(self, "quality_tier", quality)
        object.__setattr__(self, "cost_class", cost)
        object.__setattr__(self, "processing_location", location)
        object.__setattr__(self, "auth_state", auth)
        object.__setattr__(self, "quota_state", quota)
        object.__setattr__(self, "health_state", health)
        object.__setattr__(self, "version", _safe_text(self.version, 120) if self.version else None)
        object.__setattr__(self, "source_kind", _safe_text(self.source_kind, 80) or "provider")
        object.__setattr__(self, "transport", _safe_text(self.transport, 80) or "http")
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))

    @property
    def routable(self) -> bool:
        return (
            bool(self.model_id)
            and self.auth_state in {"authorized", "not-required"}
            and self.quota_state not in {"exhausted", "expired", "blocked", "needs-auth"}
            and self.health_state in {"healthy", "ready", "available"}
            and self.metadata.get("routable", True) is not False
        )

    @property
    def requires_browser(self) -> bool:
        return self.transport in {"browser", "browser-dom", "cdp"} or self.source_kind in {"web-chat", "desktop-automation"}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = list(self.capabilities)
        value["routable"] = self.routable
        value["requires_browser"] = self.requires_browser
        return value


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    route_id: str
    state: str = "unknown"
    remaining_min: float | None = None
    remaining_max: float | None = None
    used: float | None = None
    total: float | None = None
    unit: str = ""
    source: str = "unknown"
    checked_at: str = field(default_factory=_utc_now)
    expires_at: str | None = None
    confidence: str = "unknown"
    requires_auth: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        route_id = _safe_text(self.route_id, 240)
        if not route_id:
            raise ModelPolicyError("quota route_id is required")
        state = _safe_text(self.state, 40).lower() or "unknown"
        if state not in VALID_QUOTA_STATES:
            raise ModelPolicyError(f"invalid quota state: {state}")
        object.__setattr__(self, "route_id", route_id)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "unit", _safe_text(self.unit, 40))
        object.__setattr__(self, "source", _safe_text(self.source, 160) or "unknown")
        object.__setattr__(self, "confidence", _safe_text(self.confidence, 40) or "unknown")
        object.__setattr__(self, "detail", _safe_text(self.detail, 400))
        object.__setattr__(self, "expires_at", _safe_text(self.expires_at, 80) if self.expires_at else None)
        for name in ("remaining_min", "remaining_max", "used", "total"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ModelPolicyError(f"quota {name} must be a finite non-negative number")
            if isinstance(value, int):
                value = float(value)
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["stale"] = not _quota_is_fresh(self.expires_at)
        return value


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    task_kind: str = "chat"
    difficulty: str = "auto"
    risk: str = "normal"
    context_size: int = 0
    required_capabilities: tuple[str, ...] = ()
    latency_target_ms: int | None = None
    privacy_constraints: tuple[str, ...] = ()
    budget_policy: str = "prefer-free"
    confirmation_mode: str = "recommendation-then-confirmation"
    preferred_route: str | None = None
    min_quality_tier: str | None = None
    character_id: str | None = None
    agent_preset_id: str | None = None
    task_text: str = ""
    # Runtime-neutral context used by DynamicRouteSupervisor.  These fields
    # are optional so existing model-policy callers and persisted requests
    # remain wire-compatible.
    trigger_event: str | None = None
    task_stage: str | None = None
    remaining_budget: float | None = None
    parent_turn_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_kind", _safe_text(self.task_kind, 80).lower() or "chat")
        difficulty = _safe_text(self.difficulty, 40).lower() or "auto"
        risk = _safe_text(self.risk, 40).lower() or "normal"
        if difficulty not in {"auto", "trivial", "basic", "moderate", "complex", "critical"}:
            raise ModelPolicyError(f"invalid difficulty: {difficulty}")
        if risk not in {"low", "normal", "high", "critical"}:
            raise ModelPolicyError(f"invalid risk: {risk}")
        object.__setattr__(self, "difficulty", difficulty)
        object.__setattr__(self, "risk", risk)
        context = self.context_size
        if isinstance(context, bool) or not isinstance(context, int) or context < 0 or context > 10_000_000:
            raise ModelPolicyError("context_size must be an integer from 0 to 10000000")
        latency = self.latency_target_ms
        if latency is not None and (isinstance(latency, bool) or not isinstance(latency, int) or latency < 1 or latency > 3_600_000):
            raise ModelPolicyError("latency_target_ms must be between 1 and 3600000")
        policy = _safe_text(self.budget_policy, 40).lower() or "prefer-free"
        mode = _safe_text(self.confirmation_mode, 80).lower() or "recommendation-then-confirmation"
        if policy not in VALID_BUDGET_POLICIES:
            raise ModelPolicyError(f"invalid budget_policy: {policy}")
        if mode not in VALID_CONFIRMATION_MODES:
            raise ModelPolicyError(f"invalid confirmation_mode: {mode}")
        quality = _safe_text(self.min_quality_tier, 40).lower() if self.min_quality_tier else None
        if quality and quality not in QUALITY_RANK:
            raise ModelPolicyError(f"invalid min_quality_tier: {quality}")
        object.__setattr__(self, "budget_policy", policy)
        object.__setattr__(self, "confirmation_mode", mode)
        object.__setattr__(self, "required_capabilities", _safe_tuple(self.required_capabilities))
        object.__setattr__(self, "privacy_constraints", _safe_tuple(self.privacy_constraints))
        object.__setattr__(self, "preferred_route", _safe_text(self.preferred_route, 240) if self.preferred_route else None)
        object.__setattr__(self, "min_quality_tier", quality)
        object.__setattr__(self, "character_id", _safe_text(self.character_id, 120) if self.character_id else None)
        object.__setattr__(self, "agent_preset_id", _safe_text(self.agent_preset_id, 160) if self.agent_preset_id else None)
        object.__setattr__(self, "task_text", _safe_text(self.task_text, 4000))
        trigger = _safe_text(self.trigger_event, 80).lower() if self.trigger_event else None
        stage = _safe_text(self.task_stage, 80).lower() if self.task_stage else None
        if trigger and any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._:-" for char in trigger):
            raise ModelPolicyError("trigger_event contains unsupported characters")
        if stage and any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._:-" for char in stage):
            raise ModelPolicyError("task_stage contains unsupported characters")
        budget = self.remaining_budget
        if budget is not None:
            if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(float(budget)) or float(budget) < 0:
                raise ModelPolicyError("remaining_budget must be a finite non-negative number")
            budget = round(float(budget), 6)
        parent_turn = _safe_text(self.parent_turn_id, 240) if self.parent_turn_id else None
        object.__setattr__(self, "trigger_event", trigger)
        object.__setattr__(self, "task_stage", stage)
        object.__setattr__(self, "remaining_budget", budget)
        object.__setattr__(self, "parent_turn_id", parent_turn)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_capabilities"] = list(self.required_capabilities)
        value["privacy_constraints"] = list(self.privacy_constraints)
        return value


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    status: str
    selected_route: str | None
    selected_entry: dict[str, Any] | None
    alternatives: list[dict[str, Any]]
    quality_gate: dict[str, Any]
    reason_codes: list[str]
    estimated_cost: str
    quota_impact: dict[str, Any]
    confidence: float
    requires_confirmation: bool
    cost_estimate: dict[str, Any] = field(default_factory=lambda: {"schema": "route-pricing/v1", "status": "unknown"})
    policy_version: str = MODEL_POLICY_VERSION
    valid_until: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["confidence"] = round(max(0.0, min(1.0, float(self.confidence))), 3)
        return value


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    route_id: str
    task_kind: str
    model_version: str
    success: bool
    tool_success: bool | None = None
    retry_count: int = 0
    latency_ms: float | None = None
    estimated_cost: float | None = None
    quality_passed: bool | None = None
    user_correction: bool | None = None
    observed_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_difficulty(task_kind: str = "chat", text: str = "") -> str:
    """Conservative deterministic classifier used before a real evaluator exists."""

    kind = str(task_kind or "chat").lower()
    body = str(text or "").lower()
    if any(token in body for token in ("delete", "publish", "deploy", "credential", "payment", "权限")):
        return "critical"
    if kind in {"multi-file", "refactor", "migration", "workspace", "mcp", "browser-write"}:
        return "complex"
    if kind in {"code", "tool", "plan", "review", "browser"} or len(body) > 1200:
        return "moderate"
    if kind in {"greeting", "classification", "summarize"} or len(body) < 80:
        return "basic"
    return "moderate"


def _required_quality(request: RoutingRequest) -> str:
    if request.min_quality_tier:
        baseline = request.min_quality_tier
    else:
        difficulty = request.difficulty
        if difficulty == "auto":
            difficulty = infer_difficulty(request.task_kind, request.task_text)
        baseline = {
            "trivial": "basic",
            "basic": "basic",
            "moderate": "standard",
            "complex": "strong",
            "critical": "premium",
        }[difficulty]
    if request.risk in {"high", "critical"}:
        baseline = QUALITY_LABELS[min(len(QUALITY_LABELS) - 1, QUALITY_RANK[baseline] + 1)]
    return baseline


def _privacy_allows(entry: ModelCatalogEntry, constraints: tuple[str, ...]) -> bool:
    values = {item.lower() for item in constraints}
    if not values:
        return True
    location = entry.processing_location.lower()
    if "local-only" in values or "disallow-cloud" in values:
        if location != "local":
            return False
    if "cloud-only" in values and location != "cloud":
        return False
    if "no-browser" in values and entry.requires_browser:
        return False
    if "no-third-party" in values and entry.source_kind not in {"builtin", "local", "provider"}:
        return False
    return True


class ModelRouter:
    """Apply policy in a fixed order and never silently upgrade to paid work."""

    def decide(
        self,
        request: RoutingRequest,
        entries: Iterable[ModelCatalogEntry],
        quotas: Mapping[str, QuotaSnapshot] | None = None,
        cost_estimates: Mapping[str, CostEstimate] | None = None,
    ) -> RoutingDecision:
        if not isinstance(request, RoutingRequest):
            raise ModelPolicyError("request must be RoutingRequest")
        quota_map = quotas or {}
        estimate_map = cost_estimates or {}
        required_quality = _required_quality(request)
        quality_rank = QUALITY_RANK[required_quality]
        rejected: dict[str, int] = {}
        candidates: list[ModelCatalogEntry] = []

        def reject(code: str) -> None:
            rejected[code] = rejected.get(code, 0) + 1

        for entry in entries:
            if not isinstance(entry, ModelCatalogEntry):
                continue
            if not _privacy_allows(entry, request.privacy_constraints):
                reject("privacy_constraint")
                continue
            if not set(request.required_capabilities).issubset(set(entry.capabilities)):
                reject("missing_capability")
                continue
            if entry.auth_state not in {"authorized", "not-required"}:
                reject("auth_not_ready")
                continue
            if entry.health_state not in {"healthy", "ready", "available"}:
                reject("health_not_ready")
                continue
            quota = quota_map.get(entry.route_id)
            quota_state = quota.state if quota else entry.quota_state
            if quota_state in {"exhausted", "expired", "blocked", "needs-auth"}:
                reject(f"quota_{quota_state}")
                continue
            if QUALITY_RANK[entry.quality_tier] < quality_rank:
                reject("quality_gate")
                continue
            if entry.metadata.get("routable", True) is False:
                reject("adapter_not_routable")
                continue
            candidates.append(entry)

        if not candidates:
            reasons = ["no_compatible_route", f"quality_required:{required_quality}"]
            reasons.extend(f"{key}:{value}" for key, value in sorted(rejected.items()))
            return RoutingDecision(
                status="no-compatible-route",
                selected_route=None,
                selected_entry=None,
                alternatives=[],
                quality_gate={"required": required_quality, "passed": False},
                reason_codes=reasons,
                estimated_cost="unknown",
                quota_impact={"state": "unknown"},
                confidence=0.2,
                requires_confirmation=True,
                valid_until=_expiry(5),
            )

        preferred = None
        if request.preferred_route:
            preferred = next((item for item in candidates if item.route_id == request.preferred_route), None)
            if preferred is not None:
                candidates = [preferred, *[item for item in candidates if item is not preferred]]

        def sort_key(entry: ModelCatalogEntry) -> tuple[Any, ...]:
            preference = 0 if preferred is entry else 1
            quota_state = quota_map.get(entry.route_id).state if entry.route_id in quota_map else entry.quota_state
            quota_rank = {"available": 0, "low": 1, "not-applicable": 1, "unknown": 2}.get(quota_state, 3)
            estimate = estimate_map.get(entry.route_id)
            cash_known = bool(estimate and estimate.status == "known" and estimate.cash_max is not None)
            provider_known = bool(estimate and estimate.status == "known" and estimate.provider_charge_max is not None)
            price_rank = (
                0 if cash_known else 1 if provider_known else 2,
                float(estimate.cash_max) if cash_known else float(estimate.provider_charge_max) if provider_known else math.inf,
            )
            latency = entry.metadata.get("p95_latency_ms", 10_000)
            if not isinstance(latency, (int, float)) or isinstance(latency, bool):
                latency = 10_000
            return (preference, COST_RANK[entry.cost_class], price_rank, quota_rank, -QUALITY_RANK[entry.quality_tier], latency, entry.route_id)

        candidates.sort(key=sort_key)
        selected = candidates[0]
        # An unknown price is not treated as free.  It may remain a candidate
        # under the default preference policy, but it must be confirmed and
        # is rejected by an explicit free-only/no-paid policy.
        cost_requires_confirmation = selected.cost_class in {"paid-low", "paid-high", "unknown"}
        if request.budget_policy in {"free-only", "no-paid"} and cost_requires_confirmation:
            free = next((item for item in candidates if item.cost_class in {"free-limited", "local"}), None)
            if free is None:
                return RoutingDecision(
                    status="no-compatible-route",
                    selected_route=None,
                    selected_entry=None,
                    alternatives=[item.to_dict() for item in candidates[:8]],
                    quality_gate={"required": required_quality, "passed": False},
                    reason_codes=["paid_disallowed", "no_free_candidate_meets_quality"],
                    estimated_cost="blocked",
                    quota_impact={"state": "unknown"},
                    confidence=0.7,
                    requires_confirmation=True,
                    valid_until=_expiry(5),
                )
            selected = free
            cost_requires_confirmation = False

        requires_confirmation = request.confirmation_mode != "automatic" or cost_requires_confirmation
        status = "needs-confirmation" if requires_confirmation else "selected"
        reasons = [
            "privacy_and_permissions_passed",
            "quality_gate_passed",
            "free_or_local_preferred" if not cost_requires_confirmation else "cost_or_quota_confirmation_required",
        ]
        if request.preferred_route and preferred is selected:
            reasons.append("user_preference")
        if selected.requires_browser:
            reasons.append("browser_authorization_required")
        quota = quota_map.get(selected.route_id)
        quota_state = quota.state if quota else selected.quota_state
        quota_impact = {
            "state": quota_state,
            "source": quota.source if quota else "catalog",
            "estimated": "unknown" if quota_state in {"unknown", "needs-auth"} else "within-observed-budget",
        }
        confidence = 0.85
        if selected.quota_state == "unknown" or selected.health_state == "unknown":
            confidence -= 0.2
        return RoutingDecision(
            status=status,
            selected_route=selected.route_id,
            selected_entry=selected.to_dict(),
            alternatives=[item.to_dict() for item in candidates[1:8]],
            quality_gate={"required": required_quality, "selected": selected.quality_tier, "passed": True},
            reason_codes=reasons,
            estimated_cost=selected.cost_class,
            quota_impact=quota_impact,
            confidence=confidence,
            requires_confirmation=requires_confirmation,
            cost_estimate=(estimate_map.get(selected.route_id) or CostEstimate(selected.route_id, "unknown", unknown_reasons=("pricing-not-observed",))).to_dict(),
            valid_until=_expiry(5),
        )


def _expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class ModelCatalogStore:
    """Small bounded JSON store for observations; it never stores credentials."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.path = (Path(data_dir) / "model-policy" / "catalog.json") if data_dir else None
        self._lock = threading.RLock()
        self._entries: dict[str, ModelCatalogEntry] = {}
        self._quotas: dict[str, QuotaSnapshot] = {}
        self.load()

    def load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        with self._lock:
            for raw in payload.get("entries", [])[:256] if isinstance(payload.get("entries"), list) else []:
                try:
                    if not isinstance(raw, dict):
                        continue
                    # ``to_dict`` includes presentation-only properties;
                    # ignore them when restoring the persisted contract.
                    values = {
                        key: item
                        for key, item in raw.items()
                        if key in ModelCatalogEntry.__dataclass_fields__
                    }
                    entry = ModelCatalogEntry(**values)
                except (TypeError, ModelPolicyError):
                    continue
                self._entries[entry.route_id] = entry
            for raw in payload.get("quotas", [])[:256] if isinstance(payload.get("quotas"), list) else []:
                try:
                    if not isinstance(raw, dict):
                        continue
                    quota_values = {
                        key: item
                        for key, item in raw.items()
                        if key in QuotaSnapshot.__dataclass_fields__
                    }
                    quota = QuotaSnapshot(**quota_values)
                except (TypeError, ModelPolicyError):
                    continue
                self._quotas[quota.route_id] = quota

    def upsert_entries(self, entries: Iterable[ModelCatalogEntry]) -> None:
        with self._lock:
            for entry in entries:
                if isinstance(entry, ModelCatalogEntry):
                    self._entries[entry.route_id] = entry
            if len(self._entries) > 512:
                self._entries = dict(list(self._entries.items())[-512:])

    def upsert_quota(self, snapshot: QuotaSnapshot) -> None:
        with self._lock:
            self._quotas[snapshot.route_id] = snapshot

    def entries(self) -> list[ModelCatalogEntry]:
        with self._lock:
            return list(self._entries.values())

    def quotas(self) -> dict[str, QuotaSnapshot]:
        with self._lock:
            return dict(self._quotas)

    def quota(self, route_id: str) -> QuotaSnapshot | None:
        with self._lock:
            return self._quotas.get(route_id)

    def save(self) -> None:
        if self.path is None:
            return
        payload = {
            "schema": MODEL_POLICY_VERSION,
            "entries": [entry.to_dict() for entry in self.entries()],
            "quotas": [quota.to_dict() for quota in self.quotas().values()],
            "updated_at": _utc_now(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            return


class ModelPolicyService:
    """Build model observations from profiles and an optional Agent runtime."""

    WEB_CHAT_SOURCES = (
        ("deepseek-web", "DeepSeek 网页聊天"),
        ("chatgpt-web", "ChatGPT 网页聊天"),
        ("zhipu-web", "智谱网页聊天"),
        ("qwen-web", "Qwen 网页聊天"),
        ("kimi-web", "Kimi 网页聊天"),
        ("doubao-web", "豆包网页聊天"),
    )
    quota_ttl_seconds = QUOTA_TTL_SECONDS

    def __init__(
        self,
        provider_profiles: Any = None,
        agent: Any = None,
        data_dir: str | Path | None = None,
        logger: Any = None,
        web_chat: Any = None,
        external_route_sources: Iterable[Any] | None = None,
        route_sources: Iterable[Any] | None = None,
    ) -> None:
        self.provider_profiles = provider_profiles
        self.agent = agent
        self.logger = logger
        self.web_chat = web_chat
        self._route_sources: dict[str, Any] = {}
        self.store = ModelCatalogStore(data_dir)
        self.pricing = RoutePricingService(provider_profiles, data_dir, logger=logger)
        self.router = ModelRouter()
        self._quota_lock = threading.RLock()
        self._runtime_quota_cache: dict[str, Any] | None = None
        self._runtime_quota_checked_at = 0.0
        # ``route_sources`` is a compatibility spelling for callers that use
        # the shorter name.  Keep one registry so a source cannot be listed
        # twice when both aliases are supplied.
        for source in tuple(external_route_sources or ()) + tuple(route_sources or ()):
            self.register_route_source(source)

    def register_route_source(self, source: Any, *, source_id: str | None = None) -> str:
        """Register an external model source without probing it.

        Registration is dependency injection only.  Discovery occurs at an
        explicit ``catalog(refresh=True)`` boundary, which keeps Core startup
        side-effect free and lets a future Harness adapter be added without
        changing this policy service.
        """

        if source is None:
            raise ModelPolicyError("route source is required")
        raw_id = source_id or getattr(source, "source_id", None) or getattr(source, "runtime_id", None)
        identifier = _safe_text(raw_id, 120).lower()
        if not identifier:
            identifier = f"source-{len(self._route_sources) + 1}"
        if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._:-" for char in identifier):
            raise ModelPolicyError("route source id is invalid")
        self._route_sources[identifier] = source
        return identifier

    def unregister_route_source(self, source_id: str) -> bool:
        identifier = _safe_text(source_id, 120).lower()
        if not identifier:
            return False
        return self._route_sources.pop(identifier, None) is not None

    def route_sources(self) -> list[Any]:
        return list(self._route_sources.values())

    def external_entries(
        self,
        *,
        refresh: bool = False,
        session_id: str | None = None,
    ) -> list[ModelCatalogEntry]:
        """Return the current projection from registered external sources."""

        return self._external_entries(refresh=refresh, session_id=session_id)

    def catalog(self, *, refresh: bool = False, session_id: str | None = None) -> dict[str, Any]:
        if refresh:
            self._refresh_profile_health()
        pricing_refreshed = self.pricing.refresh_profiles(force=refresh)
        quota_refreshed = self._refresh_quotas_if_due(force=refresh)
        runtime_quota = self._runtime_quota_status(force=refresh)
        entries = self._profile_entries()
        entries.extend(self._runtime_entries(session_id, runtime_quota=runtime_quota))
        entries.extend(self._external_entries(refresh=refresh, session_id=session_id))
        entries.extend(self._web_entries())
        self.store.upsert_entries(entries)
        self.store.save()
        source_ids = list(self._route_sources)
        quotas = self.store.quotas()
        return {
            "policy_version": MODEL_POLICY_VERSION,
            "entries": [entry.to_dict() for entry in entries],
            "quotas": [quota.to_dict() for quota in quotas.values()],
            "checked_at": _utc_now(),
            "refresh_requested": bool(refresh),
            "quota_refresh_performed": quota_refreshed,
            "runtime_quota": runtime_quota,
            "pricing": {
                "schema": "route-pricing/v1",
                "snapshots": [item.to_dict() for item in self.pricing.store.list()],
                "errors": dict(self.pricing.errors),
                "refresh_performed": pricing_refreshed,
            },
            "sources": ["provider-profiles", "agent-runtime", "external-route-sources", *source_ids, "browser-web-chat"],
        }

    def pricing_catalog(
        self,
        *,
        refresh: bool = False,
        provider_profile_id: str | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        """Expose bounded pricing evidence without Provider credentials."""

        return self.pricing.catalog(
            refresh=refresh,
            provider_profile_id=provider_profile_id,
            model_id=model_id,
        )

    def decide(
        self,
        params: Mapping[str, Any] | RoutingRequest,
        *,
        session_id: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Evaluate a request against the current catalog.

        ``session_id`` is intentionally a separate argument: it is an opaque
        harness session identifier used only to discover session-scoped model
        choices, and is not part of the persisted routing contract.
        """

        request = params if isinstance(params, RoutingRequest) else routing_request_from_dict(params)
        if session_id is not None:
            session_id = _safe_text(session_id, 240)
            if not session_id:
                session_id = None
        catalog = self.catalog(refresh=refresh, session_id=session_id)
        entries = [ModelCatalogEntry(**self._entry_constructor(item)) for item in catalog["entries"]]
        estimates = {
            entry.route_id: self.pricing.estimate(entry.to_dict(), request.to_dict())
            for entry in entries
        }
        decision = self.router.decide(request, entries, self.store.quotas(), estimates)
        return {"request": request.to_dict(), "decision": decision.to_dict(), "catalog_checked_at": catalog["checked_at"]}

    def preflight(
        self,
        params: Mapping[str, Any] | RoutingRequest,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a live, bounded health/quota check before an Agent turn.

        This is deliberately separate from ``decide`` so callers can choose
        an explicit preflight at a user-visible boundary without changing the
        inexpensive, read-only catalog RPC semantics.
        """

        return self.decide(params, session_id=session_id, refresh=True)

    def quota_status(self, *, refresh: bool = False, force: bool = False) -> dict[str, Any]:
        refreshed = self._refresh_quotas_if_due(force=bool(refresh or force))
        self.store.save()
        runtime_quota = self._runtime_quota_status(force=bool(refresh or force))
        external: list[dict[str, Any]] = []
        for source_id, source in list(self._route_sources.items()):
            method = getattr(source, "quota_status", None)
            if not callable(method):
                continue
            try:
                value = method({})
            except TypeError:
                try:
                    value = method()
                except Exception as error:
                    self._log_source_error(source_id, error)
                    continue
            except Exception as error:
                self._log_source_error(source_id, error)
                continue
            if isinstance(value, Mapping):
                item = {"source_id": source_id}
                for key in ("state", "source", "checked_at", "expires_at", "unit", "detail", "confidence"):
                    if value.get(key) is not None:
                        item[key] = _safe_text(value.get(key), 240)
                for key in ("remaining", "remaining_min", "remaining_max", "used", "total"):
                    number = value.get(key)
                    if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and number >= 0:
                        item[key] = float(number)
                external.append(item)
        return {
            "policy_version": MODEL_POLICY_VERSION,
            "checked_at": _utc_now(),
            "snapshots": [item.to_dict() for item in self.store.quotas().values()],
            "refresh_requested": bool(refresh),
            "refresh_performed": refreshed,
            "runtime": runtime_quota,
            "external": external,
        }

    def _entry_constructor(self, value: dict[str, Any]) -> dict[str, Any]:
        # ``to_dict`` adds presentation-only fields that the dataclass ignores.
        return {key: item for key, item in value.items() if key in ModelCatalogEntry.__dataclass_fields__}

    def _refresh_profile_health(self) -> None:
        if self.provider_profiles is None:
            return
        try:
            profiles = self.provider_profiles.list(include_archived=False)
        except Exception:
            return
        for profile in profiles:
            profile_id = profile.get("id") if isinstance(profile, dict) else None
            if not profile_id:
                continue
            try:
                self.provider_profiles.health(str(profile_id))
            except Exception as error:
                if self.logger:
                    self.logger.info("model policy profile refresh failed profile=%s error_type=%s", profile_id, type(error).__name__)

    def _profile_entries(self) -> list[ModelCatalogEntry]:
        if self.provider_profiles is None:
            return []
        try:
            profiles = self.provider_profiles.list(include_archived=False)
        except Exception:
            return []
        entries: list[ModelCatalogEntry] = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            profile_id = _safe_text(profile.get("id"), 120)
            config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
            template = _safe_text(profile.get("template_id"), 80).lower()
            location = _safe_text(profile.get("resolved_processing_location") or profile.get("processing_location") or "cloud", 40).lower()
            status = _safe_text(profile.get("status"), 40).lower()
            has_secrets = profile.get("has_secrets") is True
            auth = "not-required" if location == "local" else ("authorized" if has_secrets else "needs-auth")
            health = {"available": "healthy", "unavailable": "unavailable", "draft": "unknown", "error": "error"}.get(status, "unknown")
            cost = "local" if location == "local" else "unknown"
            pricing_config = config.get("pricing") if isinstance(config.get("pricing"), dict) else {}
            billing_group = _safe_text(pricing_config.get("billing_group"), 160)
            model_rows = configured_models(config)
            if not model_rows:
                model_rows = [{"id": "unconfigured", "name": "未配置", "enabled": False, "capabilities": ["chat"], "quality_tier": "unknown", "cost_class": cost, "health_state": "unknown"}]
            for model_row in model_rows:
                model = _safe_text(model_row.get("id"), 240)
                if not model:
                    continue
                quality = _quality_from_model(model)
                model_enabled = model_row.get("enabled", True) is True
                model_health = _safe_text(model_row.get("health_state"), 40).lower() or "unknown"
                # A profile-level health check is authoritative for legacy
                # rows and for models that have not yet received a per-model
                # observation. Explicit per-model failures remain blocked.
                effective_health = health
                if model_health in {"unavailable", "error"}:
                    effective_health = model_health
                elif model_health in {"healthy", "ready", "available"} and health in {"healthy", "ready", "available"}:
                    effective_health = model_health
                model_quality = _safe_text(model_row.get("quality_tier"), 40).lower()
                if not model_quality or model_quality == "unknown":
                    model_quality = quality
                if model_quality not in QUALITY_RANK:
                    model_quality = quality
                # A model name or imported row cannot prove that a cloud
                # route is free. Only profile-scoped pricing evidence may
                # refine the default unknown cloud cost below.
                model_cost = "local" if location == "local" else "unknown"
                pricing = self.pricing.projection(profile_id, model, billing_group or None)
                if location != "local" and pricing.get("cost_class") in COST_RANK:
                    model_cost = str(pricing["cost_class"])
                capabilities = model_row.get("capabilities")
                if isinstance(capabilities, str):
                    capabilities = (capabilities,)
                if not isinstance(capabilities, (list, tuple, set)):
                    capabilities = ("chat",)
                route_id = f"profile:{profile_id}:{model}"
                entries.append(
                    ModelCatalogEntry(
                        route_id=route_id,
                        provider_id=_safe_text(profile.get("adapter_id") or template or "provider", 120),
                        model_id=model,
                        display_name=f"{_safe_text(profile.get('name') or profile_id, 160)} · {model_row.get('name') or model}",
                        provider_profile_id=profile_id,
                        capabilities=tuple(str(item) for item in capabilities),
                        quality_tier=model_quality,
                        cost_class=model_cost,
                        processing_location=location,
                        auth_state=auth,
                        quota_state="not-applicable" if location == "local" else "unknown",
                        health_state=effective_health,
                        source_kind="local" if location == "local" else "provider",
                        transport="http",
                        metadata={
                            "template_id": template,
                            "model_enabled": model_enabled,
                            "model_config": model_row,
                            "pricing_ref": pricing.get("pricing_ref"),
                            "pricing_status": pricing.get("pricing_status", "unknown"),
                            "billing_group": pricing.get("billing_group") or billing_group,
                            "pricing_currency": pricing.get("pricing_currency"),
                            "pricing_source": pricing.get("pricing_source"),
                            "routable": bool(model_enabled and status == "available" and effective_health in {"healthy", "ready", "available"}),
                        },
                    )
                )
        return entries

    def _runtime_entries(
        self,
        session_id: str | None,
        *,
        runtime_quota: Mapping[str, Any] | None = None,
    ) -> list[ModelCatalogEntry]:
        if self.agent is None:
            return []
        try:
            if not self.agent.status().get("ready") or not self.agent.supports("models"):
                return []
            if session_id:
                value = self.agent.session_models({"session_id": session_id})
            else:
                # A recommendation must be possible before creating a
                # session.  Only adapters that expose a public, unscoped
                # model directory participate here; older runtimes remain
                # session-scoped and are intentionally omitted.
                runtime_models = getattr(self.agent, "runtime_models", None)
                if not callable(runtime_models):
                    return []
                value = runtime_models({})
        except Exception:
            return []
        quota_state = _safe_text((runtime_quota or {}).get("state"), 40).lower() or "unknown"
        if quota_state not in VALID_QUOTA_STATES:
            quota_state = "unknown"
        quota_source = _safe_text((runtime_quota or {}).get("source"), 160) or "agent-runtime"
        entries: list[ModelCatalogEntry] = []
        for group in value.get("groups", []) if isinstance(value, dict) else []:
            if not isinstance(group, dict):
                continue
            provider = _safe_text(group.get("id"), 120)
            for model in group.get("models", []) if isinstance(group.get("models"), list) else []:
                if not isinstance(model, dict):
                    continue
                model_id = _safe_text(model.get("id"), 240)
                if not provider or not model_id:
                    continue
                entries.append(
                    ModelCatalogEntry(
                        route_id=f"harness:{getattr(self.agent, 'runtime_id', 'agent')}:{provider}:{model_id}",
                        provider_id=provider,
                        model_id=model_id,
                        display_name=f"{_safe_text(group.get('name') or provider, 160)} · {_safe_text(model.get('name') or model_id, 180)}",
                        harness_id=getattr(self.agent, "runtime_id", None),
                        quality_tier=_quality_from_model(model_id),
                        cost_class="unknown",
                        processing_location="cloud",
                        auth_state="authorized",
                        quota_state=quota_state,
                        health_state="healthy",
                        source_kind="harness",
                        transport="runtime",
                        metadata={"quota_source": quota_source},
                    )
                )
        return entries

    def _external_entries(
        self,
        *,
        refresh: bool = False,
        session_id: str | None = None,
    ) -> list[ModelCatalogEntry]:
        """Project registered external Harness sources into the catalog.

        Sources are intentionally duck-typed at this boundary.  This keeps
        the policy package independent from DSH, ZCode, or a future Harness,
        while still accepting a small community adapter that implements only
        ``model_entries``.  A source may return an envelope (``entries`` or
        ``groups``) or already-normalized ``ModelCatalogEntry`` objects.
        """

        result: list[ModelCatalogEntry] = []
        for source_id, source in list(self._route_sources.items()):
            method = getattr(source, "model_entries", None)
            if not callable(method):
                method = getattr(source, "entries", None)
            if not callable(method):
                continue
            try:
                values = method(refresh=bool(refresh), session_id=session_id)
            except TypeError:
                try:
                    values = method(bool(refresh))
                except Exception as error:
                    self._log_source_error(source_id, error)
                    continue
            except Exception as error:
                self._log_source_error(source_id, error)
                continue
            rows = self._source_rows(values)
            for raw in rows[:512]:
                try:
                    entry = self._normalize_external_entry(raw, source_id)
                except (ModelPolicyError, TypeError, ValueError) as error:
                    self._log_source_error(source_id, error)
                    continue
                if entry is not None:
                    result.append(entry)
            # Optional source quota observations are persisted only as the
            # existing bounded QuotaSnapshot projection.  A source that does
            # not expose this method simply leaves quota state as unknown.
            if refresh:
                self._refresh_external_quota(source_id, source, result)
        return result

    def _log_source_error(self, source_id: str, error: Exception) -> None:
        if self.logger:
            self.logger.info(
                "model policy external source failed source=%s error_type=%s",
                source_id,
                type(error).__name__,
            )

    @staticmethod
    def _source_rows(value: Any) -> list[Any]:
        if isinstance(value, ModelCatalogEntry):
            return [value]
        if isinstance(value, Mapping):
            for key in ("entries", "models", "routes", "items"):
                nested = value.get(key)
                if isinstance(nested, (list, tuple)):
                    return list(nested)
            groups = value.get("groups")
            if isinstance(groups, list):
                rows: list[dict[str, Any]] = []
                for group in groups[:128]:
                    if not isinstance(group, Mapping):
                        continue
                    provider = group.get("id") or group.get("provider_id") or group.get("providerId")
                    group_name = group.get("name") or provider
                    models = group.get("models")
                    if not isinstance(models, list):
                        continue
                    for model in models[:128]:
                        if isinstance(model, Mapping):
                            rows.append({"provider_id": provider, "provider_name": group_name, **dict(model)})
                return rows
            return [dict(value)]
        if isinstance(value, (list, tuple)):
            return list(value)
        return []

    @staticmethod
    def _normalize_external_entry(raw: Any, source_id: str) -> ModelCatalogEntry | None:
        if isinstance(raw, ModelCatalogEntry):
            metadata = dict(raw.metadata)
            metadata.setdefault("external_source_id", source_id)
            metadata.setdefault("external_harness", True)
            if "routable" not in metadata:
                metadata["routable"] = raw.routable
            if raw.source_kind in {"provider", "harness"}:
                return replace(raw, harness_id=raw.harness_id or source_id, source_kind="external-harness", metadata=metadata)
            return replace(raw, metadata=metadata)
        if not isinstance(raw, Mapping):
            return None
        value = dict(raw)
        provider = str(value.get("provider_id") or value.get("providerId") or value.get("provider") or source_id).strip()
        model = str(value.get("model_id") or value.get("modelId") or value.get("id") or "").strip()
        if not provider or not model:
            return None
        route_id = str(value.get("route_id") or value.get("routeId") or "").strip()
        if not route_id:
            route_id = f"harness:{source_id}:{provider}:{model}"
        display = str(value.get("display_name") or value.get("displayName") or value.get("label") or value.get("name") or model).strip()
        capabilities = value.get("capabilities")
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        if not isinstance(capabilities, (list, tuple, set)):
            capabilities = ["chat", "code"]
        metadata = dict(value.get("metadata") or {}) if isinstance(value.get("metadata"), Mapping) else {}
        metadata.setdefault("external_source_id", source_id)
        metadata.setdefault("external_harness", True)
        if "routable" not in metadata:
            metadata["routable"] = bool(value.get("routable", False))
        if "quota_consent" not in metadata and value.get("quota_consent") is not None:
            metadata["quota_consent"] = value.get("quota_consent")
        return ModelCatalogEntry(
            route_id=route_id,
            provider_id=provider,
            model_id=model,
            display_name=display,
            provider_profile_id=value.get("provider_profile_id") or value.get("providerProfileId"),
            harness_id=str(value.get("harness_id") or value.get("harnessId") or source_id),
            capabilities=tuple(str(item) for item in capabilities),
            quality_tier=str(value.get("quality_tier") or value.get("qualityTier") or "unknown"),
            cost_class=str(value.get("cost_class") or value.get("costClass") or "unknown"),
            processing_location=str(value.get("processing_location") or value.get("processingLocation") or "cloud"),
            auth_state=str(value.get("auth_state") or value.get("authState") or "unknown"),
            quota_state=str(value.get("quota_state") or value.get("quotaState") or "unknown"),
            health_state=str(value.get("health_state") or value.get("healthState") or "unknown"),
            observed_at=str(value.get("observed_at") or value.get("observedAt") or _utc_now()),
            version=value.get("version"),
            source_kind="external-harness",
            transport=str(value.get("transport") or "stdio"),
            metadata=metadata,
        )

    def _refresh_external_quota(
        self,
        source_id: str,
        source: Any,
        entries: list[ModelCatalogEntry],
    ) -> None:
        method = getattr(source, "quota_status", None)
        if not callable(method):
            return
        try:
            value = method({})
        except TypeError:
            try:
                value = method()
            except Exception as error:
                self._log_source_error(source_id, error)
                return
        except Exception as error:
            self._log_source_error(source_id, error)
            return
        if not isinstance(value, Mapping):
            return
        snapshots = value.get("snapshots")
        if isinstance(snapshots, list):
            for item in snapshots[:128]:
                if not isinstance(item, Mapping) or not item.get("route_id"):
                    continue
                try:
                    self.store.upsert_quota(QuotaSnapshot(**{key: item[key] for key in QuotaSnapshot.__dataclass_fields__ if key in item}))
                except (ModelPolicyError, TypeError, ValueError):
                    continue
            return
        state = str(value.get("state") or "unknown").lower()
        if state not in VALID_QUOTA_STATES:
            state = "unknown"
        source_name = _safe_text(value.get("source") or f"{source_id}-quota", 160)
        for entry in entries:
            if entry.harness_id != source_id:
                continue
            self.store.upsert_quota(
                QuotaSnapshot(
                    route_id=entry.route_id,
                    state=state,
                    remaining_min=value.get("remaining_min") if isinstance(value.get("remaining_min"), (int, float)) else value.get("remaining"),
                    remaining_max=value.get("remaining_max") if isinstance(value.get("remaining_max"), (int, float)) else value.get("remaining"),
                    used=value.get("used") if isinstance(value.get("used"), (int, float)) else None,
                    total=value.get("total") if isinstance(value.get("total"), (int, float)) else None,
                    unit=str(value.get("unit") or ""),
                    source=source_name,
                    checked_at=str(value.get("checked_at") or _utc_now()),
                    expires_at=value.get("expires_at"),
                    confidence=str(value.get("confidence") or "observed"),
                    requires_auth=bool(value.get("requires_auth")),
                    detail=str(value.get("detail") or ""),
                )
            )

    def _web_entries(self) -> list[ModelCatalogEntry]:
        # Built-in adapters are discovered from the registry when available,
        # so adding a safe first-party adapter does not require changing the
        # policy router.  ``custom`` is a configuration template, not a
        # routable model candidate and is intentionally excluded.
        sources = self.WEB_CHAT_SOURCES
        if self.web_chat is not None:
            try:
                discovered = self.web_chat.list_adapters()
            except Exception:
                discovered = []
            dynamic_sources = [
                (str(item.get("id") or ""), str(item.get("name") or item.get("id") or ""))
                for item in discovered
                if isinstance(item, dict) and item.get("custom") is not True and item.get("id")
            ]
            if dynamic_sources:
                sources = tuple(dynamic_sources)
        entries = [
            ModelCatalogEntry(
                route_id=f"web:{source_id}",
                provider_id=source_id,
                model_id="web-session",
                display_name=label,
                # ``text`` is the runtime-neutral capability consumed by the
                # route supervisor.  Keep the more specific labels as well
                # so existing Modules/UI projections remain compatible.
                capabilities=("text", "chat", "browser"),
                quality_tier="unknown",
                cost_class="unknown",
                processing_location="cloud",
                auth_state="needs-auth",
                quota_state="unknown",
                health_state="unknown",
                source_kind="web-chat",
                transport="browser-dom",
                metadata={
                    "routable": False,
                    "requires_user_login": True,
                    "quota_source": "provider_web_account",
                    "authorization_boundary": "manual-login",
                    "quota_consent": "unknown",
                },
            )
            for source_id, label in sources
        ]
        if self.web_chat is None:
            return entries
        try:
            profiles = self.web_chat.list_profiles(include_archived=False)
        except Exception:
            profiles = []
        for profile in profiles:
            if not isinstance(profile, dict) or profile.get("archived_at"):
                continue
            profile_id = _safe_text(profile.get("id"), 120)
            if not profile_id:
                continue
            adapter_id = _safe_text(profile.get("adapter_id"), 120) or "custom"
            profile_config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
            model_id = _safe_text(profile_config.get("model_id"), 160) or "web-session"
            auth_state = _safe_text(profile.get("auth_state"), 40).lower() or "unknown"
            status = _safe_text(profile.get("status"), 40).lower() or "unknown"
            consented = profile.get("auto_chat_enabled") is True and "chat.send" in set(profile.get("allowed_actions") or [])
            ready = status == "ready" and auth_state == "authorized"
            # Keep the profile/session ownership boundary visible to the
            # runtime-neutral route layer.  ``agent_occupied`` is the local
            # coordinator's active write marker; an ``other-core`` lease is a
            # hard handoff boundary.  A lease owned by this Core is not
            # inferred to be manual here because the same BrowserSkill
            # session may be reused for a later Agent turn.
            lease_owner = _safe_text(profile.get("browser_profile_lease_owner"), 40).lower()
            occupancy = "agent" if profile.get("agent_occupied") is True else "waiting" if lease_owner == "other-core" else "idle"
            entries.append(
                ModelCatalogEntry(
                    route_id=f"web:{profile_id}",
                    provider_id=f"web-chat:{profile_id}",
                    model_id=model_id,
                    display_name=f"{_safe_text(profile.get('name') or profile_id, 160)} · 网页聊天",
                    capabilities=("text", "chat", "browser"),
                    quality_tier=_quality_from_model(model_id),
                    # Web accounts do not expose a verified quota source.  A
                    # profile-level ``free-only`` preference is a safety
                    # constraint, not evidence that the website is free, so
                    # keep the route's cost unknown until an official source
                    # is integrated.
                    cost_class="unknown",
                    processing_location="cloud",
                    auth_state=auth_state,
                    quota_state="unknown",
                    health_state="healthy" if ready else "unknown",
                    source_kind="web-chat",
                    transport="browser-dom",
                    metadata={
                        "routable": bool(ready and consented),
                        "web_profile_id": profile_id,
                        "adapter_id": adapter_id,
                        "requires_user_login": auth_state != "authorized",
                        "authorization_boundary": "one-time-chat-consent",
                        "quota_source": "provider_web_account",
                        "budget_policy": _safe_text(profile.get("budget_policy"), 40) or "free-only",
                        # Automatic chat consent is also the explicit
                        # profile-level permission to spend an unknown web
                        # quota.  It is not evidence that the site is free;
                        # the route remains ``cost_class=unknown``.
                        "quota_consent": "granted" if consented else "unknown",
                        "occupancy": occupancy,
                    },
                )
            )
        return entries

    def _refresh_declarative_quotas(self) -> None:
        if self.provider_profiles is None:
            return
        try:
            profiles = self.provider_profiles.list(include_archived=False)
        except Exception:
            return
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
            query = self._usage_query_for_profile(profile)
            if query is None:
                continue
            profile_id = str(profile.get("id") or "")
            models = configured_models(config)
            if not models:
                models = [{"id": "unconfigured"}]
            for model_row in models:
                model = str(model_row.get("id") or "")
                if not model:
                    continue
                route_id = f"profile:{profile_id}:{model}"
                snapshot = self._query_usage(profile, query, route_id)
                self.store.upsert_quota(snapshot)

    def _refresh_quotas_if_due(self, *, force: bool = False) -> bool:
        """Refresh only configured usage queries whose snapshots are stale."""

        with self._quota_lock:
            if not force and not self._quota_refresh_due():
                return False
            self._refresh_declarative_quotas()
            self.store.save()
            return True

    def _quota_refresh_due(self) -> bool:
        if self.provider_profiles is None:
            return False
        try:
            profiles = self.provider_profiles.list(include_archived=False)
        except Exception:
            return False
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
            query = self._usage_query_for_profile(profile)
            if query is None:
                continue
            models = configured_models(config) or [{"id": "unconfigured"}]
            for model_row in models:
                route_id = f"profile:{profile.get('id')}:{model_row.get('id') or 'unconfigured'}"
                snapshot = self.store.quota(route_id)
                if snapshot is None or not _quota_is_fresh(snapshot.expires_at):
                    return True
        return False

    def _usage_query_for_profile(self, profile: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return an explicit query or the fixed New API token-usage query."""

        config = profile.get("config") if isinstance(profile.get("config"), Mapping) else {}
        explicit = config.get("usage_query") if isinstance(config.get("usage_query"), Mapping) else {}
        if explicit.get("enabled") is True:
            return dict(explicit)
        pricing = config.get("pricing") if isinstance(config.get("pricing"), Mapping) else {}
        if str(pricing.get("source_type") or "").strip().lower() != "new-api":
            return None
        profile_id = str(profile.get("id") or "").strip()
        snapshots = self.pricing.store.list(provider_profile_id=profile_id)
        quota_per_units = {
            float(item.observations["quota_per_unit"])
            for item in snapshots
            if isinstance(item.observations.get("quota_per_unit"), (int, float))
            and not isinstance(item.observations.get("quota_per_unit"), bool)
            and float(item.observations["quota_per_unit"]) > 0
        }
        if len(quota_per_units) != 1:
            return None
        scheme, host, port = _url_origin(str(config.get("active_base_url") or ""))
        authority = host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"
        return {
            "enabled": True,
            "method": "GET",
            "url": f"{scheme}://{authority}/api/usage/token/",
            "fields": {
                "remaining": "data.total_available",
                "used": "data.total_used",
                "total": "data.total_granted",
            },
            "_scale_divisor": next(iter(quota_per_units)),
            "_unit": snapshots[0].currency,
            "_source": "new-api-token-usage",
            "_detail": "New API 同源 Token 余额",
        }

    def _runtime_quota_status(self, *, force: bool = False) -> dict[str, Any]:
        with self._quota_lock:
            if (
                not force
                and self._runtime_quota_cache is not None
                and time.monotonic() - self._runtime_quota_checked_at < self.quota_ttl_seconds
            ):
                return dict(self._runtime_quota_cache)
        if self.agent is None or not callable(getattr(self.agent, "quota_status", None)):
            result = {"state": "unknown", "source": "agent-runtime-not-supported"}
        else:
            try:
                value = self.agent.quota_status({})
            except Exception as error:
                result = {"state": "unknown", "source": "agent-runtime-error", "error_type": type(error).__name__}
            else:
                if not isinstance(value, dict):
                    result = {"state": "unknown", "source": "agent-runtime-invalid"}
                else:
                    result = {"state": _safe_text(value.get("state"), 40).lower() or "unknown", "source": _safe_text(value.get("source"), 160) or "agent-runtime"}
                    if result["state"] not in VALID_QUOTA_STATES:
                        result["state"] = "unknown"
                    for key in ("checked_at", "expires_at", "unit"):
                        if value.get(key) is not None:
                            result[key] = _safe_text(value.get(key), 120)
                    for key in ("remaining", "remaining_min", "remaining_max", "used", "total"):
                        number = value.get(key)
                        if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and number >= 0:
                            result[key] = float(number)
        with self._quota_lock:
            self._runtime_quota_cache = dict(result)
            self._runtime_quota_checked_at = time.monotonic()
        return dict(result)

    def _query_usage(self, profile: dict[str, Any], query: dict[str, Any], route_id: str) -> QuotaSnapshot:
        profile_id = str(profile.get("id") or "")
        try:
            config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
            base_url = str(config.get("active_base_url") or "").rstrip("/")
            raw_url = str(query.get("url") or "{{baseUrl}}/api/usage").replace("{{baseUrl}}", base_url)
            parsed = urlparse(raw_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ModelPolicyError("usage query URL must be HTTP(S)")
            base_origin = _url_origin(base_url)
            if _url_origin(raw_url) != base_origin:
                raise ModelPolicyError("authenticated usage query must use the Provider origin")
            full = self.provider_profiles.get(profile_id, include_secrets=True)
            secrets = full.get("secrets") if isinstance(full.get("secrets"), dict) else {}
            method = str(query.get("method") or "GET").upper()
            if method not in {"GET", "POST"}:
                raise ModelPolicyError("usage query method is unsupported")
            headers = {"Accept": "application/json"}
            api_key = secrets.get("api_key")
            if isinstance(api_key, str) and api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            for key, value in secrets.items():
                if isinstance(key, str) and key.startswith("header:") and isinstance(value, str):
                    headers[key.removeprefix("header:")] = value
            body = None
            if method == "POST":
                body = b"{}"
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(raw_url, data=body, headers=headers, method=method)
            opener = urllib.request.build_opener(_UsageRedirectHandler(base_origin))
            with opener.open(request, timeout=8.0) as response:
                raw = response.read(256 * 1024)
            payload = json.loads(raw.decode("utf-8"))
            fields = query.get("fields") if isinstance(query.get("fields"), dict) else {}
            remaining = _number_at(payload, fields.get("remaining"))
            used = _number_at(payload, fields.get("used"))
            total = _number_at(payload, fields.get("total"))
            if remaining is None and total is not None and used is not None:
                remaining = max(0.0, total - used)
            divisor = query.get("_scale_divisor")
            if (
                isinstance(divisor, (int, float))
                and not isinstance(divisor, bool)
                and math.isfinite(float(divisor))
                and float(divisor) > 0
            ):
                remaining = remaining / float(divisor) if remaining is not None else None
                used = used / float(divisor) if used is not None else None
                total = total / float(divisor) if total is not None else None
            state = "unknown"
            if remaining is not None:
                state = "exhausted" if remaining <= 0 else "low" if (total and remaining / total < 0.1) else "available"
            return QuotaSnapshot(
                route_id=route_id,
                state=state,
                remaining_min=remaining,
                remaining_max=remaining,
                used=used,
                total=total,
                unit=str(query.get("_unit") or fields.get("unit") or ""),
                source=str(query.get("_source") or "declarative-usage-query"),
                expires_at=_expiry(max(1, QUOTA_TTL_SECONDS // 60)),
                confidence="observed" if state != "unknown" else "low",
                detail=str(query.get("_detail") or "官方声明式额度查询"),
            )
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            state = "needs-auth" if code in {401, 403} else "unknown"
            return QuotaSnapshot(route_id=route_id, state=state, source="declarative-usage-query", expires_at=_expiry(max(1, QUOTA_TTL_SECONDS // 60)), confidence="low", requires_auth=state == "needs-auth", detail=f"HTTP {code}")
        except (OSError, ValueError, ModelPolicyError, json.JSONDecodeError) as error:
            return QuotaSnapshot(route_id=route_id, state="unknown", source="declarative-usage-query", expires_at=_expiry(max(1, QUOTA_TTL_SECONDS // 60)), confidence="low", detail=type(error).__name__)


def _url_origin(value: str) -> tuple[str, str, int]:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ModelPolicyError("Provider origin must be an HTTP(S) URL without credentials")
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


class _UsageRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        self.origin = origin

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        if _url_origin(newurl) != self.origin:
            fp.close()
            raise urllib.error.HTTPError(newurl, code, "cross-origin usage redirect blocked", headers, None)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _number_at(payload: Any, path: Any) -> float | None:
    if not isinstance(path, str) or not path.strip():
        return None
    value = payload
    for part in path.strip().split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _quota_is_fresh(expires_at: str | None) -> bool:
    """Return whether a persisted quota snapshot is still within its TTL."""

    if not expires_at:
        return False
    try:
        value = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc)


def _quality_from_model(model: str) -> str:
    value = str(model or "").lower()
    if any(token in value for token in ("opus", "o1", "o3", "gpt-5", "deepseek-r1", "reasoner")):
        return "premium"
    if any(token in value for token in ("sonnet", "gpt-4", "glm-4.5", "qwen3:4b", "qwen-72b", "70b")):
        return "strong"
    if any(token in value for token in ("qwen3:1.7b", "mini", "flash", "haiku", "7b", "8b")):
        return "basic"
    return "standard" if value and value != "unconfigured" else "unknown"


def routing_request_from_dict(value: Mapping[str, Any]) -> RoutingRequest:
    if not isinstance(value, Mapping):
        raise ModelPolicyError("routing request must be an object")
    return RoutingRequest(
        task_kind=value.get("task_kind", value.get("taskKind", "chat")),
        difficulty=value.get("difficulty", "auto"),
        risk=value.get("risk", "normal"),
        context_size=value.get("context_size", value.get("contextSize", 0)),
        required_capabilities=value.get("required_capabilities", value.get("requiredCapabilities", ())),
        latency_target_ms=value.get("latency_target_ms", value.get("latencyTargetMs")),
        privacy_constraints=value.get("privacy_constraints", value.get("privacyConstraints", ())),
        budget_policy=value.get("budget_policy", value.get("budgetPolicy", "prefer-free")),
        confirmation_mode=value.get("confirmation_mode", value.get("confirmationMode", "recommendation-then-confirmation")),
        preferred_route=value.get("preferred_route", value.get("preferredRoute")),
        min_quality_tier=value.get("min_quality_tier", value.get("minQualityTier")),
        character_id=value.get("character_id", value.get("characterId")),
        agent_preset_id=value.get("agent_preset_id", value.get("agentPresetId")),
        task_text=value.get("task_text", value.get("taskText", value.get("text", ""))),
        trigger_event=value.get("trigger_event", value.get("triggerEvent")),
        task_stage=value.get("task_stage", value.get("taskStage")),
        remaining_budget=value.get("remaining_budget", value.get("remainingBudget")),
        parent_turn_id=value.get("parent_turn_id", value.get("parentTurnId")),
    )


__all__ = [
    "MODEL_POLICY_VERSION",
    "EvaluationSample",
    "ModelCatalogEntry",
    "ModelCatalogStore",
    "ModelPolicyError",
    "ModelPolicyService",
    "ModelRouter",
    "QuotaSnapshot",
    "RoutingDecision",
    "RoutingRequest",
    "infer_difficulty",
    "routing_request_from_dict",
]
