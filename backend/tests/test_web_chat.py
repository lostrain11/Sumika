"""Contract tests for the fail-closed browser web-chat capability."""

from __future__ import annotations

import json
import threading
import time
import unittest
from unittest.mock import patch

from sumika_core.browser.runtime import BrowserRuntime
from sumika_core.browser.web_chat import (
    _input_message_state,
    _ResponseStabilityTracker,
    WebChatAdapterRegistry,
    WebChatRuntime,
    WebChatRuntimeError,
)
from sumika_core.storage import Storage


class BrowserStub:
    """Small BrowserRuntime-shaped double; no page text leaves this fixture."""

    def __init__(self, snapshots=None, visual_results=None):
        self.snapshots = list(snapshots or [])
        self.visual_results = list(visual_results or [])
        self.visual_calls = []
        self.sessions = {}
        self.tabs = {}
        self.actions = []
        self.closed = []
        self.closed_tabs = []
        self._session_counter = 0
        self._tab_counter = 0

    def create_session(self, **kwargs):
        self._session_counter += 1
        session_id = f"stub-session-{self._session_counter}"
        self.sessions[session_id] = {"id": session_id, **kwargs}
        self.tabs[session_id] = []
        return {"id": session_id, "state": "ready", "profile": kwargs.get("profile", "named")}

    def list_sessions(self):
        return list(self.sessions.values())

    def list_tabs(self, session_id, **_kwargs):
        return {"session_id": session_id, "ready": True, "tabs": list(self.tabs.get(session_id, []))}

    def create_tab(self, session_id, *, url=None, **_kwargs):
        self._tab_counter += 1
        tab = {"id": f"stub-tab-{self._tab_counter}", "url": url or "https://example.invalid/"}
        self.tabs.setdefault(session_id, []).append(tab)
        return {"executed": True, "result": {"id": tab["id"]}}

    def close_tab(self, session_id, *, tab_id, **_kwargs):
        self.closed_tabs.append((session_id, tab_id))
        self.tabs[session_id] = [item for item in self.tabs.get(session_id, []) if item.get("id") != tab_id]
        return {"executed": True, "tab_id": tab_id}

    def snapshot_session(self, _session_id, **_kwargs):
        if not self.snapshots:
            raise AssertionError("unexpected snapshot request")
        value = self.snapshots.pop(0)
        return value if isinstance(value, dict) and "ready" in value else {"ready": True, "snapshot": value}

    def visual_evidence_session(self, session_id, **kwargs):
        self.visual_calls.append((session_id, kwargs))
        if not self.visual_results:
            return {
                "available": False,
                "confidence": "unknown",
                "prompt_in_input": None,
                "assistant_response_visible": None,
                "blocking_surface_visible": None,
                "evidence_id": None,
                "error_code": "visual-probe-unavailable",
            }
        return self.visual_results.pop(0)

    def execute_action(self, session_id, *, action, target=None, value=None, **kwargs):
        self.actions.append({"session_id": session_id, "action": action, "target": target, "value": value, **kwargs})
        return {"executed": True, "action": action}

    def close_session(self, session_id):
        self.closed.append(session_id)
        self.sessions.pop(session_id, None)
        return {"id": session_id, "closed": True}


class UnavailableBrowserStub(BrowserStub):
    def create_session(self, **_kwargs):
        raise RuntimeError("BrowserSkill is unavailable")


class MalformedSnapshotBrowserStub(BrowserStub):
    def snapshot_session(self, _session_id, **_kwargs):
        return ["malformed snapshot envelope"]


class StaleSessionBrowserStub(BrowserStub):
    """Expose one cached session whose backend disappeared before reuse."""

    def __init__(self, snapshots=None):
        super().__init__(snapshots)
        self.sessions["stale-session"] = {"id": "stale-session", "state": "ready"}
        self.tabs["stale-session"] = []
        self.invalidated = []

    def list_tabs(self, session_id, **kwargs):
        if session_id == "stale-session":
            raise RuntimeError("session not registered")
        return super().list_tabs(session_id, **kwargs)

    def invalidate_session(self, session_id, **_kwargs):
        self.invalidated.append(session_id)
        self.sessions.pop(session_id, None)
        self.tabs.pop(session_id, None)
        return {"id": session_id, "invalidated": True}


class TransientSessionBrowserStub(BrowserStub):
    """Fail cached-session probing without claiming that the session is gone."""

    def __init__(self, snapshots=None):
        super().__init__(snapshots)
        self.sessions["transient-session"] = {"id": "transient-session", "state": "ready"}
        self.tabs["transient-session"] = []

    def list_tabs(self, session_id, **kwargs):
        if session_id == "transient-session":
            raise RuntimeError("temporary BrowserSkill network timeout")
        return super().list_tabs(session_id, **kwargs)


class HtmlResponseBrowserStub(BrowserStub):
    def __init__(self, snapshots=None, html_results=None):
        super().__init__(snapshots)
        self.html_results = list(html_results or [])
        self.html_calls = []

    def extract_html_text_session(self, session_id, **kwargs):
        self.html_calls.append((session_id, kwargs))
        if not self.html_results:
            return {"ready": True, "texts": [], "sensitive": False}
        value = self.html_results.pop(0)
        return value if isinstance(value, dict) else {"ready": True, "texts": [value], "sensitive": False}


class SlowSessionBrowserStub(BrowserStub):
    """Widen the first-session race without adding fixture-side locking."""

    def create_session(self, **kwargs):
        time.sleep(0.05)
        return super().create_session(**kwargs)


class RetryableCloseBrowserStub(BrowserStub):
    def __init__(self):
        super().__init__()
        self.fail_close = True

    def close_session(self, session_id):
        if self.fail_close:
            raise RuntimeError("backend is temporarily busy")
        return super().close_session(session_id)


