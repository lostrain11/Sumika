from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quality_routing import RoutingError, Scope
from sumika_core.agent.supervisor import RuntimeRouteDescriptor
from sumika_core.quality.selection import FixedEvaluationSample, QualityPrior, SELECTION_SCHEMA, SelectionCohort, SelectionEvidenceStore
from sumika_core.quality.service import QualityRoutingService
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.providers.guard import RequestNotSent
from sumika_core.storage import Storage


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(":memory:")
        self.storage.create_character("one", "One", {"persona": {}})
        self.storage.create_character("two", "Two", {"persona": {}})
        self.storage.create_session("session-one", character_id="one")
        self.routes = [self.route("strong", "basic-tiny"), self.route("cheap", "flagship-pro"), self.route("weak", "ultimate-leader")]
        self.prices = {"strong": Decimal("3"), "cheap": Decimal("1"), "weak": Decimal("0")}
        self.calls = []
        self.now = time.time()
        self.serial = 0
        self.app = SimpleNamespace(
            storage=self.storage, logger=SimpleNamespace(warning=Mock()), events=SimpleNamespace(publish=Mock()),
            provider_profiles=SimpleNamespace(runtime=self.runtime, get=lambda *args: {"status": "available"}, mark_used=Mock()),
            route_supervisor=SimpleNamespace(registered_routes=lambda: tuple(self.routes)),
            model_policy=SimpleNamespace(pricing=SimpleNamespace(refresh_profiles=Mock(), store=SimpleNamespace(list=self.snapshots))),
            _refresh_route_supervisor_catalog=Mock(),
        )
        self.service = QualityRoutingService(self.app)
        self.params = {"assistant_id": "one", "session_id": "session-one", "goal": "Compute", "external_allowed": True}

    def tearDown(self):
        self.service.close()
        self.storage.close()

    def route(self, candidate_id, model_id):
        return RuntimeRouteDescriptor(candidate_id, label=model_id, kind="provider", status="ready", routable=True,
                                      capabilities=("text",), executor="fixture", provider_profile_id=candidate_id,
                                      auth_state="authorized", health_state="healthy", cost_class="paid-high",
                                      quota_state="available", processing_location="cloud",
                                      metadata={"model_entry": {"model_id": model_id, "model_version": "build-1"}})

    def snapshots(self, provider_profile_id, model_id):
        price = self.prices.get(provider_profile_id)
        if price is None:
            return []
        return [SimpleNamespace(to_dict=lambda: {"fresh": True}, source_type="manual", billing_group="fixture",
                                cash_currency="CNY", cash_rate=1, request_price=price, billing_expression=None, context_tiers=())]

    def runtime(self, profile_id, **kwargs):
        def stream(request):
            self.calls.append((profile_id, request))
            prompt = request.messages[0].content
            if "Return only a JSON object with nodes" in prompt:
                yield json.dumps({"nodes": [{"node_id": "answer", "goal": "Compute", "task_type": "arithmetic", "acceptance": ["Correct"]}]})
            elif "Verify the task result" in prompt:
                yield '{"passed":true,"reason":"Fixture check"}'
            else:
                yield "42"

        return SimpleNamespace(stream=stream, last_usage={"input_tokens": 100, "output_tokens": 30})

    def cohort(self, purpose, **changes):
        return replace(SelectionCohort(purpose, "fixed-suite", "suite-1", Decimal("0.8")), **changes)

    def sample(self, candidate_id, purpose="leader", score="0.9", **changes):
        self.serial += 1
        sample = FixedEvaluationSample("sample-" + str(self.serial), candidate_id, "build-1", purpose, "fixed-suite", "suite-1",
                                       Decimal(score), True, self.now - 10, self.now + 3600)
        return replace(sample, **changes)

    def samples(self, candidate_id, purpose="leader", score="0.9", total=3, assistant_id="one", **changes):
        for _index in range(total):
            self.service.record_fixed_sample(assistant_id, self.sample(candidate_id, purpose, score, **changes))

    def prior(self, candidate_id, score="1", **changes):
        return replace(QualityPrior(candidate_id, "build-1", "leader", "fixed-suite", "suite-1", "external-ranking", "release-1",
                                    Decimal(score), self.now - 10, self.now + 3600), **changes)

    def configure(self, assistant_id="one", **changes):
        return self.service.update_settings({"assistant_id": assistant_id, "selection_mode": {"leader": "auto", "role": "auto"},
                                             "candidate_pool": ["strong", "cheap", "weak"], **changes})

    def qualify(self, assistant_id="one"):
        for purpose in ("leader", "role"):
            self.service.register_selection_cohort(assistant_id, self.cohort(purpose))
            for candidate_id, score in (("strong", "0.95"), ("cheap", "0.85"), ("weak", "0.2")):
                self.samples(candidate_id, purpose, score, assistant_id=assistant_id)

    def plan_params(self, **changes):
        return {**self.params, "allowed_candidate_ids": ["strong", "cheap"], "planning_confirmed": True, **changes}

    def reason(self, resolution, candidate_id, purpose="leader"):
        return next(row["reason"] for row in resolution["bindings"][purpose]["candidates"] if row["candidate_id"] == candidate_id)

    def test_defaults_remain_fixed_without_invented_evidence(self):
        settings = self.service.settings("one")
        self.assertEqual(settings["selection_mode"], {"leader": "fixed", "role": "fixed"})
        self.assertEqual(settings["candidate_pool"], [])
        result = self.service.select_bindings("one")
        self.assertIsNone(result["leader_candidate_id"])
        self.assertEqual(result["bindings"]["leader"]["reason"], "fixed-unset")
        self.assertIsNone(self.storage.get_meta(SELECTION_SCHEMA + ":one"))
        self.assertEqual(self.calls, [])

    def test_auto_leader_keeps_preference_only_when_quality_is_tied(self):
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.samples("strong", "leader", "0.95")
        self.samples("cheap", "leader", "0.95")
        self.samples("weak", "leader", "0.2")
        self.configure(leader_candidate_id="strong")
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong")
        self.configure(leader_candidate_id="weak")
        self.assertNotEqual(self.service.select_bindings("one")["leader_candidate_id"], "weak")

    def test_changed_price_is_definitely_unsent_even_with_old_catalog(self):
        self.service.catalog("one")
        candidate = self.service._candidate("strong")
        self.prices["strong"] = Decimal("4")
        result = self.service._call(candidate, Scope("one", "session-one"), "Compute", cancelled=threading.Event())
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.possibly_sent)
        self.assertEqual((result.cash_cny, result.input_tokens, result.output_tokens), (Decimal(0), 0, 0))
        self.assertEqual(self.calls, [])

    def test_live_route_changes_block_before_provider_creation(self):
        self.service.catalog("one")
        candidate = self.service._candidate("strong")
        original = self.routes[0]
        changes = ({"routable": False}, {"auth_state": "unknown"}, {"health_state": "error"},
                   {"quota_state": "expired"}, {"metadata": {"model_entry": {"model_id": "different"}}})
        for change in changes:
            with self.subTest(change=change), patch.object(self.app.provider_profiles, "runtime") as runtime:
                self.routes[0] = replace(original, **change)
                result = self.service._invoke(candidate, Scope("one", "session-one"), "Compute", threading.Event(), 100)
                self.assertEqual(result.status, "failed")
                self.assertFalse(result.possibly_sent)
                runtime.assert_not_called()

    def test_unsent_auxiliary_call_releases_budget_but_timeout_does_not(self):
        self.service.update_settings({"assistant_id": "one", "leader_candidate_id": "strong"})
        task = self.service.plan(self.params)
        scope = Scope("one", "session-one")
        self.service.engine.approve(task["task_id"], scope, 1)
        candidate = self.service._candidate("strong")
        self.prices["strong"] = Decimal("4")
        rejected = self.service._call(candidate, scope, "Compute", cancelled=threading.Event(), task_id=task["task_id"])
        self.assertEqual(rejected.status, "failed")
        self.assertEqual(self.service.engine.snapshot(task["task_id"], scope)["budget"]["reservations"], {})
        self.prices["strong"] = Decimal("3")
        provider = SimpleNamespace(stream=Mock(side_effect=TimeoutError("unknown response")))
        with patch.object(self.app.provider_profiles, "runtime", return_value=provider):
            unknown = self.service._call(candidate, scope, "Compute", cancelled=threading.Event(), task_id=task["task_id"])
        self.assertTrue(unknown.possibly_sent)
        self.assertEqual(len(self.service.engine.snapshot(task["task_id"], scope)["budget"]["reservations"]), 1)

    def test_role_stream_rechecks_price_and_keeps_messages_and_usage(self):
        self.service.update_settings({"assistant_id": "one", "role_candidate_id": "strong"})
        provider, _candidate = self.service.role_runtime("one")
        request = ChatRequest("session-one", [Message("system", "Character"), Message("user", "Hello")],
                              character_id="one", temperature=0.4, max_tokens=128, tools=[{"type": "function"}])
        self.assertEqual(list(provider.stream(request)), ["42"])
        sent = self.calls[0][1]
        self.assertEqual(sent.messages, request.messages)
        self.assertEqual((sent.temperature, sent.tools, sent.max_tokens), (0.4, request.tools, 128))
        self.assertEqual(provider.last_usage["input_tokens"], 100)
        self.prices["strong"] = Decimal("5")
        with self.assertRaises(RequestNotSent):
            list(provider.stream(request))
        self.assertEqual(len(self.calls), 1)

    def test_role_binding_cannot_be_reused_by_another_assistant_or_after_change(self):
        self.service.update_settings({"assistant_id": "one", "role_candidate_id": "strong"})
        provider, _candidate = self.service.role_runtime("one")
        request = ChatRequest("session-one", [Message("user", "Hello")], character_id="two")
        with self.assertRaises(RequestNotSent):
            list(provider.stream(request))
        request.character_id = "one"
        self.service.update_settings({"assistant_id": "one", "role_candidate_id": "cheap"})
        with self.assertRaises(RequestNotSent):
            list(provider.stream(request))
        self.assertEqual(self.calls, [])

    def test_explicit_role_effort_is_verified_and_applied_to_original_request(self):
        self.routes[0] = replace(self.routes[0], reasoning_efforts=("high",))
        self.service.register_selection_cohort("one", self.cohort("role"))
        self.samples("strong:effort:high", "role", applied_reasoning_effort="high")
        self.service.update_settings({"assistant_id": "one", "role_candidate_id": "strong:effort:high"})
        provider, _candidate = self.service.role_runtime("one")
        request = ChatRequest("session-one", [Message("user", "Hello")], character_id="one")
        self.assertEqual(list(provider.stream(request)), ["42"])
        self.assertEqual(self.calls[0][1].reasoning_effort, "high")
        self.assertIsNone(request.reasoning_effort)
        self.routes[0] = replace(self.routes[0], reasoning_efforts=())
        with self.assertRaises((RequestNotSent, RoutingError)):
            list(provider.stream(request))
        self.assertEqual(len(self.calls), 1)

    def test_execution_qualification_uses_owner_not_last_catalog_view(self):
        original = self.routes[0]
        self.routes[0] = replace(original, routable=False, metadata={**original.metadata,
            "routable": False, "evaluation_gate": True, "configured_routable": True,
            "observation_fresh": True, "observation_status": "observed"})
        self.qualify()
        self.service.catalog("one")
        candidate = self.service._candidate("strong")
        self.service.catalog("two")
        first = self.service._invoke(candidate, Scope("one", "session-one"), "Compute", threading.Event(), 100)
        second = self.service._invoke(candidate, Scope("two", "session-two"), "Compute", threading.Event(), 100)
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "failed")
        self.assertFalse(second.possibly_sent)
        self.assertEqual(len(self.calls), 1)

    def test_timeout_after_submission_remains_unknown(self):
        self.service.catalog("one")
        candidate = self.service._candidate("strong")
        provider = SimpleNamespace(stream=Mock(side_effect=TimeoutError("uncertain response")))
        with patch.object(self.app.provider_profiles, "runtime", return_value=provider):
            result = self.service._call(candidate, Scope("one", "session-one"), "Compute", cancelled=threading.Event())
        self.assertEqual(result.status, "unknown")
        self.assertTrue(result.possibly_sent)
        self.assertIsNone(result.cash_cny)

    def test_profile_edit_after_runtime_creation_is_rechecked_before_send(self):
        profile = {"status": "available", "config": {"active_base_url": "https://official.invalid/v1"}}
        self.app.provider_profiles.get = lambda _profile_id: profile
        self.service.catalog("one")
        candidate = self.service._candidate("strong")
        original = self.app.provider_profiles.runtime
        def runtime(*args, **kwargs):
            provider = original(*args, **kwargs)
            profile["config"]["active_base_url"] = "https://relay.invalid/v1"
            return provider
        self.app.provider_profiles.runtime = runtime
        result = self.service._invoke(candidate, Scope("one", "session-one"), "Compute", threading.Event(), 100)
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.possibly_sent)
        self.assertEqual(self.calls, [])

    def test_price_observation_gate_requires_exact_assistant_evidence(self):
        route = self.routes[0]
        self.routes[0] = replace(route, routable=False, metadata={**route.metadata,
            "model_version": "build-1", "routable": False, "configured_routable": True,
            "evaluation_gate": True, "observation_fresh": True, "observation_status": "observed"})
        self.configure()
        before = self.service.catalog("one")["candidates"]
        self.assertFalse(next(row for row in before if row["candidate_id"] == "strong")["authorized"])
        self.qualify()
        after = self.service.select_bindings("one")
        self.assertEqual(after["leader_candidate_id"], "strong")
        other = self.service.catalog("two")["candidates"]
        self.assertFalse(next(row for row in other if row["candidate_id"] == "strong")["authorized"])
        self.assertFalse(self.routes[0].routable)

    def test_settings_are_additive_and_reject_invalid_updates_atomically(self):
        self.service.update_settings({"assistant_id": "one", "leader_candidate_id": "cheap", "role_candidate_id": "weak"})
        self.configure(selection_mode={"leader": "auto"}, candidate_pool=["strong", "strong", "cheap"])
        self.service.update_settings({"assistant_id": "one", "budget_rule": {"multiplier": "4", "extra_cny": "7"}})
        settings = self.service.rpc("quality.settings.get", {"assistant_id": "one"})
        self.assertEqual(settings["leader_candidate_id"], "cheap")
        self.assertEqual(settings["role_candidate_id"], "weak")
        self.assertEqual(settings["selection_mode"], {"leader": "auto", "role": "fixed"})
        self.assertEqual(settings["candidate_pool"], ["cheap", "strong"])
        for invalid in ({"selection_mode": "auto"}, {"selection_mode": {"leader": True}}, {"selection_mode": {"extra": "auto"}},
                        {"candidate_pool": "strong"}, {"candidate_pool": ["unregistered"]}):
            with self.subTest(invalid=invalid), self.assertRaises(RoutingError):
                self.service.update_settings({"assistant_id": "one", "leader_candidate_id": "strong", **invalid})
        self.assertEqual(self.service.settings("one"), settings)

    def test_leader_uses_quality_role_uses_cost_after_quality_floor(self):
        self.configure(leader_candidate_id="weak", role_candidate_id="strong")
        self.qualify()
        before = self.storage.get_meta("quality-routing/settings/v1")
        result = self.service.rpc("quality.bindings.select", {"assistant_id": "one"})
        self.assertEqual(result["leader_candidate_id"], "strong")
        self.assertEqual(result["role_candidate_id"], "cheap")
        self.assertEqual(self.reason(result, "weak"), "below-cohort-quality-floor")
        self.assertEqual(self.reason(result, "weak", "role"), "below-cohort-quality-floor")
        self.assertEqual(self.storage.get_meta("quality-routing/settings/v1"), before)
        self.assertEqual(self.calls, [])
        self.assertTrue(all(not candidate.quality for candidate in self.service.engine.candidates()))

    def test_ranking_ties_are_stable_across_catalog_order(self):
        self.configure()
        for purpose in ("leader", "role"):
            self.service.register_selection_cohort("one", self.cohort(purpose))
            for candidate_id in ("strong", "cheap"):
                self.samples(candidate_id, purpose)
        self.prices["strong"] = self.prices["cheap"]
        first = self.service.select_bindings("one")
        self.routes.reverse()
        self.assertEqual(self.service.select_bindings("one"), first)
        self.assertEqual(first["leader_candidate_id"], "cheap")
        self.assertEqual(first["role_candidate_id"], "cheap")

    def test_priors_only_break_qualified_measured_score_ties(self):
        self.configure(selection_mode={"leader": "auto", "role": "fixed"})
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.service.register_quality_prior("one", self.prior("strong"))
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        self.samples("strong", score="0.89")
        self.samples("cheap", score="0.9")
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "cheap")
        self.samples("strong", score="0.91")
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong")
        self.service.register_quality_prior("one", self.prior("strong", expires_at=self.now - 1))
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "cheap")
        self.service.register_quality_prior("one", self.prior("strong", model_version="build-2"))
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "cheap")

    def test_missing_cohort_and_empty_pool_fail_closed(self):
        self.configure()
        self.assertEqual(self.service.select_bindings("one")["bindings"]["leader"]["reason"], "selection-cohort-missing")
        self.configure(candidate_pool=[])
        self.assertEqual(self.service.select_bindings("one")["bindings"]["leader"]["reason"], "candidate-pool-empty")

    def test_live_health_authorization_and_availability_cannot_come_from_priors(self):
        self.configure(candidate_pool=["strong"])
        self.qualify()
        self.service.register_quality_prior("one", self.prior("strong"))
        original = self.routes[0]
        for changes, reason in (({"health_state": "unknown"}, "explicit-health-required"),
                                ({"health_state": "unhealthy"}, "explicit-health-required"),
                                ({"auth_state": "unknown"}, "unavailable-or-unauthorized"),
                                ({"routable": False}, "unavailable-or-unauthorized"),
                                ({"status": "unavailable"}, "unavailable-or-unauthorized"),
                                ({"quota_state": "exhausted"}, "unavailable-or-unauthorized"),
                                ({"capabilities": ("image",)}, "text-capability-required")):
            with self.subTest(changes=changes):
                self.routes[0] = replace(original, **changes)
                result = self.service.select_bindings("one")
                self.assertIsNone(result["leader_candidate_id"])
                self.assertEqual(self.reason(result, "strong"), reason)
        self.assertEqual(self.calls, [])

    def test_successful_fixed_samples_must_be_fresh_and_match_suite(self):
        self.configure(candidate_pool=["strong"])
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.samples("strong", total=2)
        for changes in ({"successful": False}, {"expires_at": self.now - 1}, {"observed_at": self.now + 60},
                        {"cohort_version": "suite-2"}, {"cohort_id": "other-suite"}, {"purpose": "role"}):
            self.samples("strong", **changes)
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        self.samples("strong", total=1)
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong")

    def test_model_version_is_required_and_old_samples_never_migrate(self):
        self.configure(candidate_pool=["strong"])
        self.qualify()
        for version in (None, "unknown", "build-2", "C:\\private\\artifact", "../private"):
            with self.subTest(version=version):
                self.routes[0] = replace(self.routes[0], metadata={"model_entry": {"model_id": "basic-tiny", "model_version": version}})
                self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        self.routes[0] = replace(self.routes[0], metadata={"model_entry": {"model_id": "basic-tiny", "model_version": "build-2"}})
        self.samples("strong", model_version="build-2")
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong")

    def test_effort_variants_require_independent_applied_effort_evidence(self):
        self.routes[0] = replace(self.routes[0], reasoning_efforts=("high", "off"))
        self.configure(candidate_pool=["strong:effort:high", "strong:effort:off"], selection_mode={"leader": "auto", "role": "fixed"})
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.samples("strong", score="1", applied_reasoning_effort="high")
        self.service.register_quality_prior("one", self.prior("strong:effort:high"))
        for applied in (None, "unknown", "off"):
            self.samples("strong:effort:high", applied_reasoning_effort=applied)
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        self.samples("strong:effort:high", total=2, applied_reasoning_effort="high")
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        self.samples("strong:effort:high", total=1, applied_reasoning_effort="high")
        result = self.service.select_bindings("one")
        self.assertEqual(result["leader_candidate_id"], "strong:effort:high")
        self.assertEqual(self.reason(result, "strong:effort:off"), "unavailable-or-unauthorized")
        self.samples("strong:effort:off", score="1", applied_reasoning_effort="off")
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong:effort:off")

    def test_selection_cannot_expand_the_assistant_allowlist(self):
        self.configure(candidate_pool=["cheap"])
        self.qualify()
        result = self.service.select_bindings("one")
        self.assertEqual(result["leader_candidate_id"], "cheap")
        self.assertEqual([row["candidate_id"] for row in result["bindings"]["leader"]["candidates"]], ["cheap"])

    def test_assistant_settings_samples_and_priors_are_isolated(self):
        self.configure()
        self.qualify()
        self.assertEqual(self.service.settings("two")["selection_mode"], {"leader": "fixed", "role": "fixed"})
        self.configure("two")
        for purpose in ("leader", "role"):
            self.service.register_selection_cohort("two", self.cohort(purpose))
        self.assertIsNone(self.service.select_bindings("two")["leader_candidate_id"])
        self.samples("cheap", assistant_id="two")
        self.samples("strong", assistant_id="two")
        self.service.register_quality_prior("one", self.prior("strong"))
        self.assertEqual(self.service.select_bindings("two")["leader_candidate_id"], "cheap")
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong")
        with self.assertRaises(RoutingError):
            self.service.record_fixed_sample("missing-assistant", self.sample("strong"))

    def test_metadata_evidence_survives_restart_and_sample_ids_are_deduplicated(self):
        self.configure(candidate_pool=["strong"], selection_mode={"leader": "auto", "role": "fixed"})
        self.service.register_selection_cohort("one", self.cohort("leader"))
        sample = self.sample("strong")
        with ThreadPoolExecutor(max_workers=4) as pool:
            inserted = list(pool.map(lambda _index: self.service.record_fixed_sample("one", sample), range(8)))
        self.assertEqual(inserted.count(True), 1)
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        with self.assertRaises(RoutingError):
            self.service.record_fixed_sample("one", replace(sample, score=Decimal("1")))
        self.samples("strong", total=2)
        self.service.register_quality_prior("one", self.prior("strong"))
        before = self.service.select_bindings("one")
        self.service.close()
        self.service = QualityRoutingService(self.app)
        self.assertEqual(self.service.select_bindings("one"), before)
        self.assertFalse(self.service.record_fixed_sample("one", sample))
        stored = json.loads(self.storage.get_meta(SELECTION_SCHEMA + ":one"))
        self.assertEqual(stored["schema"], SELECTION_SCHEMA)
        self.assertEqual(len(stored["samples"]), 3)

    def test_metadata_contract_rejects_paths_secrets_bodies_and_nonfinite_values(self):
        sample = self.sample("strong")
        for value in ("C:\\private\\file.txt", "/tmp/private", "../private", "task body with spaces", "sk-" + "x" * 30):
            with self.subTest(value=value), self.assertRaises(RoutingError):
                replace(sample, sample_id=value)
        for changes in ({"score": "NaN"}, {"score": "Infinity"}, {"score": "1.01"}, {"score": True},
                        {"successful": 1}, {"expires_at": float("inf")}, {"observed_at": True}):
            with self.subTest(changes=changes), self.assertRaises(RoutingError):
                replace(sample, **changes)
        with self.assertRaises(TypeError):
            FixedEvaluationSample(**{**sample.__dict__, "body": "not metadata"})
        with self.assertRaises(RoutingError):
            self.service.record_fixed_sample("one", sample.__dict__)
        self.service.record_fixed_sample("one", sample)
        data = json.loads(self.storage.get_meta(SELECTION_SCHEMA + ":one"))
        self.assertEqual(set(data["samples"][0]), {"sample_id", "candidate_id", "model_version", "purpose", "cohort_id", "cohort_version",
                                               "score", "successful", "observed_at", "expires_at", "applied_reasoning_effort"})
        data["samples"][0]["body"] = "untrusted"
        self.storage.set_meta(SELECTION_SCHEMA + ":one", json.dumps(data))
        self.configure()
        with self.assertRaisesRegex(RoutingError, "invalid stored"):
            self.service.select_bindings("one")

    def test_rpc_and_settings_cannot_register_host_evidence(self):
        for method in ("quality.evidence.register", "quality.selection.sample", "quality.selection.prior", "quality.selection.cohort"):
            with self.subTest(method=method), self.assertRaises(RoutingError):
                self.service.rpc(method, {**self.params, "task_id": "fake", "successful": True, "score": 1, "authorized": True})
        self.service.rpc("quality.settings.set", {"assistant_id": "one", "quality": [{"baseline_id": "strong"}],
                                                  "samples": [self.sample("strong").__dict__], "authorized": True})
        self.assertIsNone(self.storage.get_meta(SELECTION_SCHEMA + ":one"))
        self.assertNotIn("samples", self.storage.get_meta("quality-routing/settings/v1"))
        self.assertTrue(all(not candidate.quality for candidate in self.service.engine.candidates()))

    def test_unknown_price_can_lead_but_cannot_be_automatic_role(self):
        self.configure()
        self.qualify()
        self.prices["strong"] = None
        self.prices["cheap"] = None
        result = self.service.select_bindings("one")
        self.assertEqual(result["leader_candidate_id"], "strong")
        self.assertIsNone(result["role_candidate_id"])
        self.assertEqual(self.reason(result, "cheap", "role"), "known-role-price-required")

    def test_plan_resolves_leader_without_overwriting_fixed_bindings_or_task_pool(self):
        self.configure(leader_candidate_id="weak", role_candidate_id="strong")
        self.qualify()
        task = self.service.plan(self.plan_params())
        self.assertEqual([profile_id for profile_id, _request in self.calls], ["strong"])
        self.assertEqual(task["plan"]["nodes"][0]["baseline_id"], "strong")
        self.assertEqual(task["selection"]["role_candidate_id"], "cheap")
        snapshot = self.service.engine.snapshot(task["task_id"], Scope("one", "session-one"))
        self.assertEqual(snapshot["allowed_ids"], ["cheap", "strong"])
        self.assertEqual(self.service.settings("one")["leader_candidate_id"], "weak")
        self.assertEqual(self.service.settings("one")["role_candidate_id"], "strong")
        self.assertTrue(all(not candidate.quality for candidate in self.service.engine.candidates()))

    def test_auto_plan_requires_explicit_pool_including_resolved_leader(self):
        self.configure(candidate_pool=["strong", "cheap"])
        self.qualify()
        for pool in (None, [], ["cheap"], ["strong", "weak"]):
            with self.subTest(pool=pool), self.assertRaises(RoutingError):
                self.service.plan(self.plan_params(allowed_candidate_ids=pool))
        with self.assertRaises(RoutingError):
            self.service.plan({**self.params, "planning_confirmed": True})
        self.assertEqual(self.calls, [])
        task = self.service.plan(self.plan_params(allowed_candidate_ids=["strong"]))
        self.assertEqual(self.service.engine.snapshot(task["task_id"], Scope("one", "session-one"))["allowed_ids"], ["strong"])

    def test_fixed_unavailable_leader_blocks_without_silent_role_fallback(self):
        self.configure(leader_candidate_id="strong", role_candidate_id="cheap", selection_mode={"leader": "fixed", "role": "fixed"})
        self.qualify()
        self.routes[0] = replace(self.routes[0], routable=False)
        result = self.service.select_bindings("one")
        self.assertIsNone(result["leader_candidate_id"])
        self.assertEqual(result["bindings"]["leader"]["reason"], "fixed-unavailable-or-unauthorized")
        with self.assertRaisesRegex(RoutingError, "leader selection blocked"):
            self.service.plan(self.plan_params())
        self.assertEqual(self.calls, [])

    def test_auto_leader_does_not_silently_change_after_an_authorized_plan(self):
        self.configure()
        self.qualify()
        self.service.plan(self.plan_params())
        self.routes[0] = replace(self.routes[0], status="unavailable", routable=False)
        resolution = self.service.select_bindings("one")
        self.assertIsNone(resolution["leader_candidate_id"])
        self.assertEqual(resolution["bindings"]["leader"]["reason"], "leader-change-needs-confirmation")
        self.assertEqual(resolution["bindings"]["leader"]["recommended_candidate_id"], "cheap")
        count_before = len(self.calls)
        with self.assertRaisesRegex(RoutingError, "leader-change-needs-confirmation"):
            self.service.plan(self.plan_params())
        self.assertEqual(len(self.calls), count_before)
        self.configure(candidate_pool=["cheap"])
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "cheap")

    def test_fixed_unavailable_role_runtime_blocks_without_automatic_switch(self):
        self.configure(role_candidate_id="cheap", selection_mode={"leader": "fixed", "role": "fixed"})
        self.qualify()
        self.routes[1] = replace(self.routes[1], health_state="unhealthy")
        with self.assertRaisesRegex(RoutingError, "role selection blocked"):
            self.service.role_runtime("one")
        self.assertEqual(self.service.settings("one")["role_candidate_id"], "cheap")

    def test_auto_role_never_becomes_missing_planning_leader(self):
        self.configure(selection_mode={"leader": "fixed", "role": "auto"})
        self.qualify()
        with self.assertRaisesRegex(RoutingError, "leader selection blocked"):
            self.service.plan(self.plan_params())
        self.assertEqual(self.calls, [])

    def test_paid_and_unknown_auto_planning_require_explicit_request_confirmation(self):
        self.configure(selection_mode={"leader": "auto", "role": "fixed"})
        self.qualify()
        for price in (Decimal("3"), None):
            self.prices["strong"] = price
            with self.subTest(price=price), self.assertRaisesRegex(RoutingError, "explicit planning_confirmed"):
                self.service.plan({**self.params, "allowed_candidate_ids": ["strong"]})
            for consent in (False, None, 1, "true"):
                with self.subTest(price=price, consent=consent), self.assertRaises(RoutingError):
                    self.service.plan(self.plan_params(planning_confirmed=consent))
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.storage.get_meta("quality-session-owner:session-one"))
        self.assertEqual(self.storage.load_quality_tasks(), [])
        task = self.service.plan(self.plan_params())
        self.assertEqual(task["status"], "awaiting-confirmation")
        self.assertIsNone(task["budget"]["quote"]["high_cny"])

    def test_external_consent_remains_independent_and_zero_cash_auto_can_plan(self):
        self.configure()
        self.qualify()
        self.prices["strong"] = Decimal(0)
        with self.assertRaisesRegex(RoutingError, "external summary sharing"):
            self.service.plan(self.plan_params(external_allowed=False))
        task = self.service.plan({**self.params, "allowed_candidate_ids": ["strong"]})
        self.assertEqual(task["status"], "awaiting-confirmation")
        self.assertEqual(len(self.calls), 1)

    def test_unknown_consultation_requires_confirmation_before_any_planning_call(self):
        self.service.browser.attach()
        self.configure(candidate_pool=["strong", "native-chatgpt"], selection_mode={"leader": "auto", "role": "fixed"})
        self.qualify()
        self.prices["strong"] = Decimal(0)
        with patch.object(self.service.browser, "consult") as consult:
            with self.assertRaisesRegex(RoutingError, "explicit planning_confirmed"):
                self.service.plan({**self.params, "allowed_candidate_ids": ["strong", "native-chatgpt"]})
            consult.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_legacy_fixed_paid_and_role_only_planning_workflows_remain_supported(self):
        self.service.update_settings({"assistant_id": "one", "role_candidate_id": "cheap"})
        task = self.service.plan(self.params)
        self.assertEqual(task["status"], "awaiting-confirmation")
        self.assertEqual(task["selection"]["planning_authorization"], "legacy-fixed-workflow")
        self.assertEqual(task["selection"]["bindings"]["leader"]["reason"], "legacy-fixed-role-fallback")
        self.assertEqual(task["selection"]["leader_candidate_id"], "cheap")
        self.assertEqual(task["plan"]["nodes"][0]["baseline_id"], "cheap")
        self.assertEqual(len(self.calls), 1)

    def test_fixed_workflow_does_not_depend_on_optional_selection_evidence(self):
        self.service.update_settings({"assistant_id": "one", "leader_candidate_id": "strong"})
        self.storage.set_meta(SELECTION_SCHEMA + ":one", "invalid optional evidence")
        task = self.service.plan(self.params)
        self.assertEqual(task["plan"]["nodes"][0]["baseline_id"], "strong")

    def test_plan_uses_one_settings_snapshot_for_selection_and_confirmation(self):
        fixed_settings = self.service.update_settings({"assistant_id": "one", "leader_candidate_id": "strong"})
        automatic_settings = self.configure(selection_mode={"leader": "auto", "role": "fixed"})
        self.qualify()
        with patch.object(self.service, "settings", side_effect=[automatic_settings, fixed_settings]) as settings:
            with self.assertRaisesRegex(RoutingError, "explicit planning_confirmed"):
                self.service.plan({**self.params, "allowed_candidate_ids": ["strong"]})
        settings.assert_called_once_with("one")
        self.assertEqual(self.calls, [])

    def test_replan_alias_keeps_original_leader_pool_and_approval_gate(self):
        self.configure()
        self.qualify()
        task = self.service.plan(self.plan_params())
        params = {**self.params, "task_id": task["task_id"]}
        with self.assertRaisesRegex(RoutingError, "task not authorized"):
            self.service.rpc("quality.task.replan", params)
        self.assertEqual(len(self.calls), 1)
        scope = Scope("one", "session-one")
        self.service.engine.approve(task["task_id"], scope, 1)
        self.configure(candidate_pool=["cheap"])
        with patch.object(self.service, "_start"):
            revised = self.service.rpc("quality.task.replan", params)
        self.assertEqual(revised["revision"], 2)
        self.assertEqual([profile_id for profile_id, _request in self.calls], ["strong", "strong"])
        self.assertEqual(revised["plan"]["nodes"][0]["baseline_id"], "strong")
        self.assertEqual(self.service.engine.snapshot(task["task_id"], scope)["allowed_ids"], ["cheap", "strong"])

    def test_resource_metadata_does_not_zero_cash_estimates_or_authorize_planning(self):
        self.routes[0] = replace(self.routes[0], metadata={**self.routes[0].metadata, "resource_pack": {"remaining_tokens": 1000000}})
        self.configure()
        self.qualify()
        self.service.select_bindings("one")
        candidate = self.service._candidate("strong")
        self.assertEqual(candidate.estimate(4000, 1000), Decimal("3"))
        with self.assertRaisesRegex(RoutingError, "explicit planning_confirmed"):
            self.service.plan({**self.params, "allowed_candidate_ids": ["strong"]})

    def test_cohort_changes_require_version_and_minimum_three_samples(self):
        self.service.register_selection_cohort("one", self.cohort("leader"))
        with self.assertRaisesRegex(RoutingError, "new version"):
            self.service.register_selection_cohort("one", self.cohort("leader", minimum_score=Decimal("0.1")))
        with self.assertRaises(RoutingError):
            self.cohort("leader", minimum_samples=2)
        self.service.register_selection_cohort("one", self.cohort("leader", cohort_version="suite-2"))
        self.configure(selection_mode={"leader": "auto", "role": "fixed"})
        self.samples("strong")
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])

    def test_quality_query_can_release_an_observation_gate_without_refresh_or_grants(self):
        self.qualify()
        self.routes[0] = replace(self.routes[0], routable=False, metadata={**self.routes[0].metadata, "routable": False})
        before = self.storage.get_meta(SELECTION_SCHEMA + ":one")
        with patch.object(self.service, "catalog", side_effect=AssertionError("quality query must not refresh catalog")):
            result = self.service.selection_qualification("one", "strong", model_version="build-1")
        self.assertTrue(result["qualified"])
        self.assertEqual(result["authority"], "quality-only")
        self.assertEqual(result["successful_samples"], 3)
        self.assertNotIn("authorized", result)
        self.assertNotIn("routable", result)
        self.assertEqual(self.storage.get_meta(SELECTION_SCHEMA + ":one"), before)
        self.assertFalse(self.routes[0].routable)
        self.configure(candidate_pool=["cheap"])
        self.assertNotIn("strong", [candidate.candidate_id for candidate in self.service.engine.candidates()])
        self.assertEqual(self.calls, [])

    def test_storage_only_quality_query_works_before_service_catalog_initialization(self):
        self.qualify()
        store = SelectionEvidenceStore(self.storage)
        result = store.qualification("one", "strong", model_version="build-1", purpose="leader", now=self.now)
        self.assertTrue(result["qualified"])
        self.assertFalse(store.qualification("two", "strong", model_version="build-1", now=self.now)["qualified"])
        self.assertFalse(store.qualification("one", "strong", model_version="build-2", now=self.now)["qualified"])
        self.app._refresh_route_supervisor_catalog.assert_not_called()

    def test_quality_query_priors_cannot_replace_successful_samples(self):
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.service.register_quality_prior("one", self.prior("strong"))
        self.samples("strong", total=2)
        result = self.service.selection_qualification("one", "strong", model_version="build-1")
        self.assertFalse(result["qualified"])
        self.assertEqual(result["reason"], "successful-fixed-samples-required")

    def test_quality_query_cannot_omit_or_misstate_full_id_effort(self):
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.samples("strong:effort:high")
        query = lambda **kwargs: self.service.selection_qualification("one", "strong:effort:high", model_version="build-1", **kwargs)
        self.assertFalse(query()["qualified"])
        self.samples("strong:effort:high", applied_reasoning_effort="high")
        self.assertTrue(query()["qualified"])
        with self.assertRaises(RoutingError):
            query(reasoning_effort="off")
        with self.assertRaises(RoutingError):
            self.service.selection_qualification("one", "strong", model_version="build-1", reasoning_effort="high")

    def test_catalog_model_version_accepts_host_projection_but_rejects_conflicts(self):
        self.configure()
        self.qualify()
        self.routes[0] = replace(self.routes[0], metadata={"model_entry": {"model_id": "basic-tiny", "metadata": {"model_version": "build-1"}}})
        self.assertEqual(self.service.select_bindings("one")["leader_candidate_id"], "strong")
        self.routes[0] = replace(self.routes[0], metadata={**self.routes[0].metadata, "model_version": "build-2"})
        self.assertEqual(self.reason(self.service.select_bindings("one"), "strong"), "model-version-required")

    def test_multiple_versioned_prior_sources_use_only_supplied_scores(self):
        self.service.register_selection_cohort("one", self.cohort("leader"))
        self.samples("strong")
        query = lambda: self.service.selection_qualification("one", "strong", model_version="build-1")
        self.assertIsNone(query()["prior_score"])
        self.service.register_quality_prior("one", self.prior("strong", "0.9", source_id="source-a"))
        self.service.register_quality_prior("one", self.prior("strong", "0.3", source_id="source-b"))
        self.assertEqual(query()["prior_score"], "0.6")
        self.assertEqual(query()["score"], "0.9")
        self.service.register_quality_prior("one", self.prior("strong", "0.5", source_id="source-a", source_version="release-2"))
        self.assertEqual(query()["prior_score"], "0.4")
        stored = json.loads(self.storage.get_meta(SELECTION_SCHEMA + ":one"))
        self.assertEqual(len(stored["priors"]), 2)
        self.assertEqual({row["source_version"] for row in stored["priors"]}, {"release-1", "release-2"})
        self.assertEqual(self.calls, [])

    def test_prepaid_projection_merges_bounded_fields_without_replacing_cash_prices(self):
        self.app.model_policy.prepaid_projection = Mock(return_value={"prepaid_tokens": 5000, "prepaid_until": self.now + 3600,
                                                                      "funding_kind": "grant", "fixed_cash": 0, "authorized": True, "body": "not metadata"})
        self.service.catalog()
        candidate = self.service._candidate("strong")
        self.assertEqual(candidate.fixed_cash, Decimal("3"))
        self.assertEqual(candidate.prepaid_tokens, 5000)
        self.assertEqual(candidate.estimate(4000, 1000), Decimal(0))
        self.assertIsNone(candidate.estimate(4000, 1001))
        self.assertFalse(candidate.quote(4000, 1001).available)
        self.app.model_policy.prepaid_projection.assert_any_call("strong", "basic-tiny")
        self.assertNotIn("body", self.service._pricing(self.routes[0], "basic-tiny"))
        self.app.model_policy.prepaid_projection.return_value = {"prepaid_tokens": 5000, "prepaid_until": self.now - 1}
        self.service.catalog()
        self.assertIsNone(self.service._candidate("strong").estimate(4000, 1000))

    def test_prepaid_does_not_grant_quality_or_cover_unbounded_planning(self):
        self.app.model_policy.prepaid_projection = Mock(return_value={"prepaid_tokens": 12000, "prepaid_until": self.now + 3600, "funding_kind": "grant"})
        self.configure(selection_mode={"leader": "auto", "role": "fixed"})
        self.assertIsNone(self.service.select_bindings("one")["leader_candidate_id"])
        self.qualify()
        with self.assertRaisesRegex(RoutingError, "explicit planning_confirmed"):
            self.service.plan({**self.params, "goal": "长任务" * 3000, "allowed_candidate_ids": ["strong"]})
        self.assertEqual(self.calls, [])
        task = self.service.plan({**self.params, "allowed_candidate_ids": ["strong"]})
        self.assertEqual(task["status"], "awaiting-confirmation")
        self.assertEqual(self.service._candidate("strong").fixed_cash, Decimal("3"))

    def test_official_free_projection_sets_forecast_rates_not_a_cash_receipt(self):
        self.app.model_policy.official_free_projection = Mock(return_value=True)
        self.service.catalog()
        candidate = self.service._candidate("strong")
        self.assertEqual(candidate.pricing_source, "official-page-observation")
        self.assertIsNone(candidate.fixed_cash)
        self.assertEqual((candidate.cash_per_million_input, candidate.cash_per_million_output, candidate.cached_input_rate),
                         (Decimal(0), Decimal(0), Decimal(0)))
        self.app.model_policy.official_free_projection.assert_any_call("strong", "basic-tiny")
        result = self.service._invoke(candidate, Scope("one", "session-one"), "Compute", threading.Event(), 1000)
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.cash_cny)
        self.assertEqual(result.input_tokens, 100)
        for value in (False, 1, "true"):
            self.app.model_policy.official_free_projection.return_value = value
            self.assertEqual(self.service._pricing(self.routes[0], "basic-tiny")["fixed_cash"], Decimal("3"))

    def test_prepaid_zero_forecast_does_not_become_actual_zero_cash(self):
        self.app.model_policy.prepaid_projection = Mock(return_value={"prepaid_tokens": 5000, "prepaid_until": self.now + 3600, "funding_kind": "grant"})
        self.service.catalog()
        candidate = self.service._candidate("strong")
        self.assertEqual(candidate.estimate(100, 30), Decimal(0))
        result = self.service._invoke(candidate, Scope("one", "session-one"), "Compute", threading.Event(), 1000)
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.cash_cny)
        self.assertEqual(result.output_tokens, 30)


if __name__ == "__main__":
    unittest.main()
