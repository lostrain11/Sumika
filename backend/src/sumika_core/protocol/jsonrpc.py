"""Minimal JSON-RPC 2.0 helpers used by the local HTTP endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass(slots=True)
class JsonRpcRequest:
    request_id: str | int | None
    method: str
    params: dict[str, Any]


def parse_request(payload: dict[str, Any]) -> JsonRpcRequest:
    if payload.get("jsonrpc") != "2.0":
        raise JsonRpcError(-32600, "Invalid Request: jsonrpc must be 2.0")
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcError(-32600, "Invalid Request: method is required")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise JsonRpcError(-32602, "Invalid params: expected an object")
    return JsonRpcRequest(payload.get("id"), method, params)


def success(request_id: str | int | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def failure(request_id: str | int | None, error: JsonRpcError) -> dict[str, Any]:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message},
    }
    if error.data is not None:
        response["error"]["data"] = error.data
    return response
