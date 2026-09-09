import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sumika_core.model_refresh import ModelObservation, RefreshCoordinator, parse_resource_observation
from sumika_core.model_policy import ModelPolicyService


def stamp(hours=0):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def resource_payload(profile="official", **overrides):
    return {
        "ok": True, "provider_profile_id": profile, "observed_at": stamp(),
        "source_url": "https://open.bigmodel.cn/finance/resourcepack", "source": "authenticated-page-dom",
        "account_scope_id": "account-a", "account_binding_verified": True, "automatic_routing_authorized": True,
        "displayed_timezone": "+08:00",
        "packs": [{"pack_id": "pack-a", "name": "GLM 资源包", "status": "生效中", "applicability": "适用于glm-4.7模型的推理",
                   "available_balance": "1,000 tokens", "expires_at": stamp(72)}],
        **overrides,
    }


def observation(**overrides):
    return {"provider_id": "zhipu-official", "model_id": "glm-4.7-flash", "observed_at": stamp(),
            "source_url": "https://bigmodel.cn/pricing", "source_version": "fixture-v1", "free_claim": True, **overrides}


class Profiles:
    def __init__(self):
        self.rows = [{
            "id": profile, "template_id": "zhipu-bigmodel", "status": "available", "has_secrets": True,
            "config": {"model": "glm-4.7", "active_base_url": endpoint},
        } for profile, endpoint in (("official", "https://open.bigmodel.cn/api/paas/v4"),
                                    ("relay", "https://relay.invalid/v1"))]

    def list(self, **kwargs):
        return self.rows

    def get(self, profile_id):
        return copy.deepcopy(next(item for item in self.rows if item["id"] == profile_id))


