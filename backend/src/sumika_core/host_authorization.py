from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


CONFIRMATION_METHODS = frozenset({
    "work.authorization.confirm",
    "quality.task.confirm",
    "quality.task.budget",
    "schedule.create",
    "schedule.update",
    "schedule.pause",
    "schedule.run",
    "agent.approval.respond",
    "agent.question.respond",
    "agent.session.retry",
    "agent.mcp.configuration.apply",
    "workspace.worktree.create",
    "workspace.commit",
    "workspace.restore",
    "workspace.checkpoint.create",
    "agent.skills.approve",
    "agent.skill.approve",
    "agent.skills.revoke",
    "agent.skill.revoke",
    "agent.session.create",
    "agent.session.select_preset",
    "agent.session.select_model",
    "agent.session.fork",
    "agent.preset.copy",
    "agent.preset.open",
    "agent.preset.remove",
    "agent.workspace.create",
    "agent.provider.sync",
    "model.policy.apply",
    "model.policy.refresh",
    "skill.builtin.set",
    "module.update",
    "plugin.approve",
    "plugin.configure",
    "plugin.run",
    "tool.run",
    "task.run",
    "audio.permission.set",
    "audio.start",
    "audio.asr.transcribe",
    "audio.tts.synthesize",
    "audio.vad.detect",
    "vision.permission.set",
    "vision.start",
    "vision.observe",
    "provider.profile.save",
    "provider.import.save",
    "provider.profile.activate",
    "provider.profile.model.select",
    "provider.profile.restore",
    "provider.profile.models",
    "provider.profile.health",
    "snapshot.restore",
    "browser.embedded.attach",
    "browser.embedded.poll",
    "browser.embedded.complete",
    "browser.embedded.alive",
    "browser.embedded.bind_portal",
    "browser.profile.create",
    "browser.profile.restore",
    "browser.session.create",
    "browser.session.focus",
    "browser.tab.create",
    "browser.tab.select",
    "browser.tab.close",
    "browser.navigate",
    "browser.action.execute",
    "browser.console",
    "browser.network",
    "browser.download.release",
    "browser.download.quarantine",
    "browser.web_chat.profile.create",
    "browser.web_chat.profile.update",
    "browser.web_chat.profile.bind_native",
    "browser.web_chat.profile.native_takeover",
    "browser.web_chat.profile.authorize",
    "browser.web_chat.profile.open",
    "browser.web_chat.profile.focus",
    "browser.web_chat.profile.check",
    "browser.web_chat.profile.consent",
    "browser.web_chat.profile.activate",
    "browser.web_chat.profile.restore",
    "desktop.automation.register",
    "desktop.automation.open",
    "desktop.automation.act",
    "desktop.automation.close",
    "desktop.automation.approval",
    "desktop.automation.takeover",
    "sumika.route.bridge_tools",
    "sumika.route.occupancy",
    "sumika.route.takeover",
    "benefits.configure",
    "benefits.refresh",
    "benefits.checkin",
    "work.task.merge.apply",
    "work.task.merge.undo",
    "agent.event.ingest",
})


def requires_confirmation(method: str, params: Mapping[str, Any]) -> bool:
    if method not in CONFIRMATION_METHODS:
        return False
    if not isinstance(params, Mapping):
        return True
    if method in {"audio.permission.set", "vision.permission.set"}:
        return not (params.get("granted") is False and set(params) <= {"permission_id", "permission", "granted"})
    if method == "module.update":
        return not (params.get("enabled") is False and set(params) <= {"module_id", "enabled"})
    if method == "skill.builtin.set":
        return not (params.get("enabled") is False and set(params) <= {"assistant_id", "project_id", "skill_id", "enabled", "sha256"})
    if method == "schedule.pause":
        return not (params.get("paused") is True and set(params) <= {"assistant_id", "schedule_id", "paused"})
    if method == "browser.web_chat.profile.consent":
        return not (params.get("enabled") is False and set(params) <= {"profile_id", "enabled", "approved"})
    if method == "sumika.route.bridge_tools":
        return params.get("register", False) is not False
    if method == "model.policy.refresh":
        return params.get("interactive_allowed", False) is not False
    if method == "desktop.automation.approval":
        if any(key in params and not isinstance(params[key], str) for key in ("operation", "action")):
            return True
        operation = params.get("operation") or params.get("action") or "list"
        return operation.strip().lower() not in ("list", "status", "revoke", "deny")
    if method == "tool.run":
        return not (params.get("approved", False) is False and set(params) <= {"tool_id", "input", "approved"})
    return True


