"""Minimal MCP stdio server used only by Sumika protocol smoke tests."""

from __future__ import annotations

import json
import sys
from typing import Any


_MAX_MESSAGE_BYTES = 1024 * 1024
_TOOL_NAME = "echo"


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _error(request_id, -32600, "Invalid Request") if request_id is not None else None
    if request_id is None:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        protocol_version = params.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            protocol_version = "2025-06-18"
        return _response(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sumika-mcp-smoke", "version": "1.0.0"},
            },
        )
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(
            request_id,
            {
                "tools": [
                    {
                        "name": _TOOL_NAME,
                        "description": "Return a deterministic Sumika MCP smoke marker.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string", "maxLength": 256}},
                            "required": ["text"],
                            "additionalProperties": False,
                        },
                    }
                ]
            },
        )
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        text = arguments.get("text")
        if params.get("name") != _TOOL_NAME or not isinstance(text, str) or len(text) > 256:
            return _error(request_id, -32602, "Invalid echo arguments")
        marker = f"SUMIKA_MCP_ECHO:{text}"
        return _response(
            request_id,
            {
                "content": [{"type": "text", "text": marker}],
                "structuredContent": {"marker": marker},
                "isError": False,
            },
        )
    return _error(request_id, -32601, "Method not found")


def main() -> int:
    for raw_line in sys.stdin.buffer:
        if len(raw_line) > _MAX_MESSAGE_BYTES:
            continue
        try:
            message = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(message, dict):
            continue
        response = _handle(message)
        if response is None:
            continue
        payload = json.dumps(response, ensure_ascii=True, separators=(",", ":"))
        sys.stdout.write(payload + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
