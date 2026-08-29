from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, ProxyHandler, build_opener, urlopen

from ..protocol.models import ChatRequest, ProviderInfo
from .base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible chat completions client using only the stdlib.

    It accepts both SSE streaming responses and a regular JSON response, so it
    can talk to common cloud gateways and local servers such as Ollama proxies.
    """

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        api_key: str | None = None,
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
        ollama: bool | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.headers = dict(headers or {})
        # A non-default Ollama port is common when the user's tray service is
        # already occupied.  Provider profiles therefore pass an explicit
        # template hint instead of making the protocol decision from port
        # 11434 alone.  ``None`` keeps backwards-compatible URL inference for
        # callers that construct this provider directly.
        self._ollama_hint = ollama
        self.info = ProviderInfo(
            id="openai-compatible",
            name="OpenAI-compatible",
            status="unconfigured",
            description="连接 Ollama 或其他兼容 OpenAI API 的真实模型服务。",
            config_schema={
                "type": "object",
                "required": ["base_url", "model"],
                "properties": {
                    "base_url": {"type": "string", "title": "服务地址", "format": "uri"},
                    "model": {"type": "string", "title": "模型"},
                    "api_key": {"type": "string", "title": "API Key", "format": "password"},
                    "timeout": {"type": "number", "title": "超时（秒）", "minimum": 1},
                },
            },
        )

    def _is_local(self) -> bool:
        return "127.0.0.1" in self.base_url or "localhost" in self.base_url

    def _is_ollama(self) -> bool:
        if self._ollama_hint is not None:
            return self._ollama_hint
        parsed = urlparse(self.base_url)
        return self._is_local() and parsed.port == 11434 and parsed.path.rstrip("/") in {"", "/v1"}

    def _open(self, request: Request, *, timeout: float | None = None):
        """Open a request without proxying loopback traffic through a VPN."""
        if self._is_local():
            return build_opener(ProxyHandler({})).open(request, timeout=timeout or self.timeout)
        return urlopen(request, timeout=timeout or self.timeout)

    def configure(self, config: dict[str, object]) -> None:
        base_url = config.get("base_url")
        model = config.get("model")
        timeout = config.get("timeout")
        api_key = config.get("api_key")
        headers = config.get("headers")
        ollama = config.get("ollama")
        if isinstance(base_url, str) and base_url.strip():
            self.base_url = base_url.rstrip("/")
        if isinstance(model, str) and model.strip():
            self.model = model
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout >= 1:
            self.timeout = float(timeout)
        if isinstance(api_key, str) and api_key:
            self.api_key = api_key
        if isinstance(headers, dict) and all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items()):
            self.headers = dict(headers)
        if isinstance(ollama, bool):
            self._ollama_hint = ollama
        self.info.status = "unconfigured"

    def _request_headers(self, *, accept: str, content_type: str | None = None) -> dict[str, str]:
        headers = dict(self.headers)
        headers["Accept"] = accept
        if content_type:
            headers["Content-Type"] = content_type
        if self.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health_check(self, *, allow_chat_probe: bool = False) -> dict[str, object]:
        """Check endpoint/model availability without silently spending tokens.

        Most services expose ``GET /models``.  A few compatible gateways do
        not; only an explicit user-triggered check may send the bounded
        ``max_tokens=1`` chat probe in that case.
        """
        if not self.base_url or not self.model:
            self.info.status = "unconfigured"
            return {
                "ok": False,
                "provider_id": self.info.id,
                "status": "unconfigured",
                "error": "provider is not configured",
            }
        headers = self._request_headers(accept="application/json")
        request = Request(f"{self.base_url}/models", headers=headers, method="GET")
        try:
            with self._open(request, timeout=min(self.timeout, 5.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # A number of legitimate OpenAI-compatible gateways intentionally
            # omit GET /models.  A user-triggered health check may perform one
            # bounded, content-free chat probe in that case.  Authentication
            # and other HTTP failures remain errors and never fall back.
            if allow_chat_probe and exc.code in {404, 405}:
                return self._health_chat_probe(headers)
            if exc.code in {404, 405}:
                self.info.status = "unconfigured"
                return {
                    "ok": False,
                    "provider_id": self.info.id,
                    "status": "unconfigured",
                    "model": self.model,
                    "error": "model catalogue unavailable; run an explicit connection test",
                }
            self.info.status = "error"
            return {
                "ok": False,
                "provider_id": self.info.id,
                "status": "error",
                "error": f"HTTP {exc.code}",
            }
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            self.info.status = "error"
            return {
                "ok": False,
                "provider_id": self.info.id,
                "status": "error",
                "error": "connection failed",
                "detail": str(getattr(exc, "reason", exc))[:200],
            }
        models = payload.get("data") if isinstance(payload, dict) else None
        model_ids = {
            str(item.get("id"))
            for item in models or []
            if isinstance(item, dict) and item.get("id")
        }
        if self.model not in model_ids:
            self.info.status = "unconfigured"
            return {
                "ok": False,
                "provider_id": self.info.id,
                "status": "unconfigured",
                "model": self.model,
                "available_models": sorted(model_ids),
                "error": "model not found",
            }
        self.info.status = "available"
        return {
            "ok": True,
            "provider_id": self.info.id,
            "status": "available",
            "model": self.model,
            "base_url": self.base_url,
        }

    def _health_chat_probe(self, headers: dict[str, str]) -> dict[str, object]:
        """Validate a provider whose API does not expose a model catalogue."""

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        probe = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._request_headers(accept="application/json", content_type="application/json"),
            method="POST",
        )
        try:
            with self._open(probe, timeout=min(self.timeout, 8.0)) as response:
                body = response.read()
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"HTTP {response.status}")
                # Validate JSON when the gateway advertises it, but do not
                # require a particular response shape across vendors.
                if body:
                    content_type = str(response.headers.get("Content-Type") or "").lower()
                    if "json" in content_type:
                        json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            self.info.status = "error"
            return {
                "ok": False,
                "provider_id": self.info.id,
                "status": "error",
                "error": f"HTTP {exc.code}",
            }
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            self.info.status = "error"
            return {
                "ok": False,
                "provider_id": self.info.id,
                "status": "error",
                "error": "connection failed",
                "detail": str(getattr(exc, "reason", exc))[:200],
            }
        self.info.status = "available"
        return {
            "ok": True,
            "provider_id": self.info.id,
            "status": "available",
            "model": self.model,
            "base_url": self.base_url,
            "model_catalog": "not-exposed",
            "health_probe": "chat-completions",
        }

    def stream(self, request: ChatRequest) -> Iterable[str]:
        if self._is_ollama():
            yield from self._stream_ollama(request)
            return
        payload = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        headers = self._request_headers(accept="text/event-stream", content_type="application/json")
        http_request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._open(http_request) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type:
                    body = json.loads(response.read().decode("utf-8"))
                    text = _extract_content(body)
                    if text:
                        yield text
                    return
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data:"):
                        text = _extract_content(json.loads(line[5:].strip()))
                        if text:
                            yield text
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI-compatible connection failed: {exc.reason}") from exc

    def _stream_ollama(self, request: ChatRequest) -> Iterable[str]:
        """Use Ollama's OpenAI endpoint and hide Qwen3 reasoning deltas."""
        payload = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
            "temperature": request.temperature,
            # Qwen3 reasoning is returned separately with ``think=low``. Give
            # that hidden channel a modest floor so it cannot consume the
            # entire user-visible answer budget.
            "max_tokens": max(request.max_tokens, 1024),
            "stream": True,
            "think": "low",
        }
        headers = self._request_headers(accept="text/event-stream", content_type="application/json")
        native_request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            visible = _ThinkFilter()
            with self._open(native_request) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type:
                    body = json.loads(response.read().decode("utf-8"))
                    content = _extract_content(body)
                    if content:
                        yield from visible.feed(content)
                    yield from visible.finish()
                    return
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data:"):
                        value = json.loads(line[5:].strip())
                        content = _extract_content(value)
                        if content:
                            yield from visible.feed(content)
                yield from visible.finish()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail[:500]}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama connection failed: {getattr(exc, 'reason', exc)}") from exc


