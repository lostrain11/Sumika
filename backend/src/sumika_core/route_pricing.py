"""Runtime-neutral pricing evidence and bounded cost calculations.

Pricing is keyed by provider profile, model, and billing group.  Public price
sources never receive provider credentials, and dynamic New API expressions
are interpreted through a small AST whitelist rather than ``eval``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urljoin, urlparse


ROUTE_PRICING_VERSION = "route-pricing/v1"
PRICING_TTL_SECONDS = 15 * 60
_MILLION = 1_000_000.0
_SOURCE_TYPES = {"direct-official", "new-api", "pinai", "manual"}
_CONFIDENCE = {"official", "published", "manual", "observed", "low", "unknown"}


class RoutePricingError(ValueError):
    """Raised when pricing configuration or evidence is malformed."""


class PricingExpressionError(RoutePricingError):
    """Raised when a dynamic billing expression leaves the safe grammar."""


class PricingSource(Protocol):
    source_type: str

    def parse(self, *args: Any, **kwargs: Any) -> list["PricingSnapshot"]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry(seconds: int = PRICING_TTL_SECONDS) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))).isoformat()


def _text(value: Any, limit: int = 240) -> str:
    result = str(value or "").strip()
    if len(result) > limit or any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise RoutePricingError("pricing text is invalid")
    return result


def _number(value: Any, *, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoutePricingError("pricing values must be numbers")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise RoutePricingError("pricing values must be finite and non-negative")
    return result


def _optional_number(value: Any) -> float | None:
    try:
        return _number(value)
    except RoutePricingError:
        return None


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_observations(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:24]:
        key = _text(raw_key, 80).lower()
        if not key or any(word in key for word in ("secret", "token", "cookie", "authorization", "password", "key")):
            continue
        if isinstance(raw_value, bool) or raw_value is None or isinstance(raw_value, str):
            result[key] = _text(raw_value, 200) if isinstance(raw_value, str) else raw_value
        elif isinstance(raw_value, (int, float)) and math.isfinite(float(raw_value)):
            result[key] = float(raw_value)
    return result


def _normalize_tiers(value: Any, *, multiplier: float = 1.0) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[dict[str, Any]] = []
    for raw in list(value)[:16]:
        if not isinstance(raw, Mapping):
            continue
        tier: dict[str, Any] = {}
        for source, target in (
            ("key", "key"),
            ("context_label", "context_label"),
            ("service_tier", "service_tier"),
            ("service_tier_label", "service_tier_label"),
        ):
            if raw.get(source) is not None:
                tier[target] = _text(raw.get(source), 120)
        for source, target in (
            ("min_tokens", "min_tokens"),
            ("max_tokens", "max_tokens"),
        ):
            number = _optional_number(raw.get(source))
            if number is not None:
                tier[target] = int(number)
        for source, target in (
            ("input_price_per_million", "input_price_per_million"),
            ("output_price_per_million", "output_price_per_million"),
            ("cache_read_price_per_million", "cache_read_price_per_million"),
            ("cache_write_price_per_million", "cache_write_price_per_million"),
        ):
            number = _optional_number(raw.get(source))
            if number is not None:
                tier[target] = round(number * multiplier, 12)
        if tier:
            result.append(tier)
    return tuple(result)


def _cash_conversion(value: Any) -> tuple[str | None, float | None]:
    if not isinstance(value, Mapping):
        return None, None
    paid = _optional_number(value.get("paid_amount"))
    credited = _optional_number(value.get("credited_amount"))
    currency = _text(value.get("currency"), 16).upper() if value.get("currency") else None
    if paid is None or credited is None or credited <= 0 or not currency:
        return None, None
    return currency, round(paid / credited, 12)


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    pricing_ref: str
    provider_profile_id: str
    model_id: str
    billing_group: str
    currency: str
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    cache_read_price_per_million: float | None = None
    cache_write_price_per_million: float | None = None
    request_price: float | None = None
    context_tiers: tuple[dict[str, Any], ...] = ()
    billing_expression: str | None = None
    group_multiplier: float = 1.0
    source_type: str = "manual"
    source_url: str | None = None
    source_version: str | None = None
    observed_at: str = field(default_factory=_now)
    expires_at: str | None = None
    confidence: str = "unknown"
    observations: dict[str, Any] = field(default_factory=dict)
    cash_currency: str | None = None
    cash_rate: float | None = None

    def __post_init__(self) -> None:
        for name, limit in (("pricing_ref", 160), ("provider_profile_id", 120), ("model_id", 240), ("billing_group", 160), ("currency", 24)):
            value = _text(getattr(self, name), limit)
            if name != "billing_group" and not value:
                raise RoutePricingError(f"{name} is required")
            object.__setattr__(self, name, value)
        for name in (
            "input_price_per_million",
            "output_price_per_million",
            "cache_read_price_per_million",
            "cache_write_price_per_million",
            "request_price",
            "cash_rate",
        ):
            object.__setattr__(self, name, _number(getattr(self, name)))
        multiplier = _number(self.group_multiplier, allow_none=False)
        object.__setattr__(self, "group_multiplier", multiplier)
        source_type = _text(self.source_type, 40).lower()
        if source_type not in _SOURCE_TYPES:
            raise RoutePricingError("unknown pricing source type")
        confidence = _text(self.confidence, 32).lower() or "unknown"
        if confidence not in _CONFIDENCE:
            confidence = "unknown"
        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "source_url", _text(self.source_url, 500) if self.source_url else None)
        object.__setattr__(self, "source_version", _text(self.source_version, 160) if self.source_version else None)
        object.__setattr__(self, "billing_expression", _text(self.billing_expression, 2000) if self.billing_expression else None)
        object.__setattr__(self, "cash_currency", _text(self.cash_currency, 16).upper() if self.cash_currency else None)
        object.__setattr__(self, "context_tiers", _normalize_tiers(self.context_tiers))
        object.__setattr__(self, "observations", _safe_observations(self.observations))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema"] = ROUTE_PRICING_VERSION
        value["context_tiers"] = [dict(item) for item in self.context_tiers]
        value["fresh"] = _fresh(self.expires_at)
        return value

    def estimate_charge(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        context_tokens: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = [input_tokens, output_tokens, cache_read_tokens, cache_write_tokens]
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in values):
            raise RoutePricingError("token counts must be non-negative integers")
        context = input_tokens if context_tokens is None else context_tokens
        if isinstance(context, bool) or not isinstance(context, int) or context < 0:
            raise RoutePricingError("context_tokens must be a non-negative integer")
        if self.request_price is not None:
            amount = self.request_price
            tier_name = "per-request"
        elif self.billing_expression:
            evaluated = evaluate_billing_expression(
                self.billing_expression,
                {
                    "p": input_tokens / _MILLION,
                    "c": output_tokens / _MILLION,
                    "cr": cache_read_tokens / _MILLION,
                    "cc": cache_write_tokens / _MILLION,
                    "len": context,
                },
                params=params,
            )
            amount = evaluated["amount"] * self.group_multiplier
            tier_name = evaluated.get("tier") or "dynamic"
        else:
            rates = {
                "input": self.input_price_per_million,
                "output": self.output_price_per_million,
                "cache_read": self.cache_read_price_per_million,
                "cache_write": self.cache_write_price_per_million,
            }
            tier_name = "base"
            for tier in self.context_tiers:
                minimum = int(tier.get("min_tokens", 0))
                maximum = tier.get("max_tokens")
                if context >= minimum and (maximum is None or context < int(maximum)):
                    tier_name = str(tier.get("context_label") or tier.get("key") or "context")
                    for key, field_name in (
                        ("input", "input_price_per_million"),
                        ("output", "output_price_per_million"),
                        ("cache_read", "cache_read_price_per_million"),
                        ("cache_write", "cache_write_price_per_million"),
                    ):
                        if tier.get(field_name) is not None:
                            rates[key] = float(tier[field_name])
                    break
            if rates["input"] is None or rates["output"] is None:
                raise RoutePricingError("pricing snapshot has no usable token rates")
            amount = (
                input_tokens / _MILLION * float(rates["input"])
                + output_tokens / _MILLION * float(rates["output"])
                + cache_read_tokens / _MILLION * float(rates["cache_read"] or 0)
                + cache_write_tokens / _MILLION * float(rates["cache_write"] or 0)
            )
        result = {
            "amount": round(max(0.0, float(amount)), 12),
            "currency": self.currency,
            "tier": tier_name,
            "pricing_ref": self.pricing_ref,
            "billing_group": self.billing_group,
        }
        if self.cash_currency and self.cash_rate is not None:
            result["cash_amount"] = round(result["amount"] * self.cash_rate, 12)
            result["cash_currency"] = self.cash_currency
        return result


@dataclass(frozen=True, slots=True)
class CostEstimate:
    route_id: str
    status: str
    pricing_refs: tuple[str, ...] = ()
    billing_groups: tuple[str, ...] = ()
    provider_currency: str | None = None
    provider_charge_min: float | None = None
    provider_charge_max: float | None = None
    cash_currency: str | None = None
    cash_min: float | None = None
    cash_max: float | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)
    unknown_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema"] = ROUTE_PRICING_VERSION
        value["pricing_refs"] = list(self.pricing_refs)
        value["billing_groups"] = list(self.billing_groups)
        value["unknown_reasons"] = list(self.unknown_reasons)
        return value


@dataclass(frozen=True, slots=True)
class ChargeReceipt:
    receipt_id: str
    route_id: str
    pricing_ref: str | None
    billing_group: str | None
    usage: dict[str, int]
    provider_charge: float | None
    provider_currency: str | None
    cash_charge: float | None
    cash_currency: str | None
    evidence_level: str
    attribution: str
    observed_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": ROUTE_PRICING_VERSION, **asdict(self)}


class _TierValue:
    __slots__ = ("name", "amount")

    def __init__(self, name: str, amount: float) -> None:
        self.name = _text(name, 120)
        self.amount = _number(amount, allow_none=False)


_ALLOWED_NAMES = {"p", "c", "cr", "cc", "len", "True", "False", "None"}
_ALLOWED_CALLS = {"tier", "hour", "param", "has", "min", "max"}


def _translate_ternary(expression: str) -> str:
    quote: str | None = None
    escaped = False
    depth = 0
    question = -1
    for index, char in enumerate(expression):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "?" and depth == 0:
            question = index
            break
    if question < 0:
        return expression
    nested = 0
    quote = None
    escaped = False
    depth = 0
    colon = -1
    for index in range(question + 1, len(expression)):
        char = expression[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and char == "?":
            nested += 1
        elif depth == 0 and char == ":":
            if nested:
                nested -= 1
            else:
                colon = index
                break
    if colon < 0:
        raise PricingExpressionError("billing expression has an unmatched ternary")
    condition = _translate_ternary(expression[:question].strip())
    truthy = _translate_ternary(expression[question + 1:colon].strip())
    falsy = _translate_ternary(expression[colon + 1:].strip())
    return f"({truthy} if {condition} else {falsy})"


def _prepare_expression(expression: str) -> str:
    value = _text(expression, 2000)
    if not value:
        raise PricingExpressionError("billing expression is empty")
    value = _translate_ternary(value)
    value = value.replace("&&", " and ").replace("||", " or ")
    value = re.sub(r"!(?!=)", " not ", value)
    value = re.sub(r"\btrue\b", "True", value, flags=re.IGNORECASE)
    value = re.sub(r"\bfalse\b", "False", value, flags=re.IGNORECASE)
    value = re.sub(r"\bnull\b", "None", value, flags=re.IGNORECASE)
    return value


def _has(value: Any, key: Any) -> bool:
    needle = str(key)
    if isinstance(value, Mapping):
        if needle in value:
            return True
        return any(_has(item, needle) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has(item, needle) for item in value)
    return False


def _evaluate_node(node: ast.AST, variables: Mapping[str, Any], params: Mapping[str, Any], hour_utc: int) -> Any:
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body, variables, params, hour_utc)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, bool, int, float)) or node.value is None:
            return node.value
        raise PricingExpressionError("unsupported billing constant")
    if isinstance(node, ast.Name):
        if node.id not in _ALLOWED_NAMES:
            raise PricingExpressionError(f"unsupported billing variable: {node.id}")
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        value = variables.get(node.id, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise PricingExpressionError("billing variables must be finite numbers")
        return float(value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
        value = _evaluate_node(node.operand, variables, params, hour_utc)
        if isinstance(node.op, ast.Not):
            return not bool(value)
        return +float(value) if isinstance(node.op, ast.UAdd) else -float(value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
        left = float(_evaluate_node(node.left, variables, params, hour_utc))
        right = float(_evaluate_node(node.right, variables, params, hour_utc))
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise PricingExpressionError("billing expression divides by zero")
            return left / right
        if right == 0:
            raise PricingExpressionError("billing expression divides by zero")
        return left % right
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [_evaluate_node(item, variables, params, hour_utc) for item in node.values]
        return all(bool(item) for item in values) if isinstance(node.op, ast.And) else any(bool(item) for item in values)
    if isinstance(node, ast.Compare):
        left = _evaluate_node(node.left, variables, params, hour_utc)
        for operator, comparator in zip(node.ops, node.comparators):
            right = _evaluate_node(comparator, variables, params, hour_utc)
            if isinstance(operator, ast.Lt):
                passed = left < right
            elif isinstance(operator, ast.LtE):
                passed = left <= right
            elif isinstance(operator, ast.Gt):
                passed = left > right
            elif isinstance(operator, ast.GtE):
                passed = left >= right
            elif isinstance(operator, ast.Eq):
                passed = left == right
            elif isinstance(operator, ast.NotEq):
                passed = left != right
            else:
                raise PricingExpressionError("unsupported billing comparison")
            if not passed:
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        branch = node.body if bool(_evaluate_node(node.test, variables, params, hour_utc)) else node.orelse
        return _evaluate_node(branch, variables, params, hour_utc)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS or node.keywords:
            raise PricingExpressionError("unsupported billing function")
        arguments = [_evaluate_node(item, variables, params, hour_utc) for item in node.args]
        if node.func.id == "tier" and len(arguments) == 2:
            return _TierValue(str(arguments[0]), float(arguments[1]))
        if node.func.id == "hour" and len(arguments) in {0, 1}:
            if arguments and str(arguments[0]).upper() != "UTC":
                raise PricingExpressionError("only UTC billing hours are supported")
            return hour_utc
        if node.func.id == "param" and len(arguments) == 1:
            return params.get(str(arguments[0]))
        if node.func.id == "has" and len(arguments) == 2:
            return _has(arguments[0], arguments[1])
        if node.func.id in {"min", "max"} and 1 <= len(arguments) <= 16:
            numbers = [float(item) for item in arguments]
            return min(numbers) if node.func.id == "min" else max(numbers)
        raise PricingExpressionError("billing function arguments are invalid")
    raise PricingExpressionError(f"unsupported billing syntax: {type(node).__name__}")


def evaluate_billing_expression(
    expression: str,
    variables: Mapping[str, Any],
    *,
    params: Mapping[str, Any] | None = None,
    hour_utc: int | None = None,
) -> dict[str, Any]:
    prepared = _prepare_expression(expression)
    try:
        tree = ast.parse(prepared, mode="eval")
    except (SyntaxError, ValueError) as error:
        raise PricingExpressionError("billing expression is invalid") from error
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise PricingExpressionError("billing expression is too complex")
    hour_value = datetime.now(timezone.utc).hour if hour_utc is None else hour_utc
    if isinstance(hour_value, bool) or not isinstance(hour_value, int) or not 0 <= hour_value <= 23:
        raise PricingExpressionError("hour_utc must be between 0 and 23")
    result = _evaluate_node(tree, variables, dict(params or {}), hour_value)
    if isinstance(result, _TierValue):
        amount = result.amount
        tier_name = result.name
    elif isinstance(result, bool) or not isinstance(result, (int, float)):
        raise PricingExpressionError("billing expression must return a numeric amount")
    else:
        amount = float(result)
        tier_name = None
    if not math.isfinite(amount) or amount < 0:
        raise PricingExpressionError("billing expression returned an invalid amount")
    return {"amount": round(amount, 12), "tier": tier_name}


def _pricing_ref(profile_id: str, model_id: str, group: str, source: str, version: str) -> str:
    digest = _hash([profile_id, model_id, group, source, version])[:24]
    return f"pricing:{digest}"


def _snapshot(
    *,
    provider_profile_id: str,
    model_id: str,
    billing_group: str,
    currency: str,
    source_type: str,
    source_url: str | None,
    source_version: str,
    cash_conversion: Mapping[str, Any] | None = None,
    **values: Any,
) -> PricingSnapshot:
    cash_currency, cash_rate = _cash_conversion(cash_conversion)
    return PricingSnapshot(
        pricing_ref=_pricing_ref(provider_profile_id, model_id, billing_group, source_type, source_version),
        provider_profile_id=provider_profile_id,
        model_id=model_id,
        billing_group=billing_group,
        currency=currency,
        source_type=source_type,
        source_url=source_url,
        source_version=source_version,
        expires_at=_expiry(),
        cash_currency=cash_currency,
        cash_rate=cash_rate,
        **values,
    )


class PinAIPricingSource:
    source_type = "pinai"
    public_url = "https://app.pinaic.com/api/v1/model-display/models"

    def parse(
        self,
        payload: Mapping[str, Any],
        *,
        provider_profile_id: str,
        model_ids: Iterable[str] = (),
        billing_group: str | None = None,
        cash_conversion: Mapping[str, Any] | None = None,
        source_url: str | None = None,
    ) -> list[PricingSnapshot]:
        data = payload.get("data") if isinstance(payload, Mapping) else None
        items = data.get("items") if isinstance(data, Mapping) else None
        if payload.get("code") not in {0, None} or not isinstance(items, list):
            raise RoutePricingError("PinAI pricing payload is invalid")
        allowed = {str(item).strip() for item in model_ids if str(item).strip()}
        selected_group = str(billing_group or "").strip()
        version = _hash(payload)[:24]
        snapshots: list[PricingSnapshot] = []
        for item in items[:512]:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("canonical_model") or item.get("display_name") or "").strip()
            if not model_id or (allowed and model_id not in allowed):
                continue
            base_pricing = item.get("pricing") if isinstance(item.get("pricing"), Mapping) else {}
            groups = item.get("groups") if isinstance(item.get("groups"), list) else []
            if not groups:
                groups = [{"group_name": "", "configured_pricing": base_pricing, "rate_multiplier": 1.0}]
            for group in groups[:64]:
                if not isinstance(group, Mapping):
                    continue
                group_name = str(group.get("group_name") or group.get("group_key") or group.get("group_id") or "").strip()
                if selected_group and selected_group not in {group_name, str(group.get("group_key") or ""), str(group.get("group_id") or "")}:
                    continue
                multiplier = _optional_number(group.get("rate_multiplier")) or 1.0
                configured = group.get("configured_pricing") if isinstance(group.get("configured_pricing"), Mapping) else base_pricing
                group_segments = configured.get("segments") if isinstance(configured, Mapping) else None
                if not isinstance(group_segments, (list, tuple)):
                    group_segments = base_pricing.get("segments") if isinstance(base_pricing, Mapping) else None
                    tiers = _normalize_tiers(group_segments, multiplier=multiplier)
                else:
                    tiers = _normalize_tiers(group_segments)
                observations = {
                    "effective_price_per_million_1h": group.get("actual_price_per_million_1h"),
                    "avg_first_token_ms_3m": group.get("avg_first_token_ms_3m"),
                    "output_tokens_per_second_3m": group.get("output_speed_tokens_per_second_3m"),
                    "rate_multiplier": group.get("rate_multiplier"),
                }
                snapshots.append(_snapshot(
                    provider_profile_id=provider_profile_id,
                    model_id=model_id,
                    billing_group=group_name,
                    currency="USD-credit",
                    source_type=self.source_type,
                    source_url=source_url or self.public_url,
                    source_version=version,
                    cash_conversion=cash_conversion,
                    input_price_per_million=_optional_number(configured.get("input_price_per_million")),
                    output_price_per_million=_optional_number(configured.get("output_price_per_million")),
                    cache_read_price_per_million=_optional_number(configured.get("cache_read_price_per_million")),
                    cache_write_price_per_million=_optional_number(configured.get("cache_write_price_per_million")),
                    context_tiers=tiers,
                    confidence="published",
                    observations=observations,
                ))
        return snapshots


class NewApiPricingSource:
    source_type = "new-api"

    def __init__(self, *, currency: str = "CNY") -> None:
        self.currency = _text(currency, 24).upper() or "CNY"

    def parse(
        self,
        status_payload: Mapping[str, Any],
        pricing_payload: Mapping[str, Any],
        *,
        provider_profile_id: str,
        model_ids: Iterable[str] = (),
        billing_group: str | None = None,
        cash_conversion: Mapping[str, Any] | None = None,
        source_url: str | None = None,
    ) -> list[PricingSnapshot]:
        status_data = status_payload.get("data") if isinstance(status_payload, Mapping) else None
        models = pricing_payload.get("data") if isinstance(pricing_payload, Mapping) else None
        ratios = pricing_payload.get("group_ratio") if isinstance(pricing_payload, Mapping) else None
        if not isinstance(status_data, Mapping) or not isinstance(models, list) or not isinstance(ratios, Mapping):
            raise RoutePricingError("New API pricing payload is invalid")
        quota_per_unit = _optional_number(status_data.get("quota_per_unit"))
        allowed = {str(item).strip() for item in model_ids if str(item).strip()}
        selected_group = str(billing_group or "").strip()
        version = str(pricing_payload.get("pricing_version") or _hash(pricing_payload)[:24])
        snapshots: list[PricingSnapshot] = []
        for item in models[:1024]:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("model_name") or "").strip()
            if not model_id or (allowed and model_id not in allowed):
                continue
            enabled_groups = item.get("enable_groups") if isinstance(item.get("enable_groups"), list) else list(ratios)
            for raw_group in enabled_groups[:64]:
                group = str(raw_group).strip()
                if selected_group and group != selected_group:
                    continue
                group_ratio = _optional_number(ratios.get(group))
                if group_ratio is None:
                    continue
                expression = str(item.get("billing_expr") or "").strip() if item.get("billing_mode") == "tiered_expr" else ""
                if expression:
                    # Parse once at ingestion so dangerous or unsupported
                    # server expressions make only this price unknown.
                    try:
                        evaluate_billing_expression(expression, {"p": 0, "c": 0, "cr": 0, "cc": 0, "len": 0})
                    except PricingExpressionError:
                        continue
                    tier_names = tuple({match for match in re.findall(r"tier\(\s*[\"']([^\"']+)[\"']", expression)})
                    tiers = tuple({"context_label": name} for name in sorted(tier_names))
                    snapshots.append(_snapshot(
                        provider_profile_id=provider_profile_id,
                        model_id=model_id,
                        billing_group=group,
                        currency=self.currency,
                        source_type=self.source_type,
                        source_url=source_url,
                        source_version=version,
                        cash_conversion=cash_conversion,
                        billing_expression=expression,
                        group_multiplier=group_ratio,
                        context_tiers=tiers,
                        confidence="published",
                        observations={"pricing_version": version, "group_ratio": group_ratio},
                    ))
                    continue
                quota_type = int(_optional_number(item.get("quota_type")) or 0)
                if quota_type == 1:
                    request_price = _optional_number(item.get("model_price"))
                    if request_price is None:
                        continue
                    snapshots.append(_snapshot(
                        provider_profile_id=provider_profile_id,
                        model_id=model_id,
                        billing_group=group,
                        currency=self.currency,
                        source_type=self.source_type,
                        source_url=source_url,
                        source_version=version,
                        cash_conversion=cash_conversion,
                        request_price=request_price * group_ratio,
                        confidence="published",
                        observations={"pricing_version": version, "group_ratio": group_ratio},
                    ))
                    continue
                model_ratio = _optional_number(item.get("model_ratio"))
                if quota_per_unit is None or quota_per_unit <= 0 or model_ratio is None:
                    continue
                input_price = _MILLION / quota_per_unit * model_ratio * group_ratio
                completion_ratio = _optional_number(item.get("completion_ratio")) or 1.0
                cache_ratio = _optional_number(item.get("cache_ratio"))
                create_cache_ratio = _optional_number(item.get("create_cache_ratio"))
                snapshots.append(_snapshot(
                    provider_profile_id=provider_profile_id,
                    model_id=model_id,
                    billing_group=group,
                    currency=self.currency,
                    source_type=self.source_type,
                    source_url=source_url,
                    source_version=version,
                    cash_conversion=cash_conversion,
                    input_price_per_million=input_price,
                    output_price_per_million=input_price * completion_ratio,
                    cache_read_price_per_million=input_price * cache_ratio if cache_ratio is not None else None,
                    cache_write_price_per_million=input_price * create_cache_ratio if create_cache_ratio is not None else None,
                    confidence="published",
                    observations={"pricing_version": version, "group_ratio": group_ratio, "quota_per_unit": quota_per_unit},
                ))
        return snapshots


class ManualPricingSource:
    source_type = "manual"

    def parse(
        self,
        config: Mapping[str, Any],
        *,
        provider_profile_id: str,
        model_ids: Iterable[str],
        billing_group: str | None = None,
        cash_conversion: Mapping[str, Any] | None = None,
        source_url: str | None = None,
        source_type: str | None = None,
        confidence: str = "manual",
    ) -> list[PricingSnapshot]:
        rates = config.get("rates") if isinstance(config.get("rates"), Mapping) else config
        raw_currency = _text(rates.get("currency") or config.get("currency") or "", 24)
        currency = "USD-credit" if raw_currency.casefold() == "usd-credit" else raw_currency.upper()
        if not currency:
            return []
        group = str(billing_group or config.get("billing_group") or "manual").strip()
        version = str(config.get("source_version") or _hash(config)[:24])
        result: list[PricingSnapshot] = []
        for model_id in list(dict.fromkeys(str(item).strip() for item in model_ids if str(item).strip()))[:256]:
            model_rates = rates.get(model_id) if isinstance(rates.get(model_id), Mapping) else rates
            result.append(_snapshot(
                provider_profile_id=provider_profile_id,
                model_id=model_id,
                billing_group=group,
                currency=currency,
                source_type=source_type or self.source_type,
                source_url=source_url or config.get("source_url"),
                source_version=version,
                cash_conversion=cash_conversion,
                input_price_per_million=_optional_number(model_rates.get("input_price_per_million")),
                output_price_per_million=_optional_number(model_rates.get("output_price_per_million")),
                cache_read_price_per_million=_optional_number(model_rates.get("cache_read_price_per_million")),
                cache_write_price_per_million=_optional_number(model_rates.get("cache_write_price_per_million")),
                request_price=_optional_number(model_rates.get("request_price")),
                context_tiers=model_rates.get("context_tiers") or (),
                confidence=confidence,
            ))
        return result


class DirectOfficialPricingSource(ManualPricingSource):
    source_type = "direct-official"

    def parse(self, config: Mapping[str, Any], **kwargs: Any) -> list[PricingSnapshot]:
        return super().parse(config, source_type=self.source_type, confidence="official", **kwargs)


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        self.origin = origin

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        if _origin(newurl) != self.origin:
            fp.close()
            raise urllib.error.HTTPError(newurl, code, "cross-origin redirect blocked", headers, None)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise RoutePricingError("pricing URL must be an HTTP(S) URL without credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def public_json(url: str, *, timeout: float = 10.0, max_bytes: int = 2 * 1024 * 1024) -> dict[str, Any]:
    """Fetch public JSON without credentials or cross-origin redirects."""

    origin = _origin(url)
    opener = urllib.request.build_opener(_SameOriginRedirect(origin))
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Sumika-Pricing/1"}, method="GET")
    try:
        with opener.open(request, timeout=max(1.0, min(float(timeout), 30.0))) as response:
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise RoutePricingError(f"pricing request failed with HTTP {code}") from None
    if len(raw) > max_bytes:
        raise RoutePricingError("pricing response is too large")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RoutePricingError("pricing response must be an object")
    return payload


class RoutePricingStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.path = Path(data_dir) / "route-pricing-v1.json" if data_dir else None
        self._snapshots: dict[str, PricingSnapshot] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for raw in list(payload.get("snapshots") or ())[:4096]:
                if isinstance(raw, Mapping):
                    values = {key: value for key, value in raw.items() if key in PricingSnapshot.__dataclass_fields__}
                    snapshot = PricingSnapshot(**values)
                    self._snapshots[snapshot.pricing_ref] = snapshot
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._snapshots = {}

    def replace_profile(self, profile_id: str, snapshots: Iterable[PricingSnapshot]) -> None:
        with self._lock:
            self._snapshots = {key: item for key, item in self._snapshots.items() if item.provider_profile_id != profile_id}
            for item in snapshots:
                self._snapshots[item.pricing_ref] = item

    def retain_profiles(self, profile_ids: Iterable[str]) -> bool:
        retained = {str(item).strip() for item in profile_ids if str(item).strip()}
        with self._lock:
            previous = len(self._snapshots)
            self._snapshots = {
                key: item
                for key, item in self._snapshots.items()
                if item.provider_profile_id in retained
            }
            return len(self._snapshots) != previous

    def list(self, *, provider_profile_id: str | None = None, model_id: str | None = None) -> list[PricingSnapshot]:
        with self._lock:
            values = list(self._snapshots.values())
        if provider_profile_id:
            values = [item for item in values if item.provider_profile_id == provider_profile_id]
        if model_id:
            values = [item for item in values if item.model_id == model_id]
        return sorted(values, key=lambda item: (item.provider_profile_id, item.model_id, item.billing_group, item.pricing_ref))

    def save(self) -> None:
        if self.path is None:
            return
        payload = {"schema": ROUTE_PRICING_VERSION, "snapshots": [item.to_dict() for item in self.list()], "updated_at": _now()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            return


class RoutePricingService:
    """Refresh pricing evidence and project estimates without reading secrets."""

    def __init__(self, provider_profiles: Any = None, data_dir: str | Path | None = None, logger: Any = None) -> None:
        self.provider_profiles = provider_profiles
        self.logger = logger
        self.store = RoutePricingStore(data_dir)
        self.errors: dict[str, str] = {}
        self.sources: dict[str, PricingSource] = {
            "direct-official": DirectOfficialPricingSource(),
            "new-api": NewApiPricingSource(),
            "pinai": PinAIPricingSource(),
            "manual": ManualPricingSource(),
        }

    def refresh_profiles(self, *, force: bool = False) -> bool:
        if self.provider_profiles is None:
            return False
        try:
            profiles = self.provider_profiles.list(include_archived=False)
        except Exception:
            return False
        changed = False
        active_profile_ids: set[str] = set()
        for profile in profiles:
            if not isinstance(profile, Mapping):
                continue
            profile_id = str(profile.get("id") or "").strip()
            if not profile_id:
                continue
            active_profile_ids.add(profile_id)
            config = profile.get("config") if isinstance(profile.get("config"), Mapping) else {}
            pricing = config.get("pricing") if isinstance(config.get("pricing"), Mapping) else {}
            source_type = str(pricing.get("source_type") or "").strip().lower()
            if source_type not in self.sources:
                if self.store.list(provider_profile_id=profile_id):
                    self.store.replace_profile(profile_id, ())
                    changed = True
                continue
            existing = self.store.list(provider_profile_id=profile_id)
            if not force and existing and all(_fresh(item.expires_at) for item in existing):
                continue
            try:
                snapshots = self._read_profile(profile, source_type, pricing)
            except Exception as error:
                self.errors[profile_id] = type(error).__name__
                if self.logger:
                    self.logger.info("pricing refresh failed profile=%s error_type=%s", profile.get("id"), type(error).__name__)
                continue
            self.errors.pop(profile_id, None)
            self.store.replace_profile(profile_id, snapshots)
            changed = True
        if self.store.retain_profiles(active_profile_ids):
            changed = True
        self.errors = {key: value for key, value in self.errors.items() if key in active_profile_ids}
        if changed:
            self.store.save()
        return changed

    def _read_profile(self, profile: Mapping[str, Any], source_type: str, pricing: Mapping[str, Any]) -> list[PricingSnapshot]:
        profile_id = str(profile.get("id") or "").strip()
        config = profile.get("config") if isinstance(profile.get("config"), Mapping) else {}
        raw_models = config.get("models") if isinstance(config.get("models"), list) else []
        model_ids = [str(item.get("id") if isinstance(item, Mapping) else item).strip() for item in raw_models]
        if not any(model_ids) and config.get("model"):
            model_ids = [str(config.get("model"))]
        common = {
            "provider_profile_id": profile_id,
            "model_ids": tuple(item for item in model_ids if item),
            "billing_group": pricing.get("billing_group"),
            "cash_conversion": pricing.get("cash_conversion") if isinstance(pricing.get("cash_conversion"), Mapping) else None,
        }
        if source_type == "pinai":
            url = str(pricing.get("public_url") or PinAIPricingSource.public_url)
            return self.sources[source_type].parse(public_json(url), source_url=url, **common)
        if source_type == "new-api":
            public_base = str(pricing.get("public_url") or config.get("active_base_url") or "").strip()
            scheme, host, port = _origin(public_base)
            authority = host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"
            root = f"{scheme}://{authority}/"
            status_url = urljoin(root, "api/status")
            pricing_url = urljoin(root, "api/pricing")
            return self.sources[source_type].parse(public_json(status_url), public_json(pricing_url), source_url=pricing_url, **common)
        manual_config = dict(pricing)
        return self.sources[source_type].parse(manual_config, source_url=pricing.get("source_url"), **common)

    def catalog(
        self,
        *,
        refresh: bool = False,
        provider_profile_id: str | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        refreshed = self.refresh_profiles(force=refresh)
        profile_filter = _text(provider_profile_id, 120) if provider_profile_id else None
        model_filter = _text(model_id, 240) if model_id else None
        return {
            "schema": ROUTE_PRICING_VERSION,
            "snapshots": [
                item.to_dict()
                for item in self.store.list(
                    provider_profile_id=profile_filter,
                    model_id=model_filter,
                )
            ],
            "errors": {
                key: value
                for key, value in self.errors.items()
                if profile_filter is None or key == profile_filter
            },
            "refreshed": refreshed,
            "checked_at": _now(),
        }

    def projection(self, provider_profile_id: str, model_id: str, billing_group: str | None = None) -> dict[str, Any]:
        snapshots = [
            item
            for item in self.store.list(provider_profile_id=provider_profile_id, model_id=model_id)
            if _fresh(item.expires_at)
        ]
        if billing_group:
            snapshots = [item for item in snapshots if item.billing_group == billing_group]
        if not snapshots:
            return {"pricing_status": "unknown"}
        currencies = {item.currency for item in snapshots}
        rates = [
            number
            for item in snapshots
            for number in (item.input_price_per_million, item.output_price_per_million, item.request_price)
            if number is not None
        ]
        paid = any(number > 0 for number in rates)
        free = bool(rates) and not paid
        cost_class = "free-limited" if free else "paid-high" if paid and max(rates) >= 30 else "paid-low" if paid else "unknown"
        return {
            "pricing_status": "known" if rates or any(item.billing_expression for item in snapshots) else "unknown",
            "pricing_ref": snapshots[0].pricing_ref if len(snapshots) == 1 else f"pricing-range:{_hash([item.pricing_ref for item in snapshots])[:20]}",
            "billing_group": snapshots[0].billing_group if len(snapshots) == 1 else "range",
            "pricing_currency": snapshots[0].currency if len(currencies) == 1 else "mixed",
            "pricing_source": snapshots[0].source_type if len({item.source_type for item in snapshots}) == 1 else "mixed",
            "cost_class": cost_class,
        }

    def estimate(self, entry: Mapping[str, Any], request: Mapping[str, Any]) -> CostEstimate:
        route_id = str(entry.get("route_id") or "")
        profile_id = str(entry.get("provider_profile_id") or "")
        model_id = str(entry.get("model_id") or "")
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {}
        group = str(metadata.get("billing_group") or "")
        snapshots = [
            item
            for item in self.store.list(provider_profile_id=profile_id, model_id=model_id)
            if _fresh(item.expires_at)
        ]
        if group and group != "range":
            snapshots = [item for item in snapshots if item.billing_group == group]
        if entry.get("cost_class") == "local" and not snapshots:
            return CostEstimate(route_id, "known", provider_currency="none", provider_charge_min=0, provider_charge_max=0, cash_min=0, cash_max=0, assumptions={"source": entry.get("cost_class")})
        if entry.get("cost_class") == "free-limited" and not snapshots:
            return CostEstimate(route_id, "unknown", unknown_reasons=("free-quota-pricing-not-observed",))
        if not snapshots:
            return CostEstimate(route_id, "unknown", unknown_reasons=("pricing-not-observed",))
        context_size = request.get("context_size", request.get("contextSize", 0))
        if isinstance(context_size, bool) or not isinstance(context_size, int):
            context_size = 0
        task_text = str(request.get("task_text") or request.get("taskText") or "")
        input_tokens = max(256, context_size, math.ceil(len(task_text) / 4))
        difficulty = str(request.get("difficulty") or "moderate").lower()
        output_tokens = {"trivial": 128, "basic": 256, "moderate": 1024, "complex": 2048, "critical": 4096, "auto": 1024}.get(difficulty, 1024)
        low_input, high_input = max(1, math.floor(input_tokens * 0.8)), math.ceil(input_tokens * 1.2)
        low_output, high_output = max(1, math.floor(output_tokens * 0.5)), math.ceil(output_tokens * 1.5)
        low_values: list[dict[str, Any]] = []
        high_values: list[dict[str, Any]] = []
        for snapshot in snapshots:
            try:
                low_values.append(snapshot.estimate_charge(input_tokens=low_input, output_tokens=low_output, context_tokens=low_input))
                high_values.append(snapshot.estimate_charge(input_tokens=high_input, output_tokens=high_output, context_tokens=high_input))
            except RoutePricingError:
                continue
        if not low_values or not high_values:
            return CostEstimate(route_id, "unknown", pricing_refs=tuple(item.pricing_ref for item in snapshots), billing_groups=tuple(item.billing_group for item in snapshots), unknown_reasons=("pricing-expression-or-rate-unknown",))
        currencies = {item["currency"] for item in low_values + high_values}
        cash_currencies = {item.get("cash_currency") for item in low_values + high_values if item.get("cash_currency")}
        cash_values = [float(item["cash_amount"]) for item in low_values + high_values if item.get("cash_amount") is not None]
        return CostEstimate(
            route_id,
            "known",
            pricing_refs=tuple(item.pricing_ref for item in snapshots),
            billing_groups=tuple(item.billing_group for item in snapshots),
            provider_currency=next(iter(currencies)) if len(currencies) == 1 else "mixed",
            provider_charge_min=min(float(item["amount"]) for item in low_values),
            provider_charge_max=max(float(item["amount"]) for item in high_values),
            cash_currency=next(iter(cash_currencies)) if len(cash_currencies) == 1 else None,
            cash_min=min(cash_values) if cash_values else None,
            cash_max=max(cash_values) if cash_values else None,
            assumptions={"input_tokens": [low_input, high_input], "output_tokens": [low_output, high_output]},
            unknown_reasons=() if cash_values else ("cash-conversion-unknown",),
        )

    def receipt(self, route: Mapping[str, Any], usage: Mapping[str, Any]) -> ChargeReceipt:
        route_id = str(route.get("route_id") or "")
        profile_id = str(route.get("provider_profile_id") or "")
        model_id = str(route.get("model_id") or "")
        metadata = route.get("metadata") if isinstance(route.get("metadata"), Mapping) else {}
        group = str(metadata.get("billing_group") or "")
        snapshots = [
            item
            for item in self.store.list(provider_profile_id=profile_id, model_id=model_id)
            if _fresh(item.expires_at)
        ]
        if group and group != "range":
            snapshots = [item for item in snapshots if item.billing_group == group]
        normalized_usage = _usage(usage)
        if len(snapshots) != 1:
            return ChargeReceipt(
                receipt_id=f"receipt:{_hash([route_id, normalized_usage, _now()])[:24]}",
                route_id=route_id,
                pricing_ref=None,
                billing_group=group or None,
                usage=normalized_usage,
                provider_charge=None,
                provider_currency=None,
                cash_charge=None,
                cash_currency=None,
                evidence_level="usage-only",
                attribution="batch-or-group-unknown",
            )
        snapshot = snapshots[0]
        try:
            estimate = snapshot.estimate_charge(
                input_tokens=normalized_usage.get("input_tokens", 0),
                output_tokens=normalized_usage.get("output_tokens", 0),
                cache_read_tokens=normalized_usage.get("cache_read_tokens", 0),
                cache_write_tokens=normalized_usage.get("cache_write_tokens", 0),
                context_tokens=normalized_usage.get("input_tokens", 0),
            )
        except RoutePricingError:
            estimate = {}
        return ChargeReceipt(
            receipt_id=f"receipt:{_hash([route_id, normalized_usage, snapshot.pricing_ref, _now()])[:24]}",
            route_id=route_id,
            pricing_ref=snapshot.pricing_ref,
            billing_group=snapshot.billing_group,
            usage=normalized_usage,
            provider_charge=estimate.get("amount"),
            provider_currency=estimate.get("currency"),
            cash_charge=estimate.get("cash_amount"),
            cash_currency=estimate.get("cash_currency"),
            evidence_level="request-usage-estimate" if estimate else "usage-only",
            attribution="request",
        )


def _usage(value: Mapping[str, Any]) -> dict[str, int]:
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
        "cache_read_tokens": ("cache_read_tokens", "cached_tokens"),
        "cache_write_tokens": ("cache_write_tokens",),
    }
    result: dict[str, int] = {}
    details = value.get("prompt_tokens_details") if isinstance(value.get("prompt_tokens_details"), Mapping) else {}
    for target, names in aliases.items():
        raw = next((value.get(name) for name in names if value.get(name) is not None), None)
        if target == "cache_read_tokens" and raw is None:
            raw = details.get("cached_tokens")
        if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 10_000_000_000:
            result[target] = raw
    if "total_tokens" not in result and ("input_tokens" in result or "output_tokens" in result):
        result["total_tokens"] = result.get("input_tokens", 0) + result.get("output_tokens", 0)
    return result


def _fresh(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        value = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc)


__all__ = [
    "ROUTE_PRICING_VERSION",
    "ChargeReceipt",
    "CostEstimate",
    "DirectOfficialPricingSource",
    "ManualPricingSource",
    "NewApiPricingSource",
    "PinAIPricingSource",
    "PricingExpressionError",
    "PricingSnapshot",
    "PricingSource",
    "RoutePricingError",
    "RoutePricingService",
    "evaluate_billing_expression",
    "public_json",
]
