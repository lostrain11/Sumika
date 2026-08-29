"""Metadata-only discovery and approval bookkeeping for user Skills.

The catalog never imports, executes, installs, or rewrites a Skill.  It only
reads a bounded ``SKILL.md`` file and stores a content hash plus safe metadata.
The DSH session-level ``skill.list`` response remains the source of truth for
what is active in a running session.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..protocol.models import utc_now
from ..storage import Storage


class SkillCatalogError(ValueError):
    """Raised when a Skill candidate cannot be safely inspected or changed."""


class SkillCatalog:
    """Persist local Skill candidates without reading their instruction body."""

    _MAX_FILE_BYTES = 512 * 1024
    _MAX_CANDIDATES = 256
    _MAX_SCAN_DEPTH = 3
    _MAX_DESCRIPTION = 320
    _MAX_PERMISSIONS = 32
    _MAX_PERMISSION_LENGTH = 96
    _SKIP_DIRECTORIES = {".git", ".sumika", "__pycache__", "node_modules", "deprecated"}
    _ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$", re.IGNORECASE)

    def __init__(
        self,
        storage: Storage,
        *,
        default_paths: Iterable[str | Path] = (),
        logger: Any = None,
    ) -> None:
        self.storage = storage
        self.default_paths = tuple(_configured_path(item, "default Skill path") for item in default_paths)
        self.logger = logger

    def list(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if refresh:
            self.refresh()
        return [self._public(row) for row in self.storage.list_skill_registrations()]

    def discover(self, paths: str | Path | Iterable[str | Path] | None = None) -> list[dict[str, Any]]:
        roots = self._roots(paths)
        candidates: list[Path] = []
        for root in roots:
            candidates.extend(self._skill_paths(root))
            if len(candidates) > self._MAX_CANDIDATES:
                raise SkillCatalogError(
                    f"Skill discovery found more than {self._MAX_CANDIDATES} SKILL.md files"
                )
        unique_paths = sorted(set(candidates), key=lambda item: str(item).casefold())
        results: list[dict[str, Any]] = []
        for path in unique_paths:
            inspected = self._inspect(path)
            self.storage.upsert_skill_registration(inspected)
            results.append(self._public(inspected))
        return results

    def refresh(self) -> list[dict[str, Any]]:
        """Recheck hashes for registered paths; never removes a tombstone."""

        refreshed: list[dict[str, Any]] = []
        for row in self.storage.list_skill_registrations():
            path = row.get("skill_path")
            if not isinstance(path, str) or not path:
                continue
            inspected = self._inspect(Path(path))
            self.storage.upsert_skill_registration(inspected)
            refreshed.append(self._public(inspected))
        return refreshed

    def approve(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.storage.get_skill_registration(candidate_id)
        if candidate is None:
            raise SkillCatalogError(f"Unknown Skill candidate: {candidate_id}")
        if candidate.get("state") == "invalid":
            raise SkillCatalogError("invalid Skill metadata must be fixed and discovered again")
        if candidate.get("state") == "changed":
            raise SkillCatalogError("SKILL.md changed since discovery; discover it again before approval")
        inspected = self._inspect(Path(str(candidate["skill_path"])))
        if inspected.get("state") == "invalid":
            raise SkillCatalogError(str(inspected.get("error") or "Skill metadata is invalid"))
        if inspected.get("candidate_id") != candidate_id:
            raise SkillCatalogError("Skill candidate path no longer matches the discovered candidate")
        if inspected.get("manifest_sha256") != candidate.get("manifest_sha256"):
            raise SkillCatalogError("SKILL.md changed since discovery; discover it again before approval")
        inspected.update(
            state="approved",
            approved_at=utc_now(),
            discovered_at=candidate.get("discovered_at") or utc_now(),
            updated_at=utc_now(),
            error=None,
        )
        self.storage.upsert_skill_registration(inspected)
        return self._public(inspected)

    def revoke(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.storage.get_skill_registration(candidate_id)
        if candidate is None:
            raise SkillCatalogError(f"Unknown Skill candidate: {candidate_id}")
        candidate["state"] = "revoked"
        candidate["approved_at"] = None
        candidate["updated_at"] = utc_now()
        candidate["error"] = None
        self.storage.upsert_skill_registration(candidate)
        updated = self.storage.get_skill_registration(candidate_id)
        if updated is None:
            raise SkillCatalogError("Skill registration disappeared while revoking")
        return self._public(updated)

    def default_path_labels(self) -> list[str]:
        return [_path_label(path) for path in self.default_paths]

    def _roots(self, paths: str | Path | Iterable[str | Path] | None) -> list[Path]:
        if paths is None:
            values: Iterable[str | Path] = self.default_paths
            allow_missing = True
        else:
            values = [paths] if isinstance(paths, (str, Path)) else paths
            allow_missing = False
        roots: list[Path] = []
        for value in values:
            path = _configured_path(value, "Skill discovery path")
            if not path.exists():
                if allow_missing:
                    continue
                raise SkillCatalogError(f"Skill discovery path does not exist: {_path_label(path)}")
            if not path.is_file() and not path.is_dir():
                raise SkillCatalogError("Skill discovery path must be a directory or SKILL.md")
            roots.append(path.resolve(strict=True))
        if len(roots) > 16:
            raise SkillCatalogError("Skill discovery accepts at most 16 paths")
        return roots

    def _skill_paths(self, root: Path) -> list[Path]:
        if root.is_file():
            if root.name.casefold() != "skill.md":
                raise SkillCatalogError("discovery file must be named SKILL.md")
            return [root]
        paths: list[Path] = []
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            relative_depth = len(current_path.relative_to(root).parts)
            if relative_depth >= self._MAX_SCAN_DEPTH:
                directories[:] = []
            else:
                directories[:] = sorted(
                    name
                    for name in directories
                    if name not in self._SKIP_DIRECTORIES
                    and not (current_path / name).is_symlink()
                )
            for name in sorted(files):
                if name.casefold() != "skill.md":
                    continue
                candidate = current_path / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                try:
                    paths.append(candidate.resolve(strict=True))
                except (OSError, RuntimeError):
                    continue
        return paths

    def _inspect(self, skill_path: Path) -> dict[str, Any]:
        # Resolve the identity even when the file has disappeared so the
        # registration remains an auditable invalid tombstone.
        path = _configured_path(skill_path, "Skill path")
        candidate_id = _candidate_id(path)
        existing = self.storage.get_skill_registration(candidate_id)
        discovered_at = existing.get("discovered_at") if existing else utc_now()
        try:
            path = _regular_file(path, "Skill path")
            raw = path.read_bytes()
            if len(raw) > self._MAX_FILE_BYTES:
                raise SkillCatalogError("SKILL.md is too large")
            digest = hashlib.sha256(raw).hexdigest()
            text = raw.decode("utf-8")
            metadata = _parse_metadata(text, path.parent.name)
            state = _same_state(existing, digest)
            return {
                "candidate_id": candidate_id,
                "skill_id": metadata["skill_id"],
                "name": metadata["name"],
                "description": metadata["description"],
                "version": metadata["version"],
                "root_path": str(path.parent.resolve()),
                "skill_path": str(path),
                "source": metadata["source"],
                "permissions": metadata["permissions"],
                "metadata": metadata,
                "manifest_sha256": digest,
                "state": state,
                "error": None,
                "discovered_at": discovered_at,
                "approved_at": (
                    existing.get("approved_at")
                    if existing
                    and existing.get("manifest_sha256") == digest
                    and existing.get("state") == "approved"
                    else None
                ),
                "updated_at": utc_now(),
            }
        except (OSError, UnicodeError, SkillCatalogError) as exc:
            return {
                "candidate_id": candidate_id,
                "skill_id": existing.get("skill_id", path.parent.name) if existing else path.parent.name,
                "name": existing.get("name", path.parent.name) if existing else path.parent.name,
                "description": existing.get("description", "") if existing else "",
                "version": existing.get("version", "") if existing else "",
                "root_path": str(path.parent),
                "skill_path": str(path),
                "source": existing.get("source", "local") if existing else "local",
                "permissions": existing.get("permissions", []) if existing else [],
                "metadata": existing.get("metadata", {}) if existing else {},
                "manifest_sha256": _file_sha256(path),
                "state": "invalid",
                "error": str(exc),
                "discovered_at": discovered_at,
                "approved_at": None,
                "updated_at": utc_now(),
            }

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        """Return a path-free, body-free projection for API/UI consumers."""

        state = str(row.get("state") or "invalid")
        return {
            "candidate_id": row.get("candidate_id"),
            "skill_id": row.get("skill_id"),
            "name": row.get("name"),
            "description": row.get("description"),
            "version": row.get("version"),
            "source": row.get("source") or "local",
            "permissions": list(row.get("permissions") or [])[: SkillCatalog._MAX_PERMISSIONS],
            "path_label": _path_label(Path(str(row.get("skill_path") or "SKILL.md"))),
            "manifest_sha256": row.get("manifest_sha256") or "",
            "state": state,
            "approved_at": row.get("approved_at"),
            "discovered_at": row.get("discovered_at"),
            "updated_at": row.get("updated_at"),
            "metadata_only": True,
            "hash_changed": state == "changed",
            "error": _safe_error(row.get("error")),
        }


def _configured_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SkillCatalogError(f"{label} must be an absolute path")
    if path.is_symlink():
        raise SkillCatalogError(f"{label} symlinks are not accepted")
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise SkillCatalogError(f"{label} is not readable") from exc


def _regular_file(value: str | Path, label: str) -> Path:
    path = _configured_path(value, label)
    if not path.is_file() or path.name.casefold() != "skill.md":
        raise SkillCatalogError(f"{label} must point to a regular SKILL.md file")
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SkillCatalogError(f"{label} is not readable") from exc


def _candidate_id(path: Path) -> str:
    normalized = os.path.normcase(str(path))
    return "skill-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _same_state(existing: dict[str, Any] | None, digest: str) -> str:
    if not existing or existing.get("manifest_sha256") != digest:
        return "changed" if existing else "discovered"
    if existing.get("state") == "approved":
        return "approved"
    if existing.get("state") == "revoked":
        return "revoked"
    return "discovered"


def _parse_metadata(text: str, folder_name: str) -> dict[str, Any]:
    frontmatter: dict[str, str] = {}
    lines = text.splitlines()
    body_start = 0
    if lines and lines[0].strip() == "---":
        closing = next((index for index in range(1, min(len(lines), 160)) if lines[index].strip() == "---"), None)
        if closing is None:
            raise SkillCatalogError("SKILL.md frontmatter is not closed")
        body_start = closing + 1
        for line in lines[1:closing]:
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            if not re.fullmatch(r"[a-z0-9_-]{1,48}", key):
                continue
            frontmatter[key] = _strip_scalar(value.strip())

    heading = next((line.strip()[2:].strip() for line in lines[body_start:] if line.strip().startswith("# ")), "")
    name = _bounded_text(frontmatter.get("name") or heading or folder_name, 120) or folder_name
    # Do not infer a description from the Markdown body.  A Skill body is
    # executable instruction material and must never cross the catalog API.
    description = _bounded_text(frontmatter.get("description"), 320)
    raw_id = frontmatter.get("id") or _slug(name) or _slug(folder_name) or "skill"
    skill_id = raw_id if SkillCatalog._ID_RE.fullmatch(raw_id) else (_slug(folder_name) or "skill")
    version = _bounded_text(frontmatter.get("version") or frontmatter.get("skill-version"), 64)
    source = _bounded_text(frontmatter.get("source") or "local", 80) or "local"
    permissions = _parse_permissions(
        frontmatter.get("permissions") or frontmatter.get("allowed-tools") or frontmatter.get("tools") or ""
    )
    return {
        "skill_id": skill_id,
        "name": name,
        "description": description,
        "version": version,
        "source": source,
        "permissions": permissions,
    }


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].replace("\\n", " ")
    return value


def _parse_permissions(value: str) -> list[str]:
    raw = value.strip().strip("[]")
    if not raw:
        return []
    values = re.split(r"[,\s]+", raw)
    result: list[str] = []
    for item in values:
        cleaned = _strip_scalar(item.strip())
        if not cleaned or len(cleaned) > SkillCatalog._MAX_PERMISSION_LENGTH:
            continue
        if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
            continue
        if cleaned not in result:
            result.append(cleaned)
        if len(result) >= SkillCatalog._MAX_PERMISSIONS:
            break
    return result


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value[:limit].strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(value).strip().lower()).strip("-._")
    return slug[:96]


def _path_label(path: Path) -> str:
    """Return a structural label without exposing user/project path segments.

    Catalog projections and audit events must remain useful without copying an
    absolute path (which can contain a Windows account name or repository
    location).  Keep only the conventional Skill directory markers and the
    candidate folder name.
    """

    parts = [part for part in path.parts if part not in {path.anchor, ""}]
    lowered = [part.casefold() for part in parts]
    if path.name.casefold() == "skill.md":
        parent = path.parent.name or "skill"
        return f"{parent}/SKILL.md"
    for index, part in enumerate(lowered[:-1]):
        if part == ".agents" and lowered[index + 1] == "skills":
            return ".agents/skills"
    if path.name.casefold() == "skills":
        return "skills"
    return "自定义 Skill 目录" if path.name else "Skill 目录"


def _safe_error(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    return text[:240]


__all__ = ["SkillCatalog", "SkillCatalogError"]
