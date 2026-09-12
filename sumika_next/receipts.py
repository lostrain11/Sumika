"""Explicit operator-declared task receipts.

A receipt records what the operator *reports* happened: the summary, the changed
files, the verification commands with their self-reported results, what remains
and the next step. It is a claim, not independent proof, and it never changes
``phase_status``. Automatic capture from DSH sessions belongs to P4.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess


RECEIPTS_DIR = "docs/project/receipts"
RESULTS = ("passed", "failed", "not_run")
PROVENANCE = "operator_report"
RECENT_LIMIT = 3
TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', *(f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10))}
FIELDS = ("task_id", "session_id", "summary", "changes", "verification", "remaining", "next")
META_FIELDS = ("schema_version", "provenance", "git_head", "recorded_at")
_AUTO = object()


class ReceiptError(ValueError):
    """A receipt was rejected; nothing was written."""


def _text(value, field):
    if not isinstance(value, str):
        raise ReceiptError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ReceiptError(f"{field} must not be empty")
    return value


def _text_list(value, field):
    if not isinstance(value, list):
        raise ReceiptError(f"{field} must be a list of strings")
    return [_text(item, f"{field} item") for item in value]


def _verification(value):
    if not isinstance(value, list):
        raise ReceiptError("verification must be a list")
    items = []
    for index, item in enumerate(value):
        where = f"verification[{index}]"
        if not isinstance(item, dict):
            raise ReceiptError(f"{where} must be an object")
        unknown = sorted(set(item) - {"command", "result"})
        if unknown:
            raise ReceiptError(f"{where} has unknown field(s): {', '.join(unknown)}")
        missing = [name for name in ("command", "result") if name not in item]
        if missing:
            raise ReceiptError(f"{where} is missing: {', '.join(missing)}")
        result = item["result"]
        if result not in RESULTS:
            raise ReceiptError(f"{where}.result must be one of {', '.join(RESULTS)}")
        items.append({"command": _text(item["command"], f"{where}.command"), "result": result})
    return items


def _task_id(value):
    if not isinstance(value, str):
        raise ReceiptError("task_id must be a string")
    task_id = value.strip()
    if (not TASK_ID_PATTERN.fullmatch(task_id) or task_id.endswith('.')
            or task_id.split('.')[0].upper() in RESERVED_NAMES):
        raise ReceiptError("task_id must be a non-empty ASCII name without path separators")
    return task_id


def _fields(report, allowed=(), allow_null_session=False):
    if not isinstance(report, dict):
        raise ReceiptError("report must be a JSON object")
    unknown = sorted(set(report) - set(FIELDS) - set(allowed))
    if unknown:
        raise ReceiptError("unknown field(s): " + ", ".join(unknown))
    missing = [name for name in FIELDS if name not in report]
    if missing:
        raise ReceiptError("missing field(s): " + ", ".join(missing))
    session = report["session_id"]
    if isinstance(session, str):
        session = session.strip() or None
    elif not (session is None and allow_null_session):
        raise ReceiptError("session_id must be a string")
    return {
        "task_id": _task_id(report["task_id"]),
        "session_id": session,
        "summary": _text(report["summary"], "summary"),
        "changes": _text_list(report["changes"], "changes"),
        "verification": _verification(report["verification"]),
        "remaining": _text_list(report["remaining"], "remaining"),
        "next": _text(report["next"], "next"),
    }


def normalize(report):
    """Validate an operator report and return its normalized fields."""
    return _fields(report)


def _receipts_dir(root):
    directory = (root / RECEIPTS_DIR).resolve()
    if not directory.is_relative_to(root):
        raise ReceiptError("receipts directory escapes the project root")
    return root / RECEIPTS_DIR


def _record_path(root, task_id):
    path = root / RECEIPTS_DIR / f"{task_id}.json"
    if not path.resolve().is_relative_to(root):
        raise ReceiptError("receipt path escapes the project root")
    return path


def _git_head(root):
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    head = done.stdout.strip()
    return head if done.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{40,64}", head) else None


def _utc(moment):
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _input_path(root, input_file):
    candidate = Path(input_file)
    if candidate.is_absolute():
        raise ReceiptError("input must be a project-relative path")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ReceiptError("input must stay inside the project root")
    if not path.is_file():
        raise ReceiptError(f"input file not found: {candidate.as_posix()}")
    return path


def create_receipt(root, input_file, *, now=None, head=_AUTO):
    """Validate the report first, then write exactly one new receipt file."""
    root = Path(root).resolve()
    if not (root / "docs/project").is_dir():
        raise ReceiptError("not a Sumika project root: docs/project is missing")
    source = _input_path(root, input_file)
    try:
        report = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptError(f"cannot read report: {source.name}") from error
    fields = normalize(report)
    path = _record_path(root, fields["task_id"])
    record = {
        "schema_version": 1,
        **fields,
        "provenance": PROVENANCE,
        "git_head": _git_head(root) if head is _AUTO else head,
        "recorded_at": _utc(now).isoformat(),
    }
    text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    try:
        payload = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ReceiptError("report contains text that cannot be encoded as UTF-8") from error
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ReceiptError(f"cannot create receipts directory: {error.strerror or error}") from error
    created = False
    try:
        with open(path, "xb") as handle:
            created = True
            handle.write(payload)
    except FileExistsError as error:
        raise ReceiptError(f"receipt already exists: {fields['task_id']}") from error
    except OSError as error:
        try:
            if created:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ReceiptError(f"cannot write receipt: {error.strerror or error}") from error
    return path


def _parse_record(data, path):
    if not isinstance(data, dict):
        raise ReceiptError(f"{path.name}: receipt must be a JSON object")
    if data.get("schema_version") != 1:
        raise ReceiptError(f"{path.name}: invalid schema version")
    if data.get("provenance") != PROVENANCE:
        raise ReceiptError(f"{path.name}: provenance must be {PROVENANCE}")
    head = data.get("git_head")
    if head is not None and not isinstance(head, str):
        raise ReceiptError(f"{path.name}: invalid git_head")
    recorded_at = data.get("recorded_at")
    if not isinstance(recorded_at, str) or not recorded_at:
        raise ReceiptError(f"{path.name}: invalid recorded_at")
    try:
        moment = datetime.fromisoformat(recorded_at)
    except ValueError as error:
        raise ReceiptError(f"{path.name}: invalid recorded_at") from error
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise ReceiptError(f"{path.name}: recorded_at must be UTC")
    try:
        fields = _fields(data, META_FIELDS, allow_null_session=True)
    except ReceiptError as error:
        raise ReceiptError(f"{path.name}: {error}") from error
    if fields["task_id"] != path.stem:
        raise ReceiptError(f"{path.name}: task_id does not match the file name")
    return {"schema_version": 1, **fields, "provenance": PROVENANCE,
            "git_head": head, "recorded_at": recorded_at}


def read_receipts(root):
    """Read every receipt; an unreadable or tampered record stops the caller."""
    root = Path(root).resolve()
    base = root / RECEIPTS_DIR
    if base.is_symlink() and not base.exists():
        raise ReceiptError("receipts path is a dangling link")
    if base.exists() and not base.is_dir():
        raise ReceiptError("receipts path is not a directory")
    if not base.is_dir():
        return []
    _receipts_dir(root)
    try:
        entries = sorted(base.iterdir(), key=lambda entry: entry.name)
    except OSError as error:
        raise ReceiptError(f"cannot list receipts directory: {error.strerror or error}") from error
    records = []
    for path in entries:
        if path.suffix.lower() != ".json":
            continue  # Not a record: keep .gitkeep or editor leftovers harmless.
        if not path.resolve().is_relative_to(root):
            raise ReceiptError(f"{path.name}: receipt file escapes the project root")
        if path.is_dir():
            raise ReceiptError(f"{path.name}: unexpected directory in the receipts directory")
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReceiptError(f"{path.name}: cannot read receipt") from error
        records.append(_parse_record(data, path))
    return records


def recent_receipts(root, limit=RECENT_LIMIT):
    records = read_receipts(root)
    records.sort(key=lambda item: (item["recorded_at"], item["task_id"]), reverse=True)
    return records if limit is None else records[:limit]


def handoff_lines(root, limit=RECENT_LIMIT):
    """Render recent receipts for handoff; empty when the project predates them."""
    records = recent_receipts(root, limit)
    if not records:
        return []
    lines = ["## 最近成果记录（人工声明 operator_report；验证结果为声明，非独立证明）"]
    for record in records:
        short = record["git_head"][:7] if record["git_head"] else "none"
        lines.append(f"- {record['task_id']} @ {record['recorded_at']} (git {short})")
        lines.append("  - 成果: " + record["summary"])
        if record["verification"]:
            lines.extend(f"  - 验证: `{item['command']}` -> {item['result']}"
                         for item in record["verification"])
        else:
            lines.append("  - 验证: （未记录）")
        lines.extend("  - 剩余: " + item for item in record["remaining"])
        if not record["remaining"]:
            lines.append("  - 剩余: （无）")
        lines.append("  - 下一步: " + record["next"])
    return lines
