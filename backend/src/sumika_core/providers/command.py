from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from pathlib import Path

from ..protocol.models import ChatRequest, ProviderInfo
from .base import LLMProvider


class CommandProvider(LLMProvider):
    """Run a user-approved external program through a JSONL contract.

    Request: one JSON object on stdin. Response: JSONL events such as
    {"type":"token","text":"..."}, followed by {"type":"done"}.
    Plain stdout lines are accepted as token text for simple adapters.
    """

    def __init__(
        self,
        executable: str,
        args: list[str] | None = None,
        working_directory: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.executable = executable
        self.args = args or []
        self.working_directory = working_directory
        self.timeout = timeout
        self.info = ProviderInfo(
            id="external-command",
            name="External command",
            status="available" if Path(executable).exists() else "unconfigured",
            description="Call an explicitly configured JSONL program in a separate process.",
            config_schema={
                "type": "object",
                "required": ["executable"],
                "properties": {
                    "executable": {"type": "string", "title": "可执行文件"},
                    "args": {"type": "array", "items": {"type": "string"}, "title": "参数"},
                    "working_directory": {"type": "string", "title": "工作目录"},
                    "timeout": {"type": "number", "title": "超时（秒）", "minimum": 1},
                },
            },
        )

    def configure(self, config: dict[str, object]) -> None:
        executable = config.get("executable")
        args = config.get("args")
        working_directory = config.get("working_directory")
        timeout = config.get("timeout")
        if isinstance(executable, str) and executable.strip():
            self.executable = executable
        if isinstance(args, list) and all(isinstance(item, str) for item in args):
            self.args = list(args)
        if isinstance(working_directory, str):
            self.working_directory = working_directory or None
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout >= 1:
            self.timeout = float(timeout)
        self.info.status = "available" if Path(self.executable).exists() else "unconfigured"

    def stream(self, request: ChatRequest) -> Iterable[str]:
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
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps(_request_payload(request), ensure_ascii=False) + "\n")
            process.stdin.close()
            for line in process.stdout:
                parsed = _parse_line(line)
                if parsed is None:
                    continue
                if parsed.get("type") == "done":
                    break
                if parsed.get("type") == "error":
                    raise RuntimeError(str(parsed.get("message", "external provider error")))
                text = parsed.get("text")
                if isinstance(text, str):
                    yield text
            try:
                code = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                raise TimeoutError("External provider timed out") from exc
            if code != 0:
                error = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"External provider exited with {code}: {error[:500]}")
        finally:
            if process.poll() is None:
                process.kill()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


def _request_payload(request: ChatRequest) -> dict:
    return {
        "session_id": request.session_id,
        "character_id": request.character_id,
        "messages": [message.to_dict() for message in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }


def _parse_line(line: str) -> dict | None:
    value = line.strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"type": "token", "text": value}
    return parsed if isinstance(parsed, dict) else {"type": "token", "text": str(parsed)}
