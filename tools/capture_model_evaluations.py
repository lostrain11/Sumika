"""Capture explicitly approved, terminal run metadata for offline evaluation.

The input is a small ``sumika.model-evaluation-capture/v1`` handoff produced
by an isolated runner.  This command never reads Sumika logs or SQLite, never
contacts a provider, and never prints rejected values.  Use ``--opt-in`` only
after reviewing that the handoff contains no user content.
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
    CAPTURE_SCHEMA_VERSION,
    EvaluationTaskSet,
    capture_evaluation_payload,
    load_capture_specs,
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
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="capture JSON or JSONL handoff")
    parser.add_argument("--task-set", default=str(DEFAULT_TASK_SET), help="versioned fixed task set")
    parser.add_argument(
        "--opt-in",
        action="store_true",
        help="explicitly approve projecting the supplied terminal metadata",
    )
    parser.add_argument("--output", default="", help="optional output path inside the project")
    parser.add_argument("--json", action="store_true", help="print the bounded capture envelope")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        task_set = EvaluationTaskSet.from_file(args.task_set)
    except Exception as error:
        print(f"task set rejected: {type(error).__name__}", file=sys.stderr)
        return 3

    records, errors = load_capture_specs(args.input, task_set, opt_in=args.opt_in)
    payload = capture_evaluation_payload(records)
    payload["accepted_records"] = len(records)
    payload["rejected_records"] = len(errors)
    payload["errors"] = errors[:128]
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["status"] = "passed" if not errors else ("needs-review" if records else "failed")

    if args.output:
        try:
            target = _write_without_overwrite(_output_path(args.output), payload)
        except (OSError, ValueError) as error:
            print(f"capture write failed: {type(error).__name__}", file=sys.stderr)
            return 3
        payload["output_file_name"] = target.name

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"Sumika evaluation capture: {payload['status']}")
        print(f"accepted={len(records)} rejected={len(errors)} schema={CAPTURE_SCHEMA_VERSION}")
        if args.output:
            print(f"capture: {payload['output_file_name']}")
    return 0 if payload["status"] == "passed" else 2 if payload["status"] == "needs-review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
