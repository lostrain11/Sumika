import tempfile
import unittest
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from sumika_core.model_refresh import RefreshCoordinator
from sumika_core.model_policy import ModelPolicyService
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.provider_profiles import provider_account_revision, provider_execution_revision
from sumika_core.providers.guard import RequestNotSent
from sumika_core.providers.resource_bound import ResourceBoundProvider


def observation(remaining=10000, authorized=True):
    return {
        "ok": True, "provider_profile_id": "official", "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://open.bigmodel.cn/finance/resourcepack", "source": "authenticated-page-dom",
        "account_scope_id": "test-account", "account_binding_verified": True, "automatic_routing_authorized": authorized,
        "packs": [{"pack_id": "shared", "name": "tokens", "status": "active", "applicability": "glm-4.7 glm-4.6v",
                   "available_balance": f"{remaining} tokens", "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}],
    }


class Provider:
    timeout = 30

    def __init__(self, fail=False, usage=True):
        self.calls = 0
        self.fail = fail
        self.usage = usage
        self.last_usage = {}

    def stream(self, request):
        self.calls += 1
        yield "answer"
        if self.fail:
            raise TimeoutError("response unknown")
        if self.usage:
            self.last_usage = {"input_tokens": 12, "output_tokens": 3}


class ResourceBoundTests(unittest.TestCase):
    def test_request_resource_uses_one_unit_per_completed_call(self):
        payload = observation()
        payload["packs"][0].update(available_balance="2 requests", funding_kind="grant")
        self.ledger.ingest_resources(payload)
        wrapped = self.wrapper()
        self.assertEqual(list(wrapped.stream(self.request)), ["answer"])
        self.assertEqual(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 1)
        self.assertEqual(wrapped.last_resource_receipt["unit"], "requests")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = RefreshCoordinator(self.directory.name)
        self.ledger.ingest_resources(observation())
        self.provider = Provider()
        self.request = ChatRequest("session", [Message("user", "hello")], max_tokens=64)

    def wrapper(self, provider=None, model="glm-4.7"):
        return ResourceBoundProvider(provider or self.provider, self.ledger, "official", model, lambda: None)

    def test_settles_actual_usage_and_shares_across_models(self):
        self.assertEqual(list(self.wrapper().stream(self.request)), ["answer"])
        self.assertEqual(self.ledger.quota_projection("glm-4.6v", "official")["remaining"], 9985)
        list(self.wrapper(model="glm-4.6v").stream(self.request))
        self.assertEqual(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 9970)

    def test_insufficient_allowance_never_sends_or_pays(self):
        self.ledger.ingest_resources(observation(1))
        with self.assertRaises(RequestNotSent):
            list(self.wrapper().stream(self.request))
        self.assertEqual(self.provider.calls, 0)

    def test_unknown_submission_is_reserved_across_restart(self):
        provider = Provider(fail=True)
        with self.assertRaises(TimeoutError):
            list(self.wrapper(provider).stream(self.request))
        self.ledger = RefreshCoordinator(self.directory.name)
        self.assertLess(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 9000)
        self.assertEqual(provider.calls, 1)

    def test_cancelled_stream_keeps_allowance(self):
        stream = self.wrapper().stream(self.request)
        self.assertEqual(next(stream), "answer")
        stream.close()
        self.assertLess(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 9000)

    def test_missing_usage_does_not_make_tokens_free_again(self):
        list(self.wrapper(Provider(usage=False)).stream(self.request))
        self.assertLess(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 9000)

    def test_revoked_binding_does_not_revert_to_cash(self):
        self.ledger.ingest_resources(observation(authorized=False))
        self.assertTrue(self.ledger.resource_bound("glm-4.7", "official"))
        with self.assertRaises(ValueError):
            list(self.wrapper().stream(self.request))
        self.assertEqual(self.provider.calls, 0)

    def test_tool_schema_is_counted_and_multimodal_is_rejected(self):
        self.request.tools = [{"type": "function"}]
        list(self.wrapper().stream(self.request))
        self.request.messages[0].content = [{"type": "image_url"}]
        with self.assertRaises(RequestNotSent):
            list(self.wrapper().stream(self.request))
        self.assertEqual(self.provider.calls, 1)

    def test_stale_refresh_failures_close_before_submission(self):
        self.ledger.mark_failure("resources", "session-unavailable")
        with self.assertRaises(ValueError):
            list(self.wrapper().stream(self.request))
        self.assertEqual(self.provider.calls, 0)

    def test_usage_above_reserved_bound_stops_new_free_routing(self):
        self.ledger.reserve("attempt", "official", "glm-4.7", 100,
                            valid_until=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
        self.ledger.settle("attempt", actual=101)
        self.assertEqual(self.ledger.status()["jobs"]["resources"]["error"], "usage-exceeded-reservation")
        self.assertEqual(self.ledger.quota_projection("glm-4.7", "official")["state"], "unknown")

    def policy(self, bind=True):
        self.profile = {"id": "official", "status": "available", "template_id": "zhipu-bigmodel",
                        "config": {"active_base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.7",
                                   "credential_revision": "a" * 32}}
        profiles = SimpleNamespace(list=lambda **kwargs: [copy.deepcopy(self.profile)],
                                   get=lambda _profile_id: copy.deepcopy(self.profile))
        policy = ModelPolicyService(profiles)
        self.addCleanup(policy.close)
        policy.refresh = self.ledger
        if bind:
            self.ledger.ingest_resources(observation(), account_revisions={
                "glm-4.7": provider_account_revision(self.profile)})
        return policy

    def test_bound_profile_changed_to_relay_never_returns_raw_provider(self):
        policy = self.policy()
        self.profile["config"]["active_base_url"] = "https://relay.invalid/v1"
        wrapped = policy.wrap_provider(self.provider, "official", "glm-4.7")
        self.assertIsInstance(wrapped, ResourceBoundProvider)
        with self.assertRaises(RequestNotSent):
            list(wrapped.stream(self.request))
        self.assertEqual(self.provider.calls, 0)

    def test_existing_runtime_stops_after_credential_rotation_or_archive(self):
        policy = self.policy()
        wrapped = policy.wrap_provider(self.provider, "official", "glm-4.7")
        self.profile["config"]["credential_revision"] = "b" * 32
        with self.assertRaises(RequestNotSent):
            list(wrapped.stream(self.request))
        self.profile["config"]["credential_revision"] = "a" * 32
        self.profile["archived_at"] = datetime.now(timezone.utc).isoformat()
        with self.assertRaises(RequestNotSent):
            list(wrapped.stream(self.request))
        self.assertEqual(self.provider.calls, 0)

    def test_recreated_runtime_cannot_rebind_old_resources_to_new_credentials(self):
        policy = self.policy()
        self.profile["config"]["credential_revision"] = "b" * 32
        policy.refresh = RefreshCoordinator(self.directory.name)
        self.assertEqual(policy.prepaid_projection("official", "glm-4.7"), {})
        with self.assertRaises(RequestNotSent):
            list(policy.wrap_provider(self.provider, "official", "glm-4.7").stream(self.request))
        with self.assertRaisesRegex(ValueError, "rebinding"):
            policy.refresh.ingest_resources(observation(), account_revisions={
                "glm-4.7": provider_account_revision(self.profile)})
        self.assertEqual(self.provider.calls, 0)

    def test_legacy_resource_binding_needs_new_host_verified_revision(self):
        policy = self.policy(bind=False)
        self.assertEqual(policy.prepaid_projection("official", "glm-4.7"), {})
        with self.assertRaises(RequestNotSent):
            list(policy.wrap_provider(self.provider, "official", "glm-4.7").stream(self.request))
        self.assertEqual(self.provider.calls, 0)

    def test_display_metadata_does_not_change_binding_but_model_version_does(self):
        policy = self.policy()
        before = provider_execution_revision(self.profile, "glm-4.7")
        self.profile["name"] = "Display name"
        self.profile["config"]["models"] = [{"id": "glm-4.7", "name": "Friendly model name",
            "health_state": "healthy", "last_tested_at": "2026-09-08T00:00:00Z"}]
        self.assertEqual(before, provider_execution_revision(self.profile, "glm-4.7"))
        self.profile["config"]["models"][0]["version"] = "new-model-version"
        self.assertNotEqual(before, provider_execution_revision(self.profile, "glm-4.7"))
        self.assertEqual(policy.prepaid_projection("official", "glm-4.7")["prepaid_tokens"], 10000)

    def test_passive_health_cannot_bypass_resource_reservations_via_chat_probe(self):
        self.provider.health_check = Mock(return_value={"ok": False, "error": "model not found"})
        result = self.wrapper().health_check(allow_chat_probe=True)
        self.provider.health_check.assert_called_once_with(allow_chat_probe=False)
        self.assertIn("chat_probe_blocked", result)
        self.assertEqual(self.provider.calls, 0)

    def test_known_pre_submission_rejection_releases_reservation(self):
        self.provider.stream = Mock(side_effect=RequestNotSent("host request rejected"))
        with self.assertRaises(RequestNotSent):
            list(self.wrapper().stream(self.request))
        self.assertEqual(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 10000)

    def test_partial_response_cannot_be_reclassified_as_unsent(self):
        def stream(request):
            yield "partial"
            raise RequestNotSent("late rejection")
        self.provider.stream = stream
        with self.assertRaises(RuntimeError):
            list(self.wrapper().stream(self.request))
        self.assertLess(self.ledger.quota_projection("glm-4.7", "official")["remaining"], 9000)
