"""Prevent generic zero price fields from authorizing token-billed models."""
from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch

from sumika_core.free_model_routing import FreeModelRouting
from sumika_core.integrations import free_model_sources, moark_catalog
from sumika_core.providers.openai_compatible import OpenAICompatibleProvider


def service(model="Example", **changes):
    return {"id": 1, "ident": model, "status": 1, "type": "serverless",
            "tags": [{"slug": "text-generation"}],
            "operation_summary": {**dict.fromkeys(moark_catalog.PRICE_FIELDS, 0),
                                  "operation_count": 1, "free_operation_count": 1}, **changes}


class MoarkCatalogTests(unittest.TestCase):
    def test_case_insensitivity_is_limited_to_official_moark(self):
        provider = OpenAICompatibleProvider(moark_catalog.API_URL, "Qwen3-8B")
        self.assertTrue(provider.response_model_matches("qwen3-8b"))
        self.assertTrue(provider.response_model_matches("Qwen/qwen3-8b"))
        for response in (None, "Qwen3-4B", "/models/Qwen3-8B", "owner/path/Qwen3-8B", "Qwen3-8B-latest"):
            self.assertFalse(provider.response_model_matches(response))
        provider.base_url = "https://proxy.example/v1"
        self.assertFalse(provider.response_model_matches("qwen3-8b"))

    def test_free_count_does_not_override_token_or_operation_prices(self):
        for field in moark_catalog.PRICE_FIELDS:
            row = service()
            row["operation_summary"][field] = "0.8"
            catalog = moark_catalog.parse_catalog({"total": 1, "items": [row]})
            self.assertFalse(catalog["models"][0]["zero_price"])

    def test_unknown_or_invalid_prices_never_become_free(self):
        for value in (None, True, "NaN", "Infinity", "-1", {}, "not-a-number"):
            row = service()
            row["operation_summary"]["max_input_million_tokens_price"] = value
            result = moark_catalog.parse_catalog({"total": 1, "items": [row]})
            self.assertIsNone(result["models"][0]["prices_cny"])
            self.assertFalse(result["complete"])

    def test_only_zero_price_text_is_collected(self):
        text = service("Text")
        audio = service("Audio", tags=[{"slug": "automatic-speech-recognition"}])
        paid = service("Paid")
        paid["operation_summary"]["max_input_million_tokens_price"] = "0.8"
        catalog = moark_catalog.parse_catalog({"total": 3, "items": [text, audio, paid]})
        with patch.object(moark_catalog, "fetch_catalog", return_value=catalog):
            result = free_model_sources.fetch_free_models("moark")
        self.assertEqual(result["models"], ["Text"])
        self.assertEqual(result["mode"], "zero-price")

    def test_public_hidden_rows_are_not_complete(self):
        result = moark_catalog.parse_catalog({"total": 237, "items": [service()]})
        self.assertFalse(result["complete"])
        self.assertTrue(result["models"][0]["zero_price"])

    def test_unknown_capability_cannot_enter_text_pool(self):
        result = moark_catalog.parse_catalog({"total": 1, "items": [service(tags=None)]})
        self.assertFalse(result["models"][0]["text_generation"])

    def test_duplicates_and_invalid_totals_rejected(self):
        for payload in ({"total": 2, "items": [service(), service()]},
                        {"total": True, "items": [service()]},
                        {"total": 0, "items": [service()]}):
            with self.assertRaises(ValueError):
                moark_catalog.parse_catalog(payload)

    def test_cost_reserves_larger_billing_mode_and_all_output_tokens(self):
        row = service()
        row["operation_summary"].update(max_price="0.02", max_input_million_tokens_price="0.8",
                                        max_output_million_tokens_price="2.8")
        price = moark_catalog.parse_catalog({"total": 1, "items": [row]})["models"][0]
        expected = max(Decimal("0.02"), Decimal("0.8") * 1027 / 1000000 + Decimal("2.8") * 2048 / 1000000)
        self.assertEqual(moark_catalog.request_cost_upper(price, "中", 2048), expected)
        for limit in (True, 0, 2049):
            with self.assertRaises(ValueError):
                moark_catalog.request_cost_upper(price, "中", limit)

    def test_moark_requires_exact_failover_disabled_header(self):
        profile = {"config": {"active_base_url": moark_catalog.API_URL,
                              "headers": {"X-Failover-Enabled": "false"}}}
        self.assertTrue(FreeModelRouting._endpoint_matches(profile, moark_catalog.API_URL))
        for headers in ({}, {"X-Failover-Enabled": "true"}, {"X-Failover-Enabled": "false", "Other": "value"}):
            altered = deepcopy(profile)
            altered["config"]["headers"] = headers
            self.assertFalse(FreeModelRouting._endpoint_matches(altered, moark_catalog.API_URL))
        self.assertFalse(FreeModelRouting._endpoint_matches(profile, "https://different.example/v1"))


if __name__ == "__main__":
    unittest.main()