class DelayedQwenSendBrowserStub(BrowserStub):
    """Expose Qwen's send button only after the controlled input settles."""

    SEND_SELECTOR = "button.send-button[aria-label='发送']"

    def __init__(self, snapshots=None):
        super().__init__(snapshots)
        self.primary_click_attempts = 0

    def execute_action(self, session_id, *, action, target=None, value=None, **kwargs):
        self.actions.append(
            {
                "session_id": session_id,
                "action": action,
                "target": target,
                "value": value,
                **kwargs,
            }
        )
        if action == "click" and target == self.SEND_SELECTOR:
            self.primary_click_attempts += 1
            return {"executed": self.primary_click_attempts >= 3, "action": action}
        if action == "click" and target in {
            "button[type='submit']",
            "button[aria-label*='Send']",
            "button[aria-label*='发送']",
        }:
            raise AssertionError("an unscoped legacy send selector must not be clicked")
        return {"executed": True, "action": action}


def page_snapshot(*, authorized=True, ready=True, response=None):
    nodes = []
    if authorized:
        nodes.append({"tag": "button", "text": "退出登录"})
    else:
        nodes.append({"tag": "button", "text": "登录"})
    if ready:
        nodes.append({"tag": "button", "text": "发送"})
    nodes.append({"tag": "textarea", "selector": "textarea"})
    if response is not None:
        nodes.append(
            {
                "tag": "div",
                "attributes": {"data-message-author-role": "assistant"},
                "text": response,
            }
        )
    return {"ready": True, "snapshot": {"tree": nodes}}


class WebChatRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._stability_patches = (
            patch("sumika_core.browser.web_chat.WEB_CHAT_RESPONSE_STABLE_OBSERVATIONS", 1),
            patch("sumika_core.browser.web_chat.WEB_CHAT_RESPONSE_STABLE_SECONDS", 0.0),
        )
        for stability_patch in self._stability_patches:
            stability_patch.start()
        self.storage = Storage(":memory:")
        self.browser_profiles = BrowserRuntime(storage=self.storage)
        self.browser_profile = self.browser_profiles.create_profile(
            name="网页账号隔离 Profile", character_id="sumika"
        )

    def tearDown(self):
        self.storage.close()
        for stability_patch in reversed(self._stability_patches):
            stability_patch.stop()

    def runtime(self, snapshots=None):
        browser = BrowserStub(snapshots)
        return WebChatRuntime(self.storage, browser), browser

    def create_profile(self, runtime, *, adapter_id="deepseek-web", config=None, draft=False):
        return runtime.create_profile(
            name="DeepSeek 测试账号",
            adapter_id=adapter_id,
            browser_profile_id=self.browser_profile["id"],
            config=config,
            draft=draft,
            approved=True,
        )

    def test_builtin_registry_is_declarative_and_custom_selector_is_validated(self):
        registry = WebChatAdapterRegistry()
        self.assertEqual(
            {item["id"] for item in registry.list()},
            {
                "deepseek-web",
                "chatgpt-web",
                "zhipu-web",
                "qwen-web",
                "kimi-web",
                "doubao-web",
                "custom",
            },
        )
        spec = registry.resolve(
            "custom",
            {
                "name": "自定义站点",
                "domains": ["chat.example.test"],
                "chat_url": "https://chat.example.test/room",
                "selectors": {"input": ["textarea"], "send": ["button.send"]},
            },
        )
        self.assertTrue(spec.custom)
        self.assertEqual(spec.domains, ("chat.example.test",))
        with self.assertRaisesRegex(WebChatRuntimeError, r"HTTP\(S\)"):
            registry.resolve(
                "custom",
                {
                    "domains": ["chat.example.test"],
                    "chat_url": "javascript:alert(1)",
                    "selectors": {"input": ["textarea"]},
                },
            )
        with self.assertRaisesRegex(WebChatRuntimeError, "safe CSS"):
            registry.resolve(
                "custom",
                {
                    "domains": ["chat.example.test"],
                    "chat_url": "https://chat.example.test/",
                    "selectors": {"input": ["javascript:alert(1)"]},
                },
            )

        deepseek = registry.resolve("deepseek-web")
        self.assertIn(
            "div[role='button'].ds-button--primary:not(.ds-button--disabled)",
            deepseek.selectors["send"],
        )
        self.assertEqual(
            deepseek.selectors["response"][0],
            "div.ds-markdown.ds-assistant-message-main-content",
        )

        zhipu = registry.resolve("zhipu-web")
        self.assertEqual(
            zhipu.selectors["response"][0],
            "div.chat-assistant.markdown-prose",
        )

    def test_builtin_site_selectors_precede_legacy_profile_defaults(self):
        registry = WebChatAdapterRegistry()
        qwen = registry.resolve(
            "qwen-web",
            {
                "selectors": {
                    "input": ["textarea"],
                    "send": ["button[type='submit']"],
                    "response": ["[class*='assistant']"],
                }
            },
        )
        kimi = registry.resolve(
            "kimi-web",
            {"selectors": {"response": ["[class*='assistant']"]}},
        )

        self.assertEqual(
            qwen.selectors["input"][0],
            "textarea.message-input-textarea.message-input-textarea-separation",
        )
        self.assertEqual(qwen.selectors["send"][0], "button.send-button[aria-label='发送']")
        self.assertEqual(
            qwen.selectors["response"][0],
            "div.response-message-content.phase-answer",
        )
        self.assertNotIn("[class*='assistant']", qwen.selectors["response"])
        self.assertNotIn("[class*='markdown']", qwen.selectors["response"])
        self.assertNotIn("button[type='submit']", qwen.selectors["send"])
        self.assertNotIn("button[aria-label*='发送']", qwen.selectors["send"])
        self.assertIn("textarea", qwen.selectors["input"])
        self.assertEqual(
            kimi.selectors["response"][0],
            "div[class='markdown-container']",
        )
        self.assertNotIn("div.markdown-container.toolcall-content-text", kimi.selectors["response"])
        self.assertNotIn("[class*='assistant']", kimi.selectors["response"])

    def test_response_tracker_requires_repeated_stable_observations(self):
        tracker = _ResponseStabilityTracker(min_observations=3, min_seconds=1.0)

        self.assertIsNone(tracker.observe("流式片段", observed_at=10.0))
        self.assertIsNone(tracker.observe("流式片段", observed_at=10.5))
        self.assertIsNone(tracker.observe("完整回答", observed_at=10.75))
        self.assertIsNone(tracker.observe("完整回答", observed_at=11.25))
        self.assertEqual(
            tracker.observe("完整回答", observed_at=11.75),
            "完整回答",
        )

    def test_long_accessible_composer_prefix_proves_message_is_still_present(self):
        message = (
            "You are an independent web consultation member for Sumika. "
            "Your response is UNTRUSTED_WEB_RESULT. "
            + ("long context " * 80)
        )
        snapshot = {
            "text": (
                '@e19 textbox "询问 Qwen" [filled] ="'
                + message[:160]
                + '"\n@e23 button "发送"'
            ),
            "ref_count": 2,
            "tab_id": 123,
            "truncated": False,
        }

        self.assertTrue(_input_message_state(snapshot, ("textarea",), message))

    def test_accessible_projection_proves_composer_cleared_when_all_textboxes_are_empty(self):
        snapshot = {
            "text": (
                '@e18 textbox "搜索对话" [empty] placeholder="搜索对话"\n'
                '@e31 textbox "询问 Qwen" [empty] placeholder="询问 Qwen"'
            ),
            "ref_count": 2,
            "tab_id": 123,
            "truncated": False,
        }

        self.assertFalse(_input_message_state(snapshot, ("textarea",), "已发送的提示词"))

    def test_accessible_projection_keeps_mixed_textbox_state_unknown(self):
        snapshot = {
            "text": (
                '@e18 textbox "搜索对话" [empty] placeholder="搜索对话"\n'
                '@e31 textbox "询问 Qwen" [filled]'
            ),
            "ref_count": 2,
            "tab_id": 123,
            "truncated": False,
        }

        self.assertIsNone(_input_message_state(snapshot, ("textarea",), "未暴露的提示词"))

    def test_send_waits_for_a_stable_complete_streaming_response(self):
        runtime, _browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True, response="旧回复"),
                page_snapshot(authorized=True, ready=True, response="短片段"),
                page_snapshot(authorized=True, ready=True, response="短片段"),
                page_snapshot(authorized=True, ready=True, response="完整回答"),
                page_snapshot(authorized=True, ready=True, response="完整回答"),
                page_snapshot(authorized=True, ready=True, response="完整回答"),
            ]
        )
        profile = self.create_profile(
            runtime,
            config={"response_timeout_seconds": 2.0, "observation_timeout_seconds": 2.0},
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        with (
            patch("sumika_core.browser.web_chat.WEB_CHAT_RESPONSE_STABLE_OBSERVATIONS", 3),
            patch("sumika_core.browser.web_chat.WEB_CHAT_RESPONSE_STABLE_SECONDS", 0.0),
        ):
            result = runtime.send_message(profile["id"], "请给出完整回答")

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "完整回答")

    def test_send_ignores_consultation_prompt_echo_before_final_response(self):
        prompt = (
            "You are an independent web consultation member for Sumika.\n"
            "请评议这个方案。"
        )
        runtime, _browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True, response="旧回复"),
                page_snapshot(authorized=True, ready=True, response=prompt),
                page_snapshot(authorized=True, ready=True, response="最终评议"),
            ]
        )
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], prompt)

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "最终评议")

    def test_profile_rejects_credentials_and_requires_named_profile_approval(self):
        runtime, _browser = self.runtime()
        with self.assertRaisesRegex(WebChatRuntimeError, "explicit approval"):
            runtime.create_profile(
                name="未批准",
                adapter_id="deepseek-web",
                browser_profile_id=self.browser_profile["id"],
            )
        with self.assertRaisesRegex(WebChatRuntimeError, "must not contain credentials"):
            self.create_profile(runtime, config={"api_key": "sk-not-for-web-chat"})
        with self.assertRaisesRegex(WebChatRuntimeError, "active named"):
            runtime.create_profile(
                name="不存在 Profile",
                adapter_id="deepseek-web",
                browser_profile_id="browser-profile-missing",
                approved=True,
            )

    def test_draft_update_preserves_state_when_draft_is_omitted(self):
        runtime, _browser = self.runtime()
        profile = self.create_profile(runtime, draft=True)
        self.assertEqual(profile["status"], "draft")
        edited = runtime.update_profile(
            profile["id"], name="改名后的草稿", approved=True
        )
        self.assertEqual(edited["status"], "draft")
        self.assertFalse(edited["auto_chat_enabled"])
        published = runtime.update_profile(
            profile["id"], name="需要重新登录", draft=False, approved=True
        )
        self.assertEqual(published["status"], "needs-auth")

    def test_check_separates_login_state_from_page_readiness(self):
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=False, ready=True),
                page_snapshot(authorized=True, ready=False),
                page_snapshot(authorized=True, ready=True),
            ]
        )
        profile = self.create_profile(runtime)
        first = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(first["ready"])
        self.assertEqual(first["auth_state"], "needs-auth")
        self.assertEqual(first["status"], "needs-auth")
        second = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(second["ready"])
        self.assertEqual(second["auth_state"], "authorized")
        self.assertEqual(second["status"], "unavailable")
        third = runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(third["ready"])
        self.assertEqual(third["status"], "ready")
        self.assertEqual(third["page_ready"], True)
        self.assertEqual(len(browser.sessions), 1)

    def test_check_waits_for_a_new_blank_tab_to_finish_loading(self):
        runtime, browser = self.runtime(
            [
                {"ready": True, "snapshot": {"text": '@vom 1\nRootWebArea "Loading shell"'}},
                page_snapshot(authorized=True, ready=True),
            ]
        )
        profile = self.create_profile(runtime)

        result = runtime.check_profile(profile["id"], approved=True)

        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertEqual(browser.snapshots, [])

    def test_generic_account_text_does_not_prove_authorization(self):
        runtime, _browser = self.runtime(
            [
                {
                    "ready": True,
                    "snapshot": {
                        "tree": [
                            {"tag": "nav", "text": "Account"},
                            {"tag": "button", "text": "发送"},
                            {"tag": "textarea", "selector": "textarea"},
                        ]
                    },
                }
            ]
        )
        profile = self.create_profile(runtime)
        with patch("sumika_core.browser.web_chat.PROFILE_PAGE_LOAD_TIMEOUT_SECONDS", 0.0):
            result = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["auth_state"], "unknown")
        self.assertEqual(result["status"], "needs-auth")

    def test_zhipu_current_shell_markers_prove_ready_profile(self):
        runtime, _browser = self.runtime(
            [
                {
                    "ready": True,
                    "snapshot": {
                        "text": 'RootWebArea "Z.ai - Advanced AI Chatbot & Agent powered by GLM" Open User Menu'
                    },
                }
            ]
        )
        profile = self.create_profile(runtime, adapter_id="zhipu-web")
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertTrue(result["page_ready"])

    def test_zhipu_waits_for_delayed_account_controls_after_the_composer_appears(self):
        partial = {
            "ready": True,
            "snapshot": {
                "text": (
                    'RootWebArea "Z.ai - Advanced AI Chatbot & Agent powered by GLM"\n'
                    '@e5 textbox "有什么我能帮您的？" [empty]\n'
                    'button "发送"'
                )
            },
        }
        settled = {
            "ready": True,
            "snapshot": {
                "text": (
                    'RootWebArea "Z.ai - Advanced AI Chatbot & Agent powered by GLM"\n'
                    'button "Open User Menu"\n'
                    '@e5 textbox "有什么我能帮您的？" [empty]\n'
                    'button "发送"'
                )
            },
        }
        runtime, browser = self.runtime([partial, settled])
        profile = self.create_profile(runtime, adapter_id="zhipu-web")

        result = runtime.check_profile(profile["id"], approved=True)

        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertTrue(result["page_ready"])
        self.assertEqual(browser.snapshots, [])

    def test_kimi_home_composer_markers_prove_ready_profile(self):
        runtime, _browser = self.runtime(
            [
                {
                    "ready": True,
                    "snapshot": {
                        "text": 'RootWebArea "Kimi" 我的 Kimi 新建会话 输入 "/" 唤起插件和技能',
                    },
                }
            ]
        )
        profile = self.create_profile(runtime, adapter_id="kimi-web")
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertTrue(result["page_ready"])
        spec = WebChatAdapterRegistry().resolve("kimi-web")
        self.assertIn(".chat-input-editor", spec.selectors["input"])
        self.assertIn(".send-button-container:not(.disabled)", spec.selectors["send"])

    def test_deepseek_dynamic_account_button_overrides_history_login_text(self):
        runtime, _browser = self.runtime(
            [
                {
                    "ready": True,
                    "snapshot": {
                        "text": (
                            'link "API登录缺失功能" [ctx: 2026-08]\n'
                            '@e109 button "Signed-in user" [ctx: 30 天内]\n'
                            '@e110 button "Signed-in user" [ctx: 30 天内]\n'
                            '@e114 textbox "给 DeepSeek 发送消息" [empty]\n'
                            '@e115 button "深度思考"\n'
                            'button "发送"'
                        )
                    },
                }
            ]
        )
        profile = self.create_profile(runtime, adapter_id="deepseek-web")
        with patch("sumika_core.browser.web_chat.PROFILE_PAGE_LOAD_TIMEOUT_SECONDS", 0.0):
            result = runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertTrue(result["page_ready"])

    def test_deepseek_waits_one_tick_for_delayed_account_controls(self):
        partial = {
            "ready": True,
            "snapshot": {
                "text": (
                    'link "API登录缺失功能" [ctx: 今天]\n'
                    '@e114 textbox "给 DeepSeek 发送消息" [empty]\n'
                    'button "发送"'
                )
            },
        }
        settled = {
            "ready": True,
            "snapshot": {
                "text": (
                    'link "API登录缺失功能" [ctx: 今天]\n'
                    '@e109 button "Signed-in user" [ctx: 7 天内]\n'
                    '@e110 button "Signed-in user" [ctx: 7 天内]\n'
                    '@e114 textbox "给 DeepSeek 发送消息" [empty]\n'
                    'button "发送"'
                )
            },
        }
        runtime, browser = self.runtime([partial, settled])
        profile = self.create_profile(runtime, adapter_id="deepseek-web")

        result = runtime.check_profile(profile["id"], approved=True)

        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertEqual(browser.snapshots, [])

    def test_deepseek_generic_contextual_buttons_do_not_prove_authorization(self):
        runtime, _browser = self.runtime(
            [
                {
                    "ready": True,
                    "snapshot": {
                        "text": (
                            '@e107 button "开启新对话" [ctx: Ctrl + J]\n'
                            '@e114 textbox "给 DeepSeek 发送消息" [empty]\n'
                            '@e115 button "发送"'
                        )
                    },
                }
            ]
        )
        profile = self.create_profile(runtime, adapter_id="deepseek-web")
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["auth_state"], "unknown")

    def test_chatgpt_localized_profile_menu_proves_authorization(self):
        runtime, _browser = self.runtime(
            [
                {
                    "ready": True,
                    "snapshot": {
                        "text": (
                            'button "打开“个人资料”菜单 [has-submenu]"\n'
                            'radio "聊天"\n'
                            'button "发送"\n'
                            'textbox "与 ChatGPT 聊天"'
                        )
                    },
                }
            ]
        )
        profile = self.create_profile(runtime, adapter_id="chatgpt-web")
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["auth_state"], "authorized")
        self.assertTrue(result["page_ready"])

    def test_chatgpt_uses_enter_before_unstable_send_button(self):
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True),
                page_snapshot(authorized=True, ready=True, response="新回复"),
            ]
        )
        profile = self.create_profile(runtime, adapter_id="chatgpt-web")
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], "Enter 发送")

        self.assertTrue(result["ok"], result)
        actions = [(item["action"], item["target"]) for item in browser.actions]
        self.assertEqual(actions[0], ("fill", "#prompt-textarea"))
        self.assertEqual(actions[1], ("press", "#prompt-textarea"))
        self.assertNotIn(("click", "[data-testid='send-button']"), actions)

    def test_chatgpt_tries_click_only_after_enter_proves_composer_still_filled(self):
        message = "Enter 后明确未发送"

        def composer_snapshot(value, response=None):
            snapshot = page_snapshot(authorized=True, ready=True, response=response)
            node = snapshot["snapshot"]["tree"][-1 if response is None else -2]
            node["value"] = value
            return snapshot

        runtime, browser = self.runtime(
            [
                composer_snapshot(""),
                composer_snapshot(message),
                composer_snapshot(message),
                composer_snapshot("", response="备用按钮已发送"),
            ]
        )
        profile = self.create_profile(runtime, adapter_id="chatgpt-web")
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"], result)
        actions = [(item["action"], item["target"]) for item in browser.actions]
        self.assertEqual(
            actions,
            [
                ("fill", "#prompt-textarea"),
                ("press", "#prompt-textarea"),
                ("click", "[data-testid='send-button']"),
            ],
        )

    def test_chatgpt_does_not_click_after_enter_submission_is_uncertain(self):
        transient = {
            "ready": True,
            "snapshot": {
                "text": '@e1 button "退出登录"\n@e2 button "发送"\nStaticText "页面重绘中"',
            },
        }
        runtime, browser = self.runtime(
            [page_snapshot(authorized=True, ready=True), transient, transient]
        )
        profile = self.create_profile(
            runtime,
            adapter_id="chatgpt-web",
            config={"response_timeout_seconds": 0.5, "observation_timeout_seconds": 1.0},
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime._send_message_once(
            profile["id"],
            "不要重复点击",
            response_timeout_seconds=0.5,
            observation_timeout_seconds=0.5,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["possibly_sent"])
        actions = [(item["action"], item["target"]) for item in browser.actions]
        self.assertEqual(actions[:2], [("fill", "#prompt-textarea"), ("press", "#prompt-textarea")])
        self.assertNotIn(("click", "[data-testid='send-button']"), actions)

    def test_consent_and_activation_require_ready_profile_and_health_reports_unknown_quota(self):
        runtime, _browser = self.runtime([page_snapshot(authorized=True, ready=True)])
        profile = self.create_profile(runtime)
        with self.assertRaisesRegex(WebChatRuntimeError, "先检查"):
            runtime.set_consent(profile["id"], enabled=True, approved=True)
        checked = runtime.check_profile(profile["id"], approved=True)
        consented = runtime.set_consent(
            profile["id"], enabled=True, allowed_actions=["chat.read", "chat.send"], approved=True
        )
        self.assertTrue(consented["auto_chat_enabled"])
        self.assertEqual(consented["status"], "ready")
        health = runtime.health(profile["id"])
        self.assertTrue(health["ok"])
        self.assertEqual(health["quota_state"], "unknown")
        self.assertEqual(checked["auth_state"], "authorized")
        activated = runtime.activate_profile(profile["id"], approved=True)
        self.assertEqual(activated["status"], "ready")

    def test_send_rechecks_auth_before_any_dom_action(self):
        runtime, browser = self.runtime([page_snapshot(authorized=False, ready=True)])
        profile = self.create_profile(runtime)
        # A persisted ready/consented state can become stale while the tab is open.
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        result = runtime.send_message(profile["id"], "不要发送")
        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_human"])
        self.assertEqual(browser.actions, [])
        self.assertIn("登录", result["reason"])

    def test_browserskill_unavailable_is_reported_without_an_exception(self):
        browser = UnavailableBrowserStub()
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime)
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("BrowserSkill", result["reason"])

    def test_cached_disconnected_session_is_invalidated_and_recreated(self):
        browser = StaleSessionBrowserStub([page_snapshot(authorized=True, ready=True)])
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime)
        runtime.sessions[profile["id"]] = "stale-session"
        runtime.set_agent_occupancy(profile["id"], True)
        reset_profiles = []
        runtime.set_session_invalidated_callback(reset_profiles.append)

        result = runtime.check_profile(profile["id"], approved=True)

        self.assertTrue(result["ready"])
        self.assertEqual(browser.invalidated, ["stale-session"])
        self.assertNotEqual(runtime.sessions[profile["id"]], "stale-session")
        self.assertFalse(runtime.agent_occupancy(profile["id"]))
        self.assertEqual(reset_profiles, [profile["id"]])

    def test_transient_cached_session_probe_is_not_invalidated(self):
        browser = TransientSessionBrowserStub([page_snapshot(authorized=True, ready=True)])
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime)
        runtime.sessions[profile["id"]] = "transient-session"
        runtime.set_agent_occupancy(profile["id"], True)
        reset_profiles = []
        runtime.set_session_invalidated_callback(reset_profiles.append)

        result = runtime.check_profile(profile["id"], approved=True)

        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(runtime.sessions[profile["id"]], "transient-session")
        self.assertTrue(runtime.agent_occupancy(profile["id"]))
        self.assertEqual(reset_profiles, [])

    def test_malformed_snapshot_fails_closed_and_is_not_exported(self):
        browser = MalformedSnapshotBrowserStub()
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime)
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("snapshot", result)

        # A malformed pre-send response must stop before any DOM action too.
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        sent = runtime.send_message(profile["id"], "不要发送")
        self.assertFalse(sent["ok"])
        self.assertNotIn("snapshot", sent)
        self.assertEqual(browser.actions, [])

    def test_no_new_assistant_response_stays_pending_without_substitute_text(self):
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True, response="旧回复"),
                page_snapshot(authorized=True, ready=True, response="旧回复"),
            ]
        )
        profile = self.create_profile(
            runtime, config={"response_timeout_seconds": 0.5}
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        result = runtime.send_message(profile["id"], "等待回复")
        self.assertFalse(result["ok"])
        self.assertTrue(result["pending"])
        self.assertNotIn("text", result)
        self.assertTrue(browser.actions)

    def test_sensitive_assistant_response_is_blocked_and_not_returned(self):
        secret = "sk-sensitive-response-12345"
        runtime, _browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True, response="旧回复"),
                page_snapshot(authorized=True, ready=True, response=f"api_key={secret}"),
            ]
        )
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        result = runtime.send_message(profile["id"], "请回复")
        self.assertFalse(result["ok"])
        self.assertNotIn("text", result)
        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))
        self.assertIn("sensitive", result["reason"])

    def test_snapshot_sensitive_fields_are_ignored_by_auth_and_response_projection(self):
        secret = "Bearer hidden-session-token-12345"
        safe_snapshot = page_snapshot(authorized=True, ready=True, response="assistant: 安全回复")
        safe_snapshot["snapshot"]["credentials"] = {
            "cookie": "session=do-not-export",
            "authorization": secret,
            "token": "do-not-export",
        }
        runtime, _browser = self.runtime([safe_snapshot])
        profile = self.create_profile(runtime)
        result = runtime.check_profile(profile["id"], approved=True)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertTrue(result["ready"])
        self.assertNotIn("snapshot", result)
        self.assertNotIn("do-not-export", serialized)
        self.assertNotIn(secret, serialized)

    def test_send_extracts_new_assistant_response_without_logging_page_text(self):
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True, response="旧回复"),
                page_snapshot(authorized=True, ready=True, response="新回复"),
            ]
        )
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        result = runtime.send_message(profile["id"], "你好")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "新回复")
        self.assertEqual(profile["id"], result["profile_id"])
        self.assertTrue(any(action["action"] == "fill" for action in browser.actions))
        self.assertTrue(any(action["action"] in {"click", "press"} for action in browser.actions))
        self.assertNotIn("新回复", json.dumps(runtime.list_profiles(), ensure_ascii=False))

    def test_send_accepts_a_new_assistant_node_with_the_same_text(self):
        """A repeated answer must be identified by node identity/count, not text alone."""

        def conversation(responses):
            tree = [
                {"tag": "button", "text": "退出登录"},
                {"tag": "button", "text": "发送"},
                {"tag": "textarea", "selector": "textarea", "ref": "@e42"},
            ]
            tree.extend(
                {
                    "tag": "div",
                    "attributes": {
                        "data-message-author-role": "assistant",
                        "data-message-id": f"message-{index}",
                    },
                    "text": response,
                }
                for index, response in enumerate(responses)
            )
            return {"ready": True, "snapshot": {"tree": tree}}

        repeated = "相同的网页回答"
        runtime, _browser = self.runtime(
            [conversation([repeated]), conversation([repeated, repeated])]
        )
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], "请再次回答")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["text"], repeated)

    def test_submission_visual_probe_is_scoped_to_the_input_ref(self):
        message = "输入框区域验证"

        def with_input(value, response=None):
            snapshot = page_snapshot(authorized=True, ready=True, response=response)
            input_node = snapshot["snapshot"]["tree"][-1 if response is None else -2]
            input_node.update({"ref": "@e42", "value": value})
            return snapshot

        runtime, browser = self.runtime(
            [
                with_input(""),
                with_input(message),
                with_input(message),
                with_input("", response="已发送"),
            ]
        )
        browser.visual_results = [
            {
                "available": True,
                "confidence": "high",
                "prompt_in_input": True,
                "assistant_response_visible": False,
                "blocking_surface_visible": False,
                "evidence_id": "visual-input-baseline",
            },
            {
                "available": True,
                "confidence": "high",
                "prompt_in_input": True,
                "assistant_response_visible": False,
                "blocking_surface_visible": False,
                "evidence_id": "visual-input-after",
            },
        ]
        profile = self.create_profile(
            runtime,
            config={
                "selectors": {"send": ["button.first", "button.second"]},
                "response_timeout_seconds": 0.5,
            },
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"], result)
        self.assertEqual(browser.visual_calls[0][1]["scope"], "input")
        self.assertEqual(browser.visual_calls[0][1]["ref"], "@e42")
        self.assertEqual(browser.visual_calls[1][1]["scope"], "input")
        self.assertEqual(browser.visual_calls[1][1]["ref"], "@e42")

    def test_send_uses_html_projection_when_snapshot_flattens_assistant_node(self):
        browser = HtmlResponseBrowserStub(
            [
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
            ],
            html_results=["旧网页回复", "新网页建议"],
        )
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime, config={"response_timeout_seconds": 0.5})
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        result = runtime.send_message(profile["id"], "给出一个新建议")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "新网页建议")
        self.assertGreaterEqual(len(browser.html_calls), 2)

    def test_html_projection_keeps_multiplicity_aligned_after_tail_limit(self):
        """Counts belong to the same last-64 projection as their text values."""
        browser = HtmlResponseBrowserStub(
            [
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
            ],
            html_results=[
                {
                    "ready": True,
                    "texts": [f"old-{index}" for index in range(64)] + ["same-answer"],
                    "text_counts": [1] * 64 + [1],
                    "sensitive": False,
                },
                {
                    "ready": True,
                    "texts": [f"old-{index}" for index in range(64)] + ["same-answer"],
                    "text_counts": [1] * 64 + [2],
                    "sensitive": False,
                },
            ],
        )
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime, config={"response_timeout_seconds": 0.5})
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], "请求相同答案")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["text"], "same-answer")

    def test_kimi_transient_thinking_text_is_not_returned_as_the_answer(self):
        browser = HtmlResponseBrowserStub(
            [
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
                page_snapshot(authorized=True, ready=True, response=None),
            ],
            html_results=["旧网页回复", "正在思考中 用户", "最终评议结论"],
        )
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(
            runtime,
            adapter_id="kimi-web",
            config={"response_timeout_seconds": 2.0, "observation_timeout_seconds": 2.0},
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], "给出最终结论")

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "最终评议结论")

    def test_send_tries_the_next_selector_when_the_composer_still_contains_the_message(self):
        message = "验证发送状态"

        def composer_snapshot(value, response=None):
            snapshot = page_snapshot(authorized=True, ready=True, response=response)
            snapshot["snapshot"]["tree"][-1 if response is None else -2]["value"] = value
            return snapshot

        runtime, browser = self.runtime(
            [
                composer_snapshot(""),
                composer_snapshot(message),
                composer_snapshot(message),
                composer_snapshot("", response="已收到"),
            ]
        )
        profile = self.create_profile(
            runtime,
            adapter_id="custom",
            config={
                "name": "发送校验夹具",
                "domains": ["example.invalid"],
                "chat_url": "https://example.invalid/",
                "selectors": {
                    "input": ["textarea"],
                    "send": ["button.wrong", "button.right"],
                    "response": ["[data-message-author-role='assistant']"],
                },
                "authorized_markers": ["退出登录"],
                "ready_markers": ["发送"],
                "response_timeout_seconds": 2.0,
            },
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"])
        clicks = [item["target"] for item in browser.actions if item["action"] == "click"]
        self.assertEqual(clicks, ["button.wrong", "button.right"])

    def test_send_rechecks_an_unknown_composer_before_accepting_the_click(self):
        message = "验证重绘后的发送状态"
        transient = {
            "ready": True,
            "snapshot": {
                "text": '@e1 button "退出登录"\n@e2 button "发送"\nStaticText "输入框重绘中"'
            },
        }
        still_filled = {
            "ready": True,
            "snapshot": {
                "text": (
                    '@e1 button "退出登录"\n@e2 button "发送"\n'
                    f'@e3 textbox "聊天" [filled] ="{message}"'
                )
            },
        }
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True),
                transient,
                still_filled,
                page_snapshot(authorized=True, ready=True, response="已收到"),
            ]
        )
        profile = self.create_profile(
            runtime,
            adapter_id="custom",
            config={
                "name": "重绘发送校验夹具",
                "domains": ["example.invalid"],
                "chat_url": "https://example.invalid/",
                "selectors": {
                    "input": ["textarea"],
                    "send": ["button.first", "button.second"],
                    "response": ["[data-message-author-role='assistant']"],
                },
                "authorized_markers": ["退出登录"],
                "ready_markers": ["发送"],
                "response_timeout_seconds": 0.5,
            },
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"])
        clicks = [item["target"] for item in browser.actions if item["action"] == "click"]
        self.assertEqual(clicks, ["button.first", "button.second"])

    def test_qwen_waits_for_dynamic_send_button_and_delayed_composer_clear(self):
        message = "验证千问动态发送按钮"

        def composer_snapshot(value, response=None):
            snapshot = page_snapshot(authorized=True, ready=True, response=response)
            snapshot["snapshot"]["tree"][-1 if response is None else -2]["value"] = value
            if response is not None:
                snapshot["snapshot"]["tree"][-1]["class"] = (
                    "response-message-content phase-answer"
                )
            return snapshot

        browser = DelayedQwenSendBrowserStub(
            [
                composer_snapshot(""),
                composer_snapshot(message),
                composer_snapshot(message),
                composer_snapshot("", response="SUMIKA_OK"),
            ]
        )
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(
            runtime,
            adapter_id="qwen-web",
            config={
                "selectors": {
                    "send": [
                        "button[type='submit']",
                        "button[aria-label*='发送']",
                    ]
                },
                "response_timeout_seconds": 2.0,
            },
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["text"], "SUMIKA_OK")
        self.assertEqual(browser.primary_click_attempts, 3)
        clicks = [item["target"] for item in browser.actions if item["action"] == "click"]
        self.assertEqual(clicks, [DelayedQwenSendBrowserStub.SEND_SELECTOR] * 3)

    def test_visual_probe_retries_when_unknown_dom_still_shows_prompt_in_composer(self):
        message = "视觉复核仍在输入框"
        transient = {
            "ready": True,
            "snapshot": {"text": '@e1 button "退出登录"\n@e2 button "发送"\nStaticText "输入框重绘中"'},
        }
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True),
                transient,
                transient,
                page_snapshot(authorized=True, ready=True, response="已收到"),
            ]
        )
        browser.visual_results = [
            {"available": True, "confidence": "high", "prompt_in_input": True, "assistant_response_visible": False, "blocking_surface_visible": False, "evidence_id": "visual-before"},
            {"available": True, "confidence": "high", "prompt_in_input": True, "assistant_response_visible": False, "blocking_surface_visible": False, "evidence_id": "visual-after"},
        ]
        profile = self.create_profile(
            runtime,
            adapter_id="custom",
            config={
                "name": "视觉发送校验夹具",
                "domains": ["example.invalid"],
                "chat_url": "https://example.invalid/",
                "selectors": {
                    "input": ["textarea"],
                    "send": ["button.first", "button.second"],
                    "response": ["[data-message-author-role='assistant']"],
                },
                "authorized_markers": ["退出登录"],
                "ready_markers": ["发送"],
                "response_timeout_seconds": 0.5,
            },
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"])
        clicks = [item["target"] for item in browser.actions if item["action"] == "click"]
        self.assertEqual(clicks, ["button.first", "button.second"])
        self.assertEqual(len(browser.visual_calls), 2)

    def test_visual_uncertainty_never_repeats_a_possibly_sent_message(self):
        message = "不要重复发送"
        transient = {
            "ready": True,
            "snapshot": {"text": '@e1 button "退出登录"\n@e2 button "发送"\nStaticText "输入框重绘中"'},
        }
        runtime, browser = self.runtime(
            [
                page_snapshot(authorized=True, ready=True),
                transient,
                transient,
                page_snapshot(authorized=True, ready=True, response="只收到一次"),
            ]
        )
        browser.visual_results = [
            {"available": True, "confidence": "high", "prompt_in_input": True, "assistant_response_visible": False, "blocking_surface_visible": False, "evidence_id": "visual-before"},
            {"available": True, "confidence": "low", "prompt_in_input": None, "assistant_response_visible": None, "blocking_surface_visible": None, "evidence_id": "visual-unknown"},
        ]
        profile = self.create_profile(
            runtime,
            adapter_id="custom",
            config={
                "name": "不确定发送夹具",
                "domains": ["example.invalid"],
                "chat_url": "https://example.invalid/",
                "selectors": {
                    "input": ["textarea"],
                    "send": ["button.first", "button.second"],
                    "response": ["[data-message-author-role='assistant']"],
                },
                "authorized_markers": ["退出登录"],
                "ready_markers": ["发送"],
                "response_timeout_seconds": 0.5,
            },
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime.send_message(profile["id"], message)

        self.assertTrue(result["ok"])
        clicks = [item["target"] for item in browser.actions if item["action"] == "click"]
        self.assertEqual(clicks, ["button.first"])

    def test_visual_reply_without_dom_extraction_returns_explicit_failure(self):
        browser = HtmlResponseBrowserStub(
            [page_snapshot(authorized=True, ready=True)] * 8,
            html_results=[None] * 8,
        )
        browser.visual_results = [
            {"available": True, "confidence": "high", "prompt_in_input": True, "assistant_response_visible": False, "blocking_surface_visible": False, "evidence_id": "visual-before"},
            {"available": True, "confidence": "high", "prompt_in_input": False, "assistant_response_visible": True, "blocking_surface_visible": False, "evidence_id": "visual-after"},
        ]
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(
            runtime,
            config={"response_timeout_seconds": 0.5, "observation_timeout_seconds": 1.0},
        )
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        result = runtime._send_message_once(
            profile["id"],
            "需要视觉佐证",
            response_timeout_seconds=0.5,
            observation_timeout_seconds=0.5,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["possibly_sent"])
        self.assertEqual(result["error_code"], "response-visible-extraction-failed")
        self.assertNotIn("text", result)

    def test_profiles_bound_to_one_named_browser_profile_share_session_but_not_tab(self):
        runtime, browser = self.runtime()
        first = self.create_profile(runtime, adapter_id="deepseek-web")
        second = runtime.create_profile(
            name="Qwen 测试账号",
            adapter_id="qwen-web",
            browser_profile_id=self.browser_profile["id"],
            approved=True,
        )

        first_open = runtime.open_profile(first["id"], approved=True)
        second_open = runtime.open_profile(second["id"], approved=True)

        self.assertEqual(first_open["session_id"], second_open["session_id"])
        self.assertNotEqual(first_open["tab_id"], second_open["tab_id"])
        self.assertEqual(len(browser.sessions), 1)
        self.assertEqual(len(browser.tabs[first_open["session_id"]]), 2)

        runtime.close_profile(first["id"], approved=True)
        self.assertIn(second_open["session_id"], browser.sessions)
        self.assertEqual(browser.closed_tabs, [(first_open["session_id"], first_open["tab_id"])])

    def test_parallel_profiles_create_one_shared_session_and_distinct_tabs(self):
        browser = SlowSessionBrowserStub()
        runtime = WebChatRuntime(self.storage, browser)
        profiles = [
            self.create_profile(runtime, adapter_id="deepseek-web"),
            runtime.create_profile(
                name="Qwen 并发测试账号",
                adapter_id="qwen-web",
                browser_profile_id=self.browser_profile["id"],
                approved=True,
            ),
            runtime.create_profile(
                name="Kimi 并发测试账号",
                adapter_id="kimi-web",
                browser_profile_id=self.browser_profile["id"],
                approved=True,
            ),
        ]
        start = threading.Event()
        results = []
        errors = []

        def open_profile(profile_id):
            start.wait()
            try:
                results.append(runtime.open_profile(profile_id, approved=True))
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [threading.Thread(target=open_profile, args=(profile["id"],)) for profile in profiles]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 3)
        self.assertEqual(len({item["session_id"] for item in results}), 1)
        self.assertEqual(len({item["tab_id"] for item in results}), 3)
        self.assertEqual(len(browser.sessions), 1)

    def test_failed_profile_close_keeps_binding_for_a_retry(self):
        browser = RetryableCloseBrowserStub()
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime)
        opened = runtime.open_profile(profile["id"], approved=True)

        with self.assertRaisesRegex(RuntimeError, "temporarily busy"):
            runtime.close_profile(profile["id"], approved=True)

        self.assertEqual(runtime.sessions[profile["id"]], opened["session_id"])
        self.assertIn(opened["session_id"], browser.sessions)
        browser.fail_close = False
        closed = runtime.close_profile(profile["id"], approved=True)
        self.assertTrue(closed["closed"])
        self.assertNotIn(profile["id"], runtime.sessions)

    def test_agent_owned_shared_window_closes_after_worker_idle_timeout(self):
        browser = BrowserStub(
            [
                page_snapshot(authorized=True, ready=True),
                page_snapshot(authorized=True, ready=True, response="评议完成"),
            ]
        )
        runtime = WebChatRuntime(
            self.storage,
            browser,
            worker_idle_close_seconds=0.03,
        )
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )

        accepted = runtime.start_message(profile["id"], "请评议", owner="agent")
        completed = runtime.wait_message(accepted["attempt_id"], timeout=2.0)
        self.assertEqual(completed["status"], "completed")
        deadline = time.monotonic() + 1.0
        while browser.sessions and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(browser.sessions, {})
        self.assertEqual(runtime.sessions, {})

    def test_sensitive_html_projection_is_not_returned(self):
        browser = HtmlResponseBrowserStub(
            [page_snapshot(authorized=True, ready=True, response=None)],
            html_results=[{"ready": True, "texts": ["api_key=sk-hidden-secret-12345"], "sensitive": True}],
        )
        runtime = WebChatRuntime(self.storage, browser)
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        result = runtime.send_message(profile["id"], "请回复")
        self.assertFalse(result["ok"])
        self.assertNotIn("sk-hidden-secret-12345", json.dumps(result, ensure_ascii=False))
        self.assertIn("sensitive", result["reason"])

    def test_archive_then_restore_always_requires_fresh_login_and_consent(self):
        runtime, browser = self.runtime()
        profile = self.create_profile(runtime)
        self.storage.update_web_chat_profile(
            profile["id"], status="ready", auth_state="authorized", auto_chat_enabled=True
        )
        archived = runtime.archive_profile(profile["id"], approved=True)
        self.assertEqual(archived["status"], "archived")
        restored = runtime.restore_profile(profile["id"], approved=True)
        self.assertEqual(restored["status"], "needs-auth")
        self.assertEqual(restored["auth_state"], "unknown")
        self.assertFalse(restored["auto_chat_enabled"])
        self.assertEqual(browser.closed, [])

    def test_provider_projection_is_unconfigured_until_consent(self):
        runtime, _browser = self.runtime()
        profile = self.create_profile(runtime)
        info = runtime.provider_info(profile["id"])
        self.assertEqual(info.id, f"web-chat:{profile['id']}")
        self.assertEqual(info.status, "unconfigured")
        self.assertNotIn("secret", json.dumps(info.to_dict(), ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
