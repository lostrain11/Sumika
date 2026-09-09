"""Offline fixtures; never read credentials or send real requests."""
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from tools import evaluate_openrouter_candidates as evaluate
from tools.test_evaluate_zhipu_candidates import Response


class OpenRouterSanityTests(unittest.TestCase):
    def setUp(self):
        self.model = evaluate.CANDIDATES[0]
        self.requests = []
        self.chat_count = 0
        self.transform = lambda value: value
        self.opener = Mock()
        self.opener.open.side_effect = self.respond
        factory = patch.object(evaluate, "build_opener", return_value=self.opener)
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        catalog = patch.object(evaluate, "fetch_catalog", return_value={"observed_at": "fixture",
                                "models": [{"model_id": model} for model in evaluate.CANDIDATES]})
        self.catalog = catalog.start()
        self.addCleanup(catalog.stop)

    def respond(self, request, **kwargs):
        self.requests.append(request)
        if request.method == "GET":
            return Response({"data": {"is_management_key": False, "is_free_tier": True, "label": "private"}}, request.full_url)
        answers = ("42", '{"ok":true,"count":3}', "id=Case_A7-x9;status=done")
        content = answers[self.chat_count % 3]
        self.chat_count += 1
        model = json.loads(request.data)["model"]
        value = {"model": model.removesuffix(":free"), "choices": [{"finish_reason": "stop",
                 "message": {"role": "assistant", "content": content}}],
                 "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": 0}}
        return Response(self.transform(value), request.full_url)

    def run_suite(self, models=None):
        return evaluate.run_suite("fixture-secret", models or [self.model], allow_free_tests=True)

    def test_three_fixed_checks_use_only_explicit_zero_price_routes(self):
        report = self.run_suite(list(evaluate.CANDIDATES))
        self.assertEqual(report["model_calls"], 9)
        self.assertTrue(all(candidate["passed"] for candidate in report["candidates"]))
        self.assertFalse(report["routing_qualified"])
        self.assertIsNone(report["free_requests_remaining"])
        for request in self.requests[1:]:
            body = json.loads(request.data)
            self.assertTrue(body["model"].endswith(":free"))
            self.assertEqual(body["provider"], {"max_price": {"prompt": 0, "completion": 0},
                                              "allow_fallbacks": False, "require_parameters": True})
            self.assertNotIn("models", body)
            self.assertNotIn("plugins", body)
            self.assertEqual(body["max_tokens"], 1024)
        for forbidden in ("fixture-secret", "private", "Case_A7", "Compute", "messages"):
            self.assertNotIn(forbidden, json.dumps(report))

    def test_no_authorization_paid_model_duplicate_or_bad_key_never_uses_network(self):
        for models, authorized, key in (([self.model], False, "fixture"), (["vendor/paid"], True, "fixture"),
                                       ([self.model, self.model], True, "fixture"), ([self.model], True, "bad\nkey")):
            with self.assertRaises(ValueError):
                evaluate.run_suite(key, models, allow_free_tests=authorized)
        self.factory.assert_not_called()
        self.catalog.assert_not_called()

    def test_current_catalog_must_still_declare_free(self):
        self.catalog.return_value["models"] = []
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["candidates"][0]["failure_class"], "not-in-current-free-catalog")

    def test_auth_failure_never_queries_catalog_or_sends_chat(self):
        self.opener.open.side_effect = HTTPError(evaluate.BASE_URL + "/key", 401, "private", {}, io.BytesIO(b"private"))
        report = self.run_suite()
        self.assertFalse(report["authenticated"])
        self.assertEqual(report["http_status"], 401)
        self.catalog.assert_not_called()
        self.assertEqual(report["model_calls"], 0)

    def test_unknown_or_positive_cost_stops_entire_batch(self):
        for value in (None, 0.01, "NaN", True, -1):
            with self.subTest(value=value):
                self.chat_count = 0
                self.transform = lambda payload: {**payload, "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": value}}
                report = self.run_suite(list(evaluate.CANDIDATES))
                self.assertEqual(report["model_calls"], 1)
                self.assertEqual(report["candidates"][0]["checks"][0]["failure_class"], "identity-usage-or-free-cost-unconfirmed")

    def test_response_from_different_model_stops(self):
        self.transform = lambda payload: {**payload, "model": "vendor/other"}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertFalse(report["candidates"][0]["passed"])

    def test_incorrect_answer_is_not_a_connection_failure(self):
        self.transform = lambda payload: {**payload, "choices": [{"finish_reason": "stop",
                        "message": {"role": "assistant", "content": "wrong"}}]}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertTrue(report["candidates"][0]["health_passed"])
        self.assertFalse(report["candidates"][0]["passed"])

    def test_timeout_and_rate_limit_are_never_retried(self):
        original = self.respond
        for error in (TimeoutError("private"), HTTPError(evaluate.BASE_URL, 429, "private", {}, io.BytesIO(b"private"))):
            with self.subTest(error=type(error).__name__):
                def respond(request, **kwargs):
                    if request.method == "POST":
                        raise error
                    return original(request, **kwargs)
                self.opener.open.side_effect = respond
                report = self.run_suite(list(evaluate.CANDIDATES))
                self.assertEqual(report["model_calls"], 1)
                self.assertEqual(len(report["candidates"]), 1)
                self.assertNotIn("private", json.dumps(report))

    def test_privacy_error_is_sanitized_and_stops_batch(self):
        def respond(request, **kwargs):
            if request.method == "POST":
                raise HTTPError(request.full_url, 404, "private", {}, io.BytesIO(json.dumps({
                    "error": {"message": "No endpoints for your data policy. private"}}).encode()))
            return self.respond(request, **kwargs)
        self.opener.open.side_effect = respond
        report = self.run_suite(list(evaluate.CANDIDATES))
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["failure_class"], "privacy-policy-no-endpoint")
        self.assertNotIn("private", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
