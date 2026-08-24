"""Small WebSocket server-side helpers for the local event channel.

The core only needs text frames and a handshake for the browser event stream;
commands remain ordinary HTTP JSON-RPC requests.
"""

from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler


def accept_websocket(handler: BaseHTTPRequestHandler) -> None:
    key = handler.headers.get("Sec-WebSocket-Key")
    if not key:
        raise ValueError("Sec-WebSocket-Key is required")
    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    handler.send_response(101, "Switching Protocols")
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()


def encode_text_frame(value: str) -> bytes:
    payload = value.encode("utf-8")
    length = len(payload)
    if length < 126:
        return bytes([0x81, length]) + payload
    if length < 65536:
        return bytes([0x81, 126]) + length.to_bytes(2, "big") + payload
    return bytes([0x81, 127]) + length.to_bytes(8, "big") + payload
