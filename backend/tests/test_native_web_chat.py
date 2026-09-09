"""Native transport fixtures only: no network, browser windows or real models."""

from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch

from sumika_core.browser.web_chat import WebChatRuntime, WebChatRuntimeError
from sumika_core.storage import Storage


class LegacyBrowserFixture:
    def __init__(self):
        self.calls = []

    def list_profiles(self, **kwargs):
        self.calls.append("list_profiles")
        return []

    def create_session(self, **kwargs):
        self.calls.append("create_session")
        raise AssertionError("native transport must not open BrowserSkill")


class NativeExchangeFixture:
    def __init__(self):
        self.calls = []
        self.results = {}
        self.entered = threading.Event()
        self.finish = threading.Event()
        self.block_send = False

    def __call__(self, operation, profile, *, text=None, attempt_id=None, cancelled=None):
        self.calls.append((operation, dict(profile), text, attempt_id, cancelled))
        if operation == "send":
            self.entered.set()
            if self.block_send:
                if not self.finish.wait(3):
                    raise TimeoutError("fixture send did not finish")
        if operation in self.results:
            result = self.results[operation]
            if isinstance(result, Exception):
                raise result
            return dict(result) if isinstance(result, dict) else result
        if operation in {"check", "health"}:
            return {"status": "ready", "auth_state": "authorized", "page_ready": True,
                    "tab_id": profile["tab_id"]}
        if operation == "send":
            return {"status": "completed", "sent": True, "text": "fixture response",
                    "attempt_id": attempt_id, "tab_id": profile["tab_id"]}
        return {"status": {"open": "opened", "authorize": "needs-auth", "focus": "focused",
                           "close": "closed", "takeover": "takeover", "resume": "resumed"}[operation],
                "tab_id": profile["tab_id"]}


class NativeWebChatTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(":memory:")
        self.browser = LegacyBrowserFixture()
        self.exchange = NativeExchangeFixture()
        self.runtime = WebChatRuntime(self.storage, self.browser, native_exchange=self.exchange)
        self.storage.create_browser_profile(profile_id="browser-fixture", name="Fixture",
                                            character_id=None, agent_id=None)

    def tearDown(self):
        self.exchange.finish.set()
        for attempt in list(self.runtime._attempts.values()):
            self.runtime.wait_message(attempt["attempt_id"], timeout=3)
        self.runtime.close()
        self.storage.close()

    def profile(self, *, adapter="chatgpt-web", browser_id="browser-fixture", native=True, ready=True):
        profile = self.runtime.create_profile(name="Fixture chat", adapter_id=adapter,
                                              browser_profile_id=browser_id, approved=True)
        if native:
            profile = self.runtime.bind_native(profile["id"], approved=True)
        if ready:
            self.storage.update_web_chat_profile(profile["id"], status="ready", auth_state="authorized",
                                                 auto_chat_enabled=True)
        self.browser.calls.clear()
        return self.runtime.get_profile(profile["id"])

    def send(self, profile, text="fixture prompt"):
        accepted = self.runtime.start_message(profile["id"], text)
        if accepted["accepted"]:
            return self.runtime.wait_message(accepted["attempt_id"], timeout=3)
        return accepted

    def test_public_native_attribute_and_injection(self):
        replacement = NativeExchangeFixture()
        self.runtime.native.exchange = replacement
        self.assertIs(self.runtime.native.exchange, replacement)
        self.runtime.set_native_exchange(self.exchange)
        with self.assertRaises(WebChatRuntimeError):
            self.runtime.set_native_exchange("not callable")

    def test_bind_requires_explicit_approval_and_preserves_original_data(self):
        profile = self.profile(native=False)
        before = self.storage.get_web_chat_profile(profile["id"])
        browser_before = self.storage.get_browser_profile("browser-fixture")
        for approval in (False, None, "yes", 1):
            with self.subTest(approval=approval), self.assertRaises(WebChatRuntimeError):
                self.runtime.bind_native(profile["id"], approved=approval)
        bound = self.runtime.bind_native(profile["id"], approved=True)
        after = self.storage.get_web_chat_profile(profile["id"])
        self.assertEqual(bound["transport"], "native")
        self.assertEqual(bound["auth_state"], "unknown")
        self.assertEqual(bound["status"], "needs-auth")
        for key in ("id", "name", "browser_profile_id", "browser_instance", "allowed_actions", "auto_chat_enabled", "budget_policy"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["config"], {**before["config"], "transport": "native"})
        self.assertEqual(browser_before, self.storage.get_browser_profile("browser-fixture"))
        self.assertEqual(self.exchange.calls, [])
        self.assertEqual(self.runtime.bind_native(profile["id"], approved=True), bound)

    def test_binding_rejects_existing_account_session(self):
        profile = self.profile(native=False)
        peer = self.profile(native=False)
        self.runtime.sessions[peer["id"]] = "legacy-session"
        with self.assertRaisesRegex(WebChatRuntimeError, "close active"):
            self.runtime.bind_native(profile["id"], approved=True)
        self.runtime.sessions.clear()
        self.assertEqual(self.runtime.get_profile(profile["id"])["transport"], "browser-skill")

    def test_profile_edits_cannot_silently_change_transport(self):
        profile = self.profile()
        edited = self.runtime.update_profile(profile["id"], name="Renamed", config={}, approved=True)
        self.assertEqual(edited["transport"], "native")
        with self.assertRaisesRegex(WebChatRuntimeError, "transport"):
            self.runtime.update_profile(profile["id"], config={"transport": "browser-skill"}, approved=True)
        with self.assertRaisesRegex(WebChatRuntimeError, "bind_native"):
            self.runtime.create_profile(name="Bypass", adapter_id="chatgpt-web", browser_profile_id="browser-fixture",
                                        config={"transport": "native"}, approved=True)

    def test_control_operations_use_callback_without_legacy_browser(self):
        profile = self.profile(ready=False)
        for method in (self.runtime.authorize_profile, self.runtime.open_profile,
                       self.runtime.focus_profile, self.runtime.close_profile):
            result = method(profile["id"], approved=True)
            self.assertEqual(result["transport"], "native")
            self.assertFalse(result["isolated_window"])
        checked = self.runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(checked["ready"])
        self.runtime.set_consent(profile["id"], enabled=True, approved=True)
        health = self.runtime.health(profile["id"])
        self.assertTrue(health["ok"])
        self.assertEqual(health["quota_state"], "unknown")
        self.assertEqual([call[0] for call in self.exchange.calls], ["authorize", "open", "focus", "close", "check"])
        self.assertEqual(self.browser.calls, [])

    def test_control_operations_do_not_bypass_approval(self):
        profile = self.profile(ready=False)
        for method in (self.runtime.authorize_profile, self.runtime.open_profile, self.runtime.focus_profile,
                       self.runtime.close_profile, self.runtime.check_profile, self.runtime.takeover_profile):
            with self.subTest(method=method.__name__), self.assertRaises(WebChatRuntimeError):
                method(profile["id"])
        self.assertFalse(self.exchange.calls)

    def test_known_sites_send_with_bounded_metadata_and_same_attempt(self):
        for adapter, site in (("chatgpt-web", "chatgpt"), ("kimi-web", "kimi")):
            with self.subTest(adapter=adapter):
                profile = self.profile(adapter=adapter)
                result = self.send(profile)
                self.assertEqual(result["status"], "completed")
                self.assertTrue(result["sent"])
                self.assertEqual(result["text"], "fixture response")
                call = self.exchange.calls[-1]
                self.assertEqual(call[0], "send")
                self.assertEqual(call[1]["site_key"], site)
                self.assertEqual(call[1]["account_id"], profile["native_account_id"])
                self.assertEqual(call[1]["tab_id"], profile["id"])
                self.assertNotIn("config", call[1])
                self.assertNotIn("browser_profile_id", call[1])
                self.assertEqual(call[3], result["attempt_id"])
                self.assertIsInstance(call[4], threading.Event)
                self.assertNotIn("fixture prompt", json.dumps(self.storage.get_web_chat_profile(profile["id"])))
        self.assertEqual(self.browser.calls, [])

    def test_other_sites_are_manual_only_even_when_callback_claims_ready(self):
        profile = self.profile(adapter="deepseek-web")
        opened = self.runtime.open_profile(profile["id"], approved=True)
        checked = self.runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(opened["automation_supported"])
        self.assertFalse(checked["ready"])
        self.assertFalse(self.runtime.health(profile["id"])["ok"])
        self.assertEqual(self.runtime.provider_info(profile["id"]).status, "unconfigured")
        with self.assertRaisesRegex(WebChatRuntimeError, "manual use only"):
            self.runtime.set_consent(profile["id"], enabled=True, approved=True)
        result = self.send(profile)
        self.assertFalse(result["accepted"])
        self.assertNotIn("send", [call[0] for call in self.exchange.calls])

    def test_login_and_consent_are_still_required(self):
        profile = self.profile(ready=False)
        result = self.send(profile)
        self.assertEqual(result["status"], "needs-confirmation")
        self.storage.update_web_chat_profile(profile["id"], auto_chat_enabled=True)
        result = self.send(profile)
        self.assertEqual(result["status"], "waiting-human")
        self.assertFalse(self.exchange.calls)

    def test_bridge_absence_and_unsupported_transport_never_fallback(self):
        profile = self.profile()
        self.runtime.set_native_exchange(None)
        result = self.send(profile)
        self.assertFalse(result["ok"])
        self.assertFalse(result["possibly_sent"])
        self.assertEqual(self.runtime.provider_info(profile["id"]).status, "unconfigured")
        self.assertFalse(self.runtime.check_profile(profile["id"], approved=True)["ready"])
        config = self.storage.get_web_chat_profile(profile["id"])["config"]
        self.storage.update_web_chat_profile(profile["id"], config={**config, "transport": "typo"})
        with self.assertRaisesRegex(WebChatRuntimeError, "unknown web-chat transport"):
            self.runtime.open_profile(profile["id"], approved=True)
        self.assertEqual(self.browser.calls, [])

    def test_same_account_profiles_cannot_write_concurrently(self):
        profile = self.profile()
        peer = self.profile()
        self.exchange.block_send = True
        accepted = self.runtime.start_message(profile["id"], "one")
        self.assertTrue(self.exchange.entered.wait(1))
        result = self.runtime.start_message(peer["id"], "two", owner="agent")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error_code"], "account-occupied")
        self.exchange.finish.set()
        self.runtime.wait_message(accepted["attempt_id"], timeout=3)
        self.assertTrue(self.send(peer)["ok"])

    def test_separate_accounts_can_send_independently(self):
        profile = self.profile()
        self.storage.create_browser_profile(profile_id="other-fixture", name="Other", character_id=None, agent_id=None)
        other = self.profile(browser_id="other-fixture")
        self.assertNotEqual(profile["native_account_id"], other["native_account_id"])
        self.exchange.block_send = True
        accepted = self.runtime.start_message(profile["id"], "one")
        self.assertTrue(self.exchange.entered.wait(1))
        second = self.runtime.start_message(other["id"], "two")
        self.assertTrue(second["accepted"])
        self.exchange.finish.set()
        self.assertTrue(self.runtime.wait_message(accepted["attempt_id"], timeout=3)["ok"])
        self.assertTrue(self.runtime.wait_message(second["attempt_id"], timeout=3)["ok"])

    def test_unknown_submission_blocks_peers_and_survives_runtime_restart(self):
        profile = self.profile()
        peer = self.profile()
        self.exchange.results["send"] = TimeoutError("no page details may leak")
        result = self.send(profile)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["possibly_sent"])
        pending = self.runtime.get_profile(profile["id"])["native_pending_attempt"]
        self.assertEqual(pending, result["attempt_id"])
        self.assertFalse(self.send(peer)["accepted"])
        self.assertFalse(self.runtime.health(profile["id"])["ok"])
        self.runtime.close()
        self.runtime = WebChatRuntime(self.storage, self.browser, native_exchange=self.exchange)
        self.assertFalse(self.send(profile)["accepted"])
        self.runtime.bind_native(profile["id"], approved=True)
        self.runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(self.send(peer)["accepted"])
        self.assertEqual(len([call for call in self.exchange.calls if call[0] == "send"]), 1)

    def test_unknown_requires_same_attempt_evidence_not_generic_readiness(self):
        profile = self.profile()
        self.exchange.results["send"] = {"status": "unknown"}
        result = self.send(profile)
        self.exchange.results["check"] = {"status": "not-sent", "attempt_id": "wrong-attempt",
                                           "sent": False, "possibly_sent": False}
        self.runtime.check_profile(profile["id"], approved=True)
        self.assertEqual(self.runtime.get_profile(profile["id"])["native_pending_attempt"], result["attempt_id"])
        self.exchange.results["check"]["attempt_id"] = result["attempt_id"]
        self.runtime.check_profile(profile["id"], approved=True)
        self.assertIsNone(self.runtime.get_profile(profile["id"])["native_pending_attempt"])
        self.assertEqual(len([call for call in self.exchange.calls if call[0] == "send"]), 1)

    def test_definite_not_sent_can_be_explicitly_retried(self):
        profile = self.profile()
        self.exchange.results["send"] = {"status": "not-sent", "sent": False, "possibly_sent": False}
        result = self.send(profile)
        self.assertFalse(result["possibly_sent"])
        self.assertIsNone(self.runtime.get_profile(profile["id"])["native_pending_attempt"])
        self.exchange.results.pop("send")
        self.assertTrue(self.send(profile)["ok"])

    def test_malformed_or_unbounded_results_fail_closed_without_content_leaks(self):
        cases = [None, {"status": "invented"}, {"status": "completed", "sent": "true", "text": "fake"},
                 {"status": "completed", "sent": True, "text": ""},
                 {"status": "completed", "sent": True, "text": "x" * 24_001},
                 {"status": "completed", "sent": True, "text": "password=fixture-secret"},
                 {"status": "completed", "sent": True, "text": "answer", "attempt_id": "wrong-attempt"},
                 {"status": "failed"}, {"status": "not-sent", "sent": "false", "possibly_sent": False}]
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                browser_id = f"malformed-{index}"
                self.storage.create_browser_profile(profile_id=browser_id, name="Malformed", character_id=None, agent_id=None)
                profile = self.profile(browser_id=browser_id)
                self.exchange.results["send"] = raw
                result = self.send(profile)
                self.assertEqual(result["status"], "unknown")
                self.assertNotIn("text", result)
                self.assertFalse(self.send(profile)["accepted"])

    def test_unknown_extra_fields_are_not_exposed_or_persisted(self):
        profile = self.profile()
        self.exchange.results["check"] = {"status": "ready", "auth_state": "authorized", "page_ready": True,
                                           "cookie": "fixture-cookie", "html": "private page", "reason": "private reason"}
        self.runtime.check_profile(profile["id"], approved=True)
        result = self.runtime.health(profile["id"])
        serialized = json.dumps(result) + json.dumps(self.storage.get_web_chat_profile(profile["id"]))
        for value in ("fixture-cookie", "private page", "private reason"):
            self.assertNotIn(value, serialized)

    def test_sensitive_and_oversized_prompts_do_not_reach_callback(self):
        profile = self.profile()
        for message in ("password=fixture-secret", "x" * 12_001):
            result = self.send(profile, message)
            self.assertFalse(result["ok"])
            self.assertFalse(result["possibly_sent"])
        self.assertFalse(self.exchange.calls)

    def test_takeover_cancels_inflight_and_never_replays_on_release(self):
        profile = self.profile()
        peer = self.profile()
        self.exchange.block_send = True
        accepted = self.runtime.start_message(profile["id"], "one", owner="agent")
        self.assertTrue(self.exchange.entered.wait(1))
        takeover = self.runtime.takeover_profile(peer["id"], approved=True)
        self.assertEqual(takeover["status"], "takeover")
        self.assertTrue(self.exchange.calls[0][4].is_set())
        self.assertFalse(self.send(peer)["accepted"])
        self.exchange.finish.set()
        finished = self.runtime.wait_message(accepted["attempt_id"], timeout=3)
        self.assertEqual(finished["status"], "cancelled")
        self.assertTrue(finished["possibly_sent"])
        self.runtime.takeover_profile(peer["id"], enabled=False, approved=True)
        self.assertFalse(self.send(peer)["accepted"])
        self.assertEqual(len([call for call in self.exchange.calls if call[0] == "send"]), 1)

    def test_takeover_survives_restart_and_needs_explicit_release(self):
        profile = self.profile()
        self.runtime.takeover_profile(profile["id"], approved=True)
        self.runtime.close()
        self.runtime = WebChatRuntime(self.storage, self.browser, native_exchange=self.exchange)
        self.runtime.check_profile(profile["id"], approved=True)
        self.assertFalse(self.send(profile)["accepted"])
        self.runtime.takeover_profile(profile["id"], enabled=False, approved=True)
        self.assertTrue(self.send(profile)["ok"])

    def test_cancel_before_worker_dispatch_releases_account(self):
        profile = self.profile()
        with patch("sumika_core.browser.web_chat.threading.Thread.start"):
            accepted = self.runtime.start_message(profile["id"], "one")
        self.runtime.cancel_message(accepted["attempt_id"])
        self.runtime._run_attempt(accepted["attempt_id"])
        self.assertTrue(self.send(profile)["ok"])

    def test_close_tracks_manual_login_tabs_and_retains_pending_attempt(self):
        profile = self.profile()
        self.runtime.authorize_profile(profile["id"], approved=True)
        self.runtime.close()
        self.assertEqual([call[0] for call in self.exchange.calls], ["authorize", "close"])
        with self.assertRaises(WebChatRuntimeError):
            self.runtime.open_profile(profile["id"], approved=True)
        self.assertIsNotNone(self.storage.get_browser_profile("browser-fixture"))

    def test_edit_cannot_discard_unknown_submission(self):
        profile = self.profile()
        self.exchange.results["send"] = {"status": "unknown"}
        self.send(profile)
        with self.assertRaisesRegex(WebChatRuntimeError, "unresolved"):
            self.runtime.update_profile(profile["id"], name="Do not clear", config={}, approved=True)

    def test_health_is_fresh_cached_and_never_queues_page_operations(self):
        profile = self.profile()
        self.assertFalse(self.runtime.health(profile["id"])["ok"])
        self.assertEqual(self.exchange.calls, [])
        self.runtime.check_profile(profile["id"], approved=True)
        calls = len(self.exchange.calls)
        for _ in range(5):
            self.assertTrue(self.runtime.health(profile["id"])["ok"])
            self.assertEqual(self.runtime.provider_info(profile["id"]).status, "available")
        self.assertEqual(len(self.exchange.calls), calls)
        self.exchange.available = False
        self.assertFalse(self.runtime.health(profile["id"])["ok"])
        self.exchange.available = True
        self.assertTrue(self.runtime.health(profile["id"])["ok"])
        with patch("sumika_core.browser.native_web_chat.time.monotonic", return_value=float("inf")):
            self.assertFalse(self.runtime.health(profile["id"])["ok"])
            self.assertEqual(self.runtime.provider_info(profile["id"]).status, "unconfigured")
        self.assertEqual(len(self.exchange.calls), calls)

    def test_health_invalidates_on_bridge_change_and_profile_edit(self):
        profile = self.profile()
        self.runtime.check_profile(profile["id"], approved=True)
        self.assertTrue(self.runtime.health(profile["id"])["ok"])
        self.runtime.native.exchange = NativeExchangeFixture()
        self.assertFalse(self.runtime.health(profile["id"])["ok"])
        self.runtime.check_profile(profile["id"], approved=True)
        self.runtime.update_profile(profile["id"], name="Edited", approved=True)
        self.assertFalse(self.runtime.health(profile["id"])["ok"])

    def test_runtime_cancel_keeps_writer_until_callback_finishes(self):
        profile = self.profile()
        peer = self.profile()
        self.exchange.block_send = True
        accepted = self.runtime.start_message(profile["id"], "one")
        self.assertTrue(self.exchange.entered.wait(1))
        cancelled = self.runtime.cancel_message(accepted["attempt_id"])
        self.assertTrue(cancelled["cancelled"])
        self.assertFalse(self.send(peer)["accepted"])
        self.exchange.finish.set()
        result = self.runtime.wait_message(accepted["attempt_id"], timeout=3)
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn("text", result)
        self.assertFalse(self.send(peer)["accepted"])

    def test_shutdown_interrupts_native_attempt_without_erasing_unknown(self):
        profile = self.profile()
        self.exchange.block_send = True
        accepted = self.runtime.start_message(profile["id"], "one")
        self.assertTrue(self.exchange.entered.wait(1))
        self.runtime.close()
        self.exchange.finish.set()
        result = self.runtime.wait_message(accepted["attempt_id"], timeout=3)
        self.assertEqual(result["status"], "interrupted")
        self.assertTrue(result["possibly_sent"])
        self.assertEqual(self.runtime.get_profile(profile["id"])["native_pending_attempt"], accepted["attempt_id"])

    def test_budget_and_action_revocation_block_native_dispatch(self):
        for field, value in (("budget_policy", "paid"), ("allowed_actions", ["chat.read"]), ("auto_chat_enabled", False)):
            with self.subTest(field=field):
                profile = self.profile()
                self.storage.update_web_chat_profile(profile["id"], **{field: value})
                result = self.send(profile)
                self.assertFalse(result["ok"])
                self.assertFalse(result.get("possibly_sent"))
        self.assertEqual(self.exchange.calls, [])

    def test_native_occupancy_blocks_legacy_peer(self):
        profile = self.profile()
        peer = self.profile(native=False)
        self.exchange.block_send = True
        accepted = self.runtime.start_message(profile["id"], "one")
        self.assertTrue(self.exchange.entered.wait(1))
        self.assertFalse(self.send(peer)["accepted"])
        self.exchange.finish.set()
        self.runtime.wait_message(accepted["attempt_id"], timeout=3)
        self.assertNotIn("create_session", self.browser.calls)

    def test_direct_bridge_health_availability_does_not_enqueue(self):
        from sumika_core.embedded_browser import EmbeddedBrowserBridge

        profile = self.profile()
        bridge = EmbeddedBrowserBridge()
        self.runtime.set_native_exchange(bridge.exchange)
        token = bridge.attach()["token"]
        self.assertFalse(self.runtime.health(profile["id"])["ok"])
        self.assertIsNone(bridge.poll(token)["request"])
        bridge.close()
        self.assertFalse(self.runtime.health(profile["id"])["ok"])


if __name__ == "__main__":
    unittest.main()
