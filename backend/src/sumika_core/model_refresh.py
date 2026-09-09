"""Credential-free observations and conservative account-scoped reservations."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
from uuid import uuid4


REFRESH_SCHEMA = "model-refresh/v1"
RESOURCE_SCHEMA = "resource-pack-observation/v1"
MODEL_OBSERVATION_SCHEMA = "model-observation/v1"
RESOURCE_REFRESH_SECONDS = 86400
CATALOG_REFRESH_SECONDS = 43200
VALID_MODEL_STATES = {"observed", "pending-evaluation", "routable", "degraded", "retired", "needs-review"}
PRICE_URLS = {"https://bigmodel.cn/pricing", "https://open.bigmodel.cn/pricing"}
RESOURCE_URLS = {
    "https://open.bigmodel.cn/finance/resourcepack",
    "https://open.bigmodel.cn/finance-center/resource-package/package-mgmt",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _fresh(observed_at: str | None, expires_at: str | None, interval: int) -> bool:
    observed = _iso(observed_at)
    if not observed:
        return False
    current = _now()
    age = (current - datetime.fromisoformat(observed)).total_seconds()
    if not 0 <= age < interval:
        return False
    return expires_at is None or bool(_iso(expires_at) and datetime.fromisoformat(_iso(expires_at)) > current)


def _text(value: Any, limit: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError("invalid observation text")
    if re.search(r"(?i)(?:bearer\s+|sk-[a-z0-9]{15,}|[a-f0-9]{32}\.[a-z0-9]{12,})", value):
        raise ValueError("credential-like observation rejected")
    return value.strip()


def _identifier(value: Any) -> str:
    value = _text(value)
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,240}", value):
        raise ValueError("invalid observation identifier")
    return value


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 10**15:
        raise ValueError("invalid resource count")
    return value


def _quantity(value: Any, unit: str | None = None) -> tuple[int, str]:
    if type(value) is int and unit in {"tokens", "requests"}:
        return _count(value), unit
    if not isinstance(value, str):
        raise ValueError("balance requires an explicit unit")
    matched = re.fullmatch(r"([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)\s*(tokens?|次|requests?)", value.strip(), re.I)
    if not matched:
        raise ValueError("ambiguous resource balance")
    inferred = "tokens" if matched[2].lower().startswith("token") else "requests"
    if unit and unit != inferred:
        raise ValueError("conflicting resource units")
    return _count(int(matched[1].replace(",", ""))), inferred


def _display_time(value: Any, offset: Any) -> str | None:
    explicit = _iso(value)
    if explicit or value is None:
        return explicit
    if not isinstance(value, str) or offset not in {"+08:00", "UTC+08:00"}:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ResourcePackSnapshot:
    pack_id: str
    provider_profile_id: str
    applies_to: tuple[str, ...]
    remaining: int
    unit: str
    observed_at: str
    expires_at: str | None = None
    source: str = "unknown"
    confidence: str = "unknown"
    name: str = ""
    applicability: str = ""
    status: str = "unknown"
    starts_at: str | None = None
    account_scope_id: str | None = None
    account_binding_verified: bool = False
    automatic_routing_authorized: bool = False
    funding_kind: str = "unknown"
    value_per_unit_cny: str | None = None

    def __post_init__(self) -> None:
        from quality_routing.costs import FundingLot

        funding = FundingLot(self.pack_id, self.funding_kind, self.remaining, self.unit, 0, self.value_per_unit_cny)
        if funding.value_per_unit_cny is not None:
            object.__setattr__(self, "value_per_unit_cny", str(funding.value_per_unit_cny))
        for key in ("pack_id", "provider_profile_id"):
            _identifier(getattr(self, key))
        if self.account_scope_id is not None:
            _identifier(self.account_scope_id)
        _count(self.remaining)
        if self.unit not in {"tokens", "requests"} or not _iso(self.observed_at):
            raise ValueError("invalid resource unit or observation time")
        object.__setattr__(self, "observed_at", _iso(self.observed_at))
        if not isinstance(self.applies_to, (list, tuple)) or len(self.applies_to) > 128:
            raise ValueError("invalid applicability")
        object.__setattr__(self, "applies_to", tuple(_identifier(item).lower() for item in self.applies_to))
        for key in ("expires_at", "starts_at"):
            if getattr(self, key) is not None and not _iso(getattr(self, key)):
                raise ValueError("ambiguous resource time")
            if getattr(self, key) is not None:
                object.__setattr__(self, key, _iso(getattr(self, key)))
        for key in ("account_binding_verified", "automatic_routing_authorized"):
            if type(getattr(self, key)) is not bool:
                raise ValueError("invalid binding flag")

    @property
    def fresh(self) -> bool:
        return _fresh(self.observed_at, None, RESOURCE_REFRESH_SECONDS)

    @property
    def available(self) -> bool:
        return bool(self.status == "active" and self.remaining > 0 and self.fresh and self.expires_at
                    and datetime.fromisoformat(self.expires_at) > _now()
                    and (not self.starts_at or datetime.fromisoformat(self.starts_at) <= _now())
                    and self.account_scope_id and self.account_binding_verified and self.automatic_routing_authorized)

    def matches(self, model_id: str) -> bool:
        return model_id.lower() in self.applies_to

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "applies_to": list(self.applies_to), "fresh": self.fresh,
                "stale": not self.fresh, "available": self.available}


@dataclass(frozen=True, slots=True)
class ModelObservation:
    provider_id: str
    model_id: str
    source_url: str
    free_claim: bool = False
    availability_state: str = "observed"
    health_state: str = "unknown"
    evaluation_count: int = 0
    quality_tier: str = "unknown"
    observed_at: str | None = None
    expires_at: str | None = None
    source_version: str | None = None
    replacement_model_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.provider_id)
        _identifier(self.model_id)
        object.__setattr__(self, "model_id", self.model_id.lower())
        if self.source_url not in PRICE_URLS or type(self.free_claim) is not bool:
            raise ValueError("invalid official price source")
        if self.availability_state not in VALID_MODEL_STATES:
            raise ValueError("invalid model state")
        if self.observed_at is not None and not _iso(self.observed_at):
            raise ValueError("invalid model observation time")
        if self.expires_at is not None and not _iso(self.expires_at):
            raise ValueError("invalid model expiry")
        for key in ("observed_at", "expires_at"):
            if getattr(self, key) is not None:
                object.__setattr__(self, key, _iso(getattr(self, key)))
        if self.source_version is not None:
            _identifier(self.source_version)
        if self.replacement_model_id is not None:
            _identifier(self.replacement_model_id)
        if self.health_state != "unknown" or self.evaluation_count != 0 or self.quality_tier != "unknown":
            raise ValueError("price observations cannot certify health or quality")
        if self.availability_state == "routable":
            raise ValueError("price observations cannot authorize routing")

    @property
    def fresh(self) -> bool:
        return _fresh(self.observed_at, self.expires_at, CATALOG_REFRESH_SECONDS)

    @property
    def routable(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fresh": self.fresh, "stale": not self.fresh, "routable": False}


def parse_resource_observation(value: Mapping[str, Any], provider_profile_id: str = "") -> list[ResourcePackSnapshot]:
    if not isinstance(value, Mapping) or value.get("ok") is not True or value.get("source_url") not in RESOURCE_URLS:
        raise ValueError("invalid resource observation source")
    observed = _iso(value.get("observed_at"))
    if not observed:
        raise ValueError("resource observation requires a timezone-aware time")
    provider = _identifier(provider_profile_id or value.get("provider_profile_id"))
    rows = value.get("packs")
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError("resource rows must be bounded")
    if not rows and value.get("complete") is not True:
        raise ValueError("partial empty resource page")
    result = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid resource row")
        name = _text(raw.get("name"))
        applicability = _text(raw.get("applicability"), 2000)
        remaining, unit = _quantity(raw.get("available_balance", raw.get("remaining")), raw.get("unit"))
        applies_to = tuple(dict.fromkeys(re.findall(r"(?<![a-z0-9.-])(?:glm-[a-z0-9.-]+|search-[a-z0-9-]+)", applicability.lower())))
        offset = value.get("displayed_timezone")
        expires = _display_time(raw.get("expires_at", raw.get("expires_at_display")), offset)
        starts = _display_time(raw.get("starts_at", raw.get("starts_at_display")), offset)
        identity = [name, applicability, raw.get("expires_at", raw.get("expires_at_display")),
                    raw.get("starts_at", raw.get("starts_at_display")), raw.get("purchased_at_display")]
        pack_id = raw.get("pack_id") or "pack-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
        state = {"生效中": "active", "active": "active", "available": "active",
                 "已失效": "expired", "expired": "expired", "exhausted": "exhausted"}.get(raw.get("status"), "unknown")
        source = value.get("source")
        if source not in {"authenticated-page-dom", "local-ocr", "official-api"}:
            raise ValueError("unsupported resource source")
        funding_kind = raw.get("funding_kind")
        if funding_kind is None:
            funding_kind = {"赠送": "grant", "免费赠送": "grant", "活动赠送": "grant", "购买": "purchased", "已购": "purchased"}.get(
                raw.get("acquisition_type", raw.get("type")), "unknown")
        result.append(ResourcePackSnapshot(
            pack_id, provider, applies_to, remaining, unit, observed, expires, source,
            "observed", name, applicability, state, starts,
            value.get("account_scope_id"), value.get("account_binding_verified") is True,
            value.get("automatic_routing_authorized") is True,
            funding_kind, raw.get("value_per_unit_cny")))
    if len({item.pack_id for item in result}) != len(result):
        raise ValueError("ambiguous duplicate resource identity")
    return result


class RefreshCoordinator:
    """One atomic observation store, shared by offline tools and the live host."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.root = Path(data_dir) / "model-policy" if data_dir else None
        self.path = self.root / "refresh-v1.json" if self.root else None
        self._lock = threading.RLock()
        self._state = {"schema": REFRESH_SCHEMA, "resources": {}, "observations": {}, "jobs": {}, "reservations": {}, "bound_routes": {}}
        self._load()

    def _load(self) -> None:
        if self.path and self.path.is_file():
            if self.path.stat().st_size > 8_000_000:
                raise ValueError("oversized refresh store")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            raw.setdefault("bound_routes", {})
            if raw.get("schema") != REFRESH_SCHEMA or any(not isinstance(raw.get(key), dict) for key in self._state if key != "schema"):
                raise ValueError("invalid refresh store")
            self._state = raw

    @contextmanager
    def _transaction(self):
        with self._lock:
            handle = None
            locked = False
            if self.root:
                self.root.mkdir(parents=True, exist_ok=True)
                handle = (self.root / "refresh.lock").open("a+b")
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
            try:
                if handle:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    self._load()
                previous = copy.deepcopy(self._state)
                try:
                    yield
                    if self.path:
                        temporary = self.path.with_suffix("." + uuid4().hex + ".tmp")
                        try:
                            with temporary.open("w", encoding="utf-8") as stream:
                                json.dump(self._state, stream, ensure_ascii=False, allow_nan=False, sort_keys=True)
                                stream.flush()
                                os.fsync(stream.fileno())
                            temporary.replace(self.path)
                        finally:
                            temporary.unlink(missing_ok=True)
                except BaseException:
                    self._state = previous
                    raise
            finally:
                if handle:
                    if locked:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    handle.close()

    def _success(self, kind: str, observed_at: str) -> None:
        self._state["jobs"][kind] = {"last_success_at": observed_at, "last_attempt_at": _now().isoformat(),
                                     "state": "ready", "error": None}

    def ingest_resources(self, observation: Mapping[str, Any], provider_profile_id: str = "", *,
                         account_revisions: Mapping[str, str] | None = None) -> list[ResourcePackSnapshot]:
        resources = parse_resource_observation(observation, provider_profile_id)
        provider = _identifier(provider_profile_id or observation.get("provider_profile_id"))
        with self._transaction():
            for item in resources:
                accounts = {raw["account_scope_id"] for raw in self._state["resources"].values()
                            if raw["provider_profile_id"] == provider and raw.get("account_binding_verified")}
                if item.account_binding_verified and accounts and accounts != {item.account_scope_id}:
                    raise ValueError("provider account changed; explicit rebinding required")
                key = provider + "|" + item.pack_id
                previous = self._state["resources"].get(key)
                if previous and item.observed_at <= previous["observed_at"]:
                    if asdict(item) != previous:
                        raise ValueError("resource observation is older or conflicting")
                    continue
                self._state["resources"][key] = asdict(item)
                if item.account_binding_verified and item.automatic_routing_authorized:
                    for model_id in item.applies_to:
                        route_key = provider + "|" + model_id
                        revision = (account_revisions or {}).get(model_id)
                        bound = self._state["bound_routes"].get(route_key)
                        if revision is not None:
                            _identifier(revision)
                            if isinstance(bound, str) and bound != revision:
                                raise ValueError("provider account binding changed; explicit rebinding required")
                            self._state["bound_routes"][route_key] = revision
                        elif bound is None:
                            self._state["bound_routes"][route_key] = True
            if observation.get("complete") is True:
                present = {item.pack_id for item in resources}
                for key, raw in self._state["resources"].items():
                    if raw["provider_profile_id"] == provider and raw["pack_id"] not in present:
                        raw["status"] = "unknown"
            self._success("resources", _iso(observation["observed_at"]))
        return resources

    def ingest_models(self, values: Iterable[Mapping[str, Any]], *, reconcile_source: str | None = None) -> list[ModelObservation]:
        rows = list(values)
        if not 1 <= len(rows) <= 512:
            raise ValueError("model observations must be bounded and nonempty")
        result = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise ValueError("invalid model observation")
            item = ModelObservation(**{key: raw[key] for key in ModelObservation.__dataclass_fields__ if key in raw})
            if not item.observed_at:
                raise ValueError("imported evidence needs its original observation time")
            result.append(item)
        keys = {(item.provider_id, item.model_id) for item in result}
        if len(keys) != len(result):
            raise ValueError("duplicate model observation")
        with self._transaction():
            for item in result:
                key = item.provider_id + "|" + item.model_id
                previous = self._state["observations"].get(key)
                if previous and item.observed_at < previous["observed_at"]:
                    raise ValueError("older price observation")
                self._state["observations"][key] = asdict(item)
            if reconcile_source:
                for key, raw in self._state["observations"].items():
                    if raw["source_url"] == reconcile_source and (raw["provider_id"], raw["model_id"]) not in keys:
                        raw["availability_state"] = "needs-review"
                        raw["free_claim"] = False
            self._success("pricing", min(item.observed_at for item in result))
            self._success("catalog", min(item.observed_at for item in result))
        return result

    def mark_failure(self, kind: str, error: Exception | str) -> None:
        if kind not in {"resources", "pricing", "catalog"}:
            raise ValueError("unknown refresh job")
        with self._transaction():
            previous = self._state["jobs"].get(kind, {})
            self._state["jobs"][kind] = {**previous, "last_attempt_at": _now().isoformat(), "state": "needs-review",
                                         "error": type(error).__name__ if isinstance(error, Exception) else _identifier(error)}

    def resources(self) -> list[ResourcePackSnapshot]:
        with self._lock:
            self._load()
            return sorted((ResourcePackSnapshot(**raw) for raw in self._state["resources"].values()),
                          key=lambda item: (item.expires_at or "9999", item.pack_id))

    def observations(self) -> list[ModelObservation]:
        with self._lock:
            self._load()
            result = [ModelObservation(**raw) for raw in self._state["observations"].values()]
        for model in ("glm-4.7-flash", "glm-4.6v-flash"):
            if not any(item.provider_id == "zhipu-official" and item.model_id == model for item in result):
                result.append(ModelObservation("zhipu-official", model, "https://bigmodel.cn/pricing"))
        return sorted(result, key=lambda item: (item.provider_id, item.model_id))

    def resource_for(self, model_id: str, provider_profile_id: str) -> list[ResourcePackSnapshot]:
        return [item for item in self.resources() if item.provider_profile_id == provider_profile_id and item.matches(model_id)]

    def resource_bound(self, model_id: str, provider_profile_id: str) -> bool:
        with self._lock:
            self._load()
            binding = self._state["bound_routes"].get(provider_profile_id + "|" + model_id.lower())
            return binding is True or isinstance(binding, str)

    def resource_binding_matches(self, model_id: str, provider_profile_id: str, revision: str) -> bool:
        with self._lock:
            self._load()
            return self._state["bound_routes"].get(provider_profile_id + "|" + model_id.lower()) == revision

    def _remaining(self, item: ResourcePackSnapshot) -> int:
        debits = sum(allocation["amount"] for receipt in self._state["reservations"].values()
                     if receipt["state"] != "released" and receipt["account_scope_id"] == item.account_scope_id
                     for allocation in receipt["allocations"] if allocation["pack_id"] == item.pack_id)
        balances = [raw["remaining"] for raw in self._state["resources"].values()
                    if raw.get("account_scope_id") == item.account_scope_id and raw["pack_id"] == item.pack_id
                    and raw.get("account_binding_verified")]
        return max(0, min([item.remaining, *balances]) - debits)

    def quota_projection(self, model_id: str, provider_profile_id: str) -> dict[str, Any] | None:
        candidates = self.resource_for(model_id, provider_profile_id)
        if not candidates:
            return None
        available = [item for item in candidates if item.available]
        if self._state["jobs"].get("resources", {}).get("state") == "needs-review":
            available = []
        if not available:
            return {"state": "unknown", "source": "resource-pack-unverified", "detail": "refresh-or-account-binding-required"}
        units = {item.unit for item in available}
        if len(units) != 1 or len({item.account_scope_id for item in available}) != 1:
            return {"state": "unknown", "source": "resource-pack-ambiguous"}
        remaining = sum(self._remaining(item) for item in available)
        first = available[0]
        fresh_until = min(datetime.fromisoformat(item.observed_at) + timedelta(seconds=RESOURCE_REFRESH_SECONDS) for item in available)
        return {"state": "available" if remaining else "exhausted", "remaining": remaining, "unit": first.unit,
                "source": "resource-pack", "checked_at": min(item.observed_at for item in available),
                "expires_at": min(first.expires_at, fresh_until.isoformat()), "pack_expires_at": first.expires_at,
                "confidence": "observed", "detail": "account-scoped-resource-pool",
                "funding_lots": [{"lot_id": item.pack_id, "kind": item.funding_kind, "remaining": self._remaining(item),
                                  "unit": item.unit, "expires_at": min(datetime.fromisoformat(item.expires_at),
                                    datetime.fromisoformat(item.observed_at) + timedelta(seconds=RESOURCE_REFRESH_SECONDS)).timestamp(),
                                  "value_per_unit_cny": item.value_per_unit_cny} for item in available]}

    def reserve(self, attempt_id: str, provider_profile_id: str, model_id: str, amount: int, *,
                unit: str = "tokens", valid_until: str) -> dict[str, Any]:
        _identifier(attempt_id)
        _identifier(provider_profile_id)
        _identifier(model_id)
        _count(amount)
        expiry = _iso(valid_until)
        if not amount or not expiry or datetime.fromisoformat(expiry) <= _now():
            raise ValueError("reservation requires a positive bound and future deadline")
        with self._transaction():
            previous = self._state["reservations"].get(attempt_id)
            if previous:
                if any(previous[key] != value for key, value in (("provider_profile_id", provider_profile_id), ("model_id", model_id), ("amount", amount), ("unit", unit))):
                    raise ValueError("attempt identity conflict")
                return copy.deepcopy(previous)
            if len(self._state["reservations"]) >= 10000:
                raise ValueError("resource ledger requires reconciliation")
            candidates = sorted((ResourcePackSnapshot(**raw) for raw in self._state["resources"].values()),
                                key=lambda item: (item.expires_at or "9999", item.pack_id))
            candidates = [item for item in candidates if item.provider_profile_id == provider_profile_id and item.matches(model_id)
                          and item.available and item.unit == unit and item.expires_at > expiry
                          and datetime.fromisoformat(item.observed_at) + timedelta(seconds=RESOURCE_REFRESH_SECONDS) > datetime.fromisoformat(expiry)]
            if self._state["jobs"].get("resources", {}).get("state") == "needs-review":
                candidates = []
            accounts = {item.account_scope_id for item in candidates}
            if len(accounts) != 1:
                raise ValueError("resource account binding is ambiguous or unavailable")
            needed = amount
            allocations = []
            for item in candidates:
                allocated = min(needed, self._remaining(item))
                if allocated:
                    allocations.append({"pack_id": item.pack_id, "amount": allocated,
                                        "funding_kind": item.funding_kind, "value_per_unit_cny": item.value_per_unit_cny})
                    needed -= allocated
                if not needed:
                    break
            if needed:
                raise ValueError("insufficient verified resource allowance")
            receipt = {"provider_profile_id": provider_profile_id, "account_scope_id": next(iter(accounts)),
                       "model_id": model_id, "unit": unit, "amount": amount, "allocations": allocations,
                       "created_at": _now().isoformat(), "valid_until": expiry, "state": "reserved"}
            self._state["reservations"][attempt_id] = receipt
            return copy.deepcopy(receipt)

    def settle(self, attempt_id: str, *, actual: int | None = None, definitely_not_sent: bool = False) -> None:
        with self._transaction():
            receipt = self._state["reservations"][_identifier(attempt_id)]
            if receipt["state"] in {"settled", "released"}:
                return
            if definitely_not_sent:
                receipt["state"] = "released"
            elif actual is None:
                receipt["state"] = "unknown"
            else:
                _count(actual)
                if actual > receipt["amount"]:
                    receipt["state"] = "unknown"
                    previous = self._state["jobs"].get("resources", {})
                    self._state["jobs"]["resources"] = {**previous, "state": "needs-review", "error": "usage-exceeded-reservation"}
                else:
                    needed = actual
                    for allocation in receipt["allocations"]:
                        allocated = min(needed, allocation["amount"])
                        allocation["amount"] = allocated
                        needed -= allocated
                    receipt["state"] = "settled"

    def status(self) -> dict[str, Any]:
        resources = [dict(item.to_dict(), reservable_remaining=self._remaining(item)) for item in self.resources()]
        observations = [item.to_dict() for item in self.observations()]
        jobs = {}
        for kind, interval in (("resources", RESOURCE_REFRESH_SECONDS), ("pricing", CATALOG_REFRESH_SECONDS), ("catalog", CATALOG_REFRESH_SECONDS)):
            item = dict(self._state["jobs"].get(kind, {"state": "never"}))
            last = item.get("last_success_at")
            item["due"] = item["state"] != "ready" or not _fresh(last, None, interval)
            item["next_refresh_at"] = (datetime.fromisoformat(last) + timedelta(seconds=interval)).isoformat() if _iso(last) else None
            if item["state"] == "ready" and item["due"]:
                item["state"] = "stale"
            jobs[kind] = item
        return {"schema": REFRESH_SCHEMA, "intervals": {"resources_seconds": RESOURCE_REFRESH_SECONDS, "catalog_seconds": CATALOG_REFRESH_SECONDS},
                "resources": resources, "observations": observations, "jobs": jobs, "model_calls": 0}
