import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.providers import CommandProvider, OpenAICompatibleProvider, ProviderRegistry
from sumika_core.providers.openai_compatible import _ThinkFilter
from fixtures.providers import FakeProvider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.request = ChatRequest("s1", [Message("user", "hello")])

    def test_openai_provider_does_not_inherit_legacy_environment_key(self):
        with patch.dict(os.environ, {"SUMIKA_OPENAI_API_KEY": "legacy-secret"}):
            provider = OpenAICompatibleProvider("http://127.0.0.1:19090/v1", "test-model")
        self.assertIsNone(provider.api_key)
        self.assertNotIn("Authorization", provider._request_headers(accept="application/json"))

    def test_fake_provider_streams_deterministically(self):
        provider = FakeProvider("one two")
        self.assertEqual("".join(provider.stream(self.request)), "one two")

    def test_registry_lists_and_routes(self):
        registry = ProviderRegistry()
        registry.register(FakeProvider("ok"))
        self.assertEqual(registry.list()[0].id, "fake")
        self.assertEqual("".join(registry.stream("fake", self.request)), "ok")

    def test_external_jsonl_provider(self):
        code = (
            "import json,sys; "
            "request=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'type':'token','text':request['messages'][-1]['content']}),flush=True); "
            "print(json.dumps({'type':'done'}),flush=True)"
        )
        provider = CommandProvider(sys.executable, ["-c", code])
        self.assertEqual("".join(provider.stream(self.request)), "hello")

    def test_openai_compatible_sse_provider(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n')
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_address[1]}", "test-model")
            self.assertEqual("".join(provider.stream(self.request)), "ok")
            self.assertEqual(received["body"]["messages"], [{"role": "user", "content": "hello"}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_openai_compatible_json_provider(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"json-ok"}}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(f"http://127.0.0.1:{server.server_address[1]}", "test-model")
            self.assertEqual("".join(provider.stream(self.request)), "json-ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_think_filter_handles_split_reasoning_tags(self):
        filter_ = _ThinkFilter()
        output = []
        for chunk in ("prefix <thi", "nk>hidden", " reasoning</thi", "nk>visible"):
            output.extend(filter_.feed(chunk))
        output.extend(filter_.finish())
        self.assertEqual("".join(output), "prefix visible")

    def test_ollama_hint_supports_non_default_local_port(self):
        provider = OpenAICompatibleProvider(
            "http://127.0.0.1:11435/v1",
            "qwen3:4b",
            ollama=True,
        )
        self.assertTrue(provider._is_ollama())

    def test_openai_compatible_health_check_requires_configured_model(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                received["authorization"] = self.headers.get("Authorization")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"available-model"}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(
                f"http://127.0.0.1:{server.server_address[1]}", "missing-model", api_key="health-secret"
            )
            result = provider.health_check()
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "unconfigured")
            self.assertEqual(result["available_models"], ["available-model"])
            self.assertEqual(received["authorization"], "Bearer health-secret")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_health_check_does_not_spend_a_chat_request_without_explicit_probe(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                calls.append("GET")
                self.send_response(404)
                self.end_headers()

            def do_POST(self):  # noqa: N802
                calls.append("POST")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(
                f"http://127.0.0.1:{server.server_address[1]}/v1", "test-model"
            )
            passive = provider.health_check()
            self.assertFalse(passive["ok"])
            self.assertEqual(calls, ["GET"])
            active = provider.health_check(allow_chat_probe=True)
            self.assertTrue(active["ok"])
            self.assertEqual(calls, ["GET", "GET", "POST"])
            self.assertEqual(active["health_probe"], "chat-completions")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
