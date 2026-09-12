"""Validate the phase-0 continuity record without changing repository files."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["requirements.json", "plan.json", "progress.json", "decisions.json", "handoff.json"]

def main() -> int:
    base = ROOT / "docs" / "project"
    for name in REQUIRED:
        path = base / name
        if not path.is_file():
            raise SystemExit(f"missing continuity file: {path}")
        with path.open(encoding="utf-8") as fh:
            value = json.load(fh)
        if value.get("schema_version") != 1:
            raise SystemExit(f"unsupported schema_version in {path}")
    plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
    if not any(p["id"] == "P0" and p["status"] == "in_progress" for p in plan["phases"]):
        raise SystemExit("P0 must remain in_progress until its acceptance is verified")
    print("continuity records: ok")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
