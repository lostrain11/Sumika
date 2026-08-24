"""Vision provider contracts and local/external reference implementations.

The provider boundary receives one in-memory image observation and returns a
text summary. Providers never own capture devices, persistence, or memory
promotion. The external adapter uses one JSONL request per observation and
does not invoke a shell.
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
class VisionRequest:
    source: str
    image: bytes
    mime_type: str = "image/png"
    prompt: str | None = None


@dataclass(slots=True)
class VisionResult:
    summary: str


class VisionProvider(ABC):
    """Capability contract for one controlled visual observation."""

    info: ProviderInfo

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": self.info.status == "available",
            "provider_id": self.info.id,
            "capability": "vision",
        }

    def configure(self, config: dict[str, Any]) -> None:
        return None

    @abstractmethod
    def summarize(self, request: VisionRequest) -> VisionResult:
        """Return a summary for one in-memory image."""

    def close(self) -> None:
        return None


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


class CommandVisionProvider(VisionProvider):
    """Run an explicitly configured visual tool through a JSONL boundary."""

    def __init__(
        self,
        executable: str = "",
        args: list[str] | None = None,
        working_directory: str | None = None,
        timeout: float = 30,
    ) -> None:
        self.executable = executable
        self.args = list(args or [])
        self.working_directory = working_directory
        self.timeout = timeout
        self.info = ProviderInfo(
            id="external-vision",
            name="External Vision",
            capability="vision",
            status="unconfigured",
            description="调用明确配置路径的 JSONL 视觉摘要软件。",
            config_schema=_COMMAND_CONFIG_SCHEMA,
        )
        self._refresh_status()

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

    def summarize(self, request: VisionRequest) -> VisionResult:
        responses = self._run(
            {
                "type": "vision.observe",
                "source": request.source,
                "mime_type": request.mime_type,
                "image_base64": base64.b64encode(request.image).decode("ascii"),
                "prompt": request.prompt,
            }
        )
        for response in responses:
            if response.get("type") == "error":
                raise RuntimeError(str(response.get("message", "external vision error")))
            if response.get("type") in {"result", "summary"} and isinstance(response.get("summary"), str):
                return VisionResult(response["summary"])
        raise RuntimeError("External vision provider returned no summary")

    def _refresh_status(self) -> None:
        self.info.status = "available" if self.executable.strip() and Path(self.executable).is_file() else "unconfigured"

    def _run(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.executable.strip():
            raise RuntimeError("External vision provider is not configured")
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
            try:
                stdout, stderr = process.communicate(json.dumps(payload, ensure_ascii=False) + "\n", timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise TimeoutError("External vision provider timed out") from exc
            if process.returncode != 0:
                raise RuntimeError(f"External vision provider exited with {process.returncode}: {stderr[:500]}")
            responses: list[dict[str, Any]] = []
            for line in stdout.splitlines():
                value = line.strip()
                if not value:
                    continue
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    responses.append(parsed)
            return responses
        finally:
            if process.poll() is None:
                process.kill()


__all__ = ["CommandVisionProvider", "VisionProvider", "VisionRequest", "VisionResult"]
