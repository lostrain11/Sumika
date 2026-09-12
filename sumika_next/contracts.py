from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from pathlib import Path


class Trust(str, Enum):
    MANAGED = "managed"
    UNVERIFIED = "unverified"


class TaskState(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    UNKNOWN = "unknown"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"


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
    # Exact serialized arguments, including content, command, cwd and model settings.
    # The adapter must execute these bytes, not fetch mutable arguments elsewhere.
    arguments: bytes = b"{}"


@dataclass(frozen=True)
class Workspace:
    path: Path

    def __post_init__(self):
        if not self.path.is_absolute() or not self.path.is_dir():
            raise ValueError("workspace must be an existing absolute directory")


@dataclass(frozen=True)
class Session:
    instance_id: str
    session_id: str
    workspace: Workspace


@dataclass(frozen=True)
class TaskEvent:
    binding: WorkBinding
    sequence: int
    state: TaskState
    detail: str = ""


@dataclass(frozen=True)
class Recovery:
    binding: WorkBinding
    state: TaskState
    can_replay: bool = False
    reason: str = "Inspection does not authorize replay"


@dataclass(frozen=True)
class Task:
    binding: WorkBinding
    state: TaskState


@dataclass(frozen=True)
class Cancellation:
    binding: WorkBinding
    acknowledged: bool
    # Acknowledgement is not proof that an in-flight side effect never occurred.
    state: TaskState = TaskState.CANCEL_REQUESTED


class Harness(Protocol):
    instance: HarnessInstance

    def execute(self, request: ToolRequest) -> dict: ...
    def inspect(self, binding: WorkBinding) -> Recovery: ...
    def close(self) -> None: ...
