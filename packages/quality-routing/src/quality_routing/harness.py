from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Mapping

from .contracts import RoutingError, bounded_text, count, identifier


__all__ = ["HarnessRecord", "RuntimeBinding", "ExternalSessionRef", "CapabilityEvidence",
           "ModelInvocation", "InvocationReceipt", "RecoveryAssessment", "MergePreview"]


class HarnessRecord:
    __slots__ = ()
    schema_version: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        result = {"schema_version": self.schema_version}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = (value.to_dict() if isinstance(value, HarnessRecord)
                                 else list(value) if isinstance(value, tuple) else value)
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]):
        if not isinstance(value, Mapping) or value.get("schema_version") != cls.schema_version:
            raise RoutingError("unsupported harness record schema")
        names = {item.name for item in fields(cls)}
        if set(value) - names - {"schema_version"}:
            raise RoutingError("unexpected harness record fields")
        arguments = {key: item for key, item in value.items() if key != "schema_version"}
        if "runtime_binding" in arguments and arguments["runtime_binding"] is not None:
            arguments["runtime_binding"] = RuntimeBinding.from_dict(arguments["runtime_binding"])
        try:
            return cls(**arguments)
        except TypeError as error:
            raise RoutingError("incomplete harness record") from error


@dataclass(frozen=True, slots=True)
class RuntimeBinding(HarnessRecord):
    schema_version: ClassVar[str] = "runtime-binding/v1"
    harness_id: str
    instance_id: str
    distribution_id: str
    adapter_version: str
    execution_mode: str
    identity_evidence_ref: str
    launch_id: str | None = None
    launch_evidence_ref: str | None = None

    def __post_init__(self):
        for name in ("harness_id", "instance_id", "distribution_id", "adapter_version", "identity_evidence_ref"):
            identifier(getattr(self, name))
        if not isinstance(self.execution_mode, str) or self.execution_mode not in {"managed", "external", "api"}:
            raise RoutingError("invalid runtime execution mode")
        if (self.launch_id is None) != (self.launch_evidence_ref is None):
            raise RoutingError("launch identity requires evidence")
        if self.launch_id is not None:
            identifier(self.launch_id)
            identifier(self.launch_evidence_ref)

    def matches_attempt(self, current: RuntimeBinding) -> bool:
        return isinstance(current, RuntimeBinding) and self.launch_id is not None and self == current


@dataclass(frozen=True, slots=True)
class ExternalSessionRef(HarnessRecord):
    schema_version: ClassVar[str] = "external-session-ref/v1"
    harness_id: str
    instance_id: str
    session_id: str
    turn_id: str | None = None

    def __post_init__(self):
        identifier(self.harness_id)
        identifier(self.instance_id)
        for name in ("session_id", "turn_id"):
            value = getattr(self, name)
            if name == "turn_id" and value is None:
                continue
            if not isinstance(value, str) or not value or len(value) > 512 or any(ord(char) < 32 for char in value):
                raise RoutingError("invalid external session reference")

    @property
    def session_key(self) -> tuple[str, str, str]:
        return self.harness_id, self.instance_id, self.session_id

    def belongs_to(self, binding: RuntimeBinding) -> bool:
        return self.harness_id == binding.harness_id and self.instance_id == binding.instance_id


def _string_tuple(record: HarnessRecord, name: str, validator=identifier) -> None:
    value = getattr(record, name)
    if not isinstance(value, (tuple, list)) or len(value) > 128:
        raise RoutingError("invalid harness record list")
    for item in value:
        validator(item)
    object.__setattr__(record, name, tuple(value))


def _revision(work_request_id: str, requirement_revision: int) -> None:
    identifier(work_request_id)
    if count(requirement_revision) < 1:
        raise RoutingError("requirement revision must be positive")


def _binding(value: RuntimeBinding | None, optional: bool = False) -> None:
    if not isinstance(value, RuntimeBinding) and not (optional and value is None):
        raise RoutingError("invalid runtime binding")


