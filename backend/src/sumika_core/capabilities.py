"""Unified, read-only capability implementation catalog.

The catalog is a projection boundary.  It does not install, start, configure,
or execute an implementation; it only combines the state already reported by
the module/provider/runtime registries into one UI-safe shape.  Keeping this
projection independent from a particular harness lets DSH, ZCode, or a future
runtime expose the same capability vocabulary without making the Core depend
on one implementation.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .protocol.models import utc_now


CAPABILITY_CATALOG_VERSION = "capability-catalog/v1"

# These are presentation states, not adapter-specific protocol states.  The
# set deliberately includes observed/configured states used by MCP and
# BrowserSkill so a disconnected implementation is never presented as ready.
VALID_CAPABILITY_STATUSES = frozenset(
    {
        "available",
        "ready",
        "healthy",
        "running",
        "low",
        "not-applicable",
        "disabled",
        "unconfigured",
        "draft",
        "needs-auth",
        "unavailable",
        "error",
        "discovered",
        "changed",
        "revoked",
        "invalid",
        "configured",
        "observed",
        "not-exposed",
        "not-installed",
        "awaiting-extension",
        "policy-only",
        "declared",
        "preview",
        "approved",
        "rejected",
        "session-scoped",
        "unknown",
    }
)

_BLOCKED_NAME_TOKENS = ("fake", "stub", "placeholder")
_SENSITIVE_KEY_TOKENS = (
    "secret",
    "password",
    "token",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "credential",
)
_PATH_VALUE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]\\?\\?\\?[\\/]|/|\\\\)")
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9._:-]+")

_CAPABILITY_LABELS = {
    "llm": "大语言模型",
    "asr": "语音识别",
    "tts": "语音合成",
    "vad": "语音活动检测",
    "memory": "长期记忆",
    "vision": "视觉观察",
    "avatar": "Avatar",
    "tools": "工具与外部软件",
    "browser": "隔离浏览器",
    "harness": "Agent Harness",
    "skill": "Skills",
    "mcp": "MCP",
}

_CAPABILITY_ORDER = (
    "harness",
    "llm",
    "tools",
    "browser",
    "mcp",
    "skill",
    "memory",
    "vision",
    "asr",
    "tts",
    "vad",
    "avatar",
)


class CapabilityCatalogError(ValueError):
    """Raised when a capability descriptor cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class CapabilityImplementationDescriptor:
    """One selectable implementation or explicit module control."""

    id: str
    capability: str
    name: str
    status: str = "unknown"
    selectable: bool = False
    selected: bool = False
    enabled: bool = False
    source_type: str = "builtin"
    transport: str = "in-process"
    trust: str = "builtin"
    lifecycle: str = "in-process"
    processing_location: str = "unknown"
    permissions: tuple[str, ...] = ()
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("id", "capability", "name"):
            value = _safe_text(getattr(self, name), 240)
            if not value:
                raise CapabilityCatalogError(f"{name} is required")
            object.__setattr__(self, name, value)
        capability = _canonical_capability(self.capability)
        object.__setattr__(self, "capability", capability)
        status = _safe_text(self.status, 48).lower() or "unknown"
        if status not in VALID_CAPABILITY_STATUSES:
            raise CapabilityCatalogError(f"invalid capability status: {status}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "selectable", bool(self.selectable))
        object.__setattr__(self, "selected", bool(self.selected))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "source_type", _safe_text(self.source_type, 80) or "builtin")
        object.__setattr__(self, "transport", _safe_text(self.transport, 80) or "in-process")
        object.__setattr__(self, "trust", _safe_text(self.trust, 80) or "unknown")
        object.__setattr__(self, "lifecycle", _safe_text(self.lifecycle, 80) or "in-process")
        object.__setattr__(self, "processing_location", _safe_text(self.processing_location, 40).lower() or "unknown")
        object.__setattr__(self, "permissions", _safe_tuple(self.permissions))
        object.__setattr__(self, "description", _safe_text(self.description, 600))
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))

    @property
    def ready(self) -> bool:
        return self.status in {"available", "ready", "healthy", "running"}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["permissions"] = list(self.permissions)
        value["ready"] = self.ready
        return value


