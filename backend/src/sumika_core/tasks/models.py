from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class AutonomyLevel(StrEnum):
    OFF = "L0"
    SUGGEST = "L1"
    SUPERVISED = "L2"
    SANDBOX = "L3"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TaskBudget:
    token_limit: int = 0
    cost_limit: float = 0.0
    time_limit_seconds: int = 0
    disk_limit_bytes: int = 0


@dataclass(slots=True)
class TaskRecord:
    title: str
    status: TaskStatus = TaskStatus.PENDING
    autonomy_level: AutonomyLevel = AutonomyLevel.OFF
    budget: TaskBudget = field(default_factory=TaskBudget)
    id: str = field(default_factory=lambda: str(uuid4()))
    character_id: str | None = None
    progress: float = 0.0
    result: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
