"""Read-only projection of Agent Runtime sessions into task-center records."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import re
from typing import Any

from ..agent import AgentCapability, AgentRuntime
from ..storage import Storage
from ..workspace import WorkspaceRuntime


_MAX_SNAPSHOT_WORKERS = 6
_MAX_WORKSPACE_WORKERS = 4


class AgentTaskProjector:
    """Map runtime-owned state without creating a second durable task model."""

    def __init__(
        self,
        runtime: AgentRuntime,
        workspace: WorkspaceRuntime | None = None,
        *,
        storage: Storage | None = None,
        logger: Any = None,
    ) -> None:
        self.runtime = runtime
        self.workspace = workspace
        self.storage = storage
        self.logger = logger

    def project(self, *, limit: int = 24) -> dict[str, Any]:
        limit = max(1, min(int(limit), 64))
        try:
            status = self.runtime.status()
        except Exception as error:
            self._log_failure("status", error)
            return self._stale_result(
                reason="Agent Runtime 状态不可用",
                error=error,
                limit=limit,
            )
        if not status.get("ready"):
            return self._stale_result(
                reason=str(status.get("reason") or status.get("error") or "Agent Runtime 未连接"),
                limit=limit,
            )
        try:
            listing = self.runtime.list_sessions({})
        except Exception as error:
            self._log_failure("sessions", error)
            return self._stale_result(reason="Agent Session 列表不可用", error=error, limit=limit)
        sessions = listing.get("sessions") if isinstance(listing, dict) else []
        sessions = [item for item in sessions or [] if isinstance(item, dict) and item.get("id")][:limit]
        pending_by_session = self._pending_interactions()
        workspace_by_session = self._workspaces_by_session()
        workspace_cache = self._load_workspace_cache(workspace_by_session)
        cached_by_session = self._cached_by_session(limit=max(limit, 64))
        errors: list[dict[str, str]] = []
        tasks: list[dict[str, Any]] = []
        snapshots = self._load_snapshots(sessions)
        for session, (snapshot, snapshot_failed, snapshot_error) in zip(sessions, snapshots):
            session_id = str(session["id"])
            if snapshot_error is not None:
                self._log_failure("snapshot", snapshot_error, session_id=session_id)
                snapshot = {}
                errors.append(
                    {"scope": "snapshot", "session_id": session_id, "error_type": type(snapshot_error).__name__}
                )
            if snapshot_failed and session_id in cached_by_session:
                cached = dict(cached_by_session[session_id])
                cached["stale_reason"] = "当前 Session 摘要不可用"
                tasks.append(cached)
                continue
            workspace_value = workspace_by_session.get(session_id)
            workspace_evidence = self._workspace_evidence(workspace_value, workspace_cache)
            task = _project_task(
                runtime_id=self.runtime.runtime_id,
                session=session,
                snapshot=snapshot,
                pending=pending_by_session.get(session_id, []),
                workspace=workspace_evidence,
            )
            task["stale"] = snapshot_failed
            task["projection_state"] = "stale" if snapshot_failed else "live"
            task["last_synced_at"] = None
            if not snapshot_failed:
                self._persist(task, errors)
            tasks.append(task)
        return {
            "available": True,
            "runtime_id": self.runtime.runtime_id,
            "tasks": tasks,
            "errors": errors,
            "read_only": True,
            "projection_state": "live",
        }

    def _load_snapshots(
        self,
        sessions: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], bool, Exception | None]]:
        """Read session snapshots with bounded concurrency and stable ordering.

        DSH's session snapshot is an independent HTTP request.  The task page
        may request many sessions at once, so serial reads make an otherwise
        healthy Runtime look unavailable.  Keep the worker pool small and
        return results in the same order as ``sessions`` for deterministic UI
        and cache behavior.
        """

        def load(session: dict[str, Any]) -> tuple[dict[str, Any], bool, Exception | None]:
            try:
                value = self.runtime.snapshot(
                    {"sessionId": str(session["id"]), "maxMessages": 2, "include_history": True}
                )
                return (value if isinstance(value, dict) else {}), False, None
            except Exception as error:
                return {}, True, error

        if len(sessions) < 2:
            return [load(session) for session in sessions]
        results: list[tuple[dict[str, Any], bool, Exception | None] | None] = [None] * len(sessions)
        worker_count = min(_MAX_SNAPSHOT_WORKERS, len(sessions))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="sumika-agent-snapshot",
        ) as executor:
            futures = {
                executor.submit(load, session): index
                for index, session in enumerate(sessions)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as error:  # pragma: no cover - defensive future boundary
                    results[index] = ({}, True, error)
        return [
            item if item is not None else ({}, True, RuntimeError("snapshot worker returned no result"))
            for item in results
        ]

    def _load_workspace_cache(
        self,
        workspaces: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any] | None]:
        """Inspect distinct workspaces concurrently before rendering tasks."""

        if self.workspace is None:
            return {}
        paths = sorted(
            {
                str(value.get("path"))
                for value in workspaces.values()
                if isinstance(value, dict) and isinstance(value.get("path"), str) and value.get("path")
            }
        )

        def inspect(path: str) -> tuple[str, dict[str, Any] | None]:
            try:
                return path, self.workspace.inspect(path)
            except Exception as error:
                self._log_failure("workspace-inspect", error)
                return path, None

        if len(paths) < 2:
            return dict(inspect(path) for path in paths)
        results: dict[str, dict[str, Any] | None] = {}
        worker_count = min(_MAX_WORKSPACE_WORKERS, len(paths))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="sumika-agent-workspace",
        ) as executor:
            futures = [executor.submit(inspect, path) for path in paths]
            for future in futures:
                path, value = future.result()
                results[path] = value
        return results

    def _persist(self, task: dict[str, Any], errors: list[dict[str, str]]) -> None:
        if self.storage is None:
            return
        try:
            saved = self.storage.upsert_agent_task_projection(_redact_for_cache(task))
            task["last_synced_at"] = saved.get("observed_at")
        except Exception as error:
            self._log_failure("persist", error, session_id=str(task.get("session_id") or ""))
            errors.append({"scope": "persist", "session_id": str(task.get("session_id") or ""), "error_type": type(error).__name__})

    def _cached_by_session(self, *, limit: int) -> dict[str, dict[str, Any]]:
        if self.storage is None:
            return {}
        try:
            rows = self.storage.list_agent_task_projections(
                self.runtime.runtime_id,
                limit=limit,
                stale=True,
            )
        except Exception as error:
            self._log_failure("cache", error)
            return {}
        return {
            str(row.get("session_id")): row
            for row in rows
            if isinstance(row, dict) and row.get("session_id")
        }

    def _stale_result(
        self,
        *,
        reason: str,
        error: Exception | None = None,
        limit: int = 24,
    ) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        if self.storage is not None:
            try:
                tasks = self.storage.list_agent_task_projections(
                    self.runtime.runtime_id,
                    limit=limit,
                    stale=True,
                )
            except Exception as cache_error:
                self._log_failure("cache", cache_error)
        last_synced_at = max(
            (str(item.get("observed_at") or "") for item in tasks if item.get("observed_at")),
            default=None,
        )
        for task in tasks:
            task["stale_reason"] = reason
            task["last_synced_at"] = task.get("observed_at")
            task["projection_state"] = "stale"
        result: dict[str, Any] = {
            "available": False,
            "runtime_id": self.runtime.runtime_id,
            "tasks": tasks,
            "errors": [],
            "reason": reason,
            "read_only": True,
            "projection_state": "stale" if tasks else "unavailable",
            "last_synced_at": last_synced_at,
        }
        if error is not None:
            result["errors"] = [{"scope": "sessions", "error_type": type(error).__name__}]
        return result

    def _pending_interactions(self) -> dict[str, list[dict[str, Any]]]:
        if not self.runtime.supports(AgentCapability.INTERACTIONS):
            return {}
        try:
            value = self.runtime.interactions({})
        except Exception as error:
            self._log_failure("interactions", error)
            return {}
        result: dict[str, list[dict[str, Any]]] = {}
        for item in value.get("interactions", []) if isinstance(value, dict) else []:
            if not isinstance(item, dict) or not item.get("session_id"):
                continue
            result.setdefault(str(item["session_id"]), []).append(item)
        return result

    def _workspaces_by_session(self) -> dict[str, dict[str, Any]]:
        if not self.runtime.supports(AgentCapability.WORKSPACES):
            return {}
        try:
            value = self.runtime.list_workspaces({})
        except Exception as error:
            self._log_failure("workspaces", error)
            return {}
        result: dict[str, dict[str, Any]] = {}
        for workspace in value.get("workspaces", []) if isinstance(value, dict) else []:
            if not isinstance(workspace, dict):
                continue
            for session_id in workspace.get("session_ids", []):
                if isinstance(session_id, str) and session_id:
                    result[session_id] = workspace
        return result

    def _workspace_evidence(
        self,
        value: dict[str, Any] | None,
        cache: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        evidence: dict[str, Any] = {
            "id": str(value.get("id") or ""),
            "title": str(value.get("title") or "Workspace"),
        }
        path = value.get("path")
        if self.workspace is None or not isinstance(path, str) or not path:
            return evidence
        inspected = cache[path]
        workspace = inspected.get("workspace") if isinstance(inspected, dict) else None
        if isinstance(workspace, dict):
            evidence.update(
                {
                    "branch": workspace.get("branch"),
                    "head": workspace.get("head"),
                    "dirty": bool(workspace.get("dirty")),
                    "file_count": int(workspace.get("file_count") or 0),
                    "checkpoint_count": int(inspected.get("checkpoint_count") or 0),
                }
            )
        return evidence

    def _log_failure(self, scope: str, error: Exception, *, session_id: str | None = None) -> None:
        if self.logger:
            self.logger.info(
                "agent task projection failed scope=%s session_id=%s error_type=%s",
                scope,
                session_id or "-",
                type(error).__name__,
            )


def _project_task(
    *,
    runtime_id: str,
    session: dict[str, Any],
    snapshot: dict[str, Any],
    pending: list[dict[str, Any]],
    workspace: dict[str, Any] | None,
) -> dict[str, Any]:
    session_id = str(session.get("id") or "")
    state = str(snapshot.get("state") or session.get("state") or "unknown").lower()
    blank = bool(session.get("blank"))
    task_status = _task_status(state, blank=blank, waiting=bool(pending))
    plan = snapshot.get("plan") if isinstance(snapshot.get("plan"), dict) else {}
    stats = _compact_metric_map(
        snapshot.get("stats") if isinstance(snapshot.get("stats"), dict) else session.get("stats")
    )
    token_usage = _compact_metric_map(
        snapshot.get("token_usage")
        if isinstance(snapshot.get("token_usage"), dict)
        else session.get("token_usage")
    )
    context = _compact_metric_map(snapshot.get("context"))
    context_breakdown = _compact_metric_map(snapshot.get("context_breakdown"))
    budget = _project_budget(snapshot.get("budget"), session.get("budget"))
    turns = _compact_turn_ledger(snapshot.get("turns"))
    artifacts = [dict(item) for item in snapshot.get("artifacts", []) if isinstance(item, dict)][:16]
    timeline = [item for item in snapshot.get("timeline", []) if isinstance(item, dict)][-4:]
    permissions = [
        str(item.get("action") or item.get("kind") or "需要用户确认")
        for item in pending[:8]
    ]
    return {
        "id": f"agent:{runtime_id}:{session_id}",
        "title": str(snapshot.get("title") or session.get("title") or "未命名 Agent 会话"),
        "status": task_status,
        "autonomy_level": "L2",
        "budget": budget,
        "character_id": None,
        "progress": _task_progress(task_status, plan),
        "result": {
            "summary": _result_summary(task_status, state, blank),
            "plan": plan,
            "turns": turns,
        },
        "permissions": permissions,
        "logs": [
            {"message": str(item.get("type") or "runtime event"), "sequence": item.get("seq")}
            for item in timeline
        ],
        "artifacts": artifacts,
        "source": "agent-runtime",
        "read_only": True,
        "runtime_id": runtime_id,
        "session_id": session_id,
        "turns": turns,
        "updated_at": session.get("updated_at"),
        "metrics": {
            "stats": dict(stats),
            "token_usage": dict(token_usage),
            "context": dict(context),
            "context_breakdown": dict(context_breakdown),
        },
        "workspace": workspace,
    }


def _redact_for_cache(task: dict[str, Any]) -> dict[str, Any]:
    """Remove conversation-bearing fields before a projection reaches SQLite."""

    # Cache rows are deliberately more restrictive than the live projection.
    # Session titles, plan step labels, permission reasons and workspace names
    # may all be user-controlled text even when they do not look like chat
    # messages.  Keep only stable machine-readable categories and counts.
    safe_event_types = {
        "turn/start",
        "turn/end",
        "step/start",
        "step/end",
        "tool/call",
        "tool/result",
        "approval/requested",
        "approval/resolved",
        "question/requested",
        "question/resolved",
        "session/title",
    }
    safe_statuses = {
        "pending",
        "queued",
        "running",
        "steering",
        "completed",
        "complete",
        "success",
        "succeeded",
        "failed",
        "error",
        "cancelled",
        "canceled",
        "aborted",
        "waiting_approval",
        "paused",
    }
    safe_actions = {
        "read",
        "search",
        "edit",
        "write",
        "delete",
        "move",
        "shell",
        "pwsh",
        "bash",
        "python",
        "network",
        "upload",
        "download",
        "login",
        "publish",
        "tool",
        "user-confirmation",
    }

    def safe_status(value: Any) -> str:
        candidate = str(value or "").strip().lower()
        return candidate[:32] if candidate in safe_statuses else "unknown"

    def safe_event(value: Any) -> str:
        candidate = str(value or "").strip().lower()
        return candidate if candidate in safe_event_types else "runtime-event"

    def safe_action(value: Any) -> str:
        candidate = str(value or "").strip().lower()
        if candidate in safe_actions:
            return candidate
        # Do not persist arbitrary action text.  It can contain a prompt,
        # command line or a credential-bearing reason.
        return "user-confirmation"

    def safe_integer(value: Any, *, maximum: int = 1_000_000) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0 or value > maximum:
            return None
        return int(value)

    def safe_records(value: Any, limit: int = 16) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            clean: dict[str, Any] = {}
            if item.get("type") is not None:
                clean["type"] = safe_event(item.get("type"))
            status = item.get("status")
            if status is not None:
                clean["status"] = safe_status(status)
            sequence = safe_integer(item.get("sequence", item.get("seq")))
            if sequence is not None:
                clean["sequence"] = sequence
            file_count = safe_integer(item.get("file_count"))
            if file_count is not None:
                clean["file_count"] = file_count
            if item.get("id") is not None:
                # IDs are only useful for correlating a bounded card; reject
                # free-form text and keep a short opaque token.
                identifier = str(item.get("id") or "").strip()
                if re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", identifier):
                    clean["id"] = identifier
            if clean:
                result.append(clean)
        return result

    result = dict(task)
    result["title"] = "Agent 会话（最后已知）"
    result["status"] = safe_status(task.get("status"))
    raw_result = task.get("result") if isinstance(task.get("result"), dict) else {}
    raw_plan = raw_result.get("plan") if isinstance(raw_result.get("plan"), dict) else {}
    result["result"] = {
        # Summary text is reconstructed from status at render time.  Never
        # persist a Runtime-provided sentence that could contain user input.
        "summary": "",
        "plan": {
            "active": bool(raw_plan.get("active")),
            "pending": bool(raw_plan.get("pending")),
            "step_count": min(64, len([
                item for item in (raw_plan.get("steps") or [])
                if isinstance(item, dict)
            ])),
            "completed_steps": min(64, sum(
                1
                for item in (raw_plan.get("steps") or [])
                if isinstance(item, dict)
                and str(item.get("status") or "").strip().lower() in {"completed", "complete", "done", "skipped"}
            )),
        },
        "turns": _compact_turn_ledger(task.get("turns") or raw_result.get("turns")),
    }
    result["logs"] = safe_records(task.get("logs"))
    result["artifacts"] = safe_records(task.get("artifacts"))
    result["permissions"] = [safe_action(item) for item in (task.get("permissions") or [])[:16]]
    metrics = task.get("metrics") if isinstance(task.get("metrics"), dict) else {}
    result["metrics"] = {
        key: _compact_metric_map(value)
        for key, value in metrics.items()
        if key in {"stats", "token_usage", "context", "context_breakdown"}
        and isinstance(value, dict)
    }
    workspace = task.get("workspace") if isinstance(task.get("workspace"), dict) else None
    if workspace is not None:
        result["workspace"] = {
            "id": str(workspace.get("id") or "")[:120],
            "dirty": bool(workspace.get("dirty")),
            "file_count": safe_integer(workspace.get("file_count")) or 0,
            "checkpoint_count": safe_integer(workspace.get("checkpoint_count")) or 0,
        }
    else:
        result["workspace"] = None
    return result


_TURN_LEDGER_STATUSES = {
    "running",
    "completed",
    "cancelled",
    "aborted",
    "failed",
    "error",
    "interrupted",
    "stopped",
}
_TURN_LEDGER_MODES = {"plan", "execute", "readonly"}


def _compact_turn_ledger(value: Any) -> list[dict[str, Any]]:
    """Keep a bounded, content-free summary of recent Agent turns."""

    if not isinstance(value, list):
        return []

    def count(candidate: Any) -> int:
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            return 0
        if not math.isfinite(candidate):
            return 0
        return max(0, min(10_000, int(candidate)))

    records: list[dict[str, Any]] = []
    for item in value[-16:]:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or "").strip()
        if not identifier or len(identifier) > 96 or not re.fullmatch(r"[A-Za-z0-9._:-]+", identifier):
            continue
        status = str(item.get("status") or "running").strip().lower()
        if status not in _TURN_LEDGER_STATUSES:
            status = "running"
        record: dict[str, Any] = {
            "id": identifier,
            "status": status,
            "steps": count(item.get("steps")),
            "tools": count(item.get("tools")),
            "approvals": count(item.get("approvals")),
            "artifacts": count(item.get("artifacts")),
        }
        turn = item.get("turn")
        if isinstance(turn, int) and not isinstance(turn, bool) and turn >= 0:
            record["turn"] = turn
        elif isinstance(turn, str) and turn.strip() and len(turn.strip()) <= 80 and not any(ord(char) < 32 or ord(char) == 127 for char in turn):
            record["turn"] = turn.strip()
        mode = str(item.get("mode") or "").strip().lower()
        if mode in _TURN_LEDGER_MODES:
            record["mode"] = mode
        for key in ("start_seq", "end_seq"):
            sequence = item.get(key)
            if isinstance(sequence, int) and not isinstance(sequence, bool) and 0 <= sequence <= 10_000_000_000:
                record[key] = sequence
        records.append(record)
    return records


_METRIC_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("turns", ("turns",)),
    ("steps", ("steps",)),
    ("llmMs", ("llmMs", "llm_ms")),
    ("toolMs", ("toolMs", "tool_ms")),
    ("ttftMs", ("ttftMs", "ttft_ms")),
    ("ttftSteps", ("ttftSteps", "ttft_steps")),
    ("decodeMs", ("decodeMs", "decode_ms")),
    ("decodeTokens", ("decodeTokens", "decode_tokens")),
    ("uncachedInputTokens", ("uncachedInputTokens", "uncached_input_tokens", "inputTokens", "input_tokens")),
    ("outputTokens", ("outputTokens", "output_tokens")),
    ("cacheReadTokens", ("cacheReadTokens", "cache_read_tokens", "cachedInputTokens", "cached_input_tokens")),
    ("cacheWriteTokens", ("cacheWriteTokens", "cache_write_tokens")),
    ("projectedTokens", ("projectedTokens", "projected_tokens", "usedTokens", "used_tokens")),
    ("pressureTokens", ("pressureTokens", "pressure_tokens")),
    ("contextWindow", ("contextWindow", "context_window", "maxContextTokens", "max_context_tokens")),
    ("systemTokens", ("systemTokens", "system_tokens")),
    ("toolsTokens", ("toolsTokens", "tools_tokens")),
    ("messageTokens", ("messageTokens", "message_tokens")),
)


def _finite_non_negative(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value) if isinstance(value, int) or value.is_integer() else float(value)


def _compact_metric_map(value: Any) -> dict[str, int | float]:
    """Keep a small, non-sensitive set of runtime metric fields."""

    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for output_key, aliases in _METRIC_FIELDS:
        for alias in aliases:
            number = _finite_non_negative(value.get(alias))
            if number is not None:
                result[output_key] = number
                break
    return result


_BUDGET_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("token_limit", ("token_limit", "tokenLimit")),
    ("cost_limit", ("cost_limit", "costLimit")),
    ("time_limit_seconds", ("time_limit_seconds", "timeLimitSeconds", "timeLimit")),
    ("disk_limit_bytes", ("disk_limit_bytes", "diskLimitBytes", "diskLimit")),
)


def _project_budget(*candidates: Any) -> dict[str, Any]:
    """Expose configured limits only when the runtime explicitly supplies them."""

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        limits: dict[str, int | float] = {}
        for output_key, aliases in _BUDGET_FIELDS:
            for alias in aliases:
                number = _finite_non_negative(candidate.get(alias))
                if number is not None:
                    limits[output_key] = number
                    break
        if limits:
            return {"available": True, "source": "agent-runtime", **limits}
    return {
        "available": False,
        "source": "agent-runtime",
        "reason": "Runtime 未提供任务预算上限",
    }


def _task_status(state: str, *, blank: bool, waiting: bool) -> str:
    if waiting:
        return "waiting_approval"
    if state in {"running", "queued", "steering"}:
        return "running"
    if state in {"completed", "complete", "success", "succeeded", "stop"}:
        return "completed"
    if state in {"failed", "error"}:
        return "failed"
    if state in {"cancelled", "canceled", "aborted"}:
        return "cancelled"
    return "pending" if blank else "paused"


def _task_progress(status: str, plan: dict[str, Any]) -> float:
    if status == "completed":
        return 1.0
    steps = [item for item in plan.get("steps", []) if isinstance(item, dict)]
    if steps:
        completed = sum(
            1
            for item in steps
            if str(item.get("status") or "").lower() in {"completed", "complete", "done", "skipped"}
        )
        return min(0.95, completed / len(steps))
    if status in {"running", "waiting_approval", "paused"}:
        return 0.5
    return 0.0


def _result_summary(status: str, state: str, blank: bool) -> str:
    if blank:
        return "尚未开始 Agent 回合"
    return {
        "running": "Agent 回合正在运行",
        "waiting_approval": "Agent 正在等待用户确认",
        "completed": "最近 Agent 回合已完成",
        "failed": "最近 Agent 回合失败",
        "cancelled": "最近 Agent 回合已取消",
        "paused": "Agent 会话当前空闲",
    }.get(status, f"Agent 状态：{state or 'unknown'}")


__all__ = ["AgentTaskProjector"]
