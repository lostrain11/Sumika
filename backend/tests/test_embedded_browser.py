import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from sumika_core.embedded_browser import EmbeddedBrowserBridge, EmbeddedBenefitsReader, NATIVE_BROWSER, fixed_account_read_reason


class EmbeddedBrowserTests(unittest.TestCase):
    def setUp(self):
        self.bridge = EmbeddedBrowserBridge()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown)
        self.addCleanup(self.bridge.close)
        self.token = self.bridge.attach()["token"]

    def take_request(self):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            result = self.bridge.poll(self.token)["request"]
            if result:
                return result
            time.sleep(0.005)
        self.fail("request not queued")

    def test_read_is_bound_to_fixed_page_and_projects_only_account_facts(self):
        pending = self.pool.submit(self.bridge.read_portal, "modelscope", NATIVE_BROWSER, threading.Event())
        request = self.take_request()
        self.assertEqual(request["url"], "https://modelscope.cn/magicube/usage")
        self.assertEqual(request["action"], "read-account")
        self.bridge.complete(self.token, request["attempt_id"], {"state": "verified", "unit": "magicube", "available_balance": 242,
            "grants": [{"kind": "daily-login", "amount": 200, "granted_date_display": "2026-09-08", "validity_days_display": 1}],
            "body": "discard this page content", "routing_eligible": True})
        result = pending.result(1)
        self.assertEqual(result["available_balance"], 242)
        self.assertFalse(result["routing_eligible"])
        self.assertNotIn("body", result)
        self.assertFalse(self.bridge.complete(self.token, request["attempt_id"], {})["accepted"])

    def test_takeover_same_page_cannot_start_another_reader(self):
        pending = self.pool.submit(self.bridge.read_portal, "ollama", NATIVE_BROWSER, threading.Event())
        request = self.take_request()
        other = self.bridge.read_portal("ollama", NATIVE_BROWSER, threading.Event())
        self.assertEqual(other["quality"]["state"], "takeover")
        self.bridge.complete(self.token, request["attempt_id"], {"state": "login-required"})
        self.assertEqual(pending.result(1)["quality"]["state"], "login-required")

    def test_fixed_reason_projection_is_source_specific_and_never_coerces_page_content(self):
        self.assertEqual(fixed_account_read_reason("modelscope", "missing-records-tabs"), "missing-records-tabs")
        self.assertEqual(fixed_account_read_reason("moark", "official-log-forbidden"), "official-log-forbidden")
        for source, reason in (("modelscope", "official-log-forbidden"), ("moark", "invalid-grant-row"),
                               ("other", "missing-records-tabs"), ("modelscope", None), ("moark", []),
                               ("modelscope", {"reason": "missing-records-tabs"}), ("moark", 401),
                               ("modelscope", "private-page-content"), ("moark", "official-log-forbidden private-details")):
            with self.subTest(source=source, reason=reason):
                self.assertIsNone(fixed_account_read_reason(source, reason))

    def test_modelscope_failure_keeps_fixed_reason_without_balance_or_page_body(self):
        for reason in ("missing-records-tabs", "invalid-grant-row", "ambiguous-records-tab"):
            pending = self.pool.submit(self.bridge.read_portal, "modelscope", NATIVE_BROWSER, threading.Event())
            request = self.take_request()
            self.bridge.complete(self.token, request["attempt_id"], {"state": "needs-review", "reason": reason,
                "body": "private-page-content", "available_balance": 999, "unit": "magicube"})
            result = pending.result(1)
            self.assertEqual(result["quality"], {"state": "needs-review", "blocking_reason": reason})
            self.assertIsNone(result["available_balance"])
            self.assertFalse(result["routing_eligible"])
            self.assertEqual(result["grants"], [])
            self.assertNotIn("private", json.dumps(result))

    def test_native_failure_drops_unknown_reason_text_and_does_not_infer_login(self):
        for source in ("modelscope", "moark"):
            for reason in ("private-page-content", {"private": "body"}, ["missing-records-tabs"], None):
                pending = self.pool.submit(self.bridge.read_portal, source, NATIVE_BROWSER, threading.Event())
                request = self.take_request()
                self.bridge.complete(self.token, request["attempt_id"], {"state": "needs-review", "reason": reason,
                    "error": "private-exception-text"})
                result = pending.result(1)
                expected = "native-portal-read-failed" if source == "modelscope" else "official-receipts-unavailable"
                self.assertEqual(result["quality"]["blocking_reason"] if source == "modelscope" else result["reason"], expected)
                self.assertNotIn("private", json.dumps(result))
                self.assertNotIn("login", json.dumps(result))

    def test_native_receipt_failure_keeps_permission_timeout_and_parser_codes_only(self):
        for reason in ("official-log-forbidden", "official-log-auth-rejected", "official-log-read-timeout",
                       "invalid-log-schema", "invalid-receipt-identity", "profile-resource-unavailable"):
            pending = self.pool.submit(self.bridge.read_receipts, "moark", NATIVE_BROWSER, threading.Event())
            request = self.take_request()
            self.bridge.complete(self.token, request["attempt_id"], {"state": "needs-review", "reason": reason,
                "receipts": [{"private": "partial-body"}], "error": "private-exception"})
            self.assertEqual(pending.result(1), {"state": "needs-review", "reason": reason})

    def test_failure_payload_with_key_is_rejected_without_retaining_it(self):
        pending = self.pool.submit(self.bridge.read_portal, "modelscope", NATIVE_BROWSER, threading.Event())
        request = self.take_request()
        with self.assertRaises(ValueError):
            self.bridge.complete(self.token, request["attempt_id"], {"state": "needs-review",
                "reason": "invalid-grant-row", "api_key": "sk-" + "a" * 48})
        self.bridge.complete(self.token, request["attempt_id"], {"state": "needs-review", "reason": "invalid-grant-row"})
        self.assertNotIn("sk-", json.dumps(pending.result(1)))
        self.assertNotIn("api_key", json.dumps(self.bridge.status()))

    def test_closed_bridge_wakes_waiter_and_rejects_new_commands(self):
        pending = self.pool.submit(self.bridge.read_portal, "ollama", NATIVE_BROWSER, threading.Event())
        self.take_request()
        self.bridge.close()
        self.assertEqual(pending.result(1)["quality"]["state"], "interrupted")
        with self.assertRaises(ValueError):
            self.bridge.poll(self.token)

    def test_timeout_does_not_requeue_or_replay(self):
        pending = self.pool.submit(self.bridge.read_portal, "ollama", NATIVE_BROWSER, threading.Event(), timeout=0.04)
        request = self.take_request()
        self.assertEqual(pending.result(1)["quality"]["state"], "needs-review")
        self.assertIsNone(self.bridge.poll(self.token)["request"])
        self.assertFalse(self.bridge.complete(self.token, request["attempt_id"], {})["accepted"])

    def test_different_token_and_unregistered_source_rejected(self):
        with self.assertRaises(ValueError):
            self.bridge.poll("other")
        with self.assertRaises(ValueError):
            self.bridge.read_portal("arbitrary-url", NATIVE_BROWSER, threading.Event())
        self.assertNotIn("token", self.bridge.status())

    def test_legacy_binding_keeps_its_reader_without_silent_login_migration(self):
        calls = []
        legacy = SimpleNamespace(browsers=lambda: [{"instance_id": "legacy"}], read=lambda *args: calls.append(args) or {"state": "verified"})
        reader = EmbeddedBenefitsReader(self.bridge, legacy)
        self.assertEqual([row["instance_id"] for row in reader.browsers()], [NATIVE_BROWSER, "legacy"])
        self.assertEqual(reader.read("legacy", threading.Event())["state"], "verified")
        self.assertEqual(len(calls), 1)

    def test_native_message_cancel_revokes_delivery_and_cannot_replay(self):
        cancelled = threading.Event()
        profile = {"tab_id": "chat-test", "account_id": "account-test", "chat_url": "https://chatgpt.com/", "site_key": "chatgpt",
                   "automation_supported": True, "auto_chat_enabled": True, "allowed_actions": ["chat.send"], "budget_policy": "no-paid"}
        pending = self.pool.submit(self.bridge.exchange, "send", profile, text="synthetic fixture", attempt_id="message-once", cancelled=cancelled)
        request = self.take_request()
        self.assertTrue(self.bridge.alive(self.token, request["attempt_id"])["active"])
        self.assertNotIn("text", self.bridge.status()["requests"][0])
        cancelled.set()
        self.assertEqual(pending.result(1)["status"], "unknown")
        self.assertFalse(self.bridge.alive(self.token, request["attempt_id"])["active"])
        self.assertIsNone(self.bridge.poll(self.token)["request"])

    def test_desktop_maintenance_requires_explicit_native_binding_without_external_browser_calls(self):
        def forbidden(*args):
            self.fail("desktop must not call the external browser")
        reader = EmbeddedBenefitsReader(self.bridge, SimpleNamespace(browsers=forbidden, read=forbidden), native_required=True)
        self.assertEqual([row["instance_id"] for row in reader.browsers()], [NATIVE_BROWSER])
        self.assertEqual(reader.read("legacy", threading.Event())["reason"], "bind-native-browser-and-login-required")

    def test_native_receipts_project_exact_evidence_and_do_not_accept_unbounded_rows(self):
        pending = self.pool.submit(self.bridge.read_receipts, "moark", NATIVE_BROWSER, threading.Event())
        request = self.take_request()
        self.assertEqual(request["action"], "read-receipts")
        receipt = {"evidence_id": "a" * 64, "trace_fingerprint": "b" * 64, "package_fingerprint": "c" * 64,
                   "model_id": "fixture", "amount": "0.0000001", "unit": "CNY", "charge_source": "resource-package", "finalized": True}
        with self.assertRaises(ValueError):
            self.bridge.complete(self.token, request["attempt_id"], {"state": "verified", "extra": "x" * 32001})
        self.bridge.complete(self.token, request["attempt_id"], {"schema": "moark-receipts/v1",
            "source_url": "https://moark.com/api/base/{account}/inference-logs", "state": "verified", "receipts": [receipt]})
        result = pending.result(1)
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["receipts"][0]["amount"], "0.0000001")

    def test_native_exchange_does_not_accept_mismatched_message_result(self):
        profile = {"tab_id": "chat-test", "account_id": "account-test", "chat_url": "https://chatgpt.com/", "site_key": "chatgpt",
                   "automation_supported": True, "auto_chat_enabled": True, "allowed_actions": ["chat.send"], "budget_policy": "no-paid"}
        pending = self.pool.submit(self.bridge.exchange, "send", profile, text="synthetic fixture", attempt_id="message-once")
        request = self.take_request()
        with self.assertRaises(ValueError):
            self.bridge.complete(self.token, request["attempt_id"], {"status": "completed", "sent": True, "text": "fixture", "attempt_id": "wrong-attempt"})
        self.bridge.complete(self.token, request["attempt_id"], {"status": "completed", "sent": True, "text": "fixture", "attempt_id": "message-once"})
        self.assertEqual(pending.result(1)["text"], "fixture")


if __name__ == "__main__":
    unittest.main()
