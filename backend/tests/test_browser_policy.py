import unittest

from sumika_core.browser.policy import (
    BrowserPolicyError,
    BrowserPolicyEvaluator,
    classify_target,
    domain_from_url,
    normalize_domain,
)
from sumika_core.browser.runtime import BrowserRuntime, BrowserRuntimeError, BrowserSkillClient


def metadata(**overrides):
    value = {
        "tool_name": "browser_snapshot",
        "action": "snapshot",
        "session_id": "bsk-1",
        "domain": "example.com",
        "current_domain": "example.com",
        "target_kind": "none",
        "value_length": 0,
        "sensitive": False,
        "session_known": True,
        "new_tab": False,
    }
    value.update(overrides)
    return value


class BrowserPolicyTests(unittest.TestCase):
    def test_domains_and_urls_are_normalized_without_paths_or_credentials(self):
        self.assertEqual(normalize_domain("Example.COM."), "example.com")
        self.assertEqual(normalize_domain("[::1]"), "::1")
        self.assertEqual(domain_from_url("https://Example.COM/a?token=hidden"), ("example.com", False))
        self.assertEqual(domain_from_url("chrome://newtab/"), (None, True))
        with self.assertRaises(BrowserPolicyError):
            normalize_domain("https://example.com/path")
        with self.assertRaises(BrowserPolicyError):
            domain_from_url("https://user:secret@example.com/")

    def test_target_classification_does_not_retain_target_text(self):
        self.assertEqual(classify_target("@e12"), "snapshot_ref")
        self.assertEqual(classify_target("#password"), "css_selector")
        self.assertEqual(classify_target("role=button"), "unknown")
        self.assertEqual(classify_target(None), "none")

    def test_read_only_known_domain_is_allowed(self):
        result = BrowserPolicyEvaluator().evaluate(metadata())
        self.assertEqual(result["decision"], "allow")
        self.assertFalse(result["requires_human"])

    def test_unknown_session_fails_closed(self):
        result = BrowserPolicyEvaluator().evaluate(metadata(session_known=False))
        self.assertEqual(result["decision"], "deny")
        self.assertIn("会话", result["reason"])

    def test_first_and_cross_domain_navigation_need_approval(self):
        first = BrowserPolicyEvaluator().evaluate(
            metadata(
                tool_name="browser_navigate",
                action="navigate",
                current_domain=None,
                domain="example.com",
            )
        )
        self.assertEqual(first["decision"], "ask")
        cross = BrowserPolicyEvaluator().evaluate(
            metadata(
                tool_name="browser_navigate",
                action="navigate",
                current_domain="example.com",
                domain="other.example",
            )
        )
        self.assertEqual(cross["decision"], "ask")
        same = BrowserPolicyEvaluator().evaluate(
            metadata(
                tool_name="browser_navigate",
                action="navigate",
                current_domain="example.com",
                domain="example.com",
            )
        )
        self.assertEqual(same["decision"], "allow")

    def test_writes_are_approval_gated_and_sensitive_fill_is_human_only(self):
        click = BrowserPolicyEvaluator().evaluate(
            metadata(tool_name="browser_click", action="click", target_kind="snapshot_ref")
        )
        self.assertEqual(click["decision"], "ask")
        sensitive = BrowserPolicyEvaluator().evaluate(
            metadata(
                tool_name="browser_fill",
                action="fill",
                target_kind="css_selector",
                sensitive=True,
                value_length=12,
            )
        )
        self.assertEqual(sensitive["decision"], "deny")
        self.assertTrue(sensitive["requires_human"])

    def test_blank_session_and_request_help_are_safe_special_cases(self):
        blank = BrowserPolicyEvaluator().evaluate(
            {
                "tool_name": "browser_session_start",
                "action": "session_start",
                "session_id": None,
                "domain": None,
                "current_domain": None,
                "target_kind": "none",
                "value_length": 0,
                "sensitive": False,
                "session_known": False,
                "new_tab": True,
            }
        )
        self.assertEqual(blank["decision"], "allow")
        help_result = BrowserPolicyEvaluator().evaluate(
            metadata(
                tool_name="browser_request_help",
                action="request_help",
                target_kind="none",
            )
        )
        self.assertEqual(help_result["decision"], "allow")

    def test_disabled_runtime_and_unknown_fields_are_explicit(self):
        disabled = BrowserPolicyEvaluator(enabled=False).evaluate(metadata())
        self.assertEqual(disabled["decision"], "deny")
        with self.assertRaises(BrowserPolicyError):
            BrowserPolicyEvaluator().evaluate(metadata(secret_value="must-not-cross"))

    def test_external_help_forwards_only_to_browserskill_and_returns_redacted_status(self):
        calls = []

        def runner(args):
            calls.append(args)
            return {"outcome": "continued", "note": "private page note"}

        runtime = BrowserRuntime(browser_skill=BrowserSkillClient("bsk", runner=runner))
        result = runtime.request_external_help(
            session_id="bsk-1",
            domain="accounts.example",
            reason="Complete the login in the isolated window",
            targets=["#login"],
        )
        self.assertEqual(result["outcome"], "continued")
        self.assertNotIn("note", result)
        self.assertIn(("request-help", "--session", "bsk-1", "--prompt", "Complete the login in the isolated window", "--target", "#login"), calls)
        with self.assertRaises(BrowserRuntimeError):
            runtime.request_external_help(
                session_id="bsk-1",
                domain="accounts.example",
                reason="password: private-secret",
            )


if __name__ == "__main__":
    unittest.main()
