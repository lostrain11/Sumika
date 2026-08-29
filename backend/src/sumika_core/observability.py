"""Content-independent Agent runtime observations.

The observability stream is deliberately separate from the product event log.
It is intended for offline maintenance analysis, not for recovering sessions or
displaying conversation content.  Only bounded dimensions, timings, counters,
and opaque correlation tokens are written.  Callers must never pass prompts,
tool arguments, file contents, credentials, cookies, or raw exception text to
this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


OBSERVABILITY_SCHEMA_VERSION = 1
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
_OUTCOMES = frozenset({"accepted", "queued", "running", "completed", "failed", "cancelled", "rejected", "unknown"})
_LOCATIONS = frozenset({"local", "cloud", "mixed", "unknown"})
_MAX_LINE_BYTES = 32 * 1024
_MAX_PARTS = 32


def _utc_timestamp() -> str:
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
        raise ValueError("observability date must use YYYY-MM-DD")
    try:
        date_type.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError("observability date is invalid") from error
    return candidate


def _safe_token(value: Any, *, default: str = "unknown", limit: int = 96) -> str:
    if value is None:
        return default
    candidate = str(value).strip()
    if not candidate:
        return default
    if len(candidate) <= limit and _TOKEN_RE.fullmatch(candidate):
        return candidate
    # Arbitrary runtime labels can contain paths or user text.  Preserve only
    # a stable opaque identity so cohorts remain comparable without leakage.
    return "hash-" + hashlib.sha256(candidate.encode("utf-8", "replace")).hexdigest()[:24]


def _safe_outcome(value: Any) -> str:
    candidate = str(value or "unknown").strip().lower()
    return candidate if candidate in _OUTCOMES else "unknown"


def _safe_location(value: Any) -> str:
    candidate = str(value or "unknown").strip().lower()
    return candidate if candidate in _LOCATIONS else "unknown"


def _safe_number(value: Any, *, maximum: float = 10**15) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or value > maximum:
        return None
    if isinstance(value, int) or value.is_integer():
        return int(value)
    return round(float(value), 6)


def _opaque(value: Any, salt: bytes) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    return hashlib.sha256(salt + candidate.encode("utf-8", "replace")).hexdigest()[:24]


def _percentile(values: list[int | float], percentile: float) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = index - lower
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return int(result) if float(result).is_integer() else round(result, 3)


class AgentObservability:
    """Append safe operation receipts and aggregate them by UTC day.

    ``data_dir=None`` disables persistence (used by in-memory tests).  The
    writer is thread-safe within a Core process, uses bounded line sizes, and
    never accepts an arbitrary payload.  Rotated parts remain disposable
    runtime data and are not used as a recovery source.
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        logger: Any = None,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.logger = logger
        self.root = (Path(data_dir) / "logs" / "agent-observability") if data_dir is not None else None
        self.max_bytes = max(4096, int(max_bytes))
        self.run_id = uuid4().hex
        self._salt = os.urandom(32)
        self._lock = threading.RLock()
        self._closed = False
        self._sequence = 0
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.root is not None and not self._closed

    def start(
        self,
        *,
        component: str,
        capability: str,
        phase: str = "start",
        session_id: Any = None,
        turn_id: Any = None,
        operation_id: Any = None,
        adapter_id: str | None = None,
        adapter_version: str | None = None,
        provider_kind: str | None = None,
        processing_location: str | None = None,
    ) -> str:
        """Write an accepted boundary receipt and return its operation id."""

        operation = _safe_token(operation_id or uuid4().hex, limit=96)
        self.record(
            component=component,
            capability=capability,
            phase=phase,
            outcome="accepted",
            session_id=session_id,
            turn_id=turn_id,
            operation_id=operation,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            provider_kind=provider_kind,
            processing_location=processing_location,
        )
        return operation

    def finish(
        self,
        operation_id: str,
        *,
        component: str,
        capability: str,
        phase: str = "end",
        outcome: str = "completed",
        duration_ms: int | float | None = None,
        queue_ms: int | float | None = None,
        retry_count: int | float | None = None,
        error_class: str | None = None,
        session_id: Any = None,
        turn_id: Any = None,
        adapter_id: str | None = None,
        adapter_version: str | None = None,
        provider_kind: str | None = None,
        processing_location: str | None = None,
        input_units: int | float | None = None,
        output_units: int | float | None = None,
        cache_units: int | float | None = None,
        estimated_cost: int | float | None = None,
        approval_count: int | float | None = None,
        cancellation_reason: str | None = None,
        recovery_action: str | None = None,
    ) -> None:
        self.record(
            component=component,
            capability=capability,
            phase=phase,
            outcome=outcome,
            duration_ms=duration_ms,
            queue_ms=queue_ms,
            retry_count=retry_count,
            error_class=error_class,
            session_id=session_id,
            turn_id=turn_id,
            operation_id=operation_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            provider_kind=provider_kind,
            processing_location=processing_location,
            input_units=input_units,
            output_units=output_units,
            cache_units=cache_units,
            estimated_cost=estimated_cost,
            approval_count=approval_count,
            cancellation_reason=cancellation_reason,
            recovery_action=recovery_action,
        )

    def record(
        self,
        *,
        component: str,
        capability: str,
        phase: str,
        outcome: str = "unknown",
        duration_ms: int | float | None = None,
        queue_ms: int | float | None = None,
        retry_count: int | float | None = None,
        error_class: str | None = None,
        session_id: Any = None,
        turn_id: Any = None,
        operation_id: Any = None,
        adapter_id: str | None = None,
        adapter_version: str | None = None,
        provider_kind: str | None = None,
        processing_location: str | None = None,
        input_units: int | float | None = None,
        output_units: int | float | None = None,
        cache_units: int | float | None = None,
        estimated_cost: int | float | None = None,
        approval_count: int | float | None = None,
        cancellation_reason: str | None = None,
        recovery_action: str | None = None,
        event_type: str | None = None,
        timestamp_utc: str | None = None,
    ) -> dict[str, Any] | None:
        """Write one bounded receipt and return the serialized safe shape."""

        if self.root is None or self._closed:
            return None
        timestamp = timestamp_utc or _utc_timestamp()
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            day = parsed.astimezone(timezone.utc).date().isoformat()
            timestamp = parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            timestamp = _utc_timestamp()
            day = timestamp[:10]
        with self._lock:
            self._sequence += 1
            record: dict[str, Any] = {
                "schema_version": OBSERVABILITY_SCHEMA_VERSION,
                "timestamp_utc": timestamp,
                "monotonic_ns": time.monotonic_ns(),
                "run_id": self.run_id,
                "sequence": self._sequence,
                "operation_id": _safe_token(operation_id or uuid4().hex),
                "component": _safe_token(component),
                "capability": _safe_token(capability),
                "phase": _safe_token(phase),
                "outcome": _safe_outcome(outcome),
                "adapter_id": _safe_token(adapter_id, default="unknown"),
                "adapter_version": _safe_token(adapter_version, default="unknown"),
                "provider_kind": _safe_token(provider_kind, default="unknown"),
                "processing_location": _safe_location(processing_location),
            }
            for key, value in (
                ("duration_ms", duration_ms),
                ("queue_ms", queue_ms),
                ("retry_count", retry_count),
                ("input_units", input_units),
                ("output_units", output_units),
                ("cache_units", cache_units),
                ("estimated_cost", estimated_cost),
                ("approval_count", approval_count),
            ):
                number = _safe_number(value)
                if number is not None:
                    record[key] = number
            if error_class:
                record["error_class"] = _safe_token(error_class)
            if cancellation_reason:
                record["cancellation_reason"] = _safe_token(cancellation_reason)
            if recovery_action:
                record["recovery_action"] = _safe_token(recovery_action)
            if event_type:
                record["event_type"] = _safe_token(event_type)
            session_hash = _opaque(session_id, self._salt)
            turn_hash = _opaque(turn_id, self._salt)
            if session_hash:
                record["session_id_hash"] = session_hash
            if turn_hash:
                record["turn_id_hash"] = turn_hash
            encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(encoded) > _MAX_LINE_BYTES:
                # This should only be possible if a future field is added;
                # fail closed rather than truncating JSON into an invalid line.
                record = {
                    "schema_version": OBSERVABILITY_SCHEMA_VERSION,
                    "timestamp_utc": timestamp,
                    "run_id": self.run_id,
                    "sequence": self._sequence,
                    "operation_id": record["operation_id"],
                    "component": record["component"],
                    "capability": record["capability"],
                    "phase": record["phase"],
                    "outcome": record["outcome"],
                    "error_class": "record_too_large",
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
                    self.logger.warning("agent observability write failed error_type=%s", type(error).__name__)
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
        # Never overwrite an earlier diagnostic record.  Continue allocating
        # a fresh bounded part if an unusually busy day exceeds the normal
        # part hint; the scan is capped to avoid unbounded filesystem work.
        for index in range(_MAX_PARTS + 1, 10001):
            candidate = self.root / f"{day}.{index}.jsonl"
            if not candidate.exists() or candidate.stat().st_size + incoming_bytes <= self.max_bytes:
                return candidate
        raise OSError("agent observability has too many daily parts")

    def aggregate(self, day: str | date_type | None = None) -> dict[str, Any]:
        """Aggregate one UTC day without exposing source record payloads."""

        selected = _safe_date(day)
        files = self._files_for(selected)
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        invalid_lines = 0
        total_lines = 0
        for path in files:
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
                if not isinstance(value, dict) or value.get("schema_version") != OBSERVABILITY_SCHEMA_VERSION:
                    invalid_lines += 1
                    continue
                # Re-validate through the same allowlist and omit anything an
                # older/newer writer may have appended unexpectedly.
                key = (
                    _safe_token(value.get("component")),
                    _safe_token(value.get("capability")),
                    _safe_token(value.get("adapter_id")),
                    _safe_token(value.get("provider_kind")),
                    _safe_location(value.get("processing_location")),
                )
                groups[key].append(value)
        summaries: list[dict[str, Any]] = []
        for key, values in sorted(groups.items()):
            durations = [n for n in (_safe_number(item.get("duration_ms")) for item in values) if n is not None]
            queue = [n for n in (_safe_number(item.get("queue_ms")) for item in values) if n is not None]
            retries = [n for n in (_safe_number(item.get("retry_count")) for item in values) if n is not None]
            summary: dict[str, Any] = {
                "component": key[0],
                "capability": key[1],
                "adapter_id": key[2],
                "provider_kind": key[3],
                "processing_location": key[4],
                "count": len(values),
                "outcomes": {outcome: sum(1 for item in values if item.get("outcome") == outcome) for outcome in sorted(_OUTCOMES) if any(item.get("outcome") == outcome for item in values)},
            }
            if durations:
                summary["duration_ms"] = {
                    "p50": _percentile(durations, 0.50),
                    "p95": _percentile(durations, 0.95),
                    "total": sum(durations),
                }
            if queue:
                summary["queue_ms"] = {"p50": _percentile(queue, 0.50), "p95": _percentile(queue, 0.95)}
            if retries:
                summary["retry_count"] = sum(retries)
            for field in ("input_units", "output_units", "cache_units", "estimated_cost", "approval_count"):
                numbers = [n for n in (_safe_number(item.get(field)) for item in values) if n is not None]
                if numbers:
                    summary[field] = sum(numbers)
            summaries.append(summary)
        return {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "day": selected,
            "generated_at": _utc_timestamp(),
            "source_files": len(files),
            "record_count": total_lines - invalid_lines,
            "invalid_lines": invalid_lines,
            "groups": summaries,
        }

    def write_daily_summary(self, day: str | date_type | None = None) -> dict[str, Any]:
        report = self.aggregate(day)
        if self.root is None:
            return report
        selected = report["day"]
        target = self.root / f"{selected}.summary.json"
        temporary = self.root / f".{selected}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        except OSError as error:
            if self.logger:
                self.logger.warning("agent observability summary write failed error_type=%s", type(error).__name__)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return report

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.root is not None,
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "run_id": self.run_id if self.root is not None else None,
            "relative_path": "logs/agent-observability" if self.root is not None else None,
            "retention": "runtime-disposable; aggregate summaries are not recovery data",
        }

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _files_for(self, day: str) -> list[Path]:
        if self.root is None:
            return []
        candidates = [self.root / f"{day}.jsonl"]
        # Read all matching numeric parts, including overflow parts allocated
        # on unusually busy days; ignore unrelated files in the directory.
        try:
            candidates.extend(
                path
                for path in self.root.glob(f"{day}.*.jsonl")
                if path.name.removesuffix(".jsonl").rsplit(".", 1)[-1].isdigit()
            )
        except OSError:
            pass
        return sorted({path for path in candidates if path.is_file()}, key=lambda item: item.name)


def classify_rpc_method(method: str) -> tuple[str, str]:
    """Map a public RPC name to stable machine dimensions."""

    candidate = str(method or "unknown").strip()
    prefix = candidate.split(".", 1)[0].lower() if candidate else "unknown"
    component = {
        "agent": "agent",
        "workspace": "workspace",
        "browser": "browser",
        "chat": "provider",
        "provider": "provider",
        "module": "module",
        "memory": "memory",
        "vision": "vision",
        "audio": "audio",
        "task": "task",
        "snapshot": "storage",
        "core": "core",
    }.get(prefix, "rpc")
    return component, _safe_token(candidate)


__all__ = [
    "AgentObservability",
    "OBSERVABILITY_SCHEMA_VERSION",
    "classify_rpc_method",
]
