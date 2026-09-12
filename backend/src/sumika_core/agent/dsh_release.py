"""Single source of truth for the managed DSH release a host is allowed to run.

The desktop shell, the PowerShell setup helpers and Core all read the same
description under ``dsh-release/``.  This module owns the parts that must not
be duplicated per language: strict schema validation, plugin content digests
and the distribution identity that a managed launch is bound to.

Nothing here talks to a network, a model or a credential store.  Loading a
description is not an installation and is not an authorization to run it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


RELEASE_SCHEMA = "sumika.dsh-release/v1"
CHANNEL_SCHEMA = "sumika.dsh-release-channel/v1"
DISTRIBUTION_SCHEMA = "sumika.dsh-distribution/v1"
# Protocol families a description may declare.  The Sumika adapter implements
# ADAPTER_CONTRACT; a release exposing another family is described truthfully
# and marked blocked instead of being presented as a drop-in upgrade.
ADAPTER_CONTRACT = "dsh-web-api-v1"
KNOWN_ADAPTER_CONTRACTS = {ADAPTER_CONTRACT, "dsh-web-remote-v1"}

_RELEASE_KEYS = {
    "schema", "id", "status", "adapter_contract", "harness", "toolchain",
    "install_policy", "plugins", "verification", "bundle",
}
_HARNESS_KEYS = {"id", "package", "version", "source", "install", "artifacts", "signals"}
_SOURCE_KEYS = {"commit", "commit_evidence", "tarball", "tarball_sha512", "tarball_sha1"}
_INSTALL_KEYS = {"root", "root_env", "directory", "executable"}
_TOOLCHAIN_KEYS = {"node", "package_manager", "package_manager_major", "lockfile", "lockfile_sha256"}
_PLUGIN_KEYS = {
    "id", "name", "version", "path", "content_digest", "install", "default_enabled",
    "capabilities", "groups", "validation", "third_party",
}
_VERIFICATION_KEYS = {"evidence", "limitations", "blockers"}

PLUGIN_INSTALL_MODES = {"bridge", "optional", "reference"}
RELEASE_STATUSES = {"verified-active", "verified-candidate", "blocked"}


class DshReleaseError(RuntimeError):
    """The release description is missing, malformed or inconsistent."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def release_root(root: Path | None = None) -> Path:
    override = os.environ.get("SUMIKA_DSH_RELEASE_ROOT", "").strip()
    if override:
        return Path(override)
    if root is not None:
        return Path(root) / "dsh-release"
    return repository_root() / "dsh-release"


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DshReleaseError(f"missing release file: {path.name}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise DshReleaseError(f"unreadable release file: {path.name}") from error
    if not isinstance(value, dict):
        raise DshReleaseError(f"release file is not an object: {path.name}")
    return value


def load_channel(root: Path | None = None) -> dict:
    channel = _load_json(release_root(root) / "channel.json")
    if channel.get("schema") != CHANNEL_SCHEMA:
        raise DshReleaseError("unsupported channel schema")
    if set(channel) - {"schema", "default_release", "notes"}:
        raise DshReleaseError("unexpected channel fields")
    default = channel.get("default_release")
    if not isinstance(default, str) or not default.strip():
        raise DshReleaseError("channel default_release is required")
    return channel


def release_path(release_id: str, root: Path | None = None) -> Path:
    if not isinstance(release_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", release_id) or release_id.endswith("."):
        raise DshReleaseError("invalid release id")
    return safe_relative(release_root(root), f"releases/{release_id}")


def safe_relative(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or re.search(r'[\x00-\x1f:*?"<>|]', value):
        raise DshReleaseError("invalid relative release path")
    parts = value.replace("\\", "/").split("/")
    for part in parts:
        if not part or part in {".", ".."} or part.endswith((".", " ")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part):
            raise DshReleaseError("invalid relative release path")
    target = Path(root).absolute()
    for part in parts:
        target = target / part
        if target.is_symlink() or (target.exists() and getattr(target.lstat(), "st_file_attributes", 0) & 0x400):
            raise DshReleaseError("release paths must not contain links")
    return target


def resolve_release_id(explicit: str | None = None, root: Path | None = None) -> str:
    if explicit:
        return explicit
    override = os.environ.get("SUMIKA_DSH_RELEASE", "").strip()
    if override:
        return override
    return load_channel(root)["default_release"]


def load_release(release_id: str | None = None, root: Path | None = None) -> dict:
    release_id = resolve_release_id(release_id, root)
    directory = release_path(release_id, root)
    release = _load_json(directory / "release.json")
    _validate(release, directory, release_id)
    return release


def _require_keys(value: dict, allowed: set[str], required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise DshReleaseError(f"{label} must be an object")
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise DshReleaseError(f"{label} has unexpected fields: {', '.join(unexpected)}")
    missing = sorted(required - set(value))
    if missing:
        raise DshReleaseError(f"{label} is missing fields: {', '.join(missing)}")


def _validate(release: dict, directory: Path, release_id: str) -> None:
    _require_keys(release, _RELEASE_KEYS, _RELEASE_KEYS - {"bundle"}, "release")
    _require_keys(release["verification"], _VERIFICATION_KEYS, _VERIFICATION_KEYS, "verification")
    if release["schema"] != RELEASE_SCHEMA:
        raise DshReleaseError("unsupported release schema")
    if release["id"] != release_id:
        raise DshReleaseError("release id does not match its directory")
    if release["status"] not in RELEASE_STATUSES:
        raise DshReleaseError("unsupported release status")
    if release["adapter_contract"] not in KNOWN_ADAPTER_CONTRACTS:
        raise DshReleaseError(f"unsupported adapter contract: {release['adapter_contract']}")
    if release["adapter_contract"] != ADAPTER_CONTRACT and release["status"] != "blocked":
        raise DshReleaseError("a release outside the adapter contract must be marked blocked")
    if release["status"] == "verified-active" and release["verification"]["blockers"]:
        raise DshReleaseError("a verified-active release cannot carry blockers")

    harness = release["harness"]
    _require_keys(harness, _HARNESS_KEYS, _HARNESS_KEYS, "harness")
    if harness["id"] != "dsh" or not str(harness["package"]).strip() or not str(harness["version"]).strip():
        raise DshReleaseError("invalid harness identity")
    _require_keys(harness["source"], _SOURCE_KEYS, _SOURCE_KEYS, "harness.source")
    _require_keys(harness["install"], _INSTALL_KEYS, _INSTALL_KEYS, "harness.install")
    safe_relative(directory, harness["install"]["directory"])
    safe_relative(directory, harness["install"]["executable"])
    if harness["install"]["root_env"] != "SUMIKA_DSH_INSTALL_ROOT":
        raise DshReleaseError("unsupported install root environment binding")
    if not isinstance(harness["artifacts"], list) or not harness["artifacts"]:
        raise DshReleaseError("harness.artifacts must list the verified package artifacts")
    if not isinstance(harness["signals"], list) or not harness["signals"]:
        raise DshReleaseError("harness.signals must record the verified capability signals")

    toolchain = release["toolchain"]
    _require_keys(toolchain, _TOOLCHAIN_KEYS, _TOOLCHAIN_KEYS, "toolchain")
    lockfile = safe_relative(directory, toolchain["lockfile"])
    if not lockfile.is_file():
        raise DshReleaseError(f"missing frozen lockfile: {toolchain['lockfile']}")
    if _sha256_file(lockfile) != str(toolchain["lockfile_sha256"]).lower():
        raise DshReleaseError("frozen lockfile digest does not match the description")
    if f"{harness['package']}@{harness['version']}" not in lockfile.read_text(encoding="utf-8", errors="replace"):
        raise DshReleaseError("frozen lockfile does not resolve the declared harness version")

    policy = release["install_policy"]
    _require_keys(policy, {"lockfile_only", "ignore_scripts", "scripts_allowed"},
                  {"lockfile_only", "ignore_scripts", "scripts_allowed"}, "install_policy")
    if policy["lockfile_only"] is not True or policy["ignore_scripts"] is not True:
        raise DshReleaseError("the release must install from the frozen lockfile without scripts")
    if not isinstance(policy["scripts_allowed"], list):
        raise DshReleaseError("install_policy.scripts_allowed must be a list")

    plugins = release["plugins"]
    if not isinstance(plugins, list) or not plugins:
        raise DshReleaseError("release must describe its own plugins")
    seen = set()
    for plugin in plugins:
        _require_keys(plugin, _PLUGIN_KEYS, _PLUGIN_KEYS - {"groups", "validation", "third_party"}, "plugin")
        if plugin["id"] in seen:
            raise DshReleaseError(f"duplicate plugin id: {plugin['id']}")
        seen.add(plugin["id"])
        if plugin["install"] not in PLUGIN_INSTALL_MODES:
            raise DshReleaseError(f"unsupported plugin install mode: {plugin['install']}")
        safe_relative(repository_root(), plugin["path"])
    if "bundle" in release:
        bundle = release["bundle"]
        keys = {"schema", "package_manager_version", "runtime_manifest", "profile_directory", "files"}
        _require_keys(bundle, keys, keys, "bundle")
        if bundle["schema"] != "sumika.dsh-bundle/v1" or not re.fullmatch(r"\d+\.\d+\.\d+", bundle["package_manager_version"]):
            raise DshReleaseError("unsupported release bundle")
        safe_relative(directory, bundle["profile_directory"])
        files = bundle["files"]
        if not isinstance(files, list) or not files:
            raise DshReleaseError("bundle files are required")
        seen_files = set()
        for item in files:
            _require_keys(item, {"path", "sha256"}, {"path", "sha256"}, "bundle file")
            path = safe_relative(directory, item["path"])
            if item["path"].lower() in seen_files or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise DshReleaseError("invalid or duplicate bundle file")
            seen_files.add(item["path"].lower())
            if not path.is_file() or _sha256_file(path) != item["sha256"]:
                raise DshReleaseError(f"bundle file digest mismatch: {item['path']}")
        required = {bundle["runtime_manifest"], f"{bundle['profile_directory']}/package.json",
                    f"{bundle['profile_directory']}/pnpm-lock.yaml", f"{bundle['profile_directory']}/pnpm-workspace.yaml",
                    f"{bundle['profile_directory']}/cordis.patch.yml"}
        if not required.issubset({item["path"] for item in files}):
            raise DshReleaseError("bundle is missing required frozen inputs")
        manifest = _load_json(safe_relative(directory, bundle["runtime_manifest"]))
        if manifest.get("dependencies") != {harness["package"]: harness["version"]}:
            raise DshReleaseError("runtime manifest differs from the described harness")

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SKIPPED_PARTS = {".git", "node_modules", "__pycache__"}


def plugin_files(plugin_dir: Path) -> list[Path]:
    """Return the shipped files of one plugin, relative and canonically ordered."""

    collected: list[Path] = []
    for path in plugin_dir.rglob("*"):
        relative = path.relative_to(plugin_dir)
        if any(part in _SKIPPED_PARTS for part in relative.parts):
            continue
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise DshReleaseError("plugin sources must not contain links")
        if not path.is_file():
            continue
        collected.append(relative)
    return sorted(collected, key=lambda item: item.as_posix())


def plugin_content_digest(plugin_dir: Path) -> str:
    """Digest the shipped plugin content so a build cannot drift silently."""

    digest = hashlib.sha256()
    for relative in plugin_files(plugin_dir):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(plugin_dir / relative).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_plugins(release: dict, root: Path | None = None) -> list[str]:
    """Return the reasons the checked-in plugin content no longer matches."""

    base = (root or repository_root()).resolve()
    errors: list[str] = []
    for plugin in release["plugins"]:
        directory = (base / str(plugin["path"])).resolve()
        if base not in directory.parents:
            errors.append(f"{plugin['id']}: path escapes the repository")
            continue
        if not directory.is_dir():
            errors.append(f"{plugin['id']}: missing plugin directory")
            continue
        manifest = directory / "package.json"
        if not manifest.is_file():
            errors.append(f"{plugin['id']}: missing package.json")
            continue
        declared = _load_json(manifest)
        if declared.get("name") != plugin["name"] or declared.get("version") != plugin["version"]:
            errors.append(f"{plugin['id']}: package identity differs from the release description")
        actual = plugin_content_digest(directory)
        if actual != str(plugin["content_digest"]).lower():
            errors.append(f"{plugin['id']}: content digest changed")
    return errors


def distribution_id(release: dict) -> str:
    """Identity of the declared release combination, independent of install path."""

    material = {
        "schema": DISTRIBUTION_SCHEMA,
        "release": release["id"],
        "adapter_contract": release["adapter_contract"],
        "harness": {
            "package": release["harness"]["package"],
            "version": release["harness"]["version"],
            "tarball_sha512": release["harness"]["source"]["tarball_sha512"],
        },
        "lockfile_sha256": release["toolchain"]["lockfile_sha256"].lower(),
        "plugins": sorted(
            (
                {"id": plugin["id"], "version": plugin["version"], "content_digest": plugin["content_digest"].lower()}
                for plugin in release["plugins"]
            ),
            key=lambda item: item["id"],
        ),
    }
    if "bundle" in release:
        material["bundle"] = release["bundle"]
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def install_directory(release: dict, root_override: str | None = None) -> Path:
    install = release["harness"]["install"]
    override = root_override
    if override is None:
        override = os.environ.get(str(install["root_env"]), "").strip() or None
    base = Path(override) if override else Path(str(install["root"]))
    return base / str(install["directory"])


def executable_path(release: dict, root_override: str | None = None) -> Path:
    return install_directory(release, root_override) / str(release["harness"]["install"]["executable"])


def described_layout(release: dict) -> tuple[str, ...]:
    """The install-relative path a managed executable must sit at.

    Binding to the layout instead of one absolute root keeps a relocated
    install usable without letting a launch point at an unrelated binary.
    """

    install = release["harness"]["install"]
    relative = Path(str(install["directory"])) / str(install["executable"])
    return tuple(os.path.normcase(part) for part in relative.parts)


def matches_described_layout(release: dict, executable: str | Path) -> bool:
    parts = tuple(os.path.normcase(part) for part in Path(str(executable)).parts)
    layout = described_layout(release)
    return len(parts) >= len(layout) and parts[-len(layout):] == layout


def installed_lockfile_evidence(release: dict, root_override: str | None = None) -> dict:
    """Report whether an install was produced from the frozen resolution.

    ``frozen-lockfile-verified`` means the installed virtual-store lockfile is
    byte-identical to the declared one.  ``declared-unverified`` means the
    release is declared but this particular install tree cannot be tied to it.
    """

    declared = str(release["toolchain"]["lockfile_sha256"]).lower()
    installed = install_directory(release, root_override) / "node_modules" / ".pnpm" / "lock.yaml"
    if not installed.is_file():
        return {"level": "declared-unverified", "reason": "no-installed-lockfile"}
    actual = _sha256_file(installed)
    if actual != declared:
        return {"level": "mismatch", "reason": "installed-lockfile-differs", "installed_sha256": actual}
    return {"level": "frozen-lockfile-verified", "installed_sha256": actual}


def release_digest(release: dict) -> str:
    encoded = json.dumps(release, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def summary(release_id: str | None = None, root: Path | None = None) -> dict:
    release = load_release(release_id, root)
    return {
        "release": release["id"],
        "status": release["status"],
        "adapter_contract": release["adapter_contract"],
        "harness_version": release["harness"]["version"],
        "distribution_id": distribution_id(release),
        "release_digest": release_digest(release),
        "executable": str(executable_path(release)),
        "install_evidence": installed_lockfile_evidence(release),
        "plugin_errors": verify_plugins(release, root),
        "blockers": release["verification"]["blockers"],
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "show"
    release_id = argv[1] if len(argv) > 1 else None
    try:
        if command == "show":
            print(json.dumps(summary(release_id), ensure_ascii=False, indent=2))
            return 0
        if command == "describe":
            print(json.dumps(load_release(release_id), ensure_ascii=False))
            return 0
        if command == "digests":
            release = load_release(release_id)
            for plugin in release["plugins"]:
                print(f"{plugin['id']} {plugin['content_digest']}")
            return 0
        if command == "channel":
            print(json.dumps(load_channel(), ensure_ascii=False))
            return 0
        if command == "verify":
            release = load_release(release_id)
            errors = verify_plugins(release)
            for error in errors:
                print(error, file=sys.stderr)
            print(json.dumps({"ok": not errors, "release": release["id"],
                              "distribution_id": distribution_id(release)}, ensure_ascii=False))
            return 1 if errors else 0
    except DshReleaseError as error:
        print(f"dsh-release-unavailable: {error}", file=sys.stderr)
        return 2
    print(f"unsupported dsh-release command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
