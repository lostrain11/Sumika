"""Adapters for approved manifest-based provider plugins.

Third-party code stays outside the core process.  The catalog revalidates the
manifest, entrypoint and launcher immediately before every request, then the
capability adapter speaks its JSONL contract over a one-shot non-shell process.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .audio import ASRProvider, ASRRequest, TTSProvider, TTSRequest, TTSResult, VADProvider, VADRequest
from .memory import MemoryProvider
from .vision import VisionProvider, VisionRequest, VisionResult
from ..protocol.models import ChatRequest, ProviderInfo
from .base import LLMProvider

if TYPE_CHECKING:
    from ..plugins.catalog import PluginCatalog


class _PluginProcessProvider:
    """Shared lifecycle and process boundary for manifest provider adapters."""

    def _init_plugin(self, catalog: PluginCatalog, candidate_id: str, capability: str) -> None:
        self.catalog = catalog
        self.candidate_id = candidate_id
        self.capability = capability
        self._config: dict[str, Any] = {}
        candidate = catalog.get_registration(candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown plugin candidate: {candidate_id}")
        manifest = candidate.get("manifest") if isinstance(candidate.get("manifest"), dict) else {}
        self.plugin_id = str(candidate.get("plugin_id") or manifest.get("id") or candidate_id)
        schema = manifest.get("config_schema", {})
        self.info = ProviderInfo(
            id=f"plugin:{candidate_id}",
            name=f"Plugin · {self.plugin_id}",
            capability=capability,
            description=f"Approved external JSONL {capability.upper()} plugin.",
            config_schema=schema if isinstance(schema, dict) else {},
            status="unconfigured",
        )
        self.refresh()

    def refresh(self) -> None:
        """Refresh display status without starting the plugin process."""

        candidate = self.catalog.get_registration(self.candidate_id)
        if candidate is None:
            self.info.status = "unconfigured"
            return
        manifest = candidate.get("manifest") if isinstance(candidate.get("manifest"), dict) else {}
        schema = manifest.get("config_schema", {})
        if isinstance(schema, dict):
            self.info.config_schema = schema
        launcher = candidate.get("launcher")
        executable = launcher.get("executable") if isinstance(launcher, dict) else None
        self.info.status = (
            "available"
            if candidate.get("state") == "approved"
            and isinstance(launcher, dict)
            and bool(launcher)
            and isinstance(executable, str)
            and Path(executable).is_file()
            else "unconfigured"
        )

    def health_check(self) -> dict[str, Any]:
        self.refresh()
        try:
            self.catalog.prepare_provider_run(self.candidate_id, self.capability)
        except Exception as exc:
            return {
                "ok": False,
                "provider_id": self.info.id,
                "plugin_id": self.plugin_id,
                "error": str(exc),
            }
        return {"ok": True, "provider_id": self.info.id, "plugin_id": self.plugin_id}

    def configure(self, config: dict[str, Any]) -> None:
        self._config = dict(config)

    def close(self) -> None:
        return None

    def _run_jsonl(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        prepared = self.catalog.prepare_provider_run(self.candidate_id, self.capability)
        launcher = prepared["launcher"]
        process = subprocess.Popen(
            [launcher["executable"], *launcher["arguments"]],
            cwd=launcher.get("working_directory") or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            try:
                stdout, stderr = process.communicate(
                    json.dumps({**payload, "config": self._config}, ensure_ascii=False) + "\n",
                    timeout=float(launcher["timeout_seconds"]),
                )
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise TimeoutError(f"Plugin {self.capability} provider timed out") from exc
            if process.returncode != 0:
                raise RuntimeError(f"Plugin {self.capability} provider exited with {process.returncode}: {stderr[:500]}")
            responses: list[dict[str, Any]] = []
            for line in stdout.splitlines():
                parsed = _parse_line(line)
                if parsed is not None:
                    responses.append(parsed)
            return responses
        finally:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass

    def _stream_jsonl(self, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        prepared = self.catalog.prepare_provider_run(self.candidate_id, self.capability)
        launcher = prepared["launcher"]
        process = subprocess.Popen(
            [launcher["executable"], *launcher["arguments"]],
            cwd=launcher.get("working_directory") or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps({**payload, "config": self._config}, ensure_ascii=False) + "\n")
            process.stdin.close()
            for line in process.stdout:
                parsed = _parse_line(line)
                if parsed is not None:
                    yield parsed
            try:
                code = process.wait(timeout=float(launcher["timeout_seconds"]))
            except subprocess.TimeoutExpired as exc:
                process.kill()
                raise TimeoutError(f"Plugin {self.capability} provider timed out") from exc
            if code != 0:
                error = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"Plugin {self.capability} provider exited with {code}: {error[:500]}")
        finally:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


class PluginLLMProvider(_PluginProcessProvider, LLMProvider):
    """Run one approved ``llm`` plugin candidate through its launcher."""

    def __init__(self, catalog: PluginCatalog, candidate_id: str) -> None:
        self._init_plugin(catalog, candidate_id, "llm")

    def stream(self, request: ChatRequest) -> Iterable[str]:
        events = self._stream_jsonl(_request_payload(request))
        try:
            for response in events:
                event_type = response.get("type")
                if event_type == "done":
                    break
                if event_type == "error":
                    raise RuntimeError(str(response.get("message", "plugin provider error")))
                text = response.get("text")
                if isinstance(text, str):
                    yield text
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()


class PluginASRProvider(_PluginProcessProvider, ASRProvider):
    def __init__(self, catalog: PluginCatalog, candidate_id: str) -> None:
        self._init_plugin(catalog, candidate_id, "asr")

    def transcribe(self, request: ASRRequest) -> str:
        import base64

        pieces: list[str] = []
        for response in self._run_jsonl(
            {
                "type": "asr",
                "audio_base64": base64.b64encode(request.audio).decode("ascii"),
                "sample_rate": request.sample_rate,
                "channels": request.channels,
                "language": request.language,
            }
        ):
            _raise_plugin_error(response, "ASR")
            if response.get("type") == "done":
                break
            text = response.get("text")
            if isinstance(text, str):
                pieces.append(text)
        return "".join(pieces)


class PluginTTSProvider(_PluginProcessProvider, TTSProvider):
    def __init__(self, catalog: PluginCatalog, candidate_id: str) -> None:
        self._init_plugin(catalog, candidate_id, "tts")

    def synthesize(self, request: TTSRequest) -> TTSResult:
        import base64

        for response in self._run_jsonl(
            {
                "type": "tts",
                "text": request.text,
                "voice": request.voice,
                "language": request.language,
                "sample_rate": request.sample_rate,
            }
        ):
            _raise_plugin_error(response, "TTS")
            if response.get("type") not in {"audio", "result"} or not isinstance(response.get("audio_base64"), str):
                continue
            try:
                audio = base64.b64decode(response["audio_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("Plugin TTS returned invalid audio_base64") from exc
            return TTSResult(
                audio=audio,
                content_type=str(response.get("content_type") or "application/octet-stream"),
                sample_rate=_optional_int(response.get("sample_rate"), request.sample_rate),
            )
        raise RuntimeError("Plugin TTS returned no audio")


class PluginVADProvider(_PluginProcessProvider, VADProvider):
    def __init__(self, catalog: PluginCatalog, candidate_id: str) -> None:
        self._init_plugin(catalog, candidate_id, "vad")

    def detect(self, request: VADRequest) -> bool:
        import base64

        for response in self._run_jsonl(
            {
                "type": "vad",
                "audio_base64": base64.b64encode(request.audio).decode("ascii"),
                "sample_rate": request.sample_rate,
                "channels": request.channels,
            }
        ):
            _raise_plugin_error(response, "VAD")
            if response.get("type") in {"speech", "result"}:
                value = response.get("speech", response.get("is_speech"))
                if isinstance(value, bool):
                    return value
        raise RuntimeError("Plugin VAD returned no speech result")


class PluginMemoryProvider(_PluginProcessProvider, MemoryProvider):
    def __init__(self, catalog: PluginCatalog, candidate_id: str) -> None:
        self._init_plugin(catalog, candidate_id, "memory")

    def list_memories(
        self,
        character_id: str,
        *,
        category: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        for response in self._run_jsonl(
            {"type": "memory.list", "character_id": character_id, "category": category, "query": query, "limit": limit}
        ):
            _raise_plugin_error(response, "memory")
            if isinstance(response.get("items"), list):
                return [item for item in response["items"] if isinstance(item, dict)]
            if isinstance(response.get("memory"), dict):
                return [response["memory"]]
        return []

    def add_memory(
        self,
        *,
        memory_id: str,
        character_id: str,
        category: str,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        for response in self._run_jsonl(
            {
                "type": "memory.add",
                "memory": {
                    "id": memory_id,
                    "character_id": character_id,
                    "category": category,
                    "content": content,
                    "source": source,
                    "metadata": metadata,
                },
            }
        ):
            _raise_plugin_error(response, "memory")
            if isinstance(response.get("memory"), dict):
                return response["memory"]
        raise RuntimeError("Plugin memory provider returned no memory")

    def delete_memory(self, memory_id: str) -> bool:
        for response in self._run_jsonl({"type": "memory.delete", "memory_id": memory_id}):
            _raise_plugin_error(response, "memory")
            if isinstance(response.get("deleted"), bool):
                return response["deleted"]
        return False


class PluginVisionProvider(_PluginProcessProvider, VisionProvider):
    def __init__(self, catalog: PluginCatalog, candidate_id: str) -> None:
        self._init_plugin(catalog, candidate_id, "vision")

    def summarize(self, request: VisionRequest) -> VisionResult:
        import base64

        for response in self._run_jsonl(
            {
                "type": "vision.observe",
                "source": request.source,
                "mime_type": request.mime_type,
                "image_base64": base64.b64encode(request.image).decode("ascii"),
                "prompt": request.prompt,
            }
        ):
            _raise_plugin_error(response, "vision")
            if response.get("type") in {"result", "summary"} and isinstance(response.get("summary"), str):
                return VisionResult(response["summary"])
        raise RuntimeError("Plugin vision provider returned no summary")


def _request_payload(request: ChatRequest) -> dict[str, Any]:
    return {
        "type": "chat",
        "session_id": request.session_id,
        "character_id": request.character_id,
        "messages": [message.to_dict() for message in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }


def _parse_line(line: str) -> dict[str, Any] | None:
    value = line.strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"type": "text", "text": value}
    return parsed if isinstance(parsed, dict) else {"type": "text", "text": str(parsed)}


def _raise_plugin_error(response: dict[str, Any], capability: str) -> None:
    if response.get("type") == "error":
        raise RuntimeError(str(response.get("message", f"plugin {capability} error")))


def _optional_int(value: Any, fallback: int | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


__all__ = [
    "PluginASRProvider",
    "PluginLLMProvider",
    "PluginMemoryProvider",
    "PluginTTSProvider",
    "PluginVADProvider",
    "PluginVisionProvider",
]
