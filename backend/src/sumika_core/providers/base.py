"""Provider protocol.

An implementation may be in-process or a thin client for a separate process.
The core only consumes a stream of text chunks and provider metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from ..protocol.models import ChatRequest, ProviderInfo


class LLMProvider(ABC):
    info: ProviderInfo

    @abstractmethod
    def stream(self, request: ChatRequest) -> Iterable[str]:
        """Yield text chunks in display order."""

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "provider_id": self.info.id}

    def configure(self, config: dict[str, Any]) -> None:
        """Apply non-persistent runtime configuration supplied by the catalog."""
        return None

    def close(self) -> None:
        return None
