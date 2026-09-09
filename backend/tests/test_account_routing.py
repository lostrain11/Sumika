import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from sumika_core.account_routing import AccountRouting, PORTAL_STATES_KEY
from sumika_core.credentials import MemoryCredentialStore
from sumika_core.integrations.account_sources import parse_deepseek_prices, read_account
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.providers.guard import RequestNotSent
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.route_pricing import PricingSnapshot, RoutePricingService
from sumika_core.storage import Storage
from sumika_core.funding_ledger import FundingLedger


class AccountRoutingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage()
        self.addCleanup(self.storage.close)
        self.profiles = ProviderProfileManager(self.storage, MemoryCredentialStore())
        self.profiles.save({"id": "deepseek", "name": "Test", "base_url": "https://api.deepseek.com/v1", "model": "fixture"})
        self.pricing = RoutePricingService(self.profiles, data_dir=directory.name)
        self.accounts = AccountRouting(self.profiles, self.pricing, directory.name)
        self.addCleanup(self.accounts.close)
        self.accounts.bind("deepseek", "deepseek", ["fixture"])
        self.price = PricingSnapshot("price", "deepseek", "fixture", "official", "CNY", input_price_per_million=100,
            output_price_per_million=100, cash_currency="CNY", cash_rate=1,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        self.pricing.store.replace_profile("deepseek", [self.price])
        self.reader = patch("sumika_core.account_routing.read_account", return_value={"available": True, "grant": "0.2", "cash": "0.8"})
        self.reader_mock = self.reader.start()
        self.addCleanup(self.reader.stop)
        self.accounts.refresh()
        self.entry = {"provider_profile_id": "deepseek", "model_id": "fixture"}

    def test_exact_binding_and_mixed_funding(self):
        quote = self.accounts.quote(self.entry, 2000, 1000)
        self.assertTrue(quote.available)
        self.assertEqual(quote.funding_kind, "mixed")
        self.assertEqual(quote.cash_due_cny, Decimal("0.1"))
        self.assertEqual(quote.effective_cost_cny, Decimal("0.1"))
        self.assertFalse(self.accounts.quote(self.entry, 10000, 1000).available)
        self.profiles.save({"id": "deepseek", "active_base_url": "https://relay.example/v1", "base_urls": ["https://relay.example/v1"]})
        self.assertFalse(self.accounts.quote(self.entry, 1, 1).available)

    def test_refresh_failure_blocks_previous_balance(self):
        self.reader_mock.return_value["available"] = False
        self.accounts.refresh(force=True)
        self.assertFalse(self.accounts.quote(self.entry, 1, 1).available)
        self.assertNotIn("api_key", json.dumps(self.accounts.status()))

    def test_old_free_label_cannot_override_verified_paid_price(self):
        entry = {**self.entry, "cost_class": "local", "processing_location": "local", "metadata": {"verified_zero_price": True}}
        quote = self.accounts.quote(entry, 2000, 1000)
        self.assertFalse(quote.free)
        self.assertEqual(quote.cash_due_cny, Decimal("0.1"))

    def test_web_profile_does_not_break_api_quote_catalog(self):
        from sumika_core.model_policy import ModelPolicyService
        policy = ModelPolicyService(self.profiles)
        self.addCleanup(policy.close)
        pricing = policy.candidate_pricing({"provider_profile_id": "web-session", "model_id": "web-model"})
        self.assertIsNone(pricing["quote_provider"](100, 100).effective_cost_cny)

    def test_portal_binding_does_not_authorize_unknown_quota(self):
        self.profiles.save({"id": "ollama", "name": "Ollama", "base_url": "https://ollama.com/v1", "model": "gpt-oss:20b"})
        self.accounts.bind_portal("ollama", "ollama", "browser-1")
        self.accounts.refresh_portals(force=True)
        self.assertFalse(self.accounts.portal_status()[0]["routable"])
        self.assertFalse(self.accounts.portal_status()[0]["fresh"])
        self.assertFalse(self.accounts.manages("ollama", "gpt-oss:20b"))

    def test_runtime_reserves_and_preserves_estimate_until_bill(self):
        provider = SimpleNamespace(timeout=10, last_usage={"input_tokens": 20, "output_tokens": 30},
                                   stream=lambda request: iter(["ok"]))
        runtime = self.accounts.wrap(provider, "deepseek", "fixture")
        self.assertEqual(list(runtime.stream(ChatRequest("session", [Message("user", "hello")], max_tokens=2000))), ["ok"])
        rows = self.accounts.ledger.status()["reservations"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["state"] == "estimated" and row["actual"] is None for row in rows))
        self.assertEqual(sum((row["estimated"] for row in rows), Decimal(0)), Decimal("0.005"))
        self.assertIsNone(runtime.last_charge_receipt["actual_cash_cny"])
        self.accounts.refresh(force=True)
        self.assertEqual(sum((row["inflight_and_unsettled"] for row in self.accounts.ledger.status()["projections"]), Decimal(0)), Decimal("0.005"))

    def test_native_reader_is_used_without_bsk_and_failure_never_falls_back(self):
        from sumika_core.integrations.account_portals import project_ollama_starter_portal, OLLAMA_STARTER_MODELS
        observation = project_ollama_starter_portal({"state": "verified", "free_usage_percent": 0,
            "extra_usage_balance": 0, "allowed_models": list(OLLAMA_STARTER_MODELS)})
        self.profiles.save({"id": "ollama", "name": "Ollama", "base_url": "https://ollama.com/v1", "model": "gpt-oss:20b"})
        self.accounts.bind_portal("ollama", "ollama", "sumika-native")
        self.accounts.browser_client = Mock()
        with patch("sumika_core.integrations.account_portals.AccountPortalReader.read") as old_reader:
            self.accounts.native_reader = Mock(return_value=observation)
            self.accounts.refresh_portals(force=True)
            self.accounts.native_reader.assert_called_once_with("ollama", "sumika-native", self.accounts.closed)
            self.assertTrue(self.accounts.portal_status()[0]["fresh"])
            for callback in (None, Mock(side_effect=RuntimeError("secret must not escape")),
                             Mock(return_value={"quality": {"state": "login-required"}})):
                self.accounts.native_reader = callback
                self.accounts.refresh_portals(force=True)
                status = self.accounts.portal_status()[0]
                self.assertEqual(status["state"], "needs-review")
                self.assertFalse(status["fresh"])
                self.assertFalse(status["routable"])
            old_reader.assert_not_called()
        self.assertNotIn("secret must not escape", json.dumps(self.accounts.status()))

    def test_native_reader_does_not_replace_legacy_browser_binding(self):
        self.profiles.save({"id": "ollama", "name": "Ollama", "base_url": "https://ollama.com/v1", "model": "gpt-oss:20b"})
        self.accounts.bind_portal("ollama", "ollama", "legacy-browser")
        self.accounts.native_reader = Mock()
        self.accounts.browser_client = Mock()
        with patch("sumika_core.integrations.account_portals.AccountPortalReader.read", return_value={"quality": {"state": "needs-review"}}) as reader:
            self.accounts.refresh_portals(force=True)
        reader.assert_called_once_with("ollama", "legacy-browser", self.accounts.closed)
        self.accounts.native_reader.assert_not_called()

    def test_modelscope_native_failure_keeps_old_observation_stale_with_exact_fixed_reason(self):
        from sumika_core.integrations.account_portals import project_modelscope_portal
        self.profiles.save({"id": "modelscope", "name": "ModelScope", "base_url": "https://api-inference.modelscope.cn/v1", "model": "fixture"})
        self.accounts.bind_portal("modelscope", "modelscope", "sumika-native")
        previous = project_modelscope_portal({"state": "verified", "available_balance": 242, "unit": "magicube",
            "grants": [{"kind": "daily-login", "amount": 200, "granted_date_display": "2026-09-08", "validity_days_display": 1}]},
            observed_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        self.accounts.native_reader = Mock(return_value=previous)
        self.accounts.refresh_portals(force=True)
        self.assertTrue(self.accounts.portal_status()[0]["fresh"])
        for reason in ("missing-records-tabs", "invalid-grant-row", "ambiguous-records-tab"):
            self.accounts.native_reader.return_value = {"quality": {"state": "needs-review", "blocking_reason": reason},
                "available_balance": 999, "body": "private-page-content", "api_key": "private-key"}
            self.accounts.refresh_portals(force=True)
            status = self.accounts.portal_status()[0]
            self.assertEqual(status["state"], "needs-review")
            self.assertEqual(status["reason"], reason)
            self.assertFalse(status["fresh"])
            self.assertFalse(status["routable"])
            for field in ("available_balance", "grants", "observed_at", "fresh_until"):
                self.assertEqual(status[field], previous[field])
            self.assertGreater(datetime.fromisoformat(status["last_failure_at"]), datetime.fromisoformat(previous["observed_at"]))
            stored = self.storage.get_meta(PORTAL_STATES_KEY)
            self.assertNotIn("private", stored)
            self.assertNotIn("api_key", stored)
            self.assertNotIn("login-required", stored)

    def test_native_failure_without_previous_observation_never_stores_arbitrary_reason_or_exception(self):
        self.profiles.save({"id": "modelscope", "name": "ModelScope", "base_url": "https://api-inference.modelscope.cn/v1", "model": "fixture"})
        self.accounts.bind_portal("modelscope", "modelscope", "sumika-native")
        for callback in (None, Mock(side_effect=RuntimeError("private-exception-and-key")),
                         Mock(return_value={"quality": {"state": "needs-review", "blocking_reason": "private-page-content"}}),
                         Mock(return_value={"quality": {"state": "needs-review", "blocking_reason": "official-log-forbidden"}}),
                         Mock(return_value={"quality": {"state": "needs-review", "blocking_reason": {"private": "content"}}}),
                         Mock(return_value={"quality": ["private-body"]})):
            self.accounts.native_reader = callback
            self.accounts.refresh_portals(force=True)
            status = self.accounts.portal_status()[0]
            self.assertEqual(status["state"], "needs-review")
            self.assertEqual(status["reason"], "native-portal-read-failed")
            self.assertIsNone(status["available_balance"])
            self.assertFalse(status["fresh"])
            self.assertNotIn("private", self.storage.get_meta(PORTAL_STATES_KEY))
            self.assertNotIn("login", self.storage.get_meta(PORTAL_STATES_KEY))

    def test_desktop_portal_does_not_use_or_rebind_legacy_login(self):
        self.profiles.save({"id": "ollama", "name": "Ollama", "base_url": "https://ollama.com/v1", "model": "gpt-oss:20b"})
        self.accounts.bind_portal("ollama", "ollama", "legacy-browser")
        self.accounts.native_required = True
        self.accounts.browser_client = Mock()
        self.accounts.native_reader = Mock()
        with patch("sumika_core.integrations.account_portals.AccountPortalReader.read") as legacy:
            self.accounts.refresh_portals(force=True)
        legacy.assert_not_called()
        self.accounts.native_reader.assert_not_called()
        self.assertEqual(self.accounts.portal_bindings()["ollama"]["browser_instance_id"], "legacy-browser")
        self.assertFalse(self.accounts.portal_status()[0]["fresh"])

    def _moark_request(self, *, trace=True):
        from sumika_core.integrations.account_sources import MOARK_RECEIPTS_URL
        self.profiles.save({"id": "moark", "name": "Moark", "base_url": "https://api.moark.com/v1", "model": "fixture"})
        self.accounts.bind("moark", "moark", ["fixture"], funding_kind="purchased", unit_value_cny="1",
                           evidence="order-fixture", package_fingerprints=["a" * 64])
        self.reader_mock.return_value = {"balance": "10", "package_fingerprints": ["a" * 64]}
        self.accounts.refresh_account("moark")
        binding = self.accounts.bindings()["moark"]
        self.accounts.ledger.reserve_bundle("request-moark", [{"provider": "moark", "account_revision": binding["account_revision"],
            "amount": "0.1", "unit": "CNY", "source": "purchased", "pocket_id": "package"}])
        if trace:
            self.accounts.ledger.record_request_trace("request-moark", "b" * 64, "fixture")
        self.accounts.ledger.settle("request-moark", estimated="0.05")
        return {"schema": "moark-receipts/v1", "source_url": MOARK_RECEIPTS_URL, "state": "verified", "receipts": [
            {"evidence_id": "c" * 64, "trace_fingerprint": "b" * 64, "package_fingerprint": "a" * 64,
             "model_id": "fixture", "amount": "0.0009136", "unit": "CNY", "charge_source": "resource-package", "finalized": True}]}

    def test_exact_receipt_closes_loop_without_double_deducting_or_guessing(self):
        evidence = self._moark_request()
        self.reader_mock.return_value["balance"] = "9.9990864"
        result = self.accounts.reconcile_receipts("moark", evidence)
        self.assertEqual(result["matched"], 1)
        row = self.accounts.ledger.status()["reservations"][-1]
        self.assertEqual(row["actual"], Decimal("0.0009136"))
        self.assertTrue(row["absorbed"])
        self.assertEqual(self.accounts._pockets("moark")[0]["available"], Decimal("9.9990864"))
        self.accounts.reconcile_receipts("moark", evidence)
        self.assertEqual(self.accounts._pockets("moark")[0]["inflight_and_unsettled"], 0)

    def test_old_request_without_trace_remains_unmatched(self):
        evidence = self._moark_request(trace=False)
        result = self.accounts.reconcile_receipts("moark", evidence)
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["unmatched"], 1)
        self.assertEqual(self.accounts._pockets("moark")[0]["inflight_and_unsettled"], Decimal("0.05"))

    def test_receipt_wrong_package_or_model_cannot_settle(self):
        from copy import deepcopy
        evidence = self._moark_request()
        for field, value in (("package_fingerprint", "d" * 64), ("model_id", "other"), ("amount", 0.01)):
            invalid = deepcopy(evidence)
            invalid["receipts"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.accounts.reconcile_receipts("moark", invalid)
        self.assertIsNone(self.accounts.ledger.status()["reservations"][-1]["actual"])

    def test_receipt_without_fresh_balance_is_not_absorbed(self):
        evidence = self._moark_request()
        self.reader_mock.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            self.accounts.reconcile_receipts("moark", evidence)
        row = self.accounts.ledger.status()["reservations"][-1]
        self.assertEqual(row["actual"], Decimal("0.0009136"))
        self.assertFalse(row["absorbed"])

    def test_bound_receipt_reader_runs_before_balance_and_native_does_not_fallback(self):
        evidence = self._moark_request()
        self.accounts.bind_receipt_portal("moark", "sumika-native")
        self.accounts.browser_client = Mock()
        self.accounts.receipt_reader = Mock(return_value=evidence)
        self.accounts.refresh_account("moark")
        self.accounts.receipt_reader.assert_called_once_with("moark", "sumika-native", self.accounts.closed)
        self.assertTrue(self.accounts.ledger.status()["reservations"][-1]["absorbed"])
        self.accounts.receipt_reader = None
        with patch("sumika_core.integrations.account_portals.AccountPortalReader.read_receipts") as reader:
            self.accounts.refresh_account("moark")
            reader.assert_not_called()
        self.assertEqual(self.accounts.receipt_status["moark"]["state"], "needs-review")

    def test_native_receipt_failures_keep_fixed_reason_and_never_reconcile_partial_evidence(self):
        evidence = self._moark_request()
        self.accounts.bind_receipt_portal("moark", "sumika-native")
        self.accounts.browser_client = Mock()
        for reason in ("official-log-forbidden", "invalid-log-schema", "official-log-read-timeout", "profile-resource-unavailable"):
            self.accounts.receipt_reader = Mock(return_value={**evidence, "state": "needs-review", "reason": reason,
                                                              "body": "private-receipt-content"})
            with patch("sumika_core.integrations.account_portals.AccountPortalReader.read_receipts") as legacy:
                self.accounts.refresh_account("moark")
                legacy.assert_not_called()
            self.assertEqual(self.accounts.receipt_status["moark"], {"state": "needs-review", "reason": reason})
            row = self.accounts.ledger.status()["reservations"][-1]
            self.assertEqual(row["estimated"], Decimal("0.05"))
            self.assertIsNone(row["actual"])
            self.assertFalse(row["absorbed"])
            self.assertNotIn("private", json.dumps(self.accounts.status()))

    def test_native_receipt_unknown_reason_and_exception_never_export_page_text(self):
        self._moark_request()
        self.accounts.bind_receipt_portal("moark", "sumika-native")
        for callback in (Mock(side_effect=ValueError("private-exception")),
                         Mock(return_value={"state": "needs-review", "reason": "private-page-content"}),
                         Mock(return_value={"state": "needs-review", "reason": "invalid-grant-row"}),
                         Mock(return_value={"state": "needs-review", "reason": ["official-log-forbidden"]}),
                         Mock(return_value={"state": "verified", "reason": "official-log-forbidden", "receipts": "private-malformed-evidence"})):
            self.accounts.receipt_reader = callback
            self.accounts.refresh_account("moark")
            self.assertEqual(self.accounts.receipt_status["moark"], {"state": "needs-review", "reason": "official-receipts-unavailable"})
            self.assertNotIn("private", json.dumps(self.accounts.status()))
            self.assertIsNone(self.accounts.ledger.status()["reservations"][-1]["actual"])

    def test_provider_captures_transport_trace_on_private_copy(self):
        from sumika_core.providers.openai_compatible import OpenAICompatibleProvider
        from sumika_core.integrations.account_sources import trace_fingerprint
        import io
        provider = OpenAICompatibleProvider(base_url="https://api.deepseek.com/v1", model="fixture")
        response = io.BytesIO(json.dumps({"model": "fixture", "choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 2, "completion_tokens": 1}}).encode())
        response.headers = {"Content-Type": "application/json", "x-ds-trace-id": "transport-fixture"}
        with patch.object(provider, "_open", return_value=response):
            runtime = self.accounts.wrap(provider, "deepseek", "fixture")
            self.assertIsNot(runtime.provider, provider)
            self.assertEqual(list(runtime.stream(ChatRequest("session", [Message("user", "hello")], max_tokens=100))), ["ok"])
        rows = self.accounts.ledger.match_request_trace("deepseek", self.accounts.bindings()["deepseek"]["account_revision"],
                                                        trace_fingerprint("transport-fixture"), "fixture")
        self.assertTrue(rows)
        self.assertNotIn("transport-fixture", json.dumps(self.accounts.status()))

    def test_same_wrapper_concurrency_rejects_before_reset_or_send(self):
        from sumika_core.providers.openai_compatible import OpenAICompatibleProvider
        from sumika_core.integrations.account_sources import trace_fingerprint
        import io
        calls = []
        def open_response(provider, http_request):
            label = json.loads(http_request.data)["messages"][0]["content"]
            calls.append(label)
            payload = {"model": "fixture", "choices": [{"delta": {"content": label}}],
                       "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
            response = io.BytesIO(("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n").encode())
            response.headers = {"Content-Type": "text/event-stream", "x-ds-trace-id": label}
            return response
        provider = OpenAICompatibleProvider(base_url="https://api.deepseek.com/v1", model="fixture")
        request = lambda label: ChatRequest("session", [Message("user", label)], max_tokens=100)
        with patch.object(OpenAICompatibleProvider, "_open", new=open_response):
            runtime = self.accounts.wrap(provider, "deepseek", "fixture")
            first = runtime.stream(request("first"))
            self.addCleanup(first.close)
            self.assertEqual(next(first), "first")
            active_usage = dict(runtime.last_usage)
            trace = runtime._trace_fingerprint
            reservations_before = self.accounts.ledger.status()["reservations"]
            with ThreadPoolExecutor(max_workers=1) as executor:
                rejected = executor.submit(lambda: list(runtime.stream(request("second"))))
                with self.assertRaisesRegex(RequestNotSent, "active stream"):
                    rejected.result(timeout=5)
            self.assertEqual(runtime.last_usage, active_usage)
            self.assertEqual(runtime._trace_fingerprint, trace)
            self.assertEqual(self.accounts._active_operations, 1)
            self.assertEqual(self.accounts.ledger.status()["reservations"], reservations_before)
            self.assertEqual(calls, ["first"])
            self.assertEqual(list(first), [])
            self.assertEqual(runtime.last_charge_receipt["estimated_provider_cny"], "0.003")
            revision = self.accounts.bindings()["deepseek"]["account_revision"]
            self.assertTrue(self.accounts.ledger.match_request_trace("deepseek", revision, trace_fingerprint("first"), "fixture"))
            self.assertEqual(self.accounts.ledger.match_request_trace("deepseek", revision, trace_fingerprint("second"), "fixture"), [])
            self.assertEqual(list(runtime.stream(request("second"))), ["second"])
            self.assertEqual(calls, ["first", "second"])

    def test_different_wrappers_overlap_without_trace_or_usage_cross_talk(self):
        from sumika_core.providers.openai_compatible import OpenAICompatibleProvider
        from sumika_core.integrations.account_sources import trace_fingerprint
        import io
        def open_response(provider, http_request):
            label = json.loads(http_request.data)["messages"][0]["content"]
            tokens = 20 if label == "first" else 50
            payload = {"model": "fixture", "choices": [{"delta": {"content": label}}],
                       "usage": {"prompt_tokens": tokens, "completion_tokens": 10}}
            response = io.BytesIO(("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n").encode())
            response.headers = {"Content-Type": "text/event-stream", "x-ds-trace-id": label}
            return response
        provider = OpenAICompatibleProvider(base_url="https://api.deepseek.com/v1", model="fixture")
        request = lambda label: ChatRequest("session", [Message("user", label)], max_tokens=100)
        with patch.object(OpenAICompatibleProvider, "_open", new=open_response):
            first_runtime = self.accounts.wrap(provider, "deepseek", "fixture")
            second_runtime = self.accounts.wrap(provider, "deepseek", "fixture")
            first = first_runtime.stream(request("first"))
            self.addCleanup(first.close)
            self.assertEqual(next(first), "first")
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(lambda: list(second_runtime.stream(request("second"))))
                self.assertEqual(result.result(timeout=5), ["second"])
            self.assertEqual(first_runtime.last_usage["input_tokens"], 20)
            self.assertEqual(second_runtime.last_usage["input_tokens"], 50)
            self.assertEqual(list(first), [])
        revision = self.accounts.bindings()["deepseek"]["account_revision"]
        first_rows = self.accounts.ledger.match_request_trace("deepseek", revision, trace_fingerprint("first"), "fixture")
        second_rows = self.accounts.ledger.match_request_trace("deepseek", revision, trace_fingerprint("second"), "fixture")
        self.assertEqual(sum((row["estimated"] for row in first_rows), Decimal(0)), Decimal("0.003"))
        self.assertEqual(sum((row["estimated"] for row in second_rows), Decimal(0)), Decimal("0.006"))
        self.assertNotEqual(first_rows[0]["request_id"], second_rows[0]["request_id"])
        self.assertEqual(provider.last_usage, {})
        self.assertEqual(self.accounts._active_operations, 0)

    def test_stream_lock_releases_on_close_preflight_failure_and_upstream_failure(self):
        provider = SimpleNamespace(timeout=10, last_usage={}, stream=lambda request: iter(["first", "second"]))
        runtime = self.accounts.wrap(provider, "deepseek", "fixture")
        request = ChatRequest("session", [Message("user", "hello")], max_tokens=100)
        stream = runtime.stream(request)
        self.assertEqual(next(stream), "first")
        stream.close()
        self.assertEqual(list(runtime.stream(request)), ["first", "second"])
        with patch.object(self.accounts, "begin_operation", side_effect=RequestNotSent("closed")):
            with self.assertRaisesRegex(RequestNotSent, "closed"):
                list(runtime.stream(request))
        with patch.object(provider, "stream", side_effect=TimeoutError("upstream")):
            with self.assertRaisesRegex(TimeoutError, "upstream"):
                list(runtime.stream(request))
        self.assertEqual(list(runtime.stream(request)), ["first", "second"])
        self.assertEqual(self.accounts._active_operations, 0)

    def test_unknown_send_holds_and_unsent_releases(self):
        def failed(request):
            raise TimeoutError("upstream")
            yield
        provider = SimpleNamespace(timeout=10, last_usage={}, stream=failed)
        with self.assertRaises(TimeoutError):
            list(self.accounts.wrap(provider, "deepseek", "fixture").stream(ChatRequest("session", [Message("user", "hello")], max_tokens=2)))
        self.assertEqual(self.accounts.ledger.status()["reservations"][0]["state"], "unknown")
        def unsent(request):
            raise RequestNotSent("not submitted")
            yield
        provider.stream = unsent
        with self.assertRaises(RequestNotSent):
            list(self.accounts.wrap(provider, "deepseek", "fixture").stream(ChatRequest("session", [Message("user", "hello")], max_tokens=2)))
        self.assertEqual(self.accounts.ledger.status()["reservations"][-1]["state"], "released")

    def test_inflight_price_change_preserves_submitted_price(self):
        def stream(request):
            self.pricing.store.replace_profile("deepseek", [replace(self.price, input_price_per_million=0, output_price_per_million=0)])
            yield "ok"
        provider = SimpleNamespace(timeout=10, last_usage={"input_tokens": 20, "output_tokens": 30}, stream=stream)
        runtime = self.accounts.wrap(provider, "deepseek", "fixture")
        list(runtime.stream(ChatRequest("session", [Message("user", "hello")], max_tokens=100)))
        self.assertEqual(runtime.last_charge_receipt["estimated_provider_cny"], "0.005")
        self.assertEqual(runtime.last_charge_receipt["pricing_ref"], "price")

    def test_missing_zero_negative_and_boolean_usage_preserve_reservation(self):
        for usage in ({}, {"input_tokens": 0, "output_tokens": 0}, {"input_tokens": -1, "output_tokens": 2},
                      {"input_tokens": True, "output_tokens": 2}, {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 2}):
            with self.subTest(usage=usage):
                self.accounts.errors.clear()
                provider = SimpleNamespace(timeout=10, last_usage=usage, stream=lambda request: iter(["ok"]))
                runtime = self.accounts.wrap(provider, "deepseek", "fixture")
                list(runtime.stream(ChatRequest("session", [Message("user", "hello")], max_tokens=10)))
                self.assertIsNone(runtime.last_charge_receipt["estimated_provider_cny"])
                identifiers = runtime.last_charge_receipt["reservation_ids"]
                rows = [row for row in self.accounts.ledger.status()["reservations"] if row["request_id"] in identifiers]
                self.assertTrue(rows)
                self.assertTrue(all(row["estimated"] is None and row["state"] == "unknown" for row in rows))

    def test_close_rejects_new_work_but_allows_active_stream_to_settle(self):
        provider = SimpleNamespace(timeout=10, last_usage={"input_tokens": 20, "output_tokens": 30},
                                   stream=lambda request: iter(["first", "second"]))
        runtime = self.accounts.wrap(provider, "deepseek", "fixture")
        request = ChatRequest("session", [Message("user", "hello")], max_tokens=100)
        stream = runtime.stream(request)
        self.assertEqual(next(stream), "first")
        self.accounts.close()
        with self.assertRaises(RequestNotSent):
            list(runtime.stream(request))
        self.assertEqual(list(stream), ["second"])
        ledger = FundingLedger(self.accounts._data_dir)
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.status()["reservations"][0]["estimated"], Decimal("0.005"))

    def test_close_during_preflight_prevents_send_and_releases(self):
        ledger = self.accounts.ledger
        reserve = ledger.reserve_bundle
        def closing_reserve(*args, **kwargs):
            result = reserve(*args, **kwargs)
            self.accounts.close()
            return result
        provider = SimpleNamespace(timeout=10, last_usage={}, stream=Mock())
        with patch.object(ledger, "reserve_bundle", side_effect=closing_reserve), self.assertRaises(RequestNotSent):
            list(self.accounts.wrap(provider, "deepseek", "fixture").stream(ChatRequest("session", [Message("user", "hello")], max_tokens=100)))
        provider.stream.assert_not_called()
        reopened = FundingLedger(self.accounts._data_dir)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.status()["reservations"][0]["state"], "released")

    def test_settlement_error_does_not_replace_upstream_error(self):
        def failed(request):
            raise TimeoutError("upstream")
            yield
        provider = SimpleNamespace(timeout=10, last_usage={}, stream=failed)
        with patch.object(self.accounts.ledger, "settle", side_effect=ValueError("ledger")), self.assertRaisesRegex(TimeoutError, "upstream"):
            list(self.accounts.wrap(provider, "deepseek", "fixture").stream(ChatRequest("session", [Message("user", "hello")], max_tokens=10)))
        self.assertEqual(self.accounts.errors["deepseek"], "settlement-failed")

    def test_purchased_package_identity_change_does_not_reclassify(self):
        self.profiles.save({"id": "moark", "name": "Moark", "base_url": "https://api.moark.com/v1", "model": "fixture"})
        with self.assertRaises(ValueError):
            self.accounts.bind("moark", "moark", ["fixture"], funding_kind="purchased", unit_value_cny="1", evidence="paid-order")
        self.accounts.bind("moark", "moark", ["fixture"], funding_kind="purchased", unit_value_cny="1",
                           evidence="paid-order", package_fingerprints=["a" * 64])
        self.reader_mock.return_value = {"balance": "10", "package_fingerprints": ["b" * 64]}
        self.accounts.refresh(force=True)
        self.assertIn("moark", self.accounts.errors)


class AccountSourceTests(unittest.TestCase):
    def test_deepseek_price_versions_peak_and_cache(self):
        text = "deepseek-v4-flash deepseek-v4-pro deepseek-v4-flash-vision-exp 北京时间周一至周五 9:00 - 12:00、14:00 - 18:00 "
        text += "模型版本 DeepSeek-V4-Flash-0731 DeepSeek-V4-Pro-0813 DeepSeek-V4-Flash-Vision-Exp "
        text += "空闲时段 0.05元 0.15元 0.05元 高峰时段 0.1元 0.3元 0.1元 "
        text += "空闲时段 1.5元 4.5元 1.5元 高峰时段 3元 9元 3元 "
        text += "空闲时段 4.5元 13.5元 4.5元 高峰时段 9元 27元 9元"
        prices, versions = parse_deepseek_prices(text, "official")
        self.assertEqual(prices[1].input_price_per_million, 9)
        self.assertEqual(prices[1].cache_read_price_per_million, 0.3)
        self.assertEqual(versions["deepseek-v4-pro"], "DeepSeek-V4-Pro-0813")
        with self.assertRaises(ValueError):
            parse_deepseek_prices(text.replace("27元", "13.5元"), "official")

    def test_account_source_reconciles_and_never_follows_redirect(self):
        runtime = SimpleNamespace(base_url="https://api.deepseek.com/v1", _request_headers=Mock(return_value={}))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = "https://api.deepseek.com/user/balance"
        raw = {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "1", "granted_balance": "0.2", "topped_up_balance": "0.8"}]}
        response.read.return_value = json.dumps(raw).encode()
        with patch("sumika_core.integrations.account_sources.build_opener") as opener:
            opener.return_value.open.return_value = response
            self.assertEqual(read_account("deepseek", runtime)["cash"], "0.8")
            response.geturl.return_value = "https://relay.example/account"
            with self.assertRaises(ValueError):
                read_account("deepseek", runtime)


if __name__ == "__main__":
    unittest.main()
