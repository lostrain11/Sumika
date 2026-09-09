"""Offline MaaS price and bounded-probe fixtures."""
import copy
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import evaluate_siliconflow_candidates as evaluate
from tools import read_xfyun_public_catalog as catalog
from tools import test_evaluate_siliconflow_candidates as fixtures


def catalog_payload():
    prices = {"showPrice": True}
    for field in ("inTokens", "outTokens", "cacheTokens"):
        prices[field + "Price"] = 0
        prices[field + "Unit"] = catalog.PRICE_UNIT
    return {"code": 0, "succeed": True, "data": {"rows": [
        {"name": name, "serviceId": model, "urls": {"api": {"http": catalog.BASE_URL}},
         "price": {"inferencePrice": copy.deepcopy(prices)}} for model, name in catalog.MODELS.items()]}}


class XfyunCatalogTests(unittest.TestCase):
    def test_inference_only_and_unknown_quota(self):
        payload = catalog_payload()
        payload["data"]["rows"][0]["price"]["trainPrice"] = {"tokensPrice": 5}
        payload["data"]["rows"][1]["categoryTree"] = [{"key": "indexMarker", "children": [{"name": "\u9650\u65f6\u514d\u8d39"}]}]
        rows = catalog.free_rows(payload)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1]["limited_time"])
        self.assertIsNone(rows[1]["expires_at"])
        self.assertTrue(all(row["account_quota"] == "unknown" for row in rows))

    def test_price_must_be_explicit_zero_with_correct_unit(self):
        for invalid in (None, True, 1, "NaN", "-1", "Infinity"):
            payload = catalog_payload()
            payload["data"]["rows"][0]["price"]["inferencePrice"]["outTokensPrice"] = invalid
            with self.assertRaises(ValueError):
                catalog.free_rows(payload)
        payload = catalog_payload()
        payload["data"]["rows"][0]["price"]["inferencePrice"]["cacheTokensUnit"] = "USD"
        with self.assertRaises(ValueError):
            catalog.free_rows(payload)

    def test_missing_duplicate_identity_and_endpoint_rejected(self):
        payloads = []
        missing = catalog_payload()
        missing["data"]["rows"].pop()
        payloads.append(missing)
        duplicate = catalog_payload()
        duplicate["data"]["rows"].append(copy.deepcopy(duplicate["data"]["rows"][0]))
        payloads.append(duplicate)
        wrong = catalog_payload()
        wrong["data"]["rows"][0]["urls"]["api"]["http"] = "https://wrong.example/v1"
        payloads.append(wrong)
        for payload in payloads:
            with self.assertRaises(ValueError):
                catalog.free_rows(payload)


class XfyunProbeTests(unittest.TestCase):
    respond = fixtures.SiliconFlowSanityTests.respond

    def setUp(self):
        fixtures.SiliconFlowSanityTests.setUp(self)
        self.models = []
        self.pricing = {"models": catalog.free_rows(catalog_payload()), "authority": "public-price-observation-only"}
        for factory in (patch.object(evaluate.time, "sleep"),
                        patch.object(evaluate, "fetch_xfyun_catalog", return_value=self.pricing)):
            factory.start()
            self.addCleanup(factory.stop)

    def run_suite(self, authorized=True):
        return evaluate.run_suite("offline-fixture-secret", list(catalog.MODELS), provider="xfyun",
                                  allow_confirmed_free_tests=True, allow_public_catalog_probe=authorized)

    def test_empty_account_catalog_requires_manual_probe_opt_in(self):
        report = self.run_suite(False)
        self.assertFalse(report["authenticated"])
        self.assertEqual(report["model_calls"], 0)

    def test_public_evidence_not_account_quota_or_routing_authorization(self):
        report = self.run_suite()
        self.assertTrue(all(candidate["passed"] for candidate in report["candidates"]))
        self.assertEqual(report["model_calls"], 6)
        self.assertTrue(report["authenticated"])
        self.assertFalse(report["routing_qualified"])
        self.assertIn("account-catalog-empty", report["catalog_basis"])
        self.assertIsNone(report["actual_billed_cash_cny"])
        self.assertTrue(all(request.full_url.startswith(catalog.BASE_URL) for request in self.requests))

    def test_missing_identity_separates_answer_from_qualification(self):
        self.transform = lambda payload: {name: value for name, value in payload.items() if name != "model"}
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        candidate = report["candidates"][0]
        self.assertFalse(candidate["health_passed"])
        self.assertTrue(candidate["checks"][0]["answer_contract_passed"])
        self.assertFalse(candidate["passed"])

    def test_catalog_failure_prevents_credentialled_request(self):
        with patch.object(evaluate, "fetch_xfyun_catalog", side_effect=ValueError("invalid")):
            report = self.run_suite()
        self.assertEqual(report["model_calls"], 0)
        self.opener.open.assert_not_called()

    def test_model_permission_error_stops_batch_without_paid_fallback(self):
        def respond(request, **kwargs):
            if request.method == "POST":
                raise HTTPError(request.full_url, 403, "private", {},
                                io.BytesIO(b'{"error":{"code":11200,"message":"private"}}'))
            return self.respond(request, **kwargs)
        self.opener.open.side_effect = respond
        report = self.run_suite()
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["candidates"][0]["checks"][0]["provider_code"], "11200")
        self.assertFalse(report["authenticated"])


if __name__ == "__main__":
    unittest.main()
