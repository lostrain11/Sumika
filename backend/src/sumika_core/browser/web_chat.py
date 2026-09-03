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
from typing import Any, Callable, Iterable, Mapping, TYPE_CHECKING
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
WEB_CHAT_SUBMISSION_STRATEGIES = frozenset({"click-first", "enter-first"})
_ACCOUNT_BUTTON_MARKER = "__account_button__"
DEFAULT_WEB_CHAT_OBSERVATION_SECONDS = 300.0
MAX_WEB_CHAT_OBSERVATION_SECONDS = 300.0
PROFILE_PAGE_LOAD_TIMEOUT_SECONDS = 5.0
PROFILE_PAGE_LOAD_POLL_SECONDS = 0.2
WEB_CHAT_PRIMARY_SEND_READY_POLLS = 10
WEB_CHAT_DEFAULT_SUBMISSION_CONFIRM_POLLS = 2
WEB_CHAT_QWEN_SUBMISSION_CONFIRM_POLLS = 8
WEB_CHAT_SNAPSHOT_MAX_TOKENS = 8_000
WEB_CHAT_RESPONSE_STABLE_OBSERVATIONS = 3
WEB_CHAT_RESPONSE_STABLE_SECONDS = 1.5
WEB_CHAT_WORKER_IDLE_CLOSE_SECONDS = 60.0
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
_LEGACY_UNSCOPED_SEND_SELECTORS = frozenset(
    {
        "button[type='submit']",
        'button[type="submit"]',
        "button[aria-label*='Send']",
        'button[aria-label*="Send"]',
        "button[aria-label*='发送']",
        'button[aria-label*="发送"]',
    }
)
_QWEN_UNSCOPED_RESPONSE_SELECTORS = frozenset(
    {
        "[class*='markdown']",
        '[class*="markdown"]',
        "[data-message-author-role='assistant']",
        '[data-message-author-role="assistant"]',
        "[data-message-author-role=assistant]",
        "[data-testid*='assistant']",
        '[data-testid*="assistant"]',
        "[data-testid*=assistant]",
        "[class*='assistant']",
        '[class*="assistant"]',
        "[class*=assistant]",
    }
)
_KIMI_UNSCOPED_RESPONSE_SELECTORS = frozenset(
    {
        "div.markdown-container.toolcall-content-text",
        "[data-message-author-role='assistant']",
        '[data-message-author-role="assistant"]',
        "[data-message-author-role=assistant]",
        "[data-testid*='assistant']",
        '[data-testid*="assistant"]',
        "[data-testid*=assistant]",
        "[class*='assistant']",
        '[class*="assistant"]',
        "[class*=assistant]",
    }
)


class WebChatRuntimeError(RuntimeError):
    """Raised when a web-chat profile cannot be used safely."""


class _StaleBrowserSession(WebChatRuntimeError):
    """A cached BrowserSkill session is conclusively gone.

    This private distinction is important: only an explicit missing-session
    signal may release a profile binding.  Transport timeouts and other
    transient failures must leave the binding intact for a later retry.
    """


_MISSING_SESSION_RE = re.compile(
    r"(?i)(?:\bnot[_ -]?found\b|\bnot registered\b|\bunknown (?:browser )?session\b|"
    r"\bsession\s+(?:does not|doesn't)\s+exist\b|会话(?:不存在|未注册))"
)


def _is_missing_browser_session(error: BaseException) -> bool:
    """Recognize only explicit BrowserSkill missing-session responses."""

    current: BaseException | None = error
    for _ in range(4):
        if current is None:
            break
        code = str(getattr(current, "code", "") or "").strip().casefold().replace("-", "_")
        if code in {"not_found", "session_not_found", "unknown_session"}:
            return True
        if _MISSING_SESSION_RE.search(str(current)):
            return True
        cause = current.__cause__ or current.__context__
        current = cause if isinstance(cause, BaseException) else None
    return False


