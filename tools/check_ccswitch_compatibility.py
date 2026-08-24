"""Run Sumika's read-only CC Switch compatibility monitor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core.integrations import CCSwitchCompatibilityChecker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checker = CCSwitchCompatibilityChecker(ROOT / "docs" / "integrations" / "cc-switch-compatibility.json")
    result = checker.check()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        changed = [item for item in result.get("changes", []) if item.get("changed")]
        lines = [
            "## CC Switch compatibility",
            "",
            f"- Status: `{result.get('status', 'unknown')}`",
            f"- Baseline: `{result.get('baseline_tag', 'unknown')}`",
            f"- Latest: `{result.get('latest_tag', 'unknown')}`",
            f"- Changed monitored files: `{len(changed)}`",
            "- Automatic changes applied: `false`",
        ]
        Path(summary_path).open("a", encoding="utf-8").write("\n".join(lines) + "\n")
    return 0 if result.get("status") in {"up_to_date", "release_only"} and result.get("fixtures", {}).get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
