"""Write a redacted, read-only account-portal report from existing browser tabs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core.browser.runtime import BrowserSkillClient
from sumika_core.integrations.account_portals import AccountPortalReader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("modelscope", "ollama"))
    parser.add_argument("--browser-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bsk", default=r"D:\Tools\BrowserSkill\0.1.11\bsk.exe")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists; refusing to overwrite")
    report = AccountPortalReader(BrowserSkillClient(args.bsk)).read(args.provider, args.browser_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
