"""Versioned, content-free model and plugin evaluation helpers.

The evaluator is deliberately offline.  A runner supplies one small result
record for each task in the fixed task set; this module validates the record,
groups only comparable runs, and produces bounded statistics.  Prompts,
outputs, paths, credentials, and arbitrary metadata are rejected rather than
being copied into an evaluation report.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


TASK_SET_SCHEMA_VERSION = "sumika.model-evaluation-taskset/v1"
EVALUATION_SCHEMA_VERSION = "sumika.model-evaluation/v1"
DEFAULT_MIN_REPETITIONS = 3

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~\-]{0,159}$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_OUTCOMES = frozenset({"completed", "failed", "cancelled", "rejected", "unknown"})
_DIFFICULTIES = frozenset({"basic", "moderate", "complex", "critical"})
_RISKS = frozenset({"low", "normal", "high", "critical"})
_SENSITIVE_KEYS = frozenset(
    {
        "prompt",
        "prompts",
        "input",
        "inputs",
        "output",
        "outputs",
        "response",
        "responses",
        "content",
        "body",
        "text",
        "message",
        "messages",
        "path",
        "paths",
        "file",
        "files",
        "diff",
        "patch",
        "dom",
        "screenshot",
        "audio",
        "cookie",
        "cookies",
        "token",
        "tokens",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
    }
)


class EvaluationValidationError(ValueError):
    """A safe, non-content-bearing validation error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _label(value: Any, field_name: str, *, allow_unknown: bool = True) -> str:
    if not isinstance(value, str):
        raise EvaluationValidationError(f"{field_name}-must-be-label")
    value = value.strip()
    if not value or len(value) > 160 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise EvaluationValidationError(f"{field_name}-invalid")
    if value in {"unknown", "none"}:
        if allow_unknown:
            return value
        raise EvaluationValidationError(f"{field_name}-invalid")
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise EvaluationValidationError(f"{field_name}-invalid")
    return value


def _boolean(value: Any, field_name: str, *, optional: bool = False) -> bool | None:
    if value is None and optional:
        return None
    if not isinstance(value, bool):
        raise EvaluationValidationError(f"{field_name}-must-be-boolean")
    return value


def _number(value: Any, field_name: str, *, optional: bool = True, maximum: float = 10**9) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationValidationError(f"{field_name}-must-be-number")
    if not math.isfinite(float(value)) or float(value) < 0 or float(value) > maximum:
        raise EvaluationValidationError(f"{field_name}-out-of-range")
    return float(value)


def _integer(value: Any, field_name: str, *, optional: bool = False, maximum: int = 100) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationValidationError(f"{field_name}-must-be-integer")
    if value < 0 or value > maximum:
        raise EvaluationValidationError(f"{field_name}-out-of-range")
    return value


