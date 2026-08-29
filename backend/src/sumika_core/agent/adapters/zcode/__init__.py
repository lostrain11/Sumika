"""Explicit ZCode app-server adapter.

The adapter is intentionally optional.  Selecting ``zcode`` never changes the
default DSH runtime and never reads ZCode's credential or settings files.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...contracts import AgentRuntime
from .config import ZCodeRuntimeConfig


def create_runtime(
    data_dir: str | Path | None,
    env: Mapping[str, str],
    logger: Any = None,
) -> AgentRuntime:
    from .runtime import ZCodeAgentRuntime

    return ZCodeAgentRuntime(data_dir, env=dict(env), logger=logger)


__all__ = ["ZCodeRuntimeConfig", "create_runtime"]
