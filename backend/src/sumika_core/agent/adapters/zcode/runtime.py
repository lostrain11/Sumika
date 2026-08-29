"""ZCode ``app-server --stdio`` Agent runtime adapter.

Only the public line-delimited JSON-RPC boundary is used here.  The adapter
does not inspect ZCode's settings, credential, cookie, or browser storage;
authentication remains owned by the ZCode process itself.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ....protocol.models import utc_now
from ...contracts import AgentCapability, AgentRuntime, AgentRuntimeError
from ...models import AgentEvent
from .config import ZCodeRuntimeConfig, config_from_env


_MAX_LINE_BYTES = 4 * 1024 * 1024
_MAX_TEXT = 12_000
_MAX_RESPONSE_ITEMS = 256


class ZCodeProtocolError(AgentRuntimeError):
    """A JSON-RPC error returned by the ZCode app-server."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class _TransportFailure(RuntimeError):
    pass


class _JsonRpcProcess:
    """One owned child process with correlated requests and notifications."""

    def __init__(
        self,
        config: ZCodeRuntimeConfig,
        *,
        logger: Any = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.on_message = on_message
        self.process: subprocess.Popen[str] | None = None
        self._pending: dict[str, queue.Queue[Any]] = {}
        self._write_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._closed = False
        self._last_error: str | None = None

    @property
    def alive(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    def start(self) -> None:
        with self._state_lock:
            if self.alive:
                return
            if self._closed:
                raise AgentRuntimeError("ZCode runtime has been closed", transport=True)
            executable = (self.config.executable or "").strip()
            if not self.config.enabled:
                raise AgentRuntimeError("ZCode runtime is disabled")
            if not executable:
                raise AgentRuntimeError("ZCode executable is not configured")
            command = [executable, *self.config.arguments]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=self.config.working_directory or None,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    shell=False,
                    creationflags=creationflags,
                )
            except (OSError, ValueError) as exc:
                self.process = None
                raise AgentRuntimeError(
                    "ZCode app-server could not be started",
                    transport=True,
                ) from exc
            self._last_error = None
            self._reader_thread = threading.Thread(
                target=self._read_stdout,
                name="sumika-zcode-jsonrpc",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                name="sumika-zcode-stderr",
                daemon=True,
            )
            self._reader_thread.start()
            self._stderr_thread.start()
            if self.logger:
                self.logger.info(
                    "zcode app-server started executable_name=%s argument_count=%d",
                    Path(executable).name,
                    len(self.config.arguments),
                )

    def request(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        self.start()
        process = self.process
        if process is None or process.stdin is None:
            raise AgentRuntimeError("ZCode app-server stdin is unavailable", transport=True)
        request_id = f"sumika-{uuid4().hex}"
        response_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
        with self._state_lock:
            self._pending[request_id] = response_queue
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise AgentRuntimeError("ZCode app-server request could not be written", transport=True) from exc

        wait_seconds = timeout if timeout is not None else self.config.request_timeout
        try:
            value = response_queue.get(timeout=wait_seconds)
        except queue.Empty as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise AgentRuntimeError(
                f"ZCode app-server timed out while calling {method}",
                transport=True,
            ) from exc
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)
        if isinstance(value, _TransportFailure):
            raise AgentRuntimeError("ZCode app-server connection closed", transport=True) from value
        if not isinstance(value, dict):
            raise ZCodeProtocolError("ZCode returned an invalid JSON-RPC response")
        if value.get("error"):
            error = value.get("error")
            if isinstance(error, dict):
                code = error.get("code") if isinstance(error.get("code"), int) else None
                message = _safe_text(error.get("message"), 600) or "ZCode request failed"
                raise ZCodeProtocolError(message, code=code)
            raise ZCodeProtocolError("ZCode request failed")
        return value.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.start()
        process = self.process
        if process is None or process.stdin is None:
            raise AgentRuntimeError("ZCode app-server stdin is unavailable", transport=True)
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AgentRuntimeError("ZCode app-server notification could not be written", transport=True) from exc

    def respond(self, request_id: str, *, result: Any = None, error: dict[str, Any] | None = None) -> None:
        self.start()
        process = self.process
        if process is None or process.stdin is None:
            raise AgentRuntimeError("ZCode app-server stdin is unavailable", transport=True)
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        body["error" if error is not None else "result"] = error if error is not None else (result if result is not None else {})
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AgentRuntimeError("ZCode app-server response could not be written", transport=True) from exc

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            process = self.process
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            try:
                response_queue.put_nowait(_TransportFailure("closed"))
            except queue.Full:
                pass
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        for thread in (self._reader_thread, self._stderr_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self.process = None
        if self.logger:
            self.logger.info("zcode app-server stopped")

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if len(line.encode("utf-8", errors="replace")) > _MAX_LINE_BYTES:
                    self._fail_pending("response line too large")
                    continue
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    if self.logger:
                        self.logger.info("zcode app-server emitted malformed json line")
                    continue
                if not isinstance(value, dict):
                    continue
                is_response = "method" not in value and ("result" in value or "error" in value)
                if is_response and value.get("id") is not None:
                    request_id = str(value.get("id"))
                    with self._state_lock:
                        response_queue = self._pending.get(request_id)
                    if response_queue is not None:
                        try:
                            response_queue.put_nowait(value)
                        except queue.Full:
                            pass
                        continue
                callback = self.on_message
                if callback is not None:
                    try:
                        callback(value)
                    except Exception as exc:
                        if self.logger:
                            self.logger.info(
                                "zcode event callback failed error_type=%s",
                                type(exc).__name__,
                            )
        finally:
            self._fail_pending("stdout closed")

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            if self.logger:
                # Never copy stderr into application logs: ZCode may include
                # account or prompt data in diagnostics.  Keep only a bound.
                self.logger.info("zcode app-server stderr line_length=%d", len(line))

    def _fail_pending(self, detail: str) -> None:
        with self._state_lock:
            self._last_error = detail
            pending = list(self._pending.values())
        for response_queue in pending:
            try:
                response_queue.put_nowait(_TransportFailure(detail))
            except queue.Full:
                pass


class ZCodeAgentRuntime(AgentRuntime):
    """Harness-neutral facade over a user-configured ZCode app-server."""

    runtime_id = "zcode"
    capability_ids = frozenset(
        {
            AgentCapability.DIAGNOSTICS,
            AgentCapability.SESSION_SEARCH,
            AgentCapability.SESSION_RENAME,
            AgentCapability.MODELS,
            AgentCapability.SESSION_FORK,
            AgentCapability.HISTORY,
            AgentCapability.ATTACHMENTS,
            AgentCapability.QUEUE,
            AgentCapability.SUBAGENTS,
            AgentCapability.PLAN,
            AgentCapability.READONLY,
            AgentCapability.INTERACTIONS,
            AgentCapability.EVENT_INGEST,
        }
    )

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        logger: Any = None,
        config: ZCodeRuntimeConfig | None = None,
    ) -> None:
        self.config = config or config_from_env(data_dir, env)
        self.logger = logger
        self._last_health: dict[str, Any] | None = None
        self._last_health_at = 0.0
        self._initialized = False
        self._event_sink: Any = None
        self._event_lock = threading.RLock()
        self._pending_server_requests: set[str] = set()
        self._advertised_capabilities: set[AgentCapability] | None = None
        self._transport = _JsonRpcProcess(self.config, logger=logger, on_message=self._on_message)

    def status(self) -> dict[str, Any]:
        if not self.config.enabled:
            state = "disabled"
        elif self._last_health and self._last_health.get("ok"):
            state = "ready"
        else:
            state = "unavailable"
        return {
            "runtime_id": self.runtime_id,
            "version": self.config.version,
            "state": state,
            "ready": state == "ready",
            "enabled": self.config.enabled,
            "configured": bool(self.config.executable),
            "managed": self.config.managed,
            "transport": "stdio-jsonrpc",
            "process_alive": self._transport.alive,
            "profile_configured": bool(self.config.profile_dir),
            "runtime_capabilities": self.runtime_capabilities(),
        }

    def health(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "state": "disabled", "error": "ZCode runtime is disabled"}
        try:
            self._initialize()
            try:
                value = self._call_variants(("health", "status", "host/describe"), {})
            except ZCodeProtocolError as error:
                if error.code not in {-32600, -32601}:
                    raise
                value = {"protocol": "initialized"}
            self._last_health = {
                "ok": True,
                "state": "ready",
                "runtime": _compact_public(value),
            }
        except AgentRuntimeError as error:
            self._last_health = {
                "ok": False,
                "state": "unavailable",
                "error": str(error),
            }
        self._last_health_at = time.monotonic()
        return dict(self._last_health)

    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        health = self.health()
        return {
            "checked_at": utc_now(),
            "runtime": {
                "runtime_id": self.runtime_id,
                "state": health.get("state"),
                "ready": bool(health.get("ok")),
                "transport": "stdio-jsonrpc",
                "configured": bool(self.config.executable),
                "profile_configured": bool(self.config.profile_dir),
            },
            "capabilities": [
                {"id": value, "available": True, "status": "declared"}
                for value in self.runtime_capabilities()
            ],
            "summary": {"available": len(self.runtime_capabilities())} if health.get("ok") else {"unavailable": 1},
        }

    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = _session_payload(params)
        value = self._call_variants(("session/create", "thread/start", "session.create"), payload)
        session_id = _extract_id(value, ("sessionId", "session_id", "threadId", "thread_id", "id"))
        if not session_id:
            raise AgentRuntimeError("ZCode did not return a session id")
        return {
            "sessionId": session_id,
            "session_id": session_id,
            "title": _safe_text(_first(value, "title", "name"), 240),
            "state": _safe_text(_first(value, "state", "status"), 80) or "idle",
        }

    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        value = self._call_variants(("session/list", "thread/list", "session.list"), {})
        raw = _first_list(value, ("sessions", "threads", "items", "data"))
        sessions: list[dict[str, Any]] = []
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            session_id = _extract_id(item, ("sessionId", "session_id", "threadId", "thread_id", "id"))
            if not session_id:
                continue
            sessions.append(
                {
                    "id": session_id,
                    "title": _safe_text(_first(item, "title", "name") or "未命名 Agent 会话", 240),
                    "state": _safe_text(_first(item, "state", "status"), 80) or "idle",
                    "updated_at": _safe_scalar(_first(item, "updatedAt", "updated_at", "createdAt")),
                    "model": _safe_text(_first(item, "model", "modelId"), 160) or None,
                }
            )
        return {"sessions": sessions}

    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        value = self._call_variants(
            ("session/snapshot", "thread/read", "session/read", "session.snapshot"),
            {"sessionId": session_id},
        )
        result = _compact_public(value)
        if isinstance(result, dict):
            result.setdefault("session_id", session_id)
            return result
        return {"session_id": session_id, "value": result}

    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        content = _prompt_content(params)
        mode = _safe_text(params.get("mode") or "execute", 40).lower()
        if mode not in {"plan", "execute", "readonly"}:
            mode = "execute"
        payload: dict[str, Any] = {"sessionId": session_id, "content": content, "mode": mode}
        model = params.get("model") or params.get("modelId")
        if model is not None:
            payload["model"] = _safe_text(model, 240)
        value = self._call_variants(("turn/start", "session/prompt", "turn/create", "session.prompt"), payload)
        receipt = _compact_public(value)
        if not isinstance(receipt, dict):
            receipt = {"value": receipt}
        receipt["session_id"] = session_id
        receipt["accepted"] = bool(receipt.get("accepted", True))
        return receipt

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        value = self._call_variants(
            ("turn/interrupt", "session/cancel", "turn/cancel", "session.cancel"),
            {"sessionId": session_id},
        )
        result = _compact_public(value)
        if not isinstance(result, dict):
            result = {"value": result}
        result.update({"session_id": session_id, "accepted": bool(result.get("accepted", True))})
        return result

    def search_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        query = _safe_text(params.get("query") or "", 500)
        if not query:
            raise AgentRuntimeError("session search query is required")
        value = self._call_variants(("session/search", "thread/search", "session.search"), {"query": query})
        return _compact_public(value) if isinstance(_compact_public(value), dict) else {"items": []}

    def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        title = _safe_text(params.get("title"), 240)
        if not title:
            raise AgentRuntimeError("session title is required")
        value = self._call_variants(("session/rename", "thread/rename", "session.rename"), {"sessionId": session_id, "title": title})
        return {"session_id": session_id, "title": _safe_text(_first(value, "title") or title, 240)}

    def session_models(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        value = self._call_variants(
            ("model/list", "session/models", "session.models"),
            {"sessionId": session_id},
        )
        return _normalize_models(value)

    def select_model(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        model = _safe_text(params.get("model") or params.get("modelId"), 240)
        if not model:
            raise AgentRuntimeError("model is required")
        value = self._call_variants(
            ("session/model", "model/select", "session.selectModel"),
            {"sessionId": session_id, "model": model},
        )
        return {"session_id": session_id, "selected": _compact_public(value), "model": model}

    def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        value = self._call_variants(("session/fork", "thread/fork", "session.fork"), {"sessionId": session_id})
        child = _extract_id(value, ("sessionId", "threadId", "id"))
        if not child:
            raise AgentRuntimeError("ZCode did not return a forked session id")
        return {"sessionId": child, "parent_session_id": session_id}

    def history(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        value = self._call_variants(("session/history", "thread/read", "session.history"), {"sessionId": session_id})
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"session_id": session_id, "items": []}

    def attachment(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        attachment_id = _safe_text(params.get("attachmentId") or params.get("attachment_id"), 240)
        if not attachment_id:
            raise AgentRuntimeError("attachment id is required")
        value = self._call_variants(
            ("session/attachment", "attachment/get", "session.attachment"),
            {"sessionId": session_id, "attachmentId": attachment_id},
        )
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"session_id": session_id, "attachment_id": attachment_id}

    def queue(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        value = self._call_variants(("session/queue", "turn/queue", "session.queue"), {"sessionId": session_id})
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"session_id": session_id, "items": []}

    def update_queue(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        action = _safe_text(params.get("action") or params.get("kind"), 40).lower()
        if action not in {"edit", "remove", "steer"}:
            raise AgentRuntimeError("queue action must be edit, remove, or steer")
        item_id = _safe_text(params.get("itemId") or params.get("item_id"), 240)
        if not item_id:
            raise AgentRuntimeError("queue item id is required")
        payload = {"sessionId": session_id, "itemId": item_id, "action": action}
        if action == "edit":
            payload["text"] = _safe_text(params.get("text"), _MAX_TEXT)
            if not payload["text"]:
                raise AgentRuntimeError("queue edit text is required")
        value = self._call_variants(("session/queue/update", "session/updateQueue", "session.updateQueue"), payload)
        return {"session_id": session_id, "item_id": item_id, "action": action, "accepted": True, "result": _compact_public(value)}

    def list_subagents(self, params: dict[str, Any]) -> dict[str, Any]:
        parent = _session_id(params, names=("parentSessionId", "parent_session_id", "sessionId", "session_id"))
        value = self._call_variants(("subagent/list", "session/subagents", "subagent.list"), {"parentSessionId": parent})
        raw = _first_list(value, ("subagents", "items", "sessions", "data"))
        result = []
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            child = _extract_id(item, ("sessionId", "childSessionId", "id"))
            if child:
                result.append({"id": child, "state": _safe_text(_first(item, "state", "status"), 80) or "unknown", "title": _safe_text(_first(item, "title", "name"), 200)})
        return {"parent_session_id": parent, "subagents": result}

    def subagent_history(self, params: dict[str, Any]) -> dict[str, Any]:
        parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
        child = _session_id(params, names=("childSessionId", "child_session_id"))
        value = self._call_variants(("subagent/history", "session/history", "subagent.history"), {"parentSessionId": parent, "childSessionId": child})
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"parent_session_id": parent, "child_session_id": child, "items": []}

    def prompt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
        child = _session_id(params, names=("childSessionId", "child_session_id"))
        text = _safe_text(params.get("text"), _MAX_TEXT)
        if not text:
            raise AgentRuntimeError("subagent prompt text is required")
        self._call_variants(("subagent/prompt", "session/prompt", "subagent.prompt"), {"parentSessionId": parent, "childSessionId": child, "content": [{"type": "text", "text": text}]})
        return {"accepted": True, "parent_session_id": parent, "child_session_id": child}

    def interrupt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
        child = _session_id(params, names=("childSessionId", "child_session_id"))
        self._call_variants(("subagent/interrupt", "turn/interrupt", "subagent.interrupt"), {"parentSessionId": parent, "childSessionId": child})
        return {"accepted": True, "parent_session_id": parent, "child_session_id": child}

    def list_capabilities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        try:
            value = self._call_variants(("capabilities", "capabilities/list", "host/capabilities"), {})
        except AgentRuntimeError as error:
            return {"available": False, "status": "unavailable", "error": str(error)}
        return {"available": True, "status": "observed", "entries": _compact_public(value)}

    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        try:
            value = self._call_variants(("mcp/list", "mcp/listServers", "mcp.list"), {})
        except ZCodeProtocolError as error:
            return {"available": False, "status": "not-exposed" if error.code == -32601 else "rejected", "entries": [], "server_count": 0, "tool_count": 0}
        except AgentRuntimeError as error:
            return {"available": False, "status": "unavailable", "entries": [], "server_count": 0, "tool_count": 0, "reason": str(error)}
        raw = _first_list(value, ("servers", "entries", "items", "data"))
        entries: list[dict[str, Any]] = []
        tool_count = 0
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            name = _safe_text(_first(item, "name", "id"), 160)
            if not name:
                continue
            tools = _first_list(item, ("tools",))
            compact_tools = [{"name": _safe_text(_first(tool, "name", "id"), 160)} for tool in tools[:128] if isinstance(tool, dict) and _safe_text(_first(tool, "name", "id"), 160)]
            tool_count += len(compact_tools)
            entries.append({"name": name, "status": _safe_text(_first(item, "status", "state"), 80) or "unknown", "tools": compact_tools})
        return {"available": True, "status": "observed", "entries": entries, "server_count": len(entries), "tool_count": tool_count}

    def respond(self, params: dict[str, Any]) -> dict[str, Any]:
        request_id = _safe_text(params.get("rpcId") or params.get("rpc_id") or params.get("requestId"), 240)
        if not request_id:
            raise AgentRuntimeError("ZCode interaction id is required")
        with self._event_lock:
            if request_id not in self._pending_server_requests:
                raise AgentRuntimeError("ZCode interaction is no longer pending")
            self._pending_server_requests.remove(request_id)
        approved = params.get("approved") is True
        self._transport.respond(request_id, result={"approved": approved})
        return {"rpc_id": request_id, "accepted": True, "approved": approved}

    def interactions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        with self._event_lock:
            return {"available": True, "interactions": [{"rpc_id": value, "status": "pending"} for value in sorted(self._pending_server_requests)]}

    def normalize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AgentRuntimeError("ZCode event must be an object")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else payload
        method = _safe_text(payload.get("method") or params.get("type") or params.get("event") or "event", 160)
        event_type = _event_type(method)
        session_id = _extract_id(params, ("sessionId", "session_id", "threadId", "thread_id"))
        turn_id = _extract_id(params, ("turnId", "turn_id"))
        item_id = _extract_id(params, ("itemId", "item_id", "messageId", "message_id"))
        status = _safe_text(params.get("status") or params.get("state") or method, 100) or "unknown"
        text = params.get("text") or params.get("content")
        content = _safe_text(text, 1200) if isinstance(text, str) else None
        extensions: dict[str, Any] = {"source": "zcode", "method": method}
        for key in ("tool", "approval", "plan", "metrics"):
            if isinstance(params.get(key), dict):
                extensions[key] = _compact_public(params[key], depth=2)
        if payload.get("id") is not None and payload.get("method"):
            extensions["rpc_id"] = _safe_text(payload.get("id"), 240)
        return AgentEvent(
            event_type=event_type,
            session_id=session_id,
            turn_id=turn_id,
            item_id=item_id,
            status=status,
            content=content,
            extensions=extensions,
            timestamp=_safe_text(params.get("timestamp"), 80) or utc_now(),
        ).to_dict()

    def set_event_sink(self, sink: Any) -> None:
        self._event_sink = sink

    def bind_credential_store(self, credential_store: Any) -> None:
        # ZCode owns its login state.  Deliberately do not retain or inspect
        # Sumika's credential store here.
        del credential_store

    def close(self) -> None:
        self._transport.close()
        self._initialized = False
        self._last_health = None
        with self._event_lock:
            self._pending_server_requests.clear()

    def _initialize(self) -> None:
        if self._initialized and self._transport.alive:
            return
        value = self._transport.request(
            "initialize",
            {
                "protocolVersion": "1",
                "clientInfo": {"name": "sumika", "version": "2.x"},
                "capabilities": {"events": True, "plans": True, "tools": True},
            },
            timeout=self.config.startup_timeout,
        )
        self._initialized = True
        self._advertised_capabilities = _capabilities_from(value)
        try:
            self._transport.notify("initialized", {})
        except AgentRuntimeError:
            # Some app-servers complete initialization with the response and
            # do not accept the optional notification.
            pass

    def _call_variants(self, methods: tuple[str, ...], params: dict[str, Any]) -> Any:
        last: ZCodeProtocolError | None = None
        for method in methods:
            try:
                return self._transport.request(method, params)
            except ZCodeProtocolError as error:
                if error.code in {-32600, -32601}:
                    last = error
                    continue
                raise
        if last is not None:
            raise last
        raise AgentRuntimeError("ZCode method list is empty")

    def _on_message(self, payload: dict[str, Any]) -> None:
        # A request from the server (rather than a response to our request)
        # must wait for an explicit user/Core decision.
        if payload.get("id") is not None and payload.get("method"):
            request_id = _safe_text(payload.get("id"), 240)
            if request_id:
                with self._event_lock:
                    self._pending_server_requests.add(request_id)
        try:
            event = self.normalize_event(payload)
        except AgentRuntimeError:
            return
        sink = self._event_sink
        if sink is not None:
            try:
                sink(event)
            except Exception as error:
                if self.logger:
                    self.logger.info("zcode event sink failed error_type=%s", type(error).__name__)

    def supports(self, capability: AgentCapability | str) -> bool:
        try:
            value = capability if isinstance(capability, AgentCapability) else AgentCapability(capability)
        except ValueError:
            return False
        if self._advertised_capabilities is None:
            return value in self.capability_ids
        return value in self.capability_ids or value in self._advertised_capabilities

    def runtime_capabilities(self) -> list[str]:
        values = set(self.capability_ids)
        if self._advertised_capabilities:
            values.update(self._advertised_capabilities)
        return sorted(item.value for item in values)


def _safe_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        text = text[:limit]
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    return text


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _first(value: Any, *keys: str) -> Any:
    if not isinstance(value, dict):
        return None
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def _first_list(value: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
    return []


def _extract_id(value: Any, keys: tuple[str, ...]) -> str:
    for key in keys:
        candidate = _first(value, key)
        text = _safe_text(candidate, 240)
        if text:
            return text
    return ""


def _session_id(params: Mapping[str, Any], *, names: tuple[str, ...] = ("sessionId", "session_id", "threadId", "thread_id")) -> str:
    for name in names:
        value = _safe_text(params.get(name), 240)
        if value:
            return value
    raise AgentRuntimeError("session id is required")


def _session_payload(params: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source, target, limit in (
        ("title", "title", 240),
        ("cwd", "cwd", 4096),
        ("workspaceId", "workspaceId", 240),
        ("workspace_id", "workspaceId", 240),
        ("agentPreset", "agentPreset", 160),
        ("agent_preset", "agentPreset", 160),
        ("model", "model", 240),
    ):
        if params.get(source) is not None:
            value = _safe_text(params.get(source), limit)
            if value:
                result[target] = value
    return result


def _prompt_content(params: Mapping[str, Any]) -> list[dict[str, str]]:
    content = params.get("content")
    if isinstance(content, list):
        result: list[dict[str, str]] = []
        for block in content[:32]:
            if not isinstance(block, dict):
                continue
            kind = _safe_text(block.get("type") or "text", 40)
            text = _safe_text(block.get("text"), _MAX_TEXT)
            if kind == "text" and text:
                result.append({"type": "text", "text": text})
        if result:
            return result
    text = _safe_text(params.get("text"), _MAX_TEXT)
    if not text:
        raise AgentRuntimeError("Agent prompt requires non-empty text or content")
    return [{"type": "text", "text": text}]


def _compact_public(value: Any, *, depth: int = 3) -> Any:
    """Bound app-server data before it can reach UI events or audit logs."""

    if depth <= 0:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:128]:
            name = _safe_text(key, 100)
            lowered = name.lower()
            if any(token in lowered for token in ("token", "secret", "password", "cookie", "authorization", "api_key", "apikey")):
                result[name] = "[redacted]"
                continue
            if lowered in {"prompt", "messages", "raw", "body", "stdout", "stderr"}:
                if isinstance(item, list):
                    result[name] = {"count": min(len(item), _MAX_RESPONSE_ITEMS)}
                else:
                    result[name] = "[omitted]"
                continue
            result[name] = _compact_public(item, depth=depth - 1)
        return result
    if isinstance(value, list):
        return [_compact_public(item, depth=depth - 1) for item in value[:_MAX_RESPONSE_ITEMS]]
    if isinstance(value, str):
        return _safe_text(value, 1200)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _normalize_models(value: Any) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    raw_groups = _first_list(value, ("groups", "providers", "data", "models"))
    if isinstance(value, dict) and isinstance(value.get("models"), list) and all(isinstance(item, dict) and "id" in item for item in value["models"]):
        raw_groups = [{"id": "zcode", "name": "ZCode", "models": value["models"]}]
    for group in raw_groups[:64]:
        if not isinstance(group, dict):
            continue
        models = _first_list(group, ("models", "items"))
        compact = []
        for model in models[:128]:
            if not isinstance(model, dict):
                continue
            model_id = _safe_text(_first(model, "id", "modelId", "name"), 240)
            if model_id:
                compact.append({"id": model_id, "name": _safe_text(_first(model, "name", "label") or model_id, 240)})
        if compact:
            groups.append({"id": _safe_text(_first(group, "id", "providerId") or "zcode", 120), "name": _safe_text(_first(group, "name", "label") or "ZCode", 160), "models": compact})
    return {"groups": groups}


def _capabilities_from(value: Any) -> set[AgentCapability]:
    names: list[str] = []
    if isinstance(value, dict):
        raw = value.get("capabilities") or value.get("features")
        if isinstance(raw, list):
            names.extend(str(item) for item in raw)
        elif isinstance(raw, dict):
            names.extend(str(key) for key, enabled in raw.items() if enabled is True)
    result: set[AgentCapability] = set()
    aliases = {
        "mcp": AgentCapability.MCP,
        "skills": AgentCapability.SKILLS,
        "subagents": AgentCapability.SUBAGENTS,
        "plan": AgentCapability.PLAN,
        "readonly": AgentCapability.READONLY,
        "attachments": AgentCapability.ATTACHMENTS,
        "models": AgentCapability.MODELS,
        "interactions": AgentCapability.INTERACTIONS,
    }
    for name in names:
        normalized = name.strip().lower().replace("_", "-")
        if normalized in aliases:
            result.add(aliases[normalized])
        else:
            try:
                result.add(AgentCapability(normalized))
            except ValueError:
                continue
    return result


def _event_type(method: str) -> str:
    value = method.lower().replace("/", ".")
    if "approval" in value or "permission" in value:
        return "approval/requested"
    if "question" in value or "input" in value:
        return "question/requested"
    if "error" in value or "failed" in value:
        return "session/event"
    if "item" in value or "message" in value or "turn" in value or "session" in value:
        return "session/event"
    return "runtime/event"


__all__ = ["ZCodeAgentRuntime", "ZCodeProtocolError"]
