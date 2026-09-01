"""Generic, fail-closed adapters for browser based chat accounts.

Web chat providers are intentionally modelled as *profiles*, rather than as
API keys.  The authenticated state belongs to a dedicated Edge/Chromium
profile managed by BrowserSkill.  Sumika stores only the site adapter,
consent and other non-sensitive metadata, so a browser login can be reused
without importing cookies, localStorage or authorization headers.

The built-in sites below are presets for the same declarative adapter.  A
custom site can use the ``custom`` adapter with explicit domains, URL and CSS
selectors.  No arbitrary JavaScript, CDP expression or page script is ever
accepted by this layer.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

from ..protocol.models import ChatRequest, ProviderInfo, utc_now
from ..providers.base import LLMProvider
from ..storage import Storage
from .policy import BrowserPolicyError, normalize_domain

if TYPE_CHECKING:  # pragma: no cover - imported only for type checking
    from .runtime import BrowserRuntime


WEB_CHAT_SCHEMA = "web-chat/v1"
WEB_CHAT_ADAPTER_VERSION = "web-chat-adapter/v1"
WEB_CHAT_ACTIONS = frozenset({"chat.read", "chat.send"})
WEB_CHAT_BUDGET_POLICIES = frozenset({"free-only", "no-paid"})
DEFAULT_WEB_CHAT_OBSERVATION_SECONDS = 300.0
MAX_WEB_CHAT_OBSERVATION_SECONDS = 300.0
_PROFILE_ID_RE = re.compile(r"^web-chat-[a-f0-9]{8,32}$")
_SAFE_INSTANCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:secret|password|passwd|token|cookie|authorization|api[_-]?key|credential|otp)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|token|password|secret|otp)\s*[:=]\s*[^\s,;]+)"
)
_UNSAFE_SELECTOR_RE = re.compile(r"(?i)(?:^|\s)(?:javascript|data):|[\r\n<>]")


class WebChatRuntimeError(RuntimeError):
    """Raised when a web-chat profile cannot be used safely."""


def _text(value: Any, limit: int = 240) -> str:
    if not isinstance(value, str):
        value = str(value or "")
    value = value.strip()
    if len(value) > limit:
        value = value[:limit]
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise WebChatRuntimeError("web-chat text contains control characters")
    return value


def _selector_list(value: Any, *, required: bool = False) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if value is None:
        value = []
    if not isinstance(value, (list, tuple)):
        raise WebChatRuntimeError("web-chat selectors must be arrays of CSS selectors")
    result: list[str] = []
    for raw in list(value)[:16]:
        selector = _text(raw, 300)
        if not selector or _UNSAFE_SELECTOR_RE.search(selector):
            raise WebChatRuntimeError("web-chat selectors must be safe CSS selectors")
        if selector not in result:
            result.append(selector)
    if required and not result:
        raise WebChatRuntimeError("web-chat adapter requires an input selector")
    return tuple(result)


def _marker_list(value: Any, *, fallback: Iterable[str] = ()) -> tuple[str, ...]:
    if value is None or value == () or value == [] or value == "":
        value = list(fallback)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise WebChatRuntimeError("web-chat markers must be arrays of text")
    result: list[str] = []
    for raw in list(value)[:32]:
        marker = _text(raw, 160)
        if marker and marker.casefold() not in {item.casefold() for item in result}:
            result.append(marker)
    return tuple(result)


def _safe_url(value: Any, *, domains: tuple[str, ...] | None = None) -> str:
    raw = _text(value, 2048)
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebChatRuntimeError("web-chat URL must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise WebChatRuntimeError("web-chat URL must not contain embedded credentials")
    domain = normalize_domain(parsed.hostname)
    if domains and domain not in domains:
        raise WebChatRuntimeError("web-chat URL host is not in the adapter domain allowlist")
    return raw.rstrip("/") or raw


def _domain_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        raise WebChatRuntimeError("web-chat adapter requires one or more domains")
    result: list[str] = []
    for raw in list(value)[:8]:
        try:
            domain = normalize_domain(raw)
        except BrowserPolicyError as exc:
            raise WebChatRuntimeError(str(exc)) from exc
        if not domain:
            raise WebChatRuntimeError("web-chat domain is required")
        if domain not in result:
            result.append(domain)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class WebChatAdapterSpec:
    """Declarative description of one web chat UI."""

    id: str
    name: str
    domains: tuple[str, ...]
    chat_url: str
    selectors: dict[str, tuple[str, ...]]
    login_markers: tuple[str, ...] = ()
    authorized_markers: tuple[str, ...] = ()
    ready_markers: tuple[str, ...] = ()
    model_id: str = "web-session"
    version: str = WEB_CHAT_ADAPTER_VERSION
    custom: bool = False

    def __post_init__(self) -> None:
        adapter_id = _text(self.id, 80).lower()
        if not adapter_id or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,79}", adapter_id):
            raise WebChatRuntimeError("web-chat adapter id is invalid")
        object.__setattr__(self, "id", adapter_id)
        object.__setattr__(self, "name", _text(self.name, 160) or adapter_id)
        domains = _domain_list(self.domains)
        object.__setattr__(self, "domains", domains)
        object.__setattr__(self, "chat_url", _safe_url(self.chat_url, domains=domains))
        normalized_selectors: dict[str, tuple[str, ...]] = {}
        for key in ("input", "send", "response"):
            normalized_selectors[key] = _selector_list(self.selectors.get(key, ()), required=key == "input")
        object.__setattr__(self, "selectors", normalized_selectors)
        object.__setattr__(self, "login_markers", _marker_list(self.login_markers, fallback=("登录", "Log in", "Sign in")))
        object.__setattr__(self, "authorized_markers", _marker_list(self.authorized_markers, fallback=("退出登录", "Log out", "Sign out", "注销")))
        object.__setattr__(self, "ready_markers", _marker_list(self.ready_markers))
        model = _text(self.model_id, 160) or "web-session"
        object.__setattr__(self, "model_id", model)
        object.__setattr__(self, "version", _text(self.version, 120) or WEB_CHAT_ADAPTER_VERSION)
        object.__setattr__(self, "custom", bool(self.custom))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "domains": list(self.domains),
            "chat_url": self.chat_url,
            "selectors": {key: list(value) for key, value in self.selectors.items()},
            "login_markers": list(self.login_markers),
            "authorized_markers": list(self.authorized_markers),
            "ready_markers": list(self.ready_markers),
            "model_id": self.model_id,
            "version": self.version,
            "custom": self.custom,
            "schema": WEB_CHAT_SCHEMA,
        }

    def public_config(self) -> dict[str, Any]:
        """Return the safe, reproducible part persisted with a profile."""

        return {
            "domains": list(self.domains),
            "chat_url": self.chat_url,
            "selectors": {key: list(value) for key, value in self.selectors.items()},
            "login_markers": list(self.login_markers),
            "authorized_markers": list(self.authorized_markers),
            "ready_markers": list(self.ready_markers),
            "model_id": self.model_id,
        }


def _builtin_specs() -> tuple[WebChatAdapterSpec, ...]:
    # These selectors are deliberately broad and versioned presets.  A site
    # may change its DOM; the adapter then fails closed and the user can edit
    # the profile instead of having Sumika guess at a new page structure.
    selectors = {
        "input": ("textarea", "[contenteditable='true']"),
        "send": ("button[type='submit']", "button[aria-label*='Send']", "button[aria-label*='发送']"),
        "response": (
            "[data-message-author-role='assistant']",
            "[data-testid*='assistant']",
            "[class*='assistant']",
        ),
    }
    return (
        WebChatAdapterSpec(
            id="deepseek-web",
            name="DeepSeek 网页聊天",
            domains=("chat.deepseek.com",),
            chat_url="https://chat.deepseek.com/",
            selectors=selectors,
            ready_markers=("新对话", "New chat", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="chatgpt-web",
            name="ChatGPT 网页聊天",
            domains=("chatgpt.com", "chat.openai.com"),
            chat_url="https://chatgpt.com/",
            selectors=selectors,
            ready_markers=("New chat", "新聊天", "Send", "发送"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="zhipu-web",
            name="智谱网页聊天",
            domains=("chat.z.ai", "chatglm.cn"),
            chat_url="https://chat.z.ai/",
            selectors=selectors,
            ready_markers=("新建对话", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="qwen-web",
            name="Qwen 网页聊天",
            domains=("chat.qwen.ai",),
            chat_url="https://chat.qwen.ai/",
            selectors=selectors,
            ready_markers=("新建对话", "新对话", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="kimi-web",
            name="Kimi 网页聊天",
            domains=("www.kimi.com", "kimi.moonshot.cn"),
            chat_url="https://www.kimi.com/",
            selectors=selectors,
            ready_markers=("新建对话", "新对话", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="doubao-web",
            name="豆包网页聊天",
            domains=("www.doubao.com",),
            chat_url="https://www.doubao.com/chat/",
            selectors=selectors,
            ready_markers=("新对话", "创建对话", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="custom",
            name="通用网页聊天",
            domains=("example.invalid",),
            chat_url="https://example.invalid/",
            selectors={"input": ("textarea",), "send": (), "response": ()},
            ready_markers=(),
            custom=True,
        ),
    )


class WebChatAdapterRegistry:
    """In-process registry for built-ins; custom definitions live per profile."""

    def __init__(self, specs: Iterable[WebChatAdapterSpec] | None = None) -> None:
        self._specs = {item.id: item for item in (specs or _builtin_specs())}

    def list(self) -> list[dict[str, Any]]:
        return [self._specs[key].to_dict() for key in self._specs]

    def get(self, adapter_id: str) -> WebChatAdapterSpec | None:
        return self._specs.get(str(adapter_id or "").strip().lower())

    def resolve(self, adapter_id: str, config: Mapping[str, Any] | None = None) -> WebChatAdapterSpec:
        normalized = str(adapter_id or "").strip().lower()
        raw = dict(config or {})
        base = self.get(normalized)
        if normalized == "custom":
            name = _text(raw.get("name") or "通用网页聊天", 160)
            domains = _domain_list(raw.get("domains"))
            chat_url = _safe_url(raw.get("chat_url"), domains=domains)
            selectors_value = raw.get("selectors") if isinstance(raw.get("selectors"), dict) else {}
            selectors = {
                "input": _selector_list(selectors_value.get("input"), required=True),
                "send": _selector_list(selectors_value.get("send")),
                "response": _selector_list(selectors_value.get("response")),
            }
            return WebChatAdapterSpec(
                id="custom",
                name=name,
                domains=domains,
                chat_url=chat_url,
                selectors=selectors,
                login_markers=_marker_list(raw.get("login_markers")),
                authorized_markers=_marker_list(raw.get("authorized_markers"), fallback=("退出登录", "Log out", "Sign out", "注销")),
                ready_markers=_marker_list(raw.get("ready_markers")),
                model_id=raw.get("model_id") or "web-session",
                version=raw.get("adapter_version") or WEB_CHAT_ADAPTER_VERSION,
                custom=True,
            )
        if base is None:
            raise WebChatRuntimeError(f"unknown web-chat adapter: {normalized}")
        # Built-in presets allow safe selector/marker overrides so a user can
        # repair a DOM change without shipping executable code.
        selectors_value = raw.get("selectors") if isinstance(raw.get("selectors"), dict) else {}
        selectors = dict(base.selectors)
        for key in ("input", "send", "response"):
            if key in selectors_value:
                selectors[key] = _selector_list(selectors_value[key], required=key == "input")
        domains = _domain_list(raw.get("domains", base.domains))
        chat_url = _safe_url(raw.get("chat_url", base.chat_url), domains=domains)
        return WebChatAdapterSpec(
            id=base.id,
            name=_text(raw.get("name") or base.name, 160),
            domains=domains,
            chat_url=chat_url,
            selectors=selectors,
            login_markers=_marker_list(raw.get("login_markers"), fallback=base.login_markers),
            authorized_markers=_marker_list(raw.get("authorized_markers"), fallback=base.authorized_markers),
            ready_markers=_marker_list(raw.get("ready_markers"), fallback=base.ready_markers),
            model_id=raw.get("model_id") or base.model_id,
            version=raw.get("adapter_version") or base.version,
            custom=False,
        )


def _walk_strings(value: Any, *, depth: int = 0, limit: int = 400) -> list[str]:
    """Collect bounded marker text without retaining the page snapshot."""

    if depth > 6 or limit <= 0:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text[:400]] if text else []
    if isinstance(value, (int, float, bool)) or value is None:
        return []
    result: list[str] = []
    if isinstance(value, dict):
        # These keys contain the semantic text that BrowserSkill snapshots
        # expose.  Do not inspect arbitrary binary or credential containers.
        for key, item in list(value.items())[:80]:
            lowered = str(key).lower()
            if any(token in lowered for token in ("cookie", "token", "secret", "password", "authorization", "base64", "image_data")):
                continue
            result.extend(_walk_strings(item, depth=depth + 1, limit=limit - len(result)))
            if len(result) >= limit:
                break
    elif isinstance(value, (list, tuple)):
        for item in list(value)[:160]:
            result.extend(_walk_strings(item, depth=depth + 1, limit=limit - len(result)))
            if len(result) >= limit:
                break
    return result[:limit]


def _snapshot_payload(value: Any) -> Any:
    if isinstance(value, dict) and "snapshot" in value:
        return value.get("snapshot")
    if isinstance(value, dict) and "observation" in value:
        return value.get("observation")
    return value


def _validated_snapshot(value: Any) -> tuple[str, Any | None]:
    """Validate the transport envelope before inspecting page data.

    BrowserSkill is an external process. A malformed response must never
    become an exception in the Core RPC boundary, and it must never be
    interpreted as an authenticated page. Keep the distinction between a
    normal disconnected/not-ready response and a structurally invalid one so
    callers can expose a useful, bounded status without retaining the raw
    payload.
    """

    if not isinstance(value, Mapping):
        return "invalid", None
    if value.get("ready") is not True:
        return "not-ready", None
    if "snapshot" not in value:
        return "invalid", None
    payload = value.get("snapshot")
    if payload is None or not isinstance(payload, (Mapping, list, tuple, str)):
        return "invalid", None
    return "ready", payload


def _contains_marker(strings: Iterable[str], markers: Iterable[str]) -> bool:
    haystack = "\n".join(strings).casefold()
    return any(marker.casefold() in haystack for marker in markers if marker)


def _auth_state(spec: WebChatAdapterSpec, snapshot: Any) -> str:
    strings = _walk_strings(_snapshot_payload(snapshot))
    # A positive account marker wins over a footer/login hint.  We deliberately
    # use only coarse markers; no account name or page content is persisted.
    # Only explicit, adapter-owned markers prove authorization.  Generic
    # words such as "Account" also appear on login pages and public footers,
    # so treating them as proof would allow an unauthenticated send.
    positive = spec.authorized_markers
    if _contains_marker(strings, positive):
        return "authorized"
    if _contains_marker(strings, spec.login_markers):
        return "needs-auth"
    return "unknown"


def _page_ready(spec: WebChatAdapterSpec, snapshot: Any, *, auth_state: str | None = None) -> bool:
    """Return whether the chat page, rather than the account, is ready.

    Login and page-ready markers are intentionally separate.  A generic
    ``发送``/``New chat`` marker must never be treated as proof that a user is
    authenticated.  Custom adapters may omit ready markers; in that case an
    authenticated page is the only safe readiness signal available to this
    metadata-only bridge.
    """

    markers = spec.ready_markers
    if not markers:
        return auth_state == "authorized"
    strings = _walk_strings(_snapshot_payload(snapshot))
    return _contains_marker(strings, markers)


def _selector_alternatives(selector: str) -> tuple[str, ...]:
    # The adapter validator rejects executable CSS.  Splitting simple comma
    # groups here keeps matching deterministic without evaluating page code.
    return tuple(item.strip() for item in str(selector or "").split(",") if item.strip())


_CSS_ATTR_RE = re.compile(
    r"\[\s*([a-zA-Z_][\w:-]*)\s*(?:(\*=|\^=|\$=|~=|=)\s*['\"]?([^'\"\]]+)['\"]?)?\s*\]"
)


def _node_attributes(value: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if lowered in {"attributes", "attrs", "properties"} and isinstance(item, Mapping):
            for attr, attr_value in item.items():
                if isinstance(attr_value, (str, int, float, bool)):
                    result[str(attr).lower()] = str(attr_value)
        elif lowered in {
            "id",
            "class",
            "classname",
            "role",
            "name",
            "testid",
            "data-testid",
            "data-message-author-role",
            "selector",
            "css_selector",
        } and isinstance(item, (str, int, float, bool)):
            normalized = "class" if lowered == "classname" else lowered
            result[normalized] = str(item)
    return result


def _node_matches_selector(value: Any, selector: str) -> bool:
    """Match the small, declarative selector subset exposed by snapshots."""

    if not isinstance(value, Mapping):
        return False
    attrs = _node_attributes(value)
    tag = str(value.get("tag") or value.get("tag_name") or value.get("element") or "").lower()
    for alternative in _selector_alternatives(selector):
        direct_selector = attrs.get("selector") or attrs.get("css_selector")
        if direct_selector and direct_selector == alternative:
            return True
        candidate = alternative
        attr_matches = list(_CSS_ATTR_RE.finditer(candidate))
        valid = True
        for match in attr_matches:
            name, operator, expected = match.groups()
            actual = attrs.get(name.lower())
            if actual is None:
                valid = False
                break
            if not operator:
                continue
            expected = expected or ""
            if operator == "=" and actual != expected:
                valid = False
            elif operator == "*=" and expected.casefold() not in actual.casefold():
                valid = False
            elif operator == "^=" and not actual.startswith(expected):
                valid = False
            elif operator == "$=" and not actual.endswith(expected):
                valid = False
            elif operator == "~=" and expected not in actual.split():
                valid = False
        if not valid:
            continue
        candidate = _CSS_ATTR_RE.sub("", candidate)
        id_matches = re.findall(r"#([a-zA-Z_][\w:-]*)", candidate)
        if id_matches and attrs.get("id") not in id_matches:
            continue
        class_matches = re.findall(r"\.([a-zA-Z_][\w:-]*)", candidate)
        classes = set((attrs.get("class") or "").split())
        if class_matches and not all(item in classes for item in class_matches):
            continue
        tag_match = re.match(r"^\s*([a-zA-Z][\w-]*)", candidate)
        if tag_match and tag and tag_match.group(1).lower() != tag:
            continue
        if tag_match and not tag:
            # A snapshot node without an element name cannot prove a tag
            # selector, but attribute/class selectors can still be matched.
            if not attr_matches and not id_matches and not class_matches:
                continue
        if re.search(r"\[", candidate):
            continue
        if attr_matches or id_matches or class_matches or tag_match:
            return True
    return False


def _node_text(value: Any, *, depth: int = 0, limit: int = 24_000) -> str:
    if depth > 8 or limit <= 0:
        return ""
    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in list(value)[:160]:
            nested = _node_text(item, depth=depth + 1, limit=limit - len("\n".join(parts)))
            if nested:
                parts.append(nested)
            if len("\n".join(parts)) >= limit:
                break
        return "\n".join(dict.fromkeys(parts))[:limit]
    if not isinstance(value, Mapping):
        return ""
    parts: list[str] = []
    for key in ("content", "text", "message", "value", "markdown", "body"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
    for key in ("children", "child", "nodes", "items"):
        item = value.get(key)
        if isinstance(item, (list, tuple, Mapping)):
            nested = _node_text(item, depth=depth + 1, limit=limit - len("\n".join(parts)))
            if nested:
                parts.append(nested)
    return "\n".join(dict.fromkeys(parts))[:limit]


def _extract_assistant_text(
    snapshot: Any,
    *,
    selectors: Iterable[str] = (),
    max_chars: int = 24_000,
) -> str | None:
    """Extract only an explicitly assistant-labelled response.

    Generic pages are not treated as chat responses merely because they have
    text.  This prevents a navigation page, an account page or a login form
    from being returned as a model answer when a site changes its DOM.
    """

    root = _snapshot_payload(snapshot)
    candidates: list[str] = []
    selector_candidates: list[str] = []
    response_selectors = tuple(str(item) for item in selectors if str(item).strip())

    def visit(value: Any, role_hint: str = "", depth: int = 0) -> None:
        if depth > 8 or len(candidates) >= 64:
            return
        if isinstance(value, dict):
            role = str(value.get("role") or value.get("author") or value.get("sender") or role_hint).lower()
            key_hint = " ".join(str(key).lower() for key in value.keys())
            is_assistant = any(token in role or token in key_hint for token in ("assistant", "model", "bot"))
            if response_selectors and any(_node_matches_selector(value, selector) for selector in response_selectors):
                selected = _node_text(value)
                if selected:
                    selector_candidates.append(selected)
            if is_assistant:
                for key in ("content", "text", "message", "value", "markdown", "body"):
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        candidates.append(item.strip())
            for key, item in list(value.items())[:100]:
                lowered = str(key).lower()
                if any(token in lowered for token in ("cookie", "token", "secret", "password", "authorization", "base64", "image_data")):
                    continue
                visit(item, role, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in list(value)[:160]:
                visit(item, role_hint, depth + 1)

    visit(root)
    # Some accessibility snapshots flatten role/text into lines.  Only accept
    # lines with an explicit assistant prefix in that fallback.
    # An explicit response selector wins over broad semantic matching.  If the
    # snapshot implementation omitted selector metadata, retain the older
    # assistant-labelled fallback rather than guessing from arbitrary text.
    if selector_candidates:
        candidates = selector_candidates
    if not candidates:
        for line in _walk_strings(root, limit=600):
            match = re.match(r"(?is)^\s*(?:assistant|model|bot)\s*[:：]\s*(.+)$", line)
            if match:
                candidates.append(match.group(1).strip())
    if not candidates:
        return None
    # Keep the latest distinct response; the browser snapshot often includes
    # the full conversation in chronological order.
    text = candidates[-1].strip()
    if not text:
        return None
    if _SECRET_VALUE_RE.search(text):
        raise WebChatRuntimeError("web-chat response appears to contain sensitive data")
    return text[:max_chars]


class WebChatRuntime:
    """Manage persistent web-account metadata and BrowserSkill sessions."""

    def __init__(
        self,
        storage: Storage,
        browser: "BrowserRuntime",
        *,
        registry: WebChatAdapterRegistry | None = None,
        logger: Any = None,
    ) -> None:
        self.storage = storage
        self.browser = browser
        self.registry = registry or WebChatAdapterRegistry()
        self.logger = logger
        self.sessions: dict[str, str] = {}
        # RouteCoordinator marks a profile while an Agent worker is writing to
        # it.  Manual sends fail closed during that interval instead of
        # sharing the same BrowserSkill tab concurrently.
        self._agent_occupancy: set[str] = set()
        self._occupancy_lock = threading.RLock()
        self._attempts: dict[str, dict[str, Any]] = {}
        self._profile_attempts: dict[str, str] = {}
        self._closed = False

    def set_agent_occupancy(self, profile_id: str, occupied: bool) -> None:
        normalized = str(profile_id or "").strip()
        if not normalized:
            return
        with self._occupancy_lock:
            if occupied:
                self._agent_occupancy.add(normalized)
            else:
                self._agent_occupancy.discard(normalized)

    def agent_occupancy(self, profile_id: str) -> bool:
        with self._occupancy_lock:
            return str(profile_id or "").strip() in self._agent_occupancy

    def list_adapters(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def list_profiles(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        rows = self.storage.list_web_chat_profiles(include_archived=include_archived)
        return [self._public_profile(row) for row in rows]

    def get_profile(self, profile_id: str, *, include_archived: bool = True) -> dict[str, Any]:
        profile = self._profile(profile_id)
        if not include_archived and profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        return self._public_profile(profile)

    def provider_info(self, profile_id: str) -> ProviderInfo:
        profile = self._profile(profile_id)
        spec = self._spec(profile)
        status = "available" if profile["status"] == "ready" and profile["auth_state"] == "authorized" and profile["auto_chat_enabled"] else "unconfigured"
        return ProviderInfo(
            id=f"web-chat:{profile['id']}",
            name=f"{profile['name']} · {spec.name}",
            capability="llm",
            status=status,
            description="通过专用浏览器 Profile 复用网页登录态；普通聊天可按一次性授权自动发送。",
            config_schema={},
        )

    def create_profile(
        self,
        *,
        name: str,
        adapter_id: str,
        browser_profile_id: str,
        browser_instance: str | None = None,
        config: Mapping[str, Any] | None = None,
        budget_policy: str = "free-only",
        draft: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            raise WebChatRuntimeError("creating a web-chat profile requires explicit approval")
        normalized_name = _text(name, 100)
        if not normalized_name:
            raise WebChatRuntimeError("web-chat profile name is required")
        if budget_policy not in WEB_CHAT_BUDGET_POLICIES:
            raise WebChatRuntimeError("web-chat budget policy must be free-only or no-paid")
        browser_profile = self.storage.get_browser_profile(str(browser_profile_id or "").strip())
        if browser_profile is None or browser_profile.get("archived_at") is not None or browser_profile.get("status") != "active":
            raise WebChatRuntimeError("web-chat profile requires an active named BrowserSkill Profile")
        instance = _text(browser_instance, 160) if browser_instance else None
        if instance and not _SAFE_INSTANCE_RE.fullmatch(instance):
            raise WebChatRuntimeError("browser instance id is invalid")
        raw_config = dict(config or {})
        self._reject_secrets(raw_config)
        spec = self.registry.resolve(adapter_id, raw_config)
        profile_id = f"web-chat-{uuid4().hex[:12]}"
        persisted_config = spec.public_config()
        if "response_timeout_seconds" in raw_config:
            timeout_value = raw_config.get("response_timeout_seconds")
            if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)) or not 0.5 <= float(timeout_value) <= 15:
                raise WebChatRuntimeError("response_timeout_seconds must be between 0.5 and 15")
            persisted_config["response_timeout_seconds"] = float(timeout_value)
        if "observation_timeout_seconds" in raw_config:
            observation_value = raw_config.get("observation_timeout_seconds")
            if (
                isinstance(observation_value, bool)
                or not isinstance(observation_value, (int, float))
                or not 1 <= float(observation_value) <= MAX_WEB_CHAT_OBSERVATION_SECONDS
            ):
                raise WebChatRuntimeError(
                    f"observation_timeout_seconds must be between 1 and {int(MAX_WEB_CHAT_OBSERVATION_SECONDS)}"
                )
            persisted_config["observation_timeout_seconds"] = float(observation_value)
        if spec.custom:
            persisted_config["name"] = spec.name
        row = self.storage.create_web_chat_profile(
            profile_id=profile_id,
            name=normalized_name,
            adapter_id=spec.id,
            site_key=spec.id,
            browser_profile_id=str(browser_profile_id).strip(),
            browser_instance=instance,
            chat_url=spec.chat_url,
            status="draft" if draft else "needs-auth",
            auth_state="unknown" if draft else "needs-auth",
            auto_chat_enabled=False,
            allowed_actions=sorted(WEB_CHAT_ACTIONS),
            budget_policy=budget_policy,
            config=persisted_config,
            adapter_version=spec.version,
        )
        return self._public_profile(row)

    def authorize_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        """Open the dedicated chat page for one manual login.

        This method never fills credentials and intentionally does not block on
        BrowserSkill's ``request-help`` overlay.  The UI can show the isolated
        window, the user logs in there, and then calls ``check_profile``.
        """

        if not approved:
            raise WebChatRuntimeError("opening a web-chat login window requires explicit approval")
        profile = self._profile(profile_id)
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        session = self._ensure_session(profile, allow_auto=True)
        tab_id = self._ensure_chat_tab(profile, session["id"])
        updated = self.storage.update_web_chat_profile(
            profile["id"], status="needs-auth", auth_state="needs-auth", last_checked=False
        ) or profile
        return {
            **self._public_profile(updated),
            "session_id": session["id"],
            "tab_id": tab_id,
            "requires_human": True,
            "credentials_excluded": True,
            "human_action": "在隔离浏览器窗口中登录；完成后点击检查登录状态",
        }

    def open_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        """Open or reuse the isolated BrowserSkill window for a profile."""

        if not approved:
            raise WebChatRuntimeError("opening a web-chat profile requires explicit approval")
        profile = self._profile(profile_id)
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        session = self._ensure_session(profile, allow_auto=True)
        tab_id = self._ensure_chat_tab(profile, session["id"])
        return {
            **self._public_profile(profile),
            "session_id": session["id"],
            "tab_id": tab_id,
            "window_state": "opened",
            "isolated_window": True,
        }

    def focus_profile(self, profile_id: str, *, tab_id: str | None = None, approved: bool = False) -> dict[str, Any]:
        """Bring a profile's isolated tab to the foreground when supported."""

        if not approved:
            raise WebChatRuntimeError("focusing a web-chat profile requires explicit approval")
        opened = self.open_profile(profile_id, approved=True)
        session_id = str(opened.get("session_id") or "")
        try:
            result = self.browser.focus_session(session_id, tab_id=tab_id)
        except AttributeError:
            result = {"focused": False, "reason": "BrowserSkill focus is not exposed by this runtime"}
        return {**opened, **result, "window_state": "focused" if result.get("focused") else "opened"}

    def close_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        """Close only the BrowserSkill session owned by this web profile."""

        if not approved:
            raise WebChatRuntimeError("closing a web-chat profile requires explicit approval")
        profile = self._profile(profile_id)
        session_id = self.sessions.get(str(profile.get("id")))
        if session_id:
            self.browser.close_session(session_id)
            self.sessions.pop(str(profile.get("id")), None)
        return {
            **self._public_profile(profile),
            "session_id": session_id,
            "closed": True,
            "window_state": "closed",
        }

    def check_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        profile = self._profile(profile_id)
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        if not approved and not profile.get("auto_chat_enabled"):
            raise WebChatRuntimeError("checking an unapproved web-chat profile requires explicit approval")
        try:
            session = self._ensure_session(profile, allow_auto=True)
            tab_id = self._ensure_chat_tab(profile, session["id"])
        except Exception as error:
            # BrowserSkill is an optional external process.  A missing daemon,
            # extension, or disconnected tab is a normal not-ready outcome;
            # expose a bounded reason instead of leaking a backend traceback.
            if self.logger:
                try:
                    self.logger.info("web chat profile check unavailable profile=%s error_type=%s", profile_id, type(error).__name__)
                except Exception:
                    pass
            updated = self.storage.update_web_chat_profile(
                profile["id"], status="unavailable", auth_state="unknown", last_checked=True
            ) or profile
            return {
                **self._public_profile(updated),
                "page_ready": False,
                "ready": False,
                "tab_id": None,
                "reason": "隔离浏览器未连接；请启动 BrowserSkill 后重试",
            }
        if not tab_id:
            updated = self.storage.update_web_chat_profile(
                profile["id"], status="needs-auth", auth_state="unknown", last_checked=True
            ) or profile
            return {**self._public_profile(updated), "ready": False, "reason": "BrowserSkill session is not connected"}
        spec = self._spec(profile)
        try:
            snapshot = self.browser.snapshot_session(session["id"], tab_id=tab_id)
        except Exception as error:
            if self.logger:
                try:
                    self.logger.info("web chat profile snapshot unavailable profile=%s error_type=%s", profile_id, type(error).__name__)
                except Exception:
                    pass
            updated = self.storage.update_web_chat_profile(
                profile["id"], status="unavailable", auth_state="unknown", last_checked=True
            ) or profile
            return {
                **self._public_profile(updated),
                "page_ready": False,
                "ready": False,
                "tab_id": tab_id,
                "reason": "隔离浏览器页面暂不可观察；请检查 BrowserSkill 连接后重试",
            }
        snapshot_state, snapshot_payload = _validated_snapshot(snapshot)
        if snapshot_state == "invalid":
            updated = self.storage.update_web_chat_profile(
                profile["id"], status="unavailable", auth_state="unknown", last_checked=True
            ) or profile
            return {
                **self._public_profile(updated),
                "page_ready": False,
                "ready": False,
                "tab_id": tab_id,
                "reason": "隔离浏览器返回了无法识别的页面快照；请检查 BrowserSkill 后重试",
            }
        if snapshot_state != "ready":
            auth = "unknown"
            page_ready = False
        else:
            auth = _auth_state(spec, snapshot_payload)
            page_ready = _page_ready(spec, snapshot_payload, auth_state=auth)
        # Keep authorization and DOM readiness distinct.  A page that happens
        # to show a "Send" button is not sufficient evidence of a logged-in
        # account, and a logged-in account on a stale page is not send-ready.
        if auth != "authorized":
            status = "needs-auth"
        elif not page_ready:
            status = "unavailable"
        else:
            status = "ready"
        updated = self.storage.update_web_chat_profile(
            profile["id"], status=status, auth_state=auth, last_checked=True
        ) or profile
        return {
            **self._public_profile(updated),
            "page_ready": page_ready,
            "ready": auth == "authorized" and page_ready,
            "tab_id": tab_id,
            "reason": None if auth == "authorized" and page_ready else (
                "聊天页面未就绪；请打开正确的对话页面后重试"
                if auth == "authorized"
                else "登录状态无法确认；请在隔离窗口完成登录后重试"
            ),
        }

    def set_consent(
        self,
        profile_id: str,
        *,
        enabled: bool,
        allowed_actions: Iterable[str] | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            raise WebChatRuntimeError("changing automatic web-chat consent requires explicit approval")
        profile = self._profile(profile_id)
        actions = set(allowed_actions or WEB_CHAT_ACTIONS)
        if not actions.issubset(WEB_CHAT_ACTIONS):
            raise WebChatRuntimeError("web-chat consent may only include chat.read and chat.send")
        if enabled and "chat.send" not in actions:
            raise WebChatRuntimeError("automatic chat consent requires chat.send")
        if enabled and (
            profile.get("status") != "ready" or profile.get("auth_state") != "authorized"
        ):
            raise WebChatRuntimeError("请先检查网页已登录且聊天页面就绪，再启用自动聊天授权")
        next_status = profile["status"]
        if enabled and profile["auth_state"] == "authorized":
            next_status = "ready"
        elif not enabled and profile["status"] == "ready":
            next_status = "configured"
        updated = self.storage.update_web_chat_profile(
            profile["id"],
            status=next_status,
            auto_chat_enabled=bool(enabled),
            allowed_actions=sorted(actions),
        ) or profile
        return self._public_profile(updated)

    def activate_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        """Validate a consented web profile before projecting it as the LLM."""

        if not approved:
            raise WebChatRuntimeError("activating a web-chat profile requires explicit approval")
        profile = self._profile(profile_id)
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        health = self.health(profile_id)
        if not health.get("ok"):
            raise WebChatRuntimeError(str(health.get("reason") or "web-chat profile is not ready"))
        updated = self.storage.update_web_chat_profile(profile_id, status="ready", mark_used=True)
        if updated is None:
            raise WebChatRuntimeError("unknown web-chat profile")
        return self._public_profile(updated)

    def mark_used(self, profile_id: str) -> dict[str, Any]:
        """Record a successful web chat without exposing page content."""

        profile = self._profile(profile_id)
        updated = self.storage.update_web_chat_profile(
            profile_id,
            status="ready",
            auth_state="authorized",
            mark_used=True,
        ) or profile
        return self._public_profile(updated)

    def update_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        adapter_id: str | None = None,
        site_key: str | None = None,
        browser_profile_id: str | None = None,
        browser_instance: str | None = None,
        config: Mapping[str, Any] | None = None,
        budget_policy: str | None = None,
        # ``None`` means that an edit should preserve the current draft/live
        # state.  Callers that intentionally publish or demote a profile must
        # pass an explicit boolean; an omitted field must not silently revoke
        # a previously saved draft or readiness state.
        draft: bool | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Edit non-secret adapter metadata and invalidate prior readiness."""

        if not approved:
            raise WebChatRuntimeError("editing a web-chat profile requires explicit approval")
        profile = self._profile(profile_id)
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        if profile_id in self.sessions:
            raise WebChatRuntimeError("cannot edit a web-chat profile with an active session")
        raw_config = dict(config) if isinstance(config, Mapping) else dict(profile.get("config") or {})
        self._reject_secrets(raw_config)
        selected_adapter = str(adapter_id or profile.get("adapter_id") or "").strip().lower()
        if not selected_adapter:
            raise WebChatRuntimeError("web-chat adapter is required")
        spec = self.registry.resolve(selected_adapter, raw_config)
        normalized_name = _text(name if name is not None else profile.get("name"), 100)
        if not normalized_name:
            raise WebChatRuntimeError("web-chat profile name is required")
        policy = str(budget_policy or profile.get("budget_policy") or "free-only")
        if policy not in WEB_CHAT_BUDGET_POLICIES:
            raise WebChatRuntimeError("web-chat budget policy must be free-only or no-paid")
        next_browser_profile_id = str(browser_profile_id or profile.get("browser_profile_id") or "").strip()
        browser_profile = self.storage.get_browser_profile(next_browser_profile_id)
        if browser_profile is None or browser_profile.get("archived_at") is not None or browser_profile.get("status") != "active":
            raise WebChatRuntimeError("web-chat profile requires an active named BrowserSkill Profile")
        instance = str(browser_instance if browser_instance is not None else profile.get("browser_instance") or "").strip() or None
        if instance and not _SAFE_INSTANCE_RE.fullmatch(instance):
            raise WebChatRuntimeError("browser instance id is invalid")
        persisted_config = spec.public_config()
        if "response_timeout_seconds" in raw_config:
            timeout_value = raw_config.get("response_timeout_seconds")
            if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)) or not 0.5 <= float(timeout_value) <= 15:
                raise WebChatRuntimeError("response_timeout_seconds must be between 0.5 and 15")
            persisted_config["response_timeout_seconds"] = float(timeout_value)
        if spec.custom:
            persisted_config["name"] = spec.name
        next_draft = bool(draft) if draft is not None else profile.get("status") == "draft"
        updated = self.storage.update_web_chat_profile(
            profile_id,
            name=normalized_name,
            adapter_id=spec.id,
            site_key=_text(site_key or spec.id, 120),
            browser_profile_id=next_browser_profile_id,
            browser_instance=instance,
            chat_url=spec.chat_url,
            config=persisted_config,
            adapter_version=spec.version,
            budget_policy=policy,
            status="draft" if next_draft else "needs-auth",
            auth_state="unknown",
            auto_chat_enabled=False,
        )
        if updated is None:
            raise WebChatRuntimeError("unknown web-chat profile")
        return self._public_profile(updated)

    def archive_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        if not approved:
            raise WebChatRuntimeError("archiving a web-chat profile requires explicit approval")
        profile = self._profile(profile_id)
        if profile_id in self.sessions:
            try:
                self.browser.close_session(self.sessions[profile_id])
            finally:
                self.sessions.pop(profile_id, None)
        updated = self.storage.update_web_chat_profile(profile_id, archived=True)
        if updated is None:
            raise WebChatRuntimeError("unknown web-chat profile")
        return self._public_profile(updated)

    def restore_profile(self, profile_id: str, *, approved: bool = False) -> dict[str, Any]:
        if not approved:
            raise WebChatRuntimeError("restoring a web-chat profile requires explicit approval")
        profile = self._profile(profile_id)
        # Restoring metadata must not imply that an account is ready.  Consent
        # and a fresh page check are still required before activation.
        # Restoring an archived account is metadata-only.  Even if it was
        # previously authorized, require a fresh page/login check and a new
        # consent decision before it can be projected as an active Provider.
        updated = self.storage.update_web_chat_profile(
            profile_id,
            archived=False,
            status="needs-auth",
            auth_state="unknown",
            auto_chat_enabled=False,
        )
        if updated is None:
            raise WebChatRuntimeError("unknown web-chat profile")
        return self._public_profile(updated)

    # ------------------------------------------------------------------
    # Message attempt lifecycle
    # ------------------------------------------------------------------
    def _attempt_public(self, attempt: Mapping[str, Any]) -> dict[str, Any]:
        """Return a bounded attempt projection without the submitted text."""

        status = str(attempt.get("status") or "unknown")
        response = attempt.get("response") if isinstance(attempt.get("response"), Mapping) else {}
        value: dict[str, Any] = {
            "schema": WEB_CHAT_SCHEMA,
            "attempt_id": attempt.get("attempt_id"),
            "profile_id": attempt.get("profile_id"),
            "owner": attempt.get("owner"),
            "status": status,
            "accepted": bool(attempt.get("accepted")),
            "created_at": attempt.get("created_at"),
            "updated_at": attempt.get("updated_at"),
            "started_at": attempt.get("started_at"),
            "completed_at": attempt.get("completed_at"),
            "session_id": attempt.get("session_id"),
            "tab_id": attempt.get("tab_id"),
            "possibly_sent": bool(attempt.get("possibly_sent")),
            "sent": bool(attempt.get("sent")),
            "error_code": attempt.get("error_code"),
            "reason": attempt.get("reason"),
        }
        if status == "completed" and isinstance(response.get("text"), str):
            value["text"] = response["text"]
            value["ok"] = True
        else:
            value["ok"] = False
            if status in {"running", "accepted", "possibly-sent"} and attempt.get("possibly_sent"):
                value["pending"] = True
            if response.get("requires_human") or status == "waiting-human":
                value["requires_human"] = True
            if response.get("requires_approval") or status == "needs-confirmation":
                value["requires_approval"] = True
        return value

    @staticmethod
    def _attempt_terminal(status: Any) -> bool:
        return str(status or "").lower() in {
            "completed", "failed", "waiting-human", "possibly-sent",
            "unknown", "interrupted", "cancelled",
        }

    def _release_attempt(self, attempt: Mapping[str, Any]) -> None:
        done_event = attempt.get("done_event")
        if done_event is not None and not done_event.is_set():
            return
        profile_id = str(attempt.get("profile_id") or "")
        attempt_id = str(attempt.get("attempt_id") or "")
        with self._occupancy_lock:
            if self._profile_attempts.get(profile_id) == attempt_id:
                self._profile_attempts.pop(profile_id, None)
            if attempt.get("owner") == "agent":
                self._agent_occupancy.discard(profile_id)

    def _complete_attempt(self, attempt_id: str, response: Mapping[str, Any] | None, error: Exception | None = None) -> None:
        with self._occupancy_lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                return
            # Explicit cancellation/interruption wins over a late browser
            # callback.  The callback may finish in the executor, but it must
            # not turn an uncertain send into a replayable success.
            if self._attempt_terminal(attempt.get("status")):
                return
            response = dict(response or {})
            if error is not None:
                response = {"ok": False, "status": "failed", "error_code": type(error).__name__.lower().replace("_", "-")[:120], "reason": "web-chat attempt failed"}
            if response.get("ok") is True and isinstance(response.get("text"), str):
                status = "completed"
            elif response.get("requires_human") or response.get("status") == "waiting-human":
                status = "waiting-human"
            elif response.get("possibly_sent") or response.get("pending") or response.get("status") in {"possibly-sent", "unknown"}:
                status = "possibly-sent"
            elif response.get("status") == "cancelled":
                status = "cancelled"
            else:
                status = "failed"
            now = utc_now()
            attempt["status"] = status
            attempt["response"] = response
            attempt["updated_at"] = now
            attempt["completed_at"] = now
            attempt["possibly_sent"] = bool(attempt.get("possibly_sent") or response.get("possibly_sent") or status == "possibly-sent")
            attempt["error_code"] = response.get("error_code") or ("possibly-sent" if status == "possibly-sent" else None)
            attempt["reason"] = response.get("reason")

    def _run_attempt(self, attempt_id: str) -> dict[str, Any]:
        with self._occupancy_lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                return {"status": "failed", "error_code": "unknown-attempt"}
            if self._attempt_terminal(attempt.get("status")):
                return self._attempt_public(attempt)
            attempt["status"] = "running"
            attempt["started_at"] = utc_now()
            attempt["updated_at"] = attempt["started_at"]
            profile_id = str(attempt["profile_id"])
            message = str(attempt["message"])
            owner = str(attempt["owner"])
            cancel_event = attempt["cancel_event"]
        try:
            # A worker gets a longer bounded observation window than the
            # compatibility wrapper's first wait.  This lets callers poll the
            # same attempt after an early response timeout without resending.
            response = self._send_message_once(
                profile_id,
                message,
                owner=owner,
                cancel_event=cancel_event,
                attempt_id=attempt_id,
                response_timeout_seconds=None,
                observation_timeout_seconds=DEFAULT_WEB_CHAT_OBSERVATION_SECONDS,
            )
            self._complete_attempt(attempt_id, response)
        except Exception as error:  # pragma: no cover - defensive executor boundary
            self._complete_attempt(attempt_id, None, error)
        finally:
            # Observer threads are daemonized, but still mark their handle as
            # finished so a profile cannot accept a second send while the
            # previous browser action is unwinding.
            with self._occupancy_lock:
                current = self._attempts.get(attempt_id)
                if current is not None:
                    current["done_event"].set()
                    self._release_attempt(current)
        with self._occupancy_lock:
            current = self._attempts.get(attempt_id)
            return self._attempt_public(current) if current is not None else {"status": "unknown", "attempt_id": attempt_id}

    def start_message(self, profile_id: str, text: str, *, owner: str = "manual") -> dict[str, Any]:
        """Accept one web message and return an idempotent attempt handle."""

        if self._closed:
            raise WebChatRuntimeError("web-chat runtime is closed")
        profile = self._profile(profile_id)
        message = _text(text, 16_000)
        if not message:
            raise WebChatRuntimeError("web-chat message must not be empty")
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        owner = str(owner or "manual").strip().lower()
        if owner not in {"manual", "agent"}:
            raise WebChatRuntimeError("web-chat message owner is invalid")
        profile_key = str(profile["id"])
        if owner != "agent" and self.agent_occupancy(profile_key):
            return {
                "schema": WEB_CHAT_SCHEMA,
                "accepted": False,
                "ok": False,
                "status": "waiting-human",
                "requires_human": True,
                "profile_id": profile_key,
                "error_code": "profile-occupied",
                "reason": "该网页 Profile 当前由 Agent 占用；请等待或请求接管",
            }
        if not profile.get("auto_chat_enabled") or "chat.send" not in set(profile.get("allowed_actions") or []):
            return {
                "schema": WEB_CHAT_SCHEMA,
                "accepted": False,
                "ok": False,
                "status": "needs-confirmation",
                "requires_approval": True,
                "profile_id": profile_key,
                "reason": "请先启用该网页账号的一次性普通聊天授权",
            }
        if profile.get("auth_state") != "authorized":
            return {
                "schema": WEB_CHAT_SCHEMA,
                "accepted": False,
                "ok": False,
                "status": "waiting-human",
                "requires_human": True,
                "profile_id": profile_key,
                "reason": "网页登录状态未确认；请在隔离窗口登录后检查状态",
            }
        attempt_id = f"web-attempt-{uuid4().hex[:16]}"
        now = utc_now()
        with self._occupancy_lock:
            active_id = self._profile_attempts.get(profile_key)
            active = self._attempts.get(active_id) if active_id else None
            if active is not None and (
                not self._attempt_terminal(active.get("status"))
                or not active.get("done_event", threading.Event()).is_set()
            ):
                return {
                    "schema": WEB_CHAT_SCHEMA,
                    "accepted": False,
                    "ok": False,
                    "status": "waiting-human",
                    "requires_human": True,
                    "profile_id": profile_key,
                    "error_code": "profile-occupied",
                    "reason": "该网页 Profile 当前已有消息回合；请等待其结束或请求接管",
                }
            attempt = {
                "attempt_id": attempt_id,
                "profile_id": profile_key,
                "owner": owner,
                "message": message,
                "status": "accepted",
                "accepted": True,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "session_id": None,
                "tab_id": None,
                "possibly_sent": False,
                "sent": False,
                "response": {},
                "error_code": None,
                "reason": None,
                "cancel_event": threading.Event(),
                "done_event": threading.Event(),
                "thread": None,
            }
            self._attempts[attempt_id] = attempt
            self._profile_attempts[profile_key] = attempt_id
            if owner == "agent":
                self._agent_occupancy.add(profile_key)
        try:
            observer = threading.Thread(
                target=self._run_attempt,
                args=(attempt_id,),
                name=f"sumika-web-chat-{attempt_id[-8:]}",
                daemon=True,
            )
            with self._occupancy_lock:
                attempt["thread"] = observer
            observer.start()
        except Exception as error:
            with self._occupancy_lock:
                attempt["done_event"].set()
            self._complete_attempt(attempt_id, None, error)
            with self._occupancy_lock:
                self._release_attempt(attempt)
        with self._occupancy_lock:
            return self._attempt_public(self._attempts[attempt_id])

    def message_status(self, attempt_id: str) -> dict[str, Any]:
        identifier = _text(attempt_id, 120)
        with self._occupancy_lock:
            attempt = self._attempts.get(identifier)
            if attempt is not None:
                return {**self._attempt_public(attempt), "found": True}
        return {"schema": WEB_CHAT_SCHEMA, "attempt_id": identifier, "found": False, "status": "unknown", "ok": False}

    def wait_message(self, attempt_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        identifier = _text(attempt_id, 120)
        with self._occupancy_lock:
            attempt = self._attempts.get(identifier)
        if attempt is None:
            return {"schema": WEB_CHAT_SCHEMA, "attempt_id": identifier, "found": False, "status": "unknown", "ok": False}
        try:
            wait_seconds = max(0.0, min(30.0, float(timeout if timeout is not None else 15.0)))
        except (TypeError, ValueError):
            wait_seconds = 15.0
        attempt["done_event"].wait(wait_seconds)
        with self._occupancy_lock:
            return {**self._attempt_public(attempt), "found": True}

    def cancel_message(self, attempt_id: str) -> dict[str, Any]:
        identifier = _text(attempt_id, 120)
        with self._occupancy_lock:
            attempt = self._attempts.get(identifier)
            if attempt is None:
                return {"schema": WEB_CHAT_SCHEMA, "attempt_id": identifier, "found": False, "cancelled": False}
            if self._attempt_terminal(attempt.get("status")):
                return {**self._attempt_public(attempt), "found": True, "cancelled": False, "reason": "already-finished"}
            attempt["cancel_event"].set()
            attempt["status"] = "cancelled"
            attempt["possibly_sent"] = bool(attempt.get("possibly_sent") or attempt.get("started_at"))
            attempt["error_code"] = "cancelled"
            attempt["reason"] = "web-chat attempt cancelled; it will not be resent"
            attempt["completed_at"] = utc_now()
            attempt["updated_at"] = attempt["completed_at"]
            self._release_attempt(attempt)
            return {**self._attempt_public(attempt), "found": True, "cancelled": True}

    def send_message(self, profile_id: str, text: str, *, owner: str = "manual") -> dict[str, Any]:
        """Compatibility wrapper: start one attempt and wait for its first result."""

        accepted = self.start_message(profile_id, text, owner=owner)
        if not accepted.get("accepted"):
            return accepted
        profile = self._profile(profile_id)
        config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
        try:
            timeout_seconds = min(15.0, max(0.5, float(config.get("response_timeout_seconds", 4))))
        except (TypeError, ValueError):
            timeout_seconds = 4.0
        result = self.wait_message(str(accepted["attempt_id"]), timeout=timeout_seconds)
        if result.get("status") == "completed":
            return result
        # Preserve the old ``pending`` flag while exposing the stronger
        # possibly-sent state to new callers.
        if result.get("status") in {"running", "accepted"}:
            result = {**result, "status": "possibly-sent", "pending": True, "possibly_sent": True, "error_code": "response-pending"}
        return result

    def _send_message_once(
        self,
        profile_id: str,
        text: str,
        *,
        owner: str = "manual",
        cancel_event: threading.Event | None = None,
        attempt_id: str | None = None,
        response_timeout_seconds: float | None = None,
        observation_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Send one ordinary chat message through a consented web account."""

        profile = self._profile(profile_id)
        message = _text(text, 16_000)
        def cancelled() -> dict[str, Any] | None:
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "ok": False,
                    "status": "cancelled",
                    "profile_id": profile_id,
                    "error_code": "cancelled",
                    "possibly_sent": bool(attempt_id),
                    "reason": "web-chat attempt cancelled; it will not be resent",
                }
            return None

        def mark_attempt(**values: Any) -> None:
            if not attempt_id:
                return
            with self._occupancy_lock:
                attempt = self._attempts.get(attempt_id)
                if attempt is not None:
                    attempt.update(values)

        if not message:
            raise WebChatRuntimeError("web-chat message must not be empty")
        if profile.get("archived_at"):
            raise WebChatRuntimeError("web-chat profile is archived")
        if owner != "agent" and self.agent_occupancy(profile_id):
            return {
                "ok": False,
                "status": "waiting-human",
                "requires_human": True,
                "profile_id": profile_id,
                "error_code": "profile-occupied",
                "reason": "该网页 Profile 当前由 Agent 占用；请等待或请求接管",
            }
        if not profile.get("auto_chat_enabled") or "chat.send" not in set(profile.get("allowed_actions") or []):
            return {
                "ok": False,
                "status": "needs-confirmation",
                "requires_approval": True,
                "profile_id": profile_id,
                "reason": "请先启用该网页账号的一次性普通聊天授权",
            }
        if profile.get("auth_state") != "authorized":
            return {
                "ok": False,
                "status": "waiting-human",
                "requires_human": True,
                "profile_id": profile_id,
                "reason": "网页登录状态未确认；请在隔离窗口登录后检查状态",
            }
        spec = self._spec(profile)
        early = cancelled()
        if early:
            return early
        try:
            session = self._ensure_session(profile, allow_auto=True, no_focus=owner == "agent")
            tab_id = self._ensure_chat_tab(profile, session["id"])
            mark_attempt(session_id=session.get("id"), tab_id=tab_id)
        except Exception as error:
            if self.logger:
                try:
                    self.logger.info("web chat send unavailable profile=%s error_type=%s", profile_id, type(error).__name__)
                except Exception:
                    pass
            return {
                "ok": False,
                "status": "failed",
                "profile_id": profile_id,
                "reason": "隔离浏览器不可用；消息未发送",
            }
        if not tab_id:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": "BrowserSkill session is not connected"}

        try:
            before = self.browser.snapshot_session(session["id"], tab_id=tab_id)
        except Exception:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": "无法读取聊天页面；消息未发送"}
        # A profile can become logged out or navigate away after the last
        # explicit check.  Re-evaluate both signals immediately before any
        # fill/click/press action.  Never treat a visible send button as proof
        # of authentication, and never continue on a stale DOM snapshot.
        before_state, before_payload = _validated_snapshot(before)
        if before_state == "invalid":
            self.storage.update_web_chat_profile(
                profile_id, status="unavailable", auth_state="unknown", last_checked=True
            )
            return {
                "ok": False,
                "status": "failed",
                "profile_id": profile_id,
                "reason": "隔离浏览器返回了无法识别的页面快照；消息未发送",
            }
        if before_state != "ready":
            self.storage.update_web_chat_profile(
                profile_id, status="unavailable", last_checked=True
            )
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": "聊天页面暂不可观察；消息未发送"}
        before_auth = _auth_state(spec, before_payload)
        before_page_ready = _page_ready(spec, before_payload, auth_state=before_auth)
        if before_auth != "authorized":
            self.storage.update_web_chat_profile(
                profile_id, status="needs-auth", auth_state=before_auth, last_checked=True
            )
            return {
                "ok": False,
                "status": "waiting-human",
                "requires_human": True,
                "profile_id": profile_id,
                "reason": "网页登录状态已变化；请在隔离窗口重新登录后检查状态",
            }
        if not before_page_ready:
            self.storage.update_web_chat_profile(
                profile_id, status="unavailable", auth_state=before_auth, last_checked=True
            )
            return {
                "ok": False,
                "status": "failed",
                "profile_id": profile_id,
                "reason": "聊天页面结构或就绪标记已变化；消息未发送",
            }
        self.storage.update_web_chat_profile(
            profile_id, status="ready", auth_state=before_auth, last_checked=True
        )
        baseline = None
        try:
            baseline = _extract_assistant_text(
                before_payload, selectors=spec.selectors.get("response", ())
            )
        except WebChatRuntimeError as error:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": str(error)}
        input_result: dict[str, Any] | None = None
        input_selector = None
        for selector in spec.selectors.get("input", ()):
            early = cancelled()
            if early:
                return early
            try:
                candidate = self.browser.execute_action(
                    session["id"],
                    action="fill",
                    target=selector,
                    value=message,
                    approved=True,
                    tab_id=tab_id,
                )
            except Exception:
                candidate = {"executed": False}
            input_result = candidate if isinstance(candidate, dict) else {"executed": False}
            if input_result.get("executed"):
                input_selector = selector
                break
            if input_result.get("requires_human"):
                return {"ok": False, "status": "waiting-human", "requires_human": True, "profile_id": profile_id, "reason": input_result.get("reason")}
        if not input_selector:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": "未找到安全的聊天输入框；适配器已停止"}

        sent = False
        send_result: dict[str, Any] | None = None
        for selector in spec.selectors.get("send", ()):
            early = cancelled()
            if early:
                return early
            try:
                candidate = self.browser.execute_action(
                    session["id"], action="click", target=selector, approved=True, tab_id=tab_id
                )
            except Exception:
                candidate = {"executed": False}
            send_result = candidate if isinstance(candidate, dict) else {"executed": False}
            if send_result.get("executed"):
                sent = True
                break
        if not sent:
            early = cancelled()
            if early:
                return early
            try:
                candidate = self.browser.execute_action(
                    session["id"],
                    action="press",
                    target=input_selector,
                    key="Enter",
                    approved=True,
                    tab_id=tab_id,
                )
            except Exception:
                candidate = {"executed": False}
            send_result = candidate if isinstance(candidate, dict) else {"executed": False}
            sent = bool(send_result.get("executed"))
        if not sent:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": "发送按钮或 Enter 操作未执行"}

        mark_attempt(sent=True, possibly_sent=True)

        response: str | None = None
        stored_config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
        if response_timeout_seconds is not None:
            initial_timeout_seconds = min(15.0, max(0.5, float(response_timeout_seconds)))
        else:
            try:
                initial_timeout_seconds = min(15.0, max(0.5, float(stored_config.get("response_timeout_seconds", 4))))
            except (TypeError, ValueError):
                initial_timeout_seconds = 4.0
        if observation_timeout_seconds is not None:
            max_observation_seconds = min(MAX_WEB_CHAT_OBSERVATION_SECONDS, max(initial_timeout_seconds, float(observation_timeout_seconds)))
        else:
            try:
                max_observation_seconds = min(
                    MAX_WEB_CHAT_OBSERVATION_SECONDS,
                    max(initial_timeout_seconds, float(stored_config.get("observation_timeout_seconds", DEFAULT_WEB_CHAT_OBSERVATION_SECONDS))),
                )
            except (TypeError, ValueError):
                max_observation_seconds = DEFAULT_WEB_CHAT_OBSERVATION_SECONDS
        started_observing = time.monotonic()
        initial_deadline = started_observing + initial_timeout_seconds
        deadline = started_observing + max_observation_seconds
        pending_marked = False
        while time.monotonic() <= deadline:
            early = cancelled()
            if early:
                return early
            try:
                observed = self.browser.snapshot_session(session["id"], tab_id=tab_id)
            except Exception:
                break
            observed_state, observed_payload = _validated_snapshot(observed)
            if observed_state == "invalid":
                self.storage.update_web_chat_profile(
                    profile_id, status="unavailable", auth_state="unknown", last_checked=True
                )
                return {
                    "ok": False,
                    "status": "possibly-sent",
                    "possibly_sent": True,
                    "profile_id": profile_id,
                    "reason": "隔离浏览器返回了无法识别的页面快照；消息状态无法确认",
                }
            if observed_state != "ready":
                self.storage.update_web_chat_profile(
                    profile_id, status="unavailable", last_checked=True
                )
                break
            observed_auth = _auth_state(spec, observed_payload)
            observed_page_ready = _page_ready(spec, observed_payload, auth_state=observed_auth)
            if observed_auth != "authorized":
                self.storage.update_web_chat_profile(
                    profile_id, status="needs-auth", auth_state=observed_auth, last_checked=True
                )
                return {
                    "ok": False,
                    "status": "possibly-sent",
                    "possibly_sent": True,
                    "requires_human": True,
                    "profile_id": profile_id,
                    "reason": "网页登录状态在等待回复期间失效；请重新登录",
                }
            if not observed_page_ready:
                self.storage.update_web_chat_profile(
                    profile_id, status="unavailable", auth_state=observed_auth, last_checked=True
                )
                return {
                    "ok": False,
                    "status": "possibly-sent",
                    "possibly_sent": True,
                    "error_code": "possibly-sent",
                    "profile_id": profile_id,
                    "reason": "等待回复时聊天页面已离开就绪状态",
                }
            try:
                candidate = _extract_assistant_text(
                    observed_payload, selectors=spec.selectors.get("response", ())
                )
            except WebChatRuntimeError as error:
                return {"ok": False, "status": "possibly-sent", "possibly_sent": True, "error_code": "possibly-sent", "profile_id": profile_id, "reason": str(error)}
            if candidate and candidate != baseline:
                response = candidate
                break
            if not pending_marked and time.monotonic() >= initial_deadline:
                # Keep the attempt running after the compatibility wrapper's
                # short wait.  The caller can poll this same id; no second
                # fill/click/press action will ever be issued.
                pending_marked = True
                mark_attempt(
                    status="running",
                    pending=True,
                    error_code="response-pending",
                    reason="消息已发送，继续等待同一网页回合的 assistant 响应",
                )
            time.sleep(0.25)
        if response is None:
            return {
                "ok": False,
                "status": "possibly-sent",
                "pending": True,
                "possibly_sent": True,
                "error_code": "response-pending",
                "profile_id": profile_id,
                "reason": "消息已发送，暂未找到明确的 assistant 响应；不会生成替代文本",
            }
        updated = self.mark_used(profile_id)
        if self.logger:
            try:
                self.logger.info("web chat completed profile=%s adapter=%s response_chars=%d", profile_id, spec.id, len(response))
            except Exception:
                pass
        return {"ok": True, "status": "completed", "profile_id": profile_id, "adapter_id": spec.id, "text": response, "profile": updated}

    def health(self, profile_id: str) -> dict[str, Any]:
        profile = self._profile(profile_id)
        page_ready = bool(profile.get("status") == "ready")
        ready = bool(page_ready and profile["auth_state"] == "authorized" and profile["auto_chat_enabled"])
        return {
            "ok": ready,
            "profile_id": profile_id,
            "status": profile["status"],
            "auth_state": profile["auth_state"],
            "page_ready": page_ready,
            "auto_chat_enabled": bool(profile["auto_chat_enabled"]),
            "quota_state": "unknown",
            "reason": None if ready else "web-chat profile is not consented, authenticated, and page-ready",
        }

    def close(self) -> None:
        # Close only sessions created by this runtime.  BrowserRuntime owns the
        # backend BrowserSkill ids and releases named-profile leases there.
        with self._occupancy_lock:
            if self._closed:
                return
            self._closed = True
            active_attempts = [
                attempt for attempt in self._attempts.values()
                if not self._attempt_terminal(attempt.get("status"))
            ]
            for attempt in active_attempts:
                attempt["cancel_event"].set()
                attempt["status"] = "interrupted"
                attempt["possibly_sent"] = bool(attempt.get("possibly_sent") or attempt.get("started_at"))
                attempt["error_code"] = "core-shutdown"
                attempt["reason"] = "Core closed before the web response was confirmed"
                attempt["completed_at"] = utc_now()
                attempt["updated_at"] = attempt["completed_at"]
                self._release_attempt(attempt)
        for profile_id, session_id in list(self.sessions.items()):
            try:
                self.browser.close_session(session_id)
            except Exception as error:
                if self.logger:
                    try:
                        self.logger.warning(
                            "web chat session shutdown skipped profile=%s error_type=%s",
                            profile_id,
                            type(error).__name__,
                        )
                    except Exception:
                        pass
            finally:
                self.sessions.pop(profile_id, None)
        with self._occupancy_lock:
            self._agent_occupancy.clear()
        # Attempts are observed by daemon threads.  There is no executor to
        # shut down anymore; cancellation above marks the attempt terminal and
        # the thread will stop at its next BrowserSkill boundary.

    def _profile(self, profile_id: str) -> dict[str, Any]:
        normalized = str(profile_id or "").strip()
        if not _PROFILE_ID_RE.fullmatch(normalized):
            raise WebChatRuntimeError("web-chat profile id is invalid")
        profile = self.storage.get_web_chat_profile(normalized)
        if profile is None:
            raise WebChatRuntimeError("unknown web-chat profile")
        return profile

    def _spec(self, profile: Mapping[str, Any]) -> WebChatAdapterSpec:
        config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
        return self.registry.resolve(str(profile.get("adapter_id") or ""), config)

    def _ensure_session(self, profile: Mapping[str, Any], *, allow_auto: bool, no_focus: bool = False) -> dict[str, Any]:
        profile_id = str(profile["id"])
        existing_id = self.sessions.get(profile_id)
        if existing_id:
            try:
                for item in self.browser.list_sessions():
                    if str(item.get("id")) == existing_id:
                        return {"id": existing_id, **item}
            except Exception:
                pass
            self.sessions.pop(profile_id, None)
        if not allow_auto and not profile.get("auto_chat_enabled"):
            raise WebChatRuntimeError("web-chat session requires explicit consent")
        binding = self.storage.get_browser_profile(str(profile["browser_profile_id"]))
        if binding is None:
            raise WebChatRuntimeError("bound BrowserSkill Profile no longer exists")
        session = self.browser.create_session(
            profile="named",
            profile_id=str(profile["browser_profile_id"]),
            character_id=binding.get("character_id"),
            agent_id=binding.get("agent_id"),
            browser_instance=profile.get("browser_instance"),
            approved=True,
            no_focus=bool(no_focus),
        )
        self.sessions[profile_id] = str(session["id"])
        return session

    def _ensure_chat_tab(self, profile: Mapping[str, Any], session_id: str) -> str | None:
        spec = self._spec(profile)
        try:
            tabs = self.browser.list_tabs(session_id).get("tabs", [])
        except Exception:
            tabs = []
        for tab in tabs if isinstance(tabs, list) else []:
            if not isinstance(tab, dict):
                continue
            raw_url = str(tab.get("url") or "")
            host = (urlparse(raw_url).hostname or "").lower()
            if host in spec.domains and tab.get("id"):
                return str(tab["id"])
        try:
            created = self.browser.create_tab(session_id, url=spec.chat_url, approved=True)
        except Exception as error:
            raise WebChatRuntimeError(f"could not open web-chat page: {type(error).__name__}") from error
        if not created.get("executed"):
            return None
        result = created.get("result")
        if isinstance(result, dict):
            tab_id = result.get("id") or result.get("tab_id")
            if tab_id:
                return str(tab_id)
        # BrowserSkill versions differ in create-tab response shape.  Re-list
        # tabs and choose the newly opened tab without exposing page content.
        try:
            tabs = self.browser.list_tabs(session_id).get("tabs", [])
            for tab in tabs if isinstance(tabs, list) else []:
                if isinstance(tab, dict) and tab.get("id"):
                    if (urlparse(str(tab.get("url") or "")).hostname or "").lower() in spec.domains:
                        return str(tab["id"])
        except Exception:
            pass
        return None

    @staticmethod
    def _reject_secrets(value: Any, *, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if _SECRET_KEY_RE.search(str(key)):
                    raise WebChatRuntimeError("web-chat adapter config must not contain credentials")
                WebChatRuntime._reject_secrets(item, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value[:64]:
                WebChatRuntime._reject_secrets(item, depth=depth + 1)
        elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
            raise WebChatRuntimeError("web-chat adapter config appears to contain credentials")

    def _public_profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        spec = self._spec(profile)
        active_session = self.sessions.get(str(profile.get("id")))
        browser_lease = None
        browser_lease_owner = "none"
        browser_profile_id = str(profile.get("browser_profile_id") or "")
        try:
            browser_profiles = self.browser.list_profiles(include_archived=True)
            browser_profile = next((item for item in browser_profiles if str(item.get("id")) == browser_profile_id), None)
            if browser_profile and browser_profile.get("leased"):
                browser_lease = browser_profile.get("lease_expires_at")
                # BrowserRuntime intentionally exposes no owner token.  The
                # active session flag is enough to distinguish this Core's
                # lease from an unknown external owner at the UI boundary.
                browser_lease_owner = "this-core" if active_session else "other-core"
        except Exception:
            browser_lease = None
        stored_config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
        return {
            "id": str(profile.get("id") or ""),
            "name": str(profile.get("name") or ""),
            "adapter_id": spec.id,
            "adapter_name": spec.name,
            "site_key": str(profile.get("site_key") or spec.id),
            "browser_profile_id": str(profile.get("browser_profile_id") or ""),
            "browser_instance": str(profile.get("browser_instance") or "") or None,
            "chat_url": spec.chat_url,
            "status": str(profile.get("status") or "unknown"),
            "auth_state": str(profile.get("auth_state") or "unknown"),
            "page_ready": str(profile.get("status") or "") == "ready",
            "auto_chat_enabled": bool(profile.get("auto_chat_enabled")),
            "allowed_actions": sorted(str(item) for item in (profile.get("allowed_actions") or [])),
            "budget_policy": str(profile.get("budget_policy") or "free-only"),
            "adapter_version": str(profile.get("adapter_version") or spec.version),
            "created_at": profile.get("created_at"),
            "updated_at": profile.get("updated_at"),
            "last_checked_at": profile.get("last_checked_at"),
            "last_used_at": profile.get("last_used_at"),
            "archived_at": profile.get("archived_at"),
            "active_session": bool(active_session),
            "browser_profile_leased": bool(browser_lease),
            "browser_profile_lease_owner": browser_lease_owner,
            "browser_profile_lease_expires_at": browser_lease,
            "agent_occupied": self.agent_occupancy(str(profile.get("id") or "")),
            "credentials_stored_in": "BrowserSkill 专用浏览器 Profile（Sumika 不读取 Cookie）",
            "config": {
                "domains": list(spec.domains),
                "chat_url": spec.chat_url,
                "selectors": {key: list(value) for key, value in spec.selectors.items()},
                "login_markers": list(spec.login_markers),
                "authorized_markers": list(spec.authorized_markers),
                "ready_markers": list(spec.ready_markers),
                "model_id": spec.model_id,
                "response_timeout_seconds": stored_config.get("response_timeout_seconds", 4),
                "observation_timeout_seconds": stored_config.get(
                    "observation_timeout_seconds", DEFAULT_WEB_CHAT_OBSERVATION_SECONDS
                ),
            },
        }


class WebChatProvider(LLMProvider):
    """LLM provider projection backed by one consented web-chat profile."""

    def __init__(self, runtime: WebChatRuntime, profile_id: str) -> None:
        self.runtime = runtime
        self.profile_id = profile_id
        self.info = runtime.provider_info(profile_id)

    def refresh(self) -> None:
        self.info = self.runtime.provider_info(self.profile_id)

    def health_check(self) -> dict[str, Any]:
        self.refresh()
        result = self.runtime.health(self.profile_id)
        return {"provider_id": self.info.id, **result}

    def stream(self, request: ChatRequest) -> Iterable[str]:
        latest = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "",
        )
        result = self.runtime.send_message(self.profile_id, latest)
        if not result.get("ok"):
            reason = str(result.get("reason") or "web-chat provider did not return a response")
            if result.get("requires_human"):
                reason = f"需要人工登录：{reason}"
            elif result.get("requires_approval"):
                reason = f"需要启用网页聊天授权：{reason}"
            raise RuntimeError(reason)
        text = result.get("text")
        if not isinstance(text, str) or not text:
            raise RuntimeError("web-chat provider returned no assistant response")
        yield text

    def close(self) -> None:
        return None


__all__ = [
    "WEB_CHAT_SCHEMA",
    "WEB_CHAT_ADAPTER_VERSION",
    "WEB_CHAT_ACTIONS",
    "WebChatAdapterSpec",
    "WebChatAdapterRegistry",
    "WebChatRuntime",
    "WebChatRuntimeError",
    "WebChatProvider",
]
