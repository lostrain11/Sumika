from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

try:
    from tools import model_preflight
except ImportError:  # direct ``python tools/test_model_preflight.py``
    import model_preflight


class _OllamaHandler(BaseHTTPRequestHandler):
    payload = {"data": [{"id": "qwen3:4b"}, {"id": "qwen3:1.7b"}]}

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.payload).encode("utf-8"))

    def log_message(self, *_args):
        return None


class _FakeZCode:
    def __init__(self, *_args, **_kwargs):
        self.closed = False

    def health(self):
        return {"ok": True}

    def runtime_models(self):
        return {"groups": [{"id": "zai", "models": [{"id": "glm-5.1"}]}]}

    def quota_status(self):
        return {"state": "unknown", "source": "zcode-app-server-not-exposed"}

    def status(self):
        return {"wire_protocol": "zcode"}

    def close(self):
        self.closed = True


class ModelPreflightTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_ollama_directory_is_read_without_chat_request(self):
        result = model_preflight.check_ollama(self.url, expected_model="qwen3:4b")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["models"], ["qwen3:4b", "qwen3:1.7b"])

    def test_missing_target_model_needs_action(self):
        result = model_preflight.check_ollama(self.url, expected_model="missing")
        self.assertEqual(result["status"], "needs-action")
        self.assertNotIn("response", result)

    def test_invalid_endpoint_rejects_credentials(self):
        with self.assertRaises(ValueError):
            model_preflight._safe_base_url("https://user:pass@example.com")

    def test_zcode_is_explicit_and_quota_unknown_is_not_free(self):
        values = {
            "SUMIKA_ZCODE_EXECUTABLE": "node",
            "SUMIKA_ZCODE_SCRIPT": "public.cjs",
            "SUMIKA_ZCODE_PROTOCOL": "zcode",
        }
        with patch.object(model_preflight, "ZCodeAgentRuntime", _FakeZCode), patch.object(
            model_preflight, "config_from_env", return_value=type("Config", (), {"enabled": True, "executable": "node"})()
        ):
            report = model_preflight.run_preflight([], include_zcode=True, zcode_environment=values)
        self.assertEqual(report["overall"], "needs-action")
        check = report["checks"][0]
        self.assertEqual(check["status"], "ready")
        self.assertEqual(check["quota"]["state"], "unknown")
        self.assertEqual(report["chat_requests_sent"], 0)
        self.assertFalse(report["credentials_read"])

    def test_zcode_is_not_started_when_not_explicitly_configured(self):
        with patch.object(model_preflight, "ZCodeAgentRuntime") as runtime:
            result = model_preflight.check_zcode(environment={})
        self.assertEqual(result["status"], "needs-action")
        runtime.assert_not_called()


if __name__ == "__main__":
    unittest.main()
