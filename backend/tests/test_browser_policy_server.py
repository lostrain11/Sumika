import unittest
from unittest.mock import patch

from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication


class BrowserPolicyServerTests(unittest.TestCase):
    def setUp(self):
        self.application = CoreApplication(":memory:")

    def tearDown(self):
        self.application.close()

    def test_policy_rpc_uses_local_session_ownership_and_audits_only_metadata(self):
        session = self.application.rpc(
            "browser.session.create",
            {"profile": "temporary", "character_id": "sumika"},
        )
        allowed = self.application.rpc(
            "browser.policy.evaluate",
            {
                "tool_name": "browser_snapshot",
                "action": "snapshot",
                "session_id": session["id"],
                "domain": "Example.COM.",
                "current_domain": "example.com",
                "target_kind": "none",
                "value_length": 0,
                "sensitive": False,
                "session_known": False,
                "new_tab": False,
            },
        )
        self.assertEqual(allowed["decision"], "allow")
        self.assertEqual(allowed["domain"], "example.com")
        denied = self.application.rpc(
            "browser.policy.evaluate",
            {
                "tool_name": "browser_fill",
                "action": "fill",
                "session_id": session["id"],
                "domain": "example.com",
                "current_domain": "example.com",
                "target_kind": "css_selector",
                "value_length": 14,
                "sensitive": True,
                "session_known": False,
                "new_tab": False,
            },
        )
        self.assertEqual(denied["decision"], "deny")
        self.assertTrue(denied["requires_human"])
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "browser.policy.evaluate",
                {
                    "tool_name": "browser_snapshot",
                    "action": "snapshot",
                    "session_id": session["id"],
                    "domain": "example.com",
                    "secret_value": "private-secret",
                },
            )
        self.assertEqual(error.exception.code, -32602)
        audit = str(self.application.storage.list_events(20))
        self.assertIn("browser.policy.allowed", audit)
        self.assertIn("browser.policy.denied", audit)
        self.assertNotIn("private-secret", audit)

    def test_external_help_rejects_prompt_secrets_and_does_not_audit_prompt(self):
        with patch.object(
            self.application.browser,
            "request_external_help",
            return_value={
                "session_id": "bsk-1",
                "domain": "accounts.example",
                "outcome": "continued",
                "requires_human": True,
                "credentials_excluded": True,
                "backend_requested": True,
            },
        ) as request_help:
            result = self.application.rpc(
                "browser.policy.request_help",
                {
                    "session_id": "bsk-1",
                    "domain": "Accounts.Example.",
                    "reason": "请在隔离窗口中完成登录",
                    "title": "需要人工操作",
                    "targets": ["#login"],
                    "timeout_ms": 5000,
                },
            )
        self.assertEqual(result["outcome"], "continued")
        request_help.assert_called_once()
        with self.assertRaises(JsonRpcError):
            self.application.rpc(
                "browser.policy.request_help",
                {
                    "session_id": "bsk-1",
                    "domain": "accounts.example",
                    "reason": "use password: private-secret",
                },
            )
        audit = str(self.application.storage.list_events(20))
        self.assertIn("browser.request_help", audit)
        self.assertNotIn("请在隔离窗口中完成登录", audit)
        self.assertNotIn("private-secret", audit)


if __name__ == "__main__":
    unittest.main()
