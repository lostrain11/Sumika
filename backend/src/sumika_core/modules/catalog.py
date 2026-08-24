"""The first module catalog boundary.

The catalog owns capability-level choices while providers own their runtime
implementation.  Keeping these concerns separate lets a future ASR, memory,
or Avatar plugin register without changing chat orchestration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..providers.audio_registry import AudioProviderRegistry
from ..providers.memory import SQLiteMemoryProvider
from ..providers.memory_registry import MemoryProviderRegistry
from ..providers.registry import ProviderRegistry
from ..providers.vision import CommandVisionProvider
from ..providers.vision_registry import VisionProviderRegistry
from ..protocol.models import ProviderInfo
from ..storage import Storage


class ModuleError(ValueError):
    """Raised when a module selection or configuration is invalid."""


_PROFILE_MANAGED_LLM_ADAPTERS = {"openai-compatible"}


@dataclass(frozen=True, slots=True)
class ModuleImplementation:
    id: str
    name: str
    status: str = "preview"
    description: str = ""
    config_schema: dict[str, Any] = field(default_factory=dict)
    source: str = "builtin"

    @classmethod
    def from_provider(cls, info: ProviderInfo) -> "ModuleImplementation":
        return cls(
            id=info.id,
            name=info.name,
            status=info.status,
            description=info.description,
            config_schema=info.config_schema,
            source="provider",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "description": self.description,
            "config_schema": self.config_schema,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    id: str
    name: str
    capability: str
    description: str
    default_enabled: bool
    default_implementation: str
    implementations: tuple[ModuleImplementation, ...]
    permissions: tuple[str, ...] = ()
    resource_requirements: dict[str, Any] = field(default_factory=dict)


def _none_implementation() -> ModuleImplementation:
    return ModuleImplementation(
        id="none",
        name="关闭模块",
        status="ready",
        description="保持该能力关闭，不启动外部实现。",
    )


def _first_real_id(implementations: tuple[ModuleImplementation, ...]) -> str:
    """Return the first usable implementation while keeping ``none`` legacy-safe."""
    return next((item.id for item in implementations if item.id != "none"), "none")


class ModuleCatalog:
    """Persist and validate user-selectable capability implementations."""

    def __init__(
        self,
        storage: Storage,
        providers: ProviderRegistry,
        audio: AudioProviderRegistry | None = None,
        memory: MemoryProviderRegistry | None = None,
        vision: VisionProviderRegistry | None = None,
    ) -> None:
        self.storage = storage
        self.providers = providers
        self.audio = audio or AudioProviderRegistry()
        self.memory = memory or _default_memory_registry(storage)
        self.vision = vision or _default_vision_registry()
        self._specs = self._build_specs()
        self._ensure_defaults()
        self._repair_missing_selections()

    def _build_specs(self) -> dict[str, ModuleSpec]:
        none = _none_implementation()
        provider_options = tuple(
            ModuleImplementation.from_provider(info)
            for info in self.providers.list()
            if info.capability == "llm"
        )
        provider_options = (none, *provider_options)
        default_implementation = next(
            (implementation.id for implementation in provider_options if implementation.id == "openai-compatible"),
            "none",
        )
        asr_options = (none, *self._audio_implementations("asr"))
        tts_options = (none, *self._audio_implementations("tts"))
        vad_options = (none, *self._audio_implementations("vad"))
        memory_options = (none, *self._memory_implementations())
        vision_options = (none, *self._vision_implementations())
        return {
            "llm": ModuleSpec(
                id="llm",
                name="大语言模型",
                capability="llm",
                description="对话生成的可替换 provider。",
                default_enabled=True,
                default_implementation=default_implementation,
                implementations=provider_options,
                resource_requirements={"network": "implementation-dependent"},
            ),
            "asr": ModuleSpec(
                id="asr",
                name="语音识别",
                capability="asr",
                description="将麦克风输入转换为文字，默认关闭。",
                default_enabled=False,
                default_implementation="none",
                implementations=asr_options,
                permissions=("microphone",),
                resource_requirements={"audio_input": True},
            ),
            "tts": ModuleSpec(
                id="tts",
                name="语音合成",
                capability="tts",
                description="将回复转换为语音，默认关闭。",
                default_enabled=False,
                default_implementation="none",
                implementations=tts_options,
                permissions=("audio_output",),
                resource_requirements={"audio_output": True},
            ),
            "vad": ModuleSpec(
                id="vad",
                name="语音活动检测",
                capability="vad",
                description="判断语音输入的开始与结束，默认关闭。",
                default_enabled=False,
                default_implementation="none",
                implementations=vad_options,
                permissions=("microphone",),
            ),
            "memory": ModuleSpec(
                id="memory",
                name="长期记忆",
                capability="memory",
                description="按类别保存可审计的长期信息，默认关闭。",
                default_enabled=False,
                default_implementation="none",
                implementations=memory_options,
                permissions=("memory.write",),
                resource_requirements={"storage": "local"},
            ),
            "vision": ModuleSpec(
                id="vision",
                name="视觉观察",
                capability="vision",
                description="受控读取屏幕或摄像头摘要，默认关闭。",
                default_enabled=False,
                default_implementation="none",
                implementations=vision_options,
                permissions=("screen.read", "camera.read"),
                resource_requirements={"raw_data_retention": "never"},
            ),
            "avatar": ModuleSpec(
                id="avatar",
                name="Avatar",
                capability="avatar",
                description="Live2D、VRM 或其他模型的渲染驱动。",
                default_enabled=True,
                default_implementation="none",
                implementations=(
                    none,
                    ModuleImplementation(
                        id="vrm",
                        name="VRM / 3D",
                        status="ready",
                        description="使用内置 Three.js/VRM 渲染器显示本地模型。",
                    ),
                ),
                resource_requirements={"rendering": "desktop"},
            ),
            "tools": ModuleSpec(
                id="tools",
                name="工具与外部软件",
                capability="tool",
                description="显式授权的本地命令或 JSON-RPC 工具。",
                default_enabled=False,
                default_implementation="none",
                implementations=(
                    none,
                    ModuleImplementation(
                        id="external-process",
                        name="External process",
                        description="使用 JSONL 调用一个明确配置的本地软件。",
                        config_schema={
                            "type": "object",
                            "required": ["executable"],
                            "properties": {
                                "executable": {"type": "string", "title": "可执行文件绝对路径"},
                                "arguments": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "title": "固定启动参数",
                                    "default": [],
                                },
                                "working_directory": {"type": "string", "title": "工作目录绝对路径"},
                                "timeout_seconds": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 120,
                                    "title": "超时秒数",
                                    "default": 30,
                                },
                            },
                        },
                    ),
                ),
                permissions=("process.spawn",),
                resource_requirements={"isolation": "separate-process", "sandbox": "not-provided"},
            ),
        }

    def _ensure_defaults(self) -> None:
        for spec in self._specs.values():
            if self.storage.get_module_setting(spec.id) is None:
                self.storage.upsert_module_setting(
                    spec.id,
                    enabled=spec.default_enabled,
                    implementation_id=spec.default_implementation,
                    config={},
                )

    def list(self) -> list[dict[str, Any]]:
        settings = {item["module_id"]: item for item in self.storage.list_module_settings()}
        return [self._serialize(spec, settings[spec.id]) for spec in self._specs.values()]

    def refresh(self) -> None:
        """Rebuild provider-backed implementation metadata after registration changes."""

        self._specs = self._build_specs()
        self._ensure_defaults()
        self._repair_missing_selections()

    def _repair_missing_selections(self) -> None:
        """Disable stale selections when an external implementation disappears."""

        for spec in self._specs.values():
            setting = self.storage.get_module_setting(spec.id)
            if setting is None:
                continue
            try:
                self._implementation(spec, str(setting["implementation_id"]))
            except ModuleError:
                self.storage.upsert_module_setting(
                    spec.id,
                    enabled=False,
                    implementation_id=spec.default_implementation,
                    config={},
                )

    def get(self, module_id: str) -> dict[str, Any]:
        try:
            spec = self._specs[module_id]
        except KeyError as exc:
            raise ModuleError(f"Unknown module: {module_id}") from exc
        setting = self.storage.get_module_setting(module_id)
        if setting is None:
            self._ensure_defaults()
            setting = self.storage.get_module_setting(module_id)
        assert setting is not None
        return self._serialize(spec, setting)

    def update(
        self,
        module_id: str,
        *,
        enabled: bool | None = None,
        implementation_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            spec = self._specs[module_id]
        except KeyError as exc:
            raise ModuleError(f"Unknown module: {module_id}") from exc
        setting = self.storage.get_module_setting(module_id)
        if setting is None:
            self._ensure_defaults()
            setting = self.storage.get_module_setting(module_id)
        assert setting is not None

        selected_id = implementation_id or str(setting["implementation_id"])
        # ``none`` was previously exposed as a second way to disable a
        # module. Keep it readable for old snapshots, but persist the real
        # implementation and let the module switch own the enabled state.
        disabling = implementation_id == "none"
        if selected_id == "none":
            selected_id = _first_real_id(spec.implementations)
        implementation = self._implementation(spec, selected_id)
        next_config = dict(setting["config"])
        secret_fields: list[str] = []
        if implementation_id is not None and implementation_id != setting["implementation_id"] and config is None:
            next_config = {}
        if config is not None:
            if not isinstance(config, dict):
                raise ModuleError("config must be an object")
            # Selecting an unconfigured real adapter is a valid intermediate
            # state; required fields are enforced once values are supplied.
            if module_id == "llm" and selected_id in _PROFILE_MANAGED_LLM_ADAPTERS:
                self._validate_profile_config(config)
            elif config or implementation.status != "unconfigured":
                self._validate_config(implementation.config_schema, config)
            next_config, secret_fields = (
                (dict(config), [])
                if module_id == "llm" and selected_id in _PROFILE_MANAGED_LLM_ADAPTERS
                else _persistable_config(implementation.config_schema, config)
            )

        if selected_id != "none":
            if module_id == "llm" and selected_id in _PROFILE_MANAGED_LLM_ADAPTERS:
                pass
            elif self.providers.has(selected_id):
                self.providers.configure(selected_id, config or next_config)
            elif self.audio.has(selected_id):
                self.audio.configure(selected_id, config or next_config)
            elif self.memory.has(selected_id):
                self.memory.configure(selected_id, config or next_config)
            elif self.vision.has(selected_id):
                self.vision.configure(selected_id, config or next_config)
        self.storage.upsert_module_setting(
            module_id,
            enabled=False if disabling else (bool(setting["enabled"]) if enabled is None else enabled),
            implementation_id=selected_id,
            config=next_config,
        )
        result = self.get(module_id)
        if secret_fields:
            result["secret_fields_not_persisted"] = secret_fields
        return result

    def is_enabled(self, module_id: str) -> bool:
        return bool(self.get(module_id)["enabled"])

    def selected_implementation(self, module_id: str) -> str:
        return str(self.get(module_id)["implementation_id"])

    def selected_profile(self, module_id: str) -> str | None:
        profile_id = self.get(module_id).get("config", {}).get("profile_id")
        return str(profile_id) if isinstance(profile_id, str) and profile_id else None

    def validate_snapshot_settings(self, rows: list[dict[str, Any]]) -> None:
        """Validate persisted module rows before a snapshot can be restored."""
        for row in rows:
            module_id = str(row.get("module_id") or "")
            try:
                spec = self._specs[module_id]
            except KeyError as exc:
                raise ModuleError(f"Unknown module in snapshot: {module_id}") from exc
            implementation_id = str(row.get("implementation_id") or "")
            implementation = self._implementation(spec, implementation_id)
            config_value = row.get("config_json", "{}")
            try:
                config = json.loads(config_value) if isinstance(config_value, str) else config_value
            except json.JSONDecodeError as exc:
                raise ModuleError(f"Invalid module config in snapshot: {module_id}") from exc
            if not isinstance(config, dict):
                raise ModuleError(f"Invalid module config in snapshot: {module_id}")
            if module_id == "llm" and implementation_id in _PROFILE_MANAGED_LLM_ADAPTERS:
                self._validate_profile_config(config)
            elif config or implementation.status != "unconfigured":
                self._validate_config(implementation.config_schema, config)

    def restore_runtime(self) -> None:
        """Apply restored module selections to the already-running providers."""
        for spec in self._specs.values():
            setting = self.storage.get_module_setting(spec.id)
            if setting is None:
                continue
            implementation_id = str(setting["implementation_id"])
            self._implementation(spec, implementation_id)
            if implementation_id == "none":
                continue
            config = setting["config"]
            if spec.id == "llm" and implementation_id in _PROFILE_MANAGED_LLM_ADAPTERS:
                continue
            if self.providers.has(implementation_id):
                self.providers.configure(implementation_id, config)
            elif self.audio.has(implementation_id):
                self.audio.configure(implementation_id, config)
            elif self.memory.has(implementation_id):
                self.memory.configure(implementation_id, config)
            elif self.vision.has(implementation_id):
                self.vision.configure(implementation_id, config)

    @staticmethod
    def _implementation(spec: ModuleSpec, implementation_id: str) -> ModuleImplementation:
        for implementation in spec.implementations:
            if implementation.id == implementation_id:
                return implementation
        raise ModuleError(f"Unknown implementation for {spec.id}: {implementation_id}")

    def _serialize(self, spec: ModuleSpec, setting: dict[str, Any]) -> dict[str, Any]:
        selected_id = str(setting["implementation_id"])
        if selected_id == "none":
            # Present a coherent state to new clients even before a legacy
            # row is edited. The old value remains recoverable in SQLite.
            selected_id = _first_real_id(spec.implementations)
            enabled = False
        else:
            enabled = bool(setting["enabled"])
        implementation = self._runtime_implementation(self._implementation(spec, selected_id))
        status = "disabled" if not enabled else implementation.status
        return {
            "id": spec.id,
            "name": spec.name,
            "capability": spec.capability,
            "description": spec.description,
            "enabled": enabled,
            "status": status,
            "implementation_id": implementation.id,
            "implementation": implementation.to_dict(),
            # Keep the legacy value in the protocol for old snapshots and
            # clients. The first-party UI deliberately hides it and uses the
            # module switch as the only disable control.
            "implementations": [self._runtime_implementation(item).to_dict() for item in spec.implementations],
            "config": setting["config"],
            "config_schema": {} if spec.id == "llm" and implementation.id in _PROFILE_MANAGED_LLM_ADAPTERS else implementation.config_schema,
            "permissions": list(spec.permissions),
            "resource_requirements": spec.resource_requirements,
            "updated_at": setting["updated_at"],
        }

    def _runtime_implementation(self, implementation: ModuleImplementation) -> ModuleImplementation:
        if implementation.source == "provider" and self.providers.has(implementation.id):
            return ModuleImplementation.from_provider(self.providers.get(implementation.id).info)
        if implementation.source == "provider" and self.audio.has(implementation.id):
            return ModuleImplementation.from_provider(self.audio.get(implementation.id).info)
        if implementation.source == "provider" and self.memory.has(implementation.id):
            return ModuleImplementation.from_provider(self.memory.get(implementation.id).info)
        if implementation.source == "provider" and self.vision.has(implementation.id):
            return ModuleImplementation.from_provider(self.vision.get(implementation.id).info)
        return implementation

    @staticmethod
    def _validate_profile_config(config: dict[str, Any]) -> None:
        profile_id = config.get("profile_id")
        if isinstance(profile_id, str) and profile_id.strip():
            if set(config) != {"profile_id"}:
                raise ModuleError("LLM module configuration may only contain profile_id")
            return
        # Version-1 snapshots stored the OpenAI-compatible fields directly.
        # They are accepted only for restore and are migrated immediately by
        # CoreApplication before the runtime is resumed.
        legacy_fields = {"base_url", "model", "timeout"}
        if config and set(config).issubset(legacy_fields) and isinstance(config.get("base_url"), str) and isinstance(config.get("model"), str):
            return
        if not config:
            return
        raise ModuleError("LLM module configuration requires a provider profile_id")

    def _audio_implementations(self, capability: str) -> tuple[ModuleImplementation, ...]:
        return tuple(
            ModuleImplementation.from_provider(info)
            for info in self.audio.list(capability)
        )

    def _memory_implementations(self) -> tuple[ModuleImplementation, ...]:
        return tuple(
            ModuleImplementation.from_provider(info)
            for info in self.memory.list()
        )

    def _vision_implementations(self) -> tuple[ModuleImplementation, ...]:
        return tuple(
            ModuleImplementation.from_provider(info)
            for info in self.vision.list()
        )

    @staticmethod
    def _validate_config(schema: dict[str, Any], config: dict[str, Any]) -> None:
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        for key in required:
            if key not in config or config[key] in (None, ""):
                raise ModuleError(f"Missing required config field: {key}")
        for key, value in config.items():
            definition = properties.get(key)
            if not isinstance(definition, dict):
                continue
            expected = definition.get("type")
            if expected == "string" and not isinstance(value, str):
                raise ModuleError(f"Config field must be a string: {key}")
            if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise ModuleError(f"Config field must be a number: {key}")
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ModuleError(f"Config field must be an integer: {key}")
            if expected == "boolean" and not isinstance(value, bool):
                raise ModuleError(f"Config field must be a boolean: {key}")
            if expected == "array" and not isinstance(value, list):
                raise ModuleError(f"Config field must be an array: {key}")
            if expected == "object" and not isinstance(value, dict):
                raise ModuleError(f"Config field must be an object: {key}")
            minimum = definition.get("minimum")
            if minimum is not None and isinstance(value, (int, float)) and value < minimum:
                raise ModuleError(f"Config field is below minimum: {key}")
            maximum = definition.get("maximum")
            if maximum is not None and isinstance(value, (int, float)) and value > maximum:
                raise ModuleError(f"Config field is above maximum: {key}")
            items = definition.get("items")
            if expected == "array" and isinstance(items, dict) and items.get("type") == "string":
                if not all(isinstance(item, str) for item in value):
                    raise ModuleError(f"Config array items must be strings: {key}")


def _persistable_config(schema: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    secret_fields = {
        key
        for key, definition in properties.items()
        if isinstance(definition, dict) and definition.get("format") == "password"
    }
    return ({key: value for key, value in config.items() if key not in secret_fields}, sorted(secret_fields & config.keys()))


def _default_memory_registry(storage: Storage) -> MemoryProviderRegistry:
    registry = MemoryProviderRegistry()
    registry.register(SQLiteMemoryProvider(storage))
    return registry


def _default_vision_registry() -> VisionProviderRegistry:
    registry = VisionProviderRegistry()
    registry.register(CommandVisionProvider())
    return registry
