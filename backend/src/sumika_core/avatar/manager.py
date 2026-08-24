"""Safe local Avatar asset registration and character binding."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..storage import Storage
from .base import AvatarState, NullAvatarDriver, PreviewAvatarDriver


class AvatarError(ValueError):
    """Raised when an Avatar asset or binding is invalid."""


class AvatarManager:
    """Manage model metadata and renderer selection without loading binaries."""

    _DRIVERS = {"none", "live2d", "vrm"}

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.driver: NullAvatarDriver | PreviewAvatarDriver = NullAvatarDriver()
        self.active_character_id: str | None = None
        self.active_model: dict[str, Any] | None = None

    def list_models(self) -> list[dict[str, Any]]:
        return self.storage.list_avatar_models()

    def discover_directory(
        self,
        directory: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
        exclude_paths: set[str | Path] | None = None,
    ) -> list[dict[str, Any]]:
        """Register supported model manifests found directly under a managed directory.

        Discovery only reads file metadata. It skips symlinks and unsupported files,
        and never removes registrations when a file is later moved or deleted.
        """
        root = Path(directory).expanduser()
        if not root.is_absolute():
            raise AvatarError("model discovery directory must be absolute")
        try:
            root = root.resolve(strict=True)
        except OSError as exc:
            raise AvatarError(f"model discovery directory is not readable: {directory}") from exc
        if not root.is_dir():
            raise AvatarError("model discovery path must point to a directory")
        excluded = {
            Path(path).expanduser().resolve()
            for path in (exclude_paths or set())
        }

        discovered: list[dict[str, Any]] = []
        for candidate in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.resolve() in excluded:
                continue
            try:
                detected_kind = _detect_kind(candidate)
            except AvatarError:
                continue
            try:
                discovered.append(
                    self.import_model(
                        str(candidate),
                        kind=detected_kind,
                        metadata=dict(metadata or {}),
                    )
                )
            except AvatarError:
                continue
        return discovered

    def import_model(
        self,
        path: str,
        *,
        name: str | None = None,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(path, str) or not path.strip():
            raise AvatarError("path must not be empty")
        model_path = Path(path).expanduser()
        if not model_path.is_absolute():
            raise AvatarError("model path must be absolute")
        try:
            resolved_path = model_path.resolve(strict=True)
        except OSError as exc:
            raise AvatarError(f"model path is not readable: {path}") from exc
        if not resolved_path.is_file():
            raise AvatarError("model path must point to a file")
        detected_kind = _detect_kind(resolved_path)
        if kind is not None and kind != detected_kind:
            raise AvatarError(f"model type does not match extension: {kind}")
        existing = self.storage.find_avatar_model(str(resolved_path))
        if existing is not None:
            return existing
        stat = resolved_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        stored_metadata = dict(metadata or {})
        stored_metadata.update({"extension": resolved_path.suffix.lower(), "availability": "available"})
        return self.storage.create_avatar_model(
            model_id=f"avatar-{uuid4().hex[:12]}",
            name=(name or _display_name(resolved_path)),
            kind=detected_kind,
            path=str(resolved_path),
            size_bytes=stat.st_size,
            modified_at=modified_at,
            metadata=stored_metadata,
        )

    def refresh_model(self, model_id: str) -> dict[str, Any]:
        """Refresh stored file metadata without loading the model binary."""
        model = self.storage.get_avatar_model(model_id)
        if model is None:
            raise AvatarError(f"Unknown Avatar model: {model_id}")
        model_path = Path(model["path"])
        try:
            resolved_path = model_path.resolve(strict=True)
        except OSError as exc:
            raise AvatarError(f"model path is not readable: {model['path']}") from exc
        if not resolved_path.is_file():
            raise AvatarError("model path must point to a file")
        detected_kind = _detect_kind(resolved_path)
        if detected_kind != model["kind"]:
            raise AvatarError("registered model type no longer matches the file extension")
        stat = resolved_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        metadata = dict(model.get("metadata") or {})
        metadata.update({"extension": resolved_path.suffix.lower(), "availability": "available"})
        updated = self.storage.update_avatar_model(
            model_id,
            size_bytes=stat.st_size,
            modified_at=modified_at,
            metadata=metadata,
        )
        if updated is None:
            raise AvatarError(f"Unknown Avatar model: {model_id}")
        if self.active_model and self.active_model.get("id") == model_id:
            self.active_model = updated
            self.driver.state.metadata.update(
                {"kind": updated["kind"], "name": updated["name"], "path": updated["path"]}
            )
        return updated

    def inspect_model(self, model_id: str) -> dict[str, Any]:
        """Inspect a registered model without loading its renderer binary."""
        model = self.storage.get_avatar_model(model_id)
        if model is None:
            raise AvatarError(f"Unknown Avatar model: {model_id}")
        if model["kind"] == "live2d":
            return inspect_live2d_manifest(model["path"])
        if model["kind"] == "vrm":
            path = Path(model["path"])
            available = path.is_file()
            return {
                "kind": "vrm",
                "path": str(path),
                "status": "ready" if available else "error",
                "valid": available,
                "available": available,
                "format": "VRM",
                "referenced_files": [],
                "counts": {},
                "errors": [] if available else ["model file is missing"],
                "warnings": [],
            }
        raise AvatarError(f"Unsupported Avatar model kind: {model['kind']}")

    def unregister_model(self, model_id: str) -> dict[str, Any]:
        """Remove a registration while leaving the user's model file untouched."""
        model, bindings = self.storage.remove_avatar_model_if_unbound(model_id)
        if model is None:
            raise AvatarError(f"Unknown Avatar model: {model_id}")
        if bindings:
            names = ", ".join(binding["name"] for binding in bindings)
            raise AvatarError(f"Avatar model is still bound to: {names}")
        if self.active_model and self.active_model.get("id") == model_id:
            self.driver.close()
            self.driver = NullAvatarDriver()
            self.active_model = None
        return {"model": model}

    def select(self, character_id: str, *, model_id: str | None, driver_id: str) -> dict[str, Any]:
        if driver_id not in self._DRIVERS:
            raise AvatarError(f"Unknown Avatar driver: {driver_id}")
        character = self.storage.get_character(character_id)
        if character is None:
            raise AvatarError(f"Unknown character: {character_id}")
        model = None
        if model_id is not None:
            model = self.storage.get_avatar_model(model_id)
            if model is None:
                raise AvatarError(f"Unknown Avatar model: {model_id}")
            if driver_id != model["kind"]:
                raise AvatarError(f"Driver {driver_id} cannot load {model['kind']} model")
        elif driver_id != "none":
            raise AvatarError("A model is required for a non-null driver")

        config = dict(character["config"])
        config["avatar_driver"] = driver_id
        if model_id is None:
            config.pop("avatar_model_id", None)
        else:
            config["avatar_model_id"] = model_id
        updated_character = self.storage.update_character_config(character_id, config)
        self._activate(character_id, updated_character, model)
        return {"character": updated_character, "state": self.state()}

    def restore_character(self, character_id: str) -> dict[str, Any]:
        character = self.storage.get_character(character_id)
        if character is None:
            raise AvatarError(f"Unknown character: {character_id}")
        config = character["config"]
        model_id = config.get("avatar_model_id")
        model = self.storage.get_avatar_model(model_id) if isinstance(model_id, str) else None
        driver_id = str(config.get("avatar_driver") or "none")
        if model is None or driver_id not in self._DRIVERS or (driver_id != "none" and model["kind"] != driver_id):
            model = None
            driver_id = "none"
        self._activate(character_id, character, model, driver_id=driver_id)
        return self.state()

    def state(self) -> dict[str, Any]:
        avatar_state = self.driver.state
        character = self.storage.get_character(self.active_character_id) if self.active_character_id else None
        presentation = character["config"].get("avatar", {}) if character and isinstance(character["config"].get("avatar"), dict) else {}
        return {
            "driver": self.driver.id,
            "driver_status": avatar_state.metadata.get("status", "ready"),
            "character_id": self.active_character_id,
            "model": self.active_model,
            "presentation": presentation,
            "state": {
                "model_id": avatar_state.model_id,
                "expression": avatar_state.expression,
                "motion": avatar_state.motion,
                "viseme": avatar_state.viseme,
                "metadata": avatar_state.metadata,
            },
        }

    def close(self) -> None:
        self.driver.close()

    def _activate(
        self,
        character_id: str,
        character: dict[str, Any],
        model: dict[str, Any] | None,
        *,
        driver_id: str | None = None,
    ) -> None:
        selected_driver = driver_id or str(character["config"].get("avatar_driver") or "none")
        self.driver.close()
        self.driver = NullAvatarDriver() if selected_driver == "none" else PreviewAvatarDriver(selected_driver)
        self.active_character_id = character_id
        self.active_model = model
        if model is not None:
            self.driver.load_model(model["path"])
            self.driver.state.model_id = model["id"]
            self.driver.state.metadata.update({"kind": model["kind"], "name": model["name"], "path": model["path"]})
            if model["kind"] == "live2d":
                inspection = inspect_live2d_manifest(model["path"])
                self.driver.state.metadata.update(
                    {
                        "manifest_status": inspection["status"],
                        "manifest_valid": inspection["valid"],
                        "manifest_errors": inspection["errors"][:3],
                        "manifest_warnings": inspection["warnings"][:3],
                        "manifest_counts": inspection["counts"],
                    }
                )


