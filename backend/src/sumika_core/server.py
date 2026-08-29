from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import socket
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .audio import AudioRuntime, AudioRuntimeError
from .agent import AgentCapability, AgentRuntime, AgentRuntimeError, SkillCatalog, SkillCatalogError, create_agent_runtime
from .avatar import AvatarError, AvatarManager
from .browser import (
    BrowserRuntime,
    BrowserRuntimeError,
    looks_like_secret_text,
    normalize_domain,
)
from .credentials import CredentialStore, credential_namespace_for_data_dir, default_credential_store
from .events import EventBus
from .evolution import EvolutionRegistry
from .diagnostics import close_logging, configure_logging, redact_text, safe_error
from .integrations import CCSwitchCompatibilityChecker
from .memory import MemoryRuntime, MemoryRuntimeError
from .modules import ModuleCatalog, ModuleError
from .observability import AgentObservability, classify_rpc_method
from .plugins import PluginCatalog, PluginCatalogError
from .persona import build_persona_context, normalize_persona
from .provider_imports import ProviderImportError, ProviderImportRegistry
from .provider_profiles import (
    ProviderProfileError,
    ProviderProfileManager,
)
from .vision import VisionRuntime, VisionRuntimeError
from .workspace import WorkspaceError, WorkspaceRuntime
from .protocol.jsonrpc import JsonRpcError, failure, parse_request, success
from .protocol.models import ChatRequest, EventEnvelope, Message, utc_now
from .providers import (
    AudioProviderRegistry,
    CommandASRProvider,
    CommandProvider,
    CommandTTSProvider,
    CommandVADProvider,
    CommandMemoryProvider,
    CommandVisionProvider,
    MemoryProviderRegistry,
    OpenAICompatibleProvider,
    PluginASRProvider,
    PluginLLMProvider,
    PluginMemoryProvider,
    PluginTTSProvider,
    PluginVADProvider,
    PluginVisionProvider,
    ProviderRegistry,
    SQLiteMemoryProvider,
    VisionProviderRegistry,
)
from .storage import Storage
from .tasks import AgentTaskProjector, TaskError, TaskManager, TaskRunner
from .tools import ToolRuntime, ToolRuntimeError
from .transport.websocket import accept_websocket, encode_text_frame


ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT_DIR / "frontend"
DEFAULT_AVATAR_PATH = ROOT_DIR / "assets" / "avatars" / "AvatarSample_A.vrm"
DEFAULT_AVATAR_THUMBNAIL_PATH = ROOT_DIR / "assets" / "avatars" / "AvatarSample_A.thumbnail.png"
AVATAR_ASSETS_DIR = ROOT_DIR / "assets" / "avatars"
AVATAR_DISCOVERY_IGNORED_META_KEY = "avatar.discovery.ignored.v1"
AVATAR_CENTER_MIGRATION_META_KEY = "avatar.presentation.center_migration.v1"
DEFAULT_AVATAR_META_KEY = "bootstrap.default_avatar.v2"
DEFAULT_AVATAR_SOURCE_SIZE = 15096320
DEFAULT_AVATAR_SOURCE_SHA256 = "B86B0B8A66D48911431D6F920A5211A974226F83AA672ECA3F3DFADE58AC346E"
_DEFAULT_JSON_BODY_LIMIT = 2_000_000
_RPC_JSON_BODY_LIMIT = 18 * 1024 * 1024
DEFAULT_AVATAR_METADATA = {
    "bundled": True,
    "bundled_role": "default_demo_avatar",
    "source_repository": "https://github.com/madjin/vrm-samples",
    "source_commit": "e16eb187100149a315ad92c3c9968f1d5baa6c7d",
    "source_url": "https://raw.githubusercontent.com/madjin/vrm-samples/e16eb187100149a315ad92c3c9968f1d5baa6c7d/vroid/stable/AvatarSample_A.vrm",
    "authors": ["VRoid"],
    "source_size_bytes": DEFAULT_AVATAR_SOURCE_SIZE,
    "source_sha256": DEFAULT_AVATAR_SOURCE_SHA256,
    "license": "VRoid Studio sample model terms",
    "license_url": "https://vroid.pixiv.help/hc/en-us/articles/4402394424089",
    "allow_redistribution": True,
    "allow_modification_redistribution": True,
    "credit_notation": "follow the linked VRoid sample model terms",
    "preview_path": "assets/avatars/AvatarSample_A.thumbnail.png",
    "preview_sha256": "FB842AC062564CCB199555C20170DAD502C63D87007D4F602712C194175349D8",
    "renderer_status": "three_vrm_local_renderer",
}

PROVIDER_MIGRATION_META_KEY = "provider.real_backend_migration.v1"
PROVIDER_PROFILE_MIGRATION_META_KEY = "provider.profile_migration.v1"
PROVIDER_UNCONFIGURED_MIGRATION_META_KEY = "provider.unconfigured_default_migration.v1"
DEFAULT_OPENAI_BASE_URL = ""
DEFAULT_OPENAI_MODEL = ""


