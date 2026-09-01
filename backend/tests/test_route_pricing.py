import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sumika_core.route_pricing import (
    NewApiPricingSource,
    PinAIPricingSource,
    PricingExpressionError,
    RoutePricingError,
    RoutePricingService,
    evaluate_billing_expression,
    public_json,
)


FIXTURES = Path(__file__).with_name("fixtures")


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class RoutePricingTests(unittest.TestCase):
    def test_pinai_keeps_configured_groups_separate_from_observed_effective_price(self):
        snapshots = PinAIPricingSource().parse(
            fixture("pinai_pricing.json"),
            provider_profile_id="pinai-profile",
            model_ids=("fixture-model",),
        )

        self.assertEqual(len(snapshots), 2)
        low = next(item for item in snapshots if item.billing_group == "低价池")
        self.assertEqual(low.currency, "USD-credit")
        self.assertEqual(low.input_price_per_million, 0.5)
        self.assertEqual(low.output_price_per_million, 2.0)
        self.assertEqual(low.cache_read_price_per_million, 0.05)
        self.assertEqual(low.observations["effective_price_per_million_1h"], 0.42)
        self.assertEqual(low.context_tiers[0]["context_label"], "0-128K")
        self.assertNotEqual(low.input_price_per_million, low.observations["effective_price_per_million_1h"])

    def test_new_api_applies_group_ratio_and_preserves_pricing_version(self):
        snapshots = NewApiPricingSource().parse(
            fixture("new_api_status.json"),
            fixture("new_api_pricing.json"),
            provider_profile_id="relay-profile",
            model_ids=("ratio-model",),
            billing_group="经济组",
        )

        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot.currency, "CNY")
        self.assertEqual(snapshot.source_version, "fixture-pricing-v1")
        self.assertEqual(snapshot.input_price_per_million, 1.0)
        self.assertEqual(snapshot.output_price_per_million, 2.0)
        self.assertEqual(snapshot.cache_read_price_per_million, 0.1)
        self.assertEqual(snapshot.cache_write_price_per_million, 1.25)

    def test_dynamic_expression_is_evaluated_without_eval(self):
        snapshots = NewApiPricingSource().parse(
            fixture("new_api_status.json"),
            fixture("new_api_pricing.json"),
            provider_profile_id="relay-profile",
            model_ids=("dynamic-model",),
            billing_group="经济组",
        )
        snapshot = snapshots[0]
        short = snapshot.estimate_charge(
            input_tokens=1_000_000,
            output_tokens=500_000,
            cache_read_tokens=100_000,
            context_tokens=16_000,
        )
        long = snapshot.estimate_charge(
            input_tokens=1_000_000,
            output_tokens=500_000,
            cache_read_tokens=100_000,
            context_tokens=64_000,
        )
        self.assertEqual(short["tier"], "short")
        self.assertAlmostEqual(short["amount"], 0.302, places=6)
        self.assertEqual(long["tier"], "long")
        self.assertAlmostEqual(long["amount"], 0.906, places=6)

    def test_dynamic_expression_rejects_code_and_unsupported_syntax(self):
        rejected = (
            "__import__('os').system('whoami')",
            "open('secret.txt').read()",
            "[value for value in (1, 2, 3)]",
            "(lambda: 1)()",
            "param('x').secret",
        )
        for expression in rejected:
            with self.subTest(expression=expression):
                with self.assertRaises(PricingExpressionError):
                    evaluate_billing_expression(expression, {"p": 1, "c": 1, "cr": 0, "cc": 0, "len": 1})

    def test_unsupported_dynamic_expression_does_not_discard_other_model_prices(self):
        payload = fixture("new_api_pricing.json")
        payload["data"].append({
            "model_name": "unsafe-model",
            "enable_groups": ["经济组"],
            "billing_mode": "tiered_expr",
            "billing_expr": "__import__('os').system('whoami')",
        })

        snapshots = NewApiPricingSource().parse(
            fixture("new_api_status.json"),
            payload,
            provider_profile_id="relay-profile",
            model_ids=("ratio-model", "unsafe-model"),
            billing_group="经济组",
        )

        self.assertEqual([item.model_id for item in snapshots], ["ratio-model"])

    def test_public_pricing_request_has_no_sensitive_headers_and_blocks_cross_origin_redirect(self):
        received = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                received.append(dict(self.headers.items()))
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return None

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/target")
                self.end_headers()

            def log_message(self, *_args):
                return None

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        try:
            result = public_json(f"http://127.0.0.1:{target.server_address[1]}/pricing")
            self.assertTrue(result["ok"])
            headers = {key.lower(): value for key, value in received.pop().items()}
            self.assertNotIn("authorization", headers)
            self.assertNotIn("cookie", headers)
            self.assertNotIn("x-api-key", headers)

            with self.assertRaises(RoutePricingError):
                public_json(f"http://127.0.0.1:{redirect.server_address[1]}/pricing")
            self.assertEqual(received, [])
        finally:
            redirect.shutdown()
            redirect.server_close()
            redirect_thread.join(timeout=2)
            target.shutdown()
            target.server_close()
            target_thread.join(timeout=2)

    def test_pricing_projection_drops_removed_or_archived_profiles(self):
        class Profiles:
            def __init__(self):
                self.rows = [
                    {
                        "id": "priced-profile",
                        "config": {
                            "model": "priced-model",
                            "models": [{"id": "priced-model"}],
                            "pricing": {
                                "source_type": "manual",
                                "billing_group": "default",
                                "rates": {
                                    "currency": "CNY",
                                    "input_price_per_million": 1,
                                    "output_price_per_million": 2,
                                },
                            },
                        },
                    }
                ]

            def list(self, *, include_archived=False):
                del include_archived
                return list(self.rows)

        profiles = Profiles()
        with tempfile.TemporaryDirectory() as data_dir:
            service = RoutePricingService(profiles, data_dir)
            self.assertTrue(service.refresh_profiles(force=True))
            self.assertEqual(len(service.store.list()), 1)

            profiles.rows[0]["config"]["pricing"] = None
            self.assertTrue(service.refresh_profiles(force=True))
            self.assertEqual(service.store.list(), [])

            profiles.rows = []
            service.refresh_profiles(force=True)
            self.assertEqual(service.catalog()["snapshots"], [])

    def test_expired_snapshot_remains_auditable_but_cannot_price_a_route(self):
        class Profiles:
            def list(self, *, include_archived=False):
                del include_archived
                return [{
                    "id": "stale-profile",
                    "config": {
                        "model": "stale-model",
                        "models": [{"id": "stale-model"}],
                        "pricing": {
                            "source_type": "manual",
                            "billing_group": "default",
                            "rates": {
                                "currency": "CNY",
                                "input_price_per_million": 1,
                                "output_price_per_million": 2,
                            },
                        },
                    },
                }]

        service = RoutePricingService(Profiles())
        service.refresh_profiles(force=True)
        snapshot = replace(service.store.list()[0], expires_at="2000-01-01T00:00:00+00:00")
        service.store.replace_profile("stale-profile", [snapshot])
        service.provider_profiles = None

        self.assertFalse(service.catalog()["snapshots"][0]["fresh"])
        self.assertEqual(service.projection("stale-profile", "stale-model"), {"pricing_status": "unknown"})
        estimate = service.estimate(
            {
                "route_id": "profile:stale-profile:stale-model",
                "provider_profile_id": "stale-profile",
                "model_id": "stale-model",
                "metadata": {"billing_group": "default"},
            },
            {"task_kind": "chat"},
        )
        self.assertEqual(estimate.status, "unknown")


if __name__ == "__main__":
    unittest.main()
