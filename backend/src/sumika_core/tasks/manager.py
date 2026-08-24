"""Task lifecycle and audit boundary for the first task-center slice."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from ..events import EventBus
from ..protocol.models import EventEnvelope, utc_now
from ..storage import Storage
from .models import AutonomyLevel, TaskBudget, TaskStatus


class TaskError(ValueError):
    """Raised when a task request violates the lifecycle contract."""


_ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL, TaskStatus.PAUSED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.WAITING_APPROVAL, TaskStatus.PAUSED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.WAITING_APPROVAL: {TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.CANCELLED},
    TaskStatus.PAUSED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class TaskManager:
    """Persist task records and publish changes without running work itself."""

    def __init__(self, storage: Storage, events: EventBus) -> None:
        self.storage = storage
        self.events = events

    def ensure_default(self) -> dict[str, Any] | None:
        if self.storage.list_tasks():
            return None
        return self.create(
            title="核心服务",
            task_id="core-service",
            status=TaskStatus.RUNNING,
            progress=1.0,
            result={"summary": "本地核心服务就绪", "runner": "none"},
            logs=[{"message": "核心服务已启动", "timestamp": utc_now()}],
        )

    def list(self) -> list[dict[str, Any]]:
        return self.storage.list_tasks()

    def get(self, task_id: str) -> dict[str, Any]:
        task = self.storage.get_task(task_id)
        if task is None:
            raise TaskError(f"Unknown task: {task_id}")
        return task

    def create(
        self,
        *,
        title: str,
        task_id: str | None = None,
        status: TaskStatus | str = TaskStatus.PENDING,
        autonomy_level: AutonomyLevel | str = AutonomyLevel.OFF,
        budget: TaskBudget | dict[str, Any] | None = None,
        character_id: str | None = None,
        progress: float = 0.0,
        result: dict[str, Any] | None = None,
        permissions: list[str] | None = None,
        logs: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        clean_title = str(title).strip()
        if not clean_title:
            raise TaskError("title must not be empty")
        task_status = _status(status)
        task_autonomy = _autonomy(autonomy_level)
        task_budget = _budget(budget)
        task_progress = _progress(progress)
        task_id = task_id or f"task-{uuid4().hex[:12]}"
        if self.storage.get_task(task_id) is not None:
            raise TaskError(f"Task already exists: {task_id}")
        task_result = _object(result, "result")
        task_logs = _records(logs, "logs")
        task_artifacts = _records(artifacts, "artifacts")
        task = self.storage.create_task(
            task_id=task_id,
            title=clean_title,
            status=task_status.value,
            autonomy_level=task_autonomy.value,
            budget=task_budget,
            character_id=character_id,
            progress=task_progress,
            result=task_result,
            permissions=_strings(permissions),
            logs=task_logs,
            artifacts=task_artifacts,
        )
        self.events.publish(EventEnvelope("task.created", {"task": task}, character_id=character_id))
        return task

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | str | None = None,
        progress: float | None = None,
        result: dict[str, Any] | None = None,
        log: str | dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.get(task_id)
        current_status = _status(current["status"])
        next_status = _status(status) if status is not None else current_status
        if next_status != current_status and next_status not in _ALLOWED_TRANSITIONS[current_status]:
            raise TaskError(f"Invalid task transition: {current_status.value} -> {next_status.value}")
        next_progress = _progress(current["progress"] if progress is None else progress)
        if next_status == TaskStatus.COMPLETED:
            next_progress = 1.0
        next_result = dict(current["result"])
        if result is not None:
            if not isinstance(result, dict):
                raise TaskError("result must be an object")
            next_result = result
        next_logs = list(current["logs"])
        if log is not None:
            entry = dict(log) if isinstance(log, dict) else {"message": str(log)}
            entry.setdefault("timestamp", utc_now())
            next_logs.append(entry)
        next_artifacts = list(current["artifacts"])
        if artifact is not None:
            if not isinstance(artifact, dict):
                raise TaskError("artifact must be an object")
            next_artifacts.append(artifact)
        task = self.storage.update_task(
            task_id,
            status=next_status.value,
            progress=next_progress,
            result=next_result,
            logs=next_logs,
            artifacts=next_artifacts,
        )
        if task is None:
            raise TaskError(f"Unknown task: {task_id}")
        self.events.publish(EventEnvelope("task.updated", {"task": task}, character_id=task.get("character_id")))
        return task


def _status(value: TaskStatus | str) -> TaskStatus:
    try:
        return value if isinstance(value, TaskStatus) else TaskStatus(str(value))
    except ValueError as exc:
        raise TaskError(f"Unknown task status: {value}") from exc


def _autonomy(value: AutonomyLevel | str) -> AutonomyLevel:
    try:
        return value if isinstance(value, AutonomyLevel) else AutonomyLevel(str(value))
    except ValueError as exc:
        raise TaskError(f"Unknown autonomy level: {value}") from exc


def _budget(value: TaskBudget | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return asdict(TaskBudget())
    raw = asdict(value) if isinstance(value, TaskBudget) else value
    if not isinstance(raw, dict):
        raise TaskError("budget must be an object")
    result = asdict(TaskBudget())
    for key in result:
        if key not in raw:
            continue
        number = raw[key]
        if not isinstance(number, (int, float)) or isinstance(number, bool) or number < 0:
            raise TaskError(f"budget field must be non-negative: {key}")
        result[key] = int(number) if key != "cost_limit" else float(number)
    return result


def _progress(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TaskError("progress must be a number")
    if value < 0 or value > 1:
        raise TaskError("progress must be between 0 and 1")
    return float(value)


def _strings(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise TaskError("permissions must be a list of strings")
    return list(values)


def _object(value: dict[str, Any] | None, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TaskError(f"{name} must be an object")
    return dict(value)


def _records(values: list[dict[str, Any]] | None, name: str) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise TaskError(f"{name} must be a list of objects")
    return [dict(value) for value in values]
