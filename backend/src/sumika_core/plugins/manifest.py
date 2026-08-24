"""Manifest validation shared by local plugins and the future catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePath
from typing import Any


class ManifestError(ValueError):
    pass


@dataclass(slots=True)
class PluginManifest:
    id: str
    version: str
    capabilities: list[str]
    entrypoint: str
    config_schema: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    sdk_range: str = ">=0.1,<1.0"
    runtime: str = "external-process"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        if not isinstance(data, dict):
            raise ManifestError("Manifest root must be an object")
        required = ("id", "version", "capabilities", "entrypoint")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ManifestError(f"Missing required fields: {', '.join(missing)}")
        for key in ("id", "version", "entrypoint"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ManifestError(f"{key} must be a non-empty string")
        entrypoint = data["entrypoint"].strip()
        entrypoint_path = PurePath(entrypoint.replace("\\", "/"))
        if entrypoint_path.is_absolute() or ".." in entrypoint_path.parts:
            raise ManifestError("entrypoint must stay inside the plugin directory")
        if not isinstance(data["capabilities"], list) or not all(isinstance(x, str) for x in data["capabilities"]):
            raise ManifestError("capabilities must be a list of strings")
        if not data["capabilities"] or any(not item.strip() for item in data["capabilities"]):
            raise ManifestError("capabilities must contain at least one non-empty string")
        for key in ("permissions", "dependencies"):
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ManifestError(f"{key} must be a list of strings")
        for key in ("config_schema", "resource_requirements"):
            if not isinstance(data.get(key, {}), dict):
                raise ManifestError(f"{key} must be an object")
        runtime = data.get("runtime", "external-process")
        if not isinstance(runtime, str) or not runtime.strip():
            raise ManifestError("runtime must be a non-empty string")
        return cls(
            id=str(data["id"]),
            version=str(data["version"]),
            capabilities=list(data["capabilities"]),
            entrypoint=entrypoint,
            config_schema=data.get("config_schema", {}),
            permissions=list(data.get("permissions", [])),
            dependencies=list(data.get("dependencies", [])),
            resource_requirements=data.get("resource_requirements", {}),
            sdk_range=str(data.get("sdk_range", ">=0.1,<1.0")),
            runtime=runtime,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "capabilities": self.capabilities,
            "entrypoint": self.entrypoint,
            "config_schema": self.config_schema,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
            "resource_requirements": self.resource_requirements,
            "sdk_range": self.sdk_range,
            "runtime": self.runtime,
        }


def load_manifest(path: str | Path) -> PluginManifest:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"Unable to read manifest: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid JSON manifest: {manifest_path}") from exc
    if not isinstance(data, dict):
        raise ManifestError("Manifest root must be an object")
    return PluginManifest.from_dict(data)
