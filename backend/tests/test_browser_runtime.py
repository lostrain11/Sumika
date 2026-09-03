import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sumika_core.browser.runtime import BrowserRuntime, BrowserRuntimeError, BrowserSkillClient
from sumika_core.storage import Storage


class BrowserRuntimeTests(unittest.TestCase):
    def test_visual_evidence_consumes_raw_screenshot_without_exposing_path_or_text(self):
        calls = []

        class Probe:
            available = True

            def status(self):
                return {"available": True, "implementation": "fixture"}

            def observe(self, path):
                calls.append(("observe", str(path)))
                return {"private_text": "fixture OCR text"}

            def evaluate(self, _observation, **_kwargs):
                return {
                    "available": True,
                    "confidence": "high",
                    "prompt_in_input": False,
                    "assistant_response_visible": True,
                    "blocking_surface_visible": False,
                    "evidence": ["baseline-compared"],
                    "error_code": None,
                    "line_count": 2,
                }

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "private-page.png"
            screenshot.write_bytes(b"png")

            def runner(args):
                calls.append(args)
                if args == ("status",):
                    return {"browsers": [{"id": "browser-1"}], "sessions": []}
                if args == ("session", "start"):
                    return {"id": "bsk-session-1"}
                if args[0] == "screenshot":
                    return {"path": str(screenshot), "width": 640}
                raise AssertionError(args)

            runtime = BrowserRuntime(
                browser_skill=BrowserSkillClient("bsk", runner=runner),
                visual_probe=Probe(),
            )
            session = runtime.create_session()
            result = runtime.visual_evidence_session(
                session["id"],
                expected_text="private prompt",
            )

        self.assertTrue(result["available"])
        self.assertTrue(result["assistant_response_visible"])
        serialized = str(result)
        self.assertNotIn("private-page.png", serialized)
        self.assertNotIn("fixture OCR text", serialized)
        self.assertNotIn("private prompt", serialized)

    def test_cli_actions_force_ref_or_selector_target_kind(self):
        calls = []

        def runner(args):
            calls.append(args)
            return {"executed": True}

        client = BrowserSkillClient("bsk", runner=runner)
        client.click("session-1", "@e12")
        client.fill("session-1", "textarea", "hello")
        client.select("session-1", "e3", ["option-a"])
        client.press("session-1", "Enter", target="@e4")

        self.assertEqual(calls[0], ("click", "--session", "session-1", "--ref", "@e12"))
        self.assertEqual(calls[1], ("fill", "--session", "session-1", "--value", "hello", "--selector", "textarea"))
        self.assertEqual(calls[2], ("select", "--session", "session-1", "--value", "option-a", "--ref", "@e3"))
        self.assertEqual(calls[3], ("press", "--session", "session-1", "--ref", "@e4", "Enter"))

    def test_cli_state_distinguishes_waiting_for_extension(self):
        calls = []

        def runner(args):
            calls.append(args)
            return {"daemon_version": "0.1.11", "browsers": [], "sessions": []}

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        status = runtime.status()
        self.assertEqual(status["state"], "awaiting-extension")
        self.assertFalse(status["ready"])
        self.assertEqual(status["browser_count"], 0)
        self.assertEqual(calls, [("status",)])

    def test_cli_status_is_cached_briefly_between_ui_refreshes(self):
        calls = []

        def runner(args):
            calls.append(args)
            return {"daemon_version": "0.1.11", "browsers": [], "sessions": []}

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        runtime.status()
        runtime.status()
        self.assertEqual(calls, [("status",)])

    def test_connected_cli_owns_backend_session_lifecycle(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"daemon_version": "0.1.11", "browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args == ("session", "stop", "bsk-session-1"):
                return {"closed": True}
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        self.assertEqual(session["state"], "ready")
        self.assertEqual(session["backend_session_id"], "bsk-session-1")
        self.assertEqual(runtime.close_session(session["id"])["closed"], True)
        self.assertIn(("session", "start"), calls)
        self.assertIn(("session", "stop", "bsk-session-1"), calls)

    def test_observe_and_tabs_use_real_bsk_commands_and_redact_page_secrets(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[:3] == ("tab", "list", "--session"):
                return [{"id": "tab-1", "title": "Inbox", "url": "https://example.test/inbox"}]
            if args[:2] == ("observe", "--session"):
                return {"url": "https://example.test/inbox", "password": "secret", "tree": [{"text": "Hello"}]}
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        tabs = runtime.list_tabs(session["id"])
        observation = runtime.observe_session(session["id"])
        self.assertEqual(tabs["tabs"][0]["id"], "tab-1")
        self.assertEqual(observation["observation"]["tree"][0]["text"], "Hello")
        self.assertEqual(observation["observation"]["password"], "[redacted]")
        self.assertTrue(any(args[0] == "observe" for args in calls))

    def test_snapshot_marker_hits_scan_beyond_compact_projection_without_returning_text(self):
        long_text = "head " + ("x" * 5_000) + " 退出登录 ... 发送"
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "snapshot":
                return {
                    "text": long_text,
                    "credentials": {"token": "private-token"},
                }
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        result = runtime.snapshot_session(
            session["id"],
            max_tokens=8_000,
            marker_sets={
                "authorized": ("退出登录",),
                "login": ("请先登录",),
                "ready": ("发送",),
            },
        )
        self.assertTrue(result["marker_hits"]["authorized"])
        self.assertTrue(result["marker_hits"]["ready"])
        self.assertFalse(result["marker_hits"]["login"])
        self.assertNotIn("private-token", str(result))
        self.assertLessEqual(len(result["snapshot"]["text"]), 800)
        snapshot_call = next(args for args in calls if args[0] == "snapshot")
        self.assertIn("8000", snapshot_call)

    def test_missing_backend_stop_is_idempotent_and_releases_named_profile_lease(self):
        storage = Storage(":memory:")

        def runner(args):
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args == ("session", "stop", "bsk-session-1"):
                raise BrowserRuntimeError("session not registered", code="not_found")
            raise AssertionError(args)

        runtime = BrowserRuntime(
            storage=storage,
            browser_skill=BrowserSkillClient("bsk", runner=runner),
        )
        profile = runtime.create_profile(name="可恢复网页账号", agent_id="agent-1")
        session = runtime.create_session(
            profile="named",
            profile_id=profile["id"],
            agent_id="agent-1",
            approved=True,
        )
        self.assertIsNotNone(storage.get_browser_profile_lease(profile["id"]))

        closed = runtime.close_session(session["id"])

        self.assertTrue(closed["closed"])
        self.assertTrue(closed["backend_session_missing"])
        self.assertNotIn(session["id"], runtime.sessions)
        self.assertIsNone(storage.get_browser_profile_lease(profile["id"]))
        storage.close()

    def test_real_backend_stop_error_remains_explicit(self):
        def runner(args):
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args == ("session", "stop", "bsk-session-1"):
                raise BrowserRuntimeError("unfinished command", code="session_busy")
            raise AssertionError(args)

        runtime = BrowserRuntime(
            browser_skill=BrowserSkillClient("bsk", runner=runner),
        )
        session = runtime.create_session()

        with self.assertRaisesRegex(BrowserRuntimeError, "could not stop"):
            runtime.close_session(session["id"])

        self.assertIn(session["id"], runtime.sessions)

    def test_cli_preserves_structured_error_code_for_idempotent_callers(self):
        completed = SimpleNamespace(
            returncode=1,
            stdout='{"code":"not_found","message":"already stopped"}',
            stderr="",
        )
        client = BrowserSkillClient("bsk")

        with patch("sumika_core.browser.runtime.subprocess.run", return_value=completed):
            with self.assertRaises(BrowserRuntimeError) as raised:
                client.stop_session("missing-session")

        self.assertEqual(raised.exception.code, "not_found")

    def test_snapshot_marker_hits_dynamic_account_button_without_returning_label(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "snapshot":
                return {
                    "text": (
                        '@e1 button "Private display name" [ctx: 30 天内]\n'
                        '@e2 button "Private display name" [ctx: 30 天内]'
                    ),
                }
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        result = runtime.snapshot_session(
            session["id"],
            marker_sets={"account_button": ("__account_button__",)},
        )
        self.assertTrue(result["marker_hits"]["account_button"])
        self.assertNotIn("account_label", result["marker_hits"])
        self.assertTrue(any(args[0] == "snapshot" for args in calls))

    def test_html_projection_forwards_bounded_get_html_and_returns_selected_text_only(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "get-html":
                return {
                    "html": (
                        '<script>const token="sk-script-secret-12345";</script>'
                        '<div class="user-message">不应返回</div>'
                        '<div class="ds-assistant-message-main-content">'
                        "安全的建议 <strong>可执行</strong>"
                        "</div>"
                    ),
                    "truncated": False,
                }
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        result = runtime.extract_html_text_session(
            session["id"],
            tab_id="tab-1",
            selectors=("[class*='assistant']",),
            max_bytes=1,
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["texts"], ["安全的建议 可执行"])
        self.assertFalse(result["sensitive"])
        self.assertNotIn("user-message", str(result))
        html_calls = [args for args in calls if args[0] == "get-html"]
        self.assertEqual(len(html_calls), 1)
        self.assertIn("--max-bytes", html_calls[0])
        self.assertIn("32000", html_calls[0])

    def test_html_projection_redacts_selected_secret_and_marks_sensitive(self):
        def runner(args):
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "get-html":
                return {"html": '<div class="assistant">api_key=sk-selected-secret-12345</div>'}
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        result = runtime.extract_html_text_session(
            session["id"], selectors=("[class*='assistant']",)
        )
        self.assertTrue(result["sensitive"])
        self.assertNotIn("sk-selected-secret-12345", str(result))
        self.assertEqual(result["texts"], ["[redacted]"])

    def test_html_projection_keeps_only_the_outermost_nested_selected_node(self):
        def runner(args):
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "get-html":
                return {
                    "html": (
                        '<div class="assistant message">'
                        '<div class="assistant markdown">同一条回答</div>'
                        '</div>'
                        '<div class="assistant message">第二条回答</div>'
                    )
                }
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()

        result = runtime.extract_html_text_session(
            session["id"],
            selectors=("[class*='assistant']",),
        )

        self.assertEqual(result["texts"], ["同一条回答", "第二条回答"])
        self.assertEqual(result["text_counts"], [1, 1])
        self.assertEqual(result["selected_node_count"], 2)

    def test_html_projection_supports_current_chatgpt_composer_and_assistant_attributes(self):
        def runner(args):
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "get-html":
                return {
                    "html": (
                        '<textarea data-composer-draft-react="" aria-label="与 ChatGPT 聊天"></textarea>'
                        '<button data-composer-submit="" aria-label="发送消息"></button>'
                        '<li data-message-role="assistant">'
                        '<div data-assistant-markdown="">当前 ChatGPT 回复</div>'
                        '</li>'
                    )
                }
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        result = runtime.extract_html_text_session(
            session["id"],
            selectors=("[data-assistant-markdown]", "[data-message-role='assistant']"),
        )

        self.assertEqual(result["texts"], ["当前 ChatGPT 回复"])
        self.assertEqual(result["selected_node_count"], 1)

    def test_html_projection_scans_a_bounded_large_page_for_a_late_response(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "get-html":
                return {
                    "html": (
                        "<main><p>"
                        + ("x" * 1_550_000)
                        + '</p><div class="response-message-content phase-answer">'
                        + "SUMIKA_QWEN_OK"
                        + "</div></main>"
                    ),
                    "truncated": False,
                }
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()

        result = runtime.extract_html_text_session(
            session["id"],
            selectors=("div.response-message-content.phase-answer",),
        )

        self.assertEqual(result["texts"], ["SUMIKA_QWEN_OK"])
        html_call = next(args for args in calls if args[0] == "get-html")
        self.assertEqual(html_call[html_call.index("--max-bytes") + 1], "2000000")

    def test_navigation_requires_approval_before_calling_bsk(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "navigate":
                return {"url": "https://example.test"}
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        pending = runtime.navigate_session(session["id"], url="https://example.test")
        self.assertFalse(pending["executed"])
        self.assertFalse(any(args[0] == "navigate" for args in calls))
        done = runtime.navigate_session(session["id"], url="https://example.test", approved=True)
        self.assertTrue(done["executed"])
        self.assertTrue(any(args[0] == "navigate" for args in calls))

    def test_internal_tabs_only_allow_the_newtab_page(self):
        runtime = BrowserRuntime()
        session = runtime.create_session()
        with self.assertRaises(BrowserRuntimeError):
            runtime.create_tab(session["id"], url="chrome://settings/")
        with self.assertRaises(BrowserRuntimeError):
            runtime.create_tab(session["id"], url="chrome://newtab/?unsafe=1")

    def test_tab_and_navigation_urls_reject_embedded_credentials(self):
        runtime = BrowserRuntime()
        session = runtime.create_session()
        with self.assertRaises(BrowserRuntimeError):
            runtime.create_tab(session["id"], url="https://user:secret@example.test/")
        with self.assertRaises(BrowserRuntimeError):
            runtime.navigate_session(session["id"], url="https://user:secret@example.test/", approved=True)

    def test_screenshot_projection_does_not_expose_local_paths(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "screenshot":
                return {"path": r"C:\Users\private\capture.png", "data": "base64-secret", "width": 640}
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        result = runtime.screenshot_session(session["id"])
        self.assertEqual(result["screenshot"]["path"], "[omitted local path]")
        self.assertEqual(result["screenshot"]["data"], "[omitted binary payload]")
        self.assertNotIn(r"C:\Users\private", str(result))

    def test_dom_actions_are_approval_gated_and_credentials_stay_manual(self):
        calls = []

        def runner(args):
            calls.append(args)
            if args == ("status",):
                return {"browsers": [{"id": "browser-1"}], "sessions": []}
            if args == ("session", "start"):
                return {"id": "bsk-session-1"}
            if args[0] == "click":
                return {"ok": True}
            if args[0] == "fill":
                return {"ok": True}
            raise AssertionError(args)

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        session = runtime.create_session()
        pending = runtime.execute_action(session["id"], action="click", target="@e1")
        self.assertFalse(pending["executed"])
        self.assertFalse(any(args[0] == "click" for args in calls))
        done = runtime.execute_action(session["id"], action="click", target="@e1", approved=True)
        self.assertTrue(done["executed"])
        manual = runtime.execute_action(session["id"], action="fill", target="#password", value="secret", approved=True)
        self.assertTrue(manual["requires_human"])
        self.assertFalse(any(args[0] == "fill" for args in calls))

    def test_sensitive_actions_require_approval(self):
        runtime = BrowserRuntime()
        session = runtime.create_session()
        denied = runtime.check_action(session_id=session["id"], action="login", domain="example.com")
        self.assertTrue(denied["requires_approval"])
        self.assertFalse(denied["allowed"])
        allowed = runtime.check_action(session_id=session["id"], action="login", domain="example.com", approved=True)
        self.assertTrue(allowed["allowed"])

    def test_help_never_contains_credentials_and_download_is_quarantined(self):
        runtime = BrowserRuntime()
        session = runtime.create_session()
        help_request = runtime.request_help(session_id=session["id"], domain="accounts.example", reason="需要输入 OTP")
        self.assertTrue(help_request["credentials_excluded"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "download.txt"
            path.write_text("safe", encoding="utf-8")
            item = runtime.quarantine_download(session_id=session["id"], path=str(path), source_url="https://example.invalid/file")
            self.assertEqual(item["status"], "quarantine")
            with self.assertRaises(BrowserRuntimeError):
                runtime.release_download(item["id"])
            self.assertEqual(runtime.release_download(item["id"], approved=True)["status"], "approved")
            with self.assertRaises(BrowserRuntimeError):
                runtime.release_download(item["id"], approved=True)

    def test_release_rechecks_quarantine_hash_before_import(self):
        runtime = BrowserRuntime()
        session = runtime.create_session()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "download.txt"
            path.write_text("safe", encoding="utf-8")
            item = runtime.quarantine_download(session_id=session["id"], path=str(path), source_url="https://example.invalid/file")
            path.write_text("changed", encoding="utf-8")
            with self.assertRaises(BrowserRuntimeError):
                runtime.release_download(item["id"], approved=True)

    def test_temporary_profile_has_expiry(self):
        runtime = BrowserRuntime()
        session = runtime.create_session(profile="temporary")
        self.assertIsNotNone(session["expires_at"])
        self.assertEqual(runtime.list_sessions()[0]["id"], session["id"])
        self.assertNotIn("backend_session_id", runtime.list_sessions()[0])
        self.assertEqual(runtime.close_session(session["id"])["closed"], True)

    def test_named_profile_persists_and_has_one_write_lease(self):
        storage = Storage(":memory:")
        try:
            first_runtime = BrowserRuntime(storage=storage)
            profile = first_runtime.create_profile(name="工作账号", character_id="sumika")
            self.assertEqual(first_runtime.list_profiles()[0]["id"], profile["id"])

            second_runtime = BrowserRuntime(storage=storage)
            persisted = second_runtime.list_profiles()
            self.assertEqual(persisted[0]["name"], "工作账号")
            session = second_runtime.create_session(
                profile="named",
                profile_id=profile["id"],
                character_id="sumika",
                approved=True,
            )
            self.assertTrue(next(item for item in second_runtime.list_profiles() if item["id"] == profile["id"])["leased"])
            with self.assertRaisesRegex(BrowserRuntimeError, "already in use"):
                first_runtime.create_session(
                    profile="named",
                    profile_id=profile["id"],
                    character_id="sumika",
                    approved=True,
                )

            second_runtime.close_session(session["id"])
            released = next(item for item in first_runtime.list_profiles() if item["id"] == profile["id"])
            self.assertFalse(released["leased"])
            resumed = first_runtime.create_session(
                profile="named",
                profile_id=profile["id"],
                character_id="sumika",
                approved=True,
            )
            first_runtime.close_session(resumed["id"])
        finally:
            storage.close()

    def test_named_profile_survives_storage_close_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sumika.sqlite3"
            storage = Storage(database)
            profile = BrowserRuntime(storage=storage).create_profile(
                name="重开后仍可用",
                character_id="sumika",
            )
            storage.close()

            reopened = Storage(database)
            try:
                persisted = reopened.list_browser_profiles()
                self.assertEqual([item["id"] for item in persisted], [profile["id"]])
                self.assertEqual(persisted[0]["name"], "重开后仍可用")
            finally:
                reopened.close()

    def test_named_profile_requires_matching_authorization_and_approval(self):
        storage = Storage(":memory:")
        try:
            runtime = BrowserRuntime(storage=storage)
            profile = runtime.create_profile(name="仅 Sumika", character_id="sumika")
            with self.assertRaisesRegex(BrowserRuntimeError, "explicit approval"):
                runtime.create_session(profile="named", profile_id=profile["id"], character_id="sumika")
            with self.assertRaisesRegex(BrowserRuntimeError, "another character"):
                runtime.create_session(
                    profile="named",
                    profile_id=profile["id"],
                    character_id="other",
                    approved=True,
                )
            with self.assertRaisesRegex(BrowserRuntimeError, "profile_id"):
                runtime.create_session(profile="named", character_id="sumika", approved=True)
        finally:
            storage.close()

    def test_named_profile_can_be_archived_and_restored_without_deleting_metadata(self):
        storage = Storage(":memory:")
        try:
            runtime = BrowserRuntime(storage=storage)
            profile = runtime.create_profile(name="可恢复登录", agent_id="agent-1")
            archived = runtime.archive_profile(profile["id"])
            self.assertEqual(archived["status"], "archived")
            self.assertEqual(storage.get_browser_profile(profile["id"])["name"], "可恢复登录")
            with self.assertRaisesRegex(BrowserRuntimeError, "unavailable"):
                runtime.create_session(
                    profile="named",
                    profile_id=profile["id"],
                    agent_id="agent-1",
                    approved=True,
                )
            restored = runtime.restore_profile(profile["id"])
            self.assertEqual(restored["status"], "active")
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
