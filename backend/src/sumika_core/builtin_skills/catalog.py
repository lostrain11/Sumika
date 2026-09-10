from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
import threading
from pathlib import Path


class BuiltinSkills:
    namespace = "builtin-skills/v1"

    def __init__(self, repository, *, resources=None, install_root=None, skill_catalog=None):
        self.repository = repository
        self.install_root = Path(install_root).absolute() if install_root else None
        self.skill_catalog = skill_catalog
        self._lock = threading.RLock()
        self.resources = Path(resources) if resources else Path(__file__).parent / "resources"
        self.catalog = json.loads((self.resources / "catalog.json").read_text(encoding="utf-8"))
        if self.catalog.get("schema") != "sumika.builtin-skills/v1":
            raise ValueError("unsupported built-in skill catalog")
        self.entries = {row["id"]: row for row in self.catalog["skills"]}
        if len(self.entries) != len(self.catalog["skills"]):
            raise ValueError("duplicate built-in skill")

    @staticmethod
    def _regular_path(path):
        for component in [*reversed(path.parents), path]:
            try:
                info = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("linked Skill installation paths are not supported")

    def _directory(self, identifier, owner=None):
        entry = self.entries.get(identifier)
        if not entry:
            raise ValueError("unknown built-in skill")
        if owner is not None and self.install_root:
            directory = self.install_root / hashlib.sha256(owner.encode()).hexdigest()[:24] / identifier
            self._regular_path(directory)
            if directory.exists():
                return directory
        return self.resources / identifier

    def _body(self, identifier, owner=None):
        directory = self._directory(identifier)
        path = directory / "SKILL.md"
        if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
            raise ValueError("invalid built-in skill path")
        raw = path.read_bytes()
        if len(raw) > 16000:
            raise ValueError("built-in skill exceeds context limit")
        digest = hashlib.sha256(raw)
        for helper in self.entries[identifier].get("helpers", {}).values():
            script = directory / helper["script"]
            if script.is_symlink() or not script.resolve().is_relative_to(directory.resolve()):
                raise ValueError("invalid skill helper path")
            digest.update(script.read_bytes())
        return raw.decode("utf-8"), digest.hexdigest()

    def _install(self, owner, identifier):
        if self.install_root is None:
            raise ValueError("persistent Skill installation is unavailable")
        target = self.install_root / hashlib.sha256(owner.encode()).hexdigest()[:24] / identifier
        self._regular_path(target)
        source = self.resources / identifier
        for path in source.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            destination = target / path.relative_to(source)
            self._regular_path(path)
            self._regular_path(destination)
            if destination.exists() and path.relative_to(source).parts[0] == "config":
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
        if self.skill_catalog:
            self.skill_catalog.discover(target)
        return target

    def list(self, owner):
        settings = self.repository.get_record(self.namespace, owner, owner) or {}
        selected = settings.get("enabled", {})
        rows = []
        for identifier, entry in self.entries.items():
            body, digest = self._body(identifier, owner)
            rows.append({**{key: value for key, value in entry.items() if key != "path"},
                         "publisher": "Sumika", "sha256": digest, "enabled": selected.get(identifier) == digest,
                         "update_available": identifier in selected and selected[identifier] != digest,
                         "installed": self.install_root is not None and self._directory(identifier, owner) != self.resources / identifier,
                         "config_path": str(self._directory(identifier, owner) / "config/paths.json") if entry.get("helpers") and self._directory(identifier, owner) != self.resources / identifier else None,
                         "runtime_status": "可在API开发任务中按需加载；其他Harness尚未挂接"})
        return {"schema_version": "sumika.builtin-skills/v1", "skills": rows}

    def set_enabled(self, owner, identifier, enabled, expected_sha256):
        with self._lock:
            return self._set_enabled(owner, identifier, enabled, expected_sha256)

    def _set_enabled(self, owner, identifier, enabled, expected_sha256):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        body, digest = self._body(identifier, owner)
        if digest != expected_sha256:
            raise ValueError("skill changed; refresh before changing its setting")
        settings = self.repository.get_record(self.namespace, owner, owner) or {"enabled": {}}
        if enabled:
            self._install(owner, identifier)
            if self._body(identifier, owner)[1] != digest:
                raise ValueError("Skill changed during installation")
            settings["enabled"][identifier] = digest
        else:
            settings["enabled"].pop(identifier, None)
        self.repository.save_record(self.namespace, owner, owner, settings)
        return self.list(owner)

    def snapshot(self, owner):
        return [{"id": row["id"], "description": row["description"], "sha256": row["sha256"], "content": self._body(row["id"], owner)[0],
                 "directory": str(self._directory(row["id"], owner)), "helpers": self.entries[row["id"]].get("helpers", {}),
                 "helper_sources": {name: (self.resources / row["id"] / helper["script"]).read_text(encoding="utf-8")
                                    for name, helper in self.entries[row["id"]].get("helpers", {}).items()}}
                for row in self.list(owner)["skills"] if row["enabled"]]

    def helper(self, owner, snapshot, identifier, helper_name, operation, *, data_root=None):
        row = next((item for item in snapshot if item["id"] == identifier), None)
        if not row or helper_name not in row.get("helpers", {}):
            raise ValueError("Skill helper is not enabled for this request")
        helper = row["helpers"][helper_name]
        if operation not in helper["operations"]:
            raise ValueError("unsupported helper operation")
        directory = self._directory(identifier, owner)
        configuration = directory / helper["configuration"]
        self._regular_path(configuration)
        command = [sys.executable, "-I", "-c", row["helper_sources"][helper_name], "--config", str(configuration), "--operation", operation]
        if data_root:
            command.extend(["--data-root", str(data_root)])
        result = subprocess.run(command, capture_output=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode not in {0, 2} or len(result.stdout) > 64000:
            raise ValueError("Skill helper failed")
        return json.loads(result.stdout)
