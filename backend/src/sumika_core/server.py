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
from dataclasses import replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from .audio import AudioRuntime, AudioRuntimeError
from .agent import AgentCapability, AgentRuntime, AgentRuntimeError, SkillCatalog, SkillCatalogError, create_agent_runtime
from .agent.adapters.zcode.config import config_from_env as zcode_config_from_env
from .agent.adapters.zcode.runtime import ZCodeAgentRuntime
from .agent.runtime_workers import (
    DesktopAutomationWorker,
    ExternalHarnessClientWorker,
    ExternalHarnessRouteSource,
    LegacyWebWorker,
    NativeRuntimeWorker,
    ProviderProfileWorker,
    ZCodeExternalHarnessWorker,
)
from .agent.routes import (
    AGENT_ROUTE_SCHEMA,
    ConsultationRequest,
    RouteCoordinator,
    RouteError,
    RouteValidationError,
    SubtaskDispatch,
)
from .agent.supervisor import (
    DynamicRouteEvidence,
    DynamicRouteSupervisor,
    RuntimeRouteDescriptor,
    SupervisorError,
    SupervisorValidationError,
    WorkerRegistry,
)
from .agent.route_trace import RouteDecisionTrace
from .avatar import AvatarError, AvatarManager
from .capabilities import CapabilityCatalog, CapabilityCatalogError
from .browser import (
    BrowserRuntime,
    BrowserRuntimeError,
    WebChatRuntime,
    WebChatRuntimeError,
    WebChatProvider,
    looks_like_secret_text,
    normalize_domain,
)
from .credentials import CredentialStore, credential_namespace_for_data_dir, default_credential_store
from .events import EventBus
from .evolution import EvolutionRegistry
from .diagnostics import close_logging, configure_logging, redact_text, safe_error
from .desktop_automation import DesktopAutomationError, DesktopAutomationRuntime
from .integrations import CCSwitchCompatibilityChecker
from .memory import MemoryRuntime, MemoryRuntimeError
from .model_policy import (
    ModelPolicyError,
    ModelPolicyService,
    RoutingRequest,
    routing_request_from_dict,
)
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

# The route bridge is an optional DSH-side adapter.  Keep its registration
# contract in Core so a discovered plugin cannot claim that it is mounted
# merely because a manifest or source directory exists.
ROUTE_BRIDGE_PLUGIN_ID = "sumika.dsh-route-bridge"
ROUTE_BRIDGE_VERSION = "0.1.0"
ROUTE_BRIDGE_TOOL_NAMES = frozenset(
    {
        "sumika_route_catalog",
        "sumika_route_replan",
        "sumika_route_dispatch",
        "sumika_route_status",
        "sumika_consultation_start",
        "sumika_consultation_status",
        "sumika_route_cancel",
        "sumika_route_retry",
        "sumika_route_arm",
        "sumika_route_pending",
        "sumika_route_ack",
    }
)
ROUTE_BRIDGE_LEGACY_TOOL_NAMES = frozenset(
    {
        "sumika_route_catalog",
        "sumika_route_replan",
        "sumika_route_dispatch",
        "sumika_route_status",
        "sumika_consultation_start",
        "sumika_consultation_status",
        "sumika_route_cancel",
        "sumika_route_retry",
    }
)
ROUTE_BRIDGE_CANONICAL_TOOLS = (
    {"name": "sumika.route.catalog", "description": "List consented runtime-neutral routes"},
    {"name": "sumika.route.replan", "description": "Replan a route at an Agent event boundary"},
    {"name": "sumika.route.dispatch", "description": "Dispatch one isolated route worker"},
    {"name": "sumika.route.status", "description": "Read one route worker status"},
    {"name": "sumika.consultation.start", "description": "Ask independent web profiles in parallel"},
    {"name": "sumika.consultation.status", "description": "Read consultation progress and untrusted results"},
    {"name": "sumika.route.cancel", "description": "Cancel a pending route or consultation"},
    {"name": "sumika.route.retry", "description": "Retry only a confirmed pre-send failure"},
    {"name": "sumika.route.arm", "description": "Arm an explicit parent turn request for a later boundary"},
    {"name": "sumika.route.pending", "description": "Read terminal worker results waiting for parent acknowledgement"},
    {"name": "sumika.route.ack", "description": "Acknowledge one terminal worker result"},
)


def _route_identifier_fragment(value: Any, *, preserve_colons: bool = False) -> str:
    """Return a portable route-id fragment without exposing arbitrary text."""

    text = str(value or "").strip()
    allowed = r"A-Za-z0-9._:-" if preserve_colons else r"A-Za-z0-9._-"
    text = re.sub(fr"[^{allowed}]+", "-", text).strip("-")
    return text[:160] or "unknown"


def _route_quality_tier(model_id: Any) -> str:
    """Conservative quality hint for a runtime model declaration.

    This is only a routing hint; real quality remains determined by the
    fixed evaluation samples recorded by the model-policy layer.
    """

    name = str(model_id or "").lower()
    if any(token in name for token in ("opus", "o1", "o3", "5.3", "5.2", "reason", "pro")):
        return "strong"
    if any(token in name for token in ("flash", "mini", "1.7b", "small", "lite")):
        return "basic"
    return "standard"


def _route_event_boundary(event: Mapping[str, Any] | Any) -> str | None:
    """Normalize public Harness turn markers to supervisor boundaries.

    DSH emits a normalized ``session/event`` envelope whose actual event is
    under ``extensions.event.type`` and whose terminal state is under
    ``extensions.turn.state``.  ZCode uses the same outer envelope but puts
    its wire method in ``extensions.method``.  Keep this parser deliberately
    structural: arbitrary ``status=completed`` fields are not a turn boundary
    unless a turn marker is present in the same envelope.
    """

    if not isinstance(event, Mapping):
        return None

    def mappings(value: Any, depth: int = 0) -> list[Mapping[str, Any]]:
        if depth > 5:
            return []
        if not isinstance(value, Mapping):
            if isinstance(value, (list, tuple)):
                result: list[Mapping[str, Any]] = []
                for item in list(value)[:32]:
                    result.extend(mappings(item, depth + 1))
                return result
            return []
        result = [value]
        # These are protocol envelope keys.  Do not recursively inspect
        # arbitrary response fields where a user-controlled ``type`` could
        # accidentally become a scheduler trigger.
        for key in ("extensions", "event", "params", "data", "payload", "result"):
            nested = value.get(key)
            if isinstance(nested, (Mapping, list, tuple)):
                result.extend(mappings(nested, depth + 1))
        return result

    def marker(value: Any) -> str:
        return str(value or "").strip().lower().replace("/", ".").replace("_", ".").replace("-", ".")

    rows = mappings(event)
    explicit: list[str] = []
    turn_states: list[str] = []
    for row in rows:
        for key in ("event_type", "type", "method", "name"):
            value = marker(row.get(key))
            if value:
                explicit.append(value)
        # State is meaningful only on an explicitly named turn object or a
        # turn end marker.  A generic model/tool ``status`` is not enough.
        row_marker = marker(row.get("event_type") or row.get("type") or row.get("method") or row.get("name"))
        if "turn" in row_marker or row is event and isinstance(row.get("extensions"), Mapping) and isinstance(row["extensions"].get("turn"), Mapping):
            for key in ("state", "status"):
                value = marker(row.get(key))
                if value:
                    turn_states.append(value)
        turn = row.get("turn")
        if isinstance(turn, Mapping):
            for key in ("type", "event_type", "method", "state", "status"):
                value = marker(turn.get(key))
                if value:
                    (explicit if key not in {"state", "status"} else turn_states).append(value)

    # Failure/cancellation states take precedence over a generic turn/end
    # marker.  This covers DSH reason.kind and ZCode model_request_failed.
    failure_markers = {"turn.failed", "turn.fail", "turn.error", "turn.failure", "model.request.failed", "runtime.error", "turn.aborted"}
    cancel_markers = {"turn.cancelled", "turn.canceled", "turn.cancel", "turn.stopped", "turn.interrupted", "turn.aborted"}
    if any(value in failure_markers or "model.request.failed" in value for value in explicit) or any(value in {"failed", "error", "failure"} for value in turn_states):
        return "turn.failed"
    if any(value in cancel_markers for value in explicit) or any(value in {"cancelled", "canceled", "stopped", "interrupted", "aborted"} for value in turn_states):
        return "turn.cancelled"
    if any(value in {"turn.started", "turn.start"} for value in explicit):
        return "turn.started"
    if any(value in {"turn.completed", "turn.complete", "turn.end", "turn.ended", "turn.success"} for value in explicit):
        return "turn.completed"
    if any(value in {"tool.completed", "tool.result"} for value in explicit):
        return "tool.completed"
    if any(value in {"approval.resolved", "approval.resolve"} for value in explicit):
        return "approval.resolved"
    return None


