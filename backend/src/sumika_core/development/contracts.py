from __future__ import annotations

from typing import Callable, Protocol


LEGACY_EXECUTOR_ID = "api-source-copy/v1"


class DevelopmentExecutor(Protocol):
    executor_id: str

    def preflight(self, directory: str, options: dict) -> dict: ...

    def inspect(self, spec: dict, prepared: dict) -> dict: ...

    def run(self, goal: str, *, spec: dict, skills: list, invoke: Callable, helper: Callable,
            cancelled: Callable, prepared: Callable, journal: Callable, event: Callable) -> dict: ...
