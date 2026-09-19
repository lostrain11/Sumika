"""OpenAI-compatible cloud role provider with no automatic fallback.

The API key is read from a named environment variable at call time and is never
stored in settings, reports or logs. Failures are classified and surfaced with
the operation outcome left unknown when the provider state is not confirmed.
"""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse


class CloudError(RuntimeError):
    def __init__(self, kind, message, *, retryable=False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


_STATUS_KINDS = {400: "bad_request", 401: "auth", 403: "auth",
                 404: "bad_request", 429: "rate_limit"}
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def image_parts(images, *, max_images=8, max_bytes=20_000_000):
    """Validate optional images and return OpenAI-compatible content parts."""
    if images is None:
        return []
    if not isinstance(images, (list, tuple)) or not images:
        raise ValueError("images must be a nonempty list")
    if len(images) > max_images:
        raise ValueError("too many images")
    parts = []
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("invalid image entry")
        media_type = image.get("media_type")
        data = image.get("data_base64")
        if media_type not in IMAGE_TYPES:
            raise ValueError("unsupported image type")
        if not isinstance(data, str) or not data:
            raise ValueError("image data required")
        if len(data) * 3 // 4 > max_bytes:
            raise ValueError("image exceeds size limit")
        parts.append({"type": "image_url",
                      "image_url": {"url": f"data:{media_type};base64,{data}"}})
    return parts


class CloudProvider:
    def __init__(self, endpoint, *, key_env, enabled=True, timeout=180):
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint required")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("cloud endpoint must be https")
        if parsed.username or parsed.password:
            raise ValueError("cloud endpoint must not embed credentials")
        if not isinstance(key_env, str) or not key_env.strip():
            raise ValueError("key environment name required")
        if type(enabled) is not bool:
            raise ValueError("invalid enabled flag")
        if type(timeout) is not int or timeout < 1 or timeout > 900:
            raise ValueError("invalid timeout")
        self.endpoint = endpoint.rstrip("/")
        self.key_env = key_env
        self.enabled = enabled
        self.timeout = timeout

    def _key(self):
        if not self.enabled:
            raise CloudError("disabled", "cloud provider disabled")
        value = os.environ.get(self.key_env)
        if not value:
            raise CloudError("missing_key", f"{self.key_env} is not set in the process environment")
        return value

    def _request(self, path, *, payload=None, method=None):
        headers = {"Authorization": "Bearer " + self._key()}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.endpoint + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf8"))
        except urllib.error.HTTPError as error:
            kind = _STATUS_KINDS.get(error.code, "http_error")
            raise CloudError(kind, f"provider returned HTTP {error.code}",
                             retryable=error.code >= 500) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CloudError("unavailable", "provider outcome unknown", retryable=True) from error
        except ValueError as error:
            raise CloudError("bad_response", "provider returned invalid JSON") from error

    def health(self):
        try:
            value = self._request("/models", method="GET")
        except CloudError as error:
            return {"status": "unavailable", "kind": error.kind, "endpoint": self.endpoint}
        models = value.get("data") if isinstance(value, dict) else None
        if not isinstance(models, list):
            return {"status": "unknown", "reason": "invalid model inventory", "endpoint": self.endpoint}
        return {"status": "ready", "endpoint": self.endpoint,
                "models": [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]}

    def generate(self, *, model, messages, max_tokens=1024, temperature=0.7, images=None,
                 max_images=8, max_image_bytes=20_000_000):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model required")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages required")
        if type(max_tokens) is not int or max_tokens < 1 or max_tokens > 32768:
            raise ValueError("invalid max tokens")
        if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("invalid temperature")
        parts = image_parts(images, max_images=max_images, max_bytes=max_image_bytes)
        if parts:
            last = messages[-1]
            if last.get("role") != "user" or not isinstance(last.get("content"), str):
                raise ValueError("images require a final user message with text content")
            messages = messages[:-1] + [{"role": "user",
                                         "content": [{"type": "text", "text": last["content"]}] + parts}]
        payload = {"model": model, "messages": messages, "stream": False,
                   "temperature": temperature, "max_tokens": max_tokens}
        value = self._request("/chat/completions", payload=payload)
        choices = value.get("choices") if isinstance(value, dict) else None
        if not isinstance(choices, list) or not choices:
            raise CloudError("bad_response", "provider returned no choices")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise CloudError("bad_response", "provider returned no assistant text")
        usage = value.get("usage") if isinstance(value.get("usage"), dict) else {}
        if any(key in usage for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
            status = "reported"
        else:
            status = "unknown"
        return {"text": text, "provider": "openai-compatible", "model": value.get("model", model),
                "finish_reason": choice.get("finish_reason"), "usage_status": status,
                "usage": {key: usage.get(key) for key in
                          ("prompt_tokens", "completion_tokens", "total_tokens") if key in usage}}
