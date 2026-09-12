"""Frozen DSH installation, staged by a readiness receipt rather than moving junctions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlparse
from uuid import uuid4

from . import dsh_release as releases

RECEIPT = ".sumika-installation.json"
PENDING = ".sumika-installation-pending.json"
SCHEMA = "sumika.dsh-installation/v1"


def checked_destination(value):
    path = Path(value)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise releases.DshReleaseError("installation destination must be an absolute local path")
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise releases.DshReleaseError("installation destination contains a link")
        if part.exists() and not part.is_dir():
            raise releases.DshReleaseError("installation destination contains a non-directory")
    if any(part in {".", ".."} or part.endswith((".", " ")) or ":" in part for part in path.parts[1:]):
        raise releases.DshReleaseError("invalid installation destination")
    return path


def inventory(directory, known=None):
    result = {}
    for parent, directories, files in os.walk(directory, followlinks=False):
        for name in sorted([*directories, *files]):
            path = Path(parent) / name
            relative = path.relative_to(directory).as_posix()
            if relative in {RECEIPT, PENDING}:
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                target = path.resolve(strict=True)
                if not target.is_relative_to(directory):
                    raise releases.DshReleaseError(f"installed link escapes its tree: {relative}")
                result[relative] = {"link": target.relative_to(directory).as_posix()}
                if name in directories:
                    directories.remove(name)
            elif stat.S_ISREG(info.st_mode):
                identity = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
                previous = (known or {}).get(relative, {})
                digest = previous.get("sha256") if previous.get("identity") == identity else releases._sha256_file(path)
                result[relative] = {"sha256": digest, "identity": identity}
            elif not stat.S_ISDIR(info.st_mode):
                raise releases.DshReleaseError(f"unsupported installed file: {relative}")
    return result


def seal(directory, release, kind, endpoint=None):
    receipt = {"schema": SCHEMA, "distribution_id": releases.distribution_id(release),
               "kind": kind, "files": inventory(directory)}
    if endpoint is not None:
        receipt["endpoint"] = endpoint
    temporary = directory / f".sumika-receipt-{uuid4().hex}.tmp"
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, directory / RECEIPT)
    return receipt


def verify(directory, release, kind, *, full=True, preparing=False):
    directory = checked_destination(directory)
    receipt_path = releases.safe_relative(directory, RECEIPT)
    if ((directory / PENDING).exists() and not preparing) or not receipt_path.is_file():
        raise releases.DshReleaseError("installation is incomplete or has no readiness receipt")
    receipt = releases._load_json(receipt_path)
    if receipt.get("schema") != SCHEMA or receipt.get("kind") != kind or receipt.get("distribution_id") != releases.distribution_id(release):
        raise releases.DshReleaseError("installation receipt does not match the frozen distribution")
    bundle = release.get("bundle")
    if not bundle:
        raise releases.DshReleaseError("release has no frozen runtime/profile bundle")
    prefix = bundle["profile_directory"] + "/"
    expected = ({release["toolchain"]["lockfile"]: release["toolchain"]["lockfile_sha256"],
                 **{item["path"]: item["sha256"] for item in bundle["files"] if item["path"] == bundle["runtime_manifest"]}}
                if kind == "runtime" else
                {item["path"][len(prefix):]: item["sha256"] for item in bundle["files"] if item["path"].startswith(prefix)})
    for relative, digest in expected.items():
        path = releases.safe_relative(directory, relative)
        if kind == "profile" and relative == "cordis.patch.yml":
            digest = receipt.get("files", {}).get(relative, {}).get("sha256")
        if not path.is_file() or releases._sha256_file(path) != digest:
            raise releases.DshReleaseError(f"installed frozen input differs: {relative}")
    lock = releases.safe_relative(directory, "node_modules/.pnpm/lock.yaml")
    frozen_lock = release["toolchain"]["lockfile_sha256"] if kind == "runtime" else expected["pnpm-lock.yaml"]
    if not lock.is_file() or releases._sha256_file(lock) != frozen_lock:
        raise releases.DshReleaseError("installed resolution differs from its frozen lock")
    if full and inventory(directory, receipt.get("files")) != receipt.get("files"):
        raise releases.DshReleaseError("installed package content differs from its verified inventory")
    return {"level": "frozen-bundle-verified", "receipt_sha256": releases._sha256_file(receipt_path),
            "distribution_id": receipt["distribution_id"]}


def package_manager(script=None, node=None):
    executable = node or shutil.which("node")
    if not executable:
        raise releases.DshReleaseError("Node.js is required")
    if script is None:
        launcher = shutil.which("pnpm")
        if not launcher:
            raise releases.DshReleaseError("pnpm is required")
        root = Path(launcher).parent
        choices = [root / "node_modules/pnpm/bin/pnpm.mjs", root / "node_modules/pnpm/bin/pnpm.cjs"]
        script = next((str(path) for path in choices if path.is_file()), None)
    if script is None or not Path(script).is_file():
        raise releases.DshReleaseError("provide the installed pnpm JS entry with --pnpm-script")
    return [str(executable), str(Path(script).absolute())]


def validate_toolchain(command, release):
    version = subprocess.run([*command, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if version != release["bundle"]["package_manager_version"]:
        raise releases.DshReleaseError("pnpm version differs from the frozen bundle")
    node_version = subprocess.run([command[0], "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if int(node_version.lstrip("v").split(".")[0]) < 22:
        raise releases.DshReleaseError("the release requires Node.js >=22")


def prepare(directory, release, kind, files, command, *, endpoint=None):
    directory = checked_destination(directory)
    if directory.exists():
        evidence = verify(directory, release, kind)
        if endpoint is not None and releases._load_json(directory / RECEIPT).get("endpoint") != endpoint:
            raise releases.DshReleaseError("existing profile belongs to a different Core endpoint; prepare a new profile")
        return evidence
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir()
    (directory / PENDING).write_text(json.dumps({"schema": SCHEMA, "distribution_id": releases.distribution_id(release)}), encoding="utf-8")
    for source, relative in files:
        target = releases.safe_relative(directory, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "profile" and relative == "cordis.patch.yml":
            target.write_text(source.read_text(encoding="utf-8").replace("__SUMIKA_CORE_ENDPOINT__", endpoint), encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(source, target)
    subprocess.run([*command, "install", "--dir", str(directory), "--frozen-lockfile", "--ignore-scripts"], check=True, stdout=sys.stderr)
    if kind == "runtime" and not (directory / release["harness"]["install"]["executable"]).is_file():
        raise releases.DshReleaseError("installation has no described runtime launcher")
    seal(directory, release, kind, endpoint)
    evidence = verify(directory, release, kind, preparing=True)
    (directory / PENDING).unlink()
    return evidence


def install(release_id, install_dir, dsh_home=None, endpoint="http://127.0.0.1:8771/rpc", *, pnpm_script=None, node=None):
    release = releases.load_release(release_id)
    if release["status"] != "verified-active" or release["adapter_contract"] != releases.ADAPTER_CONTRACT or not release.get("bundle"):
        raise releases.DshReleaseError("only the reviewed legacy frozen bundle can be installed; candidate upgrade is deferred")
    parsed = urlparse(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.path != "/rpc"
            or parsed.username or parsed.password or parsed.query or parsed.fragment or "'" in endpoint or "\n" in endpoint or "\r" in endpoint):
        raise releases.DshReleaseError("Core endpoint must be a plain HTTP loopback /rpc URL")
    destination = checked_destination(install_dir)
    if not releases.matches_described_layout(release, destination / release["harness"]["install"]["executable"]):
        raise releases.DshReleaseError("install destination does not match the described layout")
    profile = checked_destination(Path(dsh_home) / "profiles" / "web") if dsh_home else None
    for target, kind in ((destination, "runtime"), (profile, "profile")):
        if target is not None and target.exists():
            verify(target, release, kind)
    command = package_manager(pnpm_script, node)
    validate_toolchain(command, release)
    directory = releases.release_path(release["id"])
    bundle = release["bundle"]
    runtime_files = [(releases.safe_relative(directory, name), name) for name in (bundle["runtime_manifest"], release["toolchain"]["lockfile"])]
    runtime_evidence = prepare(destination, release, "runtime", runtime_files, command)
    profile_evidence = None
    if profile is not None:
        prefix = bundle["profile_directory"] + "/"
        files = [(releases.safe_relative(directory, item["path"]), item["path"][len(prefix):]) for item in bundle["files"] if item["path"].startswith(prefix)]
        profile_evidence = prepare(profile, release, "profile", files, command, endpoint=endpoint)
    return {"ok": True, "release": release["id"], "executable": str(destination / release["harness"]["install"]["executable"]),
            "install_dir": str(destination), "runtime": runtime_evidence, "profile": profile_evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release")
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--dsh-home")
    parser.add_argument("--core-endpoint", default="http://127.0.0.1:8771/rpc")
    parser.add_argument("--pnpm-script")
    parser.add_argument("--node")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.release, args.install_dir, args.dsh_home, args.core_endpoint, pnpm_script=args.pnpm_script, node=args.node)))
    except (OSError, ValueError, releases.DshReleaseError, subprocess.SubprocessError) as error:
        print(f"dsh-installation-failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
