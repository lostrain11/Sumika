"""Policy and lifecycle runtime for controlled desktop software automation."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ..protocol.models import utc_now
from .adapters import ZCodeDesktopAdapter
from .audit import DesktopAuditSink
from .contracts import (
    DESKTOP_AUTOMATION_SCHEMA,
    DesktopActionRequest,
    DesktopActionResult,
    DesktopAdapter,
    DesktopApplication,
    DesktopAutomationError,
    DesktopLeaseError,
    DesktopPermissionError,
    DesktopRegistrationError,
    DesktopSession,
    action_risk,
    hash_value,
    safe_identifier,
    safe_text,
)


_SECRET_RE = re.compile(
    r"(?ix)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|(?:api[_ -]?key|token|password|secret|cookie|otp|private[_ -]?key)\s*[:=]\s*[^\s,;]+)"
)
_SENSITIVE_TARGET_RE = re.compile(r"(?i)(?:password|passwd|passcode|otp|one[-_ ]?time|secret|token|api[-_ ]?key|verification|captcha|cookie|credential)")
_SENSITIVE_KEY_RE = re.compile(r"(?i)(?:password|passwd|passcode|otp|secret|token|api[-_ ]?key|authorization|cookie|credential|private[-_ ]?key)")
_OWNERS = frozenset({"agent", "manual", "system"})
_PERMISSION_SCOPES = frozenset({"observe", "control"})
_CONTROL_ACTIONS = frozenset({"click", "fill", "press", "select", "type", "write", "focus", "send", "prompt", "stop", "cancel", "select_model", "set_model"})
_SENSITIVE_ACTIONS = frozenset({"login", "credential", "password", "otp", "captcha", "delete", "publish", "purchase", "upload", "download", "permission_change"})


def _iso_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _expired(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)


def _safe_public(value: Any, *, depth: int = 0) -> Any:
    """Bound adapter output without writing it to durable metadata."""

    if depth > 5:
        return "[truncated]"
    if isinstance(value, str):
        text = value.strip()
        if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", text):
            return "[omitted local path]"
        text = _SECRET_RE.sub("[redacted]", text)
        return text[:16_000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        blocked = ("password", "secret", "token", "cookie", "authorization", "api_key", "apikey", "credential", "executable", "working_directory", "profile_dir")
        for raw_key, item in list(value.items())[:96]:
            key = str(raw_key)[:120]
            normalized = key.lower().replace("-", "_")
            if any(token in normalized for token in blocked):
                result[key] = "[redacted]"
            elif normalized in {"path", "file", "filename", "filepath", "file_path", "cwd"}:
                result[key] = "[omitted local path]"
            elif normalized in {"data", "image", "image_data", "base64", "base64_data", "buffer", "png_bytes", "jpeg_bytes"}:
                result[key] = "[omitted binary payload]"
            else:
                result[key] = _safe_public(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_public(item, depth=depth + 1) for item in list(value)[:96]]
    return _safe_public(str(value), depth=depth + 1)


def _looks_sensitive(request: DesktopActionRequest) -> bool:
    target = request.target or ""
    value = request.value if isinstance(request.value, str) else ""
    if request.action in _SENSITIVE_ACTIONS:
        return True
    if request.action in {"fill", "type", "write"} and (_SENSITIVE_TARGET_RE.search(target) or _SECRET_RE.search(value)):
        return True
    if _SECRET_RE.search(target):
        return True
    return _contains_sensitive_value(request.args)


def _contains_sensitive_value(value: Any, *, depth: int = 0) -> bool:
    """Inspect nested action arguments without retaining their contents."""

    if depth > 5:
        return False
    if isinstance(value, Mapping):
        for raw_key, item in list(value.items())[:96]:
            key = str(raw_key)
            if _SENSITIVE_KEY_RE.search(key):
                return True
            if _contains_sensitive_value(item, depth=depth + 1):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_sensitive_value(item, depth=depth + 1) for item in list(value)[:96])
    return isinstance(value, str) and bool(_SECRET_RE.search(value))


class DesktopAutomationRuntime:
    """Own registrations, permissions, profile leases, and adapter sessions.

    The runtime never discovers an arbitrary window and never invokes a shell.
    An adapter must be registered explicitly; the built-in ZCode declaration is
    inert until the user approves and configures it.
    """

    LEASE_TTL_SECONDS = 15 * 60

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        storage: Any = None,
        logger: Any = None,
        agent_runtime: Any = None,
        adapters: Mapping[str, DesktopAdapter] | None = None,
        register_zcode: bool = True,
        foreground_takeover: bool = False,
    ) -> None:
        self.data_dir = data_dir
        self.storage = storage
        self.logger = logger
        self.foreground_takeover = bool(foreground_takeover)
        self.owner_token = f"desktop-core-{uuid4().hex}"
        self.audit = DesktopAuditSink(data_dir, logger=logger)
        self._lock = threading.RLock()
        self._adapters: dict[str, DesktopAdapter] = {}
        self._apps: dict[str, DesktopApplication] = {}
        self._sessions: dict[str, DesktopSession] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self._permissions: dict[tuple[str, str], dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[str, DesktopActionResult] = {}
        self._closed = False

        for adapter_id, adapter in (adapters or {}).items():
            self.register_adapter(adapter_id, adapter)
        if register_zcode:
            runtime = agent_runtime if getattr(agent_runtime, "runtime_id", None) == "zcode" else None
            self.register_adapter(
                "zcode-desktop",
                ZCodeDesktopAdapter(
                    data_dir,
                    env=os.environ,
                    runtime=runtime,
                    foreground_enabled=self.foreground_takeover,
                    logger=logger,
                ),
            )
        self._load_persisted_applications()
        if register_zcode and "zcode" not in self._apps:
            self._apps["zcode"] = DesktopApplication(
                app_id="zcode",
                name="ZCode",
                adapter_id="zcode-desktop",
                transport="app-protocol",
                status="unconfigured",
                approved=False,
                managed=True,
                capabilities=("observe", "read", "send", "control", "select_model", "stop"),
                permissions=("desktop.observe", "desktop.control"),
                metadata={"builtin": True, "credential_source": "ZCode-managed-login"},
            )

    # ------------------------------------------------------------------
    # Registration and catalog
    # ------------------------------------------------------------------
    def register_adapter(self, adapter_id: str, adapter: DesktopAdapter) -> None:
        normalized = safe_identifier(adapter_id, "adapter_id").lower()
        if not isinstance(adapter, DesktopAdapter):
            raise DesktopRegistrationError("adapter must implement DesktopAdapter", code="invalid-adapter")
        with self._lock:
            if normalized in self._adapters and self._adapters[normalized] is not adapter:
                raise DesktopRegistrationError("adapter_id is already registered", code="duplicate-adapter")
            self._adapters[normalized] = adapter

    def _load_persisted_applications(self) -> None:
        if self.storage is None or not callable(getattr(self.storage, "list_desktop_applications", None)):
            return
        try:
            rows = self.storage.list_desktop_applications()
        except Exception as error:
            self._log("desktop application metadata read failed", error)
            return
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            try:
                app_id = safe_identifier(row.get("app_id"), "app_id")
                adapter_id = safe_identifier(row.get("adapter_id"), "adapter_id")
                if adapter_id not in self._adapters:
                    continue
                self._apps[app_id] = DesktopApplication(
                    app_id=app_id,
                    name=str(row.get("name") or app_id),
                    adapter_id=adapter_id,
                    transport=str(row.get("transport") or "app-protocol"),
                    status=str(row.get("status") or "unconfigured"),
                    approved=bool(row.get("approved")),
                    managed=bool(row.get("managed")),
                    capabilities=tuple(row.get("capabilities") or ("observe", "read")),
                    permissions=tuple(row.get("permissions") or ()),
                    profile_id=row.get("profile_id"),
                    fingerprint=row.get("fingerprint") if isinstance(row.get("fingerprint"), Mapping) else {},
                    metadata=row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {},
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            except DesktopAutomationError:
                continue

    def register_application(self, value: Mapping[str, Any], *, approved: bool = False, confirm_app_id: str | None = None) -> dict[str, Any]:
        if not approved:
            raise DesktopPermissionError("registering a desktop application requires explicit approval", code="approval-required")
        if not isinstance(value, Mapping):
            raise DesktopRegistrationError("application declaration must be an object", code="invalid-application")
        app_id = safe_identifier(value.get("app_id") or value.get("appId"), "app_id")
        if confirm_app_id not in (None, "") and str(confirm_app_id) != app_id:
            raise DesktopPermissionError("confirm_app_id does not match app_id", code="approval-mismatch")
        adapter_id = safe_identifier(value.get("adapter_id") or value.get("adapterId"), "adapter_id").lower()
        with self._lock:
            if adapter_id not in self._adapters:
                raise DesktopRegistrationError("adapter is not registered", code="adapter-not-registered")
        name = safe_text(value.get("name") or app_id, "name", 240, allow_empty=False)
        config = value.get("config") if isinstance(value.get("config"), Mapping) else {}
        requested_transport = value.get("transport")
        # ``enable_cdp`` was the original opt-in spelling for the built-in
        # Electron client.  Preserve it as an explicit transport selection so
        # the route projection and worker cannot later reinterpret it as an
        # implicit fallback.
        if requested_transport in (None, "") and config.get("enable_cdp") is True and config.get("cdp_endpoint"):
            requested_transport = "electron-cdp"
        transport = safe_text(requested_transport or getattr(self._adapters[adapter_id], "transport", "app-protocol"), "transport", 40, allow_empty=False).lower()
        status = safe_text(value.get("status") or ("configured" if value.get("config") else "unconfigured"), "status", 40).lower()
        capabilities = tuple(value.get("capabilities") or getattr(self._adapters[adapter_id], "capabilities", ("observe", "read")))
        permissions = tuple(value.get("permissions") or ())
        profile_id = value.get("profile_id") or value.get("profileId")
        if profile_id not in (None, ""):
            profile_id = safe_identifier(profile_id, "profile_id")
        self._validate_config(config)
        existing = self._apps.get(app_id)
        now = utc_now()
        app = DesktopApplication(
            app_id=app_id,
            name=name,
            adapter_id=adapter_id,
            transport=transport,
            status=status,
            approved=True,
            managed=value.get("managed") is True,
            capabilities=capabilities,
            permissions=permissions,
            profile_id=profile_id,
            fingerprint=value.get("fingerprint") if isinstance(value.get("fingerprint"), Mapping) else {},
            metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
            config=config,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        with self._lock:
            self._apps[app_id] = app
        self._persist_application(app)
        self._log_info("desktop application registered app_id=%s adapter_id=%s", app_id, adapter_id)
        self.audit.record(
            app_id=app.app_id,
            adapter_id=app.adapter_id,
            transport=app.transport,
            session_id=None,
            action="register",
            risk="control",
            status="completed",
            approval=True,
        )
        return self._app_public(app)

    def _validate_config(self, config: Mapping[str, Any]) -> None:
        if len(config) > 32:
            raise DesktopRegistrationError("application config has too many fields", code="config-too-large")
        # Launcher paths may be kept in memory for an adapter, but credentials
        # are never accepted even when nested under an options object.
        if _contains_sensitive_value(config):
            raise DesktopRegistrationError(
                "credentials must not be supplied to desktop automation",
                code="credential-boundary",
            )
        try:
            encoded = repr(config).encode("utf-8", "replace")
        except Exception as error:
            raise DesktopRegistrationError("application config is invalid", code="invalid-config") from error
        if len(encoded) > 256 * 1024:
            raise DesktopRegistrationError("application config is too large", code="config-too-large")
        for raw_key, value in config.items():
            key = str(raw_key).strip().lower()
            if not key or len(key) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in key):
                raise DesktopRegistrationError("application config key is invalid", code="invalid-config")

    def catalog(self, *, refresh: bool = False, include_unavailable: bool = True) -> dict[str, Any]:
        with self._lock:
            apps = list(self._apps.values())
            adapters = dict(self._adapters)
            sessions = list(self._sessions.values())
        if refresh:
            for app in apps:
                # A catalog refresh must not start or probe an application the
                # user has not explicitly approved.  This matters for the
                # inert built-in ZCode declaration and arbitrary registrations
                # restored from the metadata projection.
                if not app.approved:
                    continue
                adapter = adapters.get(app.adapter_id)
                if adapter is None:
                    continue
                try:
                    health = adapter.health(app)
                    status = "ready" if health.get("ok") else ("configured" if app.config else "unavailable")
                    updated = replace(app, status=status, updated_at=utc_now())
                    with self._lock:
                        self._apps[app.app_id] = updated
                    # Keep the safe status projection useful after a restart;
                    # no adapter configuration or path is persisted here.
                    self._persist_application(updated)
                except Exception as error:
                    self._log("desktop adapter health failed", error)
        with self._lock:
            apps = list(self._apps.values())
            public_apps = [self._app_public(app) for app in apps if include_unavailable or app.status in {"ready", "running"}]
            adapter_rows = []
            for adapter_id, adapter in sorted(self._adapters.items()):
                adapter_rows.append(
                    {
                        "adapter_id": adapter_id,
                        "transport": str(getattr(adapter, "transport", "app-protocol")),
                        "capabilities": sorted(str(item) for item in getattr(adapter, "capabilities", ())),
                        "status": "registered",
                    }
                )
        return {
            "schema": DESKTOP_AUTOMATION_SCHEMA,
            "checked_at": utc_now(),
            "apps": public_apps,
            "adapters": adapter_rows,
            "sessions": [item.to_public() for item in sessions],
            "permissions": self._permission_public(),
            "foreground_takeover": self.foreground_takeover,
            "global_input": False if not self.foreground_takeover else "approval-required",
        }

    def _app_public(self, app: DesktopApplication) -> dict[str, Any]:
        with self._lock:
            count = sum(1 for session in self._sessions.values() if session.app_id == app.app_id and session.state == "open")
            lease_state = "idle"
            lease_owner = "none"
            for lease in self._leases.values():
                if lease.get("app_id") == app.app_id and not _expired(lease.get("expires_at")):
                    lease_state = "leased"
                    owner = str(lease.get("owner") or "unknown").strip().lower()
                    lease_owner = owner if owner in {"agent", "manual", "system"} else "unknown"
                    break
        return app.to_public(session_count=count, lease_state=lease_state, lease_owner=lease_owner)

    # ------------------------------------------------------------------
    # Session and lease lifecycle
    # ------------------------------------------------------------------
    def open_session(self, app_id: str, *, profile_id: str | None = None, owner: str = "agent", options: Mapping[str, Any] | None = None) -> dict[str, Any]:
        app_id = safe_identifier(app_id, "app_id")
        owner = safe_text(owner, "owner", 32, allow_empty=False).lower()
        if owner not in _OWNERS:
            raise DesktopAutomationError("owner is invalid", code="invalid-owner")
        options = options if isinstance(options, Mapping) else {}
        with self._lock:
            if self._closed:
                raise DesktopAutomationError("desktop automation runtime is closed", code="runtime-closed")
            app = self._apps.get(app_id)
            adapter = self._adapters.get(app.adapter_id) if app else None
        if app is None:
            raise DesktopRegistrationError("desktop application is not registered", code="app-not-registered")
        if not app.approved:
            raise DesktopPermissionError("desktop application requires approval", code="approval-required")
        if adapter is None:
            raise DesktopRegistrationError("desktop adapter is unavailable", code="adapter-unavailable")
        profile = profile_id or app.profile_id or "default"
        profile = safe_identifier(profile, "profile_id")
        session_id = f"desktop-session-{uuid4().hex[:16]}"
        lease_id = f"desktop-lease-{uuid4().hex[:16]}"
        profile_key = self._profile_key(app_id, profile)
        expires_at = _iso_after(self.LEASE_TTL_SECONDS)
        self._acquire_lease(profile_key, session_id, app_id, owner, lease_id, expires_at)
        opened: Mapping[str, Any] | None = None
        try:
            opened_value = adapter.open(app, profile, options)
            if not isinstance(opened_value, Mapping):
                raise DesktopAutomationError("desktop adapter returned an invalid open result", code="invalid-adapter-result")
            opened = opened_value
            session = DesktopSession(
                session_id=session_id,
                app_id=app_id,
                profile_id=profile,
                profile_key=profile_key,
                owner=owner,
                transport=str(opened.get("transport") or app.transport),
                native_session_id=self._native_id(opened),
                state="open",
                opened_at=utc_now(),
                lease_id=lease_id,
                metadata=_safe_public(opened.get("result") if isinstance(opened.get("result"), Mapping) else {}),
            )
            # Adapters that use a native window/session may retain a handle;
            # protocol-only adapters can use DesktopSession directly.
            bind_handle = getattr(adapter, "bind_handle", None)
            if callable(bind_handle):
                bind_handle(session_id, opened)
            with self._lock:
                self._sessions[session_id] = session
                self._leases[profile_key] = {
                    "profile_key": profile_key,
                    "session_id": session_id,
                    "app_id": app_id,
                    "owner": owner,
                    "lease_id": lease_id,
                    "expires_at": expires_at,
                }
            self._persist_lease(self._leases[profile_key])
            self.audit.record(app_id=app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session_id, action="open", risk="control", status="completed", approval=True)
            return {"opened": True, "session": session.to_public()}
        except Exception:
            self._release_lease(profile_key, lease_id, session_id)
            raise

    def _acquire_lease(self, profile_key: str, session_id: str, app_id: str, owner: str, lease_id: str, expires_at: str) -> None:
        with self._lock:
            current = self._leases.get(profile_key)
            if current and not _expired(current.get("expires_at")):
                raise DesktopLeaseError("desktop profile is already leased", code="profile-occupied")
            if current:
                self._leases.pop(profile_key, None)
        if self.storage is not None and callable(getattr(self.storage, "acquire_desktop_automation_lease", None)):
            try:
                result = self.storage.acquire_desktop_automation_lease(
                    profile_key=profile_key,
                    session_id=session_id,
                    app_id=app_id,
                    owner=owner,
                    lease_id=lease_id,
                    expires_at=expires_at,
                )
            except Exception as error:
                self._log("desktop lease persistence failed", error)
                result = None
            if result is None:
                raise DesktopLeaseError("desktop profile is already leased", code="profile-occupied")
        with self._lock:
            self._leases[profile_key] = {
                "profile_key": profile_key,
                "session_id": session_id,
                "app_id": app_id,
                "owner": owner,
                "lease_id": lease_id,
                "expires_at": expires_at,
            }

    def _release_lease(self, profile_key: str, lease_id: str | None, session_id: str | None) -> None:
        with self._lock:
            lease = self._leases.get(profile_key)
            if lease and (lease_id is None or lease.get("lease_id") == lease_id) and (session_id is None or lease.get("session_id") == session_id):
                self._leases.pop(profile_key, None)
        if self.storage is not None and lease_id and callable(getattr(self.storage, "release_desktop_automation_lease", None)):
            try:
                self.storage.release_desktop_automation_lease(profile_key=profile_key, lease_id=lease_id, session_id=session_id)
            except Exception as error:
                self._log("desktop lease release failed", error)

    @staticmethod
    def _profile_key(app_id: str, profile_id: str) -> str:
        return "profile-" + hashlib.sha256(f"{app_id}\0{profile_id}".encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _native_id(value: Mapping[str, Any]) -> str | None:
        for key in ("native_session_id", "nativeSessionId", "window_id", "windowId", "session_id", "sessionId", "id", "handle"):
            item = value.get(key)
            if isinstance(item, (str, int)) and str(item).strip():
                return str(item).strip()[:240]
        return None

    def list_sessions(self) -> dict[str, Any]:
        with self._lock:
            return {"schema": DESKTOP_AUTOMATION_SCHEMA, "sessions": [session.to_public() for session in self._sessions.values()]}

    def _get_session(self, session_id: str) -> tuple[DesktopSession, DesktopApplication, DesktopAdapter]:
        session_id = safe_identifier(session_id, "session_id")
        with self._lock:
            session = self._sessions.get(session_id)
            app = self._apps.get(session.app_id) if session else None
            adapter = self._adapters.get(app.adapter_id) if app else None
        if session is None or session.state != "open":
            raise DesktopAutomationError("desktop session is not open", code="session-not-open")
        if app is None or adapter is None:
            raise DesktopAutomationError("desktop session adapter is unavailable", code="adapter-unavailable")
        return session, app, adapter

    def observe(self, session_id: str, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
        session, app, adapter = self._get_session(session_id)
        started = time.monotonic()
        try:
            value = adapter.observe(session, options if isinstance(options, Mapping) else {})
            result = {"status": "completed", "session": session.to_public(), "observation": _safe_public(value)}
            status = "completed"
            error_code = None
        except DesktopAutomationError as error:
            result = {"status": "failed", "session_id": session.session_id, "error_code": error.code, "reason": str(error)}
            status = "failed"
            error_code = error.code
        except Exception as error:
            result = {"status": "failed", "session_id": session.session_id, "error_code": "adapter-failed", "reason": "desktop adapter failed"}
            status = "failed"
            error_code = type(error).__name__
            self._log("desktop observation failed", error)
        self.audit.record(app_id=app.app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session.session_id, action="observe", risk="read", status=status, duration_ms=(time.monotonic() - started) * 1000, error_code=error_code)
        return result

    # ------------------------------------------------------------------
    # Actions and approvals
    # ------------------------------------------------------------------
    def act(self, value: Mapping[str, Any] | DesktopActionRequest) -> dict[str, Any]:
        request = value if isinstance(value, DesktopActionRequest) else DesktopActionRequest.from_dict(value)
        session, app, adapter = self._get_session(request.session_id)
        if request.action in {"login", "credential", "password", "otp", "captcha"} or _looks_sensitive(request):
            risk = "sensitive"
        else:
            risk = request.risk
        input_hash = request.hash_input()
        idem_key = self._idempotency_key(session, request)
        if idem_key:
            with self._lock:
                previous = self._idempotency.get(idem_key)
            if previous is not None:
                replay = replace(previous, idempotent_replay=True)
                return replay.to_dict()

        # Credentials and credential-shaped input can never be passed through
        # the desktop adapter.  Human login is a separate takeover flow.
        if _looks_sensitive(request) and request.action not in {"delete", "publish", "purchase"}:
            return self._action_result(
                request,
                app,
                session,
                status="denied",
                input_hash=input_hash,
                error_code="credential-input-requires-human",
                reason="credential or sensitive form input must be entered by the user in the application window",
                idem_key=idem_key,
            )

        if risk == "takeover":
            return self._action_result(request, app, session, status="denied", input_hash=input_hash, error_code="use-takeover-endpoint", reason="foreground takeover uses the explicit takeover endpoint", idem_key=idem_key)
        allowed, approval_id, reason = self._authorize_action(app, session, request, risk)
        if not allowed:
            return self._action_result(request, app, session, status="waiting-approval", input_hash=input_hash, error_code="approval-required", reason=reason, approval_id=approval_id, idem_key=None)

        started = time.monotonic()
        try:
            raw = adapter.act(session, request)
            if not isinstance(raw, Mapping):
                raw = {"value": raw}
            safe_raw = _safe_public(raw)
            output_hash = hash_value(safe_raw)
            raw_status = str(raw.get("status") or "").strip().lower()
            if raw.get("possibly_sent") is True or raw_status in {"unknown", "possibly-sent"}:
                status = "unknown"
                error_code = "possibly-sent"
                reason = "无法确认发送是否成功；不会自动重试或切换其他模型"
                retryable = False
            elif raw.get("completed") is True or raw_status == "completed":
                status = "completed"
                error_code = None
                reason = None
                retryable = False
            elif raw_status in {"accepted", "running"} or raw.get("accepted") is True or raw.get("ok") is True:
                # An app protocol commonly acknowledges that a command was
                # accepted before the application finishes it.  Preserve that
                # intermediate state; callers must observe a later explicit
                # completion event and may never replay it automatically.
                status = raw_status if raw_status in {"accepted", "running"} else "accepted"
                error_code = "action-accepted"
                reason = "动作已被应用接受，完成状态仍待观察"
                retryable = False
            else:
                status = "unknown"
                error_code = "action-status-unknown"
                reason = "适配器未提供明确的完成状态"
                retryable = False
            result = self._action_result(
                request,
                app,
                session,
                status=status,
                input_hash=input_hash,
                output_hash=output_hash,
                result=safe_raw,
                error_code=error_code,
                reason=reason,
                idem_key=idem_key,
                retryable=retryable,
                duration_ms=(time.monotonic() - started) * 1000,
                approval=request.approved or bool(approval_id),
            )
            return result
        except DesktopAutomationError as error:
            status = "unknown" if error.code in {"possibly-sent", "send-status-unknown"} else "failed"
            return self._action_result(request, app, session, status=status, input_hash=input_hash, error_code=error.code, reason=str(error), idem_key=idem_key if status != "unknown" else None, retryable=False, duration_ms=(time.monotonic() - started) * 1000)
        except Exception as error:
            self._log("desktop action failed", error)
            return self._action_result(request, app, session, status="failed", input_hash=input_hash, error_code="adapter-failed", reason="desktop adapter failed", idem_key=idem_key, retryable=False, duration_ms=(time.monotonic() - started) * 1000)

    def _authorize_action(self, app: DesktopApplication, session: DesktopSession, request: DesktopActionRequest, risk: str) -> tuple[bool, str | None, str]:
        if risk == "read":
            return True, None, "read-only action"
        if risk == "sensitive":
            if request.approved:
                return True, None, "explicit one-time approval"
            return False, self._new_pending(app, session, request), "敏感操作必须逐次确认"
        if request.approval_id:
            with self._lock:
                pending = self._pending.get(request.approval_id)
                matches = bool(
                    pending
                    and pending.get("approved") is True
                    and pending.get("session_id") == session.session_id
                    and pending.get("action") == request.action
                    and pending.get("input_sha256") == request.hash_input()
                )
                if matches:
                    self._pending.pop(request.approval_id, None)
                    return True, request.approval_id, "one-time approval"
        with self._lock:
            grant = self._permissions.get((app.app_id, "control"))
        if grant and not _expired(grant.get("expires_at")):
            return True, None, "application control grant"
        if request.approved:
            return True, None, "explicit one-time approval"
        return False, self._new_pending(app, session, request, risk=risk), "首次控制操作需要为该应用授予权限"

    def _new_pending(self, app: DesktopApplication, session: DesktopSession, request: DesktopActionRequest, *, risk: str | None = None) -> str:
        approval_id = f"desktop-approval-{uuid4().hex[:16]}"
        with self._lock:
            self._pending[approval_id] = {
                "approval_id": approval_id,
                "app_id": app.app_id,
                "session_id": session.session_id,
                "action": request.action,
                "risk": risk or ("sensitive" if _looks_sensitive(request) else request.risk),
                "input_sha256": request.hash_input(),
                "approved": False,
                "created_at": utc_now(),
            }
        self.audit.record(app_id=app.app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session.session_id, action="approval-request", risk=request.risk, status="waiting-approval", input_sha256=request.hash_input())
        return approval_id

    def _action_result(
        self,
        request: DesktopActionRequest,
        app: DesktopApplication,
        session: DesktopSession,
        *,
        status: str,
        input_hash: str,
        output_hash: str | None = None,
        result: Any = None,
        error_code: str | None = None,
        reason: str | None = None,
        approval_id: str | None = None,
        idem_key: str | None = None,
        retryable: bool = False,
        duration_ms: float | None = None,
        approval: bool = False,
    ) -> dict[str, Any]:
        value = DesktopActionResult(
            session_id=session.session_id,
            action=request.action,
            status=status,
            risk="sensitive" if _looks_sensitive(request) else request.risk,
            input_sha256=input_hash,
            output_sha256=output_hash,
            result=result,
            error_code=error_code,
            reason=reason,
            approval_id=approval_id,
            retryable=retryable,
        )
        if idem_key and status not in {"waiting-approval", "unknown"}:
            with self._lock:
                self._idempotency[idem_key] = value
                if len(self._idempotency) > 2048:
                    self._idempotency.pop(next(iter(self._idempotency)))
        self.audit.record(app_id=app.app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session.session_id, action=request.action, risk=value.risk, status=status, duration_ms=duration_ms, target=request.target, input_sha256=input_hash, output_sha256=output_hash, error_code=error_code, approval=approval)
        return value.to_dict()

    @staticmethod
    def _idempotency_key(session: DesktopSession, request: DesktopActionRequest) -> str | None:
        if not request.idempotency_key:
            return None
        return f"{session.session_id}:{request.idempotency_key}"

    # ------------------------------------------------------------------
    # Approval, takeover, and shutdown
    # ------------------------------------------------------------------
    def approval(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise DesktopAutomationError("approval request must be an object", code="invalid-approval")
        operation = str(value.get("operation") or value.get("action") or "list").strip().lower()
        if operation in {"list", "status"}:
            return {"schema": DESKTOP_AUTOMATION_SCHEMA, "permissions": self._permission_public(), "pending": self._pending_public()}
        if operation in {"grant", "revoke"}:
            app_id = safe_identifier(value.get("app_id") or value.get("appId"), "app_id")
            scope = safe_text(value.get("scope") or "control", "scope", 40, allow_empty=False).lower()
            if scope not in _PERMISSION_SCOPES:
                raise DesktopAutomationError("permission scope is invalid", code="invalid-permission-scope")
            if operation == "grant" and value.get("approved") is not True:
                raise DesktopPermissionError("granting desktop permission requires explicit approval", code="approval-required")
            confirm = value.get("confirm_app_id") or value.get("confirmAppId")
            if operation == "grant" and confirm not in (None, "") and str(confirm) != app_id:
                raise DesktopPermissionError("confirm_app_id does not match app_id", code="approval-mismatch")
            with self._lock:
                app = self._apps.get(app_id)
            if app is None:
                raise DesktopRegistrationError("desktop application is not registered", code="app-not-registered")
            if operation == "grant":
                expires_at = _iso_after(float(value.get("ttl_seconds") or 30 * 24 * 3600))
                grant = {"app_id": app_id, "scope": scope, "granted": True, "expires_at": expires_at, "granted_at": utc_now()}
                with self._lock:
                    self._permissions[(app_id, scope)] = grant
                self.audit.record(app_id=app_id, adapter_id=app.adapter_id, transport=app.transport, session_id=None, action="permission-grant", risk="control", status="completed", approval=True)
                return {"permission": dict(grant)}
            with self._lock:
                removed = self._permissions.pop((app_id, scope), None)
            return {"app_id": app_id, "scope": scope, "revoked": removed is not None}
        if operation in {"resolve", "approve", "deny"}:
            approval_id = safe_identifier(value.get("approval_id") or value.get("approvalId"), "approval_id")
            with self._lock:
                pending = self._pending.get(approval_id)
                if pending is None:
                    raise DesktopAutomationError("approval request is unknown", code="approval-not-found")
                pending["approved"] = operation in {"resolve", "approve"} and value.get("approved") is True
                pending["resolved_at"] = utc_now()
                result = dict(pending)
            return {"approval": {key: item for key, item in result.items() if key not in {"input_sha256"}}, "approved": bool(result.get("approved"))}
        raise DesktopAutomationError("approval operation is invalid", code="invalid-approval-operation")

    def takeover(self, session_id: str, *, enabled: bool = True, approved: bool = False) -> dict[str, Any]:
        session, app, adapter = self._get_session(session_id)
        if not isinstance(enabled, bool) or not isinstance(approved, bool):
            raise DesktopAutomationError("takeover flags must be boolean", code="invalid-takeover")
        if enabled and not self.foreground_takeover:
            raise DesktopPermissionError("foreground takeover is disabled", code="foreground-takeover-disabled")
        if not approved:
            return {"status": "waiting-approval", "session_id": session.session_id, "approval_id": self._new_pending(app, session, DesktopActionRequest(session.session_id, "takeover", approved=False), risk="takeover"), "reason": "前台鼠标键盘接管必须逐次确认"}
        try:
            result = adapter.takeover(session, enabled=enabled)
            with self._lock:
                session.foreground_takeover = enabled
            self.audit.record(app_id=app.app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session.session_id, action="takeover", risk="takeover", status="completed", approval=True)
            return {"status": "completed", "session": session.to_public(), "result": _safe_public(result)}
        except DesktopAutomationError as error:
            self.audit.record(app_id=app.app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session.session_id, action="takeover", risk="takeover", status="failed", error_code=error.code, approval=True)
            return {"status": "failed", "session_id": session.session_id, "error_code": error.code, "reason": str(error)}

    def close_session(self, session_id: str) -> dict[str, Any]:
        session, app, adapter = self._get_session(session_id)
        try:
            result = adapter.close(session)
            with self._lock:
                session.state = "closed"
                self._sessions.pop(session.session_id, None)
            self._release_lease(session.profile_key, session.lease_id, session.session_id)
            self.audit.record(app_id=app.app_id, adapter_id=app.adapter_id, transport=session.transport, session_id=session.session_id, action="close", risk="control", status="completed")
            return {"closed": True, "session_id": session.session_id, "result": _safe_public(result)}
        except DesktopAutomationError as error:
            return {"closed": False, "session_id": session.session_id, "error_code": error.code, "reason": str(error)}
        except Exception as error:
            self._log("desktop session close failed", error)
            return {"closed": False, "session_id": session.session_id, "error_code": "adapter-failed", "reason": "desktop adapter failed"}

    def _permission_public(self) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._permissions.values())
        return [{key: item for key, item in value.items() if key != "owner_token"} for value in values if not _expired(value.get("expires_at"))]

    def _pending_public(self) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._pending.values())
        return [{key: item for key, item in value.items() if key not in {"input_sha256"}} for value in values]

    def _persist_application(self, app: DesktopApplication) -> None:
        if self.storage is None or not callable(getattr(self.storage, "upsert_desktop_application", None)):
            return
        try:
            self.storage.upsert_desktop_application(app.to_record())
        except Exception as error:
            self._log("desktop application metadata write failed", error)

    def _persist_lease(self, lease: Mapping[str, Any]) -> None:
        if self.storage is None or not callable(getattr(self.storage, "upsert_desktop_automation_lease", None)):
            return
        try:
            self.storage.upsert_desktop_automation_lease(dict(lease))
        except Exception as error:
            self._log("desktop lease metadata write failed", error)

    def status(self) -> dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions.values())
            apps = list(self._apps.values())
            active_lease_count = sum(1 for lease in self._leases.values() if not _expired(lease.get("expires_at")))
        return {
            "schema": DESKTOP_AUTOMATION_SCHEMA,
            "state": "closed" if self._closed else "ready",
            "ready": not self._closed,
            "app_count": len(apps),
            "approved_app_count": sum(1 for app in apps if app.approved),
            "session_count": len(sessions),
            "active_lease_count": active_lease_count,
            "adapter_count": len(self._adapters),
            "foreground_takeover": self.foreground_takeover,
            "global_input": False,
            "audit": self.audit.status(),
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            sessions = list(self._sessions.values())
            self._closed = True
        for session in sessions:
            try:
                self.close_session(session.session_id)
            except Exception:
                pass
        with self._lock:
            adapters = list(self._adapters.values())
            self._sessions.clear()
            self._leases.clear()
        for adapter in adapters:
            try:
                adapter.shutdown()
            except Exception:
                pass
        self.audit.close()

    def _log(self, message: str, error: Exception) -> None:
        if self.logger is not None:
            try:
                self.logger.warning("%s error_type=%s", message, type(error).__name__)
            except Exception:
                pass

    def _log_info(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            try:
                self.logger.info(message, *args)
            except Exception:
                pass


__all__ = ["DesktopAutomationRuntime"]
