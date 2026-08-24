"""Capability-specific audio provider contracts and reference adapters.

Audio providers deliberately exchange bytes only at the runtime boundary. The
core never persists microphone input or synthesized output; an external
adapter receives one JSONL request and returns one JSONL response per call.
"""

from __future__ import annotations

import base64
import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..protocol.models import ProviderInfo


@dataclass(slots=True)
class ASRRequest:
    audio: bytes
    sample_rate: int = 16_000
    channels: int = 1
    language: str | None = None


@dataclass(slots=True)
class TTSRequest:
    text: str
    voice: str | None = None
    language: str | None = None
    sample_rate: int | None = None


@dataclass(slots=True)
class VADRequest:
    audio: bytes
    sample_rate: int = 16_000
    channels: int = 1


@dataclass(slots=True)
class TTSResult:
    audio: bytes
    content_type: str = "application/octet-stream"
    sample_rate: int | None = None


class AudioProvider(ABC):
    """Common lifecycle contract for capability-specific audio providers."""

    info: ProviderInfo

    def health_check(self) -> dict[str, Any]:
        return {"ok": self.info.status == "available", "provider_id": self.info.id, "capability": self.info.capability}

    def configure(self, config: dict[str, Any]) -> None:
        return None

    def close(self) -> None:
        return None


class ASRProvider(AudioProvider):
    @abstractmethod
    def transcribe(self, request: ASRRequest) -> str:
        """Convert one in-memory audio buffer into text."""


class TTSProvider(AudioProvider):
    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult:
        """Convert text into one in-memory audio buffer."""


class VADProvider(AudioProvider):
    @abstractmethod
    def detect(self, request: VADRequest) -> bool:
        """Return whether the supplied buffer contains speech."""


_COMMAND_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["executable"],
    "properties": {
        "executable": {"type": "string", "title": "软件路径"},
        "args": {"type": "array", "items": {"type": "string"}, "title": "启动参数", "default": []},
        "working_directory": {"type": "string", "title": "工作目录"},
        "timeout": {"type": "number", "title": "超时（秒）", "minimum": 1, "default": 30},
    },
}


