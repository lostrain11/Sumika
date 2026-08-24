"""Deterministic provider doubles used by unit and contract tests only."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any

from sumika_core.protocol.models import ChatRequest, ProviderInfo
from sumika_core.providers.audio import ASRProvider, ASRRequest, TTSProvider, TTSRequest, TTSResult, VADProvider, VADRequest
from sumika_core.providers.base import LLMProvider
from sumika_core.providers.memory import MemoryProvider
from sumika_core.providers.vision import VisionProvider, VisionRequest, VisionResult


class FakeProvider(LLMProvider):
    def __init__(self, response: str = "test response") -> None:
        self.response = response
        self.info = ProviderInfo(
            id="fake",
            name="Test fixture LLM",
            capability="llm",
            status="available",
            description="Test-only deterministic provider.",
        )

    def stream(self, request: ChatRequest):
        yield self.response


class FakeASRProvider(ASRProvider):
    def __init__(self, transcript: str = "test transcript") -> None:
        self.transcript = transcript
        self.info = ProviderInfo(
            id="fake-asr", name="Test fixture ASR", capability="asr", status="available"
        )

    def transcribe(self, request: ASRRequest) -> str:
        return self.transcript


class FakeTTSProvider(TTSProvider):
    def __init__(self, prefix: str = "test-tts:") -> None:
        self.prefix = prefix
        self.info = ProviderInfo(
            id="fake-tts", name="Test fixture TTS", capability="tts", status="available"
        )

    def synthesize(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio=f"{self.prefix}{request.text}".encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            sample_rate=request.sample_rate,
        )


class FakeVADProvider(VADProvider):
    def __init__(self, minimum_bytes: int = 1) -> None:
        self.minimum_bytes = minimum_bytes
        self.info = ProviderInfo(
            id="fake-vad", name="Test fixture VAD", capability="vad", status="available"
        )

    def detect(self, request: VADRequest) -> bool:
        return len(request.audio) >= self.minimum_bytes


class FakeMemoryProvider(MemoryProvider):
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = RLock()
        self.info = ProviderInfo(
            id="fake-memory", name="Test fixture memory", capability="memory", status="available"
        )

    def list_memories(self, character_id: str, *, category: str | None = None, query: str | None = None, limit: int = 100):
        query_lower = query.lower() if query else None
        with self._lock:
            records = [
                dict(record)
                for record in self._records.values()
                if record["character_id"] == character_id
                and (category is None or record["category"] == category)
                and (query_lower is None or query_lower in record["content"].lower())
            ]
        records.sort(key=lambda record: (record["updated_at"], record["created_at"]), reverse=True)
        return records[: max(1, min(limit, 500))]

    def add_memory(self, *, memory_id: str, character_id: str, category: str, content: str, source: str, metadata: dict[str, Any]):
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": memory_id,
            "character_id": character_id,
            "category": category,
            "content": content,
            "source": source,
            "metadata": dict(metadata),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._records[memory_id] = record
        return dict(record)

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            return self._records.pop(memory_id, None) is not None


class FakeVisionProvider(VisionProvider):
    def __init__(self, summary: str = "test summary") -> None:
        self.summary = summary
        self.info = ProviderInfo(
            id="fake-vision", name="Test fixture vision", capability="vision", status="available"
        )

    def summarize(self, request: VisionRequest) -> VisionResult:
        return VisionResult(self.summary)
