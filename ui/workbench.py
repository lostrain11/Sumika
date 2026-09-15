"""Managed DSH lifecycle for the workbench page.

Starting the workbench launches the same managed entry the CLI uses
(`python -m sumika_next.cli run`). The bridge never fabricates a running state:
it reports the child process it actually owns, and stops only that process tree.
"""
import json
import socket
import sys
import threading
import uuid
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

from sumika_next.daily import default_home
from sumika_next.dsh import Dsh, DshError

SKIN_MODULE = Path(__file__).resolve().parents[1] / "extensions" / "ui" / "sumika-skin" / "dsh.mjs"
BRAND_PACKAGE = Path(__file__).resolve().parents[1] / "extensions" / "ui" / "sumika-brand"


def ensure_skin(home, *, enabled=True):
    """Register the Sumika skin in a managed profile's patch layer.

    The patch file is the documented extension point of a DSH profile; nothing
    under runtime/dsh is touched. Idempotent, and never touches other rows.
    """
    patch = Path(home) / "cordis.patch.yml"
    try:
        rows = json.loads(patch.read_text(encoding="utf8")) if patch.is_file() else []
        if not isinstance(rows, list):
            return {"registered": False, "reason": "unexpected patch layer shape"}
    except (OSError, ValueError):
        return {"registered": False, "reason": "patch layer is not valid JSON"}
    entry = {"id": "sumika-skin", "name": str(SKIN_MODULE), "config": {"enabled": bool(enabled)}}
    found = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for item in row.get("insert", []) or []:
            if isinstance(item, dict) and item.get("id") == "sumika-skin":
                item.update(entry)
                found = True
    if not found:
        rows.append({"insert": [entry]})
    # The brand plugin ships a browser half, so its loader entry points at the
    # package (the host reads dsh.client and serves exports["./client"]).
    # The official brand occupies the same slot keys, so our half shadows it by
    # priority instead of disabling an upstream plugin (verified against the real
    # client; see docs/project/workbench-skin-plan.md).
    # The loader imports this path as a module, so it must be a file; the host
    # still reads the enclosing package.json to find dsh.client and ./client.
    release = None
    release_path = Path(home).parents[2] / "runtime" / "dsh" / "release.json"
    if not release_path.is_file():
        release_path = Path(__file__).resolve().parents[1] / "runtime" / "dsh" / "release.json"
    try:
        release = json.loads(release_path.read_text(encoding="utf8")).get("version")
    except (OSError, ValueError):
        release = None
    brand_entry = {"id": "sumika-brand", "name": str(BRAND_PACKAGE / "lib" / "index.js"),
                   "config": {"harness": "dsh", "release": release}}
    brand_found = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for item in row.get("insert", []) or []:
            if isinstance(item, dict) and item.get("id") == "sumika-brand":
                item.update(brand_entry)
                brand_found = True
    if not brand_found:
        rows.append({"insert": [brand_entry]})
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return {"registered": True, "enabled": bool(enabled), "path": str(patch)}


class WorkbenchError(RuntimeError):
    pass


