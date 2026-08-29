"""Small OpenAI-compatible HTTP server for protocol integration tests only."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class OpenAICompatibleStub:
    """Serve one deterministic model without entering the production catalog."""

    def __init__(
        self,
        *,
        model: str = "sumika-dsh-smoke",
        response_text: str = "SUMIKA_DSH_SMOKE_OK",
        scripted_tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.model = model
        self.response_text = response_text
        self.scripted_tool_calls = [dict(item) for item in scripted_tool_calls or []]
        self.requests: list[dict[str, Any]] = []
        self.completed_tool_calls: list[str] = []
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._script_index = 0
        self._pending_tool_call: dict[str, Any] | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("OpenAI-compatible stub is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> "OpenAICompatibleStub":
        if self._server is not None:
            return self
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                if self.path.rstrip("/") == "/v1/models":
                    self._json(
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": owner.model,
                                    "object": "model",
                                    "created": 0,
                                    "owned_by": "sumika-tests",
                                }
                            ],
                        }
                    )
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if length < 0 or length > 4 * 1024 * 1024:
                    self.send_error(413)
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.send_error(400)
                    return
                if not isinstance(payload, dict):
                    self.send_error(400)
                    return
                with owner._lock:
                    owner.requests.append(
                        {
                            "path": self.path,
                            "payload": payload,
                            "authorization_present": bool(self.headers.get("Authorization")),
                        }
                    )
                    completion = owner._next_completion(payload)
                if payload.get("stream"):
                    self._stream_completion(completion)
                else:
                    self._json(owner._non_stream_response(completion))

            def _stream_completion(self, completion: dict[str, Any]) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                if completion["kind"] == "tool":
                    chunks = [
                        {"role": "assistant", "content": ""},
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": completion["id"],
                                    "type": "function",
                                    "function": {
                                        "name": completion["name"],
                                        "arguments": json.dumps(
                                            completion["arguments"], ensure_ascii=False, separators=(",", ":")
                                        ),
                                    },
                                }
                            ]
                        },
                    ]
                    finish_reason = "tool_calls"
                else:
                    response_text = str(completion["text"])
                    split = len(response_text) // 2
                    chunks = [
                        {"role": "assistant", "content": ""},
                        {"content": response_text[:split]},
                        {"content": response_text[split:]},
                    ]
                    finish_reason = "stop"
                for delta in chunks:
                    self._sse(
                        {
                            "id": "chatcmpl-sumika-stub",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": owner.model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                    )
                self._sse(
                    {
                        "id": "chatcmpl-sumika-stub",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": owner.model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
                    }
                )
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True

            def _sse(self, value: dict[str, Any]) -> None:
                data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()

            def _json(self, value: dict[str, Any]) -> None:
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
                self.close_connection = True

            def log_message(self, format: str, *args: Any) -> None:
                del format, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="sumika-openai-stub", daemon=True)
        self._thread.start()
        return self

    def _next_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        tools = payload.get("tools")
        if not self.scripted_tool_calls or not isinstance(tools, list) or not tools:
            return {"kind": "text", "text": self.response_text}

        pending = self._pending_tool_call
        if pending is not None and _has_tool_result(payload.get("messages"), str(pending["id"])):
            self.completed_tool_calls.append(str(pending["name"]))
            self._script_index += 1
            pending = None
            self._pending_tool_call = None

        # A foreground DSH subagent makes a nested model request before the
        # parent receives the matching tool result.  The deterministic fixture
        # has one global script, so let that child finish with plain text
        # instead of replaying the parent's still-pending tool call into the
        # child (which would recurse until DSH's depth guard fires).
        if (
            pending is not None
            and str(pending.get("name") or "") == "subagent"
            and not _has_assistant_tool_call(payload.get("messages"), str(pending["id"]))
        ):
            return {"kind": "text", "text": self.response_text}

        if pending is None and self._script_index < len(self.scripted_tool_calls):
            source = self.scripted_tool_calls[self._script_index]
            name = str(source.get("name") or "").strip()
            arguments = source.get("arguments")
            if not name or not isinstance(arguments, dict):
                raise ValueError("scripted tool calls require a name and object arguments")
            pending = {
                "kind": "tool",
                "id": f"call-sumika-{self._script_index + 1}",
                "name": name,
                "arguments": dict(arguments),
            }
            self._pending_tool_call = pending

        return dict(pending) if pending is not None else {"kind": "text", "text": self.response_text}

    def _non_stream_response(self, completion: dict[str, Any]) -> dict[str, Any]:
        if completion["kind"] == "tool":
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": completion["id"],
                        "type": "function",
                        "function": {
                            "name": completion["name"],
                            "arguments": json.dumps(
                                completion["arguments"], ensure_ascii=False, separators=(",", ":")
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": completion["text"]}
            finish_reason = "stop"
        return {
            "id": "chatcmpl-sumika-stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        }

    def close(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)

    def __enter__(self) -> "OpenAICompatibleStub":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.close()


def _has_tool_result(messages: Any, call_id: str) -> bool:
    if not isinstance(messages, list):
        return False
    return any(
        isinstance(message, dict)
        and message.get("role") == "tool"
        and str(message.get("tool_call_id") or "") == call_id
        for message in messages
    )


def _has_assistant_tool_call(messages: Any, call_id: str) -> bool:
    """Return whether a conversation contains the scripted call itself."""

    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        if any(isinstance(call, dict) and str(call.get("id") or "") == call_id for call in calls):
            return True
    return False


__all__ = ["OpenAICompatibleStub"]
