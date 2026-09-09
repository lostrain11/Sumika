import io
import json
import unittest
from unittest.mock import patch

from sumika_core.providers.openai_compatible import OpenAICompatibleProvider
from sumika_core.protocol.models import ChatRequest, Message


class Response(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


class SparkLiteTests(unittest.TestCase):
    def run_stream(self, *, code=0, done=True, echo=None):
        payload = {"code": code, "choices": [{"delta": {"content": "42"}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        if echo is not None:
            payload["model"] = echo
        body = ("data:" + json.dumps(payload) + "\n\n" + ("data:[DONE]\n\n" if done else "")).encode()
        provider = OpenAICompatibleProvider("https://spark-api-open.xf-yun.com/v1", "lite")
        with patch.object(provider, "_open", return_value=Response(body)):
            result = "".join(provider.stream(ChatRequest("test", [Message("user", "6*7")], max_tokens=128)))
        return provider, result

    def test_official_stream_without_echo_or_finish_reason(self):
        provider, result = self.run_stream()
        self.assertEqual(result, "42")
        self.assertEqual(provider.last_finish_reason, "stop")
        self.assertEqual(provider.last_model_identity_basis, "spark-lite-request-and-completion")
        self.assertIsNone(provider.last_response_model)

    def test_eof_is_not_completion(self):
        provider, result = self.run_stream(done=False)
        self.assertIsNone(provider.last_finish_reason)
        self.assertIsNone(provider.last_model_identity_basis)

    def test_nonzero_business_error_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "business response"):
            self.run_stream(code=10013)

    def test_boolean_success_code_rejected(self):
        with self.assertRaises(RuntimeError):
            self.run_stream(code=False)

    def test_wrong_echo_keeps_mismatch(self):
        provider, result = self.run_stream(echo="general")
        self.assertTrue(provider.last_response_model_mismatch)


if __name__ == "__main__":
    unittest.main()
