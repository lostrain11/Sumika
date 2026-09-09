"""Runtime-neutral advisory adapter for the model-picker public HTTP API.

The picker is an evidence source, not a provider worker.  It can describe
models, prices and evaluations, and can record an explicitly supplied result
through its public ledger endpoint.  It cannot authorize a route or execute a
provider request.  Sumika's Model Policy remains the only routing authority.
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urljoin, urlparse

from ...model_policy import ModelCatalogEntry


MODEL_PICKER_CATALOG_SCHEMA = "model-picker/catalog/v1"
MODEL_PICKER_EVALUATION_SCHEMA = "model-picker/evaluations/v1"
MODEL_PICKER_PRICING_SCHEMA = "model-picker/pricing/v1"
_DEFAULT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_FRAGMENT = re.compile(r"[^A-Za-z0-9._:-]+")
_PUBLIC_PATHS = frozenset({"health", "catalog", "pricing", "evaluations", "recommend", "record"})
_MAX_JSON_DEPTH = 32
_MAX_JSON_ITEMS = 4096
_MAX_REQUEST_BYTES = 64 * 1024


class ModelPickerAdapterError(ValueError):
    """Raised for an invalid endpoint or an invalid public projection."""


def _text(value: Any, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    value = value.strip()
    if len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ModelPickerAdapterError("invalid model-picker text")
    if required and not value:
        raise ModelPickerAdapterError("required model-picker text is missing")
    return value


def _fragment(value: Any, fallback: str = "unknown") -> str:
    text = _text(value, 180) or fallback
    text = _FRAGMENT.sub("-", text).strip("-.")
    return text[:120] or fallback


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or not math.isfinite(value):
        return None
    return float(value)


def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ModelPickerAdapterError("model-picker response must be an object")
    if payload.get("ok") is False:
        raise ModelPickerAdapterError("model-picker reported an error")
    value = payload.get("data", payload)
    if not isinstance(value, Mapping):
        raise ModelPickerAdapterError("model-picker data must be an object")
    return dict(value)


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ModelPickerAdapterError("model-picker JSON is too deeply nested")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ModelPickerAdapterError("model-picker JSON has an invalid number")
        return
    if isinstance(value, Mapping):
        if len(value) > _MAX_JSON_ITEMS:
            raise ModelPickerAdapterError("model-picker JSON has too many object fields")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ModelPickerAdapterError("model-picker JSON object keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_JSON_ITEMS:
            raise ModelPickerAdapterError("model-picker JSON has too many array items")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    raise ModelPickerAdapterError("model-picker JSON contains an unsupported value")


def _origin_parts(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as error:
        raise ModelPickerAdapterError("model-picker URL has an invalid port") from error
    if not scheme or not host:
        raise ModelPickerAdapterError("model-picker URL must be HTTP(S)")
    return scheme, host, port if port is not None else (443 if scheme == "https" else 80)


def _origin_url(scheme: str, host: str, port: int) -> str:
    host_text = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host_text}:{port}"


def _strictly_fresh(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("stale") is False


def _timestamp(value: Any) -> str:
    text = _text(value, 80)
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def _token_estimate(value: int | str) -> int | str:
    if isinstance(value, bool):
        raise ModelPickerAdapterError("invalid token estimate")
    if isinstance(value, int):
        if 0 <= value <= 10**12:
            return value
        raise ModelPickerAdapterError("invalid token estimate")
    if isinstance(value, str):
        return _text(value, 40, required=True)
    raise ModelPickerAdapterError("invalid token estimate")


def _optional_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10**12:
        raise ModelPickerAdapterError("invalid token count")
    return value


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        target = urljoin(req.full_url, newurl)
        parsed = urlparse(target)
        try:
            target_origin = _origin_parts(target)
        except ModelPickerAdapterError:
            target_origin = None
        if parsed.username or parsed.password or target_origin != self.origin:
            if fp is not None:
                fp.close()
            raise urllib.error.HTTPError(newurl, code, "cross-origin redirect blocked", headers, None)
        return super().redirect_request(req, fp, code, msg, headers, target)


class ModelPickerAdapter:
    """Project a model-picker HTTP catalog into Sumika model observations.

    The endpoint is loopback-only by default.  ``allow_hosts`` is an explicit
    caller-controlled allowlist for a trusted LAN deployment; it never reads
    credentials and never sends an Authorization header.
    """

    source_id = "model-picker"
    worker_id = "model-picker-advisory"

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 3.0,
        max_bytes: int = 4 * 1024 * 1024,
        allow_hosts: tuple[str, ...] | None = None,
        profile_map: Mapping[str, str] | None = None,
        fetch_json: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.base_url = self._validate_origin(base_url, allow_hosts=allow_hosts)
        self.timeout = max(1.0, min(float(timeout), 30.0))
        self.max_bytes = max(1024, min(int(max_bytes), 16 * 1024 * 1024))
        self.allow_hosts = frozenset(
            _text(item, 253, required=True).strip("[]").lower()
            for item in (allow_hosts or _DEFAULT_HOSTS)
        )
        self.profile_map = {
            _text(key, 120).lower(): _text(value, 120)
            for key, value in (profile_map or {}).items()
            if _text(key, 120) and _text(value, 120)
        }
        self._fetch_json = fetch_json
        self._cache: list[ModelCatalogEntry] = []
        self._last_catalog: dict[str, Any] | None = None
        self._last_error: str | None = None

    @staticmethod
    def _validate_origin(value: str, *, allow_hosts: tuple[str, ...] | None) -> str:
        raw_url = _text(value, 2048, required=True)
        parsed = urlparse(raw_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ModelPickerAdapterError("model-picker URL must be HTTP(S)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ModelPickerAdapterError("model-picker URL must not contain credentials or query")
        try:
            scheme, host, port = _origin_parts(raw_url)
        except ModelPickerAdapterError:
            raise
        if port < 1 or port > 65535:
            raise ModelPickerAdapterError("model-picker URL has an invalid port")
        allowed = frozenset(_text(item, 253, required=True).strip("[]").lower() for item in (allow_hosts or _DEFAULT_HOSTS))
        if host not in allowed:
            raise ModelPickerAdapterError("model-picker host is not allowlisted")
        return _origin_url(scheme, host, port)

    def _request_json(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if method not in {"GET", "POST"} or path not in _PUBLIC_PATHS:
            raise ModelPickerAdapterError("model-picker endpoint is not public")
        if self._fetch_json is not None:
            try:
                response = self._fetch_json(path) if method == "GET" else self._fetch_json(path, dict(payload or {}))
                _validate_json_value(response)
                return _unwrap(response)
            except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError, RecursionError):
                raise ModelPickerAdapterError("model-picker request unavailable: injected transport") from None
        url = f"{self.base_url}/{path.lstrip('/')}"
        origin = _origin_parts(url)
        opener = urllib.request.build_opener(_SameOriginRedirect(origin))
        data: bytes | None = None
        headers = {"Accept": "application/json", "User-Agent": "Sumika-ModelPicker/1"}
        if method == "POST":
            try:
                data = json.dumps(dict(payload or {}), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                raise ModelPickerAdapterError("invalid model-picker JSON request") from None
            if len(data) > min(self.max_bytes, _MAX_REQUEST_BYTES):
                raise ModelPickerAdapterError("model-picker request is too large")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > self.max_bytes:
                    raise ModelPickerAdapterError("model-picker response is too large")
                body = response.read(self.max_bytes + 1)
        except ModelPickerAdapterError:
            raise
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, RecursionError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            raise ModelPickerAdapterError(f"model-picker request unavailable: {type(error).__name__}") from None
        if len(body) > self.max_bytes:
            raise ModelPickerAdapterError("model-picker response is too large")
        try:
            value = json.loads(body.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid constant")))
            _validate_json_value(value)
            return _unwrap(value)
        except (UnicodeDecodeError, json.JSONDecodeError, ModelPickerAdapterError, RecursionError, ValueError):
            raise ModelPickerAdapterError("invalid model-picker JSON response") from None

    def _get(self, path: str) -> dict[str, Any]:
        return self._request_json("GET", path)

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", path, payload)

    def health(self) -> dict[str, Any]:
        try:
            value = self._get("health")
        except ModelPickerAdapterError as error:
            self._last_error = str(error)
            return {"status": "unavailable", "source": self.source_id, "error_type": type(error).__name__}
        status = _text(value.get("status"), 40).lower() or "unknown"
        self._last_error = None if status in {"ok", "ready", "available", "healthy"} else "health-not-ready"
        return {"status": status, "source": self.source_id, "models": value.get("models", 0)}

    def model_entries(self, *, refresh: bool = False, session_id: str | None = None) -> list[ModelCatalogEntry]:
        del session_id
        if not refresh:
            return list(self._cache)
        try:
            catalog = self._get("catalog")
            entries = self._project_catalog(catalog)
        except ModelPickerAdapterError as error:
            self._last_error = str(error)
            stale_at = datetime.now(timezone.utc).isoformat()
            self._cache = [
                replace(
                    item,
                    health_state="unavailable",
                    metadata={
                        **item.metadata,
                        "stale": True,
                        "stale_at": item.metadata.get("stale_at") or stale_at,
                        "catalog_error": type(error).__name__,
                        "routable": False,
                    },
                )
                for item in self._cache
            ]
            return list(self._cache)
        self._last_catalog = catalog
        self._cache = entries
        self._last_error = None
        return list(entries)

    def _project_catalog(self, catalog: Mapping[str, Any]) -> list[ModelCatalogEntry]:
        schema = _text(catalog.get("schema"), 80, required=True)
        if schema != MODEL_PICKER_CATALOG_SCHEMA:
            raise ModelPickerAdapterError("unsupported model-picker catalog schema")
        rows = catalog.get("models")
        freshness = catalog.get("freshness") if isinstance(catalog.get("freshness"), Mapping) else {}
        if not isinstance(rows, list):
            raise ModelPickerAdapterError("model-picker catalog models must be an array")
        observed_at = _timestamp(catalog.get("generated_at"))
        result: list[ModelCatalogEntry] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows[:1024]:
            if not isinstance(row, Mapping):
                continue
            model_id = _text(row.get("model_id") or row.get("id"), 240, required=True)
            model_name = _text(row.get("name") or model_id, 240, required=True)
            benchmarks = row.get("benchmarks") if isinstance(row.get("benchmarks"), Mapping) else {}
            reasoning = row.get("reasoning_efforts") or ()
            if isinstance(reasoning, str):
                reasoning = (reasoning,)
            if not isinstance(reasoning, (list, tuple)):
                reasoning = ()
            reasoning = tuple(_text(item, 40).lower() for item in reasoning if _text(item, 40))
            default_effort = _text(row.get("default_reasoning_effort") or "unknown", 40).lower() or "unknown"
            offers = row.get("offers")
            if not isinstance(offers, list):
                continue
            for offer in offers[:128]:
                if not isinstance(offer, Mapping):
                    continue
                vendor = _text(offer.get("vendor"), 120, required=True)
                remote_id = _text(offer.get("remote_id") or model_id, 240, required=True)
                channel = _text(offer.get("channel") or "api", 40).lower()
                billing_group = _text(offer.get("billing_group"), 120) if offer.get("billing_group") else ""
                identity = (vendor.lower(), channel, remote_id, billing_group)
                if identity in seen:
                    continue
                seen.add(identity)
                vendor_freshness = freshness.get(vendor)
                freshness_known = _strictly_fresh(vendor_freshness) or (
                    isinstance(vendor_freshness, Mapping) and vendor_freshness.get("stale") is True
                )
                evidence_fresh = _strictly_fresh(vendor_freshness)
                stale = not evidence_fresh
                pricing_source = _text(offer.get("pricing_source") or "unknown", 40).lower() or "unknown"
                price_in = _number(offer.get("price_in_usd_per_1m"))
                price_out = _number(offer.get("price_out_usd_per_1m"))
                per_call = _number(offer.get("per_call_usd"))
                price_known = offer.get("price_known") is True and (per_call is not None or price_in is not None or price_out is not None)
                if channel == "web" or not price_known:
                    cost_class = "unknown"
                else:
                    maximum = max(price_in or 0.0, price_out or 0.0, per_call or 0.0)
                    cost_class = "paid-high" if maximum >= 30.0 else "paid-low"
                profile_id = self.profile_map.get(vendor.lower())
                route_id = f"picker:{_fragment(vendor)}:{_fragment(model_id)}:{_fragment(remote_id)}:{_fragment(billing_group, 'default')}"
                metadata = {
                    "advisory_only": True,
                    "routable": False,
                    "picker_vendor": vendor,
                    "picker_model_id": model_id,
                    "remote_id": remote_id,
                    "pricing_source": pricing_source,
                    "pricing_status": "known" if price_known else "unknown",
                    "billing_group": billing_group or None,
                    "quota_type": offer.get("quota_type"),
                    "stale": stale,
                    "stale_at": observed_at if stale else None,
                    "freshness_known": freshness_known,
                    "evidence_fresh": evidence_fresh,
                    "freshness_evidence": vendor,
                    "benchmark_count": len(benchmarks),
                    "picker_health": "unavailable" if self._last_error else "observed",
                }
                result.append(
                    ModelCatalogEntry(
                        route_id=route_id,
                        provider_id=vendor,
                        model_id=model_id,
                        display_name=f"{model_name} · {vendor}",
                        provider_profile_id=profile_id,
                        harness_id=self.source_id,
                        capabilities=("chat", "text"),
                        quality_tier="unknown",
                        reasoning_efforts=reasoning,
                        default_reasoning_effort=default_effort if default_effort in reasoning or not reasoning else "unknown",
                        cost_class=cost_class,
                        processing_location="cloud",
                        auth_state="unknown",
                        quota_state="unknown",
                        health_state="unknown",
                        observed_at=observed_at,
                        source_kind="model-picker",
                        transport="advisory",
                        metadata=metadata,
                    )
                )
        return result

    def quota_status(self) -> dict[str, Any]:
        return {
            "state": "unknown",
            "source": "model-picker-no-quota-contract",
            "confidence": "unknown",
            "requires_auth": False,
            "detail": "model-picker catalog does not prove remaining provider quota",
        }

    def pricing_catalog(self, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            self.model_entries(refresh=True)
        try:
            projection = self._get("pricing")
            if _text(projection.get("schema"), 80, required=True) != MODEL_PICKER_PRICING_SCHEMA:
                raise ModelPickerAdapterError("unsupported model-picker pricing schema")
            offers = projection.get("offers")
            if not isinstance(offers, list):
                raise ModelPickerAdapterError("model-picker pricing offers must be an array")
            freshness = projection.get("freshness") if isinstance(projection.get("freshness"), Mapping) else {}
            normalized_offers = []
            for offer in offers[:_MAX_JSON_ITEMS]:
                if not isinstance(offer, Mapping):
                    continue
                normalized = dict(offer)
                vendor = _text(offer.get("vendor"), 120)
                normalized["evidence_fresh"] = _strictly_fresh(freshness.get(vendor))
                normalized_offers.append(normalized)
            return {**projection, "offers": normalized_offers, "available": True}
        except ModelPickerAdapterError:
            return {"schema": MODEL_PICKER_PRICING_SCHEMA, "offers": [], "available": False}

    def evaluation_catalog(self) -> dict[str, Any]:
        try:
            projection = self._get("evaluations")
            if _text(projection.get("schema"), 80, required=True) != MODEL_PICKER_EVALUATION_SCHEMA:
                raise ModelPickerAdapterError("unsupported model-picker evaluation schema")
            models = projection.get("models")
            if not isinstance(models, list):
                raise ModelPickerAdapterError("model-picker evaluations models must be an array")
            normalized_models = []
            for row in models[:_MAX_JSON_ITEMS]:
                if not isinstance(row, Mapping):
                    continue
                evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
                freshness = evidence.get("freshness") if isinstance(evidence.get("freshness"), Mapping) else {}
                normalized = dict(row)
                normalized["evidence_freshness"] = {
                    _text(source, 120): _strictly_fresh(status)
                    for source, status in freshness.items()
                    if _text(source, 120)
                }
                normalized_models.append(normalized)
            return {**projection, "models": normalized_models, "available": True}
        except ModelPickerAdapterError:
            return {"schema": MODEL_PICKER_EVALUATION_SCHEMA, "models": [], "available": False}

    def recommend(self, *, task_type: str, est_in: int | str, est_out: int | str, **kwargs: Any) -> dict[str, Any]:
        """Request a sanitized advisory recommendation; never dispatch it."""
        body = {
            "task_type": _text(task_type, 80, required=True),
            "est_in": _token_estimate(est_in),
            "est_out": _token_estimate(est_out),
        }
        for key in ("phase", "quality", "channel", "session_id"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = _text(kwargs[key], 120, required=True)
        if "budget_usd" in kwargs and kwargs["budget_usd"] is not None:
            budget = _number(kwargs["budget_usd"])
            if budget is None:
                raise ModelPickerAdapterError("invalid recommendation budget")
            body["budget_usd"] = budget
        if "limit" in kwargs and kwargs["limit"] is not None:
            limit = kwargs["limit"]
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
                raise ModelPickerAdapterError("invalid recommendation limit")
            body["limit"] = limit
        if "force_update" in kwargs and kwargs["force_update"] is not None:
            if not isinstance(kwargs["force_update"], bool):
                raise ModelPickerAdapterError("invalid recommendation force_update")
            body["force_update"] = kwargs["force_update"]
        try:
            return self._post("recommend", body)
        except ModelPickerAdapterError:
            return {"available": False, "reason": "recommendation-unavailable"}

    def record_evaluation(
        self,
        *,
        task_type: str,
        model_id: str,
        vendor: str,
        verdict: str,
        phase: str = "implement",
        quality: str = "standard",
        channel: str = "api",
        est_in: int | None = None,
        est_out: int | None = None,
        actual_in: int | None = None,
        actual_out: int | None = None,
        cost_usd: int | float | None = None,
        session_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Write an observed result through model-picker's public ``POST /record`` contract."""
        if verdict not in {"ok", "retry", "fail"}:
            raise ModelPickerAdapterError("invalid evaluation verdict")
        if note not in {"", "verified", "verification-failed", "execution-failed", "cancelled", "unknown"}:
            raise ModelPickerAdapterError("evaluation note must be a non-private status code")
        body: dict[str, Any] = {
            "task_type": _text(task_type, 80, required=True),
            "model": _text(model_id, 240, required=True),
            "vendor": _text(vendor, 120, required=True),
            "verdict": verdict,
            "phase": _text(phase, 80, required=True),
            "quality": _text(quality, 40, required=True),
            "channel": _text(channel, 40, required=True),
            "session_id": _text(session_id, 120),
            "note": _text(note, 1000),
        }
        for key, value in {
            "est_in": est_in,
            "est_out": est_out,
            "actual_in": actual_in,
            "actual_out": actual_out,
        }.items():
            count = _optional_count(value)
            if count is not None:
                body[key] = count
        if cost_usd is not None:
            cost = _number(cost_usd)
            if cost is None:
                raise ModelPickerAdapterError("invalid evaluation cost")
            body["cost_usd"] = cost
        try:
            return self._post("record", body)
        except ModelPickerAdapterError:
            return {"recorded": False, "available": False, "reason": "record-unavailable"}

    def record_outcome(self, **kwargs: Any) -> dict[str, Any]:
        """Compatibility name for the public model-picker ``POST /record`` writeback."""
        return self.record_evaluation(**kwargs)

    def worker(self) -> None:
        """Picker has no execution worker; Sumika must use a provider route."""
        return None


__all__ = [
    "MODEL_PICKER_CATALOG_SCHEMA",
    "MODEL_PICKER_EVALUATION_SCHEMA",
    "MODEL_PICKER_PRICING_SCHEMA",
    "ModelPickerAdapter",
    "ModelPickerAdapterError",
]
