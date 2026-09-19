"""Loopback UI bridge: serve the D-direction UI and expose real Sumika state.

Only 127.0.0.1 binding is allowed. Endpoints return projections or validated
settings; credentials are never returned, and a disabled role model performs no
request at all.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from extensions.capabilities import CapabilityStore
from extensions.desktop.audio_devices import list_input_devices
from extensions.models.cloud import CloudError
from extensions.models.ollama import OllamaError
from extensions.models.settings import default_path, load as load_settings, save as save_settings, example
from extensions.roles.card_context import compile_card, resolve_language_policy
from extensions.roles.chat import RoleChat, open_session
from extensions.roles.conversations import Conversations
from extensions.roles.speech_input import SpeechInput
from extensions.roles.speech_playback import SpeechPlayback
from extensions.roles.roles import (attach_asset, import_card, list_roles, load_role,
                                    remove_role, rename_role)
from ui.state_snapshot import snapshot, validate_state
from ui import startup as startup_registry
from ui.readiness import probes as readiness_probes, service_capabilities
from ui.schedule import ScheduleController
from ui.workbench import WorkbenchController, WorkbenchError
from ui.management import Management, Conflict

UI_ROOT = Path(__file__).resolve().parent
BUILTIN_ROLES = UI_ROOT.parent / "extensions" / "roles" / "defaults"
# Roles the user imported live outside the source tree; the built-in store stays
# pristine so "user-imported" really means user-imported.
def user_role_store():
    """Where imported roles live: beside the rest of this install's runtime data."""
    override = os.environ.get("SUMIKA_ROLE_STORE")
    if override:
        return Path(override)
    return default_path().parent / "roles"
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
                 schedule_directory=None):
        self.settings_path = Path(settings_path) if settings_path else default_path()
        if not self.settings_path.exists():
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            initial = example(BUILTIN_ROLES / 'sampleA', self.settings_path.parent / 'memory.sqlite3')
            # First launch never enables generation or downloads a model.
            try:
                with self.settings_path.open('x', encoding='utf8') as output:
                    json.dump(initial, output, ensure_ascii=False, indent=2)
            except FileExistsError:
                pass  # Another launcher initialized it; never overwrite.
        self.capability_database = Path(capability_database) if capability_database else None
        self.workbench = WorkbenchController(workbench_root or Path(__file__).resolve().parents[1],
                                             )
        self.schedule = ScheduleController(schedule_directory)
        self.capability_bootstrap()
        self.management = Management(self)
        self.conversations = Conversations(self.settings_path.parent / 'role-conversations.sqlite3')
        self._chat_lock = threading.RLock()
        self._shutdown_requested = threading.Event()
        self._closing = False
        self.speech = SpeechInput(self.settings_path.parent/'speech-input', self.speech_configuration)
        self.playback = SpeechPlayback(self.settings_path.parent/'speech-output', self.playback_configuration)

    def playback_configuration(self, role_id):
        from extensions.desktop.audio_devices import env_python
        settings = load_settings(self.settings_path)
        if load_role(settings['role']['role_dir'])['id'] != role_id:
            raise ValueError('active role changed')
        if not settings['voice']['enabled'] or not self.capability_database:
            raise PermissionError('enable voice in capability settings')
        store = CapabilityStore(self.capability_database)
        try:
            selected = store.resolve('voice')
            if selected['provider'] != 'windows-sapi':
                raise PermissionError('selected voice provider is not connected')
        finally:
            store.close()
        interpreter = env_python()
        if not interpreter:
            raise ValueError('local voice runtime unavailable')
        return dict(python=interpreter, root=str(self.workbench.root),
                    voice_name=settings['voice']['tts_voice'], voice_capability=selected,
                    capabilities=str(self.capability_database.resolve()))

    def speech_configuration(self, role_id):
        from extensions.desktop.audio_devices import env_python
        settings = load_settings(self.settings_path)
        voice = settings['voice']
        if load_role(settings['role']['role_dir'])['id'] != role_id:
            raise ValueError('active role changed')
        if not voice['enabled'] or type(voice['input_device']) is not int:
            raise PermissionError('enable voice and choose a microphone in capability settings')
        if not self.capability_database:
            raise PermissionError('speech capabilities not configured')
        store = CapabilityStore(self.capability_database)
        try:
            microphone, asr = store.resolve('microphone'), store.resolve('asr')
            if (microphone['provider'] != 'sounddevice' or microphone['options'].get('user_authorized') is not True
                    or asr['provider'] != 'vosk'):
                raise PermissionError('microphone authorization and local recognition must be enabled')
        finally:
            store.close()
        interpreter = env_python()
        model = Path(voice['asr_model'])
        if not model.is_absolute():
            model = self.workbench.root/model
        if not interpreter or not model.is_dir():
            raise ValueError('local speech runtime or recognition model unavailable')
        return dict(python=interpreter, root=str(self.workbench.root), device=voice['input_device'],
                    sample_rate=voice['sample_rate'], model=str(model.resolve()),
                    capabilities=str(self.capability_database.resolve()), microphone=microphone, asr=asr)

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
            known = {item["id"] for item in store.list()} | store.removed()
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
        before = load_settings(self.settings_path)
        saved = save_settings(payload, self.settings_path)
        if before['voice'] != payload['voice'] or before['role']['role_dir'] != payload['role']['role_dir']:
            self.stop_speech()
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
            if capability_id in ('voice', 'asr', 'microphone'):
                self.stop_speech()
            return {"id": capability_id, "enabled": enabled, "provider": item["provider"]}
        finally:
            store.close()

    def _role_paths(self):
        settings = self.settings()
        if not settings.get("configured"):
            return {}
        role_dir = Path(settings["role"]["role_dir"])
        # Built-in roles ship with the client; imported ones stay in the runtime
        # store. A user role with the same id as a built-in wins, which is what an
        # explicit import means.
        paths={item["id"]: item["path"] for item in
                list_roles(BUILTIN_ROLES, user_role_store())}
        for moved in self.conversations.relocated_locations(settings['role']['user_id'],settings['role']['project_id']):
            selected=load_role(moved)
            if selected['verified']['status']=='ok':paths[selected['id']]=moved
        return paths

    def _role_kinds(self):
        kinds={item["id"]: item["kind"] for item in list_roles(BUILTIN_ROLES, user_role_store())}
        settings=self.settings()
        if settings.get('configured'):
            for moved in self.conversations.relocated_locations(settings['role']['user_id'],settings['role']['project_id']):
                selected=load_role(moved)
                if selected['verified']['status']=='ok':kinds[selected['id']]='user'
        return kinds

    def roles(self):
        result = []
        for role_id, path in self._role_paths().items():
            try:
                role = load_role(path)
            except (OSError, ValueError, KeyError):
                continue
            # A roster entry is a whole character: a name, its card and its model.
            # The name is the one the card carries; an incomplete role is still
            # reported, with what it lacks, instead of silently disappearing.
            missing = [kind for kind in ("card", "model_3d") if kind not in role["assets"]]
            result.append({"id": role_id, "name": role["name"], "enabled": role["enabled"],
                           "assets": sorted(role["assets"]), "verified": role["verified"]["status"],
                           "has_model_3d": "model_3d" in role["assets"],
                           "has_thumbnail": "thumbnail" in role["assets"],
                           "model_3d_url": f"/api/roles/{role_id}/asset/model_3d"
                           if "model_3d" in role["assets"] else None,
                           "kind": self._role_kinds().get(role_id, "builtin"),
                           "complete": not missing, "missing": missing})
        return result

    def import_role(self, payload):
        """Import a user role: card text from the browser, model from a local path.

        The card is small enough to travel as JSON text. A model is not, so the
        caller passes the path of a file that is already on this machine; copying
        it through the browser would only add a needless 16 MB round trip.
        """
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        role_id = payload.get("id")
        card_text = payload.get("card")
        model_path = payload.get("modelPath")
        display_name = payload.get("name")
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError("role id required")
        if not isinstance(card_text, str) or not card_text.strip():
            raise ValueError("character card required")
        if len(card_text) > 4_000_000:
            raise ValueError("card too large")
        if display_name is not None and (not isinstance(display_name, str)
                                        or not display_name.strip()):
            raise ValueError("invalid display name")
        if isinstance(display_name, str) and len(display_name.strip()) > 60:
            raise ValueError("display name too long")
        store = user_role_store()
        store.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="sumika-import-") as directory:
            card = Path(directory) / "card.json"
            card.write_text(card_text, encoding="utf8")
            path = import_card(card, store, role_id.strip())
        if isinstance(display_name, str):
            # The card already carries a name; this only replaces the label shown
            # in the client when the user prefers their own wording.
            rename_role(role_id.strip(), store, display_name)
        attached = None
        if isinstance(model_path, str) and model_path.strip():
            attached = attach_asset(role_id.strip(), store, "model_3d", model_path.strip())
        return {"id": role_id.strip(), "path": str(path),
                "model_3d": str(attached) if attached else None}

    def remove_role(self, role_id):
        """Undo an import: only roles in the user store can be removed here."""
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError("role id required")
        return str(remove_role(role_id.strip(), user_role_store()))

    def attach_role_asset(self, payload):
        """Give an existing role an asset it is missing, typically its model.

        Only user roles can be edited: a built-in role is part of the client and
        adding a model to it would be a silent fork of what ships.
        """
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        role_id = payload.get("id")
        kind = payload.get("kind")
        source = payload.get("path")
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError("role id required")
        if kind not in ("model_3d", "model_2d", "voice", "scene", "thumbnail"):
            raise ValueError("unsupported asset kind for this action")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("local file path required")
        if self._role_kinds().get(role_id.strip()) != "user":
            raise ValueError("only imported roles can be completed here")
        target = attach_asset(role_id.strip(), user_role_store(), kind, source.strip())
        return {"id": role_id.strip(), "kind": kind, "path": str(target)}

    def select_role(self, role_id):
        """Point the active role session at this role so switching is real."""
        if not isinstance(role_id, str) or not role_id.strip():
            raise ValueError("role id required")
        paths = self._role_paths()
        if role_id not in paths:
            raise ValueError("unknown role")
        settings = load_settings(self.settings_path)
        if settings['role']['role_dir'] != paths[role_id]:
            self.stop_speech()
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

    def chat(self, message, session_id="ui-role-chat", role_id=None):
        with self._chat_lock:
            if self._closing or self._shutdown_requested.is_set():
                raise ValueError('bridge is shutting down; message was not sent')
            settings = load_settings(self.settings_path)
            if role_id is not None and load_role(settings['role']['role_dir'])['id'] != role_id:
                raise ValueError('active role changed; message was not sent')
            scope = self._chat_scope(settings)
            chat = self._role_chat(settings)
            chat.histories[session_id] = self.conversations.context(scope, session_id, chat.history_limit)
            turn_id = self.conversations.begin(scope, session_id, message)
            result = chat.reply(message, session_id=session_id, task_intent=True, source_message_id=turn_id + ':user')
            self.conversations.complete(turn_id, result)
            result['source_message_id'] = turn_id + ':user'
        if "usage" not in result:
            return result
        return {key: value for key, value in result.items() if key != "usage"} | {
            "usage": result.get("usage", {}),
            "usage_status": result.get("usage_status", "unknown")}

    def stop_speech(self, *, closing=False):
        failures = []
        for service in (self.speech, self.playback):
            try:
                service.close() if closing else service.cancel_active()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                failures.append(error)
        if failures:
            raise WorkbenchError('speech stop outcome unknown; operation not confirmed') from failures[0]

    def shutdown(self):
        # Fence new admissions before waiting for the current writer. A failed
        # stop remains fenced: only reads and explicit shutdown retry are safe.
        self._shutdown_requested.set()
        self.stop_speech(closing=True)
        with self._chat_lock:
            if self._closing:
                return
            self.workbench.stop()
            self._closing = True

    def _role_chat(self, settings):
        """One live RoleChat per settings revision.

        A fresh instance per request would drop the conversation history the model
        needs, so the bridge keeps it and rebuilds only when the settings change.
        """
        try:
            stat = self.settings_path.stat()
            revision = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            revision = None
        if getattr(self, "_role_chat_cache", None) is None or self._role_chat_revision != revision:
            self._role_chat_cache = RoleChat(settings)
            self._role_chat_revision = revision
        return self._role_chat_cache

    def _chat_scope(self, settings):
        from extensions.roles.relocation import require_settled
        require_settled(self.settings_path)
        role = settings['role']
        return self.conversations.scope_for(role['user_id'], str(Path(role['role_dir']).resolve()), role['project_id'])

    def transcript(self, session_id):
        return self.conversations.messages(self._chat_scope(load_settings(self.settings_path)), session_id)

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
            """Only the bridge origin may read private data and request tokens."""
            origin = self.headers.get("Origin")
            if not origin:
                return
            if origin in bridge.management.allowed_origins(self):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sumika-CSRF")

        def _authorize(self, write=False):
            try:
                bridge.management.authorize(self, write=write)
                return True
            except PermissionError as error:
                self._json(403, {'error': str(error)})
                return False

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
            self._cors()
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
            if not self._authorize():
                return
            if path.startswith('/api/manage/'):
                return self._manage('GET')
            try:
                if path == "/api/instance":
                    from sumika_next.runtime_ownership import process_identity
                    return self._json(200, {"kind": "sumika-ui-bridge", "pid": os.getpid(),
                        "creation": process_identity(os.getpid()),
                        "root": str(UI_ROOT.parent.resolve()),
                        "settings": str(bridge.settings_path.resolve())})
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
                if path == '/api/voice/input':
                    identifier = (parse_qs(urlparse(self.path).query).get('id') or [''])[0]
                    return self._json(200, bridge.speech.status(identifier))
                if path == '/api/voice/output':
                    identifier = (parse_qs(urlparse(self.path).query).get('id') or [''])[0]
                    return self._json(200, bridge.playback.status(identifier))
                if path == "/api/startup":
                    return self._json(200, bridge.startup_state())
                if path == "/api/tree":
                    return self._json(200, bridge.tree())
                if path == "/api/workbench/embed":
                    return self._json(200, bridge.workbench.embed_url())
                if path == "/api/role/chat/history":
                    query = parse_qs(urlparse(self.path).query)
                    session = (query.get("session") or ["ui-role-chat"])[0]
                    if not isinstance(session, str) or not session.strip():
                        raise ValueError("invalid session")
                    settings=load_settings(bridge.settings_path)
                    role_id=(query.get('role_id') or [None])[0]
                    if role_id and load_role(settings['role']['role_dir'])['id'] != role_id:
                        raise ValueError('active role changed')
                    if 'limit' in query:
                        before=(query.get('before') or [None])[0]
                        return self._json(200, {'session':session, 'supports_clear':True, **bridge.conversations.page(
                            bridge._chat_scope(settings),session,int(before) if before else None,int(query['limit'][0]))})
                    return self._json(200, {"session": session,
                                            "messages": bridge.transcript(session)})
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
            if not self._authorize(write=True):
                return
            if bridge._closing or bridge._shutdown_requested.is_set():
                return self._json(503, {'error': 'bridge is shutting down; request was not applied'})
            with bridge._chat_lock:
                if not self._authorize(write=True):
                    return
                if bridge._closing or bridge._shutdown_requested.is_set():
                    return self._json(503, {'error': 'bridge is shutting down; request was not applied'})
                return self._put()

        def _put(self):
            if urlparse(self.path).path != "/api/settings/role-model":
                return self._json(404, {"error": "unknown endpoint"})
            try:
                return self._json(200, bridge.save_settings(self._body()))
            except WorkbenchError as error:
                return self._json(502, {'status':'unknown', 'error':str(error)})
            except (ValueError, OSError, KeyError) as error:
                return self._json(400, {"error": str(error)})

        def do_OPTIONS(self):
            if not self._authorize():
                return
            """CORS preflight for JSON POSTs from the workbench page."""
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if not self._authorize(write=True):
                return
            # Shutdown must announce its fence before acquiring the writer lock.
            # Keep this authenticated route available for an explicit stop retry.
            if urlparse(self.path).path == '/api/lifecycle/shutdown':
                return self._post()
            if bridge._closing or bridge._shutdown_requested.is_set():
                return self._json(503, {'error': 'bridge is shutting down; request was not applied'})
            # Share admission with chat persistence and shutdown. A queued write
            # must recheck closing after obtaining the lock, not before it.
            with bridge._chat_lock:
                if not self._authorize(write=True):
                    return
                if bridge._closing or bridge._shutdown_requested.is_set():
                    return self._json(503, {'error': 'bridge is shutting down; request was not applied'})
                return self._post()

        def _post(self):
            route = urlparse(self.path).path
            if route not in ('/api/manage/role-relocation/resume','/api/manage/role-relocation/rollback','/api/lifecycle/shutdown'):
                from extensions.roles.relocation import require_settled
                try: require_settled(bridge.settings_path)
                except ValueError as error: return self._json(409, {'error':str(error)})
            if route in ('/api/voice/input/start', '/api/voice/input/cancel',
                         '/api/voice/output/start', '/api/voice/output/cancel'):
                try:
                    payload = self._body()
                    service = bridge.playback if '/output/' in route else bridge.speech
                    if route.endswith('/cancel'):
                        result = service.cancel(payload.get('id'))
                    else:
                        extra = {'text': payload.get('text')} if service is bridge.playback else {}
                        result = service.start(payload.get('role_id'), approved=payload.get('approved'), **extra)
                    return self._json(200, result)
                except PermissionError as error:
                    return self._json(403, {'error': str(error)})
                except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/role/chat/clear':
                try:
                    payload=self._body()
                    settings=load_settings(bridge.settings_path)
                    role_id=load_role(settings['role']['role_dir'])['id']
                    if payload.get('role_id') != role_id or payload.get('session') != 'room-'+role_id:
                        raise ValueError('current role and room session required')
                    count=bridge.conversations.clear(bridge._chat_scope(settings),payload['session'])
                    cached=getattr(bridge,'_role_chat_cache',None)
                    if cached: cached.histories.pop(payload['session'],None)
                    return self._json(200, {'cleared':True,'turns':count})
                except (ValueError,OSError,KeyError) as error:
                    return self._json(400, {'error':str(error)})
            if route == '/api/lifecycle/shutdown':
                try:
                    bridge.shutdown()
                except WorkbenchError as error:
                    return self._json(502, {'status':'unknown', 'message':str(error)})
                self._json(200, {'stopping':True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if route.startswith('/api/manage/'):
                return self._manage('POST')
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
                except WorkbenchError as error:
                    return self._json(502, {'status':'unknown', 'error':str(error)})
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/roles/import":
                try:
                    return self._json(200, bridge.import_role(self._body()))
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/roles/remove":
                try:
                    return self._json(200, {"removed": bridge.remove_role(self._body().get("id"))})
                except (ValueError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/roles/attach":
                try:
                    return self._json(200, bridge.attach_role_asset(self._body()))
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
                except WorkbenchError as error:
                    return self._json(502, {'status':'unknown', 'error':str(error)})
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
                return self._json(200, bridge.chat(message, session_id=session_id, role_id=payload.get('role_id')))
            except (CloudError, OllamaError) as error:
                return self._json(502, {"status": "unknown", "kind": getattr(error, "kind", "unknown"),
                                        "message": str(error), "fallback_used": False})
            except (ValueError, OSError, KeyError) as error:
                return self._json(400, {"error": str(error)})

        def _manage(self, method):
            try:
                bridge.management.authorize(self, write=method != 'GET')
                if method == 'GET' and urlparse(self.path).path == '/api/manage/session':
                    return self._json(200, {'csrf': bridge.management.client_token(self)})
                payload = self._body() if method != 'GET' else None
                return self._json(200, bridge.management.dispatch(method, self.path, payload))
            except PermissionError as error:
                return self._json(403, {'error': str(error)})
            except Conflict as error:
                return self._json(409, {'error': str(error)})
            except WorkbenchError as error:
                return self._json(502, {'status':'unknown', 'error':str(error)})
            except (ValueError, OSError, KeyError, TypeError) as error:
                return self._json(400, {'error': str(error)})

    return Handler


def serve(settings_path=None, *, host="127.0.0.1", port=8765, capability_database=None,
          workbench_root=None, schedule_directory=None):
    if host != "127.0.0.1":
        raise ValueError("UI bridge must bind loopback")
    from ui.data_lease import DataLease
    lease = DataLease((Path(settings_path) if settings_path else default_path()).parent).acquire()

    class OwnedServer(ThreadingHTTPServer):
        def server_close(self):
            # Do not release the personal-data lease while admitted writes or an
            # owned workbench remain active. Failed stop retains ownership.
            if hasattr(self, 'sumika_bridge'):
                self.sumika_bridge.shutdown()
            try:
                super().server_close()
            finally:
                lease.release()

    try:
        restore_state = lease.directory/'role-restore-state.json'
        if restore_state.exists():
            state = json.loads(restore_state.read_text(encoding='utf8'))
            if (not isinstance(state, dict) or state.get('schema_version') != 1
                    or state.get('status') != 'complete'
                    or state.get('destination') != str(lease.directory)):
                raise ValueError('personal data recovery is incomplete; explicitly resume before startup')
        bridge = Bridge(settings_path, capability_database=capability_database,
                        workbench_root=workbench_root, schedule_directory=schedule_directory)
        httpd = OwnedServer((host, port), _handler(bridge))
        httpd.sumika_bridge = bridge
        return httpd
    except BaseException:
        lease.release()
        raise


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