class CoreApplication:
    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        test_providers: dict[str, list[Any]] | None = None,
        credential_store: CredentialStore | None = None,
        agent_runtime: AgentRuntime | None = None,
    ) -> None:
        configured_dir = data_dir or os.getenv("SUMIKA_DATA_DIR", str(ROOT_DIR / ".sumika"))
        self.data_dir = Path(configured_dir) if str(configured_dir) != ":memory:" else Path(".")
        self.configured_data_dir = None if str(configured_dir) == ":memory:" else self.data_dir
        self.logger, self.log_path = configure_logging(self.configured_data_dir)
        # The observability stream is intentionally separate from SQLite's
        # product audit events.  It stores only bounded, content-independent
        # receipts for offline maintenance analysis.
        self.observability = AgentObservability(self.configured_data_dir, logger=self.logger)
        self._closed = False
        self.started_at = time.monotonic()
        self.logger.info("core initializing data_dir=%s", configured_dir)
        if str(configured_dir) == ":memory:":
            self.storage = Storage(":memory:")
        else:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.storage = Storage(self.data_dir / "sumika.sqlite3")
        credential_namespace = credential_namespace_for_data_dir(configured_dir)
        self.credentials = credential_store or default_credential_store(
            in_memory=str(configured_dir) == ":memory:",
            namespace=credential_namespace,
        )
        self.provider_profiles = ProviderProfileManager(self.storage, self.credentials)
        self.provider_imports = ProviderImportRegistry()
        self.ccswitch_compatibility = CCSwitchCompatibilityChecker(
            ROOT_DIR / "docs" / "integrations" / "cc-switch-compatibility.json"
        )
        self.events = EventBus(self.storage, self.logger)
        self.workspace = WorkspaceRuntime(self.configured_data_dir, logger=self.logger)
        self.agent = agent_runtime if agent_runtime is not None else create_agent_runtime(
            self.configured_data_dir,
            logger=self.logger,
        )
        self.agent.bind_credential_store(self.credentials)
        self.agent.set_event_sink(self._on_agent_runtime_event)
        self.browser = BrowserRuntime(
            self.configured_data_dir,
            logger=self.logger,
            storage=self.storage,
        )
        self.evolution_registry = EvolutionRegistry(ROOT_DIR / "docs" / "integrations" / "evolution-knowledge-registry.json")
        self.tasks = TaskManager(self.storage, self.events)
        self.task_runner = TaskRunner(self.tasks, self.events)
        self.agent_tasks = AgentTaskProjector(
            self.agent,
            self.workspace,
            storage=self.storage,
            logger=self.logger,
        )
        self.task_runner.register("core-health", self._run_core_health)
        self.avatar = AvatarManager(self.storage)
        self.plugins = PluginCatalog(self.storage)
        self.plugin_paths = _default_plugin_paths()
        self.skills = SkillCatalog(
            self.storage,
            default_paths=_default_skill_paths(),
            logger=self.logger,
        )
        self._ensure_defaults()
        self._discover_plugins_at_startup()
        self.providers = ProviderRegistry()
        self.providers.register(
            OpenAICompatibleProvider(
                base_url=os.getenv("SUMIKA_OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
                model=os.getenv("SUMIKA_OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            )
        )
        command_path = os.getenv("SUMIKA_COMMAND_PROVIDER")
        if command_path:
            self.providers.register(CommandProvider(command_path))
        self.audio_providers = AudioProviderRegistry()
        self.audio_providers.register(CommandASRProvider())
        self.audio_providers.register(CommandTTSProvider())
        self.audio_providers.register(CommandVADProvider())
        self.memory_providers = MemoryProviderRegistry()
        self.memory_providers.register(SQLiteMemoryProvider(self.storage))
        self.memory_providers.register(CommandMemoryProvider())
        self.vision_providers = VisionProviderRegistry()
        self.vision_providers.register(CommandVisionProvider())
        self._register_test_providers(test_providers)
        self._migrate_legacy_provider_settings()
        self._sync_plugin_providers()
        self.modules = ModuleCatalog(
            self.storage,
            self.providers,
            self.audio_providers,
            self.memory_providers,
            self.vision_providers,
        )
        # Tests inject deterministic providers explicitly. Select that fixture
        # only for the lifetime of the test application; production startup
        # never registers or selects a fake backend.
        injected_llm = (test_providers or {}).get("llm", [])
        if injected_llm:
            injected_info = getattr(injected_llm[0], "info", None)
            if injected_info is not None:
                self.modules.update("llm", enabled=True, implementation_id=injected_info.id)
        self._migrate_legacy_provider_config()
        self.audio = AudioRuntime(self.storage, self.modules, self.audio_providers, self.events)
        self.memory = MemoryRuntime(self.storage, self.modules, self.memory_providers, self.events)
        self.vision = VisionRuntime(self.storage, self.modules, self.vision_providers, self.events)
        self.tools = ToolRuntime(self.modules, self.events)
        try:
            self.modules.restore_runtime()
        except ModuleError as exc:
            self.logger.warning("module runtime restore skipped error_type=%s", type(exc).__name__)
        self.logger.info(
            "core initialized modules=%d providers=%d avatars=%d",
            len(self.modules.list()),
            len(self.providers.list()),
            len(self.avatar.list_models()),
        )

    def _register_test_providers(self, providers: dict[str, list[Any]] | None) -> None:
        """Inject deterministic providers only when a test explicitly asks for them."""
        if not providers:
            return
        registries: dict[str, Any] = {
            "llm": self.providers,
            "asr": self.audio_providers,
            "tts": self.audio_providers,
            "vad": self.audio_providers,
            "memory": self.memory_providers,
            "vision": self.vision_providers,
        }
        for capability, values in providers.items():
            registry = registries.get(capability)
            if registry is None:
                raise ValueError(f"Unknown test provider capability: {capability}")
            items = values if isinstance(values, list) else [values]
            for provider in items:
                info = getattr(provider, "info", None)
                if info is None:
                    raise ValueError(f"Test provider for {capability} has no info")
                if not registry.has(info.id):
                    registry.register(provider)

    def _migrate_legacy_provider_settings(self) -> None:
        """Idempotently move old Fake/placeholder selections to explicit states."""
        changed: list[dict[str, Any]] = []
        llm = self.storage.get_module_setting("llm")
        if llm and str(llm["implementation_id"]).lower() in {"fake", "local-reference"}:
            config = {
                key: value
                for key, value in dict(llm.get("config") or {}).items()
                if key in {"base_url", "model", "timeout"}
            }
            has_legacy_config = bool(config)
            base_url = config.get("base_url") or (os.getenv("SUMIKA_OPENAI_BASE_URL") if has_legacy_config else None)
            model = config.get("model") or (os.getenv("SUMIKA_OPENAI_MODEL") if has_legacy_config else None)
            if base_url and model:
                config.update({"base_url": base_url, "model": model})
                enabled = bool(llm["enabled"])
            else:
                enabled = False
            self.storage.upsert_module_setting(
                "llm",
                enabled=enabled,
                implementation_id="openai-compatible",
                config=config,
            )
            changed.append(
                {
                    "module_id": "llm",
                    "from": llm["implementation_id"],
                    "to": "openai-compatible",
                    "enabled": enabled,
                    "configuration_preserved": bool(config),
                }
            )
        disabled_legacy = {
            "asr": {"fake-asr"},
            "tts": {"fake-tts"},
            "vad": {"fake-vad"},
            "memory": {"fake-memory"},
            "vision": {"fake-vision", "local-reference"},
            "avatar": {"live2d", "local-reference"},
        }
        for module_id, legacy_ids in disabled_legacy.items():
            setting = self.storage.get_module_setting(module_id)
            if setting and str(setting["implementation_id"]).lower() in legacy_ids:
                self.storage.upsert_module_setting(
                    module_id,
                    enabled=False,
                    implementation_id="none",
                    config={},
                )
                changed.append({"module_id": module_id, "from": setting["implementation_id"], "to": "none"})
        self.storage.set_meta(PROVIDER_MIGRATION_META_KEY, "done")
        if changed:
            self.events.publish(
                EventEnvelope(
                    "provider.settings.migrated",
                    {"migration": PROVIDER_MIGRATION_META_KEY, "changes": changed},
                )
            )
            self.logger.info("migrated legacy provider settings count=%d", len(changed))

    def _migrate_legacy_provider_config(self) -> None:
        """Migrate the single legacy adapter config to a reusable profile."""
        setting = self.storage.get_module_setting("llm")
        if not setting or setting.get("implementation_id") != "openai-compatible":
            return
        config = dict(setting.get("config") or {})
        profile_id = config.get("profile_id")
        if isinstance(profile_id, str) and profile_id:
            if self.storage.get_provider_profile(profile_id):
                return
            if bool(setting["enabled"]):
                self.modules.update(
                    "llm",
                    enabled=False,
                    implementation_id="openai-compatible",
                    config={"profile_id": profile_id},
                )
                if self.storage.get_meta(PROVIDER_UNCONFIGURED_MIGRATION_META_KEY) != "done":
                    self.storage.set_meta(PROVIDER_UNCONFIGURED_MIGRATION_META_KEY, "done")
                    self.events.publish(
                        EventEnvelope(
                            "provider.unconfigured_default.disabled",
                            {
                                "migration": PROVIDER_UNCONFIGURED_MIGRATION_META_KEY,
                                "previous_enabled": True,
                                "reason": "missing-profile",
                                "retained_profile_id": profile_id,
                            },
                        )
                    )
            return
        if not bool(setting["enabled"]) and not config:
            return
        has_legacy_config = bool(config)
        base_url = config.get("base_url") or (os.getenv("SUMIKA_OPENAI_BASE_URL") if has_legacy_config else None)
        model = config.get("model") or (os.getenv("SUMIKA_OPENAI_MODEL") if has_legacy_config else None)
        if not base_url or not model:
            if bool(setting["enabled"]) or config:
                self.storage.upsert_module_setting(
                    "llm",
                    enabled=False,
                    implementation_id="openai-compatible",
                    config=config,
                )
                if self.storage.get_meta(PROVIDER_UNCONFIGURED_MIGRATION_META_KEY) != "done":
                    self.storage.set_meta(PROVIDER_UNCONFIGURED_MIGRATION_META_KEY, "done")
                    self.events.publish(
                        EventEnvelope(
                            "provider.unconfigured_default.disabled",
                            {
                                "migration": PROVIDER_UNCONFIGURED_MIGRATION_META_KEY,
                                "previous_enabled": bool(setting["enabled"]),
                                "reason": "incomplete-legacy-config" if config else "empty-legacy-default",
                                "retained_config_keys": sorted(config),
                            },
                        )
                    )
            return
        config.update({"base_url": base_url, "model": model})
        profile = self.provider_profiles.ensure_legacy_profile(config)
        if any(config.get(key) not in (None, "") for key in ("base_url", "model", "timeout")):
            profile = self.provider_profiles.save(
                {
                    **profile,
                    "base_urls": [config.get("base_url") or profile["config"].get("active_base_url")],
                    "active_base_url": config.get("base_url") or profile["config"].get("active_base_url"),
                    "model": config.get("model") or profile["config"].get("model"),
                    "timeout": config.get("timeout") or profile["config"].get("timeout", 60),
                }
            )
        environment_key = os.getenv("SUMIKA_OPENAI_API_KEY")
        if environment_key and not profile.get("has_secrets"):
            profile = self.provider_profiles.save({**profile, "api_key": environment_key})
        self.modules.update(
            "llm",
            enabled=bool(setting["enabled"]),
            implementation_id="openai-compatible",
            config={"profile_id": profile["id"]},
        )
        if self.storage.get_meta(PROVIDER_PROFILE_MIGRATION_META_KEY) != "done":
            self.storage.set_meta(PROVIDER_PROFILE_MIGRATION_META_KEY, "done")
            self.events.publish(
                EventEnvelope(
                    "provider.profile.migrated",
                    {
                        "migration": PROVIDER_PROFILE_MIGRATION_META_KEY,
                        "profile_id": profile["id"],
                        "adapter_id": "openai-compatible",
                    },
                )
            )

    def _ensure_defaults(self) -> None:
        if not self.storage.list_characters():
            self.storage.create_character(
                "sumika",
                "Sumika",
                {
                    "avatar_driver": "none",
                    "memory_enabled": False,
                    "language": "zh-CN",
                    "persona": {
                        "identity": "",
                        "traits": "",
                        "relationship": "",
                        "speaking_style": "",
                        "behavior": "",
                        "boundaries": "",
                        "response_length": "balanced",
                        "system_prompt": "",
                        "greeting": "",
                    },
                    "avatar": {
                        "position": "center",
                        "opacity": 1,
                        "scale": 1,
                        "idle_motion": True,
                        "auto_rotate": False,
                        "rotation_speed": 0.12,
                        "natural_pose": True,
                        "look_at_enabled": True,
                        "head_follow_enabled": True,
                        "look_at_strength": 1.0,
                        "head_follow_strength": 0.35,
                    },
                },
            )
        self._ensure_character_avatar_defaults()
        self._ensure_center_avatar_stage_migration()
        characters = self.storage.list_characters()
        default_character_id = "sumika" if self.storage.get_character("sumika") else characters[0]["id"]
        if not self.storage.list_sessions():
            self.storage.create_session("default", "初始会话", default_character_id)
        self.tasks.ensure_default()
        self.avatar.restore_character(default_character_id)
        self._ensure_default_avatar(default_character_id)
        self._discover_avatar_assets()

    def _ensure_character_avatar_defaults(self) -> None:
        """Normalize legacy character records without changing their choices."""
        for character in self.storage.list_characters():
            normalized = _validate_character_config(character["config"])
            if normalized != character["config"]:
                self.storage.update_character_config(character["id"], normalized)

    def _ensure_center_avatar_stage_migration(self) -> None:
        """Move only the original Sumika character to the centered stage once."""
        if self.storage.get_meta(AVATAR_CENTER_MIGRATION_META_KEY) == "done":
            return
        character = self.storage.get_character("sumika")
        if character is not None:
            config = _validate_character_config(character["config"])
            avatar = config.get("avatar", {})
            if avatar.get("position") == "right":
                avatar["position"] = "center"
                updated = self.storage.update_character_config("sumika", config)
                if updated is not None:
                    self.events.publish(
                        EventEnvelope(
                            "avatar.presentation.migrated",
                            {"character_id": "sumika", "from": "right", "to": "center"},
                            character_id="sumika",
                        )
                    )
        self.storage.set_meta(AVATAR_CENTER_MIGRATION_META_KEY, "done")

    def _ensure_default_avatar(self, character_id: str) -> None:
        """Seed the bundled demo model once, without overriding later user choices."""
        if self.storage.get_meta(DEFAULT_AVATAR_META_KEY) == "done":
            return
        if self.avatar.list_models():
            # An existing registration means the user already has an Avatar choice.
            self.storage.set_meta(DEFAULT_AVATAR_META_KEY, "done")
            return
        if not DEFAULT_AVATAR_PATH.is_file() or not DEFAULT_AVATAR_THUMBNAIL_PATH.is_file():
            return
        try:
            source_stat = DEFAULT_AVATAR_PATH.stat()
            source_hash = _sha256_file(DEFAULT_AVATAR_PATH)
        except OSError as exc:
            self.events.publish(EventEnvelope("avatar.default.failed", {"error": str(exc)}))
            return
        if source_stat.st_size != DEFAULT_AVATAR_SOURCE_SIZE or source_hash.upper() != DEFAULT_AVATAR_SOURCE_SHA256:
            self.events.publish(EventEnvelope("avatar.default.failed", {"error": "bundled Avatar hash mismatch"}))
            return
        try:
            model = self.avatar.import_model(
                str(DEFAULT_AVATAR_PATH),
                name="Sumika 默认 Avatar（VRoid Sample A）",
                kind="vrm",
                metadata=dict(DEFAULT_AVATAR_METADATA),
            )
            result = self.avatar.select(character_id, model_id=model["id"], driver_id="vrm")
        except AvatarError as exc:
            self.events.publish(EventEnvelope("avatar.default.failed", {"error": str(exc)}))
            return
        self.storage.set_meta(DEFAULT_AVATAR_META_KEY, "done")
        self.events.publish(
            EventEnvelope(
                "avatar.default.seeded",
                {"model": model, "state": result["state"]},
                character_id=character_id,
            )
        )

    def _discover_avatar_assets(self) -> list[dict[str, Any]]:
        """Register new supported assets from the repository Avatar directory."""
        before = {model["id"] for model in self.avatar.list_models()}
        try:
            excluded_paths = {DEFAULT_AVATAR_PATH, *self._ignored_avatar_paths()}
            models = self.avatar.discover_directory(
                AVATAR_ASSETS_DIR,
                metadata={"auto_discovered": True, "managed_directory": "assets/avatars"},
                exclude_paths=excluded_paths,
            )
        except AvatarError as exc:
            self.events.publish(EventEnvelope("avatar.discovery.failed", {"error": str(exc)}))
            return []
        for model in models:
            if model["id"] not in before:
                self.events.publish(EventEnvelope("avatar.model.imported", {"model": model}))
        return self.avatar.list_models()

    def _ignored_avatar_paths(self) -> set[Path]:
        raw = self.storage.get_meta(AVATAR_DISCOVERY_IGNORED_META_KEY)
        if not raw:
            return set()
        try:
            values = json.loads(raw)
        except (TypeError, ValueError):
            return set()
        if not isinstance(values, list):
            return set()
        return {Path(value).resolve() for value in values if isinstance(value, str) and value.strip()}

    def _set_avatar_path_ignored(self, path: str, ignored: bool) -> None:
        resolved = Path(path).expanduser().resolve()
        paths = self._ignored_avatar_paths()
        if ignored:
            paths.add(resolved)
        else:
            paths.discard(resolved)
        self.storage.set_meta(
            AVATAR_DISCOVERY_IGNORED_META_KEY,
            json.dumps(sorted(str(item) for item in paths), ensure_ascii=False),
        )

    def _ignored_avatar_models(self) -> list[dict[str, Any]]:
        """Describe managed model paths hidden from automatic discovery."""
        models: list[dict[str, Any]] = []
        for path in sorted(self._ignored_avatar_paths(), key=lambda item: str(item).lower()):
            if not self._is_managed_avatar_path(str(path)):
                continue
            name = path.name
            lower_name = name.lower()
            if path.suffix.lower() == ".vrm":
                kind = "vrm"
                display_name = path.stem
            elif lower_name.endswith(".model3.json"):
                kind = "live2d"
                display_name = name[:-len(".model3.json")]
            elif lower_name.endswith(".model.json"):
                kind = "live2d"
                display_name = name[:-len(".model.json")]
            else:
                continue
            available = path.is_file()
            size_bytes = 0
            modified_at: str | None = None
            if available:
                try:
                    stat = path.stat()
                    size_bytes = stat.st_size
                    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                except OSError:
                    available = False
            models.append(
                {
                    "id": f"ignored-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:12]}",
                    "name": display_name or name,
                    "kind": kind,
                    "path": str(path),
                    "size_bytes": size_bytes,
                    "modified_at": modified_at,
                    "metadata": {
                        "ignored": True,
                        "managed_directory": "assets/avatars",
                        "availability": "available" if available else "missing",
                        "reason": "ignored_by_user" if available else "missing_or_inaccessible",
                    },
                    "managed": True,
                    "ignored": True,
                    "available": available,
                    "last_known_kind": kind,
                    "reason": "ignored_by_user" if available else "missing_or_inaccessible",
                }
            )
        return models

    @staticmethod
    def _is_managed_avatar_path(path: str) -> bool:
        try:
            return Path(path).expanduser().resolve().parent.is_relative_to(AVATAR_ASSETS_DIR.resolve())
        except (OSError, ValueError):
            return False

    def avatar_thumbnail(self, model_id: str) -> bytes | None:
        """Return a verified bundled preview without exposing arbitrary local files."""
        model = self.storage.get_avatar_model(model_id)
        if model is None:
            return None
        metadata = model.get("metadata")
        if not isinstance(metadata, dict):
            return None
        relative_path = metadata.get("preview_path")
        expected_hash = metadata.get("preview_sha256")
        if (
            not isinstance(relative_path, str)
            or Path(relative_path).is_absolute()
            or not isinstance(expected_hash, str)
        ):
            return None
        allowed_root = (ROOT_DIR / "assets" / "avatars").resolve()
        candidate = (ROOT_DIR / relative_path).resolve()
        if allowed_root not in candidate.parents or not candidate.is_file():
            return None
        if candidate.stat().st_size > 5 * 1024 * 1024:
            return None
        body = candidate.read_bytes()
        if hashlib.sha256(body).hexdigest().upper() != expected_hash.upper():
            return None
        return body

    def avatar_file(self, model_id: str) -> bytes | None:
        """Return a registered VRM binary for the local renderer only."""
        model = self.storage.get_avatar_model(model_id)
        if model is None or model.get("kind") != "vrm":
            return None
        raw_path = model.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        try:
            candidate = Path(raw_path).expanduser().resolve(strict=True)
            if not candidate.is_file() or candidate.suffix.lower() != ".vrm":
                return None
            if candidate.stat().st_size > 100 * 1024 * 1024:
                return None
            return candidate.read_bytes()
        except OSError:
            return None

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        started = time.monotonic()
        component, capability = classify_rpc_method(method)
        operation_id = None
        try:
            operation_id = self.observability.start(
                component=component,
                capability=capability,
                phase="accepted",
                session_id=params.get("session_id") if isinstance(params, dict) else None,
                turn_id=params.get("turn_id") if isinstance(params, dict) else None,
                provider_kind=params.get("provider_id") if isinstance(params, dict) else None,
            )
        except Exception as error:
            # Diagnostics must never make a product request fail.  The normal
            # logger still records the operational failure type.
            self.logger.warning("agent observability start failed error_type=%s", type(error).__name__)
        self.logger.info("rpc start method=%s", method)
        try:
            result = self._rpc(method, params)
            if operation_id:
                try:
                    self.observability.finish(
                        operation_id,
                        component=component,
                        capability=capability,
                        phase="completed",
                        outcome="completed",
                        duration_ms=(time.monotonic() - started) * 1000,
                        session_id=params.get("session_id") if isinstance(params, dict) else None,
                        turn_id=params.get("turn_id") if isinstance(params, dict) else None,
                        provider_kind=params.get("provider_id") if isinstance(params, dict) else None,
                    )
                except Exception as error:
                    self.logger.warning("agent observability finish failed error_type=%s", type(error).__name__)
            return result
        except Exception as error:
            self.logger.error(
                "rpc failed method=%s duration_ms=%d error_type=%s",
                method,
                round((time.monotonic() - started) * 1000),
                type(error).__name__,
            )
            if operation_id:
                try:
                    self.observability.finish(
                        operation_id,
                        component=component,
                        capability=capability,
                        phase="failed",
                        outcome="rejected" if isinstance(error, JsonRpcError) and error.code in {-32600, -32601, -32602, -32010, -32031, -32033} else "failed",
                        duration_ms=(time.monotonic() - started) * 1000,
                        error_class=type(error).__name__,
                        session_id=params.get("session_id") if isinstance(params, dict) else None,
                        turn_id=params.get("turn_id") if isinstance(params, dict) else None,
                        provider_kind=params.get("provider_id") if isinstance(params, dict) else None,
                    )
                except Exception as diagnostic_error:
                    self.logger.warning("agent observability failure receipt failed error_type=%s", type(diagnostic_error).__name__)
            raise
        finally:
            self.logger.info("rpc end method=%s duration_ms=%d", method, round((time.monotonic() - started) * 1000))

    def _on_agent_runtime_event(self, event: dict[str, Any]) -> None:
        """Project harness events into Sumika's local auditable event bus."""

        event_type = str(event.get("event_type") or "agent.event")
        projected_type = {
            "approval/requested": "agent.approval.requested",
            "approval/resolved": "agent.approval.resolved",
            "question/requested": "agent.question.requested",
            "question/resolved": "agent.question.resolved",
            "session/event": "agent.session.event",
            "session/queue": "agent.session.queue",
            "session/jobs": "agent.session.jobs",
        }.get(event_type, f"agent.{self.agent.runtime_id}.event")
        payload = _redact_agent_payload(event)
        try:
            event_outcome = _observability_event_outcome(event_type, event)
            extensions = event.get("extensions") if isinstance(event.get("extensions"), dict) else {}
            metrics = extensions.get("metrics") if isinstance(extensions.get("metrics"), dict) else {}
            self.observability.record(
                component="agent",
                capability="runtime-event",
                phase=_observability_event_phase(event_type),
                outcome=event_outcome,
                session_id=event.get("session_id"),
                turn_id=event.get("turn_id"),
                event_type=event_type,
                error_class=(event.get("error", {}).get("name") if isinstance(event.get("error"), dict) else None),
                duration_ms=metrics.get("duration_ms"),
                queue_ms=metrics.get("queue_ms"),
                retry_count=metrics.get("retry_count"),
                input_units=metrics.get("input_units"),
                output_units=metrics.get("output_units"),
                cache_units=metrics.get("cache_units"),
                estimated_cost=metrics.get("estimated_cost"),
                approval_count=metrics.get("approval_count"),
            )
        except Exception as error:
            self.logger.warning("agent observability event failed error_type=%s", type(error).__name__)
        self.events.publish(
            EventEnvelope(
                projected_type,
                payload,
                session_id=event.get("session_id"),
            )
        )

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if method == "core.health":
            return {
                "ok": True,
                "version": "0.1.0",
                "transport": ["http", "websocket"],
                "uptime_seconds": round(time.monotonic() - self.started_at, 3),
            }
        if method == "core.diagnostics":
            return self.diagnostics()
        if method == "agent.observability.status":
            return self.observability.status()
        if method == "agent.observability.daily":
            day = params.get("day") if isinstance(params, dict) else None
            write = bool(params.get("write")) if isinstance(params, dict) else False
            try:
                return self.observability.write_daily_summary(day) if write else self.observability.aggregate(day)
            except ValueError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "agent.acceptance.evidence":
            session_id = _agent_session_id_param(
                params.get("sessionId") or params.get("session_id"),
                "sessionId",
            )
            return _agent_acceptance_evidence(
                self.storage.list_events(1000),
                session_id=session_id,
                runtime_id=self.agent.runtime_id,
            )
        if method in {"agent.status", "agent.health"}:
            result = self.agent.status() if method == "agent.status" else self.agent.health()
            result = {
                **result,
                "runtime_id": self.agent.runtime_id,
                "runtime_capabilities": self.agent.runtime_capabilities(),
            }
            if method == "agent.health":
                self.events.publish(EventEnvelope("agent.runtime.health", {"ok": bool(result.get("ok")), "state": result.get("state")}))
            return result
        if method == "agent.diagnostics":
            try:
                return self.agent.diagnostics(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.presets":
            try:
                return self.agent.list_presets(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.preset.copy":
            copy_params = _agent_preset_copy_params(params)
            try:
                result = self.agent.copy_preset(copy_params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.preset.copied",
                    {
                        "source": result.get("source"),
                        "agent_preset": result.get("agent_preset"),
                    },
                )
            )
            return result
        if method == "agent.preset.open":
            preset = _agent_preset_id_param(
                params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
                "agentPreset",
            )
            try:
                result = self.agent.open_preset_document({"agentPreset": preset})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.preset.document.opened",
                    {
                        "agent_preset": result.get("agent_preset", preset),
                        "opened": bool(result.get("opened")),
                    },
                )
            )
            return {
                "agent_preset": result.get("agent_preset", preset),
                "opened": bool(result.get("opened")),
            }
        if method == "agent.preset.validate":
            preset = _agent_preset_id_param(
                params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
                "agentPreset",
            )
            request: dict[str, Any] = {"agentPreset": preset}
            raw_workspace_id = params.get("workspaceId") or params.get("workspace_id")
            raw_cwd = params.get("cwd")
            if raw_workspace_id not in (None, "") and raw_cwd not in (None, ""):
                raise JsonRpcError(-32602, "preset validation accepts workspaceId or cwd, not both")
            if raw_workspace_id not in (None, ""):
                if (
                    not isinstance(raw_workspace_id, str)
                    or not raw_workspace_id.strip()
                    or len(raw_workspace_id.strip()) > 160
                    or any(ord(char) < 32 or ord(char) == 127 for char in raw_workspace_id)
                ):
                    raise JsonRpcError(-32602, "workspaceId must be a non-empty identifier")
                request["workspaceId"] = raw_workspace_id.strip()
            elif raw_cwd not in (None, ""):
                request["cwd"] = _workspace_path_param(raw_cwd)
            try:
                result = self.agent.validate_preset_mount(request)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.preset.mount.validated",
                    {
                        "agent_preset": preset,
                        "mountable": result.get("mountable") is True,
                        "validation_session_archived": result.get("validation_session_archived") is True,
                    },
                )
            )
            return {
                "agent_preset": preset,
                "mountable": result.get("mountable") is True,
                "validation_session_archived": result.get("validation_session_archived") is True,
            }
        if method == "agent.preset.remove":
            preset = _agent_preset_id_param(
                params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
                "agentPreset",
            )
            if params.get("approved") is not True or params.get("confirm_agent_preset") != preset:
                raise JsonRpcError(
                    -32031,
                    "removing a user preset requires explicit approval and an exact preset id confirmation",
                )
            try:
                roster = self.agent.list_presets({})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            entries = roster.get("presets") if isinstance(roster, dict) else None
            entry = next(
                (
                    item
                    for item in entries
                    if isinstance(item, dict) and item.get("id") == preset
                ),
                None,
            ) if isinstance(entries, list) else None
            if entry is None:
                raise JsonRpcError(-32602, "the requested Agent preset is not in the current runtime roster")
            if entry.get("trust") != "user":
                raise JsonRpcError(-32031, "only explicitly user-owned Agent presets can be removed")
            try:
                result = self.agent.remove_preset({"agentPreset": preset})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            removed = isinstance(result, dict) and result.get("removed") is True
            if not removed:
                raise JsonRpcError(-32030, "the Agent runtime did not confirm preset removal")
            self.events.publish(
                EventEnvelope(
                    "agent.preset.removed",
                    {"agent_preset": preset, "removed": True},
                )
            )
            return {"agent_preset": preset, "removed": True}
        if method == "agent.session.select_preset":
            try:
                result = self.agent.select_preset(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.session.preset.selected",
                    {
                        "session_id": result.get("session_id"),
                        "agent_preset": result.get("agent_preset"),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "agent.session.create":
            request = dict(params)
            workspace = None
            if self._agent_workspace_safety_active():
                workspace, _ = self._agent_workspace_binding(request)
                request.pop("workspace_id", None)
                request.pop("cwd", None)
                request["workspaceId"] = workspace["id"]
            provider_binding = None
            if self.agent.supports(AgentCapability.PROVIDER_BRIDGE):
                try:
                    provider_profile = self._agent_provider_profile(request, refresh_health=True)
                    if provider_profile.get("status") != "available":
                        raise ProviderProfileError(
                            "Provider 档案当前不可用；请在模块页测试连接后再创建 Agent 会话"
                        )
                    provider_binding = self.agent.sync_provider_profile(provider_profile)
                except (AgentRuntimeError, ProviderProfileError) as exc:
                    raise JsonRpcError(-32032, str(exc)) from exc
            try:
                result = self.agent.create_session(request)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            if provider_binding:
                session_id = result.get("sessionId") or result.get("id")
                if not session_id:
                    raise JsonRpcError(-32030, "Agent runtime did not return a session id for provider binding")
                try:
                    selected = self.agent.select_model(
                        {
                            "session_id": session_id,
                            "provider": provider_binding["route_id"],
                            "model": provider_binding["model"],
                        }
                    )
                except AgentRuntimeError as exc:
                    raise JsonRpcError(-32032, f"Agent Provider 已同步，但会话模型选择失败：{exc}") from exc
                result = {
                    **result,
                    "provider": provider_binding,
                    "selected_model": selected.get("selected") if isinstance(selected, dict) else selected,
                }
            self.events.publish(
                EventEnvelope(
                    "agent.session.created",
                    {
                        "session": _redact_agent_payload(result),
                        "workspace_id": workspace.get("id") if workspace else None,
                    },
                )
            )
            return result
        if method == "agent.sessions":
            try:
                return self.agent.list_sessions(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.sessions.search":
            query = params.get("query")
            if (
                not isinstance(query, str)
                or not query.strip()
                or len(query.strip()) > 512
                or any(ord(char) < 32 or ord(char) == 127 for char in query)
            ):
                raise JsonRpcError(-32602, "session search query must be non-empty, at most 512 characters, and contain no control characters")
            try:
                return self.agent.search_sessions({"query": query.strip()})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.session.rename":
            session_id = params.get("sessionId") or params.get("session_id")
            title = params.get("title")
            if (
                not isinstance(session_id, (str, int))
                or isinstance(session_id, bool)
                or not str(session_id).strip()
                or len(str(session_id).strip()) > 240
                or any(ord(char) < 32 or ord(char) == 127 for char in str(session_id))
            ):
                raise JsonRpcError(-32602, "sessionId must be a non-empty identifier without control characters")
            if (
                not isinstance(title, str)
                or not title.strip()
                or len(title.strip()) > 240
                or any(ord(char) < 32 or ord(char) == 127 for char in title)
            ):
                raise JsonRpcError(-32602, "title must be non-empty, at most 240 characters, and contain no control characters")
            try:
                result = self.agent.rename_session({"sessionId": str(session_id).strip(), "title": title.strip()})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.session.renamed",
                    {
                        "session_id": result.get("session_id"),
                        "title": result.get("title"),
                        "seq": result.get("seq"),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "agent.session.models":
            try:
                return self.agent.session_models(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.session.fork":
            try:
                result = self.agent.fork_session(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.session.forked",
                    {
                        "source_session_id": params.get("sessionId") or params.get("session_id"),
                        "child_session_id": result.get("sessionId"),
                        "at_seq": params.get("atSeq") if params.get("atSeq") is not None else params.get("at_seq"),
                    },
                    session_id=params.get("sessionId") or params.get("session_id"),
                )
            )
            return result
        if method == "agent.session.select_model":
            try:
                return self.agent.select_model(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.workspaces":
            try:
                return self.agent.list_workspaces(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.workspace.create":
            path = _workspace_path_param(params.get("path"))
            try:
                self.workspace.inspect(path)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
            try:
                result = self.agent.create_workspace({"path": path})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            workspace = result.get("workspace") if isinstance(result, dict) else {}
            self.events.publish(
                EventEnvelope(
                    "agent.workspace.registered",
                    {
                        "workspace_id": workspace.get("id") if isinstance(workspace, dict) else None,
                        "title": workspace.get("title") if isinstance(workspace, dict) else None,
                        "created": bool(result.get("created")) if isinstance(result, dict) else False,
                    },
                )
            )
            return result
        if method == "workspace.inspect":
            path = _workspace_path_param(params.get("path"))
            try:
                return self.workspace.inspect(path)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
        if method == "workspace.worktree.preview":
            source_path = _workspace_path_param(params.get("source_path") or params.get("path"))
            destination_path = _workspace_path_param(params.get("destination_path") or params.get("destination"))
            branch = _workspace_branch_param(params.get("branch"))
            try:
                result = self.workspace.preview_worktree(source_path, destination_path, branch)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.worktree.previewed",
                    {
                        "source_workspace_id": result.get("source", {}).get("id"),
                        "worktree_id": result.get("worktree", {}).get("id"),
                        "branch": result.get("worktree", {}).get("branch"),
                        "source_head": result.get("source", {}).get("head"),
                        "source_dirty": bool(result.get("source", {}).get("dirty")),
                        "preview_sha256": hashlib.sha256(str(result.get("preview_token") or "").encode("utf-8")).hexdigest(),
                    },
                )
            )
            return result
        if method == "workspace.worktree.create":
            preview_token = params.get("preview_token")
            if (
                params.get("approved") is not True
                or not isinstance(preview_token, str)
                or re.fullmatch(r"[0-9a-f]{64}", preview_token) is None
            ):
                raise JsonRpcError(-32031, "worktree creation requires a fresh preview and explicit approval")
            source_path = _workspace_path_param(params.get("source_path") or params.get("path"))
            destination_path = _workspace_path_param(params.get("destination_path") or params.get("destination"))
            branch = _workspace_branch_param(params.get("branch"))
            confirm_branch = _workspace_branch_param(params.get("confirm_branch"), "confirm_branch")
            confirm_destination = _workspace_path_param(params.get("confirm_destination"))
            try:
                result = self.workspace.create_worktree(
                    source_path,
                    destination_path,
                    branch,
                    approved=True,
                    confirm_branch=confirm_branch,
                    confirm_destination=confirm_destination,
                    preview_token=preview_token,
                )
            except WorkspaceError as exc:
                self.events.publish(
                    EventEnvelope(
                        "workspace.worktree.create_failed",
                        {"branch": branch, "error_type": type(exc).__name__},
                    )
                )
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.worktree.created",
                    {
                        "source_workspace_id": result.get("source", {}).get("id"),
                        "workspace_id": result.get("worktree", {}).get("id"),
                        "branch": result.get("worktree", {}).get("branch"),
                        "head": result.get("worktree", {}).get("head"),
                    },
                )
            )
            return result
        if method == "workspace.checkpoints":
            raw_path = params.get("path")
            path = _workspace_path_param(raw_path) if raw_path not in (None, "") else None
            try:
                return self.workspace.list_checkpoints(path)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
        if method == "workspace.checkpoint.create":
            path = _workspace_path_param(params.get("path"))
            try:
                result = self.workspace.create_checkpoint(path, name=params.get("name") or "Agent checkpoint")
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
            checkpoint = result["checkpoint"]
            self.events.publish(
                EventEnvelope(
                    "workspace.checkpoint.created",
                    {
                        "checkpoint_id": checkpoint.get("id"),
                        "workspace_id": checkpoint.get("workspace_id"),
                        "file_count": checkpoint.get("file_count"),
                        "total_bytes": checkpoint.get("total_bytes"),
                    },
                )
            )
            return result
        if method == "workspace.commit.preview":
            checkpoint_id = _workspace_checkpoint_param(params.get("checkpoint_id") or params.get("id"))
            path = _workspace_path_param(params.get("path"))
            message = _workspace_commit_message_param(params.get("message"))
            try:
                result = self.workspace.preview_commit(checkpoint_id, path=path, message=message)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.commit.previewed",
                    {
                        "checkpoint_id": checkpoint_id,
                        "workspace_id": result.get("checkpoint", {}).get("workspace_id"),
                        "branch": result.get("workspace", {}).get("branch"),
                        "changed_total": result.get("counts", {}).get("changed_total", 0),
                        "message_sha256": result.get("message_sha256"),
                        "preview_sha256": hashlib.sha256(str(result.get("preview_token") or "").encode("utf-8")).hexdigest(),
                    },
                )
            )
            return result
        if method == "workspace.commit":
            checkpoint_id = _workspace_checkpoint_param(params.get("checkpoint_id") or params.get("id"))
            preview_token = params.get("preview_token")
            if (
                params.get("approved") is not True
                or not isinstance(preview_token, str)
                or re.fullmatch(r"[0-9a-f]{64}", preview_token) is None
            ):
                raise JsonRpcError(-32031, "Git commit requires a fresh preview and explicit approval")
            path = _workspace_path_param(params.get("path"))
            message = _workspace_commit_message_param(params.get("message"))
            confirm_branch = _workspace_branch_param(params.get("confirm_branch"), "confirm_branch")
            try:
                result = self.workspace.commit(
                    checkpoint_id,
                    path=path,
                    message=message,
                    approved=True,
                    confirm_branch=confirm_branch,
                    preview_token=preview_token,
                )
            except WorkspaceError as exc:
                self.events.publish(
                    EventEnvelope(
                        "workspace.commit.failed",
                        {"checkpoint_id": checkpoint_id, "branch": confirm_branch, "error_type": type(exc).__name__},
                    )
                )
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.committed",
                    {
                        "checkpoint_id": checkpoint_id,
                        "workspace_id": result.get("workspace", {}).get("id"),
                        "branch": result.get("branch"),
                        "commit": result.get("commit"),
                        "file_count": result.get("file_count"),
                        "pushed": False,
                    },
                )
            )
            return result
        if method == "workspace.checkpoint.diff":
            checkpoint_id = _workspace_checkpoint_param(params.get("checkpoint_id") or params.get("id"))
            raw_path = params.get("path")
            path = _workspace_path_param(raw_path) if raw_path not in (None, "") else None
            try:
                result = self.workspace.diff_checkpoint(checkpoint_id, path=path)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.checkpoint.diffed",
                    {
                        "checkpoint_id": checkpoint_id,
                        "workspace_id": result.get("checkpoint", {}).get("workspace_id"),
                        "changed": bool(result.get("changed")),
                        "changed_total": result.get("counts", {}).get("changed_total", 0),
                    },
                )
            )
            return result
        if method == "workspace.restore.preview":
            checkpoint_id = _workspace_checkpoint_param(params.get("checkpoint_id") or params.get("id"))
            raw_path = params.get("path")
            path = _workspace_path_param(raw_path) if raw_path not in (None, "") else None
            try:
                result = self.workspace.restore_preview(checkpoint_id, path=path)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.restore.previewed",
                    {
                        "checkpoint_id": checkpoint_id,
                        "workspace_id": result.get("checkpoint", {}).get("workspace_id"),
                        "archive_count": result.get("restore", {}).get("archive_count", 0),
                        "write_count": result.get("restore", {}).get("write_count", 0),
                    },
                )
            )
            return result
        if method == "workspace.restore":
            checkpoint_id = _workspace_checkpoint_param(params.get("checkpoint_id") or params.get("id"))
            preview_token = params.get("preview_token")
            if (
                params.get("approved") is not True
                or params.get("confirm_checkpoint") != checkpoint_id
                or not isinstance(preview_token, str)
                or re.fullmatch(r"[0-9a-f]{64}", preview_token) is None
            ):
                raise JsonRpcError(-32031, "workspace restore requires a fresh preview, explicit approval, and exact checkpoint confirmation")
            raw_path = params.get("path")
            path = _workspace_path_param(raw_path) if raw_path not in (None, "") else None
            try:
                result = self.workspace.restore(
                    checkpoint_id,
                    path=path,
                    approved=True,
                    confirm_checkpoint=checkpoint_id,
                    preview_token=preview_token,
                )
            except WorkspaceError as exc:
                self.events.publish(
                    EventEnvelope(
                        "workspace.restore.failed",
                        {"checkpoint_id": checkpoint_id, "error_type": type(exc).__name__},
                    )
                )
                raise JsonRpcError(-32033, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "workspace.restored",
                    {
                        "checkpoint_id": checkpoint_id,
                        "workspace_id": result.get("checkpoint", {}).get("workspace_id"),
                        "pre_restore_checkpoint_id": result.get("pre_restore_checkpoint", {}).get("id"),
                        "changed_total": result.get("diff", {}).get("counts", {}).get("changed_total", 0),
                        "archive_count": len(result.get("archive", {}).get("entries", [])),
                    },
                )
            )
            return result
        if method == "agent.provider.status":
            if not self.agent.supports(AgentCapability.PROVIDER_BRIDGE):
                status = self.agent.status()
                return {
                    "profile": None,
                    "state": "runtime-owned",
                    "ready": bool(status.get("ready")),
                    "runtime_id": self.agent.runtime_id,
                }
            try:
                profile = self._agent_provider_profile(
                    params,
                    required=False,
                    refresh_health=True,
                )
                if profile is not None and profile.get("status") != "available":
                    return {
                        "profile": self._agent_provider_profile_public(profile),
                        "profile_id": profile.get("id"),
                        "state": "unavailable",
                        "ready": False,
                        "runtime_id": self.agent.runtime_id,
                        "reason": "Provider 档案未就绪；请先在模块页测试连接",
                    }
                status = self.agent.provider_status(profile)
            except (AgentRuntimeError, ProviderProfileError) as exc:
                raise JsonRpcError(-32032, str(exc)) from exc
            return {"profile": self._agent_provider_profile_public(profile), **status}
        if method == "agent.provider.sync":
            try:
                profile = self._agent_provider_profile(params, refresh_health=True)
                if profile is None:
                    raise ProviderProfileError("没有可同步的 Sumika Provider 档案")
                if profile.get("status") != "available":
                    raise ProviderProfileError("Provider 档案当前不可用；请在模块页测试连接后再同步到 DSH")
                result = self.agent.sync_provider_profile(profile)
            except (AgentRuntimeError, ProviderProfileError) as exc:
                raise JsonRpcError(-32032, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.provider.synced",
                    {
                        "profile_id": result.get("profile_id"),
                        "route_id": result.get("route_id"),
                        "model": result.get("model"),
                        "changed": bool(result.get("changed")),
                    },
                )
            )
            return {"profile": self._agent_provider_profile_public(profile), **result}
        if method == "agent.session.history":
            try:
                return self.agent.history(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.session.attachment":
            session_id = params.get("sessionId") or params.get("session_id")
            attachment_id = params.get("attachmentId") or params.get("attachment_id")
            for value, label in ((session_id, "sessionId"), (attachment_id, "attachmentId")):
                if (
                    not isinstance(value, (str, int))
                    or isinstance(value, bool)
                    or not str(value).strip()
                    or len(str(value).strip()) > 240
                    or any(ord(char) < 32 or ord(char) == 127 for char in str(value))
                ):
                    raise JsonRpcError(-32602, f"{label} must be a non-empty identifier without control characters")
            try:
                return self.agent.attachment(
                    {"sessionId": str(session_id).strip(), "attachmentId": str(attachment_id).strip()}
                )
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.session.snapshot":
            try:
                return self.agent.snapshot(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.session.retry":
            session_id = _agent_session_id_param(
                params.get("sessionId") or params.get("session_id"),
                "sessionId",
            )
            confirmation = params.get("confirmSessionId")
            if confirmation is None:
                confirmation = params.get("confirm_session_id")
            self.events.publish(
                EventEnvelope(
                    "agent.turn.retry_requested",
                    {
                        "session_id": session_id,
                        "approved": params.get("approved") is True,
                        "confirmed": confirmation == session_id,
                    },
                    session_id=session_id,
                )
            )
            if params.get("approved") is not True or confirmation != session_id:
                self.events.publish(
                    EventEnvelope(
                        "agent.turn.retry_rejected",
                        {
                            "session_id": session_id,
                            "reason": "explicit approval and exact session confirmation are required",
                        },
                        session_id=session_id,
                    )
                )
                raise JsonRpcError(
                    -32031,
                    "retrying an Agent turn requires explicit approval and an exact session id confirmation",
                )
            if not self.agent.supports(AgentCapability.RETRY):
                self.events.publish(
                    EventEnvelope(
                        "agent.turn.retry_rejected",
                        {"session_id": session_id, "reason": "runtime does not support retry"},
                        session_id=session_id,
                    )
                )
                raise JsonRpcError(-32030, "the current Agent runtime does not support retry")

            # Forward only runtime controls.  Approval and confirmation
            # fields belong to this Core policy gate and must never become
            # adapter input that a future harness could interpret differently.
            request = {"sessionId": session_id}
            for key in ("mode", "transport_mode", "queue_mode"):
                if key in params:
                    request[key] = params[key]
            if params.get("workspaceId") is not None:
                request["workspaceId"] = params.get("workspaceId")
            elif params.get("workspace_id") is not None:
                request["workspaceId"] = params.get("workspace_id")
            checkpoint = None
            workspace = None
            if self._agent_workspace_safety_active():
                workspace, workspace_path = self._agent_workspace_binding(
                    dict(request),
                    session_id=session_id,
                )
                try:
                    checkpoint = self.workspace.create_checkpoint(
                        workspace_path,
                        name=f"Agent retry · {session_id[:12]}",
                    )["checkpoint"]
                except WorkspaceError as exc:
                    self.events.publish(
                        EventEnvelope(
                            "agent.turn.retry_rejected",
                            {
                                "session_id": session_id,
                                "workspace_id": workspace.get("id"),
                                "reason": "workspace checkpoint failed",
                                "error_type": type(exc).__name__,
                            },
                            session_id=session_id,
                        )
                    )
                    raise JsonRpcError(-32033, str(exc)) from exc
                request.pop("workspaceId", None)
                request.pop("workspace_id", None)

            try:
                result = self.agent.retry_prompt(request)
            except AgentRuntimeError as exc:
                self.events.publish(
                    EventEnvelope(
                        "agent.turn.retry_rejected",
                        {
                            "session_id": session_id,
                            "workspace_checkpoint_id": checkpoint.get("id") if checkpoint else None,
                            "reason": "runtime rejected retry",
                            "error_type": type(exc).__name__,
                        },
                        session_id=session_id,
                    )
                )
                raise JsonRpcError(-32030, str(exc)) from exc

            # Only forward the adapter's bounded retry receipt.  A future
            # adapter must not accidentally expose its recovered prompt body.
            safe_result: dict[str, Any] = {}
            if isinstance(result, dict):
                for key in ("accepted", "session_id", "source_turn", "mode", "text_length", "id"):
                    value = result.get(key)
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        safe_result[key] = value
            safe_result["session_id"] = session_id
            if checkpoint:
                safe_result["workspace_checkpoint"] = checkpoint
            self.events.publish(
                EventEnvelope(
                    "agent.turn.retry_accepted",
                    {
                        "session_id": session_id,
                        "source_turn": safe_result.get("source_turn"),
                        "mode": safe_result.get("mode"),
                        "text_length": safe_result.get("text_length"),
                        "workspace_checkpoint_id": checkpoint.get("id") if checkpoint else None,
                    },
                    session_id=session_id,
                )
            )
            return safe_result
        if method == "agent.task.projections":
            raw_limit = params.get("limit", 24)
            if not isinstance(raw_limit, int) or isinstance(raw_limit, bool) or raw_limit < 1 or raw_limit > 64:
                raise JsonRpcError(-32602, "agent task projection limit must be between 1 and 64")
            return self.agent_tasks.project(limit=raw_limit)
        if method == "agent.session.queue":
            try:
                return self.agent.queue(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.session.update_queue":
            action = params.get("action") or params.get("kind")
            if isinstance(action, dict):
                action_kind = action.get("kind")
                if action_kind == "edit":
                    content = action.get("content")
                    text = " ".join(
                        str(block.get("text") or "").strip()
                        for block in content
                        if isinstance(content, list) and isinstance(block, dict) and block.get("type") == "text"
                    ).strip()
                    params = {**params, "kind": "edit", "text": text}
                elif action_kind in {"remove", "steer"}:
                    params = {**params, "kind": action_kind}
            action_kind = str(params.get("kind") or params.get("action") or "").strip().lower()
            if action_kind not in {"edit", "remove", "steer"}:
                raise JsonRpcError(-32602, "queue action must be edit, remove, or steer")
            try:
                result = self.agent.update_queue(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.session.queue.updated",
                    {
                        "session_id": result.get("session_id"),
                        "item_id": result.get("item_id"),
                        "action": result.get("action"),
                        "accepted": bool(result.get("accepted")),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "agent.session.prompt":
            request = dict(params)
            checkpoint = None
            workspace = None
            requested_mode = str(request.get("mode") or "execute").strip().lower()
            if requested_mode == "readonly" and not self.agent.supports(AgentCapability.READONLY):
                raise JsonRpcError(-32030, "the current Agent runtime does not support readonly mode")
            if self._agent_workspace_safety_active():
                session_id = request.get("sessionId") or request.get("session_id")
                if (
                    not isinstance(session_id, (str, int))
                    or isinstance(session_id, bool)
                    or not str(session_id).strip()
                    or len(str(session_id).strip()) > 240
                    or any(ord(char) < 32 or ord(char) == 127 for char in str(session_id))
                ):
                    raise JsonRpcError(-32602, "sessionId must be a non-empty identifier without control characters")
                session_id = str(session_id).strip()
                workspace, workspace_path = self._agent_workspace_binding(
                    request,
                    session_id=session_id,
                )
                if requested_mode == "execute":
                    try:
                        checkpoint = self.workspace.create_checkpoint(
                            workspace_path,
                            name=f"Agent execute · {session_id[:12]}",
                        )["checkpoint"]
                    except WorkspaceError as exc:
                        self.events.publish(
                            EventEnvelope(
                                "agent.turn.rejected",
                                {
                                    "session_id": session_id,
                                    "workspace_id": workspace.get("id"),
                                    "reason": "workspace checkpoint failed",
                                    "error_type": type(exc).__name__,
                                },
                                session_id=session_id,
                            )
                        )
                        raise JsonRpcError(-32033, str(exc)) from exc
                    self.events.publish(
                        EventEnvelope(
                            "workspace.checkpoint.created",
                            {
                                "checkpoint_id": checkpoint.get("id"),
                                "workspace_id": checkpoint.get("workspace_id"),
                                "file_count": checkpoint.get("file_count"),
                                "total_bytes": checkpoint.get("total_bytes"),
                                "trigger": "agent.execute",
                            },
                            session_id=session_id,
                        )
                    )
                    # The checkpoint is an internal Core safety detail; do
                    # not forward the workspace fields to the adapter for an
                    # Execute request. Plan requests retain the verified
                    # workspaceId so a Workspace-capable Harness can apply
                    # its own session-scoped policy.
                    request.pop("workspaceId", None)
                    request.pop("workspace_id", None)
            try:
                result = self.agent.prompt(request)
            except AgentRuntimeError as exc:
                self.events.publish(
                    EventEnvelope(
                        "agent.turn.rejected",
                        {
                            "session_id": request.get("sessionId") or request.get("session_id"),
                            "workspace_checkpoint_id": checkpoint.get("id") if checkpoint else None,
                            "reason": redact_text(str(exc)),
                        },
                    )
                )
                raise JsonRpcError(-32030, str(exc)) from exc
            if checkpoint:
                result = {**result, "workspace_checkpoint": checkpoint}
            self.events.publish(
                EventEnvelope(
                    "agent.turn.started",
                    {
                        "session_id": request.get("sessionId") or request.get("session_id"),
                        "workspace_id": workspace.get("id") if workspace else None,
                        "workspace_checkpoint_id": checkpoint.get("id") if checkpoint else None,
                    },
                    session_id=request.get("sessionId") or request.get("session_id"),
                )
            )
            return result
        if method == "agent.session.cancel":
            try:
                result = self.agent.cancel(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(EventEnvelope("agent.turn.cancelled", {"session_id": params.get("sessionId") or params.get("session_id")}))
            return result
        if method == "agent.subagent.list":
            try:
                return self.agent.list_subagents(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.subagent.history":
            try:
                return self.agent.subagent_history(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.subagent.prompt":
            try:
                result = self.agent.prompt_subagent(params)
            except AgentRuntimeError as exc:
                self.events.publish(
                    EventEnvelope(
                        "agent.subagent.prompt.rejected",
                        {
                            "parent_session_id": params.get("parentSessionId") or params.get("parent_session_id"),
                            "child_session_id": params.get("childSessionId") or params.get("child_session_id"),
                            "reason": redact_text(str(exc)),
                        },
                    )
                )
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.subagent.prompt.accepted",
                    {
                        "parent_session_id": result.get("parent_session_id"),
                        "child_session_id": result.get("child_session_id"),
                        "message_id": result.get("message_id"),
                    },
                    session_id=result.get("parent_session_id"),
                )
            )
            return result
        if method == "agent.subagent.interrupt":
            try:
                result = self.agent.interrupt_subagent(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.subagent.interrupt.accepted",
                    {
                        "parent_session_id": result.get("parent_session_id"),
                        "child_session_id": result.get("child_session_id"),
                    },
                    session_id=result.get("parent_session_id"),
                )
            )
            return result
        if method.startswith("agent.goal."):
            action = method.removeprefix("agent.goal.")
            if action not in {"create", "edit", "pause", "resume", "complete", "clear"}:
                raise JsonRpcError(-32601, "unknown Agent goal method")
            try:
                result = self.agent.goal_action(action, params)
            except AgentRuntimeError as exc:
                self.events.publish(
                    EventEnvelope(
                        "agent.goal.rejected",
                        {
                            "action": action,
                            "session_id": params.get("sessionId") or params.get("session_id"),
                            "reason": redact_text(str(exc)),
                        },
                    )
                )
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.goal.changed",
                    {
                        "action": action,
                        "session_id": params.get("sessionId") or params.get("session_id"),
                        "goal_id": result.get("ref", {}).get("id") if isinstance(result.get("ref"), dict) else None,
                        "revision": result.get("ref", {}).get("revision") if isinstance(result.get("ref"), dict) else None,
                        "cleared": bool(result.get("cleared")),
                    },
                    session_id=params.get("sessionId") or params.get("session_id"),
                )
            )
            return result
        if method == "agent.mcp.inventory":
            try:
                return self.agent.mcp_inventory(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.mcp.catalog":
            try:
                return self.agent.mcp_catalog(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method in {"agent.skills.catalog", "agent.skill.catalog"}:
            refresh = bool(params.get("refresh", False))
            try:
                return {
                    "skills": self.skills.list(refresh=refresh),
                    "default_path_labels": self.skills.default_path_labels(),
                    "metadata_only": True,
                }
            except SkillCatalogError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method in {"agent.skills.discover", "agent.skill.discover"}:
            raw_paths = params.get("paths")
            try:
                paths = _skill_paths_param(raw_paths) if raw_paths is not None else None
                discovered = self.skills.discover(paths)
            except (SkillCatalogError, TypeError, ValueError) as exc:
                self.events.publish(EventEnvelope("agent.skill.discovery.failed", {"error_type": type(exc).__name__}))
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.skill.discovered",
                    {"count": len(discovered), "candidates": [_skill_summary(item) for item in discovered]},
                )
            )
            return {"skills": discovered, "count": len(discovered), "metadata_only": True}
        if method in {"agent.skills.approve", "agent.skill.approve", "agent.skills.revoke", "agent.skill.revoke"}:
            candidate_id = str(params.get("candidate_id") or params.get("candidateId") or params.get("id") or "").strip()
            if (
                params.get("approved") is not True
                or params.get("confirm_skill_id") != candidate_id
                or not candidate_id
            ):
                raise JsonRpcError(
                    -32031,
                    "changing a Skill registration requires explicit approval and an exact candidate id confirmation",
                )
            try:
                if method.endswith(".approve"):
                    result = self.skills.approve(candidate_id)
                    event_type = "agent.skill.approved"
                else:
                    result = self.skills.revoke(candidate_id)
                    event_type = "agent.skill.revoked"
            except SkillCatalogError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope(event_type, {"skill": _skill_summary(result)}))
            return result
        if method == "agent.mcp.configurations":
            preset = _agent_preset_id_param(
                params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
                "agentPreset",
            )
            try:
                return self.agent.list_mcp_configurations({"agentPreset": preset})
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.mcp.configuration.preview":
            preset = _agent_preset_id_param(
                params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
                "agentPreset",
            )
            action = str(params.get("action") or "upsert").strip().lower()
            configuration = params.get("configuration")
            if action not in {"upsert", "remove"} or not isinstance(configuration, dict):
                raise JsonRpcError(-32602, "MCP preview requires an upsert/remove action and configuration object")
            request = {
                "agentPreset": preset,
                "action": action,
                "configuration": configuration,
            }
            try:
                result = self.agent.preview_mcp_configuration(request)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.mcp.configuration.previewed",
                    {
                        "agent_preset": preset,
                        "server_name": result.get("server_name"),
                        "change": result.get("change"),
                        "requires_approval": result.get("requires_approval") is True,
                    },
                )
            )
            return result
        if method == "agent.mcp.configuration.apply":
            preset = _agent_preset_id_param(
                params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
                "agentPreset",
            )
            token = params.get("previewToken") or params.get("preview_token")
            if (
                params.get("approved") is not True
                or params.get("confirm_agent_preset") != preset
                or not isinstance(token, str)
                or not token.strip()
                or len(token.strip()) > 256
            ):
                raise JsonRpcError(
                    -32031,
                    "applying MCP configuration requires approval, the exact preset id, and a preview token",
                )
            try:
                result = self.agent.apply_mcp_configuration(
                    {
                        "agentPreset": preset,
                        "previewToken": token.strip(),
                        "credentialValue": params.get("credentialValue"),
                    }
                )
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.mcp.configuration.applied",
                    {
                        "agent_preset": preset,
                        "server_name": result.get("server_name"),
                        "change": result.get("change"),
                        "applied": result.get("applied") is True,
                        "mountable": result.get("mountable") is True,
                        "backup_retained": result.get("backup_retained") is True,
                        "credential_changed": result.get("credential_changed") is True,
                        "credential_removed": result.get("credential_removed") is True,
                        "restart_required": result.get("restart_required") is True,
                    },
                )
            )
            return result
        if method in {"agent.skills", "agent.mcp", "agent.subagents", "agent.commands"}:
            try:
                values = self.agent.list_capabilities(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            key = method.removeprefix("agent.")
            return values.get(key, {"available": False})
        if method == "agent.interactions":
            try:
                return self.agent.interactions(params)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
        if method == "agent.approval.respond":
            try:
                result = self.agent.respond_interaction(
                    {
                        "rpcId": params.get("rpcId") or params.get("rpc_id"),
                        "sessionId": params.get("sessionId") or params.get("session_id"),
                        "approvalId": params.get("approvalId") or params.get("approval_id"),
                        "outcome": params.get("outcome"),
                    }
                )
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.approval.decided",
                    {
                        "request_id": params.get("rpcId") or params.get("rpc_id"),
                        "decision": params.get("outcome"),
                    },
                    session_id=params.get("sessionId") or params.get("session_id"),
                )
            )
            return result
        if method == "agent.question.respond":
            request_id = params.get("rpcId") or params.get("rpc_id")
            session_id = params.get("sessionId") or params.get("session_id")
            answer = params.get("answer")
            plan_approved = False
            checkpoint = None
            workspace = None
            if self._agent_workspace_safety_active():
                try:
                    plan_approved = self._agent_plan_review_approved(
                        request_id,
                        session_id,
                        answer,
                    )
                except AgentRuntimeError as exc:
                    raise JsonRpcError(-32030, str(exc)) from exc
                if plan_approved:
                    workspace, workspace_path = self._agent_workspace_binding(
                        params,
                        session_id=str(session_id),
                    )
                    try:
                        checkpoint = self.workspace.create_checkpoint(
                            workspace_path,
                            name=f"Agent plan approval · {str(session_id)[:12]}",
                        )["checkpoint"]
                    except WorkspaceError as exc:
                        self.events.publish(
                            EventEnvelope(
                                "agent.plan.approval_rejected",
                                {
                                    "session_id": session_id,
                                    "workspace_id": workspace.get("id"),
                                    "reason": "workspace checkpoint failed",
                                    "error_type": type(exc).__name__,
                                },
                                session_id=session_id,
                            )
                        )
                        raise JsonRpcError(-32033, str(exc)) from exc
                    self.events.publish(
                        EventEnvelope(
                            "workspace.checkpoint.created",
                            {
                                "checkpoint_id": checkpoint.get("id"),
                                "workspace_id": checkpoint.get("workspace_id"),
                                "file_count": checkpoint.get("file_count"),
                                "total_bytes": checkpoint.get("total_bytes"),
                                "trigger": "agent.plan.approval",
                            },
                            session_id=session_id,
                        )
                    )
            try:
                result = self.agent.respond_interaction(
                    {
                        "rpcId": request_id,
                        "sessionId": session_id,
                        "answer": answer,
                    }
                )
            except AgentRuntimeError as exc:
                if checkpoint:
                    self.events.publish(
                        EventEnvelope(
                            "agent.plan.approval_rejected",
                            {
                                "session_id": session_id,
                                "workspace_id": workspace.get("id") if workspace else None,
                                "workspace_checkpoint_id": checkpoint.get("id"),
                                "reason": "runtime rejected plan approval",
                                "error_type": type(exc).__name__,
                            },
                            session_id=session_id,
                        )
                    )
                raise JsonRpcError(-32030, str(exc)) from exc
            if checkpoint:
                result = {**result, "workspace_checkpoint": checkpoint}
            answers = answer.get("answers", []) if isinstance(answer, dict) else []
            self.events.publish(
                EventEnvelope(
                    "agent.question.answered",
                    {
                        "request_id": request_id,
                        "answer_count": len(answers),
                        "plan_approved": plan_approved,
                        "workspace_checkpoint_id": checkpoint.get("id") if checkpoint else None,
                    },
                    session_id=session_id,
                )
            )
            return result
        if method == "agent.question.cancel":
            request_id = params.get("rpcId") or params.get("rpc_id")
            session_id = params.get("sessionId") or params.get("session_id")
            try:
                result = self.agent.cancel_interaction(
                    {
                        "rpcId": request_id,
                        "sessionId": session_id,
                    }
                )
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.question.cancelled",
                    {
                        "request_id": request_id,
                        "cancelled": result.get("cancelled") is True,
                    },
                    session_id=session_id,
                )
            )
            return result
        if method == "agent.event.ingest":
            payload = params.get("event") if isinstance(params.get("event"), dict) else params
            if not isinstance(payload, dict):
                raise JsonRpcError(-32602, "event must be an object")
            try:
                event = self.agent.normalize_event(payload)
            except AgentRuntimeError as exc:
                raise JsonRpcError(-32030, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.event",
                    _redact_agent_payload(event),
                    session_id=event.get("session_id"),
                )
            )
            return event
        if method == "browser.status":
            return self.browser.status()
        if method == "browser.policy.evaluate":
            try:
                result = self.browser.evaluate_policy(params)
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            # Policy RPC is consumed by the local DSH bridge.  Do not echo
            # caller-controlled metadata beyond the validated projection.
            decision = str(result.get("decision") or "deny")
            event_type = {
                "allow": "browser.policy.allowed",
                "ask": "browser.policy.waiting_approval",
                "deny": "browser.policy.denied",
            }.get(decision, "browser.policy.denied")
            self.events.publish(
                EventEnvelope(
                    event_type,
                    {
                        "audit_id": result.get("audit_id"),
                        "tool_name": result.get("tool_name"),
                        "action": result.get("action"),
                        "session_id": result.get("session_id"),
                        "domain": result.get("domain"),
                        "decision": decision,
                        "value_length": result.get("value_length", 0),
                        "sensitive": bool(result.get("sensitive")),
                        "requires_human": bool(result.get("requires_human")),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.profiles":
            return {
                "profiles": self.browser.list_profiles(
                    include_archived=bool(params.get("include_archived"))
                )
            }
        if method == "browser.profile.create":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "creating a named browser profile requires explicit approval")
            try:
                result = self.browser.create_profile(
                    name=str(params.get("name") or ""),
                    character_id=str(params["character_id"]) if params.get("character_id") else None,
                    agent_id=str(params["agent_id"]) if params.get("agent_id") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.profile.created",
                    {"profile": _redact_browser_payload(result)},
                )
            )
            return result
        if method in {"browser.profile.archive", "browser.profile.restore"}:
            if not params.get("approved"):
                raise JsonRpcError(-32031, "changing a named browser profile requires explicit approval")
            try:
                if method.endswith("archive"):
                    result = self.browser.archive_profile(str(params.get("profile_id") or ""))
                    event_type = "browser.profile.archived"
                else:
                    result = self.browser.restore_profile(str(params.get("profile_id") or ""))
                    event_type = "browser.profile.restored"
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(event_type, {"profile": _redact_browser_payload(result)})
            )
            return result
        if method == "browser.sessions":
            return {"sessions": self.browser.list_sessions()}
        if method == "browser.session.create":
            try:
                result = self.browser.create_session(
                    profile=str(params.get("profile") or "temporary"),
                    profile_id=str(params["profile_id"]) if params.get("profile_id") else None,
                    character_id=str(params["character_id"]) if params.get("character_id") else None,
                    agent_id=str(params["agent_id"]) if params.get("agent_id") else None,
                    approved=bool(params.get("approved")),
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.session.created", {"session": _redact_browser_payload(result)}))
            return result
        if method == "browser.session.close":
            try:
                result = self.browser.close_session(str(params.get("session_id") or params.get("id") or ""))
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.session.closed", result))
            return result
        if method == "browser.tabs":
            try:
                scope = str(params.get("scope") or "").strip().lower() or None
                if scope not in {None, "user", "agent", "all"}:
                    raise JsonRpcError(-32602, "browser tab scope must be user, agent, or all")
                return self.browser.list_tabs(str(params.get("session_id") or ""), scope=scope)
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
        if method == "browser.tab.create":
            try:
                result = self.browser.create_tab(
                    str(params.get("session_id") or ""),
                    url=str(params["url"]) if params.get("url") is not None else None,
                    approved=bool(params.get("approved")),
                    active=bool(params.get("active", True)),
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.tab.created" if result.get("executed") else "browser.tab.waiting_approval",
                    {
                        "session_id": result.get("session_id"),
                        "executed": bool(result.get("executed")),
                        "domain": (result.get("policy") or {}).get("domain"),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.tab.select":
            try:
                result = self.browser.select_tab(
                    str(params.get("session_id") or ""),
                    tab_id=str(params.get("tab_id") or ""),
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.tab.selected", {"session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "executed": bool(result.get("executed"))}, session_id=result.get("session_id")))
            return result
        if method == "browser.tab.close":
            try:
                result = self.browser.close_tab(
                    str(params.get("session_id") or ""),
                    tab_id=str(params.get("tab_id") or ""),
                    approved=bool(params.get("approved")),
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.tab.closed" if result.get("executed") else "browser.tab.close.waiting_approval",
                    {"session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "executed": bool(result.get("executed"))},
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.observe":
            try:
                result = self.browser.observe_session(
                    str(params.get("session_id") or ""),
                    tab_id=str(params["tab_id"]) if params.get("tab_id") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.observed",
                    {
                        "session_id": result.get("session_id"),
                        "tab_id": result.get("tab_id"),
                        "ready": bool(result.get("ready")),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.snapshot":
            try:
                result = self.browser.snapshot_session(
                    str(params.get("session_id") or ""),
                    tab_id=str(params["tab_id"]) if params.get("tab_id") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.snapshot", {"session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "ready": bool(result.get("ready"))}, session_id=result.get("session_id")))
            return result
        if method == "browser.screenshot":
            try:
                result = self.browser.screenshot_session(
                    str(params.get("session_id") or ""),
                    tab_id=str(params["tab_id"]) if params.get("tab_id") else None,
                    ref=str(params["ref"]) if params.get("ref") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.screenshot", {"session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "ready": bool(result.get("ready"))}, session_id=result.get("session_id")))
            return result
        if method in {"browser.console", "browser.network"}:
            try:
                since = params.get("since")
                if since is not None:
                    since = int(since)
                    if since < 0:
                        raise ValueError
                limit = int(params.get("limit", 50))
                if limit < 1 or limit > 200:
                    raise ValueError
                kwargs = {
                    "tab_id": str(params["tab_id"]) if params.get("tab_id") else None,
                    "since": since,
                    "limit": limit,
                    "developer_mode": bool(params.get("developer_mode")),
                    "approved": bool(params.get("approved")),
                }
                result = self.browser.read_console(str(params.get("session_id") or ""), **kwargs) if method == "browser.console" else self.browser.read_network(str(params.get("session_id") or ""), **kwargs)
            except ValueError as exc:
                raise JsonRpcError(-32602, "since must be non-negative and limit must be between 1 and 200") from exc
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.console.read" if method == "browser.console" else "browser.network.read",
                    {"session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "executed": bool(result.get("executed")), "requires_developer_mode": bool(result.get("requires_developer_mode"))},
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.navigate":
            url = str(params.get("url") or "").strip()
            try:
                result = self.browser.navigate_session(
                    str(params.get("session_id") or ""),
                    url=url,
                    approved=bool(params.get("approved")),
                    tab_id=str(params["tab_id"]) if params.get("tab_id") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.navigated" if result.get("executed") else "browser.navigation.waiting_approval",
                    {
                        "session_id": result.get("session_id"),
                        "domain": result.get("domain") or (result.get("policy") or {}).get("domain"),
                        "executed": bool(result.get("executed")),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.action.execute":
            values = params.get("values")
            if values is not None and not isinstance(values, list):
                raise JsonRpcError(-32602, "browser action values must be an array")
            try:
                result = self.browser.execute_action(
                    str(params.get("session_id") or ""),
                    action=str(params.get("action") or ""),
                    target=str(params["target"]) if params.get("target") is not None else None,
                    value=str(params["value"]) if params.get("value") is not None else None,
                    values=[str(entry) for entry in values] if isinstance(values, list) else None,
                    key=str(params["key"]) if params.get("key") is not None else None,
                    approved=bool(params.get("approved")),
                    tab_id=str(params["tab_id"]) if params.get("tab_id") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.action.executed" if result.get("executed") else "browser.action.waiting_approval",
                    {
                        "session_id": result.get("session_id"),
                        "action": result.get("action"),
                        "executed": bool(result.get("executed")),
                        "requires_human": bool(result.get("requires_human")),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "browser.action.check":
            try:
                return self.browser.check_action(
                    session_id=str(params.get("session_id") or ""),
                    action=str(params.get("action") or ""),
                    domain=str(params["domain"]) if params.get("domain") else None,
                    approved=bool(params.get("approved")),
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
        if method == "browser.request_help":
            try:
                result = self.browser.request_help(session_id=str(params.get("session_id") or ""), domain=str(params.get("domain") or ""), reason=str(params.get("reason") or ""))
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.request_help",
                    {
                        "session_id": result["session_id"],
                        "domain": result["domain"],
                        "reason_length": len(str(result.get("reason") or "")),
                        "credentials_excluded": True,
                    },
                )
            )
            return result
        if method == "browser.policy.request_help":
            try:
                help_params = _browser_external_help_params(params)
            except ValueError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            try:
                policy = self.browser.evaluate_policy(
                    {
                        "tool_name": "browser_request_help",
                        "action": "request_help",
                        "session_id": help_params["session_id"],
                        "domain": help_params["domain"],
                        "current_domain": help_params["domain"],
                        "target_kind": "none",
                        "value_length": 0,
                        "sensitive": False,
                        "session_known": True,
                        "new_tab": False,
                    }
                )
                if policy.get("decision") != "allow":
                    raise BrowserRuntimeError(str(policy.get("reason") or "browser policy denied human takeover"))
                result = self.browser.request_external_help(
                    session_id=help_params["session_id"],
                    domain=help_params["domain"],
                    reason=help_params["reason"],
                    title=help_params["title"],
                    targets=help_params["targets"],
                    timeout=help_params["timeout_ms"] / 1000.0,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.request_help",
                    {
                        "session_id": result["session_id"],
                        "domain": result.get("domain"),
                        "outcome": result.get("outcome"),
                        "requires_human": True,
                        "credentials_excluded": True,
                    },
                    session_id=result["session_id"],
                )
            )
            return result
        if method == "browser.download.quarantine":
            try:
                result = self.browser.quarantine_download(session_id=str(params.get("session_id") or ""), path=str(params.get("path") or ""), source_url=str(params.get("source_url") or ""), content_type=str(params["content_type"]) if params.get("content_type") else None)
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.download.quarantined", {"download_id": result["id"], "sha256": result["sha256"], "source_url": result["source_url"]}))
            return result
        if method == "browser.downloads":
            return {"downloads": self.browser.list_downloads()}
        if method == "browser.download.release":
            try:
                result = self.browser.release_download(
                    str(params.get("download_id") or ""),
                    approved=bool(params.get("approved")),
                    workspace_path=str(params["workspace_path"]) if params.get("workspace_path") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.download.released", {"download_id": result["id"], "approved": True}))
            return result
        if method == "evolution.registry.list":
            return self.evolution_registry.list()
        if method == "evolution.registry.check":
            return self.evolution_registry.check()
        if method == "privacy.status":
            return self._privacy_status()
        if method == "provider.list":
            # Refresh reachability so the UI never presents an unverified local
            # endpoint as ready. Health responses contain no secrets.
            self.providers.health()
            return [info.to_dict() for info in self.providers.list()]
        if method == "provider.health":
            return self.providers.health()
        if method == "provider.profile.templates":
            return self.provider_profiles.templates()
        if method == "provider.profile.list":
            active_profile_id = self._active_provider_profile_id()
            if active_profile_id:
                try:
                    self.provider_profiles.health(active_profile_id)
                except ProviderProfileError:
                    pass
            return self._provider_profile_list(
                include_archived=bool(params.get("include_archived", False))
            )
        if method == "provider.profile.get":
            try:
                return self.provider_profiles.get(str(params.get("profile_id") or params.get("id") or ""))
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "provider.profile.save":
            profile_payload = params.get("profile") if isinstance(params.get("profile"), dict) else params
            try:
                profile = self.provider_profiles.save(profile_payload)
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "provider.profile.saved",
                    {"profile_id": profile["id"], "adapter_id": profile["adapter_id"], "status": profile["status"]},
                )
            )
            return profile
        if method == "provider.profile.health":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            try:
                result = self.provider_profiles.health(profile_id, allow_chat_probe=True)
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "provider.profile.health",
                    {"profile_id": profile_id, "ok": bool(result.get("ok")), "status": result.get("profile", {}).get("status")},
                )
            )
            return result
        if method == "provider.profile.activate":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            try:
                health = self.provider_profiles.health(profile_id, allow_chat_probe=True)
                if not health.get("ok"):
                    raise ProviderProfileError(str(health.get("error") or "Provider profile is not ready"))
                profile = self.provider_profiles.get(profile_id)
                self.modules.update(
                    "llm",
                    enabled=True,
                    implementation_id=str(profile["adapter_id"]),
                    config={"profile_id": profile_id},
                )
                profile = self.provider_profiles.mark_used(profile_id)
            except (ModuleError, ProviderProfileError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "provider.profile.activated",
                    {"profile_id": profile_id, "adapter_id": profile["adapter_id"]},
                )
            )
            return {"profile": profile, "module": self._module("llm"), "privacy": self._privacy_status()}
        if method == "provider.profile.archive":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            if profile_id == self._active_provider_profile_id():
                raise JsonRpcError(-32602, "The active provider profile cannot be archived")
            try:
                profile = self.provider_profiles.archive(profile_id)
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("provider.profile.archived", {"profile_id": profile_id}))
            return profile
        if method == "provider.profile.restore":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            try:
                profile = self.provider_profiles.restore(profile_id)
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("provider.profile.restored", {"profile_id": profile_id}))
            return profile
        if method == "provider.import.preview":
            try:
                return self.provider_imports.preview(
                    str(params.get("raw") or ""),
                    str(params.get("filename") or "") or None,
                )
            except ProviderImportError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "provider.import.save":
            try:
                imported = self.provider_imports.parse(
                    str(params.get("raw") or ""),
                    str(params.get("filename") or "") or None,
                )
                profile = self.provider_profiles.save({**imported.profile, "secrets": imported.secrets})
            except (ProviderImportError, ProviderProfileError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "provider.profile.imported",
                    {"profile_id": profile["id"], "importer_id": imported.importer_id, "status": profile["status"]},
                )
            )
            return {"profile": profile, "preview": imported.preview()}
        if method == "integration.ccswitch.manifest":
            return self.ccswitch_compatibility.manifest()
        if method == "integration.ccswitch.check":
            result = self.ccswitch_compatibility.check()
            self.events.publish(
                EventEnvelope(
                    "integration.compatibility.checked",
                    {"integration": "ccswitch-v1", "status": result.get("status"), "ok": bool(result.get("ok"))},
                )
            )
            return result
        if method == "module.list":
            return self._module_list()
        if method == "plugin.list":
            return self.plugins.list()
        if method == "plugin.discover":
            raw_paths = params.get("paths", self.plugin_paths)
            try:
                paths = _plugin_paths_param(raw_paths)
                discovered = self.plugins.discover(paths)
            except (PluginCatalogError, TypeError, ValueError) as exc:
                self.events.publish(EventEnvelope("plugin.discovery.failed", {"error": str(exc)}))
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "plugin.discovered",
                    {"count": len(discovered), "candidates": [_plugin_summary(item) for item in discovered]},
                )
            )
            self._sync_plugin_providers()
            return discovered
        if method == "plugin.approve":
            candidate_id = str(params.get("candidate_id") or params.get("id") or "")
            try:
                approved = self.plugins.approve(candidate_id)
            except PluginCatalogError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("plugin.approved", {"plugin": _plugin_summary(approved)}))
            self._sync_plugin_providers()
            return approved
        if method in {"plugin.revoke", "plugin.reject"}:
            candidate_id = str(params.get("candidate_id") or params.get("id") or "")
            try:
                revoked = self.plugins.revoke(candidate_id)
            except PluginCatalogError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("plugin.revoked", {"plugin": _plugin_summary(revoked)}))
            self._sync_plugin_providers()
            return revoked
        if method == "plugin.configure":
            candidate_id = str(params.get("candidate_id") or params.get("id") or "")
            launcher = params.get("launcher")
            if not isinstance(launcher, dict):
                raise JsonRpcError(-32602, "launcher must be an object")
            try:
                configured = self.plugins.configure_launcher(candidate_id, launcher)
            except PluginCatalogError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("plugin.configured", {"plugin": _plugin_summary(configured)}))
            self._sync_plugin_providers()
            return configured
        if method == "plugin.run":
            candidate_id = str(params.get("candidate_id") or params.get("id") or "")
            try:
                prepared = self.plugins.prepare_tool_run(candidate_id)
                execution = self.tools.run_configured(
                    tool_id=f"plugin:{candidate_id}",
                    input=params.get("input"),
                    approved=params.get("approved", False),
                    config=prepared["launcher"],
                )
            except PluginCatalogError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            except ToolRuntimeError as exc:
                raise JsonRpcError(-32014, str(exc)) from exc
            plugin = self.storage.get_plugin_registration(candidate_id)
            return {"plugin": _plugin_summary(plugin or {}), "execution": execution}
        if method == "module.update":
            module_id = str(params.get("module_id") or "")
            enabled = params.get("enabled") if isinstance(params.get("enabled"), bool) else None
            implementation_id = params.get("implementation_id")
            if implementation_id is not None:
                implementation_id = str(implementation_id)
            config = params.get("config") if "config" in params else None
            if config is not None and not isinstance(config, dict):
                raise JsonRpcError(-32602, "config must be an object")
            if module_id == "llm" and enabled is True:
                current_llm = self.storage.get_module_setting("llm") or {}
                selected_adapter = implementation_id or current_llm.get("implementation_id")
                profile_id = (config or {}).get("profile_id")
                if profile_id is None:
                    profile_id = (current_llm.get("config") or {}).get("profile_id")
                profile = self.storage.get_provider_profile(str(profile_id)) if profile_id else None
                if selected_adapter == "openai-compatible" and profile is not None:
                    try:
                        # Re-check the passive model catalogue before enabling
                        # the module; a stale SQLite "available" flag must not
                        # make a stopped endpoint look usable.
                        self.provider_profiles.health(str(profile_id))
                    except ProviderProfileError as exc:
                        raise JsonRpcError(-32602, str(exc)) from exc
                    profile = self.storage.get_provider_profile(str(profile_id))
                if selected_adapter == "openai-compatible" and (not profile or profile.get("status") != "available"):
                    raise JsonRpcError(-32602, "Test and activate a ready provider profile before enabling LLM")
            try:
                result = self.modules.update(
                    module_id,
                    enabled=enabled,
                    implementation_id=implementation_id,
                    config=config,
                )
            except (KeyError, ModuleError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.audio.reconcile()
            self.vision.reconcile()
            result = self._decorate_module(result)
            self.events.publish(EventEnvelope("module.changed", {"module": result}))
            return result
        if method == "audio.status":
            return self.audio.status()
        if method == "audio.permission.set":
            permission_id = str(params.get("permission_id") or params.get("permission") or "")
            try:
                return self.audio.set_permission(permission_id, params.get("granted"))
            except AudioRuntimeError as exc:
                raise JsonRpcError(-32011, str(exc)) from exc
        if method == "audio.start":
            try:
                return self.audio.start(str(params.get("capability") or ""))
            except AudioRuntimeError as exc:
                raise JsonRpcError(-32011, str(exc)) from exc
        if method == "audio.stop":
            try:
                return self.audio.stop(str(params.get("capability") or ""))
            except AudioRuntimeError as exc:
                raise JsonRpcError(-32011, str(exc)) from exc
        if method == "audio.asr.transcribe":
            try:
                audio = _decode_audio(params.get("audio_base64"))
                return {
                    "text": self.audio.transcribe(
                        audio,
                        sample_rate=int(params.get("sample_rate", 16_000)),
                        channels=int(params.get("channels", 1)),
                        language=str(params["language"]) if params.get("language") else None,
                    )
                }
            except (AudioRuntimeError, ValueError, TypeError, binascii.Error) as exc:
                raise JsonRpcError(-32011, str(exc)) from exc
        if method == "audio.tts.synthesize":
            try:
                result = self.audio.synthesize(
                    str(params.get("text") or ""),
                    voice=str(params["voice"]) if params.get("voice") else None,
                    language=str(params["language"]) if params.get("language") else None,
                    sample_rate=int(params["sample_rate"]) if params.get("sample_rate") is not None else None,
                )
                return {
                    "audio_base64": base64.b64encode(result.audio).decode("ascii"),
                    "content_type": result.content_type,
                    "sample_rate": result.sample_rate,
                }
            except (AudioRuntimeError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32011, str(exc)) from exc
        if method == "audio.vad.detect":
            try:
                audio = _decode_audio(params.get("audio_base64"))
                return {
                    "speech": self.audio.detect(
                        audio,
                        sample_rate=int(params.get("sample_rate", 16_000)),
                        channels=int(params.get("channels", 1)),
                    )
                }
            except (AudioRuntimeError, ValueError, TypeError, binascii.Error) as exc:
                raise JsonRpcError(-32011, str(exc)) from exc
        if method == "memory.status":
            return self.memory.status()
        if method in {"memory.list", "memory.search"}:
            try:
                return self.memory.list(
                    str(params.get("character_id") or "sumika"),
                    category=str(params["category"]) if params.get("category") else None,
                    query=str(params["query"]) if params.get("query") else None,
                    limit=int(params.get("limit", 100)),
                )
            except MemoryRuntimeError as exc:
                raise JsonRpcError(-32012, str(exc)) from exc
        if method == "memory.add":
            try:
                return self.memory.add(
                    character_id=str(params.get("character_id") or "sumika"),
                    category=str(params.get("category") or ""),
                    content=str(params.get("content") or ""),
                    source=str(params.get("source") or "user"),
                    metadata=params.get("metadata") if params.get("metadata") is not None else {},
                )
            except MemoryRuntimeError as exc:
                raise JsonRpcError(-32012, str(exc)) from exc
        if method == "memory.delete":
            try:
                return {"deleted": self.memory.delete(str(params.get("memory_id") or ""))}
            except MemoryRuntimeError as exc:
                raise JsonRpcError(-32012, str(exc)) from exc
        if method == "vision.status":
            return self.vision.status()
        if method == "vision.permission.set":
            permission_id = str(params.get("permission_id") or params.get("permission") or "")
            try:
                return self.vision.set_permission(permission_id, params.get("granted"))
            except VisionRuntimeError as exc:
                raise JsonRpcError(-32013, str(exc)) from exc
        if method == "vision.start":
            try:
                return self.vision.start(str(params.get("source") or ""))
            except VisionRuntimeError as exc:
                raise JsonRpcError(-32013, str(exc)) from exc
        if method == "vision.stop":
            try:
                return self.vision.stop(str(params.get("source") or ""))
            except VisionRuntimeError as exc:
                raise JsonRpcError(-32013, str(exc)) from exc
        if method == "vision.observe":
            try:
                image = _decode_image(params.get("image_base64"))
                prompt = params.get("prompt")
                if prompt is not None and not isinstance(prompt, str):
                    raise ValueError("prompt must be a string")
                return self.vision.observe(
                    str(params.get("source") or ""),
                    image,
                    mime_type=str(params.get("mime_type") or "image/png"),
                    prompt=prompt,
                )
            except (VisionRuntimeError, ValueError, TypeError, binascii.Error) as exc:
                raise JsonRpcError(-32013, str(exc)) from exc
        if method == "tool.run":
            try:
                return self.tools.run(
                    tool_id=str(params["tool_id"]) if params.get("tool_id") is not None else None,
                    input=params.get("input"),
                    approved=params.get("approved", False),
                )
            except ToolRuntimeError as exc:
                raise JsonRpcError(-32014, str(exc)) from exc
        if method == "task.list":
            return self.tasks.list()
        if method == "task.runner.list":
            return self.task_runner.list_handlers()
        if method == "task.run":
            try:
                return self.task_runner.run(
                    str(params.get("task_id") or ""),
                    handler_id=str(params.get("handler_id") or "core-health"),
                    approved=params.get("approved", False),
                )
            except TaskError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "task.get":
            try:
                return self.tasks.get(str(params.get("task_id") or ""))
            except TaskError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "task.create":
            try:
                task = self.tasks.create(
                    title=str(params.get("title") or ""),
                    task_id=str(params["id"]) if params.get("id") else None,
                    status=str(params.get("status", "pending")),
                    autonomy_level=str(params.get("autonomy_level", "L0")),
                    budget=params.get("budget"),
                    character_id=params.get("character_id"),
                    progress=params.get("progress", 0),
                    result=params.get("result"),
                    permissions=params.get("permissions"),
                    logs=params.get("logs"),
                    artifacts=params.get("artifacts"),
                )
            except TaskError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            return task
        if method == "task.update":
            try:
                task = self.tasks.update(
                    str(params.get("task_id") or ""),
                    status=params.get("status"),
                    progress=params.get("progress"),
                    result=params.get("result"),
                    log=params.get("log"),
                    artifact=params.get("artifact"),
                )
            except TaskError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            return task
        if method == "session.list":
            return self.storage.list_sessions()
        if method == "session.create":
            session_id = str(params.get("id") or _safe_id("session"))
            title = str(params.get("title") or "新会话")
            character_id = params.get("character_id")
            return self.storage.create_session(session_id, title, character_id)
        if method == "session.messages":
            session_id = str(params.get("session_id") or "default")
            return self.storage.list_messages(session_id)
        if method == "character.list":
            return self.storage.list_characters()
        if method == "character.create":
            character_id = str(params.get("id") or _safe_id("character"))
            name = str(params.get("name") or "未命名角色")
            config = params.get("config") if isinstance(params.get("config"), dict) else {}
            try:
                _validate_character_name(name)
                config = _validate_character_config(config)
                return self.storage.create_character(character_id, name, config)
            except (ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "character.update":
            character_id = str(params.get("character_id") or params.get("id") or "")
            current = self.storage.get_character(character_id)
            if current is None:
                raise JsonRpcError(-32602, f"Unknown character: {character_id}")
            name = params.get("name")
            if name is not None:
                name = str(name)
                try:
                    _validate_character_name(name)
                except ValueError as exc:
                    raise JsonRpcError(-32602, str(exc)) from exc
            incoming = params.get("config")
            if incoming is not None and not isinstance(incoming, dict):
                raise JsonRpcError(-32602, "config must be an object")
            try:
                config = _merge_character_config(current["config"], incoming)
                config = _validate_character_config(config)
            except (ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            if name is None and incoming is None:
                raise JsonRpcError(-32602, "character.update requires name or config")
            updated = self.storage.update_character(character_id, name=name, config=config)
            if updated is None:
                raise JsonRpcError(-32602, f"Unknown character: {character_id}")
            if self.avatar.active_character_id == character_id:
                self.avatar.restore_character(character_id)
            self.events.publish(EventEnvelope("character.changed", {"character": updated}, character_id=character_id))
            return updated
        if method == "event.list":
            return self.storage.list_events(int(params.get("limit", 100)))
        if method == "snapshot.list":
            return self.storage.list_snapshots()
        if method == "snapshot.get":
            snapshot_id = str(params.get("snapshot_id") or params.get("id") or "")
            snapshot = self.storage.get_snapshot(snapshot_id)
            if snapshot is None:
                raise JsonRpcError(-32602, f"Unknown snapshot: {snapshot_id}")
            return snapshot
        if method == "snapshot.export":
            snapshot_id = str(params.get("snapshot_id") or params.get("id") or "")
            snapshot = self.storage.get_snapshot(snapshot_id)
            if snapshot is None:
                raise JsonRpcError(-32602, f"Unknown snapshot: {snapshot_id}")
            self.events.publish(
                EventEnvelope("snapshot.exported", {"snapshot": self._snapshot_summary(snapshot)})
            )
            return _snapshot_export_package(snapshot)
        if method == "snapshot.import":
            package = params.get("package")
            if not isinstance(package, dict):
                raise JsonRpcError(-32602, "package must be an object")
            imported = package.get("snapshot")
            if not isinstance(imported, dict):
                raise JsonRpcError(-32602, "package.snapshot must be an object")
            payload = imported.get("payload")
            if not isinstance(payload, dict):
                raise JsonRpcError(-32602, "snapshot payload must be an object")
            try:
                _validate_snapshot_export_package(package)
                payload = _sanitize_imported_provider_credentials(payload)
                self.storage.diff_snapshot_state(payload)
                name = str(params.get("name") or imported.get("name") or "导入快照")
                snapshot = self.storage.create_snapshot(_safe_id("snapshot"), name, payload)
            except (ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            summary = self._snapshot_summary(snapshot)
            summary["imported_from_id"] = imported.get("id")
            self.events.publish(EventEnvelope("snapshot.imported", {"snapshot": summary}))
            return summary
        if method == "snapshot.create":
            try:
                scope, target_id = _snapshot_target(params)
                snapshot = self._create_snapshot(
                    str(params.get("name") or "手动快照"),
                    scope=scope,
                    target_id=target_id,
                )
            except (ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            return self._snapshot_summary(snapshot)
        if method == "snapshot.diff":
            snapshot_id = str(params.get("snapshot_id") or params.get("id") or "")
            snapshot = self.storage.get_snapshot(snapshot_id)
            if snapshot is None:
                raise JsonRpcError(-32602, f"Unknown snapshot: {snapshot_id}")
            try:
                return {
                    "snapshot": self._snapshot_summary(snapshot),
                    "diff": self.storage.diff_snapshot_state(snapshot["payload"]),
                }
            except (ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "snapshot.restore":
            snapshot_id = str(params.get("snapshot_id") or params.get("id") or "")
            snapshot = self.storage.get_snapshot(snapshot_id)
            if snapshot is None:
                raise JsonRpcError(-32602, f"Unknown snapshot: {snapshot_id}")
            try:
                diff = self.storage.diff_snapshot_state(snapshot["payload"])
                scope = str(snapshot["payload"]["scope"])
                target_id = snapshot["payload"].get("target_id")
                if scope in {"modules", "system"}:
                    self.modules.validate_snapshot_settings(snapshot["payload"]["tables"].get("module_settings", []))
                    self.provider_profiles.validate_snapshot_profiles(
                        snapshot["payload"]["tables"].get("provider_profiles", [])
                    )
                pre_restore = self._create_snapshot(
                    f"恢复前 · {snapshot['name']}",
                    scope=scope,
                    target_id=target_id,
                )
                restored = self.storage.restore_snapshot_state(snapshot["payload"])
                if scope == "modules" or scope == "system":
                    self._migrate_legacy_provider_config()
                    self.modules.restore_runtime()
                self._ensure_defaults()
                self.audio.reconcile()
                self.vision.reconcile()
                result = {
                    "snapshot": self._snapshot_summary(snapshot),
                    "pre_restore_snapshot": self._snapshot_summary(pre_restore),
                    "diff": diff,
                    "restored": restored,
                }
                self.events.publish(
                    EventEnvelope(
                        "snapshot.restored",
                        {
                            "snapshot_id": snapshot_id,
                            "pre_restore_snapshot_id": pre_restore["id"],
                            "scope": scope,
                            "target_id": target_id,
                            "diff": diff,
                        },
                    )
                )
                return result
            except (ValueError, TypeError, KeyError, ProviderProfileError) as exc:
                self.events.publish(
                    EventEnvelope(
                        "snapshot.restore.failed",
                        {"snapshot_id": snapshot_id, "error": str(exc)},
                    )
                )
                raise JsonRpcError(-32020, str(exc)) from exc
        if method == "avatar.models":
            return self.avatar.list_models()
        if method == "avatar.ignored":
            return self._ignored_avatar_models()
        if method == "avatar.ignored.clear":
            path_value = params.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise JsonRpcError(-32602, "path must not be empty")
            try:
                resolved_path = Path(path_value).expanduser().resolve()
            except OSError as exc:
                raise JsonRpcError(-32602, f"model path is not readable: {path_value}") from exc
            if not self._is_managed_avatar_path(str(resolved_path)):
                raise JsonRpcError(-32602, "only ignored models from assets/avatars can be cleared")
            ignored_paths = self._ignored_avatar_paths()
            if resolved_path not in ignored_paths:
                raise JsonRpcError(-32602, "model path is not currently ignored")
            self._set_avatar_path_ignored(str(resolved_path), False)
            result = {
                "path": str(resolved_path),
                "removed": True,
                "available": resolved_path.is_file(),
            }
            self.events.publish(EventEnvelope("avatar.ignored.cleared", result))
            return result
        if method == "avatar.discover":
            return self._discover_avatar_assets()
        if method == "avatar.import":
            try:
                model = self.avatar.import_model(
                    str(params.get("path") or ""),
                    name=str(params["name"]) if params.get("name") else None,
                    kind=str(params["kind"]) if params.get("kind") else None,
                )
            except AvatarError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self._set_avatar_path_ignored(model["path"], False)
            self.events.publish(EventEnvelope("avatar.model.imported", {"model": model}))
            return model
        if method == "avatar.refresh":
            try:
                model = self.avatar.refresh_model(str(params.get("model_id") or ""))
            except AvatarError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("avatar.model.refreshed", {"model": model}))
            return model
        if method == "avatar.inspect":
            try:
                inspection = self.avatar.inspect_model(str(params.get("model_id") or ""))
            except AvatarError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "avatar.model.inspected",
                    {
                        "model_id": str(params.get("model_id") or ""),
                        "status": inspection["status"],
                        "valid": inspection["valid"],
                        "error_count": len(inspection["errors"]),
                        "warning_count": len(inspection["warnings"]),
                    },
                )
            )
            return inspection
        if method == "avatar.unregister":
            try:
                result = self.avatar.unregister_model(str(params.get("model_id") or ""))
            except AvatarError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            if self._is_managed_avatar_path(result["model"]["path"]):
                self._set_avatar_path_ignored(result["model"]["path"], True)
            self.events.publish(EventEnvelope("avatar.model.unregistered", result))
            return result
        if method == "avatar.restore":
            path_value = params.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise JsonRpcError(-32602, "path must not be empty")
            try:
                resolved_path = Path(path_value).expanduser().resolve()
            except OSError as exc:
                raise JsonRpcError(-32602, f"model path is not readable: {path_value}") from exc
            if not self._is_managed_avatar_path(str(resolved_path)):
                raise JsonRpcError(-32602, "only ignored models from assets/avatars can be restored")
            if resolved_path not in self._ignored_avatar_paths():
                raise JsonRpcError(-32602, "model path is not currently ignored")
            restore_metadata = {"auto_discovered": True, "managed_directory": "assets/avatars"}
            restore_name: str | None = None
            restore_kind: str | None = None
            if resolved_path == DEFAULT_AVATAR_PATH.resolve():
                restore_metadata = dict(DEFAULT_AVATAR_METADATA)
                restore_name = "Sumika 默认 Avatar（VRoid Sample A）"
                restore_kind = "vrm"
            try:
                model = self.avatar.import_model(
                    str(resolved_path),
                    name=restore_name,
                    kind=restore_kind,
                    metadata=restore_metadata,
                )
            except AvatarError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self._set_avatar_path_ignored(str(resolved_path), False)
            self.events.publish(EventEnvelope("avatar.model.restored", {"model": model}))
            return model
        if method == "avatar.select":
            try:
                result = self.avatar.select(
                    str(params.get("character_id") or "sumika"),
                    model_id=str(params["model_id"]) if params.get("model_id") else None,
                    driver_id=str(params.get("driver_id") or "none"),
                )
            except AvatarError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(EventEnvelope("avatar.changed", result["state"], character_id=result["character"]["id"]))
            return result
        if method == "avatar.state":
            character_id = params.get("character_id")
            if character_id and character_id != self.avatar.active_character_id:
                try:
                    self.avatar.restore_character(str(character_id))
                except AvatarError as exc:
                    raise JsonRpcError(-32602, str(exc)) from exc
            return self.avatar.state()
        if method == "chat.send":
            return self._chat(params)
        raise JsonRpcError(-32601, f"Method not found: {method}")

    def _discover_plugins_at_startup(self) -> None:
        try:
            discovered = self.plugins.discover(self.plugin_paths)
        except PluginCatalogError as exc:
            self.events.publish(EventEnvelope("plugin.discovery.failed", {"error": str(exc)}))
            return
        if discovered:
            self.events.publish(
                EventEnvelope(
                    "plugin.discovered",
                    {"count": len(discovered), "candidates": [_plugin_summary(item) for item in discovered]},
                )
            )

    def _sync_plugin_providers(self) -> None:
        """Expose approved manifest providers without importing plugin code."""

        if not hasattr(self, "providers") or not hasattr(self, "audio_providers"):
            return
        registries = {
            "llm": (self.providers, PluginLLMProvider),
            "asr": (self.audio_providers, PluginASRProvider),
            "tts": (self.audio_providers, PluginTTSProvider),
            "vad": (self.audio_providers, PluginVADProvider),
            "memory": (self.memory_providers, PluginMemoryProvider),
            "vision": (self.vision_providers, PluginVisionProvider),
        }
        desired: set[tuple[str, str]] = set()
        for candidate in self.plugins.list():
            manifest = candidate.get("manifest") if isinstance(candidate.get("manifest"), dict) else {}
            capabilities = manifest.get("capabilities", []) if isinstance(manifest, dict) else []
            candidate_id = str(candidate.get("candidate_id") or "")
            if not candidate_id:
                continue
            provider_id = f"plugin:{candidate_id}"
            for capability, (registry, provider_type) in registries.items():
                if capability not in capabilities:
                    continue
                if candidate.get("state") != "approved":
                    continue
                desired.add((capability, provider_id))
                if registry.has(provider_id):
                    provider = registry.get(provider_id)
                    refresh = getattr(provider, "refresh", None)
                    if callable(refresh):
                        refresh()
                    continue
                registry.register(provider_type(self.plugins, candidate_id))
        for capability, (registry, _provider_type) in registries.items():
            for info in registry.list():
                if info.capability != capability:
                    continue
                provider_id = info.id
                if provider_id.startswith("plugin:") and (capability, provider_id) not in desired:
                    registry.unregister(provider_id)
        if hasattr(self, "modules"):
            self.modules.refresh()
            # Revoke or hash invalidation can remove a provider while a
            # capability is running. Stop stale in-memory sessions immediately.
            if hasattr(self, "audio"):
                self.audio.reconcile()
            if hasattr(self, "vision"):
                self.vision.reconcile()

    def _create_snapshot(
        self,
        name: str,
        *,
        scope: str,
        target_id: str | None,
    ) -> dict[str, Any]:
        payload = self.storage.export_snapshot_state(scope, target_id)
        snapshot = self.storage.create_snapshot(_safe_id("snapshot"), name, payload)
        self.events.publish(EventEnvelope("snapshot.created", {"snapshot": self._snapshot_summary(snapshot)}))
        return snapshot

    @staticmethod
    def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
        payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {}
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return {
            "id": snapshot.get("id"),
            "name": snapshot.get("name"),
            "created_at": snapshot.get("created_at"),
            "scope": payload.get("scope", "unknown"),
            "target_id": payload.get("target_id"),
            "format_version": payload.get("format_version"),
            "size_bytes": len(serialized),
            "table_counts": {
                str(table): len(value) if isinstance(value, list) else 0
                for table, value in tables.items()
            },
        }

    def _run_core_health(self, task: dict[str, Any]) -> dict[str, Any]:
        """Safe built-in handler used to exercise the approval boundary."""
        provider_health = self.providers.health()
        available = sum(1 for item in provider_health if item.get("ok"))
        return {
            "summary": "本地核心健康检查完成",
            "checks": {
                "module_count": len(self.modules.list()),
                "provider_count": len(provider_health),
                "available_provider_count": available,
            },
            "runner": "in-process-reference",
            "task_id": task.get("id"),
        }

    def _active_provider_profile_id(self) -> str | None:
        setting = self.storage.get_module_setting("llm")
        if (
            not setting
            or not bool(setting.get("enabled"))
            or setting.get("implementation_id") != "openai-compatible"
        ):
            return None
        profile_id = (setting.get("config") or {}).get("profile_id")
        return str(profile_id) if isinstance(profile_id, str) and profile_id else None

    def _agent_provider_profile(
        self,
        params: dict[str, Any] | None = None,
        *,
        required: bool = True,
        refresh_health: bool = False,
    ) -> dict[str, Any] | None:
        params = params or {}
        requested = params.get("provider_profile_id") or params.get("profile_id")
        profile_id = str(requested).strip() if requested else self._active_provider_profile_id()
        if not profile_id:
            if required:
                raise ProviderProfileError("没有启用的 Sumika Provider 档案")
            return None
        try:
            profile = self.provider_profiles.get(profile_id, include_secrets=True)
            if refresh_health:
                # GET /models is passive and does not consume model tokens.
                # Refresh before Agent operations so a stopped endpoint cannot
                # remain falsely marked as ready in SQLite.
                self.provider_profiles.health(profile_id)
                profile = self.provider_profiles.get(profile_id, include_secrets=True)
            return profile
        except ProviderProfileError:
            if required:
                raise
            return None

    @staticmethod
    def _agent_provider_profile_public(profile: dict[str, Any] | None) -> dict[str, Any] | None:
        if profile is None:
            return None
        return {
            key: value
            for key, value in profile.items()
            if key not in {"secrets", "credential_ref"}
        }

    def _agent_plan_review_approved(
        self,
        request_id: Any,
        session_id: Any,
        answer: Any,
    ) -> bool:
        """Recognize an exact approval of a pending runtime plan review."""

        if not request_id or not session_id or not isinstance(answer, dict):
            return False
        pending = self.agent.interactions({"sessionId": str(session_id)})
        entries = pending.get("interactions") if isinstance(pending, dict) else None
        interaction = next(
            (
                item
                for item in entries
                if isinstance(item, dict)
                and str(item.get("id") or "") == str(request_id)
                and item.get("kind") == "question"
                and isinstance(item.get("plan_review"), dict)
            ),
            None,
        ) if isinstance(entries, list) else None
        if interaction is None:
            return False
        questions = interaction.get("questions")
        question = next(
            (
                item
                for item in questions
                if isinstance(item, dict)
                and isinstance(item.get("intent"), dict)
                and item["intent"].get("kind") == "plan-review"
            ),
            None,
        ) if isinstance(questions, list) else None
        if question is None:
            return False
        approve = str(
            interaction["plan_review"].get("approve")
            or question["intent"].get("approve")
            or ""
        ).strip()
        question_id = str(question.get("id") or "").strip()
        answers = answer.get("answers")
        if not approve or not question_id or not isinstance(answers, list):
            return False
        selected = next(
            (
                item
                for item in answers
                if isinstance(item, dict)
                and str(item.get("id") or "") == question_id
            ),
            None,
        )
        return bool(
            isinstance(selected, dict)
            and selected.get("selected") == [approve]
            and not str(selected.get("custom") or "").strip()
        )

    def _agent_workspace_binding(
        self,
        params: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        if params.get("cwd") not in (None, ""):
            raise JsonRpcError(
                -32602,
                "workspace-capable Agent runtimes require workspaceId; cwd is not accepted",
            )
        raw_workspace_id = params.get("workspaceId") or params.get("workspace_id")
        if (
            not isinstance(raw_workspace_id, str)
            or not raw_workspace_id.strip()
            or len(raw_workspace_id.strip()) > 160
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_workspace_id)
        ):
            raise JsonRpcError(-32602, "workspaceId must be a non-empty identifier")
        workspace_id = raw_workspace_id.strip()
        try:
            roster = self.agent.list_workspaces({})
        except AgentRuntimeError as exc:
            raise JsonRpcError(-32030, str(exc)) from exc
        entries = roster.get("workspaces") if isinstance(roster, dict) else None
        workspace = next(
            (
                item
                for item in entries
                if isinstance(item, dict) and item.get("id") == workspace_id
            ),
            None,
        ) if isinstance(entries, list) else None
        if workspace is None:
            raise JsonRpcError(-32033, "the selected Agent Workspace is no longer registered")
        if session_id is not None:
            session_ids = workspace.get("session_ids")
            if not isinstance(session_ids, list) or session_id not in session_ids:
                raise JsonRpcError(
                    -32033,
                    "the Agent session is not bound to the selected Workspace",
                )
        try:
            path = _workspace_path_param(workspace.get("path"))
        except JsonRpcError as exc:
            raise JsonRpcError(-32030, "Agent runtime returned an invalid Workspace path") from exc
        if session_id is None:
            try:
                self.workspace.inspect(path)
            except WorkspaceError as exc:
                raise JsonRpcError(-32033, str(exc)) from exc
        return workspace, path

    def _agent_workspace_safety_active(self) -> bool:
        if not self.agent.supports(AgentCapability.WORKSPACES):
            return False
        try:
            return self.agent.status().get("ready") is True
        except AgentRuntimeError:
            return False

    def _provider_profile_list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        active_profile_id = self._active_provider_profile_id()
        return [
            {**profile, "active": profile["id"] == active_profile_id}
            for profile in self.provider_profiles.list(include_archived=include_archived)
        ]

    def _module_list(self) -> list[dict[str, Any]]:
        active_profile_id = self._active_provider_profile_id()
        if active_profile_id:
            try:
                # Keep the module/privacy surfaces honest after an external
                # Ollama or gateway process stops.  The adapter's passive
                # health check only reads the model catalogue and consumes no
                # chat tokens.
                self.provider_profiles.health(active_profile_id)
            except ProviderProfileError:
                pass
        return [self._decorate_module(module) for module in self.modules.list()]

    def _module(self, module_id: str) -> dict[str, Any]:
        return self._decorate_module(self.modules.get(module_id))

    def _decorate_module(self, module: dict[str, Any]) -> dict[str, Any]:
        if module.get("id") != "llm" or module.get("implementation_id") != "openai-compatible":
            return module
        result = dict(module)
        profile_id = result.get("config", {}).get("profile_id")
        profile = self.storage.get_provider_profile(str(profile_id)) if profile_id else None
        public_profile = self.provider_profiles.public(profile) if profile else None
        result["profile_id"] = profile_id
        result["profile"] = public_profile
        if result.get("enabled"):
            profile_status = (public_profile or {}).get("status")
            result["status"] = {
                "available": "available",
                "draft": "unconfigured",
                "unavailable": "error",
                "archived": "error",
            }.get(str(profile_status), "unconfigured")
        implementation = dict(result.get("implementation") or {})
        implementation["status"] = result["status"]
        result["implementation"] = implementation
        result["config_schema"] = {}
        return result

    def _privacy_status(self) -> dict[str, Any]:
        routes: list[dict[str, str]] = []
        for module in self._module_list():
            if not module.get("enabled"):
                continue
            location = "local"
            if module.get("id") == "llm":
                location = str((module.get("profile") or {}).get("resolved_processing_location") or "cloud")
            elif module.get("config", {}).get("processing_location") in {"local", "cloud"}:
                location = str(module["config"]["processing_location"])
            routes.append({"module_id": str(module.get("id")), "location": location})
        locations = {item["location"] for item in routes}
        if locations == {"cloud"}:
            mode, label = "cloud", "云端处理"
        elif "cloud" in locations and "local" in locations:
            mode, label = "mixed", "混合处理"
        else:
            mode, label = "local", "本地处理"
        return {"mode": mode, "label": label, "routes": routes}

    def _chat(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "default")
        if not self.modules.is_enabled("llm"):
            raise JsonRpcError(-32010, "LLM module is disabled")
        configured_provider_id = self.modules.selected_implementation("llm") or "openai-compatible"
        profile_id = self.modules.selected_profile("llm") if configured_provider_id == "openai-compatible" else None
        runtime_provider = None
        event_provider_id = configured_provider_id
        if profile_id:
            try:
                health = self.provider_profiles.health(profile_id)
                profile = health.get("profile") if isinstance(health, dict) else None
                if not health.get("ok") or not isinstance(profile, dict) or profile.get("status") != "available":
                    raise ProviderProfileError("Provider profile is not ready; test it on the Modules page")
                runtime_provider = self.provider_profiles.runtime(profile_id)
                event_provider_id = profile_id
            except ProviderProfileError as exc:
                raise JsonRpcError(-32010, str(exc)) from exc
        requested_provider_id = params.get("provider_id")
        allowed_requested_ids = {configured_provider_id, event_provider_id}
        if requested_provider_id and str(requested_provider_id) not in allowed_requested_ids:
            raise JsonRpcError(
                -32010,
                f"LLM module is configured to use {event_provider_id}; change it on the Modules page",
            )
        provider_id = event_provider_id
        character_id = str(params.get("character_id")) if params.get("character_id") else None
        character = self.storage.get_character(character_id) if character_id else None
        raw_messages = params.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise JsonRpcError(-32602, "messages must be a non-empty list")
        try:
            incoming_messages = [
                Message(
                    role=item["role"],
                    content=str(item["content"]),
                    id=str(item.get("id") or _safe_id("message")),
                    created_at=str(item.get("created_at") or utc_now()),
                    character_id=item.get("character_id") or character_id,
                )
                for item in raw_messages
                if isinstance(item, dict) and item.get("role") in {"system", "user", "assistant", "tool"}
            ]
        except KeyError as exc:
            raise JsonRpcError(-32602, f"message missing field: {exc.args[0]}") from exc
        if not incoming_messages:
            raise JsonRpcError(-32602, "messages contains no valid entries")
        context_messages: list[Message] = []
        persona = (character or {}).get("config", {}).get("persona", {}) if character else {}
        context = build_persona_context(
            character["name"],
            (character or {}).get("config", {}).get("language"),
            persona,
        ) if character else None
        if context:
            context_messages.append(Message(role="system", content=context, character_id=character_id))
        is_first_turn = not self.storage.list_messages(session_id)
        greeting = str(persona.get("greeting") or "").strip() if isinstance(persona, dict) else ""
        if is_first_turn and greeting:
            context_messages.append(Message(role="assistant", content=greeting, character_id=character_id))
        messages = [*context_messages, *incoming_messages]
        request = ChatRequest(
            session_id=session_id,
            messages=messages,
            provider_id=provider_id,
            character_id=character_id,
            temperature=float(params.get("temperature", 0.7)),
            max_tokens=int(params.get("max_tokens", 512)),
        )
        latest = incoming_messages[-1]
        if latest.role == "user":
            self.storage.append_message(session_id, latest)
            self.events.publish(EventEnvelope("message.created", {"message": latest.to_dict()}, session_id, character_id))
        self.events.publish(EventEnvelope("provider.status", {"provider_id": provider_id, "status": "running"}, session_id, character_id))
        pieces: list[str] = []
        try:
            stream = runtime_provider.stream(request) if runtime_provider is not None else self.providers.stream(configured_provider_id, request)
            for piece in stream:
                pieces.append(piece)
                self.events.publish(EventEnvelope("llm.token", {"provider_id": provider_id, "text": piece}, session_id, character_id))
        except KeyError as exc:
            raise JsonRpcError(-32602, str(exc)) from exc
        except Exception as exc:
            safe = safe_error(exc)
            self.events.publish(
                EventEnvelope(
                    "provider.status",
                    {
                        "provider_id": provider_id,
                        "status": "error",
                        "error_type": safe["type"],
                        "error": safe["message"],
                    },
                    session_id,
                    character_id,
                )
            )
            raise JsonRpcError(-32000, f"Provider failed: {safe['message']}") from exc
        answer = "".join(pieces)
        if profile_id:
            self.provider_profiles.mark_used(profile_id)
        assistant = Message(role="assistant", content=answer, character_id=character_id)
        self.storage.append_message(session_id, assistant)
        self.events.publish(EventEnvelope("message.created", {"message": assistant.to_dict()}, session_id, character_id))
        self.events.publish(EventEnvelope("chat.completed", {"provider_id": provider_id, "message": assistant.to_dict()}, session_id, character_id))
        self.events.publish(EventEnvelope("provider.status", {"provider_id": provider_id, "status": "ready"}, session_id, character_id))
        return {"message": assistant.to_dict(), "provider_id": provider_id}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.logger.info("core shutdown requested uptime_seconds=%.3f", time.monotonic() - self.started_at)
            self.providers.close()
            self.agent.close()
            self.browser.close()
            self.audio.close()
            self.vision.close()
            self.audio_providers.close()
            self.memory_providers.close()
            self.vision_providers.close()
            self.avatar.close()
            self.storage.close()
            try:
                self.observability.write_daily_summary()
            except Exception as error:
                self.logger.warning("agent observability close summary failed error_type=%s", type(error).__name__)
            self.observability.close()
            self.logger.info("core shutdown complete")
        finally:
            # A failed provider close must not leave the rotating file handle
            # attached to a temporary data directory or a later core instance.
            close_logging(self.logger, self.log_path)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "version": "0.1.0",
            "pid": os.getpid(),
            "data_dir": str(self.configured_data_dir) if self.configured_data_dir else ":memory:",
            "log_path": str(self.log_path) if self.log_path else None,
            "uptime_seconds": round(time.monotonic() - self.started_at, 3),
            "module_count": len(self.modules.list()),
            "provider_count": len(self.providers.list()),
            "provider_profile_count": len(self.provider_profiles.list(include_archived=True)),
            "avatar_count": len(self.avatar.list_models()),
            "event_count": self.storage.count_events(),
            "agent_runtime": self.agent.status(),
            "browser_runtime": self.browser.status(),
            "workspace_checkpoint_count": len(self.workspace.list_checkpoints()["checkpoints"]),
            "evolution_registry": self.evolution_registry.check(),
            "agent_observability": self.observability.status(),
        }


class SumikaRequestHandler(BaseHTTPRequestHandler):
    application: CoreApplication

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Allow the production Tauri origin to call the local core API."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ws/events" and self.headers.get("Upgrade", "").lower() == "websocket":
            self._serve_websocket()
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(self.application.rpc("core.health", {}))
            return
        if parsed.path == "/api/diagnostics":
            self._send_json(self.application.rpc("core.diagnostics", {}))
            return
        if parsed.path == "/api/agent/status":
            self._send_json(self.application.rpc("agent.status", {}))
            return
        if parsed.path == "/api/agent/diagnostics":
            self._send_json(self.application.rpc("agent.diagnostics", {}))
            return
        if parsed.path == "/api/agent/mcp/catalog":
            query = parse_qs(parsed.query)
            session_id = (query.get("session_id") or [None])[0]
            self._send_json(self.application.rpc("agent.mcp.catalog", {"sessionId": session_id} if session_id else {}))
            return
        if parsed.path == "/api/agent/skills":
            query = parse_qs(parsed.query)
            refresh = (query.get("refresh") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("agent.skills.catalog", {"refresh": refresh}))
            return
        if parsed.path == "/api/agent/observability":
            query = parse_qs(parsed.query)
            day = (query.get("day") or [None])[0]
            write = (query.get("write") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("agent.observability.daily", {"day": day, "write": write}))
            return
        if parsed.path == "/api/agent/provider":
            self._send_json(self.application.rpc("agent.provider.status", {}))
            return
        if parsed.path == "/api/agent/session.export":
            self._serve_agent_session_export(parsed.query)
            return
        if parsed.path == "/api/browser/status":
            self._send_json(self.application.rpc("browser.status", {}))
            return
        if parsed.path == "/api/browser/profiles":
            query = parse_qs(parsed.query)
            include_archived = (query.get("include_archived") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("browser.profiles", {"include_archived": include_archived}))
            return
        if parsed.path == "/api/browser/downloads":
            self._send_json(self.application.rpc("browser.downloads", {}))
            return
        if parsed.path == "/api/evolution/registry":
            self._send_json(self.application.rpc("evolution.registry.list", {}))
            return
        if parsed.path == "/api/providers":
            self._send_json(self.application.rpc("provider.list", {}))
            return
        if parsed.path == "/api/provider-profiles":
            query = parse_qs(parsed.query)
            include_archived = (query.get("include_archived") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("provider.profile.list", {"include_archived": include_archived}))
            return
        if parsed.path == "/api/provider-templates":
            self._send_json(self.application.rpc("provider.profile.templates", {}))
            return
        if parsed.path == "/api/privacy":
            self._send_json(self.application.rpc("privacy.status", {}))
            return
        if parsed.path == "/api/integrations/ccswitch":
            self._send_json(self.application.rpc("integration.ccswitch.manifest", {}))
            return
        if parsed.path == "/api/modules":
            self._send_json(self.application.rpc("module.list", {}))
            return
        if parsed.path == "/api/plugins":
            self._send_json(self.application.rpc("plugin.list", {}))
            return
        if parsed.path == "/api/audio/status":
            self._send_json(self.application.rpc("audio.status", {}))
            return
        if parsed.path == "/api/memory/status":
            self._send_json(self.application.rpc("memory.status", {}))
            return
        if parsed.path == "/api/vision/status":
            self._send_json(self.application.rpc("vision.status", {}))
            return
        if parsed.path == "/api/memories":
            query = parse_qs(parsed.query)
            params = {
                "character_id": (query.get("character_id") or ["sumika"])[0],
                "category": (query.get("category") or [None])[0],
                "query": (query.get("query") or [None])[0],
                "limit": (query.get("limit") or [100])[0],
            }
            try:
                self._send_json(self.application.rpc("memory.list", params))
            except JsonRpcError as exc:
                self._send_json({"error": exc.message, "code": exc.code}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/tasks":
            self._send_json(self.application.rpc("task.list", {}))
            return
        thumbnail_prefix = "/api/avatar/models/"
        thumbnail_suffix = "/thumbnail"
        file_suffix = "/file"
        if parsed.path.startswith(thumbnail_prefix) and parsed.path.endswith(file_suffix):
            model_id = unquote(parsed.path[len(thumbnail_prefix) : -len(file_suffix)]).strip("/")
            body = self.application.avatar_file(model_id)
            if body is None:
                self._send_json({"error": "Avatar model file is not available"}, HTTPStatus.NOT_FOUND)
            else:
                self._send_bytes(body, "model/gltf-binary")
            return
        if parsed.path.startswith(thumbnail_prefix) and parsed.path.endswith(thumbnail_suffix):
            model_id = unquote(parsed.path[len(thumbnail_prefix) : -len(thumbnail_suffix)]).strip("/")
            body = self.application.avatar_thumbnail(model_id)
            if body is None:
                self._send_json({"error": "Avatar preview is not available"}, HTTPStatus.NOT_FOUND)
            else:
                self._send_bytes(body, "image/png")
            return
        inspection_suffix = "/inspection"
        if parsed.path.startswith(thumbnail_prefix) and parsed.path.endswith(inspection_suffix):
            model_id = unquote(parsed.path[len(thumbnail_prefix) : -len(inspection_suffix)]).strip("/")
            try:
                inspection = self.application.rpc("avatar.inspect", {"model_id": model_id})
            except JsonRpcError as exc:
                self._send_json({"error": exc.message, "code": exc.code}, HTTPStatus.BAD_REQUEST)
            else:
                self._send_json(inspection)
            return
        if parsed.path == "/api/avatar/models":
            self._send_json(self.application.rpc("avatar.models", {}))
            return
        if parsed.path == "/api/avatar/ignored":
            self._send_json(self.application.rpc("avatar.ignored", {}))
            return
        if parsed.path == "/api/sessions":
            self._send_json(self.application.rpc("session.list", {}))
            return
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/messages"):
            session_id = unquote(parsed.path.removeprefix("/api/sessions/").removesuffix("/messages")).strip("/")
            self._send_json(self.application.rpc("session.messages", {"session_id": session_id}))
            return
        if parsed.path == "/api/characters":
            self._send_json(self.application.rpc("character.list", {}))
            return
        if parsed.path == "/api/events":
            self._send_json(self.application.rpc("event.list", {}))
            return
        if parsed.path == "/api/snapshots":
            self._send_json(self.application.rpc("snapshot.list", {}))
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        payload: dict[str, Any] = {}
        try:
            payload = self._read_json()
            if self.path == "/rpc":
                request = parse_request(payload)
                self._send_json(success(request.request_id, self.application.rpc(request.method, request.params)))
                return
            if self.path == "/api/chat":
                self._send_json(self.application.rpc("chat.send", payload))
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except JsonRpcError as exc:
            self._send_json(failure(payload.get("id") if isinstance(payload, dict) else None, exc), HTTPStatus.BAD_REQUEST)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.application.logger.warning("http request rejected path=%s error_type=%s", urlparse(self.path).path, type(exc).__name__)
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
            # A browser can leave a long-running local-model request when its
            # test/page timeout fires. The client is already gone, so do not
            # attempt a second response or emit a misleading error traceback.
            self.application.logger.info("http client disconnected path=%s error_type=%s", urlparse(self.path).path, type(exc).__name__)
        except Exception as exc:
            self.application.logger.error("http request failed path=%s error=%s", urlparse(self.path).path, safe_error(exc)["type"])
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_websocket(self) -> None:
        try:
            accept_websocket(self)
        except (ValueError, BrokenPipeError):
            return
        write_lock = threading.Lock()

        def send(event: dict) -> None:
            frame = encode_text_frame(json.dumps(event, ensure_ascii=False))
            with write_lock:
                self.connection.sendall(frame)

        unsubscribe = self.application.events.subscribe(send)
        try:
            send({"event_type": "connection.ready", "payload": {"version": "0.1.0"}})
            self.connection.settimeout(1.0)
            while True:
                try:
                    header = self.connection.recv(2)
                    if not header:
                        break
                    # Client frames are not commands in this version. Read and
                    # discard their payload so browser close frames disconnect cleanly.
                    length = header[1] & 0x7F
                    if length == 126:
                        length = int.from_bytes(self.connection.recv(2), "big")
                    elif length == 127:
                        length = int.from_bytes(self.connection.recv(8), "big")
                    if header[1] & 0x80:
                        self.connection.recv(4)
                    remaining = length
                    while remaining:
                        chunk = self.connection.recv(min(remaining, 4096))
                        if not chunk:
                            return
                        remaining -= len(chunk)
                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break
        finally:
            unsubscribe()

    def _serve_static(self, url_path: str) -> None:
        relative = url_path.lstrip("/") or "index.html"
        candidate = (FRONTEND_DIR / relative).resolve()
        if FRONTEND_DIR.resolve() not in candidate.parents and candidate != FRONTEND_DIR.resolve():
            self._send_json({"error": "Invalid path"}, HTTPStatus.BAD_REQUEST)
            return
        # Vite exposes files under frontend/public at the web root. Keep the
        # Python development server aligned with that convention so bundled
        # browser modules (for example /vendor/*) are served directly.
        if not candidate.is_file():
            public_root = (FRONTEND_DIR / "public").resolve()
            public_candidate = (public_root / relative).resolve()
            if public_root in public_candidate.parents and public_candidate.is_file():
                candidate = public_candidate
        if not candidate.is_file():
            candidate = FRONTEND_DIR / "index.html"
        if not candidate.is_file():
            self._send_json({"error": "Frontend is not built"}, HTTPStatus.NOT_FOUND)
            return
        content_type = "text/html; charset=utf-8" if candidate.suffix == ".html" else "text/plain; charset=utf-8"
        if candidate.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        if candidate.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
            self.application.logger.info("http client disconnected path=%s error_type=%s", urlparse(self.path).path, type(exc).__name__)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length < 0:
            raise ValueError("Invalid Content-Length")
        request_path = urlparse(self.path).path
        limit = _RPC_JSON_BODY_LIMIT if request_path == "/rpc" else _DEFAULT_JSON_BODY_LIMIT
        if length > limit:
            raise ValueError("Request body is too large")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON request must be an object")
        return value

    def _send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
            self.application.logger.info("http client disconnected path=%s error_type=%s", urlparse(self.path).path, type(exc).__name__)

    def _serve_agent_session_export(self, raw_query: str) -> None:
        query = parse_qs(raw_query, keep_blank_values=True)
        session_values = query.get("session_id") or []
        include_values = query.get("include_descendants") or ["false"]
        if len(session_values) != 1 or len(include_values) != 1:
            self._send_json({"error": "A single session_id is required"}, HTTPStatus.BAD_REQUEST)
            return
        session_id = session_values[0].strip()
        include_text = include_values[0].strip().lower()
        if (
            not session_id
            or len(session_id) > 240
            or any(ord(character) < 32 for character in session_id)
            or include_text not in {"true", "false"}
        ):
            self._send_json({"error": "Invalid session export parameters"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            export = self.application.agent.open_session_export(
                {
                    "session_id": session_id,
                    "include_descendants": include_text == "true",
                }
            )
        except AgentRuntimeError as exc:
            status = HTTPStatus.SERVICE_UNAVAILABLE if exc.transport else HTTPStatus.BAD_GATEWAY
            if exc.http_status == 404:
                status = HTTPStatus.NOT_FOUND
            elif exc.http_status == 501:
                status = HTTPStatus.NOT_IMPLEMENTED
            self._send_json({"error": str(exc)}, status)
            return

        stream = export.get("stream") if isinstance(export, dict) else None
        if stream is None or not hasattr(stream, "read"):
            self._send_json({"error": "Agent session export stream is unavailable"}, HTTPStatus.BAD_GATEWAY)
            return
        filename_token = re.sub(r"[^A-Za-z0-9._-]+", "-", session_id).strip("-.")[:80] or "session"
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            content_length = export.get("content_length")
            if isinstance(content_length, int) and not isinstance(content_length, bool) and content_length >= 0:
                self.send_header("Content-Length", str(content_length))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="sumika-agent-{filename_token}.zip"',
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            shutil.copyfileobj(stream, self.wfile, length=64 * 1024)
            self.application.logger.info(
                "agent session export completed session_id=%s include_descendants=%s",
                session_id,
                include_text == "true",
            )
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as exc:
            self.application.logger.info(
                "agent session export interrupted session_id=%s error_type=%s",
                session_id,
                type(exc).__name__,
            )
        finally:
            stream.close()

    def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
            self.application.logger.info("http client disconnected path=%s error_type=%s", urlparse(self.path).path, type(exc).__name__)

    def log_message(self, format: str, *args: object) -> None:
        self.application.logger.info("http access method=%s path=%s", self.command, urlparse(self.path).path)


class SumikaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    data_dir: str | Path | None = None,
    *,
    test_providers: dict[str, list[Any]] | None = None,
) -> tuple[SumikaHTTPServer, CoreApplication]:
    """Create an HTTP server; test doubles must be explicitly injected."""
    application = CoreApplication(data_dir, test_providers=test_providers)

    class Handler(SumikaRequestHandler):
        pass

    Handler.application = application
    return SumikaHTTPServer((host, port), Handler), application


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Sumika local core service")
    parser.add_argument("--host", default=os.getenv("SUMIKA_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SUMIKA_PORT", "8765")))
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()
    server, application = create_server(args.host, args.port, args.data_dir)
    print(f"Sumika core listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Sumika core")
    finally:
        server.server_close()
        application.close()


def _safe_id(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _observability_event_phase(event_type: str) -> str:
    """Map a harness event to a bounded lifecycle phase."""

    candidate = str(event_type or "").strip().lower()
    if any(token in candidate for token in ("requested", "start", "queued", "accepted")):
        return "start"
    if any(token in candidate for token in ("resolved", "completed", "end", "finished", "succeeded")):
        return "end"
    if any(token in candidate for token in ("failed", "error", "rejected")):
        return "failure"
    if any(token in candidate for token in ("cancel", "abort")):
        return "cancel"
    return "event"


def _observability_event_outcome(event_type: str, event: dict[str, Any]) -> str:
    """Derive a stable outcome without inspecting event content."""

    candidate = str(event.get("status") or event.get("outcome") or "").strip().lower()
    if candidate in {"accepted", "queued", "running", "completed", "failed", "cancelled", "rejected"}:
        return candidate
    event_name = str(event_type or "").strip().lower()
    if any(token in event_name for token in ("failed", "error")):
        return "failed"
    if any(token in event_name for token in ("rejected",)):
        return "rejected"
    if any(token in event_name for token in ("cancel", "abort")):
        return "cancelled"
    if any(token in event_name for token in ("complete", "resolved", "succeeded", "success")):
        return "completed"
    if any(token in event_name for token in ("request", "accepted", "queued")):
        return "accepted"
    return "unknown"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_plugin_paths() -> list[Path]:
    configured = os.getenv("SUMIKA_PLUGIN_PATHS", "")
    values = [item.strip() for item in configured.split(os.pathsep) if item.strip()]
    paths = [Path(item) for item in values]
    repository_plugins = ROOT_DIR / "plugins"
    if repository_plugins.exists():
        paths.insert(0, repository_plugins)
    # Startup discovery is best-effort and read-only. Non-existent optional
    # paths are omitted so a stale environment variable cannot stop the core.
    return [path for path in paths if path.is_absolute() and path.exists()]


def _default_skill_paths() -> list[Path]:
    """Return explicit, user-owned Skill roots without scanning broad folders."""

    configured = os.getenv("SUMIKA_SKILL_PATHS", "")
    values = [item.strip() for item in configured.split(os.pathsep) if item.strip()]
    paths = [Path(item) for item in values]
    paths.extend((ROOT_DIR / ".agents" / "skills", Path.home() / ".agents" / "skills"))
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_absolute():
            continue
        try:
            key = str(path.resolve(strict=False)).casefold()
        except (OSError, RuntimeError):
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _plugin_paths_param(value: Any) -> list[str | Path]:
    if isinstance(value, (str, Path)):
        return [value]
    if not isinstance(value, list) or not value:
        raise ValueError("plugin discovery paths must be a non-empty string or list")
    if not all(isinstance(item, (str, Path)) for item in value):
        raise ValueError("plugin discovery paths must be strings")
    return value


def _skill_paths_param(value: Any) -> list[str | Path]:
    if isinstance(value, (str, Path)):
        return [value]
    if not isinstance(value, list) or not value:
        raise ValueError("Skill discovery paths must be a non-empty string or list")
    if not all(isinstance(item, (str, Path)) for item in value):
        raise ValueError("Skill discovery paths must be strings")
    return value


def _plugin_summary(plugin: dict[str, Any]) -> dict[str, Any]:
    manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
    return {
        "candidate_id": plugin.get("candidate_id"),
        "plugin_id": plugin.get("plugin_id") or manifest.get("id"),
        "version": plugin.get("version") or manifest.get("version"),
        "capabilities": manifest.get("capabilities", []),
        "manifest_path": plugin.get("manifest_path"),
        "state": plugin.get("state"),
        "configured": bool(plugin.get("launcher")),
        "manifest_sha256": plugin.get("manifest_sha256"),
        "error": plugin.get("error"),
        "updated_at": plugin.get("updated_at"),
    }


def _skill_summary(skill: dict[str, Any]) -> dict[str, Any]:
    """Keep Skill audit events metadata-only and path-free."""

    return {
        "candidate_id": skill.get("candidate_id"),
        "skill_id": skill.get("skill_id"),
        "name": skill.get("name"),
        "version": skill.get("version"),
        "source": skill.get("source"),
        "state": skill.get("state"),
        "manifest_sha256": skill.get("manifest_sha256"),
        "metadata_only": True,
    }


_AGENT_PRESET_ID_PARAM_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_AGENT_PRESET_ID_PARAM_LENGTH = 160
_MAX_AGENT_PRESET_NAME_PARAM_LENGTH = 240
_WORKSPACE_CHECKPOINT_ID_RE = re.compile(r"^wschk-[0-9a-f]{20}$")
_MAX_AGENT_SESSION_ID_PARAM_LENGTH = 240


def _event_datetime(event: dict[str, Any] | None) -> datetime | None:
    if not isinstance(event, dict):
        return None
    value = event.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _bounded_event_count(value: Any, maximum: int = 10000) -> int:
    try:
        return max(0, min(maximum, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _agent_acceptance_evidence(
    events: list[dict[str, Any]],
    *,
    session_id: str,
    runtime_id: str,
) -> dict[str, Any]:
    """Correlate one completed real-provider run without exposing its content."""

    bounded_events = [event for event in events[:1000] if isinstance(event, dict)]
    approval_candidates = [
        event
        for event in bounded_events
        if event.get("event_type") == "agent.question.answered"
        and event.get("session_id") == session_id
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("plan_approved") is True
        and isinstance(event["payload"].get("workspace_checkpoint_id"), str)
    ]
    approval = max(approval_candidates, key=lambda event: _event_datetime(event) or datetime.min.replace(tzinfo=timezone.utc), default=None)
    approval_payload = approval.get("payload") if isinstance(approval, dict) else {}
    approval_payload = approval_payload if isinstance(approval_payload, dict) else {}
    checkpoint_id = approval_payload.get("workspace_checkpoint_id")
    request_id = approval_payload.get("request_id")
    approval_time = _event_datetime(approval)

    def matching_event(event_type: str, *, session_scoped: bool = False) -> dict[str, Any] | None:
        matches = []
        for event in bounded_events:
            if event.get("event_type") != event_type:
                continue
            if session_scoped and event.get("session_id") != session_id:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if checkpoint_id and payload.get("checkpoint_id") != checkpoint_id:
                continue
            matches.append(event)
        return min(matches, key=lambda event: _event_datetime(event) or datetime.max.replace(tzinfo=timezone.utc), default=None)

    checkpoint = matching_event("workspace.checkpoint.created", session_scoped=True) if approval else None
    checkpoint_payload = checkpoint.get("payload") if isinstance(checkpoint, dict) else {}
    checkpoint_payload = checkpoint_payload if isinstance(checkpoint_payload, dict) else {}
    checkpoint_time = _event_datetime(checkpoint)
    checkpoint_before_approval = bool(
        checkpoint_time is not None
        and approval_time is not None
        and checkpoint_time <= approval_time
        and checkpoint_payload.get("trigger") == "agent.plan.approval"
    )

    requested = False
    if approval and request_id:
        for event in bounded_events:
            if event.get("event_type") != "agent.question.requested" or event.get("session_id") != session_id:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            extensions = payload.get("extensions") if isinstance(payload.get("extensions"), dict) else {}
            if extensions.get("rpcId") == request_id:
                requested = True
                break

    completion_candidates: list[dict[str, Any]] = []
    if approval_time is not None:
        for event in bounded_events:
            if event.get("event_type") != "agent.session.event" or event.get("session_id") != session_id:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            event_time = _event_datetime(event)
            if payload.get("status") == "turn/end" and event_time is not None and event_time >= approval_time:
                completion_candidates.append(event)
    completion = min(completion_candidates, key=lambda event: _event_datetime(event) or datetime.max.replace(tzinfo=timezone.utc), default=None)
    completion_time = _event_datetime(completion)
    completion_payload = completion.get("payload") if isinstance(completion, dict) else {}
    completion_extensions = completion_payload.get("extensions") if isinstance(completion_payload, dict) and isinstance(completion_payload.get("extensions"), dict) else {}
    completion_turn = completion_extensions.get("turn") if isinstance(completion_extensions.get("turn"), dict) else {}
    turn_state = str(completion_turn.get("state") or "unknown").lower()
    if turn_state not in {"completed", "failed", "cancelled", "interrupted"}:
        turn_state = "unknown"

    tool_calls = 0
    tool_results = 0
    write_tool_seen = False
    if approval_time is not None:
        for event in bounded_events:
            if event.get("event_type") != "agent.session.event" or event.get("session_id") != session_id:
                continue
            event_time = _event_datetime(event)
            if event_time is None or event_time < approval_time or (completion_time is not None and event_time > completion_time):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            status = payload.get("status")
            extensions = payload.get("extensions") if isinstance(payload.get("extensions"), dict) else {}
            tool = extensions.get("tool") if isinstance(extensions.get("tool"), dict) else {}
            if status == "tool/call":
                tool_calls += 1
                write_tool_seen = write_tool_seen or str(tool.get("name") or "").lower() in {"write", "edit", "apply_patch"}
            elif status == "tool/result":
                tool_results += 1

    diff = matching_event("workspace.checkpoint.diffed") if approval else None
    preview = matching_event("workspace.restore.previewed") if approval else None
    restored = matching_event("workspace.restored") if approval else None
    diff_payload = diff.get("payload") if isinstance(diff, dict) and isinstance(diff.get("payload"), dict) else {}
    restored_payload = restored.get("payload") if isinstance(restored, dict) and isinstance(restored.get("payload"), dict) else {}
    changed_file_count = _bounded_event_count(diff_payload.get("changed_total"))
    archive_count = _bounded_event_count(restored_payload.get("archive_count"))

    safety_failed = bool(approval) and (checkpoint is None or not checkpoint_before_approval)
    execution_failed = turn_state in {"failed", "cancelled", "interrupted"}
    passed = bool(
        approval
        and requested
        and checkpoint_before_approval
        and turn_state == "completed"
        and tool_results > 0
        and write_tool_seen
        and diff is not None
        and changed_file_count > 0
        and preview is not None
        and restored is not None
    )
    status = "passed" if passed else ("failed" if safety_failed or execution_failed else "needs-action")

    def elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
        if start is None or end is None or end < start:
            return None
        return min(86_400_000, max(0, round((end - start).total_seconds() * 1000)))

    safe_runtime_id = runtime_id if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(runtime_id or "")) else "unknown"
    return {
        "schema_version": "sumika.agent-real-evidence.v1",
        "status": status,
        "runtime_id": safe_runtime_id,
        "plan_review": {
            "requested": requested,
            "approved": approval is not None,
            "checkpoint_created": checkpoint is not None,
            "checkpoint_before_approval": checkpoint_before_approval,
        },
        "execution": {
            "turn_state": turn_state,
            "tool_call_count": min(64, tool_calls),
            "tool_result_count": min(64, tool_results),
            "write_tool_seen": write_tool_seen,
        },
        "workspace": {
            "diff_observed": diff is not None,
            "changed_file_count": changed_file_count,
            "restore_previewed": preview is not None,
            "restored": restored is not None,
            "archive_count": archive_count,
        },
        "timing": {
            "approval_to_completion_ms": elapsed_ms(approval_time, completion_time),
            "approval_to_restore_ms": elapsed_ms(approval_time, _event_datetime(restored)),
        },
        "evidence_window_events": min(1000, len(bounded_events)),
    }


def _agent_session_id_param(value: Any, field: str = "sessionId") -> str:
    """Validate a session identifier before a mutating Agent operation.

    Session ids are opaque values owned by the harness.  Keep the Core gate
    deliberately small: accept only scalar ids, reject control characters and
    bound their size before using the value in audit events or adapter calls.
    """

    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise JsonRpcError(-32602, f"{field} must be a non-empty identifier without control characters")
    candidate = str(value).strip()
    if (
        not candidate
        or len(candidate) > _MAX_AGENT_SESSION_ID_PARAM_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in candidate)
    ):
        raise JsonRpcError(-32602, f"{field} must be a non-empty identifier without control characters")
    return candidate


def _agent_preset_id_param(value: Any, field: str = "agentPreset") -> str:
    """Validate a preset id before dispatching a mutating runtime operation."""

    if not isinstance(value, str):
        raise JsonRpcError(-32602, f"{field} must be a preset id")
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > _MAX_AGENT_PRESET_ID_PARAM_LENGTH
        or _AGENT_PRESET_ID_PARAM_RE.fullmatch(candidate) is None
    ):
        raise JsonRpcError(
            -32602,
            f"{field} must use lowercase letters, digits, and hyphens; paths are not allowed",
        )
    return candidate


def _workspace_path_param(value: Any) -> str:
    if not isinstance(value, str):
        raise JsonRpcError(-32602, "workspace path must be an absolute path")
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > 4096
        or any(ord(char) < 32 or ord(char) == 127 for char in candidate)
    ):
        raise JsonRpcError(-32602, "workspace path must be non-empty and contain no control characters")
    if not Path(candidate).expanduser().is_absolute():
        raise JsonRpcError(-32602, "workspace path must be absolute")
    return candidate


def _workspace_checkpoint_param(value: Any) -> str:
    if not isinstance(value, str) or _WORKSPACE_CHECKPOINT_ID_RE.fullmatch(value.strip()) is None:
        raise JsonRpcError(-32602, "checkpoint_id is invalid")
    return value.strip()


def _workspace_branch_param(value: Any, field: str = "branch") -> str:
    if not isinstance(value, str):
        raise JsonRpcError(-32602, f"{field} must be a Git branch name")
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > 240
        or any(ord(char) < 32 or ord(char) == 127 for char in candidate)
    ):
        raise JsonRpcError(-32602, f"{field} must be non-empty and contain no control characters")
    return candidate


def _workspace_commit_message_param(value: Any) -> str:
    if not isinstance(value, str):
        raise JsonRpcError(-32602, "commit message must be text")
    candidate = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if (
        not candidate
        or len(candidate) > 4000
        or any(
            (ord(char) < 32 and char not in {"\n", "\t"}) or ord(char) == 127
            for char in candidate
        )
    ):
        raise JsonRpcError(-32602, "commit message must be non-empty and contain no unsupported control characters")
    return candidate


def _agent_preset_copy_params(params: dict[str, Any]) -> dict[str, Any]:
    source = _agent_preset_id_param(params.get("from") or params.get("source"), "from")
    destination = _agent_preset_id_param(
        params.get("agentPreset") or params.get("agent_preset") or params.get("id"),
        "agentPreset",
    )
    if source == destination:
        raise JsonRpcError(-32602, "from and agentPreset must differ")
    name = params.get("name")
    if name is not None:
        if not isinstance(name, str):
            raise JsonRpcError(-32602, "name must be text")
        name = name.strip()
        if (
            len(name) > _MAX_AGENT_PRESET_NAME_PARAM_LENGTH
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or any(separator in name for separator in ("/", "\\"))
            or ":" in name
        ):
            raise JsonRpcError(-32602, "name must be at most 240 characters and must not be a path")
    return {"from": source, "agentPreset": destination, "name": name}


def _redact_agent_payload(value: Any) -> Any:
    """Remove likely credential fields before agent metadata enters the audit log."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in ("token", "secret", "password", "apikey", "api_key", "authorization", "cookie")):
                result[str(key)] = "[redacted]"
            else:
                result[str(key)] = _redact_agent_payload(item)
        return result
    if isinstance(value, list):
        return [_redact_agent_payload(item) for item in value]
    return value


def _redact_browser_payload(value: Any) -> Any:
    """Keep browser audit events free of credentials and page contents."""

    if not isinstance(value, dict):
        return value
    allowed = {
        "id",
        "name",
        "profile",
        "profile_id",
        "character_id",
        "agent_id",
        "status",
        "state",
        "created_at",
        "updated_at",
        "expires_at",
        "lease_expires_at",
    }
    return {key: value[key] for key in allowed if key in value}


def _browser_external_help_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate the DSH-to-Core human takeover request without retaining it."""

    allowed = {"session_id", "domain", "reason", "title", "targets", "timeout_ms"}
    if set(params) - allowed:
        raise ValueError("browser human takeover contains unsupported fields")
    session_id = str(params.get("session_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", session_id):
        raise ValueError("external browser session id is invalid")
    reason = params.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
        raise ValueError("human takeover reason must be between 1 and 2000 characters")
    reason = reason.strip()
    if looks_like_secret_text(reason):
        raise ValueError("human takeover reason must not contain credential values")
    raw_domain = params.get("domain")
    domain = normalize_domain(raw_domain)
    title = params.get("title")
    if title is not None and (not isinstance(title, str) or len(title.strip()) > 120):
        raise ValueError("human takeover title is too long")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    raw_targets = params.get("targets", [])
    if not isinstance(raw_targets, list) or len(raw_targets) > 8:
        raise ValueError("human takeover targets must be an array of at most 8 items")
    targets: list[str] = []
    for target in raw_targets:
        if not isinstance(target, str) or not 1 <= len(target.strip()) <= 160:
            raise ValueError("human takeover target is invalid")
        targets.append(target.strip())
    timeout_ms = params.get("timeout_ms", 300_000)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 1_000 <= timeout_ms <= 900_000:
        raise ValueError("human takeover timeout_ms must be between 1000 and 900000")
    return {
        "session_id": session_id,
        "domain": domain,
        "reason": reason,
        "title": title,
        "targets": targets,
        "timeout_ms": timeout_ms,
    }


def _snapshot_target(params: dict[str, Any]) -> tuple[str, str | None]:
    scope = str(params.get("scope") or "system").strip().lower()
    aliases = {"module": "modules", "character": "characters", "memory": "memories"}
    scope = aliases.get(scope, scope)
    if scope not in {"system", "modules", "characters", "memories"}:
        raise ValueError("snapshot scope must be system, modules, characters, or memories")
    target = params.get("target_id")
    if target is None:
        target_key = {"modules": "module_id", "characters": "character_id", "memories": "memory_id"}.get(scope)
        if target_key:
            target = params.get(target_key)
    target_id = None if target in (None, "") else str(target)
    if scope == "system" and target_id is not None:
        raise ValueError("system snapshots cannot have a target id")
    return scope, target_id


def _snapshot_export_package(snapshot: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "format": "sumika.snapshot",
        "format_version": 1,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "snapshot": snapshot,
    }


def _validate_snapshot_export_package(package: dict[str, Any]) -> None:
    if package.get("format") != "sumika.snapshot" or package.get("format_version") != 1:
        raise ValueError("unsupported snapshot export format")
    snapshot = package.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("package.snapshot must be an object")
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if package.get("sha256") != digest:
        raise ValueError("snapshot export checksum does not match")


def _sanitize_imported_provider_credentials(payload: dict[str, Any]) -> dict[str, Any]:
    """Detach external snapshot files from this machine's credential vault."""
    sanitized = json.loads(json.dumps(payload, ensure_ascii=False))
    tables = sanitized.get("tables")
    if not isinstance(tables, dict):
        return sanitized
    profiles = tables.get("provider_profiles")
    if not isinstance(profiles, list):
        return sanitized
    for row in profiles:
        if not isinstance(row, dict):
            continue
        row["credential_ref"] = None
        row["secret_fields_json"] = "[]"
        if row.get("status") == "available":
            row["status"] = "unavailable"
    return sanitized


def _validate_character_name(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("character name must not be empty")
    if len(value.strip()) > 100:
        raise ValueError("character name is too long")


def _merge_character_config(current: Any, incoming: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(current, dict):
        current = {}
    result = dict(current)
    if incoming is None:
        return result
    for key, value in incoming.items():
        if key in {"persona", "avatar"} and isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def _validate_character_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    result = json.loads(json.dumps(config, ensure_ascii=False))
    language = result.get("language")
    if language is not None and (not isinstance(language, str) or not language.strip() or len(language) > 32):
        raise ValueError("language must be a short non-empty string")
    result["persona"] = normalize_persona(result.get("persona"))
    avatar_value = result.get("avatar")
    if avatar_value is None:
        avatar: dict[str, Any] = {}
    elif isinstance(avatar_value, dict):
        avatar = dict(avatar_value)
    else:
        raise ValueError("avatar must be an object")
    avatar.setdefault("position", "center")
    avatar.setdefault("opacity", 1)
    avatar.setdefault("scale", 1)
    avatar.setdefault("idle_motion", True)
    avatar.setdefault("auto_rotate", False)
    avatar.setdefault("rotation_speed", 0.12)
    avatar.setdefault("natural_pose", True)
    avatar.setdefault("look_at_enabled", True)
    avatar.setdefault("head_follow_enabled", True)
    avatar.setdefault("look_at_strength", 1.0)
    avatar.setdefault("head_follow_strength", 0.35)
    position = avatar.get("position")
    if position not in {"left", "center", "right"}:
        raise ValueError("avatar.position must be left, center, or right")
    opacity = avatar.get("opacity")
    if not isinstance(opacity, (int, float)) or isinstance(opacity, bool) or not 0 <= opacity <= 1:
        raise ValueError("avatar.opacity must be between 0 and 1")
    scale = avatar.get("scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0.5 <= scale <= 2.5:
        raise ValueError("avatar.scale must be between 0.5 and 2.5")
    for key in ("idle_motion", "auto_rotate", "natural_pose", "look_at_enabled", "head_follow_enabled"):
        if not isinstance(avatar.get(key), bool):
            raise ValueError(f"avatar.{key} must be a boolean")
    rotation_speed = avatar.get("rotation_speed")
    if (
        not isinstance(rotation_speed, (int, float))
        or isinstance(rotation_speed, bool)
        or not 0.05 <= rotation_speed <= 0.4
    ):
        raise ValueError("avatar.rotation_speed must be between 0.05 and 0.4")
    for key in ("look_at_strength", "head_follow_strength"):
        strength = avatar.get(key)
        if (
            not isinstance(strength, (int, float))
            or isinstance(strength, bool)
            or not 0 <= strength <= 1
        ):
            raise ValueError(f"avatar.{key} must be between 0 and 1")
    result["avatar"] = avatar
    memory_enabled = result.get("memory_enabled")
    if memory_enabled is not None and not isinstance(memory_enabled, bool):
        raise ValueError("memory_enabled must be a boolean")
    for key in ("avatar_driver", "avatar_model_id"):
        value = result.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise ValueError(f"{key} must be a short string")
    return result


def _decode_audio(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("audio_base64 must be a non-empty string")
    try:
        audio = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("audio_base64 is invalid") from exc
    if not audio:
        raise ValueError("audio_base64 must not decode to an empty buffer")
    if len(audio) > 10 * 1024 * 1024:
        raise ValueError("audio buffer is too large")
    return audio


def _decode_image(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("image_base64 must be a non-empty string")
    try:
        image = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("image_base64 is invalid") from exc
    if not image:
        raise ValueError("image_base64 must not decode to an empty buffer")
    if len(image) > 10 * 1024 * 1024:
        raise ValueError("image buffer is too large")
    return image
