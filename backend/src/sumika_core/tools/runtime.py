"""Approval-gated JSONL execution for configured external software."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..events import EventBus
from ..modules import ModuleCatalog
from ..protocol.models import EventEnvelope


class ToolRuntimeError(ValueError):
    """Raised when an external tool call is not safe or does not complete."""


class ToolRuntime:
    """Run one configured executable without a shell or persistent process."""

    _IMPLEMENTATION = "external-process"
    _MAX_INPUT_BYTES = 1 * 1024 * 1024
    _MAX_OUTPUT_BYTES = 4 * 1024 * 1024
    _MAX_TIMEOUT_SECONDS = 120

    def __init__(self, modules: ModuleCatalog, events: EventBus) -> None:
        self.modules = modules
        self.events = events

    def run(
        self,
        *,
        tool_id: str | None,
        input: Any,
        approved: bool,
    ) -> dict[str, Any]:
        module = self.modules.get("tools")
        return self.run_configured(
            tool_id=tool_id,
            input=input,
            approved=approved,
            config=module["config"],
        )

    def run_configured(
        self,
        *,
        tool_id: str | None,
        input: Any,
        approved: bool,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one explicitly supplied launcher under the tools module gate.

        Plugin launchers use this path after their manifest and entrypoint have
        been revalidated by ``PluginCatalog``. The module still has to be
        enabled and selected for the external-process implementation.
        """
        module = self.modules.get("tools")
        if not module["enabled"]:
            raise ToolRuntimeError("tools module is disabled")
        if module["implementation_id"] != self._IMPLEMENTATION:
            raise ToolRuntimeError("tools module is not configured for external-process")
        if not isinstance(approved, bool):
            raise ToolRuntimeError("approved must be a boolean")
        if not approved:
            raise ToolRuntimeError("explicit approval is required before invoking an external tool")

        clean_tool_id = str(tool_id or "manual").strip()
        if not clean_tool_id or len(clean_tool_id) > 128:
            raise ToolRuntimeError("tool_id must be a short non-empty string")
        executable, arguments, working_directory, timeout_seconds = _resolve_config(config)
        request_id = f"tool-{uuid4().hex[:12]}"
        request_payload = {
            "protocol": "sumika.tool.v1",
            "request_id": request_id,
            "tool_id": clean_tool_id,
            "input": input,
        }
        try:
            encoded_request = json.dumps(request_payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ToolRuntimeError("tool input must be JSON serializable") from exc
        request_size = len(encoded_request.encode("utf-8"))
        if request_size > self._MAX_INPUT_BYTES:
            raise ToolRuntimeError("tool input is too large")
        input_hash = hashlib.sha256(encoded_request.encode("utf-8")).hexdigest()
        self.events.publish(
            EventEnvelope(
                "tool.started",
                {
                    "request_id": request_id,
                    "tool_id": clean_tool_id,
                    "executable": executable.name,
                    "input_sha256": input_hash,
                    "input_size": request_size,
                },
            )
        )

        started = time.monotonic()
        try:
            result, output_size = self._execute(
                executable,
                arguments,
                working_directory,
                encoded_request,
                timeout_seconds,
            )
        except ToolRuntimeError as exc:
            self.events.publish(
                EventEnvelope(
                    "tool.failed",
                    {
                        "request_id": request_id,
                        "tool_id": clean_tool_id,
                        "executable": executable.name,
                        "error": "external_tool_failed",
                        "error_type": type(exc).__name__,
                    },
                )
            )
            raise

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        self.events.publish(
            EventEnvelope(
                "tool.completed",
                {
                    "request_id": request_id,
                    "tool_id": clean_tool_id,
                    "executable": executable.name,
                    "output_size": output_size,
                    "duration_ms": duration_ms,
                },
            )
        )
        return {
            "request_id": request_id,
            "tool_id": clean_tool_id,
            "runner": self._IMPLEMENTATION,
            "result": result,
        }

    def _execute(
        self,
        executable: Path,
        arguments: list[str],
        working_directory: Path | None,
        encoded_request: str,
        timeout_seconds: int,
    ) -> tuple[Any, int]:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                [str(executable), *arguments],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(working_directory) if working_directory else None,
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = process.communicate(encoded_request + "\n", timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()
            raise ToolRuntimeError(f"external tool timed out after {timeout_seconds}s") from exc
        except OSError as exc:
            raise ToolRuntimeError(f"unable to start external tool: {exc}") from exc
        finally:
            if process is not None and process.poll() is None:
                process.kill()

        if process.returncode != 0:
            detail = (stderr or "").strip()
            suffix = f": {detail[:500]}" if detail else ""
            raise ToolRuntimeError(f"external tool exited with {process.returncode}{suffix}")
        output_size = len((stdout or "").encode("utf-8"))
        if output_size > self._MAX_OUTPUT_BYTES:
            raise ToolRuntimeError("external tool output is too large")
        return _parse_output(stdout), output_size


def _resolve_config(config: Any) -> tuple[Path, list[str], Path | None, int]:
    if not isinstance(config, dict):
        raise ToolRuntimeError("external tool config must be an object")
    executable_value = config.get("executable")
    if not isinstance(executable_value, str) or not executable_value.strip():
        raise ToolRuntimeError("external tool executable is required")
    executable = Path(executable_value).expanduser()
    if not executable.is_absolute():
        raise ToolRuntimeError("external tool executable must be an absolute path")
    try:
        executable = executable.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ToolRuntimeError("external tool executable is not readable") from exc
    if not executable.is_file():
        raise ToolRuntimeError("external tool executable must point to a file")

    arguments = config.get("arguments", [])
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise ToolRuntimeError("external tool arguments must be a list of strings")
    if len(arguments) > 64 or any(len(value) > 4096 for value in arguments):
        raise ToolRuntimeError("external tool arguments are too large")

    working_directory = None
    working_value = config.get("working_directory")
    if working_value not in (None, ""):
        if not isinstance(working_value, str):
            raise ToolRuntimeError("working_directory must be a string")
        working_directory = Path(working_value).expanduser()
        if not working_directory.is_absolute():
            raise ToolRuntimeError("working_directory must be an absolute path")
        try:
            working_directory = working_directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ToolRuntimeError("working_directory is not readable") from exc
        if not working_directory.is_dir():
            raise ToolRuntimeError("working_directory must point to a directory")

    timeout_seconds = config.get("timeout_seconds", 30)
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
        or timeout_seconds > ToolRuntime._MAX_TIMEOUT_SECONDS
    ):
        raise ToolRuntimeError("timeout_seconds must be an integer between 1 and 120")
    return executable, list(arguments), working_directory, timeout_seconds


def _parse_output(stdout: str) -> Any:
    values: list[Any] = []
    for line in stdout.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolRuntimeError("external tool returned invalid JSONL") from exc
        if isinstance(parsed, dict) and parsed.get("type") == "error":
            raise ToolRuntimeError(str(parsed.get("message") or "external tool reported an error"))
        if isinstance(parsed, dict) and parsed.get("type") == "result":
            values.append(parsed.get("result"))
        else:
            values.append(parsed.get("result") if isinstance(parsed, dict) and "result" in parsed else parsed)
    if not values:
        raise ToolRuntimeError("external tool returned no result")
    return values[-1]
