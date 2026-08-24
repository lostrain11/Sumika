"""Minimal external tool for the Sumika JSONL contract."""

from __future__ import annotations

import json
import sys


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        return 1
    request = json.loads(line)
    result = {
        "tool_id": request.get("tool_id"),
        "input": request.get("input"),
    }
    sys.stdout.write(json.dumps({"type": "result", "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
