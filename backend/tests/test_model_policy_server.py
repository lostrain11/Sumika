import json
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication, create_server


class ModelPolicyServerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"SUMIKA_DSH_ENABLED": "0"})
        self.environment.start()
        self.application = CoreApplication(":memory:")

    def tearDown(self):
        self.application.close()
        self.environment.stop()

    def test_policy_catalog_and_quota_rpc_are_available_without_network_refresh(self):
        catalog = self.application.rpc("model.policy.catalog", {})
        self.assertEqual(catalog["policy_version"], "model-policy/v1")
        self.assertTrue(any(item["source_kind"] == "web-chat" for item in catalog["entries"]))
        quota = self.application.rpc("model.policy.quota", {})
        self.assertEqual(quota["policy_version"], "model-policy/v1")

    def test_policy_route_rejects_invalid_refresh_and_exposes_safe_decision(self):
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc("model.policy.catalog", {"refresh": "yes"})
        self.assertEqual(error.exception.code, -32602)

        result = self.application.rpc(
            "model.policy.route",
            {"taskKind": "chat", "confirmationMode": "automatic"},
        )
        self.assertIn("decision", result)
        self.assertNotIn("secrets", json.dumps(result, ensure_ascii=False))

    def test_refresh_rpc_cannot_forge_price_or_quality_evidence(self):
        with self.assertRaises(JsonRpcError):
            self.application.rpc("model.policy.refresh", {
                "kind": "catalog", "force": True,
                "modelObservations": [{"model_id": "glm-4.7-flash", "free_claim": True}],
            })
        result = self.application.rpc("model.policy.refresh", {"kind": "catalog"})
        self.assertEqual(result["changed"], {})
        status = self.application.rpc("model.policy.refresh.status", {})
        self.assertEqual(status["schema"], "model-refresh/v1")
        self.assertTrue(any(item["model_id"] == "glm-4.7-flash" for item in status["observations"]))
        self.assertEqual(status["jobs"]["pricing"]["state"], "never")

    def test_policy_apply_forwards_reasoning_and_records_runtime_ack(self):
        decision = {
            "selected_route": "harness:fixture:model",
            "selected_entry": {
                "provider_id": "fixture-provider",
                "model_id": "fixture-model",
                "harness_id": self.application.agent.runtime_id,
            },
            "requires_confirmation": False,
            "requested_reasoning_effort": "medium",
            "applied_reasoning_effort": "unknown",
        }
        with patch.object(
            self.application.agent,
            "select_model",
            return_value={"current": {"reasoning_effort": "medium"}},
        ) as select_model:
            result = self.application._apply_agent_route(
                decision,
                session_id="session-1",
                approved=True,
            )
        select_model.assert_called_once_with(
            {
                "session_id": "session-1",
                "provider": "fixture-provider",
                "model": "fixture-model",
                "reasoningEffort": "medium",
            }
        )
        self.assertEqual(result["decision"]["applied_reasoning_effort"], "medium")

    def test_diagnostics_contains_model_policy_summary(self):
        diagnostics = self.application.rpc("core.diagnostics", {})
        self.assertEqual(diagnostics["model_policy"]["version"], "model-policy/v1")
        self.assertGreaterEqual(diagnostics["model_policy"]["entry_count"], 3)

    def test_http_policy_catalog_endpoint(self):
        server, application = create_server("127.0.0.1", 0, ":memory:")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/api/model-policy/catalog")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["policy_version"], "model-policy/v1")
        finally:
            server.shutdown()
            server.server_close()
            application.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
