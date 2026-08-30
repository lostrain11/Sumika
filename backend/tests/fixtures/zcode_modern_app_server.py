"""Deterministic current-ZCode wire fixture for adapter tests.

The real app-server uses line-delimited objects shaped like JSON-RPC, but it
omits the ``jsonrpc`` member and exposes workspace-scoped methods.
"""

from __future__ import annotations

import json
import sys
from itertools import count


sessions: dict[str, dict[str, object]] = {}
session_counter = count(1)
turn_counter = count(1)


def send(value: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def response(request_id: object, result: object = None, error: dict[str, object] | None = None) -> None:
    value: dict[str, object] = {"id": request_id}
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
    if "jsonrpc" in request:
        response(request_id, error={"code": -32600, "message": "Invalid ZCode Protocol message"})
    elif method == "session/list":
        response(request_id, {"sessions": list(sessions.values())})
    elif method == "workspace/readState":
        response(
            request_id,
            {
                "modelCatalog": {
                    "revision": 1,
                    "providers": [
                        {"id": "fixture-provider", "name": "Fixture", "models": [{"id": "fixture-model", "name": "Fixture Model"}]}
                    ],
                },
                "settings": {"mode": {"current": "build"}},
                "slashCommands": [{"name": "plan", "description": "Plan"}],
                "workspace": params.get("workspace"),
            },
        )
    elif method == "mcp/list":
        response(request_id, {"statuses": {"fixture-mcp": {"status": "connected", "transport": "stdio", "toolCount": 2}}})
    elif method == "session/requestRuntimePreferences":
        response(request_id, {"nativeSearchEnhancementsEnabled": True, "memoryEnabled": False, "askUserQuestionAutoResolutionEnabled": True, "modelContextBudgetStrategy": "preflight-v1"})
    elif method == "session/create":
        session_id = f"modern-session-{next(session_counter)}"
        session = {
            "sessionId": session_id,
            "workspace": params.get("workspace"),
            "status": "idle",
            "mode": params.get("mode", "build"),
            "createdAt": 1,
            "updatedAt": 1,
        }
        if params.get("mode") != "edit":
            session["title"] = "Modern fixture"
        sessions[session_id] = session
        # The real server asks this while creating the session.  Use a
        # server request to ensure the adapter's automatic response path is
        # exercised without introducing any credential or user data.
        # The adapter responds asynchronously; acknowledge the create after
        # emitting the request, matching the ordering of the real server.
        send({"id": "runtime-preferences-1", "method": "session/requestRuntimePreferences", "params": {"sessionId": session_id, "scope": "runtime-materialization"}})
        response(request_id, session)
        send({"method": "session/event", "params": {"type": "session.created", "sessionId": session_id, "status": "idle"}})
    elif method == "session/setMode":
        response(request_id, {})
    elif method == "session/send":
        session_id = str(params.get("sessionId") or "")
        turn_id = f"modern-turn-{next(turn_counter)}"
        send({"method": "session/event", "params": {"type": "turn.started", "sessionId": session_id, "turnId": turn_id, "status": "running"}})
        response(request_id, {"accepted": True, "sessionId": session_id, "stateRevision": 2})
        send({"method": "session/event", "params": {"type": "part.delta", "sessionId": session_id, "turnId": turn_id, "delta": "ok"}})
        send({"method": "session/event", "params": {"type": "turn.completed", "sessionId": session_id, "turnId": turn_id, "status": "completed"}})
    elif method == "session/stop":
        response(request_id, {})
    elif method == "session/read":
        response(request_id, {"sessionId": params.get("sessionId"), "messages": [], "status": "idle"})
    elif method == "session/messages":
        response(request_id, {"messages": []})
    elif method == "session/setModel":
        response(request_id, {"changed": True})
    elif method == "session/fork":
        child = f"modern-session-{next(session_counter)}"
        response(request_id, {"forkedSessionId": child, "parentSessionId": params.get("sessionId"), "target": params.get("target")})
    elif method == "session/subagents":
        response(request_id, {"revision": 1, "childSessionIds": [], "running": [], "ended": {"total": 0, "items": []}})
    elif method == "trigger/permission":
        send({"id": "permission-1", "method": "interaction/requestPermission", "params": {"sessionId": str(params.get("sessionId") or ""), "toolName": "fixture", "reason": "fixture", "riskLevel": "low", "options": [{"optionId": "allow", "kind": "allow", "name": "Allow", "response": {"decision": "allow"}}]}})
        response(request_id, {"accepted": True})
    else:
        response(request_id, error={"code": -32601, "message": "Method not found"})
