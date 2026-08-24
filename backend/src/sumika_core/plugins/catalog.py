"""Safe local plugin manifest discovery and approval bookkeeping.

Discovery is deliberately metadata-only.  It never imports an entrypoint,
starts a process, installs dependencies, or changes files in a plugin folder.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..protocol.models import utc_now
from ..storage import Storage
from .manifest import ManifestError, load_manifest


class PluginCatalogError(ValueError):
    """Raised when a plugin candidate cannot be safely inspected or approved."""


class PluginCatalog:
    """Persist local manifest candidates without loading third-party code."""

    _MAX_MANIFEST_BYTES = 256 * 1024
    _MAX_CANDIDATES = 200
    _MAX_SCAN_DEPTH = 4
    _SKIP_DIRECTORIES = {".git", ".sumika", "__pycache__", "node_modules", "deprecated"}

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def list(self) -> list[dict[str, Any]]:
        return self.storage.list_plugin_registrations()

    def get_registration(self, candidate_id: str) -> dict[str, Any] | None:
        """Return a persisted registration without inspecting or executing it."""

        return self.storage.get_plugin_registration(candidate_id)

    def discover(self, paths: str | Path | Iterable[str | Path]) -> list[dict[str, Any]]:
        roots = _normalise_paths(paths)
        manifest_paths: list[Path] = []
        for root in roots:
            manifest_paths.extend(self._manifest_paths(root))
        unique_paths = sorted({path for path in manifest_paths}, key=lambda item: str(item).casefold())
        if len(unique_paths) > self._MAX_CANDIDATES:
            raise PluginCatalogError(f"plugin discovery found more than {self._MAX_CANDIDATES} manifests")
        results = []
        for manifest_path in unique_paths:
            result = self._inspect(manifest_path)
            self.storage.upsert_plugin_registration(result)
            results.append(result)
        return results

    def approve(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.storage.get_plugin_registration(candidate_id)
        if candidate is None:
            raise PluginCatalogError(f"Unknown plugin candidate: {candidate_id}")
        if candidate["state"] == "invalid":
            raise PluginCatalogError("invalid plugin manifests must be fixed and discovered again")
        try:
            manifest_path = _absolute_file(candidate["manifest_path"], "manifest path")
        except PluginCatalogError as exc:
            raise PluginCatalogError(f"cannot approve missing manifest: {exc}") from exc
        inspected = self._inspect(manifest_path)
        if inspected["state"] == "invalid":
            raise PluginCatalogError(str(inspected.get("error") or "manifest is invalid"))
        if (
            inspected["manifest_sha256"] != candidate["manifest_sha256"]
            or inspected["entrypoint_sha256"] != candidate.get("entrypoint_sha256", "")
        ):
            raise PluginCatalogError("manifest changed since discovery; discover it again before approval")
        if inspected["candidate_id"] != candidate_id:
            raise PluginCatalogError("plugin candidate path no longer matches the discovered candidate")
        inspected.update(
            state="approved",
            approved_at=utc_now(),
            discovered_at=candidate["discovered_at"],
            updated_at=utc_now(),
            error=None,
        )
        self.storage.upsert_plugin_registration(inspected)
        return inspected

    def revoke(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.storage.get_plugin_registration(candidate_id)
        if candidate is None:
            raise PluginCatalogError(f"Unknown plugin candidate: {candidate_id}")
        candidate["state"] = "revoked"
        candidate["approved_at"] = None
        candidate["updated_at"] = utc_now()
        candidate["error"] = None
        candidate["launcher"] = {}
        candidate["configured_at"] = None
        self.storage.upsert_plugin_registration(candidate)
        return self.storage.get_plugin_registration(candidate_id)  # type: ignore[return-value]

    def configure_launcher(self, candidate_id: str, launcher: dict[str, Any]) -> dict[str, Any]:
        candidate = self._current_approved(candidate_id, None)
        manifest = candidate["manifest"]
        root_path = Path(candidate["root_path"])
        entrypoint = _entrypoint_path(root_path, str(manifest["entrypoint"]))
        normalized = _normalize_launcher(launcher, entrypoint)
        now = utc_now()
        updated = self.storage.update_plugin_launcher(candidate_id, normalized, now, now)
        if updated is None:
            raise PluginCatalogError(f"Unknown plugin candidate: {candidate_id}")
        return updated

    def prepare_tool_run(self, candidate_id: str) -> dict[str, Any]:
        return self.prepare_provider_run(candidate_id, "tool")

    def prepare_provider_run(self, candidate_id: str, capability: str) -> dict[str, Any]:
        """Revalidate an approved external provider immediately before use."""

        candidate = self._current_approved(candidate_id, capability)
        launcher = candidate.get("launcher")
        if not isinstance(launcher, dict) or not launcher:
            raise PluginCatalogError("plugin launcher is not configured")
        manifest = candidate["manifest"]
        entrypoint = _entrypoint_path(Path(candidate["root_path"]), str(manifest["entrypoint"]))
        normalized = _normalize_launcher(launcher, entrypoint)
        return {
            "candidate_id": candidate["candidate_id"],
            "plugin_id": candidate["plugin_id"],
            "launcher": normalized,
        }

    def _current_approved(self, candidate_id: str, capability: str | None) -> dict[str, Any]:
        candidate = self.storage.get_plugin_registration(candidate_id)
        if candidate is None:
            raise PluginCatalogError(f"Unknown plugin candidate: {candidate_id}")
        if candidate.get("state") != "approved":
            raise PluginCatalogError("plugin must be approved before it can be configured or run")
        manifest_path = _absolute_file(candidate["manifest_path"], "manifest path")
        inspected = self._inspect(manifest_path)
        if (
            inspected["manifest_sha256"] != candidate["manifest_sha256"]
            or inspected["entrypoint_sha256"] != candidate.get("entrypoint_sha256", "")
        ):
            self.storage.upsert_plugin_registration(inspected)
            raise PluginCatalogError("manifest changed since approval; discover and approve it again")
        if inspected.get("state") != "approved":
            self.storage.upsert_plugin_registration(inspected)
            raise PluginCatalogError("manifest is no longer approved")
        manifest = inspected.get("manifest")
        capabilities = manifest.get("capabilities", []) if isinstance(manifest, dict) else []
        if capability is not None and capability not in capabilities:
            raise PluginCatalogError(f"plugin does not declare capability: {capability}")
        return inspected

    def _manifest_paths(self, root: Path) -> list[Path]:
        resolved = _absolute_path(root, "plugin discovery path")
        if resolved.is_file():
            if resolved.name.casefold() != "manifest.json":
                raise PluginCatalogError("discovery file must be named manifest.json")
            return [resolved]
        if not resolved.is_dir():
            raise PluginCatalogError("plugin discovery path must be a directory or manifest.json")
        paths: list[Path] = []
        for current, directories, files in os.walk(resolved, topdown=True, followlinks=False):
            current_path = Path(current)
            relative_depth = len(current_path.relative_to(resolved).parts)
            if relative_depth >= self._MAX_SCAN_DEPTH:
                directories[:] = []
            else:
                directories[:] = sorted(
                    name
                    for name in directories
                    if name not in self._SKIP_DIRECTORIES and not (current_path / name).is_symlink()
                )
            for name in sorted(files):
                if name.casefold() != "manifest.json":
                    continue
                candidate = current_path / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                paths.append(candidate.resolve(strict=True))
                if len(paths) > self._MAX_CANDIDATES:
                    raise PluginCatalogError(f"plugin discovery found more than {self._MAX_CANDIDATES} manifests")
        return paths

    def _inspect(self, manifest_path: Path) -> dict[str, Any]:
        path = _absolute_file(manifest_path, "manifest path")
        candidate_id = _candidate_id(path)
        root_path = path.parent.resolve(strict=True)
        existing = self.storage.get_plugin_registration(candidate_id)
        discovered_at = existing["discovered_at"] if existing else utc_now()
        try:
            raw = path.read_bytes()
            if len(raw) > self._MAX_MANIFEST_BYTES:
                raise PluginCatalogError("manifest is too large")
            manifest_sha256 = hashlib.sha256(raw).hexdigest()
            manifest = load_manifest(path)
            entrypoint = _entrypoint_path(root_path, manifest.entrypoint)
            if not entrypoint.is_file():
                raise PluginCatalogError(f"entrypoint does not exist: {manifest.entrypoint}")
            entrypoint_sha256 = _file_sha256(entrypoint)
            result = {
                "candidate_id": candidate_id,
                "plugin_id": manifest.id,
                "version": manifest.version,
                "root_path": str(root_path),
                "manifest_path": str(path),
                "manifest": manifest.to_dict(),
                "manifest_sha256": manifest_sha256,
                "entrypoint_sha256": _file_sha256(entrypoint),
                "state": _same_registration_state(existing, manifest_sha256, entrypoint_sha256),
                "error": None,
                "discovered_at": discovered_at,
                "approved_at": existing.get("approved_at") if existing and existing.get("manifest_sha256") == manifest_sha256 and existing.get("entrypoint_sha256") == entrypoint_sha256 and existing.get("state") == "approved" else None,
                "launcher": existing.get("launcher", {}) if existing and existing.get("manifest_sha256") == manifest_sha256 and existing.get("entrypoint_sha256") == entrypoint_sha256 else {},
                "configured_at": existing.get("configured_at") if existing and existing.get("manifest_sha256") == manifest_sha256 and existing.get("entrypoint_sha256") == entrypoint_sha256 else None,
                "entrypoint_sha256": entrypoint_sha256,
                "updated_at": utc_now(),
            }
            if result["state"] == "approved" and result["approved_at"] is None:
                result["state"] = "discovered"
            return result
        except (OSError, ManifestError, PluginCatalogError, UnicodeError) as exc:
            return {
                "candidate_id": candidate_id,
                "plugin_id": existing.get("plugin_id", "") if existing else "",
                "version": existing.get("version", "") if existing else "",
                "root_path": str(root_path),
                "manifest_path": str(path),
                "manifest": existing.get("manifest", {}) if existing else {},
                "manifest_sha256": _file_sha256(path),
                "entrypoint_sha256": "",
                "state": "invalid",
                "error": str(exc),
                "discovered_at": discovered_at,
                "approved_at": None,
                "launcher": {},
                "configured_at": None,
                "updated_at": utc_now(),
            }


def _normalise_paths(paths: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(paths, (str, Path)):
        values: list[str | Path] = [paths]
    else:
        values = list(paths)
    if not values or len(values) > 32:
        raise PluginCatalogError("plugin discovery requires between 1 and 32 paths")
    return [_absolute_path(value, "plugin discovery path") for value in values]


def _absolute_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PluginCatalogError(f"{label} must be an absolute path")
    if path.is_symlink():
        raise PluginCatalogError(f"{label} symlinks are not accepted")
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PluginCatalogError(f"{label} is not readable") from exc


def _absolute_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PluginCatalogError(f"{label} must be an absolute path")
    if path.is_symlink():
        raise PluginCatalogError(f"{label} symlinks are not accepted")
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PluginCatalogError(f"{label} is not readable") from exc
    if not path.is_file():
        raise PluginCatalogError(f"{label} must point to a regular file")
    return path


def _entrypoint_path(root: Path, entrypoint: str) -> Path:
    raw_path = root / Path(entrypoint.replace("\\", "/"))
    if raw_path.is_symlink():
        raise PluginCatalogError("entrypoint symlinks are not accepted")
    path = raw_path.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PluginCatalogError("entrypoint escapes the plugin directory") from exc
    return path


def _normalize_launcher(launcher: Any, entrypoint: Path) -> dict[str, Any]:
    if not isinstance(launcher, dict):
        raise PluginCatalogError("launcher must be an object")
    executable_value = launcher.get("executable")
    if not isinstance(executable_value, str) or not executable_value.strip():
        raise PluginCatalogError("launcher executable is required")
    executable = _launcher_file(executable_value, "launcher executable")

    arguments = launcher.get("arguments", [])
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise PluginCatalogError("launcher arguments must be a list of strings")
    if len(arguments) > 64 or any(len(value) > 4096 for value in arguments):
        raise PluginCatalogError("launcher arguments are too large")
    if executable != entrypoint and not any(_argument_targets(argument, entrypoint) for argument in arguments):
        raise PluginCatalogError("launcher arguments must include the manifest entrypoint")

    working_directory = None
    working_value = launcher.get("working_directory")
    if working_value not in (None, ""):
        if not isinstance(working_value, str):
            raise PluginCatalogError("launcher working_directory must be a string")
        working_directory = _launcher_directory(working_value, "launcher working_directory")

    timeout_seconds = launcher.get("timeout_seconds", 30)
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
        or timeout_seconds > 120
    ):
        raise PluginCatalogError("launcher timeout_seconds must be an integer between 1 and 120")
    return {
        "executable": str(executable),
        "arguments": list(arguments),
        "working_directory": str(working_directory) if working_directory else None,
        "timeout_seconds": timeout_seconds,
    }


def _launcher_file(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PluginCatalogError(f"{label} must be an absolute path")
    if path.is_symlink():
        raise PluginCatalogError(f"{label} symlinks are not accepted")
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PluginCatalogError(f"{label} is not readable") from exc
    if not path.is_file():
        raise PluginCatalogError(f"{label} must point to a file")
    return path


def _launcher_directory(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise PluginCatalogError(f"{label} must be an absolute path")
    if path.is_symlink():
        raise PluginCatalogError(f"{label} symlinks are not accepted")
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PluginCatalogError(f"{label} is not readable") from exc
    if not path.is_dir():
        raise PluginCatalogError(f"{label} must point to a directory")
    return path


def _argument_targets(argument: str, entrypoint: Path) -> bool:
    path = Path(argument).expanduser()
    if not path.is_absolute():
        return False
    try:
        return path.resolve(strict=False) == entrypoint
    except (OSError, RuntimeError):
        return False


def _candidate_id(path: Path) -> str:
    value = os.path.normcase(str(path))
    return "plugin-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _file_sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _same_registration_state(
    existing: dict[str, Any] | None,
    manifest_sha256: str,
    entrypoint_sha256: str,
) -> str:
    if (
        not existing
        or existing.get("manifest_sha256") != manifest_sha256
        or existing.get("entrypoint_sha256", "") != entrypoint_sha256
    ):
        return "changed" if existing else "discovered"
    if existing.get("state") == "approved":
        return "approved"
    if existing.get("state") == "revoked":
        return "revoked"
    return "discovered"
