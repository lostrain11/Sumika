"""Aggregate fixed, content-free model evaluation results offline.

The input is a JSON array/object or JSONL stream of records produced by an
isolated runner.  This command never contacts a model, provider, browser, or
GitHub, and it never prints rejected field values.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core.model_evaluation import (  # noqa: E402
    DEFAULT_MIN_REPETITIONS,
    EvaluationTaskSet,
    aggregate_evaluations,
    load_records,
)


DEFAULT_TASK_SET = ROOT / "tools" / "fixtures" / "model-evaluation-v1.json"


def _output_path(value: str) -> Path:
    target = Path(value).expanduser().resolve()
    allowed = (ROOT, ROOT / ".sumika-desktop")
    if not any(target == base or base in target.parents for base in allowed):
        raise ValueError("--output must be inside the Sumika project or .sumika-desktop")
    return target


def _write_without_overwrite(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    suffix = 1
    while target.exists():
        target = path.with_name(f"{path.stem}-{suffix}{path.suffix}")
        suffix += 1
    stored = dict(payload)
    stored["report_written"] = True
    stored["report_file_name"] = target.name
    target.write_text(json.dumps(stored, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON or JSONL evaluation records")
    parser.add_argument("--task-set", default=str(DEFAULT_TASK_SET), help="versioned task-set JSON")
    parser.add_argument(
        "--min-repetitions",
        type=int,
        default=DEFAULT_MIN_REPETITIONS,
        help="minimum observations per task before a cohort is evidence-ready (default: 3)",
    )
    parser.add_argument("--output", default="", help="optional report path inside the project")
    parser.add_argument("--json", action="store_true", help="print the complete bounded JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        task_set = EvaluationTaskSet.from_file(args.task_set)
    except Exception as error:
        print(f"task set rejected: {type(error).__name__}", file=sys.stderr)
        return 3
    records, errors = load_records(args.input, task_set)
    try:
        report = aggregate_evaluations(records, task_set, min_repetitions=args.min_repetitions)
    except Exception as error:
        print(f"evaluation aggregation failed: {type(error).__name__}", file=sys.stderr)
        return 3
    report["input_validation"] = {
        "accepted_records": len(records),
        "rejected_records": len(errors),
        "errors": errors[:128],
    }
    report["status"] = "passed" if not errors else ("needs-review" if records else "failed")
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    if args.output:
        try:
            target = _write_without_overwrite(_output_path(args.output), report)
        except (OSError, ValueError) as error:
            print(f"report write failed: {type(error).__name__}", file=sys.stderr)
            return 3
        report["report_written"] = True
        report["report_file_name"] = target.name
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"Sumika model evaluation: {report['status']}")
        print(f"accepted={len(records)} rejected={len(errors)} cohorts={report['cohort_count']}")
        for cohort in report["cohorts"]:
            comparison = cohort["comparison"]
            print(
                f"- {comparison['cache_state']} / {comparison['provider_kind']}: "
                f"{cohort['candidate_count']} candidate(s), "
                f"recommendation={cohort['recommendation']['status']}"
            )
        if args.output:
            print(f"report: {report['report_file_name']}")
    return 0 if report["status"] == "passed" else 2 if report["status"] == "needs-review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
