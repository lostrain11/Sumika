"""Fail-closed BrowserSkill policy boundary.

The first release does not embed a browser.  It records the exact policy that
will guard the pinned BrowserSkill backend, so a later bridge can be added
without granting global desktop input or silently accepting sensitive actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from .constants import (
    BROWSERSKILL_CLI_COMMIT,
    BROWSERSKILL_CLI_VERSION,
    BROWSERSKILL_COMMIT,
    BROWSERSKILL_DSH_PLUGIN_VERSION,
    BROWSERSKILL_EXTENSION_COMMIT,
    BROWSERSKILL_EXTENSION_VERSION,
)
from .policy import (
    BrowserPolicyError,
    BrowserPolicyEvaluator,
    normalize_domain,
)
from ..protocol.models import utc_now
from ..storage import Storage


class BrowserRuntimeError(RuntimeError):
    pass


class BrowserSkillClient:
    """Small JSON-only bridge to the user-installed ``bsk`` CLI.

    BrowserSkill owns the daemon, browser window, and extension connection.  The
    core only asks for health/session lifecycle information and never forwards
    page contents or credentials through this process.
    """

    def __init__(
        self,
        executable: str | None = None,
        *,
        runner: Any = None,
        timeout: float = 10.0,
        logger: Any = None,
    ) -> None:
        configured = executable or os.getenv("SUMIKA_BSK_EXECUTABLE")
        self.executable = configured or shutil.which("bsk")
        self.runner = runner or self._run
        self.timeout = timeout
        self.logger = logger

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def status(self) -> dict[str, Any]:
        value = self.runner(("status",))
        if not isinstance(value, dict):
            raise BrowserRuntimeError("BrowserSkill status was not an object")
        return value

    def start_session(
        self,
        *,
        browser: str | None = None,
        no_focus: bool = False,
    ) -> dict[str, Any]:
        args = ["session", "start"]
        if browser:
            args.extend(["--browser", str(browser)])
        if no_focus:
            args.append("--no-focus")
        value = self.runner(tuple(args))
        if not isinstance(value, dict):
            raise BrowserRuntimeError("BrowserSkill session start was not an object")
        return value

    def stop_session(self, session_id: str) -> dict[str, Any]:
        value = self.runner(("session", "stop", session_id))
        return value if isinstance(value, dict) else {"value": value}

    def list_tabs(self, session_id: str, *, scope: str | None = None) -> Any:
        args = ["tab", "list", "--session", session_id]
        if scope:
            args.extend(["--scope", scope])
        return self.runner(tuple(args))

    def create_tab(self, session_id: str, *, url: str | None = None, active: bool = True) -> Any:
        args = ["tab", "create", "--session", session_id]
        if url:
            args.extend(["--url", url])
        if not active:
            args.append("--no-active")
        return self.runner(tuple(args))

    def close_tab(self, session_id: str, tab_id: str) -> Any:
        return self.runner(("tab", "close", "--session", session_id, tab_id))

    def select_tab(self, session_id: str, tab_id: str) -> Any:
        return self.runner(("tab", "select", "--session", session_id, tab_id))

    def observe(self, session_id: str, *, tab_id: str | None = None, max_depth: int = 8, max_tokens: int = 2400) -> Any:
        args = ["observe", "--session", session_id, "--max-depth", str(max_depth), "--max-tokens", str(max_tokens)]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        return self.runner(tuple(args))

    def snapshot(self, session_id: str, *, tab_id: str | None = None, max_depth: int = 8, max_tokens: int = 2400) -> Any:
        args = ["snapshot", "--session", session_id, "--max-depth", str(max_depth), "--max-tokens", str(max_tokens)]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        return self.runner(tuple(args))

    def screenshot(self, session_id: str, *, tab_id: str | None = None, ref: str | None = None) -> Any:
        args = ["screenshot", "--session", session_id]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        if ref:
            args.extend(["--ref", ref])
        return self.runner(tuple(args))

    def console(self, session_id: str, *, tab_id: str | None = None, since: int | None = None, limit: int = 50) -> Any:
        args = ["console", "--session", session_id, "--limit", str(limit)]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        if since is not None:
            args.extend(["--since", str(since)])
        return self.runner(tuple(args))

    def network(self, session_id: str, *, tab_id: str | None = None, since: int | None = None, limit: int = 50) -> Any:
        args = ["network", "--session", session_id, "--limit", str(limit)]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        if since is not None:
            args.extend(["--since", str(since)])
        return self.runner(tuple(args))

    def navigate(self, session_id: str, url: str, *, tab_id: str | None = None) -> Any:
        args = ["navigate", "--session", session_id]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        args.append(url)
        return self.runner(tuple(args))

    def request_help(
        self,
        session_id: str,
        prompt: str,
        *,
        tab_id: str | None = None,
        title: str | None = None,
        targets: list[str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        args = ["request-help", "--session", session_id, "--prompt", prompt]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        if title:
            args.extend(["--title", title])
        for target in targets or []:
            args.extend(["--target", target])
        # Test doubles intentionally keep the one-argument runner contract.
        # The real client can use a longer timeout because human takeover may
        # remain open for several minutes.
        if timeout is not None and self.runner == self._run:
            return self._run(tuple(args), timeout=timeout)
        return self.runner(tuple(args))

    def click(self, session_id: str, target: str, *, tab_id: str | None = None) -> Any:
        args = ["click", "--session", session_id]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        args.append(target)
        return self.runner(tuple(args))

    def fill(self, session_id: str, target: str, value: str, *, tab_id: str | None = None) -> Any:
        args = ["fill", "--session", session_id, "--value", value]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        args.append(target)
        return self.runner(tuple(args))

    def select(self, session_id: str, target: str, values: list[str], *, tab_id: str | None = None) -> Any:
        args = ["select", "--session", session_id]
        for value in values:
            args.extend(["--value", value])
        if tab_id:
            args.extend(["--tab-id", tab_id])
        args.append(target)
        return self.runner(tuple(args))

    def press(self, session_id: str, key: str, *, tab_id: str | None = None, target: str | None = None) -> Any:
        args = ["press", "--session", session_id]
        if tab_id:
            args.extend(["--tab-id", tab_id])
        if target:
            args.extend(["--selector", target])
        args.append(key)
        return self.runner(tuple(args))

    def _run(self, args: tuple[str, ...], *, timeout: float | None = None) -> Any:
        if not self.executable:
            raise BrowserRuntimeError("BrowserSkill CLI is not installed or SUMIKA_BSK_EXECUTABLE is not set")
        try:
            completed = subprocess.run(
                [self.executable, *args, "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout if timeout is None else max(0.1, float(timeout)),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            if self.logger:
                self.logger.info("bsk command unavailable error_type=%s", type(error).__name__)
            raise BrowserRuntimeError("BrowserSkill CLI is unavailable") from error
        if completed.returncode != 0:
            if self.logger:
                self.logger.info("bsk command failed error_type=ProcessError")
            raise BrowserRuntimeError("BrowserSkill command failed")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise BrowserRuntimeError("BrowserSkill returned invalid JSON") from error


SENSITIVE_ACTIONS = {
    "first_visit", "cross_origin", "login", "submit", "send", "upload", "download", "purchase", "publish", "delete", "permission_change", "evaluate", "raw_cdp", "network_inspection", "console", "close_tab", "click", "fill", "select", "press",
}

_BROWSER_SECRET_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|(?:api[_ -]?key|token|password|secret|otp)\s*[:=]\s*[^\s,;]+)"
)
_BROWSER_MARKER_BLOCKED_KEY_RE = re.compile(
    r"(?i)(?:password|secret|token|cookie|authorization|api[_-]?key|apikey|otp|credential)"
)


def _snapshot_marker_hits(
    value: Any,
    marker_sets: dict[str, Any],
    *,
    depth: int = 0,
    budget: int = 24_000,
) -> dict[str, bool]:
    """Find adapter-owned markers without returning page text.

    BrowserSkill snapshots can put the useful controls well past the compact
    800-character UI projection.  Scan the bounded raw response inside Core,
    skip credential-bearing branches, and expose only booleans to callers.
    """

    normalized: dict[str, tuple[str, ...]] = {}
    for raw_name, raw_markers in (marker_sets or {}).items():
        name = str(raw_name or "").strip()[:80]
        if not name:
            continue
        if isinstance(raw_markers, str):
            raw_markers = (raw_markers,)
        if not isinstance(raw_markers, (list, tuple, set, frozenset)):
            continue
        markers: list[str] = []
        for raw_marker in list(raw_markers)[:32]:
            marker = str(raw_marker or "").strip()[:200]
            if marker and marker.casefold() not in {item.casefold() for item in markers}:
                markers.append(marker)
        normalized[name] = tuple(markers)
    found = {name: False for name in normalized}
    if not found:
        return found

    remaining = [max(0, int(budget))]

    def visit(node: Any, level: int) -> None:
        if level > 6 or remaining[0] <= 0 or all(found.values()):
            return
        if isinstance(node, str):
            text = node.strip()
            if not text:
                return
            take = min(len(text), remaining[0])
            # Preserve both ends when a single serialized snapshot string is
            # larger than the scan budget; controls commonly occur at either
            # the beginning or the end of an ARIA tree.
            if take < len(text):
                half = max(1, take // 2)
                sample = f"{text[:half]}\n{text[-(take - half):]}"
            else:
                sample = text
            remaining[0] -= take
            folded = sample.casefold()
            for name, markers in normalized.items():
                if not found[name] and any(marker.casefold() in folded for marker in markers):
                    found[name] = True
            return
        if isinstance(node, dict):
            for key, item in list(node.items())[:96]:
                if _BROWSER_MARKER_BLOCKED_KEY_RE.search(str(key)):
                    continue
                visit(item, level + 1)
                if remaining[0] <= 0 or all(found.values()):
                    break
            return
        if isinstance(node, (list, tuple, set, frozenset)):
            for item in list(node)[:192]:
                visit(item, level + 1)
                if remaining[0] <= 0 or all(found.values()):
                    break

    visit(value, depth)
    return found


def _compact_browser_tab(value: dict[str, Any]) -> dict[str, Any] | None:
    tab_id = str(value.get("id") or value.get("tab_id") or "").strip()
    if not tab_id:
        return None
    result = {"id": tab_id[:160]}
    for source, target, limit in (
        ("title", "title", 240),
        ("url", "url", 1000),
        ("active", "active", 20),
        ("scope", "scope", 80),
    ):
        item = value.get(source)
        if isinstance(item, (str, bool)):
            result[target] = _compact_browser_url(item, limit) if target == "url" else _compact_browser_text(item, limit)
    return result


def _compact_browser_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _BROWSER_SECRET_RE.sub("[redacted]", text)
    if len(text) > limit:
        text = f"{text[: max(1, limit - 1)]}…"
    return text


def _compact_browser_url(value: Any, limit: int = 1200) -> str:
    """Redact credentials from URLs before they cross the core boundary."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return _compact_browser_text(raw, limit)
    if parsed.scheme not in {"http", "https"}:
        return _compact_browser_text(raw, limit)
    sensitive_names = {"token", "access_token", "api_key", "apikey", "key", "secret", "password", "otp", "code"}
    query = []
    for name, item in parse_qsl(parsed.query, keep_blank_values=True):
        query.append((name, "[redacted]" if name.lower() in sensitive_names else item))
    safe = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), ""))
    return _compact_browser_text(safe, limit)


