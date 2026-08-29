"""Harness runtime registration and construction."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .contracts import AgentRuntime, UnavailableAgentRuntime

AgentRuntimeBuilder = Callable[[str | Path | None, Mapping[str, str], Any], AgentRuntime]


class AgentRuntimeRegistry:
    """Small explicit registry; production entries must be real adapters."""

    def __init__(self) -> None:
        self._builders: dict[str, AgentRuntimeBuilder] = {}

    def register(self, runtime_id: str, builder: AgentRuntimeBuilder) -> None:
        normalized = runtime_id.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", normalized) or normalized in self._builders:
            raise ValueError(f"invalid or duplicate Agent runtime id: {runtime_id!r}")
        self._builders[normalized] = builder

    def available(self) -> list[str]:
        return sorted(self._builders)

    def create(
        self,
        runtime_id: str,
        data_dir: str | Path | None,
        *,
        env: Mapping[str, str],
        logger: Any = None,
    ) -> AgentRuntime:
        normalized = runtime_id.strip().lower()
        builder = self._builders.get(normalized)
        if builder is None:
            return UnavailableAgentRuntime(
                f"Agent runtime '{normalized or runtime_id}' is not registered"
            )
        return builder(data_dir, env, logger)


def default_agent_runtime_registry() -> AgentRuntimeRegistry:
    registry = AgentRuntimeRegistry()

    def build_dsh(data_dir: str | Path | None, env: Mapping[str, str], logger: Any) -> AgentRuntime:
        from .adapters.dsh import create_runtime

        return create_runtime(data_dir, env, logger)

    def build_zcode(data_dir: str | Path | None, env: Mapping[str, str], logger: Any) -> AgentRuntime:
        # Keep the optional adapter lazy so selecting DSH never imports or
        # probes the ZCode process.
        from .adapters.zcode import create_runtime

        return create_runtime(data_dir, env, logger)

    registry.register("dsh", build_dsh)
    registry.register("zcode", build_zcode)
    return registry


def create_agent_runtime(
    data_dir: str | Path | None,
    *,
    env: Mapping[str, str] | None = None,
    logger: Any = None,
    registry: AgentRuntimeRegistry | None = None,
) -> AgentRuntime:
    values = env if env is not None else os.environ
    runtime_id = str(values.get("SUMIKA_AGENT_RUNTIME", "dsh")).strip().lower()
    if runtime_id in {"", "none", "disabled"}:
        return UnavailableAgentRuntime("Agent runtime is disabled")
    return (registry or default_agent_runtime_registry()).create(
        runtime_id,
        data_dir,
        env=values,
        logger=logger,
    )
