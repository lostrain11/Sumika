"""Loopback UI bridge: serve the D-direction UI and expose real Sumika state.

Only 127.0.0.1 binding is allowed. Endpoints return projections or validated
settings; credentials are never returned, and a disabled role model performs no
request at all.
"""
import argparse
import json
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from extensions.capabilities import CapabilityStore
from extensions.desktop.audio_devices import list_input_devices
from extensions.models.cloud import CloudError
from extensions.models.ollama import OllamaError
from extensions.models.settings import default_path, load as load_settings, save as save_settings
from extensions.roles.card_context import compile_card, resolve_language_policy
from extensions.roles.chat import RoleChat, open_session
from extensions.roles.roles import list_roles, load_role
from ui.state_snapshot import snapshot, validate_state
from ui import startup as startup_registry
from ui.readiness import probes as readiness_probes, service_capabilities
from ui.schedule import ScheduleController
from ui.workbench import WorkbenchController, WorkbenchError

UI_ROOT = Path(__file__).resolve().parent
BUILTIN_ROLES = UI_ROOT.parent / "extensions" / "roles" / "defaults"
# Display-only labels for registered capabilities; an id absent here is shown
# as-is and never described as available.
CAPABILITY_LABELS = {
    "memory": ("长期记忆", "角色事实与关系的本地存储"),
    "office": ("办公文件", "Word/Excel/PPT/PDF 的读取与生成"),
    "office-render": ("办公文件渲染", "LibreOffice 转 PDF 与公式重算"),
    "ocr": ("OCR / 截屏翻译", "屏幕文字识别，供操作核验与翻译"),
    "desktop": ("桌面控制", "窗口观察与经授权的点击输入"),
    "browser": ("网页咨询", "内置浏览器中的咨询页面"),
    "voice": ("语音朗读", "本地语音合成"),
    "asr": ("语音识别", "本地语音转文字"),
    "camera": ("摄像头感知", "经授权的摄像头画面读取"),
    "microphone": ("麦克风采集", "经授权的本地录音"),
    "schedule": ("定时任务", "一次性与周期性提醒/执行"),
}
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
                 ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
                 ".vrm": "model/gltf-binary", ".glb": "model/gltf-binary"}


