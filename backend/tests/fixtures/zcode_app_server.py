"""Deterministic JSON-RPC line server for the ZCode adapter contract tests."""

from __future__ import annotations

import json
import sys
from itertools import count


sessions: dict[str, dict[str, str]] = {}
session_counter = count(1)
turn_counter = count(1)


def send(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def response(request_id, result=None, error=None) -> None:
    value = {"jsonrpc": "2.0", "id": request_id}
    value["error" if error is not None else "result"] = error if error is not None else result
    send(value)


for raw_line in sys.stdin:
    try:
        request = json.loads(raw_line)
    except json.JSONDecodeError:
        continue
    if not isinstance(request, dict):
        continue
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if method == "initialize":
        response(
            request_id,
            {
                "protocolVersion": "1",
                "capabilities": ["models", "plan", "readonly", "interactions", "mcp"],
            },
        )
    elif method == "initialized":
        continue
    elif method in {"health", "status", "host/describe"}:
        response(request_id, {"state": "ready", "version": "fixture"})
    elif method in {"session/create", "thread/start", "session.create"}:
        session_id = f"z-session-{next(session_counter)}"
        sessions[session_id] = {"id": session_id, "title": str(params.get("title") or "Fixture session"), "state": "idle"}
        response(request_id, {"sessionId": session_id, "title": sessions[session_id]["title"], "state": "idle"})
    elif method in {"session/list", "thread/list", "session.list"}:
        response(request_id, {"sessions": list(sessions.values())})
    elif method in {"session/snapshot", "thread/read", "session/read", "session.snapshot", "session/history"}:
        session_id = str(params.get("sessionId") or "")
        response(request_id, {"sessionId": session_id, "items": []})
    elif method in {"turn/start", "session/prompt", "turn/create", "session.prompt"}:
        session_id = str(params.get("sessionId") or "")
        turn_id = f"z-turn-{next(turn_counter)}"
        send({"jsonrpc": "2.0", "method": "turn/started", "params": {"sessionId": session_id, "turnId": turn_id, "status": "running"}})
        response(request_id, {"accepted": True, "sessionId": session_id, "turnId": turn_id})
        send({"jsonrpc": "2.0", "method": "turn/completed", "params": {"sessionId": session_id, "turnId": turn_id, "status": "completed"}})
    elif method in {"turn/interrupt", "session/cancel", "turn/cancel", "session.cancel"}:
        response(request_id, {"accepted": True})
    elif method in {"model/list", "session/models", "session.models"}:
        response(request_id, {"groups": [{"id": "fixture", "name": "Fixture", "models": [{"id": "qwen3:4b", "name": "Qwen3 4B"}]}]})
    elif method in {"mcp/list", "mcp/listServers", "mcp.list"}:
        response(request_id, {"servers": [{"id": "fixture-mcp", "name": "Fixture MCP", "status": "ready", "tools": [{"name": "fixture.echo"}]}]})
    elif method == "capabilities":
        response(request_id, {"capabilities": ["models", "mcp", "plan"]})
    elif method == "trigger/approval":
        send({"jsonrpc": "2.0", "id": "approval-1", "method": "approval/requested", "params": {"sessionId": str(params.get("sessionId") or ""), "status": "pending", "reason": "fixture"}})
        response(request_id, {"accepted": True})
    else:
        response(request_id, error={"code": -32601, "message": "method not found"})