def _is_new_tab_url(value: str, parsed: Any | None = None) -> bool:
    """Allow only the browser's inert new-tab page for internal URLs."""

    candidate = parsed or urlparse(value)
    return (
        str(value) == "chrome://newtab/"
        and candidate.scheme.lower() == "chrome"
        and candidate.netloc.lower() == "newtab"
        and candidate.path == "/"
        and not candidate.params
        and not candidate.query
        and not candidate.fragment
    )


def _looks_like_sensitive_input(target: str | None) -> bool:
    if not target:
        return False
    return bool(re.search(r"(?i)(password|passwd|passcode|otp|one[-_ ]?time|secret|token|api[-_ ]?key|verification|captcha)", target))


def _compact_browser_value(value: Any, *, depth: int = 0) -> Any:
    """Bound BrowserSkill observations before they reach the UI."""

    if depth > 5:
        return "[truncated]"
    if isinstance(value, str):
        return _compact_browser_text(value, 800)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_browser_value(item, depth=depth + 1) for item in value[:48]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            normalized = str(key).lower()
            if normalized in {"data", "image", "image_data", "data_uri", "base64", "base64_data", "png_bytes", "jpeg_bytes", "buffer"} or any(token in normalized for token in ("base64", "data_uri", "image_data", "png_bytes", "jpeg_bytes")):
                result[str(key)] = "[omitted binary payload]"
                continue
            if any(token in normalized for token in ("password", "secret", "token", "cookie", "authorization", "api_key", "apikey", "otp")):
                result[str(key)] = "[redacted]"
                continue
            if normalized in {"url", "source_url", "request_url", "document_url", "referrer"}:
                result[str(key)] = _compact_browser_url(item)
            else:
                result[str(key)] = _compact_browser_value(item, depth=depth + 1)
        return result
    return _compact_browser_text(value, 400)


