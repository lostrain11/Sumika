import io
import json
import unittest
from unittest.mock import patch

from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.providers.openai_compatible import OpenAICompatibleProvider


class Response(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


class MoarkProviderTests(unittest.TestCase):
    def stream(self, fragments, model="Qwen3-8B", base="https://api.moark.com/v1", echo="Qwen/Qwen3-8B"):
        frames = [{"model": echo, "choices": [{"delta": {"content": fragment}}]} for fragment in fragments]
        frames.append({"model": echo, "choices": [{"delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 4, "completion_tokens": 30}})
        body = "".join("data:" + json.dumps(frame) + "\n\n" for frame in frames) + "data:[DONE]\n\n"
        provider = OpenAICompatibleProvider(base, model)
        with patch.object(provider, "_open", return_value=Response(body.encode())):
            text = "".join(provider.stream(ChatRequest("test", [Message("user", "extract")], max_tokens=64)))
        return provider, text

    def test_split_reasoning_removed_but_usage_retained(self):
        provider, text = self.stream([" ", "<th", "ink>", "hidden reasoning", "</th", "ink>", '{"answer":42}'])
        self.assertEqual(text, '{"answer":42}')
        self.assertEqual(provider.last_usage["output_tokens"], 30)
        self.assertFalse(provider.last_response_model_mismatch)

    def test_literal_tags_inside_answer_are_preserved(self):
        text = '{"example":"<think>literal</think>"}'
        self.assertEqual(self.stream([text])[1], text)

    def test_no_reasoning_and_other_endpoints_are_preserved(self):
        self.assertEqual(self.stream(['{"value":', '42}'])[1], '{"value":42}')
        text = "<think>literal</think>answer"
        self.assertEqual(self.stream([text], base="https://proxy.example/v1")[1], text)

    def test_unclosed_reasoning_is_rejected(self):
        for pieces in (["<th"], ["<think>"], ["<think>missing end"]):
            with self.assertRaises(ValueError):
                self.stream(pieces)


if __name__ == "__main__":
    unittest.main()
