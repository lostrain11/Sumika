"""Runtime-neutral worker adapters.

The implementations live in :mod:`sumika_core.agent.supervisor` so there is
one lifecycle implementation.  This module is a small discoverable import
surface for future Harness adapters and community plugins.
"""

from .supervisor import (
    ChildAgentWorker,
    DesktopAppWorker,
    ExternalHarnessWorker,
    NativeChildAgentWorker,
    ProviderWorker,
    WebWorker,
    WorkerAdapter,
    WorkerExecutor,
    WorkerRegistry,
)
from .runtime_workers import (
    LegacyWebWorker,
    NativeRuntimeWorker,
    ProviderProfileWorker,
    ZCodeExternalHarnessWorker,
)

__all__ = [
    "WorkerExecutor",
    "WorkerAdapter",
    "ProviderWorker",
    "WebWorker",
    "ChildAgentWorker",
    "NativeChildAgentWorker",
    "ExternalHarnessWorker",
    "DesktopAppWorker",
    "WorkerRegistry",
    "ProviderProfileWorker",
    "LegacyWebWorker",
    "NativeRuntimeWorker",
    "ZCodeExternalHarnessWorker",
]
