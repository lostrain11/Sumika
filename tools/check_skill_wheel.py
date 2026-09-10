import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def check_wheel(wheel):
    prefix = "sumika_core/builtin_skills/resources/"
    identifiers = {"project-progress", "troubleshooting-notes", "tool-registry"}
    expected = {"catalog.json", "tool-registry/config/paths.json", "tool-registry/scripts/check_paths.py"}
    expected.update(identifier + "/SKILL.md" for identifier in identifiers)
    with zipfile.ZipFile(wheel) as archive, tempfile.TemporaryDirectory(prefix="skill-wheel-") as directory:
        actual = {name[len(prefix):] for name in archive.namelist() if name.startswith(prefix)}
        assert actual == expected, actual.symmetric_difference(expected)
        catalog = json.loads(archive.read(prefix + "catalog.json"))
        assert {row["id"] for row in catalog["skills"]} == identifiers
        assert all(row["default_enabled"] is False for row in catalog["skills"])
        config_bytes = archive.read(prefix + "tool-registry/config/paths.json")
        assert json.loads(config_bytes) == {"tool_directories": [], "download_cache_directory": ""}
        root = Path(directory)
        config = root / "paths.json"
        script = root / "check_paths.py"
        config.write_bytes(config_bytes)
        script.write_bytes(archive.read(prefix + "tool-registry/scripts/check_paths.py"))
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "-I", str(script), "--config", str(config), "--operation", "reuse", "--data-root", str(root)],
                                cwd=root, env=environment, capture_output=True, timeout=10)
        assert result.returncode == 2, result.stderr
        assert json.loads(result.stdout)["status"] == "configuration-empty"
        assert config.read_bytes() == config_bytes
        assert {path.name for path in root.iterdir()} == {"paths.json", "check_paths.py"}
    print("Skill wheel passed: three disabled Skills, empty configuration, standalone read-only helper.")


if __name__ == "__main__":
    check_wheel(sys.argv[1])
