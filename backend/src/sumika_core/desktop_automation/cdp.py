"""Small, dependency-free Electron CDP transport.

The transport is deliberately limited to an explicitly configured loopback
debug endpoint.  It discovers an existing page target, evaluates a fixed
observation script, and maps a small set of DOM actions.  It never launches a
process, enables remote debugging, or sends arbitrary JavaScript.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import threading
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, ProxyHandler, build_opener

from .contracts import DesktopActionRequest, DesktopAutomationError, safe_text


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_MAX_HTTP_BYTES = 256 * 1024
_MAX_FRAME_BYTES = 2 * 1024 * 1024
_MAX_OBSERVATION_TEXT = 16_000
_MAX_SELECTOR = 600


def _endpoint_parts(endpoint: str) -> tuple[Any, str]:
    try:
        parsed = urlparse(str(endpoint or "").strip())
    except ValueError as error:
        raise DesktopAutomationError("CDP endpoint is invalid", code="cdp-endpoint-invalid") from error
    try:
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as error:
        raise DesktopAutomationError("CDP endpoint port or host is invalid", code="cdp-endpoint-invalid") from error
    if scheme not in {"http", "https"} or hostname not in _LOOPBACK_HOSTS:
        raise DesktopAutomationError("CDP endpoint must be loopback-only", code="cdp-endpoint-invalid")
    if port is not None and not 1 <= port <= 65_535:
        raise DesktopAutomationError("CDP endpoint port is invalid", code="cdp-endpoint-invalid")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise DesktopAutomationError("CDP endpoint must not contain credentials or query data", code="cdp-endpoint-invalid")
    prefix = parsed.path.rstrip("/")
    return parsed, prefix


def _authority(host: str, port: int | None) -> str:
    rendered = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{rendered}:{port}" if port else rendered


class _CdpSocket:
    """Minimal RFC 6455 client for one CDP target."""

    def __init__(self, websocket_url: str, *, timeout: float) -> None:
        parsed = urlparse(websocket_url)
        try:
            scheme = parsed.scheme.lower()
            hostname = (parsed.hostname or "").lower()
            port = parsed.port or (443 if scheme == "wss" else 80)
        except ValueError as error:
            raise DesktopAutomationError("CDP websocket host or port is invalid", code="cdp-endpoint-invalid") from error
        if scheme not in {"ws", "wss"} or hostname not in _LOOPBACK_HOSTS:
            raise DesktopAutomationError("CDP target websocket must be loopback-only", code="cdp-endpoint-invalid")
        if not 1 <= port <= 65_535:
            raise DesktopAutomationError("CDP websocket port is invalid", code="cdp-endpoint-invalid")
        if parsed.username is not None or parsed.password is not None:
            raise DesktopAutomationError("CDP websocket must not contain credentials", code="cdp-endpoint-invalid")
        self._timeout = max(0.2, min(float(timeout), 30.0))
        connection = None
        try:
            connection = socket.create_connection((hostname, port), timeout=self._timeout)
            if scheme == "wss":
                context = ssl.create_default_context()
                connection = context.wrap_socket(connection, server_hostname=hostname)
            connection.settimeout(self._timeout)
            self._socket = connection
            self._lock = threading.RLock()
            self._next_id = 0
            self._closed = False
            self._read_buffer = bytearray()
            self._handshake(parsed)
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            raise

    def _handshake(self, parsed: Any) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host = _authority(parsed.hostname, parsed.port)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._socket.sendall(request)
        response = self._read_until(b"\r\n\r\n", 64 * 1024)
        head = response.decode("iso-8859-1", "replace").split("\r\n")
        if not head or " 101 " not in f" {head[0]} ":
            raise DesktopAutomationError("CDP websocket handshake failed", code="cdp-connect-failed")
        headers: dict[str, str] = {}
        for line in head[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise DesktopAutomationError("CDP websocket handshake was rejected", code="cdp-connect-failed")

    def _read_until(self, marker: bytes, limit: int) -> bytes:
        data = bytearray()
        while marker not in data:
            if len(data) >= limit:
                raise DesktopAutomationError("CDP websocket header is too large", code="cdp-connect-failed")
            try:
                chunk = self._socket.recv(min(4096, limit - len(data)))
            except OSError as error:
                raise DesktopAutomationError("CDP websocket connection failed", code="cdp-connect-failed", retryable=True) from error
            if not chunk:
                raise DesktopAutomationError("CDP websocket closed during handshake", code="cdp-connect-failed")
            data.extend(chunk)
        before, after = bytes(data).split(marker, 1)
        self._read_buffer.extend(after)
        return before

    def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        if self._read_buffer:
            take = min(size, len(self._read_buffer))
            data.extend(self._read_buffer[:take])
            del self._read_buffer[:take]
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise DesktopAutomationError("CDP websocket closed", code="cdp-connection-closed", retryable=True)
            data.extend(chunk)
        return bytes(data)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if len(payload) > _MAX_FRAME_BYTES:
            raise DesktopAutomationError("CDP payload is too large", code="cdp-payload-too-large")
        first = 0x80 | (opcode & 0x0F)
        size = len(payload)
        if size < 126:
            header = bytes((first, 0x80 | size))
        elif size <= 0xFFFF:
            header = bytes((first, 0x80 | 126)) + size.to_bytes(2, "big")
        else:
            header = bytes((first, 0x80 | 127)) + size.to_bytes(8, "big")
        mask = os.urandom(4)
        masked = bytes(item ^ mask[index % 4] for index, item in enumerate(payload))
        self._socket.sendall(header + mask + masked)

    def _receive_message(self, deadline: float) -> str:
        fragments: list[bytes] = []
        text_message = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DesktopAutomationError("CDP command timed out", code="cdp-timeout", retryable=True)
            self._socket.settimeout(remaining)
            header = self._read_exact(2)
            first, second = header
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            size = second & 0x7F
            if size == 126:
                size = int.from_bytes(self._read_exact(2), "big")
            elif size == 127:
                size = int.from_bytes(self._read_exact(8), "big")
            if size > _MAX_FRAME_BYTES:
                raise DesktopAutomationError("CDP frame is too large", code="cdp-payload-too-large")
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(size)
            if masked:
                payload = bytes(item ^ mask[index % 4] for index, item in enumerate(payload))
            if opcode == 0x8:
                raise DesktopAutomationError("CDP websocket closed", code="cdp-connection-closed", retryable=True)
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                text_message = True
            elif opcode != 0x0:
                continue
            fragments.append(payload)
            if fin:
                if not text_message:
                    raise DesktopAutomationError("CDP returned a non-text message", code="cdp-protocol-error")
                return b"".join(fragments).decode("utf-8", "replace")

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        with self._lock:
            if self._closed:
                raise DesktopAutomationError("CDP websocket is closed", code="cdp-connection-closed")
            self._next_id += 1
            request_id = self._next_id
            body = json.dumps({"id": request_id, "method": method, "params": dict(params or {})}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self._send_frame(0x1, body)
            deadline = time.monotonic() + self._timeout
            while True:
                try:
                    message = json.loads(self._receive_message(deadline))
                except json.JSONDecodeError as error:
                    raise DesktopAutomationError("CDP returned invalid JSON", code="cdp-protocol-error") from error
                except OSError as error:
                    raise DesktopAutomationError("CDP websocket read failed", code="cdp-connection-closed", retryable=True) from error
                if not isinstance(message, Mapping):
                    continue
                if message.get("id") != request_id:
                    continue
                if message.get("error"):
                    raise DesktopAutomationError("CDP command was rejected", code="cdp-command-failed")
                return message.get("result") or {}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._send_frame(0x8, b"")
            except (OSError, DesktopAutomationError):
                pass
            try:
                self._socket.close()
            except OSError:
                pass


class StdlibCdpRunner:
    """Concrete runner for :class:`ElectronCdpClient`.

    The runner only attaches to an already-running target.  It does not use
    the ``/json/new`` or ``/json/close`` endpoints, so opening/closing a
    Sumika session cannot create or terminate the user's application window.
    """

    def __init__(self, endpoint: str = "http://127.0.0.1:9222", *, timeout: float = 3.0) -> None:
        self.endpoint = str(endpoint or "").rstrip("/")
        self._parsed, self._prefix = _endpoint_parts(self.endpoint)
        self.timeout = max(0.2, min(float(timeout), 30.0))
        self._lock = threading.RLock()
        self._sessions: dict[str, _CdpSocket] = {}
        self._targets: dict[str, dict[str, Any]] = {}

    def _http_json(self, path: str) -> Any:
        api_path = f"{self._prefix}{path}" if self._prefix else path
        url = f"{self._parsed.scheme}://{_authority(self._parsed.hostname, self._parsed.port)}{api_path}"
        opener = build_opener(ProxyHandler({}))
        request = Request(url, headers={"accept": "application/json"}, method="GET")
        try:
            with opener.open(request, timeout=self.timeout) as response:
                chunks: list[bytes] = []
                total = 0
                while total <= _MAX_HTTP_BYTES:
                    chunk = response.read(min(64 * 1024, _MAX_HTTP_BYTES + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                raw = b"".join(chunks)
        except Exception as error:
            raise DesktopAutomationError("CDP HTTP endpoint is unavailable", code="cdp-endpoint-unavailable", retryable=True) from error
        if len(raw) > _MAX_HTTP_BYTES:
            raise DesktopAutomationError("CDP HTTP response is too large", code="cdp-payload-too-large")
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except (TypeError, ValueError) as error:
            raise DesktopAutomationError("CDP endpoint returned invalid JSON", code="cdp-protocol-error") from error

    def _targets_list(self) -> list[dict[str, Any]]:
        value = self._http_json("/json/list")
        if not isinstance(value, list):
            value = self._http_json("/json")
        return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []

    def health(self) -> dict[str, Any]:
        value = self._http_json("/json/version")
        if not isinstance(value, Mapping):
            raise DesktopAutomationError("CDP version response is invalid", code="cdp-protocol-error")
        targets = self._targets_list()
        return {
            "ok": True,
            "state": "ready",
            "browser": str(value.get("Browser") or "")[:120],
            "protocol_version": str(value.get("Protocol-Version") or "")[:40],
            "target_count": len(targets),
        }

    def _choose_target(self, options: Mapping[str, Any]) -> dict[str, Any]:
        targets = self._targets_list()
        target_id = str(options.get("target_id") or options.get("targetId") or "").strip()
        requested_url = str(options.get("target_url") or options.get("url") or "").strip()
        requested_title = str(options.get("title") or "").strip()
        pages = [item for item in targets if str(item.get("type") or "page") == "page"]
        if target_id:
            pages = [item for item in pages if str(item.get("id") or "") == target_id]
        elif requested_url:
            pages = [item for item in pages if str(item.get("url") or "") == requested_url]
        elif requested_title:
            pages = [item for item in pages if str(item.get("title") or "") == requested_title]
        if not pages:
            raise DesktopAutomationError("no matching CDP page target", code="cdp-target-not-found")
        target = pages[0]
        if not target.get("id") or not target.get("webSocketDebuggerUrl"):
            raise DesktopAutomationError("CDP target has no websocket handle", code="cdp-target-invalid")
        return target

    def _open(self, options: Mapping[str, Any]) -> dict[str, Any]:
        nested = options.get("options")
        if isinstance(nested, Mapping):
            options = {**dict(options), **dict(nested)}
        target = self._choose_target(options)
        target_id = str(target["id"])
        session_id = f"cdp-{target_id[:96]}"
        with self._lock:
            if session_id in self._sessions:
                return {"native_session_id": session_id, "target_id": target_id, "url": str(target.get("url") or "")[:500], "reused": True}
        connection = _CdpSocket(str(target["webSocketDebuggerUrl"]), timeout=self.timeout)
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                connection.close()
                return {"native_session_id": session_id, "target_id": target_id, "url": str(target.get("url") or "")[:500], "reused": True}
            self._sessions[session_id] = connection
            self._targets[session_id] = {"id": target_id, "title": str(target.get("title") or "")[:240], "url": str(target.get("url") or "")[:500]}
        return {"native_session_id": session_id, "target_id": target_id, "title": str(target.get("title") or "")[:240], "url": str(target.get("url") or "")[:500]}

    def _connection(self, native_session_id: str) -> _CdpSocket:
        with self._lock:
            connection = self._sessions.get(str(native_session_id))
        if connection is None:
            raise DesktopAutomationError("CDP session is not open", code="cdp-session-not-open")
        return connection

    @staticmethod
    def _evaluate(connection: _CdpSocket, expression: str) -> Any:
        result = connection.request("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if not isinstance(result, Mapping):
            raise DesktopAutomationError("CDP evaluation result is invalid", code="cdp-protocol-error")
        if result.get("exceptionDetails"):
            raise DesktopAutomationError("CDP page evaluation failed", code="cdp-evaluation-failed")
        remote = result.get("result")
        if not isinstance(remote, Mapping):
            return None
        return remote.get("value")

    def _observe(self, native_session_id: str, options: Mapping[str, Any]) -> dict[str, Any]:
        limit = options.get("text_limit", 8000)
        try:
            limit = max(0, min(int(limit), _MAX_OBSERVATION_TEXT))
        except (TypeError, ValueError):
            limit = 8000
        include_text = options.get("include_text", True) is not False
        expression = """(() => {
          const limit = %d;
          const body = document.body;
          const controls = Array.from(document.querySelectorAll('input,textarea,button,select,[contenteditable="true"]')).slice(0, 64).map((node) => ({
            tag: node.tagName,
            type: node.getAttribute('type') || '',
            name: node.getAttribute('name') || '',
            aria: node.getAttribute('aria-label') || '',
            placeholder: node.getAttribute('placeholder') || '',
            text: String(node.innerText || node.value || '').slice(0, 160)
          }));
          return {title: document.title, url: location.href, readyState: document.readyState,
            text: %s ? String(body ? body.innerText || '' : '').slice(0, limit) : '', controls};
        })()""" % (limit, "true" if include_text else "false")
        value = self._evaluate(self._connection(native_session_id), expression)
        return dict(value) if isinstance(value, Mapping) else {"value": value}

    @staticmethod
    def _selector(request: DesktopActionRequest) -> str:
        value = request.target or request.args.get("selector")
        if not isinstance(value, str) or not value.strip():
            raise DesktopAutomationError("DOM action requires a CSS selector", code="invalid-action-target")
        return safe_text(value, "selector", _MAX_SELECTOR, allow_empty=False)

    def _act(self, native_session_id: str, request: DesktopActionRequest) -> dict[str, Any]:
        action = request.action.replace("-", "_").lower()
        if action in {"observe", "read", "snapshot", "inspect"}:
            return self._observe(native_session_id, request.args)
        if action in {"evaluate", "raw_cdp", "console", "network_inspection", "navigate"}:
            raise DesktopAutomationError("arbitrary CDP evaluation is not exposed", code="cdp-action-unavailable")
        selector = self._selector(request)
        selector_json = json.dumps(selector, ensure_ascii=True)
        connection = self._connection(native_session_id)
        if action in {"click", "focus"}:
            method = "click" if action == "click" else "focus"
            expression = "(() => { const node = document.querySelector(%s); if (!node) return {matched:false}; node.%s(); return {matched:true}; })()" % (selector_json, method)
            result = self._evaluate(connection, expression)
            return {"completed": bool(isinstance(result, Mapping) and result.get("matched")), "result": result}
        if action in {"fill", "type", "write"}:
            if not isinstance(request.value, str):
                raise DesktopAutomationError("fill action requires text", code="invalid-action-value")
            value_json = json.dumps(request.value[:64 * 1024], ensure_ascii=True)
            expression = """(() => { const node = document.querySelector(%s); if (!node) return {matched:false};
              node.focus(); const editable = node.isContentEditable || node.getAttribute('contenteditable') === 'true';
              if (editable) { node.textContent = %s; } else if ('value' in node) {
                const proto = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set; if (setter) setter.call(node, %s); else node.value = %s;
              } else return {matched:false, reason:'not-editable'};
              try { node.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText'})); } catch (_) { node.dispatchEvent(new Event('input', {bubbles:true})); }
              node.dispatchEvent(new Event('change', {bubbles:true})); return {matched:true, editable}; })()""" % (selector_json, value_json, value_json, value_json)
            result = self._evaluate(connection, expression)
            return {"completed": bool(isinstance(result, Mapping) and result.get("matched")), "result": result}
        if action == "select":
            if not isinstance(request.value, str):
                raise DesktopAutomationError("select action requires a value", code="invalid-action-value")
            value_json = json.dumps(request.value[:2000], ensure_ascii=True)
            expression = "(() => { const node = document.querySelector(%s); if (!node) return {matched:false}; node.value = %s; node.dispatchEvent(new Event('change', {bubbles:true})); return {matched:true}; })()" % (selector_json, value_json)
            result = self._evaluate(connection, expression)
            return {"completed": bool(isinstance(result, Mapping) and result.get("matched")), "result": result}
        if action == "press":
            key = request.value if isinstance(request.value, str) else request.args.get("key")
            if not isinstance(key, str) or not key.strip():
                raise DesktopAutomationError("press action requires a key", code="invalid-action-value")
            key_json = json.dumps(key[:80], ensure_ascii=True)
            expression = "(() => { const node = document.querySelector(%s); if (!node) return {matched:false}; node.focus(); const event = new KeyboardEvent('keydown', {key:%s, code:%s, bubbles:true}); node.dispatchEvent(event); node.dispatchEvent(new KeyboardEvent('keyup', {key:%s, code:%s, bubbles:true})); return {matched:true}; })()" % (selector_json, key_json, key_json, key_json, key_json)
            result = self._evaluate(connection, expression)
            return {"completed": bool(isinstance(result, Mapping) and result.get("matched")), "result": result}
        if action in {"send", "prompt"}:
            if not isinstance(request.value, str) or not request.value.strip():
                raise DesktopAutomationError("send action requires text", code="invalid-action-value")
            value_json = json.dumps(request.value[:64 * 1024], ensure_ascii=True)
            send_selector = request.args.get("send_selector") or request.args.get("sendSelector")
            send_json = json.dumps(str(send_selector), ensure_ascii=True) if isinstance(send_selector, str) and send_selector.strip() else "null"
            expression = """(() => { const input = document.querySelector(%s); if (!input) return {matched:false}; input.focus();
              const editable = input.isContentEditable || input.getAttribute('contenteditable') === 'true';
              if (editable) { input.textContent = %s; } else if ('value' in input) {
                const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set; if (setter) setter.call(input, %s); else input.value = %s;
              } else return {matched:false, reason:'not-editable'};
              try { input.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText'})); } catch (_) { input.dispatchEvent(new Event('input', {bubbles:true})); }
              const button = %s ? document.querySelector(%s) : null; if (button) button.click(); else input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', bubbles:true}));
              return {matched:true, dispatched:true, editable}; })()""" % (selector_json, value_json, value_json, value_json, "true" if send_json != "null" else "false", send_json)
            result = self._evaluate(connection, expression)
            # A DOM event is not proof that the remote model accepted a send.
            return {"possibly_sent": True, "accepted": bool(isinstance(result, Mapping) and result.get("matched")), "result": result}
        raise DesktopAutomationError("CDP DOM action is unsupported", code="cdp-action-unavailable")

    def __call__(self, operation: str, payload: Mapping[str, Any] | None = None) -> Any:
        options = payload if isinstance(payload, Mapping) else {}
        if operation == "health":
            return self.health()
        if operation == "open":
            return self._open(options)
        native = str(options.get("session_id") or options.get("sessionId") or "").strip()
        if operation == "observe":
            nested = options.get("options")
            return self._observe(native, nested if isinstance(nested, Mapping) else options)
        if operation == "act":
            request = DesktopActionRequest(
                session_id=native,
                action=safe_text(options.get("action"), "action", 80, allow_empty=False).lower(),
                target=options.get("target") if isinstance(options.get("target"), str) else None,
                value=options.get("value"),
                args=options.get("args") if isinstance(options.get("args"), Mapping) else {},
            )
            return self._act(native, request)
        if operation == "close":
            with self._lock:
                connection = self._sessions.pop(native, None)
                self._targets.pop(native, None)
            if connection is not None:
                connection.close()
            return {"closed": True, "session_id": native}
        if operation == "takeover":
            raise DesktopAutomationError("CDP transport does not provide foreground takeover", code="foreground-takeover-unavailable")
        raise DesktopAutomationError("CDP operation is unsupported", code="cdp-operation-unavailable")

    def shutdown(self) -> None:
        with self._lock:
            connections = list(self._sessions.values())
            self._sessions.clear()
            self._targets.clear()
        for connection in connections:
            connection.close()


__all__ = ["StdlibCdpRunner"]
