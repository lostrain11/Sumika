import json
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from sumika_core.server import create_server


class QualityHttpTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"contract-model"}]}')

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(request)
                prompt = request["messages"][-1]["content"]
                if "Return only a JSON object with nodes" in prompt:
                    answer = json.dumps({"nodes": [{"node_id": "answer", "goal": "Calculate six times seven", "task_type": "arithmetic", "acceptance": ["Answer equals 42"]}]})
                elif "Verify the task result" in prompt:
                    answer = '{"passed":true,"reason":"Exact answer"}'
                elif "short in-character introduction" in prompt:
                    answer = "Checked answer:"
                else:
                    answer = "42"
                delta = {"content": answer}
                if request.get("tools") and prompt == "Plan the calculation":
                    delta = {"tool_calls": [{"index": 0, "id": "call-plan", "type": "function", "function": {
                        "name": "sumika_plan_task", "arguments": '{"goal":"Calculate six times seven"}'}}]}
                payload = {"choices": [{"delta": delta}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode())

        self.remote = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.remote_thread = threading.Thread(target=self.remote.serve_forever, daemon=True)
        self.remote_thread.start()
        self.environment = patch.dict("os.environ", {"SUMIKA_AGENT_RUNTIME": "none", "SUMIKA_AGENT_AUTOSTART": "0", "SUMIKA_MODEL_PICKER_URL": ""})
        self.environment.start()
        self.server, self.app = create_server("127.0.0.1", 0, ":memory:")
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.close_servers)
        profile = self.app.provider_profiles.save({
            "name": "Contract relay", "base_url": f"http://127.0.0.1:{self.remote.server_address[1]}/v1",
            "model": "contract-model", "processing_location": "cloud",
            "api_key": "fixture-key-not-a-real-credential",
            "pricing": {"source_type": "manual", "billing_group": "contract-relay",
                        "rates": {"currency": "USD-credit", "input_price_per_million": 2, "output_price_per_million": 4},
                        "cash_conversion": {"paid_amount": 50, "credited_amount": 100, "currency": "CNY"}},
        })
        self.assertTrue(self.app.provider_profiles.health(profile["id"])["ok"])
        self.app.modules.update("llm", enabled=True, implementation_id="openai-compatible", config={"profile_id": profile["id"]})
        catalog = self.rpc("quality.catalog", {})
        self.candidate = next(item["candidate_id"] for item in catalog["candidates"] if item["model_id"] == "contract-model")
        self.rpc("quality.settings.set", {"assistant_id": "sumika", "role_candidate_id": self.candidate, "leader_candidate_id": self.candidate})

    def close_servers(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.server_thread.join(2)
        self.remote.shutdown()
        self.remote.server_close()
        self.remote_thread.join(2)
        self.environment.stop()

    def rpc(self, method, params):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            connection.request("POST", "/rpc", json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertNotIn("error", payload)
            return payload["result"]
        finally:
            connection.close()

    def test_real_http_role_tool_quote_confirmation_and_delivery(self):
        scope = {"assistant_id": "sumika", "session_id": "default"}
        chat = {"character_id": "sumika", "session_id": "default", "messages": [{"role": "user", "content": "hello"}]}
        ordinary = self.rpc("chat.send", chat)
        self.assertEqual(ordinary["status"], "awaiting-confirmation")
        self.assertEqual(len(self.calls), 0)
        approval = ordinary["work_request"]
        self.rpc("work.authorization.confirm", {**scope, "request_id": approval["request_id"], "revision": 1,
                                                "max_cny": approval["quote"]["high_cny"]})
        ordinary = self.rpc("chat.send", chat)
        self.assertEqual(ordinary["message"]["content"], "42")
        self.assertEqual(len(self.calls), 1)
        planned = self.rpc("work.task.preflight", {**scope, "goal": "Calculate six times seven"})
        self.assertEqual(planned["status"], "awaiting-confirmation")
        self.assertEqual(len(self.calls), 1)
        task_scope = {**scope, "request_id": planned["request_id"]}
        self.rpc("work.authorization.confirm", {**task_scope, "revision": 1, "max_cny": planned["quote"]["high_cny"]})
        self.rpc("work.task.submit", task_scope)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.rpc("work.task.get", task_scope)
            if result.get("status") in {"completed", "failed", "submission-unknown"}:
                break
            time.sleep(0.02)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["artifacts"][0]["content"], "42")
        self.assertEqual(result["task"]["final_message"]["content"], "42")
        self.assertEqual(result["task"]["budget"]["calls"], 3)
        self.assertEqual(len(self.calls), 4)
        self.assertNotIn("hello", self.calls[1]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