def _tuple_labels(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > 32:
        raise EvaluationValidationError(f"{field_name}-must-be-non-empty-list")
    result: list[str] = []
    for item in value:
        label = _label(item, field_name, allow_unknown=False)
        if label not in result:
            result.append(label)
    return tuple(result)


def _check_no_sensitive_keys(value: Any) -> None:
    """Reject content-like fields before parsing anything else."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or any(part in normalized for part in ("api_key", "apikey", "password", "cookie", "secret")):
                # Do not echo even the rejected field name: a caller may use
                # a custom key that itself contains sensitive information.
                raise EvaluationValidationError("forbidden-field")
            _check_no_sensitive_keys(child)
    elif isinstance(value, list):
        if len(value) > 64:
            raise EvaluationValidationError("nested-list-too-large")
        for child in value:
            _check_no_sensitive_keys(child)


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    id: str
    kind: str
    workload_version: str
    difficulty: str
    risk: str
    required_capabilities: tuple[str, ...]
    assertions: tuple[str, ...]
    label: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationTask":
        if not isinstance(value, Mapping):
            raise EvaluationValidationError("task-must-be-object")
        _check_no_sensitive_keys(value)
        allowed = {"id", "kind", "workload_version", "difficulty", "risk", "required_capabilities", "assertions", "label"}
        unknown = set(value) - allowed
        if unknown:
            raise EvaluationValidationError("task-contains-unsupported-field")
        task_id = _label(value.get("id"), "task-id", allow_unknown=False)
        difficulty = _label(value.get("difficulty"), "task-difficulty", allow_unknown=False).lower()
        risk = _label(value.get("risk"), "task-risk", allow_unknown=False).lower()
        if difficulty not in _DIFFICULTIES:
            raise EvaluationValidationError("task-difficulty-invalid")
        if risk not in _RISKS:
            raise EvaluationValidationError("task-risk-invalid")
        assertions = _tuple_labels(value.get("assertions"), "task-assertions")
        label = value.get("label", "")
        if not isinstance(label, str) or len(label) > 120 or any(ord(char) < 32 or ord(char) == 127 for char in label):
            raise EvaluationValidationError("task-label-invalid")
        return cls(
            id=task_id,
            kind=_label(value.get("kind"), "task-kind", allow_unknown=False),
            workload_version=_label(value.get("workload_version"), "workload-version", allow_unknown=False),
            difficulty=difficulty,
            risk=risk,
            required_capabilities=_tuple_labels(value.get("required_capabilities"), "task-capabilities"),
            assertions=assertions,
            label=label.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_capabilities"] = list(self.required_capabilities)
        value["assertions"] = list(self.assertions)
        return value


@dataclass(frozen=True, slots=True)
class EvaluationTaskSet:
    id: str
    version: str
    tasks: tuple[EvaluationTask, ...]
    schema_version: str = TASK_SET_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationTaskSet":
        if not isinstance(value, Mapping):
            raise EvaluationValidationError("task-set-must-be-object")
        if value.get("schema_version") != TASK_SET_SCHEMA_VERSION:
            raise EvaluationValidationError("task-set-schema-unsupported")
        task_id = _label(value.get("task_set_id"), "task-set-id", allow_unknown=False)
        version = _label(value.get("version"), "task-set-version", allow_unknown=False)
        raw_tasks = value.get("tasks")
        if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= 64:
            raise EvaluationValidationError("task-set-tasks-invalid")
        tasks = tuple(EvaluationTask.from_dict(item) for item in raw_tasks)
        ids = [item.id for item in tasks]
        if len(set(ids)) != len(ids):
            raise EvaluationValidationError("task-set-duplicate-task-id")
        return cls(id=task_id, version=version, tasks=tasks)

    @classmethod
    def from_file(cls, path: str | Path) -> "EvaluationTaskSet":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise EvaluationValidationError("task-set-file-invalid") from error
        return cls.from_dict(value)

    def task(self, task_id: str) -> EvaluationTask:
        for item in self.tasks:
            if item.id == task_id:
                return item
        raise EvaluationValidationError("unknown-task-id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_set_id": self.id,
            "version": self.version,
            "tasks": [item.to_dict() for item in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class EvaluationManifest:
    """Dimensions that must match for two candidates to be comparable."""

    task_set_id: str
    task_set_version: str
    harness_id: str
    harness_version: str
    adapter_id: str
    adapter_version: str
    provider_kind: str
    model_id: str
    model_version: str
    hardware_class: str
    privacy_policy: str
    cache_state: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], task_set: EvaluationTaskSet) -> "EvaluationManifest":
        if not isinstance(value, Mapping):
            raise EvaluationValidationError("manifest-must-be-object")
        allowed = {
            "task_set_id", "task_set_version", "harness_id", "harness_version", "adapter_id", "adapter_version",
            "provider_kind", "model_id", "model_version", "hardware_class", "privacy_policy", "cache_state",
        }
        if set(value) - allowed:
            raise EvaluationValidationError("manifest-contains-unsupported-field")
        result = cls(
            task_set_id=_label(value.get("task_set_id"), "task-set-id", allow_unknown=False),
            task_set_version=_label(value.get("task_set_version"), "task-set-version", allow_unknown=False),
            harness_id=_label(value.get("harness_id"), "harness-id"),
            harness_version=_label(value.get("harness_version"), "harness-version"),
            adapter_id=_label(value.get("adapter_id"), "adapter-id"),
            adapter_version=_label(value.get("adapter_version"), "adapter-version"),
            provider_kind=_label(value.get("provider_kind"), "provider-kind"),
            model_id=_label(value.get("model_id"), "model-id"),
            model_version=_label(value.get("model_version"), "model-version"),
            hardware_class=_label(value.get("hardware_class"), "hardware-class"),
            privacy_policy=_label(value.get("privacy_policy"), "privacy-policy"),
            cache_state=_label(value.get("cache_state"), "cache-state"),
        )
        if result.task_set_id != task_set.id or result.task_set_version != task_set.version:
            raise EvaluationValidationError("manifest-task-set-mismatch")
        return result

    def comparison_key(self) -> tuple[str, ...]:
        return (
            self.task_set_id,
            self.task_set_version,
            self.harness_id,
            self.harness_version,
            self.adapter_id,
            self.adapter_version,
            self.provider_kind,
            self.hardware_class,
            self.privacy_policy,
            self.cache_state,
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    task_id: str
    route_id: str
    manifest: EvaluationManifest
    success: bool
    outcome: str
    tool_success: bool | None = None
    retry_count: int = 0
    latency_ms: float | None = None
    estimated_cost: float | None = None
    quota_units: float | None = None
    quality_passed: bool | None = None
    user_correction: bool | None = None
    approval_count: int | None = None
    error_class: str | None = None
    observed_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], task_set: EvaluationTaskSet) -> "EvaluationRecord":
        if not isinstance(value, Mapping):
            raise EvaluationValidationError("record-must-be-object")
        _check_no_sensitive_keys(value)
        allowed = {
            "schema_version", "task_id", "route_id", "manifest", "success", "outcome", "tool_success", "retry_count",
            "latency_ms", "estimated_cost", "quota_units", "quality_passed", "user_correction", "approval_count",
            "error_class", "observed_at",
        }
        if set(value) - allowed:
            raise EvaluationValidationError("record-contains-unsupported-field")
        schema = value.get("schema_version", EVALUATION_SCHEMA_VERSION)
        if schema != EVALUATION_SCHEMA_VERSION:
            raise EvaluationValidationError("record-schema-unsupported")
        task_id = _label(value.get("task_id"), "task-id", allow_unknown=False)
        task_set.task(task_id)
        manifest = EvaluationManifest.from_dict(value.get("manifest"), task_set)
        success = _boolean(value.get("success"), "success")
        outcome = _label(value.get("outcome"), "outcome", allow_unknown=False).lower()
        if outcome not in _OUTCOMES:
            raise EvaluationValidationError("outcome-invalid")
        if outcome in {"failed", "cancelled", "rejected"} and success:
            raise EvaluationValidationError("successful-record-has-failure-outcome")
        observed_at = value.get("observed_at", _now())
        if not isinstance(observed_at, str) or not _ISO_RE.match(observed_at) or len(observed_at) > 80:
            raise EvaluationValidationError("observed-at-invalid")
        try:
            datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise EvaluationValidationError("observed-at-invalid") from error
        return cls(
            task_id=task_id,
            route_id=_label(value.get("route_id"), "route-id", allow_unknown=False),
            manifest=manifest,
            success=bool(success),
            outcome=outcome,
            tool_success=_boolean(value.get("tool_success"), "tool-success", optional=True),
            retry_count=int(_integer(value.get("retry_count", 0), "retry-count", maximum=100) or 0),
            latency_ms=_number(value.get("latency_ms"), "latency-ms", maximum=86_400_000),
            estimated_cost=_number(value.get("estimated_cost"), "estimated-cost", maximum=10**6),
            quota_units=_number(value.get("quota_units"), "quota-units", maximum=10**12),
            quality_passed=_boolean(value.get("quality_passed"), "quality-passed", optional=True),
            user_correction=_boolean(value.get("user_correction"), "user-correction", optional=True),
            approval_count=_integer(value.get("approval_count"), "approval-count", optional=True, maximum=1000),
            error_class=_label(value.get("error_class"), "error-class") if value.get("error_class") is not None else None,
            observed_at=observed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "task_id": self.task_id,
            "route_id": self.route_id,
            "manifest": self.manifest.to_dict(),
            "success": self.success,
            "outcome": self.outcome,
            "tool_success": self.tool_success,
            "retry_count": self.retry_count,
            "latency_ms": self.latency_ms,
            "estimated_cost": self.estimated_cost,
            "quota_units": self.quota_units,
            "quality_passed": self.quality_passed,
            "user_correction": self.user_correction,
            "approval_count": self.approval_count,
            "error_class": self.error_class,
            "observed_at": self.observed_at,
        }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = index - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _wilson(successes: int, total: int) -> dict[str, float | int | None]:
    if total <= 0:
        return {"sample_count": 0, "lower": None, "upper": None}
    z = 1.96
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total) / denominator
    return {
        "sample_count": total,
        "lower": round(max(0.0, centre - margin), 4),
        "upper": round(min(1.0, centre + margin), 4),
    }


def _rate(values: list[bool]) -> float | None:
    return round(sum(1 for value in values if value) / len(values), 4) if values else None


def _candidate_stats(records: list[EvaluationRecord], task_set: EvaluationTaskSet, min_repetitions: int) -> dict[str, Any]:
    success_count = sum(1 for item in records if item.success)
    tools = [item.tool_success for item in records if item.tool_success is not None]
    quality = [item.quality_passed for item in records if item.quality_passed is not None]
    corrections = [item.user_correction for item in records if item.user_correction is not None]
    latencies = [item.latency_ms for item in records if item.latency_ms is not None]
    costs = [item.estimated_cost for item in records if item.estimated_cost is not None]
    quota = [item.quota_units for item in records if item.quota_units is not None]
    counts = {task.id: sum(1 for item in records if item.task_id == task.id) for task in task_set.tasks}
    per_task: list[dict[str, Any]] = []
    for task in task_set.tasks:
        subset = [item for item in records if item.task_id == task.id]
        if not subset:
            continue
        per_task.append(
            {
                "task_id": task.id,
                "sample_count": len(subset),
                "success_rate": round(sum(1 for item in subset if item.success) / len(subset), 4),
                "latency_ms": {"p50": _percentile([item.latency_ms for item in subset if item.latency_ms is not None], 0.5), "p95": _percentile([item.latency_ms for item in subset if item.latency_ms is not None], 0.95)},
            }
        )
    complete = bool(counts) and all(counts[task.id] >= min_repetitions for task in task_set.tasks)
    outcomes = {outcome: sum(1 for item in records if item.outcome == outcome) for outcome in sorted(_OUTCOMES) if any(item.outcome == outcome for item in records)}
    return {
        "route_id": records[0].route_id,
        "model_id": records[0].manifest.model_id,
        "model_version": records[0].manifest.model_version,
        "sample_count": len(records),
        "task_count": len(task_set.tasks),
        "covered_task_count": sum(1 for count in counts.values() if count),
        "samples_per_task": counts,
        "minimum_repetitions": min_repetitions,
        "evidence_status": "ready" if complete else "insufficient",
        "success_rate": round(success_count / len(records), 4) if records else None,
        "success_confidence_95": _wilson(success_count, len(records)),
        "tool_success_rate": _rate([bool(value) for value in tools]),
        "tool_sample_count": len(tools),
        "quality_pass_rate": _rate([bool(value) for value in quality]),
        "quality_sample_count": len(quality),
        "user_correction_rate": _rate([bool(value) for value in corrections]),
        "user_correction_sample_count": len(corrections),
        "retry_total": sum(item.retry_count for item in records),
        "retry_rate": round(sum(item.retry_count for item in records) / len(records), 4) if records else None,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "estimated_cost": {"total": round(sum(costs), 8) if costs else None, "average": round(sum(costs) / len(costs), 8) if costs else None},
        "quota_units": round(sum(quota), 6) if quota else None,
        "outcomes": outcomes,
        "per_task": per_task,
    }


def _diagnostic_recommendation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [item for item in candidates if item.get("evidence_status") == "ready" and item.get("success_confidence_95", {}).get("lower") is not None]
    if len(ready) < 2:
        return {"status": "insufficient-evidence", "candidate_route_id": None}
    ordered = sorted(ready, key=lambda item: (float(item["success_rate"]), float(item["tool_success_rate"] or 0), -(float(item["latency_ms"]["p95"] or 10**12))))
    best = ordered[-1]
    best_lower = float(best["success_confidence_95"]["lower"])
    others_upper = max(float(item["success_confidence_95"]["upper"]) for item in ordered[:-1])
    if best_lower <= others_upper:
        return {"status": "inconclusive", "candidate_route_id": None, "reason": "confidence-intervals-overlap"}
    return {"status": "diagnostic-recommendation", "candidate_route_id": best["route_id"], "reason": "success-confidence-separates-candidates"}


def aggregate_evaluations(
    records: Iterable[EvaluationRecord],
    task_set: EvaluationTaskSet,
    *,
    min_repetitions: int = DEFAULT_MIN_REPETITIONS,
) -> dict[str, Any]:
    """Aggregate records into comparable cohorts without changing routing."""

    if isinstance(min_repetitions, bool) or not isinstance(min_repetitions, int) or not 1 <= min_repetitions <= 100:
        raise EvaluationValidationError("minimum-repetitions-invalid")
    groups: dict[tuple[str, ...], dict[tuple[str, ...], list[EvaluationRecord]]] = {}
    for record in records:
        if not isinstance(record, EvaluationRecord):
            raise EvaluationValidationError("records-must-be-evaluation-records")
        task_set.task(record.task_id)
        comparison = record.manifest.comparison_key()
        candidate = (record.route_id, record.manifest.model_id, record.manifest.model_version)
        groups.setdefault(comparison, {}).setdefault(candidate, []).append(record)

    cohorts: list[dict[str, Any]] = []
    for comparison, candidates_map in sorted(groups.items()):
        candidate_stats = [_candidate_stats(items, task_set, min_repetitions) for _, items in sorted(candidates_map.items())]
        first = next(iter(candidates_map.values()))[0].manifest
        cohorts.append(
            {
                "comparison": {
                    "task_set_id": first.task_set_id,
                    "task_set_version": first.task_set_version,
                    "harness_id": first.harness_id,
                    "harness_version": first.harness_version,
                    "adapter_id": first.adapter_id,
                    "adapter_version": first.adapter_version,
                    "provider_kind": first.provider_kind,
                    "hardware_class": first.hardware_class,
                    "privacy_policy": first.privacy_policy,
                    "cache_state": first.cache_state,
                },
                "candidate_count": len(candidate_stats),
                "candidates": candidate_stats,
                "recommendation": _diagnostic_recommendation(candidate_stats),
            }
        )
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "task_set": {"id": task_set.id, "version": task_set.version, "task_count": len(task_set.tasks)},
        "record_count": sum(len(items) for candidates in groups.values() for items in candidates.values()),
        "cohort_count": len(cohorts),
        "minimum_repetitions": min_repetitions,
        "cohorts": cohorts,
        "routing_action": "none",
        "generated_at": _now(),
    }


def load_records(path: str | Path, task_set: EvaluationTaskSet) -> tuple[list[EvaluationRecord], list[dict[str, Any]]]:
    """Read JSON or JSONL and return safe line-level errors, never values."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        return [], [{"line": 0, "code": "input-unreadable", "error_type": type(error).__name__}]
    if source.suffix.lower() == ".jsonl":
        raw_items: list[tuple[int, Any]] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw_items.append((line_number, json.loads(line)))
            except (ValueError, json.JSONDecodeError):
                raw_items.append((line_number, None))
    else:
        try:
            payload = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            return [], [{"line": 1, "code": "input-json-invalid"}]
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            payload = payload["records"]
        if not isinstance(payload, list):
            return [], [{"line": 1, "code": "input-records-must-be-list"}]
        raw_items = list(enumerate(payload, 1))
    records: list[EvaluationRecord] = []
    errors: list[dict[str, Any]] = []
    for line_number, raw in raw_items:
        if raw is None:
            errors.append({"line": line_number, "code": "record-json-invalid"})
            continue
        try:
            records.append(EvaluationRecord.from_dict(raw, task_set))
        except EvaluationValidationError as error:
            errors.append({"line": line_number, "code": error.code})
    return records, errors


__all__ = [
    "DEFAULT_MIN_REPETITIONS",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationManifest",
    "EvaluationRecord",
    "EvaluationTask",
    "EvaluationTaskSet",
    "EvaluationValidationError",
    "TASK_SET_SCHEMA_VERSION",
    "aggregate_evaluations",
    "load_records",
]
