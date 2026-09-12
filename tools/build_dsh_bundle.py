"""Build deterministic own-plugin archives; dependency resolution is a separate step."""

from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "quality-routing" / "src"))

from sumika_core.agent import dsh_release


def build(release_id):
    directory = dsh_release.release_path(release_id, ROOT)
    release = json.loads((directory / "release.json").read_text(encoding="utf-8"))
    output = directory / "profile" / "packages"
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    for plugin in release["plugins"]:
        if plugin["install"] != "bridge":
            continue
        source = ROOT / plugin["path"]
        if dsh_release.plugin_content_digest(source) != plugin["content_digest"]:
            raise ValueError(f"source differs from approved plugin: {plugin['id']}")
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for relative in dsh_release.plugin_files(source):
                content = (source / relative).read_bytes()
                member = tarfile.TarInfo(f"package/{relative.as_posix()}")
                member.size = len(content)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(content))
        target = output / f"{plugin['id']}-{plugin['version']}.tgz"
        target.write_bytes(gzip.compress(data.getvalue(), mtime=0))
        archives.append({"path": target.relative_to(directory).as_posix(), "sha256": dsh_release._sha256_file(target)})
    print(json.dumps(archives, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    build(parser.parse_args().release)
