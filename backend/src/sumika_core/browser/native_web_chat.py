"""Bounded native web-chat exchange; no browser processes or credential migration.

The host implements exchange(operation, profile, *, text=None, attempt_id=None,
cancelled=None). It must enforce native account leases, allowed domains, current
login/composer evidence, consent and budget before writing. Only ChatGPT/Kimi
have automatic adapters. Other sites may open for manual use. The host must
honour the cancellation Event and bound control calls to 30 seconds and send
observation to 300 seconds, without retrying an uncertain submission.
Prompts are limited to 12,000 characters. Health is a local 15-second evidence
cache, never a synchronous host request; bound bridges expose available.

Results contain status, auth_state, page_ready, sent, possibly_sent,
requires_human, tab_id and, for completed sends only, text (<= 24,000 chars).
check may reconcile an unknown send only with its exact attempt_id and a
completed/not-sent status. takeover pauses writes; resume explicitly releases
manual control, never an unresolved submission. No arbitrary page data is
accepted, persisted or logged.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Any, Callable, Mapping

from .policy import looks_like_secret_text


NATIVE_TRANSPORT = "native"
NATIVE_HEALTH_TTL_SECONDS = 15.0
NATIVE_SITES = {"chatgpt-web": "chatgpt", "kimi-web": "kimi"}
NATIVE_OPERATIONS = frozenset({"check", "authorize", "open", "focus", "close", "send", "health", "takeover", "resume"})
_STATUSES = frozenset({"ready", "opened", "focused", "closed", "completed", "not-sent", "unknown", "cancelled", "interrupted", "needs-auth", "waiting-human", "unavailable", "unsupported", "takeover", "resumed", "failed"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class NativeWebChatTransport:
    def __init__(self, storage: Any, exchange: Callable[..., Mapping[str, Any]] | None = None) -> None:
        self.storage = storage
        self._lock = threading.RLock()
        self._exchange_callback = exchange
        self._health: dict[str, tuple[float, dict[str, Any]]] = {}
        self._writers: dict[str, str] = {}
        self._opened: dict[str, dict[str, Any]] = {}

    @property
    def exchange(self) -> Callable[..., Mapping[str, Any]] | None:
        return self._exchange_callback

    @exchange.setter
    def exchange(self, exchange: Callable[..., Mapping[str, Any]] | None) -> None:
        if exchange is not None and not callable(exchange):
            raise ValueError("native exchange must be callable")
        with self._lock:
            self._exchange_callback = exchange
            self._health.clear()

    def invalidate(self, profile_id: str) -> None:
        with self._lock:
            self._health.pop(profile_id, None)

    def health(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        """Read fresh evidence without queuing work on the frontend RPC loop."""

        callback = self.exchange
        bridge = getattr(callback, "__self__", callback)
        if not callable(callback) or getattr(bridge, "available", True) is not True:
            return self.failure("unavailable", "native-bridge-unavailable")
        with self._lock:
            cached = self._health.get(profile["id"])
            if not cached or time.monotonic() - cached[0] >= NATIVE_HEALTH_TTL_SECONDS:
                return self.failure("unavailable", "native-health-stale")
            result = dict(cached[1])
        return result

    @staticmethod
    def selected(profile: Mapping[str, Any]) -> bool:
        return (profile.get("config") or {}).get("transport") == NATIVE_TRANSPORT

    @staticmethod
    def supported(profile: Mapping[str, Any]) -> bool:
        return profile.get("adapter_id") in NATIVE_SITES

    @staticmethod
    def account_id(profile: Mapping[str, Any]) -> str:
        digest = hashlib.sha256(str(profile["browser_profile_id"]).encode("utf-8")).hexdigest()[:24]
        return f"webchat-{digest}"

    def profiles(self, profile: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [row for row in self.storage.list_web_chat_profiles(include_archived=True)
                if row["browser_profile_id"] == profile["browser_profile_id"]]

    def blocked(self, profile: Mapping[str, Any]) -> str | None:
        with self._lock:
            if self.account_id(profile) in self._writers:
                return "account-occupied"
            for row in self.profiles(profile):
                config = row.get("config") or {}
                if config.get("native_pending_attempt"):
                    return "native-submission-unknown"
                if config.get("native_takeover"):
                    return "native-takeover"
        return None

    def reserve(self, profile: Mapping[str, Any], attempt_id: str) -> str | None:
        with self._lock:
            reason = self.blocked(profile)
            if reason:
                return reason
            self._writers[self.account_id(profile)] = attempt_id
        return None

    def release(self, profile: Mapping[str, Any], attempt_id: str) -> None:
        with self._lock:
            account = self.account_id(profile)
            if self._writers.get(account) == attempt_id:
                self._writers.pop(account, None)

    def _config(self, profile_id: str, **values: Any) -> None:
        profile = self.storage.get_web_chat_profile(profile_id)
        config = dict(profile.get("config") or {})
        for key, value in values.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        self.storage.update_web_chat_profile(profile_id, config=config)

    def project(self, profile: Mapping[str, Any], spec: Any) -> dict[str, Any]:
        return {
            "id": profile["id"], "profile_id": profile["id"],
            "account_id": self.account_id(profile), "tab_id": profile["id"],
            "adapter_id": spec.id, "site_key": NATIVE_SITES.get(spec.id, spec.id),
            "chat_url": spec.chat_url, "domains": list(spec.domains),
            "transport": NATIVE_TRANSPORT, "automation_supported": self.supported(profile),
            "auto_chat_enabled": bool(profile.get("auto_chat_enabled")),
            "allowed_actions": list(profile.get("allowed_actions") or []),
            "budget_policy": profile.get("budget_policy"),
        }

    @staticmethod
    def failure(status: str, code: str) -> dict[str, Any]:
        return {"ok": False, "status": status, "transport": NATIVE_TRANSPORT,
                "sent": False, "possibly_sent": status == "unknown",
                "requires_human": status in {"unknown", "waiting-human", "unsupported", "takeover"},
                "error_code": code, "reason": code}

    def _result(self, raw: Any, operation: str) -> dict[str, Any]:
        if not isinstance(raw, Mapping) or len(raw) > 24:
            raise ValueError("bounded native result required")
        status = raw.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError("native result status required")
        result: dict[str, Any] = {"status": status, "transport": NATIVE_TRANSPORT}
        for key in ("sent", "possibly_sent", "requires_human", "page_ready"):
            if key in raw:
                if type(raw[key]) is not bool:
                    raise ValueError("native result flags must be boolean")
                result[key] = raw[key]
        for key in ("tab_id", "attempt_id"):
            if key in raw:
                value = raw[key]
                if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) or looks_like_secret_text(value):
                    raise ValueError("native identifier invalid")
                result[key] = value
        if "auth_state" in raw:
            if raw["auth_state"] not in ("authorized", "needs-auth", "unknown"):
                raise ValueError("native auth state invalid")
            result["auth_state"] = raw["auth_state"]
        if operation == "send":
            if status == "completed":
                response = raw.get("text")
                if (raw.get("sent") is not True or not isinstance(response, str)
                        or not response.strip() or len(response) > 24_000
                        or looks_like_secret_text(response)
                        or any(ord(char) < 32 and char not in "\r\n\t" for char in response)):
                    raise ValueError("bounded assistant response required")
                result.update(text=response, sent=True, possibly_sent=True)
            elif not (raw.get("sent") is False and raw.get("possibly_sent") is False
                      and status in {"not-sent", "cancelled", "needs-auth", "waiting-human", "unsupported", "unavailable", "takeover", "failed"}):
                result.update(status="unknown", possibly_sent=True, requires_human=True)
        result["ok"] = result["status"] in {"ready", "opened", "focused", "closed", "completed", "resumed"}
        if result["status"] in {"needs-auth", "waiting-human", "takeover", "unsupported", "unknown"}:
            result["requires_human"] = True
        return result

    def _exchange(self, operation: str, projected: dict[str, Any], *, text: str | None = None,
                  attempt_id: str | None = None, cancelled: threading.Event | None = None) -> dict[str, Any]:
        if not callable(self.exchange):
            return self.failure("unavailable", "native-bridge-unavailable")
        try:
            raw = self.exchange(operation, projected, text=text, attempt_id=attempt_id, cancelled=cancelled)
            result = self._result(raw, operation)
            if result.get("attempt_id") not in (None, attempt_id):
                raise ValueError("native attempt mismatch")
            return result
        except Exception:
            return self.failure("unknown" if operation == "send" else "unavailable", "native-exchange-unconfirmed")

    def operate(self, operation: str, profile: Mapping[str, Any], spec: Any) -> dict[str, Any]:
        if operation not in NATIVE_OPERATIONS or operation == "send":
            raise ValueError("native control operation required")
        if operation == "health":
            return self.health(profile)
        projected = self.project(profile, spec)
        account = self.account_id(profile)
        control_id = f"control:{operation}:{profile['id']}"
        with self._lock:
            active_writer = account in self._writers
            if active_writer and operation not in {"takeover", "close"}:
                return self.failure("waiting-human", "account-occupied")
            if operation == "takeover":
                self._config(profile["id"], native_takeover=True)
            pending = (profile.get("config") or {}).get("native_pending_attempt")
            attempt_id = pending if isinstance(pending, str) else None
            if not active_writer:
                self._writers[account] = control_id
        try:
            result = self._exchange(operation, projected, attempt_id=attempt_id)
            with self._lock:
                if operation in {"check", "authorize", "resume"}:
                    self._health[profile["id"]] = (time.monotonic(), dict(result))
                elif operation in {"close", "takeover"} or result["status"] == "unavailable":
                    self._health.pop(profile["id"], None)
                if operation in {"open", "authorize", "focus", "check"} and (
                    result.get("tab_id") or result["status"] in {"ready", "opened", "focused", "needs-auth", "takeover"}
                ):
                    self._opened[profile["id"]] = projected
                if operation == "close" and result["status"] == "closed":
                    self._opened.pop(profile["id"], None)
                if operation == "resume" and result["status"] == "resumed":
                    for row in self.profiles(profile):
                        self._config(row["id"], native_takeover=None)
                if (operation == "check" and attempt_id and result.get("attempt_id") == attempt_id
                        and (result["status"] == "completed" and result.get("sent") is True
                             or result["status"] == "not-sent" and result.get("sent") is False
                             and result.get("possibly_sent") is False)):
                    self._config(profile["id"], native_pending_attempt=None)
            return result
        finally:
            if not active_writer:
                self.release(profile, control_id)

    def send(self, profile: Mapping[str, Any], spec: Any, text: str, *, attempt_id: str,
             cancelled: threading.Event) -> dict[str, Any]:
        with self._lock:
            if self._writers.get(self.account_id(profile)) != attempt_id:
                return self.failure("waiting-human", "account-occupied")
            if cancelled.is_set():
                return self.failure("cancelled", "cancelled-before-send")
            if any((row.get("config") or {}).get("native_takeover") for row in self.profiles(profile)):
                return self.failure("takeover", "native-takeover")
            if not self.supported(profile):
                return self.failure("unsupported", "native-manual-only")
            if (not profile.get("auto_chat_enabled") or "chat.send" not in (profile.get("allowed_actions") or [])
                    or profile.get("auth_state") != "authorized"
                    or profile.get("budget_policy") not in {"free-only", "no-paid"}):
                return self.failure("waiting-human", "native-consent-required")
            if len(text) > 12_000:
                return self.failure("failed", "native-message-too-long")
            if looks_like_secret_text(text):
                return self.failure("failed", "sensitive-message-rejected")
            if not callable(self.exchange):
                return self.failure("unavailable", "native-bridge-unavailable")
            self._config(profile["id"], native_pending_attempt=attempt_id)
            projected = self.project(profile, spec)
            self._opened[profile["id"]] = projected
        result = self._exchange("send", projected, text=text, attempt_id=attempt_id, cancelled=cancelled)
        with self._lock:
            if cancelled.is_set():
                self._health.pop(profile["id"], None)
                return self.failure("unknown", "native-cancelled-after-dispatch")
            if result["status"] == "completed":
                self._health[profile["id"]] = (time.monotonic(), {
                    "ok": True, "status": "ready", "auth_state": "authorized", "page_ready": True,
                })
            else:
                self._health.pop(profile["id"], None)
            if result["status"] == "completed" or (result.get("sent") is False and result.get("possibly_sent") is False):
                self._config(profile["id"], native_pending_attempt=None)
        return result

    def close(self) -> None:
        with self._lock:
            opened = list(self._opened.values())
            self._opened.clear()
            self._health.clear()
        for projected in opened:
            self._exchange("close", projected)
