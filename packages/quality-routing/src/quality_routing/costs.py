from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable

from .contracts import RoutingError, amount, count, identifier


@dataclass(frozen=True)
class FundingLot:
    lot_id: str
    kind: str
    remaining: Decimal
    unit: str
    expires_at: float
    value_per_unit_cny: Decimal | None = None

    def __post_init__(self) -> None:
        identifier(self.lot_id)
        if self.kind not in {"grant", "purchased", "unknown"} or self.unit not in {"tokens", "requests", "CNY"}:
            raise RoutingError("invalid funding source")
        object.__setattr__(self, "remaining", amount(self.remaining))
        if self.unit != "CNY" and self.remaining != self.remaining.to_integral_value():
            raise RoutingError("resource units must be integral")
        if type(self.expires_at) not in {int, float} or not math.isfinite(self.expires_at):
            raise RoutingError("invalid funding expiry")
        if self.value_per_unit_cny is not None:
            object.__setattr__(self, "value_per_unit_cny", amount(self.value_per_unit_cny))
        if self.kind != "purchased" and self.value_per_unit_cny is not None:
            raise RoutingError("only purchased resources have an acquisition cost")


@dataclass(frozen=True)
class ResourceUse:
    lot_id: str
    kind: str
    quantity: Decimal
    unit: str
    expires_at: float
    value_cny: Decimal | None


@dataclass(frozen=True)
class RouteQuote:
    cash_due_cny: Decimal | None = None
    resource_value_cny: Decimal | None = None
    effective_cost_cny: Decimal | None = None
    funding_kind: str = "unknown"
    provider_charge: Decimal | None = None
    provider_currency: str | None = None
    allocations: tuple[ResourceUse, ...] = ()
    available: bool = True
    reason: str = "price-unknown"
    cash_balance_cny: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("cash_due_cny", "resource_value_cny", "effective_cost_cny", "provider_charge", "cash_balance_cny"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, amount(value))
        if self.funding_kind not in {"unknown", "free", "local", "grant", "purchased", "cash", "mixed"}:
            raise RoutingError("invalid quote funding")
        if type(self.available) is not bool:
            raise RoutingError("quote availability must be boolean")

    @property
    def free(self) -> bool:
        return bool(self.available and self.funding_kind in {"free", "local", "grant"}
                    and self.cash_due_cny == 0 and self.effective_cost_cny == 0)

    def to_dict(self) -> dict[str, Any]:
        def encode(value: Any) -> Any:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, dict):
                return {key: encode(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [encode(item) for item in value]
            return value
        return {"schema": "quality-routing/route-quote/v1", **encode(asdict(self)), "free": self.free}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RouteQuote:
        fields = {key: item for key, item in value.items() if key in cls.__dataclass_fields__}
        fields["allocations"] = tuple(ResourceUse(**{**item, "quantity": amount(item["quantity"]),
                                                     "value_cny": amount(item["value_cny"]) if item["value_cny"] is not None else None})
                                      for item in value.get("allocations", ()))
        return cls(**fields)


def quote_cost(*, input_tokens: int, output_tokens: int, cash_price_cny: Decimal | None,
               provider_charge: Decimal | None = None, provider_currency: str | None = None,
               lots: Iterable[FundingLot] = (), funding_required: bool = False,
               cash_balance_cny: Decimal | None = None, local: bool = False,
               now: float | None = None) -> RouteQuote:
    count(input_tokens)
    count(output_tokens)
    cash_price = amount(cash_price_cny) if cash_price_cny is not None else None
    balance = amount(cash_balance_cny) if cash_balance_cny is not None else None
    timestamp = time.time() if now is None else now
    if (local or cash_price == 0) and not funding_required:
        return RouteQuote(Decimal(0), Decimal(0), Decimal(0), "local" if local else "free",
                          provider_charge, provider_currency, reason="no-model-charge", cash_balance_cny=balance)
    sources = sorted((lot for lot in lots if lot.expires_at > timestamp and lot.remaining > 0),
                     key=lambda lot: (lot.expires_at, lot.lot_id))
    if len({lot.lot_id for lot in sources}) != len(sources):
        raise RoutingError("duplicate funding lot")
    units = {lot.unit for lot in sources}
    if len(units) > 1:
        return RouteQuote(available=False, reason="mixed-resource-units-require-explicit-order")
    unit = next(iter(units), "tokens")
    required = Decimal(input_tokens + output_tokens) if unit == "tokens" else Decimal(1) if unit == "requests" else cash_price
    used = []
    needed = required
    for lot in sources:
        if needed is None or needed <= 0:
            break
        quantity = min(needed, lot.remaining)
        value = Decimal(0) if lot.kind == "grant" else quantity * lot.value_per_unit_cny if lot.value_per_unit_cny is not None else None
        used.append(ResourceUse(lot.lot_id, lot.kind, quantity, lot.unit, lot.expires_at, value))
        needed -= quantity
    covered = bool(used and needed == 0)
    if used and not covered and unit != "CNY":
        return RouteQuote(allocations=tuple(used), available=False, reason="partial-resource-coverage-requires-requote")
    if funding_required and not covered:
        return RouteQuote(allocations=tuple(used), available=False, reason="verified-resource-insufficient-or-stale")
    cash_due = Decimal(0) if covered else needed if used and unit == "CNY" else cash_price
    value = None if any(item.value_cny is None for item in used) else sum((item.value_cny for item in used), Decimal(0))
    cost = cash_due + value if cash_due is not None and value is not None else None
    kinds = {item.kind for item in used}
    if not covered:
        kinds.add("cash" if cash_due is not None else "unknown")
    kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    available = not (balance is not None and cash_due is not None and cash_due > balance)
    reason = "cash-balance-insufficient" if not available else "funding-origin-or-value-unknown" if value is None else "price-unknown" if cash_due is None else "quoted"
    return RouteQuote(cash_due, value, cost, kind, provider_charge, provider_currency, tuple(used),
                      available, reason, balance)


def cost_order(quote: RouteQuote) -> tuple[Any, ...]:
    known = quote.effective_cost_cny is not None
    expiry = min((item.expires_at for item in quote.allocations if item.kind == "grant"), default=math.inf)
    return (not quote.available, not known, quote.effective_cost_cny if known else Decimal(0),
            not quote.free, quote.cash_due_cny is None,
            quote.cash_due_cny if quote.cash_due_cny is not None else Decimal(0), expiry)
