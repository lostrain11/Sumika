from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from quality_routing.harness import RuntimeBinding

from . import dsh_release
from .contracts import AgentRuntimeError


REQUEST_KEYS = frozenset({"root_pid", "endpoint", "profile", "executable", "version", "release"})
# The install evidence is part of the binding. A different dependency tree is a
# different runtime, even when it reports the same DSH version.
STABLE_KEYS = ("schema_version", "root_pid", "endpoint", "profile", "executable", "version",
               "release", "process", "profile_identity", "launcher_digest", "release_digest",
               "distribution_id", "install_evidence", "binding")


def _profile_identity(path):
    target = Path(path)
    if not target.is_absolute():
        raise ValueError("profile must be absolute")
    for part in (target, *target.parents):
        info = part.stat(follow_symlinks=False)
        if getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
            raise ValueError("profile links and special paths are not supported")
    info = target.stat()
    return hashlib.sha256(f"{info.st_dev}:{info.st_ino}".encode()).hexdigest()


def _launcher_digest(path):
    target = Path(path)
    if not target.is_absolute() or not target.is_file() or target.stat().st_size > 1024 * 1024:
        raise ValueError("invalid managed launcher")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _install_root_for_executable(release, executable):
    """Derive the install root from the executable being verified."""
    executable_path = Path(executable).resolve()
    layout = Path(str(release["harness"]["install"]["directory"])) / str(
        release["harness"]["install"]["executable"]
    )
    if len(layout.parts) == 0 or len(executable_path.parts) < len(layout.parts):
        raise ValueError("managed executable has an invalid release layout")
    if tuple(os.path.normcase(part) for part in executable_path.parts[-len(layout.parts):]) != tuple(
        os.path.normcase(part) for part in layout.parts
    ):
        raise ValueError("managed executable has an invalid release layout")
    return str(executable_path.parents[len(layout.parts) - 1])


def capture(request):
    from .windows_identity import observe_listener

    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        raise ValueError("invalid managed launch request")
    release = dsh_release.load_release(request["release"])
    if str(request["version"]) != str(release["harness"]["version"]):
        raise ValueError("managed runtime version is not the described release")
    if not dsh_release.matches_described_layout(release, request["executable"]):
        raise ValueError("managed runtime executable is not the described release layout")
    if release["status"] == "blocked":
        raise ValueError("the described release is blocked for the managed adapter")
    process = observe_listener(request["root_pid"], request["endpoint"])
    profile_id = _profile_identity(request["profile"])
    launcher_digest = _launcher_digest(request["executable"])
    distribution = dsh_release.distribution_id(release)
    launch = hashlib.sha256(json.dumps(process, sort_keys=True).encode()).hexdigest()
    binding = RuntimeBinding("dsh", "profile-" + profile_id,
                             f"dsh-release-{release['id']}-{distribution[:16]}",
                             release["adapter_contract"], "managed", "profile-stat-" + profile_id,
                             "process-" + launch, "windows-listener-" + launch)
    install_root = _install_root_for_executable(release, request["executable"])
    install_evidence = dsh_release.installed_lockfile_evidence(release, install_root)
    if install_evidence["level"] != "frozen-lockfile-verified":
        raise ValueError("managed runtime installation is not verified against the frozen lockfile")
    return {"schema_version": "managed-runtime-evidence/v1", **request, "process": process,
            "profile_identity": profile_id, "launcher_digest": launcher_digest,
            "release_digest": dsh_release.release_digest(release), "distribution_id": distribution,
            "install_evidence": install_evidence,
            "binding": binding.to_dict()}


def _stable(evidence):
    return {key: evidence.get(key) for key in STABLE_KEYS}


class ManagedRuntimeGuard:
    def __init__(self, evidence, *, endpoint, profile, version, release):
        if not isinstance(evidence, dict) or evidence.get("schema_version") != "managed-runtime-evidence/v1":
            raise AgentRuntimeError("unsupported managed runtime evidence")
        if (evidence.get("endpoint") != endpoint or evidence.get("version") != version or
                evidence.get("release") != release or
                os.path.normcase(os.path.abspath(evidence.get("profile", ""))) != os.path.normcase(os.path.abspath(profile))):
            raise AgentRuntimeError("managed runtime configuration changed")
        self.evidence = json.loads(json.dumps(evidence))
        self.binding = RuntimeBinding.from_dict(evidence["binding"])
        self.check()

    def check(self):
        try:
            request = {key: self.evidence[key] for key in REQUEST_KEYS}
            if _stable(capture(request)) != _stable(self.evidence):
                raise ValueError("managed launch evidence changed")
        except (OSError, ValueError, KeyError, TypeError, dsh_release.DshReleaseError) as error:
            raise AgentRuntimeError("managed runtime identity changed; new host preflight required") from error


def main():
    try:
        line = sys.stdin.readline(16385)
        if len(line) > 16384 or not line.endswith("\n"):
            raise ValueError("invalid managed identity frame")
        request = json.loads(line)
        if sys.argv[1:] == ["--stop"]:
            from .windows_identity import stop_verified_listener
            if not isinstance(request, dict) or request.get("schema_version") != "managed-runtime-evidence/v1":
                raise ValueError("unsupported managed runtime evidence")
            stop_verified_listener(request["process"], request["endpoint"])
            print(json.dumps({"stopped": True}))
        elif not sys.argv[1:]:
            print(json.dumps(capture(request)))
        else:
            raise ValueError("unsupported identity operation")
    except Exception:
        print("managed-runtime-identity-unavailable", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
