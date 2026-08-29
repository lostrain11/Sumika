import json
import unittest
import urllib.request

from backend.tests.fixtures.openai_compatible import OpenAICompatibleStub


class OpenAICompatibleStubTests(unittest.TestCase):
    def test_lists_one_real_protocol_model_and_serves_streaming_completion(self):
        with OpenAICompatibleStub(response_text="stub answer") as stub:
            with urllib.request.urlopen(f"{stub.base_url}/models", timeout=2) as response:
                models = json.loads(response.read().decode("utf-8"))
            request = urllib.request.Request(
                f"{stub.base_url}/chat/completions",
                data=json.dumps(
                    {
                        "model": stub.model,
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": True,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer test-only"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                stream = response.read().decode("utf-8")

        self.assertEqual(models["data"][0]["id"], "sumika-dsh-smoke")
        frames = [
            json.loads(line.removeprefix("data: "))
            for line in stream.splitlines()
            if line.startswith("data: {")
        ]
        content = "".join(
            frame["choices"][0]["delta"].get("content", "")
            for frame in frames
            if frame.get("choices")
        )
        self.assertEqual(content, "stub answer")
        self.assertIn("data: [DONE]", stream)
        self.assertEqual(len(stub.requests), 1)
        self.assertTrue(stub.requests[0]["authorization_present"])
        self.assertEqual(stub.requests[0]["payload"]["model"], stub.model)

    def test_streams_scripted_tool_call_then_waits_for_its_result(self):
        script = [{"name": "read", "arguments": {"file_path": "README.md", "limit": 2}}]
        with OpenAICompatibleStub(response_text="finished", scripted_tool_calls=script) as stub:
            first = self._stream_request(
                stub,
                messages=[{"role": "user", "content": "read the file"}],
                tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}],
            )
            tool_frame = next(
                frame
                for frame in first
                if frame.get("choices") and frame["choices"][0]["delta"].get("tool_calls")
            )
            tool_call = tool_frame["choices"][0]["delta"]["tool_calls"][0]
            self.assertEqual(tool_call["function"]["name"], "read")
            self.assertEqual(json.loads(tool_call["function"]["arguments"]), script[0]["arguments"])
            self.assertEqual(first[-1]["choices"][0]["finish_reason"], "tool_calls")

            second = self._stream_request(
                stub,
                messages=[
                    {"role": "user", "content": "read the file"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_call["id"],
                                "type": "function",
                                "function": tool_call["function"],
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": tool_call["id"], "content": "README"},
                ],
                tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}],
            )

        content = "".join(frame["choices"][0]["delta"].get("content", "") for frame in second)
        self.assertEqual(content, "finished")
        self.assertEqual(stub.completed_tool_calls, ["read"])

    def test_nested_subagent_request_does_not_replay_parent_tool_call(self):
        script = [{"name": "subagent", "arguments": {"description": "child", "prompt": "reply"}}]
        with OpenAICompatibleStub(response_text="finished", scripted_tool_calls=script) as stub:
            first = self._stream_request(
                stub,
                messages=[{"role": "user", "content": "delegate"}],
                tools=[{"type": "function", "function": {"name": "subagent", "parameters": {"type": "object"}}}],
            )
            tool_call = next(
                frame["choices"][0]["delta"]["tool_calls"][0]
                for frame in first
                if frame.get("choices") and frame["choices"][0]["delta"].get("tool_calls")
            )
            child = self._stream_request(
                stub,
                messages=[{"role": "user", "content": "reply"}],
                tools=[{"type": "function", "function": {"name": "subagent", "parameters": {"type": "object"}}}],
            )
            child_text = "".join(frame["choices"][0]["delta"].get("content", "") for frame in child)
            parent = self._stream_request(
                stub,
                messages=[
                    {"role": "user", "content": "delegate"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": tool_call["id"], "type": "function", "function": tool_call["function"]}],
                    },
                    {"role": "tool", "tool_call_id": tool_call["id"], "content": "child complete"},
                ],
                tools=[{"type": "function", "function": {"name": "subagent", "parameters": {"type": "object"}}}],
            )
            parent_text = "".join(frame["choices"][0]["delta"].get("content", "") for frame in parent)

        self.assertEqual(child_text, "finished")
        self.assertEqual(parent_text, "finished")
        self.assertEqual(stub.completed_tool_calls, ["subagent"])

    @staticmethod
    def _stream_request(stub, *, messages, tools):
        request = urllib.request.Request(
            f"{stub.base_url}/chat/completions",
            data=json.dumps(
                {"model": stub.model, "messages": messages, "tools": tools, "stream": True}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer test-only"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            stream = response.read().decode("utf-8")
        return [
            json.loads(line.removeprefix("data: "))
            for line in stream.splitlines()
            if line.startswith("data: {")
        ]


if __name__ == "__main__":
    unittest.main()
