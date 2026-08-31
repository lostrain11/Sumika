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
# A separate envelope makes it explicit that a caller opted into projecting
# an already-finished run.  It is intentionally not a log/database format.
CAPTURE_SCHEMA_VERSION = "sumika.model-evaluation-capture/v1"
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
        "answer",
        "answers",
        "question",
        "questions",
        "context",
        "context_refs",
        "workspace",
        "artifacts",
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

_CAPTURE_TERMINAL_STATES = frozenset(
    {"completed", "failed", "cancelled", "rejected", "unknown", "interrupted", "partial"}
)
_CAPTURE_METRIC_KEYS = frozenset(
    {
        "success",
        "outcome",
        "tool_success",
        "retry_count",
        "latency_ms",
        "estimated_cost",
        "quota_units",
        "quality_passed",
        "user_correction",
        "approval_count",
        "error_class",
        "observed_at",
    }
)
_CAPTURE_RUN_KEYS = frozenset(
    {"task_id", "route_id", "status", "latency_ms", "retry_count", "error_code", "started_at", "completed_at"}
)
_CAPTURE_SPEC_KEYS = frozenset({"schema_version", "task_id", "route_id", "manifest", "run", "metrics"})


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


def _capture_field(value: Any, name: str, default: Any = None) -> Any:
    """Read one explicitly named field without serializing an arbitrary object."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _capture_label(value: Any, field_name: str, *, default: str = "unknown", allow_unknown: bool = True) -> str:
    """Validate a generated label and reject values that look like secrets/paths."""

    candidate = default if value in (None, "") else value
    if not isinstance(candidate, str):
        candidate = str(candidate)
    candidate = candidate.strip()
    # Route metadata is not a place to carry credentials or a user-specific
    # absolute path.  Keep the rejection code content-free.
    if re.search(r"(?i)(?:^|[\s:=])(sk-[A-Za-z0-9]|bearer\s+|eyJ[A-Za-z0-9_-]{8,})", candidate):
        raise EvaluationValidationError("forbidden-value")
    if re.match(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}|/)", candidate):
        raise EvaluationValidationError("absolute-path-forbidden")
    return _label(candidate, field_name, allow_unknown=allow_unknown)


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
        _check_no_sensitive_keys(value)
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


def manifest_from_route(
    route: Any,
    task_set: EvaluationTaskSet,
    *,
    harness_id: str = "unknown",
    harness_version: str = "unknown",
    adapter_id: str | None = None,
    adapter_version: str = "unknown",
    hardware_class: str = "unknown",
    privacy_policy: str = "unknown",
    cache_state: str = "unknown",
) -> EvaluationManifest:
    """Build a manifest from an adapter-owned route without copying metadata.

    Only a fixed set of scalar route fields is read.  In particular, this
    helper never serializes a route or its metadata, so a path or credential
    accidentally attached by an adapter cannot enter an evaluation record.
    """

    if not isinstance(task_set, EvaluationTaskSet):
        raise EvaluationValidationError("task-set-invalid")
    if route is None:
        raise EvaluationValidationError("route-required")
    if isinstance(route, Mapping):
        _check_no_sensitive_keys(route)
    metadata = _capture_field(route, "metadata", {})
    if isinstance(metadata, Mapping):
        _check_no_sensitive_keys(metadata)
    model_entry = metadata.get("model_entry") if isinstance(metadata, Mapping) else None
    if not isinstance(model_entry, Mapping):
        model_entry = {}
    else:
        _check_no_sensitive_keys(model_entry)

    def scalar(name: str, *sources: Mapping[str, Any] | None, default: Any = None) -> Any:
        direct = _capture_field(route, name, None)
        if direct not in (None, ""):
            return direct
        for source in sources:
            if isinstance(source, Mapping) and source.get(name) not in (None, ""):
                return source.get(name)
        return default

    route_id = _capture_label(scalar("route_id"), "route-id", allow_unknown=False)
    provider_kind = _capture_label(
        scalar("provider_kind", model_entry, metadata if isinstance(metadata, Mapping) else None, default=_capture_field(route, "source_kind", "unknown")),
        "provider-kind",
    )
    model_id = _capture_label(
        scalar("model_id", model_entry, metadata if isinstance(metadata, Mapping) else None, default=route_id),
        "model-id",
        allow_unknown=False,
    )
    model_version = _capture_label(
        scalar("model_version", model_entry, metadata if isinstance(metadata, Mapping) else None, default=_capture_field(route, "version", "unknown")),
        "model-version",
    )
    runtime = _capture_label(harness_id, "harness-id")
    runtime_version = _capture_label(harness_version, "harness-version")
    adapter = _capture_label(adapter_id or _capture_field(route, "adapter_id", None) or "unknown", "adapter-id")
    adapter_ver = _capture_label(adapter_version, "adapter-version")
    hardware = _capture_label(hardware_class, "hardware-class")
    privacy = _capture_label(privacy_policy, "privacy-policy")
    cache = _capture_label(cache_state, "cache-state")
    return EvaluationManifest(
        task_set_id=task_set.id,
        task_set_version=task_set.version,
        harness_id=runtime,
        harness_version=runtime_version,
        adapter_id=adapter,
        adapter_version=adapter_ver,
        provider_kind=provider_kind,
        model_id=model_id,
        model_version=model_version,
        hardware_class=hardware,
        privacy_policy=privacy,
        cache_state=cache,
    )


def _capture_run_status(run: Any) -> tuple[str, Any]:
    raw_status = _capture_field(run, "status", None)
    if raw_status in (None, ""):
        raise EvaluationValidationError("run-status-required")
    status = str(raw_status).strip().lower()
    if status in {"queued", "running"}:
        raise EvaluationValidationError("run-not-terminal")
    result = _capture_field(run, "result", None)
    # An internal Supervisor _Run has a result object.  Read only its status
    # and never call to_dict(), which could contain an answer body.
    result_status = _capture_field(result, "status", None)
    if result_status:
        result_status = str(result_status).strip().lower()
        if result_status not in _CAPTURE_TERMINAL_STATES:
            raise EvaluationValidationError("result-status-invalid")
        if status in _CAPTURE_TERMINAL_STATES and status != result_status:
            raise EvaluationValidationError("run-status-mismatch")
        status = result_status
    if status not in _CAPTURE_TERMINAL_STATES:
        raise EvaluationValidationError("run-status-invalid")
    return status, result


def _capture_run_route_id(run: Any, route: Any = None) -> Any:
    direct = _capture_field(run, "route_id", None)
    if direct not in (None, ""):
        return direct
    dispatch = _capture_field(run, "dispatch", None)
    nested = _capture_field(dispatch, "route_id", None)
    if nested not in (None, ""):
        return nested
    return _capture_field(route, "route_id", None)


def capture_evaluation_sample(
    run: Any,
    task_set: EvaluationTaskSet,
    *,
    task_id: str,
    manifest: EvaluationManifest | Mapping[str, Any] | None = None,
    route: Any = None,
    opt_in: bool = False,
    metrics: Mapping[str, Any] | None = None,
) -> EvaluationRecord:
    """Project one finished run into a content-free evaluation record.

    The explicit opt-in is intentional.  This function does not inspect logs,
    databases, prompts, answers, files, or browser state; callers must hand it
    one already-selected run and task label.
    """

    if opt_in is not True:
        raise EvaluationValidationError("capture-opt-in-required")
    if not isinstance(task_set, EvaluationTaskSet):
        raise EvaluationValidationError("task-set-invalid")
    task = task_set.task(task_id)
    if isinstance(run, Mapping):
        _check_no_sensitive_keys(run)
        allowed_run = set(_CAPTURE_RUN_KEYS) | {"schema_version"}
        if set(run) - allowed_run:
            raise EvaluationValidationError("run-contains-unsupported-field")
    status, result = _capture_run_status(run)
    if manifest is None:
        selected_route = route
        if selected_route is None:
            selected_route = _capture_field(run, "route", None)
        if selected_route is None:
            raise EvaluationValidationError("manifest-required")
        manifest_obj = manifest_from_route(selected_route, task_set)
    elif isinstance(manifest, EvaluationManifest):
        manifest_obj = manifest
        if manifest_obj.task_set_id != task_set.id or manifest_obj.task_set_version != task_set.version:
            raise EvaluationValidationError("manifest-task-set-mismatch")
    else:
        manifest_obj = EvaluationManifest.from_dict(manifest, task_set)

    if metrics is not None and not isinstance(metrics, Mapping):
        raise EvaluationValidationError("metrics-invalid")
    supplied = dict(metrics or {})
    _check_no_sensitive_keys(supplied)
    if set(supplied) - _CAPTURE_METRIC_KEYS:
        raise EvaluationValidationError("metrics-contains-unsupported-field")
    result_latency = _capture_field(result, "latency_ms", None)
    result_error = _capture_field(result, "error_code", None)
    result_error_class = supplied.pop("error_class", None)
    if result_error_class not in (None, ""):
        result_error_class = _capture_label(result_error_class, "error-class")
    if result_error_class in (None, "") and result_error:
        result_error_class = _capture_label(result_error, "error-class")
    values: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "task_id": task.id,
        "route_id": _capture_label(
            _capture_run_route_id(run, route) or manifest_obj.model_id,
            "route-id",
            allow_unknown=False,
        ),
        "manifest": manifest_obj.to_dict(),
        "success": status == "completed",
        "outcome": {"partial": "unknown", "interrupted": "unknown"}.get(status, status),
        "latency_ms": supplied.pop("latency_ms", None),
        "retry_count": supplied.pop("retry_count", _capture_field(run, "retry_count", 0)),
        "error_class": result_error_class,
        "observed_at": supplied.pop("observed_at", None) or _capture_field(run, "completed_at", None) or _now(),
    }
    if values["latency_ms"] is None:
        values["latency_ms"] = result_latency or _capture_field(run, "latency_ms", None)
    # A caller may add outcome/quality booleans, but never turn a non-success
    # terminal state into a successful sample.
    for name in ("success", "outcome"):
        supplied.pop(name, None)
    values.update(supplied)
    if values["outcome"] != "completed":
        values["success"] = False
    return EvaluationRecord.from_dict(values, task_set)


def capture_evaluation_records(
    runs: Iterable[Any],
    task_set: EvaluationTaskSet,
    *,
    task_id: str | None = None,
    task_ids: Iterable[str] | None = None,
    manifest: EvaluationManifest | Mapping[str, Any] | None = None,
    manifests: Iterable[EvaluationManifest | Mapping[str, Any]] | None = None,
    route: Any = None,
    metrics: Mapping[str, Any] | None = None,
    opt_in: bool = False,
) -> list[EvaluationRecord]:
    """Capture a bounded batch of explicitly selected terminal runs.

    ``task_id``/``manifest``/``metrics`` may be shared by the batch; callers
    that need per-run values can provide the corresponding plural iterables.
    No automatic discovery from logs, storage, or runtime objects is done.
    """

    if opt_in is not True:
        raise EvaluationValidationError("capture-opt-in-required")
    values = list(runs)
    if len(values) > 256:
        raise EvaluationValidationError("capture-limit-exceeded")
    ids = list(task_ids) if task_ids is not None else []
    if ids and len(ids) != len(values):
        raise EvaluationValidationError("task-ids-length-mismatch")
    manifest_values = list(manifests) if manifests is not None else []
    if manifest_values and len(manifest_values) != len(values):
        raise EvaluationValidationError("manifests-length-mismatch")
    captured: list[EvaluationRecord] = []
    for index, run in enumerate(values):
        selected_task = ids[index] if ids else task_id or _capture_field(run, "task_id", None)
        if not selected_task:
            raise EvaluationValidationError("task-id-required")
        selected_manifest = manifest_values[index] if manifest_values else manifest
        selected_metrics = metrics
        if callable(metrics):
            selected_metrics = metrics(run, index)
        selected_route = route(run, index) if callable(route) else route
        captured.append(
            capture_evaluation_sample(
                run,
                task_set,
                task_id=str(selected_task),
                manifest=selected_manifest,
                route=selected_route,
                metrics=selected_metrics,
                opt_in=True,
            )
        )
    return captured


def capture_evaluation_payload(records: Iterable[EvaluationRecord]) -> dict[str, Any]:
    """Return a bounded capture envelope suitable for an offline CLI."""

    output: list[dict[str, Any]] = []
    values = list(records)
    if len(values) > 256:
        raise EvaluationValidationError("capture-limit-exceeded")
    for record in values:
        if not isinstance(record, EvaluationRecord):
            raise EvaluationValidationError("capture-records-invalid")
        output.append(record.to_dict())
    return {"schema_version": CAPTURE_SCHEMA_VERSION, "records": output}


def load_capture_specs(
    path: str | Path,
    task_set: EvaluationTaskSet,
    *,
    opt_in: bool = False,
) -> tuple[list[EvaluationRecord], list[dict[str, Any]]]:
    """Load explicit capture specs without reading runtime state.

    The file is a handoff from an isolated runner, not a log source.  Only
    the fixed ``run`` and ``metrics`` allowlists are accepted, and errors are
    reduced to line numbers plus stable codes.
    """

    if opt_in is not True:
        return [], [{"line": 0, "code": "capture-opt-in-required"}]
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        return [], [{"line": 0, "code": "input-unreadable", "error_type": type(error).__name__}]
    raw_items: list[tuple[int, Any]] = []
    if source.suffix.lower() == ".jsonl":
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
        if isinstance(payload, Mapping) and isinstance(payload.get("captures"), list):
            payload = payload["captures"]
        elif isinstance(payload, Mapping) and payload.get("schema_version") == CAPTURE_SCHEMA_VERSION and isinstance(payload.get("records"), list):
            payload = payload["records"]
        if not isinstance(payload, list):
            return [], [{"line": 1, "code": "input-captures-must-be-list"}]
        raw_items = list(enumerate(payload, 1))

    records: list[EvaluationRecord] = []
    errors: list[dict[str, Any]] = []
    for line_number, raw in raw_items[:256]:
        if raw is None:
            errors.append({"line": line_number, "code": "capture-json-invalid"})
            continue
        try:
            if not isinstance(raw, Mapping):
                raise EvaluationValidationError("capture-must-be-object")
            _check_no_sensitive_keys(raw)
            if set(raw) - _CAPTURE_SPEC_KEYS and raw.get("schema_version") != EVALUATION_SCHEMA_VERSION:
                raise EvaluationValidationError("capture-contains-unsupported-field")
            schema = raw.get("schema_version", CAPTURE_SCHEMA_VERSION)
            if schema == EVALUATION_SCHEMA_VERSION:
                # Existing offline records may be deliberately re-used, but
                # they still pass the same strict EvaluationRecord parser.
                records.append(EvaluationRecord.from_dict(raw, task_set))
                continue
            if schema != CAPTURE_SCHEMA_VERSION:
                raise EvaluationValidationError("capture-schema-unsupported")
            task_id = raw.get("task_id")
            run = raw.get("run")
            if not isinstance(run, Mapping):
                raise EvaluationValidationError("capture-run-required")
            if raw.get("route_id") not in (None, ""):
                run = {**run, "route_id": raw["route_id"]}
            if set(run) - _CAPTURE_RUN_KEYS:
                raise EvaluationValidationError("capture-run-contains-unsupported-field")
            metrics = raw.get("metrics", {})
            if not isinstance(metrics, Mapping):
                raise EvaluationValidationError("capture-metrics-invalid")
            manifest = raw.get("manifest")
            if not isinstance(manifest, Mapping):
                raise EvaluationValidationError("capture-manifest-required")
            records.append(
                capture_evaluation_sample(
                    run,
                    task_set,
                    task_id=str(task_id or ""),
                    manifest=manifest,
                    opt_in=True,
                    metrics=metrics,
                )
            )
        except EvaluationValidationError as error:
            errors.append({"line": line_number, "code": error.code})
    if len(raw_items) > 256:
        errors.append({"line": 0, "code": "capture-limit-exceeded"})
    return records, errors


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
    "CAPTURE_SCHEMA_VERSION",
    "DEFAULT_MIN_REPETITIONS",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationManifest",
    "EvaluationRecord",
    "EvaluationTask",
    "EvaluationTaskSet",
    "EvaluationValidationError",
    "TASK_SET_SCHEMA_VERSION",
    "aggregate_evaluations",
    "capture_evaluation_payload",
    "capture_evaluation_records",
    "capture_evaluation_sample",
    "load_capture_specs",
    "load_records",
    "manifest_from_route",
]
