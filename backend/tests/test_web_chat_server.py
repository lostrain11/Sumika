"""RPC contract tests for web-chat profile projection."""

from __future__ import annotations

import unittest

from sumika_core.server import CoreApplication

try:
    from .test_web_chat import BrowserStub, page_snapshot
except ImportError:  # Running this file directly from ``backend/tests``.
    from test_web_chat import BrowserStub, page_snapshot


class WebChatServerTests(unittest.TestCase):
    def setUp(self):
        self.application = CoreApplication(":memory:")
        browser_profile = self.application.browser.create_profile(
            name="网页测试登录态", character_id="sumika"
        )
        self.browser_stub = BrowserStub([page_snapshot(authorized=True, ready=True)])
        # Keep the real BrowserRuntime for profile authorization metadata, but
        # replace only the external BrowserSkill transport for deterministic
        # RPC tests.
        self.application.web_chat.browser = self.browser_stub
        self.browser_profile_id = browser_profile["id"]

    def tearDown(self):
        self.application.close()

    def test_profile_rpc_lifecycle_projects_real_provider_and_resets_restore_consent(self):
        adapters = self.application.rpc("browser.web_chat.adapters", {})
        self.assertIn("deepseek-web", {item["id"] for item in adapters["adapters"]})

        created = self.application.rpc(
            "browser.web_chat.profile.create",
            {
                "name": "DeepSeek 网页测试",
                "adapter_id": "deepseek-web",
                "browser_profile_id": self.browser_profile_id,
                "draft": True,
                "approved": True,
            },
        )
        profile = created
        self.assertEqual(profile["status"], "draft")
        profile_id = profile["id"]

        # An update without the optional draft field keeps the saved draft.
        edited = self.application.rpc(
            "browser.web_chat.profile.update",
            {
                "profile_id": profile_id,
                "name": "DeepSeek 网页测试·改名",
                "approved": True,
            },
        )
        self.assertEqual(edited["status"], "draft")

        checked = self.application.rpc(
            "browser.web_chat.profile.check",
            {"profile_id": profile_id, "approved": True},
        )
        self.assertTrue(checked["ready"])
        checked_route = next(
            item
            for item in self.application.route_supervisor.catalog(include_unavailable=True)["routes"]
            if item["route_id"] == f"web:{profile_id}"
        )
        self.assertEqual(checked_route["auth_state"], "authorized")
        self.assertEqual(checked_route["health_state"], "healthy")
        self.assertFalse(checked_route["routable"])
        consented = self.application.rpc(
            "browser.web_chat.profile.consent",
            {
                "profile_id": profile_id,
                "enabled": True,
                "allowed_actions": ["chat.read", "chat.send"],
                "approved": True,
            },
        )
        self.assertTrue(consented["auto_chat_enabled"])
        consented_route = next(
            item
            for item in self.application.route_supervisor.catalog(include_unavailable=True)["routes"]
            if item["route_id"] == f"web:{profile_id}"
        )
        self.assertTrue(consented_route["routable"])
        self.assertEqual(consented_route["quota_consent"], "granted")

        self.application.rpc(
            "browser.web_chat.profile.authorize",
            {"profile_id": profile_id, "approved": True},
        )
        relogin_route = next(
            item
            for item in self.application.route_supervisor.catalog(include_unavailable=True)["routes"]
            if item["route_id"] == f"web:{profile_id}"
        )
        self.assertEqual(relogin_route["auth_state"], "needs-auth")
        self.assertFalse(relogin_route["routable"])
        self.browser_stub.snapshots.append(page_snapshot(authorized=True, ready=True))
        self.application.rpc(
            "browser.web_chat.profile.check",
            {"profile_id": profile_id, "approved": True},
        )
        self.application.rpc(
            "browser.web_chat.profile.consent",
            {
                "profile_id": profile_id,
                "enabled": True,
                "allowed_actions": ["chat.read", "chat.send"],
                "approved": True,
            },
        )
        activated = self.application.rpc(
            "browser.web_chat.profile.activate",
            {"profile_id": profile_id, "approved": True},
        )
        self.assertTrue(activated["activated"])
        self.assertEqual(activated["module"]["implementation_id"], f"web-chat:{profile_id}")
        self.assertIn(f"web-chat:{profile_id}", {item.id for item in self.application.providers.list()})

        # The active profile is protected from archival; turn the module off
        # first, exactly as the production UI requires.
        self.application.rpc(
            "module.update",
            {"module_id": "llm", "enabled": False, "implementation_id": "none"},
        )
        archived = self.application.rpc(
            "browser.web_chat.profile.archive",
            {"profile_id": profile_id, "approved": True},
        )
        self.assertEqual(archived["status"], "archived")
        self.assertNotIn(
            f"web:{profile_id}",
            {
                item["route_id"]
                for item in self.application.route_supervisor.catalog(include_unavailable=True)["routes"]
            },
        )
        restored = self.application.rpc(
            "browser.web_chat.profile.restore",
            {"profile_id": profile_id, "approved": True},
        )
        self.assertEqual(restored["status"], "needs-auth")
        self.assertEqual(restored["auth_state"], "unknown")
        self.assertFalse(restored["auto_chat_enabled"])
        restored_route = next(
            item
            for item in self.application.route_supervisor.catalog(include_unavailable=True)["routes"]
            if item["route_id"] == f"web:{profile_id}"
        )
        self.assertFalse(restored_route["routable"])
        listed = self.application.rpc(
            "browser.web_chat.profiles", {"include_archived": True}
        )
        self.assertEqual(listed["profiles"][0]["id"], profile_id)


if __name__ == "__main__":
    unittest.main()
