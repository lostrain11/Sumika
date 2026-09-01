import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sumika_core.model_policy import (
    ModelCatalogEntry,
    ModelCatalogStore,
    ModelPolicyService,
    ModelRouter,
    QuotaSnapshot,
    RoutingRequest,
    routing_request_from_dict,
)
from sumika_core.route_pricing import CostEstimate


def entry(route_id, *, model_id="model", quality="standard", cost="local", location="local", **kwargs):
    return ModelCatalogEntry(
        route_id=route_id,
        provider_id=kwargs.pop("provider_id", "fixture"),
        model_id=model_id,
        display_name=kwargs.pop("display_name", route_id),
        quality_tier=quality,
        cost_class=cost,
        processing_location=location,
        auth_state=kwargs.pop("auth_state", "not-required" if location == "local" else "authorized"),
        quota_state=kwargs.pop("quota_state", "not-applicable" if location == "local" else "available"),
        health_state=kwargs.pop("health_state", "healthy"),
        **kwargs,
    )


class ModelRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = ModelRouter()

    def test_local_candidate_is_selected_for_basic_work(self):
        decision = self.router.decide(
            RoutingRequest(task_kind="greeting", confirmation_mode="automatic"),
            [entry("local:small", quality="basic")],
        )
        self.assertEqual(decision.status, "selected")
        self.assertEqual(decision.selected_route, "local:small")
        self.assertFalse(decision.requires_confirmation)

    def test_paid_candidate_requires_confirmation_even_in_automatic_mode(self):
        decision = self.router.decide(
            RoutingRequest(task_kind="chat", min_quality_tier="standard", confirmation_mode="automatic"),
            [entry("cloud:paid", quality="standard", cost="paid-low", location="cloud")],
        )
        self.assertEqual(decision.status, "needs-confirmation")
        self.assertTrue(decision.requires_confirmation)
        self.assertIn("cost_or_quota_confirmation_required", decision.reason_codes)

    def test_unknown_cost_is_not_accepted_by_free_only_policy(self):
        decision = self.router.decide(
            RoutingRequest(task_kind="chat", budget_policy="free-only", confirmation_mode="automatic"),
            [entry("cloud:unknown", quality="standard", cost="unknown", location="cloud")],
        )
        self.assertEqual(decision.status, "no-compatible-route")
        self.assertIn("paid_disallowed", decision.reason_codes)

    def test_free_candidate_wins_over_unknown_cost_when_available(self):
        decision = self.router.decide(
            RoutingRequest(task_kind="chat", confirmation_mode="automatic"),
            [
                entry("cloud:unknown", quality="standard", cost="unknown", location="cloud"),
                entry("cloud:free", quality="standard", cost="free-limited", location="cloud"),
            ],
        )
        self.assertEqual(decision.selected_route, "cloud:free")
        self.assertEqual(decision.status, "selected")

    def test_known_cash_estimate_breaks_tie_between_paid_routes(self):
        expensive = entry("cloud:expensive", quality="standard", cost="paid-low", location="cloud")
        cheaper = entry("cloud:cheaper", quality="standard", cost="paid-low", location="cloud")
        decision = self.router.decide(
            RoutingRequest(task_kind="chat", confirmation_mode="automatic"),
            [expensive, cheaper],
            cost_estimates={
                expensive.route_id: CostEstimate(expensive.route_id, "known", cash_currency="CNY", cash_min=2, cash_max=3),
                cheaper.route_id: CostEstimate(cheaper.route_id, "known", cash_currency="CNY", cash_min=0.5, cash_max=1),
            },
        )
        self.assertEqual(decision.selected_route, cheaper.route_id)
        self.assertEqual(decision.cost_estimate["cash_max"], 1)

    def test_privacy_constraint_excludes_cloud(self):
        decision = self.router.decide(
            RoutingRequest(task_kind="chat", privacy_constraints=("local-only",)),
            [entry("cloud:one", quality="standard", cost="free-limited", location="cloud")],
        )
        self.assertEqual(decision.status, "no-compatible-route")
        self.assertIn("privacy_constraint:1", decision.reason_codes)

    def test_exhausted_quota_is_not_routable(self):
        candidate = entry("cloud:one", quality="standard", cost="free-limited", location="cloud")
        decision = self.router.decide(
            RoutingRequest(task_kind="chat"),
            [candidate],
            {candidate.route_id: QuotaSnapshot(route_id=candidate.route_id, state="exhausted")},
        )
        self.assertEqual(decision.status, "no-compatible-route")
        self.assertIn("quota_exhausted:1", decision.reason_codes)

    def test_web_entry_is_never_silently_routable(self):
        web = entry(
            "web:chatgpt",
            model_id="web-session",
            quality="standard",
            cost="free-limited",
            location="cloud",
            auth_state="needs-auth",
            health_state="unknown",
            source_kind="web-chat",
            transport="browser-dom",
            metadata={"routable": False},
        )
        self.assertTrue(web.requires_browser)
        self.assertFalse(web.routable)
        decision = self.router.decide(RoutingRequest(task_kind="chat"), [web])
        self.assertEqual(decision.status, "no-compatible-route")
        self.assertIn("auth_not_ready:1", decision.reason_codes)


