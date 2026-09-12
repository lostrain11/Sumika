"""DSH 0.1.5-rc.2 Remote API adapter. No private Agent loop or paid fallback."""
import hashlib
from collections import deque
import http.cookiejar
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .authorization import AuthorizationError
from .contracts import HarnessInstance, Recovery, TaskState, ToolRequest, Trust


class DshError(RuntimeError):
    pass


class Dsh:
    # Only these lifecycle operations are admitted in P1. Prompt/model dispatch
    # awaits P2/P3 real tool and model acceptance, never silently falls back.
    ACTIONS = {"session.create": "session/create", "session.cancel": "session/cancel"}

    def __init__(self, root: Path, home: Path):
        self.root, self.home = root.resolve(), home.resolve()
        self.process = None
        self.instance = HarnessInstance("dsh", secrets.token_hex(16), Trust.UNVERIFIED)
        self.sessions = set()
        self.startup_messages = deque(maxlen=20)
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self._cookies))

    def start(self, timeout=60):
        if self.process is not None and self.process.poll() is None:
            raise DshError("instance is already running")
        release = json.loads((self.root / "runtime/dsh/release.json").read_text(encoding="utf-8"))
        runtime = self.root / "runtime/dsh"
        for name, digest in release["files"].items():
            if hashlib.sha256((runtime / name).read_bytes()).hexdigest() != digest:
                raise DshError("release manifest mismatch")
        cli = runtime / "node_modules/@deepseek-ai/dsh/lib/bin.js"
        package = json.loads((cli.parent.parent / "package.json").read_text(encoding="utf-8"))
        if package["version"] != release["version"]:
            raise DshError("installed DSH version mismatch")
        node = shutil.which("node")
        if not node:
            raise DshError("node is required")
        self.home.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not (
            k.startswith(("DSH_", "OPENAI_", "ANTHROPIC_", "DEEPSEEK_"))
            or k.endswith(("_API_KEY", "_API_TOKEN")))}
        env["DSH_HOME"] = str(self.home)
        self.process = subprocess.Popen(
            [node, str(cli), "--profile", "web", "--host", "127.0.0.1", "--port", "0", "--no-open"],
            cwd=self.home, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        lines = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.startup_messages.append(re.sub(r"(?i)(token|api[_-]?key|password)([=:]\s*)[^\s]+", r"\1\2<redacted>", line).strip())
                lines.put(line)
        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise DshError("DSH exited during startup")
                try:
                    line = lines.get(timeout=.2)
                except queue.Empty:
                    continue
                match = re.search(r"dsh web: (http://127\.0\.0\.1:(\d+)/\?token=[A-Za-z0-9_-]+)", line)
                if not match:
                    continue
                self.url = "http://127.0.0.1:" + match[2]
                # The token is obtained from the owned child's stdout, not an arbitrary endpoint.
                with self._opener.open(match[1], timeout=15) as response:
                    response.read()
                self._check_owner(int(match[2]))
                self._rpc("settings/describe", {})
                self.instance = HarnessInstance("dsh", self.instance.instance_id, Trust.MANAGED)
                return self
            raise DshError("DSH startup timed out")
        except BaseException:
            self.close()
            raise

    def _check_owner(self, port):
        if self.process is None or self.process.poll() is not None:
            raise DshError("managed process is no longer alive")
        if os.name != "nt":
            raise DshError("managed peer verification currently supports Windows only")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
            f"(Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction Stop).OwningProcess"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        owners = set(result.stdout.split())
        if result.returncode or str(self.process.pid) not in owners or len(owners) != 1:
            raise DshError("listening socket does not belong to managed process")

    def _rpc(self, method, arguments):
        rpc_id = secrets.token_hex(16)
        body = json.dumps({"type": "client-request", "rpcId": rpc_id,
                           "method": method, "payload": {"args": {} if method == "settings/describe" else {"request": arguments}}}).encode()
        request = urllib.request.Request(self.url + "/api/" + method, data=body,
            headers={"Content-Type": "application/json", "Origin": self.url})
        try:
            with self._opener.open(request, timeout=20) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise DshError(f"DSH RPC {method} HTTP {error.code}") from None
        if not isinstance(result, dict) or result.get("type") != "server-response" or result.get("rpcId") != rpc_id:
            raise DshError("invalid or mismatched RPC response")
        outcome = result.get("result")
        if not isinstance(outcome, dict) or outcome.get("ok") is not True:
            code = outcome.get("error", {}).get("code", "malformed") if isinstance(outcome, dict) else "malformed"
            raise DshError(f"DSH RPC {method} failed: {code}")
        if "value" not in outcome:
            raise DshError("RPC success has no value")
        return outcome.get("value")

    def execute(self, request: ToolRequest):
        if self.instance.trust != Trust.MANAGED or request.binding.instance_id != self.instance.instance_id:
            raise AuthorizationError("unverified or different instance")
        self._check_owner(int(self.url.rsplit(":", 1)[1]))
        if request.action not in self.ACTIONS:
            raise AuthorizationError("unsupported action; no implicit model or tool dispatch")
        args = json.loads(request.arguments)
        if not isinstance(args, dict) or args.get("sessionId") != request.binding.session_id:
            raise AuthorizationError("session arguments differ from approved binding")
        if request.action == "session.create":
            if set(args) != {"sessionId", "cwd"}:
                raise AuthorizationError("unsupported create arguments")
            cwd = Path(args["cwd"])
            if not cwd.is_absolute() or not cwd.is_dir() or str(cwd.resolve()) != request.target:
                raise AuthorizationError("workspace differs from approved target")
        else:
            if set(args) != {"sessionId"} or args["sessionId"] not in self.sessions or request.target != args["sessionId"]:
                raise AuthorizationError("session is not owned by this adapter")
        result = self._rpc(self.ACTIONS[request.action], args)
        if request.action == "session.create":
            if not isinstance(result, dict) or result.get("sessionId") != args["sessionId"]:
                raise DshError("create acknowledged a different session")
            self.sessions.add(args["sessionId"])
        elif result != {"accepted": True}:
            raise DshError("cancel was not acknowledged")
        return result

    def inspect(self, binding):
        if binding.instance_id != self.instance.instance_id or binding.session_id not in self.sessions:
            raise AuthorizationError("unknown session binding")
        self._check_owner(int(self.url.rsplit(":", 1)[1]))
        history = self._rpc("session/page", {"address": {"kind": "session", "sessionId": binding.session_id}, "throughSeq": 0})
        if not isinstance(history, dict) or not isinstance(history.get("records"), list):
            raise DshError("invalid history response")
        # History availability alone proves neither task completion nor safe replay.
        return Recovery(binding, TaskState.UNKNOWN)

    def stream(self, endpoint, arguments, timeout=15):
        """Read native Remote streams; iteration errors never authorize replay."""
        import websocket
        if endpoint not in ("session/follow", "session/control", "$events"):
            raise DshError("unsupported read stream")
        self._check_owner(int(self.url.rsplit(":", 1)[1]))
        request = urllib.request.Request(self.url + "/api/remote.mux")
        self._cookies.add_cookie_header(request)
        ws = websocket.create_connection(self.url.replace("http:", "ws:") + "/api/remote.mux",
            cookie=request.get_header("Cookie"), origin=self.url, timeout=timeout,
            http_no_proxy=["127.0.0.1"])
        stream_id = secrets.token_hex(16)
        payload = {"args": {"request": arguments}} if endpoint == "session/follow" else {"args": arguments}
        try:
            ws.send(json.dumps({"type":"open", "streamId":stream_id, "endpoint":endpoint, "payload":payload}))
            while True:
                frame = json.loads(ws.recv())
                if frame.get("streamId") != stream_id:
                    raise DshError("stream id mismatch")
                if frame.get("type") == "item":
                    yield frame["value"]
                elif frame.get("type") == "end":
                    return
                else:
                    raise DshError(f"Remote stream error: {frame.get('error', {}).get('code', 'malformed')}")
        finally:
            ws.close()

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.process.stdout:
                self.process.stdout.close()
        self.instance = HarnessInstance("dsh", self.instance.instance_id, Trust.UNVERIFIED)
        self.sessions.clear()