def _extract_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    choice = choices[0]
    delta = choice.get("delta") or {}
    if isinstance(delta.get("content"), str):
        return delta["content"]
    message = choice.get("message") or {}
    return message.get("content", "") if isinstance(message.get("content"), str) else ""


class _ThinkFilter:
    """Remove Qwen-style reasoning tags without delaying normal text chunks."""

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._thinking = False

    def feed(self, chunk: str) -> Iterable[str]:
        self._buffer += chunk
        while self._buffer:
            marker = self._CLOSE if self._thinking else self._OPEN
            index = self._buffer.find(marker)
            if index >= 0:
                if not self._thinking and index:
                    yield self._buffer[:index]
                self._buffer = self._buffer[index + len(marker) :]
                self._thinking = not self._thinking
                continue
            # Retain a possible partial marker across network chunks.
            keep = max(len(marker) - 1, 0)
            if self._thinking:
                # Reasoning is never user-visible. Discard everything except
                # a suffix that could become the closing marker next time.
                self._buffer = self._buffer[-keep:] if keep else ""
            elif len(self._buffer) > keep:
                yield self._buffer[:-keep] if keep else self._buffer
                self._buffer = self._buffer[-keep:] if keep else ""
            break

    def finish(self) -> Iterable[str]:
        if not self._thinking and self._buffer:
            yield self._buffer
        self._buffer = ""