def _detect_kind(path: Path) -> str:
    name = path.name.lower()
    if path.suffix.lower() == ".vrm":
        return "vrm"
    if name.endswith(".model3.json") or name.endswith(".model.json"):
        return "live2d"
    raise AvatarError("unsupported model file; use .vrm or Live2D .model3.json/.model.json")


def _display_name(path: Path) -> str:
    name = path.name
    for suffix in (".model3.json", ".model.json", ".vrm"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def inspect_live2d_manifest(path: str | Path) -> dict[str, Any]:
    """Validate a Live2D manifest and its relative file references.

    The result intentionally contains only metadata and relative reference
    names. It never returns the manifest body or opens referenced model data.
    """
    manifest_path = Path(path).expanduser()
    result: dict[str, Any] = {
        "kind": "live2d",
        "path": str(manifest_path),
        "status": "error",
        "valid": False,
        "available": False,
        "format": "model3.json" if manifest_path.name.lower().endswith(".model3.json") else "model.json",
        "format_version": None,
        "model_file": None,
        "referenced_files": [],
        "counts": {"textures": 0, "motions": 0, "expressions": 0},
        "errors": [],
        "warnings": [],
    }
    try:
        resolved = manifest_path.resolve(strict=True)
    except OSError:
        result["errors"].append("manifest file is missing")
        return result
    if not resolved.is_file():
        result["errors"].append("manifest path is not a file")
        return result
    result["path"] = str(resolved)
    root = resolved.parent
    try:
        if resolved.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("manifest file is larger than 2 MiB")
        document = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result["errors"].append(f"manifest JSON cannot be read: {type(exc).__name__}")
        return result
    if not isinstance(document, dict):
        result["errors"].append("manifest root must be a JSON object")
        return result

    result["format_version"] = document.get("Version", document.get("version"))
    references: list[tuple[str, str]] = []
    file_references = document.get("FileReferences")
    if isinstance(file_references, dict):
        _append_reference(references, "model", file_references.get("Moc"))
        textures = file_references.get("Textures")
        if isinstance(textures, list):
            for value in textures:
                _append_reference(references, "texture", value)
            result["counts"]["textures"] = len(textures)
        _append_reference(references, "physics", file_references.get("Physics"))
        expressions = file_references.get("Expressions")
        if isinstance(expressions, list):
            for expression in expressions:
                if isinstance(expression, dict):
                    _append_reference(references, "expression", expression.get("File"))
            result["counts"]["expressions"] = len(expressions)
        motions = file_references.get("Motions")
        if isinstance(motions, dict):
            for group, entries in motions.items():
                if not isinstance(entries, list):
                    continue
                for motion in entries:
                    if isinstance(motion, dict):
                        _append_reference(references, f"motion:{str(group)[:80]}", motion.get("File"))
                        result["counts"]["motions"] += 1
    else:
        _append_reference(references, "model", document.get("model"))
        textures = document.get("textures")
        if isinstance(textures, list):
            for value in textures:
                _append_reference(references, "texture", value)
            result["counts"]["textures"] = len(textures)
        _append_reference(references, "physics", document.get("physics"))
        expressions = document.get("expressions")
        if isinstance(expressions, list):
            for expression in expressions:
                if isinstance(expression, dict):
                    _append_reference(references, "expression", expression.get("file"))
            result["counts"]["expressions"] = len(expressions)
        motions = document.get("motions")
        if isinstance(motions, dict):
            for group, entries in motions.items():
                if not isinstance(entries, list):
                    continue
                for motion in entries:
                    if isinstance(motion, dict):
                        _append_reference(references, f"motion:{str(group)[:80]}", motion.get("file"))
                        result["counts"]["motions"] += 1

    if len(references) > 200:
        result["warnings"].append("manifest references were truncated at 200 files")
        references = references[:200]
    for role, value in references:
        reference = _inspect_reference(root, role, value)
        result["referenced_files"].append(reference)
        if not reference["safe"]:
            result["errors"].append(f"unsafe {role} reference: {value}")
        elif not reference["exists"]:
            result["warnings"].append(f"missing {role} reference: {value}")
    result["model_file"] = next(
        (item["reference"] for item in result["referenced_files"] if item["role"] == "model"),
        None,
    )
    result["available"] = True
    result["valid"] = not result["errors"]
    result["status"] = "error" if result["errors"] else "warning" if result["warnings"] or not references else "ready"
    return result


def _append_reference(references: list[tuple[str, str]], role: str, value: object) -> None:
    if isinstance(value, str) and value.strip():
        references.append((role, value.strip()))


def _inspect_reference(root: Path, role: str, reference: str) -> dict[str, Any]:
    candidate = (root / reference).resolve()
    safe = candidate == root or root in candidate.parents
    return {
        "role": role,
        "reference": reference,
        "exists": safe and candidate.is_file(),
        "safe": safe,
    }
