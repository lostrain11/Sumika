"""Small, harness-neutral policy evaluator for browser tool calls.

The evaluator deliberately accepts only redacted metadata.  It is used by the
Sumika RPC boundary and by the DSH BrowserSkill policy plugin, so browser
control remains replaceable without moving trust decisions into a UI or a
third-party plugin.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


class BrowserPolicyError(ValueError):
    """Raised when a policy request is malformed."""


TOOL_ACTIONS: dict[str, str] = {
    "browser_session_start": "session_start",
    "browser_session_stop": "session_stop",
    "browser_session_list": "session_list",
    "browser_navigate": "navigate",
    "browser_snapshot": "snapshot",
    "browser_observe": "observe",
    "browser_click": "click",
    "browser_fill": "fill",
    "browser_press": "press",
    "browser_screenshot": "screenshot",
    "browser_emulate": "emulate",
    "browser_request_help": "request_help",
}

READ_ONLY_ACTIONS = frozenset({"observe", "snapshot", "screenshot"})
WRITE_ACTIONS = frozenset({"click", "fill", "press", "emulate"})
TARGET_KINDS = frozenset({"none", "snapshot_ref", "css_selector", "unknown"})
POLICY_DECISIONS = frozenset({"allow", "ask", "deny"})
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9\u0080-\uffff](?:[A-Za-z0-9\u0080-\uffff-]{0,61}[A-Za-z0-9\u0080-\uffff])?$")
_SECRET_TEXT_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|token|password|secret|otp)\s*[:=]\s*[^\s,;]+)"
)

_ALLOWED_METADATA_KEYS = frozenset(
    {
        "tool_name",
        "session_id",
        "action",
        "domain",
        "current_domain",
        "target_kind",
        "value_length",
        "sensitive",
        "session_known",
        "new_tab",
    }
)


@dataclass(frozen=True, slots=True)
class BrowserPolicyDecision:
    decision: str
    reason: str
    requires_human: bool = False
    audit_id: str = ""
    tool_name: str = ""
    action: str = ""
    session_id: str | None = None
    domain: str | None = None
    value_length: int = 0
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "requires_human": self.requires_human,
            "audit_id": self.audit_id,
            "tool_name": self.tool_name,
            "action": self.action,
            "session_id": self.session_id,
            "domain": self.domain,
            "value_length": self.value_length,
            "sensitive": self.sensitive,
        }


def normalize_domain(value: Any) -> str | None:
    """Normalize one hostname without accepting a URL or credential material."""

    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise BrowserPolicyError("domain must be text or null")
    raw = value.strip().rstrip(".").lower()
    if not raw:
        return None
    if len(raw) > 253 or any(ord(char) < 32 or char.isspace() for char in raw):
        raise BrowserPolicyError("domain is invalid")
    if any(char in raw for char in "/?#@"):
        raise BrowserPolicyError("domain must be a hostname, not a URL")
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    try:
        ipaddress.ip_address(raw)
        return raw
    except ValueError:
        pass
    if ":" in raw:
        raise BrowserPolicyError("domain is invalid")
    labels = raw.split(".")
    if any(not label or len(label) > 63 or not _HOST_LABEL_RE.fullmatch(label) for label in labels):
        raise BrowserPolicyError("domain is invalid")
    try:
        return raw.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise BrowserPolicyError("domain is invalid") from error


def domain_from_url(value: Any) -> tuple[str | None, bool]:
    """Return ``(hostname, is_new_tab)`` from a URL, without returning the URL."""

    if not isinstance(value, str) or not value.strip():
        raise BrowserPolicyError("url must be a non-empty string")
    raw = value.strip()
    if len(raw) > 4096:
        raise BrowserPolicyError("url is too long")
    try:
        parsed = urlparse(raw)
    except ValueError as error:
        raise BrowserPolicyError("url is invalid") from error
    if (
        parsed.scheme.lower() == "chrome"
        and parsed.netloc.lower() == "newtab"
        and parsed.path == "/"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    ):
        return None, True
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise BrowserPolicyError("url must be http(s) or chrome://newtab/")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserPolicyError("url must not contain embedded credentials")
    try:
        # Accessing port catches malformed values such as ``:99999``.
        _ = parsed.port
    except ValueError as error:
        raise BrowserPolicyError("url has an invalid port") from error
    return normalize_domain(parsed.hostname), False


def classify_target(value: Any) -> str:
    """Classify a target without retaining its text."""

    if value is None or value == "":
        return "none"
    if not isinstance(value, str):
        raise BrowserPolicyError("target must be text or null")
    target = value.strip()
    if not target:
        return "none"
    if re.fullmatch(r"@?e\d+", target, flags=re.IGNORECASE):
        return "snapshot_ref"
    if target.startswith(("#", ".", "[", ":")):
        return "css_selector"
    return "unknown"


def looks_like_secret_text(value: Any) -> bool:
    return isinstance(value, str) and bool(_SECRET_TEXT_RE.search(value))


def validate_metadata(metadata: Any) -> dict[str, Any]:
    """Validate and normalize the deliberately small policy wire contract."""

    if not isinstance(metadata, dict):
        raise BrowserPolicyError("policy metadata must be an object")
    unknown = set(metadata) - _ALLOWED_METADATA_KEYS
    if unknown:
        raise BrowserPolicyError("policy metadata contains unsupported fields")
    tool_name = metadata.get("tool_name")
    if not isinstance(tool_name, str) or tool_name not in TOOL_ACTIONS:
        raise BrowserPolicyError("tool_name is not a supported browser tool")
    action = metadata.get("action")
    expected_action = TOOL_ACTIONS[tool_name]
    if not isinstance(action, str) or action != expected_action:
        raise BrowserPolicyError("action does not match tool_name")

    session_id = metadata.get("session_id")
    if session_id is not None:
        if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id.strip()):
            raise BrowserPolicyError("session_id is invalid")
        session_id = session_id.strip()

    domain = normalize_domain(metadata.get("domain"))
    current_domain = normalize_domain(metadata.get("current_domain"))
    target_kind = metadata.get("target_kind", "none")
    if not isinstance(target_kind, str) or target_kind not in TARGET_KINDS:
        raise BrowserPolicyError("target_kind is invalid")
    value_length = metadata.get("value_length", 0)
    if isinstance(value_length, bool) or not isinstance(value_length, int) or not 0 <= value_length <= 1_000_000:
        raise BrowserPolicyError("value_length is out of range")
    sensitive = metadata.get("sensitive", False)
    session_known = metadata.get("session_known", False)
    new_tab = metadata.get("new_tab", False)
    if not isinstance(sensitive, bool) or not isinstance(session_known, bool) or not isinstance(new_tab, bool):
        raise BrowserPolicyError("sensitive, session_known and new_tab must be booleans")
    if action == "navigate" and domain is None and not new_tab:
        raise BrowserPolicyError("navigate requires a normalized domain or new_tab")
    if action == "session_start" and domain is None and new_tab is False and "domain" in metadata:
        # An explicit null is fine for a blank session; the branch only keeps
        # malformed callers from pretending an arbitrary URL was checked.
        pass
    if action not in {"session_start", "session_list"} and not session_id:
        raise BrowserPolicyError("browser action requires session_id")
    return {
        "tool_name": tool_name,
        "action": action,
        "session_id": session_id,
        "domain": domain,
        "current_domain": current_domain,
        "target_kind": target_kind,
        "value_length": value_length,
        "sensitive": sensitive,
        "session_known": session_known,
        "new_tab": new_tab,
    }


class BrowserPolicyEvaluator:
    """Evaluate redacted browser metadata with a fail-closed default."""

    def __init__(self, *, enabled: bool = True, allowlist: set[str] | None = None) -> None:
        self.enabled = bool(enabled)
        self.allowlist = {
            normalized
            for value in (allowlist or set())
            for normalized in (normalize_domain(value),)
            if normalized
        }

    def evaluate(self, metadata: Any) -> dict[str, Any]:
        item = validate_metadata(metadata)
        decision = "deny"
        reason = "浏览器策略拒绝了该操作"
        requires_human = False
        action = item["action"]
        domain = item["domain"]
        current_domain = item["current_domain"]
        session_known = item["session_known"]

        if not self.enabled:
            reason = "浏览器运行时已关闭"
        elif action == "session_list":
            decision, reason = "allow", "仅列出当前插件拥有的浏览器会话"
        elif action == "session_start":
            if item["sensitive"]:
                decision, reason = "ask", "会话设备设置需要用户批准"
            elif item["new_tab"] or domain is None:
                decision, reason = "allow", "允许打开空白隔离浏览器会话"
            else:
                decision, reason = "ask", "首次访问域名需要用户批准"
        elif action == "session_stop":
            if session_known:
                decision, reason = "allow", "只停止调用方拥有的浏览器会话"
            else:
                reason = "未知或不属于当前插件的浏览器会话"
        elif action == "request_help":
            if session_known:
                decision, reason = "allow", "允许请求用户在隔离浏览器窗口中接管"
            else:
                reason = "人工接管只能针对当前插件拥有的浏览器会话"
        elif not session_known:
            reason = "未知或不属于当前插件的浏览器会话"
        elif action in READ_ONLY_ACTIONS:
            if domain and current_domain and domain != current_domain:
                decision, reason = "ask", "观察目标域名与当前域名不同，需要用户批准"
            elif domain and domain not in self.allowlist and current_domain is None:
                decision, reason = "ask", "尚未批准该域名的只读观察"
            else:
                decision, reason = "allow", "已批准域名内的只读浏览操作"
        elif action == "navigate":
            if item["new_tab"]:
                decision, reason = "allow", "允许返回隔离浏览器空白页"
            elif domain in self.allowlist or (current_domain and domain == current_domain):
                decision, reason = "allow", "当前已批准域名内的导航"
            else:
                decision, reason = "ask", "首次访问或跨域导航需要用户批准"
        elif action in WRITE_ACTIONS:
            if action == "fill" and item["sensitive"]:
                decision = "deny"
                reason = "密码、OTP 和凭据字段必须由用户在隔离窗口中输入"
                requires_human = True
            else:
                decision, reason = "ask", "页面写入或环境变更需要用户批准"

        result = BrowserPolicyDecision(
            decision=decision,
            reason=reason,
            requires_human=requires_human,
            audit_id=f"browser-policy-{uuid4().hex[:12]}",
            tool_name=item["tool_name"],
            action=action,
            session_id=item["session_id"],
            domain=domain,
            value_length=item["value_length"],
            sensitive=item["sensitive"],
        )
        return result.to_dict()


__all__ = [
    "BrowserPolicyDecision",
    "BrowserPolicyError",
    "BrowserPolicyEvaluator",
    "TOOL_ACTIONS",
    "classify_target",
    "domain_from_url",
    "looks_like_secret_text",
    "normalize_domain",
    "validate_metadata",
]
