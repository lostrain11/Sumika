import io
import json
import unittest
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from sumika_core.integrations.account_sources import (
    MODELSCOPE_ACCOUNT_URLS, MOARK_RECEIPTS_URL, _authenticated_json,
    read_modelscope_funding, validate_moark_receipts,
)


def receipt_evidence():
    return {"schema": "moark-receipts/v1", "source_url": MOARK_RECEIPTS_URL, "state": "verified", "receipts": [
        {"evidence_id": "a" * 64, "trace_fingerprint": "b" * 64, "package_fingerprint": "c" * 64,
         "model_id": "qwen3.8-flash", "amount": "0.0009136", "unit": "CNY", "charge_source": "resource-package", "finalized": True}]}


class AccountEvidenceSourceTests(unittest.TestCase):
    def test_receipts_keep_exact_amount_and_drop_unapproved_fields(self):
        evidence = receipt_evidence()
        evidence["receipts"][0]["request"] = {"messages": "must not escape"}
        projected = validate_moark_receipts(evidence)
        self.assertEqual(projected[0]["amount"], "0.0009136")
        self.assertNotIn("request", projected[0])

    def test_receipt_estimate_float_nonfinite_wrong_source_and_duplicates_reject(self):
        for key, value in (("amount", 0.0009136), ("amount", "NaN"), ("amount", "1e-100000"),
                           ("amount", "1e100000"), ("finalized", False), ("charge_source", "estimate"),
                           ("unit", "USD"), ("trace_fingerprint", "not-a-fingerprint")):
            evidence = receipt_evidence()
            evidence["receipts"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_moark_receipts(evidence)
        evidence = receipt_evidence()
        evidence["receipts"].append(deepcopy(evidence["receipts"][0]))
        with self.assertRaises(ValueError):
            validate_moark_receipts(evidence)
        evidence = receipt_evidence()
        evidence["source_url"] = "https://relay.example/receipts"
        with self.assertRaises(ValueError):
            validate_moark_receipts(evidence)

    def test_modelscope_rates_do_not_invent_model_mapping_or_identity(self):
        runtime = SimpleNamespace(base_url="https://api-inference.modelscope.cn/v1")
        values = [{"success": True, "data": {"total_balance": 242, "available_balance": 240, "frozen_amount": 2}},
                  {"success": True, "data": {"rates": [{"scene": "api_inference", "model_tier": "discount", "unit": "request",
                                                        "unit_price": Decimal("0.2"), "min_charge": Decimal("0.2")} ]}}]
        with patch("sumika_core.integrations.account_sources._authenticated_json", side_effect=values) as reader:
            result = read_modelscope_funding(runtime)
        self.assertEqual([call.args[0] for call in reader.call_args_list], list(MODELSCOPE_ACCOUNT_URLS.values()))
        self.assertEqual(result["available_balance"], "240")
        self.assertFalse(result["account_binding_verified"])
        self.assertFalse(result["routing_eligible"])
        self.assertEqual(result["rates"][0]["unit_price"], "0.2")

    def test_modelscope_wrong_endpoint_and_failed_auth_cannot_be_evidence(self):
        with self.assertRaises(ValueError):
            read_modelscope_funding(SimpleNamespace(base_url="https://relay.example/v1"))
        runtime = SimpleNamespace(base_url="https://api-inference.modelscope.cn/v1")
        with patch("sumika_core.integrations.account_sources._authenticated_json", return_value={"success": False}), self.assertRaises(ValueError):
            read_modelscope_funding(runtime)

    def test_account_http_errors_are_closed_without_secret_body(self):
        runtime = SimpleNamespace(_request_headers=lambda **kwargs: {"Authorization": "Bearer fixture-secret"})
        body = io.BytesIO(b"private account body")
        error = HTTPError("https://modelscope.cn/openapi/v1/magicubes/balance", 401, "private account body", {}, body)
        with patch("sumika_core.integrations.account_sources.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError, "^official account HTTP 401$"):
                _authenticated_json(error.url, runtime)
        self.assertTrue(body.closed)

    def test_account_duplicate_keys_and_redirects_reject(self):
        runtime = SimpleNamespace(_request_headers=lambda **kwargs: {})
        url = MODELSCOPE_ACCOUNT_URLS["balance"]
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = url
        response.read.return_value = b'{"success":true,"success":false}'
        with patch("sumika_core.integrations.account_sources.build_opener") as opener:
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(ValueError, "duplicate"):
                _authenticated_json(url, runtime)
            response.read.return_value = b'{}'
            response.geturl.return_value = "https://relay.example/"
            with self.assertRaises(ValueError):
                _authenticated_json(url, runtime)


if __name__ == "__main__":
    unittest.main()
