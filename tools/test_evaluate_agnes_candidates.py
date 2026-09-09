"""Agnes transport fixtures never use real keys or the network."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import evaluate_siliconflow_candidates as evaluate
from tools import test_evaluate_siliconflow_candidates as fixtures


class AgnesSanityTests(unittest.TestCase):
    respond = fixtures.SiliconFlowSanityTests.respond

    def setUp(self):
        fixtures.SiliconFlowSanityTests.setUp(self)
        sleep = patch.object(evaluate.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        self.models = [{"id": model} for model in evaluate.PROVIDERS["agnes"]["models"]]

    def run_suite(self, models=None):
        return evaluate.run_suite("offline-fixture-secret", models or [row["id"] for row in self.models],
                                  allow_confirmed_free_tests=True, provider="agnes")

    def test_bounded_agnes_models_and_sanitized_unknown_cash(self):
        report = self.run_suite()
        self.assertEqual(report["schema"], "agnes-candidate-sanity/v1")
        self.assertEqual(report["model_calls"], 6)
        self.assertTrue(all(candidate["passed"] for candidate in report["candidates"]))
        self.assertFalse(report["routing_qualified"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        self.assertEqual(self.sleep.call_count, 5)
        for request in self.requests:
            self.assertTrue(request.full_url.startswith("https://apihub.agnes-ai.com/v1/"))
            if request.method == "POST":
                payload = json.loads(request.data)
                self.assertIn(payload["model"], evaluate.PROVIDERS["agnes"]["models"])
                self.assertEqual(payload["max_tokens"], 1024)
        for forbidden in ("offline-fixture-secret", "Case_A7", "Compute", "messages"):
            self.assertNotIn(forbidden, json.dumps(report))

    def test_cross_provider_or_observed_only_model_rejected(self):
        for model in (evaluate.MODELS[0], "agnes-1.5-flash", "agnes-paid"):
            with self.assertRaises(ValueError):
                self.run_suite([model])
        self.factory.assert_not_called()

    def test_rate_limit_stops_both_models(self):
        def respond(request, **kwargs):
            if request.method == "POST":
                raise HTTPError(request.full_url, 429, "private", {}, io.BytesIO(b"private"))
            return self.respond(request, **kwargs)
        self.opener.open.side_effect = respond
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["http_status"], 429)

    def test_empty_answer_is_not_health_success(self):
        self.transform = lambda payload: {**payload, "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": " "}}]}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 2)
        self.assertTrue(all(not candidate["health_passed"] for candidate in report["candidates"]))

    def test_unknown_usage_does_not_repeat_questions(self):
        self.transform = lambda payload: {name: value for name, value in payload.items() if name != "usage"}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 2)
        self.assertTrue(all(not candidate["passed"] for candidate in report["candidates"]))

    def test_positive_charge_stops_batch(self):
        self.transform = lambda payload: {**payload, "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": 0.01}}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["failure_class"], "unexpected-reported-charge")


if __name__ == "__main__":
    unittest.main()