class WorkbenchController:
    def __init__(self, root, *, python=None, browser=False, start_timeout=90):
        self.root = Path(root).resolve()
        self.python = python or sys.executable
        self.browser = browser
        self.start_timeout = start_timeout
        self.adapter = None
        self.url = None
        self._embed_url = None
        self.log = deque(maxlen=200)
        self.timeline = deque(maxlen=200)
        # Re-entrant: start() cleans up through stop() while still holding it.
        self._lock = threading.RLock()

    # ---- facts -----------------------------------------------------------------
    def release(self):
        path = self.root / "runtime" / "dsh" / "release.json"
        if not path.is_file():
            return {"installed": False, "version": None, "verified": False}
        value = json.loads(path.read_text(encoding="utf-8"))
        installed = (self.root / "runtime" / "dsh" / "node_modules" /
                     "@deepseek-ai" / "dsh" / "package.json").is_file()
        return {"installed": installed, "version": value.get("version"),
                "verified": value.get("status") == "verified"}

    def profile(self):
        from sumika_next.daily import default_home
        try:
            return str(default_home(self.root))
        except (OSError, ValueError, KeyError):
            return None

    def running(self):
        process = getattr(self.adapter, "process", None)
        return process is not None and process.poll() is None

    def status(self):
        release = self.release()
        process = getattr(self.adapter, "process", None)
        return {**release, "profile": self.profile(), "running": self.running(),
                "url": self.url if self.running() else None,
                "pid": process.pid if self.running() else None,
                "embed_ready": bool(self.running() and self._embed_url),
                "recent_log": list(self.log)[-8:],
                "timeline": list(self.timeline)}

    def embed_url(self):
        """Tokenized URL of the owned instance. Never logged or written to evidence."""
        if not self.running() or not self._embed_url:
            raise WorkbenchError("managed DSH is not running")
        return {"url": self._embed_url}

    def create_session(self, workspace=None):
        """Create one native session in a workspace so the UI leaves its welcome state."""
        if not self.running():
            raise WorkbenchError("managed DSH is not running")
        path = Path(workspace).resolve() if workspace else Path(self.root)
        if not path.is_dir():
            raise WorkbenchError("workspace directory does not exist")
        session_id = "sumika-" + uuid.uuid4().hex[:12]
        try:
            self.adapter._rpc("session/create", {"sessionId": session_id, "cwd": str(path)})
        except Exception as error:
            raise WorkbenchError(f"session/create failed: {type(error).__name__}: {error}") from error
        self._record(f"已创建工作区会话 {session_id}（{path}）")
        return {"session_id": session_id, "cwd": str(path)}

    _ERROR_MARKERS = ("error", "exception", "traceback", "failed", "failure", "refused", "denied")

    def _record(self, line):
        """Keep a bounded, timestamped task timeline; never invent entries."""
        text = line.rstrip()
        if not text:
            return
        lowered = text.casefold()
        if any(marker in lowered for marker in self._ERROR_MARKERS):
            level = "error"
        elif text.startswith(("DSH Web:", "Profile:", "Workspace session:", "Select the model", "Browser disabled")):
            level = "system"
        else:
            level = "info"
        self.log.append(text)
        self.timeline.append({"at": datetime.now(timezone.utc).isoformat(), "level": level,
                              "text": text})

    # ---- lifecycle -------------------------------------------------------------
    def start(self, workspace=None, port=0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise WorkbenchError("invalid port")
        with self._lock:
            if self.running():
                return self.status()
            release = self.release()
            if not release["installed"]:
                raise WorkbenchError("managed DSH is not installed under runtime/dsh")
            if port and self._port_in_use(port):
                # The fixed port may still be held by an instance this bridge does not
                # own. If it is our own orphan (same managed profile) we stop it;
                # anything else must be reported instead of killed.
                if not self._stop_orphan(port):
                    raise WorkbenchError(
                        f"port {port} is already in use by another program; free it or "
                        f"pick a different port before starting again")
            self.log.clear()
            self.timeline.clear()
            self.url = None
            self._embed_url = None
            home = default_home(self.root)
            home.mkdir(parents=True, exist_ok=True)
            skin = ensure_skin(home)
            if skin.get("registered"):
                self._record("Sumika 皮肤已登记到受管 profile")
            adapter = Dsh(self.root, home)
            try:
                # Owning the adapter (instead of spawning the CLI) keeps the PID, the
                # tokenized launch URL and the RPC surface inside this process.
                adapter.start(port=port)
            except Exception as error:  # boundary layer: any adapter failure becomes one error type
                detail = ""
                messages = list(getattr(adapter, "startup_messages", []) or [])
                if messages:
                    detail = " | " + " | ".join(str(line).strip() for line in messages[-12:])
                raise WorkbenchError(
                    f"managed DSH failed to start: {type(error).__name__}: {error}{detail}") from error
            if not getattr(adapter, "url", None):
                try:
                    adapter.close()
                except (DshError, OSError):
                    pass
                raise WorkbenchError("managed DSH did not report a URL")
            self.adapter = adapter
            self.url = adapter.url
            self._embed_url = adapter._browser_url
            for line in list(getattr(adapter, "startup_messages", []) or []):
                self._record(str(line))
            self._record(f"DSH Web: {self.url}")
            return self.status()

    def stop(self):
        with self._lock:
            if self.adapter is None:
                return {"stopped": False, "reason": "no process owned by this bridge"}
            process = getattr(self.adapter, "process", None)
            pid = getattr(process, "pid", None)
            alive = self.running()
            try:
                self.adapter.close()
            except (DshError, OSError):
                pass
            self.adapter = None
            self.url = None
            self._embed_url = None
            return {"stopped": alive, "pid": pid}

    @staticmethod
    def _port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            return probe.connect_ex(("127.0.0.1", int(port))) == 0

    def _stop_orphan(self, port):
        """Stop a leftover DSH launched from our own managed profile, if that is
        what holds the port. Returns True only when we identified and stopped it."""
        import subprocess
        try:
            listing = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-NetTCPConnection -State Listen -LocalPort "
                 f"{int(port)} -ErrorAction SilentlyContinue).OwningProcess"],
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            pid = listing.stdout.strip().splitlines()[0].strip() if listing.stdout.strip() else ""
            if not pid.isdigit():
                return False
            detail = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            command = detail.stdout or ""
        except (OSError, subprocess.SubprocessError, IndexError):
            return False
        # The child runs as `<root>/runtime/dsh/.../bin.js --profile web --port N`,
        # so the runtime path plus the port identifies our own instance.
        marker = str(Path(self.root) / "runtime" / "dsh")
        if marker not in command or f"--port {int(port)}" not in command:
            return False
        try:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                           capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        for _ in range(20):
            if not self._port_in_use(port):
                self._record(f"已清理遗留的受管 DSH 进程（pid {pid}）")
                return True
            threading.Event().wait(0.5)
        return False
