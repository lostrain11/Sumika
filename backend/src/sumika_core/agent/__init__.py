"""Portable Agent contracts with lazy compatibility exports for DSH."""

from typing import TYPE_CHECKING, Any

from .contracts import AgentCapability, AgentRuntime, AgentRuntimeError, UnavailableAgentRuntime
from .models import AgentApproval, AgentEvent
from .registry import AgentRuntimeRegistry, create_agent_runtime
from .skill_catalog import SkillCatalog, SkillCatalogError

if TYPE_CHECKING:
    from .adapters.dsh.config import DSHRuntimeConfig
    from .adapters.dsh.runtime import DSHAgentRuntime


def __getattr__(name: str) -> Any:
    if name == "DSHRuntimeConfig":
        from .adapters.dsh.config import DSHRuntimeConfig

        return DSHRuntimeConfig
    if name == "DSHAgentRuntime":
        from .adapters.dsh.runtime import DSHAgentRuntime

        return DSHAgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AgentApproval",
    "AgentCapability",
    "AgentEvent",
    "AgentRuntime",
    "AgentRuntimeError",
    "AgentRuntimeRegistry",
    "SkillCatalog",
    "SkillCatalogError",
    "DSHAgentRuntime",
    "DSHRuntimeConfig",
    "UnavailableAgentRuntime",
    "create_agent_runtime",
]
