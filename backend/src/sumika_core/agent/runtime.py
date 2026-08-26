"""DeepSeek Harness adapter.

This module never imports or forks DSH.  It speaks the pinned Web API and
fails closed when the independently managed DSH runtime is not reachable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

from ..protocol.models import utc_now
from .models import AgentApproval, AgentEvent, DSHRuntimeConfig, default_profile_dir


# ``llm-pi-ai`` requires a credential reference for OpenAI-compatible routes,
# even when the target is an unauthenticated local server such as Ollama.  The
# value is stored only in the managed DSH credential store and is never sent to
# a remote service as a user secret; the adapter uses it to satisfy its auth
# seam while the local endpoint ignores the bearer token.
_LOCAL_CREDENTIAL_SENTINEL = "sumika-local"


class AgentRuntimeError(RuntimeError):
    """A controlled Agent runtime failure.

    ``http_status`` and ``transport`` are intentionally kept as operational
    metadata.  They let the diagnostics probe distinguish an unregistered RPC
    (for example the pinned DSH ``mcp.list`` 404) from a disconnected runtime
    without exposing the upstream response body.
    """

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        transport: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.transport = transport


class AgentRuntime(ABC):
    """Stable capability slot consumed by CoreApplication."""

    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_presets(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def copy_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def open_preset_document(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def remove_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def select_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def session_models(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def open_session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_workspaces(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_workspace(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def select_model(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def sync_provider_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def provider_status(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def history(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def attachment(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def queue(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_queue(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_subagents(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def subagent_history(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def prompt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def interrupt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def goal_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_capabilities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def respond(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def interactions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def respond_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class UnavailableAgentRuntime(AgentRuntime):
    """Explicitly unavailable slot used before DSH is installed or started."""

    def __init__(self, reason: str = "DSH runtime is not connected") -> None:
        self.reason = reason

    def status(self) -> dict[str, Any]:
        return {"state": "unavailable", "ready": False, "reason": self.reason}

    def health(self) -> dict[str, Any]:
        return {"ok": False, "state": "unavailable", "error": self.reason}

    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "checked_at": utc_now(),
            "runtime": {"state": "unavailable", "ready": False},
            "capabilities": [],
            "mcp": {
                "available": False,
                "status": "unavailable",
                "endpoint": "mcp.list",
                "client_installed": False,
                "reason": self.reason,
            },
            "summary": {"available": 0, "unavailable": 1},
        }

    def _fail(self) -> None:
        raise AgentRuntimeError(self.reason)

    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def search_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def list_presets(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def copy_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def open_preset_document(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def remove_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def select_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def session_models(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def open_session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def list_workspaces(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def create_workspace(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def select_model(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def sync_provider_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def provider_status(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def history(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def attachment(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def queue(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def update_queue(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def list_subagents(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def subagent_history(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def prompt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def interrupt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def goal_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def list_capabilities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "available": False,
            "status": "unavailable",
            "catalog_available": False,
            "observation_source": "session-history",
            "client_installed": False,
            "client_version": None,
            "entries": [],
            "server_count": 0,
            "tool_count": 0,
            "reason": self.reason,
        }

    def respond(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def interactions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._fail()

    def respond_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        self._fail()

    def set_event_sink(self, sink: Any) -> None:
        return None

    def close(self) -> None:
        return None


class _WebSocketEventBridge:
    """Small stdlib-only client for DSH's read-only event WebSockets."""

    PATHS = ("/api/events.mux", "/api/events.host")

    def __init__(self, endpoint: str, sink: Any, logger: Any = None) -> None:
        self.endpoint = endpoint
        self.sink = sink
        self.logger = logger
        self.stop_event = threading.Event()
        self._lock = threading.RLock()
        self._sockets: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self.stop_event.clear()
        self._threads = []
        for path in self.PATHS:
            thread = threading.Thread(
                target=self._run,
                args=(path,),
                name=f"sumika-dsh-events-{path.rsplit('/', 1)[-1]}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def close(self) -> None:
        self.stop_event.set()
        with self._lock:
            sockets = list(self._sockets)
        for connection in sockets:
            try:
                _send_ws_frame(connection, 0x8, b"")
            except OSError:
                pass
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        current = threading.current_thread()
        for thread in self._threads:
            if thread is not current:
                thread.join(timeout=1.5)
        self._threads = []
        with self._lock:
            self._sockets.clear()

    def _run(self, path: str) -> None:
        retry = 0
        while not self.stop_event.is_set():
            connection: socket.socket | None = None
            try:
                connection, pending = self._connect(path)
                retry = 0
                with self._lock:
                    self._sockets.add(connection)
                _read_ws_messages(connection, pending, self.stop_event, self._receive)
            except Exception as error:
                retry += 1
                if self.logger:
                    self.logger.info(
                        "dsh event bridge path=%s unavailable error_type=%s retry=%d",
                        path,
                        type(error).__name__,
                        retry,
                    )
            finally:
                if connection is not None:
                    with self._lock:
                        self._sockets.discard(connection)
                    try:
                        connection.close()
                    except OSError:
                        pass
            if not self.stop_event.wait(min(5.0, 0.5 * max(1, retry))):
                continue

    def _connect(self, path: str) -> tuple[socket.socket, bytes]:
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AgentRuntimeError(f"unsupported DSH endpoint: {self.endpoint}")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection = socket.create_connection((parsed.hostname, port), timeout=3.0)
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            connection = context.wrap_socket(connection, server_hostname=parsed.hostname)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        host = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: {parsed.scheme}://{host}\r\n\r\n"
        ).encode("ascii")
        connection.sendall(request)
        response = _read_http_headers(connection)
        if not response.startswith(b"HTTP/1.1 101") and not response.startswith(b"HTTP/1.0 101"):
            raise AgentRuntimeError("DSH event WebSocket upgrade was refused")
        headers, _, pending = response.partition(b"\r\n\r\n")
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        header_map = _parse_headers(headers)
        if header_map.get("sec-websocket-accept") != expected:
            raise AgentRuntimeError("DSH event WebSocket handshake validation failed")
        connection.settimeout(1.0)
        return connection, pending

    def _receive(self, payload: bytes) -> None:
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(value, dict):
            return
        frame = value.get("payload") if isinstance(value.get("payload"), dict) else value
        if isinstance(frame, dict):
            event = dict(frame)
            if value.get("rpcId") is not None:
                event["rpcId"] = value["rpcId"]
            self.sink(event)