def _compact_screenshot_value(value: Any, *, depth: int = 0) -> Any:
    """Project screenshot metadata without returning local filesystem paths."""

    if depth > 5:
        return "[truncated]"
    if isinstance(value, str):
        text = _compact_browser_text(value, 800)
        if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", text):
            return "[omitted local path]"
        return text
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_screenshot_value(item, depth=depth + 1) for item in value[:48]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            normalized = str(key).lower()
            if normalized in {"data", "image", "image_data", "data_uri", "base64", "base64_data", "png_bytes", "jpeg_bytes", "buffer"} or any(token in normalized for token in ("base64", "data_uri", "image_data", "png_bytes", "jpeg_bytes")):
                result[str(key)] = "[omitted binary payload]"
            elif normalized in {"path", "file", "filename", "filepath", "file_path", "saved_to", "output_path", "screenshot_path"}:
                result[str(key)] = "[omitted local path]"
            elif normalized in {"url", "source_url", "request_url", "document_url", "referrer"}:
                result[str(key)] = _compact_browser_url(item)
            else:
                result[str(key)] = _compact_screenshot_value(item, depth=depth + 1)
        return result
    return _compact_browser_text(value, 400)


class BrowserRuntime:
    PROFILE_LEASE_TTL = timedelta(minutes=30)

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        logger: Any = None,
        browser_skill: BrowserSkillClient | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else None
        self.logger = logger
        self.storage = storage
        self.sessions: dict[str, dict[str, Any]] = {}
        self.profile_leases: dict[str, dict[str, str]] = {}
        self.owner_token = f"sumika-{uuid4().hex}"
        self.browser_profiles: dict[str, dict[str, Any]] = {
            str(item["id"]): dict(item)
            for item in (storage.list_browser_profiles(include_archived=True) if storage else [])
        }
        self.downloads: dict[str, dict[str, Any]] = {}
        self.quarantine_dir = (self.data_dir / "browser" / "quarantine") if self.data_dir else None
        self.allowlist: set[str] = set()
        self.enabled = os.getenv("SUMIKA_BROWSER_ENABLED", "1").lower() not in {"0", "false", "no"}
        self.policy = BrowserPolicyEvaluator(enabled=self.enabled, allowlist=self.allowlist)
        self.browser_skill = browser_skill or BrowserSkillClient(logger=logger)
        self._backend_status_cache: tuple[str, str | None, int] | None = None
        self._backend_status_at = 0.0
        self._backend_status_ttl = 5.0

    def status(self) -> dict[str, Any]:
        self.cleanup_expired()
        backend_state = "not-installed"
        backend_reason = "BrowserSkill CLI 未安装"
        browser_count = 0
        if self.enabled and self.browser_skill.available:
            cached = self._backend_status_cache
            if cached is not None and time.monotonic() - self._backend_status_at < self._backend_status_ttl:
                backend_state, backend_reason, browser_count = cached
            else:
                try:
                    backend = self.browser_skill.status()
                    browsers = backend.get("browsers") if isinstance(backend.get("browsers"), list) else []
                    browser_count = len(browsers)
                    if browser_count:
                        backend_state = "ready"
                        backend_reason = None
                    else:
                        backend_state = "awaiting-extension"
                        backend_reason = "请在 Chrome 或 Edge 中安装并连接 BrowserSkill 扩展"
                    self._backend_status_cache = (backend_state, backend_reason, browser_count)
                    self._backend_status_at = time.monotonic()
                except BrowserRuntimeError as error:
                    backend_state = "unavailable"
                    backend_reason = str(error)
        state = "disabled" if not self.enabled else (backend_state if self.browser_skill.available else "policy-only")
        return {
            "state": state,
            "ready": bool(self.enabled and backend_state == "ready"),
            "backend": "BrowserSkill",
            "backend_repository": "https://github.com/tencent/BrowserSkill",
            "backend_commit": BROWSERSKILL_COMMIT,
            "cli_version": BROWSERSKILL_CLI_VERSION,
            "cli_commit": BROWSERSKILL_CLI_COMMIT,
            "dsh_plugin_version": BROWSERSKILL_DSH_PLUGIN_VERSION,
            "extension_version": BROWSERSKILL_EXTENSION_VERSION,
            "extension_commit": BROWSERSKILL_EXTENSION_COMMIT,
            "auto_update": False,
            "global_desktop_control": False,
            "cli_available": bool(self.browser_skill.available),
            "cli_path": self.browser_skill.executable,
            "backend_state": backend_state,
            "backend_reason": backend_reason,
            "policy_bridge": {
                "rpc_method": "browser.policy.evaluate",
                "fail_closed": True,
                "metadata_only": True,
                "dsh_plugin": "sumika-dsh-browser-policy",
            },
            "browser_count": browser_count,
            "temporary_profile_retention_hours": 24,
            "active_sessions": len(self.sessions),
            "named_profiles": len(self.list_profiles()),
            "active_named_leases": sum(
                1 for profile in self.list_profiles() if profile.get("leased")
            ),
            "quarantined_downloads": sum(1 for item in self.downloads.values() if item["status"] == "quarantine"),
        }

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        if self.storage:
            self.storage.delete_expired_browser_profile_leases(now=now.isoformat())
        expired = [
            session_id
            for session_id, item in self.sessions.items()
            if item.get("profile") == "temporary"
            and item.get("expires_at")
            and datetime.fromisoformat(str(item["expires_at"])) <= now
        ]
        expired.extend(
            session_id
            for session_id, item in self.sessions.items()
            if item.get("profile") == "named"
            and item.get("lease_expires_at")
            and datetime.fromisoformat(str(item["lease_expires_at"])) <= now
        )
        for session_id in expired:
            try:
                self.close_session(session_id)
            except BrowserRuntimeError as error:
                if self.logger:
                    self.logger.warning(
                        "browser expired session cleanup failed error_type=%s",
                        type(error).__name__,
                    )
        return len(expired)

    def list_profiles(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        if self.storage:
            profiles = self.storage.list_browser_profiles(include_archived=include_archived)
            self.browser_profiles = {str(item["id"]): dict(item) for item in profiles}
        else:
            profiles = list(self.browser_profiles.values())
            if not include_archived:
                profiles = [item for item in profiles if item.get("archived_at") is None]
        now = datetime.now(timezone.utc)
        result: list[dict[str, Any]] = []
        for profile in profiles:
            lease = self._profile_lease(str(profile["id"]))
            lease_expires_at = str(lease.get("expires_at")) if lease else None
            leased = bool(lease and self._lease_is_active(lease, now=now))
            result.append(
                {
                    **profile,
                    "leased": leased,
                    "lease_expires_at": lease_expires_at if leased else None,
                }
            )
        return result

    def create_profile(
        self,
        *,
        name: str,
        character_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise BrowserRuntimeError("named browser profile requires a name")
        if len(normalized_name) > 100:
            raise BrowserRuntimeError("named browser profile name is too long")
        normalized_character = str(character_id or "").strip() or None
        normalized_agent = str(agent_id or "").strip() or None
        if not normalized_character and not normalized_agent:
            raise BrowserRuntimeError("named browser profile requires character_id or agent_id authorization")
        profile_id = f"browser-profile-{uuid4().hex[:12]}"
        if self.storage:
            profile = self.storage.create_browser_profile(
                profile_id=profile_id,
                name=normalized_name,
                character_id=normalized_character,
                agent_id=normalized_agent,
            )
        else:
            now = utc_now()
            profile = {
                "id": profile_id,
                "name": normalized_name,
                "character_id": normalized_character,
                "agent_id": normalized_agent,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "last_used_at": None,
                "archived_at": None,
            }
        self.browser_profiles[profile_id] = dict(profile)
        return {**profile, "leased": False, "lease_expires_at": None}

    def archive_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self._get_profile(profile_id)
        if profile is None:
            raise BrowserRuntimeError("unknown named browser profile")
        if any(item.get("profile_id") == profile_id for item in self.sessions.values()):
            raise BrowserRuntimeError("cannot archive a profile with an active session")
        if self._profile_lease(profile_id):
            raise BrowserRuntimeError("cannot archive a profile with an active write lease")
        if self.storage:
            updated = self.storage.update_browser_profile_state(profile_id, archived=True)
            assert updated is not None
            profile = updated
        else:
            profile = {**profile, "status": "archived", "archived_at": utc_now(), "updated_at": utc_now()}
            self.browser_profiles[profile_id] = profile
        return {**profile, "leased": False, "lease_expires_at": None}

    def restore_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self._get_profile(profile_id)
        if profile is None:
            raise BrowserRuntimeError("unknown named browser profile")
        if self.storage:
            updated = self.storage.update_browser_profile_state(profile_id, archived=False)
            assert updated is not None
            profile = updated
        else:
            profile = {**profile, "status": "active", "archived_at": None, "updated_at": utc_now()}
            self.browser_profiles[profile_id] = profile
        return {**profile, "leased": False, "lease_expires_at": None}

    def _get_profile(self, profile_id: str | None) -> dict[str, Any] | None:
        normalized = str(profile_id or "").strip()
        if not normalized:
            return None
        if self.storage:
            profile = self.storage.get_browser_profile(normalized)
            if profile is not None:
                self.browser_profiles[normalized] = dict(profile)
            return profile
        return self.browser_profiles.get(normalized)

    @staticmethod
    def _lease_is_active(lease: dict[str, Any], *, now: datetime | None = None) -> bool:
        try:
            expires_at = datetime.fromisoformat(str(lease.get("expires_at") or ""))
        except ValueError:
            return False
        return expires_at > (now or datetime.now(timezone.utc))

    def _profile_lease(self, profile_id: str) -> dict[str, Any] | None:
        lease = self.storage.get_browser_profile_lease(profile_id) if self.storage else self.profile_leases.get(profile_id)
        if lease and not self._lease_is_active(lease):
            if self.storage:
                self.storage.delete_expired_browser_profile_leases()
                lease = self.storage.get_browser_profile_lease(profile_id)
            else:
                self.profile_leases.pop(profile_id, None)
                lease = None
        return dict(lease) if lease else None

    def _acquire_profile_lease(self, lease: dict[str, str]) -> dict[str, Any] | None:
        profile_id = str(lease["profile_id"])
        if self.storage:
            acquired = self.storage.acquire_browser_profile_lease(
                profile_id=profile_id,
                lease_id=str(lease["lease_id"]),
                owner_token=str(lease["owner_token"]),
                expires_at=str(lease["expires_at"]),
            )
        else:
            current = self._profile_lease(profile_id)
            acquired = None if current else dict(lease)
            if acquired:
                self.profile_leases[profile_id] = dict(acquired)
        if acquired:
            self.profile_leases[profile_id] = {
                "lease_id": str(acquired["lease_id"]),
                "owner_token": str(acquired["owner_token"]),
                "expires_at": str(acquired["expires_at"]),
            }
        return acquired

    def _release_profile_lease(self, profile_id: str, lease_id: str) -> None:
        lease = self.profile_leases.get(profile_id)
        if self.storage:
            self.storage.release_browser_profile_lease(
                profile_id=profile_id,
                lease_id=lease_id,
                owner_token=self.owner_token,
            )
        self.profile_leases.pop(profile_id, None)

    def _renew_profile_lease(self, item: dict[str, Any]) -> None:
        if item.get("profile") != "named" or not item.get("profile_id"):
            return
        profile_id = str(item["profile_id"])
        lease_id = str(item["id"])
        expires_at = (datetime.now(timezone.utc) + self.PROFILE_LEASE_TTL).isoformat()
        if self.storage:
            renewed = self.storage.renew_browser_profile_lease(
                profile_id=profile_id,
                lease_id=lease_id,
                owner_token=self.owner_token,
                expires_at=expires_at,
            )
            if renewed is None:
                raise BrowserRuntimeError("named browser profile write lease has expired")
        elif not self.profile_leases.get(profile_id):
            raise BrowserRuntimeError("named browser profile write lease has expired")
        self.profile_leases[profile_id] = {
            "lease_id": lease_id,
            "owner_token": self.owner_token,
            "expires_at": expires_at,
        }
        item["lease_expires_at"] = expires_at

    @staticmethod
    def _check_profile_authorization(
        profile: dict[str, Any], *, character_id: str | None, agent_id: str | None
    ) -> None:
        expected_character = str(profile.get("character_id") or "").strip() or None
        expected_agent = str(profile.get("agent_id") or "").strip() or None
        if expected_character and str(character_id or "").strip() != expected_character:
            raise BrowserRuntimeError("named browser profile is authorized for another character")
        if expected_agent and str(agent_id or "").strip() != expected_agent:
            raise BrowserRuntimeError("named browser profile is authorized for another Agent")

    def close(self) -> None:
        """Stop owned backend sessions and release named Profile leases."""

        for session_id in list(self.sessions):
            try:
                self.close_session(session_id)
            except BrowserRuntimeError as error:
                if self.logger:
                    self.logger.warning(
                        "browser session shutdown skipped error_type=%s",
                        type(error).__name__,
                    )
                item = self.sessions.pop(session_id, None)
                if item and item.get("profile") == "named" and item.get("profile_id"):
                    self._release_profile_lease(str(item["profile_id"]), session_id)
        for profile_id, lease in list(self.profile_leases.items()):
            self._release_profile_lease(profile_id, str(lease.get("lease_id") or ""))

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return UI-safe metadata for sessions owned by this core instance."""

        self.cleanup_expired()
        sessions = [dict(item) for item in self.sessions.values()]
        sessions.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        for item in sessions:
            # The BrowserSkill id is an implementation detail and is not needed
            # by the UI; keep it inside the runtime for stop_session only.
            item.pop("backend_session_id", None)
        return sessions

    def create_session(
        self,
        *,
        profile: str = "temporary",
        profile_id: str | None = None,
        character_id: str | None = None,
        agent_id: str | None = None,
        browser_instance: str | None = None,
        approved: bool = False,
        no_focus: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise BrowserRuntimeError("Browser runtime is disabled")
        if profile not in {"temporary", "named"}:
            raise BrowserRuntimeError("profile must be temporary or named")
        named_profile = None
        if profile == "named":
            if not approved:
                raise BrowserRuntimeError("starting a named browser profile requires explicit approval")
            if not profile_id:
                raise BrowserRuntimeError("named browser session requires profile_id")
            named_profile = self._get_profile(profile_id)
            if named_profile is None or named_profile.get("archived_at") is not None or named_profile.get("status") != "active":
                raise BrowserRuntimeError("named browser profile is unavailable")
            self._check_profile_authorization(named_profile, character_id=character_id, agent_id=agent_id)
        session_id = f"browser-{uuid4().hex[:12]}"
        backend_session_id = None
        state = "awaiting-browser-backend"
        lease_expires_at = None
        if named_profile is not None:
            lease_expires_at = (datetime.now(timezone.utc) + self.PROFILE_LEASE_TTL).isoformat()
            lease = {
                "profile_id": str(named_profile["id"]),
                "lease_id": session_id,
                "owner_token": self.owner_token,
                "expires_at": lease_expires_at,
            }
            acquired = self._acquire_profile_lease(lease)
            if acquired is None:
                raise BrowserRuntimeError("named browser profile is already in use")
        if self.status()["ready"]:
            try:
                backend_session = (
                    self.browser_skill.start_session(browser=browser_instance, no_focus=bool(no_focus))
                    if browser_instance
                    else self.browser_skill.start_session(no_focus=bool(no_focus))
                )
                backend_session_id = str(backend_session.get("id") or backend_session.get("session_id") or "") or None
                if backend_session_id:
                    state = "ready"
            except BrowserRuntimeError as error:
                if named_profile is not None:
                    self._release_profile_lease(str(named_profile["id"]), session_id)
                raise BrowserRuntimeError(f"BrowserSkill session could not start: {error}") from error
        item = {
            "id": session_id,
            "profile": profile,
            "profile_id": f"temporary-{session_id}" if profile == "temporary" else str(named_profile["id"]),
            "character_id": character_id,
            "agent_id": agent_id,
            "browser_instance": str(browser_instance or "").strip() or None,
            "backend_session_id": backend_session_id,
            "state": state,
            "created_at": utc_now(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat() if profile == "temporary" else None,
            "lease_expires_at": lease_expires_at,
        }
        self.sessions[session_id] = item
        return dict(item)

    def focus_session(self, session_id: str, *, tab_id: str | None = None) -> dict[str, Any]:
        """Focus an owned Agent Window by selecting one of its tabs.

        BrowserSkill does not expose a separate OS-window focus RPC. Selecting
        the requested tab is the stable public operation and keeps this bridge
        honest about that limitation.
        """

        item = self._session(session_id)
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "focused": False, "reason": "BrowserSkill session is not connected"}
        selected = str(tab_id or "").strip()
        if not selected:
            tabs = self.list_tabs(session_id).get("tabs", [])
            selected = str(next((tab.get("id") for tab in tabs if isinstance(tab, dict) and tab.get("active")), "") or "")
            if not selected and tabs:
                selected = str(tabs[0].get("id") or "")
        if not selected:
            return {"session_id": session_id, "focused": False, "reason": "no-tab"}
        try:
            result = self.browser_skill.select_tab(str(backend_session_id), selected)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill window focus failed: {error}") from error
        return {"session_id": session_id, "tab_id": selected, "focused": True, "result": _compact_browser_value(result)}

    def close_session(self, session_id: str) -> dict[str, Any]:
        item = self.sessions.get(session_id)
        if item is None:
            raise BrowserRuntimeError("unknown browser session")
        backend_session_id = item.get("backend_session_id")
        if backend_session_id:
            try:
                self.browser_skill.stop_session(str(backend_session_id))
            except BrowserRuntimeError as error:
                raise BrowserRuntimeError(f"BrowserSkill session could not stop: {error}") from error
        self.sessions.pop(session_id, None)
        profile_id = item.get("profile_id")
        if item.get("profile") == "named" and profile_id:
            self._release_profile_lease(str(profile_id), session_id)
            if self.storage:
                self.storage.update_browser_profile_state(str(profile_id), mark_used=True)
            elif profile_id in self.browser_profiles:
                self.browser_profiles[profile_id] = {
                    **self.browser_profiles[profile_id],
                    "last_used_at": utc_now(),
                    "updated_at": utc_now(),
                }
        return {"id": session_id, "closed": True}

    def list_tabs(self, session_id: str, *, scope: str | None = None) -> dict[str, Any]:
        item = self._session(session_id)
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "ready": False, "tabs": [], "reason": "BrowserSkill session is not connected"}
        try:
            value = self.browser_skill.list_tabs(str(backend_session_id), scope=scope)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill tab list failed: {error}") from error
        raw_tabs = value.get("tabs") if isinstance(value, dict) else value
        tabs = [_compact_browser_tab(tab) for tab in raw_tabs or [] if isinstance(tab, dict)]
        return {"session_id": session_id, "ready": True, "tabs": [tab for tab in tabs if tab is not None]}

    def create_tab(self, session_id: str, *, url: str | None = None, approved: bool = False, active: bool = True) -> dict[str, Any]:
        item = self._session(session_id)
        value = str(url or "").strip() or "chrome://newtab/"
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"}:
            if parsed.username or parsed.password:
                raise BrowserRuntimeError("browser tab URL must not contain embedded credentials")
            policy = self.check_action(session_id=session_id, action="navigate", domain=(parsed.hostname or "").lower(), approved=approved)
            if not policy["allowed"]:
                return {"session_id": session_id, "executed": False, "policy": policy, "url": _compact_browser_url(value)}
        elif not _is_new_tab_url(value, parsed):
            raise BrowserRuntimeError("new tab URL must be http(s) or chrome://newtab/")
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "executed": False, "reason": "BrowserSkill session is not connected"}
        try:
            result = self.browser_skill.create_tab(str(backend_session_id), url=value, active=active)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill tab create failed: {error}") from error
        return {"session_id": session_id, "executed": True, "url": _compact_browser_url(value), "result": _compact_browser_value(result)}

    def close_tab(self, session_id: str, *, tab_id: str, approved: bool = False) -> dict[str, Any]:
        item = self._session(session_id)
        tab_id = str(tab_id or "").strip()
        if not tab_id:
            raise BrowserRuntimeError("tab_id is required")
        policy = self.check_action(session_id=session_id, action="close_tab", approved=approved)
        if not policy["allowed"]:
            return {"session_id": session_id, "executed": False, "tab_id": tab_id, "policy": policy}
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "executed": False, "tab_id": tab_id, "reason": "BrowserSkill session is not connected"}
        try:
            result = self.browser_skill.close_tab(str(backend_session_id), tab_id)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill tab close failed: {error}") from error
        return {"session_id": session_id, "executed": True, "tab_id": tab_id, "result": _compact_browser_value(result)}

    def select_tab(self, session_id: str, *, tab_id: str) -> dict[str, Any]:
        item = self._session(session_id)
        tab_id = str(tab_id or "").strip()
        if not tab_id:
            raise BrowserRuntimeError("tab_id is required")
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "executed": False, "tab_id": tab_id, "reason": "BrowserSkill session is not connected"}
        try:
            result = self.browser_skill.select_tab(str(backend_session_id), tab_id)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill tab select failed: {error}") from error
        return {"session_id": session_id, "executed": True, "tab_id": tab_id, "result": _compact_browser_value(result)}

    def observe_session(self, session_id: str, *, tab_id: str | None = None) -> dict[str, Any]:
        item = self._session(session_id)
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "ready": False, "observation": None, "reason": "BrowserSkill session is not connected"}
        try:
            value = self.browser_skill.observe(str(backend_session_id), tab_id=tab_id)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill observe failed: {error}") from error
        return {
            "session_id": session_id,
            "ready": True,
            "tab_id": tab_id,
            "observation": _compact_browser_value(value),
        }

    def snapshot_session(
        self,
        session_id: str,
        *,
        tab_id: str | None = None,
        marker_sets: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = self._session(session_id)
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "ready": False, "snapshot": None, "reason": "BrowserSkill session is not connected"}
        try:
            value = self.browser_skill.snapshot(str(backend_session_id), tab_id=tab_id)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill snapshot failed: {error}") from error
        result = {
            "session_id": session_id,
            "ready": True,
            "tab_id": tab_id,
            "snapshot": _compact_browser_value(value),
        }
        if marker_sets:
            result["marker_hits"] = _snapshot_marker_hits(value, marker_sets)
        return result

    def screenshot_session(self, session_id: str, *, tab_id: str | None = None, ref: str | None = None) -> dict[str, Any]:
        item = self._session(session_id)
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "ready": False, "screenshot": None, "reason": "BrowserSkill session is not connected"}
        try:
            value = self.browser_skill.screenshot(str(backend_session_id), tab_id=tab_id, ref=ref)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill screenshot failed: {error}") from error
        return {"session_id": session_id, "ready": True, "tab_id": tab_id, "ref": _compact_browser_text(ref, 120) if ref else None, "screenshot": _compact_screenshot_value(value)}

    def _diagnostic_stream(
        self,
        session_id: str,
        *,
        stream: str,
        tab_id: str | None = None,
        since: int | None = None,
        limit: int = 50,
        developer_mode: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not developer_mode:
            return {"session_id": session_id, "executed": False, "requires_developer_mode": True, "stream": stream}
        item = self._session(session_id)
        policy = self.check_action(session_id=session_id, action=stream, approved=approved)
        if not policy["allowed"]:
            return {"session_id": session_id, "executed": False, "policy": policy, "stream": stream}
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "executed": False, "stream": stream, "reason": "BrowserSkill session is not connected"}
        try:
            if stream == "console":
                value = self.browser_skill.console(str(backend_session_id), tab_id=tab_id, since=since, limit=limit)
            else:
                value = self.browser_skill.network(str(backend_session_id), tab_id=tab_id, since=since, limit=limit)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill {stream} read failed: {error}") from error
        return {"session_id": session_id, "executed": True, "stream": stream, "tab_id": tab_id, "result": _compact_browser_value(value)}

    def read_console(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._diagnostic_stream(session_id, stream="console", **kwargs)

    def read_network(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._diagnostic_stream(session_id, stream="network_inspection", **kwargs)

    def navigate_session(self, session_id: str, *, url: str, approved: bool = False, tab_id: str | None = None) -> dict[str, Any]:
        item = self._session(session_id)
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise BrowserRuntimeError("navigation requires an http(s) URL")
        if parsed.username or parsed.password:
            raise BrowserRuntimeError("navigation URL must not contain embedded credentials")
        domain = parsed.hostname.lower()
        policy = self.check_action(session_id=session_id, action="navigate", domain=domain, approved=approved)
        if not policy["allowed"]:
            return {"session_id": session_id, "executed": False, "policy": policy}
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "executed": False, "policy": policy, "reason": "BrowserSkill session is not connected"}
        try:
            value = self.browser_skill.navigate(str(backend_session_id), url.strip(), tab_id=tab_id)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill navigation failed: {error}") from error
        return {
            "session_id": session_id,
            "executed": True,
            "domain": domain,
            "tab_id": tab_id,
            "result": _compact_browser_value(value),
        }

    def execute_action(
        self,
        session_id: str,
        *,
        action: str,
        target: str | None = None,
        value: str | None = None,
        values: list[str] | None = None,
        key: str | None = None,
        approved: bool = False,
        tab_id: str | None = None,
    ) -> dict[str, Any]:
        item = self._session(session_id)
        action = action.strip().lower()
        if action not in {"click", "fill", "select", "press"}:
            raise BrowserRuntimeError("browser action must be click, fill, select, or press")
        target = str(target or "").strip() or None
        if action in {"click", "fill", "select"} and not target:
            raise BrowserRuntimeError(f"{action} requires a snapshot ref or selector")
        if action == "fill" and (value is None or not str(value)):
            raise BrowserRuntimeError("fill requires a value")
        if action == "select" and (not isinstance(values, list) or not values or not all(isinstance(entry, str) and entry for entry in values)):
            raise BrowserRuntimeError("select requires one or more option values")
        if action == "press" and not str(key or "").strip():
            raise BrowserRuntimeError("press requires a key")
        if action == "fill" and _looks_like_sensitive_input(target):
            return {
                "session_id": session_id,
                "executed": False,
                "requires_human": True,
                "reason": "密码、OTP 和凭据字段必须在隔离窗口中由用户输入",
                "action": action,
            }
        policy = self.check_action(session_id=session_id, action=action, approved=approved)
        if not policy["allowed"]:
            return {"session_id": session_id, "executed": False, "policy": policy, "action": action}
        backend_session_id = item.get("backend_session_id")
        if not backend_session_id:
            return {"session_id": session_id, "executed": False, "reason": "BrowserSkill session is not connected", "action": action}
        try:
            if action == "click":
                result = self.browser_skill.click(str(backend_session_id), target or "", tab_id=tab_id)
            elif action == "fill":
                result = self.browser_skill.fill(str(backend_session_id), target or "", str(value), tab_id=tab_id)
            elif action == "select":
                result = self.browser_skill.select(str(backend_session_id), target or "", values or [], tab_id=tab_id)
            else:
                result = self.browser_skill.press(str(backend_session_id), str(key), tab_id=tab_id, target=target)
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill {action} failed: {error}") from error
        return {
            "session_id": session_id,
            "executed": True,
            "action": action,
            "target": target,
            "result": _compact_browser_value(result),
        }

    def check_action(self, *, session_id: str, action: str, domain: str | None = None, approved: bool = False) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise BrowserRuntimeError("unknown browser session")
        action = action.strip().lower()
        if not action:
            raise BrowserRuntimeError("action is required")
        allowed_domain = not domain or domain in self.allowlist
        sensitive = action in SENSITIVE_ACTIONS or not allowed_domain
        return {
            "allowed": bool(self.enabled and approved) if sensitive else bool(self.enabled),
            "requires_approval": sensitive,
            "reason": "用户批准后才能执行敏感或跨域操作" if sensitive else "已批准域名内的只读浏览操作",
            "action": action,
            "domain": domain,
            "global_desktop_control": False,
        }

    def evaluate_policy(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a redacted policy request from a Harness adapter.

        A local Sumika session is authoritative when present.  External DSH
        sessions may set ``session_known`` only after the DSH BrowserSkill
        plugin has established ownership in its own process; no page payload
        or credential value is accepted here.
        """

        if not isinstance(metadata, dict):
            raise BrowserRuntimeError("browser policy metadata must be an object")
        payload = dict(metadata)
        session_id = payload.get("session_id")
        if isinstance(session_id, str) and session_id.strip() in self.sessions:
            payload["session_known"] = True
        self.policy.enabled = self.enabled
        self.policy.allowlist = set(self.allowlist)
        try:
            return self.policy.evaluate(payload)
        except BrowserPolicyError as error:
            raise BrowserRuntimeError(str(error)) from error

    def request_external_help(
        self,
        *,
        session_id: str,
        domain: str | None,
        reason: str,
        title: str | None = None,
        targets: list[str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Ask BrowserSkill to show its human takeover surface for a DSH session.

        The DSH policy plugin owns the session registry.  Core only accepts a
        bounded identifier and forwards the request to the already configured
        loopback BrowserSkill CLI; the prompt is never persisted or logged.
        """

        if not self.enabled:
            raise BrowserRuntimeError("Browser runtime is disabled")
        normalized_session = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", normalized_session):
            raise BrowserRuntimeError("external browser session id is invalid")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason or len(normalized_reason) > 2000:
            raise BrowserRuntimeError("human takeover reason must be between 1 and 2000 characters")
        if _BROWSER_SECRET_RE.search(normalized_reason):
            raise BrowserRuntimeError("human takeover reason must not contain credential values")
        try:
            normalized_domain = normalize_domain(domain)
        except BrowserPolicyError as error:
            raise BrowserRuntimeError(str(error)) from error
        normalized_title = str(title or "").strip() or None
        if normalized_title is not None and len(normalized_title) > 120:
            raise BrowserRuntimeError("human takeover title is too long")
        normalized_targets: list[str] = []
        for target in targets or []:
            value = str(target or "").strip()
            if not value or len(value) > 160:
                raise BrowserRuntimeError("human takeover target is invalid")
            normalized_targets.append(value)
        try:
            result = self.browser_skill.request_help(
                normalized_session,
                normalized_reason,
                title=normalized_title,
                targets=normalized_targets,
                timeout=timeout,
            )
        except BrowserRuntimeError as error:
            raise BrowserRuntimeError(f"BrowserSkill human takeover failed: {error}") from error
        outcome = "requested"
        if isinstance(result, dict) and isinstance(result.get("outcome"), str):
            candidate = result["outcome"].strip().lower()
            if candidate in {"continued", "cancelled", "timed_out", "completed", "disabled", "requested"}:
                outcome = candidate
        return {
            "session_id": normalized_session,
            "domain": normalized_domain,
            "outcome": outcome,
            "requires_human": True,
            "credentials_excluded": True,
            "backend_requested": True,
        }

    def request_help(self, *, session_id: str, domain: str, reason: str) -> dict[str, Any]:
        item = self._session(session_id)
        result = {
            "event_type": "browser_request_help",
            "session_id": session_id,
            "domain": _compact_browser_text(domain, 240),
            "reason": _compact_browser_text(reason, 800),
            "state": "paused",
            "credentials_excluded": True,
            "created_at": utc_now(),
        }
        backend_session_id = item.get("backend_session_id")
        if backend_session_id:
            try:
                backend = self.browser_skill.request_help(str(backend_session_id), reason, title="Sumika 需要你的操作")
                result["backend_requested"] = True
                result["backend_state"] = _compact_browser_value(backend)
            except BrowserRuntimeError as error:
                result["backend_requested"] = False
                result["backend_error"] = str(error)
        return result

    def _session(self, session_id: str) -> dict[str, Any]:
        item = self.sessions.get(session_id)
        if item is None:
            raise BrowserRuntimeError("unknown browser session")
        self._renew_profile_lease(item)
        return item

    def list_downloads(self) -> list[dict[str, Any]]:
        return [self._public_download(item) for item in sorted(self.downloads.values(), key=lambda value: str(value.get("created_at") or ""), reverse=True)]

    def quarantine_download(self, *, session_id: str, path: str, source_url: str, content_type: str | None = None) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise BrowserRuntimeError("unknown browser session")
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            raise BrowserRuntimeError("download path is not a regular file")
        candidate = candidate.resolve()
        size_bytes = candidate.stat().st_size
        if size_bytes > 100 * 1024 * 1024:
            raise BrowserRuntimeError("download exceeds the 100 MB quarantine limit")
        if not source_url.strip():
            raise BrowserRuntimeError("source_url is required for a quarantined download")
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        item_id = f"download-{uuid4().hex[:12]}"
        safe_name = _safe_download_name(candidate.name)
        stored_path = candidate
        managed = False
        if self.quarantine_dir is not None:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
            stored_path = (self.quarantine_dir / f"{item_id}-{safe_name}").resolve()
            if self.quarantine_dir.resolve() not in stored_path.parents:
                raise BrowserRuntimeError("quarantine path escaped its managed directory")
            try:
                shutil.copy2(candidate, stored_path)
            except OSError as error:
                raise BrowserRuntimeError("could not copy download into quarantine") from error
            managed = True
        item = {"id": item_id, "session_id": session_id, "path": str(stored_path), "original_path": str(candidate), "filename": safe_name, "size_bytes": size_bytes, "source_url": _compact_browser_url(source_url), "content_type": _compact_browser_text(content_type, 160) if content_type else None, "sha256": digest.hexdigest(), "status": "quarantine", "managed": managed, "created_at": utc_now()}
        self.downloads[item["id"]] = item
        return self._public_download(item)

    def release_download(self, download_id: str, *, approved: bool = False, workspace_path: str | None = None) -> dict[str, Any]:
        item = self.downloads.get(download_id)
        if item is None:
            raise BrowserRuntimeError("unknown quarantined download")
        if item.get("status") != "quarantine":
            raise BrowserRuntimeError("download has already been released")
        if not approved:
            raise BrowserRuntimeError("download import requires explicit approval")
        source = Path(str(item.get("path") or ""))
        if not source.is_file():
            raise BrowserRuntimeError("quarantined file is no longer available")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != str(item.get("sha256") or ""):
            raise BrowserRuntimeError("quarantined file changed after it was recorded")
        if workspace_path:
            workspace = Path(workspace_path).expanduser()
            if not workspace.is_dir():
                raise BrowserRuntimeError("workspace_path must be an existing directory")
            workspace = workspace.resolve()
            target = (workspace / _safe_download_name(str(item.get("filename") or "download.bin"))).resolve()
            if target.parent != workspace:
                raise BrowserRuntimeError("download destination escaped the workspace")
            if target.exists():
                target = workspace / f"{target.stem}-{uuid4().hex[:8]}{target.suffix}"
            try:
                shutil.copy2(source, target)
            except OSError as error:
                raise BrowserRuntimeError("could not import quarantined file into workspace") from error
            item["destination_name"] = target.name
            item["imported_at"] = utc_now()
        item["status"] = "approved"
        item["approved_at"] = utc_now()
        return self._public_download(item)

    @staticmethod
    def _public_download(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item[key]
            for key in ("id", "session_id", "filename", "size_bytes", "source_url", "content_type", "sha256", "status", "managed", "created_at", "approved_at", "imported_at", "destination_name")
            if key in item
        }


def _safe_download_name(value: str) -> str:
    name = Path(value or "download.bin").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (name[:120] or "download.bin")
