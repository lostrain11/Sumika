"""Portable Agent contracts with lazy compatibility exports for DSH."""

from typing import TYPE_CHECKING, Any

from .contracts import AgentCapability, AgentRuntime, AgentRuntimeError, UnavailableAgentRuntime
from .models import AgentApproval, AgentEvent
from .registry import AgentRuntimeRegistry, create_agent_runtime
from .skill_catalog import SkillCatalog, SkillCatalogError
from .routes import (
    AGENT_CONSULTATION_SCHEMA,
    AGENT_ROUTE_SCHEMA,
    ConsultationMemberResult,
    ConsultationRequest,
    ConsultationResult,
    RouteCoordinator,
    RouteDescriptor,
    RouteError,
    RouteValidationError,
    SubtaskDispatch,
    SubtaskResult,
    WebRouteCoordinator,
)

if TYPE_CHECKING:
    from .adapters.dsh.config import DSHRuntimeConfig
    from .adapters.dsh.runtime import DSHAgentRuntime
    from .adapters.zcode.config import ZCodeRuntimeConfig
    from .adapters.zcode.runtime import ZCodeAgentRuntime


def __getattr__(name: str) -> Any:
    if name == "DSHRuntimeConfig":
        from .adapters.dsh.config import DSHRuntimeConfig

        return DSHRuntimeConfig
    if name == "DSHAgentRuntime":
        from .adapters.dsh.runtime import DSHAgentRuntime

        return DSHAgentRuntime
    if name == "ZCodeRuntimeConfig":
        from .adapters.zcode.config import ZCodeRuntimeConfig

        return ZCodeRuntimeConfig
    if name == "ZCodeAgentRuntime":
        from .adapters.zcode.runtime import ZCodeAgentRuntime

        return ZCodeAgentRuntime
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
    "ZCodeAgentRuntime",
    "ZCodeRuntimeConfig",
    "UnavailableAgentRuntime",
    "AGENT_ROUTE_SCHEMA",
    "AGENT_CONSULTATION_SCHEMA",
    "ConsultationMemberResult",
    "ConsultationRequest",
    "ConsultationResult",
    "RouteCoordinator",
    "WebRouteCoordinator",
    "RouteDescriptor",
    "RouteError",
    "RouteValidationError",
    "SubtaskDispatch",
    "SubtaskResult",
    "create_agent_runtime",
]
