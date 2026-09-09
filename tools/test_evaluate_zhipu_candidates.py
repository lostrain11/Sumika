"""Offline mocks only: no real vault reads, provider requests, or Core startup."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from tools import evaluate_zhipu_candidates as evaluate


KEY = "offline-fixture-key"
ANSWERS = ("42", '{"ok":true,"count":3}', "id=Case_A7-x9;status=done")


class Response(io.BytesIO):
    def __init__(self, value, url, *, status=200, headers=None):
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.url = url
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}

    def geturl(self):
        return self.url


class CandidateSanityTests(unittest.TestCase):
    def test_http_diagnostics_keep_only_bounded_code_and_category(self):
        error = HTTPError(evaluate.BASE_URL, 429, "private", {}, io.BytesIO(json.dumps({
            "error": {"code": "1302", "message": "\u5e76\u53d1\u9650\u5236 private credential"}}).encode()))
        self.assertEqual(evaluate._safe_error_metadata(error), ("1302", "concurrency-limit"))
        error.close()
        invalid = HTTPError(evaluate.BASE_URL, 429, "private", {}, io.BytesIO(json.dumps({
            "error": {"code": KEY, "message": KEY}}).encode()))
        self.assertEqual(evaluate._safe_error_metadata(invalid), (None, None))
        invalid.close()

    def test_explicit_chat_probe_only_after_missing_catalog(self):
        original = self.opener.open.side_effect
        def request(request, **kwargs):
            if request.method == "GET":
                raise HTTPError(request.full_url, 404, "missing", {}, None)
            return original(request, **kwargs)
        self.opener.open.side_effect = request
        report = evaluate.run_sanity_suite(KEY, self.model, allow_paid=True, allow_chat_health=True)
        self.assertTrue(report["passed"])
        self.assertEqual(report["health"]["source"], "explicit-chat-probe")
        self.assertEqual(self.chat_count, 3)

    def test_chat_health_does_not_bypass_auth_failure(self):
        self.opener.open.side_effect = HTTPError(evaluate.BASE_URL + "/models", 401, "unauthorized", {}, None)
        report = evaluate.run_sanity_suite(KEY, self.model, allow_paid=True, allow_chat_health=True)
        self.assertFalse(report["passed"])
        self.assertEqual(report["health"]["http_status"], 401)
        self.assertEqual(self.chat_count, 0)

    def setUp(self):
        self.factory_patch = patch.object(evaluate, "build_opener")
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.vault_patch = patch.object(evaluate, "WindowsCredentialStore")
        self.vault = self.vault_patch.start()
        self.addCleanup(self.vault_patch.stop)
        self.opener = self.factory.return_value
        self.requests = []
        self.model = evaluate.ALLOWED_MODELS[0]
        self.chat_count = 0
        self.response_transform = lambda payload: payload
        self.opener.open.side_effect = self.respond

    def respond(self, request, *, timeout):
        self.requests.append(request)
        self.assertEqual(timeout, 30)
        if request.method == "GET":
            return Response({"data": [{"id": self.model}]}, request.full_url)
        content = ANSWERS[self.chat_count]
        self.chat_count += 1
        payload = {"model": self.model, "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}
        return Response(self.response_transform(payload), request.full_url)

    def run_suite(self):
        return evaluate.run_sanity_suite(KEY, self.model, allow_paid=True)

    def test_both_models_run_exactly_one_get_and_three_distinct_short_questions(self):
        for model in evaluate.ALLOWED_MODELS:
            with self.subTest(model=model):
                self.model, self.chat_count, self.requests = model, 0, []
                result = self.run_suite()
                self.assertTrue(result["passed"])
                self.assertTrue(result["health"]["passed"])
                self.assertTrue(result["usage_complete"])
                self.assertEqual([request.method for request in self.requests], ["GET", "POST", "POST", "POST"])
                self.assertEqual(self.requests[0].full_url, evaluate.BASE_URL + "/models")
                prompts = []
                for request in self.requests[1:]:
                    self.assertEqual(request.full_url, evaluate.BASE_URL + "/chat/completions")
                    payload = json.loads(request.data)
                    self.assertEqual(set(payload), {"model", "messages", "max_tokens", "stream"})
                    self.assertEqual(payload["model"], model)
                    self.assertEqual(payload["max_tokens"], 1024)
                    self.assertFalse(payload["stream"])
                    self.assertEqual(len(payload["messages"]), 1)
                    prompts.append(payload["messages"][0]["content"])
                    self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
                self.assertEqual(len(set(prompts)), 3)
                self.assertTrue(all(len(prompt) < 300 for prompt in prompts))
                self.assertTrue(all(item["latency_ms"] >= 0 for item in result["checks"]))
                self.assertTrue(all(item["finish_reason"] == "stop" for item in result["checks"]))

    def test_report_never_promotes_unknown_version_or_invents_prices_effort(self):
        result = self.run_suite()
        self.assertIsNone(result["model_version"])
        self.assertIsNone(result["estimated_cash_cny"])
        self.assertIsNone(result["actual_billed_cash_cny"])
        self.assertIn("not complex-task, leader, role, or routing qualification", result["scope"])
        for check in result["checks"]:
            self.assertIsNone(check["applied_reasoning_effort"])
            self.assertEqual(set(check), {"check_id", "passed", "usage", "latency_ms", "finish_reason", "applied_reasoning_effort"})
        serialized = json.dumps(result)
        for forbidden in (KEY, ANSWERS[2], "Compute", "messages", "reasoning_content", "routable", "quality_tier"):
            self.assertNotIn(forbidden, serialized)

    def test_authorization_and_model_are_checked_before_any_request(self):
        for model, authorized in ((self.model, False), ("glm-4.7-flashx", True), ("glm-4.5-flash", True), ("glm-5.3-flash", True)):
            with self.subTest(model=model, authorized=authorized), self.assertRaises(ValueError):
                evaluate.run_sanity_suite(KEY, model, allow_paid=authorized)
        self.factory.assert_not_called()

    def test_bad_credentials_are_rejected_without_network(self):
        for key in ("", "x" * 513, "key\nvalue", "key with space", None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate.run_sanity_suite(key, self.model, allow_paid=True)
        self.factory.assert_not_called()

    def test_health_failure_or_missing_exact_model_stops_without_chat_probe(self):
        for rows in ([], [{"id": "glm-4.7-flashx"}], [{"id": self.model}, {"id": self.model}], None):
            with self.subTest(rows=rows):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = lambda request, **kwargs: Response({"data": rows}, request.full_url)
                result = self.run_suite()
                self.assertFalse(result["passed"])
                self.assertFalse(result["health"]["passed"])
                self.assertEqual(result["checks"], [])
                self.assertEqual(self.opener.open.call_count, 1)

    def test_health_http_failures_do_not_fall_back_to_chat(self):
        for code in (401, 404, 405, 429, 500):
            with self.subTest(code=code):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = HTTPError(evaluate.BASE_URL + "/models", code, "sensitive-error", {}, io.BytesIO(b"secret-html"))
                result = self.run_suite()
                self.assertFalse(result["health"]["passed"])
                self.assertEqual(result["checks"], [])
                self.assertEqual(self.opener.open.call_count, 1)
                self.assertNotIn("sensitive", json.dumps(result))

    def test_failed_unknown_or_truncated_answers_stop_without_retry(self):
        for finish, content in (("stop", "wrong-sensitive-answer"), ("length", "42"), (None, "42"), ("content_filter", "42"), ("tool_calls", "42")):
            with self.subTest(finish=finish):
                self.chat_count, self.requests = 0, []
                def transform(payload):
                    payload["choices"][0]["finish_reason"] = finish
                    payload["choices"][0]["message"]["content"] = content
                    return payload
                self.response_transform = transform
                result = self.run_suite()
                self.assertFalse(result["passed"])
                self.assertEqual(len(self.requests), 2)
                self.assertEqual(len(result["checks"]), 1)
                self.assertFalse(result["checks"][0]["passed"])
                self.assertNotIn("sensitive", json.dumps(result))

    def test_timeout_or_unknown_submission_never_resubmits(self):
        for error in (TimeoutError("sensitive-timeout"), URLError("sensitive-url"), ConnectionResetError("sensitive-error")):
            with self.subTest(error=type(error).__name__):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = [Response({"data": [{"id": self.model}]}, evaluate.BASE_URL + "/models"), error]
                result = self.run_suite()
                self.assertFalse(result["passed"])
                self.assertEqual(self.opener.open.call_count, 2)
                self.assertEqual(len(result["checks"]), 1)
                self.assertFalse(result["checks"][0]["passed"])
                self.assertNotIn("sensitive", json.dumps(result))

    def test_unknown_usage_stops_without_fabricating_zero(self):
        def transform(payload):
            payload.pop("usage")
            return payload
        self.response_transform = transform
        result = self.run_suite()
        self.assertFalse(result["passed"])
        self.assertFalse(result["usage_complete"])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result["checks"][0]["usage"], {})

    def test_json_contract_checks_types_exact_keys_and_duplicate_keys(self):
        for content in ('{"ok":true,"count":3}', '{"count":3,"ok":true}'):
            self.assertTrue(evaluate._matches("json", content))
        for content in ('{"ok":1,"count":3}', '{"ok":true,"count":3.0}', '{"ok":true,"count":3,"extra":0}',
                        '{"ok":true,"count":1,"count":3}', '```json\n{"ok":true,"count":3}\n```', '{"ok":true,"count":NaN}'):
            self.assertFalse(evaluate._matches("json", content))
        self.assertFalse(evaluate._matches("arithmetic", "The answer is 42"))
        self.assertFalse(evaluate._matches("transform", "id=case_a7-x9;status=done"))

    def test_third_question_failure_preserves_previous_checks_without_retry(self):
        def transform(payload):
            if self.chat_count == 3:
                payload["choices"][0]["message"]["content"] = "id=changed;status=done"
            return payload
        self.response_transform = transform
        result = self.run_suite()
        self.assertFalse(result["passed"])
        self.assertEqual([item["passed"] for item in result["checks"]], [True, True, False])
        self.assertTrue(result["usage_complete"])
        self.assertEqual(len(self.requests), 4)

    def test_usage_and_effort_are_allowlisted_not_copied_from_untrusted_text(self):
        def transform(payload):
            payload["applied_reasoning_effort"] = "high"
            payload["reasoning_effort"] = "low"
            payload["usage"]["private-key"] = KEY
            payload["usage"]["prompt_tokens_details"] = {"cached_tokens": 2, "secret": KEY}
            payload["usage"]["completion_tokens_details"] = {"reasoning_tokens": 1}
            return payload
        self.response_transform = transform
        result = self.run_suite()
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks"][0]["applied_reasoning_effort"], "high")
        self.assertEqual(result["checks"][0]["usage"]["cache_read_tokens"], 2)
        self.assertEqual(result["checks"][0]["usage"]["reasoning_tokens"], 1)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(evaluate._usage({"usage": {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "30"}}), {})

    def test_requested_effort_does_not_become_applied_evidence(self):
        self.response_transform = lambda payload: {**payload, "reasoning_effort": "high", "applied_reasoning_effort": "sensitive-effort"}
        result = self.run_suite()
        self.assertTrue(all(item["applied_reasoning_effort"] is None for item in result["checks"]))
        self.assertNotIn("sensitive", json.dumps(result))

    def test_tools_refusal_and_different_model_cannot_pass(self):
        for update in ({"tool_calls": [{"function": {"name": "do-not-execute"}}]}, {"refusal": "sensitive-refusal"}):
            self.chat_count, self.requests = 0, []
            def transform(payload):
                payload["choices"][0]["message"].update(update)
                return payload
            self.response_transform = transform
            result = self.run_suite()
            self.assertFalse(result["passed"])
            self.assertEqual(len(self.requests), 2)
            self.assertNotIn("sensitive", json.dumps(result))
        self.chat_count, self.requests = 0, []
        self.response_transform = lambda payload: {**payload, "model": "glm-4.7-flashx"}
        self.assertFalse(self.run_suite()["passed"])

    def test_response_bounds_types_status_and_redirects_fail_closed(self):
        cases = [Response(b"x" * (evaluate.MAX_RESPONSE_BYTES + 1), evaluate.BASE_URL + "/models"),
                 Response({}, evaluate.BASE_URL + "/models", status=206),
                 Response({}, "https://evil.invalid/", status=200),
                 Response({}, evaluate.BASE_URL + "/models", headers={"Content-Type": "text/html"}),
                 Response({}, evaluate.BASE_URL + "/models", headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}),
                 Response({"data": [], "error": {"message": KEY}}, evaluate.BASE_URL + "/models")]
        for response in cases:
            with self.subTest(status=response.status, headers=response.headers):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = None
                self.opener.open.return_value = response
                self.assertFalse(self.run_suite()["health"]["passed"])
                self.assertEqual(self.opener.open.call_count, 1)

    def test_redirect_is_denied_before_any_followup_with_key(self):
        self.run_suite()
        proxy, redirect = self.factory.call_args.args
        self.assertEqual(proxy.proxies, {})
        redirect.parent = Mock()
        request = Request(evaluate.BASE_URL + "/models", headers={"Authorization": "Bearer " + KEY})
        with self.assertRaises(RuntimeError):
            redirect.http_error_302(request, io.BytesIO(), 302, "redirect", {"location": "https://other.invalid/"})
        redirect.parent.open.assert_not_called()

    def test_timeout_includes_response_read_budget(self):
        self.opener.open.side_effect = None
        self.opener.open.return_value = Response({"data": [{"id": self.model}]}, evaluate.BASE_URL + "/models")
        with patch.object(evaluate.time, "monotonic", side_effect=[0, 31]), self.assertRaises(TimeoutError):
            evaluate._request_json(self.opener, KEY, self.model)
        self.assertEqual(self.opener.open.call_count, 1)

    def test_unknown_finish_and_usage_fields_cannot_leak_response_text(self):
        self.response_transform = lambda payload: {
            **payload,
            "choices": [{"message": {"role": "assistant", "content": "42", "reasoning_content": KEY},
                         "finish_reason": "sensitive-finish"}],
            "usage": {"input_tokens": 20, "prompt_tokens": 999, "completion_tokens": True,
                      "total_tokens": "sensitive-count"},
        }
        result = self.run_suite()
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["usage"], {})
        self.assertIsNone(result["checks"][0]["finish_reason"])
        self.assertNotIn("sensitive", json.dumps(result))
        self.assertNotIn(KEY, json.dumps(result))

    def test_cli_requires_all_explicit_flags_before_vault_or_network(self):
        complete = ["--saved-key", "--allow-paid", "--model", self.model, "--report", "unused.json"]
        for flag in ("--saved-key", "--allow-paid"):
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                evaluate.main([item for item in complete if item != flag])
            self.assertEqual(caught.exception.code, 2)
        self.vault.assert_not_called()
        self.factory.assert_not_called()

    def test_cli_reads_only_approved_vault_and_writes_sanitized_report(self):
        self.vault.return_value.read.return_value = {"api_key": KEY}
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            destination = Path(directory) / "sanity.json"
            code = evaluate.main(["--saved-key", "--allow-paid", "--model", self.model, "--report", str(destination)])
            report = json.loads(destination.read_text())
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])
        self.vault.assert_called_once_with("approved-provider-tests")
        self.vault.return_value.read.assert_called_once_with("zhipu-official")
        self.vault.return_value.write.assert_not_called()
        self.assertNotIn(KEY, output.getvalue())
        self.assertNotIn(ANSWERS[2], json.dumps(report))

    def test_vault_failure_is_reported_without_exception_text_or_network(self):
        self.vault.return_value.read.side_effect = RuntimeError("sensitive-key-vault")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            destination = Path(directory) / "failure.json"
            code = evaluate.main(["--saved-key", "--allow-paid", "--model", self.model, "--report", str(destination)])
            report = json.loads(destination.read_text())
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        self.assertFalse(report["health"]["passed"])
        self.assertEqual(report["checks"], [])
        self.assertNotIn("sensitive", output.getvalue())
        self.factory.assert_not_called()

    def test_existing_report_is_preserved_before_vault_or_paid_call(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            destination = Path(directory) / "existing.json"
            destination.write_text("original-evidence")
            code = evaluate.main(["--saved-key", "--allow-paid", "--model", self.model, "--report", str(destination)])
            self.assertEqual(destination.read_text(), "original-evidence")
        self.assertEqual(code, 2)
        self.vault.assert_not_called()
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
