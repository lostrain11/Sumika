"""DeepSeek Harness adapter configuration and construction."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...contracts import AgentRuntime
from .config import DSHRuntimeConfig


def create_runtime(
    data_dir: str | Path | None,
    env: Mapping[str, str],
    logger: Any = None,
) -> AgentRuntime:
    # Import lazily so selecting another harness never loads DSH transport code.
    from .runtime import DSHAgentRuntime

    return DSHAgentRuntime(data_dir, env=dict(env), logger=logger)


__all__ = ["DSHRuntimeConfig", "create_runtime"]
