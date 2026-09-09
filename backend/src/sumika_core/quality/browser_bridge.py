from __future__ import annotations

import threading
import time
from typing import Any
from uuid import uuid4

from quality_routing import RoutingError, Scope

from ..browser import looks_like_secret_text


class ConsultationBridge:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._attached_at = 0.0
        self._token = uuid4().hex
        self._requests: dict[str, dict[str, Any]] = {}
        self._closed = False

    @property
    def available(self) -> bool:
        return not self._closed and time.monotonic() - self._attached_at < 15

    def attach(self) -> dict[str, str]:
        with self._condition:
            self._attached_at = time.monotonic()
            return {"token": self._token, "profile": "chatgpt"}

    def poll(self, token: str, *, accept_requests: bool = True) -> dict[str, Any]:
        if type(accept_requests) is not bool:
            raise RoutingError("accept_requests must be boolean")
        with self._condition:
            if token != self._token or self._closed:
                raise RoutingError("native bridge not attached")
            self._attached_at = time.monotonic()
            pending = next((item for item in self._requests.values() if item["status"] == "queued"), None) if accept_requests else None
            if pending:
                pending["status"] = "running"
                return {"request": {key: pending[key] for key in ("attempt_id", "question", "owner_id", "session_id")}}
            return {"request": None}

    def complete(self, token: str, attempt_id: str, result: dict[str, Any]) -> dict[str, bool]:
        with self._condition:
            if token != self._token:
                raise RoutingError("native bridge not attached")
            item = self._requests.get(attempt_id)
            if not item or item["status"] != "running":
                return {"accepted": False}
            status = result.get("status")
            if status not in {"completed", "failed", "unknown", "cancelled", "login-required", "challenge", "limited", "takeover"}:
                raise RoutingError("invalid native result status")
            text = result.get("text", "")
            if not isinstance(text, str) or len(text) > 64000 or looks_like_secret_text(text):
                raise RoutingError("native result rejected")
            item["result"] = {"status": status, "text": text, "possibly_sent": result.get("possibly_sent") is True}
            item["status"] = "done"
            self._condition.notify_all()
            return {"accepted": True}

    def consult(self, scope: Scope, question: str, cancelled: threading.Event, timeout: float = 120) -> dict[str, Any]:
        if not isinstance(question, str) or len(question) > 12000 or looks_like_secret_text(question):
            raise RoutingError("consultation requires a bounded non-secret summary")
        with self._condition:
            if not self.available:
                return {"status": "unavailable", "text": "", "possibly_sent": False}
            attempt_id = uuid4().hex
            item = {"attempt_id": attempt_id, "question": question, "owner_id": scope.owner_id,
                    "session_id": scope.session_id, "status": "queued"}
            self._requests[attempt_id] = item
            deadline = time.monotonic() + timeout
            while item["status"] != "done" and not cancelled.is_set() and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(min(remaining, 0.25))
            result = item.get("result") or {"status": "unknown" if item["status"] == "running" else "cancelled",
                                          "text": "", "possibly_sent": item["status"] == "running"}
            self._requests.pop(attempt_id, None)
            return {**result, "attempt_id": attempt_id}

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
