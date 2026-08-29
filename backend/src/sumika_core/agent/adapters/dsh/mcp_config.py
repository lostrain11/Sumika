"""Managed MCP rows for user-owned DSH Agent presets.

The pinned DSH release has no composition-write RPC.  This module therefore
owns a deliberately narrow file format: Sumika appends JSON flow mappings
(valid YAML) between versioned marker comments and never parses or rewrites
the rest of ``agent.cordis.yml``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from ....credentials import CredentialError, CredentialStore
from ...contracts import AgentRuntimeError


_PLUGIN_NAME = "@deepseek-ai/dsh-mcp-client"
_COMPOSITION_FILE = "agent.cordis.yml"
_USER_PRESET_DIR = ".agent-presets"
_MAX_COMPOSITION_BYTES = 2 * 1024 * 1024
_PREVIEW_TTL_SECONDS = 300
_MAX_PREVIEWS = 32
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_MARKER_V1_RE = re.compile(
    r"^# sumika-managed-mcp:v1 begin (?P<name>[A-Za-z0-9_-]{1,32})\r?\n"
    r"- (?P<row>\{[^\r\n]*\})\r?\n"
    r"# sumika-managed-mcp:v1 end (?P=name)(?:\r?\n|$)",
    re.MULTILINE,
)
_MARKER_V2_RE = re.compile(
    r"^# sumika-managed-mcp:v2 begin (?P<name>[A-Za-z0-9_-]{1,32})\r?\n"
    r"# sumika-mcp-metadata:v2 (?P<metadata>[A-Za-z0-9_-]+)\r?\n"
    r"- (?P<row>\{[^\r\n]*\})\r?\n"
    r"# sumika-managed-mcp:v2 end (?P=name)(?:\r?\n|$)",
    re.MULTILINE,
)
_MARKER_PREFIX = "# sumika-managed-mcp:"
_ALLOWED_CONFIGURATION_KEYS = {
    "server_name",
    "transport",
    "enabled",
    "command",
    "args",
    "cwd",
    "url",
    "tool_call_timeout_ms",
    "credential",
}
_ALLOWED_CREDENTIAL_KEYS = {"target", "prefix", "rotate"}
_ENV_TARGET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_HEADER_TARGET_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$")
_CREDENTIAL_REVISION_RE = re.compile(r"^[a-f0-9]{16}$")
_MCP_ENVIRONMENT_RE = re.compile(r"^SUMIKA_MCP_[A-F0-9]{24}_SECRET$")
_CREDENTIAL_SHAPE_RE = re.compile(r"(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_FORBIDDEN_ENV_TARGETS = {
    "COMSPEC",
    "HOME",
    "NODE_OPTIONS",
    "PATH",
    "PATHEXT",
    "PYTHONHOME",
    "PYTHONPATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
}
_FORBIDDEN_HEADERS = {
    "connection",
    "content-length",
    "cookie",
    "host",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_MAX_SECRET_UTF8_BYTES = 1800
_MAX_MCP_LAUNCH_BINDINGS = 32


class ManagedMcpPresetStore:
    """Preview and atomically apply Sumika-owned MCP rows."""

    def __init__(
        self,
        profile_dir: str | Path,
        *,
        logger: Any = None,
        credential_store: CredentialStore | None = None,
        launch_credential_refs: set[str] | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir) if str(profile_dir).strip() else None
        self.logger = logger
        self.credential_store = credential_store
        self.launch_credential_refs = set(launch_credential_refs or ())
        self._lock = threading.RLock()
        self._previews: dict[str, dict[str, Any]] = {}

    def bind_credential_store(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store

    def list_configurations(self, preset: str) -> dict[str, Any]:
        with self._lock:
            path = self._composition_path(preset)
            text, _ = self._read_composition(path)
            blocks = _managed_blocks(text, preset)
            return {
                "agent_preset": preset,
                "configurations": [
                    self._public_configuration(preset, block["configuration"])
                    for block in blocks
                ],
                "credential_fields_supported": self.credential_store is not None,
                "credential_storage": "secure-store" if self.credential_store is not None else "unavailable",
                "supported_transports": ["stdio", "streamable-http"],
            }

    def preview(self, preset: str, params: dict[str, Any]) -> dict[str, Any]:
        action = str(params.get("action") or "upsert").strip().lower()
        if action not in {"upsert", "remove"}:
            raise AgentRuntimeError("MCP configuration action must be upsert or remove")
        raw_configuration = params.get("configuration")
        if not isinstance(raw_configuration, dict):
            raise AgentRuntimeError("MCP configuration must be an object")

        with self._lock:
            self._prune_previews()
            path = self._composition_path(preset)
            text, original = self._read_composition(path)
            blocks = _managed_blocks(text, preset)
            server_name = _server_name(raw_configuration)
            current = next(
                (block for block in blocks if block["configuration"]["server_name"] == server_name),
                None,
            )
            configuration, credential_plan = self._normalize_for_preview(
                preset,
                raw_configuration,
                action=action,
                current=current["configuration"] if current else None,
            )
            if action == "remove" and current is None:
                change = "noop"
                rendered = original
            elif action == "remove":
                change = "remove"
                rendered = _replace_block(text, current, "").encode("utf-8")
            else:
                block_text = _render_block(preset, configuration, _line_ending(text))
                if current is None:
                    change = "create"
                    rendered = _append_block(text, block_text, _line_ending(text)).encode("utf-8")
                else:
                    rendered_text = _replace_block(text, current, block_text)
                    rendered = rendered_text.encode("utf-8")
                    change = "noop" if rendered == original else "update"

            token = secrets.token_urlsafe(24)
            expires_at = time.time() + _PREVIEW_TTL_SECONDS
            self._previews[token] = {
                "agent_preset": preset,
                "server_name": configuration["server_name"],
                "action": action,
                "change": change,
                "original_sha256": _sha256(original),
                "rendered_sha256": _sha256(rendered),
                "rendered": rendered,
                "configuration": configuration,
                "credential_plan": credential_plan,
                "expires_at": expires_at,
            }
            public_configuration = self._public_configuration(preset, configuration)
            return {
                "agent_preset": preset,
                "server_name": configuration["server_name"],
                "action": action,
                "change": change,
                "configuration": public_configuration,
                "preview_token": token,
                "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
                "requires_approval": change != "noop",
                "credential_fields_supported": self.credential_store is not None,
                "credential_change": credential_plan["change"],
                "credential_requires_value": credential_plan["requires_value"],
                "restart_required": credential_plan["restart_required"],
                "deferred_enable": credential_plan["deferred_enable"],
            }

    def apply(
        self,
        preset: str,
        preview_token: str,
        validate_mount: Callable[[str], dict[str, Any]],
        *,
        credential_value: Any = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._prune_previews()
            preview = self._previews.get(preview_token)
            if preview is None or preview.get("agent_preset") != preset:
                raise AgentRuntimeError("MCP configuration preview is missing, expired, or belongs to another preset")
            if preview["change"] == "noop":
                self._previews.pop(preview_token, None)
                raise AgentRuntimeError("MCP configuration has no changes to apply")

            path = self._composition_path(preset)
            _, original = self._read_composition(path)
            if _sha256(original) != preview["original_sha256"]:
                self._previews.pop(preview_token, None)
                raise AgentRuntimeError("MCP preset composition changed after preview; create a new preview")

            backup = self._write_backup(preset, original)
            credential_snapshot = self._apply_credential_plan(
                preset,
                preview["credential_plan"],
                credential_value,
            )
            try:
                self._atomic_write(path, preview["rendered"])
            except Exception:
                credentials_restored = self._restore_credential_snapshot(credential_snapshot)
                self._previews.pop(preview_token, None)
                if not credentials_restored:
                    raise AgentRuntimeError(
                        "MCP preset write failed and credential recovery could not be confirmed; backup retained"
                    ) from None
                raise
            if _sha256(path.read_bytes()) != preview["rendered_sha256"]:
                restored = self._restore_if_unchanged(path, preview["rendered_sha256"], original)
                credentials_restored = self._restore_credential_snapshot(credential_snapshot)
                self._previews.pop(preview_token, None)
                if restored and credentials_restored:
                    raise AgentRuntimeError("MCP preset composition write verification failed; original content was restored")
                raise AgentRuntimeError(
                    "MCP preset composition write verification failed and restore could not be confirmed; backup retained"
                )

            try:
                validation = validate_mount(preset)
                if not (
                    isinstance(validation, dict)
                    and validation.get("mountable") is True
                    and validation.get("validation_session_archived") is True
                ):
                    raise AgentRuntimeError("DSH did not confirm MCP preset mount validation")
            except Exception as error:
                restored = self._restore_if_unchanged(path, preview["rendered_sha256"], original)
                credentials_restored = self._restore_credential_snapshot(credential_snapshot)
                self._previews.pop(preview_token, None)
                if not restored or not credentials_restored:
                    raise AgentRuntimeError(
                        "MCP preset mount failed and recovery could not be fully confirmed; backup retained"
                    ) from error
                raise AgentRuntimeError(
                    "MCP preset mount failed; original composition was restored and backup retained"
                ) from error

            self._previews.pop(preview_token, None)
            if self.logger:
                self.logger.info(
                    "dsh mcp configuration applied preset=%s server=%s change=%s backup=%s",
                    preset,
                    preview["server_name"],
                    preview["change"],
                    bool(backup),
                )
            return {
                "agent_preset": preset,
                "server_name": preview["server_name"],
                "change": preview["change"],
                "applied": True,
                "mountable": True,
                "validation_session_archived": True,
                "backup_retained": True,
                "rolled_back": False,
                "credential_changed": preview["credential_plan"]["change"] in {"create", "rotate", "replace"},
                "credential_removed": preview["credential_plan"]["change"] == "remove",
                "restart_required": preview["credential_plan"]["restart_required"],
                "deferred_enable": preview["credential_plan"]["deferred_enable"],
            }

    def _normalize_for_preview(
        self,
        preset: str,
        value: dict[str, Any],
        *,
        action: str,
        current: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        configuration = _normalize_configuration(value, action=action)
        old_credential = current.get("credential") if isinstance(current, dict) else None
        if action == "remove":
            return configuration, self._credential_plan(
                preset,
                configuration["server_name"],
                old_credential,
                None,
                rotate=False,
                requested_enabled=False,
            )

        if "credential" in value:
            new_credential, rotate = _normalize_credential(
                value.get("credential"),
                preset=preset,
                server_name=configuration["server_name"],
                transport=configuration["transport"],
                current=old_credential,
            )
        else:
            new_credential = dict(old_credential) if isinstance(old_credential, dict) else None
            rotate = False
        requested_enabled = configuration["enabled"]
        plan = self._credential_plan(
            preset,
            configuration["server_name"],
            old_credential,
            new_credential,
            rotate=rotate,
            requested_enabled=requested_enabled,
        )
        if plan["deferred_enable"]:
            configuration["enabled"] = False
        if new_credential is not None:
            configuration["credential"] = new_credential
        return configuration, plan

    def _credential_plan(
        self,
        preset: str,
        server_name: str,
        old_credential: dict[str, Any] | None,
        new_credential: dict[str, Any] | None,
        *,
        rotate: bool,
        requested_enabled: bool,
    ) -> dict[str, Any]:
        old_target = old_credential.get("target") if old_credential else None
        new_target = new_credential.get("target") if new_credential else None
        old_ref = _mcp_credential_reference(preset, server_name, old_target) if old_target else None
        new_ref = _mcp_credential_reference(preset, server_name, new_target) if new_target else None
        configured = self._credential_is_configured(new_ref) if new_ref else False
        if old_credential is None and new_credential is None:
            change = "none"
        elif new_credential is None:
            change = "remove"
        elif old_credential is None:
            change = "create"
        elif old_target != new_target:
            change = "replace"
        elif rotate:
            change = "rotate"
        else:
            change = "keep"
        requires_value = new_credential is not None and (
            change in {"create", "replace", "rotate"} or not configured
        )
        if requires_value and self.credential_store is None:
            raise AgentRuntimeError("secure credential storage is unavailable for this MCP configuration")
        loaded = bool(
            new_credential
            and new_credential["environment_ref"] in self.launch_credential_refs
        )
        restart_required = change in {"create", "replace", "rotate", "remove"} or bool(
            new_credential and configured and not loaded
        )
        deferred_enable = bool(requested_enabled and new_credential and (requires_value or not loaded))
        return {
            "change": change,
            "old_ref": old_ref,
            "new_ref": new_ref,
            "requires_value": requires_value,
            "restart_required": restart_required,
            "deferred_enable": deferred_enable,
        }

    def _credential_is_configured(self, reference: str | None) -> bool:
        if not reference or self.credential_store is None:
            return False
        try:
            value = self.credential_store.read(reference).get("secret")
        except CredentialError as error:
            raise AgentRuntimeError("MCP credential status could not be read from secure storage") from error
        return isinstance(value, str) and bool(value)

    def _public_configuration(self, preset: str, configuration: dict[str, Any]) -> dict[str, Any]:
        public = {key: value for key, value in configuration.items() if key != "credential"}
        credential = configuration.get("credential")
        if not isinstance(credential, dict):
            return public
        reference = _mcp_credential_reference(
            preset,
            configuration["server_name"],
            credential["target"],
        )
        configured = self._credential_is_configured(reference)
        loaded = credential["environment_ref"] in self.launch_credential_refs
        public["credential"] = {
            "target": credential["target"],
            "prefix": credential.get("prefix", ""),
            "configured": configured,
            "loaded_at_launch": loaded,
            "restart_required": configured and not loaded,
        }
        return public

    def _apply_credential_plan(
        self,
        preset: str,
        plan: dict[str, Any],
        credential_value: Any,
    ) -> list[tuple[str, dict[str, str]]]:
        del preset
        change = plan["change"]
        if change in {"none", "keep"}:
            if credential_value not in {None, ""}:
                raise AgentRuntimeError("MCP credential value was supplied without a credential update preview")
            return []
        if self.credential_store is None:
            raise AgentRuntimeError("secure credential storage is unavailable for this MCP configuration")
        if plan["requires_value"]:
            credential_value = _normalize_secret_value(credential_value)
        elif credential_value not in {None, ""}:
            raise AgentRuntimeError("MCP credential value was not expected for this preview")

        references = {
            reference
            for reference in (plan.get("old_ref"), plan.get("new_ref"))
            if isinstance(reference, str) and reference
        }
        snapshot: list[tuple[str, dict[str, str]]] = []
        try:
            snapshot = [(reference, self.credential_store.read(reference)) for reference in sorted(references)]
            if change in {"remove", "replace"} and plan.get("old_ref") != plan.get("new_ref"):
                self.credential_store.delete(plan["old_ref"])
            if plan["requires_value"]:
                self.credential_store.write(plan["new_ref"], {"secret": credential_value})
            return snapshot
        except CredentialError as error:
            self._restore_credential_snapshot(snapshot)
            raise AgentRuntimeError("MCP credential could not be updated in secure storage") from error

    def _restore_credential_snapshot(self, snapshot: list[tuple[str, dict[str, str]]]) -> bool:
        if not snapshot or self.credential_store is None:
            return True
        try:
            for reference, values in snapshot:
                if values:
                    self.credential_store.write(reference, values)
                else:
                    self.credential_store.delete(reference)
            return True
        except CredentialError:
            return False

    def _composition_path(self, preset: str) -> Path:
        if self.profile_dir is None or not self.profile_dir.is_absolute():
            raise AgentRuntimeError("managed DSH profile directory is not configured")
        root = self.profile_dir / _USER_PRESET_DIR
        directory = root / preset
        path = directory / _COMPOSITION_FILE
        try:
            resolved_root = root.resolve(strict=True)
            resolved_directory = directory.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
        except OSError as error:
            raise AgentRuntimeError("user Agent preset composition is unavailable") from error
        if resolved_directory.parent != resolved_root or resolved_path.parent != resolved_directory:
            raise AgentRuntimeError("user Agent preset composition escaped the managed preset root")
        for candidate in (root, directory, path):
            if _is_reparse_point(candidate):
                raise AgentRuntimeError("reparse points are not allowed in managed Agent preset paths")
        if not resolved_path.is_file():
            raise AgentRuntimeError("user Agent preset composition is not a regular file")
        return resolved_path

    @staticmethod
    def _read_composition(path: Path) -> tuple[str, bytes]:
        try:
            content = path.read_bytes()
        except OSError as error:
            raise AgentRuntimeError("user Agent preset composition could not be read") from error
        if len(content) > _MAX_COMPOSITION_BYTES:
            raise AgentRuntimeError("user Agent preset composition is too large for managed editing")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AgentRuntimeError("user Agent preset composition must be UTF-8") from error
        return text, content

    def _write_backup(self, preset: str, content: bytes) -> Path:
        assert self.profile_dir is not None
        directory = self.profile_dir / "sumika-backups" / "agent-presets" / preset
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        digest = _sha256(content)[:12]
        for suffix in range(100):
            name = f"{stamp}-{digest}{'' if suffix == 0 else f'-{suffix}'}.agent.cordis.yml"
            candidate = directory / name
            try:
                with candidate.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    candidate.chmod(0o600)
                except OSError:
                    pass
                return candidate
            except FileExistsError:
                continue
            except OSError as error:
                raise AgentRuntimeError("MCP preset backup could not be created") from error
        raise AgentRuntimeError("MCP preset backup name allocation failed")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".sumika-mcp-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, path)
            temporary = None
        except OSError as error:
            raise AgentRuntimeError("MCP preset composition could not be written atomically") from error
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _restore_if_unchanged(self, path: Path, expected_sha256: str, original: bytes) -> bool:
        try:
            if _sha256(path.read_bytes()) != expected_sha256:
                return False
            self._atomic_write(path, original)
            return _sha256(path.read_bytes()) == _sha256(original)
        except (OSError, AgentRuntimeError):
            return False

    def _prune_previews(self) -> None:
        now = time.time()
        expired = [token for token, item in self._previews.items() if item["expires_at"] <= now]
        for token in expired:
            self._previews.pop(token, None)
        while len(self._previews) >= _MAX_PREVIEWS:
            oldest = min(self._previews, key=lambda token: self._previews[token]["expires_at"])
            self._previews.pop(oldest, None)


def _normalize_configuration(value: dict[str, Any], *, action: str) -> dict[str, Any]:
    unknown = sorted(str(key) for key in value if str(key) not in _ALLOWED_CONFIGURATION_KEYS)
    if unknown:
        raise AgentRuntimeError(
            "unsupported MCP configuration fields: " + ", ".join(unknown)
        )
    server_name = value.get("server_name")
    if not isinstance(server_name, str) or _SERVER_NAME_RE.fullmatch(server_name.strip()) is None:
        raise AgentRuntimeError("MCP server_name must match [A-Za-z0-9_-]{1,32}")
    result: dict[str, Any] = {"server_name": server_name.strip()}
    if action == "remove":
        return result

    transport = str(value.get("transport") or "").strip().lower()
    if transport not in {"stdio", "streamable-http"}:
        raise AgentRuntimeError("MCP transport must be stdio or streamable-http")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise AgentRuntimeError("MCP enabled must be boolean")
    timeout = value.get("tool_call_timeout_ms", 60000)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1000 or timeout > 600000:
        raise AgentRuntimeError("MCP tool_call_timeout_ms must be an integer from 1000 to 600000")
    result.update(
        {
            "transport": transport,
            "enabled": enabled,
            "tool_call_timeout_ms": timeout,
        }
    )
    if transport == "stdio":
        command = _bounded_text(value.get("command"), "MCP command", 1024, required=True)
        args = value.get("args", [])
        if not isinstance(args, list) or len(args) > 64:
            raise AgentRuntimeError("MCP args must be an array with at most 64 entries")
        normalized_args = [
            _bounded_text(item, "MCP argument", 2048, required=False)
            for item in args
        ]
        cwd = _bounded_text(value.get("cwd"), "MCP cwd", 4096, required=False)
        if cwd:
            candidate = Path(cwd).expanduser()
            if not candidate.is_absolute() or not candidate.is_dir():
                raise AgentRuntimeError("MCP cwd must be an existing absolute directory")
            result["cwd"] = str(candidate)
        result["command"] = command
        result["args"] = normalized_args
    else:
        url = _bounded_text(value.get("url"), "MCP URL", 2048, required=True)
        try:
            parsed = urlparse(url)
        except ValueError as error:
            raise AgentRuntimeError("MCP URL is invalid") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise AgentRuntimeError("MCP URL must be HTTP(S) without credentials or fragments")
        result["url"] = url
    return result


def _bounded_text(value: Any, field: str, limit: int, *, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise AgentRuntimeError(f"{field} must be text")
    text = value.strip()
    if (required and not text) or len(text) > limit or any(ord(char) < 32 or ord(char) == 127 for char in text):
        qualifier = "non-empty " if required else ""
        raise AgentRuntimeError(f"{field} must be {qualifier}text of at most {limit} characters without controls")
    return text


def _server_name(value: dict[str, Any]) -> str:
    server_name = value.get("server_name")
    if not isinstance(server_name, str) or _SERVER_NAME_RE.fullmatch(server_name.strip()) is None:
        raise AgentRuntimeError("MCP server_name must match [A-Za-z0-9_-]{1,32}")
    return server_name.strip()


def _normalize_credential(
    value: Any,
    *,
    preset: str,
    server_name: str,
    transport: str,
    current: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, dict):
        raise AgentRuntimeError("MCP credential must be an object or null")
    unknown = sorted(str(key) for key in value if str(key) not in _ALLOWED_CREDENTIAL_KEYS)
    if unknown:
        raise AgentRuntimeError("unsupported MCP credential fields: " + ", ".join(unknown))
    target = _credential_target(value.get("target"), transport)
    prefix = _credential_prefix(value.get("prefix"))
    if transport == "stdio" and prefix:
        raise AgentRuntimeError("stdio MCP credentials do not support a prefix")
    rotate = value.get("rotate", False)
    if not isinstance(rotate, bool):
        raise AgentRuntimeError("MCP credential rotate must be boolean")
    same_binding = bool(
        current
        and current.get("target") == target
        and current.get("prefix", "") == prefix
    )
    if same_binding and not rotate:
        revision = str(current.get("revision") or "")
    else:
        revision = secrets.token_hex(8)
    if _CREDENTIAL_REVISION_RE.fullmatch(revision) is None:
        raise AgentRuntimeError("MCP credential revision is invalid")
    return {
        "target": target,
        "prefix": prefix,
        "revision": revision,
        "environment_ref": _mcp_environment_name(preset, server_name, target, revision),
    }, rotate


def _normalize_stored_credential(
    value: Any,
    *,
    preset: str,
    server_name: str,
    transport: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "target",
        "prefix",
        "revision",
        "environment_ref",
    }:
        raise AgentRuntimeError("managed MCP credential metadata is invalid")
    target = _credential_target(value.get("target"), transport)
    prefix = _credential_prefix(value.get("prefix"))
    if transport == "stdio" and prefix:
        raise AgentRuntimeError("stdio MCP credentials do not support a prefix")
    revision = str(value.get("revision") or "")
    if _CREDENTIAL_REVISION_RE.fullmatch(revision) is None:
        raise AgentRuntimeError("managed MCP credential revision is invalid")
    expected_environment = _mcp_environment_name(preset, server_name, target, revision)
    if value.get("environment_ref") != expected_environment:
        raise AgentRuntimeError("managed MCP credential environment reference was modified")
    return {
        "target": target,
        "prefix": prefix,
        "revision": revision,
        "environment_ref": expected_environment,
    }


def _credential_target(value: Any, transport: str) -> str:
    target = _bounded_text(value, "MCP credential target", 64, required=True)
    if transport == "stdio":
        if (
            _ENV_TARGET_RE.fullmatch(target) is None
            or target.upper() in _FORBIDDEN_ENV_TARGETS
            or target.upper().startswith("SUMIKA_")
            or _CREDENTIAL_SHAPE_RE.search(target) is None
        ):
            raise AgentRuntimeError("MCP credential target must be a non-reserved credential environment name")
    elif (
        _HEADER_TARGET_RE.fullmatch(target) is None
        or target.lower() in _FORBIDDEN_HEADERS
        or _CREDENTIAL_SHAPE_RE.search(target) is None
    ):
        raise AgentRuntimeError("MCP credential target must be a safe authentication header name")
    return target


def _credential_prefix(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 128:
        raise AgentRuntimeError("MCP credential prefix must be text of at most 128 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AgentRuntimeError("MCP credential prefix must not contain controls")
    return value


def _normalize_secret_value(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise AgentRuntimeError("MCP credential value is required")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise AgentRuntimeError("MCP credential value is not valid UTF-8") from error
    if size > _MAX_SECRET_UTF8_BYTES or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AgentRuntimeError(
            f"MCP credential value must be at most {_MAX_SECRET_UTF8_BYTES} UTF-8 bytes without controls"
        )
    return value


def _mcp_credential_reference(preset: str, server_name: str, target: str) -> str:
    digest = hashlib.sha256(f"{preset}\0{server_name}\0{target}".encode("utf-8")).hexdigest()[:32]
    return f"mcp-{digest}"


def _mcp_environment_name(preset: str, server_name: str, target: str, revision: str) -> str:
    digest = hashlib.sha256(
        f"{preset}\0{server_name}\0{target}\0{revision}".encode("utf-8")
    ).hexdigest()[:24].upper()
    return f"SUMIKA_MCP_{digest}_SECRET"


def _encode_metadata(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_metadata(value: str) -> dict[str, Any]:
    if len(value) > 16384:
        raise AgentRuntimeError("managed MCP metadata is too large")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        result = json.loads(decoded.decode("ascii"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AgentRuntimeError("managed MCP metadata is invalid") from error
    if not isinstance(result, dict):
        raise AgentRuntimeError("managed MCP metadata is invalid")
    return result


def _managed_blocks(text: str, preset: str) -> list[dict[str, Any]]:
    matches = [(match, 1) for match in _MARKER_V1_RE.finditer(text)]
    matches.extend((match, 2) for match in _MARKER_V2_RE.finditer(text))
    matches.sort(key=lambda item: item[0].start())
    if text.count(_MARKER_PREFIX) != len(matches) * 2:
        raise AgentRuntimeError("managed MCP markers are malformed; restore the preset before editing")
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_end = -1
    for match, version in matches:
        if match.start() < last_end:
            raise AgentRuntimeError("managed MCP markers overlap")
        last_end = match.end()
        name = match.group("name")
        if name in seen:
            raise AgentRuntimeError("managed MCP preset contains duplicate server names")
        seen.add(name)
        if version == 1:
            try:
                row = json.loads(match.group("row"))
            except json.JSONDecodeError as error:
                raise AgentRuntimeError("managed MCP row is not valid JSON") from error
            configuration = _configuration_from_row(name, row)
        else:
            metadata = _decode_metadata(match.group("metadata"))
            raw_configuration = metadata.get("configuration")
            if metadata.get("preset") != preset or not isinstance(raw_configuration, dict):
                raise AgentRuntimeError("managed MCP credential metadata belongs to another preset")
            if raw_configuration.get("server_name") != name:
                raise AgentRuntimeError("managed MCP credential metadata names another server")
            configuration = _normalize_configuration(raw_configuration, action="upsert")
            configuration["credential"] = _normalize_stored_credential(
                raw_configuration.get("credential"),
                preset=preset,
                server_name=name,
                transport=configuration["transport"],
            )
            if match.group("row") != _render_row(configuration):
                raise AgentRuntimeError("managed MCP credential row was modified")
        blocks.append({"start": match.start(), "end": match.end(), "configuration": configuration})
    return blocks


def _configuration_from_row(name: str, row: Any) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("name") != _PLUGIN_NAME:
        raise AgentRuntimeError("managed MCP row names an unexpected plugin")
    expected_id = _plugin_id(name)
    if row.get("id") != expected_id or not isinstance(row.get("config"), dict):
        raise AgentRuntimeError("managed MCP row identity is invalid")
    config = row["config"]
    if config.get("serverName") != name or config.get("failOnStartupError") is not True:
        raise AgentRuntimeError("managed MCP row safety fields were modified")
    value: dict[str, Any] = {
        "server_name": name,
        "transport": config.get("transport"),
        "enabled": row.get("disabled") is not True,
        "tool_call_timeout_ms": config.get("toolCallTimeoutMs", 60000),
    }
    if config.get("transport") == "stdio":
        value.update({"command": config.get("command"), "args": config.get("args", [])})
        if config.get("cwd") is not None:
            value["cwd"] = config.get("cwd")
        expected_keys = {"serverName", "transport", "command", "args", "toolCallTimeoutMs", "failOnStartupError"}
        if "cwd" in config:
            expected_keys.add("cwd")
    else:
        value["url"] = config.get("url")
        expected_keys = {"serverName", "transport", "url", "toolCallTimeoutMs", "failOnStartupError"}
    if set(config) != expected_keys:
        raise AgentRuntimeError("managed MCP row contains unsupported or credential-bearing fields")
    return _normalize_configuration(value, action="upsert")


def _render_row(configuration: dict[str, Any]) -> str:
    name = configuration["server_name"]
    config: dict[str, Any] = {
        "serverName": name,
        "transport": configuration["transport"],
    }
    if configuration["transport"] == "stdio":
        config["command"] = configuration["command"]
        config["args"] = configuration["args"]
        if configuration.get("cwd"):
            config["cwd"] = configuration["cwd"]
    else:
        config["url"] = configuration["url"]
    credential = configuration.get("credential")
    expression_placeholder = "__SUMIKA_MCP_JS_EXPRESSION__"
    if isinstance(credential, dict):
        environment_ref = credential["environment_ref"]
        if _MCP_ENVIRONMENT_RE.fullmatch(environment_ref) is None:
            raise AgentRuntimeError("managed MCP credential environment reference is invalid")
        if configuration["transport"] == "stdio":
            config["env"] = {credential["target"]: expression_placeholder}
            expression = f'process.env.{environment_ref} || ""'
        else:
            prefix = json.dumps(credential.get("prefix", ""), ensure_ascii=True)
            config["headers"] = {credential["target"]: expression_placeholder}
            expression = f'process.env.{environment_ref} ? {prefix} + process.env.{environment_ref} : ""'
    config["toolCallTimeoutMs"] = configuration["tool_call_timeout_ms"]
    config["failOnStartupError"] = True
    row = {
        "id": _plugin_id(name),
        "name": _PLUGIN_NAME,
        "disabled": not configuration["enabled"],
        "config": config,
    }
    rendered = json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if isinstance(credential, dict):
        marker = json.dumps(expression_placeholder)
        if rendered.count(marker) != 1:
            raise AgentRuntimeError("managed MCP credential expression could not be rendered")
        rendered = rendered.replace(marker, f"!!js {_yaml_single_quoted(expression)}")
    return rendered


def _render_block(preset: str, configuration: dict[str, Any], newline: str) -> str:
    name = configuration["server_name"]
    rendered = _render_row(configuration)
    if isinstance(configuration.get("credential"), dict):
        metadata = _encode_metadata({"preset": preset, "configuration": configuration})
        return (
            f"# sumika-managed-mcp:v2 begin {name}{newline}"
            f"# sumika-mcp-metadata:v2 {metadata}{newline}"
            f"- {rendered}{newline}"
            f"# sumika-managed-mcp:v2 end {name}{newline}"
        )
    return (
        f"# sumika-managed-mcp:v1 begin {name}{newline}"
        f"- {rendered}{newline}"
        f"# sumika-managed-mcp:v1 end {name}{newline}"
    )


def _yaml_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def load_mcp_launch_bindings(
    profile_dir: str | Path,
    credential_store: CredentialStore,
) -> list[tuple[str, str]]:
    """Load managed MCP secrets for one DSH launch without exposing references."""

    profile = Path(profile_dir)
    if not profile.is_absolute():
        raise AgentRuntimeError("managed DSH profile directory must be absolute")
    preset_root = profile / _USER_PRESET_DIR
    if not preset_root.exists():
        return []
    if not preset_root.is_dir() or _is_reparse_point(preset_root):
        raise AgentRuntimeError("managed DSH preset root is not a regular directory")
    bindings: dict[str, str] = {}
    try:
        preset_directories = sorted(preset_root.iterdir(), key=lambda item: item.name)
    except OSError as error:
        raise AgentRuntimeError("managed DSH preset root could not be read") from error
    for directory in preset_directories:
        if not directory.is_dir():
            continue
        preset = directory.name
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,159}", preset) is None:
            continue
        if _is_reparse_point(directory):
            raise AgentRuntimeError("reparse points are not allowed in managed Agent preset paths")
        composition = directory / _COMPOSITION_FILE
        if not composition.exists():
            continue
        if not composition.is_file() or _is_reparse_point(composition):
            raise AgentRuntimeError("managed MCP composition is not a regular file")
        try:
            content = composition.read_bytes()
        except OSError as error:
            raise AgentRuntimeError("managed MCP composition could not be read") from error
        if len(content) > _MAX_COMPOSITION_BYTES:
            raise AgentRuntimeError("managed MCP composition is too large")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AgentRuntimeError("managed MCP composition must be UTF-8") from error
        for block in _managed_blocks(text, preset):
            configuration = block["configuration"]
            credential = configuration.get("credential")
            if not isinstance(credential, dict):
                continue
            reference = _mcp_credential_reference(
                preset,
                configuration["server_name"],
                credential["target"],
            )
            try:
                value = credential_store.read(reference).get("secret")
            except CredentialError as error:
                raise AgentRuntimeError("MCP credential could not be read from secure storage") from error
            if not isinstance(value, str) or not value:
                if configuration["enabled"]:
                    raise AgentRuntimeError("an enabled MCP connection is missing its protected credential")
                continue
            secret = _normalize_secret_value(value)
            environment_name = credential["environment_ref"]
            previous = bindings.get(environment_name)
            if previous is not None and previous != secret:
                raise AgentRuntimeError("managed MCP credential environment names collide")
            bindings[environment_name] = secret
            if len(bindings) > _MAX_MCP_LAUNCH_BINDINGS:
                raise AgentRuntimeError("too many managed MCP credentials for one DSH launch")
    return sorted(bindings.items())


def _append_block(text: str, block: str, newline: str) -> str:
    if not text:
        return block
    separator = "" if text.endswith(("\n", "\r")) else newline
    if not text.endswith(newline * 2):
        separator += newline
    return text + separator + block


def _replace_block(text: str, block: dict[str, Any], replacement: str) -> str:
    return text[: block["start"]] + replacement + text[block["end"] :]


def _line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _plugin_id(server_name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", server_name.lower()).strip("-") or "server"
    digest = hashlib.sha256(server_name.encode("utf-8")).hexdigest()[:8]
    return f"sumika-mcp-{slug[:24]}-{digest}"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        details = path.lstat()
    except OSError:
        return True
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(details, "st_file_attributes", 0)
    return path.is_symlink() or bool(marker and attributes & marker)
