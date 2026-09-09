from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from typing import Any

from .contracts import BudgetRule, Quote, RoutingError, amount, count, identifier


@dataclass(frozen=True)
class Reservation:
    cash_cny: Decimal | None
    tokens: int


class Budget:
    def __init__(self, quote: Quote, rule: BudgetRule = BudgetRule()) -> None:
        self.quote = quote
        self.rule = rule
        self.spent_cny = Decimal(0)
        self.estimated_cny = Decimal(0)
        self.unpriced_calls = 0
        self.calls = 0
        self.tokens = 0
        self.reservations: dict[str, Reservation] = {}
        self.settled: set[str] = set()
        self._lock = RLock()

    def reserve(self, attempt_id: str, cash_cny: Decimal | None, tokens: int) -> str:
        identifier(attempt_id)
        count(tokens)
        cost = amount(cash_cny) if cash_cny is not None else None
        with self._lock:
            if attempt_id in self.reservations or attempt_id in self.settled:
                raise RoutingError("attempt already accounted")
            if self.calls + len(self.reservations) + 1 > self.quote.max_calls:
                raise RoutingError("budget-call-limit")
            if self.tokens + sum(item.tokens for item in self.reservations.values()) + tokens > self.quote.max_tokens:
                raise RoutingError("budget-token-limit")
            predicted = self.spent_cny + self.estimated_cny + sum(
                (item.cash_cny or Decimal(0) for item in self.reservations.values()), Decimal(0)) + (cost or Decimal(0))
            high = self.quote.high_cny
            if cost != 0 and high is not None and predicted > high * self.rule.multiplier and predicted - high > self.rule.extra_cny:
                raise RoutingError("budget-extreme-overrun")
            self.reservations[attempt_id] = Reservation(cost, tokens)
            if cost is None or high is None or self.unpriced_calls or any(item.cash_cny is None for item in self.reservations.values()):
                return "unpriced-bounded"
            return "overrun-warning" if predicted > high else "within-estimate"

    def settle(self, attempt_id: str, actual_cash: Decimal | None, actual_tokens: int | None) -> None:
        cost = amount(actual_cash) if actual_cash is not None else None
        if actual_tokens is not None:
            count(actual_tokens)
        with self._lock:
            if attempt_id in self.settled:
                return
            if attempt_id not in self.reservations:
                raise RoutingError("unknown reservation")
            reserved = self.reservations.pop(attempt_id)
            self.calls += 1
            self.tokens += actual_tokens if actual_tokens is not None else reserved.tokens
            if cost is not None:
                self.spent_cny += cost
            elif reserved.cash_cny is not None:
                self.estimated_cny += reserved.cash_cny
            else:
                self.unpriced_calls += 1
            self.settled.add(attempt_id)

    def record_prior_call(self, attempt_id: str, estimated_cash: Decimal | None,
                          actual_cash: Decimal | None, tokens: int) -> None:
        identifier(attempt_id)
        count(tokens)
        estimate = amount(estimated_cash) if estimated_cash is not None else None
        with self._lock:
            if attempt_id in self.settled:
                return
            if attempt_id in self.reservations:
                raise RoutingError("prior call conflicts with an active reservation")
            self.reservations[attempt_id] = Reservation(estimate, tokens)
            self.settle(attempt_id, actual_cash, tokens)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "quote": self.quote.to_dict(), "rule": self.rule.to_dict(), "spent_cny": str(self.spent_cny),
                "estimated_cny": str(self.estimated_cny), "unpriced_calls": self.unpriced_calls,
                "calls": self.calls, "tokens": self.tokens,
                "reservations": {key: {"cash_cny": str(item.cash_cny) if item.cash_cny is not None else None,
                                        "tokens": item.tokens} for key, item in self.reservations.items()},
                "settled": sorted(self.settled),
            }

    @classmethod
    def restore(cls, value: dict[str, Any]) -> Budget:
        result = cls(Quote(**value["quote"]), BudgetRule(**value["rule"]))
        result.spent_cny = amount(value["spent_cny"])
        result.estimated_cny = amount(value["estimated_cny"])
        result.unpriced_calls = count(value["unpriced_calls"])
        result.calls = count(value["calls"])
        result.tokens = count(value["tokens"])
        result.settled = {identifier(item) for item in value["settled"]}
        result.reservations = {identifier(key): Reservation(amount(item["cash_cny"]) if item["cash_cny"] is not None else None,
                                                          count(item["tokens"]))
                               for key, item in value["reservations"].items()}
        return result