class _ProfileFixture:
    def __init__(self, profiles, secrets=None):
        self.profiles = profiles
        self.secrets = secrets or {}
        self.health_calls = []

    def list(self, *, include_archived=False):
        return list(self.profiles)

    def health(self, profile_id):
        self.health_calls.append(profile_id)
        return {"ok": True}

    def get(self, profile_id, *, include_secrets=False):
        value = next(profile for profile in self.profiles if profile["id"] == profile_id)
        result = dict(value)
        if include_secrets:
            result["secrets"] = dict(self.secrets.get(profile_id, {}))
        return result


class _AgentFixture:
    runtime_id = "fixture"

    def status(self):
        return {"ready": True}

    def supports(self, capability):
        return str(capability) in {"models", "AgentCapability.MODELS"} or getattr(capability, "value", None) == "models"

    def session_models(self, params):
        self.session_id = params["session_id"]
        return {"groups": [{"id": "fixture", "name": "Fixture", "models": [{"id": "qwen3:4b"}]}]}


class _GlobalModelQuotaFixture(_AgentFixture):
    def __init__(self, quota):
        self.quota = quota
        self.quota_calls = 0

    def runtime_models(self, params=None):
        del params
        return {"groups": [{"id": "zcode", "name": "ZCode", "models": [{"id": "glm-4.5-air"}]}]}

    def quota_status(self, params=None):
        del params
        self.quota_calls += 1
        return dict(self.quota)


class _WebChatFixture:
    def list_adapters(self):
        return [
            {"id": "deepseek-web", "name": "DeepSeek 网页聊天", "custom": False},
            {"id": "custom", "name": "通用网页聊天", "custom": True},
        ]

    def list_profiles(self, *, include_archived=False):
        del include_archived
        return [
            {
                "id": "web-chat-authorized",
                "name": "已授权网页账号",
                "adapter_id": "deepseek-web",
                "status": "ready",
                "auth_state": "authorized",
                "auto_chat_enabled": True,
                "allowed_actions": ["chat.read", "chat.send"],
                "budget_policy": "free-only",
                "config": {"model_id": "web-session"},
                "archived_at": None,
            }
        ]