class ModelRefreshTests(unittest.TestCase):
    def test_seed_is_not_a_current_free_observation(self):
        for item in RefreshCoordinator().observations():
            self.assertFalse(item.fresh)
            self.assertFalse(item.free_claim)
            self.assertFalse(item.routable)

    def test_exact_model_matching_prevents_flash_or_air_cross_use(self):
        item = parse_resource_observation(resource_payload())[0]
        self.assertTrue(item.matches("GLM-4.7"))
        for model in ("glm-4", "glm-4.7-flash", "glm-4.7-flashx", "glm-4.5-air"):
            self.assertFalse(item.matches(model))

    def test_account_and_profile_scope_are_required(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        self.assertIsNone(coordinator.quota_projection("glm-4.7", "relay"))
        coordinator.ingest_resources(resource_payload(account_binding_verified=False))
        self.assertEqual(coordinator.quota_projection("glm-4.7", "official")["state"], "unknown")

    def test_dates_never_assume_utc_for_displayed_local_time(self):
        payload = resource_payload(displayed_timezone="unspecified-by-page")
        payload["packs"][0].pop("expires_at")
        payload["packs"][0]["expires_at_display"] = "2099-11-20 20:12:08"
        item = parse_resource_observation(payload)[0]
        self.assertIsNone(item.expires_at)
        self.assertFalse(item.available)
        payload["displayed_timezone"] = "+08:00"
        item = parse_resource_observation(payload)[0]
        self.assertEqual(item.expires_at, "2099-11-20T12:12:08+00:00")

    def test_invalid_quantities_and_units_reject(self):
        for amount in ("-5 tokens", "1.5万 tokens", "unavailable 100", "0.8", "1,00 tokens", True, float("nan")):
            payload = resource_payload()
            payload["packs"][0]["available_balance"] = amount
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                parse_resource_observation(payload)

    def test_shared_scopes_do_not_duplicate_balance(self):
        coordinator = RefreshCoordinator()
        payload = resource_payload()
        payload["packs"][0]["applicability"] = "适用于glm-4.7,glm-4.6模型的推理"
        coordinator.ingest_resources(payload)
        coordinator.reserve("attempt-1", "official", "glm-4.7", 800, valid_until=stamp(1))
        with self.assertRaises(ValueError):
            coordinator.reserve("attempt-2", "official", "glm-4.6", 300, valid_until=stamp(1))
        self.assertEqual(coordinator.quota_projection("glm-4.6", "official")["remaining"], 200)

    def test_earliest_expiry_and_attempt_idempotency(self):
        coordinator = RefreshCoordinator()
        payload = resource_payload()
        later = copy.deepcopy(payload["packs"][0])
        later.update(pack_id="later", expires_at=stamp(100))
        payload["packs"].insert(0, later)
        coordinator.ingest_resources(payload)
        receipt = coordinator.reserve("attempt", "official", "glm-4.7", 1200, valid_until=stamp(1))
        self.assertEqual(receipt["allocations"], [
            {"pack_id": "pack-a", "amount": 1000, "funding_kind": "unknown", "value_per_unit_cny": None},
            {"pack_id": "later", "amount": 200, "funding_kind": "unknown", "value_per_unit_cny": None}])
        self.assertEqual(coordinator.reserve("attempt", "official", "glm-4.7", 1200, valid_until=stamp(1)), receipt)
        with self.assertRaises(ValueError):
            coordinator.reserve("attempt", "official", "glm-4.7", 10, valid_until=stamp(1))

    def test_unknown_outcome_retains_reservation_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = RefreshCoordinator(directory)
            coordinator.ingest_resources(resource_payload())
            coordinator.reserve("attempt", "official", "glm-4.7", 800, valid_until=stamp(1))
            coordinator.settle("attempt")
            reopened = RefreshCoordinator(directory)
            self.assertEqual(reopened.quota_projection("glm-4.7", "official")["remaining"], 200)

    def test_settle_usage_and_definitely_unsent_release(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        coordinator.reserve("sent", "official", "glm-4.7", 800, valid_until=stamp(1))
        coordinator.settle("sent", actual=100)
        coordinator.reserve("unsent", "official", "glm-4.7", 800, valid_until=stamp(1))
        coordinator.settle("unsent", definitely_not_sent=True)
        self.assertEqual(coordinator.quota_projection("glm-4.7", "official")["remaining"], 900)

    def test_refresh_lag_never_restores_spent_or_inflight_allowance(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        coordinator.reserve("sent", "official", "glm-4.7", 900, valid_until=stamp(1))
        coordinator.settle("sent", actual=500)
        coordinator.ingest_resources(resource_payload())
        self.assertEqual(coordinator.quota_projection("glm-4.7", "official")["remaining"], 500)

    def test_future_stale_expired_and_expiring_before_completion_reject(self):
        for payload in (resource_payload(observed_at=stamp(-48)), resource_payload(observed_at=stamp(1))):
            coordinator = RefreshCoordinator()
            coordinator.ingest_resources(payload)
            with self.assertRaises(ValueError):
                coordinator.reserve("attempt", "official", "glm-4.7", 100, valid_until=stamp(1))
        payload = resource_payload()
        payload["packs"][0]["expires_at"] = stamp(0.5)
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(payload)
        with self.assertRaises(ValueError):
            coordinator.reserve("attempt", "official", "glm-4.7", 100, valid_until=stamp(1))

    def test_partial_accounts_and_duplicate_rows(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        coordinator.ingest_resources(resource_payload("second-account", account_scope_id="account-b"))
        self.assertEqual(len(coordinator.resources()), 2)
        payload = resource_payload()
        payload["packs"] *= 2
        with self.assertRaises(ValueError):
            coordinator.ingest_resources(payload)
        self.assertEqual(len(coordinator.resources()), 2)

    def test_refresh_failure_preserves_observation_but_blocks_usage(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        coordinator.mark_failure("resources", TimeoutError())
        self.assertEqual(coordinator.resources()[0].remaining, 1000)
        self.assertEqual(coordinator.quota_projection("glm-4.7", "official")["state"], "unknown")
        self.assertEqual(coordinator.status()["jobs"]["resources"]["state"], "needs-review")

    def test_import_is_not_quality_or_authorization(self):
        coordinator = RefreshCoordinator()
        for extra in ({"availability_state": "routable"}, {"evaluation_count": 3}, {"health_state": "healthy"}, {"quality_tier": "premium"}):
            with self.assertRaises(ValueError):
                coordinator.ingest_models([observation(**extra)])
        coordinator.ingest_models([observation()])
        self.assertFalse(coordinator.observations()[1].routable)

    def test_import_transaction_and_old_observations(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_models([observation()])
        with self.assertRaises(ValueError):
            coordinator.ingest_models([observation(model_id="new"), observation(model_id="bad", health_state="healthy")])
        self.assertNotIn("new", {item.model_id for item in coordinator.observations()})
        with self.assertRaises(ValueError):
            coordinator.ingest_models([observation(observed_at=stamp(-48))])

    def test_missing_from_partial_free_list_is_not_retired(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_models([observation()])
        coordinator.ingest_models([observation(model_id="glm-new")], reconcile_source="https://bigmodel.cn/pricing")
        previous = next(item for item in coordinator.observations() if item.model_id == "glm-4.7-flash")
        self.assertEqual(previous.availability_state, "needs-review")
        self.assertFalse(previous.free_claim)

    def test_disk_failure_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = RefreshCoordinator(directory)
            with patch.object(Path, "replace", side_effect=OSError("disk unavailable")), self.assertRaises(OSError):
                coordinator.ingest_models([observation()])
            self.assertEqual(coordinator.status()["jobs"]["pricing"]["state"], "never")

    def test_two_coordinators_cannot_overspend(self):
        with tempfile.TemporaryDirectory() as directory:
            first = RefreshCoordinator(directory)
            first.ingest_resources(resource_payload())
            second = RefreshCoordinator(directory)
            def reserve(coordinator, attempt):
                try:
                    coordinator.reserve(attempt, "official", "glm-4.7", 800, valid_until=stamp(1))
                    return True
                except (ValueError, OSError):
                    return False
            with ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(reserve, first, "one"), pool.submit(reserve, second, "two")]
                self.assertEqual(sum(future.result() for future in futures), 1)

    def test_official_quota_and_observation_never_apply_to_relay(self):
        service = ModelPolicyService(Profiles())
        service.register_resource_reader("official", resource_payload)
        service.refresh_observations(kind="resources")
        entries = service.catalog()["entries"]
        self.assertEqual(next(item for item in entries if item["route_id"] == "profile:official:glm-4.7")["quota_state"], "available")
        self.assertEqual(next(item for item in entries if item["route_id"] == "profile:relay:glm-4.7")["quota_state"], "unknown")
        self.assertIsNone(service._model_observation(Profiles().rows[1], "glm-4.7-flash"))

    def test_current_real_observation_is_unbound_and_not_auto_routable(self):
        payload = resource_payload(account_binding_verified=False, automatic_routing_authorized=False)
        item = parse_resource_observation(payload)[0]
        self.assertFalse(item.available)

    def test_public_refresh_runs_once_until_due_and_failure_revokes_free_evidence(self):
        service = ModelPolicyService(Profiles())
        with patch("sumika_core.integrations.zhipu_pricing.fetch_pricing_observations", return_value=[observation()]) as fetch:
            result = service.refresh_observations(kind="pricing")
            self.assertEqual(result["changed"]["pricing"], 1)
            self.assertTrue(service.official_free_projection("official", "glm-4.7-flash"))
            self.assertFalse(service.official_free_projection("relay", "glm-4.7-flash"))
            service.refresh_observations(kind="catalog")
            fetch.assert_called_once_with()
        with patch("sumika_core.integrations.zhipu_pricing.fetch_pricing_observations", side_effect=ValueError("invalid page")):
            service.refresh_observations(kind="pricing", force=True)
        self.assertFalse(service.official_free_projection("official", "glm-4.7-flash"))
        self.assertTrue(service.refresh.observations()[1].free_claim)

    def test_closed_host_never_starts_refresh(self):
        service = ModelPolicyService(Profiles())
        service.close()
        with patch("sumika_core.integrations.zhipu_pricing.fetch_pricing_observations") as fetch:
            with self.assertRaisesRegex(ValueError, "closed"):
                service.refresh_observations(kind="pricing", force=True)
            fetch.assert_not_called()

    def test_spa_fallback_uses_isolated_public_dom_not_model_or_credentials(self):
        from sumika_core.integrations.zhipu_pricing import PricingNeedsReview
        service = ModelPolicyService(Profiles())
        with patch("sumika_core.integrations.zhipu_pricing.fetch_pricing_observations", side_effect=PricingNeedsReview("SPA")), \
             patch("sumika_core.integrations.zhipu_pricing.fetch_rendered_pricing_observations", return_value=[observation()]) as rendered:
            result = service.refresh_observations(kind="pricing")
        rendered.assert_called_once_with()
        self.assertEqual(result["refresh"]["model_calls"], 0)
        self.assertEqual(result["refresh"]["jobs"]["pricing"]["state"], "ready")

    def test_registered_resource_reader_does_not_use_credentials(self):
        service = ModelPolicyService(Profiles())
        service.register_resource_reader("official", resource_payload)
        with patch("sumika_core.integrations.zhipu_pricing.fetch_pricing_observations") as fetch:
            result = service.refresh_observations(kind="resources")
            self.assertEqual(result["changed"], {"resources": 1})
            fetch.assert_not_called()
        self.assertEqual(service.prepaid_projection("official", "glm-4.7")["prepaid_tokens"], 1000)
        self.assertEqual(service.prepaid_projection("relay", "glm-4.7"), {})

    def test_account_change_requires_explicit_rebinding(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        with self.assertRaisesRegex(ValueError, "rebinding"):
            coordinator.ingest_resources(resource_payload(account_scope_id="account-b"))

    def test_shared_account_profiles_use_conservative_common_balance(self):
        coordinator = RefreshCoordinator()
        coordinator.ingest_resources(resource_payload())
        payload = resource_payload(profile="official-other")
        payload["packs"][0]["available_balance"] = "2,000 tokens"
        coordinator.ingest_resources(payload)
        self.assertEqual(coordinator.quota_projection("glm-4.7", "official-other")["remaining"], 1000)
        coordinator.reserve("first", "official", "glm-4.7", 800, valid_until=stamp(1))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            coordinator.reserve("second", "official-other", "glm-4.7", 800, valid_until=stamp(1))

    def test_price_refresh_does_not_disable_previously_tested_fixed_profile(self):
        profiles = Profiles()
        profiles.rows[0]["config"]["models"] = [{"id": "glm-4.7", "enabled": True,
            "health_state": "healthy", "last_tested_at": stamp(-1)}]
        service = ModelPolicyService(profiles)
        service.refresh.ingest_models([observation(model_id="glm-4.7", free_claim=False)])
        entry = next(row for row in service._profile_entries() if row.provider_profile_id == "official")
        self.assertTrue(entry.routable)
        self.assertNotIn("evaluation_gate", entry.metadata)


if __name__ == "__main__":
    unittest.main()
