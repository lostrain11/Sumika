"""Permission-gated long-term memory runtime and portable contracts."""

from .contracts import MEMORY_CONTRACT_VERSION, MemoryContractError, MemoryScope

__all__ = [
    "MEMORY_CONTRACT_VERSION",
    "MemoryContractError",
    "MemoryRuntime",
    "MemoryRuntimeError",
    "MemoryScope",
]


def __getattr__(name: str):
    if name in {"MemoryRuntime", "MemoryRuntimeError"}:
        from .runtime import MemoryRuntime, MemoryRuntimeError

        return {"MemoryRuntime": MemoryRuntime, "MemoryRuntimeError": MemoryRuntimeError}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
