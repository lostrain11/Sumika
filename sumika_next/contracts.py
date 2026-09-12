from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Trust(str, Enum):
    MANAGED = "managed"
    UNVERIFIED = "unverified"


class TaskState(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HarnessInstance:
    harness_id: str
    instance_id: str
    trust: Trust


@dataclass(frozen=True)
class WorkBinding:
    instance_id: str
    request_id: str
    request_version: int
    session_id: str
    step_id: str


@dataclass(frozen=True)
class ToolRequest:
    binding: WorkBinding
    action: str
    target: str


class Harness(Protocol):
    def cancel(self, binding: WorkBinding) -> None: ...
    def inspect(self, binding: WorkBinding) -> TaskState: ...

