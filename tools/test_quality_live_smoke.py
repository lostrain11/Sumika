import json
import io
import unittest
from unittest.mock import patch
from urllib.request import Request

from tools.quality_live_smoke import BASE_URL, MODEL, PAID_MODEL, NoRedirect, RequestGuard, SmokeStopped, run_paid_probe, run_smoke


class QualityLiveSmokeTests(unittest.TestCase):
    def test_isolated_workflow_and_usage_capture_with_fixture(self):
        def respond(request, **kwargs):
            if request.method == "GET":
                response = io.BytesIO(b'{"data":[]}')
                response.headers = {"Content-Type": "application/json"}
            else:
                payload = json.loads(request.data)
                prompt = payload["messages"][-1]["content"]
                answer = "42"
                if "Return only a JSON object with nodes" in prompt:
                    answer = '```json\n{"nodes":[{"node_id":"answer","goal":"Compute 6 times 7", "task_type":"arithmetic","acceptance":["Exactly 42"]}]}\n```'
                elif "Verify the task result" in prompt:
                    answer = '```json\n{"passed":true,"reason":"Exact answer"}\n```'
                elif "short in-character introduction" in prompt:
                    answer = "Checked answer:"
                result = {"choices": [{"delta" if payload.get("stream") else "message": {"content": answer}}],
                          "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
                body = "data: " + json.dumps(result) + "\n\ndata: [DONE]\n\n" if payload.get("stream") else json.dumps(result)
                response = io.BytesIO(body.encode())
                response.headers = {"Content-Type": "text/event-stream" if payload.get("stream") else "application/json"}
            response.status = 200
            return response

        for allow_paid, paid_only in ((False, False), (True, False), (True, True)):
            with self.subTest(allow_paid=allow_paid, paid_only=paid_only):
                guard = RequestGuard(allow_paid=allow_paid)
                with patch.object(guard.opener, "open", side_effect=respond):
                    report = run_smoke("fixture-key-not-real", guard, paid_only=paid_only)
                self.assertTrue(report["passed"], report)
                self.assertTrue(report["usage_complete"])
                self.assertEqual(len(report["calls"]), 8 if allow_paid and not paid_only else 7)
                self.assertEqual(report["reported_input_tokens"], 160 if allow_paid and not paid_only else 140)
                self.assertNotIn("fixture-key", json.dumps(report))

    def request(self, **changes):
        payload = {"model": MODEL, "messages": [{"role": "user", "content": "test"}], "max_tokens": 100}
        payload.update(changes)
        return Request(BASE_URL + "/chat/completions", data=json.dumps(payload).encode(), method="POST")

    def test_direct_paid_probe_is_single_call_without_free_model(self):
        guard = RequestGuard(allow_paid=True, max_calls=1)
        response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"42"},"finish_reason":"stop"}],"usage":{"prompt_tokens":20,"completion_tokens":10}}\n\ndata: [DONE]\n\n')
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream"}
        with patch.object(guard.opener, "open", return_value=response):
            report = run_paid_probe("fixture-key-not-real", guard)
        self.assertTrue(report["passed"], report)
        self.assertEqual(len(report["calls"]), 1)
        self.assertEqual(report["calls"][0]["model"], PAID_MODEL)
        self.assertEqual(report["estimated_cash_cny"], "0.000044")
        self.assertNotIn("fixture-key", json.dumps(report))

    def test_model_and_destination_allowlist(self):
        guard = RequestGuard()
        for request in (self.request(model="paid-model"), Request("https://other.invalid/models", method="GET")):
            with self.assertRaises(SmokeStopped):
                guard.admit(request)
        self.assertEqual(guard.calls, [])

    def test_request_and_token_limits(self):
        guard = RequestGuard(max_calls=1)
        for value in (True, 0, 4097):
            with self.assertRaises(SmokeStopped):
                guard.admit(self.request(max_tokens=value))
        with self.assertRaises(SmokeStopped):
            guard.admit(self.request(messages=[{"role": "user", "content": "x" * 16001}]))
        guard.admit(self.request())
        with self.assertRaises(SmokeStopped):
            guard.admit(self.request())

    def test_paid_requires_opt_in_and_reserves_before_send(self):
        guard = RequestGuard(allow_paid=True, cash_limit="0.0001")
        with self.assertRaises(SmokeStopped):
            guard.admit(self.request(model=PAID_MODEL))
        self.assertEqual(guard.calls, [])
        guard = RequestGuard(allow_paid=True)
        guard.admit(self.request(model=PAID_MODEL))
        self.assertGreater(guard.reserved_cash, 0)
        self.assertIsNone(guard.summary()["estimated_cash_cny"])

    def test_failure_stops_further_calls(self):
        guard = RequestGuard()
        guard.stopped = True
        with self.assertRaises(SmokeStopped):
            guard.admit(self.request())

    def test_report_has_no_prompts_secrets_or_invented_actual_cost(self):
        guard = RequestGuard()
        request = self.request(messages=[{"role": "user", "content": "private-content"}])
        request.add_header("Authorization", "Bearer private-key")
        guard.admit(request)
        report = guard.summary()
        self.assertNotIn("private", json.dumps(report))
        self.assertFalse(report["usage_complete"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        self.assertIsNone(report["remaining_balance_cny"])

    def test_redirects_are_never_followed(self):
        with self.assertRaises(SmokeStopped):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")


if __name__ == "__main__":
    unittest.main()