class DSHAgentRuntime(AgentRuntime):
    """HTTP/WebSocket-compatible client for the pinned DSH Web API."""

    def __init__(self, data_dir: str | Path | None = None, *, env: dict[str, str] | None = None, logger: Any = None) -> None:
        env = env or os.environ
        endpoint = str(env.get("SUMIKA_DSH_ENDPOINT", "http://127.0.0.1:3080")).rstrip("/")
        configured_profile = env.get("SUMIKA_DSH_PROFILE_DIR") or env.get("SUMIKA_DSH_HOME")
        profile_dir = configured_profile or default_profile_dir(data_dir)
        executable = env.get("SUMIKA_DSH_EXECUTABLE") or shutil.which("dsh")
        self.config = DSHRuntimeConfig(
            endpoint=endpoint,
            profile_dir=profile_dir,
            executable=executable,
            enabled=env.get("SUMIKA_DSH_ENABLED", "1").lower() not in {"0", "false", "no"},
        )
        self.logger = logger
        self._last_health: dict[str, Any] | None = None
        self._last_health_at = 0.0
        self._event_sink: Any = None
        self._event_bridge: _WebSocketEventBridge | None = None
        self._event_lock = threading.RLock()
        self._interaction_lock = threading.RLock()
        self._pending_interactions: dict[str, dict[str, Any]] = {}
        self._queue_lock = threading.RLock()
        self._session_queues: dict[str, dict[str, Any]] = {}

    def status(self) -> dict[str, Any]:
        if self.config.enabled and (self._last_health is None or time.monotonic() - self._last_health_at > 1.0):
            self.health()
        state = "disabled" if not self.config.enabled else "unavailable"
        if self._last_health and self._last_health.get("ok"):
            state = "ready"
        return {
            **self.config.to_dict(),
            "state": state,
            "ready": state == "ready",
            "launch_policy": "managed-profile-only",
            "global_install_untouched": True,
            "event_bridge": "running" if self._event_bridge is not None else "stopped",
            "event_paths": list(_WebSocketEventBridge.PATHS),
        }

    def health(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "state": "disabled", "error": "DSH runtime is disabled"}
        try:
            result = self._call("host.describe", {})
        except AgentRuntimeError as error:
            self._last_health = {"ok": False, "state": "unavailable", "error": str(error)}
            self._last_health_at = time.monotonic()
            return self._last_health
        self._last_health = {"ok": True, "state": "ready", "runtime": result}
        self._last_health_at = time.monotonic()
        self.start_event_bridge()
        return self._last_health

    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Probe the pinned DSH read-only API without exposing raw payloads.

        The probe is deliberately independent from ``list_capabilities``:
        capability cards are session-scoped, while this report answers the
        operational question "what is actually mounted in this profile?".
        Every check returns a bounded status and endpoint name only.  DSH
        responses such as ``cwd``, ``home``, prompts, settings values and
        credentials never cross this boundary.
        """

        del params
        checked_at = utc_now()
        profile_info = self._mcp_profile_info()
        report: dict[str, Any] = {
            "checked_at": checked_at,
            "runtime": {
                "state": "disabled" if not self.config.enabled else "unavailable",
                "ready": False,
                "endpoint": self.config.endpoint,
                "version": self.config.version,
                "commit": self.config.commit,
                "profile": "web",
                "profile_dir_configured": bool(self.config.profile_dir),
                "executable_configured": bool(self.config.executable),
            },
            "capabilities": [],
            "mcp": {
                "available": False,
                "status": "disabled" if not self.config.enabled else "unavailable",
                "endpoint": "mcp.list",
                "client_installed": profile_info["installed"],
                "client_version": profile_info["version"],
                "reason": "DSH runtime is disabled" if not self.config.enabled else "尚未连接 DSH",
            },
        }
        if not self.config.enabled:
            report["summary"] = {"available": 0, "disabled": 1}
            return report

        host_probe, host_value = self._probe_rpc("host.describe", {})
        report["capabilities"].append(
            self._diagnostic_capability("host", "Host API", "host.describe", host_probe)
        )
        if host_probe["status"] != "available":
            report["runtime"]["error"] = host_probe["detail"]
            report["mcp"]["status"] = "unavailable"
            report["mcp"]["reason"] = "DSH 未连接，无法判断 MCP 挂载状态"
            report["summary"] = self._diagnostic_summary(report["capabilities"])
            return report

        report["runtime"]["state"] = "ready"
        report["runtime"]["ready"] = True
        if isinstance(host_value, dict):
            protocol_version = _safe_agent_text(host_value.get("version"), 80)
            if protocol_version:
                report["runtime"]["protocol_version"] = protocol_version
            attached = host_value.get("attachedSessions")
            if isinstance(attached, int) and not isinstance(attached, bool) and attached >= 0:
                report["runtime"]["attached_sessions"] = attached
            for field in ("provider", "model"):
                value = _safe_agent_text(host_value.get(field), 160)
                if value:
                    report["runtime"][field] = value

        session_probe, session_value = self._probe_rpc("session.list", {})
        report["capabilities"].append(
            self._diagnostic_capability("sessions", "Sessions", "session.list", session_probe)
        )
        session_ids = _diagnostic_session_ids(session_value)
        session_id = session_ids[0] if session_ids else None

        for capability_id, label, method in (
            ("presets", "Agent presets", "agentPreset.list"),
            ("workspaces", "Workspaces", "workspace.list"),
            ("providers", "LLM providers", "llm.providers"),
            ("settings", "Settings", "settings.describe"),
        ):
            probe, _ = self._probe_rpc(method, {})
            report["capabilities"].append(
                self._diagnostic_capability(capability_id, label, method, probe)
            )

        if session_id:
            scoped_probes = (
                ("models", "Session models", "session.models", {"sessionId": session_id}),
                ("skills", "Skills", "skill.list", {"sessionId": session_id}),
                ("commands", "Command plane", "commands/list", {"args": {"agentId": session_id}}),
                ("subagents", "Subagents", "subagent.list", {"parentSessionId": session_id}),
            )
            for capability_id, label, method, payload in scoped_probes:
                probe, _ = self._probe_rpc(method, payload)
                report["capabilities"].append(
                    self._diagnostic_capability(capability_id, label, method, probe, scope="session")
                )
        else:
            for capability_id, label, method in (
                ("models", "Session models", "session.models"),
                ("skills", "Skills", "skill.list"),
                ("commands", "Command plane", "commands/list"),
                ("subagents", "Subagents", "subagent.list"),
            ):
                report["capabilities"].append(
                    {
                        "id": capability_id,
                        "label": label,
                        "endpoint": method,
                        "status": "session-scoped",
                        "available": None,
                        "scope": "session",
                        "detail": "需要至少一个 Agent 会话才能探测",
                    }
                )

        mcp_probe, mcp_value = self._probe_rpc("mcp.list", {})
        mcp_status = mcp_probe["status"]
        mcp_reason = {
            "not-exposed": "固定版 DSH Web API 未注册独立 mcp.list；MCP server 以 profile plugin 形式挂载，工具只能从 DSH tool catalog/事件观察",
            "unavailable": "DSH MCP 目录探测不可用",
            "rejected": "DSH 拒绝了 MCP 目录探测请求",
            "available": "DSH 返回了 MCP 目录",
        }.get(mcp_status, "未能确认 MCP 状态")
        mcp_report: dict[str, Any] = {
            "available": mcp_status == "available",
            "status": mcp_status,
            "endpoint": "mcp.list",
            "client_installed": profile_info["installed"],
            "client_version": profile_info["version"],
            "reason": mcp_reason,
        }
        if mcp_status == "available":
            mcp_report["server_count"] = _diagnostic_entry_count(mcp_value)
        elif profile_info["installed"]:
            mcp_report["reason"] += "；已发现 dsh-mcp-client 包，但当前 API 没有可读目录端点"
        else:
            mcp_report["reason"] += "；受管 web profile 未发现 dsh-mcp-client"
        report["mcp"] = mcp_report
        report["summary"] = self._diagnostic_summary(report["capabilities"])
        if self.logger:
            self.logger.info(
                "dsh diagnostics state=%s capabilities=%s mcp_status=%s mcp_client=%s",
                report["runtime"]["state"],
                report["summary"],
                mcp_status,
                profile_info["installed"],
            )
        return report

    def _probe_rpc(self, method: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Run one read-only probe and return a safe status plus raw value."""

        try:
            value = self._call(method, payload)
        except AgentRuntimeError as error:
            if error.http_status == 404:
                status = "not-exposed"
                detail = "HTTP 404：固定版 DSH 未注册该 RPC"
            elif error.transport:
                status = "unavailable"
                detail = "DSH endpoint 不可达"
            else:
                status = "rejected"
                detail = "DSH 已收到请求但拒绝了探测"
            return {"status": status, "available": False, "detail": detail}, None
        return {"status": "available", "available": True, "detail": "探测成功"}, value

    @staticmethod
    def _diagnostic_capability(
        capability_id: str,
        label: str,
        method: str,
        probe: dict[str, Any],
        *,
        scope: str = "runtime",
    ) -> dict[str, Any]:
        return {
            "id": capability_id,
            "label": label,
            "endpoint": method,
            "status": probe["status"],
            "available": probe["available"],
            "scope": scope,
            "detail": probe["detail"],
        }

    @staticmethod
    def _diagnostic_summary(capabilities: list[dict[str, Any]]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for item in capabilities:
            status = str(item.get("status") or "unknown")
            summary[status] = summary.get(status, 0) + 1
        return summary

    def _mcp_profile_info(self) -> dict[str, Any]:
        """Inspect only the managed web profile manifests for MCP package info.

        DSH's web profile can install the client under ``profiles/node_modules``
        while its top-level package manifest has no dependency declaration.
        Keep both checks explicit and rooted in the managed profile; never walk
        arbitrary ``node_modules`` trees or import package code.
        """

        result: dict[str, Any] = {"installed": False, "version": None}
        if not self.config.profile_dir:
            return result
        profile_root = Path(self.config.profile_dir)
        candidates = (
            profile_root / "profiles" / "node_modules" / "@deepseek-ai" / "dsh-mcp-client" / "package.json",
            profile_root / "profiles" / "web" / "package.json",
            profile_root / "package.json",
        )
        for candidate in candidates:
            try:
                # Keep the lexical path check. pnpm commonly represents this
                # managed package as a junction into its content-addressed
                # store; resolving it would incorrectly classify a valid
                # profile install as an external scan.
                root_text = os.path.normcase(os.path.abspath(str(profile_root)))
                candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
                if os.path.commonpath((root_text, candidate_text)) != root_text:
                    continue
                if not candidate.is_file():
                    continue
                value = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if candidate.parts[-3:] == ("@deepseek-ai", "dsh-mcp-client", "package.json"):
                if value.get("name") != "@deepseek-ai/dsh-mcp-client":
                    continue
                result["installed"] = True
                result["version"] = _safe_agent_text(value.get("version"), 80) or None
                return result
            dependencies: dict[str, Any] = {}
            for key in ("dependencies", "devDependencies", "optionalDependencies"):
                section = value.get(key)
                if isinstance(section, dict):
                    dependencies.update(section)
            package_version = dependencies.get("@deepseek-ai/dsh-mcp-client")
            if package_version is not None:
                result["installed"] = True
                result["version"] = _safe_agent_text(package_version, 80)
                return result
        return result

    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = _session_create_payload(params)
        return self._call("session.create", payload)

    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """List only the managed DSH session metadata needed by Sumika."""

        value = self._call("session.list", {})
        items = value.get("items") if isinstance(value, dict) else []
        sessions: list[dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            projections = item.get("projections") if isinstance(item.get("projections"), dict) else {}
            values = projections.get("values") if isinstance(projections.get("values"), dict) else {}
            stats = _safe_numeric_map(values.get("sessionStats"))
            sessions.append(
                {
                    "id": _safe_agent_text(item.get("sessionId"), 120),
                    "title": _safe_agent_text(values.get("title") or "未命名 Agent 会话", 180),
                    "state": "running" if bool(item.get("running")) else "idle",
                    "blank": bool(item.get("blank")),
                    "updated_at": item.get("updatedAt"),
                    "agent_preset": _safe_agent_text(item.get("agentPreset"), 80),
                    "stats": stats,
                }
            )
        sessions.sort(key=lambda session: (session.get("updated_at") or 0), reverse=True)
        return {"sessions": sessions}

    def search_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Search visible session content through DSH's bounded search API."""

        query = _session_search_query(params or {})
        return _compact_session_search(self._call("session.search", {"query": query}))

    def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Pin a user-provided title using DSH's session/title event."""

        session_id = _session_id(params)
        title = _session_title(params.get("title"))
        value = self._call(
            "session.rename",
            {"sessionId": session_id, "title": title},
        )
        accepted = _session_title(value.get("title") if isinstance(value, dict) else None)
        sequence = value.get("seq") if isinstance(value, dict) else None
        if not accepted or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise AgentRuntimeError("DSH session.rename returned an invalid title response")
        return {
            "session_id": session_id,
            "title": _safe_agent_text(accepted, 240),
            "seq": sequence,
        }

    def list_presets(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the DSH preset roster as a bounded, path-free projection."""

        return _compact_agent_presets(self._call("agentPreset.list", {}))

    def copy_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        """Copy a known preset into DSH's managed user preset root.

        DSH owns the copy operation and validates the destination id.  Sumika
        only accepts a slug-like id and bounded display name, then returns a
        path-free acknowledgement so local filesystem details do not leak.
        """

        source = _agent_preset_id(params.get("from") or params.get("source"), "from")
        destination = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        if source == destination:
            raise AgentRuntimeError("DSH source and destination presets must differ")
        payload: dict[str, Any] = {"from": source, "agentPreset": destination}
        name = _agent_preset_name(params.get("name"))
        if name:
            payload["name"] = name
        value = self._call("agentPreset.copy", payload)
        copied = _agent_preset_id(
            value.get("agentPreset") if isinstance(value, dict) else destination,
            "agentPreset",
        )
        return {"agent_preset": copied, "source": source}

    def open_preset_document(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ask DSH to open a user-owned preset directory.

        The pinned API may return a path when the host cannot open it.  That
        path is intentionally discarded at the Sumika boundary.
        """

        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        value = self._call("agentPreset.openDocument", {"agentPreset": preset})
        opened = bool(value.get("opened")) if isinstance(value, dict) else False
        return {"agent_preset": preset, "opened": opened}

    def remove_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        """Remove a preset through DSH after the Core policy gate approves it."""

        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        self._call("agentPreset.remove", {"agentPreset": preset})
        return {"agent_preset": preset, "removed": True}

    def select_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        """Select a preset for a still-blank session; DSH enforces that lock."""

        session_id = _session_id(params)
        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset"),
            "agentPreset",
        )
        value = self._call(
            "agentPreset.select",
            {"sessionId": session_id, "agentPreset": preset},
        )
        try:
            selected = _agent_preset_id(
                value.get("agentPreset") if isinstance(value, dict) else None,
                "agentPreset",
            )
        except AgentRuntimeError:
            selected = preset
        return {"session_id": session_id, "agent_preset": selected}

    def session_models(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return DSH's advisory model directory with no provider secrets."""

        return _compact_model_catalog(
            self._call("session.models", {"sessionId": _session_id(params)})
        )

    def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a recoverable child session from a completed-turn prefix."""

        payload: dict[str, Any] = {"sessionId": _session_id(params)}
        at_seq = params.get("atSeq") if params.get("atSeq") is not None else params.get("at_seq")
        if at_seq is not None:
            if isinstance(at_seq, bool) or not isinstance(at_seq, int) or at_seq < 0:
                raise AgentRuntimeError("session fork atSeq must be a non-negative integer")
            payload["atSeq"] = at_seq
        result = self._call("session.fork", payload)
        child_id = result.get("sessionId") or result.get("id")
        if not isinstance(child_id, str) or not child_id.strip():
            raise AgentRuntimeError("DSH fork did not return a child session id")
        return {"sessionId": child_id}

    def open_session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        """Open DSH's streamed session-log ZIP without buffering it in Core."""

        session_id = _session_id(params)
        include_descendants = params.get("includeDescendants")
        if include_descendants is None:
            include_descendants = params.get("include_descendants", False)
        if not isinstance(include_descendants, bool):
            raise AgentRuntimeError("includeDescendants must be a boolean")
        query = {"sessionId": session_id}
        if include_descendants:
            query["includeDescendants"] = "true"
        request = urllib.request.Request(
            f"{self.config.endpoint.rstrip('/')}/api/session.export?{urlencode(query)}",
            method="GET",
            headers={"Accept": "application/zip"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=30.0)
        except urllib.error.HTTPError as error:
            if self.logger:
                self.logger.info(
                    "dsh session export http_error endpoint=%s status=%s",
                    self.config.endpoint,
                    error.code,
                )
            raise AgentRuntimeError(
                f"DSH session export returned HTTP {error.code}",
                http_status=error.code,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if self.logger:
                self.logger.info(
                    "dsh session export unavailable endpoint=%s error_type=%s",
                    self.config.endpoint,
                    type(error).__name__,
                )
            raise AgentRuntimeError(
                f"DSH runtime unavailable at {self.config.endpoint}",
                transport=True,
            ) from error

        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/zip":
            response.close()
            raise AgentRuntimeError("DSH session export did not return a ZIP archive")
        content_length: int | None = None
        raw_length = response.headers.get("Content-Length")
        if raw_length:
            try:
                parsed_length = int(raw_length)
            except (TypeError, ValueError):
                parsed_length = -1
            if parsed_length >= 0:
                content_length = parsed_length
        return {
            "stream": response,
            "session_id": session_id,
            "content_type": content_type,
            "content_length": content_length,
            "include_descendants": include_descendants,
        }

    def list_workspaces(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """List DSH workspace registrations without reading workspace files."""

        value = self._call("workspace.list", {})
        items = value.get("items") if isinstance(value, dict) else []
        workspaces = [_compact_workspace(item) for item in items or [] if isinstance(item, dict)]
        return {
            "workspaces": [item for item in workspaces if item is not None],
            "archived_session_ids": [
                _safe_agent_text(item, 120)
                for item in (value.get("archivedSessionIds") if isinstance(value, dict) else []) or []
                if isinstance(item, str) and item.strip()
            ],
        }

    def create_workspace(self, params: dict[str, Any]) -> dict[str, Any]:
        """Register an existing directory; DSH, not Sumika, validates it."""

        path = str(params.get("path") or "").strip()
        if not path:
            raise AgentRuntimeError("workspace path is required")
        if len(path) > 4096:
            raise AgentRuntimeError("workspace path is too long")
        value = self._call("workspace.create", {"path": path})
        workspace = _compact_workspace(value.get("workspace") if isinstance(value, dict) else None)
        if workspace is None:
            raise AgentRuntimeError("DSH workspace registration returned no workspace")
        return {"workspace": workspace, "created": bool(value.get("created")) if isinstance(value, dict) else False}

    def select_model(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        provider = str(params.get("provider") or "").strip()
        model = str(params.get("model") or "").strip()
        if not provider or not model:
            raise AgentRuntimeError("DSH model selection requires provider and model")
        payload: dict[str, Any] = {
            "sessionId": session_id,
            "provider": provider,
            "model": model,
        }
        reasoning_effort = params.get("reasoningEffort") or params.get("reasoning_effort")
        if reasoning_effort is not None and str(reasoning_effort).strip():
            payload["reasoningEffort"] = str(reasoning_effort)
        return self._call("session.selectModel", payload)

    def sync_provider_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Expose one Sumika profile as an isolated DSH ``llm-pi-ai`` route.

        The managed DSH profile is the only state changed here. Existing DSH
        routes remain untouched, and secret values travel only through the
        credentials RPC; this method never returns or logs them.
        """

        if not self.config.enabled:
            raise AgentRuntimeError("DSH runtime is disabled")
        desired = _dsh_route_from_sumika_profile(profile)
        namespace = self._call("settings.describe", {})
        descriptor = _find_settings_namespace(namespace, "llm-pi-ai")
        current_value = descriptor.get("value") if isinstance(descriptor, dict) else {}
        if not isinstance(current_value, dict):
            current_value = {}
        current_providers = current_value.get("providers")
        if not isinstance(current_providers, dict):
            current_providers = {}
        route_id = desired["route_id"]
        previous = current_providers.get(route_id)
        changed = not isinstance(previous, dict) or not _dsh_route_matches(previous, desired["route"])
        credential_ref = desired.get("credential_ref")
        secret_value = desired.get("secret_value")

        # Store the credential before activating a route that references it.
        # The value is deliberately kept out of every response and log.
        if credential_ref and secret_value:
            self._call("credentials.set", {"ref": credential_ref, "value": secret_value})

        if changed:
            payload: dict[str, Any] = {
                "ns": "llm-pi-ai",
                "ops": [{"op": "set", "path": ["providers", route_id], "value": desired["route"]}],
            }
            revision = descriptor.get("revision") if isinstance(descriptor, dict) else None
            if isinstance(revision, int):
                payload["expectedRevision"] = revision
            try:
                self._call("settings.mutate", payload)
            except AgentRuntimeError:
                # A concurrent settings editor can advance the revision. Read
                # once and retry with the fresh revision; no blind overwrite.
                refreshed = self._call("settings.describe", {})
                fresh_descriptor = _find_settings_namespace(refreshed, "llm-pi-ai")
                retry_payload = dict(payload)
                fresh_revision = fresh_descriptor.get("revision")
                if isinstance(fresh_revision, int):
                    retry_payload["expectedRevision"] = fresh_revision
                self._call("settings.mutate", retry_payload)

        # If an earlier version of this route had an API key and the current
        # profile no longer does, remove only Sumika's own credential ref.
        if not credential_ref:
            old_route = previous if isinstance(previous, dict) else {}
            old_ref = old_route.get("apiKeyEnv")
            if isinstance(old_ref, str) and old_ref:
                try:
                    self._call("credentials.unset", {"ref": old_ref})
                except AgentRuntimeError as error:
                    if self.logger:
                        self.logger.info("dsh provider credential cleanup skipped error_type=%s", type(error).__name__)

        try:
            providers = self._call("llm.providers", {}).get("providers", [])
        except AgentRuntimeError as error:
            raise AgentRuntimeError(f"DSH provider catalog unavailable after sync: {error}") from error
        catalog_entry = next(
            (item for item in providers if isinstance(item, dict) and item.get("provider") == route_id),
            None,
        )
        if not isinstance(catalog_entry, dict) or not bool(catalog_entry.get("active")):
            raise AgentRuntimeError(
                f'DSH did not activate provider route "{route_id}"; the llm-pi-ai adapter may be unavailable'
            )
        result = {
            "profile_id": desired["profile_id"],
            "route_id": route_id,
            "model": desired["model"],
            "changed": changed,
            "active": True,
            "credential_configured": bool(credential_ref and secret_value),
            "credential_mode": desired.get("credential_mode"),
        }
        if self.logger:
            self.logger.info(
                "dsh provider route synced profile_id=%s route_id=%s model=%s changed=%s",
                desired["profile_id"],
                route_id,
                desired["model"],
                changed,
            )
        return result

    def provider_status(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        if profile is None:
            return {"state": "unconfigured", "ready": False, "reason": "没有选择 Sumika Provider 档案"}
        try:
            desired = _dsh_route_from_sumika_profile(profile)
            namespace = self._call("settings.describe", {})
            descriptor = _find_settings_namespace(namespace, "llm-pi-ai")
            value = descriptor.get("value") if isinstance(descriptor, dict) else {}
            providers = value.get("providers") if isinstance(value, dict) else {}
            current = providers.get(desired["route_id"]) if isinstance(providers, dict) else None
            synced = isinstance(current, dict) and _dsh_route_matches(current, desired["route"])
            catalog = self._call("llm.providers", {}).get("providers", [])
            active = any(
                isinstance(item, dict)
                and item.get("provider") == desired["route_id"]
                and bool(item.get("active"))
                for item in catalog
            )
            ready = synced and active
            return {
                "state": "ready" if ready else "not-synced",
                "ready": ready,
                "profile_id": desired["profile_id"],
                "route_id": desired["route_id"],
                "model": desired["model"],
                "synced": synced,
                "active": active,
                "reason": None if ready else "Provider 档案尚未同步到 DSH",
            }
        except AgentRuntimeError as error:
            return {"state": "unavailable", "ready": False, "error": str(error)}

    def _settings_namespace(self, namespace: str) -> dict[str, Any]:
        value = self._call("settings.describe", {})
        return _find_settings_namespace(value, namespace)

    def history(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"sessionId": _session_id(params)}
        for key in ("beforeSeq", "maxMessages"):
            if params.get(key) is not None:
                payload[key] = params[key]
        return self._call("session.history", payload)

    def attachment(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read one image only after DSH verifies session ownership."""

        session_id = _session_id(params)
        attachment_id = _attachment_id(params.get("attachmentId") or params.get("attachment_id"))
        value = self._call(
            "session.attachment",
            {"sessionId": session_id, "attachmentId": attachment_id},
        )
        if not isinstance(value, dict):
            raise AgentRuntimeError("DSH attachment response was not an object")
        reference = _compact_attachment_reference(value.get("attachment"), expected_id=attachment_id)
        data = value.get("data")
        if not isinstance(data, str) or not _valid_base64_payload(data, max_bytes=_MAX_ATTACHMENT_BYTES):
            raise AgentRuntimeError("DSH attachment response contained invalid or oversized image data")
        return {"session_id": session_id, "attachment": reference, "data": data}

    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return a compact, UI-safe projection of one DSH session.

        DSH history contains every streaming chunk plus system/plugin prompts.
        The Sumika UI only needs the durable conversation and execution summary,
        so this boundary deliberately drops raw arguments, tool output, and
        prompt snapshots before data leaves the core process.
        """

        session_id = _session_id(params)
        listing = self._call("session.list", {})
        items = listing.get("items") if isinstance(listing, dict) else None
        item = next(
            (candidate for candidate in items or [] if isinstance(candidate, dict) and candidate.get("sessionId") == session_id),
            None,
        )
        if not isinstance(item, dict):
            raise AgentRuntimeError(f"unknown DSH session: {session_id}")
        projections = item.get("projections") if isinstance(item.get("projections"), dict) else {}
        values = projections.get("values") if isinstance(projections.get("values"), dict) else {}
        compact = _compact_session_history(
            session_id,
            {
                "events": [],
                "projections": {"values": values},
            },
        )
        compact["state"] = "running" if bool(item.get("running")) else compact["state"]
        compact["event_count"] = int(projections.get("asOfSeq", -1)) + 1 if isinstance(projections.get("asOfSeq"), int) else 0
        if params.get("include_history", True) is False:
            return compact
        history = self.history(
            {
                "session_id": session_id,
                # DSH's maxMessages bounds message groups, not raw chunks.
                # Two groups contain the latest user/assistant exchange while
                # avoiding an unnecessary full replay for routine refreshes.
                "maxMessages": min(8, max(1, int(params.get("maxMessages", 2)))),
            }
        )
        detailed = _compact_session_history(session_id, history)
        for key in ("messages", "timeline", "tools", "approvals", "artifacts", "has_more"):
            compact[key] = detailed.get(key, compact.get(key))
        if detailed.get("state") not in {"idle", "unknown"} and compact["state"] != "running":
            compact["state"] = detailed["state"]
        return compact

    def queue(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return the latest authoritative transient queue snapshot from DSH."""

        session_id = _session_id(params)
        with self._queue_lock:
            value = self._session_queues.get(session_id)
            if value is None:
                return {
                    "session_id": session_id,
                    "known": False,
                    "items": [],
                    "hidden_context_count": 0,
                    "updated_at": None,
                }
            return {
                "session_id": session_id,
                "known": True,
                "items": [dict(item) for item in value["items"]],
                "hidden_context_count": value["hidden_context_count"],
                "updated_at": value["updated_at"],
            }

    def update_queue(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        item_id = _safe_agent_text(params.get("itemId") or params.get("item_id"), 160)
        if not item_id:
            raise AgentRuntimeError("DSH queue itemId is required")
        kind = str(params.get("action") or params.get("kind") or "").strip().lower()
        if kind not in {"edit", "remove", "steer"}:
            raise AgentRuntimeError("DSH queue action must be edit, remove, or steer")
        action: dict[str, Any] = {"kind": kind}
        if kind == "edit":
            text = str(params.get("text") or "").strip()
            if not text:
                raise AgentRuntimeError("DSH queue edit requires non-empty text")
            if len(text) > 12000:
                raise AgentRuntimeError("DSH queue edit text exceeds 12000 characters")
            action["content"] = [{"type": "text", "text": text}]
        result = self._call(
            "session.updateQueue",
            {"sessionId": session_id, "itemId": item_id, "action": action},
        )
        return {
            "accepted": bool(result.get("accepted")) if isinstance(result, dict) else False,
            "session_id": session_id,
            "item_id": item_id,
            "action": kind,
        }

    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _session_id(params)
        text = str(params.get("text") or "").strip()
        content = params.get("content")
        if content is None:
            if not text:
                raise AgentRuntimeError("Agent prompt requires non-empty text or content")
            content = [{"type": "text", "text": text}]
        content = _prompt_content(content)
        mode = str(params.get("transport_mode") or params.get("queue_mode") or "queue")
        if mode not in {"queue", "steer"}:
            mode = "queue"
        requested_mode = str(params.get("mode") or "execute")
        if requested_mode == "readonly":
            raise AgentRuntimeError("readonly mode requires a DSH agent preset with a read-only policy")
        if requested_mode == "plan":
            # Slash commands live in DSH's command plane.  Sending `/plan` via
            # session.prompt would persist it as a user message and may start a
            # model turn, so route it through the typed commands endpoint.
            command_line = _plan_command_line(content)
            result = self._execute_command(session_id, command_line)
            return {"id": result["commandId"], "command": result}
        if requested_mode == "execute" and bool(params.get("leave_plan", True)):
            # Wait for the command handler to settle before queueing the real
            # prompt.  This prevents a plan-exit command from racing the user's
            # execution request or entering model history as plain text.
            self._execute_command(session_id, "/plan off")
        return self._call("session.prompt", {"sessionId": session_id, "mode": mode, "content": content})

    def _execute_command(self, session_id: str, line: str) -> dict[str, Any]:
        """Execute one DSH slash command without routing it through the model."""

        result = self._call(
            "commands/execute",
            {"args": {"agentId": session_id, "line": line, "images": []}},
        )
        command_id = result.get("commandId") if isinstance(result, dict) else None
        if not isinstance(command_id, str) or not command_id:
            raise AgentRuntimeError(
                "DSH command bridge did not return a command id; the pinned runtime may not mount commands/execute"
            )
        command_result = result.get("result")
        if isinstance(command_result, dict) and command_result.get("kind") == "error":
            message = str(command_result.get("text") or "DSH command was rejected")
            raise AgentRuntimeError(message)
        return result

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._call("session.cancel", {"sessionId": _session_id(params)})

    def list_subagents(self, params: dict[str, Any]) -> dict[str, Any]:
        """List direct DSH children without exposing host internals."""

        parent_id = _session_id(params)
        return _compact_subagent_catalog(
            self._call("subagent.list", {"parentSessionId": parent_id})
        )

    def subagent_history(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a child transcript through DSH's addressable history API."""

        payload = _subagent_address_payload(params)
        for key in ("beforeSeq", "maxMessages"):
            if params.get(key) is not None:
                payload[key] = params[key]
        child_id = payload["childSessionId"]
        value = self._call("subagent.history", payload)
        compact = _compact_session_history(child_id, value)
        return {
            "parent_session_id": payload["parentSessionId"],
            "child_session_id": child_id,
            "mode": payload["mode"],
            **compact,
            "has_more": bool(value.get("hasMore")) if isinstance(value, dict) else compact.get("has_more", False),
        }

    def prompt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send a text-only follow-up to a continuable child."""

        payload = _subagent_address_payload(params, require_continuable=True)
        content = _safe_text_content(params.get("content"), params.get("text"))
        payload["content"] = content
        timezone_value = params.get("clientTimeZone") or params.get("client_time_zone")
        if timezone_value is not None:
            timezone_text = _safe_agent_text(timezone_value, 80)
            if timezone_text:
                payload["clientTimeZone"] = timezone_text
        value = self._call("subagent.prompt", payload)
        message_id = _safe_agent_text(
            value.get("messageId") if isinstance(value, dict) else None,
            160,
        )
        if not message_id and isinstance(value, dict):
            message_id = _safe_agent_text(value.get("message_id") or value.get("id"), 160)
        if not message_id:
            raise AgentRuntimeError("DSH subagent prompt did not return a message id")
        return {
            "accepted": True,
            "parent_session_id": payload["parentSessionId"],
            "child_session_id": payload["childSessionId"],
            "message_id": message_id,
        }

    def interrupt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Admit a cancellation request for a continuable child."""

        payload = _subagent_address_payload(params, require_continuable=True)
        value = self._call("subagent.interrupt", payload)
        accepted = bool(value.get("accepted")) if isinstance(value, dict) else False
        if not accepted:
            raise AgentRuntimeError("DSH did not accept the subagent interrupt")
        return {
            "accepted": True,
            "parent_session_id": payload["parentSessionId"],
            "child_session_id": payload["childSessionId"],
        }

    def goal_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Apply one CAS-guarded DSH goal mutation and return only its receipt."""

        action = str(action).strip().lower()
        method = {
            "create": "goal.create",
            "edit": "goal.edit",
            "pause": "goal.pause",
            "resume": "goal.resume",
            "complete": "goal.complete",
            "clear": "goal.clear",
        }.get(action)
        if method is None:
            raise AgentRuntimeError("unsupported DSH goal action")
        session_id = _session_id(params)
        payload: dict[str, Any] = {"sessionId": session_id}
        if action == "create":
            objective = _safe_agent_text(params.get("objective"), 12000)
            if not objective:
                raise AgentRuntimeError("goal objective is required")
            payload["objective"] = objective
            _add_goal_round_cap(payload, params)
        else:
            payload["ref"] = _goal_ref(params.get("ref"))
            if action == "edit":
                if "objective" in params:
                    objective = _safe_agent_text(params.get("objective"), 12000)
                    if not objective:
                        raise AgentRuntimeError("goal objective cannot be empty")
                    payload["objective"] = objective
                _add_goal_round_cap(payload, params)
        value = self._call(method, payload)
        if action == "clear":
            return {"cleared": bool(value.get("cleared", True)) if isinstance(value, dict) else True}
        ref = _goal_ref(value.get("ref") if isinstance(value, dict) else None)
        return {"ref": ref}

    def list_capabilities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        session_id = (
            _session_id(params)
            if params.get("sessionId")
            or params.get("session_id")
            or params.get("parentSessionId")
            or params.get("parent_session_id")
            else None
        )
        values: dict[str, Any] = {}
        if not session_id:
            return {
                "skills": {"available": False, "error": "create an Agent session first"},
                "mcp": {"available": False, "error": "DSH does not expose an MCP catalog RPC in the pinned API"},
                "subagents": {"available": False, "error": "create an Agent session first"},
                "commands": {"available": False, "error": "create an Agent session first"},
            }
        values["mcp"] = {
            "available": False,
            "error": "DSH does not expose an MCP catalog RPC in the pinned API; MCP tools remain in the DSH tool catalog",
        }
        for key, method, payload in (
            ("skills", "skill.list", {"sessionId": session_id}),
            ("subagents", "subagent.list", {"parentSessionId": session_id}),
            ("commands", "commands/list", {"args": {"agentId": session_id}}),
        ):
            try:
                value = self._call(method, payload)
                if isinstance(value, dict) and isinstance(value.get("value"), list):
                    values[key] = {"available": True, "entries": value["value"]}
                else:
                    values[key] = value
            except AgentRuntimeError as error:
                values[key] = {"available": False, "error": str(error)}
        return values

    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return MCP tools observed in one bounded DSH session history.

        The pinned DSH API has no independent MCP catalog.  Public tool names
        in durable session events are authoritative evidence that a server was
        available for that call, but they are not a live health signal.
        """

        params = params or {}
        profile_info = self._mcp_profile_info()
        result: dict[str, Any] = {
            "available": False,
            "status": "not-observed",
            "catalog_available": False,
            "observation_source": "session-history",
            "client_installed": profile_info["installed"],
            "client_version": profile_info["version"],
            "entries": [],
            "server_count": 0,
            "tool_count": 0,
            "reason": "选择一个 Agent 会话后，Sumika 会从近期 DSH 工具事件中归纳 MCP 使用情况",
        }
        if not any(
            params.get(key)
            for key in ("sessionId", "session_id", "parentSessionId", "parent_session_id")
        ):
            return result

        session_id = _session_id(params)
        history = self.history({"session_id": session_id, "maxMessages": 32})
        compact = _compact_session_history(session_id, history)
        observed = _mcp_inventory_from_tools(compact.get("tools"))
        result.update(observed)
        result["session_id"] = session_id
        if result["tool_count"]:
            result["available"] = True
            result["status"] = "observed"
            result["reason"] = "来自该会话近期 DSH 历史；表示曾成功挂载，不代表当前连接健康"
        else:
            result["reason"] = "该会话近期 DSH 历史中尚未观察到 MCP 工具调用"
        return result

    def respond(self, params: dict[str, Any]) -> dict[str, Any]:
        # DSH server-initiated approval/question requests are answered as a
        # client-response envelope with the original server-request rpcId.
        rpc_id = params.get("rpcId") or params.get("rpc_id") or params.get("request_id")
        if not rpc_id:
            raise AgentRuntimeError("DSH response requires the original rpcId")
        result = params.get("result")
        if not isinstance(result, dict):
            result = {"ok": True, "value": result if result is not None else {}}
        body = {"type": "client-response", "rpcId": str(rpc_id), "result": result}
        return self._post("/api/respond", body)

    def interactions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return UI-safe pending DSH approval/question requests.

        Answerable frames are transient host state.  Keeping the projection in
        this adapter lets a reconnecting Sumika UI recover the same queue while
        leaving the DSH request ids and raw payloads out of the public status API.
        """

        session_id = None
        if params:
            value = params.get("sessionId") or params.get("session_id")
            if value:
                session_id = str(value)
        with self._interaction_lock:
            values = [dict(item) for item in self._pending_interactions.values()]
        if session_id:
            values = [item for item in values if item.get("session_id") == session_id]
        values.sort(key=lambda item: str(item.get("created_at") or ""))
        return {"interactions": values}

    def respond_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate and answer one DSH server-request frame.

        DSH validates the same payload again, but validating here prevents a
        malformed or stale browser request from ever being sent across the
        runtime boundary.
        """

        rpc_id = str(params.get("rpcId") or params.get("rpc_id") or "").strip()
        if not rpc_id:
            raise AgentRuntimeError("interaction response requires rpcId")
        with self._interaction_lock:
            pending = dict(self._pending_interactions.get(rpc_id) or {})
        if not pending:
            raise AgentRuntimeError("interaction is no longer pending")
        kind = pending.get("kind")
        session_id = str(params.get("sessionId") or params.get("session_id") or "").strip()
        if session_id != pending.get("session_id"):
            raise AgentRuntimeError("interaction session does not match")
        if kind == "approval":
            approval_id = str(params.get("approvalId") or params.get("approval_id") or "").strip()
            outcome = str(params.get("outcome") or "").strip()
            if approval_id != pending.get("approval_id") or outcome not in {"allowed-once", "rejected"}:
                raise AgentRuntimeError("invalid approval response")
            result = {"ok": True, "value": {"sessionId": session_id, "approvalId": approval_id, "outcome": outcome}}
        elif kind == "question":
            answer = params.get("answer")
            if not isinstance(answer, dict) or not _valid_question_answer(answer, pending.get("questions")):
                raise AgentRuntimeError("invalid question response")
            result = {"ok": True, "value": {"sessionId": session_id, "answer": answer}}
        else:
            raise AgentRuntimeError("unsupported interaction type")
        response = self.respond({"rpc_id": rpc_id, "result": result})
        response_value = response.get("value") if isinstance(response.get("value"), dict) else response
        if response_value.get("accepted") is not True:
            raise AgentRuntimeError(f"DSH rejected the interaction response: {response.get('reason') or 'unknown reason'}")
        with self._interaction_lock:
            self._pending_interactions.pop(rpc_id, None)
        return {"accepted": True, "kind": kind, "response": response}

    def set_event_sink(self, sink: Any) -> None:
        self._event_sink = sink

    def start_event_bridge(self) -> None:
        with self._event_lock:
            if not self.config.enabled or self._event_sink is None or self._event_bridge is not None:
                return
            self._event_bridge = _WebSocketEventBridge(self.config.endpoint, self._receive_event, self.logger)
            self._event_bridge.start()

    def stop_event_bridge(self) -> None:
        with self._event_lock:
            bridge, self._event_bridge = self._event_bridge, None
        if bridge is not None:
            bridge.close()

    def close(self) -> None:
        self.stop_event_bridge()
        with self._interaction_lock:
            self._pending_interactions.clear()
        with self._queue_lock:
            self._session_queues.clear()

    def normalize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        nested_event = payload.get("event") if isinstance(payload.get("event"), dict) else None
        source = nested_event or payload
        event_type = str(payload.get("event_type") or payload.get("type") or payload.get("method") or "agent.event")
        status = str(payload.get("status") or source.get("type") or "unknown")
        content = None
        if event_type not in {"session/event", "session/queue", "session/jobs", "session/projection"}:
            content = source.get("content") or source.get("text")
        event = AgentEvent(
            event_type=event_type,
            session_id=_text(payload.get("session_id") or payload.get("sessionId") or source.get("sessionId")),
            turn_id=_text(payload.get("turn_id") or payload.get("turnId")),
            item_id=_text(payload.get("item_id") or payload.get("itemId")),
            status=status,
            content=_safe_agent_text(content, 1200) if content is not None else None,
            extensions=_safe_event_extensions(payload, source, event_type),
            timestamp=str(payload.get("timestamp") or source.get("timestamp") or utc_now()),
        )
        normalized = event.to_dict()
        self._track_interaction(source, payload)
        self._track_queue(source, payload)
        return normalized

    def _track_queue(self, source: dict[str, Any], payload: dict[str, Any]) -> None:
        if str(payload.get("type") or "") != "session/queue":
            return
        session_id = _text(payload.get("sessionId") or source.get("sessionId"))
        items = payload.get("items")
        if not session_id or not isinstance(items, list):
            return
        compact = _compact_queue_items(items)
        with self._queue_lock:
            self._session_queues[session_id] = {
                "items": compact["items"],
                "hidden_context_count": compact["hidden_context_count"],
                "updated_at": utc_now(),
            }

    def _track_interaction(self, source: dict[str, Any], payload: dict[str, Any]) -> None:
        event_type = str(source.get("type") or payload.get("type") or "")
        session_id = _text(source.get("sessionId") or payload.get("session_id") or payload.get("sessionId"))
        rpc_id = _text(payload.get("rpcId") or source.get("rpcId"))
        if not session_id:
            return
        with self._interaction_lock:
            if event_type == "approval/requested" and rpc_id:
                self._pending_interactions[rpc_id] = {
                    "id": rpc_id,
                    "kind": "approval",
                    "session_id": session_id,
                    "approval_id": _safe_agent_text(source.get("approvalId"), 120),
                    "action": _safe_agent_text(source.get("toolName") or "需要确认", 160),
                    "reason": _safe_agent_text(source.get("reason"), 500),
                    "created_at": str(source.get("timestamp") or utc_now()),
                }
            elif event_type == "question/requested" and rpc_id:
                questions = _safe_questions(source.get("questions"))
                if questions:
                    self._pending_interactions[rpc_id] = {
                        "id": rpc_id,
                        "kind": "question",
                        "session_id": session_id,
                        "questions": questions,
                        "created_at": str(source.get("timestamp") or utc_now()),
                    }
            elif event_type == "approval/resolved":
                approval_id = _text(source.get("approvalId"))
                for key, item in list(self._pending_interactions.items()):
                    if item.get("kind") == "approval" and item.get("session_id") == session_id and item.get("approval_id") == approval_id:
                        self._pending_interactions.pop(key, None)
            elif event_type == "question/resolved":
                resolved_id = _text(source.get("questionRpcId") or rpc_id)
                if resolved_id:
                    self._pending_interactions.pop(resolved_id, None)

    def _receive_event(self, payload: dict[str, Any]) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(self.normalize_event(payload))
        except Exception as error:
            if self.logger:
                self.logger.warning("dsh event sink failed error_type=%s", type(error).__name__)

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise AgentRuntimeError("DSH runtime is disabled")
        request_id = str(uuid4())
        body = {"type": "client-request", "rpcId": request_id, "method": method, "payload": payload}
        result = self._post(f"/api/{method}", body)
        if isinstance(result, dict) and result.get("type") == "server-response":
            result = result.get("result") or {}
        if isinstance(result, dict) and "result" in result and set(result).issubset({"result", "rpcId", "id", "jsonrpc"}):
            result = result.get("result") or {}
        if isinstance(result, dict) and result.get("ok") is False:
            raise AgentRuntimeError(str(result.get("error") or "DSH request failed"))
        if isinstance(result, dict) and result.get("ok") is True and "value" in result:
            result = result.get("value")
        return result if isinstance(result, dict) else {"value": result}

    def _get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.config.endpoint}{path}", method="GET")
        return self._request(request)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.endpoint}{path}",
            data=raw,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return self._request(request)

    def _request(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if self.logger:
                self.logger.info(
                    "dsh request http_error endpoint=%s status=%s",
                    self.config.endpoint,
                    error.code,
                )
            raise AgentRuntimeError(
                f"DSH endpoint returned HTTP {error.code}",
                http_status=error.code,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            if self.logger:
                self.logger.info("dsh request unavailable endpoint=%s error_type=%s", self.config.endpoint, type(error).__name__)
            raise AgentRuntimeError(
                f"DSH runtime unavailable at {self.config.endpoint}",
                transport=True,
            ) from error
        if not isinstance(value, dict):
            raise AgentRuntimeError("DSH returned a non-object response")
        if "error" in value and value.get("error"):
            raise AgentRuntimeError("DSH request returned an error")
        return value


def _find_settings_namespace(value: dict[str, Any], namespace: str) -> dict[str, Any]:
    namespaces = value.get("namespaces") if isinstance(value, dict) else None
    if not isinstance(namespaces, list):
        raise AgentRuntimeError("DSH settings response did not contain namespaces")
    for item in namespaces:
        if isinstance(item, dict) and item.get("ns") == namespace:
            return item
    raise AgentRuntimeError(f'DSH settings namespace "{namespace}" is not registered')


def _dsh_route_from_sumika_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise AgentRuntimeError("Provider profile must be an object")
    profile_id = str(profile.get("id") or "").strip()
    name = str(profile.get("name") or profile_id).strip()
    config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
    base_url = str(config.get("active_base_url") or "").strip().rstrip("/")
    model = str(config.get("model") or "").strip()
    if not profile_id or not base_url or not model:
        raise AgentRuntimeError("Provider profile is incomplete; test a Base URL and model first")
    route_id = _dsh_route_id(profile_id)
    raw_headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
    headers = {str(key): str(value) for key, value in raw_headers.items() if str(key).strip() and value is not None}
    secrets_value = profile.get("secrets") if isinstance(profile.get("secrets"), dict) else {}
    unsupported_secret_headers = sorted(
        key for key in secrets_value if str(key).startswith("header:")
    )
    if unsupported_secret_headers:
        raise AgentRuntimeError(
            "DSH 桥接暂不支持自定义敏感请求头；请改用 API Key 字段或在 DSH 中单独配置"
        )
    api_key = secrets_value.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise AgentRuntimeError("Provider API Key must be a string")
    local_endpoint = _is_local_provider(profile, base_url)
    credential_ref = _dsh_credential_ref(route_id) if api_key or local_endpoint else None
    credential_mode = "profile" if api_key else ("local-placeholder" if local_endpoint else None)
    credential_value = api_key if api_key else (_LOCAL_CREDENTIAL_SENTINEL if local_endpoint else None)
    route: dict[str, Any] = {
        "displayName": name,
        "api": "openai-completions",
        "baseURL": base_url,
        "models": [
            {
                "id": model,
                "name": model,
                "contextWindow": 262144,
                "maxTokens": 32768,
                "input": ["text"],
                "reasoningEfforts": False,
            }
        ],
        "defaultContextWindow": 262144,
        "defaultMaxTokens": 32768,
        "defaultInput": ["text"],
        "headers": headers,
    }
    if credential_ref:
        route["apiKeyEnv"] = credential_ref
    return {
        "profile_id": profile_id,
        "route_id": route_id,
        "model": model,
        "route": route,
        "credential_ref": credential_ref,
        "secret_value": credential_value,
        "credential_mode": credential_mode,
    }


def _is_local_provider(profile: dict[str, Any], base_url: str) -> bool:
    """Return whether a profile explicitly targets a local, no-auth service."""

    location = str(
        profile.get("resolved_processing_location")
        or profile.get("processing_location")
        or ""
    ).strip().lower()
    if location == "local":
        return True
    try:
        hostname = (urlparse(base_url).hostname or "").lower()
    except ValueError:
        return False
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _dsh_route_id(profile_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", profile_id.lower()).strip("-")
    if not slug:
        slug = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:12]
    # Keep the route readable while making collisions from punctuation or
    # truncation impossible for two profile ids.
    digest = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:10]
    return f"sumika-{slug[:48]}-{digest}"


def _dsh_credential_ref(route_id: str) -> str:
    digest = hashlib.sha256(route_id.encode("utf-8")).hexdigest()[:16].upper()
    return f"SUMIKA_{digest}_API_KEY"


def _dsh_route_matches(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    if current.get("displayName") != desired.get("displayName"):
        return False
    if current.get("api") != desired.get("api") or current.get("baseURL") != desired.get("baseURL"):
        return False
    if current.get("apiKeyEnv") != desired.get("apiKeyEnv"):
        return False
    if current.get("headers") != desired.get("headers"):
        return False
    current_models = current.get("models")
    desired_models = desired.get("models")
    if not isinstance(current_models, list) or not isinstance(desired_models, list) or len(current_models) != len(desired_models):
        return False
    for current_model, desired_model in zip(current_models, desired_models):
        if not isinstance(current_model, dict) or not isinstance(desired_model, dict):
            return False
        for key in ("id", "name", "contextWindow", "maxTokens", "input", "reasoningEfforts"):
            if current_model.get(key) != desired_model.get(key):
                return False
    return True


def _compact_agent_presets(value: Any) -> dict[str, Any]:
    """Whitelist the preset roster; preset paths and compositions stay in DSH."""

    if isinstance(value, dict):
        raw = value.get("presets")
        if not isinstance(raw, list) and isinstance(value.get("value"), list):
            raw = value["value"]
        authorable = bool(value.get("authorable"))
        has_document = bool(value.get("hasDocument") or value.get("has_document"))
    elif isinstance(value, list):
        raw = value
        authorable = False
        has_document = False
    else:
        raw = []
        authorable = False
        has_document = False
    presets: list[dict[str, Any]] = []
    for item in raw[:128] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            preset_id = _agent_preset_id(item.get("id") or item.get("agentPreset"))
        except AgentRuntimeError:
            continue
        trust = str(item.get("trust") or "unknown").strip().lower()
        if trust not in {"system", "user"}:
            trust = "unknown"
        row: dict[str, Any] = {
            "id": preset_id,
            "trust": trust,
            "is_default": bool(item.get("isDefault") or item.get("is_default")),
        }
        for source, target, limit in (("name", "name", 240), ("description", "description", 600), ("broken", "broken", 600)):
            text = _safe_agent_text(item.get(source), limit)
            if text:
                row[target] = text
        presets.append(row)
    return {"presets": presets, "authorable": authorable, "has_document": has_document}


def _compact_subagent_catalog(value: Any) -> dict[str, Any]:
    """Keep only the stable direct-child fields defined by DSH."""

    if not isinstance(value, dict):
        return {"entries": [], "parent_available": False}
    raw = value.get("entries")
    if not isinstance(raw, list) and isinstance(value.get("value"), list):
        raw = value["value"]
    entries: list[dict[str, Any]] = []
    for item in raw[:128] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "child").strip().lower()
        child_id = _safe_agent_text(item.get("id") or item.get("sessionId"), 160)
        if not child_id:
            continue
        if kind != "child":
            reason = str(item.get("reason") or "unavailable").strip().lower()
            if reason not in {"corrupt", "unsupported", "unavailable"}:
                reason = "unavailable"
            entries.append({"kind": "diagnostic", "id": child_id, "reason": reason})
            continue
        mode = str(item.get("mode") or "one-shot").strip().lower()
        if mode not in {"one-shot", "continuable"}:
            mode = "one-shot"
        row: dict[str, Any] = {
            "kind": "child",
            "id": child_id,
            "mode": mode,
            "activity": "running" if str(item.get("activity") or "inactive").lower() == "running" else "inactive",
            "has_children": bool(item.get("hasChildren") or item.get("has_children")),
        }
        label = _safe_agent_text(item.get("label"), 240)
        # DSH requires labels for continuable children; keep a safe fallback
        # for malformed host responses so the row remains inspectable.
        if label:
            row["label"] = label
        entries.append(row)
    return {
        "entries": entries,
        "parent_available": bool(value.get("parentAvailable") or value.get("parent_available")),
    }


def _subagent_address_payload(params: dict[str, Any], *, require_continuable: bool = False) -> dict[str, Any]:
    parent = _safe_agent_text(params.get("parentSessionId") or params.get("parent_session_id"), 160)
    child = _safe_agent_text(params.get("childSessionId") or params.get("child_session_id"), 160)
    mode = str(params.get("mode") or "").strip().lower()
    if not parent or not child:
        raise AgentRuntimeError("subagent parentSessionId and childSessionId are required")
    if mode not in {"one-shot", "continuable"}:
        raise AgentRuntimeError("subagent mode must be one-shot or continuable")
    if require_continuable and mode != "continuable":
        raise AgentRuntimeError("only continuable subagents accept this operation")
    return {"parentSessionId": parent, "childSessionId": child, "mode": mode}


def _safe_text_content(content: Any, text: Any = None) -> list[dict[str, str]]:
    if content is None:
        value = _safe_agent_text(text, 12000)
        if not value:
            raise AgentRuntimeError("subagent prompt requires non-empty text content")
        return [{"type": "text", "text": value}]
    if isinstance(content, str):
        value = _safe_agent_text(content, 12000)
        if not value:
            raise AgentRuntimeError("subagent prompt requires non-empty text content")
        return [{"type": "text", "text": value}]
    if not isinstance(content, list) or not content:
        raise AgentRuntimeError("subagent prompt content must be a non-empty list")
    result: list[dict[str, str]] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            raise AgentRuntimeError("subagent prompt currently accepts text content only")
        value = _safe_agent_text(block.get("text"), 12000)
        if value:
            result.append({"type": "text", "text": value})
    if not result:
        raise AgentRuntimeError("subagent prompt requires non-empty text content")
    return result


def _goal_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentRuntimeError("goal ref is required")
    goal_id = _safe_agent_text(value.get("id"), 160)
    revision = value.get("revision")
    if not goal_id or isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise AgentRuntimeError("goal ref requires an id and non-negative revision")
    return {"id": goal_id, "revision": revision}


def _add_goal_round_cap(payload: dict[str, Any], params: dict[str, Any]) -> None:
    value = params.get("maxGoalRounds") if params.get("maxGoalRounds") is not None else params.get("max_goal_rounds")
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1000:
        raise AgentRuntimeError("maxGoalRounds must be an integer from 1 to 1000")
    payload["maxGoalRounds"] = value


def _compact_goal(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    candidate = value.get("current") if isinstance(value.get("current"), dict) else value
    if not isinstance(candidate, dict):
        return None
    result: dict[str, Any] = {}
    raw_ref = candidate.get("ref") if isinstance(candidate.get("ref"), dict) else candidate
    try:
        result["ref"] = _goal_ref(raw_ref)
    except AgentRuntimeError:
        pass
    objective = _safe_agent_text(candidate.get("objective") or candidate.get("text"), 1200)
    if objective:
        result["objective"] = objective
    phase = _safe_agent_text(candidate.get("phase") or candidate.get("status") or candidate.get("state"), 60)
    if phase:
        result["phase"] = phase
    rounds = candidate.get("maxGoalRounds") if candidate.get("maxGoalRounds") is not None else candidate.get("max_goal_rounds")
    if isinstance(rounds, int) and not isinstance(rounds, bool) and 1 <= rounds <= 1000:
        result["max_goal_rounds"] = rounds
    if not result:
        return None
    return result


_IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_SESSION_ID_LENGTH = 240
_MAX_SESSION_QUERY_LENGTH = 512
_MAX_SESSION_TITLE_LENGTH = 240
_MAX_ATTACHMENT_ID_LENGTH = 240
_MAX_AGENT_PRESET_ID_LENGTH = 160
_MAX_AGENT_PRESET_NAME_LENGTH = 240
_MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
_MAX_PROMPT_BLOCKS = 16
_MAX_PROMPT_TEXT_LENGTH = 12000
_MAX_PROMPT_TOTAL_TEXT_LENGTH = 48000
_BASE64_RE = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")
_AGENT_PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _opaque_id(value: Any, field: str, limit: int) -> str:
    if value is None or not isinstance(value, (str, int)) or isinstance(value, bool):
        raise AgentRuntimeError(f"DSH {field} is required")
    text = str(value).strip()
    if not text:
        raise AgentRuntimeError(f"DSH {field} is required")
    if len(text) > limit:
        raise AgentRuntimeError(f"DSH {field} is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise AgentRuntimeError(f"DSH {field} contains control characters")
    return text


def _session_id(params: dict[str, Any]) -> str:
    value = (
        params.get("sessionId")
        or params.get("session_id")
        or params.get("parentSessionId")
        or params.get("parent_session_id")
        or params.get("id")
    )
    return _opaque_id(value, "sessionId", _MAX_SESSION_ID_LENGTH)


def _agent_preset_id(value: Any, field: str = "agentPreset") -> str:
    """Accept only DSH preset slugs, never paths or arbitrary filenames.

    DSH resolves the id against its own preset roots.  Keeping the wire value
    to a small slug grammar prevents a caller from smuggling a local path or
    an absolute Windows filename through the copy/open APIs.
    """

    if not isinstance(value, str):
        raise AgentRuntimeError(f"DSH {field} is required")
    preset_id = value.strip()
    if (
        not preset_id
        or len(preset_id) > _MAX_AGENT_PRESET_ID_LENGTH
        or _AGENT_PRESET_ID_RE.fullmatch(preset_id) is None
    ):
        raise AgentRuntimeError(
            f"DSH {field} must be a lowercase preset id using letters, digits, and hyphens"
        )
    return preset_id


def _agent_preset_name(value: Any) -> str:
    """Validate an optional display name without accepting a filesystem path."""

    if value is None:
        return ""
    if not isinstance(value, str):
        raise AgentRuntimeError("DSH preset name must be text")
    name = value.strip()
    if not name:
        return ""
    if (
        len(name) > _MAX_AGENT_PRESET_NAME_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or any(separator in name for separator in ("/", "\\"))
        or ":" in name
    ):
        raise AgentRuntimeError(
            "DSH preset name must be at most 240 characters and must not be a path"
        )
    return name


def _session_search_query(params: dict[str, Any]) -> str:
    value = params.get("query") if isinstance(params, dict) else None
    if not isinstance(value, str):
        raise AgentRuntimeError("session search query is required")
    query = value.strip()
    if not query:
        raise AgentRuntimeError("session search query must not be empty")
    if len(query) > _MAX_SESSION_QUERY_LENGTH:
        raise AgentRuntimeError("session search query is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise AgentRuntimeError("session search query contains control characters")
    return query


def _session_title(value: Any) -> str:
    if not isinstance(value, str):
        raise AgentRuntimeError("session title is required")
    title = value.strip()
    if not title:
        raise AgentRuntimeError("session title must not be empty")
    if len(title) > _MAX_SESSION_TITLE_LENGTH:
        raise AgentRuntimeError("session title is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in title):
        raise AgentRuntimeError("session title contains control characters")
    return title


def _attachment_id(value: Any) -> str:
    return _opaque_id(value, "attachmentId", _MAX_ATTACHMENT_ID_LENGTH)


def _valid_base64_payload(value: str, *, max_bytes: int) -> bool:
    if not value or len(value) > ((max_bytes + 2) // 3) * 4:
        return False
    if len(value) % 4 or not _BASE64_RE.fullmatch(value):
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error):
        return False
    return len(decoded) <= max_bytes


def _prompt_content(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise AgentRuntimeError("Agent prompt content must be a non-empty list")
    if len(value) > _MAX_PROMPT_BLOCKS:
        raise AgentRuntimeError(f"Agent prompt supports at most {_MAX_PROMPT_BLOCKS} content blocks")
    result: list[dict[str, Any]] = []
    text_size = 0
    for block in value:
        if not isinstance(block, dict):
            raise AgentRuntimeError("Agent prompt content must contain objects")
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str) or not text.strip():
                raise AgentRuntimeError("Agent prompt text blocks must not be empty")
            if len(text) > _MAX_PROMPT_TEXT_LENGTH:
                raise AgentRuntimeError("Agent prompt text block is too long")
            if any(ord(char) < 9 or (13 < ord(char) < 32) for char in text):
                raise AgentRuntimeError("Agent prompt text contains control characters")
            text_size += len(text)
            if text_size > _MAX_PROMPT_TOTAL_TEXT_LENGTH:
                raise AgentRuntimeError("Agent prompt text is too long")
            result.append({"type": "text", "text": text})
            continue
        if block_type == "image":
            media_type = block.get("mediaType") or block.get("media_type")
            data = block.get("data")
            if media_type not in _IMAGE_MEDIA_TYPES or not isinstance(data, str):
                raise AgentRuntimeError("Agent prompt image blocks require a supported mediaType and base64 data")
            if not _valid_base64_payload(data, max_bytes=_MAX_ATTACHMENT_BYTES):
                raise AgentRuntimeError("Agent prompt image data is invalid or oversized")
            image: dict[str, Any] = {"type": "image", "mediaType": media_type, "data": data}
            name = block.get("name")
            if name is not None:
                if not isinstance(name, str) or len(name) > 240 or any(ord(char) < 32 or ord(char) == 127 for char in name):
                    raise AgentRuntimeError("Agent prompt image name is invalid")
                if name.strip():
                    image["name"] = name.strip()
            result.append(image)
            continue
        raise AgentRuntimeError(f"Agent prompt content type is unsupported: {block_type}")
    return result


def _compact_session_search(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentRuntimeError("DSH session.search returned an invalid response")
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        raise AgentRuntimeError("DSH session.search response did not contain items")
    items: list[dict[str, str]] = []
    for item in raw_items[:20]:
        if not isinstance(item, dict):
            continue
        try:
            session_id = _opaque_id(item.get("sessionId") or item.get("id"), "sessionId", _MAX_SESSION_ID_LENGTH)
        except AgentRuntimeError:
            continue
        snippet = _safe_agent_text(item.get("snippet"), 240)
        items.append({"session_id": session_id, "snippet": snippet})
    return {"items": items, "has_more": bool(value.get("hasMore") or value.get("has_more"))}


def _compact_attachment_reference(value: Any, *, expected_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentRuntimeError("DSH attachment response did not contain a reference")
    actual_id = _opaque_id(value.get("attachmentId") or value.get("id"), "attachmentId", _MAX_ATTACHMENT_ID_LENGTH)
    if actual_id != expected_id:
        raise AgentRuntimeError("DSH attachment reference does not match the request")
    media_type = value.get("mediaType") or value.get("media_type")
    if media_type not in _IMAGE_MEDIA_TYPES:
        raise AgentRuntimeError("DSH attachment reference has an unsupported media type")
    reference: dict[str, Any] = {
        "attachment_id": actual_id,
        "media_type": media_type,
    }
    for source, target in (("bytes", "bytes"), ("width", "width"), ("height", "height")):
        number = value.get(source)
        if isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= 100_000_000:
            reference[target] = number
    name = value.get("name")
    if isinstance(name, str) and name.strip() and len(name) <= 240 and not any(ord(char) < 32 or ord(char) == 127 for char in name):
        reference["name"] = name.strip()
    return reference


def _session_create_payload(params: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("workspaceId", "sessionId", "agentPreset"):
        if params.get(key) is not None:
            payload[key] = str(params[key])
    if params.get("workspace_id") is not None:
        payload["workspaceId"] = str(params["workspace_id"])
    if params.get("session_id") is not None:
        payload["sessionId"] = str(params["session_id"])
    if params.get("agent_preset") is not None:
        payload["agentPreset"] = str(params["agent_preset"])
    if params.get("cwd") is not None:
        payload["cwd"] = str(params["cwd"])
    return payload


_SECRET_TEXT_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|(?:api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+)"
)


def _safe_agent_text(value: Any, limit: int = 800) -> str:
    """Keep user-visible summaries bounded and free of obvious credentials."""

    text = str(value or "").strip()
    if not text:
        return ""
    text = _SECRET_TEXT_RE.sub("[redacted]", text)
    if len(text) > limit:
        return f"{text[: max(1, limit - 1)]}…"
    return text


def _diagnostic_session_ids(value: Any) -> list[str]:
    """Extract bounded session ids for session-scoped read-only probes."""

    items = value.get("items") if isinstance(value, dict) else None
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items[:32]:
        if not isinstance(item, dict):
            continue
        session_id = _safe_agent_text(item.get("sessionId") or item.get("id"), 160)
        if session_id:
            result.append(session_id)
    return result


def _diagnostic_entry_count(value: Any) -> int:
    """Count common catalog list shapes without returning catalog contents."""

    if isinstance(value, list):
        return min(len(value), 256)
    if not isinstance(value, dict):
        return 0
    for key in ("servers", "items", "entries", "presets", "value"):
        entries = value.get(key)
        if isinstance(entries, list):
            return min(len(entries), 256)
    return 0


_MCP_PUBLIC_TOOL_RE = re.compile(r"^mcp__([A-Za-z0-9_-]{1,32})__([A-Za-z0-9_-]{1,64})$")


def _mcp_inventory_from_tools(value: Any) -> dict[str, Any]:
    """Group bounded public MCP tool names without exposing call payloads."""

    servers: dict[str, dict[str, dict[str, Any]]] = {}
    for item in value[:256] if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        public_name = _safe_agent_text(item.get("name"), 120)
        if len(public_name) > 64:
            continue
        match = _MCP_PUBLIC_TOOL_RE.fullmatch(public_name)
        if match is None:
            continue
        server_name, tool_name = match.groups()
        sequence = item.get("completed_seq") if isinstance(item.get("completed_seq"), int) else item.get("seq")
        sequence = sequence if isinstance(sequence, int) and sequence >= 0 else 0
        tool = {
            "name": public_name,
            "tool_name": tool_name,
            "status": _safe_agent_text(item.get("status") or "observed", 40),
            "last_seq": sequence,
        }
        previous = servers.setdefault(server_name, {}).get(public_name)
        if previous is None or sequence >= previous["last_seq"]:
            servers[server_name][public_name] = tool

    entries: list[dict[str, Any]] = []
    for server_name in sorted(servers, key=str.casefold):
        tools = sorted(servers[server_name].values(), key=lambda item: str(item["name"]).casefold())
        entries.append(
            {
                "id": server_name,
                "name": server_name,
                "tool_count": len(tools),
                "tools": tools,
            }
        )
    return {
        "entries": entries,
        "server_count": len(entries),
        "tool_count": sum(item["tool_count"] for item in entries),
    }


def _safe_event_extensions(payload: dict[str, Any], source: dict[str, Any], event_type: str) -> dict[str, Any]:
    """Keep only bounded presentation metadata on the persistent Sumika event bus."""

    result: dict[str, Any] = {}
    rpc_id = _safe_agent_text(payload.get("rpcId") or source.get("rpcId"), 160)
    session_id = _safe_agent_text(payload.get("sessionId") or source.get("sessionId"), 160)
    if rpc_id:
        result["rpcId"] = rpc_id
    if session_id:
        result["sessionId"] = session_id
    if event_type == "session/event":
        nested_type = _safe_agent_text(source.get("type") or "agent/event", 120)
        result["event"] = {"type": nested_type}
        data = source.get("data") if isinstance(source.get("data"), dict) else {}
        if nested_type in {"tool/call", "tool/result"}:
            tool = {
                "name": _safe_agent_text(data.get("name") or "tool", 120),
                "call_id": _safe_agent_text(data.get("callId"), 160),
            }
            view = _compact_tool_event_view(payload.get("view"), expected="call" if nested_type == "tool/call" else "result")
            if view:
                tool["presentation"] = view
            result["tool"] = tool
        elif nested_type in {"turn/start", "turn/end"}:
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            result["turn"] = {
                "state": "running" if nested_type == "turn/start" else _safe_agent_text(reason.get("kind") or "completed", 60),
            }
        for key, item in payload.items():
            if key in {"type", "event", "view", "data", "content", "text", "sessionId", "rpcId"} or key in result:
                continue
            if any(token in str(key).lower() for token in ("token", "secret", "password", "apikey", "api_key", "authorization", "cookie", "argument", "result", "output")):
                continue
            safe_value = _safe_metadata_value(item)
            if safe_value is not None:
                result[str(key)] = safe_value
        return result
    if event_type == "session/queue":
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        placements = {"queued": 0, "steering": 0, "context": 0}
        for item in items:
            if isinstance(item, dict) and item.get("placement") in placements:
                placements[str(item["placement"])] += 1
        result["queue"] = {"count": len(items), "placements": placements}
        return result
    if event_type == "session/jobs":
        jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
        result["job_count"] = len(jobs)
        return result
    if event_type == "session/projection":
        result["projection"] = {
            "key": _safe_agent_text(payload.get("key"), 120),
            "seq": payload.get("seq") if isinstance(payload.get("seq"), int) else None,
        }
        return result
    if event_type.startswith("approval/"):
        for source_key, target_key, limit in (
            ("approvalId", "approvalId", 160),
            ("toolName", "toolName", 160),
            ("reason", "reason", 500),
            ("outcome", "outcome", 80),
        ):
            value = _safe_agent_text(source.get(source_key) or payload.get(source_key), limit)
            if value:
                result[target_key] = value
    elif event_type.startswith("question/"):
        questions = source.get("questions") if isinstance(source.get("questions"), list) else []
        result["question_count"] = len(questions)
        question_rpc_id = _safe_agent_text(source.get("questionRpcId"), 160)
        if question_rpc_id:
            result["questionRpcId"] = question_rpc_id
    return result


def _safe_metadata_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if isinstance(value, str):
        return _safe_agent_text(value, 500)
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [_safe_metadata_value(item, depth=depth + 1) for item in value[:16]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:24]:
            if any(token in str(key).lower() for token in ("token", "secret", "password", "apikey", "api_key", "authorization", "cookie", "argument", "result", "output")):
                continue
            safe_item = _safe_metadata_value(item, depth=depth + 1)
            if safe_item is not None:
                result[str(key)] = safe_item
        return result
    return None


def _compact_queue_items(items: list[Any]) -> dict[str, Any]:
    visible: list[dict[str, Any]] = []
    hidden_context_count = 0
    for raw in items[:128]:
        if not isinstance(raw, dict):
            continue
        placement = str(raw.get("placement") or "")
        if placement == "context":
            hidden_context_count += 1
            continue
        if placement not in {"queued", "steering"}:
            continue
        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        item_id = _safe_agent_text(raw.get("id") or message.get("id"), 160)
        if not item_id:
            continue
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        text_parts: list[str] = []
        attachment_count = 0
        unsupported_count = 0
        for block in blocks:
            if not isinstance(block, dict):
                unsupported_count += 1
            elif block.get("type") == "text":
                value = _safe_agent_text(block.get("text"), 12000)
                if value:
                    text_parts.append(value)
            elif block.get("type") == "image":
                attachment_count += 1
            else:
                unsupported_count += 1
        text = _safe_agent_text("\n".join(text_parts), 12000)
        visible.append(
            {
                "id": item_id,
                "placement": placement,
                "text": text,
                "attachment_count": attachment_count,
                "editable": bool(text) and attachment_count == 0 and unsupported_count == 0,
                "can_remove": True,
                "can_steer": placement == "queued",
            }
        )
    return {"items": visible, "hidden_context_count": hidden_context_count}


def _safe_locations(value: Any, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        path = _safe_agent_text(item.get("path"), 500)
        if not path:
            continue
        location: dict[str, Any] = {"path": path}
        if isinstance(item.get("line"), int) and item["line"] > 0:
            location["line"] = item["line"]
        result.append(location)
    return result


def _safe_url_origin(value: Any) -> str:
    text = _safe_agent_text(value, 1000)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return _safe_agent_text(text, 240)


def _compact_tool_event_view(value: Any, *, expected: str | None = None) -> dict[str, Any] | None:
    """Whitelist DSH host presentation fields without forwarding raw args/results."""

    if not isinstance(value, dict):
        return None
    phase = str(value.get("for") or "")
    view = value.get("view") if isinstance(value.get("view"), dict) else None
    if phase not in {"call", "result"} or view is None or (expected and phase != expected):
        return None
    card = str(view.get("card") or "")
    allowed_cards = {"generic", "terminal", "diff"} if phase == "call" else {"generic", "terminal", "diff", "search", "read", "web"}
    if card not in allowed_cards:
        return None
    result: dict[str, Any] = {"phase": phase, "card": card}
    title = _safe_agent_text(view.get("title"), 320)
    if title:
        result["title"] = title
    if phase == "call":
        kind = str(view.get("kind") or "")
        if kind in {"read", "edit", "delete", "move", "search", "execute", "fetch", "other"}:
            result["kind"] = kind
        locations = _safe_locations(view.get("locations"))
        if card == "diff":
            diffs = view.get("diffs") if isinstance(view.get("diffs"), list) else []
            locations = _safe_locations([{"path": item.get("path")} for item in diffs if isinstance(item, dict)]) or locations
            result["file_count"] = len(diffs)
        if locations:
            result["locations"] = locations
        if card == "terminal":
            description = _safe_agent_text(view.get("description"), 500)
            cwd = _safe_agent_text(view.get("cwd"), 500)
            if description:
                result["description"] = description
            if cwd:
                result["cwd"] = cwd
        return result
    if card == "terminal":
        output = _safe_agent_text(view.get("output"), 1600)
        if output:
            result["output"] = output
        if isinstance(view.get("exitCode"), int):
            result["exit_code"] = view["exitCode"]
        signal = _safe_agent_text(view.get("signal"), 80)
        if signal:
            result["signal"] = signal
    elif card == "diff":
        diffs = view.get("diffs") if isinstance(view.get("diffs"), list) else []
        result["file_count"] = len(diffs)
        locations = _safe_locations([{"path": item.get("path")} for item in diffs if isinstance(item, dict)])
        if locations:
            result["locations"] = locations
    elif card == "search":
        shape = str(view.get("shape") or "")
        if shape in {"matches", "paths"}:
            result["shape"] = shape
        result["truncated"] = bool(view.get("truncated"))
        if isinstance(view.get("total"), int) and view["total"] >= 0:
            result["total"] = view["total"]
        if shape == "paths":
            result["paths"] = [_safe_agent_text(path, 500) for path in (view.get("paths") if isinstance(view.get("paths"), list) else [])[:12] if _safe_agent_text(path, 500)]
        elif shape == "matches":
            files = view.get("files") if isinstance(view.get("files"), list) else []
            result["files"] = [
                {
                    "path": _safe_agent_text(item.get("path"), 500),
                    "match_count": len(item.get("matches")) if isinstance(item.get("matches"), list) else 0,
                }
                for item in files[:12]
                if isinstance(item, dict) and _safe_agent_text(item.get("path"), 500)
            ]
    elif card == "read":
        result["path"] = _safe_agent_text(view.get("path"), 500)
        for source_key, target_key in (("offset", "offset"), ("totalLines", "total_lines")):
            if isinstance(view.get(source_key), int) and view[source_key] >= 0:
                result[target_key] = view[source_key]
        result["line_count"] = len(view.get("lines")) if isinstance(view.get("lines"), list) else 0
        language = _safe_agent_text(view.get("lang"), 40)
        if language:
            result["language"] = language
    elif card == "web":
        kind = str(view.get("kind") or "")
        if kind in {"search", "fetch"}:
            result["kind"] = kind
        result["truncated"] = bool(view.get("truncated"))
        if kind == "fetch":
            result["origin"] = _safe_url_origin(view.get("url"))
            if isinstance(view.get("statusCode"), int):
                result["status_code"] = view["statusCode"]
        elif kind == "search":
            sources = view.get("sources") if isinstance(view.get("sources"), list) else []
            result["sources"] = [
                {
                    "origin": _safe_url_origin(item.get("url")),
                    "title": _safe_agent_text(item.get("title"), 240),
                }
                for item in sources[:8]
                if isinstance(item, dict) and _safe_url_origin(item.get("url"))
            ]
    return result


def _diff_artifact_from_view(
    view: dict[str, Any],
    *,
    call_id: str,
    status: str,
    sequence: int,
) -> dict[str, Any]:
    locations = _safe_locations(view.get("locations"))
    file_count = view.get("file_count")
    if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count < 0:
        file_count = len(locations)
    return {
        "type": "tool/diff",
        "label": _safe_agent_text(view.get("title") or "文件改动", 160),
        "status": status,
        "call_id": call_id,
        "file_count": file_count,
        "locations": locations,
        "seq": sequence,
    }


def _safe_numeric_map(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for key, item in value.items():
        if any(token in str(key).lower() for token in ("secret", "password", "apikey", "api_key", "authorization")):
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        result[str(key)] = item
    return result


def _compact_model_catalog(value: Any) -> dict[str, Any]:
    """Keep DSH model discovery advisory and bounded at the Core boundary."""

    if not isinstance(value, dict):
        return {
            "current": {},
            "routable": False,
            "groups": [],
            "failures": [],
        }
    current_value = value.get("current") if isinstance(value.get("current"), dict) else {}
    current = {
        "provider": _safe_agent_text(current_value.get("provider"), 160),
        "model": _safe_agent_text(current_value.get("model"), 240),
    }
    reasoning_effort = _safe_agent_text(current_value.get("reasoningEffort"), 120)
    if reasoning_effort:
        current["reasoning_effort"] = reasoning_effort
    groups: list[dict[str, Any]] = []
    raw_groups = value.get("groups") if isinstance(value.get("groups"), list) else []
    for raw_group in raw_groups[:32]:
        if not isinstance(raw_group, dict):
            continue
        group_id = _safe_agent_text(raw_group.get("id"), 160)
        if not group_id:
            continue
        group = {
            "id": group_id,
            "name": _safe_agent_text(raw_group.get("name") or group_id, 240),
            "models": [],
        }
        raw_models = raw_group.get("models") if isinstance(raw_group.get("models"), list) else []
        for raw_model in raw_models[:128]:
            if not isinstance(raw_model, dict):
                continue
            model_id = _safe_agent_text(raw_model.get("id"), 240)
            if not model_id:
                continue
            model = {
                "id": model_id,
                "name": _safe_agent_text(raw_model.get("name") or model_id, 240),
            }
            description = _safe_agent_text(raw_model.get("description"), 600)
            if description:
                model["description"] = description
            reasoning = raw_model.get("reasoning")
            if isinstance(reasoning, dict):
                efforts: list[dict[str, str]] = []
                for effort in (reasoning.get("efforts") if isinstance(reasoning.get("efforts"), list) else [])[:16]:
                    if not isinstance(effort, dict):
                        continue
                    effort_id = _safe_agent_text(effort.get("id"), 120)
                    effort_name = _safe_agent_text(effort.get("name") or effort_id, 180)
                    if effort_id and effort_name:
                        entry = {"id": effort_id, "name": effort_name}
                        detail = _safe_agent_text(effort.get("description"), 400)
                        if detail:
                            entry["description"] = detail
                        efforts.append(entry)
                if efforts:
                    model["reasoning"] = {"efforts": efforts}
                    default_effort = _safe_agent_text(reasoning.get("defaultEffort"), 120)
                    if default_effort:
                        model["reasoning"]["default_effort"] = default_effort
            group["models"].append(model)
        groups.append(group)
    failures: list[dict[str, str]] = []
    raw_failures = value.get("failures") if isinstance(value.get("failures"), list) else []
    for raw_failure in raw_failures[:32]:
        if not isinstance(raw_failure, dict):
            continue
        failure_id = _safe_agent_text(raw_failure.get("id"), 160)
        message = _safe_agent_text(raw_failure.get("message"), 600)
        if failure_id and message:
            failures.append(
                {
                    "id": failure_id,
                    "name": _safe_agent_text(raw_failure.get("name") or failure_id, 240),
                    "message": message,
                }
            )
    return {
        "current": current,
        "routable": bool(value.get("routable")),
        "groups": groups,
        "failures": failures,
    }


def _compact_workspace(value: Any) -> dict[str, Any] | None:
    """Project one DSH workspace registration without touching its files."""

    if not isinstance(value, dict):
        return None
    workspace_id = _safe_agent_text(value.get("workspaceId") or value.get("id"), 160)
    path = _safe_agent_text(value.get("path"), 4096)
    if not workspace_id or not path:
        return None
    session_ids = [
        _safe_agent_text(item, 160)
        for item in (value.get("sessionIds") if isinstance(value.get("sessionIds"), list) else [])[:256]
        if isinstance(item, str) and item.strip()
    ]
    return {
        "id": workspace_id,
        "path": path,
        "title": _safe_agent_text(value.get("title") or Path(path).name or path, 240),
        "session_ids": session_ids,
        "created_at": _safe_agent_text(value.get("createdAt"), 80),
        "updated_at": _safe_agent_text(value.get("updatedAt"), 80),
    }


def _safe_questions(value: Any) -> list[dict[str, Any]]:
    """Project DSH question items without exposing arbitrary prompt payloads."""

    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        question_id = _safe_agent_text(item.get("id"), 120)
        question = _safe_agent_text(item.get("question"), 800)
        if not question_id or not question:
            continue
        projected: dict[str, Any] = {"id": question_id, "question": question}
        for key, limit in (("header", 120), ("detail", 1200)):
            text = _safe_agent_text(item.get(key), limit)
            if text:
                projected[key] = text
        options = item.get("options")
        if isinstance(options, list):
            safe_options: list[dict[str, str]] = []
            for option in options[:32]:
                if not isinstance(option, dict):
                    continue
                label = _safe_agent_text(option.get("label"), 240)
                if not label:
                    continue
                entry = {"label": label}
                description = _safe_agent_text(option.get("description"), 500)
                if description:
                    entry["description"] = description
                safe_options.append(entry)
            if safe_options:
                projected["options"] = safe_options
        if item.get("multiSelect") is True:
            projected["multiSelect"] = True
        intent = item.get("intent")
        if isinstance(intent, dict) and intent.get("kind") == "plan-review":
            approve = _safe_agent_text(intent.get("approve"), 240)
            if approve:
                projected["intent"] = {"kind": "plan-review", "approve": approve}
        result.append(projected)
    return result


def _valid_question_answer(answer: dict[str, Any], questions: Any) -> bool:
    """Match DSH's question response rules before sending a client-response."""

    if not isinstance(questions, list) or not isinstance(answer.get("answers"), list):
        return False
    values = answer["answers"]
    if len(values) != len(questions):
        return False
    for item, question in zip(values, questions):
        if not isinstance(item, dict) or not isinstance(question, dict):
            return False
        if str(item.get("id") or "") != str(question.get("id") or ""):
            return False
        selected = item.get("selected")
        if not isinstance(selected, list) or not all(isinstance(value, str) for value in selected):
            return False
        if len(set(selected)) != len(selected):
            return False
        if question.get("multiSelect") is not True and len(selected) > 1:
            return False
        custom = item.get("custom")
        if custom is not None and (not isinstance(custom, str) or not custom.strip()):
            return False
        if question.get("multiSelect") is not True and custom is not None and selected:
            return False
        options = question.get("options") if isinstance(question.get("options"), list) else []
        labels = {str(option.get("label")) for option in options if isinstance(option, dict) and option.get("label") is not None}
        if any(value not in labels for value in selected):
            return False
    return True


def _compact_message(event: dict[str, Any], *, sequence: int) -> dict[str, Any] | None:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    message = data.get("message") if isinstance(data.get("message"), dict) else data
    role = str(message.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    # DSH emits an internal runtime-context user message.  It contains paths,
    # policy text, and tool definitions and is not part of the conversation.
    source = message.get("source") if isinstance(message.get("source"), dict) else {}
    if role == "user" and source.get("kind") not in {None, "user"}:
        return None
    blocks = message.get("content") if isinstance(message.get("content"), list) else []
    parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"text", "output_text"}:
            text = _safe_agent_text(block.get("text"), 1200)
            if text:
                parts.append(text)
            continue
        if block.get("type") == "image" and isinstance(block.get("attachment"), dict):
            reference = block["attachment"]
            try:
                attachment_id = _attachment_id(reference.get("attachmentId") or reference.get("id"))
                attachments.append(_compact_attachment_reference(reference, expected_id=attachment_id))
            except AgentRuntimeError:
                continue
    content = "\n".join(parts).strip()
    if not content and not attachments:
        return None
    return {
        "role": role,
        "content": content,
        "attachments": attachments,
        "seq": sequence,
        "turn": data.get("turn"),
        "step": data.get("step"),
    }


def _compact_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"active": False, "pending": False, "steps": []}
    result: dict[str, Any] = {
        "active": bool(value.get("active")),
        "pending": bool(value.get("pending")),
        "steps": [],
    }
    raw_steps = value.get("steps") or value.get("items") or value.get("plan")
    if isinstance(raw_steps, list):
        for index, item in enumerate(raw_steps[:32]):
            if isinstance(item, str):
                result["steps"].append({"id": str(index + 1), "title": _safe_agent_text(item, 240), "status": "unknown"})
            elif isinstance(item, dict):
                result["steps"].append(
                    {
                        "id": _safe_agent_text(item.get("id") or item.get("step") or index + 1, 80),
                        "title": _safe_agent_text(item.get("title") or item.get("description") or item.get("text") or "未命名步骤", 240),
                        "status": _safe_agent_text(item.get("status") or "unknown", 40),
                    }
                )
    return result


def _compact_session_history(session_id: str, history: dict[str, Any]) -> dict[str, Any]:
    """Project DSH history into a bounded, stable Sumika session snapshot."""

    if not isinstance(history, dict):
        history = {}
    projections = history.get("projections") if isinstance(history.get("projections"), dict) else {}
    values = projections.get("values") if isinstance(projections.get("values"), dict) else {}
    events = history.get("events") if isinstance(history.get("events"), list) else []
    messages: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    tools_by_call_id: dict[str, dict[str, Any]] = {}
    approvals: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    artifacts_by_call_id: dict[str, dict[str, Any]] = {}
    last_turn_state = "idle"

    for wrapper in events:
        if not isinstance(wrapper, dict):
            continue
        event = wrapper.get("event") if isinstance(wrapper.get("event"), dict) else wrapper
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "agent/event")
        sequence = event.get("seq")
        sequence = sequence if isinstance(sequence, int) else 0
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        tool_view = wrapper.get("view") if isinstance(wrapper.get("view"), dict) else None
        if event_type in {"user/message", "assistant/message"}:
            compact = _compact_message(event, sequence=sequence)
            if compact:
                messages.append(compact)
        if event_type == "tool/call":
            call_id = _safe_agent_text(data.get("callId"), 120)
            entry = {
                "name": _safe_agent_text(data.get("name") or "tool", 120),
                "call_id": call_id,
                "status": "running",
                "turn": data.get("turn"),
                "step": data.get("step"),
                "seq": sequence,
            }
            presentation = _compact_tool_event_view(tool_view, expected="call")
            if presentation:
                entry["call"] = presentation
                if presentation.get("card") == "diff":
                    artifact = _diff_artifact_from_view(
                        presentation,
                        call_id=call_id,
                        status="running",
                        sequence=sequence,
                    )
                    artifacts.append(artifact)
                    if call_id:
                        artifacts_by_call_id[call_id] = artifact
            tools.append(entry)
            if call_id:
                tools_by_call_id[call_id] = entry
        elif event_type == "tool/result":
            call_id = _safe_agent_text(data.get("callId"), 120)
            entry = tools_by_call_id.get(call_id) if call_id else None
            if entry is None:
                entry = {
                    "name": _safe_agent_text(data.get("name") or "tool", 120),
                    "call_id": call_id,
                    "turn": data.get("turn"),
                    "step": data.get("step"),
                }
                tools.append(entry)
                if call_id:
                    tools_by_call_id[call_id] = entry
            entry["status"] = "failed" if bool(data.get("isError")) else "completed"
            entry["completed_seq"] = sequence
            presentation = _compact_tool_event_view(tool_view, expected="result")
            if presentation:
                entry["result"] = presentation
                if presentation.get("card") == "diff":
                    artifact = artifacts_by_call_id.get(call_id) if call_id else None
                    if artifact is None:
                        artifact = _diff_artifact_from_view(
                            presentation,
                            call_id=call_id,
                            status=entry["status"],
                            sequence=sequence,
                        )
                        artifacts.append(artifact)
                        if call_id:
                            artifacts_by_call_id[call_id] = artifact
                    else:
                        artifact.update(
                            _diff_artifact_from_view(
                                presentation,
                                call_id=call_id,
                                status=entry["status"],
                                sequence=sequence,
                            )
                        )
        if event_type.startswith("approval/") or event_type.startswith("approval."):
            approvals.append(
                {
                    "id": _safe_agent_text(data.get("approvalId") or data.get("requestId") or data.get("id"), 120),
                    "action": _safe_agent_text(data.get("action") or data.get("name") or "需要确认", 160),
                    "status": "pending" if event_type.endswith("requested") or event_type.endswith("request") else "resolved",
                    "seq": sequence,
                }
            )
        if "artifact" in event_type or "diff" in event_type:
            artifacts.append(
                {
                    "type": event_type,
                    "label": _safe_agent_text(data.get("name") or data.get("title") or event_type, 160),
                    "status": _safe_agent_text(data.get("status") or "available", 40),
                    "seq": sequence,
                }
            )
        if event_type == "turn/start":
            last_turn_state = "running"
        elif event_type == "turn/end":
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            last_turn_state = _safe_agent_text(reason.get("kind") or "completed", 40) or "completed"
        if event_type not in {"assistant/chunk", "request/header", "request/context", "session/title-llm-request"}:
            timeline.append(
                {
                    "type": event_type,
                    "seq": sequence,
                    "turn": data.get("turn"),
                    "step": data.get("step"),
                    "status": _safe_agent_text(data.get("status") or "", 60),
                }
            )

    # Keep the latest view while preserving chronological order in the UI.
    messages = messages[-16:]
    timeline = timeline[-40:]
    tools = tools[-24:]
    approvals = approvals[-16:]
    artifacts = artifacts[-16:]
    stats = _safe_numeric_map(values.get("sessionStats"))
    context = _safe_numeric_map(values.get("contextPressure"))
    return {
        "session_id": session_id,
        "state": last_turn_state,
        "title": _safe_agent_text(values.get("title"), 180),
        "plan": _compact_plan(values.get("plan")),
        "goal": _compact_goal(values.get("goal")),
        "messages": messages,
        "timeline": timeline,
        "tools": tools,
        "approvals": approvals,
        "artifacts": artifacts,
        "stats": stats,
        "context": context,
        "has_more": bool(history.get("hasMore")),
        "event_count": len(events),
    }


def _plan_command_line(content: list[dict[str, Any]]) -> str:
    """Build a text-only `/plan` command for DSH's command plane.

    The current Sumika Agent composer sends text blocks.  Rejecting other
    blocks here is safer than silently dropping an attachment before the
    command bridge gains an image-admission mapping.
    """

    text_blocks = [
        str(item.get("text") or "").strip()
        for item in content
        if item.get("type") == "text" and str(item.get("text") or "").strip()
    ]
    if any(item.get("type") != "text" for item in content):
        raise AgentRuntimeError("DSH Plan command currently accepts text content only")
    text = "\n".join(text_blocks).strip()
    if text == "/plan" or text.startswith("/plan "):
        return text
    return f"/plan {text}" if text else "/plan"


def _read_http_headers(connection: socket.socket) -> bytes:
    buffer = bytearray()
    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(4096)
        if not chunk:
            raise AgentRuntimeError("DSH event WebSocket closed during handshake")
        buffer.extend(chunk)
        if len(buffer) > 64 * 1024:
            raise AgentRuntimeError("DSH event WebSocket handshake headers are too large")
    return bytes(buffer)


def _parse_headers(raw: bytes) -> dict[str, str]:
    lines = raw.decode("latin-1").split("\r\n")[1:]
    values: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        values[name.strip().lower()] = value.strip()
    return values


def _send_ws_frame(connection: socket.socket, opcode: int, payload: bytes) -> None:
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, 0x80 | length))
    elif length <= 0xFFFF:
        header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
    mask = secrets.token_bytes(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    connection.sendall(header + mask + masked)


def _read_ws_messages(
    connection: socket.socket,
    initial: bytes,
    stop_event: threading.Event,
    sink: Any,
) -> None:
    buffer = bytearray(initial)
    fragments = bytearray()
    fragmented_opcode: int | None = None

    def read_exact(size: int) -> bytes | None:
        while len(buffer) < size and not stop_event.is_set():
            try:
                chunk = connection.recv(max(4096, size - len(buffer)))
            except socket.timeout:
                continue
            if not chunk:
                return None
            buffer.extend(chunk)
        if len(buffer) < size:
            return None
        value = bytes(buffer[:size])
        del buffer[:size]
        return value

    while not stop_event.is_set():
        header = read_exact(2)
        if header is None:
            return
        first, second = header
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            extended = read_exact(2)
            if extended is None:
                return
            length = struct.unpack("!H", extended)[0]
        elif length == 127:
            extended = read_exact(8)
            if extended is None:
                return
            length = struct.unpack("!Q", extended)[0]
        if length > 16 * 1024 * 1024:
            raise AgentRuntimeError("DSH event WebSocket frame is too large")
        mask = read_exact(4) if masked else None
        payload = read_exact(length)
        if payload is None:
            return
        if mask is not None:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            return
        if opcode == 0x9:
            try:
                _send_ws_frame(connection, 0xA, payload)
            except OSError:
                return
            continue
        if opcode == 0xA:
            continue
        if opcode == 0x1:
            fragments = bytearray(payload)
            fragmented_opcode = opcode
        elif opcode == 0x0 and fragmented_opcode is not None:
            fragments.extend(payload)
        else:
            continue
        if fin and fragmented_opcode == 0x1:
            sink(bytes(fragments))
            fragments.clear()
            fragmented_opcode = None


def _text(value: Any) -> str | None:
    return str(value) if value is not None else None
