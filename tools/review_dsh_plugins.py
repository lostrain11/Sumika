"""Snapshot public DSH plugin metadata/source without installing or executing it.

Use exact versions in --package NAME@VERSION to reproduce a reviewed snapshot.
Downloaded npm tarballs are integrity-checked; only bounded regular text files
are copied into an isolated evidence directory, never into a runtime/profile.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.parse
import urllib.request


def fetch(url, limit=16_000_000):
    request = urllib.request.Request(url, headers={"User-Agent": "Sumika-readonly-plugin-review"})
    with urllib.request.urlopen(request, timeout=40) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("source exceeds bounded review limit")
        receipt = {"url": url, "status": response.status,
                   "fetched_at": datetime.now(timezone.utc).isoformat(),
                   "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        return body, receipt


def review(spec, destination, download):
    name, marker, version = spec.rpartition("@")
    if not marker or not name:
        name, version = spec, "latest"
    target = destination / re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    target.mkdir(parents=True, exist_ok=True)
    result = {"requested": spec, "trust": "untrusted_reference_only", "receipts": []}
    try:
        body, receipt = fetch("https://registry.npmjs.org/" + urllib.parse.quote(name, safe=""))
        (target / "registry.json").write_bytes(body)
        result["receipts"].append(receipt)
        registry = json.loads(body)
        resolved = registry.get("dist-tags", {}).get(version, version)
        package = registry["versions"][resolved]
        (target / "package-metadata.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        result.update({k: package.get(k) for k in (
            "name", "version", "description", "license", "engines", "peerDependencies",
            "dependencies", "optionalDependencies", "scripts", "dsh", "repository", "deprecated")})
        result["published"] = registry.get("time", {}).get(resolved)
        result["maintainers"] = [m.get("name") for m in registry.get("maintainers", [])]
        if download:
            dist = package["dist"]
            body, receipt = fetch(dist["tarball"], 12_000_000)
            integrity = dist.get("integrity", "")
            checks = integrity.split()
            verified = any(
                token.startswith("sha512-") and
                base64.b64encode(hashlib.sha512(body).digest()).decode() == token[7:]
                for token in checks)
            if not verified:
                raise ValueError("npm SHA512 integrity missing or mismatched")
            receipt["npm_sha512_verified"] = True
            result["receipts"].append(receipt)
            (target / "source.tgz").write_bytes(body)
            copied, total = [], 0
            with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
                for member in archive:
                    path = PurePosixPath(member.name)
                    if not member.isfile() or path.is_absolute() or ".." in path.parts:
                        continue
                    if member.size > 2_000_000 or total + member.size > 32_000_000:
                        continue
                    if path.suffix.lower() not in (".js", ".mjs", ".cjs", ".ts", ".json", ".md", ".yml", ".yaml", ".py", ".ps1", ".txt"):
                        continue
                    output = target / "source" / Path(*path.parts)
                    if not output.resolve().is_relative_to((target / "source").resolve()):
                        raise ValueError("unsafe archive path")
                    stream = archive.extractfile(member)
                    if stream is None:
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(stream.read())
                    copied.append(member.name)
                    total += member.size
            result["copied_text_files"] = len(copied)
            result["copied_text_bytes"] = total
        result["status"] = "source_snapshotted" if download else "metadata_snapshotted"
    except Exception as exc:
        result["status"], result["error"] = "incomplete", str(exc)
    (target / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--download-source", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda spec: review(spec, args.out, args.download_source), args.package))
    (args.out / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in results:
        print(json.dumps({k: item.get(k) for k in ("name", "version", "published", "status", "error")}, ensure_ascii=False))
    if any(item["status"] == "incomplete" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
