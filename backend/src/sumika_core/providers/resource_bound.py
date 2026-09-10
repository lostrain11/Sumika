from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .guard import RequestNotSent


class ResourceBoundProvider:
    """Reserve before sending, never turn depleted prepaid allowance into cash."""

    def __init__(self, provider, coordinator, profile_id, model_id, recheck):
        self.provider = provider
        self.coordinator = coordinator
        self.profile_id = profile_id
        self.model_id = model_id
        self.recheck = recheck
        self.last_resource_receipt = None

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def stream(self, request):
        try:
            self.recheck()
            if any(not isinstance(message.content, str) for message in request.messages):
                raise ValueError("resource bound requires a text-only request")
            if type(request.max_tokens) is not int or not 0 < request.max_tokens <= 1000000:
                raise ValueError("resource bound requires an explicit output limit")
            payload = [message.wire_dict() if hasattr(message, "wire_dict") else {"role": message.role, "content": message.content} for message in request.messages]
            input_bound = len(json.dumps({"messages": payload, "tools": request.tools}, ensure_ascii=False, allow_nan=False).encode("utf-8")) + 1024
            deadline = datetime.now(timezone.utc) + timedelta(seconds=max(120, float(self.provider.timeout) + 30))
            attempt_id = "resource-" + uuid4().hex
            projection = self.coordinator.quota_projection(self.model_id, self.profile_id) or {}
            unit = projection.get("unit", "tokens")
            self.last_resource_receipt = self.coordinator.reserve(
                attempt_id, self.profile_id, self.model_id, 1 if unit == "requests" else input_bound + request.max_tokens,
                unit=unit, valid_until=deadline.isoformat(),
            )
        except Exception:
            raise RequestNotSent("resource preflight failed; refresh or verify allowance before retrying") from None
        completed = False
        definitely_not_sent = False
        response_started = False
        stream = None
        try:
            stream = iter(self.provider.stream(request))
            for chunk in stream:
                response_started = True
                yield chunk
            completed = True
        except RequestNotSent:
            if response_started:
                raise RuntimeError("provider state uncertain after partial response") from None
            definitely_not_sent = True
            raise
        finally:
            try:
                if stream is not None and callable(getattr(stream, "close", None)):
                    stream.close()
            finally:
                usage = getattr(self.provider, "last_usage", {}) if completed else {}
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")
                actual = input_tokens + output_tokens if type(input_tokens) is int and type(output_tokens) is int and min(input_tokens, output_tokens) >= 0 else None
                if completed and unit == "requests":
                    actual = 1
                self.coordinator.settle(attempt_id, actual=actual, definitely_not_sent=definitely_not_sent)

    def health_check(self, *, allow_chat_probe=False):
        self.recheck()
        result = self.provider.health_check(allow_chat_probe=False)
        if allow_chat_probe and not result.get("ok"):
            result = {**result, "chat_probe_blocked": "resource-bound-route-requires-bounded-evaluation"}
        return result
