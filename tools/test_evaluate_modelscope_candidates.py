"""Offline tests of ModelScope credit probes; never use real tokens."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import evaluate_siliconflow_candidates as evaluate
from tools import test_evaluate_siliconflow_candidates as fixtures


class ModelScopeSanityTests(unittest.TestCase):
    respond = fixtures.SiliconFlowSanityTests.respond

    def setUp(self):
        fixtures.SiliconFlowSanityTests.setUp(self)
        self.models = [{"id": model} for model in evaluate.PROVIDERS["modelscope"]["models"]]
        sleep = patch.object(evaluate.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def run_suite(self, models=None):
        return evaluate.run_suite("offline-private-token", models or [row["id"] for row in self.models],
                                  provider="modelscope", allow_confirmed_free_tests=True)

    def test_community_endpoint_and_bounded_calls_without_credit_or_routing_claim(self):
        report = self.run_suite()
        self.assertTrue(report["authenticated"])
        self.assertEqual(report["model_calls"], 9)
        self.assertTrue(all(candidate["passed"] for candidate in report["candidates"]))
        self.assertFalse(report["routing_qualified"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        self.assertIn("account-balance-unverified", report["price_evidence"])
        for request in self.requests:
            self.assertTrue(request.full_url.startswith("https://api-inference.modelscope.cn/v1/"))
            if request.method == "POST":
                payload = json.loads(request.data)
                self.assertEqual(payload["max_tokens"], 1024)
                self.assertIn(payload["model"], evaluate.PROVIDERS["modelscope"]["models"])
                self.assertEqual(set(payload), {"model", "messages", "max_tokens", "stream"})
        for forbidden in ("offline-private-token", "Case_A7", "messages", "Cookie"):
            self.assertNotIn(forbidden, json.dumps(report))

    def test_public_catalog_does_not_authenticate_or_bypass_account_restrictions(self):
        for status in (401, 402, 403, 429):
            def respond(request, **kwargs):
                if request.method == "POST":
                    raise HTTPError(request.full_url, status, "private", {}, io.BytesIO(b"private"))
                return self.respond(request, **kwargs)
            self.opener.open.side_effect = respond
            report = self.run_suite()
            self.assertFalse(report["authenticated"])
            self.assertEqual(report["model_calls"], 1)
            self.assertEqual(report["candidates"][0]["checks"][0]["http_status"], status)
            self.assertNotIn("private", json.dumps(report))

    def test_cross_provider_or_unobserved_model_rejected_before_network(self):
        for model in ("deepseek-v4-flash", "Qwen/Qwen2.5-72B-Instruct", evaluate.MODELS[0]):
            with self.assertRaises(ValueError):
                self.run_suite([model])
        self.factory.assert_not_called()

    def test_charged_response_stops_without_spending_more_credits(self):
        self.transform = lambda value: {**value, "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": 0.01}}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["failure_class"], "unexpected-reported-charge")

    def test_unknown_submission_is_not_retried(self):
        def respond(request, **kwargs):
            if request.method == "POST":
                raise TimeoutError("private")
            return self.respond(request, **kwargs)
        self.opener.open.side_effect = respond
        report = self.run_suite([self.models[0]["id"]])
        self.assertEqual(report["model_calls"], 1)
        self.assertFalse(report["authenticated"])
        self.assertNotIn("private", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