class CapabilityCatalog:
    """Project all known implementation sources into one safe catalog."""

    def __init__(
        self,
        modules: Any = None,
        *,
        agent: Any = None,
        browser: Any = None,
        plugins: Any = None,
        skills: Any = None,
        model_policy: Any = None,
        logger: Any = None,
    ) -> None:
        self.modules = modules
        self.agent = agent
        self.browser = browser
        self.plugins = plugins
        self.skills = skills
        self.model_policy = model_policy
        self.logger = logger

    def catalog(
        self,
        *,
        refresh: bool = False,
        session_id: str | None = None,
        include_runtime: bool = True,
    ) -> dict[str, Any]:
        """Return a bounded, read-only capability projection.

        ``refresh`` is passed only to existing read-only health/catalog APIs.
        This method never changes a module selection or approves an external
        source.  ``include_runtime=False`` is used by the cheap diagnostics
        path to avoid probing a child process or BrowserSkill CLI.
        """

        entries: list[CapabilityImplementationDescriptor] = []
        errors: list[dict[str, str]] = []
        module_rows = self._module_rows(errors)
        selected_by_capability = self._selected_map(module_rows)

        def extend_from(source: str, factory: Any, *args: Any) -> None:
            try:
                values = factory(*args)
                if isinstance(values, list):
                    entries.extend(item for item in values if isinstance(item, CapabilityImplementationDescriptor))
            except Exception as error:
                errors.append({"source": source, "error": type(error).__name__})
                if self.logger is not None:
                    try:
                        self.logger.info("capability catalog source failed source=%s error_type=%s", source, type(error).__name__)
                    except Exception:
                        pass

        # LLM profiles, harness models, and web-chat candidates are already
        # normalized by model-policy.  Keeping them here avoids a second
        # interpretation of Provider credentials and quota state.
        model_rows = self._model_rows(refresh, session_id, errors)
        extend_from("model-policy-projection", self._model_entries, model_rows, selected_by_capability)
        extend_from("module-projection", self._module_entries, module_rows, selected_by_capability)
        extend_from("plugin-projection", self._plugin_entries, selected_by_capability)
        extend_from("skill-projection", self._skill_entries)

        if include_runtime:
            extend_from("agent-runtime", self._runtime_entries)
            extend_from("browser", self._browser_entries, errors)
            extend_from("mcp", self._mcp_entries, errors)
        else:
            # The current runtime remains useful in diagnostics without a
            # network probe; Browser/MCP details are intentionally omitted.
            extend_from("agent-runtime", self._runtime_entries)

        entries = _deduplicate_entries(entries)
        groups = self._groups(entries)
        ready_count = sum(1 for item in entries if item.ready)
        selectable_count = sum(1 for item in entries if item.selectable)
        return {
            "schema": CAPABILITY_CATALOG_VERSION,
            "checked_at": utc_now(),
            "refresh_requested": bool(refresh),
            "groups": groups,
            "entries": [item.to_dict() for item in entries],
            "summary": {
                "group_count": len(groups),
                "entry_count": len(entries),
                "ready_count": ready_count,
                "selectable_count": selectable_count,
                "source_errors": len(errors),
            },
            "source_errors": errors[:16],
        }

    def summary(self) -> dict[str, Any]:
        """Return counts for Core diagnostics without probing external tools."""

        value = self.catalog(include_runtime=False)
        summary = value["summary"]
        return {
            "schema": value["schema"],
            "group_count": summary["group_count"],
            "entry_count": summary["entry_count"],
            "ready_count": summary["ready_count"],
            "selectable_count": summary["selectable_count"],
            "source_errors": summary["source_errors"],
            "checked_at": value["checked_at"],
        }

    def _module_rows(self, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
        if self.modules is None:
            return []
        try:
            value = self.modules.list()
        except Exception as error:  # projection boundary must stay available
            errors.append({"source": "modules", "error": type(error).__name__})
            return []
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _model_rows(
        self,
        refresh: bool,
        session_id: str | None,
        errors: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if self.model_policy is None:
            return []
        try:
            value = self.model_policy.catalog(refresh=refresh, session_id=session_id)
        except Exception as error:
            errors.append({"source": "model-policy", "error": type(error).__name__})
            return []
        rows = value.get("entries") if isinstance(value, dict) else []
        return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []

    @staticmethod
    def _selected_map(rows: Iterable[dict[str, Any]]) -> dict[str, tuple[str, bool]]:
        result: dict[str, tuple[str, bool]] = {}
        for row in rows:
            module_id = _safe_text(row.get("id"), 80)
            implementation_id = _safe_text(row.get("implementation_id"), 180)
            if module_id and implementation_id:
                selected_id = implementation_id
                if module_id == "llm":
                    config = row.get("config") if isinstance(row.get("config"), dict) else {}
                    profile_id = _safe_text(config.get("profile_id"), 160)
                    if profile_id:
                        selected_id = profile_id
                result[module_id] = (selected_id, bool(row.get("enabled")))
        return result

    def _model_entries(
        self,
        rows: Iterable[dict[str, Any]],
        selected_modules: Mapping[str, tuple[str, bool]],
    ) -> list[CapabilityImplementationDescriptor]:
        current_profile = selected_modules.get("llm", ("", False))[0]
        result: list[CapabilityImplementationDescriptor] = []
        for row in rows:
            route_id = _safe_text(row.get("route_id"), 280)
            if not route_id or _contains_blocked_name(row.get("display_name"), row.get("provider_id"), route_id):
                continue
            source_kind = _safe_text(row.get("source_kind"), 80).lower() or "provider"
            model_id = _safe_text(row.get("model_id"), 240) or "unconfigured"
            auth_state = _safe_text(row.get("auth_state"), 48).lower() or "unknown"
            quota_state = _safe_text(row.get("quota_state"), 48).lower() or "unknown"
            health_state = _safe_text(row.get("health_state"), 48).lower() or "unknown"
            status = _model_status(auth_state, quota_state, health_state, model_id)
            is_web = source_kind == "web-chat"
            is_harness = source_kind == "harness"
            profile_id = _safe_text(row.get("provider_profile_id"), 160)
            is_selected = bool(profile_id and profile_id == current_profile and not is_harness and not is_web)
            if is_web:
                source_type, transport, trust, lifecycle = "web-chat", "browser-dom", "unverified", "browser-session"
                selectable = False
                permissions = ("browser", "manual-login")
            elif is_harness:
                source_type, transport, trust, lifecycle = "harness-model", "runtime", "managed", "session"
                selectable = bool(row.get("routable"))
                permissions = ("agent.model",)
            else:
                source_type, transport, trust, lifecycle = "provider-profile", "http", "user-configured", "profile"
                selectable = bool(row.get("routable"))
                permissions = ("network",) if str(row.get("processing_location") or "cloud") != "local" else ()
            metadata = {
                "route_id": route_id,
                "provider_id": _safe_text(row.get("provider_id"), 160),
                "model_id": model_id,
                "profile_id": profile_id or None,
                "harness_id": _safe_text(row.get("harness_id"), 100) or None,
                "routable": bool(row.get("routable")),
                "requires_browser": bool(row.get("requires_browser")),
                "auth_state": auth_state,
                "quota_state": quota_state,
                "health_state": health_state,
                "quality_tier": _safe_text(row.get("quality_tier"), 48),
                "cost_class": _safe_text(row.get("cost_class"), 48),
            }
            if is_web:
                metadata.update(
                    {
                        "requires_user_login": True,
                        "authorization_boundary": "manual-login",
                        "quota_source": "provider_web_account",
                    }
                )
            result.append(
                CapabilityImplementationDescriptor(
                    id=_stable_id("llm", route_id),
                    capability="llm",
                    name=_safe_text(row.get("display_name"), 280) or model_id,
                    status=status,
                    selectable=selectable,
                    selected=is_selected,
                    enabled=is_selected and bool(selected_modules.get("llm", ("", False))[1]),
                    source_type=source_type,
                    transport=transport,
                    trust=trust,
                    lifecycle=lifecycle,
                    processing_location=_safe_text(row.get("processing_location"), 40).lower() or "unknown",
                    permissions=permissions,
                    description=(
                        "需要在隔离浏览器中登录并由用户确认；不会伪装成 API Provider。"
                        if is_web
                        else "由当前模型策略目录报告的真实连接或 Harness 模型。"
                    ),
                    metadata=metadata,
                )
            )
        return result

    def _module_entries(
        self,
        rows: Iterable[dict[str, Any]],
        selected: Mapping[str, tuple[str, bool]],
    ) -> list[CapabilityImplementationDescriptor]:
        result: list[CapabilityImplementationDescriptor] = []
        for row in rows:
            module_id = _safe_text(row.get("id"), 80)
            capability = _canonical_capability(row.get("capability"))
            if not module_id or capability == "llm":
                # LLM is represented by model-policy entries above.  This
                # avoids showing the same profile once as an adapter and once
                # as a model route.
                continue
            module_enabled = bool(row.get("enabled"))
            selected_id, selected_enabled = selected.get(module_id, ("", module_enabled))
            implementations = row.get("implementations") if isinstance(row.get("implementations"), list) else []
            permissions = _safe_tuple(row.get("permissions"))
            config = row.get("config") if isinstance(row.get("config"), dict) else {}
            for implementation in implementations:
                if not isinstance(implementation, dict):
                    continue
                implementation_id = _safe_text(implementation.get("id"), 180)
                name = _safe_text(implementation.get("name"), 240)
                if not implementation_id or not name or _contains_blocked_name(implementation_id, name, implementation.get("description")):
                    continue
                is_none = implementation_id == "none"
                is_selected = not is_none and implementation_id == selected_id
                if is_none:
                    result.append(
                        CapabilityImplementationDescriptor(
                            id=f"{module_id}:disable",
                            capability=capability,
                            name="关闭模块",
                            status="disabled",
                            selectable=True,
                            selected=not module_enabled,
                            enabled=False,
                            source_type="control",
                            transport="in-process",
                            trust="builtin",
                            lifecycle="control",
                            processing_location="local",
                            permissions=(),
                            description="关闭该能力；这不是一个 Provider 或占位实现。",
                            metadata={"control": "disable-module", "module_id": module_id},
                        )
                    )
                    continue
                source = _safe_text(implementation.get("source"), 80).lower() or "builtin"
                raw_status = _safe_text(implementation.get("status"), 48).lower() or "unknown"
                status = _module_status(raw_status, is_selected, module_enabled)
                if source == "provider":
                    source_type, transport, trust, lifecycle = "provider", "adapter", "builtin", "provider"
                elif implementation_id.startswith("plugin:"):
                    source_type, transport, trust, lifecycle = "plugin", "external-process", "approved", "plugin-process"
                elif implementation_id == "external-process":
                    source_type, transport, trust, lifecycle = "external-software", "external-process", "user-configured", "managed-process"
                else:
                    source_type, transport, trust, lifecycle = "builtin", "in-process", "builtin", "in-process"
                schema = implementation.get("config_schema") if isinstance(implementation.get("config_schema"), dict) else {}
                processing = _processing_location(capability, config)
                result.append(
                    CapabilityImplementationDescriptor(
                        id=f"{module_id}:{implementation_id}",
                        capability=capability,
                        name=name,
                        status=status,
                        selectable=raw_status != "preview",
                        selected=is_selected,
                        enabled=is_selected and bool(selected_enabled),
                        source_type=source_type,
                        transport=transport,
                        trust=trust,
                        lifecycle=lifecycle,
                        processing_location=processing,
                        permissions=permissions,
                        description=_safe_text(implementation.get("description"), 600),
                        metadata={
                            "module_id": module_id,
                            "implementation_id": implementation_id,
                            "configuration_required": status in {"unconfigured", "draft"},
                            "config_schema_available": bool(schema),
                        },
                    )
                )
        return result

    def _plugin_entries(self, selected: Mapping[str, tuple[str, bool]]) -> list[CapabilityImplementationDescriptor]:
        if self.plugins is None:
            return []
        try:
            rows = self.plugins.list()
        except Exception:
            return []
        result: list[CapabilityImplementationDescriptor] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            manifest = row.get("manifest") if isinstance(row.get("manifest"), dict) else {}
            plugin_id = _safe_text(row.get("plugin_id") or manifest.get("id"), 180)
            candidate_id = _safe_text(row.get("candidate_id"), 180)
            if not plugin_id or not candidate_id or _contains_blocked_name(plugin_id, row.get("name")):
                continue
            capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), list) else []
            state = _safe_text(row.get("state"), 48).lower() or "invalid"
            configured = bool(row.get("launcher"))
            status = "available" if state == "approved" and configured else "unconfigured" if state == "approved" else state
            for raw_capability in capabilities[:16]:
                capability = _canonical_capability(raw_capability)
                if capability not in _CAPABILITY_LABELS or capability == "harness":
                    continue
                module_selected = selected.get("llm" if capability == "llm" else capability, ("", False))
                implementation_id = f"plugin:{candidate_id}"
                result.append(
                    CapabilityImplementationDescriptor(
                        id=f"plugin:{candidate_id}:{capability}",
                        capability=capability,
                        name=f"Plugin · {plugin_id}",
                        status=status,
                        selectable=status == "available",
                        selected=module_selected[0] == implementation_id,
                        enabled=module_selected[0] == implementation_id and module_selected[1],
                        source_type="plugin",
                        transport="external-process",
                        trust="approved" if state == "approved" else "unverified",
                        lifecycle="plugin-process",
                        processing_location="unknown",
                        permissions=("process.spawn",),
                        description="来自已登记 manifest 的外部插件；启动前仍会重新验证清单和入口哈希。",
                        metadata={
                            "candidate_id": candidate_id,
                            "plugin_id": plugin_id,
                            "version": _safe_text(row.get("version") or manifest.get("version"), 80),
                            "manifest_sha256": _safe_text(row.get("manifest_sha256"), 80),
                            "configured": configured,
                            "registration_state": state,
                        },
                    )
                )
        return result

    def _skill_entries(self) -> list[CapabilityImplementationDescriptor]:
        if self.skills is None:
            return []
        try:
            rows = self.skills.list(refresh=False)
        except Exception:
            return []
        result: list[CapabilityImplementationDescriptor] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            skill_id = _safe_text(row.get("skill_id") or row.get("candidate_id"), 180)
            name = _safe_text(row.get("name") or skill_id, 240)
            if not skill_id or _contains_blocked_name(skill_id, name):
                continue
            state = _safe_text(row.get("state"), 48).lower() or "invalid"
            result.append(
                CapabilityImplementationDescriptor(
                    id=f"skill:{skill_id}",
                    capability="skill",
                    name=name,
                    status=state if state in VALID_CAPABILITY_STATUSES else "unknown",
                    selectable=state == "approved",
                    selected=False,
                    enabled=False,
                    source_type="skill",
                    transport="metadata-only",
                    trust="approved" if state == "approved" else "unverified",
                    lifecycle="session-scoped",
                    processing_location="local",
                    permissions=_safe_tuple(row.get("permissions")),
                    description="只读 Skill 元数据；正文由当前 Harness 按会话策略加载。",
                    metadata={
                        "candidate_id": _safe_text(row.get("candidate_id"), 180),
                        "skill_id": skill_id,
                        "version": _safe_text(row.get("version"), 80),
                        "manifest_sha256": _safe_text(row.get("manifest_sha256"), 80),
                        "metadata_only": True,
                    },
                )
            )
        return result

    def _runtime_entries(self) -> list[CapabilityImplementationDescriptor]:
        if self.agent is None:
            return []
        try:
            status = self.agent.status()
        except Exception:
            status = {"state": "unavailable", "ready": False}
        if not isinstance(status, dict):
            status = {"state": "unavailable", "ready": False}
        runtime_id = _safe_text(getattr(self.agent, "runtime_id", None) or status.get("runtime_id"), 100) or "unknown"
        state = _safe_text(status.get("state"), 48).lower()
        capability_status = "available" if status.get("ready") is True else "disabled" if state == "disabled" else "unavailable"
        try:
            capabilities = getattr(self.agent, "runtime_capabilities", lambda: [])()
        except Exception:
            capabilities = []
        return [
            CapabilityImplementationDescriptor(
                id=f"harness:{runtime_id}",
                capability="harness",
                name=runtime_id.upper() if runtime_id != "unknown" else "Agent Harness",
                status=capability_status,
                selectable=False,
                selected=True,
                enabled=bool(status.get("ready")),
                source_type="harness",
                transport=_safe_text(status.get("transport"), 80) or "runtime",
                trust="managed" if status.get("managed") is not False else "external",
                lifecycle="managed-process" if status.get("managed") is not False else "external-process",
                processing_location="local",
                permissions=("process.spawn",) if status.get("managed") is not False else (),
                description="当前 Sumika 受管 Agent Runtime；Session、Plan、工具和审批能力以其声明为准。",
                metadata={
                    "runtime_id": runtime_id,
                    "version": _safe_text(status.get("version"), 120),
                    "managed": status.get("managed") is not False,
                    "configured": bool(status.get("configured", True)),
                    "runtime_capabilities": list(capabilities)[:64] if isinstance(capabilities, list) else [],
                },
            )
        ]

    def _browser_entries(self, errors: list[dict[str, str]]) -> list[CapabilityImplementationDescriptor]:
        if self.browser is None:
            return []
        try:
            value = self.browser.status()
        except Exception as error:
            errors.append({"source": "browser", "error": type(error).__name__})
            value = {"state": "unavailable", "ready": False}
        if not isinstance(value, dict):
            value = {"state": "unavailable", "ready": False}
        raw_state = _safe_text(value.get("state"), 48).lower() or "unavailable"
        status = "available" if value.get("ready") is True else raw_state if raw_state in VALID_CAPABILITY_STATUSES else "unavailable"
        metadata = {
            "backend": _safe_text(value.get("backend"), 80),
            "backend_commit": _safe_text(value.get("backend_commit"), 100),
            "cli_version": _safe_text(value.get("cli_version"), 80),
            "extension_version": _safe_text(value.get("extension_version"), 80),
            "auto_update": value.get("auto_update") is True,
            "global_desktop_control": value.get("global_desktop_control") is True,
            "policy_bridge": _safe_metadata(value.get("policy_bridge")),
            "requires_manual_login": True,
        }
        return [
            CapabilityImplementationDescriptor(
                id="browser:browser-skill",
                capability="browser",
                name="BrowserSkill",
                status=status,
                selectable=False,
                selected=True,
                enabled=bool(value.get("ready")),
                source_type="browser-runtime",
                transport="dom-cdp",
                trust="pinned",
                lifecycle="managed-process",
                processing_location="local",
                permissions=("browser.navigation", "browser.dom", "browser.sensitive-action"),
                description="隔离浏览器能力；登录、提交、下载和其他敏感动作始终需要人工批准。",
                metadata=metadata,
            )
        ]

    def _mcp_entries(self, errors: list[dict[str, str]]) -> list[CapabilityImplementationDescriptor]:
        if self.agent is None:
            return []
        try:
            supports = self.agent.supports("mcp")
        except Exception:
            supports = False
        if not supports:
            return []
        try:
            value = self.agent.mcp_catalog({})
        except Exception as error:
            errors.append({"source": "mcp", "error": type(error).__name__})
            value = {"status": "unavailable", "entries": [], "reason": "MCP catalog unavailable"}
        if not isinstance(value, dict):
            value = {"status": "unavailable", "entries": []}
        rows = value.get("entries") if isinstance(value.get("entries"), list) else []
        result: list[CapabilityImplementationDescriptor] = []
        for row in rows[:256]:
            if not isinstance(row, dict):
                continue
            server_id = _safe_text(row.get("id") or row.get("name"), 180)
            if not server_id or _contains_blocked_name(server_id):
                continue
            raw_status = _safe_text(row.get("status"), 48).lower() or "unknown"
            status = raw_status if raw_status in VALID_CAPABILITY_STATUSES else "unknown"
            sources = _safe_tuple(row.get("sources"))
            result.append(
                CapabilityImplementationDescriptor(
                    id=f"mcp:{server_id}",
                    capability="mcp",
                    name=_safe_text(row.get("name") or server_id, 220),
                    status=status,
                    selectable=status in {"available", "configured"},
                    selected=False,
                    enabled=row.get("enabled") is True,
                    source_type="mcp",
                    transport=_safe_text(row.get("transport"), 48) or "runtime",
                    trust="managed" if "managed-config" in sources else "observed",
                    lifecycle="runtime",
                    processing_location="unknown",
                    permissions=("mcp.tool-call",),
                    description="MCP 服务器目录项；启用和工具调用仍受当前 Preset 与审批策略限制。",
                    metadata={
                        "server_id": server_id,
                        "source": _safe_text(row.get("source"), 160),
                        "freshness": _safe_text(row.get("freshness"), 48),
                        "tool_count": _bounded_int(row.get("tool_count"), 0, 512),
                        "preset_ids": list(sources)[:32],
                    },
                )
            )
        if result:
            return result
        runtime_id = _safe_text(getattr(self.agent, "runtime_id", None), 100) or "agent"
        raw_status = _safe_text(value.get("status"), 48).lower() or "unknown"
        status = raw_status if raw_status in VALID_CAPABILITY_STATUSES else "unknown"
        return [
            CapabilityImplementationDescriptor(
                id=f"mcp:{runtime_id}:catalog",
                capability="mcp",
                name="MCP 目录",
                status=status,
                selectable=False,
                selected=False,
                enabled=False,
                source_type="mcp",
                transport="runtime",
                trust="managed",
                lifecycle="runtime",
                processing_location="local",
                permissions=("mcp.tool-call",),
                description=_safe_text(value.get("reason"), 600) or "当前 Runtime 没有可观察的 MCP 服务器。",
                metadata={
                    "catalog_available": value.get("catalog_available") is True,
                    "client_installed": value.get("client_installed") is True,
                    "client_version": _safe_text(value.get("client_version"), 80),
                    "server_count": _bounded_int(value.get("server_count"), 0, 512),
                    "tool_count": _bounded_int(value.get("tool_count"), 0, 4096),
                },
            )
        ]

    @staticmethod
    def _groups(entries: Iterable[CapabilityImplementationDescriptor]) -> list[dict[str, Any]]:
        grouped: dict[str, list[CapabilityImplementationDescriptor]] = {}
        for entry in entries:
            grouped.setdefault(entry.capability, []).append(entry)
        order = {value: index for index, value in enumerate(_CAPABILITY_ORDER)}
        result: list[dict[str, Any]] = []
        for capability in sorted(grouped, key=lambda value: (order.get(value, len(order)), value)):
            values = sorted(
                grouped[capability],
                key=lambda item: (not item.selected, not item.ready, item.name.casefold(), item.id),
            )
            result.append(
                {
                    "id": capability,
                    "name": _CAPABILITY_LABELS.get(capability, capability),
                    "entry_count": len(values),
                    "entries": [item.to_dict() for item in values],
                }
            )
        return result


