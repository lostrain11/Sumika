"""Approval-aware task execution boundary.

The first runner executes only explicitly registered in-process handlers. It
does not spawn processes, touch workspaces, or perform remote actions. Those
behaviors belong to separate runner implementations with their own sandbox
and permission contracts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..events import EventBus
from ..protocol.models import EventEnvelope
from .manager import TaskError, TaskManager
from .models import TaskStatus


TaskHandler = Callable[[dict[str, Any]], dict[str, Any]]


class TaskRunner:
    """Run only handlers explicitly registered by the core application."""

    def __init__(self, tasks: TaskManager, events: EventBus) -> None:
        self.tasks = tasks
        self.events = events
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, handler_id: str, handler: TaskHandler) -> None:
        clean_id = str(handler_id).strip()
        if not clean_id:
            raise ValueError("handler_id must not be empty")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if clean_id in self._handlers:
            raise ValueError(f"Task handler already registered: {clean_id}")
        self._handlers[clean_id] = handler

    def list_handlers(self) -> list[dict[str, str]]:
        return [{"id": handler_id, "status": "available"} for handler_id in self._handlers]

    def run(
        self,
        task_id: str,
        *,
        handler_id: str = "core-health",
        approved: bool = False,
    ) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task["status"] in {status.value for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)}:
            raise TaskError(f"Task is terminal: {task_id}")
        try:
            handler = self._handlers[handler_id]
        except KeyError as exc:
            raise TaskError(f"Unknown task handler: {handler_id}") from exc
        if not isinstance(approved, bool):
            raise TaskError("approved must be a boolean")
        if not approved:
            if task["status"] == TaskStatus.PAUSED.value:
                return self.tasks.update(
                    task_id,
                    log={"message": "任务仍处于暂停状态；批准后可继续运行", "handler_id": handler_id},
                )
            if task["status"] != TaskStatus.WAITING_APPROVAL.value:
                task = self.tasks.update(
                    task_id,
                    status=TaskStatus.WAITING_APPROVAL,
                    log={"message": "等待用户批准后运行", "handler_id": handler_id},
                )
            return task

        if task["status"] != TaskStatus.RUNNING.value:
            task = self.tasks.update(
                task_id,
                status=TaskStatus.RUNNING,
                progress=0.0,
                log={"message": "已批准，开始运行", "handler_id": handler_id},
            )
        self.events.publish(EventEnvelope("task.started", {"task_id": task_id, "handler_id": handler_id}))
        try:
            result = handler(dict(task))
            if not isinstance(result, dict):
                raise TaskError("task handler must return an object")
        except Exception as exc:
            failed = self.tasks.update(
                task_id,
                status=TaskStatus.FAILED,
                result={"summary": "任务执行失败", "error": str(exc), "handler_id": handler_id},
                log={"message": f"执行失败：{exc}", "handler_id": handler_id},
            )
            self.events.publish(EventEnvelope("task.failed", {"task": failed, "handler_id": handler_id}))
            return failed

        completed = self.tasks.update(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=1.0,
            result={**result, "handler_id": handler_id},
            log={"message": "执行完成", "handler_id": handler_id},
        )
        self.events.publish(EventEnvelope("task.completed", {"task": completed, "handler_id": handler_id}))
        return completed


__all__ = ["TaskHandler", "TaskRunner"]