class ModelPolicyServiceTests(unittest.TestCase):
    def test_service_projects_profiles_web_entries_and_session_models(self):
        profiles = _ProfileFixture(
            [
                {
                    "id": "local",
                    "name": "Local Ollama",
                    "adapter_id": "openai-compatible",
                    "template_id": "ollama",
                    "processing_location": "local",
                    "status": "available",
                    "has_secrets": False,
                    "config": {"model": "qwen3:4b"},
                }
            ]
        )
        agent = _AgentFixture()
        with tempfile.TemporaryDirectory() as data_dir:
            service = ModelPolicyService(profiles, agent, data_dir)
            catalog = service.catalog(session_id="session-1")
            routes = {item["route_id"] for item in catalog["entries"]}
            self.assertIn("profile:local:qwen3:4b", routes)
            self.assertIn("harness:fixture:fixture:qwen3:4b", routes)
            self.assertIn("web:chatgpt-web", routes)
            self.assertEqual(agent.session_id, "session-1")

            decision = service.decide(
                {"taskKind": "greeting", "confirmationMode": "automatic"},
                session_id="session-1",
            )
            self.assertEqual(decision["decision"]["selected_route"], "profile:local:qwen3:4b")

    def test_one_profile_projects_one_route_per_enabled_model(self):
        profiles = _ProfileFixture(
            [
                {
                    "id": "zhipu",
                    "name": "智谱",
                    "adapter_id": "openai-compatible",
                    "template_id": "zhipu-bigmodel",
                    "processing_location": "cloud",
                    "status": "available",
                    "has_secrets": True,
                    "config": {
                        "model": "glm-4.5-air",
                        "models": [
                            {"id": "glm-4.5-air", "enabled": True, "health_state": "healthy"},
                            {"id": "glm-4.6", "enabled": True, "health_state": "healthy"},
                            {"id": "glm-4.7", "enabled": False, "health_state": "healthy"},
                        ],
                    },
                }
            ]
        )
        with tempfile.TemporaryDirectory() as data_dir:
            service = ModelPolicyService(profiles, agent=None, data_dir=data_dir)
            entries = {item["route_id"]: item for item in service.catalog()["entries"]}
        self.assertIn("profile:zhipu:glm-4.5-air", entries)
        self.assertIn("profile:zhipu:glm-4.6", entries)
        self.assertIn("profile:zhipu:glm-4.7", entries)
        self.assertTrue(entries["profile:zhipu:glm-4.5-air"]["routable"])
        self.assertTrue(entries["profile:zhipu:glm-4.6"]["routable"])
        self.assertFalse(entries["profile:zhipu:glm-4.7"]["routable"])

    def test_cloud_model_name_does_not_imply_free_pricing(self):
        profiles = _ProfileFixture(
            [
                {
                    "id": "unpriced-cloud",
                    "name": "Unpriced cloud",
                    "adapter_id": "openai-compatible",
                    "template_id": "openai-compatible",
                    "processing_location": "cloud",
                    "status": "available",
                    "has_secrets": True,
                    "config": {
                        "model": "free-model-by-name-only",
                        "models": [
                            {
                                "id": "free-model-by-name-only",
                                "enabled": True,
                                "health_state": "healthy",
                                "cost_class": "free-limited",
                            }
                        ],
                    },
                }
            ]
        )
        with tempfile.TemporaryDirectory() as data_dir:
            service = ModelPolicyService(profiles, data_dir=data_dir)
            route = next(
                item
                for item in service.catalog()["entries"]
                if item["route_id"] == "profile:unpriced-cloud:free-model-by-name-only"
            )
            estimate = service.pricing.estimate(route, {"task_kind": "chat"})
        self.assertEqual(route["cost_class"], "unknown")
        self.assertEqual(route["metadata"]["pricing_status"], "unknown")
        self.assertEqual(estimate.status, "unknown")

    def test_new_api_pricing_enables_same_origin_token_usage_quota(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                requests.append((self.path, self.headers.get("Authorization")))
                if self.path == "/api/status":
                    payload = {"success": True, "data": {"quota_per_unit": 500_000}}
                elif self.path == "/api/pricing":
                    payload = {
                        "success": True,
                        "pricing_version": "fixture-v1",
                        "group_ratio": {"default": 1},
                        "data": [
                            {
                                "model_name": "fixture-model",
                                "enable_groups": ["default"],
                                "quota_type": 0,
                                "model_ratio": 1,
                                "completion_ratio": 2,
                            }
                        ],
                    }
                elif self.path == "/api/usage/token/":
                    payload = {
                        "code": True,
                        "data": {
                            "total_granted": 3_000_000,
                            "total_used": 500_000,
                            "total_available": 2_500_000,
                        },
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f"http://127.0.0.1:{server.server_port}"
            profile = {
                "id": "new-api-relay",
                "name": "New API relay",
                "adapter_id": "openai-compatible",
                "template_id": "openai-compatible",
                "processing_location": "cloud",
                "status": "available",
                "has_secrets": True,
                "config": {
                    "active_base_url": f"{origin}/v1",
                    "model": "fixture-model",
                    "models": [{"id": "fixture-model", "enabled": True, "health_state": "healthy"}],
                    "pricing": {"source_type": "new-api", "public_url": origin, "billing_group": "default"},
                },
            }
            profiles = _ProfileFixture([profile], secrets={profile["id"]: {"api_key": "fixture-secret"}})
            with tempfile.TemporaryDirectory() as data_dir:
                service = ModelPolicyService(profiles, data_dir=data_dir)
                catalog = service.catalog(refresh=True)
            quota = next(item for item in catalog["quotas"] if item["route_id"] == "profile:new-api-relay:fixture-model")
            self.assertEqual(quota["state"], "available")
            self.assertEqual(quota["remaining_min"], 5)
            self.assertEqual(quota["used"], 1)
            self.assertEqual(quota["total"], 6)
            self.assertEqual(quota["unit"], "CNY")
            self.assertEqual(quota["source"], "new-api-token-usage")
            usage_request = next(item for item in requests if item[0] == "/api/usage/token/")
            self.assertEqual(usage_request[1], "Bearer fixture-secret")
            self.assertTrue(all(header is None for path, header in requests if path != "/api/usage/token/"))
        finally:
            server.shutdown()
            server.server_close()

    def test_manual_pricing_projects_dual_cost_estimate(self):
        profiles = _ProfileFixture(
            [
                {
                    "id": "relay",
                    "name": "Relay",
                    "adapter_id": "openai-compatible",
                    "template_id": "openai-compatible",
                    "processing_location": "cloud",
                    "status": "available",
                    "has_secrets": True,
                    "config": {
                        "model": "fixture-model",
                        "models": [{"id": "fixture-model", "enabled": True, "health_state": "healthy"}],
                        "pricing": {
                            "source_type": "manual",
                            "billing_group": "经济组",
                            "rates": {
                                "currency": "USD-credit",
                                "input_price_per_million": 1,
                                "output_price_per_million": 4,
                            },
                            "cash_conversion": {"paid_amount": 50, "credited_amount": 100, "currency": "CNY"},
                        },
                    },
                }
            ]
        )
        with tempfile.TemporaryDirectory() as data_dir:
            service = ModelPolicyService(profiles, data_dir=data_dir)
            catalog = service.catalog()
            route = next(item for item in catalog["entries"] if item["route_id"] == "profile:relay:fixture-model")
            result = service.decide({"taskKind": "greeting", "confirmationMode": "automatic"})
        self.assertEqual(route["metadata"]["pricing_status"], "known")
        self.assertEqual(route["cost_class"], "paid-low")
        estimate = result["decision"]["cost_estimate"]
        self.assertEqual(estimate["status"], "known")
        self.assertEqual(estimate["provider_currency"], "USD-credit")
        self.assertEqual(estimate["cash_currency"], "CNY")
        self.assertGreater(estimate["cash_max"], 0)

    def test_declarative_quota_query_ignores_script_and_keeps_secrets_out_of_store(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                received.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"remaining": 42, "used": 8, "total": 50}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = {
                "id": "cloud",
                "name": "Cloud fixture",
                "adapter_id": "openai-compatible",
                "template_id": "openai-compatible",
                "processing_location": "cloud",
                "status": "available",
                "has_secrets": True,
                "config": {
                    "model": "fixture-model",
                    "active_base_url": f"http://127.0.0.1:{server.server_address[1]}",
                    "usage_query": {
                        "enabled": True,
                        "url": "{{baseUrl}}/usage",
                        "method": "GET",
                        "fields": {"remaining": "remaining", "used": "used", "total": "total", "unit": "tokens"},
                        "script": "raise RuntimeError('must never execute')",
                    },
                },
            }
            profiles = _ProfileFixture([profile], {"cloud": {"api_key": "fixture-secret"}})
            with tempfile.TemporaryDirectory() as data_dir:
                service = ModelPolicyService(profiles, data_dir=data_dir)
                result = service.quota_status(refresh=True)
                self.assertEqual(result["snapshots"][0]["state"], "available")
                self.assertEqual(result["snapshots"][0]["remaining_min"], 42.0)
                self.assertEqual(received, ["Bearer fixture-secret"])
                persisted = json.dumps(service.store.path.read_text(encoding="utf-8"))
                self.assertNotIn("fixture-secret", persisted)
                self.assertNotIn("must never execute", persisted)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_declarative_quota_query_rejects_cross_origin_credentials(self):
        received = []

        class UsageHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                received.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"remaining": 10}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), UsageHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = {
                "id": "cross-origin",
                "name": "Cross origin fixture",
                "adapter_id": "openai-compatible",
                "template_id": "openai-compatible",
                "processing_location": "cloud",
                "status": "available",
                "has_secrets": True,
                "config": {
                    "model": "fixture-model",
                    "active_base_url": "https://provider.example.invalid/v1",
                    "usage_query": {
                        "enabled": True,
                        "url": f"http://127.0.0.1:{server.server_address[1]}/usage",
                        "method": "GET",
                        "fields": {"remaining": "remaining"},
                    },
                },
            }
            profiles = _ProfileFixture([profile], {"cross-origin": {"api_key": "fixture-secret"}})
            with tempfile.TemporaryDirectory() as data_dir:
                result = ModelPolicyService(profiles, data_dir=data_dir).quota_status(refresh=True)
            self.assertEqual(result["snapshots"][0]["state"], "unknown")
            self.assertEqual(received, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_declarative_quota_query_blocks_cross_origin_redirect_without_forwarding_credentials(self):
        source_headers = []
        target_headers = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                target_headers.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"remaining":10}')

            def log_message(self, *_args):
                return None

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()

        class SourceHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                source_headers.append(self.headers.get("Authorization"))
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/usage")
                self.end_headers()

            def log_message(self, *_args):
                return None

        source = ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
        source_thread = threading.Thread(target=source.serve_forever, daemon=True)
        source_thread.start()
        try:
            profile = {
                "id": "redirect-origin",
                "name": "Redirect origin fixture",
                "adapter_id": "openai-compatible",
                "template_id": "openai-compatible",
                "processing_location": "cloud",
                "status": "available",
                "has_secrets": True,
                "config": {
                    "model": "fixture-model",
                    "active_base_url": f"http://127.0.0.1:{source.server_address[1]}/v1",
                    "usage_query": {
                        "enabled": True,
                        "url": "{{baseUrl}}/usage",
                        "method": "GET",
                        "fields": {"remaining": "remaining"},
                    },
                },
            }
            profiles = _ProfileFixture([profile], {"redirect-origin": {"api_key": "fixture-secret"}})
            with tempfile.TemporaryDirectory() as data_dir:
                result = ModelPolicyService(profiles, data_dir=data_dir).quota_status(refresh=True)
            self.assertEqual(result["snapshots"][0]["state"], "unknown")
            self.assertEqual(source_headers, ["Bearer fixture-secret"])
            self.assertEqual(target_headers, [])
        finally:
            source.shutdown()
            source.server_close()
            source_thread.join(timeout=2)
            target.shutdown()
            target.server_close()
            target_thread.join(timeout=2)

    def test_store_round_trip_does_not_include_presentation_only_flags_as_required_input(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = ModelCatalogStore(data_dir)
            store.upsert_entries([entry("local:one")])
            store.save()
            loaded = ModelCatalogStore(data_dir)
            self.assertEqual(loaded.entries()[0].route_id, "local:one")
            self.assertTrue(loaded.entries()[0].routable)

    def test_global_runtime_models_participate_in_preflight_and_runtime_quota_blocks_route(self):
        agent = _GlobalModelQuotaFixture({"state": "exhausted", "source": "zcode-app-server"})
        with tempfile.TemporaryDirectory() as data_dir:
            service = ModelPolicyService(provider_profiles=None, agent=agent, data_dir=data_dir)
            catalog = service.catalog()
            runtime_entries = [item for item in catalog["entries"] if item["source_kind"] == "harness"]
            self.assertEqual(len(runtime_entries), 1)
            self.assertEqual(runtime_entries[0]["quota_state"], "exhausted")
            service.catalog()
            self.assertEqual(agent.quota_calls, 1)
            decision = service.preflight({"taskKind": "greeting", "confirmationMode": "automatic"})
            self.assertEqual(decision["decision"]["status"], "no-compatible-route")
            self.assertIn("quota_exhausted:1", decision["decision"]["reason_codes"])
            # A preflight is an explicit live check and bypasses the cache.
            self.assertEqual(agent.quota_calls, 2)

    def test_web_profile_unknown_quota_is_not_projected_as_free(self):
        with tempfile.TemporaryDirectory() as data_dir:
            service = ModelPolicyService(
                provider_profiles=None,
                agent=None,
                data_dir=data_dir,
                web_chat=_WebChatFixture(),
            )
            catalog = service.catalog()
            profile_entry = next(
                item for item in catalog["entries"] if item["route_id"] == "web:web-chat-authorized"
            )
            self.assertEqual(profile_entry["cost_class"], "unknown")
            self.assertEqual(profile_entry["quota_state"], "unknown")
            self.assertTrue(profile_entry["metadata"]["routable"])

            decision = service.decide(
                {
                    "taskKind": "chat",
                    "budgetPolicy": "free-only",
                    "confirmationMode": "automatic",
                }
            )
            self.assertEqual(decision["decision"]["status"], "no-compatible-route")
            self.assertIn("paid_disallowed", decision["decision"]["reason_codes"])


class RoutingRequestTests(unittest.TestCase):
    def test_camel_case_request_is_normalized(self):
        request = routing_request_from_dict(
            {
                "taskKind": "code",
                "requiredCapabilities": ["chat", "tools"],
                "privacyConstraints": ["no-browser"],
                "budgetPolicy": "allow-paid",
            }
        )
        self.assertEqual(request.task_kind, "code")
        self.assertEqual(request.required_capabilities, ("chat", "tools"))
        self.assertEqual(request.privacy_constraints, ("no-browser",))
        self.assertEqual(request.budget_policy, "allow-paid")


if __name__ == "__main__":
    unittest.main()
