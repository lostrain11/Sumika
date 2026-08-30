"""Runtime-neutral contracts for Sumika Agent harness adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar

from ..protocol.models import utc_now


class AgentRuntimeError(RuntimeError):
    """A controlled Agent runtime failure safe to translate at the RPC boundary."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        transport: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.transport = transport


class AgentCapability(str, Enum):
    """Optional features that a harness adapter may implement."""

    DIAGNOSTICS = "diagnostics"
    SESSION_SEARCH = "session-search"
    SESSION_RENAME = "session-rename"
    PRESETS = "presets"
    MODELS = "models"
    SESSION_FORK = "session-fork"
    RAW_EXPORT = "raw-export"
    WORKSPACES = "workspaces"
    PROVIDER_BRIDGE = "provider-bridge"
    HISTORY = "history"
    ATTACHMENTS = "attachments"
    QUEUE = "queue"
    SUBAGENTS = "subagents"
    GOALS = "goals"
    PLAN = "plan"
    READONLY = "readonly"
    COMMANDS = "commands"
    SKILLS = "skills"
    MCP = "mcp"
    MCP_CONFIGURATION = "mcp-configuration"
    INTERACTIONS = "interactions"
    EVENT_INGEST = "event-ingest"
    RETRY = "retry"


class AgentRuntime(ABC):
    """Small stable session core implemented by every harness adapter.

    Features outside this core are optional capabilities. Their default
    methods fail explicitly so an adapter never has to emulate another
    harness just to satisfy Sumika's interface.
    """

    runtime_id: ClassVar[str] = "unknown"
    capability_ids: ClassVar[frozenset[AgentCapability]] = frozenset()

    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def retry_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retry the latest failed user target without exposing its body."""

        del params
        self._unsupported(AgentCapability.RETRY, "retrying the latest failed prompt")

    def supports(self, capability: AgentCapability | str) -> bool:
        try:
            value = capability if isinstance(capability, AgentCapability) else AgentCapability(capability)
        except ValueError:
            return False
        return value in self.capability_ids

    def runtime_capabilities(self) -> list[str]:
        return sorted(item.value for item in self.capability_ids)

    def _unsupported(self, capability: AgentCapability, operation: str) -> None:
        raise AgentRuntimeError(
            f"Agent runtime '{self.runtime_id}' does not support {operation} "
            f"(capability: {capability.value})"
        )

    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.DIAGNOSTICS, "diagnostics")

    def search_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SESSION_SEARCH, "session search")

    def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SESSION_RENAME, "session rename")

    def list_presets(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.PRESETS, "preset listing")

    def copy_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.PRESETS, "preset copy")

    def open_preset_document(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.PRESETS, "preset document open")

    def remove_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.PRESETS, "preset removal")

    def validate_preset_mount(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.PRESETS, "preset mount validation")

    def select_preset(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.PRESETS, "preset selection")

    def session_models(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.MODELS, "model listing")

    def runtime_models(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return an optional model directory that does not need a Session.

        Most Harnesses expose models only after a Session is created.  An
        adapter may override this read-only hook when its public protocol has
        a global model directory, allowing policy preflight to happen before
        a confirmation-gated Session creation.
        """

        del params
        self._unsupported(AgentCapability.MODELS, "runtime model listing")

    def select_model(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.MODELS, "model selection")

    def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SESSION_FORK, "session fork")

    def open_session_export(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.RAW_EXPORT, "session export")

    def list_workspaces(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.WORKSPACES, "workspace listing")

    def create_workspace(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.WORKSPACES, "workspace creation")

    def sync_provider_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        del profile
        self._unsupported(AgentCapability.PROVIDER_BRIDGE, "provider synchronization")

    def provider_status(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        del profile
        self._unsupported(AgentCapability.PROVIDER_BRIDGE, "provider status")

    def quota_status(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a conservative runtime quota projection.

        Harnesses are not required to expose billing information.  Adapters
        must override this only when the public protocol provides a stable,
        read-only usage method; the default deliberately remains unknown.
        """

        del params
        return {
            "state": "unknown",
            "source": f"{self.runtime_id}-quota-not-exposed",
            "detail": "Agent runtime does not expose a verifiable quota endpoint",
        }

    def history(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.HISTORY, "raw history")

    def attachment(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.ATTACHMENTS, "attachments")

    def queue(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.QUEUE, "queue inspection")

    def update_queue(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.QUEUE, "queue mutation")

    def list_subagents(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SUBAGENTS, "subagent listing")

    def subagent_history(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SUBAGENTS, "subagent history")

    def prompt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SUBAGENTS, "subagent prompt")

    def interrupt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.SUBAGENTS, "subagent interrupt")

    def goal_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        del action, params
        self._unsupported(AgentCapability.GOALS, "goal mutation")

    def list_capabilities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        return {
            "skills": {"available": False},
            "mcp": {"available": False},
            "subagents": {"available": False},
            "commands": {"available": False},
        }

    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        return {
            "available": False,
            "status": "unsupported",
            "catalog_available": False,
            "observation_source": None,
            "client_installed": False,
            "client_version": None,
            "entries": [],
            "server_count": 0,
            "tool_count": 0,
            "reason": f"Agent runtime '{self.runtime_id}' does not support MCP",
        }

    def mcp_catalog(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a runtime-neutral MCP catalog projection.

        Older adapters may only know how to report observed tools.  Returning
        that bounded inventory here keeps the new catalog RPC portable while
        allowing capable adapters to add live and configured sources.
        """

        return self.mcp_inventory(params)

    def list_mcp_configurations(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.MCP_CONFIGURATION, "managed MCP configuration listing")

    def preview_mcp_configuration(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.MCP_CONFIGURATION, "managed MCP configuration preview")

    def apply_mcp_configuration(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.MCP_CONFIGURATION, "managed MCP configuration apply")

    def respond(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.INTERACTIONS, "runtime response")

    def interactions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        return {"interactions": [], "available": False}

    def respond_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.INTERACTIONS, "interaction response")

    def cancel_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._unsupported(AgentCapability.INTERACTIONS, "interaction cancellation")

    def normalize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        self._unsupported(AgentCapability.EVENT_INGEST, "event ingestion")

    def set_event_sink(self, sink: Any) -> None:
        del sink

    def bind_credential_store(self, credential_store: Any) -> None:
        del credential_store

    def close(self) -> None:
        return None


class UnavailableAgentRuntime(AgentRuntime):
    """Fail-closed slot used when no configured harness is available."""

    runtime_id = "unavailable"

    def __init__(self, reason: str = "Agent runtime is not connected") -> None:
        self.reason = reason

    def status(self) -> dict[str, Any]:
        return {"state": "unavailable", "ready": False, "reason": self.reason}

    def health(self) -> dict[str, Any]:
        return {"ok": False, "state": "unavailable", "error": self.reason}

    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        return {
            "checked_at": utc_now(),
            "runtime": {"state": "unavailable", "ready": False},
            "capabilities": [],
            "mcp": {
                "available": False,
                "status": "unavailable",
                "endpoint": "mcp.list",
                "client_installed": False,
                "reason": self.reason,
            },
            "summary": {"available": 0, "unavailable": 1},
        }

    def _fail(self) -> None:
        raise AgentRuntimeError(self.reason)

    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._fail()

    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        self._fail()

    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._fail()

    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._fail()

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self._fail()

    def _unsupported(self, capability: AgentCapability, operation: str) -> None:
        del capability, operation
        self._fail()

    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        value = super().mcp_inventory()
        value.update({"status": "unavailable", "reason": self.reason})
        return value
