from __future__ import annotations

import base64
import hashlib
import json
import socket
import socketserver
import threading
import unittest
from urllib.parse import urlparse

from sumika_core.desktop_automation import (
    DesktopActionRequest,
    DesktopAutomationError,
    DesktopApplication,
    ElectronCdpClient,
    ZCodeDesktopAdapter,
    StdlibCdpRunner,
)


def _read_exact(stream: socket.socket, size: int) -> bytes:
    value = bytearray()
    while len(value) < size:
        chunk = stream.recv(size - len(value))
        if not chunk:
            raise OSError("connection closed")
        value.extend(chunk)
    return bytes(value)


def _read_http(stream: socket.socket) -> tuple[str, dict[str, str]]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        data.extend(stream.recv(4096))
    head = bytes(data).split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
    lines = head.split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower().strip()] = value.strip()
    return lines[0], headers


def _read_ws_frame(stream: socket.socket) -> tuple[int, bytes]:
    first, second = _read_exact(stream, 2)
    opcode = first & 0x0F
    size = second & 0x7F
    if size == 126:
        size = int.from_bytes(_read_exact(stream, 2), "big")
    elif size == 127:
        size = int.from_bytes(_read_exact(stream, 8), "big")
    mask = _read_exact(stream, 4) if second & 0x80 else b""
    payload = _read_exact(stream, size)
    if mask:
        payload = bytes(item ^ mask[index % 4] for index, item in enumerate(payload))
    return opcode, payload


def _write_ws_frame(stream: socket.socket, payload: bytes, opcode: int = 1) -> None:
    size = len(payload)
    if size < 126:
        head = bytes((0x80 | opcode, size))
    elif size <= 0xFFFF:
        head = bytes((0x80 | opcode, 126)) + size.to_bytes(2, "big")
    else:
        head = bytes((0x80 | opcode, 127)) + size.to_bytes(8, "big")
    stream.sendall(head + payload)


class _CdpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        stream = self.request
        request_line, headers = _read_http(stream)
        path = request_line.split(" ", 2)[1]
        self.server.paths.append(path)
        if headers.get("upgrade", "").lower() != "websocket":
            if path.endswith("/json/version"):
                body = json.dumps({"Browser": "FakeZCode/1", "Protocol-Version": "1.3"}).encode()
            elif path.endswith("/json/list") or path.endswith("/json"):
                port = self.server.server_address[1]
                body = json.dumps(
                    [
                        {
                            "id": "page-1",
                            "type": "page",
                            "title": "ZCode",
                            "url": "http://127.0.0.1:3000/",
                            "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/page-1",
                        }
                    ]
                ).encode()
            else:
                body = b"{}"
            stream.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            return
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        stream.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            + f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
        )
        while True:
            try:
                opcode, payload = _read_ws_frame(stream)
            except OSError:
                return
            if opcode == 8:
                return
            if opcode == 9:
                _write_ws_frame(stream, payload, opcode=10)
                continue
            if opcode != 1:
                continue
            try:
                message = json.loads(payload.decode())
            except (ValueError, UnicodeError):
                continue
            if not isinstance(message, dict) or message.get("method") != "Runtime.evaluate":
                continue
            expression = str(message.get("params", {}).get("expression") or "")
            self.server.expressions.append(expression)
            value = (
                {
                    "title": "ZCode",
                    "url": "http://127.0.0.1:3000/",
                    "readyState": "complete",
                    "text": "fake page",
                    "controls": [],
                }
                if "controls" in expression
                else {"matched": True, "dispatched": True}
            )
            result = {
                "id": message.get("id"),
                "result": {
                    "result": {
                        "type": "object",
                        "value": value,
                    }
                },
            }
            _write_ws_frame(stream, json.dumps(result, separators=(",", ":")).encode())


class _CdpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paths = []
        self.expressions = []


class CdpTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _CdpServer(("127.0.0.1", 0), _CdpHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_builtin_runner_discovers_target_and_maps_safe_dom_actions(self):
        runner = StdlibCdpRunner(self.endpoint)
        self.addCleanup(runner.shutdown)
        health = runner("health")
        self.assertTrue(health["ok"])
        self.assertEqual(health["target_count"], 1)

        opened = runner("open", {"options": {"target_id": "page-1"}})
        session_id = opened["native_session_id"]
        self.assertTrue(session_id.startswith("cdp-page-1"))
        observed = runner("observe", {"session_id": session_id, "options": {"text_limit": 200}})
        self.assertEqual(observed["title"], "ZCode")
        self.assertEqual(observed["text"], "fake page")

        click = runner(
            "act",
            {"session_id": session_id, "action": "click", "target": "#send", "args": {}},
        )
        self.assertTrue(click["completed"])
        send = runner(
            "act",
            {
                "session_id": session_id,
                "action": "send",
                "target": "textarea",
                "value": "hello",
                "args": {},
            },
        )
        self.assertTrue(send["possibly_sent"])

        closed = runner("close", {"session_id": session_id})
        self.assertTrue(closed["closed"])

    def test_runner_rejects_non_loopback_and_arbitrary_evaluation(self):
        with self.assertRaisesRegex(DesktopAutomationError, "loopback"):
            StdlibCdpRunner("http://example.com:9222")
        with self.assertRaisesRegex(DesktopAutomationError, "query"):
            StdlibCdpRunner("http://127.0.0.1:9222?token=ignored")
        with self.assertRaisesRegex(DesktopAutomationError, "port"):
            StdlibCdpRunner("http://127.0.0.1:0")
        self.assertFalse(ElectronCdpClient("http://127.0.0.1:9222?token=ignored").available)
        self.assertFalse(ElectronCdpClient("http://127.0.0.1:0").available)
        request = DesktopActionRequest(session_id="session", action="evaluate", target=None)
        self.assertEqual(request.action, "evaluate")
        runner = StdlibCdpRunner(self.endpoint)
        self.addCleanup(runner.shutdown)
        opened = runner("open", {"options": {"target_id": "page-1"}})
        with self.assertRaisesRegex(DesktopAutomationError, "not exposed"):
            runner(
                "act",
                {
                    "session_id": opened["native_session_id"],
                    "action": "evaluate",
                    "value": "document.cookie",
                    "args": {},
                },
            )

    def test_runner_preserves_endpoint_path_and_supports_contenteditable_input(self):
        runner = StdlibCdpRunner(f"{self.endpoint}/proxy")
        self.addCleanup(runner.shutdown)
        health = runner("health")
        self.assertTrue(health["ok"])
        self.assertIn("/proxy/json/version", self.server.paths)
        self.assertIn("/proxy/json/list", self.server.paths)
        opened = runner("open", {"target_id": "page-1"})
        value = "line\u2028break"
        filled = runner(
            "act",
            {
                "session_id": opened["native_session_id"],
                "action": "fill",
                "target": "[contenteditable='true']",
                "value": value,
                "args": {},
            },
        )
        self.assertTrue(filled["completed"])
        expression = self.server.expressions[-1]
        self.assertIn("isContentEditable", expression)
        self.assertNotIn("\u2028", expression)
        self.assertIn("\\u2028", expression)

    def test_zcode_adapter_uses_builtin_cdp_only_when_explicitly_configured(self):
        class UnavailableRuntime:
            runtime_id = "zcode"

            def health(self):
                return {"ok": False, "state": "unavailable"}

        adapter = ZCodeDesktopAdapter(runtime=UnavailableRuntime())
        application = DesktopApplication(
            app_id="zcode-cdp",
            name="ZCode CDP",
            adapter_id="zcode-desktop",
            config={"enable_cdp": True, "cdp_endpoint": self.endpoint},
        )
        health = adapter.health(application)
        self.assertTrue(health["ok"])
        self.assertEqual(health["transport"], "electron-cdp")
        opened = adapter.open(application, "default", {"target_id": "page-1"})
        self.assertEqual(opened["transport"], "electron-cdp")
        adapter.shutdown()


if __name__ == "__main__":
    unittest.main()
