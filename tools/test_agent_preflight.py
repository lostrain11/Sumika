import unittest
from unittest.mock import patch

try:
    import agent_preflight as preflight
except ModuleNotFoundError:  # Running as ``python -m unittest tools...`` from the repo root.
    from tools import agent_preflight as preflight

PreflightError = preflight.PreflightError
_safe_base_url = preflight._safe_base_url
run_preflight = preflight.run_preflight
DEFAULT_CORE_URL = preflight.DEFAULT_CORE_URL


class AgentPreflightTests(unittest.TestCase):
    def test_default_core_url_targets_desktop_core(self):
        self.assertEqual(DEFAULT_CORE_URL, "http://127.0.0.1:8771")

    def test_safe_base_url_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            _safe_base_url("https://user:secret@example.test")

    def test_missing_core_is_unavailable_without_follow_up_requests(self):
        with patch.object(preflight, "_request_json", side_effect=PreflightError("URLError")) as request:
            report = run_preflight("http://127.0.0.1:8770")
        self.assertEqual(report["overall"], "unavailable")
        self.assertEqual(report["checks"][0]["id"], "core")
        request.assert_called_once_with("http://127.0.0.1:8770", "/api/health", timeout=3.0)

    def test_ready_runtime_requires_provider_and_workspace(self):
        responses = {
            "/api/health": {"ok": True, "version": "0.1.0"},
            "/api/agent/status": {"ready": True, "runtime_id": "dsh", "state": "ready"},
            "/api/agent/provider": {"ready": False, "state": "unconfigured", "reason": "configure"},
            "/rpc": {"result": {"workspaces": []}},
            "/api/agent/diagnostics": {"summary": {"available": 2}, "mcp": {"status": "not-exposed"}},
        }

        def request(_base, path, **_kwargs):
            return responses[path]

        with patch.object(preflight, "_request_json", side_effect=request):
            report = run_preflight("http://127.0.0.1:8770")
        self.assertEqual(report["overall"], "needs-action")
        self.assertEqual({item["id"] for item in report["checks"]}, {"core", "agent-runtime", "provider", "workspace", "capabilities"})
        self.assertIn("Provider", " ".join(report["next_actions"]))


if __name__ == "__main__":
    unittest.main()
