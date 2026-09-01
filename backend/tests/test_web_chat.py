"""Contract tests for the fail-closed browser web-chat capability."""

from __future__ import annotations

import json
import unittest

from sumika_core.browser.runtime import BrowserRuntime
from sumika_core.browser.web_chat import (
    WebChatAdapterRegistry,
    WebChatRuntime,
    WebChatRuntimeError,
)
from sumika_core.storage import Storage


class BrowserStub:
    """Small BrowserRuntime-shaped double; no page text leaves this fixture."""

    def __init__(self, snapshots=None):
        self.snapshots = list(snapshots or [])
        self.sessions = {}
        self.tabs = {}
        self.actions = []
        self.closed = []
        self._session_counter = 0

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
        tab = {"id": "stub-tab-1", "url": url or "https://example.invalid/"}
        self.tabs.setdefault(session_id, []).append(tab)
        return {"executed": True, "result": {"id": tab["id"]}}

    def snapshot_session(self, _session_id, **_kwargs):
        if not self.snapshots:
            raise AssertionError("unexpected snapshot request")
        value = self.snapshots.pop(0)
        return value if isinstance(value, dict) and "ready" in value else {"ready": True, "snapshot": value}

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
        self.storage = Storage(":memory:")
        self.browser_profiles = BrowserRuntime(storage=self.storage)
        self.browser_profile = self.browser_profiles.create_profile(
            name="网页账号隔离 Profile", character_id="sumika"
        )

    def tearDown(self):
        self.storage.close()

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
        result = runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(result["ready"])
        self.assertEqual(result["auth_state"], "unknown")
        self.assertEqual(result["status"], "needs-auth")

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
