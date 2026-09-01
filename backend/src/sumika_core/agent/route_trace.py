"""Content-safe dynamic route decision traces.

The trace is diagnostic evidence for improving routing policy.  It is not a
session log or recovery source: prompts, answers, context, file paths, DOM,
tool payloads, and credentials are deliberately outside the accepted schema.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


ROUTE_TRACE_SCHEMA = "route-decision-trace/v1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_MAX_LINE_BYTES = 32 * 1024
_MAX_PARTS = 32

_TOKEN_FIELDS = frozenset(
    {
        "task_kind",
        "task_stage",
        "trigger_event",
        "difficulty",
        "risk",
        "budget_policy",
        "budget_unit",
        "budget_class",
        "confirmation_mode",
        "route_id",
        "runtime_id",
        "worker_kind",
        "executor",
        "transport",
        "side_effect",
        "processing_location",
        "source_kind",
        "selection_source",
        "status",
        "outcome",
        "error_code",
        "rejection_code",
        "required_quality",
        "quality_tier",
        "cost_class",
        "quota_state",
        "health_state",
        "auth_state",
    }
)
_BOOL_FIELDS = frozenset(
    {
        "eligible",
        "available",
        "routable",
        "requires_confirmation",
        "route_requires_confirmation",
        "preferred",
        "confirmed",
        "quota_consent",
        "auto_dispatch",
        "retryable",
        "possibly_sent",
        "deduplicated",
    }
)
_NUMBER_FIELDS = frozenset(
    {
        "candidate_index",
        "candidate_count",
        "eligible_count",
        "alternative_count",
        "budget_remaining",
        "latency_target_ms",
        "latency_ms",
        "depth",
        "dispatch_count",
        "active_count",
        "preferred_rank",
        "cost_rank",
        "quota_rank",
        "quality_rank",
        "estimated_cost",
    }
)
_LIST_FIELDS = frozenset({"reason_codes", "alternative_routes", "required_capabilities", "privacy_constraints"})
_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "input_units",
        "output_units",
        "cache_units",
        "request_count",
    }
)
_CHARGE_NUMBER_FIELDS = frozenset(
    {
        "provider_charge",
        "cash_charge",
        "provider_charge_min",
        "provider_charge_max",
        "cash_min",
        "cash_max",
    }
)
_CHARGE_TOKEN_FIELDS = frozenset(
    {
        "status",
        "provider_currency",
        "cash_currency",
        "evidence_level",
        "attribution",
        "billing_group",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_date(value: str | date_type | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).date().isoformat()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    candidate = str(value).strip()
    if not _DATE_RE.fullmatch(candidate):
        raise ValueError("route trace date must use YYYY-MM-DD")
    try:
        date_type.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError("route trace date is invalid") from error
    return candidate


def _safe_token(value: Any, *, default: str = "unknown") -> str:
    candidate = str(value or default).strip()
    if _TOKEN_RE.fullmatch(candidate):
        return candidate
    return "hash-" + hashlib.sha256(candidate.encode("utf-8", "replace")).hexdigest()[:24]


def _safe_number(value: Any, *, maximum: float = 10**15) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or value > maximum:
        return None
    if isinstance(value, int) or value.is_integer():
        return int(value)
    return round(float(value), 9)


def _opaque(value: Any, salt: bytes) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    return hashlib.sha256(salt + candidate.encode("utf-8", "replace")).hexdigest()[:24]


def _safe_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, count in list(value.items())[:64]:
        number = _safe_number(count, maximum=1_000_000)
        if number is not None:
            result[_safe_token(key)] = int(number)
    return result


def _safe_usage(value: Any) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int | float] = {}
    for key in _USAGE_FIELDS:
        number = _safe_number(value.get(key))
        if number is not None:
            result[key] = number
    return result


def _safe_charge(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in _CHARGE_NUMBER_FIELDS:
        number = _safe_number(value.get(key))
        if number is not None:
            result[key] = number
    for key in _CHARGE_TOKEN_FIELDS:
        if value.get(key) not in (None, ""):
            result[key] = _safe_token(value.get(key))
    pricing_ref = value.get("pricing_ref")
    if pricing_ref not in (None, ""):
        result["pricing_ref_hash"] = hashlib.sha256(str(pricing_ref).encode("utf-8", "replace")).hexdigest()[:24]
    unknown = value.get("unknown_reasons")
    if isinstance(unknown, (list, tuple, set)):
        result["unknown_reasons"] = [_safe_token(item) for item in list(unknown)[:16]]
    return result


def _safe_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for item in list(value)[:16]:
        if not isinstance(item, Mapping):
            continue
        row: dict[str, Any] = {}
        for key in ("evidence_hash", "source_hash", "evidence_type", "effective_type"):
            if item.get(key) not in (None, ""):
                row[key] = _safe_token(item.get(key))
        confidence = item.get("confidence")
        if isinstance(confidence, str):
            row["confidence"] = _safe_token(confidence)
        else:
            number = _safe_number(confidence, maximum=1)
            if number is not None:
                row["confidence"] = number
        if isinstance(item.get("fresh"), bool):
            row["fresh"] = item["fresh"]
        for key in ("observed_at", "expires_at"):
            timestamp = _safe_timestamp(item.get(key))
            if timestamp:
                row[key] = timestamp
        if row:
            result.append(row)
    return result


def _percentile(values: list[int | float], percentile: float) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)
    return int(result) if float(result).is_integer() else round(result, 3)


class RouteDecisionTrace:
    """Write and aggregate bounded route decisions without task content."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        logger: Any = None,
        max_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.logger = logger
        self.root = (Path(data_dir) / "logs" / "route-decision-trace") if data_dir is not None else None
        self.max_bytes = max(4096, int(max_bytes))
        self.run_id = uuid4().hex
        self._salt = os.urandom(32)
        self._lock = threading.RLock()
        self._sequence = 0
        self._closed = False
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.root is not None and not self._closed

    @staticmethod
    def new_trace_id() -> str:
        return f"trace-{uuid4().hex[:20]}"

    def record(
        self,
        event: str,
        *,
        trace_id: str | None = None,
        session_id: Any = None,
        turn_id: Any = None,
        dispatch_id: Any = None,
        continuation_of: Any = None,
        retry_of: Any = None,
        provider_profile_id: Any = None,
        filter_counts: Any = None,
        evidence: Any = None,
        usage: Any = None,
        charge: Any = None,
        timestamp_utc: str | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        if self.root is None or self._closed:
            return None
        timestamp = _safe_timestamp(timestamp_utc) or _now()
        day = timestamp[:10]
        with self._lock:
            self._sequence += 1
            record: dict[str, Any] = {
                "schema": ROUTE_TRACE_SCHEMA,
                "timestamp_utc": timestamp,
                "monotonic_ns": time.monotonic_ns(),
                "run_id": self.run_id,
                "sequence": self._sequence,
                "trace_id": _safe_token(trace_id or self.new_trace_id()),
                "event": _safe_token(event),
            }
            for key, value in fields.items():
                if key in _TOKEN_FIELDS and value not in (None, ""):
                    record[key] = _safe_token(value)
                elif key in _BOOL_FIELDS and isinstance(value, bool):
                    record[key] = value
                elif key in _NUMBER_FIELDS:
                    number = _safe_number(value)
                    if number is not None:
                        record[key] = number
                elif key in _LIST_FIELDS and isinstance(value, (list, tuple, set)):
                    record[key] = [_safe_token(item) for item in list(value)[:32]]
            for name, value in (
                ("session_hash", session_id),
                ("turn_hash", turn_id),
                ("dispatch_hash", dispatch_id),
                ("continuation_hash", continuation_of),
                ("retry_of_hash", retry_of),
                ("provider_profile_hash", provider_profile_id),
            ):
                opaque = _opaque(value, self._salt)
                if opaque:
                    record[name] = opaque
            counts = _safe_counts(filter_counts)
            if counts:
                record["filter_counts"] = counts
            evidence_rows = _safe_evidence(evidence)
            if evidence_rows:
                record["evidence"] = evidence_rows
            usage_values = _safe_usage(usage)
            if usage_values:
                record["usage"] = usage_values
            charge_values = _safe_charge(charge)
            if charge_values:
                record["charge"] = charge_values
            encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > _MAX_LINE_BYTES:
                record = {
                    "schema": ROUTE_TRACE_SCHEMA,
                    "timestamp_utc": timestamp,
                    "run_id": self.run_id,
                    "sequence": self._sequence,
                    "trace_id": record["trace_id"],
                    "event": record["event"],
                    "outcome": "failed",
                    "error_code": "record-too-large",
                }
                encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            try:
                path = self._path_for(day, len(encoded))
                with path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as error:
                if self.logger:
                    self.logger.warning("route decision trace write failed error_type=%s", type(error).__name__)
                return None
            return record

    def _path_for(self, day: str, incoming_bytes: int) -> Path:
        assert self.root is not None
        base = self.root / f"{day}.jsonl"
        if not base.exists() or base.stat().st_size + incoming_bytes <= self.max_bytes:
            return base
        for index in range(1, _MAX_PARTS + 1):
            candidate = self.root / f"{day}.{index}.jsonl"
            if not candidate.exists() or candidate.stat().st_size + incoming_bytes <= self.max_bytes:
                return candidate
        for index in range(_MAX_PARTS + 1, 10001):
            candidate = self.root / f"{day}.{index}.jsonl"
            if not candidate.exists() or candidate.stat().st_size + incoming_bytes <= self.max_bytes:
                return candidate
        raise OSError("route decision trace has too many daily parts")

    def aggregate(self, day: str | date_type | None = None) -> dict[str, Any]:
        selected = _safe_date(day)
        events: Counter[str] = Counter()
        selected_routes: Counter[str] = Counter()
        candidate_routes: Counter[str] = Counter()
        rejection_codes: Counter[str] = Counter()
        outcomes: Counter[str] = Counter()
        route_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "candidate_count": 0,
                "selected_count": 0,
                "terminal_count": 0,
                "outcomes": Counter(),
                "rejections": Counter(),
                "latencies": [],
                "usage": Counter(),
                "provider_charges": defaultdict(float),
                "cash_charges": defaultdict(float),
            }
        )
        traces: set[str] = set()
        invalid_lines = 0
        total_lines = 0
        for path in self._files_for(selected):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                total_lines += 1
                try:
                    value = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    invalid_lines += 1
                    continue
                if not isinstance(value, dict) or value.get("schema") != ROUTE_TRACE_SCHEMA:
                    invalid_lines += 1
                    continue
                event = _safe_token(value.get("event"))
                events[event] += 1
                trace_id = value.get("trace_id")
                if isinstance(trace_id, str):
                    traces.add(_safe_token(trace_id))
                route_id = value.get("route_id")
                if event == "candidate.evaluated" and route_id:
                    route_id = _safe_token(route_id)
                    candidate_routes[route_id] += 1
                    route_stats[route_id]["candidate_count"] += 1
                if event == "decision.made" and route_id:
                    route_id = _safe_token(route_id)
                    selected_routes[route_id] += 1
                    route_stats[route_id]["selected_count"] += 1
                if value.get("rejection_code"):
                    rejection = _safe_token(value.get("rejection_code"))
                    rejection_codes[rejection] += 1
                    if route_id:
                        route_stats[_safe_token(route_id)]["rejections"][rejection] += 1
                if value.get("outcome"):
                    outcomes[_safe_token(value.get("outcome"))] += 1
                if event == "dispatch.finished" and route_id:
                    route_id = _safe_token(route_id)
                    stats = route_stats[route_id]
                    stats["terminal_count"] += 1
                    stats["outcomes"][_safe_token(value.get("outcome"))] += 1
                    latency = _safe_number(value.get("latency_ms"), maximum=86_400_000)
                    if latency is not None:
                        stats["latencies"].append(latency)
                    for key, amount in _safe_usage(value.get("usage")).items():
                        stats["usage"][key] += amount
                    charge = _safe_charge(value.get("charge"))
                    provider_charge = charge.get("provider_charge")
                    if provider_charge is not None:
                        stats["provider_charges"][_safe_token(charge.get("provider_currency"))] += provider_charge
                    cash_charge = charge.get("cash_charge")
                    if cash_charge is not None:
                        stats["cash_charges"][_safe_token(charge.get("cash_currency"))] += cash_charge
        route_rows: list[dict[str, Any]] = []
        for route_id, stats in sorted(route_stats.items()):
            row = {
                "route_id": route_id,
                "candidate_count": stats["candidate_count"],
                "selected_count": stats["selected_count"],
                "terminal_count": stats["terminal_count"],
                "outcomes": dict(sorted(stats["outcomes"].items())),
                "rejections": dict(sorted(stats["rejections"].items())),
                "usage": dict(sorted(stats["usage"].items())),
                "provider_charges": {key: round(value, 9) for key, value in sorted(stats["provider_charges"].items())},
                "cash_charges": {key: round(value, 9) for key, value in sorted(stats["cash_charges"].items())},
            }
            if stats["latencies"]:
                row["latency_ms"] = {
                    "p50": _percentile(stats["latencies"], 0.50),
                    "p95": _percentile(stats["latencies"], 0.95),
                }
            route_rows.append(row)
        return {
            "schema": ROUTE_TRACE_SCHEMA,
            "day": selected,
            "generated_at": _now(),
            "source_files": len(self._files_for(selected)),
            "record_count": total_lines - invalid_lines,
            "invalid_lines": invalid_lines,
            "trace_count": len(traces),
            "events": dict(sorted(events.items())),
            "selected_routes": dict(sorted(selected_routes.items())),
            "candidate_routes": dict(sorted(candidate_routes.items())),
            "rejection_codes": dict(sorted(rejection_codes.items())),
            "outcomes": dict(sorted(outcomes.items())),
            "routes": route_rows,
        }

    def write_daily_summary(self, day: str | date_type | None = None) -> dict[str, Any]:
        report = self.aggregate(day)
        if self.root is None:
            return report
        target = self.root / f"{report['day']}.summary.json"
        temporary = self.root / f".{report['day']}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        except OSError as error:
            if self.logger:
                self.logger.warning("route decision trace summary write failed error_type=%s", type(error).__name__)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return report

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.root is not None,
            "schema": ROUTE_TRACE_SCHEMA,
            "run_id": self.run_id if self.root is not None else None,
            "relative_path": "logs/route-decision-trace" if self.root is not None else None,
            "retention": "runtime-disposable; not session or recovery data",
        }

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _files_for(self, day: str) -> list[Path]:
        if self.root is None:
            return []
        candidates = [self.root / f"{day}.jsonl"]
        try:
            candidates.extend(
                path
                for path in self.root.glob(f"{day}.*.jsonl")
                if path.name.removesuffix(".jsonl").rsplit(".", 1)[-1].isdigit()
            )
        except OSError:
            pass
        return sorted({path for path in candidates if path.is_file()}, key=lambda item: item.name)


__all__ = ["ROUTE_TRACE_SCHEMA", "RouteDecisionTrace"]
