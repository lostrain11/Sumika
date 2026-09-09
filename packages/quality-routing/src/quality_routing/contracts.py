from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping


class RoutingError(ValueError):
    pass


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,240}", value):
        raise RoutingError("invalid identifier")
    return value


def amount(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise RoutingError("amount must be a finite non-negative number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise RoutingError("invalid amount") from None
    if not result.is_finite() or result < 0:
        raise RoutingError("amount must be a finite non-negative number")
    return result


def count(value: Any, maximum: int = 10**9) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise RoutingError("invalid non-negative count")
    return value


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise RoutingError("file scope must use relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(ord(char) < 32 for char in value):
        raise RoutingError("invalid file scope")
    return value


def bounded_text(value: Any, maximum: int = 24000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise RoutingError("invalid task text")
    return value


@dataclass(frozen=True)
class Scope:
    owner_id: str
    session_id: str

    def __post_init__(self) -> None:
        identifier(self.owner_id)
        identifier(self.session_id)


@dataclass(frozen=True)
class BudgetRule:
    multiplier: Decimal = Decimal("2")
    extra_cny: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        object.__setattr__(self, "multiplier", amount(self.multiplier))
        object.__setattr__(self, "extra_cny", amount(self.extra_cny))
        if self.multiplier < 1:
            raise RoutingError("budget multiplier must be at least one")

    def to_dict(self) -> dict[str, str]:
        return {"multiplier": str(self.multiplier), "extra_cny": str(self.extra_cny)}


@dataclass(frozen=True)
class Quote:
    low_cny: Decimal | None
    typical_cny: Decimal | None
    high_cny: Decimal | None
    max_calls: int
    max_tokens: int

    def __post_init__(self) -> None:
        for key in ("low_cny", "typical_cny", "high_cny"):
            value = getattr(self, key)
            if value is not None:
                object.__setattr__(self, key, amount(value))
        values = (self.low_cny, self.typical_cny, self.high_cny)
        if any(value is None for value in values) and not all(value is None for value in values):
            raise RoutingError("quote monetary estimates must be all known or all unknown")
        if self.high_cny is not None and not self.low_cny <= self.typical_cny <= self.high_cny:
            raise RoutingError("quote estimates must be ordered")
        count(self.max_calls, 10000)
        count(self.max_tokens)
        if not self.max_calls or not self.max_tokens:
            raise RoutingError("quote requires explicit call and token bounds")

    def to_dict(self) -> dict[str, Any]:
        return {key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(self).items()}


@dataclass(frozen=True)
class Node:
    node_id: str
    goal: str
    task_type: str
    baseline_id: str
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("text",)
    acceptance: tuple[str, ...] = ()
    allowed_files: tuple[str, ...] = ()
    input_tokens: int = 4000
    output_tokens: int = 2000
    risk: str = "normal"
    input_text: str = ""
    verification: str = "leader"

    def __post_init__(self) -> None:
        for value in (self.node_id, self.task_type, self.baseline_id, self.verification):
            identifier(value)
        bounded_text(self.goal)
        if len(self.input_text) > 32000:
            raise RoutingError("task input too large")
        for key in ("dependencies", "capabilities", "acceptance", "allowed_files"):
            value = getattr(self, key)
            if not isinstance(value, (tuple, list)) or len(value) > 128:
                raise RoutingError("invalid task list")
            object.__setattr__(self, key, tuple(value))
        for value in (*self.dependencies, *self.capabilities):
            identifier(value)
        if not self.acceptance:
            raise RoutingError("node requires acceptance criteria")
        for value in self.acceptance:
            bounded_text(value, 2000)
        for value in self.allowed_files:
            relative_path(value)
        count(self.input_tokens)
        count(self.output_tokens)
        if self.risk not in {"low", "normal", "high", "critical"}:
            raise RoutingError("invalid risk")


@dataclass(frozen=True)
class Plan:
    task_id: str
    scope: Scope
    revision: int
    nodes: tuple[Node, ...]

    def __post_init__(self) -> None:
        identifier(self.task_id)
        if count(self.revision, 10000) < 1:
            raise RoutingError("revision must be positive")
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not 1 <= len(self.nodes) <= 128:
            raise RoutingError("plan must contain 1 to 128 nodes")
        nodes = {node.node_id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise RoutingError("duplicate node id")
        resolved: set[str] = set()
        while len(resolved) < len(nodes):
            ready = {key for key, node in nodes.items() if key not in resolved and set(node.dependencies) <= resolved}
            if not ready:
                raise RoutingError("cyclic or missing dependency")
            resolved.update(ready)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Plan:
        return cls(task_id=value["task_id"], scope=Scope(**value["scope"]), revision=value["revision"],
                   nodes=tuple(Node(**node) for node in value["nodes"]))


@dataclass(frozen=True)
class QualityEvidence:
    task_type: str
    baseline_id: str
    expires_at: float
    reference: str

    def __post_init__(self) -> None:
        identifier(self.task_type)
        identifier(self.baseline_id)
        identifier(self.reference)
        if not math.isfinite(self.expires_at):
            raise RoutingError("invalid evidence expiry")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    account_id: str
    model_id: str
    channel: str
    reasoning_effort: str | None = None
    capabilities: tuple[str, ...] = ("text",)
    quality: tuple[QualityEvidence, ...] = ()
    authorized: bool = False
    available: bool = False
    external: bool = True
    cash_per_million_input: Decimal | None = None
    cash_per_million_output: Decimal | None = None
    cached_input_rate: Decimal | None = None
    fixed_cash: Decimal | None = None
    billing_group: str = "default"
    account_concurrency: int = 3
    pricing_source: str = "unknown"
    prepaid_tokens: int | None = None
    prepaid_until: float | None = None
    execution_revision: str | None = None
    quote_provider: Callable[..., Any] | None = field(default=None, repr=False, compare=False)
    pricing_revision: str | None = None
    funding_kind: str = "unknown"
    resource_value_per_token_cny: Decimal | None = None

    def __post_init__(self) -> None:
        for value in (self.candidate_id, self.account_id):
            identifier(value)
        bounded_text(self.model_id, 240)
        bounded_text(self.billing_group, 240)
        if self.execution_revision is not None:
            identifier(self.execution_revision)
        if self.pricing_revision is not None:
            identifier(self.pricing_revision)
        if self.quote_provider is not None and not callable(self.quote_provider):
            raise RoutingError("quote provider must be callable")
        if self.funding_kind not in {"grant", "purchased", "unknown"}:
            raise RoutingError("invalid prepaid funding kind")
        if self.resource_value_per_token_cny is not None:
            object.__setattr__(self, "resource_value_per_token_cny", amount(self.resource_value_per_token_cny))
        if self.channel not in {"api", "web", "harness", "tool"}:
            raise RoutingError("invalid channel")
        for key in ("authorized", "available", "external"):
            if type(getattr(self, key)) is not bool:
                raise RoutingError("candidate flags must be booleans")
        for key in ("cash_per_million_input", "cash_per_million_output", "cached_input_rate", "fixed_cash"):
            if getattr(self, key) is not None:
                object.__setattr__(self, key, amount(getattr(self, key)))
        if count(self.account_concurrency, 100) < 1:
            raise RoutingError("invalid concurrency")
        if (self.prepaid_tokens is None) != (self.prepaid_until is None):
            raise RoutingError("prepaid quota requires both bound and expiry")
        if self.prepaid_tokens is not None:
            count(self.prepaid_tokens, 10**15)
            if type(self.prepaid_until) not in {int, float} or not math.isfinite(self.prepaid_until):
                raise RoutingError("invalid prepaid expiry")

    def estimate(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Decimal | None:
        return self.quote(input_tokens, output_tokens, cached_tokens).effective_cost_cny

    def quote(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Any:
        from .costs import FundingLot, RouteQuote, quote_cost

        count(input_tokens)
        count(output_tokens)
        count(cached_tokens)
        if cached_tokens > input_tokens:
            raise RoutingError("cached tokens exceed input")
        if self.quote_provider is not None:
            result = self.quote_provider(input_tokens, output_tokens, cached_tokens)
            if not isinstance(result, RouteQuote):
                raise RoutingError("quote provider returned an invalid quote")
            return result
        lots = ()
        if self.prepaid_tokens is not None:
            lots = (FundingLot("legacy-prepaid", self.funding_kind, self.prepaid_tokens, "tokens",
                               self.prepaid_until, self.resource_value_per_token_cny),)
        cost = None
        if self.fixed_cash is not None:
            cost = self.fixed_cash
        elif self.cash_per_million_input is not None and self.cash_per_million_output is not None:
            cached_rate = self.cached_input_rate if self.cached_input_rate is not None else self.cash_per_million_input
            cost = (self.cash_per_million_input * (input_tokens - cached_tokens)
                    + cached_rate * cached_tokens + self.cash_per_million_output * output_tokens) / Decimal(1000000)
        return quote_cost(input_tokens=input_tokens, output_tokens=output_tokens, cash_price_cny=cost,
                          lots=lots, funding_required=bool(lots), local=not self.external and self.channel == "tool")

    def identity(self) -> tuple[Any, ...]:
        identity = (self.account_id, self.model_id, self.channel, self.reasoning_effort, self.billing_group, self.external)
        return (*identity, self.execution_revision) if self.execution_revision is not None else identity


@dataclass(frozen=True)
class Outcome:
    status: str
    text: str = ""
    cash_cny: Decimal | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    applied_reasoning_effort: str | None = None
    changed_files: tuple[str, ...] = ()
    possibly_sent: bool = False
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed", "unknown", "cancelled"}:
            raise RoutingError("invalid outcome status")
        if len(self.text) > 128000:
            raise RoutingError("result too large")
        if self.cash_cny is not None:
            object.__setattr__(self, "cash_cny", amount(self.cash_cny))
        for value in (self.input_tokens, self.output_tokens):
            if value is not None:
                count(value)
        for value in self.changed_files:
            relative_path(value)


@dataclass(frozen=True)
class Verification:
    passed: bool
    evidence: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if type(self.passed) is not bool:
            raise RoutingError("verification result must be boolean")
        if self.passed and not self.evidence:
            raise RoutingError("passing verification requires evidence")
