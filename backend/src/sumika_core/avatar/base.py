"""Renderer-neutral Avatar contract.

The conversation core emits AvatarCommand events. A future Cubism or VRM
adapter translates those commands into renderer-specific calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class AvatarState:
    model_id: str | None = None
    expression: str = "neutral"
    motion: str | None = None
    viseme: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AvatarDriver(Protocol):
    id: str

    def load_model(self, model_path: str) -> AvatarState: ...

    def set_expression(self, expression: str) -> None: ...

    def play_motion(self, motion: str) -> None: ...

    def set_viseme(self, viseme: str) -> None: ...

    def close(self) -> None: ...


class NullAvatarDriver:
    """Safe placeholder used until a renderer is configured."""

    id = "none"

    def __init__(self) -> None:
        self.state = AvatarState()

    def load_model(self, model_path: str) -> AvatarState:
        self.state.model_id = model_path
        return self.state

    def set_expression(self, expression: str) -> None:
        self.state.expression = expression

    def play_motion(self, motion: str) -> None:
        self.state.motion = motion

    def set_viseme(self, viseme: str) -> None:
        self.state.viseme = viseme

    def close(self) -> None:
        return None


class PreviewAvatarDriver:
    """Renderer-neutral core state for a client-side Avatar adapter."""

    def __init__(self, driver_id: str) -> None:
        self.id = driver_id
        self.state = AvatarState(metadata={"status": "preview", "renderer": driver_id})

    def load_model(self, model_path: str) -> AvatarState:
        # Do not open model binaries here. A renderer adapter owns that boundary.
        self.state.model_id = model_path
        self.state.metadata["status"] = "preview"
        return self.state

    def set_expression(self, expression: str) -> None:
        self.state.expression = expression

    def play_motion(self, motion: str) -> None:
        self.state.motion = motion

    def set_viseme(self, viseme: str) -> None:
        self.state.viseme = viseme

    def close(self) -> None:
        return None