class _CommandAudioProvider:
    """Shared non-shell JSONL process adapter for external audio software."""

    executable: str
    args: list[str]
    working_directory: str | None
    timeout: float

    def _init_command(
        self,
        executable: str,
        *,
        args: list[str] | None,
        working_directory: str | None,
        timeout: float,
    ) -> None:
        self.executable = executable
        self.args = list(args or [])
        self.working_directory = working_directory
        self.timeout = timeout
        self._refresh_status()

    def _refresh_status(self) -> None:
        if hasattr(self, "info"):
            self.info.status = "available" if self.executable.strip() and Path(self.executable).is_file() else "unconfigured"

    def configure(self, config: dict[str, Any]) -> None:
        executable = config.get("executable")
        args = config.get("args")
        working_directory = config.get("working_directory")
        timeout = config.get("timeout")
        if isinstance(executable, str):
            self.executable = executable.strip()
        if isinstance(args, list) and all(isinstance(item, str) for item in args):
            self.args = list(args)
        if isinstance(working_directory, str):
            self.working_directory = working_directory.strip() or None
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout >= 1:
            self.timeout = float(timeout)
        self._refresh_status()

    def _run_jsonl(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.executable.strip():
            raise RuntimeError("External audio provider is not configured")
        process = subprocess.Popen(
            [self.executable, *self.args],
            cwd=self.working_directory or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            request = json.dumps(payload, ensure_ascii=False) + "\n"
            try:
                stdout, stderr = process.communicate(request, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise TimeoutError("External audio provider timed out") from exc
            if process.returncode != 0:
                raise RuntimeError(f"External audio provider exited with {process.returncode}: {stderr[:500]}")
            result: list[dict[str, Any]] = []
            for line in stdout.splitlines():
                value = line.strip()
                if not value:
                    continue
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = {"type": "text", "text": value}
                result.append(parsed if isinstance(parsed, dict) else {"type": "text", "text": str(parsed)})
            return result
        finally:
            if process.poll() is None:
                process.kill()


class CommandASRProvider(_CommandAudioProvider, ASRProvider):
    """External ASR contract: request audio_base64, return text/result JSONL."""

    def __init__(self, executable: str = "", args: list[str] | None = None, working_directory: str | None = None, timeout: float = 30) -> None:
        self._init_command(executable, args=args, working_directory=working_directory, timeout=timeout)
        self.info = ProviderInfo(
            id="external-asr",
            name="External ASR",
            capability="asr",
            status="unconfigured",
            description="Call an explicitly configured JSONL speech-to-text program.",
            config_schema=_COMMAND_CONFIG_SCHEMA,
        )
        self._refresh_status()

    def transcribe(self, request: ASRRequest) -> str:
        responses = self._run_jsonl(
            {
                "type": "asr",
                "audio_base64": base64.b64encode(request.audio).decode("ascii"),
                "sample_rate": request.sample_rate,
                "channels": request.channels,
                "language": request.language,
            }
        )
        pieces: list[str] = []
        for response in responses:
            if response.get("type") == "error":
                raise RuntimeError(str(response.get("message", "external ASR error")))
            if response.get("type") == "done":
                break
            text = response.get("text")
            if isinstance(text, str):
                pieces.append(text)
        return "".join(pieces)


class CommandTTSProvider(_CommandAudioProvider, TTSProvider):
    """External TTS contract: request text, return audio_base64 JSONL."""

    def __init__(self, executable: str = "", args: list[str] | None = None, working_directory: str | None = None, timeout: float = 30) -> None:
        self._init_command(executable, args=args, working_directory=working_directory, timeout=timeout)
        self.info = ProviderInfo(
            id="external-tts",
            name="External TTS",
            capability="tts",
            status="unconfigured",
            description="Call an explicitly configured JSONL text-to-speech program.",
            config_schema=_COMMAND_CONFIG_SCHEMA,
        )
        self._refresh_status()

    def synthesize(self, request: TTSRequest) -> TTSResult:
        responses = self._run_jsonl(
            {
                "type": "tts",
                "text": request.text,
                "voice": request.voice,
                "language": request.language,
                "sample_rate": request.sample_rate,
            }
        )
        for response in responses:
            if response.get("type") == "error":
                raise RuntimeError(str(response.get("message", "external TTS error")))
            if response.get("type") in {"audio", "result"} and isinstance(response.get("audio_base64"), str):
                try:
                    audio = base64.b64decode(response["audio_base64"], validate=True)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError("External TTS returned invalid audio_base64") from exc
                return TTSResult(
                    audio=audio,
                    content_type=str(response.get("content_type") or "application/octet-stream"),
                    sample_rate=_optional_int(response.get("sample_rate"), request.sample_rate),
                )
        raise RuntimeError("External TTS returned no audio")


class CommandVADProvider(_CommandAudioProvider, VADProvider):
    """External VAD contract: request audio_base64, return speech JSONL."""

    def __init__(self, executable: str = "", args: list[str] | None = None, working_directory: str | None = None, timeout: float = 30) -> None:
        self._init_command(executable, args=args, working_directory=working_directory, timeout=timeout)
        self.info = ProviderInfo(
            id="external-vad",
            name="External VAD",
            capability="vad",
            status="unconfigured",
            description="Call an explicitly configured JSONL voice-activity detector.",
            config_schema=_COMMAND_CONFIG_SCHEMA,
        )
        self._refresh_status()

    def detect(self, request: VADRequest) -> bool:
        responses = self._run_jsonl(
            {
                "type": "vad",
                "audio_base64": base64.b64encode(request.audio).decode("ascii"),
                "sample_rate": request.sample_rate,
                "channels": request.channels,
            }
        )
        for response in responses:
            if response.get("type") == "error":
                raise RuntimeError(str(response.get("message", "external VAD error")))
            if response.get("type") in {"speech", "result"}:
                value = response.get("speech", response.get("is_speech"))
                if isinstance(value, bool):
                    return value
        raise RuntimeError("External VAD returned no speech result")


def _optional_int(value: Any, fallback: int | None) -> int | None:
    if value is None:
        return fallback
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


__all__ = [
    "ASRProvider",
    "ASRRequest",
    "AudioProvider",
    "CommandASRProvider",
    "CommandTTSProvider",
    "CommandVADProvider",
    "TTSProvider",
    "TTSRequest",
    "TTSResult",
    "VADProvider",
    "VADRequest",
]
