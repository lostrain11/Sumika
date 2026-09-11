from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


CONFIRMATION_METHODS = frozenset({
    "work.authorization.confirm", "quality.task.confirm", "quality.task.budget",
    "schedule.create", "schedule.update", "schedule.pause",
    "agent.approval.respond", "agent.question.respond",
    "work.task.merge.apply", "work.task.merge.undo",
})


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

    def authenticate(self, supplied: str | None, method: str, params: Mapping[str, Any],
                     expected_digest: str) -> CallerContext:
        if self._secret is None or not isinstance(supplied, str) or not supplied.isascii() or not hmac.compare_digest(self._secret, supplied):
            raise HostAuthorizationError("trusted native host required")
        actual = confirmation_digest(method, params)
        if not isinstance(expected_digest, str) or not expected_digest.isascii() or not hmac.compare_digest(actual, expected_digest):
            raise HostAuthorizationError("confirmation request changed")
        return CallerContext(method, actual, self._issuer)

    def require(self, caller: CallerContext | None, method: str, params: Mapping[str, Any]) -> None:
        if method not in CONFIRMATION_METHODS:
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
