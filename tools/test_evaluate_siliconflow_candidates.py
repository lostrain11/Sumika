"""Offline fixtures; no actual credentials or API calls."""
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from tools import evaluate_siliconflow_candidates as evaluate
from tools.test_evaluate_zhipu_candidates import Response


class SiliconFlowSanityTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.transform = lambda value: value
        self.models = [{"id": model} for model in evaluate.MODELS]
        self.chat_count = 0
        self.opener = Mock()
        self.opener.open.side_effect = self.respond
        factory = patch.object(evaluate, "build_opener", return_value=self.opener)
        self.factory = factory.start()
        self.addCleanup(factory.stop)

    def respond(self, request, **kwargs):
        self.requests.append(request)
        if request.method == "GET":
            return Response({"data": self.models}, request.full_url)
        content = ("42", '{"ok":true,"count":3}', "id=Case_A7-x9;status=done")[self.chat_count % 3]
        self.chat_count += 1
        model = json.loads(request.data)["model"]
        value = {"model": model, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                 "usage": {"prompt_tokens": 20, "completion_tokens": 8}}
        return Response(self.transform(value), request.full_url)

    def run_suite(self, models=None):
        return evaluate.run_suite("offline-fixture-secret", models or list(evaluate.MODELS), allow_confirmed_free_tests=True)

    def test_bounded_exact_models_no_fallback_and_unknown_cash_is_not_zero(self):
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 9)
        self.assertTrue(all(candidate["passed"] for candidate in report["candidates"]))
        self.assertFalse(report["routing_qualified"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        for request in self.requests[1:]:
            self.assertEqual(request.full_url, evaluate.BASE_URL + "/chat/completions")
            payload = json.loads(request.data)
            self.assertEqual(set(payload), {"model", "messages", "max_tokens", "stream"})
            self.assertIn(payload["model"], evaluate.MODELS)
            self.assertEqual(payload["max_tokens"], 1024)
        for forbidden in ("offline-fixture-secret", "Case_A7", "Compute", "messages"):
            self.assertNotIn(forbidden, json.dumps(report))

    def test_authorization_identity_and_credential_before_network(self):
        for models, authorized, key in (([evaluate.MODELS[0]], False, "fixture"), (["Pro/paid-model"], True, "fixture"),
                                       ([evaluate.MODELS[0]] * 2, True, "fixture"), ([evaluate.MODELS[0]], True, "bad\nkey")):
            with self.assertRaises(ValueError):
                evaluate.run_suite(key, models, allow_confirmed_free_tests=authorized)
        self.factory.assert_not_called()

    def test_catalog_missing_or_duplicate_prevents_probe(self):
        for rows in ([{"id": "unknown"}], [{"id": evaluate.MODELS[0]}] * 2):
            self.models = rows
            report = self.run_suite([evaluate.MODELS[0]])
            self.assertEqual(report["model_calls"], 0)
            self.assertEqual(report["candidates"][0]["failure_class"], "missing-or-duplicate-catalog-model")

    def test_failed_answers_are_health_evidence_not_quality_pass(self):
        self.transform = lambda payload: {**payload, "choices": [{"finish_reason": "length",
                        "message": {"role": "assistant", "content": "private-wrong"}}]}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 9)
        self.assertTrue(all(candidate["health_passed"] and not candidate["passed"] for candidate in report["candidates"]))
        self.assertNotIn("private-wrong", json.dumps(report))

    def test_unknown_usage_stops_each_model_without_retry_or_fake_zero(self):
        self.transform = lambda payload: {name: value for name, value in payload.items() if name != "usage"}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 3)
        self.assertTrue(all(not candidate["passed"] for candidate in report["candidates"]))
        self.assertTrue(all(candidate["checks"][0]["usage"] == {} for candidate in report["candidates"]))

    def test_unexpected_charge_stops_whole_batch(self):
        self.transform = lambda payload: {**payload, "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": 0.01}}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["failure_class"], "unexpected-reported-charge")

    def test_unexpected_model_stops_whole_batch(self):
        self.transform = lambda payload: {**payload, "model": "Pro/other-model"}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["failure_class"], "unexpected-model-identity")

    def test_authentication_failure_never_falls_back(self):
        self.opener.open.side_effect = HTTPError(evaluate.BASE_URL, 401, "private", {}, io.BytesIO(b"private"))
        report = self.run_suite()
        self.assertFalse(report["authenticated"])
        self.assertEqual(report["model_calls"], 0)
        self.assertNotIn("private", json.dumps(report))

    def test_rate_limit_and_timeout_do_not_resubmit_same_model(self):
        for error in (TimeoutError("private"), HTTPError(evaluate.BASE_URL, 429, "private", {}, io.BytesIO(b"private"))):
            def respond(request, **kwargs):
                if request.method == "POST":
                    raise error
                return self.respond(request, **kwargs)
            self.opener.open.side_effect = respond
            report = self.run_suite([evaluate.MODELS[0]])
            self.assertEqual(report["model_calls"], 1)
            self.assertEqual(len(report["candidates"][0]["checks"]), 1)
            self.assertNotIn("private", json.dumps(report))

    def test_remaining_checks_do_not_resend_first_question_or_claim_full_suite(self):
        self.chat_count = 1
        report = evaluate.run_suite("fixture", [evaluate.MODELS[0]], allow_confirmed_free_tests=True,
                                    check_ids=["json", "transform"])
        self.assertEqual(report["model_calls"], 2)
        self.assertEqual([record["check_id"] for record in report["candidates"][0]["checks"]], ["json", "transform"])
        self.assertTrue(report["candidates"][0]["selected_checks_passed"])
        self.assertFalse(report["candidates"][0]["passed"])

    def test_check_selection_is_validated_before_network(self):
        for checks in ([], ["unknown"], ["json", "json"]):
            with self.assertRaises(ValueError):
                evaluate.run_suite("fixture", [evaluate.MODELS[0]], allow_confirmed_free_tests=True, check_ids=checks)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
