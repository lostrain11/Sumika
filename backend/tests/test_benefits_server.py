import unittest
from unittest.mock import patch

from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication
from trusted_host_fixture import trusted_rpc


class BenefitsServerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"SUMIKA_DSH_ENABLED": "0"})
        self.environment.start()
        self.application = CoreApplication(":memory:")

    def tearDown(self):
        self.application.close()
        self.environment.stop()

    def test_new_app_status_is_offline_and_disabled(self):
        with patch.object(self.application.benefits, "collector") as collector:
            status = self.application.rpc("benefits.status", {})
            self.assertFalse(status["enabled"])
            self.assertEqual(status["schema"], "free-benefits/v1")
            collector.assert_not_called()

    def test_rpc_rejects_external_evidence_and_arbitrary_browser_commands(self):
        for method in ("benefits.status", "benefits.refresh", "benefits.checkin", "benefits.browsers", "benefits.configure"):
            with self.subTest(method=method), self.assertRaises(JsonRpcError) as error:
                params = {"url": "https://example.org", "grants": []}
                if method in {"benefits.refresh", "benefits.checkin", "benefits.configure"}:
                    trusted_rpc(self.application, method, params)
                else:
                    self.application.rpc(method, params)
            self.assertEqual(error.exception.code, -32602)

    def test_async_request_uses_service_without_touching_model_policy(self):
        with patch.object(self.application.benefits, "request", return_value={"running": True}) as request:
            result = trusted_rpc(self.application, "benefits.refresh", {})
            self.assertTrue(result["running"])
            request.assert_called_once_with("refresh")

    def test_checkin_is_not_authorized_by_loading_page(self):
        with self.assertRaises(JsonRpcError):
            self.application.rpc("benefits.checkin", {})


if __name__ == "__main__":
    unittest.main()
