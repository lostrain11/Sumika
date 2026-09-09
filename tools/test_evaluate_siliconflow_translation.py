"""Translation probe boundaries, with no network or real credentials."""
import json
import unittest
from unittest.mock import patch

from tools import evaluate_siliconflow_translation as evaluate
from tools.evaluate_siliconflow_candidates import ApiFailure


class TranslationSanityTests(unittest.TestCase):
    def setUp(self):
        self.prices = {"source_url": "https://www.siliconflow.cn/pricing", "observed_at": "2026-09-08T00:00:00Z",
                       "models": [{"model_id": evaluate.MODEL, "input_price_label": "free", "output_price_label": "free"}]}
        self.rows = [{"id": evaluate.MODEL}]
        self.calls = []
        self.transform = lambda value: value
        for name, kwargs in (("fetch_prices", {"return_value": self.prices}),
                             ("request_json", {"side_effect": self.respond}), ("build_opener", {})):
            patcher = patch.object(evaluate, name, **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def respond(self, opener, key, payload=None):
        if payload is None:
            return {"data": self.rows}
        groups = evaluate.CHECKS[len(self.calls)][2]
        self.calls.append(payload)
        return self.transform({"model": evaluate.MODEL, "usage": {"prompt_tokens": 20, "completion_tokens": 15},
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": " ".join(group[0] for group in groups)}}]})

    def run_probe(self):
        return evaluate.run_suite("fixture-private-key", allow_confirmed_free_tests=True)

    def test_three_bounded_translation_checks_no_promotion_or_content_logging(self):
        report = self.run_probe()
        self.assertTrue(report["basic_checks_passed"])
        self.assertTrue(report["health_passed"])
        self.assertFalse(report["routing_qualified"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        self.assertEqual(report["model_calls"], 3)
        for payload in self.calls:
            self.assertEqual(payload["model"], evaluate.MODEL)
            self.assertEqual(payload["max_tokens"], 256)
            self.assertFalse(payload["stream"])
        serialized = json.dumps(report)
        for private in ("fixture-private-key", "Please save", "B-204", "messages", "content"):
            self.assertNotIn(private, serialized)

    def test_authorization_and_key_checked_before_network(self):
        for key, allowed in (("fixture", False), ("bad\nkey", True), (None, True)):
            with self.assertRaises(ValueError):
                evaluate.run_suite(key, allow_confirmed_free_tests=allowed)
        self.fetch_prices.assert_not_called()
        self.request_json.assert_not_called()

    def test_unknown_nonzero_duplicate_and_unavailable_prices_block_requests(self):
        for rows in ([], [self.prices["models"][0]] * 2, [{"model_id": evaluate.MODEL, "input_price_label": "paid", "output_price_label": "free"}]):
            self.prices["models"] = rows
            self.assertEqual(self.run_probe()["model_calls"], 0)
        self.fetch_prices.side_effect = TimeoutError("private")
        self.assertEqual(self.run_probe()["model_calls"], 0)
        self.request_json.assert_not_called()

    def test_missing_or_duplicate_model_blocks_chat(self):
        for rows in ([], [{"id": "other"}], [{"id": evaluate.MODEL}] * 2):
            self.rows = rows
            self.assertEqual(self.run_probe()["model_calls"], 0)
        self.assertFalse(self.calls)

    def test_timeout_and_rate_limit_never_retry(self):
        for error in (TimeoutError("private"), ApiFailure(429, None, None)):
            self.request_json.side_effect = [{"data": self.rows}, error]
            report = self.run_probe()
            self.assertEqual(report["model_calls"], 1)
            self.assertFalse(report["basic_checks_passed"])
            self.assertNotIn("private", json.dumps(report))

    def test_charge_identity_truncation_wrong_translation_and_usage_stop_batch(self):
        for change in ({"usage": {"cost": 0.01}}, {"model": "other"}, {"usage": {}},
                       {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "private"}}]},
                       {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "private"}}]}):
            self.calls.clear()
            self.transform = lambda value: {**value, **change}
            report = self.run_probe()
            self.assertEqual(report["model_calls"], 1)
            self.assertFalse(report["basic_checks_passed"])
            self.assertNotIn("private", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
