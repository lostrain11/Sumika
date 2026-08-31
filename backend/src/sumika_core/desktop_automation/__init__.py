"""Controlled desktop software automation for explicitly approved apps.

The package is intentionally runtime-neutral.  Importing it does not install
optional UI Automation/CDP dependencies or start an external application.
"""

from .adapters import (
    ElectronCdpClient,
    MemoryDesktopAdapter,
    TransportDesktopAdapter,
    WindowsUiAutomationClient,
    ZCodeDesktopAdapter,
)
from .cdp import StdlibCdpRunner
from .audit import AUDIT_SCHEMA_VERSION, DesktopAuditSink
from .contracts import (
    DESKTOP_ACTION_SCHEMA,
    DESKTOP_AUTOMATION_SCHEMA,
    DesktopActionRequest,
    DesktopActionResult,
    DesktopAdapter,
    DesktopApplication,
    DesktopAutomationError,
    DesktopLeaseError,
    DesktopPermissionError,
    DesktopRegistrationError,
    DesktopSession,
    action_risk,
    hash_value,
    safe_identifier,
    safe_text,
)
from .runtime import DesktopAutomationRuntime

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "DESKTOP_ACTION_SCHEMA",
    "DESKTOP_AUTOMATION_SCHEMA",
    "DesktopActionRequest",
    "DesktopActionResult",
    "DesktopAdapter",
    "DesktopApplication",
    "DesktopAuditSink",
    "DesktopAutomationError",
    "DesktopAutomationRuntime",
    "DesktopLeaseError",
    "DesktopPermissionError",
    "DesktopRegistrationError",
    "DesktopSession",
    "ElectronCdpClient",
    "MemoryDesktopAdapter",
    "StdlibCdpRunner",
    "TransportDesktopAdapter",
    "WindowsUiAutomationClient",
    "ZCodeDesktopAdapter",
    "action_risk",
    "hash_value",
    "safe_identifier",
    "safe_text",
]
