"""DeepSeek Harness adapter.

This module never imports or forks DSH.  It speaks the pinned Web API and
fails closed when the independently managed DSH runtime is not reachable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

from ....protocol.models import utc_now
from ...credential_binding import (
    LOCAL_DSH_CREDENTIAL_REF,
    LOCAL_DSH_CREDENTIAL_VALUE,
    dsh_remote_credential_ref,
    dsh_route_id,
)
from ...contracts import AgentCapability, AgentRuntime, AgentRuntimeError, UnavailableAgentRuntime
from ...models import AgentApproval, AgentEvent
from .config import DSHRuntimeConfig, default_profile_dir
from .mcp_config import ManagedMcpPresetStore


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

    runtime_id = "dsh"
    capability_ids = frozenset(
        capability
        for capability in AgentCapability
        if capability is not AgentCapability.READONLY
    )

    def __init__(self, data_dir: str | Path | None = None, *, env: dict[str, str] | None = None, logger: Any = None) -> None:
        env = env if env is not None else os.environ
        endpoint = str(env.get("SUMIKA_AGENT_ENDPOINT") or env.get("SUMIKA_DSH_ENDPOINT") or "http://127.0.0.1:3080").rstrip("/")
        configured_profile = env.get("SUMIKA_AGENT_PROFILE_DIR") or env.get("SUMIKA_DSH_PROFILE_DIR") or env.get("SUMIKA_DSH_HOME")
        profile_dir = configured_profile or default_profile_dir(data_dir)
        # A Core-only process must not discover the user's global DSH.  The
        # desktop launcher injects an explicitly validated executable; an
        # external runtime may still be addressed through its endpoint without
        # pretending that its package version was verified here.
        executable = env.get("SUMIKA_AGENT_EXECUTABLE") or env.get("SUMIKA_DSH_EXECUTABLE")
        version_verified = str(env.get("SUMIKA_DSH_VERSION_VERIFIED") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        enabled = str(env.get("SUMIKA_AGENT_ENABLED") or env.get("SUMIKA_DSH_ENABLED") or "1")
        self.config = DSHRuntimeConfig(
            endpoint=endpoint,
            profile_dir=profile_dir,
            executable=executable,
            version_verified=version_verified,
            managed=str(env.get("SUMIKA_AGENT_AUTOSTART") or env.get("SUMIKA_DSH_AUTOSTART") or "0").lower()
            in {"1", "true", "yes"},
            enabled=enabled.lower() not in {"0", "false", "no"},
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
        launch_credential_refs = _mcp_launch_credential_refs(
            env.get("SUMIKA_DSH_MCP_CREDENTIAL_REFS")
        )
        self._mcp_configurations = ManagedMcpPresetStore(
            self.config.profile_dir,
            logger=logger,
            launch_credential_refs=launch_credential_refs,
        )

    def bind_credential_store(self, credential_store: Any) -> None:
        self._mcp_configurations.bind_credential_store(credential_store)

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
            "version_source": "executable --version" if self.config.version_verified else "unverified external/Core-only",
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

        params = params if isinstance(params, dict) else {}
        requested_session_id = _diagnostic_session_id(params)
        checked_at = utc_now()
        profile_info = self._mcp_profile_info()
        report: dict[str, Any] = {
            "checked_at": checked_at,
            "runtime": {
                "state": "disabled" if not self.config.enabled else "unavailable",
                "ready": False,
                "endpoint": self.config.endpoint,
                "version": self.config.version,
                "version_verified": self.config.version_verified,
                "version_source": "executable --version" if self.config.version_verified else "unverified external/Core-only",
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
        # Session-scoped probes must never silently adopt an arbitrary historical
        # session.  A caller may opt in to one explicit session; otherwise the
        # report stays honest about the missing scope and avoids touching user
        # history just to populate a capability card.
        session_id = requested_session_id

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
            stats = _compact_session_stats(values.get("sessionStats"))
            token_usage = _compact_token_usage(values.get("tokenUsage"))
            context_breakdown = _compact_context_breakdown(values.get("contextBreakdown"))
            sessions.append(
                {
                    "id": _safe_agent_text(item.get("sessionId"), 120),
                    "title": _safe_agent_text(values.get("title") or "未命名 Agent 会话", 180),
                    "state": "running" if bool(item.get("running")) else "idle",
                    "blank": bool(item.get("blank")),
                    "updated_at": item.get("updatedAt"),
                    "agent_preset": _safe_agent_text(item.get("agentPreset"), 80),
                    "stats": stats,
                    "token_usage": token_usage,
                    "context_breakdown": context_breakdown,
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

    def validate_preset_mount(self, params: dict[str, Any]) -> dict[str, Any]:
        """Mount one preset in a blank session, then archive that session."""

        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        roster = self.list_presets({})
        entry = next(
            (
                item
                for item in roster.get("presets") or []
                if isinstance(item, dict) and item.get("id") == preset
            ),
            None,
        )
        if entry is None:
            raise AgentRuntimeError("DSH preset is not in the current runtime roster")
        if entry.get("broken"):
            raise AgentRuntimeError("DSH preset composition is marked as broken")

        payload: dict[str, Any] = {"agentPreset": preset}
        workspace_id = params.get("workspaceId") or params.get("workspace_id")
        cwd = params.get("cwd")
        if workspace_id is not None and cwd is not None:
            raise AgentRuntimeError("preset mount validation accepts workspaceId or cwd, not both")
        if workspace_id is not None:
            payload["workspaceId"] = _opaque_id(workspace_id, "workspaceId", 160)
        elif cwd is not None:
            if not isinstance(cwd, str) or not cwd.strip() or len(cwd.strip()) > 4096:
                raise AgentRuntimeError("DSH preset validation cwd must be a non-empty absolute path")
            candidate = Path(cwd.strip()).expanduser()
            if not candidate.is_absolute() or any(ord(char) < 32 or ord(char) == 127 for char in str(candidate)):
                raise AgentRuntimeError("DSH preset validation cwd must be a non-empty absolute path")
            payload["cwd"] = str(candidate)

        created = self._call("session.create", payload)
        session_id = _opaque_id(
            created.get("sessionId") if isinstance(created, dict) else None,
            "sessionId",
            _MAX_SESSION_ID_LENGTH,
        )
        try:
            archived = self._call("workspace.archiveSession", {"sessionId": session_id})
        except AgentRuntimeError as error:
            raise AgentRuntimeError(
                "DSH mounted the preset but could not archive the blank validation session"
            ) from error
        archived_ids = archived.get("archivedSessionIds") if isinstance(archived, dict) else None
        if not isinstance(archived_ids, list) or session_id not in archived_ids:
            raise AgentRuntimeError("DSH did not confirm validation session archival")
        return {
            "agent_preset": preset,
            "mountable": True,
            "validation_session_archived": True,
        }

    def list_mcp_configurations(self, params: dict[str, Any]) -> dict[str, Any]:
        """List only Sumika-managed rows in one user-owned preset."""

        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        self._require_user_preset(preset)
        profile = self._mcp_profile_info()
        result = self._mcp_configurations.list_configurations(preset)
        result.update(
            {
                "client_installed": profile["installed"],
                "client_version": profile["version"],
            }
        )
        return result

    def preview_mcp_configuration(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create an expiring, path-free preview for one managed MCP row."""

        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        self._require_user_preset(preset)
        profile = self._mcp_profile_info()
        if not profile["installed"]:
            raise AgentRuntimeError("managed DSH profile does not contain dsh-mcp-client")
        result = self._mcp_configurations.preview(preset, params)
        result.update(
            {
                "client_installed": True,
                "client_version": profile["version"],
            }
        )
        return result

    def apply_mcp_configuration(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply a preview, mount it in DSH, and roll back on failure."""

        preset = _agent_preset_id(
            params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
            "agentPreset",
        )
        token = params.get("previewToken") or params.get("preview_token")
        if not isinstance(token, str) or not token.strip() or len(token.strip()) > 256:
            raise AgentRuntimeError("MCP configuration previewToken is required")
        self._require_user_preset(preset)
        return self._mcp_configurations.apply(
            preset,
            token.strip(),
            lambda selected: self.validate_preset_mount({"agentPreset": selected}),
            credential_value=params.get("credentialValue") or params.get("credential_value"),
        )

    def _require_user_preset(self, preset: str) -> dict[str, Any]:
        roster = self.list_presets({})
        entry = next(
            (
                item
                for item in roster.get("presets") or []
                if isinstance(item, dict) and item.get("id") == preset
            ),
            None,
        )
        if entry is None:
            raise AgentRuntimeError("DSH preset is not in the current runtime roster")
        if entry.get("trust") != "user":
            raise AgentRuntimeError("managed MCP configuration requires a user-owned Agent preset")
        if entry.get("broken"):
            raise AgentRuntimeError("DSH preset composition is marked as broken")
        return entry

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
        routes remain untouched. Remote secrets must already be present in the
        Runtime launch environment and never cross the DSH write API.
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
        credential = self._provider_credential_status(desired, provision_local=True)
        if not credential["ready"]:
            raise AgentRuntimeError(str(credential["reason"]))

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

        try:
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

        except AgentRuntimeError as error:
            if changed:
                try:
                    self._restore_provider_route(route_id, previous, desired["route"])
                except AgentRuntimeError as rollback_error:
                    raise AgentRuntimeError(
                        f"{error}; DSH provider route rollback failed: {rollback_error}"
                    ) from error
            raise
        result = {
            "profile_id": desired["profile_id"],
            "route_id": route_id,
            "model": desired["model"],
            "changed": changed,
            "active": True,
            "credential_configured": bool(credential["configured"]),
            "credential_mode": credential["mode"],
            "credential_source": credential["source"],
            "credential_reload_required": False,
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

    def _provider_credential_status(
        self,
        desired: dict[str, Any],
        *,
        provision_local: bool,
    ) -> dict[str, Any]:
        credential_ref = desired.get("credential_ref")
        mode = desired.get("credential_mode")
        if not isinstance(credential_ref, str) or not credential_ref:
            return {
                "required": False,
                "ready": True,
                "configured": False,
                "mode": None,
                "source": "not-required",
                "reload_required": False,
                "reason": None,
            }

        def describe() -> dict[str, Any]:
            value = self._call("credentials.describe", {"refs": [credential_ref]})
            credentials = value.get("credentials") if isinstance(value, dict) else None
            info = credentials.get(credential_ref) if isinstance(credentials, dict) else None
            if not isinstance(info, dict):
                raise AgentRuntimeError("DSH credentials.describe omitted the requested reference")
            return info

        info = describe()
        configured = bool(info.get("configured"))
        if mode == "local-placeholder" and not configured and provision_local:
            self._call(
                "credentials.set",
                {"ref": credential_ref, "value": LOCAL_DSH_CREDENTIAL_VALUE},
            )
            info = describe()
            configured = bool(info.get("configured"))
        source = str(info.get("source") or "unconfigured")

        if mode == "launch-environment":
            ready = configured and source == "env" and info.get("writable") is False
            return {
                "required": True,
                "ready": ready,
                "configured": configured,
                "mode": mode,
                "source": source,
                "reload_required": not ready,
                "reason": None
                if ready
                else "远程 Provider 凭据尚未由 Windows 安全存储加载到 DSH；关闭外部 DSH 后重启 Sumika",
            }

        ready = configured and source in {"env", "file"}
        return {
            "required": True,
            "ready": ready,
            "configured": configured,
            "mode": mode,
            "source": source,
            "reload_required": False,
            "reason": None if ready else "本地 Provider 的非敏感运行时占位凭据尚未就绪，请重新同步",
        }

    def _restore_provider_route(
        self,
        route_id: str,
        previous: dict[str, Any] | None,
        expected_current: dict[str, Any],
    ) -> None:
        """Restore one route only if it still equals this sync attempt."""

        refreshed = self._call("settings.describe", {})
        descriptor = _find_settings_namespace(refreshed, "llm-pi-ai")
        value = descriptor.get("value") if isinstance(descriptor, dict) else {}
        providers = value.get("providers") if isinstance(value, dict) else {}
        current = providers.get(route_id) if isinstance(providers, dict) else None
        if not isinstance(current, dict) or not _dsh_route_matches(current, expected_current):
            raise AgentRuntimeError("provider route changed concurrently; refusing rollback overwrite")
        operation: dict[str, Any]
        if isinstance(previous, dict):
            operation = {"op": "set", "path": ["providers", route_id], "value": previous}
        else:
            operation = {"op": "unset", "path": ["providers", route_id]}
        payload: dict[str, Any] = {"ns": "llm-pi-ai", "ops": [operation]}
        revision = descriptor.get("revision")
        if isinstance(revision, int):
            payload["expectedRevision"] = revision
        self._call("settings.mutate", payload)

    def provider_status(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        if profile is None:
            return {"state": "unconfigured", "ready": False, "reason": "没有选择 Sumika Provider 档案"}
        try:
            desired = _dsh_route_from_sumika_profile(profile)
            credential = self._provider_credential_status(desired, provision_local=False)
            if not credential["ready"]:
                return {
                    "state": "restart-required" if credential["reload_required"] else "not-synced",
                    "ready": False,
                    "profile_id": desired["profile_id"],
                    "route_id": desired["route_id"],
                    "model": desired["model"],
                    "synced": False,
                    "active": False,
                    "credential_configured": bool(credential["configured"]),
                    "credential_mode": credential["mode"],
                    "credential_source": credential["source"],
                    "credential_reload_required": bool(credential["reload_required"]),
                    "reason": credential["reason"],
                }
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
                "credential_configured": bool(credential["configured"]),
                "credential_mode": credential["mode"],
                "credential_source": credential["source"],
                "credential_reload_required": False,
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

    def retry_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Replay the latest failed or cancelled text-only user target.

        DSH does not expose a stable ``session.retry`` RPC in the pinned Web
        API.  The adapter therefore reads a bounded history page, identifies
        the latest closed turn, and sends only its original text through the
        normal prompt path.  The target itself never crosses this method's
        return or logging boundary.
        """

        session_id = _session_id(params)
        history = self.history({"session_id": session_id, "maxMessages": 64})
        target = _retry_target_from_history(history)
        mode = target["mode"]
        requested_mode = str(params.get("mode") or "").strip().lower()
        if requested_mode in {"plan", "execute", "readonly"}:
            mode = requested_mode
        prompt_params: dict[str, Any] = {
            "session_id": session_id,
            "text": target["text"],
            "mode": mode,
        }
        transport_mode = str(params.get("transport_mode") or params.get("queue_mode") or "").strip().lower()
        if transport_mode in {"queue", "steer"}:
            prompt_params["transport_mode"] = transport_mode
        result = self.prompt(prompt_params)
        receipt: dict[str, Any] = {
            "accepted": result.get("accepted") is not False if isinstance(result, dict) else True,
            "session_id": session_id,
            "source_turn": target["turn"],
            "mode": mode,
            "text_length": target["text_length"],
        }
        if isinstance(result, dict):
            for key in ("id", "messageId", "message_id", "turnId", "turn_id"):
                value = result.get(key)
                if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                    receipt["id"] = _safe_agent_text(value, 160)
                    break
        if self.logger:
            self.logger.info(
                "dsh retry accepted session=%s source_turn=%s mode=%s text_length=%s",
                session_id,
                target["turn"],
                mode,
                target["text_length"],
            )
        return receipt

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
        raw_limit = params.get("maxMessages") if params.get("maxMessages") is not None else params.get("max_messages", 2)
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or not 1 <= raw_limit <= 64:
            raise AgentRuntimeError("snapshot maxMessages must be an integer from 1 to 64")
        history_params: dict[str, Any] = {
            "session_id": session_id,
            # DSH's maxMessages bounds message groups, not raw chunks.
            # Eight groups is enough for a routine page without replaying an
            # unbounded session history.
            "maxMessages": min(8, raw_limit),
        }
        before_seq = _history_before_seq(params)
        if before_seq is not None:
            history_params["beforeSeq"] = before_seq
        history = self.history(history_params)
        detailed = _compact_session_history(session_id, history)
        for key in (
            "messages",
            "timeline",
            "tools",
            "approvals",
            "artifacts",
            "turns",
            "has_more",
            "stats",
            "context",
            "token_usage",
            "context_breakdown",
        ):
            compact[key] = detailed.get(key, compact.get(key))
        compact["history_cursor"] = detailed.get("oldest_seq") if detailed.get("has_more") else None
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
        if requested_mode == "execute" and params.get("leave_plan") is True:
            # Wait for the command handler to settle before queueing the real
            # prompt. Only an explicit caller request exits Plan: ordinary
            # Execute must work for presets that do not mount the plan command.
            self._execute_command(session_id, "/plan off")
        return self._call("session.prompt", {"sessionId": session_id, "mode": mode, "content": content})

    def _execute_command(self, session_id: str, line: str) -> dict[str, Any]:
        """Execute one DSH slash command without routing it through the model."""

        result = self._call(
            "commands/execute",
            {"args": {"agentId": session_id, "line": line, "images": []}},
        )
        command_result = result.get("result")
        if isinstance(command_result, dict) and command_result.get("kind") == "error":
            message = str(
                command_result.get("text")
                or command_result.get("message")
                or "DSH command was rejected"
            )
            raise AgentRuntimeError(message)
        command_id = result.get("commandId") if isinstance(result, dict) else None
        if not isinstance(command_id, str) or not command_id:
            raise AgentRuntimeError(
                "DSH command bridge did not return a command id; the pinned runtime may not mount commands/execute"
            )
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

    def mcp_catalog(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge live, managed-configuration, and observed MCP evidence.

        The pinned DSH release normally does not expose ``mcp.list``.  A
        missing RPC is therefore represented as ``not-exposed`` rather than
        guessed as healthy.  Managed Preset rows and session-history tools are
        useful evidence, but each entry retains its source and freshness.
        """

        params = params or {}
        profile_info = self._mcp_profile_info()
        direct_probe, direct_value = self._probe_rpc("mcp.list", {})
        merged: dict[str, dict[str, Any]] = {}
        direct_entries = _mcp_catalog_entries_from_runtime(direct_value) if direct_probe["status"] == "available" else []
        for entry in direct_entries:
            _merge_mcp_catalog_entry(merged, entry)

        managed_count = 0
        managed_error = False
        try:
            roster = self.list_presets({})
            presets = [
                item
                for item in roster.get("presets") or []
                if isinstance(item, dict) and item.get("trust") == "user" and not item.get("broken")
            ]
            for preset_entry in presets[:32]:
                preset = preset_entry.get("id")
                if not isinstance(preset, str):
                    continue
                try:
                    configurations = self._mcp_configurations.list_configurations(preset).get("configurations") or []
                except AgentRuntimeError:
                    managed_error = True
                    continue
                for configuration in configurations[:64]:
                    if not isinstance(configuration, dict):
                        continue
                    server_name = configuration.get("server_name")
                    if not isinstance(server_name, str) or not _MCP_SERVER_NAME_RE.fullmatch(server_name):
                        continue
                    managed_count += 1
                    _merge_mcp_catalog_entry(
                        merged,
                        {
                            "id": server_name,
                            "name": server_name,
                            "source": "managed-config",
                            "freshness": "configuration",
                            "status": "configured",
                            "enabled": configuration.get("enabled") is True,
                            "transport": _safe_agent_text(configuration.get("transport"), 32),
                            "preset_ids": [preset],
                            "tools": [],
                        },
                    )
        except AgentRuntimeError:
            managed_error = True

        session_id = None
        if any(params.get(key) for key in ("sessionId", "session_id", "parentSessionId", "parent_session_id")):
            session_id = _session_id(params)
            try:
                history = self.history({"session_id": session_id, "maxMessages": 32})
                observed = _mcp_inventory_from_tools(_compact_session_history(session_id, history).get("tools"))
                for entry in _mcp_catalog_entries_from_inventory(observed):
                    _merge_mcp_catalog_entry(merged, entry)
            except AgentRuntimeError:
                managed_error = True

        entries = sorted(merged.values(), key=lambda item: str(item.get("name") or item.get("id") or "").casefold())
        for entry in entries:
            sources = entry.get("sources") if isinstance(entry.get("sources"), list) else []
            if "runtime" in sources:
                entry["status"] = "available"
                entry["freshness"] = "live" if len(sources) == 1 else "mixed"
            elif "managed-config" in sources:
                entry["status"] = "configured"
                entry["freshness"] = "configuration" if len(sources) == 1 else "mixed"
            else:
                entry["status"] = "observed"
                entry["freshness"] = "session-history"
            entry["source"] = "+".join(sources) if sources else "unknown"
            entry["tool_count"] = len(entry.get("tools") or [])
            entry["preset_ids"] = sorted(set(entry.get("preset_ids") or []), key=str.casefold)[:32]

        runtime_status = direct_probe["status"]
        if entries:
            status = "available" if runtime_status == "available" else (
                "configured" if managed_count else "observed"
            )
            reason = "目录由 Runtime、受管 Preset 和会话观察证据合并；各项状态不代表静默故障转移"
        else:
            status = runtime_status if runtime_status != "available" else "not-observed"
            reason = {
                "not-exposed": "固定版 DSH 未暴露独立 mcp.list，且当前没有已配置或已观察的 MCP 项",
                "unavailable": "DSH MCP 目录不可达，无法确认当前服务器状态",
                "rejected": "DSH 拒绝了 MCP 目录探测",
                "disabled": "DSH Runtime 已关闭",
            }.get(runtime_status, "当前会话尚未观察到 MCP 工具")
        if managed_error and entries:
            reason += "；部分受管 Preset 或历史未能读取"
        result = {
            "available": bool(entries) or runtime_status == "available",
            "status": status,
            "catalog_available": runtime_status == "available",
            "runtime_status": runtime_status,
            "observation_source": "merged",
            "client_installed": profile_info["installed"],
            "client_version": profile_info["version"],
            "entries": entries[:256],
            "server_count": len(entries),
            "tool_count": sum(len(item.get("tools") or []) for item in entries),
            "configured_count": managed_count,
            "session_id": session_id,
            "reason": reason,
        }
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
        if not _interaction_response_accepted(response):
            reason = response.get("reason") if isinstance(response, dict) else None
            raise AgentRuntimeError(f"DSH rejected the interaction response: {reason or 'unknown reason'}")
        with self._interaction_lock:
            self._pending_interactions.pop(rpc_id, None)
        return {"accepted": True, "kind": kind, "response": response}

    def cancel_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a pending DSH question using its standard error result.

        DSH treats a cancelled user-question as a settled wait, rather than as
        an empty answer.  Keeping this as a separate operation prevents a UI
        dismissal from accidentally selecting one of the model's options.
        """

        rpc_id = str(params.get("rpcId") or params.get("rpc_id") or "").strip()
        if not rpc_id:
            raise AgentRuntimeError("interaction cancellation requires rpcId")
        with self._interaction_lock:
            pending = dict(self._pending_interactions.get(rpc_id) or {})
        if not pending:
            raise AgentRuntimeError("interaction is no longer pending")
        if pending.get("kind") != "question":
            raise AgentRuntimeError("only question interactions can be cancelled")
        session_id = str(params.get("sessionId") or params.get("session_id") or "").strip()
        if session_id != pending.get("session_id"):
            raise AgentRuntimeError("interaction session does not match")
        response = self.respond(
            {
                "rpc_id": rpc_id,
                "result": {
                    "ok": False,
                    "error": {
                        "code": "cancelled",
                        "message": "the user closed this question request",
                        "details": {},
                    },
                },
            }
        )
        if not _interaction_response_accepted(response):
            reason = response.get("reason") if isinstance(response, dict) else None
            raise AgentRuntimeError(f"DSH rejected the interaction cancellation: {reason or 'unknown reason'}")
        with self._interaction_lock:
            self._pending_interactions.pop(rpc_id, None)
        return {"accepted": True, "kind": "question", "cancelled": True, "response": response}

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
        source_data = source.get("data") if isinstance(source.get("data"), dict) else {}
        event_type = str(payload.get("event_type") or payload.get("type") or payload.get("method") or "agent.event")
        status = str(payload.get("status") or source.get("type") or "unknown")
        content = None
        if event_type not in {"session/event", "session/queue", "session/jobs", "session/projection"}:
            content = source.get("content") or source.get("text")
        event = AgentEvent(
            event_type=event_type,
            session_id=_text(payload.get("session_id") or payload.get("sessionId") or source.get("sessionId") or source_data.get("sessionId")),
            turn_id=_text(payload.get("turn_id") or payload.get("turnId") or source.get("turnId") or source_data.get("turnId")),
            item_id=_text(payload.get("item_id") or payload.get("itemId") or source.get("itemId") or source_data.get("itemId")),
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
                    interaction = {
                        "id": rpc_id,
                        "kind": "question",
                        "session_id": session_id,
                        "questions": questions,
                        "created_at": str(source.get("timestamp") or utc_now()),
                    }
                    plan_review = _plan_review_metadata(questions)
                    if plan_review:
                        interaction["plan_review"] = plan_review
                    self._pending_interactions[rpc_id] = interaction
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
        # MCP discovery inherits a 60-second upstream timeout and runs while a
        # preset-backed session is created.  Other control-plane calls keep the
        # short default so an unavailable runtime still fails promptly.
        timeout = 65.0 if path == "/api/session.create" else 3.0
        return self._request(request, timeout=timeout)

    def _request(self, request: urllib.request.Request, *, timeout: float = 3.0) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
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
    route_id = dsh_route_id(profile_id)
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
    credential_ref = (
        dsh_remote_credential_ref(profile)
        if api_key
        else (LOCAL_DSH_CREDENTIAL_REF if local_endpoint else None)
    )
    credential_mode = "launch-environment" if api_key else ("local-placeholder" if local_endpoint else None)
    model_profile: dict[str, Any] = {
        "id": model,
        "name": model,
        "contextWindow": 262144,
        "maxTokens": 32768,
        "input": ["text"],
        "reasoningEfforts": False,
    }
    if _uses_ollama_qwen3_chat_template(profile, model):
        # Ollama enables Qwen 3 thinking by default. DSH's pi-ai adapter can
        # explicitly disable it only through Qwen's chat-template shape.
        model_profile.update(
            {
                "reasoningEfforts": {"off": None, "low": "low"},
                "compat": {"thinkingFormat": "qwen-chat-template"},
            }
        )
    route: dict[str, Any] = {
        "displayName": name,
        "api": "openai-completions",
        "baseURL": base_url,
        "models": [model_profile],
        "defaultContextWindow": 262144,
        "defaultMaxTokens": 32768,
        "defaultInput": ["text"],
        "headers": headers,
    }
    if _uses_ollama_qwen3_chat_template(profile, model):
        route["reasoning"] = "off"
    if credential_ref:
        route["apiKeyEnv"] = credential_ref
    return {
        "profile_id": profile_id,
        "route_id": route_id,
        "model": model,
        "route": route,
        "credential_ref": credential_ref,
        "credential_mode": credential_mode,
    }


def _uses_ollama_qwen3_chat_template(profile: dict[str, Any], model: str) -> bool:
    template_id = str(profile.get("template_id") or "").strip().lower()
    normalized_model = model.strip().lower()
    return template_id == "ollama" and bool(re.match(r"^qwen3(?:[:._-]|$)", normalized_model))


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
    return dsh_route_id(profile_id)


def _dsh_route_matches(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    if current.get("displayName") != desired.get("displayName"):
        return False
    if current.get("api") != desired.get("api") or current.get("baseURL") != desired.get("baseURL"):
        return False
    if current.get("apiKeyEnv") != desired.get("apiKeyEnv"):
        return False
    if current.get("headers") != desired.get("headers"):
        return False
    if current.get("reasoning") != desired.get("reasoning"):
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
        if _normalize_dsh_compat(current_model.get("compat")) != _normalize_dsh_compat(desired_model.get("compat")):
            return False
    return True


def _normalize_dsh_compat(value: Any) -> dict[str, Any] | None:
    """Ignore empty compatibility scaffolding written by DSH.

    The pinned runtime may materialize ``chatTemplateKwargs: {}`` (or an
    otherwise empty ``compat`` object) while persisting a route.  These values
    carry no behavior and should not make every provider sync look like a
    configuration change.  Non-empty compatibility options remain exact.
    """

    if not isinstance(value, dict):
        return None
    normalized = {
        str(key): item
        for key, item in value.items()
        if not (str(key) == "chatTemplateKwargs" and isinstance(item, dict) and not item)
    }
    return normalized or None


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
_MCP_LAUNCH_ENV_RE = re.compile(r"^SUMIKA_MCP_[A-F0-9]{24}_SECRET$")


def _mcp_launch_credential_refs(value: Any) -> set[str]:
    if value is None or value == "":
        return set()
    if not isinstance(value, str) or len(value) > 4096:
        return set()
    refs = {item.strip() for item in value.split(",") if item.strip()}
    if len(refs) > 32 or any(_MCP_LAUNCH_ENV_RE.fullmatch(item) is None for item in refs):
        return set()
    return refs


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


def _history_before_seq(params: dict[str, Any]) -> int | None:
    """Validate the DSH history page cursor without accepting coercions."""

    value = params.get("beforeSeq") if params.get("beforeSeq") is not None else params.get("before_seq")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentRuntimeError("history beforeSeq must be a non-negative integer")
    return value


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


def _diagnostic_session_id(params: dict[str, Any]) -> str | None:
    """Return a caller-selected session scope, without guessing from history."""

    value = params.get("sessionId") or params.get("session_id")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _opaque_id(value, "sessionId", _MAX_SESSION_ID_LENGTH)


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
_MCP_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


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


def _mcp_catalog_entries_from_inventory(value: dict[str, Any]) -> list[dict[str, Any]]:
    entries = value.get("entries") if isinstance(value, dict) else []
    result: list[dict[str, Any]] = []
    for item in entries[:256] if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        server_name = _safe_agent_text(item.get("name") or item.get("id"), 32)
        if _MCP_SERVER_NAME_RE.fullmatch(server_name) is None:
            continue
        tools: list[dict[str, Any]] = []
        for tool in item.get("tools", [])[:128] if isinstance(item.get("tools"), list) else []:
            if not isinstance(tool, dict):
                continue
            name = _safe_agent_text(tool.get("name") or tool.get("tool_name"), 128)
            if not name:
                continue
            tools.append(
                {
                    "name": name,
                    "tool_name": _safe_agent_text(tool.get("tool_name"), 96),
                    "status": _safe_agent_text(tool.get("status") or "observed", 32),
                    "last_seq": tool.get("last_seq") if isinstance(tool.get("last_seq"), int) else 0,
                }
            )
        result.append(
            {
                "id": server_name,
                "name": server_name,
                "source": "session-history",
                "freshness": "session-history",
                "status": "observed",
                "enabled": True,
                "preset_ids": [],
                "tools": tools,
            }
        )
    return result


def _mcp_catalog_entries_from_runtime(value: Any) -> list[dict[str, Any]]:
    """Normalize common mcp.list response shapes to safe server summaries."""

    if isinstance(value, list):
        raw_entries = value
    elif isinstance(value, dict):
        raw_entries = next(
            (value.get(key) for key in ("servers", "entries", "items", "value") if isinstance(value.get(key), list)),
        ) if any(isinstance(value.get(key), list) for key in ("servers", "entries", "items", "value")) else []
    else:
        raw_entries = []
    result: list[dict[str, Any]] = []
    for item in raw_entries[:256]:
        if not isinstance(item, dict):
            continue
        server_name = _safe_agent_text(item.get("name") or item.get("id") or item.get("serverName"), 32)
        if _MCP_SERVER_NAME_RE.fullmatch(server_name) is None:
            continue
        tools: list[dict[str, Any]] = []
        raw_tools = item.get("tools") if isinstance(item.get("tools"), list) else item.get("toolCatalog")
        for tool in raw_tools[:128] if isinstance(raw_tools, list) else []:
            if isinstance(tool, str):
                tool_name = _safe_agent_text(tool, 128)
                tool_status = "available"
            elif isinstance(tool, dict):
                tool_name = _safe_agent_text(tool.get("name") or tool.get("id"), 128)
                tool_status = _safe_agent_text(tool.get("status") or "available", 32)
            else:
                continue
            if not tool_name:
                continue
            tools.append({"name": tool_name, "tool_name": tool_name, "status": tool_status})
        result.append(
            {
                "id": server_name,
                "name": server_name,
                "source": "runtime",
                "freshness": "live",
                "status": "available",
                "enabled": item.get("enabled") is not False,
                "preset_ids": [],
                "tools": tools,
            }
        )
    return result


def _merge_mcp_catalog_entry(target: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> None:
    server_id = str(incoming.get("id") or incoming.get("name") or "").strip()
    if _MCP_SERVER_NAME_RE.fullmatch(server_id) is None:
        return
    current = target.setdefault(
        server_id,
        {
            "id": server_id,
            "name": _safe_agent_text(incoming.get("name") or server_id, 64),
            "sources": [],
            "freshness": "unknown",
            "status": "unknown",
            "enabled": False,
            "preset_ids": [],
            "tools": [],
        },
    )
    source = str(incoming.get("source") or "unknown")
    if source not in current["sources"]:
        current["sources"].append(source)
    if incoming.get("enabled") is True:
        current["enabled"] = True
    for preset in incoming.get("preset_ids") or []:
        if isinstance(preset, str) and preset not in current["preset_ids"]:
            current["preset_ids"].append(preset)
    existing_tools = {str(item.get("name")): item for item in current["tools"] if isinstance(item, dict)}
    for tool in incoming.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = _safe_agent_text(tool.get("name") or tool.get("tool_name"), 128)
        if name and name not in existing_tools:
            existing_tools[name] = {
                "name": name,
                "tool_name": _safe_agent_text(tool.get("tool_name"), 96),
                "status": _safe_agent_text(tool.get("status") or "observed", 32),
            }
    current["tools"] = list(existing_tools.values())[:128]
    transport = _safe_agent_text(incoming.get("transport"), 32)
    if transport and "transport" not in current:
        current["transport"] = transport


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
            call_id = _safe_agent_text(data.get("callId"), 160)
            is_error = False
            if nested_type == "tool/result":
                call_id, is_error = _tool_result_metadata(data)
            tool = {
                "name": _safe_agent_text(data.get("name") or "tool", 120),
                "call_id": call_id,
            }
            if nested_type == "tool/result":
                tool["status"] = "failed" if is_error else "completed"
            view = _compact_tool_event_view(payload.get("view"), expected="call" if nested_type == "tool/call" else "result")
            if view:
                tool["presentation"] = view
            result["tool"] = tool
        elif nested_type in {"turn/start", "turn/end"}:
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            result["turn"] = {
                "state": "running" if nested_type == "turn/start" else _safe_agent_text(reason.get("kind") or "completed", 60),
            }
            metrics = _safe_event_metrics(data)
            if metrics:
                result["metrics"] = metrics
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


def _safe_event_metrics(data: dict[str, Any]) -> dict[str, int | float]:
    """Extract numeric runtime counters only; never copy metric-bearing text."""

    aliases: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("duration_ms", ("durationMs", "duration_ms", "elapsedMs", "elapsed_ms")),
        ("queue_ms", ("queueMs", "queue_ms")),
        ("retry_count", ("retryCount", "retry_count", "retries")),
        ("input_units", ("inputTokens", "input_tokens", "uncachedInputTokens", "uncached_input_tokens")),
        ("output_units", ("outputTokens", "output_tokens", "decodeTokens", "decode_tokens")),
        ("cache_units", ("cacheReadTokens", "cache_read_tokens", "cachedInputTokens", "cached_input_tokens")),
        ("estimated_cost", ("estimatedCost", "estimated_cost", "cost")),
        ("approval_count", ("approvalCount", "approval_count")),
    )
    result: dict[str, int | float] = {}
    for output_key, candidates in aliases:
        for key in candidates:
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not math.isfinite(value) or value < 0 or value > 10**15:
                continue
            result[output_key] = int(value) if isinstance(value, int) or value.is_integer() else round(float(value), 6)
            break
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


def _tool_result_metadata(data: dict[str, Any]) -> tuple[str, bool]:
    """Read DSH's nested tool-result envelope without exposing its content."""

    call_id = _safe_agent_text(data.get("callId"), 160)
    is_error = bool(data.get("isError")) or isinstance(data.get("error"), dict)
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    source = message.get("source") if isinstance(message.get("source"), dict) else {}
    if not call_id:
        call_id = _safe_agent_text(source.get("callId"), 160)
    content = message.get("content") if isinstance(message.get("content"), list) else []
    for block in content[:16]:
        if not isinstance(block, dict) or block.get("type") != "tool-result":
            continue
        if not call_id:
            call_id = _safe_agent_text(block.get("toolCallId"), 160)
        if block.get("isError") is True:
            is_error = True
    return call_id, is_error


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
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or item < 0:
            continue
        result[str(key)] = item
    return result


def _non_negative_number(value: Any) -> int | float | None:
    """Return a finite, non-negative JSON number suitable for telemetry."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value) if isinstance(value, int) or value.is_integer() else float(value)


def _compact_known_numbers(value: Any, fields: tuple[tuple[str, tuple[str, ...]], ...]) -> dict[str, int | float]:
    """Copy only documented projection fields, accepting known wire aliases."""

    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for output_key, aliases in fields:
        for alias in aliases:
            number = _non_negative_number(value.get(alias))
            if number is not None:
                result[output_key] = number
                break
    return result


_TOKEN_USAGE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("uncachedInputTokens", ("uncachedInputTokens", "uncached_input_tokens", "inputTokens", "input_tokens")),
    ("outputTokens", ("outputTokens", "output_tokens")),
    ("cacheReadTokens", ("cacheReadTokens", "cache_read_tokens", "cachedInputTokens", "cached_input_tokens")),
    ("cacheWriteTokens", ("cacheWriteTokens", "cache_write_tokens")),
)
_CONTEXT_PRESSURE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("projectedTokens", ("projectedTokens", "projected_tokens", "usedTokens", "used_tokens")),
    ("pressureTokens", ("pressureTokens", "pressure_tokens")),
    ("contextWindow", ("contextWindow", "context_window", "maxContextTokens", "max_context_tokens")),
)
_CONTEXT_BREAKDOWN_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("systemTokens", ("systemTokens", "system_tokens")),
    ("toolsTokens", ("toolsTokens", "tools_tokens")),
    ("messageTokens", ("messageTokens", "message_tokens")),
)
_SESSION_STATS_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("turns", ("turns",)),
    ("steps", ("steps",)),
    ("llmMs", ("llmMs", "llm_ms")),
    ("toolMs", ("toolMs", "tool_ms")),
    ("ttftMs", ("ttftMs", "ttft_ms")),
    ("ttftSteps", ("ttftSteps", "ttft_steps")),
    ("decodeMs", ("decodeMs", "decode_ms")),
    ("decodeTokens", ("decodeTokens", "decode_tokens")),
    # Older DSH projections exposed completion usage on sessionStats rather
    # than the newer tokenUsage projection. Keep this documented field in the
    # stats view for compatibility while also exposing tokenUsage separately.
    ("outputTokens", ("outputTokens", "output_tokens")),
)


def _compact_token_usage(value: Any) -> dict[str, int | float]:
    return _compact_known_numbers(value, _TOKEN_USAGE_FIELDS)


def _compact_context_pressure(value: Any) -> dict[str, int | float]:
    return _compact_known_numbers(value, _CONTEXT_PRESSURE_FIELDS)


def _compact_context_breakdown(value: Any) -> dict[str, int | float]:
    return _compact_known_numbers(value, _CONTEXT_BREAKDOWN_FIELDS)


def _compact_session_stats(value: Any) -> dict[str, int | float]:
    return _compact_known_numbers(value, _SESSION_STATS_FIELDS)


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
        plan_intent = item.get("intent") if isinstance(item.get("intent"), dict) else {}
        is_plan_review = plan_intent.get("kind") == "plan-review"
        for key, limit in (("header", 120), ("detail", 24000 if is_plan_review else 1200)):
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


def _plan_review_metadata(questions: list[dict[str, Any]]) -> dict[str, str] | None:
    """Recognize only DSH's fixed plan-review question shape."""

    for question in questions:
        intent = question.get("intent")
        if not isinstance(intent, dict) or intent.get("kind") != "plan-review":
            continue
        approve = _safe_agent_text(intent.get("approve"), 240)
        options = question.get("options") if isinstance(question.get("options"), list) else []
        labels = {
            str(option.get("label"))
            for option in options
            if isinstance(option, dict) and isinstance(option.get("label"), str)
        }
        # DSH 0.1.1-rc.2 uses these exact labels.  Do not classify a future
        # or arbitrary question as a plan review based on intent alone.
        if approve and approve in labels and "Keep planning" in labels:
            return {"approve": approve, "keep_planning": "Keep planning"}
    return None


def _interaction_response_accepted(response: Any) -> bool:
    """Accept the bounded receipt shape across DSH HTTP wrappers."""

    if not isinstance(response, dict):
        return False
    if response.get("accepted") is True:
        return True
    for key in ("value", "result"):
        nested = response.get(key)
        if isinstance(nested, dict) and _interaction_response_accepted(nested):
            return True
    return False


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


_RETRYABLE_TURN_KINDS = frozenset(
    {"error", "failed", "failure", "cancelled", "canceled", "aborted", "interrupted", "stopped"}
)
_NON_RETRYABLE_TURN_KINDS = frozenset({"completed", "success", "succeeded", "max-tokens", "max_tokens"})


def _retry_target_from_history(history: Any) -> dict[str, Any]:
    """Find a replayable text target in the latest closed DSH turn.

    The helper deliberately works on the raw history page only inside the
    adapter.  It returns the text to the caller so it can be sent immediately,
    but callers must use the bounded receipt returned by ``retry_prompt`` and
    never persist this object in an audit event.
    """

    events = history.get("events") if isinstance(history, dict) else None
    if not isinstance(events, list) or not events:
        raise AgentRuntimeError("the latest Agent turn is not retryable: no history was returned")

    ordered: list[tuple[int, dict[str, Any]]] = []
    for index, wrapper in enumerate(events):
        if not isinstance(wrapper, dict):
            continue
        event = wrapper.get("event") if isinstance(wrapper.get("event"), dict) else wrapper
        if not isinstance(event, dict):
            continue
        sequence = event.get("seq")
        order = sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else index
        ordered.append((order, event))
    ordered.sort(key=lambda item: item[0])
    if not ordered:
        raise AgentRuntimeError("the latest Agent turn is not retryable: no valid history events")

    end_index = max(
        (index for index, (_, event) in enumerate(ordered) if event.get("type") == "turn/end"),
        default=-1,
    )
    if end_index < 0:
        if any(event.get("type") == "turn/start" for _, event in ordered):
            raise AgentRuntimeError("the latest Agent turn is still running")
        raise AgentRuntimeError("the latest Agent turn is not retryable: no terminal event")

    # A start after the selected terminal event means a newer open turn exists;
    # do not replay an older failure while that turn is still running.
    if any(event.get("type") == "turn/start" for _, event in ordered[end_index + 1 :]):
        raise AgentRuntimeError("the latest Agent turn is still running")

    end_event = ordered[end_index][1]
    end_data = end_event.get("data") if isinstance(end_event.get("data"), dict) else {}
    reason = end_data.get("reason") if isinstance(end_data.get("reason"), dict) else {}
    kind = str(reason.get("kind") or end_data.get("status") or "").strip().lower()
    if kind not in _RETRYABLE_TURN_KINDS:
        if kind in _NON_RETRYABLE_TURN_KINDS or not kind:
            raise AgentRuntimeError("the latest Agent turn is not retryable")
        raise AgentRuntimeError("the latest Agent turn has an unsupported terminal state")

    raw_turn = end_data.get("turn")
    turn: int | str | None
    if isinstance(raw_turn, bool) or not isinstance(raw_turn, (int, str)):
        turn = None
    else:
        turn = raw_turn

    start_index = 0
    start_data: dict[str, Any] = {}
    for index in range(end_index - 1, -1, -1):
        event = ordered[index][1]
        if event.get("type") != "turn/start":
            continue
        candidate_data = event.get("data") if isinstance(event.get("data"), dict) else {}
        candidate_turn = candidate_data.get("turn")
        if turn is None or candidate_turn == turn or str(candidate_turn) == str(turn):
            start_index = index
            start_data = candidate_data
            break

    user_event: dict[str, Any] | None = None
    for index in range(end_index - 1, start_index - 1, -1):
        event = ordered[index][1]
        if event.get("type") != "user/message":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        message = data.get("message") if isinstance(data.get("message"), dict) else data
        if not isinstance(message, dict) or str(message.get("role") or "user").strip().lower() != "user":
            continue
        source = message.get("source") if isinstance(message.get("source"), dict) else data.get("source")
        if isinstance(source, dict) and source.get("kind") not in {None, "user"}:
            continue
        candidate_turn = data.get("turn")
        if turn is not None and candidate_turn is not None and str(candidate_turn) != str(turn):
            continue
        user_event = message
        break

    if user_event is None:
        raise AgentRuntimeError("the latest failed Agent turn has no replayable user target")

    content = user_event.get("content")
    if not isinstance(content, list) or not content:
        raise AgentRuntimeError("the retry target contains image or non-text content")
    if user_event.get("attachments") or any(
        not isinstance(block, dict) or block.get("type") != "text" for block in content
    ):
        raise AgentRuntimeError("the retry target contains image or non-text content")
    try:
        normalized = _prompt_content(content)
    except AgentRuntimeError as error:
        raise AgentRuntimeError("the retry target contains invalid text content") from error
    text = "\n".join(block["text"] for block in normalized)
    if not text.strip():
        raise AgentRuntimeError("the latest failed Agent turn has no replayable user target")

    mode = "execute"
    for candidate in (
        start_data.get("mode"),
        start_data.get("requestedMode"),
        start_data.get("requested_mode"),
        (start_data.get("trigger") or {}).get("mode") if isinstance(start_data.get("trigger"), dict) else None,
    ):
        candidate_mode = str(candidate or "").strip().lower()
        if candidate_mode in {"plan", "execute", "readonly"}:
            mode = candidate_mode
            break
    return {
        "turn": turn,
        "mode": mode,
        "text": text,
        "text_length": len(text),
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


_TURN_STATUS_ALIASES = {
    "complete": "completed",
    "completed": "completed",
    "success": "completed",
    "succeeded": "completed",
    "ok": "completed",
    "cancel": "cancelled",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "abort": "aborted",
    "aborted": "aborted",
    "fail": "failed",
    "failed": "failed",
    "failure": "failed",
    "error": "error",
    "interrupted": "interrupted",
    "stopped": "stopped",
}
def _turn_status(value: Any, *, default: str = "running") -> str:
    candidate = str(value or "").strip().lower()
    return _TURN_STATUS_ALIASES.get(candidate, default)


def _turn_reference(data: dict[str, Any], sequence: int, active: str | None) -> tuple[str | None, int | str | None]:
    raw_turn = data.get("turn")
    if isinstance(raw_turn, bool) or not isinstance(raw_turn, (int, str)):
        return active, None
    if isinstance(raw_turn, str):
        turn_value = _safe_agent_text(raw_turn, 80)
        if not turn_value:
            return active, None
    else:
        turn_value = raw_turn
    return f"turn:{turn_value}", turn_value


def _compact_turns(events: list[Any]) -> list[dict[str, Any]]:
    """Project bounded turn lifecycle counters without conversation content."""

    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    active: str | None = None
    for wrapper in events:
        if not isinstance(wrapper, dict):
            continue
        event = wrapper.get("event") if isinstance(wrapper.get("event"), dict) else wrapper
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        raw_sequence = event.get("seq")
        sequence = raw_sequence if isinstance(raw_sequence, int) and not isinstance(raw_sequence, bool) and raw_sequence >= 0 else 0
        reference, turn_value = _turn_reference(data, sequence, active)
        if event_type == "turn/start" and reference is None:
            reference = f"seq:{sequence}"
        if reference is None:
            continue
        record = records.get(reference)
        if record is None:
            record = {
                "id": reference[:96],
                "status": "running",
                "steps": 0,
                "tools": 0,
                "approvals": 0,
                "artifacts": 0,
            }
            if turn_value is not None:
                record["turn"] = turn_value
            records[reference] = record
            order.append(reference)
        if event_type == "turn/start":
            active = reference
            record["status"] = "running"
            record["start_seq"] = sequence
            mode = str(data.get("mode") or data.get("requestedMode") or data.get("requested_mode") or "").strip().lower()
            if mode in {"plan", "execute", "readonly"}:
                record["mode"] = mode
        elif event_type == "turn/end":
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            record["status"] = _turn_status(reason.get("kind") or reason.get("status") or data.get("status"), default="completed")
            record["end_seq"] = sequence
            if active == reference:
                active = None
        elif event_type == "step/start":
            record["steps"] = min(10000, int(record.get("steps") or 0) + 1)
        elif event_type == "tool/call":
            record["tools"] = min(10000, int(record.get("tools") or 0) + 1)
        elif event_type.startswith("approval/") or event_type.startswith("approval."):
            if event_type.endswith("requested") or event_type.endswith("request"):
                record["approvals"] = min(10000, int(record.get("approvals") or 0) + 1)
        elif "artifact" in event_type or "diff" in event_type:
            record["artifacts"] = min(10000, int(record.get("artifacts") or 0) + 1)

    result: list[dict[str, Any]] = []
    for reference in order[-16:]:
        record = records[reference]
        clean: dict[str, Any] = {
            "id": _safe_agent_text(record.get("id"), 96),
            "status": _turn_status(record.get("status")),
            "steps": max(0, int(record.get("steps") or 0)),
            "tools": max(0, int(record.get("tools") or 0)),
            "approvals": max(0, int(record.get("approvals") or 0)),
            "artifacts": max(0, int(record.get("artifacts") or 0)),
        }
        for key in ("turn", "mode", "start_seq", "end_seq"):
            value = record.get(key)
            if key == "mode":
                if value in {"plan", "execute", "readonly"}:
                    clean[key] = value
            elif key in {"start_seq", "end_seq"}:
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    clean[key] = value
            elif value is not None:
                clean[key] = value
        result.append(clean)
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
    sequence_values: list[int] = []
    last_turn_state = "idle"
    turns = _compact_turns(events)

    for wrapper in events:
        if not isinstance(wrapper, dict):
            continue
        event = wrapper.get("event") if isinstance(wrapper.get("event"), dict) else wrapper
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "agent/event")
        raw_sequence = event.get("seq")
        sequence = raw_sequence if isinstance(raw_sequence, int) else 0
        if isinstance(raw_sequence, int) and not isinstance(raw_sequence, bool) and raw_sequence >= 0:
            sequence_values.append(raw_sequence)
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
            call_id, is_error = _tool_result_metadata(data)
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
            entry["status"] = "failed" if is_error else "completed"
            entry["completed_seq"] = sequence
            artifact = artifacts_by_call_id.get(call_id) if call_id else None
            if artifact is not None:
                artifact["status"] = entry["status"]
                artifact["seq"] = sequence
            presentation = _compact_tool_event_view(tool_view, expected="result")
            if presentation:
                entry["result"] = presentation
                if presentation.get("card") == "diff":
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
    stats = _compact_session_stats(values.get("sessionStats"))
    context = _compact_context_pressure(values.get("contextPressure"))
    token_usage = _compact_token_usage(values.get("tokenUsage"))
    context_breakdown = _compact_context_breakdown(values.get("contextBreakdown"))
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
        "turns": turns,
        "stats": stats,
        "context": context,
        "token_usage": token_usage,
        "context_breakdown": context_breakdown,
        "has_more": bool(history.get("hasMore")),
        # DSH's beforeSeq cursor is the sequence of the first event in the
        # current page.  Keeping it separate from the compact message list
        # lets the UI page across tool-only turns without exposing raw events.
        "oldest_seq": min(sequence_values) if sequence_values else None,
        "newest_seq": max(sequence_values) if sequence_values else None,
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