class Bridge:
    def __init__(self, settings_path=None, *, capability_database=None, workbench_root=None,
                 schedule_directory=None, shell_url=None):
        self.settings_path = Path(settings_path) if settings_path else default_path()
        self.capability_database = Path(capability_database) if capability_database else None
        self.workbench = WorkbenchController(workbench_root or Path(__file__).resolve().parents[1],
                                             shell_url=shell_url)
        self.schedule = ScheduleController(schedule_directory)
        self.capability_bootstrap()

    def capability_bootstrap(self):
        """Register the capabilities this machine can serve.

        The registry is the single source of truth for the extension switches, so
        a missing entry means that device/desktop operation refuses to run. Seeding
        is additive: a capability that is not registered yet is added, while an
        existing entry keeps whatever the user configured (chosen provider,
        options, enabled state). Nothing is ever removed or overwritten here.
        """
        if not self.capability_database:
            return {"seeded": False}
        try:
            entries = service_capabilities(self.workbench.root)
        except (OSError, ValueError):
            return {"seeded": False}
        store = CapabilityStore(str(self.capability_database))
        try:
            known = {item["id"] for item in store.list()}
            added = []
            for entry in entries:
                if entry["id"] in known:
                    continue
                store.configure(entry["id"], entry["provider"],
                                enabled=entry["enabled"], options=entry.get("options"))
                added.append(entry["id"])
            return {"seeded": bool(added), "capabilities": added}
        finally:
            store.close()

    def settings(self):
        path = self.settings_path
        if not path.exists():
            return {"configured": False, "path": str(path)}
        value = load_settings(path)
        return {"configured": True, "path": str(path), **value,
                "language_policy_preview": self._policy_preview(value)}

    def _policy_preview(self, settings):
        card_policy = ""
        role_dir = Path(settings["role"]["role_dir"])
        card = role_dir / "card" / "original-card.json"
        if card.is_file():
            try:
                card_policy = compile_card(card).get("card_language_policy", "")
            except (OSError, ValueError, KeyError):
                card_policy = ""
        text, source = resolve_language_policy(
            settings["language"]["target"], user_policy=settings["language"]["policy"],
            card_policy=card_policy, allow_card_policy=settings["language"]["allow_card_policy"])
        return {"source": source, "text": text}

    def save_settings(self, payload):
        saved = save_settings(payload, self.settings_path)
        return {"saved": str(saved), "language_policy_preview": self._policy_preview(payload),
                "startup": self.apply_startup(payload)}

    def apply_startup(self, settings):
        """Make the registry match the user's choice and report what changed."""
        wanted = bool((settings.get("startup") or {}).get("auto_start"))
        result = startup_registry.apply(wanted, Path(__file__).resolve().parents[1])
        return {**startup_registry.read(), "requested": wanted, "applied": result.get("applied", False)}

    def startup_state(self):
        settings = self.settings()
        stored = bool((settings.get("startup") or {}).get("auto_start")) if settings.get("configured") else False
        return {**startup_registry.read(), "requested": stored,
                "tray": bool((settings.get("startup") or {}).get("tray", True))}

    def tree(self):
        """Project ▸ task tree from the project's own continuity records (read-only)."""
        docs = Path(__file__).resolve().parents[1] / "docs" / "project"
        plan_path, progress_path = docs / "plan.json", docs / "progress.json"
        if not plan_path.is_file():
            return {"projects": [], "error": "plan.json missing"}
        plan = json.loads(plan_path.read_text(encoding="utf8"))
        progress = json.loads(progress_path.read_text(encoding="utf8")) if progress_path.is_file() else {}
        nodes = []
        for phase in plan.get("phases", []):
            tasks = [{"id": t.get("id"), "name": t.get("name") or t.get("implemented", "")[:40],
                      "status": t.get("status")} for t in phase.get("tasks", [])]
            nodes.append({"id": phase.get("id"), "name": phase.get("name"),
                          "status": phase.get("status"), "tasks": tasks})
        return {"project": {"name": plan.get("goal", "sumika-next"),
                            "path": str(Path(__file__).resolve().parents[1])},
                "phases": nodes,
                "current_task": (progress.get("local_model_evaluation") or {}).get("current_task"),
                "next_action": progress.get("next_action")}

    def modules(self):
        if not self.capability_database or not Path(self.capability_database).exists():
            return []
        store = CapabilityStore(str(self.capability_database))
        try:
            result = []
            for item in store.list():
                label, purpose = CAPABILITY_LABELS.get(item["id"], (item["id"], ""))
                result.append({**item, "label": label, "purpose": purpose})
            return result
        finally:
            store.close()

    def voice_devices(self):
        """Input devices plus the current selection, so the UI can offer choices."""
        settings = self.settings()
        selected = None
        if settings.get("configured"):
            selected = (settings.get("voice") or {}).get("input_device")
        return {**list_input_devices(), "selected": selected}

    def toggle_module(self, capability_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if not self.capability_database or not Path(self.capability_database).exists():
            raise ValueError("capability registry not configured")
        store = CapabilityStore(str(self.capability_database))
        try:
            current = {item["id"]: item for item in store.list()}
            if capability_id not in current:
                raise ValueError("unknown capability")
            item = current[capability_id]
            store.configure(capability_id, item["provider"], enabled=enabled, options=item["options"])
            return {"id": capability_id, "enabled": enabled, "provider": item["provider"]}
        finally:
            store.close()

    def _role_paths(self):
        settings = self.settings()
        if not settings.get("configured"):
            return {}
        role_dir = Path(settings["role"]["role_dir"])
        return {item["id"]: item["path"] for item in
                list_roles(BUILTIN_ROLES, role_dir.parent)}

    def roles(self):
        result = []
        for role_id, path in self._role_paths().items():
            try:
                role = load_role(path)
            except (OSError, ValueError, KeyError):
                continue
            result.append({"id": role_id, "name": role["name"], "enabled": role["enabled"],
                           "assets": sorted(role["assets"]), "verified": role["verified"]["status"],
                           "has_model_3d": "model_3d" in role["assets"],
                           "has_thumbnail": "thumbnail" in role["assets"]})
        return result

    def select_role(self, role_id):
        """Point the active role session at this role so switching is real."""
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError("role id required")
        paths = self._role_paths()
        if role_id not in paths:
            raise ValueError("unknown role")
        settings = load_settings(self.settings_path)
        settings["role"]["role_dir"] = paths[role_id]
        saved = save_settings(settings, self.settings_path)
        return {"selected": role_id, "role_dir": settings["role"]["role_dir"], "saved": str(saved)}

    def active_role(self):
        settings = self.settings()
        if not settings.get("configured"):
            return {"id": None}
        role_dir = Path(settings["role"]["role_dir"]).resolve()
        for role_id, path in self._role_paths().items():
            if Path(path).resolve() == role_dir:
                return {"id": role_id}
        return {"id": None, "role_dir": str(role_dir)}

    def role_asset(self, role_id, kind):
        path = self._role_paths().get(role_id)
        if path is None:
            raise KeyError("unknown role")
        role = load_role(path)
        asset = role["assets"].get(kind)
        if not asset:
            raise KeyError("role has no such asset")
        return Path(asset)

    def state(self):
        settings = self.settings()
        if not settings.get("configured"):
            return validate_state(snapshot(session={"status": "unknown"},
                                           modules=self.modules()))
        chat = RoleChat(settings)
        return validate_state(snapshot(
            session={"status": "pending" if settings["enabled"] else "unknown",
                     "model": settings["model"], "provider": settings["provider"]},
            role={"enabled": settings["enabled"], "model": settings["model"],
                  "language_policy_source": settings["language_policy_preview"]["source"]},
            memory={"provider": settings["role"]["memory_provider"]},
            modules=self.modules()))

    def chat(self, message, session_id="ui-role-chat"):
        settings = load_settings(self.settings_path)
        result = RoleChat(settings).reply(message, session_id=session_id)
        if "usage" not in result:
            return result
        return {key: value for key, value in result.items() if key != "usage"} | {
            "usage": result.get("usage", {}),
            "usage_status": result.get("usage_status", "unknown")}

    # ---- long-term memory ------------------------------------------------------
    def _with_session(self, handler):
        settings = load_settings(self.settings_path)
        session = open_session(settings)
        try:
            return handler(session, settings)
        finally:
            session.close()

    def memory(self, query=None, *, limit=8):
        def run(session, settings):
            provider = settings["role"]["memory_provider"]
            if query:
                results = session.request("search", {"query": query, "limit": limit})
                return {"provider": provider, "query": query, "results": results,
                        "relations": session.request("relations_all", {"limit": 50}),
                        "sources": session.request("sources", {})}
            return {"provider": provider, "query": None, "results": [],
                    "relations": session.request("relations_all", {"limit": 50}),
                    "sources": session.request("sources", {})}
        return self._with_session(run)

    def forget(self, memory_id):
        if type(memory_id) is not int or memory_id < 1:
            raise ValueError("invalid memory id")
        return self._with_session(lambda session, settings: session.request("forget", {"id": memory_id}))

    def reset_memory(self):
        return self._with_session(lambda session, settings: session.request("reset_to_card", {}))


def _handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SumikaUI/1"

        def log_message(self, *args):
            pass

        def _cors(self):
            """Allow reads from other loopback pages only.

            DSH renders the workbench on its own port, so its panels need to call
            this bridge. Echoing the origin only for http://127.0.0.1[:port] and
            http://localhost[:port] keeps every non-local site blocked while the
            bridge stays loopback-only.
            """
            origin = self.headers.get("Origin")
            if not origin:
                return
            if re.fullmatch(r"http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?", origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid body size")
            return json.loads(self.rfile.read(length).decode("utf8"))

        def _static(self, path):
            relative = "app/index.html" if path in ("", "/") else unquote(path).lstrip("/")
            target = (UI_ROOT / relative).resolve()
            if UI_ROOT not in target.parents and target != UI_ROOT:
                return self._json(403, {"error": "path outside ui root"})
            if not target.is_file():
                return self._json(404, {"error": "not found"})
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _asset(self, role_id, kind):
            try:
                target = bridge.role_asset(role_id, kind)
            except (KeyError, OSError, ValueError) as error:
                return self._json(404, {"error": str(error)})
            if not target.is_file():
                return self._json(404, {"error": "asset missing"})
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/state":
                    return self._json(200, bridge.state())
                if path == "/api/settings/role-model":
                    return self._json(200, bridge.settings())
                if path == "/api/modules":
                    return self._json(200, {"modules": bridge.modules()})
                if path == "/api/roles":
                    return self._json(200, {"roles": bridge.roles(), "active": bridge.active_role()})
                if path == "/api/workbench":
                    return self._json(200, bridge.workbench.status())
                if path == "/api/memory":
                    parameters = parse_qs(urlparse(self.path).query)
                    query = (parameters.get("q") or [None])[0]
                    limit = int((parameters.get("limit") or ["8"])[0])
                    if not 1 <= limit <= 50:
                        raise ValueError("invalid limit")
                    return self._json(200, bridge.memory(query, limit=limit))
                if path == "/api/schedule":
                    return self._json(200, bridge.schedule.state())
                if path == "/api/readiness":
                    return self._json(200, {"capabilities": readiness_probes(
                        Path(__file__).resolve().parents[1])})
                if path == "/api/voice/devices":
                    return self._json(200, bridge.voice_devices())
                if path == "/api/startup":
                    return self._json(200, bridge.startup_state())
                if path == "/api/tree":
                    return self._json(200, bridge.tree())
                if path == "/api/workbench/embed":
                    return self._json(200, bridge.workbench.embed_url())
                if path.startswith("/api/roles/"):
                    parts = path.split("/")
                    if len(parts) == 6 and parts[1] == "api" and parts[2] == "roles" and parts[4] == "asset":
                        return self._asset(unquote(parts[3]), unquote(parts[5]))
            except (ValueError, OSError, KeyError) as error:
                return self._json(400, {"error": str(error)})
            except WorkbenchError as error:
                return self._json(502, {"status": "unknown", "message": str(error)})
            if path.startswith("/api/"):
                return self._json(404, {"error": "unknown endpoint"})
            return self._static(path)

        def do_PUT(self):
            if urlparse(self.path).path != "/api/settings/role-model":
                return self._json(404, {"error": "unknown endpoint"})
            try:
                return self._json(200, bridge.save_settings(self._body()))
            except (ValueError, OSError, KeyError) as error:
                return self._json(400, {"error": str(error)})

        def do_OPTIONS(self):
            """CORS preflight for JSON POSTs from the workbench page."""
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            route = urlparse(self.path).path
            if route in ("/api/workbench/start", "/api/workbench/stop"):
                try:
                    if route.endswith("/stop"):
                        return self._json(200, bridge.workbench.stop())
                    payload = self._body()
                    workspace = payload.get("workspace") if isinstance(payload, dict) else None
                    port = payload.get("port", 0) if isinstance(payload, dict) else 0
                    return self._json(200, bridge.workbench.start(workspace, port=port))
                except WorkbenchError as error:
                    return self._json(502, {"status": "unknown", "message": str(error)})
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/workbench/session":
                try:
                    payload = self._body()
                    workspace = payload.get("workspace") if isinstance(payload, dict) else None
                    return self._json(200, bridge.workbench.create_session(workspace))
                except WorkbenchError as error:
                    return self._json(502, {"status": "unknown", "message": str(error)})
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/memory/forget":
                try:
                    payload = self._body()
                    return self._json(200, bridge.forget(payload.get("id")))
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/memory/reset":
                try:
                    self._body()
                    return self._json(200, bridge.reset_memory())
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/roles/select":
                try:
                    payload = self._body()
                    return self._json(200, bridge.select_role(payload.get("id")))
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route in ("/api/schedule/toggle", "/api/schedule/remove", "/api/schedule/acknowledge"):
                try:
                    payload = self._body()
                    if route.endswith("/toggle"):
                        return self._json(200, bridge.schedule.toggle(payload.get("id"), payload.get("enabled")))
                    if route.endswith("/remove"):
                        return self._json(200, bridge.schedule.remove(payload.get("id")))
                    return self._json(200, bridge.schedule.acknowledge(payload.get("key")))
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/capabilities/toggle":
                try:
                    payload = self._body()
                    return self._json(200, bridge.toggle_module(payload.get("id"), payload.get("enabled")))
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route != "/api/role/chat":
                return self._json(404, {"error": "unknown endpoint"})
            try:
                payload = self._body()
                message = payload.get("message")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("message required")
                session_id = payload.get("session") or "ui-role-chat"
                if not isinstance(session_id, str) or not session_id.strip():
                    raise ValueError("invalid session")
                return self._json(200, bridge.chat(message, session_id=session_id))
            except (CloudError, OllamaError) as error:
                return self._json(502, {"status": "unknown", "kind": getattr(error, "kind", "unknown"),
                                        "message": str(error), "fallback_used": False})
            except (ValueError, OSError, KeyError) as error:
                return self._json(400, {"error": str(error)})

    return Handler


def serve(settings_path=None, *, host="127.0.0.1", port=8765, capability_database=None,
          workbench_root=None, schedule_directory=None):
    if host != "127.0.0.1":
        raise ValueError("UI bridge must bind loopback")
    bridge = Bridge(settings_path, capability_database=capability_database,
                    workbench_root=workbench_root, schedule_directory=schedule_directory,
                    shell_url=f"http://{host}:{port}/")
    httpd = ThreadingHTTPServer((host, port), _handler(bridge))
    return httpd


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=default_path())
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("--schedules", type=Path)
    args = parser.parse_args()
    httpd = serve(args.settings, port=args.port, capability_database=args.capabilities,
                  schedule_directory=args.schedules)
    print(json.dumps({"listening": f"http://127.0.0.1:{args.port}/", "settings": str(args.settings)},
                     ensure_ascii=False), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