def _digest(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise RoutingError("invalid content digest")


@dataclass(frozen=True, slots=True)
class CapabilityEvidence(HarnessRecord):
    schema_version: ClassVar[str] = "capability-evidence/v1"
    capability_id: str
    status: str
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self):
        identifier(self.capability_id)
        if not isinstance(self.status, str) or self.status not in {"supported", "unsupported", "unverified"}:
            raise RoutingError("invalid capability status")
        _string_tuple(self, "limitations", bounded_text)
        _string_tuple(self, "evidence_refs")


@dataclass(frozen=True, slots=True)
class ModelInvocation(HarnessRecord):
    schema_version: ClassVar[str] = "model-invocation/v1"
    work_request_id: str
    requirement_revision: int
    operation_id: str
    purpose: str
    candidate_id: str
    runtime_binding: RuntimeBinding
    input_ref: str
    input_digest: str
    limits_ref: str

    def __post_init__(self):
        _revision(self.work_request_id, self.requirement_revision)
        for name in ("operation_id", "candidate_id", "input_ref", "limits_ref"):
            identifier(getattr(self, name))
        bounded_text(self.purpose)
        _binding(self.runtime_binding)
        _digest(self.input_digest)


@dataclass(frozen=True, slots=True)
class InvocationReceipt(HarnessRecord):
    schema_version: ClassVar[str] = "invocation-receipt/v1"
    operation_id: str
    runtime_binding: RuntimeBinding
    submission: str
    result_ref: str | None = None
    usage_ref: str | None = None
    price_ref: str | None = None
    resource_receipt_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.operation_id)
        _binding(self.runtime_binding)
        if not isinstance(self.submission, str) or self.submission not in {"definitely-not-sent", "completed", "unknown"}:
            raise RoutingError("invalid submission fact")
        for name in ("result_ref", "usage_ref", "price_ref"):
            value = getattr(self, name)
            if value is not None:
                identifier(value)
        _string_tuple(self, "resource_receipt_refs")
        _string_tuple(self, "evidence_refs")
        if self.submission == "completed" and self.result_ref is None:
            raise RoutingError("completed invocation requires a result reference")
        if self.submission == "definitely-not-sent" and self.result_ref is not None:
            raise RoutingError("unsent invocation cannot have a result")


@dataclass(frozen=True, slots=True)
class RecoveryAssessment(HarnessRecord):
    schema_version: ClassVar[str] = "recovery-assessment/v1"
    work_request_id: str
    requirement_revision: int
    runtime_binding: RuntimeBinding | None
    operation_ids: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str
    unresolved_operation_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _revision(self.work_request_id, self.requirement_revision)
        _binding(self.runtime_binding, optional=True)
        for name in ("operation_ids", "allowed_actions", "evidence_refs", "unresolved_operation_ids"):
            _string_tuple(self, name)
        bounded_text(self.reason)
        if set(self.allowed_actions) - {"inspect", "reconcile", "resume"}:
            raise RoutingError("invalid recovery action")
        if set(self.unresolved_operation_ids) - set(self.operation_ids):
            raise RoutingError("unresolved operations must belong to the assessment")
        if "resume" in self.allowed_actions:
            if self.runtime_binding is None or self.runtime_binding.launch_id is None:
                raise RoutingError("resume requires a known launch")
            if not self.evidence_refs or self.unresolved_operation_ids:
                raise RoutingError("resume requires evidence and no unresolved operations")


@dataclass(frozen=True, slots=True)
class MergePreview(HarnessRecord):
    schema_version: ClassVar[str] = "merge-preview/v1"
    work_request_id: str
    requirement_revision: int
    preview_id: str
    source_digest: str
    changes_ref: str
    verification_refs: tuple[str, ...]
    runtime_binding: RuntimeBinding | None = None

    def __post_init__(self):
        _revision(self.work_request_id, self.requirement_revision)
        identifier(self.preview_id)
        identifier(self.changes_ref)
        _digest(self.source_digest)
        _string_tuple(self, "verification_refs")
        _binding(self.runtime_binding, optional=True)
