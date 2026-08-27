"""Compatibility imports for the pre-registry Agent runtime module."""

from .adapters.dsh.runtime import DSHAgentRuntime
from .contracts import AgentCapability, AgentRuntime, AgentRuntimeError, UnavailableAgentRuntime

__all__ = [
    "AgentCapability",
    "AgentRuntime",
    "AgentRuntimeError",
    "DSHAgentRuntime",
    "UnavailableAgentRuntime",
]