class CoreApplication:
    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        test_providers: dict[str, list[Any]] | None = None,
        credential_store: CredentialStore | None = None,
        agent_runtime: AgentRuntime | None = None,
        external_route_sources: Iterable[Any] | None = None,
        route_sources: Iterable[Any] | None = None,
    ) -> None:
        configured_dir = data_dir or os.getenv("SUMIKA_DATA_DIR", str(ROOT_DIR / ".sumika"))
        self.data_dir = Path(configured_dir) if str(configured_dir) != ":memory:" else Path(".")
        self.configured_data_dir = None if str(configured_dir) == ":memory:" else self.data_dir
        self.logger, self.log_path = configure_logging(self.configured_data_dir)
        # The observability stream is intentionally separate from SQLite's
        # product audit events.  It stores only bounded, content-independent
        # receipts for offline maintenance analysis.
        self.observability = AgentObservability(self.configured_data_dir, logger=self.logger)
        self.route_trace = RouteDecisionTrace(self.configured_data_dir, logger=self.logger)
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
        # DSH/plugin bridge handshakes are deliberately process-local.  A
        # Core restart must require the managed plugin to prove that it is
        # mounted again; no persisted flag is trusted for this purpose.
        self._route_bridge_registrations: dict[str, dict[str, Any]] = {}
        # ZCode is an optional external Harness worker.  It is created only
        # when the user explicitly configures an executable (or opts in to
        # the narrow install discovery setting); construction is inert and
        # does not start a process or inspect private credentials.  When
        # ZCode itself is the selected main runtime, do not register it as a
        # child worker as that would create a self-referential route.
        self.zcode_runtime = self._create_optional_zcode_runtime()
        # External Harnesses are explicit dependency-injection slots. Core
        # never discovers a client, reads its credentials, or starts a
        # process implicitly; callers may register a source before the route
        # supervisor is initialized (the normal plugin/fixture path).
        self._external_route_sources: dict[str, Any] = {}
        self._external_route_workers: dict[str, Any] = {}
        # Replaced sources may still have an in-flight request.  They are
        # detached from routing immediately and closed once Core shuts down,
        # rather than risking a transport close while a worker is active.
        self._retired_external_workers: list[Any] = []
        self._initial_external_route_sources = tuple(external_route_sources or ()) + tuple(route_sources or ())
        # Registration is inert: no external desktop process or window is
        # started until an approved RPC explicitly opens a session.
        self.desktop_automation = DesktopAutomationRuntime(
            self.configured_data_dir,
            storage=self.storage,
            logger=self.logger,
            agent_runtime=self.agent,
        )
        self.browser = BrowserRuntime(
            self.configured_data_dir,
            logger=self.logger,
            storage=self.storage,
        )
        self.web_chat = WebChatRuntime(
            self.storage,
            self.browser,
            logger=self.logger,
        )
        # Web workers and consultation panels are a capability bridge around
        # WebChatRuntime.  They do not become a second Agent loop or a second
        # source of DSH session state.
        self.routes = RouteCoordinator(
            self.web_chat,
            self.storage,
            logger=self.logger,
            event_sink=self._on_route_event,
        )
        # A BrowserSkill session may be stopped outside Core.  WebChat only
        # invokes this metadata-only callback after an explicit missing-session
        # signal, so a transient network error cannot clear a live route's
        # legacy occupancy marker.
        self.web_chat.set_session_invalidated_callback(self.routes.clear_stale_occupancy)
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
        self._sync_web_chat_providers()
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
        self.model_policy = ModelPolicyService(
            self.provider_profiles,
            self.agent,
            self.configured_data_dir,
            logger=self.logger,
            web_chat=self.web_chat,
        )
        self._register_initial_external_route_sources()
        self._initialize_route_supervisor()
        self.capabilities = CapabilityCatalog(
            self.modules,
            agent=self.agent,
            browser=self.browser,
            plugins=self.plugins,
            skills=self.skills,
            model_policy=self.model_policy,
            desktop_automation=self.desktop_automation,
            logger=self.logger,
        )
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

    # ------------------------------------------------------------------
    # Runtime-neutral route supervision
    # ------------------------------------------------------------------
    def _create_optional_zcode_runtime(self) -> AgentRuntime | None:
        """Construct the optional ZCode worker without touching its process.

        ZCode owns its login/session state.  Core only reads the explicitly
        documented launcher settings and keeps the adapter dormant until a
        route refresh or dispatch actually needs it.  In particular, do not
        call ``health``/``runtime_models`` here: creating a CoreApplication
        must remain side-effect free when ZCode is not selected.
        """

        self._zcode_runtime_config_error: str | None = None
        self._zcode_runtime_owned = False
        # A ZCode main runtime is already owned by ``self.agent``.  Registering
        # it again as an external worker would create a self-referential route
        # and could close the active Agent twice during shutdown.
        if str(getattr(self.agent, "runtime_id", "")).strip().lower() == "zcode":
            return None
        try:
            config = zcode_config_from_env(self.configured_data_dir)
        except (OSError, TypeError, ValueError) as exc:
            self._zcode_runtime_config_error = type(exc).__name__
            self.logger.info(
                "optional zcode configuration unavailable error_type=%s",
                type(exc).__name__,
            )
            return None
        if not getattr(config, "enabled", False) or not getattr(config, "executable", None):
            return None
        try:
            runtime = ZCodeAgentRuntime(
                self.configured_data_dir,
                logger=self.logger,
                config=config,
            )
        except (OSError, TypeError, ValueError) as exc:
            self._zcode_runtime_config_error = type(exc).__name__
            self.logger.info(
                "optional zcode runtime construction unavailable error_type=%s",
                type(exc).__name__,
            )
            return None
        self._zcode_runtime_owned = True
        return runtime

    def _register_initial_external_route_sources(self) -> None:
        """Install explicitly supplied Harness sources before route startup.

        This method is intentionally the only place where the optional
        ZCode adapter is projected into the generic external-Harness slot.
        The adapter remains dormant until an explicit catalog refresh or
        dispatch asks it to do work.  Other Harnesses are supplied by plugins
        or tests through the constructor/registration method below.
        """

        initial = self._initial_external_route_sources
        self._initial_external_route_sources = ()
        for source in initial:
            try:
                self.register_external_route_source(source)
            except (ModelPolicyError, TypeError, ValueError) as exc:
                self.logger.warning(
                    "external route source registration skipped error_type=%s",
                    type(exc).__name__,
                )

        # Keep the installed ZCode adapter available as a generic Harness
        # source for compatibility, while retaining its protocol-specific
        # event worker.  No ZCode desktop automation is involved here.
        if self.zcode_runtime is not None:
            try:
                self.register_external_route_source(
                    ExternalHarnessRouteSource(
                        self.zcode_runtime,
                        source_id="zcode",
                        worker=ZCodeExternalHarnessWorker(self.zcode_runtime),
                        cost_class="unknown",
                        processing_location="cloud",
                    )
                )
            except (ModelPolicyError, TypeError, ValueError) as exc:
                self.logger.warning(
                    "optional zcode route source unavailable error_type=%s",
                    type(exc).__name__,
                )

    def register_external_route_source(
        self,
        source: Any,
        *,
        source_id: str | None = None,
        worker: Any = None,
        worker_factory: Any = None,
        quota_consent: str | bool = "unknown",
        cost_class: str = "unknown",
        processing_location: str = "cloud",
    ) -> str:
        """Register one explicit, runtime-neutral external Harness source.

        ``source`` may already implement ``model_entries`` and ``worker`` or
        may be a public client exposing the common Harness methods.  In the
        latter case Core wraps it without inspecting credentials or private
        configuration.  Registration is safe to repeat; the newest source
        replaces the previous source with the same identifier.
        """

        if source is None:
            raise ModelPolicyError("external route source is required")
        model_entries = getattr(source, "model_entries", None)
        source_worker = getattr(source, "worker", None)
        if not callable(model_entries) or not callable(source_worker):
            source = ExternalHarnessRouteSource(
                source,
                source_id=source_id,
                worker=worker,
                worker_factory=worker_factory if callable(worker_factory) else None,
                quota_consent=quota_consent,
                cost_class=cost_class,
                processing_location=processing_location,
            )
        elif worker is not None:
            # A caller can override a source's worker while keeping its
            # catalog implementation.  This is useful for protocol fixtures
            # and does not alter the source's client.
            source = ExternalHarnessRouteSource(
                getattr(source, "client", source),
                source_id=source_id or getattr(source, "source_id", None),
                worker=worker,
                quota_consent=quota_consent,
                cost_class=cost_class,
                processing_location=processing_location,
            )
        # Let the policy service validate/normalize the identifier before
        # detaching an existing source.  If validation fails, the old source
        # remains fully usable.
        identifier = self.model_policy.register_route_source(source, source_id=source_id)
        previous_source = self._external_route_sources.get(identifier)
        previous_worker = self._external_route_workers.get(identifier)
        if (previous_source is not None and previous_source is not source) or (
            previous_source is None and previous_worker is not None
        ):
            self._detach_external_route_source(
                identifier,
                previous_source,
                previous_worker,
            )
        self._external_route_sources[identifier] = source
        if hasattr(self, "route_supervisor"):
            self._bind_external_route_worker(identifier, source)
            # A registration made after startup is visible immediately in the
            # next local catalog projection; live probing remains explicit.
            self._refresh_route_supervisor_catalog(refresh=False)
        return identifier

    # Short, discoverable alias used by plugin integrations.
    register_external_harness = register_external_route_source

    def unregister_external_route_source(self, source_id: str) -> bool:
        """Remove an explicitly registered source and its route bindings."""

        identifier = str(source_id or "").strip().lower()
        if not identifier:
            return False
        source = self._external_route_sources.pop(identifier, None)
        removed = self.model_policy.unregister_route_source(identifier)
        worker = self._external_route_workers.get(identifier)
        if source is not None or worker is not None:
            self._detach_external_route_source(identifier, source, worker)
        if hasattr(self, "route_supervisor"):
            self._refresh_route_supervisor_catalog(refresh=False)
        return bool(source is not None or removed)

    unregister_external_harness = unregister_external_route_source

    @staticmethod
    def _external_source_worker_id(source_id: str, source: Any) -> str:
        value = str(getattr(source, "worker_id", "") or "").strip()
        if value:
            return value
        return f"external-{_route_identifier_fragment(source_id)}"

    def _detach_external_route_source(
        self,
        source_id: str,
        source: Any | None,
        worker: Any | None = None,
    ) -> None:
        """Remove one external worker binding and close it when idle.

        Source replacement is a lifecycle boundary.  Keeping the old worker
        in ``WorkerRegistry`` would let stale route bindings execute against
        a client that is no longer registered; reusing the old worker would
        also silently discard the newly supplied client.  Active runs retain
        their object reference until completion, so an in-flight transport is
        not closed underneath them.
        """

        identifier = str(source_id or "").strip().lower()
        old_worker = worker or self._external_route_workers.get(identifier)
        self._external_route_workers.pop(identifier, None)
        registry = getattr(getattr(self, "route_supervisor", None), "worker_registry", None)
        worker_id = self._external_source_worker_id(identifier, source) if source is not None else f"external-{_route_identifier_fragment(identifier)}"
        registered = registry.get(worker_id) if registry is not None and hasattr(registry, "get") else None
        if registry is not None and callable(getattr(registry, "unregister", None)):
            # A replacement can have a custom worker id.  Only remove the
            # binding when it still points at the worker being detached.
            should_unregister = registered is not None and (
                old_worker is None or registered is old_worker
            )
            if should_unregister:
                try:
                    registry.unregister(worker_id)
                except Exception as exc:
                    self.logger.info(
                        "external route worker unregister failed source=%s error_type=%s",
                        identifier,
                        type(exc).__name__,
                    )

        if old_worker is None:
            return
        # Do not close a worker that is still executing a dispatched request.
        active = False
        supervisor = getattr(self, "route_supervisor", None)
        runs = getattr(supervisor, "_runs", None)
        lock = getattr(supervisor, "_lock", None)
        if isinstance(runs, dict):
            try:
                if lock is not None:
                    with lock:
                        active = any(
                            getattr(record, "worker", None) is old_worker
                            and getattr(record, "status", None) in {"queued", "running"}
                            for record in runs.values()
                        )
                else:
                    active = any(
                        getattr(record, "worker", None) is old_worker
                        and getattr(record, "status", None) in {"queued", "running"}
                        for record in runs.values()
                    )
            except Exception:
                active = True
        if active:
            if old_worker not in self._retired_external_workers:
                self._retired_external_workers.append(old_worker)
            return
        closer = getattr(old_worker, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception as exc:
                self.logger.info(
                    "external route worker close failed source=%s error_type=%s",
                    identifier,
                    type(exc).__name__,
                )

    def _bind_external_route_worker(self, source_id: str, source: Any) -> Any | None:
        """Create and register a source worker without probing its client."""

        worker = self._external_route_workers.get(source_id)
        if worker is None:
            factory = getattr(source, "worker", None)
            if not callable(factory):
                return None
            worker = factory()
            if worker is None:
                return None
            self._external_route_workers[source_id] = worker
        worker_id = self._external_source_worker_id(source_id, source)
        self.route_supervisor.register_worker(worker_id, worker)
        return worker

    def _initialize_route_supervisor(self) -> None:
        """Create the scheduler and install only inert route bindings."""

        self._route_supervisor_runtime_routes: list[RuntimeRouteDescriptor] = []
        self._zcode_route_cache: list[RuntimeRouteDescriptor] = []
        self._route_supervisor_last_refresh: str | None = None
        registry = WorkerRegistry()
        # Registering workers is dependency injection only.  None of these
        # constructors starts a process or performs a network request.
        registry.register("web-coordinator", LegacyWebWorker(self.routes))
        registry.register(
            "desktop-automation",
            DesktopAutomationWorker(self.desktop_automation),
        )
        # Bind every explicitly registered external Harness through the same
        # worker slot.  The source factory is expected to be inert; no health
        # or model probe occurs until an explicit catalog refresh.
        for source_id, source in list(self._external_route_sources.items()):
            try:
                worker = self._external_route_workers.get(source_id)
                if worker is None:
                    factory = getattr(source, "worker", None)
                    worker = factory() if callable(factory) else None
                    if worker is not None:
                        self._external_route_workers[source_id] = worker
                if worker is not None:
                    registry.register(self._external_source_worker_id(source_id, source), worker)
            except Exception as exc:
                self.logger.info(
                    "external route worker registration failed source=%s error_type=%s",
                    source_id,
                    type(exc).__name__,
                )
        if str(getattr(self.agent, "runtime_id", "")).strip().lower() not in {"", "unavailable"}:
            runtime_id = _route_identifier_fragment(getattr(self.agent, "runtime_id", "agent"))
            registry.register(
                f"native-{runtime_id}",
                NativeRuntimeWorker(self.agent, worker_id=f"native-{runtime_id}"),
            )
        self.route_supervisor = DynamicRouteSupervisor(
            registry,
            runtime=self.agent,
            orchestrator=self.agent,
            model_router=getattr(self.model_policy, "router", None),
            storage=self.storage,
            event_sink=self._on_supervisor_event,
            trace_sink=self.route_trace,
            logger=self.logger,
        )
        # Build profile/web projections only.  This deliberately avoids the
        # model-policy runtime probes performed by ``catalog(refresh=True)``.
        try:
            self._refresh_route_supervisor_catalog(refresh=False)
        except Exception as exc:
            # A malformed optional profile must not prevent the Core from
            # starting.  The explicit catalog RPC can retry and report the
            # bounded failure through the event stream.
            self.logger.warning(
                "route supervisor initial catalog unavailable error_type=%s",
                type(exc).__name__,
            )
            self.route_supervisor.set_route_catalog([])

    def _refresh_route_supervisor_catalog(
        self,
        *,
        refresh: bool = False,
        include_templates: bool = True,
        include_unavailable: bool = True,
    ) -> dict[str, Any]:
        """Synchronize route descriptors and worker bindings.

        ``refresh=False`` is a local projection of saved profiles and the
        previous runtime observations.  ``refresh=True`` is the explicit
        boundary at which DSH/ZCode health, model and quota probes are allowed.
        """

        entries: list[Any] = []
        # These two model-policy projections are read-only and do not probe a
        # Harness.  They keep the catalog useful before an external runtime is
        # started.
        for method_name in ("_profile_entries", "_web_entries", "external_entries"):
            method = getattr(self.model_policy, method_name, None)
            if callable(method):
                try:
                    values = method()
                except Exception as exc:
                    self.logger.info(
                        "route catalog source failed source=%s error_type=%s",
                        method_name,
                        type(exc).__name__,
                    )
                    values = []
                if isinstance(values, (list, tuple)):
                    entries.extend(values)

        if refresh:
            try:
                policy_catalog = self.model_policy.catalog(refresh=True)
            except Exception as exc:
                policy_catalog = None
                self.logger.info(
                    "route catalog runtime refresh failed error_type=%s",
                    type(exc).__name__,
                )
            if isinstance(policy_catalog, dict) and isinstance(policy_catalog.get("entries"), list):
                entries.extend(policy_catalog["entries"])
            self._route_supervisor_runtime_routes = [
                route
                for route in self._route_supervisor_runtime_routes
                if route.runtime_id not in {"dsh", str(getattr(self.agent, "runtime_id", ""))}
            ]
            self._route_supervisor_runtime_routes.extend(
                self._runtime_model_routes_from_catalog(policy_catalog)
            )
            # ZCode, when configured, is registered above as an external
            # source.  The legacy projection is retained only for callers
            # that explicitly use the old helper and must not duplicate the
            # generic source entries in the live catalog.
            self._zcode_route_cache = [] if "zcode" in self._external_route_sources else self._zcode_worker_routes(refresh=True)
        # External Harness entries are projected by ``external_entries``
        # above.  Never retain them in the generic runtime cache as well:
        # otherwise an unregistered/replaced source can leave a stale route
        # visible after the next local refresh, and the same model appears
        # twice.  Native Harness routes (for example DSH itself) remain in
        # this cache.
        self._route_supervisor_runtime_routes = [
            route
            for route in self._route_supervisor_runtime_routes
            if route.kind != "external-harness" and route.source_kind != "external-harness"
        ]
        entries.extend(self._route_supervisor_runtime_routes)
        entries.extend(self._zcode_route_cache)
        try:
            desktop_catalog = self.desktop_automation.catalog(
                refresh=refresh,
                include_unavailable=True,
            )
        except Exception as exc:
            desktop_catalog = None
            self.logger.info(
                "desktop route catalog unavailable error_type=%s",
                type(exc).__name__,
            )
        entries.extend(self._desktop_application_routes(desktop_catalog))

        # Read the legacy coordinator's local occupancy projection as a
        # compatibility bridge.  The modern descriptor is rebuilt from the
        # model-policy entry below, but a manual workbench/takeover marker is
        # still owned by the coordinator and must remain authoritative for
        # the shared BrowserSkill Profile lease.
        web_occupancy: dict[str, str] = {}
        try:
            legacy_catalog = self.routes.catalog(include_templates=False)
            for row in legacy_catalog.get("routes", []) if isinstance(legacy_catalog, Mapping) else []:
                if not isinstance(row, Mapping):
                    continue
                profile_id = str(row.get("provider_profile_id") or "").strip()
                occupancy = str(row.get("occupancy") or "idle").strip().lower()
                if profile_id and occupancy in {"idle", "agent", "manual", "waiting"}:
                    web_occupancy[profile_id] = occupancy
        except Exception as exc:
            self.logger.info(
                "route catalog occupancy projection unavailable error_type=%s",
                type(exc).__name__,
            )

        # De-duplicate transformed web/profile entries while preserving the
        # newest (explicit refresh) observation.
        descriptors: dict[str, RuntimeRouteDescriptor] = {}
        for entry in entries:
            try:
                descriptor = self._model_entry_to_route(entry)
            except (TypeError, ValueError, RouteValidationError) as exc:
                self.logger.info(
                    "route catalog entry skipped error_type=%s",
                    type(exc).__name__,
                )
                continue
            if descriptor.source_kind == "web-chat" and descriptor.provider_profile_id:
                occupancy = web_occupancy.get(descriptor.provider_profile_id)
                if occupancy and occupancy != descriptor.occupancy:
                    descriptor = replace(
                        descriptor,
                        occupancy=occupancy,
                        # ``available`` already accounts for manual/waiting
                        # occupancy.  Keep the source routability bit intact
                        # so a later lease release can restore it.
                        reason=("profile-occupied" if occupancy in {"manual", "waiting"} else descriptor.reason),
                    )
            if not include_templates and descriptor.source_kind == "web-chat" and not descriptor.provider_profile_id:
                continue
            descriptors[descriptor.route_id] = descriptor

        # Rebuild bindings atomically from the supervisor's point of view.
        self.route_supervisor.set_route_catalog([])
        for route in descriptors.values():
            worker = self._worker_for_route(route)
            if worker is not None:
                self.route_supervisor.register_route(route, worker=worker)
            else:
                self.route_supervisor.register_route(route)
        self._route_supervisor_last_refresh = datetime.now(timezone.utc).isoformat()
        result = self.route_supervisor.catalog(
            include_unavailable=include_unavailable,
            include_evidence=True,
        )
        result["refresh_requested"] = bool(refresh)
        result["last_refresh"] = self._route_supervisor_last_refresh
        if self._zcode_runtime_config_error:
            result["zcode_config"] = {
                "configured": False,
                "error_type": self._zcode_runtime_config_error,
            }
        return result

    def _runtime_model_routes_from_catalog(self, catalog: Any) -> list[RuntimeRouteDescriptor]:
        if not isinstance(catalog, dict) or not isinstance(catalog.get("entries"), list):
            return []
        result: list[RuntimeRouteDescriptor] = []
        for raw in catalog["entries"]:
            if not isinstance(raw, dict):
                continue
            source_kind = str(raw.get("source_kind") or "").lower()
            harness_id = str(raw.get("harness_id") or "").lower()
            # External route sources have their own explicit projection and
            # worker lifecycle.  Keeping them in the generic runtime cache
            # would survive source removal and duplicate their entries.
            if source_kind in {"external", "external-harness"}:
                continue
            if source_kind != "harness" and not harness_id:
                continue
            try:
                result.append(self._model_entry_to_route(raw))
            except (TypeError, ValueError, RouteValidationError):
                continue
        return result

    @staticmethod
    def _desktop_application_routes(catalog: Any) -> list[RuntimeRouteDescriptor]:
        """Project approved desktop applications into the neutral route slot.

        The public desktop catalog intentionally omits launcher paths and
        adapter configuration.  A route therefore carries only an ``app_id``
        and safe capability/health metadata; ``DesktopAutomationRuntime``
        remains authoritative for the real declaration and action approval.
        """

        rows = catalog.get("apps", []) if isinstance(catalog, Mapping) else []
        result: list[RuntimeRouteDescriptor] = []
        for raw in rows if isinstance(rows, list) else []:
            if not isinstance(raw, Mapping) or raw.get("approved") is not True:
                continue
            app_id = str(raw.get("app_id") or "").strip()
            adapter_id = str(raw.get("adapter_id") or "desktop").strip().lower()
            if not app_id:
                continue
            status_value = str(raw.get("status") or "unavailable").strip().lower()
            configured = raw.get("configured") is True
            if status_value in {"ready", "running"}:
                status = "ready"
                health = "healthy"
                routable = True
            elif status_value == "configured" and configured:
                status = "configured"
                health = "unknown"
                routable = True
            else:
                status = "unavailable"
                health = "unavailable" if status_value in {"unavailable", "error", "disabled", "revoked"} else "unknown"
                routable = False
            lease_owner = str(raw.get("lease_owner") or "none").strip().lower()
            if lease_owner == "manual":
                occupancy = "manual"
            elif lease_owner in {"agent", "system"}:
                occupancy = "agent"
            elif str(raw.get("lease_state") or "idle").lower() == "leased":
                occupancy = "waiting"
            else:
                occupancy = "idle"
            capabilities = ["desktop"]
            for item in raw.get("capabilities") or ():
                value = str(item).strip().lower().replace("_", "-")
                if value and value not in capabilities:
                    capabilities.append(value)
            result.append(
                RuntimeRouteDescriptor(
                    route_id=f"desktop:{_route_identifier_fragment(app_id)}",
                    kind="desktop-app",
                    label=str(raw.get("name") or app_id),
                    runtime_id="desktop",
                    executor="desktop-automation",
                    transport=str(raw.get("transport") or "app-protocol"),
                    # Action-level effects are checked by the desktop runtime;
                    # marking the entire route external would also block safe
                    # observations before that more precise gate can run.
                    side_effect="none",
                    quota_consent="granted",
                    provider_key=f"desktop-{_route_identifier_fragment(app_id)}",
                    adapter_id=adapter_id or None,
                    capabilities=tuple(capabilities),
                    status=status,
                    routable=routable,
                    occupancy=occupancy,
                    quota_state="not-applicable",
                    requires_confirmation=False,
                    reason=None if routable else f"desktop-app-{status_value or 'unavailable'}",
                    source="desktop-automation",
                    source_kind="desktop-automation",
                    quality_tier="standard",
                    cost_class="local",
                    processing_location="local",
                    auth_state="authorized",
                    health_state=health,
                    metadata={
                        "app_id": app_id,
                        "adapter_id": adapter_id,
                        "approval_boundary": "desktop-runtime",
                        "default_action": "send",
                        "lease_owner": lease_owner,
                    },
                )
            )
        return result

    def _model_entry_to_route(self, entry: Any) -> RuntimeRouteDescriptor:
        """Translate a model-policy entry into the neutral route contract."""

        if isinstance(entry, RuntimeRouteDescriptor):
            return entry
        raw = entry.to_dict() if hasattr(entry, "to_dict") and callable(entry.to_dict) else dict(entry)
        if not isinstance(raw, dict):
            raise RouteValidationError("model entry must be an object")
        source_kind = str(raw.get("source_kind") or "provider").strip().lower()
        profile_id = str(raw.get("provider_profile_id") or "").strip() or None
        metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {}
        model_entry = {
            key: raw.get(key)
            for key in (
                "route_id", "provider_id", "model_id", "display_name",
                "provider_profile_id", "harness_id", "capabilities",
                "quality_tier", "cost_class", "processing_location",
                "auth_state", "quota_state", "health_state", "observed_at",
                "version", "source_kind", "transport",
            )
            if raw.get(key) is not None
        }
        metadata["model_entry"] = model_entry
        web_profile_id = str(metadata.get("web_profile_id") or "").strip()
        if source_kind == "web-chat" and profile_id and not web_profile_id:
            web_profile_id = profile_id
        # Web entries identify the named BrowserSkill profile in metadata,
        # while API routes use provider_profile_id. Promote it at this
        # adapter boundary so execution resolves the correct profile.
        if source_kind == "web-chat" and not profile_id and web_profile_id:
            profile_id = web_profile_id
        reason = raw.get("reason")
        if source_kind == "web-chat":
            web_route_key = web_profile_id or str(raw.get("provider_id") or raw.get("route_id") or "web")
            route_id = f"web:{_route_identifier_fragment(web_route_key)}"
            kind = "web-worker"
            runtime_id = "browserskill"
            executor = "web-coordinator"
        else:
            route_id = str(raw.get("route_id") or "").strip()
            if not route_id:
                provider = _route_identifier_fragment(raw.get("provider_id") or "provider")
                model = _route_identifier_fragment(raw.get("model_id") or "model")
                route_id = f"provider:{provider}:{model}"
            route_id = _route_identifier_fragment(route_id, preserve_colons=True)
            harness_id = str(raw.get("harness_id") or "").strip().lower()
            external_source_id = str(
                metadata.get("external_source_id")
                or raw.get("external_source_id")
                or raw.get("externalSourceId")
                or ""
            ).strip().lower()
            is_external = bool(
                source_kind in {"external-harness", "external"}
                or metadata.get("external_harness") is True
                or metadata.get("externalHarness") is True
                or external_source_id
            )
            if is_external:
                external_source_id = external_source_id or harness_id
                source = self._external_route_sources.get(external_source_id)
                kind = "external-harness"
                runtime_id = external_source_id or harness_id or "external"
                executor = self._external_source_worker_id(external_source_id, source) if source is not None else f"external-{_route_identifier_fragment(runtime_id)}"
                # A catalog entry from an unregistered source is useful for
                # diagnostics, but it must never become dispatchable.
                if source is None:
                    metadata["routable"] = False
                    metadata.setdefault("unavailable_reason", "external-source-not-registered")
            elif harness_id and harness_id == str(getattr(self.agent, "runtime_id", "")).lower():
                kind = "native-child-agent"
                runtime_id = harness_id
                executor = f"native-{_route_identifier_fragment(harness_id)}"
            else:
                kind = "provider"
                runtime_id = "provider"
                executor = f"provider-profile-{_route_identifier_fragment(profile_id)}" if profile_id else "unknown"
        health = str(raw.get("health_state") or "unknown").lower()
        auth = str(raw.get("auth_state") or "unknown").lower()
        if auth == "needs-auth":
            status = "needs-auth"
        elif health in {"healthy", "ready", "available"}:
            status = "ready"
        elif health in {"unavailable", "error"}:
            status = "unavailable"
        else:
            status = "unknown"
        routable = bool(raw.get("routable", metadata.get("routable", False)))
        if kind == "external-harness":
            source_id = str(metadata.get("external_source_id") or raw.get("external_source_id") or raw.get("harness_id") or runtime_id).strip().lower()
            source = self._external_route_sources.get(source_id)
            if source is None:
                routable = False
                status = "unavailable"
                reason = "external-source-not-registered"
            else:
                reason = raw.get("reason") or metadata.get("unavailable_reason")
        if kind == "web-worker":
            metadata["web_profile_id"] = web_profile_id or profile_id
        return RuntimeRouteDescriptor(
            route_id=route_id,
            kind=kind,
            label=str(raw.get("display_name") or raw.get("model_id") or route_id),
            runtime_id=runtime_id,
            executor=executor,
            transport=str(raw.get("transport") or ("browser-dom" if kind == "web-worker" else "http")),
            side_effect=str(metadata.get("side_effect") or "none"),
            quota_consent=str(metadata.get("quota_consent") or raw.get("quota_consent") or "unknown"),
            provider_profile_id=profile_id,
            # Web profile IDs are unique sessions, not Provider identities.
            # Use the adapter/site key for panel de-duplication so two
            # profiles for the same provider do not consume two opinions.
            provider_key=str(
                (metadata.get("adapter_id") if source_kind == "web-chat" else None)
                or raw.get("provider_id")
                or "unknown"
            ),
            adapter_id=str(metadata.get("adapter_id") or raw.get("provider_id") or "") or None,
            domains=tuple(metadata.get("domains") or ()),
            capabilities=tuple(raw.get("capabilities") or ("text",)),
            status=status,
            routable=routable,
            occupancy=str(metadata.get("occupancy") or raw.get("occupancy") or "idle"),
            quota_state=str(raw.get("quota_state") or "unknown"),
            requires_confirmation=bool(raw.get("requires_confirmation", False)),
            reason=reason or ("profile-not-ready" if not routable and kind == "web-worker" else None),
            source=source_kind or "core",
            source_kind=source_kind or "provider",
            quality_tier=str(raw.get("quality_tier") or "unknown"),
            cost_class=str(raw.get("cost_class") or "unknown"),
            processing_location=str(raw.get("processing_location") or "cloud"),
            auth_state=auth,
            health_state=health,
            metadata=metadata,
        )

    def _worker_for_route(self, route: RuntimeRouteDescriptor) -> Any | None:
        if route.kind == "web-worker":
            return self.route_supervisor.worker_registry.get("web-coordinator")
        if route.kind == "external-harness":
            source_id = str(
                (route.metadata or {}).get("external_source_id")
                if isinstance(route.metadata, Mapping)
                else ""
            ).strip().lower() or str(route.runtime_id or "").strip().lower()
            source = self._external_route_sources.get(source_id)
            if source is not None:
                worker = self._bind_external_route_worker(source_id, source)
                if worker is not None:
                    return worker
            # Keep descriptor-level lookup as a compatibility path for a
            # plugin that registered a worker directly with the executor id.
            return self.route_supervisor.worker_registry.get(route.executor)
        if route.kind == "native-child-agent":
            return self.route_supervisor.worker_registry.get(route.executor)
        if route.kind == "desktop-app":
            return self.route_supervisor.worker_registry.get("desktop-automation")
        if route.kind == "provider" and route.provider_profile_id:
            worker_id = f"provider-profile-{_route_identifier_fragment(route.provider_profile_id)}"
            worker = self.route_supervisor.worker_registry.get(worker_id)
            if worker is None:
                worker = ProviderProfileWorker(
                    self.provider_profiles,
                    route.provider_profile_id,
                    pricing=self.model_policy.pricing,
                    worker_id=worker_id,
                )
                self.route_supervisor.register_worker(worker_id, worker)
            return worker
        return None

    @staticmethod
    def _consultation_route_ids(params: Mapping[str, Any]) -> tuple[str, ...]:
        """Extract bounded route constraints without changing the request."""

        constraints = params.get("route_constraints", params.get("routeConstraints"))
        values: Any = None
        if isinstance(constraints, Mapping):
            values = constraints.get("route_ids", constraints.get("routeIds"))
        if values is None:
            values = params.get("route_ids", params.get("routeIds"))
        if isinstance(values, str):
            values = (values,)
        if not isinstance(values, (list, tuple, set)):
            values = ()
        return tuple(str(item).strip() for item in list(values)[:32] if str(item).strip())

    def _modern_consultation_routes(
        self,
        params: Mapping[str, Any],
        *,
        include_unavailable: bool = False,
    ) -> list[dict[str, Any]]:
        """Return currently routable modern web routes for a panel request.

        This is an admission hint, not a second routing decision.  The
        Supervisor validates the complete request and applies its own budget,
        consent and worker gates when the dispatch is created.
        """

        supervisor = getattr(self, "route_supervisor", None)
        if supervisor is None or bool(getattr(supervisor, "_closed", False)):
            return []
        allowed = set(self._consultation_route_ids(params))
        required_raw = params.get("required_capabilities", params.get("requiredCapabilities", ()))
        if isinstance(required_raw, str):
            required_raw = (required_raw,)
        required = {str(item).strip() for item in required_raw if str(item).strip()} if isinstance(required_raw, (list, tuple, set)) else set()
        try:
            catalog = supervisor.catalog(include_unavailable=True)
        except Exception as exc:
            self.logger.info("modern consultation catalog unavailable error_type=%s", type(exc).__name__)
            return []
        rows = catalog.get("routes", []) if isinstance(catalog, Mapping) else []
        result: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            route_id = str(row.get("route_id") or "").strip()
            kind = str(row.get("kind") or row.get("worker_kind") or "").strip().lower()
            source_kind = str(row.get("source_kind") or "").strip().lower()
            if not route_id or (kind not in {"web", "web-worker"} and source_kind != "web-chat"):
                continue
            if allowed and route_id not in allowed:
                continue
            capabilities = {str(item).strip() for item in (row.get("capabilities") or ()) if str(item).strip()}
            if required and not required.issubset(capabilities):
                continue
            available = row.get("available")
            if available is None:
                available = bool(
                    row.get("routable")
                    and str(row.get("status") or "").lower() in {"ready", "available", "configured"}
                    and str(row.get("occupancy") or "idle").lower() in {"idle", "agent"}
                )
            if include_unavailable or available is True:
                result.append(dict(row))
        return result

    def _legacy_consultation_requested(self, params: Mapping[str, Any]) -> bool:
        """Recognize the old web-chat route spelling used by early clients."""

        backend = str(params.get("route_backend") or params.get("routeBackend") or "").strip().lower()
        if backend in {"legacy", "route-coordinator", "web-coordinator"}:
            return True
        return any(item.startswith("web-chat:") for item in self._consultation_route_ids(params))

    def _supervisor_owns_consultation(self, consultation_id: str) -> bool:
        supervisor = getattr(self, "route_supervisor", None)
        owns = getattr(supervisor, "owns_consultation", None) if supervisor is not None else None
        if not callable(owns):
            return False
        try:
            return bool(owns(consultation_id))
        except (RouteValidationError, SupervisorError, ValueError, TypeError):
            return False

    def _list_route_consultations(self, *, parent_session_id: Any = None, limit: int = 50) -> list[dict[str, Any]]:
        """Merge modern and legacy projections without hiding live answers."""

        parent = str(parent_session_id) if parent_session_id else None
        supervisor = getattr(self, "route_supervisor", None)
        modern: list[dict[str, Any]] = []
        if supervisor is not None and not bool(getattr(supervisor, "_closed", False)):
            try:
                modern = supervisor.list_consultations(parent_session_id=parent, limit=limit)
            except (RouteValidationError, SupervisorError, ValueError, TypeError):
                modern = []
        try:
            legacy = self.routes.list_consultations(parent_session_id=parent, limit=limit)
        except (RouteValidationError, RouteError, ValueError, TypeError):
            legacy = []

        legacy_by_id = {
            str(item.get("consultation_id")): item
            for item in legacy
            if isinstance(item, Mapping) and item.get("consultation_id")
        }
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in modern:
            if not isinstance(item, Mapping) or not item.get("consultation_id"):
                continue
            identifier = str(item["consultation_id"])
            # A live legacy coordinator owns its in-memory answer bodies; let
            # it win unless the modern Supervisor explicitly owns the panel.
            if identifier in legacy_by_id and not self._supervisor_owns_consultation(identifier):
                continue
            merged.append(dict(item))
            seen.add(identifier)
        for item in legacy:
            if not isinstance(item, Mapping) or not item.get("consultation_id"):
                continue
            identifier = str(item["consultation_id"])
            if identifier not in seen:
                merged.append(dict(item))
                seen.add(identifier)
        return merged[: max(1, min(int(limit), 100))]

    def _zcode_worker_routes(self, *, refresh: bool = False) -> list[RuntimeRouteDescriptor]:
        """Probe the explicitly configured ZCode worker only on request."""

        # Configured ZCode is normally represented by the generic external
        # route source.  Keep this legacy helper for older callers, but avoid
        # producing a second set of descriptors when that source is present.
        if "zcode" in getattr(self, "_external_route_sources", {}):
            return []
        runtime = self.zcode_runtime
        if runtime is None:
            return []
        if not refresh:
            return list(self._zcode_route_cache)
        try:
            health = runtime.health()
        except Exception as exc:
            self.logger.info("zcode route health probe failed error_type=%s", type(exc).__name__)
            health = {"ok": False}
        quota: dict[str, Any] = {}
        try:
            value = runtime.quota_status({})
            if isinstance(value, dict):
                quota = value
        except Exception as exc:
            self.logger.info("zcode route quota probe failed error_type=%s", type(exc).__name__)
        quota_state = str(quota.get("state") or "unknown").lower()
        if quota_state not in {"available", "low", "exhausted", "expired", "needs-auth", "blocked", "unknown", "not-applicable"}:
            quota_state = "unknown"
        try:
            models = runtime.runtime_models({})
        except Exception as exc:
            self.logger.info("zcode route model probe failed error_type=%s", type(exc).__name__)
            models = {}
        groups = models.get("groups", []) if isinstance(models, dict) else []
        result: list[RuntimeRouteDescriptor] = []
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            provider = str(group.get("id") or "zcode").strip()
            for model in group.get("models", []) if isinstance(group.get("models"), list) else []:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("id") or "").strip()
                if not model_id:
                    continue
                route_id = f"harness:zcode:{_route_identifier_fragment(provider)}:{_route_identifier_fragment(model_id)}"
                quality = _route_quality_tier(model_id)
                raw_entry = {
                    "route_id": route_id,
                    "provider_id": provider,
                    "model_id": model_id,
                    "display_name": f"{group.get('name') or provider} · {model.get('name') or model_id}",
                    "harness_id": "zcode",
                    "capabilities": ["chat", "code", "tools"],
                    "quality_tier": quality,
                    "cost_class": "unknown",
                    "processing_location": "cloud",
                    "auth_state": "authorized" if health.get("ok") else "unknown",
                    "quota_state": quota_state,
                    "health_state": "healthy" if health.get("ok") else "unavailable",
                    "source_kind": "harness",
                    "transport": "stdio",
                }
                result.append(self._model_entry_to_route(raw_entry))
        if not result:
            # Keep a visible, non-routable status card for a configured but
            # unavailable worker without inventing a model or quota.
            result.append(
                RuntimeRouteDescriptor(
                    route_id="harness:zcode:runtime",
                    kind="external-harness",
                    label="ZCode 客户端额度（未就绪）",
                    runtime_id="zcode",
                    executor="zcode-external-harness",
                    transport="stdio",
                    status="ready" if health.get("ok") else "unavailable",
                    routable=False,
                    quota_state=quota_state,
                    reason="model-catalog-unavailable",
                    source="harness",
                    source_kind="harness",
                    auth_state="authorized" if health.get("ok") else "unknown",
                    health_state="healthy" if health.get("ok") else "unavailable",
                    metadata={"routable": False, "quota_source": quota.get("source", "zcode-app-server")},
                )
            )
        return result

    def _on_supervisor_event(self, event: dict[str, Any]) -> None:
        """Project bounded supervisor events into Core's event/audit stream."""

        if not isinstance(event, dict):
            return
        safe_keys = {
            "dispatch_id", "parent_session_id", "parent_turn_id", "route_id",
            "runtime_id", "executor", "transport", "side_effect", "worker_kind",
            "status", "error_code", "latency_ms", "result_length", "summary_hash",
            "workspace_access", "depth", "trigger_event", "selected_route",
            "requires_confirmation", "reason_codes", "duplicate", "accepted",
            "consultation_id", "successful_count", "failed_count",
            "disagreement_detected", "member_count", "result_pending",
            "result_acknowledged", "armed", "pending",
        }
        payload = {key: event.get(key) for key in safe_keys if event.get(key) is not None}
        event_type = str(event.get("event_type") or "agent.route.event")
        session_id = event.get("parent_session_id")
        try:
            self.events.publish(EventEnvelope(event_type, payload, session_id=session_id))
        except Exception as exc:
            self.logger.info("route event projection failed error_type=%s", type(exc).__name__)
        status = str(event.get("status") or "").lower()
        if (
            str(event.get("worker_kind") or "").lower() in {"web", "web-worker"}
            and status in {"completed", "failed", "unknown", "waiting-human", "cancelled", "interrupted"}
        ):
            try:
                self._sync_web_chat_providers()
                self._refresh_route_supervisor_catalog(refresh=False)
            except Exception as exc:
                self.logger.info("web route terminal refresh failed error_type=%s", type(exc).__name__)
        try:
            outcome = "success" if status in {"completed", "recommended", "dispatched"} else "failed" if status in {"failed", "unknown", "interrupted"} else "pending"
            self.observability.record(
                component="route-supervisor",
                capability="dynamic-route",
                phase="completed" if status in {"completed", "failed", "unknown", "interrupted"} else "running",
                outcome=outcome,
                session_id=session_id,
                turn_id=event.get("parent_turn_id"),
                event_type=event_type,
                duration_ms=event.get("latency_ms"),
                error_class=event.get("error_code"),
            )
        except Exception as exc:
            self.logger.info("route observability projection failed error_type=%s", type(exc).__name__)

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
        # Feed only normalized turn boundaries to the scheduler.  Runtime
        # adapters may wrap them in ``session/event`` notifications, so map
        # the small set of public status spellings without treating arbitrary
        # model/tool events as permission to dispatch work.
        try:
            self._handle_route_boundary_event(event)
        except Exception as error:
            # A scheduler error must never break the primary Agent event
            # stream; it is reported as bounded diagnostics only.
            self.logger.info("route supervisor event handling failed error_type=%s", type(error).__name__)
        self.events.publish(
            EventEnvelope(
                projected_type,
                payload,
                session_id=event.get("session_id"),
            )
        )

    def _handle_route_boundary_event(self, event: Mapping[str, Any] | Any) -> dict[str, Any] | None:
        """Send one normalized runtime event through the route supervisor.

        This helper is shared by the live runtime callback and the explicit
        ``agent.event.ingest`` RPC.  Keeping both paths identical matters for
        reconnects and fixture-driven integrations: an event received through
        either path must have the same boundary and parent-turn semantics.
        """

        if not isinstance(event, Mapping) or not hasattr(self, "route_supervisor"):
            return None
        boundary = _route_event_boundary(event)
        if not boundary:
            return None
        supervisor_event = dict(event)
        supervisor_event["event_type"] = boundary
        request = (
            event.get("routing_request")
            or event.get("routingRequest")
            or event.get("route_request")
            or event.get("routeRequest")
        )
        selected = event.get("dispatch_selected")
        if not isinstance(selected, bool):
            selected = event.get("dispatchSelected")
        return self.route_supervisor.handle_event(
            supervisor_event,
            request=request,
            dispatch_selected=selected if isinstance(selected, bool) else None,
        )

    def _on_route_event(self, event: dict[str, Any]) -> None:
        """Project route/consultation lifecycle into the safe event stream."""

        if not isinstance(event, dict):
            return
        event_type = str(event.get("event_type") or "agent.route.event")
        # RouteCoordinator owns the BrowserSkill lease, while the modern
        # Supervisor owns the runtime-neutral catalog.  Keep both projections
        # synchronized immediately when a manual takeover or Agent lease
        # changes; waiting for a later catalog refresh would permit a race.
        if event_type == "agent.route.occupancy" and hasattr(self, "route_supervisor"):
            profile_id = event.get("profile_id")
            occupancy = event.get("occupancy")
            if profile_id and occupancy:
                try:
                    self.route_supervisor.update_occupancy(str(profile_id), str(occupancy))
                except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                    self.logger.info("route occupancy projection failed error_type=%s", type(exc).__name__)
        payload = {
            key: event.get(key)
            for key in (
                "dispatch_id",
                "consultation_id",
                "route_id",
                "profile_id",
                "occupancy",
                "status",
                "successful_count",
                "failed_count",
                "disagreement_detected",
                "error_code",
                "member_count",
            )
            if event.get(key) is not None
        }
        self.events.publish(EventEnvelope(event_type, payload))

    def _route_bridge_projection(
        self,
        *,
        plugin_id: str | None = None,
        status: str = "bridge-available",
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded route-bridge registration projection.

        Registration is intentionally not persisted.  The DSH plugin must
        repeat the handshake after either side restarts, and callers receive
        only capability names and runtime state rather than arbitrary plugin
        metadata.
        """

        registration = self._route_bridge_registrations.get(plugin_id or "")
        runtime_status: dict[str, Any]
        try:
            raw_status = self.agent.status()
            runtime_status = {
                "state": str(raw_status.get("state") or "unknown") if isinstance(raw_status, Mapping) else "unknown",
                "ready": bool(raw_status.get("ready")) if isinstance(raw_status, Mapping) else False,
            }
        except Exception:
            runtime_status = {"state": "unavailable", "ready": False}
        registered = bool(
            registration
            and status in {"bridge-available", "registered"}
            and runtime_status.get("ready")
            and not getattr(self, "_closed", False)
        )
        result: dict[str, Any] = {
            "schema": AGENT_ROUTE_SCHEMA,
            "runtime": str(getattr(self.agent, "runtime_id", "unknown")),
            "registered": registered,
            "status": "registered" if registered else status,
            "tools": [
                dict(item)
                for item in (
                    tuple(
                        item
                        for item in ROUTE_BRIDGE_CANONICAL_TOOLS
                        if not registration or item["name"].replace(".", "_") in set(registration.get("tools") or ())
                    )
                    if registration
                    else ROUTE_BRIDGE_CANONICAL_TOOLS
                )
            ],
            "runtime_state": runtime_status["state"],
            "runtime_ready": runtime_status["ready"],
        }
        if registration and registered:
            result["plugin"] = {
                "id": registration["plugin_id"],
                "version": registration["plugin_version"],
                "registered_at": registration["registered_at"],
            }
        if reason:
            result["reason"] = reason
        return result

    def _route_bridge_handshake(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and record an explicit DSH route bridge handshake."""

        raw_register = params.get("register", False)
        if not isinstance(raw_register, bool):
            raise JsonRpcError(-32602, "register must be a boolean")
        plugin_id = params.get("plugin_id", params.get("pluginId"))
        if plugin_id is not None and (not isinstance(plugin_id, str) or not plugin_id.strip()):
            raise JsonRpcError(-32602, "plugin_id must be a non-empty string")
        plugin_id = plugin_id.strip() if isinstance(plugin_id, str) else None

        # A no-argument call is a read-only description for older clients.
        if not raw_register:
            if params.get("unregister") is True:
                if plugin_id:
                    self._route_bridge_registrations.pop(plugin_id, None)
                return self._route_bridge_projection(plugin_id=plugin_id, status="unregistered")
            return self._route_bridge_projection(plugin_id=plugin_id)

        if plugin_id != ROUTE_BRIDGE_PLUGIN_ID:
            return self._route_bridge_projection(
                plugin_id=plugin_id,
                status="plugin-not-allowlisted",
                reason="route bridge plugin id is not allow-listed",
            )
        plugin_version = params.get("plugin_version", params.get("pluginVersion"))
        if not isinstance(plugin_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", plugin_version.strip()):
            raise JsonRpcError(-32602, "plugin_version must be a semantic version")
        plugin_version = plugin_version.strip()
        if plugin_version != ROUTE_BRIDGE_VERSION:
            return self._route_bridge_projection(
                plugin_id=plugin_id,
                status="plugin-version-mismatch",
                reason="route bridge version is not compatible with this Core",
            )

        raw_tools = params.get("tools")
        if not isinstance(raw_tools, list) or not raw_tools or len(raw_tools) > 16:
            raise JsonRpcError(-32602, "tools must be a non-empty list")
        tools: list[str] = []
        for value in raw_tools:
            if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_]{1,120}", value.strip()) is None:
                raise JsonRpcError(-32602, "tools contains an invalid name")
            tools.append(value.strip())
        if len(set(tools)) != len(tools):
            raise JsonRpcError(-32602, "tools must not contain duplicates")
        if set(tools) not in (ROUTE_BRIDGE_LEGACY_TOOL_NAMES, ROUTE_BRIDGE_TOOL_NAMES):
            return self._route_bridge_projection(
                plugin_id=plugin_id,
                status="tool-set-mismatch",
                reason="route bridge tool set is incomplete or unexpected",
            )

        # Explicit registration is the point at which a runtime health check
        # is allowed.  Never claim a mounted bridge while DSH is disabled or
        # unreachable, and never persist a stale success across Core restarts.
        try:
            runtime_status = self.agent.status()
        except Exception:
            runtime_status = {"ready": False}
        if not isinstance(runtime_status, Mapping) or runtime_status.get("ready") is not True:
            self._route_bridge_registrations.pop(plugin_id, None)
            return self._route_bridge_projection(
                plugin_id=plugin_id,
                status="runtime-unavailable",
                reason="selected Agent Runtime is not ready",
            )
        supervisor = getattr(self, "route_supervisor", None)
        if supervisor is None or bool(getattr(supervisor, "_closed", False)):
            return self._route_bridge_projection(
                plugin_id=plugin_id,
                status="core-not-ready",
                reason="route supervisor is not ready",
            )
        registration = {
            "plugin_id": plugin_id,
            "plugin_version": plugin_version,
            "tools": tuple(sorted(tools)),
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        self._route_bridge_registrations[plugin_id] = registration
        self.events.publish(
            EventEnvelope(
                "agent.route.bridge.registered",
                {
                    "plugin_id": plugin_id,
                    "plugin_version": plugin_version,
                    "tool_count": len(tools),
                    "runtime": str(getattr(self.agent, "runtime_id", "unknown")),
                },
            )
        )
        return self._route_bridge_projection(plugin_id=plugin_id, status="registered")

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
        if method == "model.policy.catalog":
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            raw_session = params.get("sessionId") or params.get("session_id")
            if raw_session is not None and not isinstance(raw_session, (str, int)):
                raise JsonRpcError(-32602, "sessionId must be a scalar identifier")
            try:
                return self.model_policy.catalog(
                    refresh=raw_refresh,
                    session_id=str(raw_session).strip() if raw_session is not None else None,
                )
            except ModelPolicyError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "model.policy.pricing":
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            profile_id = params.get("providerProfileId", params.get("provider_profile_id"))
            model_id = params.get("modelId", params.get("model_id"))
            for name, value in (("provider_profile_id", profile_id), ("model_id", model_id)):
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise JsonRpcError(-32602, f"{name} must be non-empty text")
            try:
                return self.model_policy.pricing_catalog(
                    refresh=raw_refresh,
                    provider_profile_id=profile_id.strip() if isinstance(profile_id, str) else None,
                    model_id=model_id.strip() if isinstance(model_id, str) else None,
                )
            except (ModelPolicyError, ValueError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "capability.catalog":
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            raw_runtime = params.get("includeRuntime", params.get("include_runtime", True))
            if not isinstance(raw_runtime, bool):
                raise JsonRpcError(-32602, "includeRuntime must be a boolean")
            raw_session = params.get("sessionId", params.get("session_id"))
            if raw_session is not None and not isinstance(raw_session, (str, int)):
                raise JsonRpcError(-32602, "sessionId must be a scalar identifier")
            try:
                return self.capabilities.catalog(
                    refresh=raw_refresh,
                    session_id=str(raw_session).strip() if raw_session is not None else None,
                    include_runtime=raw_runtime,
                )
            except CapabilityCatalogError as exc:
                raise JsonRpcError(-32034, str(exc)) from exc
        if method == "desktop.automation.status":
            return self.desktop_automation.status()
        if method == "desktop.automation.catalog":
            raw_refresh = params.get("refresh", False)
            raw_unavailable = params.get("includeUnavailable", params.get("include_unavailable", True))
            if not isinstance(raw_refresh, bool) or not isinstance(raw_unavailable, bool):
                raise JsonRpcError(-32602, "refresh and includeUnavailable must be booleans")
            return self.desktop_automation.catalog(
                refresh=raw_refresh,
                include_unavailable=raw_unavailable,
            )
        if method == "desktop.automation.register":
            if params.get("approved") is not True:
                raise JsonRpcError(-32031, "registering a desktop application requires explicit approval")
            declaration = params.get("application") if isinstance(params.get("application"), dict) else params
            try:
                result = self.desktop_automation.register_application(
                    declaration,
                    approved=True,
                    confirm_app_id=params.get("confirm_app_id") or params.get("confirmAppId"),
                )
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.registered",
                    {
                        "app_id": result.get("app_id"),
                        "adapter_id": result.get("adapter_id"),
                        "status": result.get("status"),
                    },
                )
            )
            return result
        if method == "desktop.automation.open":
            app_id = str(params.get("app_id") or params.get("appId") or "").strip()
            if not app_id:
                raise JsonRpcError(-32602, "app_id is required")
            if params.get("approved") is not True:
                raise JsonRpcError(-32031, "opening a desktop application requires explicit approval")
            options = params.get("options")
            if options is not None and not isinstance(options, dict):
                raise JsonRpcError(-32602, "options must be an object")
            try:
                result = self.desktop_automation.open_session(
                    app_id,
                    profile_id=str(params.get("profile_id") or params.get("profileId") or "") or None,
                    owner=str(params.get("owner") or "agent"),
                    options=options or {},
                )
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            session = result.get("session") if isinstance(result, dict) else {}
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.opened",
                    {
                        "app_id": app_id,
                        "session_id": session.get("session_id") if isinstance(session, dict) else None,
                        "owner": session.get("owner") if isinstance(session, dict) else None,
                    },
                )
            )
            return result
        if method == "desktop.automation.observe":
            session_id = str(params.get("session_id") or params.get("sessionId") or "").strip()
            if not session_id:
                raise JsonRpcError(-32602, "session_id is required")
            options = params.get("options")
            if options is not None and not isinstance(options, dict):
                raise JsonRpcError(-32602, "options must be an object")
            try:
                result = self.desktop_automation.observe(session_id, options or {})
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.observed",
                    {"session_id": session_id, "status": result.get("status")},
                    session_id=session_id,
                )
            )
            return result
        if method == "desktop.automation.act":
            request = params.get("request") if isinstance(params.get("request"), dict) else dict(params)
            if isinstance(params.get("request"), dict):
                # Outer approval fields are deliberately copied only when the
                # nested request did not provide them.
                for key in ("approved", "approval_id", "approvalId"):
                    if key not in request and key in params:
                        request[key] = params[key]
            try:
                result = self.desktop_automation.act(request)
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.action.completed"
                    if result.get("status") == "completed"
                    else "desktop.automation.action.pending",
                    {
                        "session_id": result.get("session_id"),
                        "action": result.get("action"),
                        "status": result.get("status"),
                        "risk": result.get("risk"),
                        "error_code": result.get("error_code"),
                    },
                    session_id=result.get("session_id"),
                )
            )
            return result
        if method == "desktop.automation.close":
            session_id = str(params.get("session_id") or params.get("sessionId") or "").strip()
            if not session_id:
                raise JsonRpcError(-32602, "session_id is required")
            if params.get("approved") is not True:
                raise JsonRpcError(-32031, "closing a desktop session requires explicit approval")
            try:
                result = self.desktop_automation.close_session(session_id)
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.closed",
                    {"session_id": session_id, "closed": bool(result.get("closed"))},
                    session_id=session_id,
                )
            )
            return result
        if method == "desktop.automation.approval":
            try:
                result = self.desktop_automation.approval(params)
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.approval.updated",
                    {
                        "operation": str(params.get("operation") or params.get("action") or "list"),
                        "approved": bool(result.get("approved")) if isinstance(result, dict) else None,
                    },
                )
            )
            return result
        if method == "desktop.automation.takeover":
            session_id = str(params.get("session_id") or params.get("sessionId") or "").strip()
            if not session_id:
                raise JsonRpcError(-32602, "session_id is required")
            enabled = params.get("enabled", True)
            if not isinstance(enabled, bool):
                raise JsonRpcError(-32602, "enabled must be a boolean")
            try:
                result = self.desktop_automation.takeover(
                    session_id,
                    enabled=enabled,
                    approved=params.get("approved") is True,
                )
            except DesktopAutomationError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "desktop.automation.takeover.updated",
                    {
                        "session_id": session_id,
                        "status": result.get("status"),
                        "enabled": enabled,
                    },
                    session_id=session_id,
                )
            )
            return result
        if method == "model.policy.route":
            raw_session = params.get("sessionId") or params.get("session_id")
            if raw_session is not None and not isinstance(raw_session, (str, int)):
                raise JsonRpcError(-32602, "sessionId must be a scalar identifier")
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            request_params = dict(params)
            request_params.pop("sessionId", None)
            request_params.pop("session_id", None)
            request_params.pop("refresh", None)
            try:
                result = self.model_policy.decide(
                    request_params,
                    session_id=str(raw_session).strip() if raw_session is not None else None,
                    refresh=raw_refresh,
                )
            except ModelPolicyError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            decision = result.get("decision") if isinstance(result, dict) else {}
            self.events.publish(
                EventEnvelope(
                    "model.policy.decided",
                    {
                        "selected_route": decision.get("selected_route"),
                        "status": decision.get("status"),
                        "requires_confirmation": bool(decision.get("requires_confirmation")),
                        "policy_version": decision.get("policy_version"),
                    },
                    session_id=str(raw_session).strip() if raw_session is not None else None,
                )
            )
            return result
        if method == "model.policy.preflight":
            raw_session = params.get("sessionId") or params.get("session_id")
            if raw_session is not None and not isinstance(raw_session, (str, int)):
                raise JsonRpcError(-32602, "sessionId must be a scalar identifier")
            request_params = dict(params)
            request_params.pop("sessionId", None)
            request_params.pop("session_id", None)
            request_params.pop("refresh", None)
            try:
                result = self.model_policy.preflight(
                    request_params,
                    session_id=str(raw_session).strip() if raw_session is not None else None,
                )
            except ModelPolicyError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            decision = result.get("decision") if isinstance(result, dict) else {}
            self.events.publish(
                EventEnvelope(
                    "model.policy.preflighted",
                    {
                        "selected_route": decision.get("selected_route"),
                        "status": decision.get("status"),
                        "requires_confirmation": bool(decision.get("requires_confirmation")),
                        "policy_version": decision.get("policy_version"),
                    },
                    session_id=str(raw_session).strip() if raw_session is not None else None,
                )
            )
            return result
        if method == "model.policy.apply":
            raw_session = params.get("sessionId") or params.get("session_id")
            if not isinstance(raw_session, (str, int)) or isinstance(raw_session, bool) or not str(raw_session).strip():
                raise JsonRpcError(-32602, "sessionId must be a non-empty identifier")
            session_id = str(raw_session).strip()
            decision = params.get("decision")
            if not isinstance(decision, dict):
                request_params = dict(params)
                request_params.pop("sessionId", None)
                request_params.pop("session_id", None)
                request_params.pop("approved", None)
                request_params.pop("decision", None)
                try:
                    preflight = self.model_policy.preflight(request_params, session_id=session_id)
                except ModelPolicyError as exc:
                    raise JsonRpcError(-32602, str(exc)) from exc
                decision = preflight.get("decision") if isinstance(preflight, dict) else None
            result = self._apply_agent_route(
                decision,
                session_id=session_id,
                approved=params.get("approved") is True,
            )
            if result.get("applied"):
                self.events.publish(
                    EventEnvelope(
                        "model.policy.applied",
                        {
                            "session_id": session_id,
                            "selected_route": result.get("route_id"),
                        },
                        session_id=session_id,
                    )
                )
            return result
        if method == "model.policy.quota":
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            raw_force = params.get("force", False)
            if not isinstance(raw_force, bool):
                raise JsonRpcError(-32602, "force must be a boolean")
            try:
                return self.model_policy.quota_status(refresh=raw_refresh, force=raw_force)
            except ModelPolicyError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "agent.observability.status":
            return self.observability.status()
        if method == "agent.observability.daily":
            day = params.get("day") if isinstance(params, dict) else None
            write = bool(params.get("write")) if isinstance(params, dict) else False
            try:
                report = self.observability.write_daily_summary(day) if write else self.observability.aggregate(day)
                report["route_decision_trace"] = self.route_trace.write_daily_summary(day) if write else self.route_trace.aggregate(day)
                return report
            except ValueError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "agent.route.trace.status":
            return self.route_trace.status()
        if method == "agent.route.trace.daily":
            day = params.get("day") if isinstance(params, dict) else None
            write = bool(params.get("write")) if isinstance(params, dict) else False
            try:
                return self.route_trace.write_daily_summary(day) if write else self.route_trace.aggregate(day)
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
            routing_result = self._agent_routing_preflight(request, mode="execute")
            routing_decision = routing_result.get("decision") if isinstance(routing_result, dict) else None
            routing_entry = routing_decision.get("selected_entry") if isinstance(routing_decision, dict) else None
            routing_approved = self._routing_approved(request)
            if routing_result is not None:
                if not isinstance(routing_decision, dict) or not routing_decision.get("selected_route"):
                    return {
                        "accepted": False,
                        "session_created": False,
                        "routing": routing_result,
                    }
                if routing_decision.get("requires_confirmation") and not routing_approved:
                    return {
                        "accepted": False,
                        "session_created": False,
                        "routing": routing_result,
                        "reason": "confirmation-required",
                    }
                if isinstance(routing_entry, dict) and routing_entry.get("provider_profile_id"):
                    if not self.agent.supports(AgentCapability.PROVIDER_BRIDGE):
                        raise JsonRpcError(-32032, "当前 Agent runtime 不支持 Provider 档案桥接")
                    request["provider_profile_id"] = routing_entry["provider_profile_id"]
            workspace = None
            if self._agent_workspace_safety_active():
                workspace, _ = self._agent_workspace_binding(request)
                request.pop("workspace_id", None)
                request.pop("cwd", None)
                request["workspaceId"] = workspace["id"]
            provider_binding = None
            # A harness-native route is selected after the session exists;
            # profile routes still use the established provider bridge before
            # session creation.  With no routing request, retain the legacy
            # active-profile behavior exactly as before.
            needs_profile_binding = routing_result is None or bool(
                isinstance(routing_entry, dict) and routing_entry.get("provider_profile_id")
            )
            if self.agent.supports(AgentCapability.PROVIDER_BRIDGE) and needs_profile_binding:
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
            if routing_result is not None:
                session_id = result.get("sessionId") or result.get("id")
                if not session_id:
                    raise JsonRpcError(-32030, "Agent runtime did not return a session id for model routing")
                if isinstance(routing_entry, dict) and routing_entry.get("provider_profile_id"):
                    applied = {
                        "applied": True,
                        "route_id": routing_decision.get("selected_route"),
                        "decision": routing_decision,
                    }
                    if provider_binding:
                        applied["provider"] = provider_binding
                        applied["selected_model"] = result.get("selected_model")
                else:
                    applied = self._apply_agent_route(
                        routing_decision,
                        session_id=str(session_id),
                        approved=True,
                    )
                result = {**result, "routing": {**routing_result, "applied": applied}}
                self.events.publish(
                    EventEnvelope(
                        "model.policy.applied",
                        {
                            "session_id": str(session_id),
                            "selected_route": routing_decision.get("selected_route"),
                        },
                        session_id=str(session_id),
                    )
                )
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
            routing_result = None
            routing_applied = None
            routing_session_id = request.get("sessionId") or request.get("session_id")
            if routing_session_id is not None:
                routing_result = self._agent_routing_preflight(
                    request,
                    text=str(request.get("text") or ""),
                    mode=requested_mode,
                    session_id=str(routing_session_id),
                )
                if routing_result is not None:
                    routing_decision = routing_result.get("decision") if isinstance(routing_result, dict) else None
                    if not isinstance(routing_decision, dict) or not routing_decision.get("selected_route"):
                        return {"accepted": False, "routing": routing_result}
                    if routing_decision.get("requires_confirmation") and not self._routing_approved(request):
                        return {"accepted": False, "routing": routing_result, "reason": "confirmation-required"}
                    routing_applied = self._apply_agent_route(
                        routing_decision,
                        session_id=str(routing_session_id),
                        approved=True,
                    )
                    request.pop("routing", None)
                    request.pop("routing_policy", None)
                    request.pop("routingApproved", None)
                    request.pop("routing_approved", None)
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
            if routing_result is not None:
                result = {
                    **result,
                    "routing": {**routing_result, "applied": routing_applied},
                }
                if routing_applied and routing_applied.get("applied"):
                    self.events.publish(
                        EventEnvelope(
                            "model.policy.applied",
                            {
                                "session_id": request.get("sessionId") or request.get("session_id"),
                                "selected_route": routing_applied.get("route_id"),
                            },
                            session_id=request.get("sessionId") or request.get("session_id"),
                        )
                    )
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
            # Explicitly ingested events (for example after a transport
            # reconnect) must enter the same dynamic-routing boundary path as
            # live runtime notifications.  The helper is fail-safe and only
            # acts on recognized turn/tool/approval boundaries.
            try:
                self._handle_route_boundary_event(event)
            except Exception as error:
                self.logger.info("ingested route event handling failed error_type=%s", type(error).__name__)
            self.events.publish(
                EventEnvelope(
                    "agent.event",
                    _redact_agent_payload(event),
                    session_id=event.get("session_id"),
                )
            )
            return event
        if method == "sumika.route.catalog":
            include_templates = params.get("include_templates", params.get("includeTemplates", True))
            if not isinstance(include_templates, bool):
                raise JsonRpcError(-32602, "include_templates must be a boolean")
            include_unavailable = params.get("include_unavailable", params.get("includeUnavailable", True))
            if not isinstance(include_unavailable, bool):
                raise JsonRpcError(-32602, "include_unavailable must be a boolean")
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            try:
                return self._refresh_route_supervisor_catalog(
                    refresh=raw_refresh,
                    include_templates=include_templates,
                    include_unavailable=include_unavailable,
                )
            except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                # Keep the old web-only projection available to older clients
                # if a newly registered optional route is malformed.
                self.logger.info(
                    "runtime-neutral route catalog failed error_type=%s",
                    type(exc).__name__,
                )
                fallback = self.routes.catalog(include_templates=include_templates)
                if not include_unavailable:
                    fallback["routes"] = [item for item in fallback.get("routes", []) if item.get("routable")]
                    fallback["count"] = len(fallback["routes"])
                    fallback["routable_count"] = len(fallback["routes"])
                return fallback
        if method == "sumika.route.replan":
            raw_refresh = params.get("refresh", False)
            if not isinstance(raw_refresh, bool):
                raise JsonRpcError(-32602, "refresh must be a boolean")
            if raw_refresh:
                self._refresh_route_supervisor_catalog(refresh=True)
            try:
                return self.route_supervisor.replan(
                    params,
                    trigger_event=params.get("trigger_event") or params.get("triggerEvent"),
                    dispatch_selected=params.get("dispatch_selected") if isinstance(params.get("dispatch_selected"), bool) else params.get("dispatchSelected") if isinstance(params.get("dispatchSelected"), bool) else None,
                    trace_id=params.get("trace_id") or params.get("traceId"),
                )
            except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.arm":
            source = params.get("request") if isinstance(params.get("request"), Mapping) else params
            try:
                result = self.route_supervisor.arm_turn(
                    source,
                    replace=params.get("replace") is True,
                )
            except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.route.turn.armed",
                    {
                        "parent_session_id": result.get("parent_session_id"),
                        "parent_turn_id": result.get("parent_turn_id"),
                        "armed": bool(result.get("armed")),
                    },
                    session_id=result.get("parent_session_id"),
                )
            )
            return result
        if method == "sumika.route.dispatch":
            raw = dict(params)
            route_id = str(params.get("route_id") or params.get("routeId") or "").strip()
            if params.get("refresh") is True:
                self._refresh_route_supervisor_catalog(refresh=True)
            supervisor_route_ids = {
                item.get("route_id")
                for item in self.route_supervisor.catalog().get("routes", [])
                if isinstance(item, dict)
            }
            if route_id in supervisor_route_ids:
                try:
                    result = self.route_supervisor.dispatch(
                        raw,
                        route_id=route_id or None,
                        wait=bool(params.get("wait")),
                        trace_id=params.get("trace_id") or params.get("traceId"),
                    )
                except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                    raise JsonRpcError(-32602, str(exc)) from exc
                self.events.publish(
                    EventEnvelope(
                        "agent.route.dispatched",
                        {
                            "dispatch_id": result.get("dispatch_id") if isinstance(result, dict) else None,
                            "route_id": route_id,
                            "accepted": bool(result.get("accepted")) if isinstance(result, dict) else False,
                        },
                        session_id=params.get("parent_session_id") or params.get("parentSessionId"),
                    )
                )
                return result
            # Preserve the original web coordinator for clients using its
            # legacy ``web-chat:<profile>`` route identifiers.
            raw.setdefault("mode", "web-worker")
            try:
                result = self.routes.dispatch(
                    raw,
                    route_id=route_id or None,
                    wait=bool(params.get("wait")),
                )
            except (RouteValidationError, RouteError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.route.dispatched",
                    {
                        "dispatch_id": (result.get("dispatch") or {}).get("dispatch_id") if isinstance(result, dict) else None,
                        "route_id": (result.get("dispatch") or {}).get("route_id") if isinstance(result, dict) else None,
                        "accepted": bool(result.get("accepted")) if isinstance(result, dict) else False,
                    },
                    session_id=params.get("parent_session_id") or params.get("parentSessionId"),
                )
            )
            return result
        if method == "sumika.route.status":
            dispatch_id = params.get("dispatch_id") or params.get("dispatchId")
            if not dispatch_id:
                raise JsonRpcError(-32602, "dispatch_id is required")
            try:
                status = self.route_supervisor.status(str(dispatch_id))
                if status.get("found"):
                    return status
                return self.routes.status(str(dispatch_id))
            except (RouteValidationError, SupervisorError, RouteError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.pending":
            parent_session_id = params.get("parent_session_id") or params.get("parentSessionId") or params.get("session_id") or params.get("sessionId")
            if not parent_session_id:
                raise JsonRpcError(-32602, "parent_session_id is required")
            parent_turn_id = params.get("parent_turn_id") or params.get("parentTurnId") or params.get("turn_id") or params.get("turnId")
            try:
                return self.route_supervisor.pending_results(
                    str(parent_session_id),
                    str(parent_turn_id) if parent_turn_id else None,
                    limit=int(params.get("limit") or 50),
                )
            except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.ack":
            dispatch_id = params.get("dispatch_id") or params.get("dispatchId")
            if not dispatch_id:
                raise JsonRpcError(-32602, "dispatch_id is required")
            try:
                return self.route_supervisor.acknowledge_result(str(dispatch_id))
            except (RouteValidationError, SupervisorError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.consultation.start":
            # New clients use the runtime-neutral Supervisor whenever at
            # least one modern web route is currently routable.  Keep the
            # original coordinator only for old route ids or when no modern
            # route is available, so legacy callers remain compatible.
            use_legacy = self._legacy_consultation_requested(params)
            try:
                # Once a modern web profile has been registered, keep the
                # request on the modern Supervisor path even when that profile
                # is currently occupied, unauthenticated, or unhealthy.  A
                # routability-only check would incorrectly fall back to the
                # legacy coordinator and could return an empty "completed"
                # panel instead of the explicit waiting/failed state.
                if not use_legacy and self._modern_consultation_routes(params, include_unavailable=True):
                    result = self.route_supervisor.start_consultation(
                        params,
                        wait=bool(params.get("wait")),
                        timeout=float(params.get("timeout")) if params.get("timeout") is not None else None,
                    )
                else:
                    result = self.routes.start_consultation(params, wait=bool(params.get("wait")))
            except (RouteValidationError, SupervisorError, RouteError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "agent.consultation.requested",
                    {
                        "consultation_id": result.get("consultation_id") if isinstance(result, dict) else None,
                        "status": result.get("status") if isinstance(result, dict) else None,
                        "member_count": len(result.get("members") or []) if isinstance(result, dict) else 0,
                    },
                    session_id=params.get("parent_session_id") or params.get("parentSessionId"),
                )
            )
            return result
        if method == "sumika.consultation.status":
            consultation_id = params.get("consultation_id") or params.get("consultationId")
            if consultation_id:
                try:
                    identifier = str(consultation_id)
                    if self._supervisor_owns_consultation(identifier):
                        return self.route_supervisor.consultation_status(identifier)
                    legacy = self.routes.consultation_status(identifier)
                    if legacy.get("found", True) and legacy.get("status") != "unknown":
                        return legacy
                    modern = self.route_supervisor.consultation_status(identifier)
                    return modern if modern.get("found") else legacy
                except (RouteValidationError, SupervisorError, RouteError) as exc:
                    raise JsonRpcError(-32602, str(exc)) from exc
            try:
                return {
                    "schema": "agent-consultation/v1",
                    "consultations": self._list_route_consultations(
                        parent_session_id=params.get("parent_session_id") or params.get("parentSessionId"),
                        limit=int(params.get("limit") or 50),
                    ),
                }
            except (RouteValidationError, RouteError, ValueError, TypeError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.cancel":
            consultation_id = params.get("consultation_id") or params.get("consultationId")
            dispatch_id = params.get("dispatch_id") or params.get("dispatchId")
            try:
                if consultation_id:
                    identifier = str(consultation_id)
                    if self._supervisor_owns_consultation(identifier):
                        return self.route_supervisor.cancel_consultation(identifier)
                    return self.routes.cancel_consultation(identifier)
                if dispatch_id:
                    status = self.route_supervisor.status(str(dispatch_id))
                    if status.get("found"):
                        return self.route_supervisor.cancel(str(dispatch_id))
                    return self.routes.cancel(str(dispatch_id))
            except (RouteValidationError, SupervisorError, RouteError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            raise JsonRpcError(-32602, "dispatch_id or consultation_id is required")
        if method == "sumika.route.retry":
            dispatch_id = params.get("dispatch_id") or params.get("dispatchId")
            if not dispatch_id:
                raise JsonRpcError(-32602, "dispatch_id is required")
            try:
                status = self.route_supervisor.status(str(dispatch_id))
                if status.get("found"):
                    return self.route_supervisor.retry(str(dispatch_id), wait=bool(params.get("wait")))
                return self.routes.retry(str(dispatch_id))
            except (RouteValidationError, SupervisorError, RouteError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.occupancy":
            profile_id = params.get("profile_id") or params.get("profileId")
            if not profile_id:
                raise JsonRpcError(-32602, "profile_id is required")
            owner = str(params.get("owner") or params.get("occupancy") or "manual")
            try:
                return self.routes.set_occupancy(str(profile_id), owner)
            except (RouteValidationError, RouteError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.takeover":
            profile_id = params.get("profile_id") or params.get("profileId")
            if not profile_id:
                raise JsonRpcError(-32602, "profile_id is required")
            try:
                return self.routes.request_takeover(str(profile_id))
            except (RouteValidationError, RouteError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
        if method == "sumika.route.bridge_tools":
            return self._route_bridge_handshake(params)
        if method == "browser.status":
            return self.browser.status()
        if method == "browser.web_chat.adapters":
            return {
                "schema": "web-chat/v1",
                "adapters": self.web_chat.list_adapters(),
            }
        if method == "browser.web_chat.profiles":
            return {
                "schema": "web-chat/v1",
                "profiles": self.web_chat.list_profiles(
                    include_archived=bool(params.get("include_archived"))
                ),
            }
        if method == "browser.web_chat.profile.create":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "creating a web-chat profile requires explicit approval")
            raw_config = params.get("config")
            if raw_config is not None and not isinstance(raw_config, dict):
                raise JsonRpcError(-32602, "web-chat profile config must be an object")
            try:
                result = self.web_chat.create_profile(
                    name=str(params.get("name") or ""),
                    adapter_id=str(params.get("adapter_id") or ""),
                    browser_profile_id=str(params.get("browser_profile_id") or ""),
                    browser_instance=str(params.get("browser_instance")) if params.get("browser_instance") else None,
                    config=raw_config,
                    budget_policy=str(params.get("budget_policy") or "free-only"),
                    draft=(bool(params["draft"]) if "draft" in params else None),
                    approved=True,
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self._sync_web_chat_providers()
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.profile.created",
                    {"profile": _redact_web_chat_payload(result)},
                )
            )
            return result
        if method == "browser.web_chat.profile.update":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "editing a web-chat profile requires explicit approval")
            raw_config = params.get("config")
            if raw_config is not None and not isinstance(raw_config, dict):
                raise JsonRpcError(-32602, "web-chat profile config must be an object")
            try:
                result = self.web_chat.update_profile(
                    str(params.get("profile_id") or params.get("id") or ""),
                    name=str(params["name"]) if "name" in params else None,
                    adapter_id=str(params["adapter_id"]) if "adapter_id" in params else None,
                    site_key=str(params["site_key"]) if "site_key" in params else None,
                    browser_profile_id=str(params["browser_profile_id"]) if "browser_profile_id" in params else None,
                    browser_instance=str(params["browser_instance"]) if "browser_instance" in params else None,
                    config=raw_config,
                    budget_policy=str(params["budget_policy"]) if "budget_policy" in params else None,
                    draft=(bool(params["draft"]) if "draft" in params else None),
                    approved=True,
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self._sync_web_chat_providers()
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.profile.updated",
                    {"profile": _redact_web_chat_payload(result)},
                )
            )
            return result
        if method == "browser.web_chat.profile.authorize":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "opening a web-chat login window requires explicit approval")
            try:
                result = self.web_chat.authorize_profile(
                    str(params.get("profile_id") or ""), approved=True
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self._sync_web_chat_providers()
            if result.get("id"):
                self.routes.set_occupancy(str(result["id"]), "manual")
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.login.requested",
                    {"profile": _redact_web_chat_payload(result), "requires_human": True},
                )
            )
            return result
        if method == "browser.web_chat.profile.open":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "opening a web-chat profile requires explicit approval")
            try:
                result = self.web_chat.open_profile(str(params.get("profile_id") or ""), approved=True)
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            if result.get("id"):
                self.routes.set_occupancy(str(result["id"]), "manual")
            self.events.publish(EventEnvelope("browser.web_chat.window.opened", {"profile_id": result.get("id"), "session_id": result.get("session_id"), "tab_id": result.get("tab_id")}))
            return result
        if method == "browser.web_chat.profile.focus":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "focusing a web-chat profile requires explicit approval")
            try:
                result = self.web_chat.focus_profile(
                    str(params.get("profile_id") or ""),
                    tab_id=str(params.get("tab_id")) if params.get("tab_id") else None,
                    approved=True,
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            if result.get("id"):
                self.routes.set_occupancy(str(result["id"]), "manual")
            self.events.publish(EventEnvelope("browser.web_chat.window.focused", {"profile_id": result.get("id"), "session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "focused": bool(result.get("focused"))}))
            return result
        if method == "browser.web_chat.profile.close":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "closing a web-chat profile requires explicit approval")
            profile_id = str(params.get("profile_id") or "")
            try:
                result = self.web_chat.close_profile(profile_id, approved=True)
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.routes.set_occupancy(profile_id, "idle")
            self.events.publish(EventEnvelope("browser.web_chat.window.closed", {"profile_id": profile_id, "session_id": result.get("session_id")}))
            return result
        if method == "browser.web_chat.profile.check":
            try:
                result = self.web_chat.check_profile(
                    str(params.get("profile_id") or ""),
                    approved=bool(params.get("approved")),
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self._sync_web_chat_providers()
            if result.get("ready") and result.get("id"):
                # Checking is the explicit hand-back after manual login.
                self.routes.set_occupancy(str(result["id"]), "idle")
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.login.checked",
                    {"profile": _redact_web_chat_payload(result), "ready": bool(result.get("ready"))},
                )
            )
            return result
        if method == "browser.web_chat.profile.consent":
            actions = params.get("allowed_actions")
            if actions is not None and not isinstance(actions, list):
                raise JsonRpcError(-32602, "allowed_actions must be an array")
            try:
                result = self.web_chat.set_consent(
                    str(params.get("profile_id") or ""),
                    enabled=bool(params.get("enabled")),
                    allowed_actions=actions,
                    approved=bool(params.get("approved")),
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self._sync_web_chat_providers()
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.consent.changed",
                    {"profile": _redact_web_chat_payload(result), "enabled": bool(result.get("auto_chat_enabled"))},
                )
            )
            return result
        if method == "browser.web_chat.profile.activate":
            if not params.get("approved"):
                raise JsonRpcError(-32031, "activating a web-chat profile requires explicit approval")
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            try:
                profile = self.web_chat.activate_profile(profile_id, approved=True)
                result_module = self.modules.update(
                    "llm",
                    enabled=True,
                    implementation_id=f"web-chat:{profile_id}",
                    config={"profile_id": profile_id},
                )
            except (WebChatRuntimeError, ModuleError) as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self._sync_web_chat_providers()
            result = {
                "profile": profile,
                "module": self._module("llm"),
                "privacy": self._privacy_status(),
                "activated": True,
            }
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.profile.activated",
                    {"profile": _redact_web_chat_payload(profile), "module_id": result_module.get("id")},
                )
            )
            return result
        if method in {"browser.web_chat.profile.archive", "browser.web_chat.profile.restore"}:
            if not params.get("approved"):
                raise JsonRpcError(-32031, "changing a web-chat profile requires explicit approval")
            try:
                if method.endswith("archive"):
                    if str(params.get("profile_id") or "") == self._active_web_chat_profile_id():
                        raise WebChatRuntimeError("The active web-chat profile cannot be archived")
                    result = self.web_chat.archive_profile(str(params.get("profile_id") or ""), approved=True)
                    event_type = "browser.web_chat.profile.archived"
                else:
                    result = self.web_chat.restore_profile(str(params.get("profile_id") or ""), approved=True)
                    event_type = "browser.web_chat.profile.restored"
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self._sync_web_chat_providers()
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(EventEnvelope(event_type, {"profile": _redact_web_chat_payload(result)}))
            return result
        if method == "browser.web_chat.message.start":
            raw_text = params.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise JsonRpcError(-32602, "web-chat text must be a non-empty string")
            owner = str(params.get("owner") or "manual").strip().lower()
            if owner not in {"manual", "agent"}:
                raise JsonRpcError(-32602, "web-chat owner is invalid")
            try:
                result = self.web_chat.start_message(
                    str(params.get("profile_id") or ""), raw_text, owner=owner
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32000, str(exc)) from exc
            self._sync_web_chat_providers()
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.message.accepted" if result.get("accepted") else "browser.web_chat.message.rejected",
                    {
                        "profile_id": result.get("profile_id"),
                        "attempt_id": result.get("attempt_id"),
                        "status": result.get("status"),
                        "owner": result.get("owner"),
                        "possibly_sent": bool(result.get("possibly_sent")),
                    },
                )
            )
            return result
        if method == "browser.web_chat.message.status":
            attempt_id = params.get("attempt_id") or params.get("attemptId")
            if not attempt_id:
                raise JsonRpcError(-32602, "attempt_id is required")
            result = self.web_chat.message_status(str(attempt_id))
            if result.get("status") not in {"accepted", "running"}:
                self._sync_web_chat_providers()
                self._refresh_route_supervisor_catalog(refresh=False)
            return result
        if method == "browser.web_chat.message.wait":
            attempt_id = params.get("attempt_id") or params.get("attemptId")
            if not attempt_id:
                raise JsonRpcError(-32602, "attempt_id is required")
            raw_timeout = params.get("timeout", 15)
            try:
                timeout = max(0.0, min(30.0, float(raw_timeout)))
            except (TypeError, ValueError):
                raise JsonRpcError(-32602, "timeout is invalid")
            result = self.web_chat.wait_message(str(attempt_id), timeout=timeout)
            if result.get("status") not in {"accepted", "running"}:
                self._sync_web_chat_providers()
                self._refresh_route_supervisor_catalog(refresh=False)
            return result
        if method == "browser.web_chat.message.cancel":
            attempt_id = params.get("attempt_id") or params.get("attemptId")
            if not attempt_id:
                raise JsonRpcError(-32602, "attempt_id is required")
            return self.web_chat.cancel_message(str(attempt_id))
        if method == "browser.web_chat.send":
            raw_text = params.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise JsonRpcError(-32602, "web-chat text must be a non-empty string")
            try:
                result = self.routes.manual_send(
                    str(params.get("profile_id") or ""), raw_text
                )
            except WebChatRuntimeError as exc:
                raise JsonRpcError(-32000, str(exc)) from exc
            self._sync_web_chat_providers()
            self._refresh_route_supervisor_catalog(refresh=False)
            self.events.publish(
                EventEnvelope(
                    "browser.web_chat.message.completed" if result.get("ok") else "browser.web_chat.message.pending",
                    {
                        "profile_id": result.get("profile_id"),
                        "attempt_id": result.get("attempt_id"),
                        "status": result.get("status"),
                        "ok": bool(result.get("ok")),
                        "pending": bool(result.get("pending")),
                        "requires_human": bool(result.get("requires_human")),
                        "requires_approval": bool(result.get("requires_approval")),
                        "response_chars": len(str(result.get("text") or "")) if result.get("ok") else 0,
                    },
                )
            )
            return result
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
                    browser_instance=str(params["browser_instance"]) if params.get("browser_instance") else None,
                    approved=bool(params.get("approved")),
                    no_focus=bool(params.get("no_focus", False)),
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(EventEnvelope("browser.session.created", {"session": _redact_browser_payload(result)}))
            return result
        if method == "browser.session.focus":
            try:
                result = self.browser.focus_session(
                    str(params.get("session_id") or params.get("id") or ""),
                    tab_id=str(params.get("tab_id")) if params.get("tab_id") else None,
                )
            except BrowserRuntimeError as exc:
                raise JsonRpcError(-32031, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "browser.session.focused",
                    {"session_id": result.get("session_id"), "tab_id": result.get("tab_id"), "focused": bool(result.get("focused"))},
                    session_id=result.get("session_id"),
                )
            )
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
            try:
                self._refresh_route_supervisor_catalog(refresh=False)
            except Exception as exc:
                self.logger.info(
                    "route catalog refresh after provider save failed error_type=%s",
                    type(exc).__name__,
                )
            return profile
        if method == "provider.profile.models":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            discover = params.get("discover", True)
            if type(discover) is not bool:
                raise JsonRpcError(-32602, "discover must be boolean")
            try:
                if discover:
                    result = self.provider_profiles.discover_models(profile_id)
                else:
                    profile = self.provider_profiles.get(profile_id)
                    result = {
                        "ok": True,
                        "status": "available",
                        "profile_id": profile_id,
                        "profile": profile,
                        "models": (profile.get("config") or {}).get("models", []),
                    }
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            try:
                self._refresh_route_supervisor_catalog(refresh=False)
            except Exception as exc:
                self.logger.info(
                    "route catalog refresh after model discovery failed error_type=%s",
                    type(exc).__name__,
                )
            self.events.publish(
                EventEnvelope(
                    "provider.profile.models",
                    {
                        "profile_id": profile_id,
                        "ok": bool(result.get("ok")),
                        "model_count": len(result.get("models", [])) if isinstance(result.get("models"), list) else 0,
                        "discovered": discover,
                    },
                )
            )
            return result
        if method == "provider.profile.model.select":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            model_id = str(params.get("model_id") or params.get("modelId") or "")
            try:
                result = self.provider_profiles.select_model(profile_id, model_id)
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            try:
                self._refresh_route_supervisor_catalog(refresh=False)
            except Exception as exc:
                self.logger.info(
                    "route catalog refresh after model selection failed error_type=%s",
                    type(exc).__name__,
                )
            self.events.publish(
                EventEnvelope(
                    "provider.profile.model.selected",
                    {"profile_id": profile_id, "model_id": model_id},
                )
            )
            return result
        if method == "provider.profile.health":
            profile_id = str(params.get("profile_id") or params.get("id") or "")
            model_id = params.get("model_id") or params.get("modelId")
            if model_id is not None and not isinstance(model_id, str):
                raise JsonRpcError(-32602, "model_id must be text")
            try:
                result = self.provider_profiles.health(
                    profile_id,
                    allow_chat_probe=True,
                    model_id=model_id,
                )
            except ProviderProfileError as exc:
                raise JsonRpcError(-32602, str(exc)) from exc
            self.events.publish(
                EventEnvelope(
                    "provider.profile.health",
                    {"profile_id": profile_id, "ok": bool(result.get("ok")), "status": result.get("profile", {}).get("status")},
                )
            )
            try:
                self._refresh_route_supervisor_catalog(refresh=False)
            except Exception as exc:
                self.logger.info(
                    "route catalog refresh after provider health failed error_type=%s",
                    type(exc).__name__,
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
                if isinstance(selected_adapter, str) and selected_adapter.startswith("web-chat:"):
                    expected_profile_id = selected_adapter.removeprefix("web-chat:")
                    if not profile_id or str(profile_id) != expected_profile_id:
                        raise JsonRpcError(-32602, "web-chat implementation requires its matching profile_id")
                    web_profile = self.storage.get_web_chat_profile(expected_profile_id)
                    if web_profile is None or web_profile.get("archived_at"):
                        raise JsonRpcError(-32602, "The selected web-chat profile is archived or unavailable")
                    try:
                        web_health = self.web_chat.health(expected_profile_id)
                    except WebChatRuntimeError as exc:
                        raise JsonRpcError(-32602, str(exc)) from exc
                    if not web_health.get("ok"):
                        raise JsonRpcError(-32602, str(web_health.get("reason") or "Test and authorize the web-chat profile before enabling LLM"))
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

    def _sync_web_chat_providers(self) -> None:
        """Project consented web-chat account profiles into the LLM registry.

        The registry is only a runtime projection.  Profile metadata remains
        owned by ``WebChatRuntime`` and browser cookies remain in the dedicated
        BrowserSkill profile.  A profile can therefore be archived or revoked
        without touching any other Provider or chat history.
        """

        if not hasattr(self, "providers") or not hasattr(self, "web_chat"):
            return
        desired: set[str] = set()
        try:
            profiles = self.web_chat.list_profiles(include_archived=False)
        except Exception as error:
            self.logger.info("web chat provider sync skipped error_type=%s", type(error).__name__)
            profiles = []
        for profile in profiles:
            if not isinstance(profile, dict) or profile.get("archived_at"):
                continue
            profile_id = str(profile.get("id") or "").strip()
            if not profile_id:
                continue
            provider_id = f"web-chat:{profile_id}"
            desired.add(provider_id)
            if self.providers.has(provider_id):
                provider = self.providers.get(provider_id)
                refresh = getattr(provider, "refresh", None)
                if callable(refresh):
                    refresh()
                continue
            try:
                self.providers.register(WebChatProvider(self.web_chat, profile_id))
            except Exception as error:
                self.logger.info(
                    "web chat provider registration skipped profile=%s error_type=%s",
                    profile_id,
                    type(error).__name__,
                )
        for info in self.providers.list():
            if info.id.startswith("web-chat:") and info.id not in desired:
                self.providers.unregister(info.id)
        if hasattr(self, "modules"):
            self.modules.refresh()

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

    @staticmethod
    def _agent_routing_config(
        params: dict[str, Any],
        *,
        text: str = "",
        mode: str = "execute",
    ) -> dict[str, Any] | None:
        """Normalize the optional per-turn model-policy request.

        Existing Agent callers remain on their explicitly selected Provider
        unless they send ``routing``/``routing_policy`` (or
        ``auto_route=true``).  This keeps old sessions stable while exposing a
        single opt-in boundary for recommendation and automatic routing.
        """

        raw = params.get("routing")
        if raw is None:
            raw = params.get("routing_policy")
        if raw is None and params.get("auto_route") is not True:
            return None
        if raw is True or raw is None:
            raw = {}
        elif isinstance(raw, str):
            raw = {"confirmation_mode": raw}
        if not isinstance(raw, dict):
            raise JsonRpcError(-32602, "routing must be an object or a confirmation mode")
        config = dict(raw)
        # Accept the short top-level aliases used by the UI and CLI.
        for key in (
            "difficulty",
            "risk",
            "task_kind",
            "taskKind",
            "budget_policy",
            "budgetPolicy",
            "confirmation_mode",
            "confirmationMode",
            "required_capabilities",
            "requiredCapabilities",
            "privacy_constraints",
            "privacyConstraints",
            "preferred_route",
            "preferredRoute",
            "min_quality_tier",
            "minQualityTier",
        ):
            if key not in config and key in params:
                config[key] = params[key]
        if not str(config.get("task_kind", config.get("taskKind", ""))).strip():
            config["task_kind"] = "plan" if str(mode).lower() == "plan" else "code"
        if not str(config.get("task_text", config.get("taskText", config.get("text", "")))).strip():
            config["task_text"] = str(text or params.get("text") or "")[:4000]
        if params.get("characterId") is not None and "character_id" not in config:
            config["character_id"] = params.get("characterId")
        if params.get("agentPreset") is not None and "agent_preset_id" not in config:
            config["agent_preset_id"] = params.get("agentPreset")
        return config

    def _agent_routing_preflight(
        self,
        params: dict[str, Any],
        *,
        text: str = "",
        mode: str = "execute",
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        config = self._agent_routing_config(params, text=text, mode=mode)
        if config is None:
            return None
        try:
            result = self.model_policy.preflight(config, session_id=session_id)
        except ModelPolicyError as exc:
            raise JsonRpcError(-32602, str(exc)) from exc
        decision = result.get("decision") if isinstance(result, dict) else None
        if not isinstance(decision, dict):
            raise JsonRpcError(-32032, "模型策略没有返回有效决策")
        return result

    def _apply_agent_route(
        self,
        decision: dict[str, Any],
        *,
        session_id: str | None,
        approved: bool,
    ) -> dict[str, Any]:
        """Apply one already preflighted route through the active harness."""

        if not isinstance(decision, dict):
            raise JsonRpcError(-32032, "模型策略决策无效")
        selected = decision.get("selected_entry")
        if not isinstance(selected, dict) or not decision.get("selected_route"):
            return {"applied": False, "reason": "no-compatible-route", "decision": decision}
        if bool(decision.get("requires_confirmation")) and not approved:
            return {"applied": False, "reason": "confirmation-required", "decision": decision}
        if not session_id:
            # A profile can be synchronized before a new session, but a
            # harness-only model cannot be selected until the runtime returns a
            # session id.  The create path handles profile routes separately.
            if not selected.get("provider_profile_id"):
                raise JsonRpcError(-32032, "所选 Harness 模型需要先创建 Agent 会话")
            return {"applied": False, "reason": "deferred-until-session", "decision": decision}

        profile_id = selected.get("provider_profile_id")
        if profile_id:
            if not self.agent.supports(AgentCapability.PROVIDER_BRIDGE):
                raise JsonRpcError(-32032, "当前 Agent runtime 不支持 Provider 档案桥接")
            try:
                profile = self._agent_provider_profile(
                    {"provider_profile_id": str(profile_id)},
                    refresh_health=True,
                )
                if profile.get("status") != "available":
                    raise ProviderProfileError("所选 Provider 档案当前不可用")
                binding = self.agent.sync_provider_profile(profile)
                selected_model = self.agent.select_model(
                    {
                        "session_id": session_id,
                        "provider": binding["route_id"],
                        "model": binding["model"],
                    }
                )
            except (AgentRuntimeError, ProviderProfileError) as exc:
                raise JsonRpcError(-32032, str(exc)) from exc
            return {
                "applied": True,
                "route_id": decision.get("selected_route"),
                "provider": binding,
                "selected_model": selected_model,
                "decision": decision,
            }

        harness_id = str(selected.get("harness_id") or "").strip()
        if harness_id and harness_id != str(self.agent.runtime_id):
            raise JsonRpcError(-32032, "所选模型属于另一个 Agent runtime")
        provider = str(selected.get("provider_id") or "").strip()
        model = str(selected.get("model_id") or "").strip()
        if not provider or not model:
            raise JsonRpcError(-32032, "所选模型缺少 Provider 或模型标识")
        try:
            selected_model = self.agent.select_model(
                {"session_id": session_id, "provider": provider, "model": model}
            )
        except AgentRuntimeError as exc:
            raise JsonRpcError(-32032, str(exc)) from exc
        return {
            "applied": True,
            "route_id": decision.get("selected_route"),
            "selected_model": selected_model,
            "decision": decision,
        }

    @staticmethod
    def _routing_approved(params: dict[str, Any]) -> bool:
        if params.get("routingApproved") is True or params.get("routing_approved") is True:
            return True
        raw = params.get("routing") or params.get("routing_policy")
        return isinstance(raw, dict) and raw.get("approved") is True

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

    def _active_web_chat_profile_id(self) -> str | None:
        """Return the enabled web-chat profile selected by the LLM module.

        Web-chat profiles are intentionally not mixed with ``provider_profiles``:
        their authentication material belongs to BrowserSkill.  Keeping this
        lookup separate prevents Agent/provider bridge code from accidentally
        attempting to read a browser profile as an API credential.
        """

        setting = self.storage.get_module_setting("llm")
        if not setting or not bool(setting.get("enabled")):
            return None
        implementation_id = str(setting.get("implementation_id") or "")
        if not implementation_id.startswith("web-chat:"):
            return None
        suffix = implementation_id.removeprefix("web-chat:").strip()
        profile_id = (setting.get("config") or {}).get("profile_id")
        if not suffix or not isinstance(profile_id, str) or profile_id.strip() != suffix:
            return None
        return suffix

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
        active_web_profile_id = self._active_web_chat_profile_id()
        if active_web_profile_id:
            # ``health`` is metadata-only for web accounts.  It does not read
            # page content or start a browser session, but keeps the module
            # status honest after an archive/restore or consent change.
            try:
                self.web_chat.health(active_web_profile_id)
            except WebChatRuntimeError:
                pass
        return [self._decorate_module(module) for module in self.modules.list()]

    def _module(self, module_id: str) -> dict[str, Any]:
        return self._decorate_module(self.modules.get(module_id))

    def _decorate_module(self, module: dict[str, Any]) -> dict[str, Any]:
        if module.get("id") != "llm":
            return module
        implementation_id = str(module.get("implementation_id") or "")
        is_api_profile = implementation_id == "openai-compatible"
        is_web_profile = implementation_id.startswith("web-chat:")
        if not is_api_profile and not is_web_profile:
            return module
        result = dict(module)
        profile_id = result.get("config", {}).get("profile_id")
        if is_web_profile:
            expected_id = implementation_id.removeprefix("web-chat:")
            if not isinstance(profile_id, str) or profile_id != expected_id:
                profile_id = expected_id or None
            profile = self.storage.get_web_chat_profile(str(profile_id)) if profile_id else None
            try:
                public_profile = self.web_chat.get_profile(str(profile_id), include_archived=True) if profile else None
            except WebChatRuntimeError as exc:
                # A malformed imported/snapshot row must not take down the
                # module and privacy endpoints.  Keep the implementation
                # visible as unavailable until the profile is repaired.
                self.logger.info(
                    "web chat profile projection unavailable profile=%s error_type=%s",
                    profile_id,
                    type(exc).__name__,
                )
                public_profile = None
            status_map = {
                "ready": "available",
                "needs-auth": "unconfigured",
                "unavailable": "error",
                "configured": "unconfigured",
                "draft": "unconfigured",
                "archived": "error",
            }
        else:
            profile = self.storage.get_provider_profile(str(profile_id)) if profile_id else None
            public_profile = self.provider_profiles.public(profile) if profile else None
            status_map = {
                "available": "available",
                "draft": "unconfigured",
                "unavailable": "error",
                "archived": "error",
            }
        result["profile_id"] = profile_id
        result["profile"] = public_profile
        if result.get("enabled"):
            profile_status = (public_profile or {}).get("status")
            result["status"] = status_map.get(str(profile_status), "unconfigured")
        implementation = dict(result.get("implementation") or {})
        implementation["status"] = result["status"]
        result["implementation"] = implementation
        result["config_schema"] = {}
        if is_web_profile:
            result["processing_location"] = "cloud"
            result["auth_state"] = (public_profile or {}).get("auth_state", "unknown")
            result["requires_human_login"] = (public_profile or {}).get("auth_state") != "authorized"
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
        configured_profile_id = self.modules.selected_profile("llm")
        profile_id = configured_profile_id if configured_provider_id == "openai-compatible" else None
        web_profile_id = None
        runtime_provider = None
        event_provider_id = configured_provider_id
        if configured_provider_id.startswith("web-chat:"):
            # Web accounts are projected into the same LLM registry as other
            # real providers, but their credentials remain in BrowserSkill.
            expected_profile_id = configured_provider_id.removeprefix("web-chat:").strip()
            if not expected_profile_id or configured_profile_id != expected_profile_id:
                raise JsonRpcError(-32010, "网页聊天模块的 profile_id 与实现不匹配；请重新选择连接")
            web_profile_id = expected_profile_id
            self._sync_web_chat_providers()
            if not self.providers.has(configured_provider_id):
                raise JsonRpcError(-32010, "网页聊天档案不可用；请先在 Agent 页检查登录状态")
            runtime_provider = self.providers.get(configured_provider_id)
            try:
                health = runtime_provider.health_check()
            except Exception as exc:
                raise JsonRpcError(-32010, f"网页聊天档案健康检查失败：{safe_error(exc)['message']}") from exc
            if not health.get("ok"):
                raise JsonRpcError(-32010, str(health.get("reason") or "网页聊天档案尚未授权"))
        elif profile_id:
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
        if web_profile_id:
            # ``send_message`` normally records usage itself.  Refreshing the
            # metadata here also covers a compatible provider wrapper that
            # returns a successful stream without updating the profile.
            try:
                self.web_chat.mark_used(web_profile_id)
            except WebChatRuntimeError:
                pass
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
            # Stop the neutral supervisor first so queued/running workers are
            # marked interrupted before any underlying runtime or browser is
            # torn down.  It is idempotent and owns only Core-created worker
            # bindings.
            if hasattr(self, "route_supervisor"):
                self.route_supervisor.close()
            # Workers retired during source replacement are no longer in the
            # supervisor registry, but an in-flight request may have kept
            # them alive.  Close them during the owning Core shutdown.
            for worker in list(getattr(self, "_retired_external_workers", ())):
                closer = getattr(worker, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        pass
            self._retired_external_workers = []
            self.providers.close()
            self.desktop_automation.close()
            self.agent.close()
            # Mark queued/running legacy web workers interrupted before
            # BrowserSkill sessions are torn down.  They are never replayed on
            # restart.
            self.routes.close()
            # WebChatRuntime owns only the sessions it created.  Release them
            # before BrowserRuntime tears down the underlying BrowserSkill
            # sessions and named-profile leases.
            self.web_chat.close()
            self.browser.close()
            # ZCode is separate from the selected main Agent runtime.  Close
            # it only when this Core constructed the optional worker; a user-
            # supplied/main runtime remains owned by its normal lifecycle.
            if getattr(self, "_zcode_runtime_owned", False) and self.zcode_runtime is not None:
                self.zcode_runtime.close()
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
            try:
                self.route_trace.write_daily_summary()
            except Exception as error:
                self.logger.warning("route decision trace close summary failed error_type=%s", type(error).__name__)
            self.route_trace.close()
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
            "desktop_automation": self.desktop_automation.status(),
            "browser_runtime": self.browser.status(),
            "agent_routes": {
                "catalog": self.route_supervisor.catalog(include_unavailable=True) if hasattr(self, "route_supervisor") else self.routes.catalog(include_templates=False),
                "consultations": self._list_route_consultations(limit=20) if hasattr(self, "route_supervisor") else self.routes.list_consultations(limit=20),
            },
            "zcode_runtime": self.zcode_runtime.status() if self.zcode_runtime is not None else {"configured": False, "state": "not-configured"},
            "workspace_checkpoint_count": len(self.workspace.list_checkpoints()["checkpoints"]),
            "evolution_registry": self.evolution_registry.check(),
            "agent_observability": self.observability.status(),
            "route_decision_trace": self.route_trace.status(),
            "model_policy": self._model_policy_diagnostics(),
            "capabilities": self.capabilities.summary(),
        }

    def _model_policy_diagnostics(self) -> dict[str, Any]:
        """Return a bounded, offline model-policy health summary."""

        try:
            catalog = self.model_policy.catalog(refresh=False)
            entries = catalog.get("entries", []) if isinstance(catalog, dict) else []
            return {
                "version": catalog.get("policy_version"),
                "entry_count": len(entries),
                "routable_count": sum(
                    1 for item in entries
                    if isinstance(item, dict) and item.get("routable") is True
                ),
                "quota_count": len(catalog.get("quotas", [])) if isinstance(catalog, dict) else 0,
                "checked_at": catalog.get("checked_at"),
            }
        except Exception as error:
            self.logger.info(
                "model policy diagnostics unavailable error_type=%s",
                type(error).__name__,
            )
            return {
                "version": None,
                "entry_count": 0,
                "routable_count": 0,
                "quota_count": 0,
                "status": "unavailable",
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
        if parsed.path == "/api/model-policy/catalog":
            query = parse_qs(parsed.query)
            refresh = (query.get("refresh") or ["false"])[0].lower() == "true"
            session_id = (query.get("session_id") or [None])[0]
            request = {"refresh": refresh}
            if session_id:
                request["sessionId"] = session_id
            self._send_json(self.application.rpc("model.policy.catalog", request))
            return
        if parsed.path == "/api/model-policy/pricing":
            query = parse_qs(parsed.query)
            request = {
                "refresh": (query.get("refresh") or ["false"])[0].lower() == "true",
            }
            profile_id = (query.get("provider_profile_id") or [None])[0]
            model_id = (query.get("model_id") or [None])[0]
            if profile_id:
                request["providerProfileId"] = profile_id
            if model_id:
                request["modelId"] = model_id
            try:
                self._send_json(self.application.rpc("model.policy.pricing", request))
            except JsonRpcError as exc:
                self._send_json({"error": exc.message, "code": exc.code}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/capabilities":
            query = parse_qs(parsed.query)
            refresh = (query.get("refresh") or ["false"])[0].lower() == "true"
            include_runtime = (query.get("include_runtime") or ["true"])[0].lower() == "true"
            session_id = (query.get("session_id") or [None])[0]
            request = {"refresh": refresh, "includeRuntime": include_runtime}
            if session_id:
                request["sessionId"] = session_id
            try:
                self._send_json(self.application.rpc("capability.catalog", request))
            except JsonRpcError as exc:
                self._send_json({"error": exc.message, "code": exc.code}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/model-policy/quota":
            query = parse_qs(parsed.query)
            refresh = (query.get("refresh") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("model.policy.quota", {"refresh": refresh}))
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
        if parsed.path == "/api/agent/route-trace":
            query = parse_qs(parsed.query)
            day = (query.get("day") or [None])[0]
            write = (query.get("write") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("agent.route.trace.daily", {"day": day, "write": write}))
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
        if parsed.path == "/api/browser/web-chat/adapters":
            self._send_json(self.application.rpc("browser.web_chat.adapters", {}))
            return
        if parsed.path == "/api/browser/web-chat/profiles":
            query = parse_qs(parsed.query)
            include_archived = (query.get("include_archived") or ["false"])[0].lower() == "true"
            self._send_json(self.application.rpc("browser.web_chat.profiles", {"include_archived": include_archived}))
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
        "browser_instance",
        "status",
        "state",
        "created_at",
        "updated_at",
        "expires_at",
        "lease_expires_at",
    }
    return {key: value[key] for key in allowed if key in value}


def _redact_web_chat_payload(value: Any) -> Any:
    """Project web-account metadata without page text or credentials."""

    if not isinstance(value, dict):
        return {}
    allowed = {
        "id",
        "name",
        "adapter_id",
        "adapter_name",
        "site_key",
        "browser_profile_id",
        "browser_instance",
        "chat_url",
        "status",
        "auth_state",
        "auto_chat_enabled",
        "allowed_actions",
        "budget_policy",
        "adapter_version",
        "created_at",
        "updated_at",
        "last_checked_at",
        "last_used_at",
        "archived_at",
        "active_session",
        "credentials_stored_in",
        "ready",
        "reason",
        "requires_human",
        "credentials_excluded",
        "human_action",
        "session_id",
        "tab_id",
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
