"""Read-only checks that keep a DSH endpoint paired with its local profile.

The DSH Web API does not expose ``DSH_HOME`` in its host descriptor.  Before a
smoke may mutate a profile, compare the bounded user-preset roster returned by
the endpoint with the local ``.agent-presets`` directory.  This is a safety
check, not a way to discover or copy profile contents.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ProfileBindingError(RuntimeError):
    """A safe, actionable endpoint/profile pairing failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(str(value or "").strip().rstrip("/"))
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _LOOPBACK_HOSTS:
        raise ProfileBindingError("endpoint-not-loopback")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProfileBindingError("endpoint-invalid")
    try:
        port = parsed.port
    except ValueError as error:
        raise ProfileBindingError("endpoint-invalid") from error
    if port is not None and not 1 <= port <= 65535:
        raise ProfileBindingError("endpoint-invalid")
    return str(value).strip().rstrip("/")


def _local_user_presets(profile: Path) -> set[str]:
    if not profile.exists() or not profile.is_dir():
        raise ProfileBindingError("profile-not-found")
    root = profile / ".agent-presets"
    if not root.exists():
        return set()
    if not root.is_dir():
        raise ProfileBindingError("profile-preset-root-invalid")
    try:
        entries = list(root.iterdir())
    except OSError as error:
        raise ProfileBindingError("profile-not-readable") from error
    return {
        entry.name
        for entry in entries
        if entry.is_dir() and _PROFILE_ID_RE.fullmatch(entry.name)
    }


def _remote_user_presets(endpoint: str, *, timeout: float) -> set[str]:
    body = json.dumps(
        {
            "type": "client-request",
            "rpcId": "sumika-profile-binding-probe",
            "method": "agentPreset.list",
            "payload": {},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        f"{endpoint}/api/agentPreset.list",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=max(0.2, float(timeout))) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ProfileBindingError("endpoint-http-error") from error
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProfileBindingError("endpoint-unavailable") from error
    if not isinstance(value, dict):
        raise ProfileBindingError("endpoint-invalid-response")
    result = value.get("result")
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ProfileBindingError("endpoint-rejected")
    payload = result.get("value")
    presets = payload.get("presets") if isinstance(payload, dict) else None
    if not isinstance(presets, list):
        raise ProfileBindingError("endpoint-invalid-roster")
    ids: set[str] = set()
    for item in presets:
        if not isinstance(item, dict) or item.get("trust") != "user":
            continue
        preset_id = item.get("id")
        if isinstance(preset_id, str) and _PROFILE_ID_RE.fullmatch(preset_id):
            ids.add(preset_id)
    return ids


def verify_profile_binding(
    endpoint: str,
    profile_dir: str | Path,
    *,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Verify a local DSH profile is the one serving ``endpoint``.

    A disjoint or ambiguous user-preset roster is rejected before any smoke
    operation can write settings, presets, sessions, or MCP configuration.
    Empty rosters on both sides are accepted with weak confidence because a
    fresh profile has no user marker yet.
    """

    safe_endpoint = _safe_endpoint(endpoint)
    profile = Path(profile_dir).expanduser().resolve()
    local = _local_user_presets(profile)
    remote = _remote_user_presets(safe_endpoint, timeout=timeout)
    overlap = local & remote
    if local and remote and not overlap:
        raise ProfileBindingError("profile-mismatch")
    if local and not remote:
        raise ProfileBindingError("profile-mismatch")
    if remote and not local:
        raise ProfileBindingError("profile-ambiguous")
    return {
        "status": "matched",
        "confidence": "strong" if overlap else "weak",
        "local_user_preset_count": len(local),
        "remote_user_preset_count": len(remote),
        "overlap_count": len(overlap),
    }


__all__ = ["ProfileBindingError", "verify_profile_binding"]
