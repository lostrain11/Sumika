"""Build a local, content-safe daily Agent observability summary.

This command is intentionally offline.  It reads only the disposable
``logs/agent-observability`` and ``logs/route-decision-trace`` files under the
selected data directory and never contacts a provider, DSH, or GitHub.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core.observability import AgentObservability  # noqa: E402
from sumika_core.agent.route_trace import RouteDecisionTrace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("SUMIKA_DATA_DIR", str(ROOT / ".sumika")),
        help="Sumika data directory (default: SUMIKA_DATA_DIR or .sumika)",
    )
    parser.add_argument("--day", default=None, help="UTC day in YYYY-MM-DD format (default: today)")
    parser.add_argument("--write", action="store_true", help="also write <day>.summary.json beside the source JSONL")
    args = parser.parse_args()
    sink = AgentObservability(Path(args.data_dir))
    route_trace = RouteDecisionTrace(Path(args.data_dir))
    report = sink.write_daily_summary(args.day) if args.write else sink.aggregate(args.day)
    report["route_decision_trace"] = route_trace.write_daily_summary(args.day) if args.write else route_trace.aggregate(args.day)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    route_trace.close()
    sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
