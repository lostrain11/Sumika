from __future__ import annotations

import json
import re
import threading
import time
from uuid import uuid4

from .browser import looks_like_secret_text
from .integrations.account_portals import MOARK_RECEIPT_REASONS, project_modelscope_portal, project_ollama_starter_portal
from .integrations.modelscope_benefits import _REASONS as MODELSCOPE_READ_REASONS


NATIVE_BROWSER = "sumika-native"
PORTALS = {
    "modelscope": {"tab_id": "account-modelscope", "account_id": "modelscope", "url": "https://modelscope.cn/magicube/usage", "title": "魔搭额度与签到"},
    "ollama": {"tab_id": "account-ollama", "account_id": "ollama", "url": "https://ollama.com/settings", "title": "Ollama 用量"},
    "moark": {"tab_id": "account-moark", "account_id": "moark", "url": "https://moark.com/serverless-api", "title": "Moark 账单"},
}


def fixed_account_read_reason(source, reason):
    reasons = MODELSCOPE_READ_REASONS if source == "modelscope" else MOARK_RECEIPT_REASONS if source == "moark" else ()
    return reason if isinstance(reason, str) and reason in reasons else None


class EmbeddedBrowserBridge:
    def __init__(self):
        self._condition = threading.Condition()
        self._token = uuid4().hex
        self._attached_at = 0.0
        self._requests = {}
        self._closed = False

    @property
    def available(self):
        return not self._closed and time.monotonic() - self._attached_at < 15

    def attach(self):
        with self._condition:
            if self._closed:
                raise ValueError("embedded browser closed")
            self._attached_at = time.monotonic()
            return {"token": self._token, "browser_id": NATIVE_BROWSER}

    def _authorize(self, token):
        if self._closed or token != self._token:
            raise ValueError("embedded browser not attached")

    def poll(self, token, *, accept_requests=True):
        if type(accept_requests) is not bool:
            raise ValueError("accept_requests must be boolean")
        with self._condition:
            self._authorize(token)
            self._attached_at = time.monotonic()
            queued = next((row for row in self._requests.values() if row["state"] == "queued"), None)
            if queued and accept_requests:
                queued["state"] = "running"
                return {"request": {key: value for key, value in queued.items() if key != "state"}}
            return {"request": None}

    def complete(self, token, attempt_id, observation):
        with self._condition:
            self._authorize(token)
            item = self._requests.get(attempt_id)
            if not item or item["state"] != "running":
                return {"accepted": False}
            if not isinstance(observation, dict) or len(json.dumps(observation, ensure_ascii=False)) > 32000 or looks_like_secret_text(json.dumps(observation)):
                raise ValueError("bounded account observation required")
            if item["source"] == "web-chat":
                from .browser.native_web_chat import NativeWebChatTransport
                projection = NativeWebChatTransport(None)._result(observation, item["operation"])
                if projection.get("attempt_id") not in (None, item.get("message_attempt_id")):
                    raise ValueError("native message attempt mismatch")
                item.update(result=projection, state="done")
                self._condition.notify_all()
                return {"accepted": True}
            if item["source"] == "moark":
                from .integrations.account_sources import validate_moark_receipts, MOARK_RECEIPTS_URL
                result = {"state": "needs-review",
                          "reason": fixed_account_read_reason("moark", observation.get("reason")) or "official-receipts-unavailable"}
                if observation.get("state") == "verified":
                    result = {"schema": "moark-receipts/v1", "source_url": MOARK_RECEIPTS_URL, "state": "verified", "receipts": validate_moark_receipts(observation)}
                item.update(result=result, state="done")
                self._condition.notify_all()
                return {"accepted": True}
            allowed = {"state", "available_balance", "unit", "grants"} if item["source"] == "modelscope" else {
                "state", "free_usage_percent", "extra_usage_balance", "allowed_models", "displayed_reset"}
            safe = {key: value for key, value in observation.items() if key in allowed}
            if not isinstance(safe.get("state"), str) or safe["state"] not in {"verified", "login-required", "challenge", "unavailable", "needs-review", "takeover", "interrupted"}:
                safe = {"state": "needs-review"}
            if item["source"] == "modelscope" and safe.get("state") != "verified":
                safe["reason"] = fixed_account_read_reason("modelscope", observation.get("reason")) or "native-portal-read-failed"
            projection = project_modelscope_portal(safe) if item["source"] == "modelscope" else project_ollama_starter_portal(safe)
            item["result"] = projection
            item["state"] = "done"
            self._condition.notify_all()
            return {"accepted": True}

    def alive(self, token, attempt_id):
        with self._condition:
            self._authorize(token)
            self._attached_at = time.monotonic()
            item = self._requests.get(attempt_id)
            return {"active": bool(item and item["state"] == "running")}

    def exchange(self, operation, profile, *, text=None, attempt_id=None, cancelled=None):
        from .browser.native_web_chat import NATIVE_OPERATIONS
        if operation not in NATIVE_OPERATIONS:
            raise ValueError("registered native operation required")
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,48}", str(profile.get(key, ""))) for key in ("tab_id", "account_id")):
            raise ValueError("registered native profile required")
        if text is not None and (not isinstance(text, str) or len(text) > 12000 or looks_like_secret_text(text)):
            raise ValueError("bounded non-sensitive message required")
        cancelled = cancelled or threading.Event()
        with self._condition:
            if not self.available or cancelled.is_set():
                return {"status": "unavailable", "sent": False, "possibly_sent": False}
            request_id = uuid4().hex
            item = {"attempt_id": request_id, "source": "web-chat", "action": "web-chat", "operation": operation,
                    "tab_id": profile["tab_id"], "account_id": profile["account_id"], "url": profile["chat_url"],
                    "title": profile["site_key"], "message_attempt_id": attempt_id,
                    "automation_supported": profile["automation_supported"], "state": "queued"}
            if operation == "send":
                if not profile.get("auto_chat_enabled") or "chat.send" not in profile.get("allowed_actions", []) or profile.get("budget_policy") not in {"free-only", "no-paid"}:
                    return {"status": "not-sent", "sent": False, "possibly_sent": False}
                item["text"] = text
            self._requests[request_id] = item
            deadline = time.monotonic() + (285 if operation == "send" else 25)
            while item["state"] != "done" and not self._closed and not cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(min(remaining, .25))
            self._requests.pop(request_id, None)
            possible = operation == "send" and item["state"] != "queued"
            return item.get("result") or {"status": "unknown" if possible else "unavailable", "sent": False, "possibly_sent": possible}

    def read_portal(self, source, browser_id, cancelled, *, timeout=25):
        if source not in PORTALS or browser_id != NATIVE_BROWSER:
            raise ValueError("registered native portal required")
        with self._condition:
            if not self.available:
                return self._failed(source, "unavailable")
            if any(row["source"] == source and row["state"] in {"queued", "running"} for row in self._requests.values()):
                return self._failed(source, "takeover")
            attempt_id = uuid4().hex
            item = {"attempt_id": attempt_id, "source": source, "action": "read-receipts" if source == "moark" else "read-account", **PORTALS[source], "state": "queued"}
            self._requests[attempt_id] = item
            deadline = time.monotonic() + timeout
            while item["state"] != "done" and not self._closed and not cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(min(remaining, 0.25))
            self._requests.pop(attempt_id, None)
            return item.get("result") or self._failed(source, "interrupted" if cancelled.is_set() or self._closed else "needs-review")

    @staticmethod
    def _failed(source, state):
        if source == "moark":
            return {"state": state}
        project = project_modelscope_portal if source == "modelscope" else project_ollama_starter_portal
        return project({"state": state})

    def read_receipts(self, source, browser_id, cancelled):
        if source != "moark":
            raise ValueError("registered native receipt source required")
        return self.read_portal(source, browser_id, cancelled)

    def status(self):
        with self._condition:
            return {"available": self.available, "browser_id": NATIVE_BROWSER,
                    "requests": [{"attempt_id": row["attempt_id"], "source": row["source"], "state": row["state"]} for row in self._requests.values()]}

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class EmbeddedBenefitsReader:
    def __init__(self, bridge, legacy, *, native_required=False):
        self.bridge, self.legacy = bridge, legacy
        self.native_required = native_required

    def browsers(self):
        rows = [{"instance_id": NATIVE_BROWSER, "browser_name": "Sumika 内置浏览器"}] if self.bridge.available else []
        return rows if self.native_required else rows + self.legacy.browsers()

    def read(self, browser, cancelled):
        if browser != NATIVE_BROWSER:
            if self.native_required:
                return {"state": "needs-review", "reason": "bind-native-browser-and-login-required"}
            return self.legacy.read(browser, cancelled)
        observation = self.bridge.read_portal("modelscope", browser, cancelled)
        quality = observation["quality"]
        return {"state": quality["state"], "reason": quality.get("blocking_reason"),
                "available_balance": observation.get("available_balance"), "unit": "magicube",
                "grants": [{key: row[key] for key in ("kind", "amount", "granted_date_display", "validity_days_display") if key in row}
                           for row in observation.get("grants", [])]}
