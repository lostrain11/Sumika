import io
import json
import unittest

from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.providers.openai_compatible import OpenAICompatibleProvider
from sumika_core.quality.service import QualityRoutingService
from quality_routing import RoutingError


class Response(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


class QualityProviderTests(unittest.TestCase):
    def test_zhipu_off_uses_thinking_switch_and_captures_truncation(self):
        provider = OpenAICompatibleProvider(base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4.5-flash")
        requests = []

        def open_request(request):
            requests.append(json.loads(request.data))
            return Response(b'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"length"}],"usage":{"prompt_tokens":20,"completion_tokens":300}}\n\ndata: [DONE]\n\n')

        provider._open = open_request
        request = ChatRequest("chat", [Message("user", "Introduce answer")], reasoning_effort="off", max_tokens=300)
        self.assertEqual(list(provider.stream(request)), [])
        self.assertEqual(requests[0]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", requests[0])
        self.assertEqual(provider.last_finish_reason, "length")
        self.assertTrue(provider.last_reasoning_content_seen)
        self.assertIsNone(provider.last_applied_reasoning_effort)
        with self.assertRaises(ValueError):
            list(provider.stream(ChatRequest("chat", [Message("user", "test")], reasoning_effort="high")))
        self.assertEqual(len(requests), 1)

    def test_glm_switch_is_not_sent_to_unrelated_relay(self):
        provider = OpenAICompatibleProvider(base_url="https://relay.invalid/v1", model="glm-4.5-flash")
        requests = []
        provider._open = lambda request: (requests.append(json.loads(request.data)) or Response(b'data: [DONE]\n\n'))
        list(provider.stream(ChatRequest("chat", [Message("user", "test")], reasoning_effort="off")))
        self.assertNotIn("thinking", requests[0])
        self.assertEqual(requests[0]["reasoning_effort"], "off")

    def test_glm53_default_does_not_disable_required_thinking(self):
        provider = OpenAICompatibleProvider(base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-5.3-flash")
        requests = []
        provider._open = lambda request: (requests.append(json.loads(request.data)) or Response(b'data: [DONE]\n\n'))
        list(provider.stream(ChatRequest("chat", [Message("user", "test")])) )
        self.assertNotIn("thinking", requests[0])
        self.assertNotIn("reasoning_effort", requests[0])

    def test_zhipu_health_probe_disables_only_supported_thinking(self):
        for model in ("glm-4.5-flash", "glm-5.3-flash"):
            with self.subTest(model=model):
                provider = OpenAICompatibleProvider(base_url="https://open.bigmodel.cn/api/paas/v4", model=model)
                requests = []

                def open_request(request, **kwargs):
                    requests.append(json.loads(request.data))
                    response = io.BytesIO(b'{"choices":[{"message":{"content":"ok"}}]}')
                    response.status = 200
                    response.headers = {"Content-Type": "application/json"}
                    self.assertEqual(kwargs["timeout"], 8.0)
                    return response

                provider._open = open_request
                self.assertTrue(provider._health_chat_probe({})["ok"])
                self.assertEqual(requests[0].get("thinking"), {"type": "disabled"} if model == "glm-4.5-flash" else None)

    def test_planner_json_accepts_only_a_complete_json_document(self):
        for source in ('{"nodes":[]}', '```json\n{"nodes":[]}\n```', '```\r\n{"nodes":[]}\r\n```'):
            self.assertEqual(QualityRoutingService._json(source), {"nodes": []})
        for source in ('Here is a plan:\n```json\n{"nodes":[]}\n```', '```json\n{"nodes":[]}\n```\nexecute now',
                       '```json\n[]\n```', '```json\n{"nodes":[]}\n```\n```json\n{}\n```'):
            with self.assertRaises(RoutingError):
                QualityRoutingService._json(source)

    def test_incomplete_catalog_requires_explicit_probe(self):
        provider = OpenAICompatibleProvider(base_url="https://example.invalid/v1", model="omitted-model")
        calls = []

        def open_request(request, **kwargs):
            calls.append(request)
            body = b'{"data":[{"id":"other-model"}]}' if request.method == "GET" else b'{"choices":[{"message":{"content":"ok"}}]}'
            response = io.BytesIO(body)
            response.status = 200
            response.headers = {"Content-Type": "application/json"}
            return response

        provider._open = open_request
        self.assertFalse(provider.health_check()["ok"])
        self.assertEqual([request.method for request in calls], ["GET"])
        result = provider.health_check(allow_chat_probe=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_catalog"], "incomplete")
        self.assertIn("omitted-model", result["available_models"])
        self.assertEqual(json.loads(calls[-1].data)["max_tokens"], 1)

    def test_tool_fragments_are_collected_without_extra_model_call(self):
        payloads = [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "sumika_plan_task", "arguments": '{"goal":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"Compute"}'}}]}}]},
            {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10, "completion_tokens_details": {"reasoning_tokens": 7}}},
        ]
        body = "".join("data: " + json.dumps(item) + "\n\n" for item in payloads) + "data: [DONE]\n\n"
        provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:1/v1", model="fixture")
        requests = []
        def open_request(request):
            requests.append(json.loads(request.data))
            return Response(body.encode())
        provider._open = open_request
        request = ChatRequest("chat", [Message("user", "Compute")], reasoning_effort="high", tools=[{"type": "function"}])
        self.assertEqual(list(provider.stream(request)), [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["reasoning_effort"], "high")
        self.assertEqual(provider.last_tool_calls, [{"name": "sumika_plan_task", "arguments": '{"goal":"Compute"}'}])
        self.assertEqual(provider.last_usage["total_tokens"], 30)
        self.assertIsNone(provider.last_applied_reasoning_effort)

    def test_ordinary_chat_does_not_add_tools_or_effort(self):
        provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:1/v1", model="fixture")
        requests = []
        def open_request(request):
            requests.append(json.loads(request.data))
            return Response(b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n')
        provider._open = open_request
        self.assertEqual(list(provider.stream(ChatRequest("chat", [Message("user", "Hi")]))), ["Hello"])
        self.assertNotIn("tools", requests[0])
        self.assertNotIn("reasoning_effort", requests[0])


if __name__ == "__main__":
    unittest.main()
