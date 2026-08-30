"""Optional desktop automation adapters.

Only the adapter contract is required at import time.  Windows UI Automation,
Electron CDP, and ZCode protocol details are injected or loaded lazily so a
normal Sumika installation does not gain global input authority by importing
this module.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .contracts import (
    DesktopActionRequest,
    DesktopAdapter,
    DesktopApplication,
    DesktopAutomationError,
    DesktopSession,
    safe_identifier,
    safe_text,
)


_SECRET_RE = re.compile(
    r"(?ix)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|(?:api[_ -]?key|token|password|secret|cookie|otp)\s*[:=]\s*[^\s,;]+)"
)
_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")
_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "private_key",
}
_BINARY_KEYS = {"data", "image", "image_data", "base64", "base64_data", "buffer", "png_bytes", "jpeg_bytes"}


def _safe_result(value: Any, *, depth: int = 0) -> Any:
    """Bound adapter output while retaining useful text for the Agent."""

    if depth > 5:
        return "[truncated]"
    if isinstance(value, str):
        text = value.strip()
        if _PATH_RE.match(text):
            return "[omitted local path]"
        text = _SECRET_RE.sub("[redacted]", text)
        return text[:16_000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:96]:
            key = str(raw_key)[:120]
            normalized = key.lower().replace("-", "_")
            if normalized in _BINARY_KEYS or any(token in normalized for token in ("base64", "screenshot_data", "image_data")):
                result[key] = "[omitted binary payload]"
            elif normalized in _SENSITIVE_KEYS or any(token in normalized for token in _SENSITIVE_KEYS):
                result[key] = "[redacted]"
            elif normalized in {"path", "file", "filename", "filepath", "file_path", "executable", "working_directory", "profile_dir"}:
                result[key] = "[omitted local path]"
            else:
                result[key] = _safe_result(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_result(item, depth=depth + 1) for item in list(value)[:96]]
    return _safe_result(str(value), depth=depth + 1)


def _native_id(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("session_id", "sessionId", "window_id", "windowId", "id", "handle"):
        candidate = value.get(key)
        if isinstance(candidate, (str, int)) and str(candidate).strip():
            return str(candidate).strip()[:240]
    return None


class MemoryDesktopAdapter(DesktopAdapter):
    """Deterministic in-memory adapter used by contract tests only."""

    adapter_id = "memory-desktop"
    transport = "app-protocol"
    capabilities = frozenset({"observe", "read", "focus", "send", "control"})

    def __init__(self, *, responses: Mapping[str, Any] | None = None) -> None:
        self.responses = dict(responses or {})
        self.sessions: dict[str, dict[str, Any]] = {}
        self.actions: list[DesktopActionRequest] = []

    def health(self, application: DesktopApplication) -> dict[str, Any]:
        del application
        return {"ok": True, "state": "ready", "adapter_id": self.adapter_id}

    def open(self, application: DesktopApplication, profile_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        del application, options
        native = f"memory-{uuid4().hex[:12]}"
        self.sessions[native] = {"profile_id": profile_id, "state": "ready"}
        return {"native_session_id": native, "state": "ready", "transport": self.transport}

    def observe(self, session: DesktopSession, options: Mapping[str, Any]) -> dict[str, Any]:
        del options
        return {
            "state": "ready",
            "session_id": session.session_id,
            "window": {"focused": True},
            "controls": ["observe", "send", "control"],
        }

    def act(self, session: DesktopSession, request: DesktopActionRequest) -> dict[str, Any]:
        del session
        self.actions.append(request)
        response = self.responses.get(request.action)
        if callable(response):
            response = response(request)
        if response is None:
            if request.action in {"send", "prompt"}:
                return {"accepted": True, "completed": True, "text": "memory adapter"}
            return {"completed": True, "action": request.action}
        if isinstance(response, Mapping):
            return dict(response)
        return {"completed": True, "value": response}


class ElectronCdpClient:
    """Small CDP compatibility surface with an injectable transport.

    A real browser/CDP dependency is intentionally optional.  The default
    implementation only performs a loopback ``/json/version`` health probe;
    action methods require a caller-supplied ``runner`` that owns the WebSocket
    implementation and can be tested independently.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:9222",
        *,
        runner: Callable[[str, Mapping[str, Any]], Any] | None = None,
        timeout: float = 3.0,
    ) -> None:
        self.endpoint = str(endpoint or "").rstrip("/")
        self.runner = runner
        self.timeout = max(0.2, min(float(timeout), 30.0))

    @property
    def available(self) -> bool:
        try:
            parsed = urlparse(self.endpoint)
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def _call(self, operation: str, payload: Mapping[str, Any]) -> Any:
        if self.runner is None:
            raise DesktopAutomationError(
                "Electron CDP action transport is not configured",
                code="cdp-transport-unavailable",
            )
        try:
            return self.runner(operation, payload)
        except DesktopAutomationError:
            raise
        except Exception as error:
            raise DesktopAutomationError(
                "Electron CDP operation failed",
                code="cdp-operation-failed",
                retryable=True,
            ) from error

    def health(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "state": "unavailable", "error_code": "cdp-endpoint-invalid"}
        if self.runner is not None:
            try:
                value = self._call("health", {})
                return {"ok": True, "state": "ready", "result": _safe_result(value)}
            except DesktopAutomationError as error:
                return {"ok": False, "state": "unavailable", "error_code": error.code}
        parsed = urlparse(self.endpoint)
        try:
            with urllib.request.urlopen(f"{self.endpoint}/json/version", timeout=self.timeout) as response:
                raw = json.loads(response.read(64 * 1024).decode("utf-8", "replace"))
            return {"ok": True, "state": "ready", "browser": _safe_result(raw.get("Browser") if isinstance(raw, Mapping) else None)}
        except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError):
            del parsed
            return {"ok": False, "state": "unavailable", "error_code": "cdp-endpoint-unavailable"}

    def open(self, application: DesktopApplication, profile_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        return dict(self._call("open", {"app_id": application.app_id, "profile_id": profile_id, "options": dict(options)}))

    def observe(self, native_session_id: str, options: Mapping[str, Any]) -> Any:
        return self._call("observe", {"session_id": native_session_id, "options": dict(options)})

    def act(self, native_session_id: str, request: DesktopActionRequest) -> Any:
        return self._call(
            "act",
            {
                "session_id": native_session_id,
                "action": request.action,
                "target": request.target,
                "value": request.value,
                "args": dict(request.args),
            },
        )

    def close(self, native_session_id: str) -> Any:
        return self._call("close", {"session_id": native_session_id})

    def takeover(self, native_session_id: str, enabled: bool) -> Any:
        return self._call("takeover", {"session_id": native_session_id, "enabled": enabled})


class WindowsUiAutomationClient:
    """Injectable Windows UIA backend; no pywin32/UIA dependency is required."""

    def __init__(
        self,
        *,
        runner: Callable[[str, Mapping[str, Any]], Any] | None = None,
        foreground_enabled: bool = False,
    ) -> None:
        self.runner = runner
        self.foreground_enabled = bool(foreground_enabled)

    @property
    def available(self) -> bool:
        return self.runner is not None

    def _call(self, operation: str, payload: Mapping[str, Any]) -> Any:
        if self.runner is None:
            raise DesktopAutomationError("Windows UI Automation backend is not installed", code="uia-unavailable")
        try:
            return self.runner(operation, payload)
        except DesktopAutomationError:
            raise
        except Exception as error:
            raise DesktopAutomationError("Windows UI Automation operation failed", code="uia-operation-failed", retryable=True) from error

    def health(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "state": "unavailable", "error_code": "uia-unavailable"}
        try:
            return {"ok": True, "state": "ready", "result": _safe_result(self._call("health", {}))}
        except DesktopAutomationError as error:
            return {"ok": False, "state": "unavailable", "error_code": error.code}

    def open(self, application: DesktopApplication, profile_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        return dict(self._call("open", {"app_id": application.app_id, "profile_id": profile_id, "options": dict(options)}))

    def observe(self, native_session_id: str, options: Mapping[str, Any]) -> Any:
        return self._call("observe", {"session_id": native_session_id, "options": dict(options)})

    def act(self, native_session_id: str, request: DesktopActionRequest) -> Any:
        return self._call(
            "act",
            {"session_id": native_session_id, "action": request.action, "target": request.target, "value": request.value, "args": dict(request.args)},
        )

    def close(self, native_session_id: str) -> Any:
        return self._call("close", {"session_id": native_session_id})

    def takeover(self, native_session_id: str, enabled: bool) -> Any:
        if enabled and not self.foreground_enabled:
            raise DesktopAutomationError("foreground takeover is disabled", code="foreground-takeover-disabled")
        return self._call("takeover", {"session_id": native_session_id, "enabled": enabled})


class TransportDesktopAdapter(DesktopAdapter):
    """Adapt a transport client to the runtime-neutral desktop contract.

    ``ElectronCdpClient`` and ``WindowsUiAutomationClient`` intentionally stay
    transport clients: they know how to speak a protocol, but do not own
    registration, leases, permissions, or session policy.  This thin adapter
    is the reusable bridge for those clients and for future transports with the
    same small method surface.  It never discovers windows or starts a process.

    A client must provide ``health()``, ``open(application, profile_id,
    options)``, ``observe(native_session_id, options)`` and
    ``act(native_session_id, request)``.  ``close`` and ``takeover`` are
    optional; unsupported operations fail closed.
    """

    _TRANSPORTS = frozenset({"app-protocol", "electron-cdp", "windows-uia", "foreground"})

    def __init__(
        self,
        adapter_id: str,
        client: Any,
        *,
        transport: str,
        capabilities: Any = None,
        foreground_enabled: bool = False,
    ) -> None:
        self.adapter_id = safe_identifier(adapter_id, "adapter_id").lower()
        self.transport = safe_text(transport, "transport", 40, allow_empty=False).lower()
        if self.transport not in self._TRANSPORTS:
            raise DesktopAutomationError("transport is unsupported", code="invalid-transport")
        if client is None:
            raise DesktopAutomationError("transport client is required", code="invalid-client")
        required = ("health", "open", "observe", "act")
        missing = [name for name in required if not callable(getattr(client, name, None))]
        if missing:
            raise DesktopAutomationError(
                "transport client is missing required methods",
                code="invalid-client",
            )
        self.client = client
        raw_capabilities = capabilities
        if raw_capabilities is None:
            raw_capabilities = getattr(client, "capabilities", ("observe", "read"))
        if isinstance(raw_capabilities, str):
            raw_capabilities = (raw_capabilities,)
        self.capabilities = frozenset(
            str(item).strip().lower()
            for item in (raw_capabilities or ())
            if str(item).strip()
        ) or frozenset({"observe", "read"})
        self.foreground_enabled = bool(foreground_enabled)

    @staticmethod
    def _native_session(session: DesktopSession) -> str:
        native = session.native_session_id
        if not native:
            raise DesktopAutomationError("desktop session has no native handle", code="session-handle-missing")
        return str(native)

    def health(self, application: DesktopApplication) -> dict[str, Any]:
        del application
        value = self.client.health()
        if isinstance(value, Mapping):
            result = dict(value)
            ok = result.get("ok") is True
            result.setdefault("ok", ok)
            result.setdefault("state", "ready" if ok else "unavailable")
            result.setdefault("transport", self.transport)
            return result
        ok = bool(value)
        return {
            "ok": ok,
            "state": "ready" if ok else "unavailable",
            "transport": self.transport,
        }

    def open(
        self,
        application: DesktopApplication,
        profile_id: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = self.client.open(application, profile_id, dict(options))
        if not isinstance(value, Mapping):
            raise DesktopAutomationError(
                "transport client returned an invalid open result",
                code="invalid-adapter-result",
            )
        result = dict(value)
        if _native_id(result) is None:
            raise DesktopAutomationError(
                "transport client did not return a native session id",
                code="session-handle-missing",
            )
        result.setdefault("transport", self.transport)
        result.setdefault("state", "ready")
        return result

    def observe(self, session: DesktopSession, options: Mapping[str, Any]) -> Any:
        return self.client.observe(self._native_session(session), dict(options))

    def act(self, session: DesktopSession, request: DesktopActionRequest) -> Any:
        return self.client.act(self._native_session(session), request)

    def close(self, session: DesktopSession) -> Any:
        close = getattr(self.client, "close", None)
        if not callable(close):
            return {"closed": True, "already_closed": True}
        return close(self._native_session(session))

    def takeover(self, session: DesktopSession, *, enabled: bool) -> Any:
        if enabled and not self.foreground_enabled:
            raise DesktopAutomationError(
                "foreground takeover is disabled",
                code="foreground-takeover-disabled",
            )
        takeover = getattr(self.client, "takeover", None)
        if not callable(takeover):
            raise DesktopAutomationError(
                "transport client does not support foreground takeover",
                code="foreground-takeover-unavailable",
            )
        return takeover(self._native_session(session), enabled)

    def shutdown(self) -> None:
        shutdown = getattr(self.client, "shutdown", None)
        if callable(shutdown):
            shutdown()


class ZCodeDesktopAdapter(DesktopAdapter):
    """Use ZCode's public app-server first, with optional CDP/UIA fallback."""

    adapter_id = "zcode-desktop"
    transport = "app-protocol"
    capabilities = frozenset({"observe", "read", "focus", "send", "control", "select_model", "stop"})

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        runtime: Any = None,
        runtime_factory: Callable[[], Any] | None = None,
        cdp: ElectronCdpClient | None = None,
        uia: WindowsUiAutomationClient | None = None,
        foreground_enabled: bool = False,
        logger: Any = None,
    ) -> None:
        self.data_dir = data_dir
        self.env = dict(env or os.environ)
        self.runtime = runtime
        self.runtime_factory = runtime_factory
        self.cdp = cdp
        self.uia = uia
        self.foreground_enabled = bool(foreground_enabled)
        self.logger = logger
        self._owns_runtime = False
        self._handles: dict[str, tuple[str, str]] = {}

    def _ensure_runtime(self, application: DesktopApplication) -> Any:
        if self.runtime is not None:
            return self.runtime
        if self.runtime_factory is not None:
            self.runtime = self.runtime_factory()
            self._owns_runtime = True
            return self.runtime
        # Importing the ZCode transport is lazy; selecting a different adapter
        # never loads or probes it.
        from ..agent.adapters.zcode.runtime import ZCodeAgentRuntime

        config_env = dict(self.env)
        config = dict(application.config)
        if isinstance(config.get("executable"), str):
            config_env["SUMIKA_ZCODE_EXECUTABLE"] = config["executable"]
        if isinstance(config.get("script"), str):
            config_env["SUMIKA_ZCODE_SCRIPT"] = config["script"]
        if isinstance(config.get("node"), str):
            config_env["SUMIKA_ZCODE_NODE"] = config["node"]
        self.runtime = ZCodeAgentRuntime(self.data_dir, env=config_env, logger=self.logger)
        self._owns_runtime = True
        return self.runtime

    @staticmethod
    def _health_value(runtime: Any) -> dict[str, Any]:
        try:
            value = runtime.health()
        except Exception as error:
            return {"ok": False, "state": "unavailable", "error_code": type(error).__name__}
        return _safe_result(value) if isinstance(value, Mapping) else {"ok": bool(value), "state": "ready" if value else "unavailable"}

    def health(self, application: DesktopApplication) -> dict[str, Any]:
        # An unconfigured built-in entry is reported without starting a child.
        if not application.config and self.runtime is None and self.runtime_factory is None:
            return {"ok": False, "state": "unconfigured", "adapter_id": self.adapter_id}
        runtime = self._ensure_runtime(application)
        result = self._health_value(runtime)
        if result.get("ok"):
            return {"ok": True, "state": "ready", "transport": "app-protocol", "result": result}
        if self.cdp is not None:
            cdp = self.cdp.health()
            if cdp.get("ok"):
                return {"ok": True, "state": "ready", "transport": "electron-cdp", "result": cdp}
        if self.uia is not None:
            uia = self.uia.health()
            if uia.get("ok"):
                return {"ok": True, "state": "ready", "transport": "windows-uia", "result": uia}
        return {"ok": False, "state": "unavailable", "transport": "app-protocol", "result": result}

    def _open_protocol(self, application: DesktopApplication, profile_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        runtime = self._ensure_runtime(application)
        health = self._health_value(runtime)
        if not health.get("ok"):
            raise DesktopAutomationError("ZCode app-server is unavailable", code="zcode-app-server-unavailable", retryable=True)
        params: dict[str, Any] = {
            "title": safe_text(options.get("title"), "title", 240) or "Sumika managed ZCode session",
            "mode": safe_text(options.get("mode"), "mode", 32) or "build",
            "profile_id": profile_id,
        }
        if options.get("cwd"):
            params["cwd"] = safe_text(options.get("cwd"), "cwd", 4096)
        if options.get("model") is not None:
            params["model"] = options.get("model")
        value = runtime.create_session(params)
        native = _native_id(value)
        if not native:
            raise DesktopAutomationError("ZCode did not return a session id", code="zcode-session-id-missing")
        return {"native_session_id": native, "transport": "app-protocol", "state": "ready", "result": _safe_result(value)}

    def open(self, application: DesktopApplication, profile_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        try:
            value = self._open_protocol(application, profile_id, options)
            return value
        except DesktopAutomationError as protocol_error:
            # Fallbacks are only considered when explicitly configured.  A
            # missing app-server never silently grants foreground control.
            if self.cdp is not None:
                health = self.cdp.health()
                if health.get("ok"):
                    value = self.cdp.open(application, profile_id, options)
                    native = _native_id(value) or f"cdp-{uuid4().hex[:12]}"
                    return {"native_session_id": native, "transport": "electron-cdp", "state": "ready", "result": _safe_result(value)}
            if self.uia is not None and options.get("allow_uia") is True:
                health = self.uia.health()
                if health.get("ok"):
                    value = self.uia.open(application, profile_id, options)
                    native = _native_id(value) or f"uia-{uuid4().hex[:12]}"
                    return {"native_session_id": native, "transport": "windows-uia", "state": "ready", "result": _safe_result(value)}
            if self.foreground_enabled and options.get("allow_foreground") is True and self.uia is not None:
                raise DesktopAutomationError("foreground takeover requires an explicit takeover action", code="foreground-takeover-required")
            raise protocol_error

    def _handle(self, session: DesktopSession) -> tuple[str, str]:
        try:
            return self._handles[session.session_id]
        except KeyError as error:
            raise DesktopAutomationError("desktop session handle is missing", code="session-handle-missing") from error

    def observe(self, session: DesktopSession, options: Mapping[str, Any]) -> dict[str, Any]:
        native, transport = self._handle(session)
        if transport == "app-protocol":
            runtime = self.runtime
            if runtime is None:
                raise DesktopAutomationError("ZCode runtime is unavailable", code="zcode-app-server-unavailable")
            value = runtime.snapshot({"sessionId": native, **dict(options)})
        elif transport == "electron-cdp" and self.cdp is not None:
            value = self.cdp.observe(native, options)
        elif transport == "windows-uia" and self.uia is not None:
            value = self.uia.observe(native, options)
        else:
            raise DesktopAutomationError("desktop observation transport is unavailable", code="adapter-unavailable")
        return {"transport": transport, "state": "ready", "observation": _safe_result(value)}

    def act(self, session: DesktopSession, request: DesktopActionRequest) -> dict[str, Any]:
        native, transport = self._handle(session)
        if request.action in {"observe", "read", "snapshot", "inspect"}:
            return self.observe(session, request.args)
        if transport == "app-protocol":
            runtime = self.runtime
            if runtime is None:
                raise DesktopAutomationError("ZCode runtime is unavailable", code="zcode-app-server-unavailable")
            if request.action in {"send", "prompt"}:
                text = request.value if isinstance(request.value, str) else request.args.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise DesktopAutomationError("send action requires text", code="invalid-action-value")
                params: dict[str, Any] = {"sessionId": native, "text": text}
                if request.args.get("mode") is not None:
                    params["mode"] = request.args.get("mode")
                if request.args.get("model") is not None:
                    params["model"] = request.args.get("model")
                value = runtime.prompt(params)
                return {"accepted": value.get("accepted") is True if isinstance(value, Mapping) else False, "completed": value.get("accepted") is True if isinstance(value, Mapping) else False, "result": _safe_result(value)}
            if request.action in {"stop", "cancel"}:
                return {"completed": True, "result": _safe_result(runtime.cancel({"sessionId": native}))}
            if request.action in {"select_model", "set_model"}:
                return {"completed": True, "result": _safe_result(runtime.select_model({"sessionId": native, "model": request.value or request.args.get("model")}))}
            if request.action == "focus":
                return {"completed": True, "focused": True, "logical": True}
            raise DesktopAutomationError("ZCode app-server does not expose this UI action", code="zcode-ui-action-unavailable")
        if transport == "electron-cdp" and self.cdp is not None:
            return _safe_result(self.cdp.act(native, request))
        if transport == "windows-uia" and self.uia is not None:
            return _safe_result(self.uia.act(native, request))
        raise DesktopAutomationError("desktop action transport is unavailable", code="adapter-unavailable")

    def close(self, session: DesktopSession) -> dict[str, Any]:
        handle = self._handles.pop(session.session_id, None)
        if handle is None:
            return {"closed": True, "already_closed": True}
        native, transport = handle
        if transport == "electron-cdp" and self.cdp is not None:
            return {"closed": True, "result": _safe_result(self.cdp.close(native))}
        if transport == "windows-uia" and self.uia is not None:
            return {"closed": True, "result": _safe_result(self.uia.close(native))}
        # Closing a logical app-server Session is intentionally separate from
        # closing the shared ZCode process.  The Agent runtime owns that child.
        return {"closed": True}

    def takeover(self, session: DesktopSession, *, enabled: bool) -> dict[str, Any]:
        native, transport = self._handle(session)
        if not enabled:
            if transport == "electron-cdp" and self.cdp is not None:
                return {"enabled": False, "result": _safe_result(self.cdp.takeover(native, False))}
            if transport == "windows-uia" and self.uia is not None:
                return {"enabled": False, "result": _safe_result(self.uia.takeover(native, False))}
            return {"enabled": False, "logical": True}
        if not self.foreground_enabled:
            raise DesktopAutomationError("foreground takeover is disabled", code="foreground-takeover-disabled")
        if transport == "electron-cdp" and self.cdp is not None:
            return {"enabled": True, "result": _safe_result(self.cdp.takeover(native, True))}
        if transport == "windows-uia" and self.uia is not None:
            return {"enabled": True, "result": _safe_result(self.uia.takeover(native, True))}
        raise DesktopAutomationError("foreground takeover is unavailable for this transport", code="foreground-takeover-unavailable")

    def bind_handle(self, session_id: str, opened: Mapping[str, Any]) -> None:
        native = _native_id(opened)
        if not native:
            raise DesktopAutomationError("adapter did not return a native session id", code="session-handle-missing")
        transport = str(opened.get("transport") or self.transport)
        self._handles[session_id] = (native, transport)

    def shutdown(self) -> None:
        if self._owns_runtime and self.runtime is not None:
            try:
                self.runtime.close()
            except Exception:
                pass
        self.runtime = None if self._owns_runtime else self.runtime
        self._handles.clear()


__all__ = [
    "ElectronCdpClient",
    "MemoryDesktopAdapter",
    "TransportDesktopAdapter",
    "WindowsUiAutomationClient",
    "ZCodeDesktopAdapter",
]