class HostAuthorizationError(ValueError):
    pass


def confirmation_digest(method: str, params: Mapping[str, Any]) -> str:
    if method not in CONFIRMATION_METHODS:
        raise HostAuthorizationError("unsupported host confirmation action")
    encoded = json.dumps({"method": method, "params": params}, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CallerContext:
    method: str
    request_digest: str
    _issuer: object = field(repr=False, compare=False)


class HostAuthorization:
    def __init__(self, secret: str | None = None):
        if secret is not None and (not isinstance(secret, str) or len(secret) != 64 or
                                   any(char not in "0123456789abcdef" for char in secret)):
            raise HostAuthorizationError("invalid host bootstrap material")
        self._secret = secret
        self._issuer = object()

    def process_proof(self, nonce: str, pid: int) -> dict[str, Any]:
        if self._secret is None:
            raise HostAuthorizationError("managed host bootstrap required")
        if not isinstance(nonce, str) or len(nonce) != 64 or any(char not in "0123456789abcdef" for char in nonce):
            raise HostAuthorizationError("invalid host identity challenge")
        if type(pid) is not int or not 0 < pid <= 0xffffffff:
            raise HostAuthorizationError("invalid host process identity")
        message = f"sumika-core-identity/v1\n{nonce}\n{pid}".encode("ascii")
        proof = hmac.new(self._secret.encode("ascii"), message, hashlib.sha256).hexdigest()
        return {"schema_version": "sumika-core-identity/v1", "nonce": nonce, "pid": pid, "proof": proof}

    def authenticate(self, supplied: str | None, method: str, params: Mapping[str, Any],
                     expected_digest: str) -> CallerContext:
        if self._secret is None or not isinstance(supplied, str) or not supplied.isascii() or not hmac.compare_digest(self._secret, supplied):
            raise HostAuthorizationError("trusted native host required")
        actual = confirmation_digest(method, params)
        if not isinstance(expected_digest, str) or not expected_digest.isascii() or not hmac.compare_digest(actual, expected_digest):
            raise HostAuthorizationError("confirmation request changed")
        return CallerContext(method, actual, self._issuer)

    def require(self, caller: CallerContext | None, method: str, params: Mapping[str, Any]) -> None:
        if not requires_confirmation(method, params):
            return
        if (not isinstance(caller, CallerContext) or caller._issuer is not self._issuer or
                caller.method != method or caller.request_digest != confirmation_digest(method, params)):
            raise HostAuthorizationError("trusted native host confirmation required")


def read_bootstrap(stream) -> str:
    line = stream.readline(1025)
    if len(line) > 1024 or not line.endswith("\n"):
        raise HostAuthorizationError("invalid host bootstrap frame")
    try:
        value = json.loads(line)
    except (TypeError, ValueError):
        raise HostAuthorizationError("invalid host bootstrap frame") from None
    if not isinstance(value, dict) or set(value) != {"schema", "secret"} or value["schema"] != "sumika-host/v1":
        raise HostAuthorizationError("unsupported host bootstrap schema")
    HostAuthorization(value["secret"])
    if value["secret"] is None:
        raise HostAuthorizationError("missing host bootstrap material")
    return value["secret"]
