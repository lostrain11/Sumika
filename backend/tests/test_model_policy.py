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

    def test_store_round_trip_does_not_include_presentation_only_flags_as_required_input(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = ModelCatalogStore(data_dir)
            store.upsert_entries([entry("local:one")])
            store.save()
            loaded = ModelCatalogStore(data_dir)
            self.assertEqual(loaded.entries()[0].route_id, "local:one")
            self.assertTrue(loaded.entries()[0].routable)


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
