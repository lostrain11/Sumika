"""ZCode ``app-server --stdio`` Agent runtime adapter.

Only the public line-delimited app-server boundary is used here.  The adapter
does not inspect ZCode's settings, credential, cookie, or browser storage;
authentication remains owned by the ZCode process itself.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ....protocol.models import utc_now
from ...contracts import AgentCapability, AgentRuntime, AgentRuntimeError
from ...models import AgentEvent
from .config import ZCodeRuntimeConfig, config_from_env


_MAX_LINE_BYTES = 4 * 1024 * 1024
_MAX_TEXT = 12_000
_MAX_RESPONSE_ITEMS = 256


class ZCodeProtocolError(AgentRuntimeError):
    """A protocol error returned by the ZCode app-server."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class _TransportFailure(RuntimeError):
    pass


class _JsonRpcProcess:
    """One owned child process with correlated requests and notifications."""

    def __init__(
        self,
        config: ZCodeRuntimeConfig,
        *,
        logger: Any = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.on_message = on_message
        self.process: subprocess.Popen[str] | None = None
        self._pending: dict[str, queue.Queue[Any]] = {}
        self._write_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._closed = False
        self._last_error: str | None = None
        self._generation = 0
        # ``zcode`` is the wire used by current ZCode app-server builds:
        # JSON objects are line-delimited but do not carry a ``jsonrpc`` key.
        # In auto mode the first read-only probe decides whether a legacy
        # JSON-RPC peer is actually on the other end.
        self._wire_protocol = (
            "jsonrpc" if config.wire_protocol == "jsonrpc" else "zcode"
        )

    @property
    def alive(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    @property
    def wire_protocol(self) -> str:
        return self._wire_protocol

    @property
    def protocol(self) -> str:
        """Compatibility alias for callers that used the shorter name."""

        return self._wire_protocol

    def set_wire_protocol(self, value: str) -> None:
        if value not in {"zcode", "jsonrpc"}:
            raise ValueError("wire protocol must be zcode or jsonrpc")
        self._wire_protocol = value

    def _request_body(self, request_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"id": request_id, "method": method, "params": params}
        if self._wire_protocol == "jsonrpc":
            body = {"jsonrpc": "2.0", **body}
        return body

    def _notification_body(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"method": method, "params": params}
        if self._wire_protocol == "jsonrpc":
            body = {"jsonrpc": "2.0", **body}
        return body

    def _response_body(self, request_id: str, *, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"id": request_id}
        body["error" if error is not None else "result"] = error if error is not None else (result if result is not None else {})
        if self._wire_protocol == "jsonrpc":
            body = {"jsonrpc": "2.0", **body}
        return body

    def start(self) -> None:
        with self._state_lock:
            if self.alive:
                return
            if self._closed:
                raise AgentRuntimeError("ZCode runtime has been closed", transport=True)
            previous = self.process
            if previous is not None and previous.poll() is not None:
                # A dead process may still have a reader thread draining its
                # pipes.  Replacing the handle is safe because the reader's
                # generation check prevents it from failing a new request.
                self.process = None
            executable = (self.config.executable or "").strip()
            if not self.config.enabled:
                raise AgentRuntimeError("ZCode runtime is disabled")
            if not executable:
                raise AgentRuntimeError("ZCode executable is not configured")
            command = [executable, *self.config.arguments]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    command,
                    cwd=self.config.working_directory or None,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    shell=False,
                    creationflags=creationflags,
                )
                self.process = process
                self._generation += 1
                generation = self._generation
            except (OSError, ValueError) as exc:
                self.process = None
                raise AgentRuntimeError(
                    "ZCode app-server could not be started",
                    transport=True,
                ) from exc
            self._last_error = None
            self._reader_thread = threading.Thread(
                target=self._read_stdout,
                args=(process, generation),
                name="sumika-zcode-jsonrpc",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                args=(process, generation),
                name="sumika-zcode-stderr",
                daemon=True,
            )
            self._reader_thread.start()
            self._stderr_thread.start()
            if self.logger:
                self.logger.info(
                    "zcode app-server started executable_name=%s argument_count=%d",
                    Path(executable).name,
                    len(self.config.arguments),
                )

    def request(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> Any:
        self.start()
        process = self.process
        if process is None or process.stdin is None:
            raise AgentRuntimeError("ZCode app-server stdin is unavailable", transport=True)
        request_id = f"sumika-{uuid4().hex}"
        response_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
        with self._state_lock:
            self._pending[request_id] = response_queue
        body = self._request_body(request_id, method, params)
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise AgentRuntimeError("ZCode app-server request could not be written", transport=True) from exc

        wait_seconds = timeout if timeout is not None else self.config.request_timeout
        try:
            value = response_queue.get(timeout=wait_seconds)
        except queue.Empty as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise AgentRuntimeError(
                f"ZCode app-server timed out while calling {method}",
                transport=True,
            ) from exc
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)
        if isinstance(value, _TransportFailure):
            raise AgentRuntimeError("ZCode app-server connection closed", transport=True) from value
        if not isinstance(value, dict):
            raise ZCodeProtocolError("ZCode returned an invalid app-server response")
        if self.config.wire_protocol == "auto":
            # A response carrying ``jsonrpc`` is an unambiguous indication of
            # the legacy peer.  Current ZCode responses intentionally omit it.
            self._wire_protocol = "jsonrpc" if "jsonrpc" in value else "zcode"
        if value.get("error"):
            error = value.get("error")
            if isinstance(error, dict):
                code = error.get("code") if isinstance(error.get("code"), int) else None
                message = _sanitize_runtime_message(error.get("message")) or "ZCode request failed"
                raise ZCodeProtocolError(message, code=code)
            raise ZCodeProtocolError("ZCode request failed")
        return value.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.start()
        process = self.process
        if process is None or process.stdin is None:
            raise AgentRuntimeError("ZCode app-server stdin is unavailable", transport=True)
        body = self._notification_body(method, params or {})
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AgentRuntimeError("ZCode app-server notification could not be written", transport=True) from exc

    def respond(self, request_id: str, *, result: Any = None, error: dict[str, Any] | None = None) -> None:
        # Never start a replacement process for a response belonging to an old
        # process.  Doing so could deliver an approval decision to an unrelated
        # session after an app-server crash.
        with self._state_lock:
            process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            raise AgentRuntimeError("ZCode app-server connection is no longer alive", transport=True)
        body = self._response_body(request_id, result=result, error=error)
        try:
            with self._write_lock:
                process.stdin.write(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AgentRuntimeError("ZCode app-server response could not be written", transport=True) from exc

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            process = self.process
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            try:
                response_queue.put_nowait(_TransportFailure("closed"))
            except queue.Full:
                pass
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        for thread in (self._reader_thread, self._stderr_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self.process = None
        if self.logger:
            self.logger.info("zcode app-server stopped")

    def _read_stdout(self, process: subprocess.Popen[str], generation: int) -> None:
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if len(line.encode("utf-8", errors="replace")) > _MAX_LINE_BYTES:
                    self._fail_pending("response line too large", process=process, generation=generation)
                    continue
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    if self.logger:
                        self.logger.info("zcode app-server emitted malformed json line")
                    continue
                if not isinstance(value, dict):
                    continue
                is_response = "method" not in value and ("result" in value or "error" in value)
                if is_response and value.get("id") is not None:
                    request_id = str(value.get("id"))
                    with self._state_lock:
                        response_queue = self._pending.get(request_id)
                    if response_queue is not None:
                        try:
                            response_queue.put_nowait(value)
                        except queue.Full:
                            pass
                        continue
                callback = self.on_message
                if callback is not None:
                    try:
                        callback(value)
                    except Exception as exc:
                        if self.logger:
                            self.logger.info(
                                "zcode event callback failed error_type=%s",
                                type(exc).__name__,
                            )
        finally:
            self._fail_pending("stdout closed", process=process, generation=generation)

    def _read_stderr(self, process: subprocess.Popen[str], generation: int) -> None:
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            if self.logger:
                # Never copy stderr into application logs: ZCode may include
                # account or prompt data in diagnostics.  Keep only a bound.
                self.logger.info("zcode app-server stderr line_length=%d", len(line))

    def _fail_pending(
        self,
        detail: str,
        *,
        process: subprocess.Popen[str] | None = None,
        generation: int | None = None,
    ) -> None:
        with self._state_lock:
            if process is not None and self.process is not process:
                return
            if generation is not None and generation != self._generation:
                return
            self._last_error = detail
            pending = list(self._pending.values())
        for response_queue in pending:
            try:
                response_queue.put_nowait(_TransportFailure(detail))
            except queue.Full:
                pass

    def transport_info(self) -> dict[str, Any]:
        with self._state_lock:
            process = self.process
            return {
                "alive": bool(process is not None and process.poll() is None),
                "returncode": process.poll() if process is not None else None,
                "last_error": self._last_error,
            }


class ZCodeAgentRuntime(AgentRuntime):
    """Harness-neutral facade over a user-configured ZCode app-server."""

    runtime_id = "zcode"
    capability_ids = frozenset(
        {
            AgentCapability.DIAGNOSTICS,
            AgentCapability.MODELS,
            AgentCapability.SESSION_FORK,
            AgentCapability.HISTORY,
            AgentCapability.SUBAGENTS,
            AgentCapability.PLAN,
            AgentCapability.INTERACTIONS,
            AgentCapability.EVENT_INGEST,
            AgentCapability.MCP,
        }
    )

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        logger: Any = None,
        config: ZCodeRuntimeConfig | None = None,
    ) -> None:
        self.config = config or config_from_env(data_dir, env)
        self.logger = logger
        self._last_health: dict[str, Any] | None = None
        self._last_health_at = 0.0
        self._initialized = False
        self._event_sink: Any = None
        self._event_lock = threading.RLock()
        self._event_listeners: set[Any] = set()
        self._pending_server_requests: set[str] = set()
        self._advertised_capabilities: set[AgentCapability] | None = None
        self._advertised_features: set[str] = set()
        self._modern_protocol = False
        self._workspace_path = self.config.working_directory or str(Path.cwd())
        self._transport = _JsonRpcProcess(self.config, logger=logger, on_message=self._on_message)

    def status(self) -> dict[str, Any]:
        transport = self._transport.transport_info()
        if not transport["alive"]:
            self._reset_after_transport_loss()
        if not self.config.enabled:
            state = "disabled"
        elif transport["alive"] and self._last_health and self._last_health.get("ok"):
            state = "ready"
        else:
            state = "unavailable"
        result = {
            "runtime_id": self.runtime_id,
            "version": self.config.version,
            "state": state,
            "ready": state == "ready",
            "enabled": self.config.enabled,
            "configured": bool(self.config.executable),
            "managed": self.config.managed,
            "transport": "stdio-zcode" if self._modern_protocol else "stdio-jsonrpc",
            "wire_protocol": self._transport.wire_protocol,
            "process_alive": transport["alive"],
            "profile_configured": bool(self.config.profile_dir),
            "runtime_capabilities": self.runtime_capabilities(),
        }
        if state == "unavailable" and transport.get("last_error"):
            result["transport_error"] = "ZCode app-server connection is unavailable"
        if transport.get("returncode") is not None:
            result["process_exit_code"] = transport["returncode"]
        return result

    def health(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "state": "disabled", "error": "ZCode runtime is disabled"}
        self._reset_after_transport_loss()
        try:
            self._initialize()
            if self._modern_protocol:
                # ``session/list`` is the public, side-effect-free modern
                # health probe.  There is no separate initialize/health call.
                value = {"protocol": "zcode", "probe": "session/list"}
            else:
                try:
                    value = self._call_variants(("health", "status", "host/describe"), {})
                except ZCodeProtocolError as error:
                    if error.code not in {-32600, -32601}:
                        raise
                    value = {"protocol": "initialized"}
            self._last_health = {
                "ok": True,
                "state": "ready",
                "runtime": _compact_public(value),
            }
        except AgentRuntimeError as error:
            self._last_health = {
                "ok": False,
                "state": "unavailable",
                "error": str(error),
            }
        self._last_health_at = time.monotonic()
        return dict(self._last_health)

    def diagnostics(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        health = self.health()
        ready = bool(health.get("ok") and self._transport.alive)
        advertised = self._advertised_capabilities
        return {
            "checked_at": utc_now(),
            "runtime": {
                "runtime_id": self.runtime_id,
                "state": health.get("state"),
                "ready": ready,
                "transport": "stdio-zcode" if self._modern_protocol else "stdio-jsonrpc",
                "configured": bool(self.config.executable),
                "profile_configured": bool(self.config.profile_dir),
                "process_alive": self._transport.alive,
            },
            "capabilities": [
                {
                    "id": value,
                    "available": bool(ready and (advertised is None or AgentCapability(value) in advertised)),
                    "status": "available" if ready and (advertised is None or AgentCapability(value) in advertised) else "declared",
                }
                for value in self.runtime_capabilities()
            ],
            "summary": {"available": len(self.runtime_capabilities())} if ready else {"unavailable": 1},
        }

    @property
    def _is_modern(self) -> bool:
        return self._modern_protocol

    def _workspace_descriptor(self, params: Mapping[str, Any] | None = None) -> dict[str, str]:
        params = params or {}
        raw = params.get("workspacePath") or params.get("workspace_path") or params.get("cwd")
        if isinstance(params.get("workspace"), Mapping):
            raw = raw or params["workspace"].get("workspacePath") or params["workspace"].get("workspace_path")
        path = str(raw or self._workspace_path).strip()
        if not path:
            path = str(Path.cwd())
        try:
            path = str(Path(path).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            path = str(Path.cwd())
        self._workspace_path = path
        return {"workspacePath": path, "workspaceKey": path}

    @staticmethod
    def _modern_mode(value: Any) -> str:
        mode = _safe_text(value, 40).lower()
        aliases = {"execute": "build", "readonly": "edit"}
        mode = aliases.get(mode, mode)
        return mode if mode in {"plan", "build", "edit", "yolo", "auto"} else "build"

    def _modern_model_ref(self, value: Any, params: Mapping[str, Any] | None = None) -> dict[str, str] | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, Mapping):
            if isinstance(value.get("ref"), Mapping):
                value = value["ref"]
            raw_provider = value.get("providerId") or value.get("provider_id") or value.get("provider")
            if isinstance(raw_provider, Mapping):
                raw_provider = raw_provider.get("id") or raw_provider.get("providerId") or raw_provider.get("provider_id")
            provider = _safe_text(raw_provider, 240)
            model = _safe_text(value.get("modelId") or value.get("model_id") or value.get("id") or value.get("name"), 240)
            variant = _safe_text(value.get("variant"), 120)
        else:
            provider = ""
            model = _safe_text(value, 240)
            variant = ""
        params = params or {}
        provider = provider or _safe_text(params.get("providerId") or params.get("provider_id") or params.get("provider"), 240)
        if not model:
            raise AgentRuntimeError("ZCode model id is required")
        # A bare model id is accepted by Sumika's legacy API, but ZCode's
        # modern schema requires an explicit provider.  Never invent a
        # provider id: doing so turns a configuration error into a request
        # that the app-server may interpret as a real route.
        if not provider:
            raise AgentRuntimeError(
                "ZCode model selection requires an explicit provider id"
            )
        result = {"providerId": provider, "modelId": model}
        if variant:
            result["variant"] = variant
        return result

    def _modern_runtime_model(self, value: Any) -> dict[str, Any] | None:
        """Validate the complete runtime model envelope accepted by ZCode.

        ``session/send`` accepts a runtime model only when the caller has a
        fully materialized provider definition.  A short ``provider/model``
        pair is intentionally handled through ``session/setModel`` instead;
        synthesizing credentials or provider metadata here produces an
        envelope that strict ZCode builds reject.
        """

        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise AgentRuntimeError("ZCode runtimeModel must be an object")
        revision = _safe_text(value.get("revision"), 240)
        generated_at = value.get("generatedAt")
        if not revision:
            raise AgentRuntimeError("ZCode runtimeModel requires a revision")
        if isinstance(generated_at, bool) or not isinstance(generated_at, int) or generated_at < 0:
            raise AgentRuntimeError(
                "ZCode runtimeModel generatedAt must be a non-negative integer timestamp"
            )

        raw_model = value.get("model")
        if not isinstance(raw_model, Mapping):
            raise AgentRuntimeError("ZCode runtimeModel requires a model reference")
        model_ref = self._modern_model_ref(raw_model)

        raw_provider = value.get("provider")
        if not isinstance(raw_provider, Mapping):
            raise AgentRuntimeError("ZCode runtimeModel requires a provider definition")
        provider_id = _safe_text(raw_provider.get("providerId"), 240)
        kind = _safe_text(raw_provider.get("kind"), 40).lower()
        if not provider_id or not kind:
            raise AgentRuntimeError("ZCode runtimeModel provider requires providerId and kind")
        if kind not in {"anthropic", "openai", "openai-compatible"}:
            raise AgentRuntimeError("ZCode runtimeModel provider kind is unsupported")
        if provider_id != model_ref["providerId"]:
            raise AgentRuntimeError(
                "ZCode runtimeModel providerId must match its model reference"
            )

        raw_models = raw_provider.get("models")
        if not isinstance(raw_models, list):
            raise AgentRuntimeError("ZCode runtimeModel provider requires a model list")
        models: list[dict[str, Any]] = []
        for raw_entry in raw_models[:128]:
            if not isinstance(raw_entry, Mapping):
                continue
            model_id = _safe_text(raw_entry.get("modelId"), 240)
            if not model_id:
                continue
            entry: dict[str, Any] = {"modelId": model_id}
            for key, limit in (("label", 240), ("description", 1200)):
                text = _safe_text(raw_entry.get(key), limit)
                if text:
                    entry[key] = text
            for key in (
                "contextWindow",
                "maxOutputTokens",
            ):
                number = raw_entry.get(key)
                if isinstance(number, int) and not isinstance(number, bool) and number > 0:
                    entry[key] = number
            for key in (
                "supportsImages",
                "supportsPdf",
                "supportsVideo",
                "supportsTools",
                "supportsStructuredOutput",
            ):
                if isinstance(raw_entry.get(key), bool):
                    entry[key] = raw_entry[key]
            models.append(entry)
        if not models:
            raise AgentRuntimeError("ZCode runtimeModel provider has no valid models")
        if not any(item["modelId"] == model_ref["modelId"] for item in models):
            raise AgentRuntimeError(
                "ZCode runtimeModel model reference is missing from the provider model list"
            )

        provider: dict[str, Any] = {
            "providerId": provider_id,
            "kind": kind,
            "models": models,
        }
        for key, limit in (
            ("apiFormat", 40),
            ("label", 240),
            ("baseURL", 4096),
            ("logoUrl", 4096),
            ("modelsDevProviderId", 240),
        ):
            text = _safe_text(raw_provider.get(key), limit)
            if text:
                if key == "apiFormat" and text not in {
                    "anthropic-messages",
                    "openai-chat-completions",
                    "openai-responses",
                }:
                    raise AgentRuntimeError("ZCode runtimeModel provider apiFormat is unsupported")
                provider[key] = text
        source = _safe_text(raw_provider.get("source"), 40).lower()
        if source in {"builtin", "models-dev", "custom", "user", "workspace", "ephemeral"}:
            provider["source"] = source
        elif raw_provider.get("source") is not None:
            raise AgentRuntimeError("ZCode runtimeModel provider source is unsupported")
        if raw_provider.get("apiKey") is not None and not isinstance(raw_provider.get("apiKey"), Mapping):
            raise AgentRuntimeError("ZCode runtimeModel apiKey must be a credential reference")
        if isinstance(raw_provider.get("apiKey"), Mapping):
            secret = raw_provider["apiKey"]
            secret_source = _safe_text(secret.get("source"), 40).lower()
            if secret_source == "inline":
                raise AgentRuntimeError("ZCode runtimeModel does not accept inline credentials")
            if secret_source not in {"credential", "env", "server-config", "session-secret"}:
                raise AgentRuntimeError("ZCode runtimeModel credential reference is unsupported")
            secret_key = _safe_text(secret.get("key") or secret.get("name"), 240)
            if not secret_key:
                raise AgentRuntimeError("ZCode runtimeModel credential reference is incomplete")
            provider["apiKey"] = {"source": secret_source, "key" if secret_source != "env" else "name": secret_key}
        if isinstance(raw_provider.get("apiKeyRequired"), bool):
            provider["apiKeyRequired"] = raw_provider["apiKeyRequired"]
        raw_headers = raw_provider.get("headers")
        if raw_headers is not None and not isinstance(raw_headers, Mapping):
            raise AgentRuntimeError("ZCode runtimeModel headers must be an object")
        if isinstance(raw_headers, Mapping):
            headers: dict[str, str] = {}
            for key, item in list(raw_headers.items())[:32]:
                header_name = _safe_text(key, 160)
                header_value = _safe_text(item, 1000)
                if not header_name or not header_value:
                    continue
                if any(token in header_name.lower() for token in ("authorization", "api-key", "token", "secret", "cookie", "password")):
                    raise AgentRuntimeError("ZCode runtimeModel rejects sensitive inline headers")
                headers[header_name] = header_value
            if headers:
                provider["headers"] = headers

        result: dict[str, Any] = {
            "revision": revision,
            "generatedAt": generated_at,
            "model": model_ref,
            "provider": provider,
        }
        thought_level = _safe_text(value.get("thoughtLevel"), 120)
        if thought_level:
            result["thoughtLevel"] = thought_level
        return result

    def _workspace_state(self, params: Mapping[str, Any] | None = None) -> Any:
        return self._transport.request(
            "workspace/readState",
            {"workspace": self._workspace_descriptor(params)},
        )

    def _ensure_initialized(self) -> None:
        if not self._initialized or not self._transport.alive:
            self._initialize()

    def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            payload: dict[str, Any] = {
                "workspace": self._workspace_descriptor(params),
                "mode": self._modern_mode(params.get("mode")),
                "persistence": _safe_text(params.get("persistence"), 40) or "immediate",
            }
            if payload["persistence"] not in {"immediate", "deferred"}:
                payload["persistence"] = "immediate"
            model_value = params.get("model") or params.get("modelRef")
            model_ref = self._modern_model_ref(model_value, params)
            if model_ref:
                payload["model"] = model_ref
            runtime_model_value = params.get("runtimeModel") or params.get("runtime_model")
            runtime_model = self._modern_runtime_model(runtime_model_value)
            if runtime_model:
                if model_ref and runtime_model["model"] != model_ref:
                    raise AgentRuntimeError(
                        "ZCode session model and runtimeModel reference do not match"
                    )
                payload["runtimeModel"] = runtime_model
            value = self._transport.request("session/create", payload)
            session_id = _extract_id(value, ("sessionId", "session_id", "id"))
            if not session_id and isinstance(value, Mapping):
                session_id = _extract_id(value.get("session"), ("sessionId", "session_id", "id"))
            if not session_id:
                raise AgentRuntimeError("ZCode did not return a session id")
            session_info = value.get("session") if isinstance(value, Mapping) and isinstance(value.get("session"), Mapping) else value
            return {
                "sessionId": session_id,
                "session_id": session_id,
                "title": _safe_text(
                    _first(session_info, "title", "name")
                    or params.get("title")
                    or "未命名 Agent 会话",
                    240,
                ),
                "state": _safe_text(_first(session_info, "state", "status"), 80) or "idle",
                "workspace": _compact_public(_first(session_info, "workspace")),
            }
        payload = _session_payload(params)
        value = self._call_variants(("session/create", "thread/start", "session.create"), payload)
        session_id = _extract_id(value, ("sessionId", "session_id", "threadId", "thread_id", "id"))
        if not session_id:
            raise AgentRuntimeError("ZCode did not return a session id")
        return {
            "sessionId": session_id,
            "session_id": session_id,
            "title": _safe_text(_first(value, "title", "name"), 240),
            "state": _safe_text(_first(value, "state", "status"), 80) or "idle",
        }

    def list_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            params = params or {}
            request: dict[str, Any] = {"workspace": self._workspace_descriptor(params)}
            if params.get("includeArchived") is not None:
                request["includeArchived"] = bool(params.get("includeArchived"))
            if isinstance(params.get("limit"), int) and params["limit"] > 0:
                request["limit"] = min(params["limit"], _MAX_RESPONSE_ITEMS)
            value = self._transport.request("session/list", request)
        else:
            del params
            value = self._call_variants(("session/list", "thread/list", "session.list"), {})
        raw = _first_list(value, ("sessions", "threads", "items", "data"))
        sessions: list[dict[str, Any]] = []
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            session_id = _extract_id(item, ("sessionId", "session_id", "threadId", "thread_id", "id"))
            if not session_id:
                continue
            raw_model = _first(item, "model", "modelRef")
            if isinstance(raw_model, Mapping):
                model_text = _safe_text(raw_model.get("providerId"), 120)
                model_id = _safe_text(raw_model.get("modelId"), 160)
                raw_model = f"{model_text}/{model_id}" if model_text and model_id else model_id
            sessions.append(
                {
                    "id": session_id,
                    "title": _safe_text(_first(item, "title", "name") or "未命名 Agent 会话", 240),
                    "state": _safe_text(_first(item, "state", "status"), 80) or "idle",
                    "updated_at": _safe_scalar(_first(item, "updatedAt", "updated_at", "createdAt")),
                    "model": _safe_text(raw_model or _first(item, "modelId"), 160) or None,
                }
            )
        return {"sessions": sessions}

    def snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        if self._is_modern:
            request: dict[str, Any] = {"sessionId": session_id}
            if params.get("deliveryKind") in {"desktop-continuous", "web-remote-replayable"}:
                request["deliveryKind"] = params["deliveryKind"]
            if isinstance(params.get("messageLimit"), int) and params["messageLimit"] > 0:
                request["messageLimit"] = min(params["messageLimit"], _MAX_RESPONSE_ITEMS)
            try:
                value = self._transport.request("session/read", request)
            except ZCodeProtocolError as error:
                if error.code != -32004:
                    raise
                # Persisted ZCode sessions are inactive until explicitly
                # resumed.  Resume only in response to the user's snapshot
                # request; listing sessions remains side-effect free.
                value = self._transport.request("session/resume", {"sessionId": session_id})
        else:
            value = self._call_variants(
                ("session/snapshot", "thread/read", "session/read", "session.snapshot"),
                {"sessionId": session_id},
            )
        result = _compact_public(value)
        if isinstance(result, dict):
            result.setdefault("session_id", session_id)
            return result
        return {"session_id": session_id, "value": result}

    def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        content = _prompt_content(params)
        mode = _safe_text(params.get("mode") or "execute", 40).lower()
        if mode not in {"plan", "execute", "readonly"}:
            mode = "execute"
        if self._is_modern:
            if mode == "readonly":
                raise AgentRuntimeError("ZCode modern app-server does not expose a readonly mode")
            modern_mode = self._modern_mode(mode)
            if params.get("mode") is not None:
                self._transport.request("session/setMode", {"sessionId": session_id, "mode": modern_mode})
            request: dict[str, Any] = {
                "sessionId": session_id,
                "content": "\n".join(block["text"] for block in content),
            }
            for key in ("inputId", "input_id", "queryId", "query_id"):
                if params.get(key):
                    request["inputId" if key.startswith("input") else "queryId"] = _safe_text(params[key], 240)
            model_value = params.get("model") or params.get("modelRef")
            runtime_model_value = params.get("runtimeModel") or params.get("runtime_model")
            runtime_model = self._modern_runtime_model(runtime_model_value)
            if model_value is not None:
                model_ref = self._modern_model_ref(model_value, params)
                if runtime_model is not None:
                    if runtime_model["model"] != model_ref:
                        raise AgentRuntimeError(
                            "ZCode prompt model and runtimeModel reference do not match"
                        )
                else:
                    # ``session/send`` has no short model field.  Apply an
                    # explicit provider/model choice through the public
                    # session endpoint instead of inventing a runtime model.
                    self._transport.request(
                        "session/setModel",
                        {
                            "sessionId": session_id,
                            "model": model_ref,
                            "persistAsWorkspaceLastUsed": bool(
                                params.get("persistAsWorkspaceLastUsed", False)
                            ),
                        },
                    )
            if runtime_model is not None:
                request["runtimeModel"] = runtime_model
            value = self._transport.request("session/send", request)
            receipt = _compact_public(value)
            if not isinstance(receipt, dict):
                receipt = {"value": receipt}
            receipt.update({"session_id": session_id, "accepted": True})
            return receipt
        payload: dict[str, Any] = {"sessionId": session_id, "content": content, "mode": mode}
        model = params.get("model") or params.get("modelId")
        if model is not None:
            payload["model"] = _safe_text(model, 240)
        value = self._call_variants(("turn/start", "session/prompt", "turn/create", "session.prompt"), payload)
        receipt = _compact_public(value)
        if not isinstance(receipt, dict):
            receipt = {"value": receipt}
        receipt["session_id"] = session_id
        receipt["accepted"] = bool(receipt.get("accepted", True))
        return receipt

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        value = self._transport.request("session/stop", {"sessionId": session_id}) if self._is_modern else self._call_variants(
            ("turn/interrupt", "session/cancel", "turn/cancel", "session.cancel"),
            {"sessionId": session_id},
        )
        result = _compact_public(value)
        if not isinstance(result, dict):
            result = {"value": result}
        result.update({"session_id": session_id, "accepted": bool(result.get("accepted", True))})
        return result

    def close_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Close one isolated session when the public app-server exposes it."""

        self._ensure_initialized()
        session_id = _session_id(params)
        if self._is_modern:
            value = self._transport.request("session/close", {"sessionId": session_id})
        else:
            value = self._call_variants(
                ("session/close", "thread/close", "session.close"),
                {"sessionId": session_id},
            )
        result = _compact_public(value)
        if not isinstance(result, dict):
            result = {"value": result}
        result.update({"session_id": session_id, "accepted": bool(result.get("accepted", True))})
        return result

    def search_sessions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            self._unsupported(AgentCapability.SESSION_SEARCH, "session search")
        params = params or {}
        query = _safe_text(params.get("query") or "", 500)
        if not query:
            raise AgentRuntimeError("session search query is required")
        value = self._call_variants(("session/search", "thread/search", "session.search"), {"query": query})
        return _compact_public(value) if isinstance(_compact_public(value), dict) else {"items": []}

    def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            self._unsupported(AgentCapability.SESSION_RENAME, "session rename")
        session_id = _session_id(params)
        title = _safe_text(params.get("title"), 240)
        if not title:
            raise AgentRuntimeError("session title is required")
        value = self._call_variants(("session/rename", "thread/rename", "session.rename"), {"sessionId": session_id, "title": title})
        return {"session_id": session_id, "title": _safe_text(_first(value, "title") or title, 240)}

    def session_models(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        if self._is_modern:
            value = self._workspace_state(params)
            return _normalize_models(_first(value, "modelCatalog") or {})
        value = self._call_variants(
            ("model/list", "session/models", "session.models"),
            {"sessionId": session_id},
        )
        return _normalize_models(value)

    def runtime_models(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read ZCode's public, session-independent model directory.

        This is intentionally separate from ``session_models``: policy
        preflight must be able to show a recommendation before it creates a
        confirmation-gated Session.  If a ZCode build only exposes a
        session-scoped method, the adapter returns an empty directory rather
        than creating a throwaway Session or guessing at private APIs.
        """

        try:
            self._initialize()
            if self._is_modern:
                value = self._workspace_state(params)
                return _normalize_models(_first(value, "modelCatalog") or {})
            value = self._call_variants(("models/list", "model/list", "models"), {})
        except AgentRuntimeError:
            return {"groups": []}
        return _normalize_models(value)

    def select_model(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        raw_model = params.get("modelRef") or params.get("model") or params.get("modelId")
        if raw_model is None or (isinstance(raw_model, str) and not raw_model.strip()):
            raise AgentRuntimeError("model is required")
        if self._is_modern:
            model_ref = self._modern_model_ref(raw_model, params)
            if model_ref is None:
                raise AgentRuntimeError("model provider and model id are required")
            value = self._transport.request(
                "session/setModel",
                {
                    "sessionId": session_id,
                    "model": model_ref,
                    "persistAsWorkspaceLastUsed": bool(params.get("persistAsWorkspaceLastUsed", True)),
                },
            )
            return {"session_id": session_id, "selected": _compact_public(value), "model": model_ref["modelId"], "model_ref": model_ref}
        model = _safe_text(raw_model, 240)
        if not model:
            raise AgentRuntimeError("model is required")
        value = self._call_variants(
            ("session/model", "model/select", "session.selectModel"),
            {"sessionId": session_id, "model": model},
        )
        return {"session_id": session_id, "selected": _compact_public(value), "model": model}

    def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        if self._is_modern:
            request: dict[str, Any] = {"sessionId": session_id, "target": {"kind": "latestCheckpoint"}}
            if isinstance(params.get("expectedRevision"), int) and params["expectedRevision"] >= 0:
                request["expectedRevision"] = params["expectedRevision"]
            value = self._transport.request("session/fork", request)
        else:
            value = self._call_variants(("session/fork", "thread/fork", "session.fork"), {"sessionId": session_id})
        child = _extract_id(value, ("forkedSessionId", "sessionId", "threadId", "id"))
        if not child:
            raise AgentRuntimeError("ZCode did not return a forked session id")
        return {"sessionId": child, "parent_session_id": session_id}

    def history(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        session_id = _session_id(params)
        if self._is_modern:
            request: dict[str, Any] = {"sessionId": session_id}
            if params.get("afterMessageId") or params.get("after_message_id"):
                request["afterMessageId"] = _safe_text(params.get("afterMessageId") or params.get("after_message_id"), 240)
            if isinstance(params.get("limit"), int) and params["limit"] > 0:
                request["limit"] = min(params["limit"], _MAX_RESPONSE_ITEMS)
            try:
                value = self._transport.request("session/messages", request)
            except ZCodeProtocolError as error:
                if error.code != -32004:
                    raise
                self._transport.request("session/resume", {"sessionId": session_id})
                value = self._transport.request("session/messages", request)
        else:
            value = self._call_variants(("session/history", "thread/read", "session.history"), {"sessionId": session_id})
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"session_id": session_id, "items": []}

    def attachment(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            self._unsupported(AgentCapability.ATTACHMENTS, "attachments")
        session_id = _session_id(params)
        attachment_id = _safe_text(params.get("attachmentId") or params.get("attachment_id"), 240)
        if not attachment_id:
            raise AgentRuntimeError("attachment id is required")
        value = self._call_variants(
            ("session/attachment", "attachment/get", "session.attachment"),
            {"sessionId": session_id, "attachmentId": attachment_id},
        )
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"session_id": session_id, "attachment_id": attachment_id}

    def queue(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            self._unsupported(AgentCapability.QUEUE, "queue inspection")
        session_id = _session_id(params)
        value = self._call_variants(("session/queue", "turn/queue", "session.queue"), {"sessionId": session_id})
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"session_id": session_id, "items": []}

    def update_queue(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            self._unsupported(AgentCapability.QUEUE, "queue mutation")
        session_id = _session_id(params)
        action = _safe_text(params.get("action") or params.get("kind"), 40).lower()
        if action not in {"edit", "remove", "steer"}:
            raise AgentRuntimeError("queue action must be edit, remove, or steer")
        item_id = _safe_text(params.get("itemId") or params.get("item_id"), 240)
        if not item_id:
            raise AgentRuntimeError("queue item id is required")
        payload = {"sessionId": session_id, "itemId": item_id, "action": action}
        if action == "edit":
            payload["text"] = _safe_text(params.get("text"), _MAX_TEXT)
            if not payload["text"]:
                raise AgentRuntimeError("queue edit text is required")
        value = self._call_variants(("session/queue/update", "session/updateQueue", "session.updateQueue"), payload)
        return {"session_id": session_id, "item_id": item_id, "action": action, "accepted": True, "result": _compact_public(value)}

    def list_subagents(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        parent = _session_id(params, names=("parentSessionId", "parent_session_id", "sessionId", "session_id"))
        if self._is_modern:
            request: dict[str, Any] = {"sessionId": parent}
            if params.get("endedCursor"):
                request["endedCursor"] = _safe_text(params["endedCursor"], 240)
            if isinstance(params.get("endedLimit"), int) and params["endedLimit"] > 0:
                request["endedLimit"] = min(params["endedLimit"], 100)
            value = self._transport.request("session/subagents", request)
            return _normalize_subagents(value, parent)
        value = self._call_variants(("subagent/list", "session/subagents", "subagent.list"), {"parentSessionId": parent})
        raw = _first_list(value, ("subagents", "items", "sessions", "data"))
        result = []
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            child = _extract_id(item, ("sessionId", "childSessionId", "id"))
            if child:
                result.append({"id": child, "state": _safe_text(_first(item, "state", "status"), 80) or "unknown", "title": _safe_text(_first(item, "title", "name"), 200)})
        return {"parent_session_id": parent, "subagents": result}

    def subagent_history(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
            child = _session_id(params, names=("childSessionId", "child_session_id"))
            return self.history({"sessionId": child, "limit": params.get("limit")}) | {
                "parent_session_id": parent,
                "child_session_id": child,
            }
        parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
        child = _session_id(params, names=("childSessionId", "child_session_id"))
        value = self._call_variants(("subagent/history", "session/history", "subagent.history"), {"parentSessionId": parent, "childSessionId": child})
        result = _compact_public(value)
        return result if isinstance(result, dict) else {"parent_session_id": parent, "child_session_id": child, "items": []}

    def prompt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            child = _session_id(params, names=("childSessionId", "child_session_id"))
            text = _safe_text(params.get("text"), _MAX_TEXT)
            if not text:
                raise AgentRuntimeError("subagent prompt text is required")
            result = self.prompt({"sessionId": child, "text": text, "mode": params.get("mode", "execute")})
            return {"accepted": True, "child_session_id": child, "result": result}
        parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
        child = _session_id(params, names=("childSessionId", "child_session_id"))
        text = _safe_text(params.get("text"), _MAX_TEXT)
        if not text:
            raise AgentRuntimeError("subagent prompt text is required")
        self._call_variants(("subagent/prompt", "session/prompt", "subagent.prompt"), {"parentSessionId": parent, "childSessionId": child, "content": [{"type": "text", "text": text}]})
        return {"accepted": True, "parent_session_id": parent, "child_session_id": child}

    def interrupt_subagent(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            child = _session_id(params, names=("childSessionId", "child_session_id"))
            self.cancel({"sessionId": child})
            return {"accepted": True, "child_session_id": child}
        parent = _session_id(params, names=("parentSessionId", "parent_session_id"))
        child = _session_id(params, names=("childSessionId", "child_session_id"))
        self._call_variants(("subagent/interrupt", "turn/interrupt", "subagent.interrupt"), {"parentSessionId": parent, "childSessionId": child})
        return {"accepted": True, "parent_session_id": parent, "child_session_id": child}

    def list_capabilities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            # The modern server intentionally has no catch-all capabilities
            # RPC.  Expose only methods whose public endpoints we verified.
            return {
                "available": True,
                "status": "derived-from-public-protocol",
                "skills": {"available": False, "status": "not-adapted"},
                "mcp": {"available": True, "status": "public-endpoint"},
                "subagents": {"available": True, "status": "public-endpoint"},
                "commands": {"available": False, "status": "not-adapted"},
            }
        del params
        try:
            value = self._call_variants(("capabilities", "capabilities/list", "host/capabilities"), {})
        except AgentRuntimeError as error:
            return {"available": False, "status": "unavailable", "error": str(error)}
        return {"available": True, "status": "observed", "entries": _compact_public(value)}

    def quota_status(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read quota only when ZCode advertises a public usage capability.

        ZCode owns its account and login state.  We never inspect its files or
        scrape a private web endpoint; an unadvertised quota remains unknown.
        """

        del params
        if not self.config.enabled:
            return {"state": "unknown", "source": "zcode-disabled", "detail": "ZCode runtime is disabled"}
        try:
            self._initialize()
        except AgentRuntimeError:
            return {"state": "unknown", "source": "zcode-unavailable", "detail": "ZCode app-server is unavailable"}
        if not any("quota" in name or "usage" in name for name in self._advertised_features):
            return {
                "state": "unknown",
                "source": "zcode-app-server-not-exposed",
                "detail": "ZCode app-server did not advertise a public quota method",
                "checked_at": utc_now(),
            }
        try:
            value = self._call_variants(
                ("quota/status", "quota.status", "usage/status", "account/usage"),
                {},
            )
        except ZCodeProtocolError as error:
            return {
                "state": "unknown",
                "source": "zcode-quota-rejected" if error.code != -32601 else "zcode-app-server-not-exposed",
                "detail": "public quota method was not available",
                "checked_at": utc_now(),
            }
        except AgentRuntimeError:
            return {"state": "unknown", "source": "zcode-quota-error", "detail": "quota request failed", "checked_at": utc_now()}
        return _compact_quota_status(value)

    def mcp_inventory(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_initialized()
        if self._is_modern:
            try:
                value = self._transport.request("mcp/list", {"workspace": self._workspace_descriptor(params)})
            except ZCodeProtocolError as error:
                return {"available": False, "status": "not-exposed" if error.code == -32601 else "rejected", "entries": [], "server_count": 0, "tool_count": 0}
            except AgentRuntimeError as error:
                return {"available": False, "status": "unavailable", "entries": [], "server_count": 0, "tool_count": 0, "reason": str(error)}
            return _normalize_mcp_statuses(value)
        del params
        try:
            value = self._call_variants(("mcp/list", "mcp/listServers", "mcp.list"), {})
        except ZCodeProtocolError as error:
            return {"available": False, "status": "not-exposed" if error.code == -32601 else "rejected", "entries": [], "server_count": 0, "tool_count": 0}
        except AgentRuntimeError as error:
            return {"available": False, "status": "unavailable", "entries": [], "server_count": 0, "tool_count": 0, "reason": str(error)}
        raw = _first_list(value, ("servers", "entries", "items", "data"))
        entries: list[dict[str, Any]] = []
        tool_count = 0
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            name = _safe_text(_first(item, "name", "id"), 160)
            if not name:
                continue
            tools = _first_list(item, ("tools",))
            compact_tools = [{"name": _safe_text(_first(tool, "name", "id"), 160)} for tool in tools[:128] if isinstance(tool, dict) and _safe_text(_first(tool, "name", "id"), 160)]
            tool_count += len(compact_tools)
            entries.append({"name": name, "status": _safe_text(_first(item, "status", "state"), 80) or "unknown", "tools": compact_tools})
        return {"available": True, "status": "observed", "entries": entries, "server_count": len(entries), "tool_count": tool_count}

    def respond(self, params: dict[str, Any]) -> dict[str, Any]:
        request_id = _safe_text(params.get("rpcId") or params.get("rpc_id") or params.get("requestId"), 240)
        if not request_id:
            raise AgentRuntimeError("ZCode interaction id is required")
        if not self._transport.alive:
            self._reset_after_transport_loss()
            raise AgentRuntimeError("ZCode interaction is no longer available", transport=True)
        with self._event_lock:
            if request_id not in self._pending_server_requests:
                raise AgentRuntimeError("ZCode interaction is no longer pending")
            self._pending_server_requests.remove(request_id)
        approved = params.get("approved") is True
        decision = _safe_text(params.get("decision"), 40).lower()
        if decision in {"allow", "deny", "escalate", "modify"}:
            approved = decision == "allow"
        try:
            result = {"decision": "allow" if approved else "deny"} if self._is_modern else {"approved": approved}
            self._transport.respond(request_id, result=result)
        except AgentRuntimeError:
            self._reset_after_transport_loss()
            raise
        return {"rpc_id": request_id, "accepted": True, "approved": approved, "decision": "allow" if approved else "deny"}

    def respond_interaction(self, params: dict[str, Any]) -> dict[str, Any]:
        """Bridge Sumika's approval/question envelope to ZCode's request id."""

        request_id = params.get("rpcId") or params.get("rpc_id") or params.get("requestId")
        if not request_id:
            raise AgentRuntimeError("interaction response requires rpcId")
        outcome = _safe_text(params.get("outcome"), 40).lower()
        answer = params.get("answer")
        if isinstance(answer, dict):
            # User-input requests expect a value/cancelled envelope rather
            # than a permission decision.
            value = answer.get("value") if "value" in answer else answer
            return self._respond_raw_interaction(str(request_id), {"value": value, "cancelled": bool(answer.get("cancelled", False))})
        return self._respond_raw_interaction(
            str(request_id),
            {"decision": "allow" if outcome in {"allowed-once", "allow", "approved"} else "deny"},
        )

    def _respond_raw_interaction(self, request_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self._event_lock:
            if request_id not in self._pending_server_requests:
                raise AgentRuntimeError("ZCode interaction is no longer pending")
            self._pending_server_requests.remove(request_id)
        self._transport.respond(request_id, result=result)
        return {"accepted": True, "rpc_id": request_id}

    def interactions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        with self._event_lock:
            return {"available": True, "interactions": [{"rpc_id": value, "status": "pending"} for value in sorted(self._pending_server_requests)]}

    def normalize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AgentRuntimeError("ZCode event must be an object")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else payload
        nested = params.get("event") if isinstance(params.get("event"), dict) else params
        method = _safe_text(
            nested.get("type")
            or nested.get("event")
            or (payload.get("method") if payload.get("method") != "session/event" else "")
            or "event",
            160,
        )
        event_type = _event_type(method)
        session_id = _extract_id(nested, ("sessionId", "session_id", "threadId", "thread_id"))
        turn_id = _extract_id(nested, ("turnId", "turn_id"))
        item_id = _extract_id(nested, ("itemId", "item_id", "messageId", "message_id", "partId", "part_id"))
        status = _safe_text(nested.get("status") or nested.get("state") or method, 100) or "unknown"
        text = nested.get("text") or nested.get("content") or nested.get("delta") or nested.get("response")
        content = _safe_text(text, 1200) if isinstance(text, str) else None
        extensions: dict[str, Any] = {"source": "zcode", "method": method}
        for key in ("tool", "approval", "plan", "metrics"):
            if isinstance(nested.get(key), dict):
                extensions[key] = _compact_public(nested[key], depth=2)
        if nested.get("requestId") is not None:
            extensions["request_id"] = _safe_text(nested.get("requestId"), 240)
        if payload.get("id") is not None and payload.get("method"):
            extensions["rpc_id"] = _safe_text(payload.get("id"), 240)
        return AgentEvent(
            event_type=event_type,
            session_id=session_id,
            turn_id=turn_id,
            item_id=item_id,
            status=status,
            content=content,
            extensions=extensions,
            timestamp=_safe_text(nested.get("timestamp"), 80) or utc_now(),
        ).to_dict()

    def set_event_sink(self, sink: Any) -> None:
        self._event_sink = sink

    def add_event_listener(self, listener: Any) -> Any:
        """Subscribe to normalized events without replacing Core's sink."""

        if not callable(listener):
            raise AgentRuntimeError("event listener must be callable")
        with self._event_lock:
            self._event_listeners.add(listener)

        def remove() -> None:
            with self._event_lock:
                self._event_listeners.discard(listener)

        return remove

    def bind_credential_store(self, credential_store: Any) -> None:
        # ZCode owns its login state.  Deliberately do not retain or inspect
        # Sumika's credential store here.
        del credential_store

    def close(self) -> None:
        self._transport.close()
        self._initialized = False
        self._modern_protocol = False
        self._last_health = None
        self._advertised_features = set()
        self._advertised_capabilities = None
        with self._event_lock:
            self._pending_server_requests.clear()
            self._event_listeners.clear()

    def _reset_after_transport_loss(self) -> None:
        if self._transport.alive:
            return
        self._initialized = False
        self._modern_protocol = False
        self._advertised_capabilities = None
        self._advertised_features = set()
        with self._event_lock:
            self._pending_server_requests.clear()

    def _initialize(self) -> None:
        if self._initialized and self._transport.alive:
            return
        self._modern_protocol = False
        self._advertised_features = set()
        self._advertised_capabilities = None

        # Current ZCode has no initialize method.  Probe its documented,
        # side-effect-free session/list endpoint first.  In auto mode a
        # response with a ``jsonrpc`` member identifies a legacy peer.
        if self.config.wire_protocol in {"auto", "zcode"}:
            try:
                probe = self._transport.request("session/list", {}, timeout=self.config.startup_timeout)
                if self._transport.wire_protocol == "zcode":
                    self._modern_protocol = True
                    self._initialized = True
                    self._advertised_features = {
                        "session/list",
                        "session/create",
                        "session/send",
                        "session/read",
                        "session/messages",
                        "session/subagents",
                        "session/fork",
                        "session/setModel",
                        "session/setMode",
                        "workspace/readState",
                        "mcp/list",
                    }
                    self._advertised_capabilities = {
                        AgentCapability.MODELS,
                        AgentCapability.SESSION_FORK,
                        AgentCapability.HISTORY,
                        AgentCapability.SUBAGENTS,
                        AgentCapability.PLAN,
                        AgentCapability.INTERACTIONS,
                        AgentCapability.EVENT_INGEST,
                        AgentCapability.MCP,
                    }
                    return
                # Legacy fixture/peer accepted the probe and returned a
                # standard JSON-RPC envelope.  Continue in the same process.
                if self.config.wire_protocol == "auto":
                    self._transport.set_wire_protocol("jsonrpc")
            except ZCodeProtocolError as error:
                if self.config.wire_protocol != "auto" or error.code not in {-32600, -32601}:
                    self._initialized = False
                    raise
                self._transport.set_wire_protocol("jsonrpc")
            except AgentRuntimeError:
                self._initialized = False
                raise

        if self.config.wire_protocol == "zcode":
            self._initialized = False
            raise AgentRuntimeError("ZCode app-server did not accept the modern session/list probe")
        try:
            value = self._transport.request(
                "initialize",
                {
                    "protocolVersion": "1",
                    "clientInfo": {"name": "sumika", "version": "2.x"},
                    "capabilities": {"events": True, "plans": True, "tools": True},
                },
                timeout=self.config.startup_timeout,
            )
        except AgentRuntimeError:
            self._initialized = False
            self._advertised_capabilities = None
            raise
        self._initialized = True
        self._advertised_features = _feature_names_from(value)
        self._advertised_capabilities = _capabilities_from(value)
        try:
            self._transport.notify("initialized", {})
        except AgentRuntimeError:
            # Some app-servers complete initialization with the response and
            # do not accept the optional notification.
            pass

    def _call_variants(self, methods: tuple[str, ...], params: dict[str, Any]) -> Any:
        last: ZCodeProtocolError | None = None
        for method in methods:
            try:
                return self._transport.request(method, params)
            except ZCodeProtocolError as error:
                if error.code in {-32600, -32601}:
                    last = error
                    continue
                raise
        if last is not None:
            raise last
        raise AgentRuntimeError("ZCode method list is empty")

    def _on_message(self, payload: dict[str, Any]) -> None:
        # ``session/create`` asks the client for runtime materialization
        # preferences before it returns.  These defaults are deliberately
        # conservative and contain no credentials or user content.
        if payload.get("method") == "session/requestRuntimePreferences" and payload.get("id") is not None:
            request_id = _safe_text(payload.get("id"), 240)
            if request_id:
                try:
                    self._transport.respond(
                        request_id,
                        result={
                            "nativeSearchEnhancementsEnabled": True,
                            "memoryEnabled": False,
                            "askUserQuestionAutoResolutionEnabled": True,
                            "modelContextBudgetStrategy": "preflight-v1",
                        },
                    )
                except AgentRuntimeError as error:
                    if self.logger:
                        self.logger.info("zcode runtime preferences response failed error_type=%s", type(error).__name__)
            return
        # A request from the server (rather than a response to our request)
        # must wait for an explicit user/Core decision.
        if payload.get("id") is not None and payload.get("method"):
            request_id = _safe_text(payload.get("id"), 240)
            if request_id:
                with self._event_lock:
                    self._pending_server_requests.add(request_id)
        try:
            event = self.normalize_event(payload)
        except AgentRuntimeError:
            return
        with self._event_lock:
            sink = self._event_sink
            listeners = tuple(self._event_listeners)
        if sink is not None:
            try:
                sink(event)
            except Exception as error:
                if self.logger:
                    self.logger.info("zcode event sink failed error_type=%s", type(error).__name__)
        for listener in listeners:
            try:
                listener(event)
            except Exception as error:
                if self.logger:
                    self.logger.info("zcode event listener failed error_type=%s", type(error).__name__)

    def supports(self, capability: AgentCapability | str) -> bool:
        try:
            value = capability if isinstance(capability, AgentCapability) else AgentCapability(capability)
        except ValueError:
            return False
        if self._advertised_capabilities is None:
            return value in self.capability_ids
        return value in self.capability_ids or value in self._advertised_capabilities

    def runtime_capabilities(self) -> list[str]:
        values = set(self.capability_ids)
        if self._advertised_capabilities:
            values.update(self._advertised_capabilities)
        return sorted(item.value for item in values)


def _safe_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        text = text[:limit]
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    return text


def _sanitize_runtime_message(value: Any, limit: int = 600) -> str:
    """Keep actionable protocol errors while hiding user-specific paths."""

    text = _safe_text(value, limit)
    if not text:
        return ""
    # ZCode's missing-config error includes the absolute home directory.  A
    # runtime error must not turn that path into an API/UI data leak.
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<local-path>", text)
    text = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s\"']+/)+[^\s\"']+", "<local-path>", text)
    return text


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _first(value: Any, *keys: str) -> Any:
    if not isinstance(value, dict):
        return None
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def _first_list(value: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
    return []


def _extract_id(value: Any, keys: tuple[str, ...]) -> str:
    for key in keys:
        candidate = _first(value, key)
        text = _safe_text(candidate, 240)
        if text:
            return text
    return ""


def _session_id(params: Mapping[str, Any], *, names: tuple[str, ...] = ("sessionId", "session_id", "threadId", "thread_id")) -> str:
    for name in names:
        value = _safe_text(params.get(name), 240)
        if value:
            return value
    raise AgentRuntimeError("session id is required")


def _session_payload(params: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source, target, limit in (
        ("title", "title", 240),
        ("cwd", "cwd", 4096),
        ("workspaceId", "workspaceId", 240),
        ("workspace_id", "workspaceId", 240),
        ("agentPreset", "agentPreset", 160),
        ("agent_preset", "agentPreset", 160),
        ("model", "model", 240),
    ):
        if params.get(source) is not None:
            value = _safe_text(params.get(source), limit)
            if value:
                result[target] = value
    return result


def _prompt_content(params: Mapping[str, Any]) -> list[dict[str, str]]:
    content = params.get("content")
    if isinstance(content, list):
        result: list[dict[str, str]] = []
        for block in content[:32]:
            if not isinstance(block, dict):
                continue
            kind = _safe_text(block.get("type") or "text", 40)
            text = _safe_text(block.get("text"), _MAX_TEXT)
            if kind == "text" and text:
                result.append({"type": "text", "text": text})
        if result:
            return result
    text = _safe_text(params.get("text"), _MAX_TEXT)
    if not text:
        raise AgentRuntimeError("Agent prompt requires non-empty text or content")
    return [{"type": "text", "text": text}]


def _compact_public(value: Any, *, depth: int = 3) -> Any:
    """Bound app-server data before it can reach UI events or audit logs."""

    if depth <= 0:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:128]:
            name = _safe_text(key, 100)
            lowered = name.lower()
            if any(token in lowered for token in ("token", "secret", "password", "cookie", "authorization", "api_key", "apikey")):
                result[name] = "[redacted]"
                continue
            if lowered in {"prompt", "messages", "raw", "body", "stdout", "stderr"}:
                if isinstance(item, list):
                    result[name] = {"count": min(len(item), _MAX_RESPONSE_ITEMS)}
                else:
                    result[name] = "[omitted]"
                continue
            result[name] = _compact_public(item, depth=depth - 1)
        return result
    if isinstance(value, list):
        return [_compact_public(item, depth=depth - 1) for item in value[:_MAX_RESPONSE_ITEMS]]
    if isinstance(value, str):
        return _safe_text(value, 1200)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _normalize_models(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"groups": []}

    groups: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    def ensure_group(provider_id: Any, provider_name: Any) -> dict[str, Any]:
        group_id = _safe_text(provider_id, 120) or "zcode"
        group = by_id.get(group_id)
        if group is None:
            group = {
                "id": group_id,
                "name": _safe_text(provider_name, 160) or group_id,
                "models": [],
            }
            by_id[group_id] = group
            groups.append(group)
        elif (
            group.get("name") == group_id
            and _safe_text(provider_name, 160)
        ):
            group["name"] = _safe_text(provider_name, 160)
        return group

    def add_model(group: dict[str, Any], model_id: Any, model_name: Any) -> None:
        identifier = _safe_text(model_id, 240)
        if not identifier:
            return
        models = group["models"]
        if any(item.get("id") == identifier for item in models):
            return
        models.append(
            {
                "id": identifier,
                "name": _safe_text(model_name, 240) or identifier,
            }
        )

    raw_groups = _first_list(value, ("groups", "providers", "data"))
    # Some legacy peers return a flat ``models`` array.  Keep that shape
    # compatible while avoiding treating modern ``available`` options as
    # provider groups.
    flat_models = value.get("models")
    if isinstance(flat_models, list) and all(
        isinstance(item, dict) and ("id" in item or "modelId" in item)
        for item in flat_models
    ):
        raw_groups = [*raw_groups, {"id": "zcode", "name": "ZCode", "models": flat_models}]

    for raw_group in raw_groups[:64]:
        if not isinstance(raw_group, dict):
            continue
        provider_id = _first(raw_group, "id", "providerId")
        provider_name = _first(raw_group, "name", "label")
        group = ensure_group(provider_id, provider_name)
        models = _first_list(raw_group, ("models", "items"))
        for model in models[:128]:
            if not isinstance(model, dict):
                continue
            add_model(
                group,
                _first(model, "id", "modelId", "name"),
                _first(model, "name", "label") or _first(model, "id", "modelId"),
            )

    # Modern workspace state exposes a flattened ``available`` catalog.  It
    # is the authoritative directory when provider configs are omitted (for
    # example while a workspace is still materializing), so project it into
    # the same stable provider/model groups used by the UI.
    available = value.get("available")
    if isinstance(available, list):
        for option in available[: _MAX_RESPONSE_ITEMS]:
            if not isinstance(option, dict):
                continue
            reference = option.get("ref") if isinstance(option.get("ref"), dict) else option
            provider_id = _first(reference, "providerId", "provider_id", "provider")
            model_id = _first(reference, "modelId", "model_id", "id")
            if not provider_id or not model_id:
                continue
            group = ensure_group(
                provider_id,
                _first(option, "providerLabel", "providerName") or provider_id,
            )
            add_model(group, model_id, _first(option, "label", "name") or model_id)

    return {
        "groups": [
            group
            for group in groups
            if isinstance(group.get("models"), list) and group["models"]
        ]
    }


def _normalize_subagents(value: Any, parent_session_id: str) -> dict[str, Any]:
    """Project the modern ``session/subagents`` shape into Sumika's API."""

    payload = value if isinstance(value, dict) else {}
    result: list[dict[str, Any]] = []
    for key, status in (("running", "running"), ("ended", "ended")):
        raw = payload.get(key)
        if isinstance(raw, dict):
            raw = raw.get("items", [])
        if not isinstance(raw, list):
            continue
        for item in raw[:_MAX_RESPONSE_ITEMS]:
            if not isinstance(item, dict):
                continue
            child = _extract_id(item, ("childSessionId", "sessionId", "id"))
            if not child:
                continue
            result.append(
                {
                    "id": child,
                    "state": _safe_text(_first(item, "status", "state"), 80) or status,
                    "title": _safe_text(_first(item, "title", "name"), 200),
                    "summary": _safe_text(_first(item, "summary", "description"), 600) or None,
                }
            )
    return {
        "parent_session_id": parent_session_id,
        "subagents": result,
        "child_session_ids": [item["id"] for item in result][: _MAX_RESPONSE_ITEMS],
        "revision": _safe_scalar(payload.get("revision")) or 0,
    }


def _normalize_mcp_statuses(value: Any) -> dict[str, Any]:
    """Compact modern ``mcp/list`` statuses without exposing configuration."""

    payload = value if isinstance(value, dict) else {}
    statuses = payload.get("statuses")
    if not isinstance(statuses, dict):
        statuses = {}
    entries: list[dict[str, Any]] = []
    for raw_name, raw_status in list(statuses.items())[:_MAX_RESPONSE_ITEMS]:
        name = _safe_text(raw_name, 160)
        if not name or not isinstance(raw_status, dict):
            continue
        entry: dict[str, Any] = {
            "name": name,
            "status": _safe_text(raw_status.get("status"), 80) or "unknown",
            "transport": _safe_text(raw_status.get("transport"), 40) or None,
            "tool_count": 0,
        }
        if raw_status.get("toolCount") is not None:
            count = raw_status.get("toolCount")
            if isinstance(count, int) and count >= 0:
                entry["tool_count"] = min(count, _MAX_RESPONSE_ITEMS)
        if isinstance(raw_status.get("error"), str):
            entry["error"] = _safe_text(raw_status["error"], 240)
        entries.append(entry)
    return {
        "available": True,
        "status": "observed",
        "entries": entries,
        "server_count": len(entries),
        "tool_count": sum(int(item.get("tool_count") or 0) for item in entries),
    }


def _capabilities_from(value: Any) -> set[AgentCapability]:
    names = list(_feature_names_from(value))
    result: set[AgentCapability] = set()
    aliases = {
        "mcp": AgentCapability.MCP,
        "skills": AgentCapability.SKILLS,
        "subagents": AgentCapability.SUBAGENTS,
        "plan": AgentCapability.PLAN,
        "readonly": AgentCapability.READONLY,
        "attachments": AgentCapability.ATTACHMENTS,
        "models": AgentCapability.MODELS,
        "interactions": AgentCapability.INTERACTIONS,
    }
    for name in names:
        normalized = name.strip().lower().replace("_", "-")
        if normalized in aliases:
            result.add(aliases[normalized])
        else:
            try:
                result.add(AgentCapability(normalized))
            except ValueError:
                continue
    return result


def _feature_names_from(value: Any) -> set[str]:
    """Extract advertised feature/method names without trusting arbitrary data."""

    names: set[str] = set()
    containers = {"capabilities", "features", "methods", "operations", "supportedmethods", "supported_methods"}

    def visit(raw: Any, *, allow_enabled_keys: bool = False, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(raw, list):
            for item in raw[:128]:
                if isinstance(item, str) and item.strip():
                    names.add(item.strip().lower().replace("_", "-"))
                elif isinstance(item, (dict, list)):
                    visit(item, allow_enabled_keys=allow_enabled_keys, depth=depth + 1)
            return
        if not isinstance(raw, dict):
            return
        for key, item in list(raw.items())[:128]:
            normalized = str(key).strip().lower().replace("-", "")
            if normalized in {name.replace("-", "") for name in containers}:
                visit(item, allow_enabled_keys=True, depth=depth + 1)
            elif allow_enabled_keys and item is True:
                name = str(key).strip().lower().replace("_", "-")
                if name:
                    names.add(name)
            elif allow_enabled_keys and isinstance(item, (dict, list)):
                visit(item, allow_enabled_keys=True, depth=depth + 1)

    visit(value)
    return names


def _compact_quota_status(value: Any) -> dict[str, Any]:
    """Keep only non-sensitive, bounded quota fields from a public response."""

    payload = value if isinstance(value, dict) else {}
    nested = payload
    for key in ("quota", "usage", "data"):
        if isinstance(payload.get(key), dict):
            nested = payload[key]
            break
    allowed_states = {"available", "low", "exhausted", "expired", "needs-auth", "blocked", "unknown"}
    state = str(nested.get("state") or nested.get("status") or "unknown").strip().lower()
    if state in {"ok", "ready", "active"}:
        state = "available"
    if state not in allowed_states:
        state = "unknown"
    result: dict[str, Any] = {
        "state": state,
        "source": "zcode-app-server",
        "checked_at": utc_now(),
    }
    for source, target in (("remaining", "remaining"), ("remaining_min", "remaining_min"), ("remaining_max", "remaining_max"), ("used", "used"), ("total", "total")):
        number = nested.get(source)
        if isinstance(number, (int, float)) and not isinstance(number, bool) and number >= 0:
            result[target] = float(number)
    remaining = result.get("remaining", result.get("remaining_min"))
    total = result.get("total")
    if state == "unknown" and isinstance(remaining, (int, float)):
        state = "exhausted" if remaining <= 0 else "low" if isinstance(total, (int, float)) and total > 0 and remaining / total < 0.1 else "available"
        result["state"] = state
    unit = nested.get("unit")
    if isinstance(unit, str) and unit.strip():
        result["unit"] = _safe_text(unit, 40)
    expires_at = nested.get("expires_at")
    if isinstance(expires_at, str) and expires_at.strip():
        result["expires_at"] = _safe_text(expires_at, 120)
    if nested.get("requires_auth") is True:
        result["requires_auth"] = True
    return result


def _event_type(method: str) -> str:
    value = method.lower().replace("/", ".")
    if "approval" in value or "permission" in value:
        return "approval/requested"
    if "question" in value or "input" in value:
        return "question/requested"
    if "error" in value or "failed" in value:
        return "session/event"
    if any(token in value for token in ("item", "message", "part", "model", "tool", "turn", "session", "checkpoint", "rewind")):
        return "session/event"
    return "runtime/event"


__all__ = ["ZCodeAgentRuntime", "ZCodeProtocolError"]
