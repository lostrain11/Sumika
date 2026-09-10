from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol

from .contracts import Quote, RoutingError, amount, bounded_text, count, identifier


SCHEMA = "quality-workflow/v1"


def delegation_digest(steps: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(steps, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def check_delegation(parent: Mapping[str, Any], child: Mapping[str, Any]) -> None:
    authorization = parent.get("authorization") or {}
    request = WorkRequest(**{key: value for key, value in parent["request"].items() if key != "schema_version"})
    reference = child["parent_authorization"]
    steps = parent.get("external_steps", [])
    if parent.get("cancel_requested") or parent["status"] not in {"planning", "executing", "running", "verifying"}:
        raise RoutingError("parent work is not executable")
    if (reference["revision"] != request.revision or reference["request_id"] != request.request_id
            or authorization.get("fingerprint") != request.fingerprint
            or authorization.get("delegation_digest") != delegation_digest(steps)):
        raise RoutingError("parent authorization does not cover this plan version")
    if any(child["request"].get(key) != parent["request"].get(key) for key in ("assistant_id", "session_id", "project_id")):
        raise RoutingError("external child is outside the parent scope")
    step = next((item for item in steps if item["id"] == reference["step_id"]), None)
    if not step or any(step[key] != child["external"].get(key) for key in ("method", "payload_digest", "binding_digest")):
        raise RoutingError("external child differs from the confirmed step")
    if amount(authorization["max_cny"]) == 0 and not child["funding"]["free"]:
        raise RoutingError("free parent authorization cannot consume paid resources")
    check_authorization(request, authorization, child["candidate_id"], child["quote"]["high_cny"])


class RecordRepository(Protocol):
    def save_record(self, namespace: str, record_id: str, assistant_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get_record(self, namespace: str, record_id: str, assistant_id: str) -> dict[str, Any] | None: ...
    def list_records(self, namespace: str, assistant_id: str) -> list[dict[str, Any]]: ...
    def delete_record(self, namespace: str, record_id: str, assistant_id: str) -> bool: ...


@dataclass(frozen=True)
class WorkRequest:
    request_id: str
    assistant_id: str
    session_id: str
    goal: str
    revision: int = 1
    source: str = "workbench"
    project_id: str | None = None
    original_message_id: str | None = None

    def __post_init__(self) -> None:
        for value in (self.request_id, self.assistant_id, self.session_id, self.source):
            identifier(value)
        for value in (self.project_id, self.original_message_id):
            if value is not None:
                identifier(value)
        bounded_text(self.goal)
        count(self.revision)
        if self.revision < 1:
            raise RoutingError("revision must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA, **self.__dict__}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ExternalQuote:
    low_cny: Decimal | None
    typical_cny: Decimal | None
    high_cny: Decimal | None
    max_calls: int | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        for key in ("low_cny", "typical_cny", "high_cny"):
            value = getattr(self, key)
            if value is not None:
                object.__setattr__(self, key, amount(value))
        values = (self.low_cny, self.typical_cny, self.high_cny)
        if any(value is None for value in values) and not all(value is None for value in values):
            raise RoutingError("external monetary estimates must all be known or unknown")
        if self.high_cny is not None and not self.low_cny <= self.typical_cny <= self.high_cny:
            raise RoutingError("external monetary estimates must be ordered")
        for value in (self.max_calls, self.max_tokens):
            if value is not None:
                count(value)
                if value == 0:
                    raise RoutingError("unknown external limits must be null, not zero")

def classify_request(goal: str) -> dict[str, Any]:
    bounded_text(goal)
    lowered = goal.lower()
    risky = ("删除", "支付", "购买", "部署", "运行", "执行脚本", "修改文件", "迁移", "密钥", "摄像头", "设备", "delete", "deploy", "credentials", "migration")
    if any(word in lowered for word in risky):
        return {"complexity": "complex", "reason": "涉及执行资源或重要边界", "task_type": "work"}
    bounded = ("翻译", "translate", "提取", "extract", "分类", "classify", "转换为", "转成")
    complex_words = ("调研", "设计", "分析", "重构", "计划", "比较", "research", "design", "analyze", "代码", "code")
    if len(goal) <= 1500 and any(word in lowered for word in bounded) and not any(word in lowered for word in complex_words):
        return {"complexity": "simple", "reason": "有界文本转换，仍需结果验证", "task_type": "bounded-text"}
    return {"complexity": "complex", "reason": "没有可靠的简单任务证据，先确认范围", "task_type": "work"}


def admission_state(complexity: str, quote: Quote, *, funding: str, executable: bool) -> str:
    if not executable:
        return "unavailable"
    if complexity == "simple" and quote.high_cny == Decimal(0) and funding in {"free", "local", "grant"}:
        return "ready"
    return "awaiting-confirmation"


def authorize(request: WorkRequest, quote: Quote | ExternalQuote, *, candidate_ids: tuple[str, ...], max_cny: Any) -> dict[str, Any]:
    ceiling = amount(max_cny)
    if quote.high_cny is None:
        raise RoutingError("unknown price cannot promise a spending limit")
    if ceiling < quote.high_cny:
        raise RoutingError("limit is lower than the estimated upper bound")
    for candidate_id in candidate_ids:
        identifier(candidate_id)
    return {"schema_version": SCHEMA, "fingerprint": request.fingerprint, "revision": request.revision,
            "candidate_ids": list(candidate_ids), "max_cny": str(ceiling), "spent_cny": "0", "reserved_cny": "0"}


def check_authorization(request: WorkRequest, authorization: Mapping[str, Any], candidate_id: str, upper_cny: Any) -> None:
    if authorization.get("fingerprint") != request.fingerprint or authorization.get("revision") != request.revision:
        raise RoutingError("authorization does not cover this request version")
    if candidate_id not in authorization.get("candidate_ids", ()):
        raise RoutingError("candidate is outside the authorized pool")
    total = amount(authorization["spent_cny"]) + amount(authorization["reserved_cny"]) + amount(upper_cny)
    if total > amount(authorization["max_cny"]):
        raise RoutingError("authorized spending limit exceeded")


def work_artifact(task_id: str, assistant_id: str, text: str, *, revision: int = 1, source: str = "quality", format: str = "markdown") -> dict[str, Any]:
    for value in (task_id, assistant_id, source):
        identifier(value)
    if not isinstance(text, str) or not text.strip():
        raise RoutingError("empty artifact")
    count(revision)
    return {"schema_version": SCHEMA, "id": f"{task_id}:artifact:{revision}", "task_id": task_id,
            "assistant_id": assistant_id, "revision": revision, "content": text, "format": format,
            "source": source, "sha256": hashlib.sha256(text.encode()).hexdigest(), "verification": "verified"}
