"""Managed DSH lifecycle for the workbench page.

Starting the workbench launches the same managed entry the CLI uses
(`python -m sumika_next.cli run`). The bridge never fabricates a running state:
it reports the child process it actually owns, and stops only that process tree.
"""
import json
import socket
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from sumika_next.daily import default_home
from sumika_next.dsh import Dsh, DshError
from sumika_next.contracts import Trust
from sumika_next.runtime_ownership import ProfileLease

SKIN_MODULE = Path(__file__).resolve().parents[1] / "extensions" / "ui" / "sumika-skin" / "dsh.mjs"
BRAND_PACKAGE = Path(__file__).resolve().parents[1] / "extensions" / "ui" / "sumika-brand"
WORKBENCH_PACKAGE = Path(__file__).resolve().parents[1] / "extensions" / "ui" / "sumika-workbench"


def ensure_skin(home, *, enabled=True, root=None, bridge_origin=None):
    """Register the Sumika skin in a managed profile's patch layer.

    The patch file is the documented extension point of a DSH profile; nothing
    under runtime/dsh is touched. Idempotent, and never touches other rows.
    """
    product = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    plugin_root = product / "extensions" / "ui"
    patch = Path(home) / "cordis.patch.yml"
    try:
        rows = json.loads(patch.read_text(encoding="utf8")) if patch.is_file() else []
        if not isinstance(rows, list):
            return {"registered": False, "reason": "unexpected patch layer shape"}
    except (OSError, ValueError):
        return {"registered": False, "reason": "patch layer is not valid JSON"}
    entry = {"id": "sumika-skin", "name": str(plugin_root / "sumika-skin" / "dsh.mjs"), "config": {"enabled": bool(enabled)}}
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
    release_path = product / "runtime" / "dsh" / "release.json"
    try:
        release = json.loads(release_path.read_text(encoding="utf8")).get("version")
    except (OSError, ValueError):
        release = None
    brand_entry = {"id": "sumika-brand", "name": str(plugin_root / "sumika-brand" / "lib" / "index.js"),
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
    # The workbench additions ship a browser half too, so their loader entry has
    # the same shape: a file path plus the enclosing package's dsh.client.
    workbench_entry = {"id": "sumika-workbench",
                       "name": str(plugin_root / "sumika-workbench" / "lib" / "index.js"),
                       "config": {"scheduleRequests":str(Path(home).resolve()/'sumika-schedule-requests'),
                                  **({"bridgeOrigin": bridge_origin} if bridge_origin else {})}}
    workbench_found = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for item in row.get("insert", []) or []:
            if isinstance(item, dict) and item.get("id") == "sumika-workbench":
                item.update(workbench_entry)
                workbench_found = True
    if not workbench_found:
        rows.append({"insert": [workbench_entry]})
    from extensions.office.native import configure as configure_office
    configure_office(rows, product)
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return {"registered": True, "enabled": bool(enabled), "path": str(patch)}


class WorkbenchError(RuntimeError):
    pass


class WorkbenchController:
    def __init__(self, root, *, python=None, browser=False, start_timeout=90, capability_database=None,
                 browser_registry=None):
        self.root = Path(root).resolve()
        self.python = python or sys.executable
        self.browser = browser
        self.start_timeout = start_timeout
        self.capability_database = capability_database
        self.browser_registry = Path(browser_registry).resolve() if browser_registry is not None else None
        self.adapter = None
        self._lease = None
        # Set by the bridge once its listen port is known; used to bind the
        # workbench plugin's postMessage origin to the exact shell origin.
        self.bridge_origin = None
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

    def work_model(self):
        """Best-effort read of the active DSH session model.

        The model is owned by the native workbench, never configured here. A
        managed Session exposes its last-used selection in the session list;
        if the instance is unowned or not ready, report unknown instead of
        inventing a model name.
        """
        if not self.running() or self.adapter is None:
            return None
        try:
            value = self.adapter._rpc("session/list", {})
            items = value.get("items") if isinstance(value, dict) else None
            if not isinstance(items, list):
                return None
            for item in items:
                if not isinstance(item, dict):
                    continue
                selection = (((item.get("projections") or {}).get("values") or {})
                             .get("modelSelection") or {})
                chosen = selection.get("lastUsed") or selection.get("next")
                if isinstance(chosen, dict) and isinstance(chosen.get("model"), str) and chosen["model"].strip():
                    return {"provider": chosen.get("provider"), "model": chosen["model"]}
        except Exception:
            return None
        return None

    def status(self):
        release = self.release()
        process = getattr(self.adapter, "process", None)
        return {**release, "profile": self.profile(), "running": self.running(),
                "url": self.url if self.running() else None,
                "pid": process.pid if self.running() else None,
                "embed_ready": bool(self.running() and self._embed_url),
                "work_model": self.work_model(),
                "recent_log": list(self.log)[-8:],
                "timeline": list(self.timeline)}

    def embed_url(self):
        """Tokenized URL of the owned instance. Never logged or written to evidence."""
        if not self.running() or not self._embed_url:
            raise WorkbenchError("managed DSH is not running")
        return {"url": self._embed_url}

    def browser_binding(self):
        """Exact live native origin and identity, never inferred from a port."""
        with self._lock:
            if not self.running() or self._lease is None:
                return None
            instance = self.adapter.instance
            if instance.trust != Trust.MANAGED:
                return None
            target = urlsplit(self.url or '')
            if target.scheme != 'http' or target.hostname != '127.0.0.1' or not target.port:
                return None
            if target.username or target.password:
                return None
            return (f'http://127.0.0.1:{target.port}', instance.instance_id)

    def handoff_context(self, workspace_id, session_id):
        """Resolve a selected session from the live native registry, not browser claims."""
        if not isinstance(workspace_id, str) or not workspace_id.strip() or not isinstance(session_id, str) or not session_id.strip():
            raise ValueError('explicit target workspace and session required')
        with self._lock:
            if self.browser_binding() is None:
                raise WorkbenchError('managed DSH is not running')
            stream = self.adapter.stream('workspace/follow', {}, timeout=15)
            try:
                baseline = next(stream)
            finally:
                stream.close()
            if not isinstance(baseline, dict) or baseline.get('type') != 'baseline':
                raise WorkbenchError('native workspace baseline unavailable')
            value = baseline.get('value', {})
            items = value.get('items') if isinstance(value, dict) else None
            if not isinstance(items, list):
                raise WorkbenchError('invalid native workspace baseline')
            matches = [item for item in items if isinstance(item, dict) and item.get('workspaceId') == workspace_id]
            if len(matches) != 1 or session_id not in matches[0].get('sessionIds', []):
                raise ValueError('target session does not belong to selected workspace')
            workspace = matches[0]
            return {'project': {'id': workspace_id, 'name': workspace.get('title'),
                                'path': workspace.get('path')},
                    'session_id': session_id, 'receipts': [],
                    'provenance': 'host_verified', 'source': 'dsh-workspace-registry'}

    def schedule_targets(self):
        """Read the owned native registry; never start a runtime to enumerate."""
        with self._lock:
            if self.browser_binding() is None:
                return {'ready': False, 'projects': [], 'reason': '请先启动工作台'}
            stream = self.adapter.stream('workspace/follow', {}, timeout=15)
            try:
                baseline = next(stream)
            finally:
                stream.close()
            if not isinstance(baseline, dict) or baseline.get('type') != 'baseline':
                raise WorkbenchError('native workspace baseline unavailable')
            items = baseline.get('value', {}).get('items')
            if not isinstance(items, list):
                raise WorkbenchError('invalid native workspace baseline')
            return {'ready': True, 'projects': [
                {'id': w['workspaceId'], 'name': w.get('title') or w['workspaceId'],
                 'sessions': w.get('sessionIds', [])}
                for w in items if isinstance(w, dict) and isinstance(w.get('workspaceId'), str)]}

    def create_native_schedule(self, payload):
        from ui.schedule import native_request
        import re
        request_id = payload.get('request_id')
        if payload.get('confirmed') is not True or not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,100}', request_id):
            raise ValueError('explicit confirmation and request identity required')
        schedule = native_request(payload.get('definition'))
        with self._lock:
            self.handoff_context(payload.get('workspace_id'), payload.get('session_id'))
            command = {'request_id': request_id, 'workspace_id': payload['workspace_id'],
                       'confirmed': True, 'schedule': schedule}
            try:
                response = self.adapter._rpc('commands/execute', {
                    'agentId': payload['session_id'],
                    'line': '/sumika-schedule-create ' + json.dumps(command, ensure_ascii=False),
                    'submittedAttachments': []})
            except Exception:
                return {'state': 'unknown', 'request_id': request_id, 'retry': False,
                        'message': '连接中断，创建结果未确认；请到原生自动化任务核对，勿重复创建。'}
            result = response.get('result', {})
            if result.get('kind') != 'success':
                raise ValueError(result.get('text') or 'native command rejected')
            try:
                value = json.loads(result['text'])
                if value.get('state') not in ('created', 'unknown'):
                    raise ValueError('invalid creation result')
            except (ValueError, KeyError, TypeError, AttributeError):
                return {'state': 'unknown', 'request_id': request_id, 'retry': False}
            return value

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
            if self.adapter is not None:
                self.stop()  # Release only after the previous child is confirmed gone.
            release = self.release()
            if not release["installed"]:
                raise WorkbenchError("managed DSH is not installed under runtime/dsh")
            if port and self._port_in_use(port):
                # Port and command line are not proof of instance ownership.
                raise WorkbenchError(f"port {port} is occupied by an unowned instance; no process was stopped")
            self.log.clear()
            self.timeline.clear()
            self.url = None
            self._embed_url = None
            home = default_home(self.root)
            home.mkdir(parents=True, exist_ok=True)
            try:
                self._lease = ProfileLease(home).acquire()
            except (OSError, ValueError) as error:
                raise WorkbenchError('profile ownership unknown or already in use') from error
            try:
                skin = ensure_skin(home, root=self.root, bridge_origin=self.bridge_origin)
                if self.browser_registry is not None:
                    from extensions.desktop.review_install import install as install_review
                    install_review(home, root=self.root, python=self.python,
                                   registry=self.browser_registry, registered_workspaces=True, managed=True)
                from extensions.desktop.screenshot_skill import publish
                screenshot_skill = publish(home, root=self.root, capabilities=self.capability_database)
                if screenshot_skill.get('registered'):
                    self._record('一次性截图翻译 Skill 已登记到受管 profile')
                if skin.get("registered"):
                    self._record("Sumika 皮肤已登记到受管 profile")
                adapter = Dsh(self.root, home)
            except Exception:
                self._lease.release()
                self._lease = None
                raise
            self.adapter = adapter
            try:
                # Owning the adapter (instead of spawning the CLI) keeps the PID, the
                # tokenized launch URL and the RPC surface inside this process.
                adapter.start(port=port)
                self._lease.bind(adapter.process)
            except Exception as error:  # boundary layer: any adapter failure becomes one error type
                try:
                    self.stop()
                except WorkbenchError:
                    pass  # Keep ownership and unknown state, never claim cleanup.
                detail = ""
                messages = list(getattr(adapter, "startup_messages", []) or [])
                if messages:
                    detail = " | " + " | ".join(str(line).strip() for line in messages[-12:])
                raise WorkbenchError(
                    f"managed DSH failed to start: {type(error).__name__}: {error}{detail}") from error
            if not getattr(adapter, "url", None):
                try:
                    self.stop()
                except WorkbenchError:
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
            except (DshError, OSError, subprocess.TimeoutExpired) as error:
                raise WorkbenchError('stop outcome unknown; instance retained for inspection') from error
            if process is not None and process.poll() is None:
                raise WorkbenchError('process exit not confirmed; instance retained for inspection')
            if self._lease is not None:
                self._lease.release()
                self._lease = None
            self.adapter = None
            self.url = None
            self._embed_url = None
            return {"stopped": alive, "pid": pid}

    @staticmethod
    def _port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            return probe.connect_ex(("127.0.0.1", int(port))) == 0