def _canonical_capability(value: Any) -> str:
    candidate = _safe_text(value, 80).lower()
    return "tools" if candidate == "tool" else candidate or "unknown"


def _safe_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        text = text[:limit]
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    return text


def _safe_tuple(value: Any, *, limit: int = 32) -> tuple[str, ...]:
    if value is None:
        return ()
    values = [value] if isinstance(value, str) else value if isinstance(value, (list, tuple, set, frozenset)) else []
    result: list[str] = []
    for item in list(values)[:limit]:
        text = _safe_text(item, 120)
        if text and not _looks_like_sensitive_value(text) and text not in result:
            result.append(text)
    return tuple(result)


def _safe_metadata(value: Any, *, depth: int = 3) -> dict[str, Any]:
    if not isinstance(value, dict) or depth <= 0:
        return {}
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:64]:
        name = _safe_text(key, 80).lower()
        if not name or any(token in name for token in (*_SENSITIVE_KEY_TOKENS, "path", "file", "directory")):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and _looks_like_sensitive_value(item):
                continue
            result[name] = item
        elif isinstance(item, list):
            result[name] = [
                _safe_text(entry, 160) if isinstance(entry, str) and not _looks_like_sensitive_value(entry) else entry
                for entry in item[:32]
                if (isinstance(entry, str) and not _looks_like_sensitive_value(entry))
                or isinstance(entry, (int, float, bool))
                or entry is None
            ]
        elif isinstance(item, dict):
            result[name] = _safe_metadata(item, depth=depth - 1)
    return result


