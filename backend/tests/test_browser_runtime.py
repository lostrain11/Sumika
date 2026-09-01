import tempfile
import unittest
from pathlib import Path

from sumika_core.browser.runtime import BrowserRuntime, BrowserRuntimeError, BrowserSkillClient
from sumika_core.storage import Storage


class BrowserRuntimeTests(unittest.TestCase):
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
        self.assertTrue(any(args[0] == "snapshot" for args in calls))

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
