import copy
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from quality_routing import Candidate, Node, QualityEvidence, select_candidate
from quality_routing.costs import FundingLot, quote_cost
from sumika_core.model_policy import ModelCatalogEntry, ModelPolicyService, ModelRouter, QuotaSnapshot, RoutingRequest
from sumika_core.model_refresh import RefreshCoordinator, parse_resource_observation
from sumika_core.provider_profiles import provider_account_revision
from sumika_core.quality.selection import FixedEvaluationSample, SelectionCohort, resolve_binding
from sumika_core.quality.service import QualityRoutingService
from sumika_core.route_pricing import CostEstimate, PricingSnapshot
from sumika_core.storage import Storage


class RouteCostConsistencyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.profiles = {name: {"id": name, "status": "available", "template_id": "openai-compatible",
                               "config": {"active_base_url": "https://" + name + ".example/v1", "model": "same-model"}}
                         for name in ("expensive", "cheap", "weak")}
        profiles = SimpleNamespace(get=lambda name: copy.deepcopy(self.profiles[name]),
                                   list=lambda **kwargs: list(self.profiles.values()))
        self.policy = ModelPolicyService(profiles, data_dir=directory.name)
        self.addCleanup(self.policy.free_models.close)
        self.policy.official_free_projection = Mock(return_value=False)
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.entries = [self.entry("expensive", "premium"), self.entry("cheap", "standard"), self.entry("weak", "basic")]
        self.prices = {"expensive": 3, "cheap": 1, "weak": 0}
        for profile, price in self.prices.items():
            self.price(profile, price)

    def entry(self, profile, quality):
        return ModelCatalogEntry("route-" + profile, profile, "same-model", profile, provider_profile_id=profile,
                                 quality_tier=quality, cost_class="paid-high", processing_location="cloud",
                                 auth_state="authorized", health_state="healthy", quota_state="available",
                                 capabilities=("text",), metadata={"billing_group": "default"})

    def price(self, profile, price, **values):
        snapshot = PricingSnapshot("price-" + profile, profile, "same-model", "default", "CNY",
                                   request_price=price, cash_currency="CNY", cash_rate=1,
                                   expires_at=self.expiry, **values)
        self.policy.pricing.store.replace_profile(profile, [snapshot])
        return snapshot

    def estimates(self, request):
        return {entry.route_id: self.policy.pricing.estimate(entry.to_dict(), request.to_dict(),
                    quote_provider=self.policy.candidate_pricing(entry.to_dict())["quote_provider"]) for entry in self.entries}

    def candidates(self):
        return [Candidate(entry.route_id, entry.provider_profile_id, entry.model_id, "api", authorized=True, available=True,
                          quality=(QualityEvidence("fixture", "route-expensive", time.time() + 3600, "fixed-suite"),) if entry.quality_tier != "basic" else (),
                          **self.policy.candidate_pricing(entry.to_dict())) for entry in self.entries]

    def test_router_and_task_executor_choose_same_cheapest_qualified_route(self):
        request = RoutingRequest(task_kind="chat", difficulty="moderate", min_quality_tier="standard")
        decision = ModelRouter().decide(request, self.entries, cost_estimates=self.estimates(request))
        selected = select_candidate(Node("answer", "Answer", "fixture", "route-expensive", acceptance=("Correct answer",)), self.candidates(),
                                    {entry.route_id for entry in self.entries}, external_allowed=True)
        self.assertEqual(decision.selected_route, "route-cheap")
        self.assertEqual(selected.candidate_id, decision.selected_route)
        self.assertIn("lowest_qualified_cost", decision.reason_codes)
        self.assertNotEqual(selected.candidate_id, "route-weak")

    def test_role_uses_same_cost_order_but_leader_keeps_quality_priority(self):
        candidates = self.candidates()
        now = time.time()
        samples = tuple(FixedEvaluationSample(f"sample-{purpose}-{candidate.candidate_id}-{index}", candidate.candidate_id,
                         "build-1", purpose, "suite", "v1", score, True, now - 10, now + 3600)
                        for purpose in ("leader", "role")
                        for candidate, score in zip(candidates, ("0.99", "0.9", "0.7")) for index in range(3))
        results = {}
        for purpose in ("leader", "role"):
            results[purpose] = resolve_binding(purpose=purpose, mode="auto", fixed_id=None,
                pool=[candidate.candidate_id for candidate in candidates], candidates=candidates,
                model_versions={candidate.candidate_id: "build-1" for candidate in candidates},
                health_states={candidate.candidate_id: "healthy" for candidate in candidates},
                cohort=SelectionCohort(purpose, "suite", "v1", "0.8"), priors=(), samples=samples, now=now)
        self.assertEqual(results["role"]["candidate_id"], "route-cheap")
        self.assertEqual(results["leader"]["candidate_id"], "route-expensive")

    def test_host_adapter_uses_shared_quote_and_stable_revision(self):
        storage = Storage(":memory:")
        self.addCleanup(storage.close)
        service = QualityRoutingService(SimpleNamespace(storage=storage, model_policy=self.policy,
            provider_profiles=self.policy.provider_profiles))
        self.addCleanup(service.close)
        entry = self.entries[1]
        route = SimpleNamespace(route_id=entry.route_id, provider_profile_id="cheap", metadata={"model_entry": entry.to_dict()},
                                processing_location="cloud", cost_class="paid-high")
        pricing = service._pricing(route, entry.model_id)
        self.assertEqual(pricing["quote_provider"](100, 50), self.policy.candidate_pricing(entry.to_dict())["quote_provider"](100, 50))
        self.assertEqual(pricing["pricing_revision"], service._pricing(route, entry.model_id)["pricing_revision"])
        self.price("cheap", 2)
        self.assertNotEqual(pricing["pricing_revision"], service._pricing(route, entry.model_id)["pricing_revision"])

    def test_cache_and_dynamic_pricing_are_used_by_both_paths(self):
        self.policy.pricing.store.replace_profile("cheap", [PricingSnapshot("dynamic", "cheap", "same-model", "default", "credit",
            billing_expression="(p + c) * 2 + cr * 0.1", cash_currency="CNY", cash_rate=2, expires_at=self.expiry)])
        candidate = self.candidates()[1]
        quote = candidate.quote(1000000, 500000, 100000)
        self.assertEqual(quote.provider_charge, Decimal("2.81"))
        self.assertEqual(quote.effective_cost_cny, Decimal("5.62"))
        self.assertEqual(quote, self.policy.pricing.quote(self.entries[1].to_dict(), 1000000, 500000, 100000))

    def test_currencies_and_billing_groups_are_not_compared_as_raw_numbers(self):
        snapshot = self.policy.pricing.store.list(provider_profile_id="cheap")[0]
        self.policy.pricing.store.replace_profile("cheap", [replace(snapshot, currency="USD", request_price=0.01, cash_currency=None, cash_rate=None)])
        request = RoutingRequest(difficulty="moderate", min_quality_tier="standard")
        decision = ModelRouter().decide(request, self.entries, cost_estimates=self.estimates(request))
        self.assertEqual(decision.selected_route, "route-expensive")
        self.policy.pricing.store.replace_profile("cheap", [snapshot, replace(snapshot, billing_group="other", pricing_ref="other")])
        self.assertEqual(self.candidates()[1].estimate(100, 100), 1)
        ambiguous = replace(self.entries[1], metadata={"billing_group": "range"})
        self.assertIsNone(self.policy.candidate_pricing(ambiguous.to_dict())["quote_provider"](100, 100).effective_cost_cny)

    def test_verified_cash_balance_blocks_overdraft_and_is_not_free(self):
        entry = self.entries[1]
        quota = QuotaSnapshot(entry.route_id, "available", remaining_min=0.5, unit="CNY", expires_at=self.expiry,
                              funding_kind="cash", account_revision=provider_account_revision(self.profiles["cheap"]))
        self.policy.store.upsert_quota(quota)
        quote = self.candidates()[1].quote(100, 50)
        self.assertFalse(quote.available)
        self.assertEqual(quote.reason, "cash-balance-insufficient")
        self.policy.store.upsert_quota(replace(quota, remaining_min=10))
        quote = self.candidates()[1].quote(100, 50)
        self.assertTrue(quote.available)
        self.assertFalse(quote.free)
        self.assertEqual(quote.effective_cost_cny, 1)
        self.profiles["cheap"]["config"]["active_base_url"] = "https://changed.example/v1"
        self.assertIsNone(self.candidates()[1].quote(100, 50).cash_balance_cny)

    def test_purchased_pack_and_unknown_funding_cannot_pass_free_only(self):
        request = RoutingRequest(difficulty="moderate", min_quality_tier="standard", budget_policy="free-only")
        entry = self.entries[1]
        for kind in ("purchased", "unknown"):
            quote = quote_cost(input_tokens=100, output_tokens=50, cash_price_cny="1",
                               lots=(FundingLot("pack", kind, 5000, "tokens", time.time() + 3600),), funding_required=True)
            estimate = CostEstimate(entry.route_id, "unknown", cash_currency="CNY", cash_max=0, route_quote=quote.to_dict())
            decision = ModelRouter().decide(request, [replace(entry, cost_class="free-limited")], cost_estimates={entry.route_id: estimate})
            self.assertEqual(decision.status, "no-compatible-route")

    def test_catalog_free_label_and_unclassified_balance_are_not_free_evidence(self):
        entry = replace(self.entries[1], cost_class="free-limited")
        request = RoutingRequest(difficulty="basic", budget_policy="free-only", confirmation_mode="automatic")
        decision = ModelRouter().decide(request, [entry], quotas={entry.route_id: QuotaSnapshot(
            entry.route_id, "available", remaining_min=10000, unit="tokens", expires_at=self.expiry)})
        self.assertEqual(decision.status, "no-compatible-route")

    def test_free_policy_reselection_has_correct_quota_and_alternatives(self):
        paid, free = self.entries[:2]
        free = replace(free, cost_class="free-limited")
        request = RoutingRequest(difficulty="basic", preferred_route=paid.route_id, budget_policy="free-only", confirmation_mode="automatic")
        decision = ModelRouter().decide(request, [paid, free], quotas={free.route_id: QuotaSnapshot(free.route_id, "low", source="free-account", expires_at=self.expiry)},
            cost_estimates={paid.route_id: CostEstimate(paid.route_id, "known", cash_currency="CNY", cash_max=3),
                            free.route_id: CostEstimate(free.route_id, "known", cash_currency="CNY", cash_max=0)})
        self.assertEqual(decision.selected_route, free.route_id)
        self.assertEqual(decision.quota_impact["source"], "free-account")
        self.assertNotIn(free.route_id, [row["route_id"] for row in decision.alternatives])

    def test_resource_provenance_survives_reservation_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = RefreshCoordinator(directory)
            expiry = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
            payload = {"ok": True, "provider_profile_id": "official", "observed_at": datetime.now(timezone.utc).isoformat(),
                "source_url": "https://open.bigmodel.cn/finance/resourcepack", "source": "official-api",
                "account_scope_id": "account", "account_binding_verified": True, "automatic_routing_authorized": True,
                "packs": [{"pack_id": "purchased", "name": "Resource", "status": "active", "applicability": "glm-4.7",
                           "remaining": 1000, "unit": "tokens", "expires_at": expiry, "funding_kind": "purchased", "value_per_unit_cny": "0.002"}]}
            coordinator.ingest_resources(payload)
            reservation = coordinator.reserve("request", "official", "glm-4.7", 100, valid_until=self.expiry)
            self.assertEqual(reservation["allocations"][0]["funding_kind"], "purchased")
            restored = RefreshCoordinator(directory).quota_projection("glm-4.7", "official")
            self.assertEqual(restored["funding_lots"][0]["remaining"], 900)
            self.assertEqual(restored["funding_lots"][0]["value_per_unit_cny"], "0.002")
            payload["packs"][0].pop("funding_kind")
            payload["packs"][0].pop("value_per_unit_cny")
            self.assertEqual(parse_resource_observation(payload)[0].funding_kind, "unknown")
