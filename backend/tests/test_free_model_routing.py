"""Offline contract tests; public collection and provider transport are fixtures."""

import copy
import sys
import tempfile
import threading
import unittest
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from sumika_core.free_model_routing import FreeModelRouting
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.provider_profiles import provider_account_revision
from sumika_core.providers.guard import RequestNotSent


MODEL = "glm-4.5-flash"
OTHER_MODEL = "glm-4.7-flash"
ENDPOINTS = {
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "openrouter": "https://openrouter.ai/api/v1",
}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    def stamp(self, offset=0):
        return datetime.fromtimestamp(self.now + offset, timezone.utc).isoformat()


class Profiles:
    def __init__(self):
        self.rows = {}
        self.lock = threading.RLock()

    def add(self, profile_id, provider_id="zhipu"):
        with self.lock:
            self.rows[profile_id] = {
                "id": profile_id,
                "adapter_id": "openai-compatible",
                "template_id": provider_id,
                "processing_location": "cloud",
                "status": "available",
                "has_secrets": True,
                "config": {
                    "active_base_url": ENDPOINTS[provider_id],
                    "credential_revision": "a" * 32,
                    "models": [{"id": MODEL}, {"id": OTHER_MODEL}],
                },
            }

    def get(self, profile_id):
        with self.lock:
            return copy.deepcopy(self.rows[profile_id])

    def update(self, profile_id, *, config=None, **fields):
        with self.lock:
            self.rows[profile_id].update(fields)
            self.rows[profile_id]["config"].update(config or {})


class Provider:
    def __init__(self, *, error=None, pieces=("answer",), finish_reason="stop", response_model=MODEL,
                 entered=None, proceed=None):
        self.calls = []
        self.lock = threading.Lock()
        self.error = error
        self.pieces = pieces
        self.last_finish_reason = finish_reason
        self.last_response_model = response_model
        self.last_response_model_mismatch = False
        self.entered = entered
        self.proceed = proceed
        self.health_check = Mock(side_effect=AssertionError("unexpected provider probe"))

    def stream(self, request):
        with self.lock:
            self.calls.append(copy.deepcopy(request))
        if self.entered is not None:
            self.entered.set()
        if self.proceed is not None and not self.proceed.wait(5):
            raise AssertionError("test did not release provider")
        if self.error is not None:
            raise self.error
        yield from self.pieces


class FreeModelRoutingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.profiles = Profiles()
        self.profiles.add("first")
        self.profiles.add("second")
        self.sources = {provider_id: self.snapshot(provider_id) for provider_id in ENDPOINTS}
        self.collector = Mock(side_effect=lambda provider_id: copy.deepcopy(self.sources[provider_id]))
        source_module = ModuleType("sumika_core.integrations.free_model_sources")
        source_module.PROVIDER_ENDPOINTS = ENDPOINTS
        source_module.fetch_free_models = Mock(side_effect=AssertionError("unexpected public fetch"))
        self.addCleanup(source_module.fetch_free_models.assert_not_called)
        source_patch = patch.dict(sys.modules, {source_module.__name__: source_module})
        source_patch.start()
        self.addCleanup(source_patch.stop)
        for target in ("socket.create_connection", "socket.socket.connect"):
            network_patch = patch(target, side_effect=AssertionError("network disabled in offline tests"))
            network_patch.start()
            self.addCleanup(network_patch.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = self.make_manager()
        self.provider = Provider()
        self.request = ChatRequest("offline-session", [Message("user", "hello")], max_tokens=64)

    def snapshot(self, provider_id="zhipu", **overrides):
        return {
            "provider_id": provider_id,
            "source_url": ENDPOINTS[provider_id] + "/models",
            "observed_at": self.clock.stamp(),
            "models": [MODEL, OTHER_MODEL],
            "complete": True,
            "mode": "zero-price",
            "ttl_seconds": 3600,
            **overrides,
        }

    def make_manager(self, data_dir=None):
        manager = FreeModelRouting(self.profiles, data_dir, collector=self.collector, clock=self.clock)
        self.addCleanup(manager.close)
        return manager

    def evaluate(self, profile_id="first", model_id=MODEL, *, manager=None, passed=True):
        (manager or self.manager).record_evaluation(
            profile_id, model_id, passed=passed,
            revision=provider_account_revision(self.profiles.get(profile_id)),
        )

    def ready(self, profile_id="first", provider_id="zhipu", *, manager=None):
        manager = manager or self.manager
        manager.enroll(profile_id, provider_id)
        manager.refresh(profile_id, force=True)
        self.evaluate(profile_id, manager=manager)
        self.assertTrue(manager.projection(profile_id, MODEL)["routable"])
        return manager.wrap(self.provider, profile_id, MODEL)

    def assert_blocked(self, wrapped, *, provider=None, request=None):
        provider = provider or self.provider
        calls_before = len(provider.calls)
        with self.assertRaises(RequestNotSent):
            list(wrapped.stream(request or self.request))
        self.assertEqual(len(provider.calls), calls_before, "preflight rejection must not dispatch")

    def profile_status(self, profile_id="first", *, manager=None):
        return next(row for row in (manager or self.manager).status()["profiles"]
                    if row["provider_profile_id"] == profile_id)

    def test_unenrolled_profile_has_no_free_projection(self):
        self.assertIsNone(self.manager.projection("first", MODEL))
        self.assertFalse(self.manager.manages("first"))
        self.assertIs(self.manager.wrap(self.provider, "first", MODEL), self.provider)
        self.collector.assert_not_called()

    def test_enrollment_requires_exact_official_endpoint(self):
        for endpoint in (
            "https://relay.invalid/v1",
            "https://open.bigmodel.cn.attacker.invalid/api/paas/v4",
            "https://open.bigmodel.cn/api/paas/v4/paid",
            "https://open.bigmodel.cn/api/paas/v4?account=other",
            "http://open.bigmodel.cn/api/paas/v4",
        ):
            with self.subTest(endpoint=endpoint):
                self.profiles.update("first", config={"active_base_url": endpoint})
                with self.assertRaises(ValueError):
                    self.manager.enroll("first", "zhipu")
                self.assertFalse(self.manager.manages("first"))
        self.collector.assert_not_called()

    def test_enrollment_rejects_custom_account_scopes(self):
        for field, value in (("headers", {"X-Account": "other"}),
                             ("organization", "other"), ("project", "other")):
            with self.subTest(field=field):
                self.profiles.add("first")
                self.profiles.update("first", config={field: value})
                with self.assertRaises(ValueError):
                    self.manager.enroll("first", "zhipu")
                self.assertFalse(self.manager.manages("first"))

    def test_enrollment_requires_active_credentials_and_boolean_confirmation(self):
        for fields in ({"has_secrets": False}, {"archived_at": self.clock.stamp()}):
            with self.subTest(fields=fields):
                self.profiles.add("first")
                self.profiles.update("first", **fields)
                with self.assertRaises(ValueError):
                    self.manager.enroll("first", "zhipu")
        self.profiles.add("first")
        for confirmation in (1, "true", None):
            with self.subTest(confirmation=confirmation), self.assertRaises(ValueError):
                self.manager.enroll("first", "zhipu", free_key_confirmed=confirmation)
        self.assertFalse(self.manager.manages("first"))

    def test_only_successful_account_bound_evaluation_admits_regular_requests(self):
        self.manager.enroll("first", "zhipu")
        self.assertFalse(self.manager.projection("first", MODEL)["zero_cash"])
        self.manager.refresh("first")
        projection = self.manager.projection("first", MODEL)
        self.assertTrue(projection["zero_cash"])
        self.assertFalse(projection["routable"])
        self.assertIn(projection["reason"], {"fixed-evaluation-required", "execution-binding-changed"})
        wrapped = self.manager.wrap(self.provider, "first", MODEL)
        self.assert_blocked(wrapped)
        self.manager.feedback("first", MODEL, successful=True)
        self.assert_blocked(wrapped)
        self.evaluate(passed=False)
        self.assert_blocked(wrapped)
        self.evaluate()
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])
        self.assertEqual(len(self.provider.calls), 1)
        self.assertFalse(self.manager.projection("first", OTHER_MODEL)["routable"])

    def test_evaluation_requests_do_not_implicitly_promote_a_model(self):
        self.manager.enroll("first", "zhipu")
        self.manager.refresh("first")
        wrapped = self.manager.wrap(self.provider, "first", MODEL, evaluation=True)
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])
        self.assert_blocked(self.manager.wrap(self.provider, "first", MODEL))

    def test_evaluation_rejects_wrong_revision_and_nonboolean_results(self):
        self.manager.enroll("first", "zhipu")
        self.manager.refresh("first")
        with self.assertRaises(ValueError):
            self.manager.record_evaluation("first", MODEL, passed=True, revision="another-account")
        for passed in (1, "true", None):
            with self.subTest(passed=passed), self.assertRaises(ValueError):
                self.evaluate(passed=passed)
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])

    def test_source_failure_retains_history_without_claiming_free_or_sending(self):
        wrapped = self.ready()
        previous = self.profile_status()["source"]
        self.collector.side_effect = OSError("public source unavailable")
        self.manager.refresh("first", force=True)
        status = self.profile_status()
        self.assertEqual(status["source"], previous)
        self.assertEqual(status["state"], "needs-review")
        projection = self.manager.projection("first", MODEL)
        self.assertFalse(projection["routable"])
        self.assertFalse(projection["zero_cash"])
        self.assert_blocked(wrapped)
        self.assertEqual(self.manager.status()["refresh_model_calls"], 0)

    def test_source_expires_at_exact_ttl_and_stale_refresh_cannot_restore_it(self):
        wrapped = self.ready()
        self.clock.advance(3599)
        self.assertTrue(self.manager.projection("first", MODEL)["routable"])
        self.clock.advance(1)
        projection = self.manager.projection("first", MODEL)
        self.assertEqual(projection["reason"], "price-stale")
        self.assertFalse(projection["zero_cash"])
        self.assert_blocked(wrapped)
        self.assertEqual(self.profile_status()["state"], "needs-review")

    def test_price_withdrawal_and_partial_missing_evidence_stop_existing_runtime(self):
        wrapped = self.ready()
        for complete, reason in ((True, "free-evidence-withdrawn"), (False, "free-evidence-missing")):
            with self.subTest(complete=complete):
                self.sources["zhipu"] = self.snapshot(models=[OTHER_MODEL], complete=complete)
                self.manager.refresh("first", force=True)
                projection = self.manager.projection("first", MODEL)
                self.assertFalse(projection["routable"])
                self.assertFalse(projection["zero_cash"])
                self.assertEqual(projection["reason"], reason)
                self.assert_blocked(wrapped)

    def test_invalid_source_evidence_never_admits_a_previously_qualified_model(self):
        wrapped = self.ready()
        invalid = (
            {"provider_id": "openrouter"}, {"complete": 1}, {"ttl_seconds": True},
            {"ttl_seconds": 0}, {"ttl_seconds": 43201}, {"mode": "paid"},
            {"observed_at": "2026-09-08T00:00:00"},
            {"observed_at": self.clock.stamp(1)},
            {"observed_at": self.clock.stamp(-3600)},
            {"models": [MODEL, MODEL]}, {"models": [MODEL, None]},
            {"models": ["model\nother"]}, {"models": MODEL},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                self.sources["zhipu"] = self.snapshot(**overrides)
                self.manager.refresh("first", force=True)
                projection = self.manager.projection("first", MODEL)
                self.assertFalse(projection["zero_cash"])
                self.assertFalse(projection["routable"])
                self.assert_blocked(wrapped)

    def test_allowance_and_unconfirmed_free_key_are_not_zero_cash_routes(self):
        for mode, reason in (("allowance", "account-allowance-binding-required"),
                             ("free-key", "free-key-confirmation-required")):
            with self.subTest(mode=mode):
                self.manager.enroll("first", "zhipu")
                self.sources["zhipu"] = self.snapshot(mode=mode)
                self.manager.refresh("first", force=True)
                self.evaluate()
                projection = self.manager.projection("first", MODEL)
                self.assertFalse(projection["zero_cash"])
                self.assertEqual(projection["reason"], reason)
                self.assert_blocked(self.manager.wrap(self.provider, "first", MODEL))

    def test_confirmed_free_key_still_needs_a_fixed_evaluation(self):
        self.manager.enroll("first", "zhipu", free_key_confirmed=True)
        self.sources["zhipu"] = self.snapshot(mode="free-key")
        self.manager.refresh("first")
        wrapped = self.manager.wrap(self.provider, "first", MODEL)
        self.assert_blocked(wrapped)
        self.evaluate()
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_independent_profiles_of_same_provider_keep_separate_snapshots_and_evaluations(self):
        self.ready()
        self.manager.enroll("second", "zhipu")
        self.sources["zhipu"] = self.snapshot(models=[OTHER_MODEL])
        self.manager.refresh("second", force=True)
        self.assertTrue(self.manager.projection("first", MODEL)["routable"])
        self.assertFalse(self.manager.projection("second", MODEL)["zero_cash"])
        self.assertFalse(self.manager.projection("second", OTHER_MODEL)["routable"])
        self.evaluate("second", OTHER_MODEL)
        self.assertTrue(self.manager.projection("second", OTHER_MODEL)["routable"])
        self.collector.side_effect = OSError("first account refresh failed")
        self.manager.refresh("first", force=True)
        self.assertFalse(self.manager.projection("first", MODEL)["zero_cash"])
        self.assertTrue(self.manager.projection("second", OTHER_MODEL)["routable"])
        self.assertEqual(self.profile_status("second")["source"]["models"], [OTHER_MODEL])

    def test_refresh_all_continues_after_one_provider_fails(self):
        self.profiles.add("second", "openrouter")
        self.ready()
        self.ready("second", "openrouter")

        def collect(provider_id):
            if provider_id == "zhipu":
                raise OSError("source down")
            return self.snapshot(provider_id)

        self.collector.side_effect = collect
        self.manager.refresh(force=True)
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])
        self.assertTrue(self.manager.projection("second", MODEL)["routable"])

    def test_refresh_is_throttled_per_profile_and_can_be_forced(self):
        self.ready()
        self.manager.enroll("second", "zhipu")
        self.manager.refresh("first")
        self.collector.assert_called_once_with("zhipu")
        self.manager.refresh("second")
        self.assertEqual(self.collector.call_count, 2)
        self.manager.refresh("first", force=True)
        self.assertEqual(self.collector.call_count, 3)

    def test_credential_rotation_invalidates_old_evaluation_and_existing_runtime(self):
        wrapped = self.ready()
        old_revision = provider_account_revision(self.profiles.get("first"))
        self.profiles.update("first", config={"credential_revision": "b" * 32})
        self.assertFalse(self.manager.projection("first", MODEL)["zero_cash"])
        self.assert_blocked(wrapped)
        with self.assertRaises(ValueError):
            self.manager.record_evaluation("first", MODEL, passed=True, revision=old_revision)
        self.manager.enroll("first", "zhipu")
        self.manager.refresh("first", force=True)
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])
        with self.assertRaises(ValueError):
            self.manager.record_evaluation("first", MODEL, passed=True, revision=old_revision)
        self.evaluate()
        self.assert_blocked(wrapped)
        replacement = self.manager.wrap(self.provider, "first", MODEL)
        self.assertEqual(list(replacement.stream(self.request)), ["answer"])

    def test_existing_runtime_rechecks_endpoint_archive_and_secret_removal(self):
        for changes in (
            {"config": {"active_base_url": "https://relay.invalid/v1"}},
            {"archived_at": self.clock.stamp()},
            {"has_secrets": False},
            {"config": {"headers": {"X-Account": "other"}}},
            {"config": {"organization": "other"}},
            {"config": {"project": "other"}},
        ):
            with self.subTest(changes=changes):
                self.profiles.add("first")
                wrapped = self.ready()
                self.profiles.update("first", **changes)
                self.assert_blocked(wrapped)
                self.assertFalse(self.manager.projection("first", MODEL)["zero_cash"])

    def test_model_version_change_invalidates_quality_and_old_runtime_even_after_reevaluation(self):
        wrapped = self.ready()
        self.profiles.update("first", config={"models": [{"id": MODEL, "version": "new-version"}]})
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])
        self.assert_blocked(wrapped)
        self.evaluate()
        self.assertTrue(self.manager.projection("first", MODEL)["routable"])
        self.assert_blocked(wrapped)
        self.assertEqual(list(self.manager.wrap(self.provider, "first", MODEL).stream(self.request)), ["answer"])

    def test_display_metadata_does_not_invalidate_evaluation(self):
        wrapped = self.ready()
        self.profiles.update("first", name="Renamed profile", config={"models": [
            {"id": MODEL, "name": "Friendly label", "health_state": "healthy",
             "last_tested_at": self.clock.stamp()}, {"id": OTHER_MODEL},
        ]})
        self.assertTrue(self.manager.projection("first", MODEL)["routable"])
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_unavailable_profile_blocks_regular_routes_but_allows_explicit_evaluation(self):
        wrapped = self.ready()
        self.profiles.update("first", status="unavailable")
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])
        self.assert_blocked(wrapped)
        evaluation = self.manager.wrap(self.provider, "first", MODEL, evaluation=True)
        self.assertEqual(list(evaluation.stream(self.request)), ["answer"])
        self.assertFalse(self.manager.projection("first", MODEL)["routable"])

    def test_disabled_or_removed_model_cannot_be_sent_by_existing_runtime(self):
        wrapped = self.ready()
        for models in ([{"id": MODEL, "enabled": False}], [{"id": OTHER_MODEL}]):
            with self.subTest(models=models):
                self.profiles.update("first", config={"models": models})
                self.assert_blocked(wrapped)
                self.assertEqual(self.manager.projection("first", MODEL)["reason"], "model-disabled")

    def test_tools_and_explicit_reasoning_settings_never_dispatch(self):
        wrapped = self.ready()
        for effort in ("none", "minimal", "low", "medium", "high", ""):
            with self.subTest(reasoning_effort=effort):
                request = copy.deepcopy(self.request)
                request.reasoning_effort = effort
                self.assert_blocked(wrapped, request=request)
        request = copy.deepcopy(self.request)
        request.tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
        self.assert_blocked(wrapped, request=request)
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_output_token_bounds_reject_invalid_values_without_reserving_account(self):
        wrapped = self.ready()
        for max_tokens in (None, True, False, 0, -1, 2049, 64.0, "64"):
            with self.subTest(max_tokens=max_tokens):
                request = copy.deepcopy(self.request)
                request.max_tokens = max_tokens
                self.assert_blocked(wrapped, request=request)
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_input_bound_counts_utf8_bytes_across_all_messages(self):
        wrapped = self.ready()
        for contents in (("x" * 16001,), ("界" * 5334,), ("x" * 8000, "y" * 8001),
                         ([{"type": "image_url", "image_url": {"url": "https://image.invalid"}}],)):
            with self.subTest(lengths=[len(content) for content in contents]):
                request = copy.deepcopy(self.request)
                request.messages = [Message("user", content) for content in contents]
                self.assert_blocked(wrapped, request=request)
        request = copy.deepcopy(self.request)
        request.messages = [Message("user", "界" * 5333 + "x")]
        request.max_tokens = 2048
        self.assertEqual(list(wrapped.stream(request)), ["answer"])
        self.assertEqual(self.provider.calls[0].max_tokens, 2048)

    def test_passive_health_never_probes_or_evaluates_provider(self):
        self.manager.enroll("first", "zhipu")
        self.manager.refresh("first")
        wrapped = self.manager.wrap(self.provider, "first", MODEL)
        self.assertFalse(wrapped.health_check(allow_chat_probe=True)["ok"])
        self.evaluate()
        self.assertTrue(wrapped.health_check(allow_chat_probe=True)["ok"])
        self.provider.health_check.assert_not_called()
        self.assertEqual(self.provider.calls, [])

    def test_429_cools_down_without_retiring_or_replaying(self):
        self.ready()
        provider = Provider(error=HTTPError(ENDPOINTS["zhipu"], 429, "rate limited", {}, None))
        wrapped = self.manager.wrap(provider, "first", MODEL)
        with self.assertRaisesRegex(RuntimeError, "429"):
            list(wrapped.stream(self.request))
        self.assertEqual(len(provider.calls), 1)
        projection = self.manager.projection("first", MODEL)
        self.assertEqual(projection["reason"], "rate-limited")
        self.assertTrue(projection["zero_cash"])
        self.assertEqual(projection["retry_at"], self.clock() + 900)
        self.assert_blocked(wrapped, provider=provider)
        self.clock.advance(899)
        self.assert_blocked(wrapped, provider=provider)
        self.clock.advance(1)
        provider.error = None
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(self.manager.projection("first", MODEL)["routable"])

    def test_402_blocks_future_sends_even_after_refresh_and_successful_evaluation(self):
        self.ready()
        provider = Provider(error=HTTPError(ENDPOINTS["zhipu"], 402, "payment required", {}, None))
        wrapped = self.manager.wrap(provider, "first", MODEL)
        with self.assertRaisesRegex(RuntimeError, "402"):
            list(wrapped.stream(self.request))
        self.assertEqual(len(provider.calls), 1)
        self.assert_blocked(wrapped, provider=provider)
        self.clock.advance(1800)
        self.manager.refresh("first", force=True)
        self.evaluate()
        provider.error = None
        self.assert_blocked(wrapped, provider=provider)
        self.assertEqual(self.manager.projection("first", MODEL)["reason"], "account-entitlement-required")
        self.assertEqual(len(provider.calls), 1)

    def test_chained_http_error_preserves_429_cooldown_classification(self):
        self.ready()
        error = RuntimeError("provider transport failed")
        error.__cause__ = HTTPError(ENDPOINTS["zhipu"], 429, "rate limited", {}, None)
        provider = Provider(error=error)
        with self.assertRaisesRegex(RuntimeError, "429"):
            list(self.manager.wrap(provider, "first", MODEL).stream(self.request))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(self.manager.projection("first", MODEL)["reason"], "rate-limited")

    def test_uncertain_submission_is_not_replayed(self):
        self.ready()
        provider = Provider(error=TimeoutError("submission outcome unknown"))
        wrapped = self.manager.wrap(provider, "first", MODEL)
        with self.assertRaisesRegex(RuntimeError, "response-unconfirmed"):
            list(wrapped.stream(self.request))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(self.manager.projection("first", MODEL)["reason"], "submission-uncertain")
        self.assert_blocked(wrapped, provider=provider)

    def test_empty_truncated_and_oversized_responses_do_not_count_as_success(self):
        for pieces, finish_reason in (((), "stop"), (("partial",), "length"), (("x" * 32001,), "stop")):
            with self.subTest(size=sum(map(len, pieces)), finish_reason=finish_reason):
                manager = self.make_manager()
                self.ready(manager=manager)
                provider = Provider(pieces=pieces, finish_reason=finish_reason)
                wrapped = manager.wrap(provider, "first", MODEL)
                with self.assertRaises(RuntimeError):
                    list(wrapped.stream(self.request))
                self.assertEqual(len(provider.calls), 1)
                self.assertFalse(manager.projection("first", MODEL)["routable"])
                self.assert_blocked(wrapped, provider=provider)

    def test_missing_wrong_or_mismatched_model_echo_cannot_count_as_success(self):
        for response_model, mismatch in ((None, False), ("", False), (OTHER_MODEL, False),
                                         (MODEL.upper(), False), (MODEL, True)):
            with self.subTest(response_model=response_model, mismatch=mismatch):
                manager = self.make_manager()
                self.ready(manager=manager)
                provider = Provider(response_model=response_model)
                provider.last_response_model_mismatch = mismatch
                wrapped = manager.wrap(provider, "first", MODEL)
                with self.assertRaises(RuntimeError):
                    list(wrapped.stream(self.request))
                self.assertEqual(len(provider.calls), 1)
                self.assertFalse(manager.projection("first", MODEL)["routable"])
                self.assert_blocked(wrapped, provider=provider)

    def test_account_spacing_applies_across_models_but_not_independent_profiles(self):
        wrapped = self.ready()
        self.evaluate(model_id=OTHER_MODEL)
        second = self.ready("second")
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])
        other_provider = Provider(response_model=OTHER_MODEL)
        other_model = self.manager.wrap(other_provider, "first", OTHER_MODEL)
        self.assert_blocked(other_model, provider=other_provider)
        self.assertEqual(list(second.stream(self.request)), ["answer"])
        self.clock.advance(3)
        self.assert_blocked(other_model, provider=other_provider)
        self.clock.advance(1)
        self.assertEqual(list(other_model.stream(self.request)), ["answer"])

    def test_restart_preserves_snapshot_and_evaluation_without_collecting_again(self):
        manager = self.make_manager(self.directory.name)
        self.ready(manager=manager)
        previous = manager.projection("first", MODEL)
        snapshot = self.profile_status(manager=manager)["source"]
        manager.close()
        reopened = self.make_manager(self.directory.name)
        self.assertEqual(reopened.projection("first", MODEL), previous)
        self.assertEqual(self.profile_status(manager=reopened)["source"], snapshot)
        self.assertEqual(list(reopened.wrap(self.provider, "first", MODEL).stream(self.request)), ["answer"])
        self.collector.assert_called_once_with("zhipu")

    def test_restart_preserves_429_cooldown(self):
        manager = self.make_manager(self.directory.name)
        self.ready(manager=manager)
        provider = Provider(error=HTTPError(ENDPOINTS["zhipu"], 429, "limited", {}, None))
        with self.assertRaises(RuntimeError):
            list(manager.wrap(provider, "first", MODEL).stream(self.request))
        retry_at = manager.projection("first", MODEL)["retry_at"]
        manager.close()
        reopened = self.make_manager(self.directory.name)
        self.assertEqual(reopened.projection("first", MODEL)["retry_at"], retry_at)
        wrapped = reopened.wrap(self.provider, "first", MODEL)
        self.assert_blocked(wrapped)
        self.clock.advance(retry_at - self.clock())
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_restart_preserves_402_block_and_cannot_fall_back_to_raw_provider(self):
        manager = self.make_manager(self.directory.name)
        self.ready(manager=manager)
        provider = Provider(error=HTTPError(ENDPOINTS["zhipu"], 402, "payment required", {}, None))
        with self.assertRaises(RuntimeError):
            list(manager.wrap(provider, "first", MODEL).stream(self.request))
        manager.close()
        reopened = self.make_manager(self.directory.name)
        wrapped = reopened.wrap(self.provider, "first", MODEL)
        self.assertIsNot(wrapped, self.provider)
        self.assert_blocked(wrapped)
        self.clock.advance(1800)
        reopened.refresh("first", force=True)
        self.assert_blocked(wrapped)

    def test_restart_does_not_rebind_old_evidence_to_rotated_credentials(self):
        manager = self.make_manager(self.directory.name)
        self.ready(manager=manager)
        manager.close()
        self.profiles.update("first", config={"credential_revision": "b" * 32})
        reopened = self.make_manager(self.directory.name)
        self.assertFalse(reopened.projection("first", MODEL)["zero_cash"])
        self.assert_blocked(reopened.wrap(self.provider, "first", MODEL))

    def test_restart_keeps_inflight_account_reserved(self):
        manager = self.make_manager(self.directory.name)
        self.ready(manager=manager)
        manager.acquire("first", MODEL, self.request)
        manager.close()
        reopened = self.make_manager(self.directory.name)
        wrapped = reopened.wrap(self.provider, "first", MODEL)
        self.assert_blocked(wrapped)
        self.clock.advance(359)
        self.assert_blocked(wrapped)
        self.clock.advance(1)
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_explicit_entitlement_expiry_blocks_at_deadline_without_expiring_other_profiles(self):
        expiry = self.clock.stamp(60)
        self.manager.enroll("first", "zhipu", entitlement_expires_at=expiry)
        wrapped = self.ready()
        unaffected = self.ready("second")
        self.assertEqual(self.profile_status()["entitlement_expires_at"], expiry)
        self.clock.advance(59)
        self.assertTrue(self.manager.projection("first", MODEL)["routable"])
        self.clock.advance(1)
        for evaluation in (False, True):
            with self.subTest(evaluation=evaluation):
                projection = self.manager.projection("first", MODEL, evaluation=evaluation)
                self.assertFalse(projection["routable"])
                self.assertFalse(projection["zero_cash"])
                self.assertEqual(projection["reason"], "account-entitlement-expired")
        self.assert_blocked(wrapped)
        self.assert_blocked(self.manager.wrap(self.provider, "first", MODEL, evaluation=True))
        self.assertTrue(self.manager.projection("second", MODEL)["routable"])
        self.assertEqual(list(unaffected.stream(self.request)), ["answer"])

    def test_old_request_release_cannot_shorten_a_new_lease_on_same_account(self):
        wrapped = self.ready()
        old_stream = wrapped.stream(self.request)
        self.addCleanup(old_stream.close)
        self.assertEqual(next(old_stream), "answer")
        self.clock.advance(360)
        new_stream = wrapped.stream(self.request)
        self.addCleanup(new_stream.close)
        self.assertEqual(next(new_stream), "answer")
        old_stream.close()
        self.clock.advance(4)
        self.assert_blocked(wrapped)
        self.assertEqual(len(self.provider.calls), 2)
        new_stream.close()
        self.clock.advance(4)
        self.assert_blocked(wrapped)
        self.clock.advance(296)
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])
        self.assertEqual(len(self.provider.calls), 3)

    def assert_single_concurrent_dispatch(self, managers, models):
        start = threading.Barrier(2)
        entered = threading.Event()
        proceed = threading.Event()
        providers = [Provider(response_model=model_id, entered=entered, proceed=proceed) for model_id in models]
        wrapped = [manager.wrap(provider, "first", model_id)
                   for manager, model_id, provider in zip(managers, models, providers)]

        def dispatch(runtime):
            start.wait(5)
            try:
                return list(runtime.stream(self.request))
            except RequestNotSent:
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(dispatch, runtime) for runtime in wrapped]
            try:
                self.assertTrue(entered.wait(5), "one request should reach the provider")
                done, pending = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
                self.assertEqual(len(done), 1, "the other request must be rejected while one is in flight")
                self.assertEqual(next(iter(done)).result(), "blocked")
                self.assertEqual(len(pending), 1)
                self.assertEqual(sum(len(provider.calls) for provider in providers), 1)
            finally:
                proceed.set()
            results = [future.result(timeout=5) for future in futures]
        self.assertCountEqual(results, ["blocked", ["answer"]])
        self.assertEqual(sum(len(provider.calls) for provider in providers), 1)

    def test_simultaneous_requests_on_same_account_dispatch_once(self):
        self.ready()
        self.assert_single_concurrent_dispatch([self.manager, self.manager], [MODEL, MODEL])

    def test_simultaneous_requests_on_different_models_share_account_limit(self):
        self.ready()
        self.evaluate(model_id=OTHER_MODEL)
        self.assert_single_concurrent_dispatch([self.manager, self.manager], [MODEL, OTHER_MODEL])

    def test_simultaneous_hosts_sharing_sqlite_cannot_double_dispatch(self):
        manager = self.make_manager(self.directory.name)
        self.ready(manager=manager)
        second_host = self.make_manager(self.directory.name)
        self.assert_single_concurrent_dispatch([manager, second_host], [MODEL, MODEL])

    def test_price_withdrawal_between_projection_and_acquire_blocks_dispatch(self):
        wrapped = self.ready()
        original = self.manager.projection
        changed = False

        def withdraw_after_projection(*args, **kwargs):
            nonlocal changed
            projection = original(*args, **kwargs)
            if "evaluation" in kwargs and projection and projection["routable"] and not changed:
                changed = True
                self.sources["zhipu"] = self.snapshot(models=[])
                self.manager.refresh("first", force=True)
            return projection

        with patch.object(self.manager, "projection", side_effect=withdraw_after_projection):
            self.assert_blocked(wrapped)
        self.assertTrue(changed)
        self.assertFalse(self.manager.projection("first", MODEL)["zero_cash"])

    def test_disabling_model_between_projection_and_acquire_blocks_dispatch(self):
        wrapped = self.ready()
        original = self.manager.projection
        changed = False

        def disable_after_projection(*args, **kwargs):
            nonlocal changed
            projection = original(*args, **kwargs)
            if "evaluation" in kwargs and projection and projection["routable"] and not changed:
                changed = True
                self.profiles.update("first", config={"models": [{"id": MODEL, "enabled": False}]})
            return projection

        with patch.object(self.manager, "projection", side_effect=disable_after_projection):
            self.assert_blocked(wrapped)
        self.assertTrue(changed)

    def test_price_expiring_between_projection_and_acquire_blocks_dispatch(self):
        wrapped = self.ready()
        original = self.manager.projection
        changed = False

        def expire_after_projection(*args, **kwargs):
            nonlocal changed
            projection = original(*args, **kwargs)
            if "evaluation" in kwargs and projection and projection["routable"] and not changed:
                changed = True
                self.clock.advance(projection["expires_at"] - self.clock())
            return projection

        with patch.object(self.manager, "projection", side_effect=expire_after_projection):
            self.assert_blocked(wrapped)
        self.assertTrue(changed)

    def test_authenticated_health_expires_even_with_fresh_price_and_valid_quality(self):
        wrapped = self.ready()
        self.clock.advance(86400)
        self.sources["zhipu"] = self.snapshot()
        self.manager.refresh("first", force=True)
        projection = self.manager.projection("first", MODEL)
        self.assertFalse(projection["routable"])
        self.assertEqual(projection["reason"], "authenticated-health-expired")
        self.assert_blocked(wrapped)
        self.manager.feedback("first", MODEL, successful=True)
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_quality_expires_even_with_fresh_price_and_authenticated_health(self):
        wrapped = self.ready()
        self.clock.advance(7 * 86400)
        self.sources["zhipu"] = self.snapshot()
        self.manager.refresh("first", force=True)
        self.manager.feedback("first", MODEL, successful=True)
        projection = self.manager.projection("first", MODEL)
        self.assertFalse(projection["routable"])
        self.assertEqual(projection["reason"], "fixed-evaluation-required")
        self.assert_blocked(wrapped)
        self.evaluate()
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])

    def test_old_runtime_failure_cannot_block_reenrolled_account(self):
        self.ready()
        entered = threading.Event()
        proceed = threading.Event()
        provider = Provider(error=HTTPError(ENDPOINTS["zhipu"], 402, "old account exhausted", {}, None),
                            entered=entered, proceed=proceed)
        wrapped = self.manager.wrap(provider, "first", MODEL)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: list(wrapped.stream(self.request)))
            try:
                self.assertTrue(entered.wait(5))
                self.profiles.update("first", config={"credential_revision": "b" * 32})
                self.ready()
            finally:
                proceed.set()
            with self.assertRaises(RuntimeError):
                future.result(timeout=5)
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(self.manager.projection("first", MODEL)["routable"],
                        "a previous account's 402 must not block the new account")

    def test_old_refresh_cannot_overwrite_reenrolled_accounts_new_evidence(self):
        self.ready()
        entered = threading.Event()
        proceed = threading.Event()
        old_thread = None

        def collect(provider_id):
            if threading.get_ident() == old_thread:
                entered.set()
                if not proceed.wait(5):
                    raise AssertionError("test did not release old refresh")
                return self.snapshot(provider_id, models=[MODEL])
            return self.snapshot(provider_id, models=[OTHER_MODEL])

        def old_refresh():
            nonlocal old_thread
            old_thread = threading.get_ident()
            self.manager.refresh("first", force=True)

        self.collector.side_effect = collect
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(old_refresh)
            try:
                self.assertTrue(entered.wait(5))
                self.profiles.update("first", config={"credential_revision": "b" * 32})
                self.manager.enroll("first", "zhipu")
                self.manager.refresh("first", force=True)
                self.evaluate(model_id=OTHER_MODEL)
                self.assertTrue(self.manager.projection("first", OTHER_MODEL)["routable"])
            finally:
                proceed.set()
            future.result(timeout=5)
        self.assertEqual(self.profile_status()["source"]["models"], [OTHER_MODEL])
        self.assertTrue(self.manager.projection("first", OTHER_MODEL)["routable"],
                        "an obsolete refresh must not invalidate the new account's evidence")


if __name__ == "__main__":
    unittest.main()