def _contains_blocked_name(*values: Any) -> bool:
    text = " ".join(_safe_text(value, 300).lower() for value in values if value is not None)
    return any(token in text for token in _BLOCKED_NAME_TOKENS)


def _looks_like_sensitive_value(value: str) -> bool:
    """Reject path-like and credential-shaped strings at the projection edge."""

    text = str(value or "").strip()
    if not text:
        return False
    if _PATH_VALUE_RE.match(text):
        return True
    lowered = text.lower()
    if lowered.startswith(("bearer ", "basic ", "sk-", "ghp_", "github_pat_", "jwt ")):
        return True
    if "=" in text and any(token in lowered for token in _SENSITIVE_KEY_TOKENS):
        return True
    return False


def _stable_id(prefix: str, value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("-", _safe_text(value, 280)).strip("-") or "unknown"
    return f"{prefix}:{cleaned[:220]}"


def _model_status(auth: str, quota: str, health: str, model_id: str) -> str:
    if model_id == "unconfigured":
        return "draft"
    if auth in {"needs-auth", "blocked"}:
        return "needs-auth" if auth == "needs-auth" else "unavailable"
    if quota in {"exhausted", "expired", "blocked", "needs-auth"}:
        return quota if quota in VALID_CAPABILITY_STATUSES else "unavailable"
    if health in {"healthy", "ready", "available"}:
        return "available"
    if health in VALID_CAPABILITY_STATUSES:
        return health
    return "unknown"


def _module_status(raw: Any, selected: bool, enabled: bool) -> str:
    status = _safe_text(raw, 48).lower() or "unknown"
    if not enabled and selected:
        return "disabled"
    if status in VALID_CAPABILITY_STATUSES:
        return status
    return "unknown"


def _processing_location(capability: str, config: Mapping[str, Any]) -> str:
    explicit = _safe_text(config.get("processing_location"), 40).lower()
    if explicit in {"local", "cloud", "mixed", "unknown"}:
        return explicit
    if capability in {"memory", "avatar", "tools"}:
        return "local"
    return "unknown"


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def _deduplicate_entries(entries: Iterable[CapabilityImplementationDescriptor]) -> list[CapabilityImplementationDescriptor]:
    result: dict[str, CapabilityImplementationDescriptor] = {}
    for entry in entries:
        # A plugin can be visible both through ModuleCatalog and PluginCatalog;
        # keep the richer plugin descriptor when both IDs refer to one source.
        existing = result.get(entry.id)
        if existing is None or (entry.source_type == "plugin" and existing.source_type != "plugin"):
            result[entry.id] = entry
    return sorted(result.values(), key=lambda item: (_CAPABILITY_ORDER.index(item.capability) if item.capability in _CAPABILITY_ORDER else 999, item.name.casefold(), item.id))


__all__ = [
    "CAPABILITY_CATALOG_VERSION",
    "CapabilityCatalog",
    "CapabilityCatalogError",
    "CapabilityImplementationDescriptor",
    "VALID_CAPABILITY_STATUSES",
]
