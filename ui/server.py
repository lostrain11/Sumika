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
from collections import deque
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from extensions.capabilities import CapabilityStore
from extensions.desktop.audio_devices import list_input_devices
from extensions.desktop.window_targets import list_window_targets
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
from ui.pet_host import PetHost
from extensions.companion import ObservationBundle, CompanionQuestionService, video, cues
from extensions.companion.perception_process import PerceptionProcess
from extensions.companion.application_audio_process import ApplicationAudioProcess
from extensions.companion.microphone_process import MicrophoneProcess
from extensions.companion.context_fusion import ContextFusion
from extensions.companion.passive_browser import PassiveBrowserConnection

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
        from extensions.companion.session_coordinator import StudySessionCoordinator
        self._coordinator = StudySessionCoordinator(
            chat=self._companion_chat,
            current=lambda: self._fusion_snapshot(),
            include_images=lambda: load_settings(self.settings_path)['multimodal']['enabled'],
            on_event=self._coordinator_event)
        self._companion = self._coordinator.service
        self._context_lock = threading.RLock()
        self._fusion = ContextFusion()
        self._voice_events_lock = threading.Lock()
        self._voice_events = deque(maxlen=64)
        self._voice_event_sequence = 0
        self._application_audio = ApplicationAudioProcess(root=UI_ROOT.parent,
            on_observation=self._companion_audio_observe, on_clear=self._companion_audio_clear)
        self._microphone = MicrophoneProcess(root=UI_ROOT.parent,
            on_event=self._companion_microphone_event)
        self._perception = PerceptionProcess(root=UI_ROOT.parent,
            on_observation=lambda payload: self.companion_observe(payload, continuous=True),
            on_clear=self._companion_clear)
        self._passive_browser = PassiveBrowserConnection(
            self._companion_passive_publish,
            self._companion_clear)
        from extensions.companion.passive_browser_audio import PassiveBrowserAudio
        self._browser_audio = PassiveBrowserAudio(root=UI_ROOT.parent,
            on_observation=self._companion_audio_observe, on_clear=self._companion_audio_clear)
        self._shutdown_requested = threading.Event()
        self._pet_host = PetHost(UI_ROOT.parent)
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
                    or asr['provider'] not in ('vosk', 'sherpa-onnx-sensevoice')):
                raise PermissionError('microphone authorization and local recognition must be enabled')
            if asr['provider'] == 'sherpa-onnx-sensevoice' and voice['sample_rate'] != 16000:
                raise ValueError('SenseVoice speech input requires 16kHz')
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
            entries = service_capabilities(self.workbench.root,
                asr_model=load_settings(self.settings_path)['voice']['asr_model'])
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

    def chat(self, message, session_id="ui-role-chat", role_id=None, images=None):
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
            result = chat.reply(message, session_id=session_id, images=images,
                                task_intent=True, source_message_id=turn_id + ':user')
            self.conversations.complete(turn_id, result)
            result['source_message_id'] = turn_id + ':user'
        if "usage" not in result:
            return result
        return {key: value for key, value in result.items() if key != "usage"} | {
            "usage": result.get("usage", {}),
            "usage_status": result.get("usage_status", "unknown")}

    def _companion_chat(self, message, *, session_id, images=None, on_delta=None):
        # Screen context is short-lived reference data, not a personal-memory source.
        with self._chat_lock:
            if self._closing or self._shutdown_requested.is_set():
                raise ValueError('bridge is shutting down; message was not sent')
            chat = RoleChat(load_settings(self.settings_path))
            stream = {'on_delta': on_delta} if on_delta is not None else {}
            return chat.reply(message, session_id=session_id, images=images,
                              task_intent=False, memory_writes=False, **stream)

    def companion_observe(self, payload, *, collection_token=None, continuous=False):
        if not isinstance(payload, dict):
            raise ValueError('observation object required')
        observed_at = payload.get('observed_at')
        if observed_at is None:
            observed_at = datetime.now(timezone.utc)
        elif isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            raise ValueError('observed_at must include timezone')
        bundle = ObservationBundle(observed_at=observed_at,
            source=payload.get('source'), target=payload.get('target'),
            valid=payload.get('valid'), text=payload.get('text',''),
            image=payload.get('image'), media_time_seconds=payload.get('media_time_seconds'),
            metadata=payload.get('metadata') or {})
        passive = self._passive_browser.status()
        if passive.get('target') is not None and passive['target'] != bundle.target:
            self._passive_browser.stop()
            self._browser_audio.stop()
        media_state = bundle.metadata.get('media_state')
        if media_state is None:
            if bundle.metadata.get('seeking') is True:
                media_state = 'seeking'
            elif bundle.metadata.get('ended') is True:
                media_state = 'ended'
            elif bundle.metadata.get('paused') is True:
                media_state = 'paused'
        if media_state in ('paused', 'seeking', 'ended'):
            audio_owner = self._application_audio.status().get('target')
            if audio_owner is None or audio_owner == bundle.target:
                self.companion_media_state({'target': bundle.target, 'state': media_state})
        audio_status = self._application_audio.status()
        audio_target = audio_status['target']
        if audio_target is not None and (audio_target != bundle.target or not bundle.valid
                or audio_status.get('media_identity') != bundle.metadata.get('media_identity')):
            self._application_audio.stop()
        previous = self._companion.latest
        if not bundle.valid or (previous is not None and previous.target != bundle.target):
            # Fence pending settings/model preflight too, before a process exists.
            self._microphone.stop()
        if not continuous and self._perception.status()['alive']:
            self._perception.stop()
            collection_token = self._companion.collection_token()
        with self._context_lock:
            if collection_token is not None and collection_token != self._companion.collection_token():
                return {'status': 'rejected', 'reason': 'collection was revoked or superseded'}
            result = self._companion_publish(self._fusion.visual(bundle), collection_token=collection_token)
            # Keep the isolated voice worker bound to the latest visual context;
            # it rejects target changes and invalid observations fail closed.
            if self._microphone.status()['alive']:
                self._microphone.observe(self._observation_payload(self._fusion.current()))
            return result

    def _companion_microphone_event(self, packet):
        with self._voice_events_lock:
            self._voice_event_sequence += 1
            self._voice_events.append({'sequence':self._voice_event_sequence, **packet})
        self._coordinator_route(packet)

    def _fusion_snapshot(self):
        with self._context_lock:
            return self._fusion.current()

    def _coordinator_event(self, name, detail):
        """Coordinator/UI events share the bounded voice event stream."""
        with self._voice_events_lock:
            self._voice_event_sequence += 1
            self._voice_events.append({'sequence':self._voice_event_sequence,
                                       'event':name, **detail})

    def _coordinator_route(self, packet):
        """Forward voice worker states to the single session owner."""
        from extensions.companion.session_coordinator import CoordinatorStopped
        event = packet.get('event')
        turn = packet.get('turn')
        try:
            if event == 'user_started':
                self._coordinator.voice_user_started(turn)
            elif event == 'answer_request':
                threading.Thread(target=self._voice_answer, args=(packet,),
                    daemon=True, name='sumika-voice-answer').start()
            elif event == 'answer_cancel':
                self._coordinator.voice_request_cancelled(packet.get('request'))
            elif event in ('playback_started', 'proactive_started', 'discuss_started'):
                self._coordinator.voice_event('playback_started', turn)
            elif event in ('playback_ended', 'segment_ended', 'interrupted',
                           'text_interrupted', 'error', 'empty_transcript'):
                self._coordinator.voice_event(event, turn)
                for request in self._coordinator.finish_turn_requests(turn):
                    pass  # released; worker-side playback already stopped
            elif event == 'discuss_rejected':
                self._coordinator_event('proactive_error',
                                        {'error': 'voice worker busy'})
        except CoordinatorStopped:
            pass

    def _voice_answer(self, packet):
        """Run a transcribed voice question on the single owner; stream to the worker."""
        request, turn = packet.get('request'), packet.get('turn')
        def delta(chunk):
            self._microphone.post({'action':'answer_delta', 'request':request,
                                   'text':chunk['text']})
        try:
            result = self._coordinator.voice_request(request=request, turn=turn,
                text=packet.get('text', ''),
                record_history=bool(packet.get('record_history', True)),
                on_delta=delta)
        except Exception as error:
            self._coordinator.voice_request_finished(request)
            try:
                self._microphone.post({'action':'answer_error', 'request':request,
                                       'reason':type(error).__name__})
            except RuntimeError:
                pass
            return
        text = result.get('text')
        if not isinstance(text, str) or not text.strip():
            self._coordinator.voice_request_finished(request)
            try:
                self._microphone.post({'action':'answer_error', 'request':request,
                                       'reason':result.get('status', 'empty')})
            except RuntimeError:
                pass
            return
        try:
            # Live deltas already reached the worker during generation; the
            # worker reconciles the final text against them before playing.
            self._microphone.post({'action':'answer_done', 'request':request, 'text':text})
            self._coordinator.voice_request_delivered(request)
        except RuntimeError:
            self._coordinator.voice_request_finished(request)

    @staticmethod
    def _observation_payload(observation):
        return {'observed_at':observation.observed_at.isoformat(),
            'source':observation.source, 'target':observation.target,
            'valid':observation.valid, 'text':observation.text, 'image':observation.image,
            'media_time_seconds':observation.media_time_seconds,
            'metadata':dict(observation.metadata)}

    def _companion_publish(self, bundle, *, collection_token=None):
        latest = self._companion.latest
        if latest is not None and bundle.observed_at < latest.observed_at:
            bundle = replace(bundle, observed_at=latest.observed_at,
                metadata={**dict(bundle.metadata),
                          'visual_observed_at': bundle.metadata.get('visual_observed_at', bundle.observed_at.isoformat())})
        return self._companion.update(bundle, collection_token=collection_token)

    def _companion_clear(self, *, collection_token=None):
        # Stop outside the context lock: joining pipe readers must not wait on
        # a callback that is itself waiting for that lock.
        if collection_token is None or collection_token == self._companion.collection_token():
            self._microphone.stop()
        self._coordinator.cancel_voice_requests()
        self._stop_worker_playback()
        with self._context_lock:
            if collection_token is not None and collection_token != self._companion.collection_token():
                return self._companion.revoke(collection_token=collection_token)
            self._fusion.clear()
            self._coordinator.context_cleared()
            return self._companion.revoke(collection_token=collection_token)

    def _stop_worker_playback(self):
        """Context died; the worker's spoken answer must stop with it."""
        if self._microphone.status()['alive']:
            try:
                self._microphone.post({'action':'answer_invalidated', 'request':0})
            except RuntimeError:
                pass

    def _companion_audio_clear(self):
        with self._context_lock:
            visual = self._fusion.clear_audio()
            self._coordinator.cancel_voice_requests()
            self._stop_worker_playback()
            self._companion.revoke()
            if visual is not None:
                self._companion.update(visual)
                if self._microphone.status()['alive']:
                    self._microphone.observe(self._observation_payload(visual))

    def _companion_audio_observe(self, payload):
        bundle = ObservationBundle(observed_at=datetime.fromisoformat(payload['observed_at']),
            source=payload['source'], target=payload['target'], valid=payload['valid'],
            text=payload['text'], metadata=payload.get('metadata') or {})
        with self._context_lock:
            combined = self._fusion.audio(bundle)
            if combined is not None:
                self._companion_publish(combined)
                if self._microphone.status()['alive']:
                    self._microphone.observe(self._observation_payload(combined))

    def companion_audio(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('application audio action required')
        action = payload.get('action')
        if action == 'status':
            return self._application_audio.status()
        if action == 'pause':
            return self._application_audio.pause()
        if action == 'stop':
            return self._application_audio.stop()
        if action != 'start':
            raise ValueError('invalid application audio action')
        if payload.get('consent') is not True:
            raise PermissionError('explicit application audio consent required')
        admission_token = self._application_audio.admission_token()
        observation = self._companion.latest
        if observation is None or not observation.valid:
            raise ValueError('select valid visible content before starting application audio')
        pid = payload.get('process_id')
        expected = f":pid:{pid}"
        if observation.source != 'window-visual' or not observation.target.endswith(expected):
            raise ValueError('application audio must match the selected window process')
        if not self.capability_database:
            raise PermissionError('ASR capability not configured')
        store = CapabilityStore(self.capability_database)
        try:
            selected_asr = store.resolve('asr')
            if selected_asr['provider'] not in ('vosk', 'sherpa-onnx-sensevoice'):
                raise PermissionError('selected application ASR provider is not connected')
        finally:
            store.close()
        voice = load_settings(self.settings_path)['voice']
        if not voice['enabled'] or not voice.get('asr_model'):
            raise PermissionError('enable recognition and configure its model')
        model = Path(voice['asr_model'])
        if not model.is_absolute():
            model = self.workbench.root/model
        return self._application_audio.start(process_id=pid,
            media_identity=observation.metadata.get('media_identity'),
            media_time_seconds=observation.media_time_seconds,
            playback_rate=observation.metadata.get('playback_rate', 1.0),
            creation=payload.get('process_creation'), target=observation.target,
            model=model, approved=True, capabilities=self.capability_database, asr=selected_asr,
            admission_token=admission_token)

    def companion_media_state(self, payload):
        """Fence application audio when an owning player pauses or seeks."""
        if not isinstance(payload, dict):
            raise ValueError('media state object required')
        target, state = payload.get('target'), payload.get('state')
        if not isinstance(target, str) or not target.strip() or len(target) > 512:
            raise ValueError('bounded media target required')
        if state not in ('playing', 'paused', 'seeking', 'ended'):
            raise ValueError('invalid media state')
        audio = self._application_audio.status()
        if audio.get('alive') and audio.get('target') != target:
            raise ValueError('media target does not own application audio')
        action = 'none'
        if state in ('paused', 'seeking', 'ended') and audio.get('alive'):
            self._application_audio.pause()
            self._companion_audio_clear()
            action = 'paused_audio'
        return {'state': state, 'target': target, 'action': action,
                'application_audio': self._application_audio.status()}

    def companion_microphone(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('microphone action required')
        action = payload.get('action')
        if action == 'status':
            after = payload.get('after', 0)
            if type(after) is not int or after < 0:
                raise ValueError('nonnegative voice event cursor required')
            status = self._microphone.status()
            capture = self._perception.status()
            application_audio = self._application_audio.status()
            with self._voice_events_lock:
                return {**status, 'capture':capture, 'application_audio':application_audio,
                        'cursor':self._voice_event_sequence,
                        'events':[dict(event) for event in self._voice_events if event['sequence'] > after]}
        if action in ('stop', 'pause'):
            result = self._microphone.stop()
            self._coordinator.detach_speaker()
            with self._voice_events_lock:
                self._voice_events.clear()
            return result
        if action != 'start':
            raise ValueError('invalid microphone action')
        if payload.get('microphone_consent') is not True or payload.get('playback_consent') is not True:
            raise PermissionError('explicit microphone and playback consent required')
        admission_token = self._microphone.admission_token()
        observation = self._companion.latest
        if observation is None or not observation.valid:
            raise ValueError('select valid visible content before starting microphone study')
        if not self.capability_database:
            raise PermissionError('voice capabilities not configured')
        store = CapabilityStore(self.capability_database)
        try:
            selected = {kind: store.resolve(kind) for kind in ('microphone', 'asr', 'voice')}
        finally:
            store.close()
        settings = load_settings(self.settings_path)
        role = load_role(settings['role']['role_dir'])
        voice = settings['voice']
        if not voice['enabled'] or type(voice.get('input_device')) is not int:
            raise PermissionError('enable voice and choose an input device')
        model = Path(voice['asr_model'])
        if not model.is_absolute():
            model = self.workbench.root / model
        config = {'settings_path':str(self.settings_path), 'settings':settings,
            'capabilities':str(self.capability_database), 'selected':selected,
            'role_id':role['id'], 'microphone_consent':True, 'playback_consent':True,
            'root':str(UI_ROOT.parent), 'model':str(model),
            'runtime_directory':str(self.settings_path.parent/'voice-runtime'),
            'proactive':payload.get('proactive', {'enabled':True,'interval_seconds':120}),
            'observation':self._observation_payload(observation)}
        # Avoid admitting a continuous session alongside the one-shot recorder
        # or player. These owners do not manage the companion microphone job.
        self.speech.cancel_active()
        self.playback.cancel_active()
        proactive = payload.get('proactive', {'enabled':True,'interval_seconds':120})
        self._coordinator.reset()
        self._coordinator.set_proactive(enabled=bool(proactive['enabled']),
                                        interval_seconds=proactive['interval_seconds'])
        with self._voice_events_lock:
            self._voice_events.clear()
        result = self._microphone.start(config, admission_token=admission_token)
        self._coordinator.attach_speaker(self._discuss_speaker())
        return result

    def _discuss_speaker(self):
        """Hand generated discussion text to the open voice worker."""
        sequence = [0]
        def speak(text):
            sequence[0] += 1
            self._microphone.post({'action':'discuss', 'request':sequence[0], 'text':text})
        return speak

    def companion_pet(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'action'}:
            raise ValueError('pet action required; custom launch arguments are not supported')
        action = payload['action']
        if action == 'status':
            return self._pet_host.status()
        if action == 'stop':
            return self._pet_host.stop()
        if action == 'start':
            if self._shutdown_requested.is_set():
                raise RuntimeError('bridge is shutting down')
            return self._pet_host.start(self.listen_port)
        raise ValueError('invalid pet action')

    def companion_ask(self, question, *, session_id='companion', on_delta=None, expected_target=None):
        passive = self._passive_browser.status()
        if expected_target is not None:
            state=self._perception.status()
            target=state.get('target')
            window_matches = (state['alive'] and target and
                expected_target == f"window:{target['handle']}:pid:{target['process_id']}")
            passive_matches = passive.get('status') == 'running' and passive.get('target') == expected_target
            if not window_matches and not passive_matches:
                raise ValueError('learning target was stopped or changed')
        with self._microphone.text_question() as token:
            return self._companion_ask_bound(question, session_id=session_id,
                on_delta=on_delta, expected_target=expected_target, cancellation_token=token)

    def _companion_ask_bound(self, question, *, session_id, on_delta, expected_target, cancellation_token):
        with self._context_lock:
            current = self._fusion.current()
            if current is not None:
                self._companion_publish(current)
            binding=self._companion.bind_question()
            if expected_target is not None and binding.observation.target != expected_target:
                raise ValueError('learning observation target changed')
        return self._companion.ask(question, session_id=session_id, on_delta=on_delta,
            binding=binding, cancellation_token=cancellation_token,
            include_images=load_settings(self.settings_path)['multimodal']['enabled'])

    def companion_revoke(self):
        self._passive_browser.stop()
        self._browser_audio.stop()
        self._application_audio.stop()
        self._microphone.stop()
        with self._voice_events_lock:
            self._voice_events.clear()
        self._perception.stop()
        return self._companion_clear()

    def companion_perception(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('perception action object required')
        action = payload.get('action')
        if action == 'start':
            from sumika_next.runtime_ownership import process_identity
            from extensions.desktop.windows_capture import _identity
            pid, handle = payload.get('process_id'), payload.get('handle')
            if type(pid) is not int or pid <= 0 or type(handle) is not int or handle <= 0:
                raise ValueError('positive window handle and process id required')
            if payload.get('consent') is not True:
                raise PermissionError('explicit window capture consent required')
            creation = payload.get('process_creation')
            if creation is not None and process_identity(pid) != creation:
                raise ValueError('selected process identity changed')
            from extensions.companion.windows_learning import WindowsLearningCollector
            expected_document = WindowsLearningCollector.validate_expected_document(payload.get('expected_document'))
            _identity(handle, pid)
            self._passive_browser.stop()
            self._application_audio.stop()
            self._microphone.stop()
            return self._perception.start(handle=payload.get('handle'),
                process_id=payload.get('process_id'), approved=payload.get('consent'),
                expected_document=expected_document)
        if action in ('pause', 'resume', 'stop', 'status'):
            if action in ('pause', 'stop'):
                self._application_audio.stop()
                self._microphone.stop()
            return getattr(self._perception, action)()
        raise ValueError('invalid perception action')

    def companion_collect(self, payload):
        if not isinstance(payload, dict) or payload.get('consent') is not True:
            raise ValueError('explicit window text collection consent required')
        if payload.get('kind') == 'pdf':
            return self._companion_collect_pdf(payload)
        handle, pid = payload.get('handle'), payload.get('process_id')
        kind, selected = payload.get('kind', 'web'), payload.get('selected', False)
        if type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0:
            raise ValueError('positive window handle and process id required')
        if kind not in ('web', 'ebook', 'document') or type(selected) is not bool:
            raise ValueError('invalid content kind or selection mode')
        self._passive_browser.stop()
        collection_token = self._companion.collection_token()
        root = Path(__file__).resolve().parents[1]
        from extensions.desktop.runtime import capability_python
        interpreter = capability_python('desktop', root=root)
        if interpreter is None:
            raise RuntimeError('desktop text collector environment is unavailable')
        command = [str(interpreter), '-X', 'utf8', '-B', '-m', 'extensions.companion.windows_text',
                   '--handle', str(handle), '--process-id', str(pid), '--kind', kind]
        if selected:
            command.append('--selected')
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf8',
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError('window text collection unavailable; check window identity and accessibility')
        return self.companion_observe(json.loads(result.stdout), collection_token=collection_token)

    def _companion_collect_pdf(self, payload):
        """Explicit file/page selection; does not infer a reader's current page."""
        from extensions.desktop.runtime import capability_python
        filename, page = payload.get('pdf_path'), payload.get('page')
        if (not isinstance(filename, str) or not Path(filename).is_absolute()
                or type(page) is not int or page < 1):
            raise ValueError('absolute PDF file and one-based current page required')
        self._passive_browser.stop()
        token = self._companion.collection_token()
        root = Path(__file__).resolve().parents[1]
        # Package uses the standalone desktop runtime. Development fallback reuses
        # the enabled Office skill, which rechecks configuration per invocation.
        launcher = root/'.agents/skills/sumika-office/scripts/run.py'
        try:
            path = Path(filename).resolve(strict=True)
            if not path.is_file() or path.suffix.lower() != '.pdf':
                raise ValueError('PDF file required')
            bundled = root/'runtime/desktop/python.exe'
            explicit = os.environ.get('SUMIKA_DESKTOP_PYTHON')
            if bundled.is_file() or explicit is not None:
                interpreter = capability_python('desktop', root=root)
                if interpreter is None:
                    raise RuntimeError('PDF desktop environment is unavailable')
                command = [str(interpreter), '-X', 'utf8', '-B',
                    str(root/'extensions/companion/pdf_learning.py')]
            else:
                if not launcher.is_file():
                    raise RuntimeError('PDF Office environment is unavailable')
                command = [sys.executable, '-X', 'utf8', '-B', str(launcher),
                    'exec', str(root/'extensions/companion/pdf_learning.py')]
            result = subprocess.run([*command, '--pdf', str(path), '--page', str(page)], cwd=root,
                capture_output=True, text=True, encoding='utf8', timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode:
                raise RuntimeError('PDF page collection failed; check Office capability, file and page')
            return self.companion_observe(json.loads(result.stdout), collection_token=token)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
            self._companion_clear(collection_token=token)
            raise

    def companion_video(self, payload):
        """Accept a bounded subtitle window from a player adapter."""
        if not isinstance(payload, dict) or payload.get('consent') is not True:
            raise ValueError('explicit video subtitle consent required')
        subtitles = payload.get('subtitles')
        if subtitles is None and isinstance(payload.get('webvtt'), str):
            subtitles, _ = cues(payload['webvtt'], at_seconds=payload.get('media_time_seconds'))
        if not isinstance(subtitles, str):
            raise ValueError('subtitle text or current WebVTT cue required')
        target = payload.get('target')
        if not isinstance(target, str) or not target.strip():
            raise ValueError('video target required')
        bundle = video(target=target, subtitles=subtitles[:12000],
                       media_time_seconds=payload.get('media_time_seconds'),
                       title=payload.get('title'), audio_transcript=payload.get('audio_transcript'))
        return self.companion_observe({
            'observed_at': payload.get('observed_at'), 'source': bundle.source,
            'target': bundle.target, 'valid': bundle.valid, 'text': bundle.text,
            'media_time_seconds': bundle.media_time_seconds, 'metadata': bundle.metadata})

    def companion_capture(self, payload):
        if not isinstance(payload, dict) or payload.get('consent') is not True:
            raise ValueError('explicit window visual collection consent required')
        handle, pid = payload.get('handle'), payload.get('process_id')
        if type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0:
            raise ValueError('positive window handle and process id required')
        self._passive_browser.stop()
        token = self._companion.collection_token()
        root = Path(__file__).resolve().parents[1]
        from extensions.desktop.runtime import capability_python
        interpreter = capability_python('desktop', root=root)
        try:
            if interpreter is None:
                raise RuntimeError('desktop capture environment is unavailable')
            result = subprocess.run([str(interpreter), '-X', 'utf8', '-B', '-m',
                'extensions.companion.windows_visual', '--handle', str(handle), '--process-id', str(pid)],
                cwd=root, capture_output=True, text=True, encoding='utf8', timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode:
                raise RuntimeError('window visual collection failed; verify target identity and WGC availability')
            return self.companion_observe(json.loads(result.stdout), collection_token=token)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
            self._companion_clear(collection_token=token)
            raise

    def companion_browser_video(self, payload):
        from extensions.companion.browser_video import collect_browser_video
        from extensions.desktop.browser_skill import BrowserSkillClient
        if not isinstance(payload, dict) or payload.get('consent') is not True:
            raise ValueError('explicit browser video collection consent required')
        site = payload.get('site')
        if not isinstance(site, str) or not site.strip():
            raise ValueError('authorized browser site required')
        self._passive_browser.stop()
        token = self._companion.collection_token()
        client = BrowserSkillClient(registry=self.settings_path.parent/'browser-authorizations.json')
        try:
            capture_frame = payload.get('capture_frame', False)
            if type(capture_frame) is not bool:
                raise ValueError('capture_frame must be boolean')
            bundle = collect_browser_video(client, site, capture_frame=capture_frame)
        except (ValueError, RuntimeError, TypeError, OSError, KeyError, subprocess.SubprocessError):
            self._companion_clear(collection_token=token)
            raise
        return self.companion_observe({'observed_at': bundle.observed_at,
            'source': bundle.source, 'target': bundle.target, 'valid': bundle.valid,
            'text': bundle.text, 'image': bundle.image, 'media_time_seconds': bundle.media_time_seconds,
            'metadata': bundle.metadata}, collection_token=token)

    def _companion_passive_publish(self, bundle):
        # receive holds the grant lock through publication. Grant revocation
        # fences callbacks; content changes advance the question generation,
        # which is distinct from this continuous collection's permission.
        token = self._companion.collection_token()
        return self.companion_observe(self._observation_payload(bundle),
            collection_token=token, continuous=True)

    def companion_passive_browser(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('passive browser action required')
        action = payload.get('action')
        if action == 'pending':
            return {'requests':self._passive_browser.pending_connections()}
        if action == 'approve':
            return self._passive_browser.approve_connection(payload, before_start=self.companion_revoke)
        if action == 'start':
            self._passive_browser.validate_selection(payload)
            self.companion_revoke()
            return self._passive_browser.start(payload)
        if action == 'resume':
            result = self._passive_browser.resume()
            return result
        if action in ('pause', 'stop', 'status'):
            if action in ('pause', 'stop'):
                self._browser_audio.stop()
            return getattr(self._passive_browser, action)()
        raise ValueError('invalid passive browser action')

    def companion_browser_audio(self, payload):
        """Approved browser tab audio into the isolated recognizer (Sumika side)."""
        if not isinstance(payload, dict):
            raise ValueError('browser audio action required')
        action = payload.get('action')
        if action == 'status':
            return self._browser_audio.status()
        if action == 'stop':
            return self._browser_audio.stop()
        if action != 'start':
            raise ValueError('invalid browser audio action')
        grant = self._passive_browser.audio_grant()
        if grant is None:
            raise PermissionError('browser audio consent requires an approved connection')
        observation = self._companion.latest
        if observation is None or not observation.valid:
            raise ValueError('select valid visible content before starting browser audio')
        voice = load_settings(self.settings_path)['voice']
        if not voice['enabled'] or not voice.get('asr_model'):
            raise PermissionError('enable recognition and configure its model')
        model = Path(voice['asr_model'])
        if not model.is_absolute():
            model = self.workbench.root/model
        if not self.capability_database:
            raise PermissionError('ASR capability not configured')
        store = CapabilityStore(self.capability_database)
        try:
            selected_asr = store.resolve('asr')
            if selected_asr['provider'] not in ('vosk', 'sherpa-onnx-sensevoice'):
                raise PermissionError('selected browser audio ASR provider is not connected')
        finally:
            store.close()
        return self._browser_audio.start(target=observation.target,
            identity=observation.metadata.get('media_identity'),
            model=model, capabilities=self.capability_database, asr=selected_asr,
            audio_epoch=grant['audio_epoch'])

    def stop_speech(self, *, closing=False):
        failures = []
        try:
            self._application_audio.stop()
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(error)
        try:
            self._microphone.stop()
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(error)
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
        self._passive_browser.stop()
        self._application_audio.stop()
        self._microphone.stop()
        self._perception.stop()
        self.stop_speech(closing=True)
        with self._chat_lock:
            self._pet_host.stop()
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
            if path == '/api/companion/windows':
                try:
                    return self._json(200, list_window_targets())
                except (OSError, RuntimeError, ValueError) as error:
                    return self._json(400, {'error':str(error)})
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
                        bridge.workbench.root,
                        asr_model=load_settings(bridge.settings_path)['voice']['asr_model'])})
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
            route = urlparse(self.path).path
            if route in ('/api/companion/passive-browser/push',
                         '/api/companion/passive-browser/request',
                         '/api/companion/passive-browser/receipt',
                         '/api/companion/passive-browser/cancel',
                         '/api/companion/passive-browser/audio',
                         '/api/companion/passive-browser/audio-epoch'):
                # Narrow extension ingress: never grants access to management
                # or arbitrary observation APIs. No website CORS is enabled.
                if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                    return self._json(403, {'error':'unexpected client host'})
                if bridge._closing or bridge._shutdown_requested.is_set():
                    return self._json(503, {'error':'bridge is shutting down'})
                authorization = self.headers.get('Authorization', '')
                token = authorization[7:] if authorization.startswith('Bearer ') else ''
                try:
                    if route.endswith('/request'):
                        return self._json(200, bridge._passive_browser.request_connection(
                            self.headers.get('Origin'), self._body()))
                    if route.endswith('/receipt') or route.endswith('/cancel'):
                        return self._json(200, bridge._passive_browser.connection_receipt(
                            self.headers.get('Origin'), self._body(), cancel=route.endswith('/cancel')))
                    if route.endswith('/audio-epoch'):
                        grant = bridge._passive_browser.rotate_audio_epoch(
                            token, self.headers.get('Origin'))
                        # Old packets are fenced; the recognizer restarts clean.
                        bridge._browser_audio.stop()
                        return self._json(200, grant)
                    if route.endswith('/audio'):
                        grant = bridge._passive_browser.audio_grant()
                        if grant is None:
                            raise PermissionError('browser audio grant unavailable')
                        return self._json(200, bridge._browser_audio.receive(
                            token, self.headers.get('Origin'), self._body(), grant=grant))
                    return self._json(200, bridge._passive_browser.receive(token,
                        self.headers.get('Origin'), self._body()))
                except PermissionError as error:
                    return self._json(403, {'error':str(error)})
                except (ValueError, TypeError, KeyError, OSError) as error:
                    return self._json(400, {'error':str(error)})
            if not self._authorize(write=True):
                return
            # Shutdown must announce its fence before acquiring the writer lock.
            # Keep this authenticated route available for an explicit stop retry.
            if urlparse(self.path).path == '/api/lifecycle/shutdown':
                return self._post()
            if bridge._closing or bridge._shutdown_requested.is_set():
                return self._json(503, {'error': 'bridge is shutting down; request was not applied'})
            route = urlparse(self.path).path
            if route == '/api/companion/pet':
                try:
                    with bridge._chat_lock:
                        return self._json(200, bridge.companion_pet(self._body()))
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error':str(error)})
            # Consent withdrawal must not wait for a model holding the writer
            # lock. Starting/resuming capture still uses normal admission below.
            if route == '/api/companion/revoke':
                return self._post()
            if route == '/api/companion/passive-browser':
                try:
                    payload = self._body()
                    if isinstance(payload, dict) and payload.get('action') in ('pause','stop','status'):
                        return self._json(200, bridge.companion_passive_browser(payload))
                    with bridge._chat_lock:
                        if bridge._closing or bridge._shutdown_requested.is_set():
                            return self._json(503, {'error':'bridge is shutting down'})
                        return self._json(200, bridge.companion_passive_browser(payload))
                except (ValueError, PermissionError, RuntimeError, OSError) as error:
                    return self._json(400, {'error':str(error)})
            if route == '/api/companion/microphone':
                try:
                    payload = self._body()
                    if not isinstance(payload, dict):
                        raise ValueError('microphone action required')
                    self._microphone_payload = payload
                    if payload.get('action') in ('pause', 'stop', 'status'):
                        return self._json(200, bridge.companion_microphone(payload))
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/companion/audio':
                try:
                    payload = self._body()
                    if not isinstance(payload, dict):
                        raise ValueError('application audio action required')
                    self._audio_payload = payload
                    if payload.get('action') in ('pause', 'stop', 'status'):
                        return self._json(200, bridge.companion_audio(payload))
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/companion/media-state':
                try:
                    payload = self._body()
                    self._media_state_payload = payload
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/companion/perception':
                try:
                    payload = self._body()
                    if not isinstance(payload, dict):
                        raise ValueError('perception action object required')
                    self._perception_payload = payload
                    if payload.get('action') in ('pause', 'stop', 'status'):
                        return self._json(200, bridge.companion_perception(payload))
                except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
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
            if route not in ('/api/manage/role-relocation/resume','/api/manage/role-relocation/rollback','/api/lifecycle/shutdown', '/api/companion/revoke'):
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
            if route == "/api/companion/collect":
                try:
                    return self._json(200, bridge.companion_collect(self._body()))
                except (ValueError, RuntimeError, TypeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/companion/video":
                try:
                    return self._json(200, bridge.companion_video(self._body()))
                except (ValueError, RuntimeError, TypeError, OSError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/companion/capture":
                try:
                    return self._json(200, bridge.companion_capture(self._body()))
                except (ValueError, RuntimeError, TypeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {"error": str(error)})
            if route == '/api/companion/perception':
                try:
                    payload = self._perception_payload if hasattr(self, '_perception_payload') else self._body()
                    return self._json(200, bridge.companion_perception(payload))
                except (ValueError, PermissionError, RuntimeError, TypeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/companion/audio':
                try:
                    payload = self._audio_payload if hasattr(self, '_audio_payload') else self._body()
                    return self._json(200, bridge.companion_audio(payload))
                except (ValueError, PermissionError, RuntimeError, TypeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/companion/media-state':
                try:
                    payload = self._media_state_payload if hasattr(self, '_media_state_payload') else self._body()
                    return self._json(200, bridge.companion_media_state(payload))
                except (ValueError, PermissionError, RuntimeError, TypeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == '/api/companion/microphone':
                try:
                    payload = self._microphone_payload if hasattr(self, '_microphone_payload') else self._body()
                    return self._json(200, bridge.companion_microphone(payload))
                except (ValueError, PermissionError, RuntimeError, TypeError, OSError, subprocess.SubprocessError) as error:
                    return self._json(400, {'error': str(error)})
            if route == "/api/companion/browser-video":
                try:
                    return self._json(200, bridge.companion_browser_video(self._body()))
                except (ValueError, RuntimeError, TypeError, OSError, KeyError, subprocess.SubprocessError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/companion/observe":
                try:
                    return self._json(200, bridge.companion_observe(self._body()))
                except (ValueError, TypeError, OSError) as error:
                    return self._json(400, {"error": str(error)})
            if route == '/api/companion/ask-stream':
                try:
                    payload = self._body()
                    if not isinstance(payload, dict) or not isinstance(payload.get('question'), str) or not payload['question'].strip():
                        raise ValueError('question required')
                except (ValueError, TypeError) as error:
                    return self._json(400, {'error':str(error)})
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                def emit(kind, value):
                    self.wfile.write((json.dumps({'event':kind, **value}, ensure_ascii=False)+'\n').encode('utf8'))
                    self.wfile.flush()
                try:
                    result = bridge.companion_ask(payload.get('question'),
                        session_id=payload.get('session') or 'companion',
                        expected_target=payload.get('expected_target'),
                        on_delta=lambda value: emit('delta', value))
                    emit('complete', result)
                except (CloudError, OllamaError, ValueError, RuntimeError, TypeError, OSError, KeyError) as error:
                    try: emit('error', {'status':'unknown', 'kind':getattr(error,'kind',type(error).__name__),
                                      'fallback_used':False, 'usage_status':'unknown'})
                    except OSError: pass
                return
            if route == "/api/companion/ask":
                try:
                    payload = self._body()
                    return self._json(200, bridge.companion_ask(payload.get('question'), session_id=payload.get('session') or 'companion'))
                except (CloudError, OllamaError) as error:
                    return self._json(502, {"status": "unknown", "kind": getattr(error, "kind", "unknown"),
                                            "message": str(error), "fallback_used": False})
                except (ValueError, RuntimeError, TypeError, OSError, KeyError) as error:
                    return self._json(400, {"error": str(error)})
            if route == "/api/companion/revoke":
                try:
                    return self._json(200, bridge.companion_revoke())
                except (ValueError, RuntimeError, TypeError, OSError, KeyError) as error:
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
        # Windows rejects excess pending connections during parallel UI loading.
        request_queue_size = 64

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
        bridge.listen_port = httpd.server_port
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
    from extensions.desktop.reference_monitor import ReferenceMonitor
    from extensions.desktop.reference_runner import ReferenceRunner
    from extensions.desktop.reference_analysis import ConfiguredReferenceAnalyzer
    root = UI_ROOT.parent
    registry = root/'docs/project/reference-projects.json'
    if not registry.is_file():
        registry = root/'extensions/desktop/reference-projects.json'
    def analyzer_factory():
        settings = load_settings(httpd.sumika_bridge.settings_path)
        return (ConfiguredReferenceAnalyzer(httpd.sumika_bridge.settings_path)
                if settings['auxiliary']['enabled'] else None)
    research = ReferenceRunner(ReferenceMonitor(registry,
        httpd.sumika_bridge.settings_path.parent/'reference-projects.sqlite3'),
        notify=httpd.sumika_bridge.schedule.notify, analyzer_factory=analyzer_factory)
    try:
        research.start()
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        research.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