def _text(value: Any, limit: int = 240, *, allow_newlines: bool = False) -> str:
    if not isinstance(value, str):
        value = str(value or "")
    value = value.strip()
    if len(value) > limit:
        value = value[:limit]
    allowed_controls = {"\n", "\r", "\t"} if allow_newlines else set()
    if any((ord(char) < 32 and char not in allowed_controls) or ord(char) == 127 for char in value):
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
    submission_strategy: str = "click-first"
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
        strategy = _text(self.submission_strategy, 40).lower() or "click-first"
        if strategy not in WEB_CHAT_SUBMISSION_STRATEGIES:
            raise WebChatRuntimeError("web-chat submission strategy is invalid")
        object.__setattr__(self, "submission_strategy", strategy)
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
            "submission_strategy": self.submission_strategy,
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
            "submission_strategy": self.submission_strategy,
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
        "send": ("button[aria-label='Send']", "button[aria-label='发送']"),
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
            selectors={
                **selectors,
                "input": ("textarea[placeholder*='DeepSeek']", *selectors["input"]),
                # DeepSeek currently renders the composer control as a div
                # with role=button, so button[type=submit] is never present.
                "send": (
                    "div[role='button'].ds-button--primary.ds-button--filled.ds-button--circle:not(.ds-button--disabled)",
                    "div[role='button'].ds-button--primary:not(.ds-button--disabled)",
                    *selectors["send"],
                ),
                "response": (
                    "div.ds-markdown.ds-assistant-message-main-content",
                    "[class*='ds-markdown']",
                    *selectors["response"],
                ),
            },
            # The current shell renders the signed-in display name as a
            # duplicated account button rather than exposing a logout label.
            # BrowserRuntime evaluates this structural marker without
            # returning the account name.
            authorized_markers=(
                "退出登录",
                "Log out",
                "Sign out",
                "注销",
                "Open User Menu",
                "用户菜单",
                "个人中心",
            ),
            ready_markers=("新对话", "New chat", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="chatgpt-web",
            name="ChatGPT 网页聊天",
            domains=("chatgpt.com", "chat.openai.com"),
            chat_url="https://chatgpt.com/",
            selectors={
                **selectors,
                # Keep the established prompt id first for older shells; the
                # current mobile/web-compatible composer follows as a
                # declarative fallback.
                "input": (
                    "#prompt-textarea",
                    "textarea[data-composer-draft-react]",
                    "#mobile-composer-prompt",
                    *selectors["input"],
                ),
                "send": (
                    "[data-testid='send-button']",
                    "button[data-composer-submit]",
                    "button[aria-label='发送消息']",
                    "button[aria-label='Send message']",
                    *selectors["send"],
                ),
                "response": (
                    "[data-assistant-markdown]",
                    "[data-message-role='assistant']",
                    *selectors["response"],
                ),
            },
            submission_strategy="enter-first",
            authorized_markers=(
                "退出登录",
                "Log out",
                "Sign out",
                "注销",
                "打开个人资料菜单",
                "打开“个人资料”菜单",
                "打开\"个人资料\"菜单",
                "账户菜单",
                "Account menu",
                "Open profile menu",
                "Open user menu",
            ),
            ready_markers=("New chat", "新聊天", "Send", "发送"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="zhipu-web",
            name="智谱网页聊天",
            domains=("chat.z.ai", "chatglm.cn"),
            chat_url="https://chat.z.ai/",
            selectors={
                **selectors,
                "input": ("textarea[placeholder*='有什么我能帮']", *selectors["input"]),
                "response": (
                    "div.chat-assistant.markdown-prose",
                    "[class*='markdown']",
                    *selectors["response"],
                ),
            },
            # The current z.ai shell exposes this account control instead of
            # rendering a literal "Log out" label in the accessibility tree.
            authorized_markers=("退出登录", "Log out", "Sign out", "注销", "Open User Menu"),
            ready_markers=("新建对话", "发送", "Send", "有什么我能帮您的？", "我能为你创造什么？", "与 z.ai 互动", "Z.ai - Advanced AI Chatbot"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="qwen-web",
            name="Qwen 网页聊天",
            domains=("chat.qwen.ai",),
            chat_url="https://chat.qwen.ai/",
            selectors={
                **selectors,
                "input": (
                    "textarea.message-input-textarea.message-input-textarea-separation",
                    *selectors["input"],
                ),
                "send": ("button.send-button[aria-label='发送']", *selectors["send"]),
                "response": (
                    "div.response-message-content.phase-answer",
                    "div.custom-qwen-markdown",
                    "div.qwen-markdown",
                ),
            },
            authorized_markers=("User profile", "退出登录", "Log out", "Sign out", "注销"),
            ready_markers=("新建对话", "新对话", "发送", "Send"),
            model_id="web-session",
        ),
        WebChatAdapterSpec(
            id="kimi-web",
            name="Kimi 网页聊天",
            domains=("www.kimi.com", "kimi.moonshot.cn"),
            chat_url="https://www.kimi.com/",
            # Kimi's current home composer is the blank-chat entry point.  It
            # uses a contenteditable editor and a div-based send control
            # rather than the button/textarea shape used by other sites.
            selectors={
                **selectors,
                "input": (".chat-input-editor", "[contenteditable='true']", "textarea"),
                "send": (
                    ".send-button-container:not(.disabled)",
                    ".send-button-container",
                    *selectors["send"],
                ),
                "response": (
                    "div[class='markdown-container']",
                ),
            },
            # The signed-in Kimi shell exposes the account entry as
            # “我的 Kimi” instead of a literal logout label.
            authorized_markers=("退出登录", "Log out", "Sign out", "注销", "我的 Kimi", "My Kimi"),
            ready_markers=(
                "新建会话",
                "新建对话",
                "新对话",
                "输入 \"/\" 唤起插件和技能",
                "发送",
                "Send",
            ),
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
                submission_strategy=raw.get("submission_strategy") or "click-first",
            )
        if base is None:
            raise WebChatRuntimeError(f"unknown web-chat adapter: {normalized}")
        # Built-in presets allow safe selector/marker overrides so a user can
        # repair a DOM change without shipping executable code.
        selectors_value = raw.get("selectors") if isinstance(raw.get("selectors"), dict) else {}
        selectors = dict(base.selectors)
        for key in ("input", "send", "response"):
            if key in selectors_value:
                configured = _selector_list(selectors_value[key], required=key == "input")
                if key == "send":
                    # Older built-in profiles persisted broad defaults that can
                    # match unrelated form controls.  Built-ins now require a
                    # semantically scoped selector; custom adapters remain the
                    # escape hatch for sites that truly need a submit button.
                    configured = tuple(
                        selector
                        for selector in configured
                        if selector not in _LEGACY_UNSCOPED_SEND_SELECTORS
                    )
                if key == "response" and base.id == "qwen-web":
                    configured = tuple(
                        selector
                        for selector in configured
                        if selector not in _QWEN_UNSCOPED_RESPONSE_SELECTORS
                    )
                if key == "response" and base.id == "kimi-web":
                    configured = tuple(
                        selector
                        for selector in configured
                        if selector not in _KIMI_UNSCOPED_RESPONSE_SELECTORS
                    )
                # Profiles created from an older built-in persist that
                # release's broad defaults.  Keep current adapter selectors
                # first while retaining explicit user repair selectors as
                # fallbacks, so an old profile cannot mask a shipped fix.
                selectors[key] = tuple(dict.fromkeys((*base.selectors[key], *configured)))[:16]
        domains = _domain_list(raw.get("domains", base.domains))
        chat_url = _safe_url(raw.get("chat_url", base.chat_url), domains=domains)

        def merged_markers(key: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
            if key not in raw:
                return defaults
            configured = _marker_list(raw.get(key))
            return tuple(dict.fromkeys((*defaults, *configured)))[:32]

        return WebChatAdapterSpec(
            id=base.id,
            name=_text(raw.get("name") or base.name, 160),
            domains=domains,
            chat_url=chat_url,
            selectors=selectors,
            submission_strategy=raw.get("submission_strategy") or base.submission_strategy,
            login_markers=merged_markers("login_markers", base.login_markers),
            authorized_markers=merged_markers("authorized_markers", base.authorized_markers),
            ready_markers=merged_markers("ready_markers", base.ready_markers),
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


_DEEPSEEK_ACCOUNT_BUTTON_RE = re.compile(
    r'(?im)^\s*@e\d+\s+button\s+"([^"\r\n]{1,120})"\s+\[ctx:[^\]\r\n]{1,160}\]'
)
_GENERIC_ACCOUNT_BUTTON_LABELS = frozenset(
    {
        "",
        "icon",
        "background",
        "brand",
        "开启新对话",
        "新聊天",
        "new chat",
        "send",
        "发送",
        "思考",
        "深度思考",
        "智能搜索",
        "升级",
        "临时聊天",
    }
)


def _deepseek_account_button_evidence(snapshot: Any) -> bool:
    """Return only a boolean for DeepSeek's dynamic account-button proof."""

    payload = _snapshot_payload(snapshot)
    if isinstance(payload, str):
        text = payload
        if len(text) > 24_000:
            text = f"{text[:12_000]}\n{text[-12_000:]}"
    else:
        text = "\n".join(_walk_strings(payload, limit=1_200))
    counts: dict[str, int] = {}
    for match in _DEEPSEEK_ACCOUNT_BUTTON_RE.finditer(text):
        label = " ".join(match.group(1).split()).casefold()
        if label in _GENERIC_ACCOUNT_BUTTON_LABELS:
            continue
        counts[label] = counts.get(label, 0) + 1
    return any(count >= 2 for count in counts.values())


def _auth_state(
    spec: WebChatAdapterSpec,
    snapshot: Any,
    *,
    marker_hits: Mapping[str, Any] | None = None,
) -> str:
    if isinstance(marker_hits, Mapping):
        # BrowserRuntime may provide marker-only evidence from the raw,
        # bounded BrowserSkill response.  The values contain no page text.
        if marker_hits.get("authorized") is True:
            return "authorized"
        if marker_hits.get("account_button") is True:
            return "authorized"
        if marker_hits.get("login") is True:
            return "needs-auth"
    # Keep the structural check useful for alternate BrowserRuntime
    # implementations and small test doubles that do not return marker_hits.
    if spec.id == "deepseek-web" and _deepseek_account_button_evidence(snapshot):
        return "authorized"
    strings = _walk_strings(_snapshot_payload(snapshot))
    # A positive account marker wins over a footer/login hint.  We deliberately
    # use only coarse markers; no account name or page content is persisted.
    # Only explicit, adapter-owned markers prove authorization.  Generic
    # words such as "Account" also appear on login pages and public footers,
    # so treating them as proof would allow an unauthenticated send.
    # Existing profiles may have been created with an older marker list.  Add
    # current built-in account controls at evaluation time so a harmless UI
    # marker update does not require deleting or recreating the login profile.
    positive = tuple(
        dict.fromkeys(
            (
                *spec.authorized_markers,
                *(
                    (
                        "打开个人资料菜单",
                        "打开“个人资料”菜单",
                        "打开\"个人资料\"菜单",
                        "账户菜单",
                        "Account menu",
                        "Open profile menu",
                        "Open user menu",
                    )
                    if spec.id == "chatgpt-web"
                    else ()
                ),
            )
        )
    )
    if _contains_marker(strings, positive):
        return "authorized"
    if _contains_marker(strings, spec.login_markers):
        return "needs-auth"
    return "unknown"


def _page_ready(
    spec: WebChatAdapterSpec,
    snapshot: Any,
    *,
    auth_state: str | None = None,
    marker_hits: Mapping[str, Any] | None = None,
) -> bool:
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
    if isinstance(marker_hits, Mapping) and "ready" in marker_hits:
        return marker_hits.get("ready") is True
    strings = _walk_strings(_snapshot_payload(snapshot))
    return _contains_marker(strings, markers)


def _deepseek_has_explicit_login_control(snapshot: Any) -> bool:
    """Distinguish a real login control from history text containing login."""

    labels = {"登录", "log in", "sign in"}

    def visit(value: Any, depth: int = 0) -> bool:
        if depth > 7:
            return False
        if isinstance(value, Mapping):
            role = str(value.get("role") or value.get("tag") or "").strip().casefold()
            label = str(
                value.get("text")
                or value.get("name")
                or value.get("label")
                or value.get("aria_label")
                or ""
            ).strip().casefold()
            if role in {"button", "link"} and label in labels:
                return True
            return any(visit(item, depth + 1) for item in list(value.values())[:100])
        if isinstance(value, (list, tuple)):
            return any(visit(item, depth + 1) for item in list(value)[:200])
        if isinstance(value, str):
            return any(
                re.fullmatch(
                    r'\s*(?:@e\d+\s+)?(?:button|link)\s+"(?:登录|log in|sign in)"(?:\s+.*)?',
                    line,
                    flags=re.IGNORECASE,
                )
                for line in value.splitlines()
            )
        return False

    return visit(_snapshot_payload(snapshot))


def _marker_sets_for(spec: WebChatAdapterSpec) -> dict[str, tuple[str, ...]]:
    """Describe the non-sensitive marker groups needed by a profile check."""

    authorized = tuple(spec.authorized_markers)
    # Existing profiles persist the marker list that was present when they
    # were created.  Keep current localized account controls in the raw,
    # marker-only scan so a harmless UI localization change does not require
    # recreating a signed-in profile or relying on a truncated snapshot.
    if spec.id == "chatgpt-web":
        authorized = tuple(
            dict.fromkeys(
                (
                    *authorized,
                    "打开个人资料菜单",
                    "打开“个人资料”菜单",
                    '打开"个人资料"菜单',
                    "账户菜单",
                    "Account menu",
                    "Open profile menu",
                    "Open user menu",
                )
            )
        )
    result = {
        "authorized": authorized,
        "login": spec.login_markers,
        "ready": spec.ready_markers,
    }
    if spec.id == "deepseek-web":
        result["account_button"] = (_ACCOUNT_BUTTON_MARKER,)
    return result


def _marker_hits_from_snapshot(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    hits = value.get("marker_hits")
    return hits if isinstance(hits, Mapping) else None


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
            "data-message-role",
            "data-assistant-markdown",
            "data-composer-submit",
            "data-composer-draft-react",
            "aria-label",
            "placeholder",
            "contenteditable",
            "type",
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


_TRANSIENT_RESPONSE_PATTERNS = (
    re.compile(r"^(?:正在)?(?:深度)?思考(?:中|…|\.{3})?(?:\s*(?:用户|user).*)?$", re.IGNORECASE),
    re.compile(r"^(?:正在)?生成(?:中|…|\.{3})?(?:\s*(?:用户|user).*)?$", re.IGNORECASE),
    re.compile(r"^(?:thinking|generating)(?:\s*(?:…|\.{3}))?(?:\s*user.*)?$", re.IGNORECASE),
    re.compile(r"^(?:用户|user)$", re.IGNORECASE),
)
_CONSULTATION_PROMPT_ECHO_MARKER = "you are an independent web consultation member for sumika."


def _normalized_response_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_transient_response(value: Any) -> bool:
    text = _normalized_response_text(value)
    return not text or any(pattern.fullmatch(text) for pattern in _TRANSIENT_RESPONSE_PATTERNS)


def _is_prompt_echo(value: Any) -> bool:
    return _CONSULTATION_PROMPT_ECHO_MARKER in _normalized_response_text(value).casefold()


def _is_usable_response(value: Any) -> bool:
    return not _is_transient_response(value) and not _is_prompt_echo(value)


@dataclass(slots=True)
class _ResponseStabilityTracker:
    """Accept a changing stream only after the same final text stays stable."""

    min_observations: int = WEB_CHAT_RESPONSE_STABLE_OBSERVATIONS
    min_seconds: float = WEB_CHAT_RESPONSE_STABLE_SECONDS
    _candidate_key: str | None = None
    _candidate_text: str | None = None
    _first_seen_at: float = 0.0
    _observations: int = 0

    def observe(self, value: Any, *, observed_at: float | None = None) -> str | None:
        text = str(value or "").strip()
        if not _is_usable_response(text):
            return None
        key = _normalized_response_text(text)
        now = time.monotonic() if observed_at is None else float(observed_at)
        if key != self._candidate_key:
            self._candidate_key = key
            self._candidate_text = text
            self._first_seen_at = now
            self._observations = 1
        else:
            self._candidate_text = text
            self._observations += 1
        if (
            self._observations >= max(1, int(self.min_observations))
            and now - self._first_seen_at >= max(0.0, float(self.min_seconds))
        ):
            return self._candidate_text
        return None


def _input_message_state(snapshot: Any, selectors: Iterable[str], message: str) -> bool | None:
    """Return whether a selected composer still contains the submitted text.

    ``None`` means the BrowserSkill projection did not expose enough element
    metadata.  Callers must treat that as unknown rather than retrying a write.
    """

    root = _snapshot_payload(snapshot)
    normalized_message = " ".join(str(message or "").split())
    if not normalized_message:
        return None
    snapshot_text = root if isinstance(root, str) else None
    if isinstance(root, Mapping) and isinstance(root.get("text"), str):
        # BrowserSkill's JSON snapshot wraps the accessibility projection in
        # a top-level ``text`` field.  Treat it exactly like the legacy raw
        # string projection so a truncated long composer value still proves
        # that the previous send action did nothing.
        snapshot_text = root["text"]
    if snapshot_text is not None:
        folded_message = normalized_message.casefold()
        # BrowserSkill bounds long accessible values.  A consultation prompt
        # can therefore remain visibly present while the snapshot contains
        # only its leading fragment.  That fragment is still strong proof
        # that a click did not submit the composer, so do not downgrade it to
        # an unknown write and wait for a response that can never arrive.
        prefix_length = min(len(folded_message), 96)
        folded_prefix = folded_message[:prefix_length]
        textbox_lines: list[str] = []
        for line in snapshot_text.splitlines():
            if not re.search(r"\btextbox\b", line, flags=re.IGNORECASE):
                continue
            folded_line = " ".join(line.split()).casefold()
            textbox_lines.append(folded_line)
            if folded_message in folded_line:
                return True
            if prefix_length >= 48 and folded_prefix in folded_line:
                return True
        # BrowserSkill marks exposed accessibility textboxes as [empty] or
        # [filled].  Only conclude that the composer cleared when every
        # exposed textbox is explicitly empty; a filled search field or an
        # unlabelled textbox keeps the write state unknown.
        if textbox_lines and all("[empty]" in line for line in textbox_lines):
            return False
        return None

    matched = False
    contains = False

    def visit(value: Any, depth: int = 0) -> None:
        nonlocal matched, contains
        if depth > 8 or contains:
            return
        if isinstance(value, Mapping):
            if any(_node_matches_selector(value, selector) for selector in selectors):
                matched = True
                selected = " ".join(_node_text(value).split())
                if normalized_message.casefold() in selected.casefold():
                    contains = True
                    return
            for key, item in list(value.items())[:100]:
                if _SECRET_KEY_RE.search(str(key)):
                    continue
                visit(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in list(value)[:160]:
                visit(item, depth + 1)

    visit(root)
    if contains:
        return True
    return False if matched else None


@dataclass(frozen=True, slots=True)
class _AssistantCandidate:
    """One assistant node from a bounded snapshot projection.

    ``identity`` is kept inside the Core only.  Stable DOM message ids are
    preferred; a traversal path is a last-resort ordering hint and is never
    persisted or returned to callers.
    """

    text: str
    identity: str
    stable_identity: bool = False
    path: tuple[str, ...] = ()


def _assistant_node_identity(value: Mapping[str, Any], path: tuple[str, ...]) -> tuple[str, bool]:
    """Resolve a non-secret message identity when a site exposes one."""

    attributes = value.get("attributes")
    candidates: list[tuple[str, Any]] = []
    for key in (
        "message_id",
        "messageId",
        "data-message-id",
        "node_id",
        "nodeId",
        "ref",
        "key",
    ):
        if key in value:
            candidates.append((key, value.get(key)))
    if isinstance(attributes, Mapping):
        for key in ("data-message-id", "data-messageid", "data-id", "id"):
            if key in attributes:
                candidates.append((key, attributes.get(key)))
    for key, raw in candidates:
        if isinstance(raw, (str, int)):
            normalized = str(raw).strip()
            # Do not turn arbitrary page text into an identity.  Message ids
            # and snapshot refs are short opaque values in supported bridges.
            if normalized and len(normalized) <= 160 and not _SECRET_KEY_RE.search(key):
                return f"{key}:{normalized}", True
    return "path:" + "/".join(path), False


def _path_is_ancestor(first: tuple[str, ...], second: tuple[str, ...]) -> bool:
    return len(first) < len(second) and second[: len(first)] == first


def _dedupe_assistant_candidates(candidates: Iterable[_AssistantCandidate]) -> tuple[_AssistantCandidate, ...]:
    """Remove nested selector projections while retaining repeated siblings."""

    result: list[_AssistantCandidate] = []
    for candidate in candidates:
        normalized = _normalized_response_text(candidate.text)
        if not normalized or not _is_usable_response(candidate.text):
            continue
        duplicate = False
        for existing in result:
            if existing.identity == candidate.identity:
                duplicate = True
                break
            # Broad selectors can match both a message wrapper and its nested
            # markdown element.  If both contain exactly the same text, keep
            # the outer/most stable node; distinct sibling messages remain.
            if (
                normalized == _normalized_response_text(existing.text)
                and (
                    _path_is_ancestor(existing.path, candidate.path)
                    or _path_is_ancestor(candidate.path, existing.path)
                )
            ):
                if candidate.stable_identity and not existing.stable_identity:
                    result[result.index(existing)] = candidate
                duplicate = True
                break
        if not duplicate:
            result.append(candidate)
    return tuple(result[-64:])


def _extract_assistant_candidates(
    snapshot: Any,
    *,
    selectors: Iterable[str] = (),
) -> tuple[_AssistantCandidate, ...]:
    """Extract all explicitly labelled assistant nodes in document order."""

    root = _snapshot_payload(snapshot)
    response_selectors = tuple(str(item) for item in selectors if str(item).strip())
    selector_candidates: list[_AssistantCandidate] = []
    semantic_candidates: list[_AssistantCandidate] = []

    def visit(value: Any, role_hint: str = "", path: tuple[str, ...] = (), depth: int = 0) -> None:
        if depth > 8 or len(selector_candidates) + len(semantic_candidates) >= 256:
            return
        if isinstance(value, Mapping):
            role = str(value.get("role") or value.get("author") or value.get("sender") or role_hint).lower()
            key_hint = " ".join(str(key).lower() for key in value.keys())
            is_assistant = any(token in role or token in key_hint for token in ("assistant", "model", "bot"))
            matched = bool(response_selectors and any(_node_matches_selector(value, selector) for selector in response_selectors))
            selected = _node_text(value)
            if selected and (matched or is_assistant):
                identity, stable = _assistant_node_identity(value, path)
                candidate = _AssistantCandidate(selected, identity, stable, path)
                if matched:
                    selector_candidates.append(candidate)
                elif is_assistant:
                    semantic_candidates.append(candidate)
            for key, item in list(value.items())[:100]:
                lowered = str(key).lower()
                if any(token in lowered for token in ("cookie", "token", "secret", "password", "authorization", "base64", "image_data")):
                    continue
                visit(item, role, path + (str(key),), depth + 1)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(list(value)[:160]):
                visit(item, role_hint, path + (str(index),), depth + 1)

    visit(root)
    candidates = selector_candidates if selector_candidates else semantic_candidates
    if candidates:
        result = _dedupe_assistant_candidates(candidates)
        for candidate in result:
            if _SECRET_VALUE_RE.search(candidate.text):
                raise WebChatRuntimeError("web-chat response appears to contain sensitive data")
        return result

    # Accessibility projections may flatten role/text into lines.  Preserve
    # line order and use the line index as an intentionally unstable fallback.
    flattened: list[_AssistantCandidate] = []
    for index, line in enumerate(_walk_strings(root, limit=600)):
        match = re.match(r"(?is)^\s*(?:assistant|model|bot)\s*[:：]\s*(.+)$", line)
        if match:
            text = match.group(1).strip()
            flattened.append(_AssistantCandidate(text, f"line:{index}", False, ("line", str(index))))
    result = _dedupe_assistant_candidates(flattened)
    for candidate in result:
        if _SECRET_VALUE_RE.search(candidate.text):
            raise WebChatRuntimeError("web-chat response appears to contain sensitive data")
    return result


def _new_assistant_response(
    current: Iterable[_AssistantCandidate],
    baseline: Iterable[_AssistantCandidate],
    *,
    submitted_key: str,
) -> str | None:
    """Return the latest candidate that was not present before the send."""

    current_items = tuple(current)
    baseline_items = tuple(baseline)
    if not current_items:
        return None
    baseline_texts = {_normalized_response_text(item.text) for item in baseline_items}
    baseline_stable_ids = {item.identity for item in baseline_items if item.stable_identity}
    baseline_by_id = {
        item.identity: _normalized_response_text(item.text)
        for item in baseline_items
        if item.stable_identity
    }
    # A new sibling with the same text is still a new response.  Count is
    # meaningful because the extractor preserves document order and removes
    # only nested duplicates.
    count_increased = len(current_items) > len(baseline_items)
    for item in reversed(current_items):
        key = _normalized_response_text(item.text)
        if not key or key == submitted_key:
            continue
        if key not in baseline_texts:
            return item.text
        if count_increased:
            return item.text
        if item.stable_identity and item.identity not in baseline_stable_ids:
            return item.text
        if item.stable_identity and baseline_by_id.get(item.identity) != key:
            return item.text
    return None


def _find_input_ref(snapshot: Any, selectors: Iterable[str]) -> str | None:
    """Find a BrowserSkill accessibility ref for an input node, if exposed."""

    root = _snapshot_payload(snapshot)
    selector_values = tuple(str(item) for item in selectors if str(item).strip())

    def normalize_ref(raw: Any) -> str | None:
        if not isinstance(raw, (str, int)):
            return None
        value = str(raw).strip()
        if re.fullmatch(r"@?e\d+", value, flags=re.IGNORECASE):
            return value if value.startswith("@") else f"@{value}"
        return None

    def visit(value: Any, depth: int = 0) -> str | None:
        if depth > 8:
            return None
        if isinstance(value, Mapping):
            if selector_values and any(_node_matches_selector(value, selector) for selector in selector_values):
                for key in ("ref", "snapshot_ref", "node_ref", "id"):
                    found = normalize_ref(value.get(key))
                    if found:
                        return found
            for key, item in list(value.items())[:100]:
                if _SECRET_KEY_RE.search(str(key)):
                    continue
                found = visit(item, depth + 1)
                if found:
                    return found
        elif isinstance(value, (list, tuple)):
            for item in list(value)[:160]:
                found = visit(item, depth + 1)
                if found:
                    return found
        return None

    found = visit(root)
    if found:
        return found
    if isinstance(root, str):
        for line in root.splitlines():
            if not re.search(r"\btextbox\b", line, flags=re.IGNORECASE):
                continue
            match = re.search(r"(@?e\d+)", line, flags=re.IGNORECASE)
            if match:
                return normalize_ref(match.group(1))
    return None


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

    candidates = _extract_assistant_candidates(snapshot, selectors=selectors)
    for candidate in reversed(candidates):
        text = candidate.text.strip()
        if _SECRET_VALUE_RE.search(text):
            raise WebChatRuntimeError("web-chat response appears to contain sensitive data")
        return text[:max_chars]
    return None


def _extract_assistant_html_candidates(
    browser: Any,
    session_id: str,
    tab_id: str,
    *,
    selectors: Iterable[str],
    logger: Any = None,
) -> tuple[_AssistantCandidate, ...]:
    """Use the Core-only HTML projection when snapshots flatten the DOM.

    BrowserRuntime deliberately returns only selected text and a sensitivity
    bit.  Older test doubles or BrowserRuntime versions without this optional
    method simply return an empty sequence.  The list deliberately preserves
    repeated sibling messages so a new response identical to an old one is
    still distinguishable by count.
    """

    extractor = getattr(browser, "extract_html_text_session", None)
    if not callable(extractor):
        return ()
    try:
        projected = extractor(
            session_id,
            tab_id=tab_id,
            selectors=tuple(selectors),
        )
    except Exception as error:
        if logger:
            try:
                logger.info(
                    "web chat html response probe failed session=%s tab=%s error_type=%s",
                    session_id,
                    tab_id,
                    type(error).__name__,
                )
            except Exception:
                pass
        return ()
    if not isinstance(projected, Mapping) or projected.get("ready") is not True:
        return ()
    if projected.get("sensitive") is True:
        raise WebChatRuntimeError("web-chat response appears to contain sensitive data")
    values = projected.get("texts")
    if not isinstance(values, (list, tuple)):
        return ()
    raw_counts = projected.get("text_counts")
    counts = list(raw_counts) if isinstance(raw_counts, (list, tuple)) else []
    # ``texts`` is a bounded projection.  Keep the multiplicity index aligned
    # with the same tail slice when the page contains more than 64 selected
    # nodes; otherwise a late response could inherit an earlier node's count.
    value_offset = max(0, len(values) - 64)
    visible_values = values[value_offset:]
    visible_counts = counts[value_offset:] if counts else []
    candidates: list[_AssistantCandidate] = []
    for index, raw in enumerate(visible_values):
        candidate = str(raw or "").strip()
        if not _is_usable_response(candidate):
            continue
        if _SECRET_VALUE_RE.search(candidate):
            raise WebChatRuntimeError("web-chat response appears to contain sensitive data")
        try:
            occurrences = max(1, min(64, int(visible_counts[index]))) if index < len(visible_counts) else 1
        except (TypeError, ValueError):
            occurrences = 1
        for occurrence in range(occurrences):
            candidates.append(
                _AssistantCandidate(
                    candidate[:24_000],
                    f"html:{index}:{occurrence}",
                    False,
                    ("html", str(index), str(occurrence)),
                )
            )
    return tuple(candidates)


def _extract_assistant_html_text(
    browser: Any,
    session_id: str,
    tab_id: str,
    *,
    selectors: Iterable[str],
    logger: Any = None,
) -> str | None:
    """Return the latest selected HTML response for legacy callers."""

    candidates = _extract_assistant_html_candidates(
        browser,
        session_id,
        tab_id,
        selectors=selectors,
        logger=logger,
    )
    return candidates[-1].text if candidates else None


class WebChatRuntime:
    """Manage persistent web-account metadata and BrowserSkill sessions."""

    def __init__(
        self,
        storage: Storage,
        browser: "BrowserRuntime",
        *,
        registry: WebChatAdapterRegistry | None = None,
        logger: Any = None,
        worker_idle_close_seconds: float = WEB_CHAT_WORKER_IDLE_CLOSE_SECONDS,
    ) -> None:
        self.storage = storage
        self.browser = browser
        self.registry = registry or WebChatAdapterRegistry()
        self.logger = logger
        self.sessions: dict[str, str] = {}
        self._profile_tabs: dict[str, str] = {}
        self._shared_sessions: dict[tuple[str, str], str] = {}
        self._session_profiles: dict[str, set[str]] = {}
        self._worker_owned_sessions: set[str] = set()
        self._idle_close_timers: dict[str, threading.Timer] = {}
        self._session_lock = threading.RLock()
        self._worker_idle_close_seconds = max(0.01, min(600.0, float(worker_idle_close_seconds)))
        # RouteCoordinator marks a profile while an Agent worker is writing to
        # it.  Manual sends fail closed during that interval instead of
        # sharing the same BrowserSkill tab concurrently.
        self._agent_occupancy: set[str] = set()
        self._occupancy_lock = threading.RLock()
        self._attempts: dict[str, dict[str, Any]] = {}
        self._profile_attempts: dict[str, str] = {}
        self._closed = False
        self._session_invalidated_callback: Callable[[str], Any] | None = None

    def set_session_invalidated_callback(self, callback: Callable[[str], Any] | None) -> None:
        """Register a compatibility hook for clearing stale route occupancy.

        The callback receives only a profile id.  It must not be used to carry
        page content, credentials, or a BrowserSkill session id across the
        runtime boundary.
        """

        self._session_invalidated_callback = callback if callable(callback) else None

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
            self._close_profile_binding(str(profile.get("id")), close_tab=True)
        return {
            **self._public_profile(profile),
            "session_id": session_id,
            "closed": True,
            "window_state": "closed",
        }

    def _observe_profile_page(
        self,
        session_id: str,
        tab_id: str,
        spec: WebChatAdapterSpec,
        *,
        wait_for_initial_load: bool,
    ) -> tuple[Any, str, Any | None, Mapping[str, Any] | None, str, bool]:
        """Read one page, retrying only an empty or explicit loading shell."""

        deadline = time.monotonic() + (PROFILE_PAGE_LOAD_TIMEOUT_SECONDS if wait_for_initial_load else 0.0)
        while True:
            snapshot = self.browser.snapshot_session(
                session_id,
                tab_id=tab_id,
                marker_sets=_marker_sets_for(spec),
                max_tokens=WEB_CHAT_SNAPSHOT_MAX_TOKENS,
            )
            snapshot_state, snapshot_payload = _validated_snapshot(snapshot)
            marker_hits = _marker_hits_from_snapshot(snapshot)
            if snapshot_state == "ready":
                auth = _auth_state(spec, snapshot_payload, marker_hits=marker_hits)
                page_ready = _page_ready(
                    spec,
                    snapshot_payload,
                    auth_state=auth,
                    marker_hits=marker_hits,
                )
            else:
                auth = "unknown"
                page_ready = False
            if (
                wait_for_initial_load
                and spec.id == "deepseek-web"
                and auth != "authorized"
                and page_ready
                and not _deepseek_has_explicit_login_control(snapshot_payload)
                and time.monotonic() < deadline
            ):
                # DeepSeek can paint history and the composer one tick before
                # its signed-in account controls.  A history title containing
                # "login" must not turn that partial first frame into a false
                # logout result.
                time.sleep(PROFILE_PAGE_LOAD_POLL_SECONDS)
                continue
            explicit_login = auth == "needs-auth"
            settled = (
                not wait_for_initial_load
                or explicit_login
                or auth == "authorized"
                or snapshot_state == "invalid"
                or time.monotonic() >= deadline
            )
            if settled:
                return snapshot, snapshot_state, snapshot_payload, marker_hits, auth, page_ready
            time.sleep(PROFILE_PAGE_LOAD_POLL_SECONDS)

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
            snapshot, snapshot_state, snapshot_payload, marker_hits, auth, page_ready = self._observe_profile_page(
                session["id"],
                tab_id,
                spec,
                wait_for_initial_load=True,
            )
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
            if self.logger:
                try:
                    self.logger.info(
                        "web chat profile marker evidence profile=%s adapter=%s auth=%s page_ready=%s hits=%s",
                        profile_id,
                        spec.id,
                        auth,
                        page_ready,
                        {
                            str(key): bool(value)
                            for key, value in (marker_hits or {}).items()
                            if str(key) in {"authorized", "login", "ready", "account_button"}
                        },
                    )
                except Exception:
                    pass
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
            self._close_profile_binding(profile_id, close_tab=True)
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
        if attempt.get("owner") == "agent":
            self._schedule_worker_idle_close(profile_id)

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
        message = _text(text, 16_000, allow_newlines=True)
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
        message = _text(text, 16_000, allow_newlines=True)
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
            tab_id = self._ensure_chat_tab(profile, session["id"], no_focus=owner == "agent")
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
            before, before_state, before_payload, before_marker_hits, before_auth, before_page_ready = self._observe_profile_page(
                session["id"],
                tab_id,
                spec,
                wait_for_initial_load=True,
            )
        except Exception:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": "无法读取聊天页面；消息未发送"}
        # A profile can become logged out or navigate away after the last
        # explicit check.  Re-evaluate both signals immediately before any
        # fill/click/press action.  Never treat a visible send button as proof
        # of authentication, and never continue on a stale DOM snapshot.
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
        baseline_snapshot_candidates: tuple[_AssistantCandidate, ...] = ()
        try:
            baseline_snapshot_candidates = _extract_assistant_candidates(
                before_payload, selectors=spec.selectors.get("response", ())
            )
        except WebChatRuntimeError as error:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": str(error)}
        # BrowserSkill's compact accessibility projection can flatten a real
        # assistant node into ordinary paragraphs.  Prefer the bounded Core
        # HTML projection when it has a response, while retaining snapshots as
        # the compatibility path for older BrowserSkill versions and stubs.
        baseline_html_candidates: tuple[_AssistantCandidate, ...] = ()
        try:
            baseline_html_candidates = _extract_assistant_html_candidates(
                self.browser,
                session["id"],
                tab_id,
                selectors=spec.selectors.get("response", ()),
                logger=self.logger,
            )
        except WebChatRuntimeError as error:
            return {"ok": False, "status": "failed", "profile_id": profile_id, "reason": str(error)}

        submitted_key = _normalized_response_text(message)
        visual_baseline_id: str | None = None
        visual_page_baseline_id: str | None = None
        input_ref = _find_input_ref(before_payload, spec.selectors.get("input", ()))

        def capture_visual(*, baseline_id: str | None = None, input_only: bool = False) -> dict[str, Any]:
            probe = getattr(self.browser, "visual_evidence_session", None)
            if not callable(probe):
                return {
                    "available": False,
                    "confidence": "unknown",
                    "prompt_in_input": None,
                    "assistant_response_visible": None,
                    "blocking_surface_visible": None,
                    "evidence_id": None,
                    "error_code": "visual-probe-unavailable",
                }
            try:
                value = probe(
                    session["id"],
                    tab_id=tab_id,
                    expected_text=message,
                    baseline_id=baseline_id,
                    ref=input_ref if input_only and input_ref else None,
                    scope="input" if input_only and input_ref else "page",
                )
            except Exception as error:
                if self.logger:
                    try:
                        self.logger.info(
                            "web chat visual evidence unavailable profile=%s error_type=%s",
                            profile_id,
                            type(error).__name__,
                        )
                    except Exception:
                        pass
                return {
                    "available": False,
                    "confidence": "unknown",
                    "prompt_in_input": None,
                    "assistant_response_visible": None,
                    "blocking_surface_visible": None,
                    "evidence_id": None,
                    "error_code": "visual-probe-failed",
                }
            return dict(value) if isinstance(value, Mapping) else {
                "available": False,
                "confidence": "unknown",
                "prompt_in_input": None,
                "assistant_response_visible": None,
                "blocking_surface_visible": None,
                "evidence_id": None,
                "error_code": "visual-probe-invalid",
            }

        def new_snapshot_response(candidates: Iterable[_AssistantCandidate]) -> str | None:
            return _new_assistant_response(
                candidates,
                baseline_snapshot_candidates,
                submitted_key=submitted_key,
            )

        def new_html_response(candidates: Iterable[_AssistantCandidate]) -> str | None:
            return _new_assistant_response(
                candidates,
                baseline_html_candidates,
                submitted_key=submitted_key,
            )

        def verify_submission() -> tuple[str, bool, Any | None]:
            """Classify one write without ever guessing that it is safe to replay.

            ``not-sent`` is reserved for an explicit composer-presence signal
            (DOM or sufficiently confident visual evidence).  Any transport,
            DOM, or visual ambiguity becomes ``possibly-sent`` so a later
            fallback cannot duplicate a real message.
            """

            observed: Any | None = None
            message_still_present = False
            probe_count = (
                WEB_CHAT_QWEN_SUBMISSION_CONFIRM_POLLS
                if spec.id == "qwen-web"
                else WEB_CHAT_DEFAULT_SUBMISSION_CONFIRM_POLLS
            )
            for probe_index in range(probe_count):
                try:
                    observed = self.browser.snapshot_session(
                        session["id"],
                        tab_id=tab_id,
                        marker_sets=_marker_sets_for(spec),
                        max_tokens=WEB_CHAT_SNAPSHOT_MAX_TOKENS,
                    )
                except Exception:
                    return "possibly-sent", False, observed
                observed_state, observed_payload = _validated_snapshot(observed)
                if observed_state != "ready":
                    return "possibly-sent", False, observed
                try:
                    snapshot_candidates = _extract_assistant_candidates(
                        observed_payload,
                        selectors=spec.selectors.get("response", ()),
                    )
                except WebChatRuntimeError:
                    return "possibly-sent", False, observed
                if new_snapshot_response(snapshot_candidates):
                    return "confirmed", True, observed
                input_state = _input_message_state(
                    observed_payload,
                    spec.selectors.get("input", ()),
                    message,
                )
                if input_state is False:
                    return "confirmed", True, observed
                if input_state is True:
                    message_still_present = True
                if probe_index + 1 < probe_count:
                    time.sleep(PROFILE_PAGE_LOAD_POLL_SECONDS)
            if message_still_present:
                visual = capture_visual(baseline_id=visual_baseline_id, input_only=True)
                confidence = visual.get("confidence")
                if visual.get("prompt_in_input") is True and confidence in {"medium", "high"}:
                    # The original prompt is still exposed in the composer;
                    # this is the only state in which another submit method is
                    # safe to try.
                    return "not-sent", False, observed
                if visual.get("prompt_in_input") is False and confidence in {"medium", "high"}:
                    # DOM and OCR disagree.  Treat the write as uncertain and
                    # never risk a duplicate submission.
                    return "possibly-sent", False, observed
                # DOM already proved the prompt is present, but weak/missing
                # visual evidence cannot overrule that proof.  Keep the write
                # conservative and permit the safe fallback.
                return "not-sent", False, observed
            # This is a page-level diagnostic, so do not compare it with the
            # input-only baseline used for submission verification.
            visual = capture_visual(baseline_id=None)
            confidence = visual.get("confidence")
            if visual.get("prompt_in_input") is True and confidence in {"medium", "high"}:
                return "not-sent", False, observed
            if visual.get("prompt_in_input") is False and confidence in {"medium", "high"}:
                return "confirmed", True, observed
            return "possibly-sent", False, observed

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

        visual_baseline = capture_visual(input_only=True)
        if visual_baseline.get("available") and visual_baseline.get("evidence_id"):
            visual_baseline_id = str(visual_baseline["evidence_id"])

        # Keep a page-level baseline separate from the input crop. A crop can
        # prove that a composer changed, but it cannot show whether a new
        # assistant response appeared elsewhere on the page. Without this
        # baseline, the timeout diagnostic has no independent visual comparison
        # and must always report an unknown response state.
        visual_page_baseline = capture_visual()
        if visual_page_baseline.get("available") and visual_page_baseline.get("evidence_id"):
            visual_page_baseline_id = str(visual_page_baseline["evidence_id"])

        sent = False
        submission_confirmed = False
        post_send_observed: Any | None = None
        send_result: dict[str, Any] | None = None
        # ChatGPT's current composer reliably submits on Enter while its
        # historical send-button selector is absent or unstable.  Keep the
        # action order declarative so a future adapter can opt into the same
        # policy without special-casing the site in the worker loop.
        actions: list[tuple[str, str, str | None]] = []
        if spec.submission_strategy == "enter-first":
            actions.append(("press", input_selector, "Enter"))
        actions.extend(("click", selector, None) for selector in spec.selectors.get("send", ()))
        if spec.submission_strategy != "enter-first":
            actions.append(("press", input_selector, "Enter"))
        for action_index, (action, target, key) in enumerate(actions):
            early = cancelled()
            if early:
                return early
            ready_polls = (
                WEB_CHAT_PRIMARY_SEND_READY_POLLS
                if action == "click" and action_index == 0
                else 1
            )
            for ready_poll in range(ready_polls):
                try:
                    candidate = self.browser.execute_action(
                        session["id"],
                        action=action,
                        target=target,
                        key=key,
                        approved=True,
                        tab_id=tab_id,
                    )
                except Exception:
                    candidate = {"executed": False}
                send_result = candidate if isinstance(candidate, dict) else {"executed": False}
                if send_result.get("executed"):
                    break
                if send_result.get("requires_human"):
                    return {
                        "ok": False,
                        "status": "waiting-human",
                        "requires_human": True,
                        "profile_id": profile_id,
                        "reason": send_result.get("reason"),
                    }
                if ready_poll + 1 < ready_polls:
                    time.sleep(PROFILE_PAGE_LOAD_POLL_SECONDS)
            if send_result.get("executed"):
                verification, confirmed, observed = verify_submission()
                if verification != "not-sent":
                    sent = True
                    submission_confirmed = confirmed
                    post_send_observed = observed
                    break
        if not sent:
            return {
                "ok": False,
                "status": "failed",
                "profile_id": profile_id,
                "error_code": "submission-not-observed",
                "reason": "发送操作未执行，或输入框在复核后仍保留原消息",
            }

        mark_attempt(sent=submission_confirmed, possibly_sent=True)

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
        last_html_probe = 0.0
        html_probe_interval = 0.75
        queued_observed = post_send_observed
        response_tracker = _ResponseStabilityTracker(
            min_observations=WEB_CHAT_RESPONSE_STABLE_OBSERVATIONS,
            min_seconds=WEB_CHAT_RESPONSE_STABLE_SECONDS,
        )
        while time.monotonic() <= deadline:
            early = cancelled()
            if early:
                return early
            if queued_observed is not None:
                observed = queued_observed
                queued_observed = None
            else:
                try:
                    observed = self.browser.snapshot_session(
                        session["id"],
                        tab_id=tab_id,
                        marker_sets=_marker_sets_for(spec),
                        max_tokens=WEB_CHAT_SNAPSHOT_MAX_TOKENS,
                    )
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
            observed_marker_hits = _marker_hits_from_snapshot(observed)
            observed_auth = _auth_state(
                spec,
                observed_payload,
                marker_hits=observed_marker_hits,
            )
            observed_page_ready = _page_ready(
                spec,
                observed_payload,
                auth_state=observed_auth,
                marker_hits=observed_marker_hits,
            )
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
                snapshot_candidates = _extract_assistant_candidates(
                    observed_payload, selectors=spec.selectors.get("response", ())
                )
            except WebChatRuntimeError as error:
                return {"ok": False, "status": "possibly-sent", "possibly_sent": True, "error_code": "possibly-sent", "profile_id": profile_id, "reason": str(error)}
            response_candidate = new_snapshot_response(snapshot_candidates)
            # Probe raw DOM at a bounded cadence only when the compact
            # snapshot did not reveal a new assistant node.  This avoids a
            # high-cost get-html call on every 250ms polling tick.
            now_monotonic = time.monotonic()
            if now_monotonic - last_html_probe >= html_probe_interval:
                last_html_probe = now_monotonic
                try:
                    html_candidates = _extract_assistant_html_candidates(
                        self.browser,
                        session["id"],
                        tab_id,
                        selectors=spec.selectors.get("response", ()),
                        logger=self.logger,
                    )
                except WebChatRuntimeError as error:
                    return {
                        "ok": False,
                        "status": "possibly-sent",
                        "possibly_sent": True,
                        "error_code": "possibly-sent",
                        "profile_id": profile_id,
                        "reason": str(error),
                    }
                html_candidate = new_html_response(html_candidates)
                if html_candidate:
                    response_candidate = html_candidate
            if response_candidate:
                submission_confirmed = True
                response = response_tracker.observe(response_candidate)
                if response:
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
            # Page-level timeout diagnostics must compare against the page
            # baseline; using the input-only crop here can hide or misclassify
            # a visible assistant reply.
            visual = capture_visual(baseline_id=visual_page_baseline_id)
            if visual.get("blocking_surface_visible") is True:
                return {
                    "ok": False,
                    "status": "waiting-human",
                    "possibly_sent": True,
                    "requires_human": True,
                    "error_code": "visual-blocking-surface",
                    "profile_id": profile_id,
                    "reason": "页面视觉状态显示登录、验证或付费遮罩；需要人工接管",
                }
            if visual.get("assistant_response_visible") is True:
                return {
                    "ok": False,
                    "status": "possibly-sent",
                    "possibly_sent": True,
                    "error_code": "response-visible-extraction-failed",
                    "profile_id": profile_id,
                    "reason": "页面已视觉显示新回复，但 DOM 提取器无法安全定位正文；不会使用 OCR 文本替代",
                }
            return {
                "ok": False,
                "status": "possibly-sent",
                "pending": True,
                "possibly_sent": True,
                "error_code": "response-pending" if submission_confirmed else "submission-unconfirmed",
                "profile_id": profile_id,
                "reason": (
                    "消息已提交，暂未找到明确的 assistant 响应；不会生成替代文本"
                    if submission_confirmed
                    else "发送动作已执行，但页面未提供足够证据确认提交；不会重试或生成替代文本"
                ),
            }
        mark_attempt(sent=True, possibly_sent=True)
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
        with self._session_lock:
            for timer in list(self._idle_close_timers.values()):
                timer.cancel()
            self._idle_close_timers.clear()
            for session_id in set(self.sessions.values()):
                try:
                    self.browser.close_session(session_id)
                except Exception as error:
                    if self.logger:
                        try:
                            self.logger.warning(
                                "web chat session shutdown skipped profile=%s error_type=%s",
                                next((profile_id for profile_id, value in self.sessions.items() if value == session_id), None),
                                type(error).__name__,
                            )
                        except Exception:
                            pass
            self.sessions.clear()
            self._profile_tabs.clear()
            self._shared_sessions.clear()
            self._session_profiles.clear()
            self._worker_owned_sessions.clear()
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

    @staticmethod
    def _session_key(profile: Mapping[str, Any]) -> tuple[str, str]:
        return (
            str(profile.get("browser_profile_id") or ""),
            str(profile.get("browser_instance") or ""),
        )

    def _cancel_idle_close(self, session_id: str) -> None:
        with self._session_lock:
            timer = self._idle_close_timers.pop(session_id, None)
            if timer is not None:
                timer.cancel()

    def _drop_session_bindings(self, session_id: str, *, notify_invalidated: bool = False) -> None:
        invalidated_profiles: set[str] = set()
        with self._session_lock:
            self._cancel_idle_close(session_id)
            for profile_id, bound_session in list(self.sessions.items()):
                if bound_session == session_id:
                    invalidated_profiles.add(str(profile_id))
                    self.sessions.pop(profile_id, None)
                    self._profile_tabs.pop(profile_id, None)
            self._session_profiles.pop(session_id, None)
            self._worker_owned_sessions.discard(session_id)
            for key, bound_session in list(self._shared_sessions.items()):
                if bound_session == session_id:
                    self._shared_sessions.pop(key, None)
        if notify_invalidated and invalidated_profiles:
            # A stale session can leave the legacy route coordinator's
            # in-memory occupancy marker behind.  Clear only the affected
            # profile ids, and keep the callback payload metadata-only.
            with self._occupancy_lock:
                for profile_id in invalidated_profiles:
                    self._agent_occupancy.discard(profile_id)
            callback = self._session_invalidated_callback
            if callback is not None:
                for profile_id in sorted(invalidated_profiles):
                    try:
                        callback(profile_id)
                    except Exception:
                        if self.logger:
                            try:
                                self.logger.info(
                                    "web chat stale occupancy reset skipped profile=%s error_type=%s",
                                    profile_id,
                                    "callback-error",
                                )
                            except Exception:
                                pass

    def _session_is_ready(self, session_id: str) -> dict[str, Any] | None:
        try:
            existing = next(
                (dict(item) for item in self.browser.list_sessions() if str(item.get("id")) == session_id),
                None,
            )
        except Exception as error:
            if _is_missing_browser_session(error):
                raise _StaleBrowserSession("BrowserSkill session no longer exists") from error
            raise WebChatRuntimeError("BrowserSkill session probe failed") from error
        if existing is None:
            # The local runtime's session inventory is authoritative for the
            # ownership check.  An owned id missing from it is an explicit
            # stale binding, rather than a transient network failure.
            raise _StaleBrowserSession("BrowserSkill session no longer exists")
        try:
            probe = self.browser.list_tabs(session_id)
        except Exception as error:
            if _is_missing_browser_session(error):
                raise _StaleBrowserSession("BrowserSkill session no longer exists") from error
            raise WebChatRuntimeError("BrowserSkill session probe failed") from error
        if isinstance(probe, Mapping) and probe.get("ready") is False:
            reason = str(probe.get("reason") or "")
            if _is_missing_browser_session(RuntimeError(reason)):
                raise _StaleBrowserSession("BrowserSkill session no longer exists")
            raise WebChatRuntimeError("BrowserSkill session is not ready")
        return {"id": session_id, **existing}

    def _invalidate_shared_session(self, session_id: str) -> None:
        invalidate = getattr(self.browser, "invalidate_session", None)
        try:
            if callable(invalidate):
                invalidate(session_id, reason="browser-backend-disconnected")
            else:
                self.browser.close_session(session_id)
        except Exception:
            pass
        self._drop_session_bindings(session_id, notify_invalidated=True)

    def _close_profile_binding(self, profile_id: str, *, close_tab: bool) -> None:
        with self._session_lock:
            session_id = self.sessions.get(profile_id)
            if not session_id:
                return
            tab_id = self._profile_tabs.get(profile_id)
            members = set(self._session_profiles.get(session_id) or ())
            remaining = {
                item for item in members
                if item != profile_id and self.sessions.get(item) == session_id
            }
            if remaining:
                if close_tab and tab_id:
                    close_tab_method = getattr(self.browser, "close_tab", None)
                    if callable(close_tab_method):
                        close_tab_method(session_id, tab_id=tab_id, approved=True)
                self.sessions.pop(profile_id, None)
                self._profile_tabs.pop(profile_id, None)
                self._session_profiles[session_id] = remaining
                return
            self.browser.close_session(session_id)
            self._drop_session_bindings(session_id)

    def _schedule_worker_idle_close(self, profile_id: str) -> None:
        with self._session_lock:
            session_id = self.sessions.get(profile_id)
            if not session_id or session_id not in self._worker_owned_sessions or self._closed:
                return
            members = set(self._session_profiles.get(session_id) or ())
            with self._occupancy_lock:
                if any(member in self._profile_attempts for member in members):
                    return
            self._cancel_idle_close(session_id)
            timer = threading.Timer(
                self._worker_idle_close_seconds,
                self._close_worker_idle_session,
                args=(session_id,),
            )
            timer.daemon = True
            self._idle_close_timers[session_id] = timer
            timer.start()

    def _close_worker_idle_session(self, session_id: str) -> None:
        with self._session_lock:
            self._idle_close_timers.pop(session_id, None)
            members = set(self._session_profiles.get(session_id) or ())
            with self._occupancy_lock:
                active = any(member in self._profile_attempts for member in members)
            if self._closed or session_id not in self._worker_owned_sessions or active:
                return
        try:
            self.browser.close_session(session_id)
        except Exception as error:
            if self.logger:
                try:
                    self.logger.warning(
                        "web chat idle session shutdown skipped error_type=%s",
                        type(error).__name__,
                    )
                except Exception:
                    pass
            return
        with self._session_lock:
            self._drop_session_bindings(session_id)

    def _ensure_session(self, profile: Mapping[str, Any], *, allow_auto: bool, no_focus: bool = False) -> dict[str, Any]:
        with self._session_lock:
            return self._ensure_session_locked(profile, allow_auto=allow_auto, no_focus=no_focus)

    def _ensure_session_locked(self, profile: Mapping[str, Any], *, allow_auto: bool, no_focus: bool = False) -> dict[str, Any]:
        profile_id = str(profile["id"])
        existing_id = self.sessions.get(profile_id)
        if existing_id:
            try:
                existing_session = self._session_is_ready(existing_id)
            except _StaleBrowserSession:
                existing_session = None
            if existing_session is not None:
                self._cancel_idle_close(existing_id)
                if not no_focus:
                    self._worker_owned_sessions.discard(existing_id)
                return existing_session
            if self.logger:
                try:
                    self.logger.info("web chat cached session invalidated profile=%s", profile_id)
                except Exception:
                    pass
            self._invalidate_shared_session(existing_id)
        if not allow_auto and not profile.get("auto_chat_enabled"):
            raise WebChatRuntimeError("web-chat session requires explicit consent")
        key = self._session_key(profile)
        shared_id = self._shared_sessions.get(key)
        if shared_id:
            try:
                shared_session = self._session_is_ready(shared_id)
            except _StaleBrowserSession:
                shared_session = None
            if shared_session is not None:
                self._cancel_idle_close(shared_id)
                self.sessions[profile_id] = shared_id
                self._session_profiles.setdefault(shared_id, set()).add(profile_id)
                if not no_focus:
                    self._worker_owned_sessions.discard(shared_id)
                return shared_session
            self._invalidate_shared_session(shared_id)
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
        session_id = str(session["id"])
        self.sessions[profile_id] = session_id
        self._shared_sessions[key] = session_id
        self._session_profiles.setdefault(session_id, set()).add(profile_id)
        if no_focus:
            self._worker_owned_sessions.add(session_id)
        return session

    def _ensure_chat_tab(
        self,
        profile: Mapping[str, Any],
        session_id: str,
        *,
        no_focus: bool = False,
    ) -> str | None:
        with self._session_lock:
            try:
                return self._ensure_chat_tab_locked(profile, session_id)
            except _StaleBrowserSession:
                # The backend disappeared between the session probe and tab
                # lookup.  Reconcile once, then create a fresh owned session;
                # never loop on an uncertain transport failure.
                self._invalidate_shared_session(session_id)
                fresh = self._ensure_session_locked(profile, allow_auto=True, no_focus=no_focus)
                return self._ensure_chat_tab_locked(profile, fresh["id"])

    def _ensure_chat_tab_locked(self, profile: Mapping[str, Any], session_id: str) -> str | None:
        spec = self._spec(profile)
        profile_id = str(profile["id"])
        try:
            listed = self.browser.list_tabs(session_id)
        except Exception as error:
            if _is_missing_browser_session(error):
                raise _StaleBrowserSession("BrowserSkill session no longer exists") from error
            raise WebChatRuntimeError("BrowserSkill tab probe failed") from error
        if isinstance(listed, Mapping):
            tabs = listed.get("tabs", [])
        elif isinstance(listed, list):
            # Keep compatibility with older BrowserSkill test doubles while
            # still rejecting malformed or ambiguous envelopes.
            tabs = listed
        else:
            raise WebChatRuntimeError("BrowserSkill tab probe returned an invalid result")
        known_tab = self._profile_tabs.get(profile_id)
        if known_tab and any(
            isinstance(tab, dict) and str(tab.get("id") or "") == known_tab
            for tab in tabs if isinstance(tabs, list)
        ):
            return known_tab
        used_tabs = {
            tab_id
            for other_profile, tab_id in self._profile_tabs.items()
            if other_profile != profile_id and self.sessions.get(other_profile) == session_id
        }
        for tab in tabs if isinstance(tabs, list) else []:
            if not isinstance(tab, dict):
                continue
            raw_url = str(tab.get("url") or "")
            host = (urlparse(raw_url).hostname or "").lower()
            if host in spec.domains and tab.get("id") and str(tab["id"]) not in used_tabs:
                self._profile_tabs[profile_id] = str(tab["id"])
                return str(tab["id"])
        try:
            created = self.browser.create_tab(session_id, url=spec.chat_url, approved=True)
        except Exception as error:
            if _is_missing_browser_session(error):
                raise _StaleBrowserSession("BrowserSkill session no longer exists") from error
            raise WebChatRuntimeError(f"could not open web-chat page: {type(error).__name__}") from error
        if not isinstance(created, Mapping) or not created.get("executed"):
            return None
        result = created.get("result")
        if isinstance(result, dict):
            tab_id = result.get("id") or result.get("tab_id")
            if tab_id:
                self._profile_tabs[profile_id] = str(tab_id)
                return str(tab_id)
        # BrowserSkill versions differ in create-tab response shape.  Re-list
        # tabs and choose the newly opened tab without exposing page content.
        try:
            listed = self.browser.list_tabs(session_id)
            tabs = listed.get("tabs", []) if isinstance(listed, Mapping) else listed if isinstance(listed, list) else []
            for tab in tabs if isinstance(tabs, list) else []:
                if isinstance(tab, dict) and tab.get("id") and str(tab["id"]) not in used_tabs:
                    if (urlparse(str(tab.get("url") or "")).hostname or "").lower() in spec.domains:
                        self._profile_tabs[profile_id] = str(tab["id"])
                        return str(tab["id"])
        except Exception as error:
            if _is_missing_browser_session(error):
                raise _StaleBrowserSession("BrowserSkill session no longer exists") from error
            raise WebChatRuntimeError("BrowserSkill tab probe failed") from error
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
