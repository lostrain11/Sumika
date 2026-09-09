"""Ollama Cloud free-plan boundaries with isolated transport fixtures."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import evaluate_siliconflow_candidates as evaluate
from tools import test_evaluate_siliconflow_candidates as fixtures


class OllamaCloudSanityTests(unittest.TestCase):
    respond = fixtures.SiliconFlowSanityTests.respond

    def setUp(self):
        fixtures.SiliconFlowSanityTests.setUp(self)
        self.models = [{"id": model} for model in evaluate.PROVIDERS["ollama-cloud"]["models"]]
        sleep = patch.object(evaluate.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def run_suite(self, models=None):
        return evaluate.run_suite("offline-private-key", models or [self.models[0]["id"]],
                                  provider="ollama-cloud", allow_confirmed_free_tests=True)

    def test_exact_provider_bounded_tests_without_free_price_or_routing_claims(self):
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 3)
        self.assertTrue(report["authenticated"])
        self.assertTrue(report["candidates"][0]["passed"])
        self.assertFalse(report["routing_qualified"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        self.assertIn("not-zero-unit-price", report["price_evidence"])
        for request in self.requests:
            self.assertTrue(request.full_url.startswith("https://ollama.com/v1/"))
            if request.method == "POST":
                payload = json.loads(request.data)
                self.assertEqual(payload["model"], "gpt-oss:20b")
                self.assertEqual(payload["max_tokens"], 1024)
        self.assertNotIn("offline-private-key", json.dumps(report))

    def test_public_catalog_is_not_authentication_or_plan_entitlement(self):
        for status in (401, 402, 403, 429):
            def respond(request, **kwargs):
                if request.method == "POST":
                    raise HTTPError(request.full_url, status, "private", {}, io.BytesIO(b"private"))
                return self.respond(request, **kwargs)
            self.opener.open.side_effect = respond
            report = self.run_suite([row["id"] for row in self.models])
            self.assertFalse(report["authenticated"])
            self.assertEqual(report["model_calls"], 1)
            self.assertEqual(report["candidates"][0]["checks"][0]["http_status"], status)
            self.assertFalse(report["routing_qualified"])
            self.assertNotIn("private", json.dumps(report))

    def test_unregistered_and_cross_provider_models_rejected_before_network(self):
        for model in ("kimi-k3", "gpt-oss:20b-cloud", evaluate.MODELS[0]):
            with self.assertRaises(ValueError):
                self.run_suite([model])
        self.factory.assert_not_called()

    def test_timeout_stops_candidate_without_replaying(self):
        def respond(request, **kwargs):
            if request.method == "POST":
                raise TimeoutError("private")
            return self.respond(request, **kwargs)
        self.opener.open.side_effect = respond
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertFalse(report["authenticated"])
        self.assertNotIn("private", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
